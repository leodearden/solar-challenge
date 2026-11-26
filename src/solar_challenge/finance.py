# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Householder bills, fleet bill distributions, the home ledger, cash-flow maths
and the cost-recovery solution for the community PV/battery project, from
simulation results and a :class:`FinanceConfig`.

Provides:
  - ``FinanceConfig`` — frozen dataclass of the financial parameters.
  - ``DEFAULT_SPREADSHEET_SELF_CONSUMPTION`` — self-consumption fraction the
    spreadsheet assumption uses when no override is set.
  - ``BillBreakdown`` — frozen dataclass of per-householder financial line items.
  - ``BillDistribution`` — frozen dataclass with fleet-level outlay statistics.
  - ``CostRecoverySolution`` — frozen dataclass result of the cost-recovery solve.
  - ``one_window`` — the one window summaries billed or projected together cover.
  - ``AnnualPhysics`` — frozen dataclass of a summary's totals scaled to its
    window's year, beside the window and how its run was priced.
  - ``annualise`` — the one annualisation rule, a summary to its AnnualPhysics.
  - ``refuse_analysis_only_forecasts`` — refuses, before they are simulated,
    homes whose grid charge a forecast no board figure may use sizes.
  - ``basis_c_own_use_kwh`` — a summary's basis-C own-use, demand − import,
    over its window.
  - ``OwnUseBasis`` — enum of where a home's ledger takes its own-use from.
  - ``own_use_basis`` — the one rule of a FinanceConfig's OwnUseBasis.
  - ``with_own_use_basis`` — a FinanceConfig put on a given OwnUseBasis.
  - ``HomeLedger`` — frozen dataclass of one home's year as the CBS bills it,
    refusing a year whose balances L1-L4 break or whose cap disagrees with them.
  - ``home_ledger`` — the one assembly of a HomeLedger, holding every pricing rule.
  - ``bill`` — period-native billing core mapping simulation outputs to a bill.
  - ``householder_bill`` — annual-period wrapper around ``bill``.
  - ``bill_distribution`` — aggregates per-home bills into a BillDistribution.
  - ``annuity_payment`` — level annual payment on a loan.
  - ``npv`` — net present value of cashflows at a discount rate.
  - ``irr`` — internal rate of return of cashflows, nan when undefined.

All monetary values are in GBP (£); energy in kWh.  The model behind these
functions is set out in ``docs/cost-recovery-finance-model.md``.  The
multi-year projection, project economics and cost-recovery solve built on
these bills are in :mod:`solar_challenge.projection`.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Sequence

import pandas as pd

from solar_challenge.dispatch import (
    ANALYSIS_ONLY_FORECASTS,
    GRID_CHARGE_FORECASTS,
    GridChargeForecast,
    distinct_grid_charge_forecasts,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import (
    FlatGridServices,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
)
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    as_finite_float,
    as_whole_number,
    read_field,
)
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.timebase import SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.home import HomeConfig, RunPricing, SummaryStatistics


