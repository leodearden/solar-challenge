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
    from solar_challenge.config import ScenarioConfig
    from solar_challenge.fleet import FleetConfig, FleetResults
    from solar_challenge.gridservices import GridServicesEventsConfig
    from solar_challenge.home import SummaryStatistics


# ---------------------------------------------------------------------------
# FinanceConfig — relocated from config.py (T2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinanceConfig:
    """Financial parameters for community PV/battery project appraisal.

    Holds investor-spreadsheet defaults (§3.1 of the financial-layer PRD)
    used to compute project NPV, payback period, and per-home savings.
    All monetary values are in nominal GBP or pence; rates are fractional.

    Attributes:
        standing_charge_pence_per_day: Retail grid standing charge (required).
        vat_rate: VAT fraction applied to retail electricity (default 0.05).
        retail_baseline_rate_pence_per_kwh: Grid import unit rate before project
            (default 23.0 p/kWh).
        self_consumption_override: Optional fixed self-consumption fraction
            (0, 1]; if None the simulator uses the modelled value.
        pv_cost_per_kwp_gbp: PV hardware + install cost per kWp (default 1000.0).
        roof_fit_cost_gbp: Fixed per-home roof-fitting cost (default 1000.0).
        battery_cost_per_kwh_gbp: Battery hardware cost per kWh (default 250.0).
        inverter_cost_per_kw_gbp: Inverter capex cost per kW of effective (AC) inverter
            capacity (default 0.0; 0 permitted).
        grant_gbp: Total grant received by the project (default 250000.0; 0 allowed).
        equity_fraction: Fraction of project cost financed by equity (default 0.75).
        loan_term_years: Loan repayment term in years (default 15).
        loan_rate: Annual loan interest rate as a fraction (default 0.07).
        opex_per_home_per_year_gbp: Annual operating cost per home (default 131.0).
        asset_life_years: Useful life of the asset in years (default 25).
        own_use_rate_pence_per_kwh: CBS transfer price for self-consumed CBS-owned solar
            (default 15.0 p/kWh; 0 permitted).
        retained_cash_floor_per_home_per_year_gbp: Board-set minimum retained CBS
            surplus per home per year in GBP (default 27.0; 0 permitted).
        grid_services_income_per_kw_per_year_gbp: Exogenous DFS/DNO grid-services income
            per kW of installed battery discharge power per year, net of aggregator share
            (default 0.0; W1 cross-PRD seam — W1-delta fills the value cross-batch).
        grid_services_model: Grid-services pricing model selector.  ``"flat"`` uses
            the legacy flat per-kW rate (``grid_services_income_per_kw_per_year_gbp``);
            ``"capacity_at_events"`` uses the structured events-based model configured
            via ``grid_services_events``.  Default ``"flat"`` leaves all existing
            behaviour bit-unchanged.
        grid_services_events: Optional :class:`~solar_challenge.gridservices.GridServicesEventsConfig`
            used when ``grid_services_model == "capacity_at_events"``.  May be ``None``
            even for that model (α only validates the selector field; γ/δ consume it).
    """

    standing_charge_pence_per_day: float
    vat_rate: float = 0.05
    retail_baseline_rate_pence_per_kwh: float = 23.0
    self_consumption_override: Optional[float] = None
    pv_cost_per_kwp_gbp: float = 1000.0
    roof_fit_cost_gbp: float = 1000.0
    battery_cost_per_kwh_gbp: float = 250.0
    inverter_cost_per_kw_gbp: float = 0.0
    grant_gbp: float = 250000.0
    equity_fraction: float = 0.75
    loan_term_years: int = 15
    loan_rate: float = 0.07
    opex_per_home_per_year_gbp: float = 131.0
    asset_life_years: int = 25
    own_use_rate_pence_per_kwh: float = 15.0
    retained_cash_floor_per_home_per_year_gbp: float = 27.0
    grid_services_income_per_kw_per_year_gbp: float = 0.0
    grid_services_model: str = "flat"
    grid_services_events: Optional["GridServicesEventsConfig"] = None

    def __post_init__(self) -> None:
        """Validate financial parameters, raising ConfigurationError on violation."""
        from solar_challenge.config import ConfigurationError  # lazy: avoids import cycle; sys.modules cache makes repeat lookups O(1)

        if not (0.0 <= self.vat_rate <= 1.0):
            raise ConfigurationError(
                f"vat_rate must be in [0, 1], got {self.vat_rate}"
            )
        if not (0.0 <= self.equity_fraction <= 1.0):
            raise ConfigurationError(
                f"equity_fraction must be in [0, 1], got {self.equity_fraction}"
            )
        if self.self_consumption_override is not None:
            if not (0.0 < self.self_consumption_override <= 1.0):
                raise ConfigurationError(
                    "self_consumption_override must be in (0, 1] when set, "
                    f"got {self.self_consumption_override}"
                )
        if self.loan_term_years <= 0:
            raise ConfigurationError(
                f"loan_term_years must be > 0, got {self.loan_term_years}"
            )
        if self.loan_rate < 0.0:
            raise ConfigurationError(
                f"loan_rate must be >= 0, got {self.loan_rate}"
            )
        if self.asset_life_years < self.loan_term_years:
            raise ConfigurationError(
                f"asset_life_years ({self.asset_life_years}) must be >= "
                f"loan_term_years ({self.loan_term_years})"
            )
        # Cost/rate fields must be strictly positive
        _positive_fields = {
            "standing_charge_pence_per_day": self.standing_charge_pence_per_day,
            "retail_baseline_rate_pence_per_kwh": self.retail_baseline_rate_pence_per_kwh,
            "pv_cost_per_kwp_gbp": self.pv_cost_per_kwp_gbp,
            "roof_fit_cost_gbp": self.roof_fit_cost_gbp,
            "battery_cost_per_kwh_gbp": self.battery_cost_per_kwh_gbp,
            "opex_per_home_per_year_gbp": self.opex_per_home_per_year_gbp,
        }
        for field_name, value in _positive_fields.items():
            if value <= 0.0:
                raise ConfigurationError(
                    f"{field_name} must be > 0, got {value}"
                )
        # Grant may be zero but not negative
        if self.grant_gbp < 0.0:
            raise ConfigurationError(
                f"grant_gbp must be >= 0, got {self.grant_gbp}"
            )
        # Inverter cost may be zero (opt-in default) but not negative
        if self.inverter_cost_per_kw_gbp < 0.0:
            raise ConfigurationError(
                f"inverter_cost_per_kw_gbp must be >= 0, got {self.inverter_cost_per_kw_gbp}"
            )
        # Cost-recovery fields: zero allowed, negative rejected
        if self.own_use_rate_pence_per_kwh < 0.0:
            raise ConfigurationError(
                f"own_use_rate_pence_per_kwh must be >= 0, got {self.own_use_rate_pence_per_kwh}"
            )
        if self.retained_cash_floor_per_home_per_year_gbp < 0.0:
            raise ConfigurationError(
                "retained_cash_floor_per_home_per_year_gbp must be >= 0, "
                f"got {self.retained_cash_floor_per_home_per_year_gbp}"
            )
        if self.grid_services_income_per_kw_per_year_gbp < 0.0:
            raise ConfigurationError(
                "grid_services_income_per_kw_per_year_gbp must be >= 0, "
                f"got {self.grid_services_income_per_kw_per_year_gbp}"
            )
        _VALID_GS_MODELS = frozenset({"flat", "capacity_at_events"})
        if self.grid_services_model not in _VALID_GS_MODELS:
            raise ConfigurationError(
                f"grid_services_model must be one of {sorted(_VALID_GS_MODELS)}, "
                f"got '{self.grid_services_model}'"
            )


