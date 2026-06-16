# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Per-householder bill computation, fleet bill distribution, and multi-year
projection (ζ surface).

Provides:
  - ``BillBreakdown`` — frozen dataclass with 11 financial line items.
  - ``BillDistribution`` — frozen dataclass with fleet-level bill statistics.
  - ``householder_bill`` — pure function mapping simulation outputs to a bill.
  - ``bill_distribution`` — aggregates per-home bills into a BillDistribution.
  - ``YearPoint`` — frozen dataclass for one year in a multi-year projection.
  - ``MultiYearCurve`` — frozen dataclass for a full 25-yr projection curve.
  - ``project_multi_year`` — forward-march driver for adaptive PCHIP projection.

All monetary values are in GBP (£); energy in kWh.  The module is fully
deterministic and has no side-effects: suitable for use in parallel fleet runs.
"""
from __future__ import annotations

import dataclasses
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence

import pandas as pd

if TYPE_CHECKING:
    from solar_challenge.config import FinanceConfig, ScenarioConfig
    from solar_challenge.fleet import FleetConfig, FleetResults
    from solar_challenge.home import SummaryStatistics


# ---------------------------------------------------------------------------
# BillBreakdown — 11 required fields per §3.1
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BillBreakdown:
    """Per-householder annual bill broken into component line items.

    Definitional invariants (§8):
      vat_gbp           = vat_rate × (import_cost_gbp + standing_charge_gbp)
      gross_bill_gbp    = (import_cost_gbp + standing_charge_gbp) × (1 + vat_rate)
      net_annual_bill_gbp = gross_bill_gbp − seg_export_income_gbp

    SEG export revenue is zero-rated (no VAT).
    Savings and baseline are valued VAT-inclusive at the retail baseline rate.

    All fields are floats in GBP (£).
    """

    standing_charge_gbp: float
    """Annual grid standing charge (£)."""

    import_cost_gbp: float
    """Cost of electricity imported from the grid (£, ex-VAT)."""

    vat_gbp: float
    """VAT on import cost + standing charge at the scenario VAT rate (£)."""

    gross_bill_gbp: float
    """Total retail bill before SEG export income: (import + standing) × (1 + vat) (£)."""

    seg_export_income_gbp: float
    """SEG export revenue (£); zero-rated, no VAT deducted."""

    self_consumption_saving_gbp: float
    """Value of self-consumed solar at the VAT-inclusive retail baseline rate (£)."""

    baseline_bill_gbp: float
    """Hypothetical annual bill without any solar / battery system (£, VAT-inclusive)."""

    net_annual_bill_gbp: float
    """Net annual bill after deducting SEG export income: gross_bill − seg_export_income (£)."""

    saving_vs_baseline_gbp: float
    """Saving compared to the no-solar baseline: baseline − net_annual_bill (£)."""

    saving_pct: float
    """Percentage saving vs baseline: 100 × saving_vs_baseline / baseline."""

    self_consumption_fraction: float
    """Fraction of total PV generation consumed on-site (dimensionless, 0–1)."""


# ---------------------------------------------------------------------------
# BillDistribution — fleet-level statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BillDistribution:
    """Fleet-wide distribution of per-home annual bills.

    ``representative`` is the BillBreakdown of the home whose net_annual_bill_gbp
    is closest to the median (median-net-bill home).  Per-home net bills are
    stored as an immutable tuple so the dataclass remains hashable.
    """

    representative: BillBreakdown
    """Representative (median-net-bill) home's full BillBreakdown."""

    per_home_net_bill_gbp: tuple[float, ...]
    """Net annual bill for each home in the fleet (£)."""

    min_gbp: float
    """Minimum net annual bill across the fleet (£)."""

    mean_gbp: float
    """Mean net annual bill across the fleet (£)."""

    median_gbp: float
    """Median net annual bill across the fleet (£)."""

    max_gbp: float
    """Maximum net annual bill across the fleet (£)."""


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Default self-consumption fraction used for the spreadsheet assumption when no
#: explicit ``self_consumption_override`` is set in ``FinanceConfig``.  Exposed
#: here (rather than buried in the CLI) so config-file authors and non-CLI
#: callers can discover and reference the value alongside the other finance
#: parameters.
DEFAULT_SPREADSHEET_SELF_CONSUMPTION: float = 0.70

