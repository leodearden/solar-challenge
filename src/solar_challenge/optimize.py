# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discrete install-config sweep and optimisation tools (W3).

This module provides the homogeneous-install config enumerator that is the
foundation of the W3 cost-recovery sweep (PRD §3.1/§3.2/§10-A/§10-B).

Exported symbols
----------------
ConfigPoint           — frozen (pv_kwp, battery_kwh, inverter_kw) value object
ConfigResult          — per-config evaluation result (cost-recovery + baseline economics)
RankedSweep           — aggregated sweep output (ranked feasible configs + infeasible set)
enumerate_configs     — cartesian-product enumerator → eager list (small grids)
iter_configs          — generator variant of enumerate_configs (large grids / streaming)
run_sweep             — drive all configs through W2 cost-recovery + rank by outlay
_rank_feasible        — pure sort helper (tie-break key)
_split_infeasible     — split ConfigResults into feasible/infeasible lists
_pareto_baseline      — non-dominated set on (baseline_outlay ↓, baseline_surplus ↑)
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable, Iterator, List, Optional, Sequence

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import FinanceConfig, ScenarioConfig
from solar_challenge.home import HomeConfig

if TYPE_CHECKING:
    import pandas as pd
    from solar_challenge.finance import CostRecoverySolution
    from solar_challenge.fleet import FleetConfig, FleetResults


# ---------------------------------------------------------------------------
# ConfigPoint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigPoint:
    """A single discrete install specification for the W3 sweep.

    Attributes:
        pv_kwp: PV DC rated capacity in kWp (must be > 0).
        battery_kwh: Battery usable capacity in kWh (must be >= 0).
            The value **exactly** ``0.0`` is the no-battery sentinel; it causes
            :func:`_apply_install` (and therefore :func:`enumerate_configs` /
            :func:`iter_configs`) to set ``battery_config = None`` on every home
            in the scenario.  Any strictly positive value — however small —
            triggers battery fabrication or replacement; there is no epsilon
            tolerance.  Callers must pass ``0.0`` (not, e.g., ``1e-9``) to mean
            "no battery".
        inverter_kw: AC inverter rated capacity in kW (must be > 0).
    """

    pv_kwp: float
    battery_kwh: float
    inverter_kw: float

    def __post_init__(self) -> None:
        """Validate install dimensions."""
        if self.pv_kwp <= 0:
            raise ValueError(
                f"pv_kwp must be > 0, got {self.pv_kwp}"
            )
        if self.battery_kwh < 0:
            raise ValueError(
                f"battery_kwh must be >= 0, got {self.battery_kwh}"
            )
        if self.inverter_kw <= 0:
            raise ValueError(
                f"inverter_kw must be > 0, got {self.inverter_kw}"
            )