# ---------------------------------------------------------------------------
# FinanceConfig — financial parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinanceConfig:
    """Financial parameters for community PV/battery project appraisal.

    Holds investor-spreadsheet defaults used to compute project NPV, payback
    period, and per-home savings.
    All monetary values are in nominal GBP or pence; rates are fractional.
    Every number is read through number_fields and held as read: a float or,
    for the two year counts, an int.

    Attributes:
        standing_charge_pence_per_day: Retail grid standing charge (required).
        vat_rate: VAT fraction applied to retail electricity (default 0.05).
        retail_baseline_rate_pence_per_kwh: Grid import unit rate before project
            (default 23.0 p/kWh).
        self_consumption_override: Optional fixed self-consumption fraction
            (0, 1]; if None the simulator uses the modelled value.  When set,
            each home's own-use is min(override × generation, demand), on the
            householder bill and the CBS own-use revenue alike, and the surplus
            generation is counted as export.
        pv_cost_per_kwp_gbp: PV hardware + install cost per kWp (default 1000.0).
        roof_fit_cost_gbp: Fixed per-home roof-fitting cost (default 1000.0).
        battery_cost_per_kwh_gbp: Battery hardware cost per kWh (default 250.0).
        inverter_cost_per_kw_gbp: Inverter capex cost per kW of effective (AC) inverter
            capacity (default 0.0; 0 permitted).
        grant_gbp: Total grant received by the project (default 250000.0; 0 allowed).
        equity_fraction: Fraction of project cost financed by equity (default 0.75).
        loan_term_years: Loan repayment term, a whole number of years (default 15).
            A whole-number float such as 20.0 is held as the int 20; a bool,
            Python's or numpy's, is refused.
        loan_rate: Annual loan interest rate as a fraction (default 0.07).
        opex_per_home_per_year_gbp: Annual operating cost per home (default 131.0).
        asset_life_years: Useful life of the asset, a whole number of years
            (default 25); like loan_term_years, a whole-number float is held as
            the int it equals and a bool is refused.
        own_use_rate_pence_per_kwh: CBS transfer price for self-consumed CBS-owned solar
            (default 15.0 p/kWh; 0 permitted).
        retained_cash_floor_per_home_per_year_gbp: Board-set minimum retained CBS
            surplus per home per year in GBP (default 27.0; 0 permitted).
        grid_services_income_per_kw_per_year_gbp: Exogenous DFS/DNO grid-services income
            per kW of installed battery discharge power per year, net of aggregator share
            (default 0.0; see docs/cost-recovery-finance-model.md §8.1).
        grid_services_model: Grid-services pricing model selector, ``"flat"`` or
            ``"capacity_at_events"``; any other value is refused.  ``"flat"`` uses
            the legacy flat per-kW rate (``grid_services_income_per_kw_per_year_gbp``)
            and refuses a ``grid_services_events`` configuration;
            ``"capacity_at_events"`` uses the structured events-based model configured
            via ``grid_services_events`` and refuses a nonzero flat rate.  Default
            ``"flat"`` leaves all existing behaviour bit-unchanged.
        grid_services_events: Optional :class:`~solar_challenge.gridservices.GridServicesEventsConfig`
            read by ``grid_services_model == "capacity_at_events"``, which refuses
            ``None``; under ``"flat"`` it must be ``None``.  The rule is
            :func:`grid_services_model_of`'s.
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
        """Read every number through number_fields, then refuse an inconsistent grid-services choice or an asset life shorter than the loan term, raising ConfigurationError."""
        read_field(self, "standing_charge_pence_per_day", as_finite_float, POSITIVE)
        read_field(self, "vat_rate", as_finite_float, UNIT_INTERVAL)
        read_field(self, "retail_baseline_rate_pence_per_kwh", as_finite_float, POSITIVE)
        read_field(self, "self_consumption_override", as_finite_float, FRACTION, optional=True)
        read_field(self, "pv_cost_per_kwp_gbp", as_finite_float, POSITIVE)
        read_field(self, "roof_fit_cost_gbp", as_finite_float, POSITIVE)
        read_field(self, "battery_cost_per_kwh_gbp", as_finite_float, POSITIVE)
        read_field(self, "inverter_cost_per_kw_gbp", as_finite_float, NON_NEGATIVE)
        read_field(self, "grant_gbp", as_finite_float, NON_NEGATIVE)
        read_field(self, "equity_fraction", as_finite_float, UNIT_INTERVAL)
        read_field(self, "loan_term_years", as_whole_number, POSITIVE)
        read_field(self, "loan_rate", as_finite_float, NON_NEGATIVE)
        read_field(self, "opex_per_home_per_year_gbp", as_finite_float, POSITIVE)
        read_field(self, "asset_life_years", as_whole_number)
        read_field(self, "own_use_rate_pence_per_kwh", as_finite_float, NON_NEGATIVE)
        read_field(self, "retained_cash_floor_per_home_per_year_gbp", as_finite_float, NON_NEGATIVE)
        read_field(self, "grid_services_income_per_kw_per_year_gbp", as_finite_float, NON_NEGATIVE)
        grid_services_model_of(self)
        if self.asset_life_years < self.loan_term_years:
            raise ConfigurationError(
                f"asset_life_years ({self.asset_life_years}) must be >= "
                f"loan_term_years ({self.loan_term_years})"
            )


def grid_services_model_of(finance: FinanceConfig) -> GridServicesModel:
    """Return the pricing value that *finance*'s three grid-services fields name, refusing a choice that leaves one of them unread.

    The rule is the β column of docs/prds/grid-services-pricing-model.md §5.2,
    which FinanceConfig.__post_init__ runs at construction:

    - ``grid_services_model="flat"`` with ``grid_services_events=None``:
      :class:`~solar_challenge.gridservices.NoGridServices` for a zero
      ``grid_services_income_per_kw_per_year_gbp``, else
      :class:`~solar_challenge.gridservices.FlatGridServices` at that rate.
    - ``"capacity_at_events"`` with ``grid_services_events`` set and a zero
      flat rate: that events configuration.

    Raises:
        ConfigurationError: If the model is ``"flat"`` and
            ``grid_services_events`` is set, if it is ``"capacity_at_events"``
            and ``grid_services_events`` is None or the flat rate is nonzero,
            or if it is neither model.  The message names the fields involved
            and their values.
    """
    model = finance.grid_services_model
    rate = finance.grid_services_income_per_kw_per_year_gbp
    events = finance.grid_services_events
    if model == "flat":
        if events is not None:
            raise ConfigurationError(
                "grid_services_model='flat' does not read grid_services_events, "
                f"got grid_services_events={events!r}; select "
                "grid_services_model='capacity_at_events' or drop grid_services_events"
            )
        if rate == 0.0:
            return NoGridServices()
        return FlatGridServices(rate)
    if model == "capacity_at_events":
        if events is None:
            raise ConfigurationError(
                "grid_services_model='capacity_at_events' requires "
                "grid_services_events to be configured, got grid_services_events=None"
            )
        if rate != 0.0:
            raise ConfigurationError(
                "grid_services_model='capacity_at_events' does not read "
                f"grid_services_income_per_kw_per_year_gbp, got {rate!r}; drop the "
                "rate or select grid_services_model='flat'"
            )
        return events
    raise ConfigurationError(
        f"grid_services_model must be one of flat, capacity_at_events, got {model!r}"
    )


# ---------------------------------------------------------------------------
# BillBreakdown — per-householder line items
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BillBreakdown:
    """One householder's cost-recovery outlay for the billed period, in line items.

    The CBS owns the PV/battery assets and the export MPAN.  The householder
    pays the CBS an own-use rate for self-consumed solar, and pays the retailer
    for grid import and the standing charge.  No SEG credit flows to the
    householder.

    Every figure covers the billed period.  :func:`bill` is the library's
    producer of this type and takes that period as ``period_days``;
    :func:`householder_bill` bills the simulator's homes for a year.  The
    identities between the fields are stated once, in :func:`bill`'s docstring.

    Two overlapping views — never sum across them:

      Whole outlay (what the household spends, and to whom).  The disjoint
      charges are standing_charge_gbp + import_cost_gbp + own_use_payment_gbp;
      all their VAT is in vat_gbp; the headline is total_outlay_gbp.

      CBS-collectable slice (what the CBS invoices).  own_use_payment_gbp plus
      own_use_vat_gbp, totalled in cbs_amount_due_gbp.  Standing charge and
      import are owed to the retailer and stay out of it.

    The slice is a strict *subset* of the whole: own_use_vat_gbp ⊆ vat_gbp and
    cbs_amount_due_gbp ⊆ total_outlay_gbp.  So a consumer that iterates the
    £-valued fields and adds them up double-counts.  Reconciling the CBS
    invoice means summing exactly {own_use_payment_gbp, own_use_vat_gbp}
    against cbs_amount_due_gbp and reading no other field.

    All monetary values are in GBP (£).
    """

    standing_charge_gbp: float
    """Grid standing charge for the billed period (£, ex-VAT)."""

    import_cost_gbp: float
    """Cost of the billed period's grid import, as the caller priced it (£, ex-VAT)."""

    own_use_payment_gbp: float
    """CBS own-use transfer payment for the solar self-consumed in the billed period (£, ex-VAT).

    This is the community-benefit-society transfer price for CBS-owned solar
    consumed on-site; it is NOT SEG and does not involve the export MPAN.
    """

    vat_gbp: float
    """VAT on the billed period's import, standing charge and own-use payment (£)."""

    total_outlay_gbp: float
    """Total householder outlay for the billed period, VAT included (£): the headline figure.

    No SEG deduction: the export income belongs to the CBS.
    """

    own_use_vat_gbp: float
    """VAT on the own-use payment (£): the part of vat_gbp the CBS invoices."""

    cbs_amount_due_gbp: float
    """What the household pays the CBS for the billed period: own_use_payment_gbp + own_use_vat_gbp (£).

    Import and standing charge are paid to the retailer and are NOT part of
    this figure.  Defined as the float SUM of the two fields above (never
    own_use_payment × (1 + vat_rate)) so a consumer summing the line floats
    reproduces this total exactly.
    """

    self_consumption_saving_gbp: float
    """Value of the solar used on-site in the billed period, net of its own-use price (£, VAT-inclusive).

    Each self-consumed kWh is valued at the gap between the baseline's effective
    import rate (``eff_rate`` in :func:`bill`'s identities) and the own-use
    rate.  This is the price-gap benefit, not the full avoided-import value, and
    is zero when the two rates are equal.
    """

    baseline_bill_gbp: float
    """Hypothetical bill for the billed period without any solar / battery system (£, VAT-inclusive).

    The caller's cost of importing all demand (:func:`bill`'s
    ``baseline_import_cost_gbp``) plus the standing charge.
    """

    saving_vs_baseline_gbp: float
    """The billed period's saving against the no-solar baseline bill (£)."""

    saving_pct: float
    """saving_vs_baseline_gbp as a percentage of baseline_bill_gbp."""

    self_consumption_fraction: float
    """Fraction of the billed period's PV generation consumed on-site (dimensionless, 0–1)."""

    def __post_init__(self) -> None:
        """Enforce the CBS-slice identity for every producer, not just bill().

        :func:`bill` builds cbs_amount_due_gbp as exactly this float sum, but
        the class is public and constructible by anyone — test fixtures, and
        consumer scaffolding in the platform repo.  A consumer reconciling the
        per-line floats against the stated total (the platform's R2 seam) must
        never be handed a breakdown where they disagree.

        Bare equality, not a tolerance: the identity is exact float addition by
        construction, and the fields must stay ``fields()``-visible for the
        generic dataclass walk in ``web.field_tree`` to serialise them, so a
        derived ``@property`` is not an option.
        """
        expected = self.own_use_payment_gbp + self.own_use_vat_gbp
        if self.cbs_amount_due_gbp != expected:
            raise ValueError(
                f"cbs_amount_due_gbp must be the float sum own_use_payment_gbp "
                f"+ own_use_vat_gbp ({self.own_use_payment_gbp!r} + "
                f"{self.own_use_vat_gbp!r} = {expected!r}), got "
                f"{self.cbs_amount_due_gbp!r}"
            )