# ---------------------------------------------------------------------------
# BillBreakdown — 11 required fields per §3.1
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BillBreakdown:
    """Per-householder annual cost-recovery outlay broken into component line items (CR3).

    The CBS owns the PV/battery assets and the export MPAN.  The householder
    pays the CBS an own-use rate for self-consumed solar, pays retail for grid
    import, and pays the standing charge.  No SEG credit flows to the householder.

    Definitional invariants (§3.1):
      own_use_payment_gbp      = own_use_rate_pence_per_kwh × self_consumed_kwh / 100
      vat_gbp                  = vat_rate × (import_cost_gbp + standing_charge_gbp
                                             + own_use_payment_gbp)
      total_outlay_gbp         = (import_cost_gbp + standing_charge_gbp
                                  + own_use_payment_gbp) × (1 + vat_rate)
      self_consumption_saving_gbp = self_consumed_kwh × (retail − own_use_rate)
                                    × (1 + vat_rate) / 100
      saving_vs_baseline_gbp   = baseline_bill_gbp − total_outlay_gbp

    All monetary values are in GBP (£).  The H3 board identity holds when
    import is retail-priced and import_kwh == demand − sc:
      saving_vs_baseline == self_consumed × (retail − own_use) × (1+vat) / 100
    """

    standing_charge_gbp: float
    """Annual grid standing charge (£)."""

    import_cost_gbp: float
    """Cost of electricity imported from the grid (£, ex-VAT)."""

    own_use_payment_gbp: float
    """CBS own-use transfer payment for self-consumed solar (£, ex-VAT).

    Computed as own_use_rate_pence_per_kwh × self_consumed_kwh / 100.
    This is the community-benefit-society transfer price for CBS-owned solar
    consumed on-site; it is NOT SEG and does not involve the export MPAN.
    """

    vat_gbp: float
    """VAT on (import + standing + own_use_payment) at the scenario VAT rate (£)."""

    total_outlay_gbp: float
    """Total annual householder outlay (headline): (import + standing + own_use) × (1+vat) (£).

    Replaces net_annual_bill_gbp from the old W2 model.  No SEG deduction.
    """

    self_consumption_saving_gbp: float
    """Value of solar used on-site relative to full retail purchase (£, VAT-inclusive).

    = self_consumed × (retail_rate − own_use_rate) × (1 + vat_rate) / 100.
    Represents the retail↔own-use price gap benefit, not the full avoided-retail value.
    Zero when own_use_rate == retail_rate.
    """

    baseline_bill_gbp: float
    """Hypothetical annual bill without any solar / battery system (£, VAT-inclusive).

    All demand priced at the retail baseline rate; standing charge added.
    """

    saving_vs_baseline_gbp: float
    """Saving compared to the no-solar baseline: baseline_bill − total_outlay (£)."""

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

    ``representative`` is the BillBreakdown of the home whose total_outlay_gbp
    is closest to the median (median-total-outlay home).  Per-home outlay values
    are stored as an immutable tuple so the dataclass remains hashable.

    Note: ``per_home_net_bill_gbp`` retains its name for back-compat (§12-Q4)
    but now holds per-home ``total_outlay_gbp`` values (CR3 redefinition).

    .. deprecated::
        ``per_home_net_bill_gbp`` will be renamed to ``per_home_total_outlay_gbp``
        once the back-compat window closes.  Track this via the §12-Q4 deprecation
        list and do not add new consumers that depend on the misleading name.
    """

    representative: BillBreakdown
    """Representative (median-net-bill) home's full BillBreakdown."""

    per_home_net_bill_gbp: tuple[float, ...]
    """Per-home total annual outlay (£).

    .. note::
        The name is retained for back-compat (§12-Q4); the values are
        ``total_outlay_gbp`` per home (CR3 redefinition), NOT the old
        W2 net-annual-bill.  Rename to ``per_home_total_outlay_gbp`` is
        tracked on the §12-Q4 deprecation list.
    """

    min_gbp: float
    """Minimum net annual bill across the fleet (£)."""

    mean_gbp: float
    """Mean net annual bill across the fleet (£)."""

    median_gbp: float
    """Median net annual bill across the fleet (£)."""

    max_gbp: float
    """Maximum net annual bill across the fleet (£)."""


# ---------------------------------------------------------------------------
# CostRecoverySolution — solve_cost_recovery_rate output (CR4 §3.1)
# ---------------------------------------------------------------------------

#: Allowed string values for :attr:`CostRecoverySolution.binding`.
_BINDING_VALUES: tuple[str, ...] = (
    "floor",
    "rate_clamped_zero",
    "infeasible_above_retail",
)