# ---------------------------------------------------------------------------
# householder_bill
# ---------------------------------------------------------------------------

_ANNUALISATION_DAYS = 365
_SHORT_PERIOD_THRESHOLD = 360


def householder_bill(
    summary: "SummaryStatistics",
    annual_self_consumption_kwh: float,
    finance: "FinanceConfig",
    simulation_days: int,
) -> BillBreakdown:
    """Compute a per-householder annual bill from simulation outputs.

    Implements the §8 definitional invariants:

    * ``vat_gbp = vat_rate × (import_cost_gbp + standing_charge_gbp)``
    * ``gross_bill_gbp = (import_cost_gbp + standing_charge_gbp) × (1 + vat_rate)``
    * ``net_annual_bill_gbp = gross_bill_gbp − seg_export_income_gbp``

    Args:
        summary: Per-home simulation output (read-only).
        annual_self_consumption_kwh: Physics self-consumption figure (kWh).
            When ``finance.self_consumption_override`` is None, this is used
            directly.  When an override is set, it is used only for scaling.
        finance: FinanceConfig with tariff + assumption parameters.
        simulation_days: Actual simulation length in days; triggers
            annualisation to 365 days when < 360.

    Returns:
        A fully computed, frozen BillBreakdown.
    """
    vat_rate = finance.vat_rate
    retail_rate_pence = finance.retail_baseline_rate_pence_per_kwh
    standing_pence_per_day = finance.standing_charge_pence_per_day
    override = finance.self_consumption_override

    # ---- Annualisation (§3.2 / §12) ----------------------------------------
    if simulation_days < _SHORT_PERIOD_THRESHOLD:
        scale = _ANNUALISATION_DAYS / max(simulation_days, 1)
        warnings.warn(
            f"Simulation period is only {simulation_days} days (<360); "
            f"scaling financial outputs to {_ANNUALISATION_DAYS}-day annual basis "
            f"(scale={scale:.3f}).",
            UserWarning,
            stacklevel=2,
        )
        # Scale physics energy quantities
        gen_kwh = summary.total_generation_kwh * scale
        demand_kwh = summary.total_demand_kwh * scale
        sc_kwh_physics = annual_self_consumption_kwh * scale
        import_kwh = summary.total_grid_import_kwh * scale
        export_kwh = summary.total_grid_export_kwh * scale
        import_cost_physics = summary.total_import_cost_gbp * scale
        export_rev_physics = summary.total_export_revenue_gbp * scale
    else:
        scale = 1.0
        gen_kwh = summary.total_generation_kwh
        demand_kwh = summary.total_demand_kwh
        sc_kwh_physics = annual_self_consumption_kwh
        import_kwh = summary.total_grid_import_kwh
        export_kwh = summary.total_grid_export_kwh
        import_cost_physics = summary.total_import_cost_gbp
        export_rev_physics = summary.total_export_revenue_gbp

    # ---- Standing charge (always annualised to 365 days) --------------------
    standing_charge_gbp = standing_pence_per_day * _ANNUALISATION_DAYS / 100.0

    # ---- Self-consumption switch (§2.3 / §3.2) ------------------------------
    if override is None:
        # Physics path: use simulation figures directly
        import_cost_gbp = import_cost_physics
        seg_export_income_gbp = export_rev_physics
        sc_kwh = sc_kwh_physics

        # Missing-tariff fallback (§3.2 robustness).  Homes generated from a
        # fleet_distribution carry tariff_config=None (config.py), and
        # simulate_home then reports total_import_cost_gbp == 0 even though
        # energy was genuinely imported (home.py: import_costs are all-zero
        # when tariff_config is None).  Pricing real imported energy at £0
        # would silently understate the headline bill for the canonical
        # scenario (bristol-phase1.yaml has no tariff_config), so fall back to
        # the retail baseline rate and warn loudly rather than emit £0.
        if import_cost_gbp == 0.0 and import_kwh > 0.0:
            import_cost_gbp = import_kwh * retail_rate_pence / 100.0
            warnings.warn(
                f"Physics import cost is £0 but {import_kwh:.1f} kWh was "
                f"imported (no tariff configured on this home); pricing grid "
                f"imports at the retail baseline rate "
                f"({retail_rate_pence:.1f} p/kWh) so the bill reflects actual "
                f"imported energy.",
                UserWarning,
                stacklevel=2,
            )
    else:
        # Spreadsheet path: override the self-consumption fraction
        sc_kwh = override * gen_kwh

        # Recompute export_kwh from the override fraction
        # export = generation - self_consumption (energy balance at home boundary)
        override_export_kwh = max(gen_kwh - sc_kwh, 0.0)

        # Effective import / export unit rates from physics (fall back if zero)
        if import_kwh > 0.0:
            effective_import_rate_pence = (import_cost_physics / import_kwh) * 100.0
        else:
            effective_import_rate_pence = retail_rate_pence

        if export_kwh > 0.0:
            effective_export_rate_pence = (export_rev_physics / export_kwh) * 100.0
        else:
            effective_export_rate_pence = 0.0

        # Recompute import: demand minus self-consumed solar
        override_import_kwh = max(demand_kwh - sc_kwh, 0.0)
        import_cost_gbp = override_import_kwh * effective_import_rate_pence / 100.0
        seg_export_income_gbp = override_export_kwh * effective_export_rate_pence / 100.0

    # ---- VAT line (applies to import + standing) ----------------------------
    vat_gbp = vat_rate * (import_cost_gbp + standing_charge_gbp)
    gross_bill_gbp = (import_cost_gbp + standing_charge_gbp) * (1.0 + vat_rate)

    # ---- Net annual bill ----------------------------------------------------
    net_annual_bill_gbp = gross_bill_gbp - seg_export_income_gbp

    # ---- Self-consumption saving (VAT-inclusive at retail baseline) ----------
    self_consumption_saving_gbp = sc_kwh * retail_rate_pence * (1.0 + vat_rate) / 100.0

    # ---- Baseline bill (no solar / no battery, VAT-inclusive) ---------------
    baseline_bill_gbp = (
        demand_kwh * retail_rate_pence / 100.0 + standing_pence_per_day * _ANNUALISATION_DAYS / 100.0
    ) * (1.0 + vat_rate)

    # ---- Saving vs baseline -------------------------------------------------
    saving_vs_baseline_gbp = baseline_bill_gbp - net_annual_bill_gbp
    saving_pct = (
        (saving_vs_baseline_gbp / baseline_bill_gbp) * 100.0
        if baseline_bill_gbp != 0.0
        else 0.0
    )

    # ---- Self-consumption fraction ------------------------------------------
    self_consumption_fraction = sc_kwh / gen_kwh if gen_kwh > 0.0 else 0.0

    return BillBreakdown(
        standing_charge_gbp=float(standing_charge_gbp),
        import_cost_gbp=float(import_cost_gbp),
        vat_gbp=float(vat_gbp),
        gross_bill_gbp=float(gross_bill_gbp),
        seg_export_income_gbp=float(seg_export_income_gbp),
        self_consumption_saving_gbp=float(self_consumption_saving_gbp),
        baseline_bill_gbp=float(baseline_bill_gbp),
        net_annual_bill_gbp=float(net_annual_bill_gbp),
        saving_vs_baseline_gbp=float(saving_vs_baseline_gbp),
        saving_pct=float(saving_pct),
        self_consumption_fraction=float(self_consumption_fraction),
    )


