# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discrete install-config sweep and optimisation tools.

Enumerates homogeneous-install fleet scenarios over discrete PV, battery and
inverter sizes, ranks them by householder outlay at the solved cost-recovery
own-use rate, and measures how one-at-a-time assumption changes move that
rank.  The knobs a sweep or panel varies, and the edit each makes, are
scenario_knobs'.  The design is specified in
docs/prds/discrete-install-config-sweep.md.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Iterator, List, Mapping, Optional, Sequence

from solar_challenge.battery import CAPACITY_SETTING_KWH
from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import FinanceConfig, bill_distribution
from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS, GridServicesBand
from solar_challenge.number_fields import POSITIVE, as_finite_float, read_field
from solar_challenge.projection import run_cost_recovery, scenario_fleet
from solar_challenge.scenario_knobs import KNOBS, Knob

if TYPE_CHECKING:
    from solar_challenge.finance import CostRecoverySolution
    from solar_challenge.fleet import FleetSimulate


# ---------------------------------------------------------------------------
# ConfigPoint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigPoint:
    """A single discrete install specification for the install-config sweep.

    Attributes:
        pv_kwp: PV DC rated capacity in kWp, a finite number greater than 0,
            held as a float.
        battery_kwh: Battery nameplate (total) energy capacity in kWh, a finite
            number ``battery.CAPACITY_SETTING_KWH`` admits, held as a float, and
            set as ``BatteryConfig.capacity_kwh`` on every home.  The
            energy a home can actually cycle is the usable window inside that
            capacity, bounded by its battery's ``min_soc_fraction`` and
            ``max_soc_fraction``.
            The value **exactly** ``0.0`` is the no-battery sentinel; the
            ``battery_capacity_kwh`` knob of
            :mod:`~solar_challenge.scenario_knobs`, which
            :func:`enumerate_configs` / :func:`iter_configs` apply, then sets
            ``battery_config = None`` on every home in the scenario.  Any
            strictly positive value — however small — triggers battery
            fabrication or replacement; there is no epsilon tolerance.
            Callers must pass ``0.0`` (not, e.g., ``1e-9``) to mean
            "no battery".
        inverter_kw: AC inverter rated capacity in kW, a finite number greater
            than 0, held as a float.
    """

    pv_kwp: float
    battery_kwh: float
    inverter_kw: float

    def __post_init__(self) -> None:
        """Read the three install dimensions through number_fields, holding the floats read."""
        read_field(self, "pv_kwp", as_finite_float, POSITIVE)
        read_field(self, "battery_kwh", as_finite_float, CAPACITY_SETTING_KWH)
        read_field(self, "inverter_kw", as_finite_float, POSITIVE)


# Each install knob a ConfigPoint sets, with the dimension of the point it sets it to.
_INSTALL_KNOBS: tuple[tuple[Knob, Callable[[ConfigPoint], float]], ...] = (
    (KNOBS["pv_capacity_kw"], lambda point: point.pv_kwp),
    (KNOBS["battery_capacity_kwh"], lambda point: point.battery_kwh),
    (KNOBS["inverter_capacity_kw"], lambda point: point.inverter_kw),
)


def _installed(base: ScenarioConfig, point: ConfigPoint) -> ScenarioConfig:
    """*base* with each install knob applied at its dimension of *point*."""
    scenario = base
    for knob, dimension in _INSTALL_KNOBS:
        scenario = knob.apply(scenario, dimension(point))
    return scenario


