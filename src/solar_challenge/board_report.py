# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board's markdown reports: `finance run`'s finance report and `optimize configs`' config ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping, Optional, Sequence, TypeVar

from solar_challenge.dispatch import distinct_grid_charge_forecasts
from solar_challenge.finance import (
    BillBreakdown,
    BillDistribution,
    CostRecoverySolution,
    FinanceConfig,
    OwnUseBasis,
    own_use_basis,
)
from solar_challenge.flex import FlexibilityValueBand, resolve_flex_band
from solar_challenge.gridservices import (
    DeliveryBaseline,
    FlatGridServices,
    GridServicesAtEvents,
    GridServicesBand,
    GridServicesEventsConfig,
)
from solar_challenge.output import grid_charge_forecast_notice
from solar_challenge.timebase import SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.optimize import ConfigPoint, RankedSweep, SensitivityPanel
    from solar_challenge.projection import FleetProjection, ProjectEconomics


def _extrapolation_notice(window: SimulationWindow) -> str:
    """The paragraph, ending in a blank line, that tells the board a report's yearly figures are extrapolated from *window*; empty when *window* runs from 1 January to 31 December."""
    if not window.extrapolated:
        return ""
    return (
        f"*Yearly figures are extrapolated ×{window.annualisation_scale:.3f} from a "
        f"{window.days}-day window ({window.first_day.isoformat()} to {window.last_day.isoformat()}), "
        "not whole calendar years.*\n\n"
    )


def _one_window_figure(per_window: tuple[float, ...], unit: str) -> str:
    """*per_window*'s figure with its *unit* when it holds one event window's, else "—": summed over windows, a reliability capacity or a per-event mean describes no set of event days."""
    return f"{per_window[0]:.1f} {unit}" if len(per_window) == 1 else "—"


_BINDING_LABELS: Mapping[str, str] = {
    "floor": "✔ Surplus meets floor",
    "rate_clamped_zero": "✔ Over-feasible (rate clamped to 0, surplus > floor)",
    "infeasible_above_retail": "✘ INFEASIBLE: required rate exceeds retail",
}


def _binding_label(binding: str) -> str:
    """The board's label for a cost-recovery *binding*.

    Raises:
        ValueError: Naming *binding* and the bindings that have a label, when it has none.
    """
    if binding not in _BINDING_LABELS:
        raise ValueError(f"a cost-recovery binding is one of {tuple(_BINDING_LABELS)}, got {binding!r}")
    return _BINDING_LABELS[binding]


def _fmt_dscr(val: float) -> str:
    """Format DSCR: inf → '∞', otherwise '{val:.2f}×'."""
    return "∞" if math.isinf(val) else f"{val:.2f}×"


def _fmt_irr(val: float) -> str:
    """Format IRR: NaN → 'n/a', otherwise '{val:.1%}'."""
    return "n/a" if math.isnan(val) else f"{val:.1%}"


def _fmt_payback(val: "Optional[float]") -> str:
    """Format payback: None → '—', otherwise '{val:.1f} yr'."""
    return "—" if val is None else f"{val:.1f} yr"


def _config_label(config: "ConfigPoint") -> str:
    """The board's label for an install *config*: its PV, battery and inverter sizes."""
    return f"{config.pv_kwp:.1f} kWp / {config.battery_kwh:.1f} kWh / {config.inverter_kw:.1f} kW"


@dataclass(frozen=True)
class AssumptionSection:
    """One own-use assumption's figures in the finance report, every one computed under its ``finance``.

    ``own_use_basis(finance)`` is the section's mode; the report renders the
    section as that mode's column of each of its tables.
    """

    finance: FinanceConfig
    """The finance configuration every figure of the section was computed under."""
    bill: BillDistribution
    """The fleet's bills under ``finance``."""
    projection: Optional[FleetProjection] = None
    """The fleet's multi-year projection under ``finance``, when one was run."""
    economics: Optional[ProjectEconomics] = None
    """The project economics of that projection, when asked for."""
    cost_recovery: Optional[CostRecoverySolution] = None
    """The cost-recovery solve under ``finance``, when asked for."""


ASSUMPTION_LABELS: Mapping[OwnUseBasis, str] = {
    OwnUseBasis.SIMULATED: "Physics",
    OwnUseBasis.OVERRIDE: "Spreadsheet",
}
"""The word that heads a finance report's column of each own-use basis."""