# ---------------------------------------------------------------------------
# YearPoint — one year in a multi-year projection (§3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearPoint:
    """Energy and financial snapshot for one year in a multi-year projection.

    ``year`` is the age of the system in calendar years (0-based from
    installation).  SOH fractions are mean fleet values:
    ``pv_soh`` from :func:`pv.calculate_degradation_factor`; ``battery_soh``
    from :func:`battery.compute_soh` (1.0 when the fleet has no batteries).

    All energy values are in kWh (fleet totals for that simulated year).
    ``fleet_revenue_gbp`` is the sum of per-home
    (self_consumption_saving_gbp + seg_export_income_gbp).
    """

    year: int
    """Calendar age of the system in years (≥ 0)."""

    pv_soh: float
    """Mean PV state-of-health across the fleet (fraction, 0–1)."""

    battery_soh: float
    """Mean battery state-of-health across the fleet (fraction, 0–1;
    1.0 when the fleet has no batteries)."""

    fleet_self_consumption_kwh: float
    """Total self-consumed solar energy for the fleet that year (kWh, ≥ 0)."""

    fleet_export_kwh: float
    """Total grid export from the fleet that year (kWh, ≥ 0)."""

    fleet_import_kwh: float
    """Total grid import by the fleet that year (kWh, ≥ 0)."""

    fleet_revenue_gbp: float
    """Fleet total revenue (self-consumption saving + SEG export income) (£)."""

    def __post_init__(self) -> None:
        if self.year < 0:
            raise ValueError(f"year must be ≥ 0, got {self.year!r}")
        if not (0.0 <= self.pv_soh <= 1.0):
            raise ValueError(
                f"pv_soh must be in [0, 1], got {self.pv_soh!r}"
            )
        if not (0.0 <= self.battery_soh <= 1.0):
            raise ValueError(
                f"battery_soh must be in [0, 1], got {self.battery_soh!r}"
            )
        if self.fleet_self_consumption_kwh < 0.0:
            raise ValueError(
                f"fleet_self_consumption_kwh must be ≥ 0, got "
                f"{self.fleet_self_consumption_kwh!r}"
            )
        if self.fleet_export_kwh < 0.0:
            raise ValueError(
                f"fleet_export_kwh must be ≥ 0, got {self.fleet_export_kwh!r}"
            )
        if self.fleet_import_kwh < 0.0:
            raise ValueError(
                f"fleet_import_kwh must be ≥ 0, got {self.fleet_import_kwh!r}"
            )