# ---------------------------------------------------------------------------
# ConfigResult — per-config evaluation output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigResult:
    """Full evaluation result for one (ConfigPoint, ScenarioConfig) pair.

    Produced by :func:`run_sweep` (one per grid cell).  Combines the projection's
    cost-recovery solve with baseline economics so the board can rank configs
    both by householder outlay and by project-economics trade-offs.  The
    baseline economics, outlay and surplus are at the configured own-use rate
    (``baseline_own_use_rate_pence_per_kwh``).

    The five solved fields, ``representative_outlay_gbp``,
    ``solved_own_use_rate_pence_per_kwh``, ``surplus_at_solved_gbp``,
    ``feasible`` and ``binding``, are read-only properties that read through
    ``solution``, so they cannot disagree with it.

    Attributes:
        config: The install specification for this grid cell.
        solution: Full :class:`~solar_challenge.finance.CostRecoverySolution`
            from :func:`~solar_challenge.projection.run_cost_recovery`.
        total_capex_gbp: Total fleet capex (£) from the baseline economics, at
            the configured own-use rate (baseline_own_use_rate_pence_per_kwh).
        min_dscr: Minimum DSCR over loan years from the baseline economics.
            ``float('inf')`` when debt-free.
        equity_irr: Equity IRR (fraction) from the baseline economics.
            ``float('nan')`` when undefined.
        payback_years: Equity payback year (1-based, float) from the baseline
            economics, or ``None`` if never within the asset life.
        baseline_own_use_rate_pence_per_kwh: The configured own-use rate the
            baseline pair is priced at (p/kWh), the scenario's
            ``finance.own_use_rate_pence_per_kwh``.
        baseline_outlay_gbp: Representative home's total annual outlay at the
            configured own-use rate (baseline_own_use_rate_pence_per_kwh),
            billed on the projection's age-0 summaries: a new install with the
            scenario's SEG.  Floor-independent (own-use rate fixed).
        baseline_surplus_per_home_gbp: Project net surplus per home per year at
            the configured own-use rate (baseline_own_use_rate_pence_per_kwh).
            == project_economics.net_surplus_per_home_per_year_gbp.
    """

    config: ConfigPoint
    """Install specification for this grid cell."""

    solution: "CostRecoverySolution"
    """Cost-recovery solve result."""

    total_capex_gbp: float
    """Total fleet capex (£) from the baseline project_economics, at the configured own-use rate."""

    min_dscr: float
    """Minimum DSCR over loan years (float('inf') when debt-free)."""

    equity_irr: float
    """Equity IRR as a fraction (float('nan') when undefined)."""

    payback_years: Optional[float]
    """First year cumulative equity cashflow ≥ 0 (1-based), or None."""

    baseline_own_use_rate_pence_per_kwh: float
    """The configured own-use rate the baseline pair is priced at, the scenario's finance.own_use_rate_pence_per_kwh (p/kWh)."""

    baseline_outlay_gbp: float
    """Representative home annual outlay at the configured own-use rate, billed on the projection's age-0 summaries (£)."""

    baseline_surplus_per_home_gbp: float
    """Project net surplus per home per year at the configured own-use rate (£/home/year)."""

    @property
    def representative_outlay_gbp(self) -> float:
        """Representative home annual outlay at the solved rate (£), the solution's; the primary rank key."""
        return self.solution.representative_outlay_gbp

    @property
    def solved_own_use_rate_pence_per_kwh(self) -> float:
        """The solution's solved own-use rate (p/kWh, ≥ 0)."""
        return self.solution.own_use_rate_pence_per_kwh

    @property
    def surplus_at_solved_gbp(self) -> float:
        """The solution's project net surplus per home per year at the solved rate (£/home/year)."""
        return self.solution.net_surplus_per_home_per_year_gbp

    @property
    def feasible(self) -> bool:
        """The solution's feasible flag: False exactly when its binding is 'infeasible_above_retail'."""
        return self.solution.feasible

    @property
    def binding(self) -> str:
        """The solution's binding: 'floor', 'rate_clamped_zero' or 'infeasible_above_retail'."""
        return self.solution.binding


# ---------------------------------------------------------------------------
# RankedSweep — aggregated sweep output
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
        retained_cash_floor_gbp: The retained-cash floor every config's
            finance sets, ``finance.retained_cash_floor_per_home_per_year_gbp``,
            which :func:`run_sweep` requires to be one (£/home/year): the
            floor of every grid cell's solve.
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
    """The configs' common retained-cash floor, every solve's (£/home/year)."""

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