def _column_label(section: AssumptionSection) -> str:
    """The header of *section*'s column: its basis's label, then the self-consumption its finance overrides, when it sets one."""
    label = ASSUMPTION_LABELS[own_use_basis(section.finance)]
    override = section.finance.self_consumption_override
    return label if override is None else f"{label} ({override * 100:g}% self-consumption)"


def _computations_carried(section: AssumptionSection) -> tuple[str, ...]:
    """The names of the computations *section* carries beside its bill, of projection, economics and cost_recovery."""
    computations = {
        "projection": section.projection,
        "economics": section.economics,
        "cost_recovery": section.cost_recovery,
    }
    return tuple(name for name, computation in computations.items() if computation is not None)


def _refuse_unrenderable_sections(sections: Mapping[OwnUseBasis, AssumptionSection]) -> None:
    """Refuse *sections* a finance report cannot render (PRD §5.2's R1-R4).

    Raises:
        ValueError: Checked in this order, naming the values: R1, *sections* is
            empty; R2, a key is not the own_use_basis of its section's finance;
            R3, the sections carry different computations; R4, their bills are
            annualised from different windows.
    """
    if not sections:
        raise ValueError(f"a finance report renders at least one section, got {dict(sections)!r}")
    for key, section in sections.items():
        basis = own_use_basis(section.finance)
        if key is not basis:
            raise ValueError(
                f"the section keyed {key.name} has a finance on the {basis.name} basis, "
                f"self_consumption_override={section.finance.self_consumption_override!r}"
            )
    carried = {key.name: _computations_carried(section) for key, section in sections.items()}
    if len(set(carried.values())) > 1:
        raise ValueError(f"every section of a finance report carries the same computations, got {carried!r}")
    windows = {key.name: section.bill.annualised_from for key, section in sections.items()}
    first_window, *other_windows = windows.values()
    if any(window != first_window for window in other_windows):
        raise ValueError(f"every bill of a finance report is annualised from one window, got {windows!r}")