# ---------------------------------------------------------------------------
# ConfigResult — per-config evaluation output (W3 task B, PRD §3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigResult:
    """Full evaluation result for one (ConfigPoint, ScenarioConfig) pair.

    Produced by :func:`run_sweep` (one per grid cell).  Combines the W2
    cost-recovery solve with baseline economics so the board can rank configs
    both by householder outlay and by project-economics trade-offs.

    Attributes:
        config: The install specification for this grid cell.
        solution: Full :class:`~solar_challenge.finance.CostRecoverySolution`
            from :func:`~solar_challenge.finance.solve_cost_recovery_rate`.
        representative_outlay_gbp: Representative (median-outlay) home's total
            annual outlay at the solved own-use rate (£).
            == solution.representative_outlay_gbp.
        solved_own_use_rate_pence_per_kwh: Solved own-use rate charged by the
            CBS to householders (p/kWh, ≥ 0).
            == solution.own_use_rate_pence_per_kwh.
        surplus_at_solved_gbp: Project net surplus per home per year at the
            solved rate (£/home/year).
            == solution.net_surplus_per_home_per_year_gbp.
        feasible: True when the CBS can meet the retained_cash_floor within
            [0, retail_baseline_rate].
            == solution.feasible.
        binding: Binding constraint — one of ``'floor'``,
            ``'rate_clamped_zero'``, ``'infeasible_above_retail'``.
            == solution.binding.
        total_capex_gbp: Total fleet capex (£) from the baseline-15p economics.
        min_dscr: Minimum DSCR over loan years from the baseline economics.
            ``float('inf')`` when debt-free.
        equity_irr: Equity IRR (fraction) from the baseline economics.
            ``float('nan')`` when undefined.
        payback_years: Equity payback year (1-based, float) from the baseline
            economics, or ``None`` if never within the asset life.
        baseline_outlay_gbp: Representative home's total annual outlay at the
            *configured* own_use_rate (15 p/kWh) derived from an independent
            age-0 fleet simulation.  Floor-independent (own_use_rate fixed).
        baseline_surplus_per_home_gbp: Project net surplus per home per year at
            own_use_rate=15p (the configured rate).
            == project_economics.net_surplus_per_home_per_year_gbp.
    """

    config: ConfigPoint
    """Install specification for this grid cell."""

    solution: "CostRecoverySolution"
    """W2 cost-recovery solve result."""

    representative_outlay_gbp: float
    """Representative home annual outlay at the solved rate (£).  W3 rank key."""

    solved_own_use_rate_pence_per_kwh: float
    """Solved own-use rate (p/kWh, ≥ 0)."""

    surplus_at_solved_gbp: float
    """Project net surplus per home per year at the solved rate (£/home/year)."""

    feasible: bool
    """True when solved within [0, retail_baseline_rate]."""

    binding: str
    """'floor', 'rate_clamped_zero', or 'infeasible_above_retail'."""

    total_capex_gbp: float
    """Total fleet capex (£) from baseline-15p project_economics."""

    min_dscr: float
    """Minimum DSCR over loan years (float('inf') when debt-free)."""

    equity_irr: float
    """Equity IRR as a fraction (float('nan') when undefined)."""

    payback_years: Optional[float]
    """First year cumulative equity cashflow ≥ 0 (1-based), or None."""

    baseline_outlay_gbp: float
    """Representative home annual outlay at own_use_rate=15p from age-0 sim (£)."""

    baseline_surplus_per_home_gbp: float
    """Project net surplus per home per year at own_use_rate=15p (£/home/year)."""


# ---------------------------------------------------------------------------
# RankedSweep — aggregated sweep output (W3 task B, PRD §3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedSweep:
    """Aggregated result of :func:`run_sweep` over a cartesian config grid.

    Attributes:
        results: Feasible :class:`ConfigResult` objects sorted ascending by
            ``representative_outlay_gbp`` (deterministic tie-break: surplus
            desc, pv_kwp asc, battery_kwh asc, inverter_kw asc).
        infeasible: :class:`ConfigPoint` objects whose
            ``binding == 'infeasible_above_retail'``, in input order.
        retained_cash_floor_gbp: The effective retained-cash floor used for
            the solve across all grid cells (£/home/year).  Echoes
            ``retained_cash_floor_gbp`` passed to :func:`run_sweep` when
            non-None, otherwise ``scenario.finance.retained_cash_floor_per_home_per_year_gbp``.
        cheapest_feasible: :class:`ConfigPoint` with the lowest
            ``representative_outlay_gbp`` (== ``results[0].config``), or
            ``None`` when ``results`` is empty.
        pareto_baseline: Non-dominated :class:`ConfigPoint` objects on the
            (baseline_outlay ↓, baseline_surplus ↑) trade-off, computed over
            ALL evaluated configs (feasible and infeasible), sorted by
            ``baseline_outlay_gbp`` ascending.
    """

    results: tuple[ConfigResult, ...]
    """Feasible configs sorted ascending by representative_outlay_gbp."""

    infeasible: tuple[ConfigPoint, ...]
    """ConfigPoints with binding=='infeasible_above_retail', in input order."""

    retained_cash_floor_gbp: float
    """Effective retained-cash floor used for the solve (£/home/year)."""

    cheapest_feasible: Optional[ConfigPoint]
    """ConfigPoint with lowest outlay (results[0].config), or None."""

    pareto_baseline: tuple[ConfigPoint, ...]
    """Non-dominated set on (baseline_outlay ↓, baseline_surplus ↑) over all configs."""

    def __post_init__(self) -> None:
        """Validate cheapest_feasible invariant."""
        if self.results:
            if self.cheapest_feasible is not self.results[0].config:
                raise ValueError(
                    "cheapest_feasible must equal results[0].config when results is non-empty; "
                    f"got cheapest_feasible={self.cheapest_feasible!r}, "
                    f"results[0].config={self.results[0].config!r}"
                )
        else:
            if self.cheapest_feasible is not None:
                raise ValueError(
                    "cheapest_feasible must be None when results is empty; "
                    f"got {self.cheapest_feasible!r}"
                )