def _require_fleet_scenario(scenario: ScenarioConfig, caller: str) -> None:
    """Raise ValueError unless *scenario* is a fleet scenario (``homes=[...]``)."""
    if not scenario.is_fleet:
        raise ValueError(
            f"{caller} requires a fleet scenario (homes=[...]); scenario "
            f"'{scenario.name}' is single-home, and single-home scenarios are not supported."
        )


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
    _require_fleet_scenario(base, "iter_configs")
    if not pv_kwp:
        raise ValueError("pv_kwp must be a non-empty sequence.")
    if not battery_kwh:
        raise ValueError("battery_kwh must be a non-empty sequence.")
    if not inverter_kw:
        raise ValueError("inverter_kw must be a non-empty sequence.")

    for pv, batt, inv in itertools.product(pv_kwp, battery_kwh, inverter_kw):
        point = ConfigPoint(pv_kwp=pv, battery_kwh=batt, inverter_kw=inv)
        yield point, _installed(base, point)


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
    :class:`~solar_challenge.config.ScenarioConfig` is produced from *base* by
    the ``pv_capacity_kw``, ``battery_capacity_kwh`` and ``inverter_capacity_kw``
    knobs of :mod:`~solar_challenge.scenario_knobs`, so every scenario-level
    field is kept.  The homes in the returned scenario are homogeneous in
    PV/battery/inverter install capacity.

    .. note::
        This function eagerly materialises the full product into a list.  For a
        moderately dense grid (e.g. 10 × 10 × 10 = 1 000 cells, 100-home fleet)
        that is ~100 000 :class:`~solar_challenge.home.HomeConfig` objects held
        simultaneously.  Use :func:`iter_configs` when memory is a concern or
        when scenarios are processed one at a time.

    Args:
        base: Fleet :class:`~solar_challenge.config.ScenarioConfig`; must have
            ``homes`` populated (``base.homes`` non-empty).  Single-home
            scenarios are rejected because the sweep operates at fleet level.
        pv_kwp: Discrete PV DC capacities in kWp (non-empty).
        battery_kwh: Discrete values for :attr:`ConfigPoint.battery_kwh`, the
            battery nameplate (total) capacities in kWh (non-empty; 0.0 = no
            battery).
        inverter_kw: Discrete AC inverter capacities in kW (non-empty).

    Returns:
        A list of ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product`` order.

    Raises:
        ValueError: If *base* is not a fleet scenario or any sequence is empty.
    """
    return list(iter_configs(base, pv_kwp, battery_kwh, inverter_kw))


# ---------------------------------------------------------------------------
# Public pure helpers
# ---------------------------------------------------------------------------

__all__ = [
    "ConfigPoint",
    "ConfigResult",
    "RankedSweep",
    "enumerate_configs",
    "iter_configs",
    "run_sweep",
    "rank",
    "feasible_split",
    "pareto_baseline",
    "cheapest_feasible",
    "SensitivityAxis",
    "SensitivityPanel",
    "sensitivity_panel",
    "SENSITIVITY_BANDS",
]


# ---------------------------------------------------------------------------
# OAT sensitivity dataclasses
# ---------------------------------------------------------------------------

def _check_axis_values(name: str, values: Sequence[float]) -> None:
    """Refuse an axis that sweeps no value or sweeps a value twice, naming the axis *name*."""
    if not values:
        raise ValueError(f"axis '{name}': values must not be empty")
    repeated = sorted(value for value, count in Counter(values).items() if count > 1)
    if repeated:
        raise ValueError(f"axis '{name}' sweeps {repeated} more than once; give each value once")


@dataclass(frozen=True)
class SensitivityAxis:
    """One one-at-a-time (OAT) sensitivity axis.

    Records the sweep of a single numeric knob over a range of values and
    the resulting per-value ConfigPoint rankings and cheapest-feasible tops.

    Attributes:
        name: The swept knob's canonical name, its
            :class:`~solar_challenge.scenario_knobs.Knob`'s ``name``.
        values: Swept values for this axis (non-empty, none repeated).
        rankings: Per-value tuple of feasible ConfigPoints in ascending
            outlay order (i.e. ``run_sweep(...).results`` mapped to configs).
            Infeasible configs are absent.  Length == len(values).
        top_config_per_value: Cheapest-feasible ConfigPoint at each swept
            value, or ``None`` when every config is infeasible at that value.
            Length == len(values).
    """

    name: str
    values: "tuple[float, ...]"
    rankings: "tuple[tuple[ConfigPoint, ...], ...]"
    top_config_per_value: "tuple[Optional[ConfigPoint], ...]"

    def __post_init__(self) -> None:
        _check_axis_values(self.name, self.values)
        if len(self.values) != len(self.rankings):
            raise ValueError(
                f"SensitivityAxis '{self.name}': "
                f"len(values)={len(self.values)} != len(rankings)={len(self.rankings)}"
            )
        if len(self.values) != len(self.top_config_per_value):
            raise ValueError(
                f"SensitivityAxis '{self.name}': "
                f"len(values)={len(self.values)} != "
                f"len(top_config_per_value)={len(self.top_config_per_value)}"
            )


@dataclass(frozen=True)
class SensitivityPanel:
    """Aggregated OAT sensitivity output over all axes.

    Attributes:
        axes: One :class:`SensitivityAxis` per swept knob (non-empty).
        baseline_top: The cheapest-feasible :class:`ConfigPoint` of the
            caller's baseline sweep, the ``run_sweep`` of the base scenarios
            at their own finance and tariff values.
        rank_stability: Fraction of (axis, value) points for which
            ``cheapest_feasible == baseline_top``; ``None`` tops count as
            unstable.  In [0, 1].
    """

    axes: "tuple[SensitivityAxis, ...]"
    baseline_top: ConfigPoint
    rank_stability: float

    def __post_init__(self) -> None:
        if not self.axes:
            raise ValueError("SensitivityPanel.axes must not be empty")
        if not (0.0 <= self.rank_stability <= 1.0):
            raise ValueError(
                f"SensitivityPanel.rank_stability must be in [0, 1], "
                f"got {self.rank_stability}"
            )


# ---------------------------------------------------------------------------
# OAT sensitivity bands
# ---------------------------------------------------------------------------

# Board-facing values to sweep per sensitivity_panel knob, headline axes first; pass the mapping,
# or a subset, as the panel's axes. Grid services sweeps GRID_SERVICES_RATE_BANDS' flat column, low to high;
# the other spans are provisional: docs/prds/discrete-install-config-sweep.md §12, questions 2-3.
SENSITIVITY_BANDS: Mapping[Knob, tuple[float, ...]] = MappingProxyType({
    KNOBS["retained_cash_floor_per_home_per_year_gbp"]: (15.0, 27.0, 40.0),
    KNOBS["grid_services_income_per_kw_per_year_gbp"]: tuple(
        GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year for band in GridServicesBand
    ),
    KNOBS["battery_cost_per_kwh_gbp"]: (200.0, 300.0, 450.0),
    KNOBS["pv_cost_per_kwp_gbp"]: (800.0, 1200.0, 1800.0),
    KNOBS["inverter_cost_per_kw_gbp"]: (100.0, 200.0, 350.0),
})


# ---------------------------------------------------------------------------
# OAT sensitivity panel
# ---------------------------------------------------------------------------

def _baseline_top(
    base_configs: Sequence[tuple[ConfigPoint, ScenarioConfig]], baseline: RankedSweep
) -> ConfigPoint:
    """*baseline*'s cheapest feasible config, refusing a baseline that is not the run_sweep of *base_configs*."""
    evaluated = Counter([*(result.config for result in baseline.results), *baseline.infeasible])
    expected = Counter(point for point, _ in base_configs)
    if evaluated != expected:
        raise ValueError(
            "sensitivity_panel's baseline must be the run_sweep of base_configs; base_configs hold "
            f"{list(expected.elements())} but the baseline evaluated {list(evaluated.elements())}"
        )
    floor = _common_floor(base_configs)
    if baseline.retained_cash_floor_gbp != floor:
        raise ValueError(
            "sensitivity_panel's baseline must be the run_sweep of base_configs; base_configs set a "
            f"retained-cash floor of {floor!r} £/home/yr but the baseline was solved at "
            f"{baseline.retained_cash_floor_gbp!r}"
        )
    if baseline.cheapest_feasible is None:
        raise ValueError(
            "baseline run_sweep has no feasible config; cannot form a sensitivity panel"
        )
    return baseline.cheapest_feasible