# ---------------------------------------------------------------------------
# MultiYearCurve — full projection curve (§3.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiYearCurve:
    """Full multi-year projection curve for a fleet.

    ``points`` covers years 0 .. asset_life_years - 1 (one :class:`YearPoint`
    per year).  ``sampled_ages`` records the ages at which the driver actually
    ran simulations; the remaining years are filled by PCHIP interpolation.
    ``interp_error_estimate`` is the maximum interpolation deviation as a
    percentage of the annual-scale value at the time the adaptive loop
    converged (or was capped at ``MAX_NODES``).
    """

    points: tuple[YearPoint, ...]
    """Per-year snapshots (len == asset_life_years)."""

    sampled_ages: tuple[int, ...]
    """Ages at which full simulations were run (subset of 0..asset_life-1)."""

    interp_error_estimate: float
    """Max remaining PCHIP midpoint deviation (%), convergence invariant."""

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("points must be non-empty")
        if not self.sampled_ages:
            raise ValueError("sampled_ages must be non-empty")
        if self.interp_error_estimate < 0.0:
            raise ValueError(
                f"interp_error_estimate must be ≥ 0, got "
                f"{self.interp_error_estimate!r}"
            )


# ---------------------------------------------------------------------------
# Interpolation helpers — PCHIP primary, Fritsch–Carlson fallback (step-4/6)
# ---------------------------------------------------------------------------


