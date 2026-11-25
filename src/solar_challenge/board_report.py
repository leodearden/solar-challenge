# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board's markdown reports: `finance run`'s finance report and `optimize configs`' config ranking."""

import math
from typing import TYPE_CHECKING, Mapping, Optional

from solar_challenge.output import grid_charge_forecast_notice
from solar_challenge.timebase import SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.finance import BillDistribution, CostRecoverySolution
    from solar_challenge.flex import FlexibilityValueBand
    from solar_challenge.gridservices import GridServicesAtEvents
    from solar_challenge.optimize import RankedSweep, SensitivityPanel
    from solar_challenge.projection import ProjectEconomics


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


def generate_finance_report(
    bill_physics: "BillDistribution",
    bill_spreadsheet: Optional["BillDistribution"] = None,
    *,
    scenario_name: str = "",
    economics: Optional["ProjectEconomics"] = None,
    cost_recovery: Optional["CostRecoverySolution"] = None,
    flex_band: Optional["FlexibilityValueBand"] = None,
    flex_band_name: str = "",
    grid_services_at_events: Optional["GridServicesAtEvents"] = None,
) -> str:
    """Generate a markdown finance report from one or two BillDistributions.

    Renders the representative householder bill line items (standing charge,
    import cost, VAT, gross bill, SEG export income, self-consumption saving,
    net annual bill, saving %) and a per-home distribution table
    (min / mean / median / max).

    When ``bill_spreadsheet`` is provided the report includes side-by-side
    Physics vs Spreadsheet columns (the ``--assumptions both`` surface).

    When ``bill_physics.annualised_from`` is not whole calendar years, the
    report opens, under its title, with a notice that its yearly figures are
    extrapolated from that window. When forecasts sized the homes' grid charge
    (``bill_physics.grid_charge_forecasts``), a notice naming each, and what it
    is, follows.

    Args:
        bill_physics: BillDistribution from the physics self-consumption path.
        bill_spreadsheet: Optional BillDistribution from the spreadsheet
            (override) path; when supplied both are rendered side by side.
        scenario_name: Optional scenario label for the report title.
        economics: Optional :class:`~solar_challenge.projection.ProjectEconomics`
            from :func:`~solar_challenge.projection.project_economics`; when
            provided, a ``## Project Economics`` block is appended after the
            bill block; ``None`` (default) omits it.
        cost_recovery: Optional :class:`~solar_challenge.finance.CostRecoverySolution`
            from :func:`~solar_challenge.projection.solve_cost_recovery_rate`; when
            provided, a ``## Cost-Recovery Analysis`` block is appended;
            ``None`` (default) omits it.
        flex_band: Optional :class:`~solar_challenge.flex.FlexibilityValueBand`
            from :func:`~solar_challenge.flex.resolve_flex_band`; when provided,
            a ``## Flexibility Value (per battery home)`` block is appended
            showing the per-battery-home time-shift saving and grid-services
            figures for the named band; ``None`` (default) omits it.
        flex_band_name: Optional human-readable label for the flexibility band
            (e.g. ``"central"``); used in the report header.  Ignored when
            ``flex_band`` is ``None``.
        grid_services_at_events: Optional
            :class:`~solar_challenge.gridservices.GridServicesAtEvents` from
            :func:`~solar_challenge.gridservices.compute_grid_services_at_events`;
            when provided (and ``flex_band`` is also set), renders a
            "Grid services (capacity-at-events)" sub-section inside the
            flexibility-value block showing the event-derived annual fleet
            income and the per-event available capacity, each summed over the
            event windows; the capacity on 50% and on 90% of event days and the
            evening self-use an event displaces, one window's figures, shown
            for a single window and as — for several; that self-use's value per
            year, summed over the windows; and a note that the income is gross
            of that self-use, valued at £0 for a home simulated without a
            tariff.  ``None`` (default) omits it.

    Returns:
        A markdown-formatted finance report string.
    """
    title = (
        f"# Finance Report: {scenario_name}"
        if scenario_name
        else "# Finance Report"
    )

    rep = bill_physics.representative
    notice = _extrapolation_notice(bill_physics.annualised_from) + grid_charge_forecast_notice(
        bill_physics.grid_charge_forecasts
    )

    if bill_spreadsheet is None:
        # ---- Physics-only path (own-use payment + total outlay; no SEG) --
        report = f"""{title}

{notice}## Householder Bill (Physics Assumptions)

| Line Item | Value |
|-----------|-------|
| Standing Charge | £{rep.standing_charge_gbp:.2f} |
| Import Cost | £{rep.import_cost_gbp:.2f} |
| Own-Use Payment | £{rep.own_use_payment_gbp:.2f} |
| VAT | £{rep.vat_gbp:.2f} |
| **Total Outlay** | **£{rep.total_outlay_gbp:.2f}** |
| Self-Consumption Saving | £{rep.self_consumption_saving_gbp:.2f} |
| Baseline Bill (no solar) | £{rep.baseline_bill_gbp:.2f} |
| Saving vs Baseline | £{rep.saving_vs_baseline_gbp:.2f} ({rep.saving_pct:.1f}%) |
| Self-Consumption Fraction | {rep.self_consumption_fraction:.1%} |

## Per-Home Bill Distribution (Total Annual Outlay, £)

| Metric | Value |
|--------|-------|
| Min | £{bill_physics.min_gbp:.2f} |
| Mean | £{bill_physics.mean_gbp:.2f} |
| Median | £{bill_physics.median_gbp:.2f} |
| Max | £{bill_physics.max_gbp:.2f} |
"""
    else:
        # ---- Physics vs Spreadsheet side-by-side --------------------
        rep_s = bill_spreadsheet.representative
        report = f"""{title}

{notice}## Householder Bill — Physics vs Spreadsheet Assumptions

| Line Item | Physics | Spreadsheet |
|-----------|---------|-------------|
| Standing Charge | £{rep.standing_charge_gbp:.2f} | £{rep_s.standing_charge_gbp:.2f} |
| Import Cost | £{rep.import_cost_gbp:.2f} | £{rep_s.import_cost_gbp:.2f} |
| Own-Use Payment | £{rep.own_use_payment_gbp:.2f} | £{rep_s.own_use_payment_gbp:.2f} |
| VAT | £{rep.vat_gbp:.2f} | £{rep_s.vat_gbp:.2f} |
| **Total Outlay** | **£{rep.total_outlay_gbp:.2f}** | **£{rep_s.total_outlay_gbp:.2f}** |
| Self-Consumption Saving | £{rep.self_consumption_saving_gbp:.2f} | £{rep_s.self_consumption_saving_gbp:.2f} |
| Baseline Bill (no solar) | £{rep.baseline_bill_gbp:.2f} | £{rep_s.baseline_bill_gbp:.2f} |
| Saving vs Baseline | £{rep.saving_vs_baseline_gbp:.2f} ({rep.saving_pct:.1f}%) | £{rep_s.saving_vs_baseline_gbp:.2f} ({rep_s.saving_pct:.1f}%) |
| Self-Consumption Fraction | {rep.self_consumption_fraction:.1%} | {rep_s.self_consumption_fraction:.1%} |

## Per-Home Bill Distribution (Total Annual Outlay, £)

| Metric | Physics | Spreadsheet |
|--------|---------|-------------|
| Min | £{bill_physics.min_gbp:.2f} | £{bill_spreadsheet.min_gbp:.2f} |
| Mean | £{bill_physics.mean_gbp:.2f} | £{bill_spreadsheet.mean_gbp:.2f} |
| Median | £{bill_physics.median_gbp:.2f} | £{bill_spreadsheet.median_gbp:.2f} |
| Max | £{bill_physics.max_gbp:.2f} | £{bill_spreadsheet.max_gbp:.2f} |
"""

    # ---- Optional project-economics block --------------------------------
    if economics is not None:
        # Format IRR: NaN → "n/a"
        if math.isnan(economics.equity_irr):
            irr_str = "n/a"
        else:
            irr_str = f"{economics.equity_irr:.1%}"

        # Format payback: None → "—"
        payback_str = (
            "—" if economics.payback_years is None
            else f"{economics.payback_years:.1f} yr"
        )

        # Format min DSCR: inf → "∞"
        if math.isinf(economics.min_dscr):
            dscr_str = "∞"
        else:
            dscr_str = f"{economics.min_dscr:.2f}×"

        report += f"""
## Project Economics

| Item | Value |
|------|-------|
| Total CapEx | £{economics.total_capex_gbp:,.0f} |
| Grant | £{economics.grant_gbp:,.0f} |
| Debt | £{economics.debt_gbp:,.0f} |
| Equity | £{economics.equity_gbp:,.0f} |
| Annual Debt Service | £{economics.annual_debt_service_gbp:,.0f} |
| Fleet OpEx / yr | £{economics.fleet_opex_gbp:,.0f} |
| Mean Fleet Surplus / yr | £{economics.mean_fleet_surplus_per_year_gbp:,.0f} |
| Net Surplus / home / yr | £{economics.net_surplus_per_home_per_year_gbp:,.0f} |
| Min DSCR (loan years) | {dscr_str} |
| Equity IRR | {irr_str} |
| Payback | {payback_str} |
"""

    # ---- Optional cost-recovery block ----------------------------------
    if cost_recovery is not None:
        # Human-readable binding/feasibility label
        if cost_recovery.binding == "floor":
            binding_label = "✔ Surplus meets floor"
        elif cost_recovery.binding == "rate_clamped_zero":
            binding_label = "✔ Over-feasible (rate clamped to 0, surplus > floor)"
        else:  # infeasible_above_retail
            binding_label = "✘ INFEASIBLE: required rate exceeds retail"

        cr = cost_recovery
        report += f"""
## Cost-Recovery Analysis

| Item | Value |
|------|-------|
| Solved Own-Use Rate | {cr.own_use_rate_pence_per_kwh:.2f} p/kWh |
| Representative Householder Outlay | £{cr.representative_outlay_gbp:.2f} |
| Saving vs Baseline | £{cr.saving_vs_baseline_gbp:.2f} ({cr.saving_pct:.1f}%) |
| CBS Net Surplus / home / yr | £{cr.net_surplus_per_home_per_year_gbp:.2f} |
| Feasibility | {binding_label} |

## Per-Home Total Outlay at Solved Rate (£)

| Metric | Value |
|--------|-------|
| Min | £{cr.outlay.min_gbp:.2f} |
| Mean | £{cr.outlay.mean_gbp:.2f} |
| Median | £{cr.outlay.median_gbp:.2f} |
| Max | £{cr.outlay.max_gbp:.2f} |
"""

    # ---- Optional flexibility-value block ----------------------------
    if flex_band is not None:
        band_label = flex_band_name if flex_band_name else "—"
        report += f"""
## Flexibility Value (per battery home)

Band: **{band_label}**

| Revenue Stream | Per Home / yr | Per kW / yr |
|----------------|---------------|-------------|
| Time-shift (arbitrage) | £{flex_band.time_shift_gbp:.0f} | — |
| Grid services (firm flex) | £{flex_band.grid_services_per_home_gbp:.0f} | £{flex_band.grid_services_per_kw_gbp:.1f}/kW |
| **Headline total** | **£{flex_band.total_gbp:.0f}** | — |

*Figures from consulting model §1.1/§1.4; band = {band_label}.
Time-shift basis: net import-cost reduction (off-peak charge cost captured in
grid_import). Grid-services rate: £{flex_band.grid_services_per_kw_gbp:.1f}/kW-discharge/yr
(PRD §6).*
"""
        # Optional capacity-at-events sub-section
        if grid_services_at_events is not None:
            events = grid_services_at_events
            per_window_note = (
                ""
                if len(events.per_window_avail_kw) == 1
                else "\n*— is one event window's figure, which does not sum over several windows.*\n"
            )
            report += f"""
**Grid services (capacity-at-events)**

| Metric | Value |
|--------|-------|
| Annual fleet income | £{events.annual_income_gbp:,.0f} |
| Per-event available capacity | {sum(events.per_window_avail_kw):.1f} kW |
| Capacity on 50% of event days | {_one_window_figure(events.per_window_avail_p50_kw, "kW")} |
| Capacity on 90% of event days | {_one_window_figure(events.per_window_avail_p90_kw, "kW")} |
| Evening self-use displaced, per event | {_one_window_figure(events.per_window_displaced_self_use_kwh_per_event, "kWh")} |
| Evening self-use displaced, value per year | £{sum(events.per_window_displaced_import_gbp_per_year):,.0f} |

*The income is gross of the evening self-use an event displaces, which householders then import; it is not netted off. That import is valued at each home's simulated tariff, £0 for a home simulated without one.*
{per_window_note}"""

    return report