def _sweep_at(
    knob: Knob,
    value: float,
    base_configs: Sequence[tuple[ConfigPoint, ScenarioConfig]],
    *,
    baseline: RankedSweep,
    simulate: FleetSimulate,
) -> RankedSweep:
    """The sweep of *base_configs* with *knob* at *value*: *baseline* itself when that leaves every scenario equal."""
    applied = [(point, knob.apply(scenario, value)) for point, scenario in base_configs]
    if all(after == before for (_, after), (_, before) in zip(applied, base_configs, strict=True)):
        return baseline
    return run_sweep(applied, simulate=simulate)


def _axis(
    knob: Knob,
    values: Sequence[float],
    base_configs: Sequence[tuple[ConfigPoint, ScenarioConfig]],
    *,
    baseline: RankedSweep,
    simulate: FleetSimulate,
) -> SensitivityAxis:
    """The panel's axis for *knob*: each of *values* swept in isolation."""
    sweeps = [
        _sweep_at(knob, value, base_configs, baseline=baseline, simulate=simulate) for value in values
    ]
    return SensitivityAxis(
        name=knob.name,
        values=tuple(values),
        rankings=tuple(tuple(result.config for result in sweep.results) for sweep in sweeps),
        top_config_per_value=tuple(sweep.cheapest_feasible for sweep in sweeps),
    )


