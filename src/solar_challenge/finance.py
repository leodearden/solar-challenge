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
from typing import TYPE_CHECKING, Any, Callable, List, NamedTuple, Optional, Sequence

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

    Energy fields are kWh totals for the *simulation period* as returned by
    :func:`home.calculate_summary` — **not** necessarily a full calendar year.
    When ``scenario.period`` covers ≥ 360 days these values approximate annual
    totals; for shorter periods they are sub-annual.  By contrast,
    ``fleet_revenue_gbp`` is annualised by :func:`householder_bill` (which
    scales short periods to 365 days), so direct £/kWh derivations from a
    sub-year :class:`YearPoint` will yield inconsistent results.  Callers
    should ensure the scenario period covers approximately one year for
    consistent energy and revenue units.

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
    """Max remaining PCHIP midpoint deviation (%) across all driven metrics
    (fleet_self_consumption_kwh, fleet_export_kwh, fleet_import_kwh,
    fleet_revenue_gbp), convergence invariant of the adaptive loop."""

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
# ProjectEconomics — project-level economics result (§3.1, η)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectEconomics:
    """Project-level financial appraisal results for a community PV/battery fleet.

    Produced by :func:`project_economics` from a :class:`MultiYearCurve` and a
    :class:`~solar_challenge.config.FinanceConfig`.  All monetary values are in
    nominal GBP (£).

    Attributes:
        total_capex_gbp: Total capital expenditure across the fleet (£).
            3-term build-up: Σ_home(pv_kwp × pv_cost + roof_fit + battery_kwh
            × battery_cost).  No inverter term (that is task #49's scope).
        grant_gbp: Total grant received by the project (£, passthrough from
            FinanceConfig).
        equity_gbp: Equity portion of the financed amount (£):
            (capex − grant) × equity_fraction.
        debt_gbp: Debt portion of the financed amount (£):
            (capex − grant) × (1 − equity_fraction).
        annual_debt_service_gbp: Level annuity payment on debt over
            loan_term_years at loan_rate (£/year).
        per_year_surplus_gbp: Per-year fleet surplus (£), one entry per
            asset_life year (0-based).  surplus_y = revenue_y − fleet_opex
            − debt_service (y < loan_term) or revenue_y − fleet_opex
            (y ≥ loan_term).
        min_dscr: Minimum Debt Service Coverage Ratio over loan years only:
            min_y<loan_term ((revenue_y − fleet_opex) / annual_debt_service).
            float('inf') when annual_debt_service_gbp == 0.
        equity_irr: Internal rate of return on equity (fraction), computed via
            NPV bisection on cashflow [−equity, surplus_0 … surplus_{N-1}].
            float('nan') when equity_gbp == 0 or cashflow has no sign change.
        payback_years: First 1-based year where cumulative equity cashflow
            (−equity + Σ surplus) ≥ 0 (float), or None if never within the
            asset life.
        net_surplus_per_home_per_year_gbp: Mean per-year surplus divided by
            the number of homes (£/home/year).
    """

    total_capex_gbp: float
    """Total capital expenditure across the fleet (£)."""

    grant_gbp: float
    """Grant received by the project (£)."""

    equity_gbp: float
    """Equity portion of project financing (£)."""

    debt_gbp: float
    """Debt portion of project financing (£)."""

    annual_debt_service_gbp: float
    """Annual level annuity debt service payment (£/year)."""

    per_year_surplus_gbp: tuple[float, ...]
    """Per-year fleet surplus after opex and debt service (£), len == asset_life_years."""

    min_dscr: float
    """Minimum DSCR over loan years (float('inf') when debt-free)."""

    equity_irr: float
    """Equity IRR as a fraction (float('nan') when undefined)."""

    payback_years: Optional[float]
    """First year cumulative equity cashflow ≥ 0 (1-based), or None."""

    net_surplus_per_home_per_year_gbp: float
    """Mean per-year surplus per home (£/home/year)."""

    def __post_init__(self) -> None:
        if not self.per_year_surplus_gbp:
            raise ValueError(
                "per_year_surplus_gbp must be non-empty; got empty tuple"
            )
        if self.payback_years is not None and self.payback_years < 0.0:
            raise ValueError(
                f"payback_years must be None or ≥ 0, got {self.payback_years!r}"
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

        import numpy as np

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


class _NodeData(NamedTuple):
    """Aggregates from one simulated fleet age in the forward-march.

    Collected once per :func:`_simulate_age` call and stored in ``sampled_data``
    (keyed by age).  Named fields replace magic-index access throughout the driver.
    """

    fleet_sc: float
    """Fleet total self-consumed solar for the simulation period (kWh)."""

    fleet_exp: float
    """Fleet total grid export for the simulation period (kWh)."""

    fleet_imp: float
    """Fleet total grid import for the simulation period (kWh)."""

    per_home_discharge: List[float]
    """Per-home battery discharge for the simulation period (kWh)."""

    mean_pv_soh: float
    """Mean PV state-of-health across the fleet (fraction, 0–1)."""

    mean_battery_soh: float
    """Mean battery state-of-health across the fleet (fraction, 0–1)."""

    fleet_revenue: float
    """Fleet total (self-consumption saving + SEG export income) (£, annualised)."""


def _aged_homes(
    homes: "list[Any]",  # list[HomeConfig]
    age: int,
    cum_throughput: Optional[List[float]] = None,
) -> "list[Any]":  # list[HomeConfig]
    """Return HomeConfig list with PV system_age_years and battery SOH set to ``age``.

    For each home the PV config's ``system_age_years`` is updated to ``age``.
    When ``cum_throughput`` is provided (a per-home list of kWh accumulated
    since installation), battery SOH at that age is computed via
    :func:`battery.compute_soh` and injected into the battery config via
    ``dataclasses.replace(battery_config, soh=soh_i)`` so :class:`Battery`
    uses it directly at construction time (β seam).

    Args:
        homes: Original fleet home configs.
        age: System age in calendar years.
        cum_throughput: Per-home cumulative battery throughput in kWh (0.0 if
            no history yet or if the home has no battery).

    Returns:
        New list of HomeConfig with aged PV and (optionally) aged battery.
    """
    from solar_challenge.battery import compute_soh

    if cum_throughput is None:
        cum_throughput = [0.0] * len(homes)

    result = []
    for i, home in enumerate(homes):
        # Age the PV config
        new_pv = dataclasses.replace(home.pv_config, system_age_years=float(age))

        # Age the battery config (inject SOH via dataclasses.replace if present)
        new_bc = home.battery_config
        if new_bc is not None:
            usable = new_bc.capacity_kwh * (new_bc.max_soc_fraction - new_bc.min_soc_fraction)
            soh_i = compute_soh(
                system_age_years=float(age),
                cumulative_throughput_kwh=cum_throughput[i],
                usable_capacity_kwh=usable,
                params=new_bc,
            )
            new_bc = dataclasses.replace(new_bc, soh=soh_i)

        result.append(dataclasses.replace(home, pv_config=new_pv, battery_config=new_bc))
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

    Note:
        For consistent units between energy fields and ``fleet_revenue_gbp``
        in the returned :class:`YearPoint` objects, ``scenario.period`` should
        cover approximately one full year (≥ 360 days).  For shorter periods
        the energy fields are sub-annual totals while ``fleet_revenue_gbp`` is
        annualised by :func:`householder_bill` — direct £/kWh derivations from
        such a curve will yield inconsistent results.

    Returns:
        :class:`MultiYearCurve` with one :class:`YearPoint` per year and
        metadata about the sampled ages and interpolation error.
    """
    # ---- Lazy import for the real simulate_fleet ----------------------------
    if simulate is None:
        from solar_challenge.fleet import simulate_fleet as _simulate_fleet
        simulate = _simulate_fleet

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
    # Initialised to 0 at age 0; accumulated trapezoidally (step-12).
    n_homes = len(homes)
    cum_throughput: list[float] = [0.0] * n_homes

    sampled_data: dict[int, _NodeData] = {}

    def _simulate_age(
        age: int,
        cum_tp: list[float],
    ) -> _NodeData:
        """Simulate the fleet at a given age, compute SOH, and return aggregates."""
        from solar_challenge.battery import compute_soh
        from solar_challenge.fleet import FleetConfig
        from solar_challenge.home import calculate_summary
        from solar_challenge.pv import calculate_degradation_factor

        aged = _aged_homes(homes, age, cum_tp)
        fleet_config = FleetConfig(homes=aged, name=f"proj-age-{age}")
        fleet_results = simulate(fleet_config, start_ts, end_ts)

        per_home_summaries = [
            calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
            for r in fleet_results.per_home_results
        ]

        fleet_sc = sum(s.total_self_consumption_kwh for s in per_home_summaries)
        fleet_exp = sum(s.total_grid_export_kwh for s in per_home_summaries)
        fleet_imp = sum(s.total_grid_import_kwh for s in per_home_summaries)
        per_home_discharge = [s.total_battery_discharge_kwh for s in per_home_summaries]

        # Fleet revenue: Σ_home (self_consumption_saving_gbp + seg_export_income_gbp)
        # Reuses householder_bill so self_consumption_override is automatically honoured.
        bills = [
            householder_bill(
                s,
                annual_self_consumption_kwh=s.total_self_consumption_kwh,
                finance=finance,
                simulation_days=s.simulation_days,
            )
            for s in per_home_summaries
        ]
        fleet_revenue = sum(
            b.self_consumption_saving_gbp + b.seg_export_income_gbp for b in bills
        )

        # PV SOH: mean of calculate_degradation_factor over all homes
        pv_sohs = [
            calculate_degradation_factor(float(age), h.pv_config.degradation_rate_per_year)
            for h in homes
        ]
        mean_pv_soh = sum(pv_sohs) / len(pv_sohs) if pv_sohs else 1.0

        # Battery SOH: mean of per-home compute_soh (1.0 if no batteries)
        battery_sohs: list[float] = []
        for i, home in enumerate(homes):
            bc = home.battery_config
            if bc is not None:
                usable = bc.capacity_kwh * (bc.max_soc_fraction - bc.min_soc_fraction)
                soh_i = compute_soh(
                    system_age_years=float(age),
                    cumulative_throughput_kwh=cum_tp[i],
                    usable_capacity_kwh=usable,
                    params=bc,
                )
                battery_sohs.append(soh_i)
        mean_battery_soh = sum(battery_sohs) / len(battery_sohs) if battery_sohs else 1.0

        return _NodeData(
            fleet_sc=fleet_sc,
            fleet_exp=fleet_exp,
            fleet_imp=fleet_imp,
            per_home_discharge=per_home_discharge,
            mean_pv_soh=mean_pv_soh,
            mean_battery_soh=mean_battery_soh,
            fleet_revenue=fleet_revenue,
        )

    # ---- Seed forward-march (snapshot cum_tp BEFORE each simulation) ---------
    # cum_tp_snapshot[age] = per-home throughput used as input for that age's sim.
    cum_tp_snapshot: dict[int, List[float]] = {}
    prev_age: Optional[int] = None
    for age in seed_ages:
        cum_tp_snapshot[age] = list(cum_throughput)      # snapshot before sim
        node = _simulate_age(age, list(cum_throughput))
        sampled_data[age] = node
        # Accumulate cumulative throughput toward next node (trapezoidal; step-12)
        if prev_age is not None:
            dt = age - prev_age
            prev_discharge = sampled_data[prev_age].per_home_discharge
            for i in range(n_homes):
                cum_throughput[i] += 0.5 * (prev_discharge[i] + node.per_home_discharge[i]) * dt
        prev_age = age

    # ---- Adaptive bisection (H4, §3.3) --------------------------------------
    # Deviation is the max across all driven energy + revenue metrics, normalised
    # to percentages by each metric's age-0 value.  This ensures interp_error_estimate
    # bounds ALL interpolated curves (self-consumption, export, import, revenue),
    # not just self-consumption.
    annual_scale_sc: float = max(sampled_data[0].fleet_sc, 1e-9)
    annual_scale_exp: float = max(sampled_data[0].fleet_exp, 1e-9)
    annual_scale_imp: float = max(sampled_data[0].fleet_imp, 1e-9)
    annual_scale_rev: float = max(sampled_data[0].fleet_revenue, 1e-9)
    max_deviation: float = 0.0
    capped: bool = False

    # Cache trial node results by midpoint age to avoid re-simulating the same
    # midpoint on subsequent bisection passes.  The cache is keyed by age: a given
    # mid always has the same lower boundary (a_k) and therefore the same forward-
    # Euler cum_tp estimate throughout the loop, so the result is stable.
    _trial_cache: dict[int, tuple[_NodeData, List[float]]] = {}

    while True:
        current_ages = sorted(sampled_data.keys())

        # Build PCHIP over the current node set for all driven metrics
        sc_vals_now = [sampled_data[a].fleet_sc for a in current_ages]
        exp_vals_now = [sampled_data[a].fleet_exp for a in current_ages]
        imp_vals_now = [sampled_data[a].fleet_imp for a in current_ages]
        rev_vals_now = [sampled_data[a].fleet_revenue for a in current_ages]

        sc_interp_now = _interpolate_per_year(current_ages, sc_vals_now, asset_life)
        exp_interp_now = _interpolate_per_year(current_ages, exp_vals_now, asset_life)
        imp_interp_now = _interpolate_per_year(current_ages, imp_vals_now, asset_life)
        rev_interp_now = _interpolate_per_year(current_ages, rev_vals_now, asset_life)

        # Scan adjacent intervals for bisectable midpoints above the error target
        to_bisect: List[tuple[int, _NodeData, List[float]]] = []
        current_max_dev: float = 0.0

        for i_interval in range(len(current_ages) - 1):
            a_k = current_ages[i_interval]
            a_k1 = current_ages[i_interval + 1]
            if a_k1 - a_k <= 1:
                continue  # width-1 interval — finest resolution
            mid = (a_k + a_k1) // 2
            if mid in sampled_data:
                continue  # already a simulation node

            # Retrieve or compute the trial node at mid (memoised by age to avoid
            # re-simulating on subsequent passes when intervals haven't changed).
            if mid not in _trial_cache:
                cum_tp_for_mid = list(cum_tp_snapshot[a_k])
                discharge_at_k: List[float] = sampled_data[a_k].per_home_discharge
                for j in range(n_homes):
                    cum_tp_for_mid[j] += discharge_at_k[j] * float(mid - a_k)
                trial_node = _simulate_age(mid, cum_tp_for_mid)
                _trial_cache[mid] = (trial_node, list(cum_tp_for_mid))
            else:
                trial_node, cum_tp_for_mid = _trial_cache[mid]

            # Max PCHIP deviation across all driven metrics (percentage)
            dev = max(
                abs(sc_interp_now[mid] - trial_node.fleet_sc) / annual_scale_sc * 100.0,
                abs(exp_interp_now[mid] - trial_node.fleet_exp) / annual_scale_exp * 100.0,
                abs(imp_interp_now[mid] - trial_node.fleet_imp) / annual_scale_imp * 100.0,
                abs(rev_interp_now[mid] - trial_node.fleet_revenue) / annual_scale_rev * 100.0,
            )
            current_max_dev = max(current_max_dev, dev)

            if dev > error_target_pct:
                to_bisect.append((mid, trial_node, cum_tp_for_mid))

        # Always update the convergence invariant with the latest check
        max_deviation = current_max_dev

        if not to_bisect:
            break  # All intervals within target — converged

        if len(sampled_data) >= MAX_NODES:
            # Cannot add any more nodes; surface the remaining error
            capped = True
            break

        # Add bisection nodes (stop if we hit the cap mid-iteration)
        for mid_age, trial_node, cum_tp_for_mid in to_bisect:
            if len(sampled_data) >= MAX_NODES:
                capped = True
                break
            sampled_data[mid_age] = trial_node
            cum_tp_snapshot[mid_age] = list(cum_tp_for_mid)

        if capped:
            break
        # Loop: rebuild PCHIP with new nodes → re-check all intervals

    if capped:
        warnings.warn(
            f"project_multi_year: adaptive bisection reached MAX_NODES ({MAX_NODES}); "
            f"interp_error_estimate surfaced at {max_deviation:.3f}% "
            f"(target was {error_target_pct}%).",
            UserWarning,
            stacklevel=2,
        )

    # ---- Interpolate per-year curves with the converged node set ------------
    ages_sorted = sorted(sampled_data.keys())
    sc_vals = [sampled_data[a].fleet_sc for a in ages_sorted]
    exp_vals = [sampled_data[a].fleet_exp for a in ages_sorted]
    imp_vals = [sampled_data[a].fleet_imp for a in ages_sorted]
    pv_soh_vals = [sampled_data[a].mean_pv_soh for a in ages_sorted]
    batt_soh_vals = [sampled_data[a].mean_battery_soh for a in ages_sorted]
    rev_vals = [sampled_data[a].fleet_revenue for a in ages_sorted]

    sc_per_year = _interpolate_per_year(ages_sorted, sc_vals, asset_life)
    exp_per_year = _interpolate_per_year(ages_sorted, exp_vals, asset_life)
    imp_per_year = _interpolate_per_year(ages_sorted, imp_vals, asset_life)
    pv_soh_per_year = _interpolate_per_year(ages_sorted, pv_soh_vals, asset_life)
    batt_soh_per_year = _interpolate_per_year(ages_sorted, batt_soh_vals, asset_life)
    rev_per_year = _interpolate_per_year(ages_sorted, rev_vals, asset_life)

    # ---- Assemble YearPoints ------------------------------------------------
    points = tuple(
        YearPoint(
            year=y,
            pv_soh=max(0.0, min(1.0, pv_soh_per_year[y])),
            battery_soh=max(0.0, min(1.0, batt_soh_per_year[y])),
            fleet_self_consumption_kwh=max(0.0, sc_per_year[y]),
            fleet_export_kwh=max(0.0, exp_per_year[y]),
            fleet_import_kwh=max(0.0, imp_per_year[y]),
            fleet_revenue_gbp=max(0.0, rev_per_year[y]),
        )
        for y in range(asset_life)
    )

    return MultiYearCurve(
        points=points,
        sampled_ages=tuple(ages_sorted),
        interp_error_estimate=max_deviation,
    )


# ---------------------------------------------------------------------------
# project_economics — project-level financial appraisal (η)
# ---------------------------------------------------------------------------


def _annuity_payment(principal: float, rate: float, n_years: int) -> float:
    """Compute the level annual payment on a loan (closed-form annuity).

    Args:
        principal: Loan principal (£).
        rate: Annual interest rate as a fraction (e.g., 0.07 for 7%).
        n_years: Loan term in years (must be > 0).

    Returns:
        Annual level payment (£).  When rate == 0 returns principal / n_years.
    """
    if principal == 0.0:
        return 0.0
    if rate == 0.0:
        return principal / n_years
    return principal * rate / (1.0 - (1.0 + rate) ** (-n_years))


def _npv(rate: float, cashflows: List[float]) -> float:
    """Compute NPV of cashflows discounted at *rate*.

    cashflows[0] is the t=0 outflow (negative equity), cashflows[1..N] are
    inflows at t=1..N.

    Args:
        rate: Discount rate as a fraction.
        cashflows: List of cash flows starting at t=0.

    Returns:
        Net present value (£).
    """
    total = 0.0
    for t, cf in enumerate(cashflows):
        total += cf / (1.0 + rate) ** t
    return total


def _irr_bisection(cashflows: List[float]) -> float:
    """Internal rate of return via NPV bisection root-find.

    Finds *r* such that NPV(r, cashflows) ≈ 0.  Returns float('nan') when
    there is no sign change (non-conventional or never-profitable cashflow) or
    when cashflows[0] == 0 (no equity invested).

    Args:
        cashflows: Cash flow list; cashflows[0] is typically −equity (negative).

    Returns:
        IRR as a fraction, or float('nan') if undefined.
    """
    if not cashflows or cashflows[0] == 0.0:
        return float("nan")

    # Bracket: search within [-50%, +500%] — wide enough for any realistic project
    lo, hi = -0.5, 5.0
    npv_lo = _npv(lo, cashflows)
    npv_hi = _npv(hi, cashflows)

    if npv_lo * npv_hi > 0.0:
        # No sign change in bracket → IRR undefined
        return float("nan")

    # Bisect to tolerance
    tol = 1e-10
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        npv_mid = _npv(mid, cashflows)
        if abs(npv_mid) < tol or (hi - lo) < tol:
            return mid
        if npv_lo * npv_mid <= 0.0:
            hi = mid
            npv_hi = npv_mid
        else:
            lo = mid
            npv_lo = npv_mid

    return 0.5 * (lo + hi)


def project_economics(
    curve: MultiYearCurve,
    scenario: "ScenarioConfig",
    finance: "FinanceConfig",
) -> ProjectEconomics:
    """Compute project-level financial appraisal from a multi-year revenue curve.

    Pure and deterministic: given the same curve, scenario, and finance
    parameters, always returns the same :class:`ProjectEconomics`.

    Algorithm:
    1. Resolve homes; raise ValueError if empty.
    2. Compute total_capex_gbp via the 3-term build-up:
       Σ_home(pv_kwp × pv_cost + roof_fit + battery_kwh × battery_cost).
       No inverter term (#49's scope).
    3. financed = max(capex − grant, 0); equity = financed × equity_fraction;
       debt = financed × (1 − equity_fraction).
    4. annual_debt_service via level annuity (_annuity_payment).
    5. fleet_opex = opex_per_home × n_homes.
    6. per_year_surplus[y] = revenue[y] − fleet_opex − debt_service (y < loan_term)
       or revenue[y] − fleet_opex (y ≥ loan_term).
    7. min_dscr = min over loan years of (revenue_y − opex) / debt_service;
       float('inf') when debt_service == 0.
    8. equity_irr via NPV bisection on [−equity, surplus_0 … surplus_{N-1}].
    9. payback_years = first 1-based year cumulative(−equity + Σ surplus) ≥ 0,
       or None.
    10. net_surplus_per_home_per_year_gbp = mean(surplus) / n_homes.

    Args:
        curve: MultiYearCurve produced by project_multi_year.
        scenario: ScenarioConfig with homes list (or single home) and finance.
        finance: FinanceConfig with cost and finance parameters.

    Returns:
        Fully populated :class:`ProjectEconomics`.

    Raises:
        ValueError: When scenario has no homes.
    """
    # 1. Resolve homes
    homes = list(scenario.homes) if scenario.homes else (
        [scenario.home] if scenario.home is not None else []
    )
    if not homes:
        raise ValueError("scenario must have at least one home")
    n_homes = len(homes)

    # 2. Capex: 3-term build-up (no inverter)
    total_capex_gbp = 0.0
    for home in homes:
        pv_kwp = home.pv_config.capacity_kw
        batt_kwh = (
            home.battery_config.capacity_kwh
            if home.battery_config is not None
            else 0.0
        )
        total_capex_gbp += (
            pv_kwp * finance.pv_cost_per_kwp_gbp
            + finance.roof_fit_cost_gbp
            + batt_kwh * finance.battery_cost_per_kwh_gbp
        )

    # 3. Grant / equity / debt split
    financed = max(total_capex_gbp - finance.grant_gbp, 0.0)
    equity_gbp = financed * finance.equity_fraction
    debt_gbp = financed * (1.0 - finance.equity_fraction)

    # 4. Annual debt service
    annual_debt_service_gbp = _annuity_payment(
        debt_gbp, finance.loan_rate, finance.loan_term_years
    )

    # 5. Fleet opex
    fleet_opex = finance.opex_per_home_per_year_gbp * n_homes

    # 6. Per-year surplus
    asset_life = finance.asset_life_years
    loan_term = finance.loan_term_years
    per_year_surplus: List[float] = []
    for y in range(asset_life):
        revenue_y = curve.points[y].fleet_revenue_gbp
        debt_y = annual_debt_service_gbp if y < loan_term else 0.0
        per_year_surplus.append(revenue_y - fleet_opex - debt_y)

    # 7. min_dscr over loan years
    if annual_debt_service_gbp == 0.0:
        min_dscr = float("inf")
    else:
        dscr_values = [
            (curve.points[y].fleet_revenue_gbp - fleet_opex) / annual_debt_service_gbp
            for y in range(loan_term)
        ]
        min_dscr = min(dscr_values)

    # 8. Equity IRR
    cashflows: List[float] = [-equity_gbp] + per_year_surplus
    equity_irr = _irr_bisection(cashflows)

    # 9. Payback years
    payback_years: Optional[float] = None
    cumulative = -equity_gbp
    for y, surplus in enumerate(per_year_surplus, start=1):
        cumulative += surplus
        if cumulative >= 0.0:
            payback_years = float(y)
            break

    # 10. Net surplus per home per year
    mean_surplus = sum(per_year_surplus) / len(per_year_surplus)
    net_surplus_per_home_per_year_gbp = mean_surplus / n_homes

    return ProjectEconomics(
        total_capex_gbp=total_capex_gbp,
        grant_gbp=finance.grant_gbp,
        equity_gbp=equity_gbp,
        debt_gbp=debt_gbp,
        annual_debt_service_gbp=annual_debt_service_gbp,
        per_year_surplus_gbp=tuple(per_year_surplus),
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        net_surplus_per_home_per_year_gbp=net_surplus_per_home_per_year_gbp,
    )