# ---------------------------------------------------------------------------
# BillDistribution — fleet-level statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BillDistribution:
    """Fleet-wide distribution of per-home annual bills.

    ``representative`` is the BillBreakdown of the home whose total_outlay_gbp
    is closest to the median (median-total-outlay home).  Per-home outlay values
    are stored as an immutable tuple so the dataclass remains hashable.
    """

    representative: BillBreakdown
    """Representative (median-total-outlay) home's full BillBreakdown."""

    per_home_total_outlay_gbp: tuple[float, ...]
    """Per-home total annual outlay (£), the ``total_outlay_gbp`` of each home."""

    min_gbp: float
    """Minimum total annual outlay across the fleet (£)."""

    mean_gbp: float
    """Mean total annual outlay across the fleet (£)."""

    median_gbp: float
    """Median total annual outlay across the fleet (£)."""

    max_gbp: float
    """Maximum total annual outlay across the fleet (£)."""

    annualised_from: SimulationWindow
    """The window the yearly figures were annualised from: the summaries' one window."""

    grid_charge_forecasts: tuple[GridChargeForecast, ...] = ()
    """The forecasts that sized the homes' grid charge (dispatch.distinct_grid_charge_forecasts), () when none grid-charged."""

    def __post_init__(self) -> None:
        """Refuse an annualised_from that is not a SimulationWindow."""
        if not isinstance(self.annualised_from, SimulationWindow):
            raise ValueError(
                "BillDistribution's annualised_from is the SimulationWindow its yearly figures were annualised "
                f"from, which bill_distribution takes from the summaries: got annualised_from={self.annualised_from!r}"
            )


# ---------------------------------------------------------------------------
# CostRecoverySolution — the cost-recovery solve's output
# ---------------------------------------------------------------------------

#: Allowed string values for :attr:`CostRecoverySolution.binding`.
_BINDING_VALUES: tuple[str, ...] = (
    "floor",
    "rate_clamped_zero",
    "infeasible_above_retail",
)