def sensitivity_panel(
    base_configs: "List[tuple[ConfigPoint, ScenarioConfig]]",
    axes: "Mapping[Knob, Sequence[float]]",
    *,
    baseline: RankedSweep,
    simulate: FleetSimulate,
) -> SensitivityPanel:
    """Compute a one-at-a-time (OAT) sensitivity panel over the cost-recovery rank.

    For each axis (knob + values), every value is swept in isolation while
    all other knobs stay at their baseline levels: each value's ``knob.apply``
    sets that knob on every base scenario, and the scenarios so set are swept
    with :func:`run_sweep`.  A value that leaves every base scenario equal,
    such as the floor axis at the scenarios' own floor, reuses *baseline*
    rather than sweeping it again.

    Args:
        base_configs: (ConfigPoint, ScenarioConfig) pairs produced by
            :func:`enumerate_configs`.  The scenarios carry the baseline
            finance / tariff values, the retained-cash floor included.
        axes: Mapping of :class:`~solar_challenge.scenario_knobs.Knob` (a value
            of ``scenario_knobs.KNOBS``) → non-empty sequence of float values,
            none repeated.  :data:`SENSITIVITY_BANDS`, or a subset of it, holds
            the board-facing values.
        baseline: The :class:`RankedSweep` that ``run_sweep(base_configs)``
            returned: the panel's baseline, never swept again.
        simulate: The fleet simulator every ``run_sweep`` call runs through,
            such as a :class:`~solar_challenge.fleet.FleetRunner`'s ``simulate``.

    Returns:
        :class:`SensitivityPanel` with one :class:`SensitivityAxis` per entry
        in *axes*.

    Raises:
        ValueError: Before any simulation, if *base_configs* is empty, *axes*
            is empty, an axis has no values or repeats one, *baseline*'s
            evaluated points or retained-cash floor differ from
            *base_configs*', or *baseline* has no feasible config.  Each axis
            also propagates any ValueError (ConfigurationError included) that
            its ``knob.apply`` raises.
    """
    if not base_configs:
        raise ValueError("base_configs must not be empty")
    if not axes:
        raise ValueError("axes mapping must not be empty")
    for knob, values in axes.items():
        _check_axis_values(knob.name, values)
    baseline_top = _baseline_top(base_configs, baseline)

    panel_axes = tuple(
        _axis(knob, values, base_configs, baseline=baseline, simulate=simulate)
        for knob, values in axes.items()
    )
    tops = [top for axis in panel_axes for top in axis.top_config_per_value]
    return SensitivityPanel(
        axes=panel_axes,
        baseline_top=baseline_top,
        rank_stability=sum(top == baseline_top for top in tops) / len(tops),
    )