def _monotone_hermite_interpolate(
    sampled_ages: List[int],
    sampled_values: List[float],
    all_years: int,
) -> List[float]:
    """Hand-rolled monotone cubic Hermite (Fritsch–Carlson) interpolant.

    No scipy dependency.  Used as fallback when scipy is unavailable.  Directly
    tested by ``TestMonotoneHermiteFallback`` so it is live, not dead code.

    Args:
        sampled_ages: Strictly ascending integer ages at which values are known.
        sampled_values: Corresponding values (same length as sampled_ages).
        all_years: Number of integer years (0 .. all_years-1) to interpolate.

    Returns:
        List of length ``all_years`` with one interpolated value per year.
    """
    n = len(sampled_ages)
    if n == 0:
        raise ValueError("sampled_ages must be non-empty")
    if n == 1:
        return [sampled_values[0]] * all_years

    xs = [float(a) for a in sampled_ages]
    ys = list(sampled_values)

    # Step 1: secant slopes
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

    # Step 2: initial tangent estimates (average of adjacent secants)
    m: List[float] = [0.0] * n
    m[0] = delta[0]
    m[-1] = delta[-1]
    for i in range(1, n - 1):
        m[i] = (delta[i - 1] + delta[i]) / 2.0

    # Step 3: Fritsch–Carlson monotonicity fix
    for i in range(n - 1):
        if delta[i] == 0.0:
            m[i] = 0.0
            m[i + 1] = 0.0
        else:
            alpha = m[i] / delta[i]
            beta = m[i + 1] / delta[i]
            r2 = alpha * alpha + beta * beta
            if r2 > 9.0:
                tau = 3.0 / (r2 ** 0.5)
                m[i] = tau * alpha * delta[i]
                m[i + 1] = tau * beta * delta[i]

    # Step 4: evaluate Hermite basis at each integer year in [0, all_years)
    result: List[float] = []
    seg_idx = 0  # current segment index
    for year in range(all_years):
        x = float(year)
        # Advance to the correct segment
        while seg_idx < n - 2 and x >= xs[seg_idx + 1]:
            seg_idx += 1
        # Clamp to valid range
        if x <= xs[0]:
            result.append(ys[0])
        elif x >= xs[-1]:
            result.append(ys[-1])
        else:
            x0, x1 = xs[seg_idx], xs[seg_idx + 1]
            y0, y1 = ys[seg_idx], ys[seg_idx + 1]
            m0, m1 = m[seg_idx], m[seg_idx + 1]
            dx = x1 - x0
            t = (x - x0) / dx
            h00 = 2 * t ** 3 - 3 * t ** 2 + 1
            h10 = t ** 3 - 2 * t ** 2 + t
            h01 = -2 * t ** 3 + 3 * t ** 2
            h11 = t ** 3 - t ** 2
            val = h00 * y0 + h10 * dx * m0 + h01 * y1 + h11 * dx * m1
            result.append(val)
    return result


def _interpolate_per_year(
    sampled_ages: List[int],
    sampled_values: List[float],
    all_years: int,
) -> List[float]:
    """Interpolate sampled (age, value) pairs to every year in 0..all_years-1.

    Uses :class:`scipy.interpolate.PchipInterpolator` when available;
    falls back to :func:`_monotone_hermite_interpolate` (Fritsch–Carlson) so
    no new runtime dependency is required.

    The degenerate single-node case returns a constant for all years.

    Args:
        sampled_ages: Strictly ascending integer ages at which values are known.
        sampled_values: Corresponding values (same length as sampled_ages).
        all_years: Number of integer years (0 .. all_years-1) to interpolate.

    Returns:
        List of length ``all_years`` with one interpolated value per year.
    """
    if len(sampled_ages) == 0:
        raise ValueError("sampled_ages must be non-empty")
    if len(sampled_ages) == 1:
        return [sampled_values[0]] * all_years

    try:
        from scipy.interpolate import PchipInterpolator  # type: ignore[import-untyped]

        import numpy as np  # type: ignore[import-untyped]

        xs = np.array(sampled_ages, dtype=float)
        ys = np.array(sampled_values, dtype=float)
        pchip = PchipInterpolator(xs, ys, extrapolate=False)
        all_x = np.arange(all_years, dtype=float)
        vals = pchip(all_x)
        # Extrapolation outside the node range → clip to boundary values
        vals = np.where(np.isnan(vals), np.interp(all_x, xs, ys), vals)
        return [float(v) for v in vals]
    except ImportError:
        return _monotone_hermite_interpolate(sampled_ages, sampled_values, all_years)