@dataclass(frozen=True)
class CostRecoverySolution:
    """Result of :func:`solve_cost_recovery_rate` — the solved cost-recovery own-use rate.

    The CBS charges householders ``own_use_rate_pence_per_kwh`` for every kWh of
    CBS-owned solar consumed on-site.  :func:`solve_cost_recovery_rate` finds the
    minimum rate that keeps project net surplus per home ≥
    ``FinanceConfig.retained_cash_floor_per_home_per_year_gbp``.

    **W3 primary key**: ``representative_outlay_gbp`` (= outlay.representative.total_outlay_gbp)
    is the householder annual outlay at the solved rate for the median-outlay home.
    The discrete-install config sweep (task 64–68) uses this field to rank configs.

    Attributes:
        own_use_rate_pence_per_kwh: Solved own-use rate (p/kWh, ∈ [0, retail_baseline]).
        outlay: Full fleet-level BillDistribution at the solved rate (age-0 sim).
        representative_outlay_gbp: Representative (median-outlay) home's total annual
            outlay in £.  == outlay.representative.total_outlay_gbp.
        net_surplus_per_home_per_year_gbp: Project net surplus per home per year at
            the solved rate (£).  Equals floor to float ε for binding='floor';
            strictly > floor for 'rate_clamped_zero'; < floor for
            'infeasible_above_retail'.
        saving_vs_baseline_gbp: Householder saving vs. no-solar baseline (£)
            at the solved rate.  == outlay.representative.saving_vs_baseline_gbp.
        saving_pct: Householder % saving vs. baseline.
            == outlay.representative.saving_pct.
        feasible: True when the CBS can meet the retained_cash_floor within
            [0, retail_baseline_rate].  False only for 'infeasible_above_retail'.
        binding: One of 'floor', 'rate_clamped_zero', 'infeasible_above_retail':
            - 'floor': r* ∈ [0, retail] and surplus(r*) == floor to ε.
            - 'rate_clamped_zero': r* < 0 (project over-delivers at r=0);
              rate clamped to 0, surplus > floor.
            - 'infeasible_above_retail': r* > retail; rate clamped to retail,
              surplus < floor; feasible=False.
    """

    own_use_rate_pence_per_kwh: float
    """Solved own-use rate charged by CBS to householders (p/kWh, ≥ 0)."""

    outlay: "BillDistribution"
    """Fleet bill distribution at the solved rate, computed from an age-0 simulation."""

    representative_outlay_gbp: float
    """Representative (median-outlay) home's total annual outlay (£, W3 primary key).

    Invariant: representative_outlay_gbp == outlay.representative.total_outlay_gbp.
    """

    net_surplus_per_home_per_year_gbp: float
    """Project net surplus per home per year at the solved rate (£/home/year)."""

    saving_vs_baseline_gbp: float
    """Householder saving vs no-solar baseline at the solved rate (£).

    Invariant: == outlay.representative.saving_vs_baseline_gbp.
    """

    saving_pct: float
    """Householder % saving vs baseline at the solved rate.

    Invariant: == outlay.representative.saving_pct.
    """

    feasible: bool
    """True when the CBS can meet the retained_cash_floor within [0, retail_baseline_rate]."""

    binding: str
    """Binding constraint: one of 'floor', 'rate_clamped_zero', 'infeasible_above_retail'."""

    def __post_init__(self) -> None:
        if self.binding not in _BINDING_VALUES:
            raise ValueError(
                f"binding must be one of {_BINDING_VALUES!r}, got {self.binding!r}"
            )
        if self.own_use_rate_pence_per_kwh < 0.0:
            raise ValueError(
                f"own_use_rate_pence_per_kwh must be >= 0, "
                f"got {self.own_use_rate_pence_per_kwh!r}"
            )


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Default self-consumption fraction used for the spreadsheet assumption when no
#: explicit ``self_consumption_override`` is set in ``FinanceConfig``.  Exposed
#: here (rather than buried in the CLI) so config-file authors and non-CLI
#: callers can discover and reference the value alongside the other finance
#: parameters.
DEFAULT_SPREADSHEET_SELF_CONSUMPTION: float = 0.70

#: Days used as the annualised year length; all short-period outputs scale to this.
_ANNUALISATION_DAYS = 365
#: Simulation periods shorter than this number of days trigger annualisation.
_SHORT_PERIOD_THRESHOLD = 360


# ---------------------------------------------------------------------------
# _AnnualisedPhysics / _annualise_physics — shared annualisation helper
# ---------------------------------------------------------------------------


class _AnnualisedPhysics(NamedTuple):
    """Simulation physics quantities scaled to a 365-day annual basis.

    Returned by :func:`_annualise_physics`.  All energy values are in kWh;
    monetary values are in GBP (£).

    ``sc_kwh`` is taken from ``summary.total_self_consumption_kwh``.
    :func:`householder_bill` overrides it with its *annual_self_consumption_kwh*
    parameter, which may differ when the caller supplies an externally-computed
    self-consumption figure.
    """

    scale: float
    """Annualisation multiplier (1.0 when simulation_days ≥ _SHORT_PERIOD_THRESHOLD)."""
    gen_kwh: float
    demand_kwh: float
    sc_kwh: float
    import_kwh: float
    import_cost_physics: float
    export_kwh: float
    export_rev_physics: float


def _annualise_physics(
    summary: "SummaryStatistics",
    simulation_days: int,
) -> _AnnualisedPhysics:
    """Scale simulation energy/cost figures to a 365-day annual basis.

    When *simulation_days* is below :data:`_SHORT_PERIOD_THRESHOLD` (360),
    all quantities are multiplied by ``365 / max(simulation_days, 1)``.
    Otherwise ``scale = 1.0`` and the raw figures are returned unchanged.

    This is the single authoritative annualisation implementation; both
    :func:`householder_bill` and :func:`_seg_export_income_gbp` delegate to it
    so the threshold, guard, and formula cannot diverge.

    Args:
        summary: Per-home simulation output (read-only).
        simulation_days: Actual simulation length in days.

    Returns:
        An :class:`_AnnualisedPhysics` namedtuple with ``scale`` and the
        annualised energy/cost quantities.
    """
    if simulation_days < _SHORT_PERIOD_THRESHOLD:
        scale = _ANNUALISATION_DAYS / max(simulation_days, 1)
    else:
        scale = 1.0
    return _AnnualisedPhysics(
        scale=scale,
        gen_kwh=summary.total_generation_kwh * scale,
        demand_kwh=summary.total_demand_kwh * scale,
        sc_kwh=summary.total_self_consumption_kwh * scale,
        import_kwh=summary.total_grid_import_kwh * scale,
        import_cost_physics=summary.total_import_cost_gbp * scale,
        export_kwh=summary.total_grid_export_kwh * scale,
        export_rev_physics=summary.total_export_revenue_gbp * scale,
    )


# ---------------------------------------------------------------------------
# _seg_export_income_gbp — CBS SEG revenue helper (extracted from W2 model)
# ---------------------------------------------------------------------------


def _seg_export_income_gbp(
    summary: "SummaryStatistics",
    finance: "FinanceConfig",
    simulation_days: int,
) -> float:
    """Compute the SEG export income for a single home (CBS-revenue side).

    This is the export-income logic that was removed from the householder bill
    in CR3 (the CBS owns the export MPAN, so export revenue flows to the CBS,
    not the householder).  It is used by :func:`project_multi_year._simulate_age`
    to compute ``seg_revenue = Σ _seg_export_income_gbp(s, ...)`` as part of
    the CBS fleet revenue formula (PRD §3.2).

    Delegates annualisation to :func:`_annualise_physics` so the threshold,
    guard, and formula cannot diverge from :func:`householder_bill`.

    * **Physics path** (``finance.self_consumption_override`` is None):
      annualised ``summary.total_export_revenue_gbp``.
    * **Override path**: re-compute override export kWh from the override
      self-consumption fraction; price at the effective export rate derived
      from the physics figures (falls back to 0.0 if physics export kWh == 0).

    Args:
        summary: Per-home simulation output (read-only).
        finance: FinanceConfig with tariff + assumption parameters.
        simulation_days: Actual simulation length in days; triggers
            annualisation to 365 days when < 360.

    Returns:
        SEG export income in GBP (£), annualised to a 365-day year.
    """
    override = finance.self_consumption_override

    phys = _annualise_physics(summary, simulation_days)

    if override is None:
        # Physics path: annualised SEG revenue from simulation
        return float(phys.export_rev_physics)
    else:
        # Spreadsheet path: recompute from override fraction
        sc_kwh = override * phys.gen_kwh
        override_export_kwh = max(phys.gen_kwh - sc_kwh, 0.0)
        if phys.export_kwh > 0.0:
            effective_export_rate_pence = (
                phys.export_rev_physics / phys.export_kwh
            ) * 100.0
        else:
            effective_export_rate_pence = 0.0
        return float(override_export_kwh * effective_export_rate_pence / 100.0)