def cheapest_feasible(
    results: Sequence["ConfigResult"],
) -> "Optional[ConfigPoint]":
    """Return the :class:`ConfigPoint` with the lowest ``representative_outlay_gbp``
    among feasible results, or ``None`` when no feasible result exists.

    Uses :func:`feasible_split` to partition then :func:`rank` to sort; the
    winner is always a feasible record even when infeasible records have a
    globally lower outlay.

    .. note::
        This function shares its name with the :attr:`RankedSweep.cheapest_feasible`
        dataclass field it logically produces.  The function is the computation;
        the field stores the result.  Inside :func:`run_sweep` the field is
        populated directly from the already-ranked feasible list (``ranked_feasible[0].config``)
        rather than by calling this function, to avoid a redundant sort pass.

    Args:
        results: Any sequence of :class:`ConfigResult` objects (may be empty).

    Returns:
        :class:`ConfigPoint` of ``rank(feasible)[0]``, or ``None`` when the
        feasible list is empty.
    """
    feasible, _ = feasible_split(results)
    ranked = rank(feasible)
    return ranked[0].config if ranked else None


def pareto_baseline(
    results: Sequence["ConfigResult"],
) -> "tuple[ConfigPoint, ...]":
    """Compute the non-dominated set on the (baseline_outlay ↓, baseline_surplus ↑) plane.

    A result *A* dominates result *B* when
    ``A.baseline_outlay_gbp <= B.baseline_outlay_gbp`` **and**
    ``A.baseline_surplus_per_home_gbp >= B.baseline_surplus_per_home_gbp``
    with at least one strict inequality.

    Computes over **all** supplied configs (feasible and infeasible); infeasible
    configs are included when their (outlay, surplus) pair is non-dominated.

    The non-dominated :class:`ConfigPoint` objects are returned sorted by
    ``baseline_outlay_gbp`` ascending (ties broken by surplus descending) for
    reproducibility.

    Args:
        results: Any sequence of :class:`ConfigResult` objects (may be empty).

    Returns:
        Non-dominated :class:`ConfigPoint` objects sorted by baseline_outlay ascending.
    """
    non_dominated: List[ConfigResult] = []
    for cand in results:
        dominated = False
        for other in results:
            if other is cand:
                continue
            better_or_equal_outlay = other.baseline_outlay_gbp <= cand.baseline_outlay_gbp
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

    non_dominated.sort(
        key=lambda r: (r.baseline_outlay_gbp, -r.baseline_surplus_per_home_gbp)
    )
    return tuple(r.config for r in non_dominated)


def feasible_split(
    results: Sequence["ConfigResult"],
) -> "tuple[List[ConfigResult], List[ConfigResult]]":
    """Partition ConfigResults into feasible and infeasible lists.

    The split is on :attr:`ConfigResult.feasible`, which is False exactly
    for ``binding == 'infeasible_above_retail'``: the solution refuses any
    other pairing at construction.

    Input order is preserved within each output list.

    Args:
        results: Any sequence of :class:`ConfigResult` objects (may be empty).

    Returns:
        ``(feasible, infeasible)`` where *infeasible* contains every record
        whose ``feasible`` is False and *feasible* contains the remainder.
        Both sides are :class:`ConfigResult` lists.
    """
    feasible: List[ConfigResult] = []
    infeasible: List[ConfigResult] = []
    for r in results:
        if r.feasible:
            feasible.append(r)
        else:
            infeasible.append(r)
    return feasible, infeasible