# ---------------------------------------------------------------------------
# bill_distribution
# ---------------------------------------------------------------------------


def bill_distribution(
    summaries: Sequence["SummaryStatistics"],
    finance: "FinanceConfig",
    simulation_days: int,
) -> BillDistribution:
    """Aggregate per-home bills into a fleet-level BillDistribution.

    Maps ``householder_bill`` over each home's SummaryStatistics, selects the
    median-net-bill home as representative, and computes min / mean / median /
    max via ``pd.Series`` (mirroring ``calculate_fleet_summary``).

    Args:
        summaries: Sequence of per-home SummaryStatistics.  Must contain at
            least one entry; an empty sequence raises ``ValueError``.
        finance: Common FinanceConfig for all homes.
        simulation_days: Actual simulation duration in days.

    Returns:
        A BillDistribution with representative and per-home statistics.

    Raises:
        ValueError: If ``summaries`` is empty.
    """
    if not summaries:
        raise ValueError("bill_distribution requires at least one summary")

    bills = [
        householder_bill(
            summary=s,
            annual_self_consumption_kwh=s.total_self_consumption_kwh,
            finance=finance,
            simulation_days=simulation_days,
        )
        for s in summaries
    ]
    net_bills = [b.net_annual_bill_gbp for b in bills]
    series = pd.Series(net_bills, dtype=float)

    median_val = float(series.median())
    # Representative: home whose net bill is closest to the median
    rep_idx = int((series - median_val).abs().idxmin())

    return BillDistribution(
        representative=bills[rep_idx],
        per_home_net_bill_gbp=tuple(net_bills),
        min_gbp=float(series.min()),
        mean_gbp=float(series.mean()),
        median_gbp=median_val,
        max_gbp=float(series.max()),
    )


# ---------------------------------------------------------------------------
# project_multi_year — forward-march driver (step-8 skeleton, extended later)
# ---------------------------------------------------------------------------

#: Maximum number of simulation nodes before the adaptive loop is capped.
MAX_NODES: int = 12


def _aged_homes(
    homes: "list[any]",  # list[HomeConfig]
    age: int,
) -> "list[any]":  # list[HomeConfig]
    """Return a list of HomeConfig with PV system_age_years set to ``age``.

    Battery SOH injection (step-10) and throughput accumulation (step-12) are
    wired in later; for the step-8 skeleton only PV age is set.
    """
    from solar_challenge.pv import PVConfig  # noqa: F401

    result = []
    for home in homes:
        new_pv = dataclasses.replace(home.pv_config, system_age_years=float(age))
        result.append(dataclasses.replace(home, pv_config=new_pv))
    return result