# ---------------------------------------------------------------------------
# _cbs_own_use_kwh — basis-C own-use energy helper (task-84 §6)
# ---------------------------------------------------------------------------


def _cbs_own_use_kwh(summary: "SummaryStatistics") -> float:
    """Basis-C own-use energy for CBS cost-recovery accounting (kWh).

    Basis C: own-use = consumption − import = CBS-supplied energy consumed.
    This equals the energy that did NOT cross the grid boundary in the
    consumption direction, i.e. the CBS-originated energy actually used by
    the home.

    Arbitrage-immune: grid-charged battery discharge inflates
    ``total_self_consumption_kwh`` (B-style: min(direct + discharge, demand))
    but does NOT inflate ``total_demand_kwh − total_grid_import_kwh`` because
    the grid-charged energy is counted in ``total_grid_import_kwh``.  The CBS
    bears the battery round-trip loss (absorbed into the headline own-use rate).

    Clamps to 0.0 for degenerate cases where import > demand (should not occur
    in real simulations but can arise in hand-crafted test fixtures).

    Args:
        summary: Per-home simulation output; uses
            ``total_demand_kwh`` and ``total_grid_import_kwh``.

    Returns:
        Basis-C own-use energy in kWh (≥ 0.0).
    """
    return max(summary.total_demand_kwh - summary.total_grid_import_kwh, 0.0)


# ---------------------------------------------------------------------------
# bill() — period-native billing core (task 83 §1)
# ---------------------------------------------------------------------------


def bill(
    *,
    period_days: float,
    generation_kwh: float,
    demand_kwh: float,
    self_consumption_kwh: float,
    import_kwh: float,
    import_cost_gbp: float,
    baseline_import_cost_gbp: float,
    finance: "FinanceConfig",
) -> BillBreakdown:
    """Period-native billing core: pure arithmetic over caller-resolved inputs.

    This is the single source of truth for the BillBreakdown identities (§3.1).
    It performs **no** annualisation, no re-pricing of import energy, and emits
    no warnings — all of that belongs in the caller (e.g. :func:`householder_bill`
    for the simulator's annual wrapper).

    Identities:
      standing_charge_gbp   = standing_pence_per_day × period_days / 100
      own_use_payment_gbp   = own_use_rate × self_consumption_kwh / 100
      vat_gbp               = vat_rate × (import_cost + standing + own_use_payment)
      total_outlay_gbp      = (import_cost + standing + own_use_payment) × (1 + vat_rate)
      baseline_bill_gbp     = (baseline_import_cost + standing) × (1 + vat_rate)
      eff_rate              = baseline_import_cost / demand_kwh × 100  (fallback to retail when demand==0)
      self_consumption_saving_gbp = sc × (eff_rate − own_use_rate) × (1 + vat_rate) / 100
      saving_vs_baseline_gbp = baseline_bill − total_outlay
      saving_pct            = 100 × saving / baseline  (0.0 when baseline==0)
      self_consumption_fraction = sc / generation  (0.0 when generation==0)

    Args:
        period_days: Duration of the billing period in days.
        generation_kwh: Total PV generation during the period (kWh).
        demand_kwh: Total household demand during the period (kWh).
        self_consumption_kwh: Solar energy consumed on-site (kWh).
        import_kwh: Energy imported from the grid (kWh).  Accepted for contract
            completeness (symmetric with platform period engine) but not consumed
            by the arithmetic; import_cost_gbp is used as the financial measure.
        import_cost_gbp: Cost of grid imports (£, caller-priced, passed verbatim).
            For TOU/mid-period billing the caller prices import_kwh at the
            appropriate rate before calling this function.
        baseline_import_cost_gbp: Hypothetical cost if all demand were imported
            at the baseline rate (£, caller-computed).  Drives eff_rate and
            self_consumption_saving.
        finance: Financial parameters.

    Returns:
        A fully computed, frozen :class:`BillBreakdown`.
    """
    vat_rate = finance.vat_rate
    own_use_rate_pence = finance.own_use_rate_pence_per_kwh
    standing_pence_per_day = finance.standing_charge_pence_per_day

    # --- Standing charge (period-proportional) ---
    standing_charge_gbp = standing_pence_per_day * period_days / 100.0

    # --- Own-use payment (CBS transfer price × self-consumed kWh) ---
    own_use_payment_gbp = own_use_rate_pence * self_consumption_kwh / 100.0

    # --- VAT (on import + standing + own-use payment) ---
    vat_gbp = vat_rate * (import_cost_gbp + standing_charge_gbp + own_use_payment_gbp)

    # --- Total outlay (headline) ---
    total_outlay_gbp = (
        import_cost_gbp + standing_charge_gbp + own_use_payment_gbp
    ) * (1.0 + vat_rate)

    # --- Baseline bill (no solar, all demand at baseline rate) ---
    baseline_bill_gbp = (baseline_import_cost_gbp + standing_charge_gbp) * (1.0 + vat_rate)

    # --- Effective displaced rate (TOU-consistent: derived from caller-priced baseline) ---
    if demand_kwh > 0.0:
        eff_rate_pence = baseline_import_cost_gbp / demand_kwh * 100.0
    else:
        eff_rate_pence = finance.retail_baseline_rate_pence_per_kwh

    # --- Self-consumption saving (price-gap benefit, VAT-inclusive) ---
    self_consumption_saving_gbp = (
        self_consumption_kwh * (eff_rate_pence - own_use_rate_pence) * (1.0 + vat_rate) / 100.0
    )

    # --- Saving vs baseline ---
    saving_vs_baseline_gbp = baseline_bill_gbp - total_outlay_gbp
    saving_pct = (
        (saving_vs_baseline_gbp / baseline_bill_gbp) * 100.0
        if baseline_bill_gbp != 0.0
        else 0.0
    )

    # --- Self-consumption fraction ---
    self_consumption_fraction = (
        self_consumption_kwh / generation_kwh if generation_kwh > 0.0 else 0.0
    )

    return BillBreakdown(
        standing_charge_gbp=float(standing_charge_gbp),
        import_cost_gbp=float(import_cost_gbp),
        own_use_payment_gbp=float(own_use_payment_gbp),
        vat_gbp=float(vat_gbp),
        total_outlay_gbp=float(total_outlay_gbp),
        self_consumption_saving_gbp=float(self_consumption_saving_gbp),
        baseline_bill_gbp=float(baseline_bill_gbp),
        saving_vs_baseline_gbp=float(saving_vs_baseline_gbp),
        saving_pct=float(saving_pct),
        self_consumption_fraction=float(self_consumption_fraction),
    )