@dataclass(frozen=True)
class GridServicesIncome:
    """What the scenario's grid-services pricing books on the bill run's fleet, the same under every assumption mode.

    Construction refuses, naming the rule and the values, a figure the pricing
    could not have printed.
    """

    pricing: FlatGridServices | GridServicesEventsConfig
    """The pricing that booked the income."""
    annual_income_gbp: float
    """The fleet's grid-services income (£/yr), as ``pricing`` priced the bill run's fleet; finite and ≥ 0."""
    battery_homes: int
    """How many of the fleet's homes have a battery; ≥ 0."""
    battery_discharge_kw: float
    """Σ max_discharge_kw of those batteries (kW); finite, and > 0 exactly when there is a battery home."""
    at_events: Optional[GridServicesAtEvents] = None
    """The capacity-at-events breakdown the income is, under events pricing; None under flat pricing."""

    def __post_init__(self) -> None:
        """Refuse another pricing, a figure out of range, and an income its pricing did not book, in that order."""
        self._refuse_another_pricing()
        self._refuse_figures_out_of_range()
        self._refuse_an_income_its_pricing_did_not_book()

    def _refuse_another_pricing(self) -> None:
        """Refuse a pricing other than flat or events pricing, and a breakdown its pricing does not make or one it lacks."""
        if not isinstance(self.pricing, (FlatGridServices, GridServicesEventsConfig)):
            raise ValueError(
                "GridServicesIncome is booked by a FlatGridServices or a GridServicesEventsConfig "
                f"(NoGridServices books nothing): got pricing={self.pricing!r}"
            )
        if isinstance(self.pricing, FlatGridServices) and self.at_events is not None:
            raise ValueError(
                "GridServicesIncome's at_events is the capacity-at-events breakdown, which flat pricing does "
                f"not make: got pricing={self.pricing!r} with at_events={self.at_events!r}"
            )
        if isinstance(self.pricing, GridServicesEventsConfig) and self.at_events is None:
            raise ValueError(
                "GridServicesIncome under events pricing carries the capacity-at-events breakdown its income is: "
                f"got pricing={self.pricing!r} with at_events=None"
            )

    def _refuse_figures_out_of_range(self) -> None:
        """Refuse a figure out of range, an income with no battery home, and kW without battery homes or homes without kW."""
        refused = [
            f"{name}={value!r}"
            for name, value in (
                ("annual_income_gbp", self.annual_income_gbp),
                ("battery_discharge_kw", self.battery_discharge_kw),
            )
            if not 0.0 <= value < math.inf
        ]
        if self.battery_homes < 0:
            refused.append(f"battery_homes={self.battery_homes!r}")
        if refused:
            raise ValueError(
                "GridServicesIncome's annual_income_gbp and battery_discharge_kw are each finite and at least 0, "
                f"and its battery_homes at least 0: got {', '.join(refused)}"
            )
        if self.annual_income_gbp > 0.0 and self.battery_homes == 0:
            raise ValueError(
                "GridServicesIncome books income only on battery homes: "
                f"got annual_income_gbp={self.annual_income_gbp!r} with battery_homes=0"
            )
        if (self.battery_discharge_kw > 0.0) != (self.battery_homes > 0):
            raise ValueError(
                "GridServicesIncome's battery_discharge_kw is > 0 exactly when battery_homes is, every battery "
                f"discharging at a positive max_discharge_kw: got battery_homes={self.battery_homes!r} "
                f"with battery_discharge_kw={self.battery_discharge_kw!r}"
            )

    def _refuse_an_income_its_pricing_did_not_book(self) -> None:
        """Refuse an events income other than its breakdown's, and a flat income other than the rate × the battery kW."""
        if self.at_events is not None and self.annual_income_gbp != self.at_events.annual_income_gbp:
            raise ValueError(
                "GridServicesIncome's annual_income_gbp under events pricing is its at_events' annual_income_gbp, "
                f"{self.at_events.annual_income_gbp!r}, got {self.annual_income_gbp!r}"
            )
        if isinstance(self.pricing, FlatGridServices):
            rate = self.pricing.income_per_kw_per_year_gbp
            booked = rate * self.battery_discharge_kw
            if not math.isclose(self.annual_income_gbp, booked):
                raise ValueError(
                    "GridServicesIncome's annual_income_gbp under flat pricing is income_per_kw_per_year_gbp × "
                    f"battery_discharge_kw, {rate!r} × {self.battery_discharge_kw!r} = {booked!r}, "
                    f"got {self.annual_income_gbp!r}"
                )

    @property
    def per_battery_home_gbp(self) -> Optional[float]:
        """The income per battery home (£/yr); None for a fleet with no battery home."""
        return self.annual_income_gbp / self.battery_homes if self.battery_homes else None

    @property
    def per_discharge_kw_gbp(self) -> Optional[float]:
        """The income per kW of battery discharge (£/kW-yr); None for a fleet with no battery home."""
        return self.annual_income_gbp / self.battery_discharge_kw if self.battery_homes else None


_Value = TypeVar("_Value")

_Rows = tuple[tuple[str, Callable[[_Value], str]], ...]
"""A table's rows: each its label, and the formatter of its cell from one column's value."""

_BILL_ROWS: _Rows[BillBreakdown] = (
    ("Standing Charge", lambda rep: f"£{rep.standing_charge_gbp:.2f}"),
    ("Import Cost", lambda rep: f"£{rep.import_cost_gbp:.2f}"),
    ("Own-Use Payment", lambda rep: f"£{rep.own_use_payment_gbp:.2f}"),
    ("VAT", lambda rep: f"£{rep.vat_gbp:.2f}"),
    ("**Total Outlay**", lambda rep: f"**£{rep.total_outlay_gbp:.2f}**"),
    ("Self-Consumption Saving", lambda rep: f"£{rep.self_consumption_saving_gbp:.2f}"),
    ("Baseline Bill (no solar)", lambda rep: f"£{rep.baseline_bill_gbp:.2f}"),
    ("Saving vs Baseline", lambda rep: f"£{rep.saving_vs_baseline_gbp:.2f} ({rep.saving_pct:.1f}%)"),
    ("Self-Consumption Fraction", lambda rep: f"{rep.self_consumption_fraction:.1%}"),
)
"""The representative householder bill's line items."""

_DISTRIBUTION_ROWS: _Rows[BillDistribution] = (
    ("Min", lambda bills: f"£{bills.min_gbp:.2f}"),
    ("Mean", lambda bills: f"£{bills.mean_gbp:.2f}"),
    ("Median", lambda bills: f"£{bills.median_gbp:.2f}"),
    ("Max", lambda bills: f"£{bills.max_gbp:.2f}"),
)
"""A fleet's per-home total annual outlays: the bills', and the outlay at the solved rate."""