def project_multi_year(
    scenario: "ScenarioConfig",
    finance: "FinanceConfig",
    *,
    error_target_pct: float = 1.0,
    simulate: Optional[Callable[["FleetConfig", pd.Timestamp, pd.Timestamp], "FleetResults"]] = None,
) -> MultiYearCurve:
    """Project fleet energy and revenue over the full asset life.

    Performs a forward-march over the asset lifetime, simulating the fleet at
    a set of *sampled ages* (seeded at 0, asset_life//2, asset_life-1 and
    adaptively refined via bisection in step-16), then interpolating the
    resulting per-year curves with PCHIP.

    Args:
        scenario: ScenarioConfig with homes, period, and location.
        finance: FinanceConfig with ``asset_life_years`` and other parameters.
        error_target_pct: Target maximum PCHIP midpoint deviation (%) before
            adaptive bisection stops.
        simulate: Optional inject for testing.  Defaults to None → lazy import
            ``fleet.simulate_fleet``.

    Returns:
        :class:`MultiYearCurve` with one :class:`YearPoint` per year and
        metadata about the sampled ages and interpolation error.
    """
    # ---- Lazy import for the real simulate_fleet ----------------------------
    if simulate is None:
        from solar_challenge.fleet import simulate_fleet as _simulate_fleet
        simulate = _simulate_fleet  # type: ignore[assignment]

    # ---- Resolve homes (support both .homes list and single .home) ----------
    homes = list(scenario.homes) if scenario.homes else (
        [scenario.home] if scenario.home is not None else []
    )
    if not homes:
        raise ValueError("scenario must have at least one home")

    # ---- Derive timezone from scenario location (or first home) -------------
    tz: str
    if scenario.location is not None:
        tz = scenario.location.timezone
    else:
        tz = homes[0].location.timezone

    # ---- Derive start/end timestamps from scenario period -------------------
    start_ts = scenario.period.get_start_timestamp(tz)
    end_ts = scenario.period.get_end_timestamp(tz)

    asset_life = finance.asset_life_years

    # ---- Seed nodes ---------------------------------------------------------
    seed_ages: list[int] = sorted({0, asset_life // 2, asset_life - 1})

    # ---- Forward-march: simulate at each seed age, collect aggregates -------
    # Per-home cumulative throughput (kWh): tracks battery history across ages.
    # Initialised to 0 at age 0; accumulated trapezoidally (steps-10/12).
    n_homes = len(homes)
    cum_throughput: list[float] = [0.0] * n_homes

    # Mapping: age → (fleet_self, fleet_export, fleet_import, per_home_discharge)
    SimNode = tuple  # (float, float, float, list[float])

    sampled_data: dict[int, SimNode] = {}

    def _simulate_age(age: int) -> SimNode:
        """Simulate the fleet at a given age and return aggregate totals."""
        from solar_challenge.fleet import FleetConfig
        from solar_challenge.home import calculate_summary

        aged = _aged_homes(homes, age)
        fleet_config = FleetConfig(homes=aged, name=f"proj-age-{age}")
        fleet_results = simulate(fleet_config, start_ts, end_ts)  # type: ignore[misc]

        per_home_summaries = [
            calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
            for r in fleet_results.per_home_results
        ]

        fleet_sc = sum(s.total_self_consumption_kwh for s in per_home_summaries)
        fleet_exp = sum(s.total_grid_export_kwh for s in per_home_summaries)
        fleet_imp = sum(s.total_grid_import_kwh for s in per_home_summaries)
        per_home_discharge = [s.total_battery_discharge_kwh for s in per_home_summaries]

        return (fleet_sc, fleet_exp, fleet_imp, per_home_discharge)

    # March ascending
    prev_age: Optional[int] = None
    for age in seed_ages:
        node = _simulate_age(age)
        sampled_data[age] = node
        # Accumulate cumulative throughput toward next node (trapezoidal; step-12)
        if prev_age is not None:
            dt = age - prev_age
            prev_discharge = sampled_data[prev_age][3]
            for i in range(n_homes):
                cum_throughput[i] += 0.5 * (prev_discharge[i] + node[3][i]) * dt
        prev_age = age

    # ---- Interpolate per-year curves ----------------------------------------
    ages_sorted = sorted(sampled_data.keys())
    sc_vals = [sampled_data[a][0] for a in ages_sorted]
    exp_vals = [sampled_data[a][1] for a in ages_sorted]
    imp_vals = [sampled_data[a][2] for a in ages_sorted]

    sc_per_year = _interpolate_per_year(ages_sorted, sc_vals, asset_life)
    exp_per_year = _interpolate_per_year(ages_sorted, exp_vals, asset_life)
    imp_per_year = _interpolate_per_year(ages_sorted, imp_vals, asset_life)

    # ---- Assemble YearPoints (SOH + revenue are placeholder 1.0/0.0) --------
    points = tuple(
        YearPoint(
            year=y,
            pv_soh=1.0,              # wired in step-10
            battery_soh=1.0,          # wired in step-10
            fleet_self_consumption_kwh=max(0.0, sc_per_year[y]),
            fleet_export_kwh=max(0.0, exp_per_year[y]),
            fleet_import_kwh=max(0.0, imp_per_year[y]),
            fleet_revenue_gbp=0.0,    # wired in step-14
        )
        for y in range(asset_life)
    )

    return MultiYearCurve(
        points=points,
        sampled_ages=tuple(ages_sorted),
        interp_error_estimate=0.0,   # wired in step-16
    )