# ---------------------------------------------------------------------------
# householder_bill
# ---------------------------------------------------------------------------


def householder_bill(
    summary: "SummaryStatistics",
    annual_self_consumption_kwh: float,
    finance: "FinanceConfig",
    simulation_days: int,
) -> BillBreakdown:
    """Annual cost-recovery bill wrapper for simulator outputs.

    This is the **annual wrapper** over :func:`bill` that converts simulation
    outputs (which may cover any period) into a standardised 365-day bill.
    All bill arithmetic (identities, VAT, savings) lives in :func:`bill` —
    the single source of truth.

    Responsibilities of this wrapper (not in bill()):
      * Annualise sub-year simulation totals via :func:`_annualise_physics`.
      * Emit a :class:`UserWarning` for short periods (< 360 days).
      * Resolve the physics/override self-consumption path.
      * Apply the missing-tariff retail fallback with a :class:`UserWarning`.
      * Always call bill(period_days=365, ...) so standing charge is
        annual regardless of the original simulation length.

    H3 board identity (holds when import is retail-priced, import_kwh = demand − sc):
      saving_vs_baseline == sc × (retail − own_use) × (1+vat) / 100

    Args:
        summary: Per-home simulation output (read-only).
        annual_self_consumption_kwh: Physics self-consumption figure (kWh).
            When ``finance.self_consumption_override`` is None, this is used
            directly.  When an override is set, it is used only for scaling.
        finance: FinanceConfig with tariff + assumption parameters.
        simulation_days: Actual simulation length in days; triggers
            annualisation to 365 days when < 360.

    Returns:
        A fully computed, frozen BillBreakdown (delegated to :func:`bill`).
    """
    retail_rate_pence = finance.retail_baseline_rate_pence_per_kwh
    override = finance.self_consumption_override

    # ---- Annualisation (§3.2 / §12) ----------------------------------------
    phys = _annualise_physics(summary, simulation_days)
    if simulation_days < _SHORT_PERIOD_THRESHOLD:
        warnings.warn(
            f"Simulation period is only {simulation_days} days (<360); "
            f"scaling financial outputs to {_ANNUALISATION_DAYS}-day annual basis "
            f"(scale={phys.scale:.3f}).",
            UserWarning,
            stacklevel=2,
        )
    # NOTE: householder_bill takes annual_self_consumption_kwh as a separate parameter
    # (caller-supplied, may differ from summary.total_self_consumption_kwh when the
    # caller has an independently-computed self-consumption figure, e.g. fleet_distribution).
    sc_kwh_physics = annual_self_consumption_kwh * phys.scale
    gen_kwh = phys.gen_kwh
    demand_kwh = phys.demand_kwh
    import_kwh = phys.import_kwh
    import_cost_physics = phys.import_cost_physics
    # export_kwh / export_rev_physics not needed here: SEG moved to
    # _seg_export_income_gbp in CR3; householder_bill no longer computes export income.

    # ---- Self-consumption switch (§2.3 / §3.2) ------------------------------
    if override is None:
        # Physics path: use simulation figures directly
        import_cost_gbp = import_cost_physics
        sc_kwh = sc_kwh_physics
        # import_kwh_for_bill matches phys.import_kwh (set above) — the energy
        # quantity priced by import_cost_gbp on the physics path.
        import_kwh_for_bill = import_kwh

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

        # Effective import unit rate from physics (fall back to retail if zero physics import)
        if import_kwh > 0.0:
            effective_import_rate_pence = (import_cost_physics / import_kwh) * 100.0
        else:
            effective_import_rate_pence = retail_rate_pence

        # Recompute import: demand minus self-consumed solar
        override_import_kwh = max(demand_kwh - sc_kwh, 0.0)
        import_cost_gbp = override_import_kwh * effective_import_rate_pence / 100.0
        # Keep import_kwh consistent with import_cost_gbp: on the override path,
        # import_cost_gbp prices override_import_kwh (not phys.import_kwh).
        import_kwh_for_bill = override_import_kwh

    # ---- Delegate all bill arithmetic to bill() (single source of truth) ----
    # period_days=365 reproduces the old annual standing-charge hard-code exactly:
    #   bill()'s standing = standing_pence * 365 / 100  ==  old _ANNUALISATION_DAYS
    baseline_import_cost_gbp = demand_kwh * retail_rate_pence / 100.0
    return bill(
        period_days=float(_ANNUALISATION_DAYS),
        generation_kwh=gen_kwh,
        demand_kwh=demand_kwh,
        self_consumption_kwh=sc_kwh,
        import_kwh=import_kwh_for_bill,
        import_cost_gbp=import_cost_gbp,
        baseline_import_cost_gbp=baseline_import_cost_gbp,
        finance=finance,
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

    ``fleet_revenue_gbp`` is the CBS revenue:
    own-use savings (own_use_rate × fleet_self_consumption_kwh / 100)
    + SEG export income (Σ seg_export_income_gbp per home)
    + grid-services topper (grid_services_income_per_kw_per_year_gbp × Σ battery max_discharge_kw)
    − CBS grid-charge cost (Σ total_grid_charge_cost_gbp per home).
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
    """CBS revenue (own-use + SEG + grid-services topper − CBS grid-charge cost) (£)."""

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
            4-term build-up: Σ_home(pv_kwp × pv_cost + roof_fit
            + battery_kwh × battery_cost + eff_inv_kw × inverter_cost).
            Inverter term is zero when inverter_cost_per_kw_gbp == 0.0 (default).
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
        mean_fleet_surplus_per_year_gbp: Mean annual fleet surplus across the
            full asset life (£/year).  Equals mean(per_year_surplus_gbp).
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

    fleet_opex_gbp: float
    """Total fleet operating expenditure per year (£/year):
    opex_per_home_per_year_gbp × n_homes."""

    mean_fleet_surplus_per_year_gbp: float
    """Mean annual fleet surplus across the full asset life (£/year):
    mean(per_year_surplus_gbp).  Single source of truth used by the economics
    report; avoids recomputing the mean from the tuple at render time."""

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
    """Aggregate per-home bills into a fleet-level BillDistribution (CR3).

    Maps ``householder_bill`` over each home's SummaryStatistics, selects the
    median-**total-outlay** home as representative, and computes min / mean /
    median / max via ``pd.Series`` (mirroring ``calculate_fleet_summary``).

    Note: ``BillDistribution.per_home_net_bill_gbp`` retains its name for
    back-compat (§12-Q4) but now holds per-home ``total_outlay_gbp`` values.

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
    # CR3: key distribution on total_outlay_gbp (not the old net_annual_bill_gbp)
    outlays = [b.total_outlay_gbp for b in bills]
    series = pd.Series(outlays, dtype=float)

    median_val = float(series.median())
    # Representative: home whose total outlay is closest to the median
    rep_idx = int((series - median_val).abs().idxmin())

    return BillDistribution(
        representative=bills[rep_idx],
        # per_home_net_bill_gbp name retained for back-compat; value = total_outlay_gbp
        per_home_net_bill_gbp=tuple(outlays),
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
    homes = _resolve_homes(scenario)

    # ---- Derive timezone from scenario location (or first home) -------------
    tz: str
    if scenario.location is not None:
        tz = scenario.location.timezone
    else:
        tz = homes[0].location.timezone

    # ---- Derive start/end timestamps from scenario period -------------------
    start_ts = scenario.period.get_start_timestamp(tz)
    end_ts = scenario.period.get_end_timestamp(tz)

    # ---- Fail-fast: validate grid_services_model prerequisites ---------------
    # Guard here so misconfiguration is caught before any simulation work is
    # done (the inner guard in _simulate_age would only fire after the first
    # full fleet simulation, which wastes a full age-0 run for a 100-home fleet).
    if finance.grid_services_model == "capacity_at_events" and finance.grid_services_events is None:
        from solar_challenge.config import ConfigurationError
        raise ConfigurationError(
            "grid_services_model='capacity_at_events' requires "
            "grid_services_events to be configured"
        )

    asset_life = finance.asset_life_years

    # ---- Seed nodes ---------------------------------------------------------
    seed_ages: list[int] = sorted({0, asset_life // 2, asset_life - 1})

    # ---- Forward-march: simulate at each seed age, collect aggregates -------
    # Per-home cumulative throughput (kWh): tracks battery history across ages.
    # Initialised to 0 at age 0; accumulated trapezoidally (step-12).
    n_homes = len(homes)
    cum_throughput: list[float] = [0.0] * n_homes

    sampled_data: dict[int, _NodeData] = {}

    # Memo dict for the capacity_at_events grid-services figure (PRD decision 7 / Open Q1).
    # Computed once from the representative (age-0) simulation, reused for all ages
    # and all bisection trial nodes.  Captured by the _simulate_age closure.
    _event_gs_memo: dict[str, float] = {}

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

        # CBS fleet revenue (PRD §3.2):
        #   own_use_revenue = own_use_rate_pence_per_kwh × fleet_sc / 100
        #   seg_revenue     = Σ _seg_export_income_gbp(s, finance, s.simulation_days)
        #   grid_services   = model-dependent (flat or capacity_at_events)
        #   cbs_grid_charge = Σ summary.total_grid_charge_cost_gbp
        #   fleet_revenue   = own_use_revenue + seg_revenue + grid_services − cbs_grid_charge
        # CR3: SEG revenue is extracted via _seg_export_income_gbp (honours
        # self_consumption_override and seg scaling automatically); householder_bill
        # is no longer called here since seg_export_income_gbp was removed from it.
        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc / 100.0
        seg_revenue = sum(
            _seg_export_income_gbp(s, finance, s.simulation_days)
            for s in per_home_summaries
        )
        if finance.grid_services_model == "capacity_at_events":
            # None is already excluded by the top-of-function guard; this assert
            # only narrows Optional[GridServicesEventsConfig] for mypy strict.
            assert finance.grid_services_events is not None
            if "value" not in _event_gs_memo:
                from solar_challenge.gridservices import compute_grid_services_at_events
                _event_gs_memo["value"] = compute_grid_services_at_events(
                    fleet_results, finance.grid_services_events
                ).annual_income_gbp
            grid_services = _event_gs_memo["value"]
        else:
            grid_services = finance.grid_services_income_per_kw_per_year_gbp * sum(
                h.battery_config.max_discharge_kw
                for h in homes
                if h.battery_config is not None
            )
        cbs_grid_charge_cost = sum(s.total_grid_charge_cost_gbp for s in per_home_summaries)
        fleet_revenue = own_use_revenue + seg_revenue + grid_services - cbs_grid_charge_cost

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


def _resolve_homes(scenario: "ScenarioConfig") -> List[Any]:
    """Resolve a list of homes from a ScenarioConfig.

    Supports both the ``.homes`` list form and the single ``.home`` form.
    Raises :class:`ValueError` when neither form yields at least one home.

    Args:
        scenario: The scenario whose homes should be resolved.

    Returns:
        Non-empty list of HomeConfig objects.

    Raises:
        ValueError: When scenario has no homes.
    """
    homes: List[Any] = (
        list(scenario.homes) if scenario.homes
        else ([scenario.home] if scenario.home is not None else [])
    )
    if not homes:
        raise ValueError("scenario must have at least one home")
    return homes


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

    # Bracket: search within [-50%, +10000%]; upper end is capped high so
    # very profitable low-equity projects (where true IRR >> 500%) are still
    # captured rather than returning nan.
    lo, hi = -0.5, 100.0
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
    2. Compute total_capex_gbp via the 4-term build-up:
       Σ_home(pv_kwp × pv_cost + roof_fit + battery_kwh × battery_cost
       + eff_inv_kw × inverter_cost).  Inverter term is zero when
       inverter_cost_per_kw_gbp == 0.0 (the default).
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
    homes = _resolve_homes(scenario)
    n_homes = len(homes)

    # 2. Capex: 4-term build-up (pv + roof + battery + inverter)
    total_capex_gbp = 0.0
    for home in homes:
        pv_kwp = home.pv_config.capacity_kw
        batt_kwh = (
            home.battery_config.capacity_kwh
            if home.battery_config is not None
            else 0.0
        )
        eff_inv_kw = home.pv_config.effective_inverter_capacity_kw
        total_capex_gbp += (
            pv_kwp * finance.pv_cost_per_kwp_gbp
            + finance.roof_fit_cost_gbp
            + batt_kwh * finance.battery_cost_per_kwh_gbp
            + eff_inv_kw * finance.inverter_cost_per_kw_gbp
        )

    # 3. Grant / equity / debt split
    financed = max(total_capex_gbp - finance.grant_gbp, 0.0)
    equity_gbp = financed * finance.equity_fraction
    debt_gbp = financed * (1.0 - finance.equity_fraction)

    # 4. Annual debt service
    annual_debt_service_gbp = _annuity_payment(
        debt_gbp, finance.loan_rate, finance.loan_term_years
    )

    # Guard: curve must be long enough to cover the full asset life.
    # Raised as a clear domain error rather than an opaque IndexError.
    if len(curve.points) < finance.asset_life_years:
        raise ValueError(
            f"curve has {len(curve.points)} points but finance.asset_life_years="
            f"{finance.asset_life_years}; pass a curve built from the same FinanceConfig"
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
        fleet_opex_gbp=fleet_opex,
        mean_fleet_surplus_per_year_gbp=mean_surplus,
    )


# ---------------------------------------------------------------------------
# spreadsheet_revenue_curve — [FIN]-assumption analytic revenue curve (θ)
# ---------------------------------------------------------------------------


def spreadsheet_revenue_curve(
    *,
    n_homes: int,
    pv_kwp: float,
    kwh_per_kwp: float,
    self_consumption_fraction: float,
    own_use_rate_pence_per_kwh: float,
    export_rate_pence_per_kwh: float,
    asset_life_years: int,
) -> MultiYearCurve:
    """Build a flat [FIN]-assumption fleet-revenue :class:`MultiYearCurve`.

    Produces a deterministic, physics-free revenue curve matching the investor
    spreadsheet's named input assumptions:

    * ``inp_kWhPerkWp`` (Sensitivity!B8) → ``kwh_per_kwp``
    * Own-use rate 15 p/kWh (§3 [FIN] assumptions)
    * Export rate 6 p/kWh (Smart Export Guarantee [FIN] basis)
    * Self-consumption fraction: typically 0.45 (PV-only) or 0.70 (with battery,
      [FIN]); caller-supplied, not enforced by this function

    Per-home generation::

        gen = pv_kwp × kwh_per_kwp   [kWh/yr]

    Fleet revenue::

        fleet_revenue_gbp = n_homes × (
            self_consumption_fraction × gen × own_use_rate_pence_per_kwh / 100
            + (1 − self_consumption_fraction) × gen × export_rate_pence_per_kwh / 100
        )

    The curve is *flat* — SOH fractions are pinned at 1.0 for every year because
    the spreadsheet's revenue projection does not model PV/battery degradation
    (verified via Capital_Stack!B6 arithmetic).  This makes the curve suitable as
    the *spreadsheet-input column* fed into :func:`project_economics` for the H6
    calibration gate.

    Do **not** use this curve for real simulation output — use
    :func:`project_multi_year` for physics-backed projections.

    Args:
        n_homes: Number of homes in the fleet.
        pv_kwp: PV capacity per home (kWp).
        kwh_per_kwp: Annual yield per kWp (kWh/kWp, e.g. 1050 from inp_kWhPerkWp).
        self_consumption_fraction: Fraction of generation consumed on-site (0–1).
        own_use_rate_pence_per_kwh: Retail value of self-consumed solar (p/kWh).
        export_rate_pence_per_kwh: SEG export rate for surplus generation (p/kWh).
        asset_life_years: Number of years in the projection (len of returned curve).

    Returns:
        A flat :class:`MultiYearCurve` with ``asset_life_years`` identical
        :class:`YearPoint` objects and ``interp_error_estimate == 0.0``.
    """
    # Validate domain constraints (mirror __post_init__ style used elsewhere)
    if not (0.0 <= self_consumption_fraction <= 1.0):
        raise ValueError(
            f"self_consumption_fraction must be in [0.0, 1.0], "
            f"got {self_consumption_fraction}"
        )
    if asset_life_years < 1:
        raise ValueError(
            f"asset_life_years must be >= 1, got {asset_life_years}"
        )

    # Per-home annual generation (kWh)
    gen_per_home_kwh: float = pv_kwp * kwh_per_kwp

    # Fleet generation (kWh)
    fleet_gen_kwh: float = float(n_homes) * gen_per_home_kwh

    # Energy split
    fleet_self_kwh: float = self_consumption_fraction * fleet_gen_kwh
    fleet_export_kwh: float = (1.0 - self_consumption_fraction) * fleet_gen_kwh

    # Fleet revenue (£/yr)  — own-use saving + SEG export income
    fleet_revenue_gbp: float = (
        fleet_self_kwh * own_use_rate_pence_per_kwh / 100.0
        + fleet_export_kwh * export_rate_pence_per_kwh / 100.0
    )

    # Build identical YearPoints for each year (flat — no degradation in spreadsheet)
    points: tuple[YearPoint, ...] = tuple(
        YearPoint(
            year=y,
            pv_soh=1.0,
            battery_soh=1.0,
            fleet_self_consumption_kwh=fleet_self_kwh,
            fleet_export_kwh=fleet_export_kwh,
            fleet_import_kwh=0.0,   # not modelled by the spreadsheet; set to 0
            fleet_revenue_gbp=fleet_revenue_gbp,
        )
        for y in range(asset_life_years)
    )

    return MultiYearCurve(
        points=points,
        sampled_ages=(0,),          # analytic; no simulation nodes
        interp_error_estimate=0.0,  # exact; no interpolation
    )


# ---------------------------------------------------------------------------
# solve_cost_recovery_rate — CR4 near-closed-form own-use-rate solve
# ---------------------------------------------------------------------------

#: Minimum absolute slope (kWh-weighted / pence) below which we treat the
#: project as having no self-consumption and fall through to the degenerate branch.
_SLOPE_EPS: float = 1e-9


def solve_cost_recovery_rate(
    scenario: "ScenarioConfig",
    finance: "FinanceConfig",
    *,
    simulate: Optional[Callable[["FleetConfig", pd.Timestamp, pd.Timestamp], "FleetResults"]] = None,
) -> "CostRecoverySolution":
    """Find the minimum CBS own-use rate that meets the retained-cash floor.

    The CBS charges householders ``own_use_rate_pence_per_kwh`` p/kWh for every
    kWh of CBS-owned solar consumed on-site.  This function finds the lowest such
    rate *r** such that ``project_economics.net_surplus_per_home_per_year_gbp ≥
    finance.retained_cash_floor_per_home_per_year_gbp``.

    **Mechanism** (no re-sim per trial rate):

    ``net_surplus_per_home_per_year_gbp`` is *exactly affine* in *r*:
    ``fleet_revenue_y = r × fleet_sc_y / 100 + C_y`` where *C_y* is
    rate-independent.  PCHIP interpolation is a linear operator on node values;
    ``project_economics`` is affine in per-year revenue.  Hence two trial rates
    (r=0, r=retail) recover the exact affine line, and the solve is closed-form:

    1. Run ``project_multi_year`` **once** at the configured rate ``r0`` → base curve.
    2. ``surplus_at(r)`` rebuilds each ``YearPoint``'s ``fleet_revenue_gbp`` via
       ``dataclasses.replace``: ``rev_y' = rev_y + (r - r0)/100 × sc_y``.
    3. Compute ``s0 = surplus_at(0)``, ``s_ret = surplus_at(retail)``,
       ``slope = (s_ret - s0) / retail``.
    4. Solve ``r* = (floor - s0) / slope``; clamp to [0, retail]; set *binding*.
    5. Compute outlay from a dedicated age-0 fleet sim (per-home granularity
       not available from the multi-year curve).

    **Affine-line precondition** (Suggestion 3 / robustness note):

    Step 2 is exact when ``project_multi_year`` does *not* clamp any year's
    ``fleet_revenue_gbp`` to zero.  The code stores
    ``fleet_revenue_gbp = max(0.0, rev_per_year[y])``, so if any year's raw
    revenue is negative (e.g. in severely loss-making scenarios where CBS
    grid-charge cost exceeds all income at the configured r0), the base node
    is clamped and the linear reconstruction diverges from a true re-sim by a
    bounded error.  In practice this only occurs in scenarios well outside the
    viable parameter range (surplus at the configured r0 is deeply negative);
    the solved rate may then be a few pence off the true breakeven.  Callers
    that need bit-exact results under such conditions should re-simulate at the
    returned rate.

    **Cost note** (Suggestion 4 / performance):

    ``project_multi_year`` already simulates the fleet at age 0 internally
    (age 0 is always in the seed-age set) but discards per-home results.
    Step 5 therefore re-runs an independent age-0 fleet simulation to obtain
    the per-home ``SummaryStatistics`` needed for ``bill_distribution``.  With
    the real ``simulate_fleet`` this doubles the age-0 simulation cost per
    ``solve_cost_recovery_rate`` call.  If this becomes a bottleneck,
    consider refactoring ``project_multi_year`` to surface the age-0 per-home
    results so the second simulation can be avoided.

    **Clamp / binding convention**:

    * ``r* < 0``: ``rate_clamped_zero`` (feasible=True, surplus > floor).
    * ``0 ≤ r* ≤ retail``: ``floor`` (feasible=True, surplus ≈ floor to float ε).
    * ``r* > retail``: ``infeasible_above_retail`` (feasible=False, rate=retail,
      surplus < floor).
    * Degenerate (slope ≈ 0, no self-consumption): if ``s0 ≥ floor`` →
      ``rate_clamped_zero``; else → ``infeasible_above_retail``.

    Args:
        scenario: ScenarioConfig with homes, period, and location.
        finance: FinanceConfig with cost-recovery fields populated (CR1).
        simulate: Optional inject for testing.  Defaults to None → lazy import
            ``fleet.simulate_fleet``.  Signature must match
            ``(FleetConfig, pd.Timestamp, pd.Timestamp) → FleetResults``.

    Returns:
        A :class:`CostRecoverySolution` with the solved rate and outlay.
    """
    # ---- Lazy import (mirrors project_multi_year) ----------------------------
    if simulate is None:
        from solar_challenge.fleet import simulate_fleet as _simulate_fleet
        simulate = _simulate_fleet

    # ---- Resolve homes + time axes (mirrors project_multi_year) --------------
    homes = _resolve_homes(scenario)

    tz: str
    if scenario.location is not None:
        tz = scenario.location.timezone
    else:
        tz = homes[0].location.timezone

    start_ts = scenario.period.get_start_timestamp(tz)
    end_ts = scenario.period.get_end_timestamp(tz)

    # ---- (1) Base curve at the configured r0 ---------------------------------
    r0 = finance.own_use_rate_pence_per_kwh
    base_curve = project_multi_year(scenario, finance, simulate=simulate)

    # ---- (2) surplus_at(r): rebuild YearPoints with rate-shifted revenue -----
    def surplus_at(r: float) -> float:
        """Return net_surplus_per_home_per_year at trial rate r (p/kWh)."""
        new_points = tuple(
            dataclasses.replace(
                yp,
                fleet_revenue_gbp=yp.fleet_revenue_gbp
                + (r - r0) / 100.0 * yp.fleet_self_consumption_kwh,
            )
            for yp in base_curve.points
        )
        rate_curve = dataclasses.replace(base_curve, points=new_points)
        # finance passed to project_economics can be the original; capex/debt
        # are rate-independent.  Surplus formula uses curve.points[y].fleet_revenue_gbp.
        return project_economics(rate_curve, scenario, finance).net_surplus_per_home_per_year_gbp

    # ---- (3) Two-point fit to recover the affine line ------------------------
    retail = finance.retail_baseline_rate_pence_per_kwh
    floor = finance.retained_cash_floor_per_home_per_year_gbp

    s0 = surplus_at(0.0)
    s_ret = surplus_at(retail)
    slope = (s_ret - s0) / retail  # retail > 0 (validated in FinanceConfig)

    # ---- (4) Solve + clamp ---------------------------------------------------
    if abs(slope) > _SLOPE_EPS:
        r_star = (floor - s0) / slope
        if r_star < 0.0:
            rate = 0.0
            binding = "rate_clamped_zero"
            feasible = True
        elif r_star <= retail:
            rate = r_star
            binding = "floor"
            feasible = True
        else:
            rate = retail
            binding = "infeasible_above_retail"
            feasible = False
    else:
        # Degenerate: near-zero self-consumption → surplus is constant
        if s0 >= floor:
            rate = 0.0
            binding = "rate_clamped_zero"
            feasible = True
        else:
            rate = retail
            binding = "infeasible_above_retail"
            feasible = False

    # ---- (5) Net surplus at the clamped/solved rate --------------------------
    net_surplus = surplus_at(rate)

    # ---- (6) Age-0 outlay BillDistribution -----------------------------------
    from solar_challenge.fleet import FleetConfig
    from solar_challenge.home import calculate_summary

    aged0 = _aged_homes(homes, 0)
    fleet_cfg = FleetConfig(homes=aged0, name="cr4-solve-age0")
    fr_age0 = simulate(fleet_cfg, start_ts, end_ts)

    summaries = [
        calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
        for r in fr_age0.per_home_results
    ]
    sim_days = summaries[0].simulation_days
    finance_solved = dataclasses.replace(finance, own_use_rate_pence_per_kwh=rate)
    outlay = bill_distribution(summaries, finance_solved, sim_days)

    # ---- (7) Assemble result -------------------------------------------------
    rep = outlay.representative
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=rate,
        outlay=outlay,
        representative_outlay_gbp=rep.total_outlay_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus,
        saving_vs_baseline_gbp=rep.saving_vs_baseline_gbp,
        saving_pct=rep.saving_pct,
        feasible=feasible,
        binding=binding,
    )