_ECONOMICS_ROWS: _Rows[ProjectEconomics] = (
    ("Total CapEx", lambda economics: f"£{economics.total_capex_gbp:,.0f}"),
    ("Grant", lambda economics: f"£{economics.grant_gbp:,.0f}"),
    ("Debt", lambda economics: f"£{economics.debt_gbp:,.0f}"),
    ("Equity", lambda economics: f"£{economics.equity_gbp:,.0f}"),
    ("Annual Debt Service", lambda economics: f"£{economics.annual_debt_service_gbp:,.0f}"),
    ("Fleet OpEx / yr", lambda economics: f"£{economics.fleet_opex_gbp:,.0f}"),
    ("Mean Fleet Surplus / yr", lambda economics: f"£{economics.mean_fleet_surplus_per_year_gbp:,.0f}"),
    ("Net Surplus / home / yr", lambda economics: f"£{economics.net_surplus_per_home_per_year_gbp:,.0f}"),
    ("Min DSCR (loan years)", lambda economics: _fmt_dscr(economics.min_dscr)),
    ("Equity IRR", lambda economics: _fmt_irr(economics.equity_irr)),
    ("Payback", lambda economics: _fmt_payback(economics.payback_years)),
)
"""The project economics."""

_COST_RECOVERY_ROWS: _Rows[CostRecoverySolution] = (
    ("Solved Own-Use Rate", lambda solution: f"{solution.own_use_rate_pence_per_kwh:.2f} p/kWh"),
    ("Representative Householder Outlay", lambda solution: f"£{solution.representative_outlay_gbp:.2f}"),
    ("Saving vs Baseline", lambda solution: f"£{solution.saving_vs_baseline_gbp:.2f} ({solution.saving_pct:.1f}%)"),
    ("CBS Net Surplus / home / yr", lambda solution: f"£{solution.net_surplus_per_home_per_year_gbp:.2f}"),
    ("Feasibility", lambda solution: _binding_label(solution.binding)),
)
"""The cost-recovery solve."""


def _markdown_row(cells: Sequence[str]) -> str:
    """The markdown table row of *cells*."""
    return "| " + " | ".join(cells) + " |"


