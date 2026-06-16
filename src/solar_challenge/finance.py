# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Per-householder bill computation and fleet bill distribution (δ surface).

Provides:
  - ``BillBreakdown`` — frozen dataclass with 11 financial line items.
  - ``BillDistribution`` — frozen dataclass with fleet-level bill statistics.
  - ``householder_bill`` — pure function mapping simulation outputs to a bill.
  - ``bill_distribution`` — aggregates per-home bills into a BillDistribution.

All monetary values are in GBP (£); energy in kWh.  The module is fully
deterministic and has no side-effects: suitable for use in parallel fleet runs.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

import pandas as pd

if TYPE_CHECKING:
    from solar_challenge.config import FinanceConfig
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