_BINDING_LABELS: Mapping[str, str] = {
    "floor": "✔ Surplus meets floor",
    "rate_clamped_zero": "✔ Over-feasible (rate clamped to 0, surplus > floor)",
    "infeasible_above_retail": "✘ INFEASIBLE: required rate exceeds retail",
}


def _fmt_dscr(val: float) -> str:
    """Format DSCR: inf → '∞', otherwise '{val:.2f}×'."""
    return "∞" if math.isinf(val) else f"{val:.2f}×"


def _fmt_irr(val: float) -> str:
    """Format IRR: NaN → 'n/a', otherwise '{val:.1%}'."""
    return "n/a" if math.isnan(val) else f"{val:.1%}"


def _fmt_payback(val: "Optional[float]") -> str:
    """Format payback: None → '—', otherwise '{val:.1f} yr'."""
    return "—" if val is None else f"{val:.1f} yr"


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
            label = f"{cp.pv_kwp:.1f} kWp / {cp.battery_kwh:.1f} kWh / {cp.inverter_kw:.1f} kW"
            if i == 0:
                label += " ★ RECOMMENDATION"
            sol = cr.solution
            dist_str = (
                f"£{sol.outlay.min_gbp:.0f} / £{sol.outlay.mean_gbp:.0f} / "
                f"£{sol.outlay.median_gbp:.0f} / £{sol.outlay.max_gbp:.0f}"
            )
            binding_label = _BINDING_LABELS.get(cr.binding, cr.binding)
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
            label = f"{cp.pv_kwp:.1f} kWp / {cp.battery_kwh:.1f} kWh / {cp.inverter_kw:.1f} kW"
            report += f"| {label} | {_BINDING_LABELS['infeasible_above_retail']} |\n"

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
            label = f"{cp.pv_kwp:.1f} kWp / {cp.battery_kwh:.1f} kWh / {cp.inverter_kw:.1f} kW"
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
        report += f"Baseline top config: {panel.baseline_top.pv_kwp:.1f} kWp / "
        report += f"{panel.baseline_top.battery_kwh:.1f} kWh / "
        report += f"{panel.baseline_top.inverter_kw:.1f} kW\n"

        for axis in panel.axes:
            report += f"\n### Axis: {axis.name}\n\n"
            report += "| Value | Top Config |\n"
            report += "|------:|-----------|\n"
            for val, top in zip(axis.values, axis.top_config_per_value):
                if top is None:
                    top_str = "—"
                else:
                    top_str = f"{top.pv_kwp:.1f} kWp / {top.battery_kwh:.1f} kWh / {top.inverter_kw:.1f} kW"
                report += f"| {val:.2f} | {top_str} |\n"

    return report
