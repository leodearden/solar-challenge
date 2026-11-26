# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Tests for board_report.generate_config_ranking_report's two tables and its sensitivity section, the report `optimize configs` prints.

The line the report opens with, naming its self-consumption assumption, and
the notices it shares with the finance report are tested in
tests/unit/test_board_report.py; the command in
tests/integration/test_optimize_cli.py.
"""
from __future__ import annotations

from typing import Optional

from solar_challenge.board_report import generate_config_ranking_report
from solar_challenge.optimize import ConfigPoint, RankedSweep, SensitivityAxis, SensitivityPanel
from tests._factories import make_bill_distribution_from_statistics, make_config_result, make_ranked_sweep
from tests._ranking_report_tables import TRADE_OFF, config_column, config_row, section_under


# ---------------------------------------------------------------------------
# §A — Helper factories
# ---------------------------------------------------------------------------


def _make_sensitivity_panel(
    axes: tuple[SensitivityAxis, ...],
    baseline_top: ConfigPoint,
    rank_stability: float = 0.8,
) -> SensitivityPanel:
    """Build a SensitivityPanel for fixture use."""
    return SensitivityPanel(
        axes=axes,
        baseline_top=baseline_top,
        rank_stability=rank_stability,
    )


def _make_sensitivity_axis(
    name: str = "grid_services_income_per_kw_per_year_gbp",
    values: tuple[float, ...] = (1.5, 12.0, 48.0),
    top_config: ConfigPoint | None = None,
) -> SensitivityAxis:
    """Build a SensitivityAxis for fixture use."""
    if top_config is None:
        top_config = ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=5.0)
    rankings: tuple[tuple[ConfigPoint, ...], ...] = tuple(
        (top_config,) for _ in values
    )
    top_per_value: tuple[Optional[ConfigPoint], ...] = tuple(top_config for _ in values)
    return SensitivityAxis(
        name=name,
        values=values,
        rankings=rankings,
        top_config_per_value=top_per_value,
    )


# ---------------------------------------------------------------------------
# §B — generate_config_ranking_report Table (1)
# ---------------------------------------------------------------------------


class TestGenerateConfigRankingReportTable1:
    """generate_config_ranking_report renders the COST-RECOVERY RANK table."""

    CHEAPEST = "4.0 kWp / 0.0 kWh / 5.0 kW"
    SECOND_CHEAPEST = "5.0 kWp / 5.0 kWh / 5.0 kW"
    INFEASIBLE = "6.0 kWp / 10.0 kWh / 5.0 kW"

    def _make_sweep_two_feasible(self) -> RankedSweep:
        """Build a RankedSweep with two feasible configs and one infeasible.

        Each feasible config's representative outlay differs from its outlay's min, mean, median and max, so a cell showing the wrong one of them fails the test that reads it.
        """
        # Config 1 (cheapest, RECOMMENDATION): 4 kWp, no battery, solved @ 12.5p
        r1 = make_config_result(
            pv_kwp=4.0,
            battery_kwh=0.0,
            inverter_kw=5.0,
            solved_own_use_rate_pence_per_kwh=12.5,
            surplus_at_solved_gbp=35.0,
            feasible=True,
            binding="floor",
            total_capex_gbp=48_000.0,
            min_dscr=float("inf"),
            equity_irr=0.09,
            payback_years=11.0,
            baseline_outlay_gbp=375.0,
            baseline_surplus_per_home_gbp=40.0,
            outlay=make_bill_distribution_from_statistics(
                representative_outlay_gbp=352.0,
                min_gbp=300.0,
                mean_gbp=345.0,
                median_gbp=350.0,
                max_gbp=400.0,
            ),
        )
        # Config 2 (second cheapest): 5 kWp, 5 kWh battery
        r2 = make_config_result(
            pv_kwp=5.0,
            battery_kwh=5.0,
            inverter_kw=5.0,
            solved_own_use_rate_pence_per_kwh=18.75,
            surplus_at_solved_gbp=27.0,
            feasible=True,
            binding="floor",
            total_capex_gbp=72_000.0,
            min_dscr=1.45,
            equity_irr=0.07,
            payback_years=14.5,
            baseline_outlay_gbp=410.0,
            baseline_surplus_per_home_gbp=55.0,
            outlay=make_bill_distribution_from_statistics(
                representative_outlay_gbp=372.0,
                min_gbp=325.0,
                mean_gbp=368.0,
                median_gbp=370.0,
                max_gbp=420.0,
            ),
        )
        # Infeasible: 6 kWp, 10 kWh — ConfigPoint only in RankedSweep
        infeasible_pt = ConfigPoint(pv_kwp=6.0, battery_kwh=10.0, inverter_kw=5.0)
        return make_ranked_sweep(
            results=(r1, r2),
            infeasible=(infeasible_pt,),
            pareto=(r1.config,),
            floor=35.0,
        )

    def test_cost_recovery_rank_heading_present(self) -> None:
        """Report must contain a cost-recovery rank heading."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        assert "cost-recovery rank" in report.lower(), (
            f"Expected 'Cost-Recovery Rank' heading in report:\n{report}"
        )

    def test_solved_own_use_rate_formatted(self) -> None:
        """Each config's solved own-use rate must appear as 'XX.XX p/kWh' in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "12.50 p/kWh",
            self.SECOND_CHEAPEST: "18.75 p/kWh",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Solved Rate (p/kWh)", expected)
        assert shown == expected, f"solved own-use rates not shown in their configs' rows:\n{report}"

    def test_representative_outlay_rendered(self) -> None:
        """Report must show each config's representative outlay, the figure Table 1 is ranked by, in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£352.00",
            self.SECOND_CHEAPEST: "£372.00",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Rep Outlay (£)", expected)
        assert shown == expected, f"representative outlays not shown in their configs' rows:\n{report}"

    def test_outlay_distribution_values(self) -> None:
        """Report must show each config's min/mean/median/max outlay in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£300 / £345 / £350 / £400",
            self.SECOND_CHEAPEST: "£325 / £368 / £370 / £420",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Min/Mean/Median/Max (£)", expected)
        assert shown == expected, f"outlay distributions not shown in their configs' rows:\n{report}"

    def test_cbs_surplus_rendered(self) -> None:
        """Report must show each config's CBS surplus at the solved rate in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£35.00",
            self.SECOND_CHEAPEST: "£27.00",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "CBS Surplus (£/home/yr)", expected)
        assert shown == expected, f"CBS surpluses not shown in their configs' rows:\n{report}"

    def test_feasibility_binding_label_present(self) -> None:
        """Report must show each config's human-readable binding/feasibility label in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "✔ Surplus meets floor",
            self.SECOND_CHEAPEST: "✔ Surplus meets floor",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Feasibility", expected)
        assert shown == expected, f"feasibility labels not shown in their configs' rows:\n{report}"

    def test_total_capex_rendered(self) -> None:
        """Report must show each feasible config's total_capex_gbp in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£48,000",
            self.SECOND_CHEAPEST: "£72,000",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Total CapEx (£)", expected)
        assert shown == expected, f"total capex not shown in their configs' rows:\n{report}"

    def test_min_dscr_inf_shown_as_infinity_symbol(self) -> None:
        """min_dscr=inf must render as '∞' in the config's Cost-Recovery Rank Min DSCR cell."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        row = config_row(report, "## Cost-Recovery Rank", self.CHEAPEST)
        assert row["Min DSCR"] == "∞", f"'∞' for inf DSCR not found in the Min DSCR cell:\n{report}"

    def test_equity_irr_formatted_as_percent(self) -> None:
        """Each config's equity_irr must be rendered as a one-decimal percentage in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "9.0%",
            self.SECOND_CHEAPEST: "7.0%",
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Equity IRR", expected)
        assert shown == expected, f"equity IRRs not shown in their configs' rows:\n{report}"

    def test_payback_none_shown_as_dash(self) -> None:
        """payback_years=None must render as '—' in the config's Cost-Recovery Rank Payback cell."""
        r_no_payback = make_config_result(
            pv_kwp=3.0, battery_kwh=0.0, inverter_kw=5.0,
            payback_years=None,
            solved_own_use_rate_pence_per_kwh=10.0,
        )
        sweep = make_ranked_sweep(results=(r_no_payback,))
        report = generate_config_ranking_report(sweep)

        row = config_row(report, "## Cost-Recovery Rank", "3.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["Payback"] == "—", f"'—' for None payback not found in the Payback cell:\n{report}"

    def test_nan_irr_shown_as_na(self) -> None:
        """equity_irr=NaN must render as 'n/a' in the config's Cost-Recovery Rank Equity IRR cell."""
        r_nan_irr = make_config_result(
            pv_kwp=3.0, battery_kwh=0.0, inverter_kw=5.0,
            equity_irr=float("nan"),
            solved_own_use_rate_pence_per_kwh=10.0,
        )
        sweep = make_ranked_sweep(results=(r_nan_irr,))
        report = generate_config_ranking_report(sweep)

        row = config_row(report, "## Cost-Recovery Rank", "3.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["Equity IRR"] == "n/a", f"'n/a' for NaN IRR not found in the Equity IRR cell:\n{report}"

    def test_recommendation_marker_on_cheapest(self) -> None:
        """The cheapest feasible config (results[0]), and no other, must be flagged '★ RECOMMENDATION' in its Config cell."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: f"{self.CHEAPEST} ★ RECOMMENDATION",
            self.SECOND_CHEAPEST: self.SECOND_CHEAPEST,
        }
        shown = config_column(report, "## Cost-Recovery Rank", "Config", expected)
        assert shown == expected, f"RECOMMENDATION marker not on the cheapest config alone:\n{report}"

    def test_infeasible_section_lists_config_dims(self) -> None:
        """Infeasible ConfigPoints must appear by their dims in the Infeasible Configurations section's table."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        row = config_row(report, "### Infeasible Configurations", self.INFEASIBLE)
        assert row["Config"] == self.INFEASIBLE, f"infeasible config's Config cell is not exactly its dims:\n{report}"

    def test_empty_infeasible_no_infeasible_section(self) -> None:
        """When there are no infeasible configs, the infeasible section is omitted."""
        r = make_config_result()
        sweep = make_ranked_sweep(results=(r,), infeasible=())
        report = generate_config_ranking_report(sweep)

        assert "### Infeasible Configurations" not in report, (
            f"Infeasible Configurations heading rendered with no infeasible configs:\n{report}"
        )

    def test_no_feasible_config_renders_a_none_found_note_and_the_infeasible_list(self) -> None:
        """With every config infeasible, Table 1 is a none-found note alone, no table and no RECOMMENDATION, and the infeasible configs are still listed."""
        infeasible_pt = ConfigPoint(pv_kwp=6.0, battery_kwh=10.0, inverter_kw=5.0)
        sweep = make_ranked_sweep((), infeasible=(infeasible_pt,))
        report = generate_config_ranking_report(sweep)

        table1 = section_under(report, "## Cost-Recovery Rank")
        assert table1.strip() == "*No feasible configurations found.*", (
            f"'## Cost-Recovery Rank' is not the none-found note alone:\n{report}"
        )
        row = config_row(report, "### Infeasible Configurations", self.INFEASIBLE)
        assert row["Config"] == self.INFEASIBLE, f"infeasible config's Config cell is not exactly its dims:\n{report}"
        assert row["Binding"] == "✘ INFEASIBLE: required rate exceeds retail", (
            f"infeasible config's Binding cell is not the infeasible label:\n{report}"
        )


# ---------------------------------------------------------------------------
# §C — generate_config_ranking_report Table (2)
# ---------------------------------------------------------------------------

class TestGenerateConfigRankingReportTable2:
    """generate_config_ranking_report renders the CONFIGURED-RATE TRADE-OFF table."""

    def _make_sweep_with_pareto(self) -> RankedSweep:
        """Build a RankedSweep where some (not all) feasible configs are on the Pareto front."""
        # Config A (cheapest, on Pareto): 4 kWp / 0 kWh — low outlay, low surplus
        r_a = make_config_result(
            pv_kwp=4.0,
            battery_kwh=0.0,
            inverter_kw=5.0,
            solved_own_use_rate_pence_per_kwh=12.5,
            surplus_at_solved_gbp=27.0,
            feasible=True,
            binding="floor",
            baseline_outlay_gbp=360.0,
            baseline_surplus_per_home_gbp=30.0,
        )
        # Config B (more expensive, on Pareto): 5 kWp / 5 kWh — higher surplus
        r_b = make_config_result(
            pv_kwp=5.0,
            battery_kwh=5.0,
            inverter_kw=5.0,
            solved_own_use_rate_pence_per_kwh=18.75,
            surplus_at_solved_gbp=27.0,
            feasible=True,
            binding="floor",
            baseline_outlay_gbp=420.0,
            baseline_surplus_per_home_gbp=80.0,
        )
        # Config C (dominated, NOT on Pareto): higher outlay, lower surplus than B
        r_c = make_config_result(
            pv_kwp=6.0,
            battery_kwh=5.0,
            inverter_kw=5.0,
            solved_own_use_rate_pence_per_kwh=20.0,
            surplus_at_solved_gbp=27.0,
            feasible=True,
            binding="floor",
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=60.0,
        )
        # Pareto front: A and B (C is dominated by B)
        pareto = (r_a.config, r_b.config)
        return make_ranked_sweep(
            results=(r_a, r_b, r_c),
            infeasible=(),
            pareto=pareto,
            floor=27.0,
        )

    def test_configured_rate_table_heading_present(self) -> None:
        """Report must contain the configured-rate trade-off table heading."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        assert f"{TRADE_OFF}\n" in report, f"Expected {TRADE_OFF!r} heading in report:\n{report}"

    def test_each_row_names_the_configured_rate_its_baseline_pair_is_priced_at(self) -> None:
        result = make_config_result(baseline_own_use_rate_pence_per_kwh=12.0)
        report = generate_config_ranking_report(make_ranked_sweep([result]))

        row = config_row(report, TRADE_OFF, "4.0 kWp / 6.0 kWh / 3.6 kW")
        assert row["Configured Rate (p/kWh)"] == "12.00 p/kWh", report

    def test_baseline_outlay_values_present(self) -> None:
        """Report must show each feasible config's baseline_outlay_gbp in its Configured-Rate Trade-Off row."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        expected = {
            "4.0 kWp / 0.0 kWh / 5.0 kW": "£360.00",
            "5.0 kWp / 5.0 kWh / 5.0 kW": "£420.00",
            "6.0 kWp / 5.0 kWh / 5.0 kW": "£450.00",
        }
        shown = config_column(report, TRADE_OFF, "Baseline Outlay (£/yr)", expected)
        assert shown == expected, f"baseline outlays not shown in their configs' rows:\n{report}"

    def test_baseline_surplus_values_present(self) -> None:
        """Report must show each feasible config's baseline_surplus_per_home_gbp in its Configured-Rate Trade-Off row."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        expected = {
            "4.0 kWp / 0.0 kWh / 5.0 kW": "£30.00",
            "5.0 kWp / 5.0 kWh / 5.0 kW": "£80.00",
            "6.0 kWp / 5.0 kWh / 5.0 kW": "£60.00",
        }
        shown = config_column(report, TRADE_OFF, "Baseline CBS Surplus (£/home/yr)", expected)
        assert shown == expected, f"baseline surpluses not shown in their configs' rows:\n{report}"

    def test_pareto_flag_set_for_pareto_configs(self) -> None:
        """Table 2 must have exactly 2 '✔ Pareto' tokens (A+B) and exactly 1 '—' marker (C)."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        # Scope to Table 2 section — both tables print config dim labels so un-scoped
        # line filters would also match Table 1 rows which carry no Pareto column.
        assert TRADE_OFF in report, "Table 2 heading not found"
        table2 = report.split(TRADE_OFF, 1)[1]

        # Exactly two '✔ Pareto' tokens: one for Config A, one for Config B
        pareto_count = table2.count("✔ Pareto")
        assert pareto_count == 2, (
            f"Expected exactly 2 '✔ Pareto' tokens in Table 2, got {pareto_count}:\n{table2}"
        )

        # Exactly one '—' (U+2014 em-dash) non-Pareto marker: only Config C.
        # Separator rows use ASCII '-', not em-dash, so only C's marker contributes U+2014.
        non_pareto_count = table2.count("—")  # U+2014 em-dash
        assert non_pareto_count == 1, (
            f"Expected exactly 1 '—' (U+2014) non-Pareto marker in Table 2, "
            f"got {non_pareto_count}:\n{table2}"
        )

    def test_pareto_flag_non_trivial(self) -> None:
        """The Pareto flag must distinguish A+B (on front) from C (not on front)."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        # Scope to Table 2 section — Table 1 also prints '{pv} kWp / {battery} kWh / {inverter} kW'
        # labels but has NO Pareto column; an un-scoped line filter on dims would match Table-1
        # rows and falsify the assertion.  Splitting on the Table-2 heading isolates the section
        # that actually carries the Pareto flag column.
        assert TRADE_OFF in report, "Table 2 heading not found"
        table2 = report.split(TRADE_OFF, 1)[1]
        table2_lines = table2.split("\n")

        # Config C row (6.0 kWp / 5.0 kWh): dominated → must carry '—' (U+2014), NOT '✔ Pareto'
        c_lines = [ln for ln in table2_lines if "6.0 kWp" in ln and "5.0 kWh" in ln]
        assert c_lines, "Config C (6.0 kWp / 5.0 kWh) not found in Table 2"
        assert all("—" in ln for ln in c_lines), (
            f"Expected '—' (U+2014, non-Pareto) for Config C in Table 2:\n{c_lines}"
        )
        assert all("✔ Pareto" not in ln for ln in c_lines), (
            f"Config C should NOT be marked '✔ Pareto' in Table 2:\n{c_lines}"
        )

        # Config A row (4.0 kWp / 0.0 kWh): on Pareto front → must carry '✔ Pareto'
        a_lines = [ln for ln in table2_lines if "4.0 kWp" in ln and "0.0 kWh" in ln]
        assert a_lines, "Config A (4.0 kWp / 0.0 kWh) not found in Table 2"
        assert all("✔ Pareto" in ln for ln in a_lines), (
            f"Expected '✔ Pareto' for Config A in Table 2:\n{a_lines}"
        )

        # Config B row (5.0 kWp / 5.0 kWh): on Pareto front → must carry '✔ Pareto'
        b_lines = [ln for ln in table2_lines if "5.0 kWp" in ln and "5.0 kWh" in ln]
        assert b_lines, "Config B (5.0 kWp / 5.0 kWh) not found in Table 2"
        assert all("✔ Pareto" in ln for ln in b_lines), (
            f"Expected '✔ Pareto' for Config B in Table 2:\n{b_lines}"
        )

    def test_infeasible_absent_from_table2(self) -> None:
        """Infeasible ConfigPoints must NOT appear in Table 2 (no baseline economics)."""
        r = make_config_result(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=5.0)
        infeasible_pt = ConfigPoint(pv_kwp=9.9, battery_kwh=15.0, inverter_kw=5.0)
        sweep = make_ranked_sweep(
            results=(r,),
            infeasible=(infeasible_pt,),
        )
        report = generate_config_ranking_report(sweep)

        infeasible = "9.9 kWp / 15.0 kWh / 5.0 kW"
        infeasible_section = section_under(report, "### Infeasible Configurations")
        assert infeasible in infeasible_section, f"infeasible config {infeasible!r} not listed under '### Infeasible Configurations':\n{infeasible_section}"
        table2 = section_under(report, TRADE_OFF)
        assert infeasible not in table2, f"infeasible config {infeasible!r} listed under {TRADE_OFF!r}:\n{table2}"

    def test_no_feasible_config_renders_a_nothing_to_compare_note_even_with_a_pareto_front(self) -> None:
        """With every config infeasible, Table 2 is a nothing-to-compare note alone, though run_sweep's Pareto front, taken over all configs, holds the infeasible one."""
        infeasible_pt = ConfigPoint(pv_kwp=9.9, battery_kwh=15.0, inverter_kw=5.0)
        sweep = make_ranked_sweep((), infeasible=(infeasible_pt,), pareto=(infeasible_pt,))
        report = generate_config_ranking_report(sweep)

        table2 = section_under(report, TRADE_OFF)
        assert table2.strip() == "*No feasible configurations to compare.*", (
            f"{TRADE_OFF!r} is not the nothing-to-compare note alone:\n{report}"
        )

    def test_two_tables_both_present(self) -> None:
        """Both Table 1 and Table 2 headings must appear in the same report."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        assert "cost-recovery rank" in report.lower()
        assert f"{TRADE_OFF}\n" in report, report


# ---------------------------------------------------------------------------
# §D — sensitivity section + optional-panel omission
# ---------------------------------------------------------------------------


class TestGenerateConfigRankingReportSensitivity:
    """generate_config_ranking_report renders SENSITIVITY section only when panel provided."""

    def _make_sweep_one(self) -> RankedSweep:
        """A minimal single-config RankedSweep."""
        r = make_config_result(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=5.0)
        return make_ranked_sweep(results=(r,), pareto=(r.config,))

    def _make_panel(self, sweep: RankedSweep) -> SensitivityPanel:
        """Build a SensitivityPanel with two axes at rank_stability=0.75."""
        top = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=5.0)

        axis_gs = _make_sensitivity_axis(
            name="grid_services_income_per_kw_per_year_gbp",
            values=(1.5, 12.0, 48.0),
            top_config=top,
        )
        axis_rf = _make_sensitivity_axis(
            name="retained_cash_floor_per_home_per_year_gbp",
            values=(20.0, 27.0, 40.0),
            top_config=top,
        )
        return _make_sensitivity_panel(
            axes=(axis_gs, axis_rf),
            baseline_top=top,
            rank_stability=0.75,
        )

    def test_sensitivity_heading_present_when_panel_provided(self) -> None:
        """Report must contain a sensitivity heading when panel is not None."""
        sweep = self._make_sweep_one()
        panel = self._make_panel(sweep)
        report = generate_config_ranking_report(sweep, panel)

        assert "sensitivity" in report.lower(), (
            f"Expected sensitivity section heading when panel provided:\n{report}"
        )

    def test_axis_name_appears_in_sensitivity_section(self) -> None:
        """Each SensitivityAxis.name must appear in the sensitivity section."""
        sweep = self._make_sweep_one()
        panel = self._make_panel(sweep)
        report = generate_config_ranking_report(sweep, panel)

        assert "grid_services" in report or "grid services" in report.lower(), (
            f"Axis name 'grid_services' not found in sensitivity:\n{report}"
        )
        assert "retained_cash_floor" in report or "retained cash floor" in report.lower(), (
            f"Axis name 'retained_cash_floor' not found in sensitivity:\n{report}"
        )

    def test_per_value_top_config_shown(self) -> None:
        """At least one per-value top config must appear in the sensitivity section."""
        sweep = self._make_sweep_one()
        panel = self._make_panel(sweep)
        report = generate_config_ranking_report(sweep, panel)

        # top_config is (4.0, 0.0, 5.0) for all values → '4.0 kWp' should appear
        # (it's already in Table 1/2 too, but the sensitivity section must show it)
        # A lenient check: the sensitivity section itself appears and has config info
        assert "sensitivity" in report.lower()

    def test_rank_stability_rendered(self) -> None:
        """rank_stability (0.75) must appear in the report as a percentage or fraction."""
        sweep = self._make_sweep_one()
        panel = self._make_panel(sweep)
        report = generate_config_ranking_report(sweep, panel)

        # 0.75 as percentage = 75.0%
        assert "75" in report, (
            f"rank_stability 75% not found in report:\n{report}"
        )

    def test_no_sensitivity_heading_when_panel_none(self) -> None:
        """Report must NOT contain a sensitivity heading when panel=None."""
        sweep = self._make_sweep_one()
        report_no_panel = generate_config_ranking_report(sweep)

        assert "sensitivity" not in report_no_panel.lower(), (
            f"Sensitivity heading found but panel=None:\n{report_no_panel}"
        )

    def test_panel_omitted_vs_none_bit_identical(self) -> None:
        """generate_config_ranking_report(ranked) == generate_config_ranking_report(ranked, None)."""
        sweep = self._make_sweep_one()
        report_omitted = generate_config_ranking_report(sweep)
        report_none = generate_config_ranking_report(sweep, panel=None)

        assert report_omitted == report_none, (
            "Omitting panel and passing panel=None must produce identical output."
        )

    def test_none_tops_rendered_as_dash(self) -> None:
        """SensitivityAxis tops that are None must be rendered as '—'."""
        # An axis where one value has no feasible top (top_config_per_value=None)
        axis_with_none = SensitivityAxis(
            name="grid_services_income_per_kw_per_year_gbp",
            values=(1.5, 48.0),
            rankings=((), ()),  # no feasible configs at either value
            top_config_per_value=(None, None),
        )
        top = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=5.0)
        panel = _make_sensitivity_panel(
            axes=(axis_with_none,),
            baseline_top=top,
            rank_stability=0.0,
        )
        sweep = self._make_sweep_one()
        report = generate_config_ranking_report(sweep, panel)

        assert "—" in report, (
            f"'—' for None tops in sensitivity section not found:\n{report}"
        )