def _table(
    heading: str, first_header: str, labels: Sequence[str], rows: _Rows[_Value], values: Sequence[_Value]
) -> str:
    """*heading* over a table of *rows* whose label column is headed *first_header*: one value column per value of *values*, headed by *labels*, each cell its row's formatter of that value."""
    lines = [
        heading,
        "",
        _markdown_row([first_header, *labels]),
        "|" + "|".join("---" for _ in range(len(labels) + 1)) + "|",
        *(_markdown_row([label, *(cell(value) for value in values)]) for label, cell in rows),
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class FlexBlock:
    """The finance report's flexibility-value block, for one grid-services uncertainty band."""

    band: GridServicesBand
    """The band whose consulting figures the block shows."""

    def __post_init__(self) -> None:
        """Hold band as the GridServicesBand it names, raising ConfigurationError, naming the value, for one naming no band."""
        object.__setattr__(self, "band", GridServicesBand.parse(self.band, what="FlexBlock.band"))

    @property
    def consulting(self) -> FlexibilityValueBand:
        """The band's consulting figures, as :func:`~solar_challenge.flex.resolve_flex_band` reads them."""
        return resolve_flex_band(self.band)


def _model_line(pricing: FlatGridServices | GridServicesEventsConfig) -> str:
    """*pricing*'s model as the board reads it: the events model with its band and delivery baseline, or the flat rate."""
    if isinstance(pricing, FlatGridServices):
        return f"flat, £{pricing.income_per_kw_per_year_gbp:.1f}/kW-yr"
    band = GridServicesBand.parse(pricing.band, what="GridServicesEventsConfig.band")
    baseline = DeliveryBaseline.parse(pricing.delivery_baseline, what="GridServicesEventsConfig.delivery_baseline")
    return f"capacity at events, {band} band, {baseline} delivery baseline"


def _refuse_projections_over_different_asset_lives(sections: Sequence[AssumptionSection]) -> int:
    """The years every section's projection spans, which label the booked rows.

    Raises:
        ValueError: Naming each mode's years, when the projections span different asset lives.
    """
    years = {
        own_use_basis(section.finance).name: len(section.projection.curve.points)
        for section in sections
        if section.projection is not None
    }
    if len(set(years.values())) != 1:
        raise ValueError(
            f"the booked grid-services rows are labelled from one asset life, so every section's projection "
            f"spans the same years, got {years!r}"
        )
    (asset_life,) = set(years.values())
    return asset_life


def _booked_table(sections: Sequence[AssumptionSection], labels: Sequence[str]) -> str:
    """The grid-services income each section's projection booked at year 1 and at its last year, one column per section."""
    asset_life = _refuse_projections_over_different_asset_lives(sections)
    rows: _Rows[FleetProjection] = (
        ("Year 1", lambda projection: f"£{projection.grid_services_income_gbp[0][1]:,.0f}"),
        (f"Year {asset_life}", lambda projection: f"£{projection.grid_services_income_gbp[-1][1]:,.0f}"),
    )
    projections = [section.projection for section in sections if section.projection is not None]
    return _table("### Booked by the projection (£ a year)", "Year", labels, rows, projections)


_FLEET_INCOME_ROWS: _Rows[GridServicesIncome] = (
    ("Annual fleet income", lambda income: f"£{income.annual_income_gbp:,.0f}"),
)
"""This window's fleet income, under every pricing."""

def _at_events(income: GridServicesIncome) -> GridServicesAtEvents:
    """*income*'s capacity-at-events breakdown.

    Raises:
        ValueError: Naming the pricing, when it is flat, which makes no breakdown.
    """
    if income.at_events is None:
        raise ValueError(f"only events pricing makes a capacity-at-events breakdown, got pricing={income.pricing!r}")
    return income.at_events


_AT_EVENTS_ROWS: _Rows[GridServicesIncome] = (
    ("Per-event available capacity", lambda income: _one_window_figure(_at_events(income).per_window_avail_kw, "kW")),
    (
        "Capacity on 50% of event days",
        lambda income: _one_window_figure(_at_events(income).per_window_avail_p50_kw, "kW"),
    ),
    (
        "Capacity on 90% of event days",
        lambda income: _one_window_figure(_at_events(income).per_window_avail_p90_kw, "kW"),
    ),
    (
        "Evening self-use displaced, per event",
        lambda income: _one_window_figure(_at_events(income).per_window_displaced_self_use_kwh_per_event, "kWh"),
    ),
    (
        "Evening self-use displaced, value per year",
        lambda income: f"£{sum(_at_events(income).per_window_displaced_import_gbp_per_year):,.0f}",
    ),
)
"""Under events pricing, this window's capacity-at-events breakdown, after its fleet income."""


def _window_table(grid_services: GridServicesIncome) -> str:
    """This window's fleet income, then under events pricing its breakdown and the notes that read it."""
    events = grid_services.at_events
    rows = _FLEET_INCOME_ROWS if events is None else _FLEET_INCOME_ROWS + _AT_EVENTS_ROWS
    table = _table("### This window's fleet, the same under every assumption", "Metric", ["Value"], rows, [grid_services])
    if events is None:
        return table
    notes = (
        "\n*The income is gross of the evening self-use an event displaces, which householders then import; it "
        "is not netted off. That import is valued at each home's simulated tariff, £0 for a home simulated "
        "without one.*\n"
    )
    if len(events.per_window_avail_kw) > 1:
        notes += "\n*— is one event window's figure, which does not sum over several windows.*\n"
    return table + notes


def _grid_services_section(
    grid_services: GridServicesIncome, sections: Sequence[AssumptionSection], labels: Sequence[str]
) -> str:
    """The Grid Services Income section: the pricing's model, each section's booked income when they carry projections, and this window's fleet."""
    parts = [f"## Grid Services Income\n\nModel: **{_model_line(grid_services.pricing)}**\n"]
    if any(section.projection is not None for section in sections):
        parts.append(_booked_table(sections, labels))
    parts.append(_window_table(grid_services))
    return "\n".join(parts)


def _flexibility_value_block(flex: FlexBlock, grid_services: Optional[GridServicesIncome]) -> str:
    """The flexibility-value block for *flex*'s band: its grid-services row the income *grid_services* books, or the band's consulting figure, not booked, with none."""
    consulting = flex.consulting
    if grid_services is None:
        grid_services_row = _markdown_row(
            [
                "Grid services (consulting planning band, not booked: the scenario prices no grid services)",
                f"£{consulting.grid_services_per_home_gbp:.0f}",
                f"£{consulting.grid_services_per_kw_gbp:.1f}/kW",
            ]
        )
        headline_gbp = consulting.total_gbp
        sourced = "Figures"
        grid_services_basis = f"Grid-services rate: £{consulting.grid_services_per_kw_gbp:.1f}/kW-discharge/yr"
    else:
        per_home = grid_services.per_battery_home_gbp
        per_kw = grid_services.per_discharge_kw_gbp
        grid_services_row = _markdown_row(
            [
                "Grid services (booked)",
                "—" if per_home is None else f"£{per_home:.0f}",
                "—" if per_kw is None else f"£{per_kw:.1f}/kW",
            ]
        )
        headline_gbp = consulting.time_shift_gbp + (0.0 if per_home is None else per_home)
        sourced = "Time-shift"
        grid_services_basis = (
            "Grid services: what the scenario's pricing books on this window's\n"
            "fleet, per battery home and per kW of battery discharge"
        )
    return f"""
## Flexibility Value (per battery home)

Band: **{flex.band}**

| Revenue Stream | Per Home / yr | Per kW / yr |
|----------------|---------------|-------------|
| Time-shift (arbitrage) | £{consulting.time_shift_gbp:.0f} | — |
{grid_services_row}
| **Headline total** | **£{headline_gbp:.0f}** | — |

*{sourced} from consulting model §1.1/§1.4; band = {flex.band}.
Time-shift basis: net import-cost reduction (off-peak charge cost captured in
grid_import). {grid_services_basis}
(docs/flexibility-buildability.md).*
"""


def generate_finance_report(
    sections: Mapping[OwnUseBasis, AssumptionSection],
    *,
    scenario_name: str = "",
    grid_services: Optional[GridServicesIncome] = None,
    flex: Optional[FlexBlock] = None,
) -> str:
    """The markdown finance report of *sections*: each bill, economics and cost-recovery table one value column per own-use basis.

    Each of those tables has one value column per section, in OwnUseBasis
    order whatever *sections*' order, headed by its basis's label in
    ASSUMPTION_LABELS and, when the section's finance sets a self-consumption
    override, the override, e.g. ``Spreadsheet (70% self-consumption)``.  No
    heading names a mode.

    The blocks, in order: the representative householder bill's line items
    (standing charge, import cost, own-use payment, VAT, total outlay,
    self-consumption saving, baseline bill, saving, self-consumption
    fraction); the per-home bill distribution (min / mean / median / max);
    when the sections carry economics, the project economics; when
    *grid_services* is given, the Grid Services Income section; when they
    carry a cost-recovery solve, the cost-recovery analysis and the per-home
    outlay at the solved rate; and, when *flex* is given, the flexibility
    value, which no mode changes, so it renders once.

    The Grid Services Income section names the pricing's model (the events
    model with its band and delivery baseline, or the flat rate); when the
    sections carry projections, the income each one booked at year 1 and at
    its last year, one column per section; and this window's fleet, the same
    under every assumption, in one table: its annual fleet income and, under
    events pricing, the per-event available capacity, the capacity on 50% and
    on 90% of event days and the evening self-use an event displaces, one
    window's figures, shown for a single window and as — for several, that
    self-use's value per year, summed over the windows, and a note that the
    income is gross of it, valued at £0 for a home simulated without a tariff.

    The flexibility-value block shows the band's consulting time-shift.  Its
    grid-services row is *grid_services*' income per battery home and per kW
    of battery discharge (— for a fleet with no battery home), its headline
    the time-shift plus that income per home; with no *grid_services* it is
    the band's consulting figure, labelled not booked, under the band's
    consulting headline.

    When the bills' one window is not whole calendar years, the report opens,
    under its title, with one notice that its yearly figures are extrapolated
    from that window.  When forecasts sized any section's grid charge
    (``bill.grid_charge_forecasts``), one notice naming each, and what it is,
    follows.

    Args:
        sections: One AssumptionSection per own-use basis the report renders,
            keyed by the own_use_basis of its finance.
        scenario_name: Optional scenario label for the report title.
        grid_services: What the scenario's grid-services pricing books on the
            bill run's fleet; None (default) when it prices none, which omits
            the Grid Services Income section.
        flex: The flexibility-value block's band; None (default) omits it.

    Returns:
        A markdown-formatted finance report string.

    Raises:
        ValueError: Naming the values, checked in this order: R1, *sections*
            is empty; R2, a key is not the own_use_basis of its section's
            finance; R3, the sections carry different computations of
            projection, economics and cost_recovery; R4, their bills are
            annualised from different windows.  Also when a cost-recovery
            binding has no label, naming it; and, with *grid_services*, when
            the sections' projections span different asset lives, naming each
            mode's years.
    """
    _refuse_unrenderable_sections(sections)
    ordered = [sections[basis] for basis in OwnUseBasis if basis in sections]
    window = ordered[0].bill.annualised_from
    labels = [_column_label(section) for section in ordered]
    title = f"# Finance Report: {scenario_name}" if scenario_name else "# Finance Report"
    notice = _extrapolation_notice(window) + grid_charge_forecast_notice(
        distinct_grid_charge_forecasts(
            forecast for section in ordered for forecast in section.bill.grid_charge_forecasts
        )
    )
    blocks = [
        _table("## Householder Bill", "Line Item", labels, _BILL_ROWS, [s.bill.representative for s in ordered]),
        _table(
            "## Per-Home Bill Distribution (Total Annual Outlay, £)",
            "Metric",
            labels,
            _DISTRIBUTION_ROWS,
            [section.bill for section in ordered],
        ),
    ]
    economics = [section.economics for section in ordered if section.economics is not None]
    if economics:
        blocks.append(_table("## Project Economics", "Item", labels, _ECONOMICS_ROWS, economics))
    if grid_services is not None:
        blocks.append(_grid_services_section(grid_services, ordered, labels))
    solutions = [section.cost_recovery for section in ordered if section.cost_recovery is not None]
    if solutions:
        blocks.append(_table("## Cost-Recovery Analysis", "Item", labels, _COST_RECOVERY_ROWS, solutions))
        blocks.append(
            _table(
                "## Per-Home Total Outlay at Solved Rate (£)",
                "Metric",
                labels,
                _DISTRIBUTION_ROWS,
                [solution.outlay for solution in solutions],
            )
        )
    report = f"{title}\n\n{notice}" + "\n".join(blocks)
    if flex is not None:
        report += _flexibility_value_block(flex, grid_services)
    return report


def generate_config_ranking_report(
    ranked: "RankedSweep",
    panel: "Optional[SensitivityPanel]" = None,
) -> str:
    """Generate the board-readable config-ranking report.

    Renders two markdown tables and an optional sensitivity section:

    - **Table 1 — Cost-Recovery Rank**: one row per feasible config in
      ``ranked.results``, sorted ascending by ``representative_outlay_gbp``.
      The cheapest feasible config (``results[0]``) is flagged as the
      RECOMMENDATION.  Infeasible configs (``ranked.infeasible``) appear in a
      separate section (dims only — economics are not retained for infeasible
      configs; see :class:`~solar_challenge.optimize.RankedSweep`).
    - **Table 2 — Configured-Rate Trade-Off**: one row per feasible config →
      the configured own-use rate it was priced at, the baseline outlay and
      CBS surplus at that rate, and a Pareto flag.  Infeasible configs are
      omitted from this table because
      :class:`~solar_challenge.optimize.RankedSweep` retains them only as
      :class:`~solar_challenge.optimize.ConfigPoint` objects without baseline
      economics; they remain visible in Table 1's infeasible list.
    - **Sensitivity section** (rendered only when ``panel`` is not ``None``):
      per-axis sub-tables and the panel-level ``rank_stability``.

    When the feasible configs' bills are annualised from a window that is not
    whole calendar years (``results[0].solution.outlay.annualised_from``), the
    report opens, under its first heading, with a notice that its yearly figures
    are extrapolated from that window. When forecasts sized the homes' grid
    charge (``results[0].solution.outlay.grid_charge_forecasts``), a notice
    naming each, and what it is, follows.

    Args:
        ranked: Aggregated sweep output from :func:`~solar_challenge.optimize.run_sweep`.
        panel: Optional OAT sensitivity panel from
            :func:`~solar_challenge.optimize.sensitivity_panel`; omitted
            (``None``) to produce just the two-table output.

    Returns:
        A markdown-formatted string suitable for console output or file export.

    Raises:
        ValueError: When a feasible config's binding has no label, naming it.
    """
    # ---- Table 1: COST-RECOVERY RANK ----------------------------------------
    report = "## Cost-Recovery Rank\n\n"

    if not ranked.results:
        report += "*No feasible configurations found.*\n"
    else:
        outlay = ranked.results[0].solution.outlay
        report += _extrapolation_notice(outlay.annualised_from)
        report += grid_charge_forecast_notice(outlay.grid_charge_forecasts)
        report += (
            "| Config | Solved Rate (p/kWh) | Rep Outlay (£) | "
            "Min/Mean/Median/Max (£) | CBS Surplus (£/home/yr) | "
            "Feasibility | Total CapEx (£) | Min DSCR | Equity IRR | Payback |\n"
        )
        report += (
            "|--------|--------------------:|---------------:|"
            "------------------------|------------------------:|"
            "------------|----------------:|----------|-----------|----------|\n"
        )
        for i, cr in enumerate(ranked.results):
            cp = cr.config
            label = _config_label(cp)
            if i == 0:
                label += " ★ RECOMMENDATION"
            sol = cr.solution
            dist_str = (
                f"£{sol.outlay.min_gbp:.0f} / £{sol.outlay.mean_gbp:.0f} / "
                f"£{sol.outlay.median_gbp:.0f} / £{sol.outlay.max_gbp:.0f}"
            )
            binding_label = _binding_label(cr.binding)
            report += (
                f"| {label} "
                f"| {cr.solved_own_use_rate_pence_per_kwh:.2f} p/kWh "
                f"| £{cr.representative_outlay_gbp:.2f} "
                f"| {dist_str} "
                f"| £{cr.surplus_at_solved_gbp:.2f} "
                f"| {binding_label} "
                f"| £{cr.total_capex_gbp:,.0f} "
                f"| {_fmt_dscr(cr.min_dscr)} "
                f"| {_fmt_irr(cr.equity_irr)} "
                f"| {_fmt_payback(cr.payback_years)} |\n"
            )

    if ranked.infeasible:
        report += "\n### Infeasible Configurations\n\n"
        report += "| Config | Binding |\n"
        report += "|--------|---------|\n"
        for cp in ranked.infeasible:
            label = _config_label(cp)
            report += f"| {label} | {_binding_label('infeasible_above_retail')} |\n"

    # ---- Table 2: CONFIGURED-RATE TRADE-OFF ----------------------------------
    # Infeasible configs are omitted from Table 2 because RankedSweep retains them
    # only as ConfigPoints without baseline_outlay/baseline_surplus economics; they
    # remain visible in Table 1's infeasible list above.
    report += "\n## Configured-Rate Trade-Off\n\n"
    if not ranked.results:
        report += "*No feasible configurations to compare.*\n"
    else:
        pareto_set = set(ranked.pareto_baseline)
        report += (
            "| Config | Configured Rate (p/kWh) | Baseline Outlay (£/yr) | "
            "Baseline CBS Surplus (£/home/yr) | Pareto |\n"
        )
        report += (
            "|--------|------------------------:|----------------------:|"
            "--------------------------------:|--------|\n"
        )
        for cr in ranked.results:
            cp = cr.config
            label = _config_label(cp)
            pareto_flag = "✔ Pareto" if cp in pareto_set else "—"
            report += (
                f"| {label} "
                f"| {cr.baseline_own_use_rate_pence_per_kwh:.2f} p/kWh "
                f"| £{cr.baseline_outlay_gbp:.2f} "
                f"| £{cr.baseline_surplus_per_home_gbp:.2f} "
                f"| {pareto_flag} |\n"
            )

    # ---- Optional sensitivity section ----------------------------------------
    if panel is not None:
        report += "\n## Sensitivity Analysis\n\n"
        report += f"Rank stability: **{panel.rank_stability:.1%}** "
        report += "(fraction of swept values where cheapest config == baseline top)\n\n"
        report += f"Baseline top config: {_config_label(panel.baseline_top)}\n"

        for axis in panel.axes:
            report += f"\n### Axis: {axis.name}\n\n"
            report += "| Value | Top Config |\n"
            report += "|------:|-----------|\n"
            for val, top in zip(axis.values, axis.top_config_per_value):
                if top is None:
                    top_str = "—"
                else:
                    top_str = _config_label(top)
                report += f"| {val:.2f} | {top_str} |\n"

    return report