def rank(results: Sequence["ConfigResult"]) -> "List[ConfigResult]":
    """Sort ConfigResults by the sweep's rank key (pure, stable, no filtering).

    Sort key (five levels, all applied for determinism):

    1. ``representative_outlay_gbp`` ascending — cheapest householder outlay first.
    2. ``surplus_at_solved_gbp`` **descending** — higher project surplus preferred on tie.
    3. ``config.pv_kwp`` ascending.
    4. ``config.battery_kwh`` ascending.
    5. ``config.inverter_kw`` ascending.

    Infeasible-binding records (``binding == 'infeasible_above_retail'``) are NOT
    filtered; they appear in the output at their natural sort position.  Use
    :func:`feasible_split` before calling ``rank`` when only feasible results are
    needed.

    Args:
        results: Any sequence of :class:`ConfigResult` objects (may be empty).

    Returns:
        New list sorted by the rank key.  The input sequence is not modified.
    """
    return sorted(
        results,
        key=lambda r: (
            r.representative_outlay_gbp,
            -r.surplus_at_solved_gbp,
            r.config.pv_kwp,
            r.config.battery_kwh,
            r.config.inverter_kw,
        ),
    )


# ---------------------------------------------------------------------------
# run_sweep — per-config cost-recovery evaluation + ranking
# ---------------------------------------------------------------------------


def _required_finance(point: ConfigPoint, scenario: ScenarioConfig) -> FinanceConfig:
    """*scenario*'s finance block, which a cost-recovery sweep of *point* requires."""
    if scenario.finance is None:
        raise ValueError(
            "a cost-recovery sweep requires every scenario to have a finance block; "
            f"got scenario.finance=None for config {point!r}"
        )
    return scenario.finance


def _common_floor(configs: Sequence[tuple[ConfigPoint, ScenarioConfig]]) -> float:
    """The retained-cash floor every config's finance sets, refusing configs at two floors."""
    first_point, first_scenario = configs[0]
    floor = _required_finance(first_point, first_scenario).retained_cash_floor_per_home_per_year_gbp
    for point, scenario in configs[1:]:
        other = _required_finance(point, scenario).retained_cash_floor_per_home_per_year_gbp
        if other != floor:
            raise ValueError(
                "a cost-recovery sweep solves every config at one retained-cash floor; "
                f"config {first_point!r} sets {floor!r} £/home/yr but config {point!r} sets {other!r}. "
                "Set the floor on the base scenario, through its "
                "retained_cash_floor_per_home_per_year_gbp knob, before enumerate_configs."
            )
    return floor


def _evaluate_config(
    point: ConfigPoint,
    scenario: ScenarioConfig,
    *,
    simulate: FleetSimulate,
) -> ConfigResult:
    """Evaluate one (ConfigPoint, ScenarioConfig) pair with one :func:`~solar_challenge.projection.run_cost_recovery`.

    The run's solution gives the *rank* fields; its economics, at
    ``finance.own_use_rate_pence_per_kwh``, the baseline surplus and economics
    fields; and its projection's age-0 summaries, billed at that rate, the
    baseline outlay.

    Args:
        point: Install specification for this grid cell.
        scenario: Fleet scenario for this grid cell (from :func:`enumerate_configs`);
            its finance block sets the retained-cash floor of the solve, which the
            baseline pair does not read.
        simulate: Injected fleet simulator callable.

    Returns:
        :class:`ConfigResult` with all fields populated.
    """
    finance = _required_finance(point, scenario)
    run = run_cost_recovery(scenario_fleet(scenario), finance, simulate=simulate)
    solution = run.solution
    econ = run.economics
    baseline_outlay = bill_distribution(run.projection.age0_summaries, finance).representative.total_outlay_gbp

    return ConfigResult(
        config=point,
        solution=solution,
        total_capex_gbp=econ.total_capex_gbp,
        min_dscr=econ.min_dscr,
        equity_irr=econ.equity_irr,
        payback_years=econ.payback_years,
        baseline_own_use_rate_pence_per_kwh=finance.own_use_rate_pence_per_kwh,
        baseline_outlay_gbp=baseline_outlay,
        baseline_surplus_per_home_gbp=econ.net_surplus_per_home_per_year_gbp,
    )