@dataclass(frozen=True)
class CostRecoverySolution:
    """Result of :func:`solar_challenge.projection.solve_cost_recovery_rate` — the solved cost-recovery own-use rate.

    The CBS charges householders ``own_use_rate_pence_per_kwh`` for every kWh of
    CBS-owned solar consumed on-site.
    :func:`solar_challenge.projection.solve_cost_recovery_rate` finds the
    minimum rate that keeps project net surplus per home ≥
    ``FinanceConfig.retained_cash_floor_per_home_per_year_gbp``.

    **Primary key**: ``representative_outlay_gbp`` (= outlay.representative.total_outlay_gbp)
    is the householder annual outlay at the solved rate for the median-outlay home.
    The discrete-install config sweep (:mod:`solar_challenge.optimize`) uses this
    field to rank configs.

    Attributes:
        own_use_rate_pence_per_kwh: Solved own-use rate (p/kWh, ∈ [0, retail_baseline]).
        outlay: Full fleet-level BillDistribution at the solved rate (age-0 sim).
        representative_outlay_gbp: Representative (median-outlay) home's total annual
            outlay in £.  Must == outlay.representative.total_outlay_gbp.
        net_surplus_per_home_per_year_gbp: Project net surplus per home per year at
            the solved rate (£).  Equals floor to float ε for binding='floor';
            strictly > floor for 'rate_clamped_zero'; < floor for
            'infeasible_above_retail'.
        saving_vs_baseline_gbp: Householder saving vs. no-solar baseline (£)
            at the solved rate.  Must == outlay.representative.saving_vs_baseline_gbp.
        saving_pct: Householder % saving vs. baseline.
            Must == outlay.representative.saving_pct.
        feasible: True when the CBS can meet the retained_cash_floor within
            [0, retail_baseline_rate].  Must == (binding != 'infeasible_above_retail').
        binding: One of 'floor', 'rate_clamped_zero', 'infeasible_above_retail':
            - 'floor': r* ∈ [0, retail] and surplus(r*) == floor to ε.
            - 'rate_clamped_zero': r* < 0 (project over-delivers at r=0);
              rate clamped to 0, surplus > floor.
            - 'infeasible_above_retail': r* > retail; rate clamped to retail,
              surplus < floor; feasible=False.

    Construction refuses a record that breaks any "Must ==" above: each is a
    bare equality, no tolerance, since the solve copies the very value it is
    checked against, and ``__post_init__`` raises a ValueError naming both
    values.
    """

    own_use_rate_pence_per_kwh: float
    """Solved own-use rate charged by CBS to householders (p/kWh, ≥ 0)."""

    outlay: "BillDistribution"
    """Fleet bill distribution at the solved rate, computed from an age-0 simulation."""

    representative_outlay_gbp: float
    """Representative (median-outlay) home's total annual outlay (£, the primary key).

    Refused at construction unless == outlay.representative.total_outlay_gbp.
    """

    net_surplus_per_home_per_year_gbp: float
    """Project net surplus per home per year at the solved rate (£/home/year)."""

    saving_vs_baseline_gbp: float
    """Householder saving vs no-solar baseline at the solved rate (£).

    Refused at construction unless == outlay.representative.saving_vs_baseline_gbp.
    """

    saving_pct: float
    """Householder % saving vs baseline at the solved rate.

    Refused at construction unless == outlay.representative.saving_pct.
    """

    feasible: bool
    """True when the CBS can meet the retained_cash_floor within [0, retail_baseline_rate].

    Refused at construction unless == (binding != 'infeasible_above_retail').
    """

    binding: str
    """Binding constraint: one of 'floor', 'rate_clamped_zero', 'infeasible_above_retail'."""

    def __post_init__(self) -> None:
        if self.binding not in _BINDING_VALUES:
            raise ValueError(
                f"binding must be one of {_BINDING_VALUES!r}, got {self.binding!r}"
            )
        if not 0.0 <= self.own_use_rate_pence_per_kwh < math.inf:
            raise ValueError(
                f"own_use_rate_pence_per_kwh must be >= 0 and finite, "
                f"got {self.own_use_rate_pence_per_kwh!r}"
            )
        expected_feasible = self.binding != "infeasible_above_retail"
        if self.feasible != expected_feasible:
            raise ValueError(
                f"feasible must be binding != 'infeasible_above_retail' "
                f"({expected_feasible!r} for binding={self.binding!r}), "
                f"got feasible={self.feasible!r}"
            )
        representative = self.outlay.representative
        for copy, copied, source, sourced in (
            ("representative_outlay_gbp", self.representative_outlay_gbp,
             "total_outlay_gbp", representative.total_outlay_gbp),
            ("saving_vs_baseline_gbp", self.saving_vs_baseline_gbp,
             "saving_vs_baseline_gbp", representative.saving_vs_baseline_gbp),
            ("saving_pct", self.saving_pct,
             "saving_pct", representative.saving_pct),
        ):
            if copied != sourced:
                raise ValueError(
                    f"{copy} must equal outlay.representative.{source} "
                    f"({sourced!r}), got {copy}={copied!r}"
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


# ---------------------------------------------------------------------------
# The window a bill is computed over (D27 invariant 8)
# ---------------------------------------------------------------------------


def one_window(summaries: Sequence["SummaryStatistics"]) -> SimulationWindow:
    """The one window all of *summaries*, at least one, cover.

    Raises:
        ValueError: If a summary's window differs from the first's, naming the
            first such position and both windows.
    """
    windows = [summary.window for summary in summaries]
    first = windows[0]
    for position, window in enumerate(windows):
        if window != first:
            raise ValueError(
                "summaries billed or projected together cover one window: "
                f"the summary at position {position} covers {window!r}, where the first covers {first!r}"
            )
    return first


# ---------------------------------------------------------------------------
# How a summary's run was priced
# ---------------------------------------------------------------------------


def _summary_pricing(summary: "SummaryStatistics") -> "RunPricing":
    """How *summary*'s run was priced: the rates finance prices its grid flows at.

    Raises:
        ValueError: If its pricing is None, which a hand-built summary or the
            summary of results simulate_home did not make has, naming
            calculate_summary, which copies the results' pricing.
    """
    pricing = summary.pricing
    if pricing is None:
        raise ValueError(
            "finance prices a summary's grid flows by how its run was priced, and this SummaryStatistics' "
            "pricing is None: build it with calculate_summary from simulate_home's results, which record "
            "their pricing, or set pricing to the RunPricing its run was priced at"
        )
    return pricing


def _refuse_an_analysis_only_forecast(forecast: Optional[GridChargeForecast], *, held_as: str) -> None:
    """Refuse *forecast*, which *held_as* names, when it is one of ANALYSIS_ONLY_FORECASTS, which no bill, projection or cost-recovery figure may use.

    The one refusal finance's two checks share: annualise's of a summary, and
    refuse_analysis_only_forecasts' of the homes a projection is about to simulate.

    Raises:
        ConfigurationError: Naming *held_as*, the forecast, why, and the forecasts to run the
            battery's grid_charging under instead.
    """
    if forecast in ANALYSIS_ONLY_FORECASTS:
        board = " or ".join(repr(each) for each in GRID_CHARGE_FORECASTS if each not in ANALYSIS_ONLY_FORECASTS)
        raise ConfigurationError(
            f"finance bills and projects board figures, and {held_as} is {forecast!r}, which reads the run's "
            "own future PV and demand: it is an upper-bound analysis mode board figures never use. Simulate "
            f"the battery's grid_charging with forecast {board} instead"
        )


def refuse_analysis_only_forecasts(homes: Iterable["HomeConfig"]) -> None:
    """Refuse *homes*, before they are simulated, when a home's battery grid-charges by one of ANALYSIS_ONLY_FORECASTS, whose summary annualise would refuse once simulated.

    The projection and its cost-recovery solve call it before their first simulation,
    so a fleet they could not bill is refused before it is simulated.

    Raises:
        ConfigurationError: Naming the first such home's battery_config.grid_charging.forecast,
            the home by its position in *homes*, the forecast, why, and the forecasts to run
            the battery's grid_charging under instead.
    """
    for index, home in enumerate(homes):
        battery = home.battery_config
        if battery is not None and battery.grid_charging is not None:
            _refuse_an_analysis_only_forecast(
                battery.grid_charging.forecast, held_as=f"home {index}'s battery_config.grid_charging.forecast"
            )


# ---------------------------------------------------------------------------
# annualise — the one annualisation rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnualPhysics:
    """A summary's simulated totals scaled to the year of its window, beside the window and how its run was priced.

    Built by :func:`annualise`.  Energy is in kWh a year and the import cost in
    GBP (£) a year.
    """

    window: SimulationWindow
    """The window the summary's totals cover."""
    generation_kwh: float
    """The home's PV generation."""
    demand_kwh: float
    """The home's demand."""
    import_kwh: float
    """The simulated grid import."""
    import_cost_gbp: float
    """What the simulated grid import cost, as its run priced it."""
    export_kwh: float
    """The simulated grid export."""
    battery_discharge_kwh: float
    """The simulated battery discharge."""
    pricing: RunPricing
    """The rates the summary's run was priced at, which its import and export are billed at."""

    @property
    def scale(self) -> float:
        """The window's annualisation_scale, year_days / days: what each window total was multiplied by."""
        return self.window.annualisation_scale


def annualise(summary: "SummaryStatistics") -> AnnualPhysics:
    """Scale *summary*'s energy and import-cost totals to the year of its window, beside the window and how its run was priced.

    The one annualisation rule, and the one place finance reads a summary's
    pricing: :func:`householder_bill` and the projection both
    annualise through here.  Every total is multiplied by the window's
    annualisation_scale, year_days / days, whatever the window's length.

    Raises:
        ValueError: If the summary has no pricing (:func:`_summary_pricing`),
            naming the missing field and calculate_summary, which sets it.
        ConfigurationError: If one of ANALYSIS_ONLY_FORECASTS, perfect_foresight,
            sized the summary's grid charge (:func:`_refuse_an_analysis_only_forecast`):
            it reads the run's own future, so no board figure may use it.
    """
    _refuse_an_analysis_only_forecast(
        summary.grid_charge_forecast, held_as="this SummaryStatistics' grid_charge_forecast"
    )
    window = summary.window
    scale = window.annualisation_scale
    return AnnualPhysics(
        window=window,
        generation_kwh=summary.total_generation_kwh * scale,
        demand_kwh=summary.total_demand_kwh * scale,
        import_kwh=summary.total_grid_import_kwh * scale,
        import_cost_gbp=summary.total_import_cost_gbp * scale,
        export_kwh=summary.total_grid_export_kwh * scale,
        battery_discharge_kwh=summary.total_battery_discharge_kwh * scale,
        pricing=_summary_pricing(summary),
    )


# ---------------------------------------------------------------------------
# HomeLedger — one home's year as the CBS bills it, and its balances L1-L4
# ---------------------------------------------------------------------------

_BALANCE_REL_TOL = 1e-12
"""The relative tolerance of a ledger's balances L2-L4 and of its cap: the float rounding of one subtraction and one scaling, and nothing more."""


def _ledger_refusal(invariant: str, rule: str, values: Mapping[str, object]) -> ValueError:
    """The ValueError for a broken ledger invariant: the *invariant*, its *rule*, then each of *values* as name=value."""
    named = ", ".join(f"{name}={value!r}" for name, value in values.items())
    return ValueError(f"HomeLedger {invariant}: {rule}: got {named}")


def _at_most(lower: float, upper: float) -> bool:
    """Whether *lower* <= *upper*, to the ledger's relative tolerance."""
    return lower <= upper or math.isclose(lower, upper, rel_tol=_BALANCE_REL_TOL)


def _require_finite_and_not_negative(figures: Mapping[str, float]) -> None:
    """L1: refuse every one of *figures*, by name, that is NaN, infinite or negative, in one ValueError."""
    refused = {name: value for name, value in figures.items() if not 0.0 <= value < math.inf}
    if refused:
        raise _ledger_refusal("L1", "every figure is finite and >= 0", refused)


def _require_own_use_within_demand(own_use_name: str, own_use_kwh: float, demand_name: str, demand_kwh: float) -> None:
    """L2: refuse an own-use above the demand, naming both by *own_use_name* and *demand_name*."""
    if not _at_most(own_use_kwh, demand_kwh):
        raise _ledger_refusal(
            "L2",
            f"a home cannot own-use more than it demands, so {own_use_name} <= {demand_name}",
            {own_use_name: own_use_kwh, demand_name: demand_kwh},
        )


def _require_own_use_and_import_cover_demand(*, demand_kwh: float, own_use_kwh: float, import_kwh: float) -> None:
    """L3: refuse a demand above own-use + import, naming all three."""
    if not _at_most(demand_kwh, own_use_kwh + import_kwh):
        raise _ledger_refusal(
            "L3",
            "own-use and import cover demand, so demand_kwh <= own_use_kwh + import_kwh",
            {"demand_kwh": demand_kwh, "own_use_kwh": own_use_kwh, "import_kwh": import_kwh},
        )


def _require_override_split_balances(
    *, generation_kwh: float, demand_kwh: float, own_use_kwh: float, import_kwh: float, export_kwh: float
) -> None:
    """L4: refuse an override split whose own-use and import are not its demand, or whose own-use and export are not its generation, naming that identity's three values."""
    if not math.isclose(own_use_kwh + import_kwh, demand_kwh, rel_tol=_BALANCE_REL_TOL):
        raise _ledger_refusal(
            "L4",
            "the override splits demand into own-use and import, so own_use_kwh + import_kwh == demand_kwh",
            {"own_use_kwh": own_use_kwh, "import_kwh": import_kwh, "demand_kwh": demand_kwh},
        )
    if not math.isclose(own_use_kwh + export_kwh, generation_kwh, rel_tol=_BALANCE_REL_TOL):
        raise _ledger_refusal(
            "L4",
            "the override splits generation into own-use and export, so own_use_kwh + export_kwh == generation_kwh",
            {"own_use_kwh": own_use_kwh, "export_kwh": export_kwh, "generation_kwh": generation_kwh},
        )


def _require_own_use_cap_agrees_with_the_split(
    *, basis: OwnUseBasis, own_use_capped: bool, own_use_kwh: float, demand_kwh: float
) -> None:
    """Refuse an ``own_use_capped`` year that is not on the OVERRIDE basis, or whose own-use is not its demand, naming the values."""
    if not own_use_capped:
        return
    if basis is not OwnUseBasis.OVERRIDE:
        raise _ledger_refusal(
            "own_use_capped",
            "only the override's own-use is capped, so a capped year is on the OVERRIDE basis",
            {"basis": basis, "own_use_capped": own_use_capped},
        )
    if not math.isclose(own_use_kwh, demand_kwh, rel_tol=_BALANCE_REL_TOL):
        raise _ledger_refusal(
            "own_use_capped",
            "a capped own-use is cut to demand, so own_use_kwh == demand_kwh",
            {"own_use_kwh": own_use_kwh, "demand_kwh": demand_kwh},
        )


class OwnUseBasis(Enum):
    """Where a home's ledger takes its own-use from."""

    SIMULATED = auto()
    """From the simulation: basis C, or householder_bill's caller figure; import and export are the simulated flows."""
    OVERRIDE = auto()
    """FinanceConfig.self_consumption_override splits the home's generation and demand."""


def own_use_basis(finance: FinanceConfig) -> OwnUseBasis:
    """The one rule of *finance*'s own-use basis: OVERRIDE when it sets a self_consumption_override, else SIMULATED."""
    return OwnUseBasis.SIMULATED if finance.self_consumption_override is None else OwnUseBasis.OVERRIDE


def with_own_use_basis(finance: FinanceConfig, basis: OwnUseBasis) -> FinanceConfig:
    """*finance* on *basis*, every other field kept, so ``own_use_basis(with_own_use_basis(f, b)) is b``.

    SIMULATED clears the override; OVERRIDE keeps *finance*'s own override, or
    sets DEFAULT_SPREADSHEET_SELF_CONSUMPTION when it has none.
    """
    if basis is OwnUseBasis.SIMULATED:
        return replace(finance, self_consumption_override=None)
    override = finance.self_consumption_override
    return replace(
        finance,
        self_consumption_override=DEFAULT_SPREADSHEET_SELF_CONSUMPTION if override is None else override,
    )


@dataclass(frozen=True)
class HomeLedger:
    """One home's year as the CBS bills it.

    Energy is in kWh a year and money in GBP (£) a year.  Construction refuses
    a year whose balances break, or whose ``own_use_capped`` disagrees with
    them, checked in this order, naming the invariant and every value in it;
    L2-L4 and the cap hold to a relative 1e-12:

    - L1: every figure is finite and >= 0.
    - L2: ``own_use_kwh <= demand_kwh``.
    - L3: ``demand_kwh <= own_use_kwh + import_kwh``: own-use and import cover
      demand.
    - L4, on the OVERRIDE basis only: ``own_use_kwh + import_kwh ==
      demand_kwh`` and ``own_use_kwh + export_kwh == generation_kwh``.
    - ``own_use_capped`` only on the OVERRIDE basis, and then
      ``own_use_kwh == demand_kwh``.
    """

    basis: OwnUseBasis
    """Where the own-use comes from."""
    generation_kwh: float
    """The home's PV generation."""
    demand_kwh: float
    """The home's demand."""
    own_use_kwh: float
    """The own-use the householder pays for and the CBS earns on."""
    import_kwh: float
    """The grid import the householder is billed for."""
    import_cost_gbp: float
    """What that import costs the householder."""
    import_at_retail: bool
    """No tariff priced the home's run, so its import is priced at the retail baseline rate."""
    export_kwh: float
    """The grid export, whose SEG income is the CBS's."""
    seg_income_gbp: float
    """The SEG income the export earns the CBS."""
    own_use_capped: bool
    """OVERRIDE only: override × generation exceeded demand, so own-use was cut to demand."""

    def __post_init__(self) -> None:
        """Refuse a year that breaks L1, L2, L3 or, on the OVERRIDE basis, L4, in that order, then one whose cap disagrees with its split."""
        _require_finite_and_not_negative(
            {
                "generation_kwh": self.generation_kwh,
                "demand_kwh": self.demand_kwh,
                "own_use_kwh": self.own_use_kwh,
                "import_kwh": self.import_kwh,
                "import_cost_gbp": self.import_cost_gbp,
                "export_kwh": self.export_kwh,
                "seg_income_gbp": self.seg_income_gbp,
            }
        )
        _require_own_use_within_demand("own_use_kwh", self.own_use_kwh, "demand_kwh", self.demand_kwh)
        _require_own_use_and_import_cover_demand(
            demand_kwh=self.demand_kwh, own_use_kwh=self.own_use_kwh, import_kwh=self.import_kwh
        )
        if self.basis is OwnUseBasis.OVERRIDE:
            _require_override_split_balances(
                generation_kwh=self.generation_kwh,
                demand_kwh=self.demand_kwh,
                own_use_kwh=self.own_use_kwh,
                import_kwh=self.import_kwh,
                export_kwh=self.export_kwh,
            )
        _require_own_use_cap_agrees_with_the_split(
            basis=self.basis,
            own_use_capped=self.own_use_capped,
            own_use_kwh=self.own_use_kwh,
            demand_kwh=self.demand_kwh,
        )


# ---------------------------------------------------------------------------
# home_ledger — the one assembly of a home's billed year
# ---------------------------------------------------------------------------


def home_ledger(
    physics: AnnualPhysics,
    finance: FinanceConfig,
    *,
    simulated_own_use_kwh: Optional[float] = None,
) -> HomeLedger:
    """One home's year as the CBS bills it, from the home's annual physics.

    The one producer of a :class:`HomeLedger`, holding every pricing rule
    (docs/cost-recovery-finance-model.md §3, One ledger per home):

    * The basis is :func:`own_use_basis` of *finance*.
    * On the SIMULATED basis own-use is *simulated_own_use_kwh*, or basis C,
      demand − import, when it is None (0.0 when the import is above the
      demand), and import and export are the simulated flows.
    * On the OVERRIDE basis own-use is
      min(override × generation, demand), import is demand − own-use and
      export generation − own-use; ``own_use_capped`` when override ×
      generation exceeded demand.
    * Import cost: when no tariff priced the run, import × the retail
      baseline rate on either basis (``import_at_retail``); else the simulated
      import cost on the SIMULATED basis, and on the OVERRIDE basis the run's
      own price per kWh imported, or the tariff's time-weighted mean rate when
      the run imported nothing.
    * SEG income: the export at the run's SEG rate, priced by
      :func:`~solar_challenge.seg.calculate_seg_revenue`, or 0.0 when no SEG
      tariff priced the run.

    It warns about nothing: :func:`householder_bill` warns its caller about
    an import at retail and a capped own-use.

    Args:
        physics: The home's annual physics (:func:`annualise`).
        finance: The override and the retail baseline rate it reads.
        simulated_own_use_kwh: The home's own-use over the physics' year for
            the SIMULATED basis.  Checked on either basis, though the override
            does not read it.

    Raises:
        ValueError: If *simulated_own_use_kwh* is negative or not finite (L1)
            or above the demand (L2), naming it; if the ledger breaks L1-L4,
            naming the invariant and its values; or if the billed export at a
            SEG rate is negative, which calculate_seg_revenue refuses.
    """
    if simulated_own_use_kwh is not None:
        _require_finite_and_not_negative({"simulated_own_use_kwh": simulated_own_use_kwh})
        _require_own_use_within_demand("simulated_own_use_kwh", simulated_own_use_kwh, "demand_kwh", physics.demand_kwh)
    basis = own_use_basis(finance)
    if basis is OwnUseBasis.SIMULATED:
        if simulated_own_use_kwh is None:
            own_use_kwh, _ = _basis_c_kwh(physics.demand_kwh, physics.import_kwh)
        else:
            own_use_kwh = simulated_own_use_kwh
        import_kwh, export_kwh, own_use_capped = physics.import_kwh, physics.export_kwh, False
    else:
        override = finance.self_consumption_override
        if override is None:
            raise ValueError(
                f"self_consumption_override is None on the {basis.name} basis, "
                "which own_use_basis gives only a finance that sets one"
            )
        implied_own_use_kwh = override * physics.generation_kwh
        own_use_kwh = min(implied_own_use_kwh, physics.demand_kwh)
        import_kwh = physics.demand_kwh - own_use_kwh
        export_kwh = physics.generation_kwh - own_use_kwh
        own_use_capped = implied_own_use_kwh > physics.demand_kwh
    seg_rate_pence_per_kwh = physics.pricing.seg_rate_pence_per_kwh
    seg_income_gbp = (
        0.0
        if seg_rate_pence_per_kwh is None
        else calculate_seg_revenue(export_kwh, SEGTariff(name="", rate_pence_per_kwh=seg_rate_pence_per_kwh))
    )
    return HomeLedger(
        basis=basis,
        generation_kwh=physics.generation_kwh,
        demand_kwh=physics.demand_kwh,
        own_use_kwh=own_use_kwh,
        import_kwh=import_kwh,
        import_cost_gbp=_ledger_import_cost_gbp(physics, basis, import_kwh, finance),
        import_at_retail=physics.pricing.import_tariff_mean_rate_gbp_per_kwh is None,
        export_kwh=export_kwh,
        seg_income_gbp=seg_income_gbp,
        own_use_capped=own_use_capped,
    )


def _ledger_import_cost_gbp(
    physics: AnnualPhysics, basis: OwnUseBasis, import_kwh: float, finance: FinanceConfig
) -> float:
    """The £ of *import_kwh*, a ledger's import on *basis*, at the price *physics*' run was priced at (:func:`home_ledger`'s import-cost rule)."""
    tariff_mean_rate_gbp_per_kwh = physics.pricing.import_tariff_mean_rate_gbp_per_kwh
    if tariff_mean_rate_gbp_per_kwh is None:
        return import_kwh * finance.retail_baseline_rate_pence_per_kwh / 100.0
    if basis is OwnUseBasis.SIMULATED:
        return physics.import_cost_gbp
    if physics.import_kwh > 0.0:
        return import_kwh * (physics.import_cost_gbp / physics.import_kwh)
    return import_kwh * tariff_mean_rate_gbp_per_kwh


# ---------------------------------------------------------------------------
# Basis C — demand − import, clamped at 0 (docs/cost-recovery-finance-model.md §2)
# ---------------------------------------------------------------------------


def _basis_c_kwh(demand_kwh: float, import_kwh: float) -> tuple[float, bool]:
    """Basis-C own-use, demand − import, and whether it was clamped to 0.0 because the import is above the demand.

    The one basis-C rule, which :func:`home_ledger` and
    :func:`basis_c_own_use_kwh` both read.  A NaN difference is kept, not
    clamped as ``max(0.0, nan)`` would, so the ledger's L1 names it.
    """
    delta_kwh = demand_kwh - import_kwh
    if delta_kwh < 0.0:
        return 0.0, True
    return delta_kwh, False


def basis_c_own_use_kwh(summary: "SummaryStatistics") -> float:
    """Basis-C own-use energy over the summary's window, for CBS cost-recovery accounting (kWh).

    Basis C: own-use = consumption − import = CBS-supplied energy consumed.
    This equals the energy that did NOT cross the grid boundary in the
    consumption direction, i.e. the CBS-originated energy actually used by
    the home.

    Arbitrage-immune: grid-charged battery discharge inflates
    ``total_self_consumption_kwh`` (B-style: min(direct + discharge, demand))
    but does NOT inflate ``total_demand_kwh − total_grid_import_kwh`` because
    the grid-charged energy is counted in ``total_grid_import_kwh``.  The CBS
    bears the battery round-trip loss (absorbed into the headline own-use rate).

    Clamps to 0.0 when import > demand and emits a ``UserWarning``.  This
    condition should not occur in real simulations (it implies net import
    exceeds total household demand, which is physically impossible under normal
    dispatch); when it does arise it indicates a dispatch/accounting bug and
    silently zeroing would mask it.

    Args:
        summary: Per-home simulation output; uses
            ``total_demand_kwh`` and ``total_grid_import_kwh``.

    Returns:
        Basis-C own-use energy in kWh (≥ 0.0).
    """
    demand_kwh, import_kwh = summary.total_demand_kwh, summary.total_grid_import_kwh
    own_use_kwh, clamped = _basis_c_kwh(demand_kwh, import_kwh)
    if clamped:
        warnings.warn(
            f"Basis-C own-use is negative for a home "
            f"(demand={demand_kwh:.3f} kWh, "
            f"import={import_kwh:.3f} kWh, "
            f"delta={demand_kwh - import_kwh:.3f} kWh); clamped to 0.0. "
            f"This likely indicates a dispatch/accounting bug in the simulation "
            f"(import > demand is physically impossible under normal operation).",
            UserWarning,
            stacklevel=2,
        )
    return own_use_kwh


# ---------------------------------------------------------------------------
# bill() — period-native billing core
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

    This is the single source of truth for the BillBreakdown identities
    (docs/cost-recovery-finance-model.md §3).
    It performs **no** annualisation, no re-pricing of import energy, and emits
    no warnings — all of that belongs in the caller (e.g. :func:`householder_bill`
    for the simulator's annual wrapper).

    Identities:
      standing_charge_gbp   = standing_pence_per_day × period_days / 100
      own_use_payment_gbp   = own_use_rate × self_consumption_kwh / 100
      vat_gbp               = vat_rate × (import_cost + standing + own_use_payment)
      total_outlay_gbp      = (import_cost + standing + own_use_payment) × (1 + vat_rate)
      own_use_vat_gbp       = vat_rate × own_use_payment
      cbs_amount_due_gbp    = own_use_payment + own_use_vat_gbp
      baseline_bill_gbp     = (baseline_import_cost + standing) × (1 + vat_rate)
      eff_rate              = baseline_import_cost / demand_kwh × 100  (fallback to retail when demand==0)
      self_consumption_saving_gbp = sc × (eff_rate − own_use_rate) × (1 + vat_rate) / 100
      saving_vs_baseline_gbp = baseline_bill − total_outlay
      saving_pct            = 100 × saving / baseline  (0.0 when baseline==0)
      self_consumption_fraction = sc / generation  (0.0 when generation==0; model doc §3)

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

    # --- CBS-collectable slice (own-use payment plus its VAT) ---
    own_use_vat_gbp = vat_rate * own_use_payment_gbp
    cbs_amount_due_gbp = own_use_payment_gbp + own_use_vat_gbp

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
        own_use_vat_gbp=float(own_use_vat_gbp),
        cbs_amount_due_gbp=float(cbs_amount_due_gbp),
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
    window_self_consumption_kwh: float,
    finance: "FinanceConfig",
) -> BillBreakdown:
    """Annual cost-recovery bill wrapper for simulator outputs.

    This is the **annual wrapper** over :func:`bill` that bills a summary's
    window, whatever its length, as the window's year: the window carries the
    days it covers (INV-8).  All bill arithmetic (identities, VAT, savings)
    lives in :func:`bill` — the single source of truth.

    Responsibilities of this wrapper (not in bill()):
      * Refuse a *window_self_consumption_kwh* outside 0 to the summary's
        ``total_demand_kwh``, on either basis, with the ledger's L1 and L2
        checks, before it is scaled, so the refusal names the caller's figure.
      * Build the home's ledger, ``home_ledger(annualise(summary), finance,
        simulated_own_use_kwh=window_self_consumption_kwh × scale)``: the
        window's totals × its annualisation_scale, year_days / days, own-use
        and import on the physics or override basis, and the import priced as
        the summary's run was priced (docs/cost-recovery-finance-model.md §3,
        One ledger per home).  The projection sums the same
        ledgers.
      * Warn, with a :class:`UserWarning`, when the ledger prices the import
        at retail because no tariff priced the run, whatever it imported, and
        when the override's own-use is capped at demand.
      * Price the no-solar baseline at the retail rate (demand × retail / 100),
        so bill()'s effective rate, and with it self_consumption_saving, is
        the retail rate.
      * Bill the standing charge over the window's year_days
        (bill(period_days=window.year_days, ...)): 365 or 366 for a window
        within one calendar year, 365.25 for one that crosses a new year.

    Board identity (docs/cost-recovery-finance-model.md §3; holds when import is retail-priced, import_kwh = demand − sc):
      saving_vs_baseline == sc × (retail − own_use) × (1+vat) / 100

    Args:
        summary: Per-home simulation output (read-only), carrying the window
            its totals cover.
        window_self_consumption_kwh: The home's own-use over the summary's
            window (kWh), from 0 to its ``total_demand_kwh``, billed scaled by
            the window's annualisation_scale when
            ``finance.self_consumption_override`` is None.  Ignored when an
            override is set, though still checked: own-use then comes from the
            override, generation and demand.
        finance: FinanceConfig with tariff + assumption parameters.

    Returns:
        A fully computed, frozen BillBreakdown (delegated to :func:`bill`).

    Raises:
        ValueError: If *window_self_consumption_kwh* is negative or not
            finite (L1), or above the summary's ``total_demand_kwh`` (L2), on
            either basis, naming the invariant and the figures as passed; if
            the summary has no pricing, naming calculate_summary
            (:func:`_summary_pricing`); or if the home's ledger refuses its
            year, naming the invariant and its values, such as an own-use that
            with the import does not cover the demand (L3) (:class:`HomeLedger`).
        ConfigurationError: If the perfect_foresight forecast sized the
            summary's grid charge, as :func:`annualise` refuses it.
    """
    _require_finite_and_not_negative({"window_self_consumption_kwh": window_self_consumption_kwh})
    _require_own_use_within_demand(
        "window_self_consumption_kwh", window_self_consumption_kwh, "total_demand_kwh", summary.total_demand_kwh
    )
    physics = annualise(summary)
    ledger = home_ledger(physics, finance, simulated_own_use_kwh=window_self_consumption_kwh * physics.scale)
    retail_rate_pence = finance.retail_baseline_rate_pence_per_kwh
    if ledger.import_at_retail:
        warnings.warn(
            f"This home's simulated grid import ({physics.import_kwh:.1f} kWh/yr) "
            f"has a £0 cost (no tariff configured on this home), so its import "
            f"rate falls back to the retail baseline rate "
            f"({retail_rate_pence:.1f} p/kWh).",
            UserWarning,
            stacklevel=2,
        )
    if ledger.own_use_capped:
        warnings.warn(
            f"self_consumption_override={finance.self_consumption_override:g} implies more own-use than "
            f"this home's demand; own-use is capped at demand and the surplus "
            f"generation is counted as export.",
            UserWarning,
            stacklevel=2,
        )
    return bill(
        period_days=physics.window.year_days,
        generation_kwh=ledger.generation_kwh,
        demand_kwh=ledger.demand_kwh,
        self_consumption_kwh=ledger.own_use_kwh,
        import_kwh=ledger.import_kwh,
        import_cost_gbp=ledger.import_cost_gbp,
        baseline_import_cost_gbp=ledger.demand_kwh * retail_rate_pence / 100.0,
        finance=finance,
    )


# ---------------------------------------------------------------------------
# bill_distribution
# ---------------------------------------------------------------------------


def bill_distribution(
    summaries: Sequence["SummaryStatistics"],
    finance: "FinanceConfig",
) -> BillDistribution:
    """Aggregate per-home bills into a fleet-level BillDistribution.

    Maps ``householder_bill`` over each home's SummaryStatistics, each billed
    over the summaries' one window, which carries the days it covers (INV-8),
    selects the median-**total-outlay** home as representative, and computes
    min / mean / median / max via ``pd.Series`` (mirroring
    ``calculate_fleet_summary``).

    Args:
        summaries: Sequence of per-home SummaryStatistics over one window.
            Must contain at least one entry; an empty sequence raises
            ``ValueError``.
        finance: Common FinanceConfig for all homes.

    Returns:
        A BillDistribution with representative and per-home statistics, the
        window they were annualised from and the forecasts that sized the
        homes' grid charge.

    Raises:
        ValueError: If ``summaries`` is empty; if the summaries cover
            different windows, naming the first position whose window differs
            and both windows; or if a summary has no pricing, naming
            calculate_summary.
        ConfigurationError: If the perfect_foresight forecast sized a
            summary's grid charge, as :func:`annualise` refuses it.
    """
    if not summaries:
        raise ValueError("bill_distribution requires at least one summary")
    window = one_window(summaries)

    bills = [
        householder_bill(
            summary=s,
            # Basis C (docs/cost-recovery-finance-model.md §2), the physics own-use
            # the projection bills too; home_ledger replaces it with the
            # override's own-use when one is set.
            window_self_consumption_kwh=basis_c_own_use_kwh(s),
            finance=finance,
        )
        for s in summaries
    ]
    # Key the distribution on total_outlay_gbp
    outlays = [b.total_outlay_gbp for b in bills]
    series = pd.Series(outlays, dtype=float)

    median_val = float(series.median())
    # Representative: home whose total outlay is closest to the median
    rep_idx = int((series - median_val).abs().idxmin())

    return BillDistribution(
        representative=bills[rep_idx],
        per_home_total_outlay_gbp=tuple(outlays),
        min_gbp=float(series.min()),
        mean_gbp=float(series.mean()),
        median_gbp=median_val,
        max_gbp=float(series.max()),
        annualised_from=window,
        grid_charge_forecasts=distinct_grid_charge_forecasts(
            summary.grid_charge_forecast for summary in summaries
        ),
    )


# ---------------------------------------------------------------------------
# Cash-flow maths — annuity, NPV, IRR
# ---------------------------------------------------------------------------


def annuity_payment(principal: float, rate: float, n_years: int) -> float:
    """Compute the level annual payment on a loan (closed-form annuity).

    Args:
        principal: Loan principal (£).
        rate: Annual interest rate as a fraction (e.g., 0.07 for 7%), finite
            and above -1.
        n_years: Loan term in years, at least 1.

    Returns:
        Annual level payment (£).  When rate == 0 returns principal / n_years.

    Raises:
        ValueError: If *n_years* is below 1, or *rate* is not finite or is at
            or below -1, naming it and its value.
    """
    if n_years < 1:
        raise ValueError(f"annuity_payment repays a loan over at least one year: got n_years={n_years!r}")
    if not -1.0 < rate < math.inf:
        raise ValueError(f"annuity_payment's rate is a finite annual fraction above -1: got rate={rate!r}")
    if principal == 0.0:
        return 0.0
    if rate == 0.0:
        return principal / n_years
    return principal * rate / (1.0 - (1.0 + rate) ** (-n_years))


def npv(rate: float, cashflows: Sequence[float]) -> float:
    """Compute NPV of cashflows discounted at *rate*.

    cashflows[0] is the t=0 outflow (negative equity), cashflows[1..N] are
    inflows at t=1..N.

    Args:
        rate: Discount rate as a fraction.
        cashflows: Cash flows starting at t=0.

    Returns:
        Net present value (£).
    """
    total = 0.0
    for t, cf in enumerate(cashflows):
        total += cf / (1.0 + rate) ** t
    return total


def irr(cashflows: Sequence[float]) -> float:
    """Internal rate of return via NPV bisection root-find.

    Finds *r* such that npv(r, cashflows) ≈ 0.  Returns float('nan') when the
    IRR is undefined: no cashflows, cashflows[0] == 0 (no equity invested), or
    no sign change of the NPV in its bracket of -50% to +10000%
    (non-conventional or never-profitable cashflows).

    Args:
        cashflows: Cash flows starting at t=0; cashflows[0] is typically −equity (negative).

    Returns:
        IRR as a fraction, or float('nan') if undefined.
    """
    if not cashflows or cashflows[0] == 0.0:
        return float("nan")

    # Bracket: search within [-50%, +10000%]; upper end is capped high so
    # very profitable low-equity projects (where true IRR >> 500%) are still
    # captured rather than returning nan.
    lo, hi = -0.5, 100.0
    npv_lo = npv(lo, cashflows)
    npv_hi = npv(hi, cashflows)

    if npv_lo * npv_hi > 0.0:
        # No sign change in bracket → IRR undefined
        return float("nan")

    # Bisect to tolerance
    tol = 1e-10
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        npv_mid = npv(mid, cashflows)
        if abs(npv_mid) < tol or (hi - lo) < tol:
            return mid
        if npv_lo * npv_mid <= 0.0:
            hi = mid
            npv_hi = npv_mid
        else:
            lo = mid
            npv_lo = npv_mid

    return 0.5 * (lo + hi)