# ---------------------------------------------------------------------------
# enumerate_configs
# ---------------------------------------------------------------------------

def iter_configs(
    base: ScenarioConfig,
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> Iterator[tuple[ConfigPoint, ScenarioConfig]]:
    """Generator variant of :func:`enumerate_configs` for memory-efficient sweeps.

    Yields one ``(ConfigPoint, ScenarioConfig)`` pair at a time, so the caller
    can process each grid cell without holding the entire product in memory.
    Prefer this over :func:`enumerate_configs` when the grid is large (e.g. a
    10×10×10 = 1 000-cell sweep over a 100-home fleet would otherwise produce
    100 000 :class:`~solar_challenge.home.HomeConfig` objects simultaneously).

    Args and raises are identical to :func:`enumerate_configs`.

    Yields:
        ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product(pv_kwp, battery_kwh, inverter_kw)`` order.
    """
    if not base.homes:
        raise ValueError(
            "iter_configs requires a fleet base (base.homes non-empty); "
            "single-home scenarios are not supported."
        )
    if not pv_kwp:
        raise ValueError("pv_kwp must be a non-empty sequence.")
    if not battery_kwh:
        raise ValueError("battery_kwh must be a non-empty sequence.")
    if not inverter_kw:
        raise ValueError("inverter_kw must be a non-empty sequence.")

    for pv, batt, inv in itertools.product(pv_kwp, battery_kwh, inverter_kw):
        point = ConfigPoint(pv_kwp=pv, battery_kwh=batt, inverter_kw=inv)
        new_homes = [_apply_install(h, point) for h in base.homes]
        yield point, replace(base, homes=new_homes)


def enumerate_configs(
    base: ScenarioConfig,
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> list[tuple[ConfigPoint, ScenarioConfig]]:
    """Enumerate homogeneous-install scenarios over the cartesian product of three
    discrete install dimensions.

    For each combination in ``itertools.product(pv_kwp, battery_kwh, inverter_kw)``
    (pv outermost, inverter innermost) a :class:`ConfigPoint` is built and a new
    :class:`~solar_challenge.config.ScenarioConfig` is produced from *base* via
    ``dataclasses.replace`` so that all scenario-level fields (finance,
    location, period, tariff, seg, name) are preserved automatically.  The homes
    in the returned scenario are homogeneous in PV/battery/inverter install
    (see :func:`_apply_install`).

    .. note::
        This function eagerly materialises the full product into a list.  For a
        moderately dense grid (e.g. 10 × 10 × 10 = 1 000 cells, 100-home fleet)
        that is ~100 000 :class:`~solar_challenge.home.HomeConfig` objects held
        simultaneously.  Use :func:`iter_configs` when memory is a concern or
        when scenarios are processed one at a time.

    Args:
        base: Fleet :class:`~solar_challenge.config.ScenarioConfig`; must have
            ``homes`` populated (``base.homes`` non-empty).  Single-home
            scenarios are rejected because the W3 sweep operates at fleet level.
        pv_kwp: Discrete PV DC capacities in kWp (non-empty).
        battery_kwh: Discrete battery capacities in kWh (non-empty; 0.0 = no battery).
        inverter_kw: Discrete AC inverter capacities in kW (non-empty).

    Returns:
        A list of ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product`` order.

    Raises:
        ValueError: If *base* is not a fleet scenario or any sequence is empty.
    """
    return list(iter_configs(base, pv_kwp, battery_kwh, inverter_kw))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _apply_install(home: HomeConfig, point: ConfigPoint) -> HomeConfig:
    """Return a new :class:`~solar_challenge.home.HomeConfig` with the PV,
    inverter, and battery install from *point* applied.

    **What is homogenized** (equalized across the fleet for a given
    :class:`ConfigPoint`):

    - PV DC capacity (``pv_config.capacity_kw``)
    - AC inverter capacity (``pv_config.inverter_capacity_kw``)
    - Battery *energy* capacity (``battery_config.capacity_kwh``)

    **What is intentionally left diverse** (preserved from the base home):

    - Battery power limit (``max_discharge_kw``), grid-charging schedule
      (``grid_charging``), and battery dispatch strategy (``dispatch_strategy``).
      Homes that already have a battery therefore retain their individual power
      and dispatch characteristics, while only capacity is swept.
    - Household load profile (``load_config``) and home-level dispatch strategy
      (``HomeConfig.dispatch_strategy``) — occupancy diversity and the board
      dispatch are preserved (PRD §3.2, W-H2).

    .. note::
        Because battery power limits and ``grid_charging`` are left diverse,
        two homes at the same :class:`ConfigPoint` may behave economically
        differently if their base configs differ in those fields.  "Homogeneous
        install" means equal *install capacity*, not equal *dispatch behaviour*.

    *PV/inverter*: ``pv_config.capacity_kw`` and ``pv_config.inverter_capacity_kw``
    are set to *point.pv_kwp* and *point.inverter_kw* respectively.

    *Battery*:

    - ``point.battery_kwh == 0.0`` (exact) → ``battery_config = None`` (no battery).
      There is no epsilon tolerance; a small positive value fabricates a battery.
    - ``point.battery_kwh > 0`` and the home already has a battery →
      ``dataclasses.replace(home.battery_config, capacity_kwh=point.battery_kwh)``
      preserving ``max_discharge_kw``, ``grid_charging``, ``dispatch_strategy``,
      ``efficiency``, and all other base fields (PRD §3.2 / design decision 2).
    - ``point.battery_kwh > 0`` and the home has NO battery → a fresh
      :class:`~solar_challenge.battery.BatteryConfig` is FABRICATED at defaults
      (``max_discharge_kw=2.5``, ``grid_charging=None``, ``dispatch_strategy=None``).
      This is the intentional divergence from ``apply_fleet_overlay`` (which
      never fabricates a battery).

    Args:
        home: Original (frozen) home configuration.
        point: Install specification for this grid cell.

    Returns:
        A fresh :class:`~solar_challenge.home.HomeConfig` with updated install.
    """
    new_pv = replace(
        home.pv_config,
        capacity_kw=point.pv_kwp,
        inverter_capacity_kw=point.inverter_kw,
    )

    new_battery: Optional[BatteryConfig]
    if point.battery_kwh == 0.0:
        new_battery = None
    elif home.battery_config is not None:
        new_battery = replace(home.battery_config, capacity_kwh=point.battery_kwh)
    else:
        new_battery = BatteryConfig(capacity_kwh=point.battery_kwh)

    return replace(home, pv_config=new_pv, battery_config=new_battery)


# ---------------------------------------------------------------------------
# run_sweep — W3 task B: per-config cost-recovery evaluation + ranking
# ---------------------------------------------------------------------------


def _age0_baseline_outlay(
    scenario: ScenarioConfig,
    finance: FinanceConfig,
    simulate: Callable[["FleetConfig", "pd.Timestamp", "pd.Timestamp"], "FleetResults"],
) -> float:
    """Compute representative householder outlay from an age-0 fleet simulation.

    Runs the fleet with all PV configs aged to 0.0 using the injected
    *simulate*, computes per-home :class:`~solar_challenge.home.SummaryStatistics`,
    and returns
    ``bill_distribution(..., finance, sim_days).representative.total_outlay_gbp``.

    This is the 'second pure post-sim evaluation' from PRD §3.3 — the baseline
    outlay at the *configured* ``own_use_rate`` (15 p/kWh), independent of the
    retained-cash floor.  The lazy imports mirror ``finance.py``'s discipline to
    avoid pulling the full pvlib/fleet stack at ``optimize`` import time.

    Args:
        scenario: Fleet scenario (must have at least one home).
        finance: FinanceConfig at the configured own_use_rate (not the solved rate).
        simulate: Injected fleet simulator callable.

    Returns:
        Representative home's total annual outlay (£).
    """
    # Lazy imports to avoid import cycles and heavy pvlib stack at module level
    from solar_challenge.finance import _resolve_homes, bill_distribution
    from solar_challenge.fleet import FleetConfig
    from solar_challenge.home import calculate_summary

    # Reuse finance._resolve_homes so homes-resolution semantics stay in one place
    homes: List[HomeConfig] = _resolve_homes(scenario)

    # Age all PV to system_age_years=0.0 (battery left unchanged for age-0 baseline)
    aged_homes = [
        replace(h, pv_config=replace(h.pv_config, system_age_years=0.0))
        for h in homes
    ]

    # Derive timezone and timestamps from the scenario
    tz: str
    if scenario.location is not None:
        tz = scenario.location.timezone
    else:
        tz = homes[0].location.timezone
    start_ts = scenario.period.get_start_timestamp(tz)
    end_ts = scenario.period.get_end_timestamp(tz)

    fleet_config = FleetConfig(homes=aged_homes, name="age-0-baseline")
    fleet_results = simulate(fleet_config, start_ts, end_ts)

    summaries = [
        calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
        for r in fleet_results.per_home_results
    ]
    sim_days = summaries[0].simulation_days if summaries else 365
    dist = bill_distribution(summaries, finance, sim_days)
    return dist.representative.total_outlay_gbp


def _split_infeasible(
    results: List[ConfigResult],
) -> tuple[List[ConfigResult], List[ConfigPoint]]:
    """Split evaluated ConfigResults into feasible list and infeasible ConfigPoints.

    Splits on the :attr:`ConfigResult.feasible` boolean rather than the
    ``binding`` string so that any future ``binding`` value with ``feasible=False``
    is correctly classified without a string-match change.

    Args:
        results: All evaluated ConfigResults from :func:`_evaluate_config`.

    Returns:
        ``(feasible_list, infeasible_points)`` where *infeasible_points* preserves
        the input order of configs whose ``feasible`` field is ``False``.
    """
    feasible: List[ConfigResult] = []
    infeasible: List[ConfigPoint] = []
    for r in results:
        if r.feasible:
            feasible.append(r)
        else:
            # binding should be 'infeasible_above_retail' when feasible=False;
            # splitting on the bool guards against future binding strings.
            infeasible.append(r.config)
    return feasible, infeasible


def _rank_feasible(feasible: List[ConfigResult]) -> List[ConfigResult]:
    """Sort feasible ConfigResults by the W3 rank key (ascending).

    Sort key (all five levels applied for determinism):

    1. ``representative_outlay_gbp`` ascending (primary — cheapest for householder)
    2. ``surplus_at_solved_gbp`` **descending** (higher surplus preferred on tie)
    3. ``config.pv_kwp`` ascending
    4. ``config.battery_kwh`` ascending
    5. ``config.inverter_kw`` ascending

    Args:
        feasible: Feasible ConfigResults (binding != 'infeasible_above_retail').

    Returns:
        New list sorted by the rank key.  The input list is not modified.
    """
    return sorted(
        feasible,
        key=lambda r: (
            r.representative_outlay_gbp,
            -r.surplus_at_solved_gbp,
            r.config.pv_kwp,
            r.config.battery_kwh,
            r.config.inverter_kw,
        ),
    )


def _pareto_baseline(results: List[ConfigResult]) -> tuple[ConfigPoint, ...]:
    """Compute the non-dominated set on the (baseline_outlay ↓, baseline_surplus ↑) plane.

    A result *A* dominates result *B* when
    ``A.baseline_outlay_gbp <= B.baseline_outlay_gbp`` **and**
    ``A.baseline_surplus_per_home_gbp >= B.baseline_surplus_per_home_gbp``
    with at least one strict inequality.

    The non-dominated :class:`ConfigPoint` objects are returned sorted by
    ``baseline_outlay_gbp`` ascending (ties broken by surplus descending) for
    reproducibility.

    Computes over **all** evaluated configs (feasible and infeasible); infeasible
    configs are included when their (outlay, surplus) pair is non-dominated.

    Args:
        results: All evaluated ConfigResults (feasible + infeasible).

    Returns:
        Non-dominated ConfigPoints sorted by baseline_outlay ascending.
    """
    non_dominated: List[ConfigResult] = []
    for cand in results:
        dominated = False
        for other in results:
            if other is cand:
                continue
            # other dominates cand if: outlay ≤ and surplus ≥ with at least one strict
            better_or_equal_outlay = (
                other.baseline_outlay_gbp <= cand.baseline_outlay_gbp
            )
            better_or_equal_surplus = (
                other.baseline_surplus_per_home_gbp >= cand.baseline_surplus_per_home_gbp
            )
            strictly_better = (
                other.baseline_outlay_gbp < cand.baseline_outlay_gbp
                or other.baseline_surplus_per_home_gbp > cand.baseline_surplus_per_home_gbp
            )
            if better_or_equal_outlay and better_or_equal_surplus and strictly_better:
                dominated = True
                break
        if not dominated:
            non_dominated.append(cand)

    # Sort by baseline_outlay ascending, then surplus descending for determinism
    non_dominated.sort(
        key=lambda r: (r.baseline_outlay_gbp, -r.baseline_surplus_per_home_gbp)
    )
    return tuple(r.config for r in non_dominated)


def _evaluate_config(
    point: ConfigPoint,
    scenario: ScenarioConfig,
    *,
    simulate: Callable[["FleetConfig", "pd.Timestamp", "pd.Timestamp"], "FleetResults"],
    retained_cash_floor_gbp: Optional[float],
) -> ConfigResult:
    """Evaluate one (ConfigPoint, ScenarioConfig) pair against the W2 contract.

    Calls three W2 primitives in sequence:

    1. :func:`~solar_challenge.finance.solve_cost_recovery_rate` → *rank* fields.
    2. :func:`~solar_challenge.finance.project_multi_year` +
       :func:`~solar_challenge.finance.project_economics` at ``finance.own_use_rate``
       (15 p/kWh) → *baseline surplus* + economics fields.
    3. :func:`_age0_baseline_outlay` → *baseline_outlay* at age 0.

    Args:
        point: Install specification for this grid cell.
        scenario: Fleet scenario for this grid cell (from :func:`enumerate_configs`).
        simulate: Injected fleet simulator callable.
        retained_cash_floor_gbp: When not None, overrides
            ``scenario.finance.retained_cash_floor_per_home_per_year_gbp`` before
            the solve; the baseline pair is computed at the *original*
            ``own_use_rate`` so it remains floor-independent.

    Returns:
        :class:`ConfigResult` with all fields populated.
    """
    from solar_challenge.finance import (
        project_economics,
        project_multi_year,
        solve_cost_recovery_rate,
    )

    # Validate finance block (required for cost-recovery sweep)
    if scenario.finance is None:
        raise ValueError(
            "run_sweep requires every scenario to have a finance block; "
            f"got scenario.finance=None for config {point!r}"
        )
    finance: FinanceConfig = scenario.finance

    # Apply retained_cash_floor_gbp override if provided
    if retained_cash_floor_gbp is not None:
        finance = replace(finance, retained_cash_floor_per_home_per_year_gbp=retained_cash_floor_gbp)
        scenario = replace(scenario, finance=finance)

    # 1. RANK: solve cost-recovery rate at the (possibly overridden) floor
    solution = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

    # 2. BASELINE + ECON: project at finance.own_use_rate (15p) — floor-independent
    curve = project_multi_year(scenario, finance, simulate=simulate)
    econ = project_economics(curve, scenario, finance)

    # 3. BASELINE OUTLAY: independent age-0 fleet sim at finance.own_use_rate
    baseline_outlay = _age0_baseline_outlay(scenario, finance, simulate)

    return ConfigResult(
        config=point,
        solution=solution,
        representative_outlay_gbp=solution.representative_outlay_gbp,
        solved_own_use_rate_pence_per_kwh=solution.own_use_rate_pence_per_kwh,
        surplus_at_solved_gbp=solution.net_surplus_per_home_per_year_gbp,
        feasible=solution.feasible,
        binding=solution.binding,
        total_capex_gbp=econ.total_capex_gbp,
        min_dscr=econ.min_dscr,
        equity_irr=econ.equity_irr,
        payback_years=econ.payback_years,
        baseline_outlay_gbp=baseline_outlay,
        baseline_surplus_per_home_gbp=econ.net_surplus_per_home_per_year_gbp,
    )


def run_sweep(
    configs: List[tuple[ConfigPoint, ScenarioConfig]],
    *,
    retained_cash_floor_gbp: Optional[float] = None,
    simulate: Optional[
        Callable[["FleetConfig", "pd.Timestamp", "pd.Timestamp"], "FleetResults"]
    ] = None,
) -> RankedSweep:
    """Drive a cartesian config grid through W2 cost-recovery evaluation and rank results.

    For each (ConfigPoint, ScenarioConfig) pair produced by :func:`enumerate_configs`:

    1. Calls :func:`~solar_challenge.finance.solve_cost_recovery_rate` at the
       (possibly overridden) retained-cash floor → *rank* fields.
    2. Calls :func:`~solar_challenge.finance.project_multi_year` +
       :func:`~solar_challenge.finance.project_economics` at
       ``finance.own_use_rate`` (15 p/kWh) → baseline surplus + economics.
    3. Runs an independent age-0 fleet simulation → baseline outlay.

    The feasible configs (``binding != 'infeasible_above_retail'``) are sorted
    ascending by ``representative_outlay_gbp`` with a deterministic 5-key
    tie-break (see :func:`_rank_feasible`).  Infeasible configs are collected as
    :class:`ConfigPoint` objects preserving input order.

    Args:
        configs: List of ``(ConfigPoint, ScenarioConfig)`` pairs, typically from
            :func:`enumerate_configs`.  Must be non-empty; every scenario must
            carry a ``finance`` block (not None).
        retained_cash_floor_gbp: When not None, overrides each scenario's
            ``finance.retained_cash_floor_per_home_per_year_gbp`` before the
            solve.  The baseline (outlay, surplus) pair is floor-independent
            (own_use_rate stays fixed at 15 p/kWh).  When None, the echoed
            ``RankedSweep.retained_cash_floor_gbp`` comes from the **first**
            config's finance block; the caller is responsible for ensuring a
            homogeneous fleet when that field is used for reporting.
        simulate: Optional injected fleet simulator for offline testing.
            Defaults to :func:`~solar_challenge.fleet.simulate_fleet`.

    Returns:
        :class:`RankedSweep` with sorted feasible results, infeasible points,
        Pareto front, cheapest config, and the effective retained-cash floor.

    Raises:
        ValueError: When *configs* is empty or any scenario's ``finance`` is None.

    .. note::
        **Simulation cost** — each config triggers up to three independent fleet
        simulations per call to :func:`_evaluate_config`: one inside
        :func:`~solar_challenge.finance.solve_cost_recovery_rate` (which
        internally calls :func:`~solar_challenge.finance.project_multi_year` at
        the solved rate), one explicit :func:`~solar_challenge.finance.project_multi_year`
        call at the baseline rate (15 p/kWh), and one age-0 baseline outlay
        simulation.  With the real ``simulate_fleet`` (ProcessPoolExecutor over
        a 100-home fleet) this is substantial: size grids conservatively or use
        an injected *simulate* for offline sweeps.
    """
    if not configs:
        raise ValueError(
            "run_sweep: configs must be non-empty; received an empty list"
        )

    if simulate is None:
        from solar_challenge.fleet import simulate_fleet as _real_simulate

        simulate = _real_simulate

    # Evaluate all configs
    all_results: List[ConfigResult] = [
        _evaluate_config(
            point,
            scenario,
            simulate=simulate,
            retained_cash_floor_gbp=retained_cash_floor_gbp,
        )
        for point, scenario in configs
    ]

    # Split into feasible / infeasible and rank
    feasible, infeasible_pts = _split_infeasible(all_results)
    ranked_feasible = _rank_feasible(feasible)

    cheapest: Optional[ConfigPoint] = (
        ranked_feasible[0].config if ranked_feasible else None
    )

    # Compute Pareto front over ALL evaluated configs
    pareto = _pareto_baseline(all_results)

    # Determine the effective retained-cash floor to echo.
    # When no global override is given, we read the floor from the FIRST config's
    # finance block.  This is a documented homogeneity assumption: callers with
    # heterogeneous finance blocks should pass retained_cash_floor_gbp explicitly
    # to get a well-defined reported floor (see run_sweep docstring).
    effective_floor: float
    if retained_cash_floor_gbp is not None:
        effective_floor = retained_cash_floor_gbp
    else:
        first_finance = configs[0][1].finance
        if first_finance is not None:
            effective_floor = first_finance.retained_cash_floor_per_home_per_year_gbp
        else:
            effective_floor = 0.0  # Guard fires before here; defensive fallback

    return RankedSweep(
        results=tuple(ranked_feasible),
        infeasible=tuple(infeasible_pts),
        retained_cash_floor_gbp=effective_floor,
        cheapest_feasible=cheapest,
        pareto_baseline=pareto,
    )