def run_sweep(
    configs: List[tuple[ConfigPoint, ScenarioConfig]],
    *,
    simulate: FleetSimulate,
) -> RankedSweep:
    """Drive a cartesian config grid through cost-recovery evaluation and rank results.

    For each (ConfigPoint, ScenarioConfig) pair produced by :func:`enumerate_configs`,
    makes one :func:`~solar_challenge.projection.run_cost_recovery` at the
    retained-cash floor its finance sets: its solution gives the *rank*
    fields, its economics the baseline surplus and economics, and its
    projection's age-0 summaries the baseline outlay, all at
    ``finance.own_use_rate_pence_per_kwh``.

    The feasible configs (``binding != 'infeasible_above_retail'``, split off by
    :func:`feasible_split`) are sorted ascending by ``representative_outlay_gbp``
    with a deterministic 5-key tie-break (see :func:`rank`).  Infeasible configs
    are collected as :class:`ConfigPoint` objects preserving input order.

    Args:
        configs: List of ``(ConfigPoint, ScenarioConfig)`` pairs, typically from
            :func:`enumerate_configs`.  Must be non-empty; every scenario must
            carry a ``finance`` block (not None), and every finance block must
            set the same ``retained_cash_floor_per_home_per_year_gbp``: set the
            floor on the base scenario, through its knob, before enumerating.
        simulate: The fleet simulator every config's projection runs
            through, such as a :class:`~solar_challenge.fleet.FleetRunner`'s
            ``simulate``.

    Returns:
        :class:`RankedSweep` with sorted feasible results, infeasible points,
        Pareto front, cheapest config, and the configs' common retained-cash
        floor.

    Raises:
        ValueError: When *configs* is empty, any scenario's ``finance`` is
            None, or two configs' finance blocks set different retained-cash
            floors; each is refused before any simulation.

    .. note::
        **Simulation cost** — each config is one projection: at least
        ``projection.fewest_simulated_ages(asset_life_years)`` fleet
        simulations (5 at the default 25 years), more where bisection adds
        ages.  With the real :meth:`~solar_challenge.fleet.FleetRunner.simulate` (a process pool over
        a 100-home fleet) this is substantial: size grids conservatively or pass
        a stand-in *simulate* for offline sweeps.
    """
    if not configs:
        raise ValueError(
            "run_sweep: configs must be non-empty; received an empty list"
        )
    common_floor = _common_floor(configs)

    # Evaluate all configs
    all_results: List[ConfigResult] = [
        _evaluate_config(point, scenario, simulate=simulate)
        for point, scenario in configs
    ]

    # Split, rank, and derive cheapest using the public pure helpers
    feasible_results, infeasible_results = feasible_split(all_results)
    ranked_feasible = rank(feasible_results)
    infeasible_pts = [r.config for r in infeasible_results]
    # Derive cheapest from the already-ranked list to avoid redundant O(n log n) work.
    cheapest: Optional[ConfigPoint] = ranked_feasible[0].config if ranked_feasible else None

    # Compute Pareto front over ALL evaluated configs (feasible + infeasible)
    pareto = pareto_baseline(all_results)

    return RankedSweep(
        results=tuple(ranked_feasible),
        infeasible=tuple(infeasible_pts),
        retained_cash_floor_gbp=common_floor,
        cheapest_feasible=cheapest,
        pareto_baseline=pareto,
    )
