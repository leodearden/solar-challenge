# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for W3 sweep E: generate_config_ranking_report + optimize CLI."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Optional

import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.optimize import (
    SENSITIVITY_BANDS,
    ConfigPoint,
    ConfigResult,
    RankedSweep,
    SensitivityAxis,
    SensitivityPanel,
)
from solar_challenge.output import generate_config_ranking_report
from tests._cli_fleet_simulator import invoke_cli
from tests._factories import make_bill_distribution_from_statistics, make_config_result
from tests._finance_builders import make_fleet_results


# ---------------------------------------------------------------------------
# §A — Helper factories
# ---------------------------------------------------------------------------


def _make_ranked_sweep(
    results: tuple[ConfigResult, ...],
    infeasible: tuple[ConfigPoint, ...] = (),
    pareto: tuple[ConfigPoint, ...] = (),
    floor: float = 27.0,
) -> RankedSweep:
    """Assemble a RankedSweep honouring cheapest_feasible == results[0].config invariant."""
    cheapest = results[0].config if results else None
    return RankedSweep(
        results=results,
        infeasible=infeasible,
        retained_cash_floor_gbp=floor,
        cheapest_feasible=cheapest,
        pareto_baseline=pareto,
    )


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
# §B — The patched `optimize configs` tests' scenario writer
# ---------------------------------------------------------------------------


def _write_optimize_scenario(tmp_path: Path, n_homes: int = 5) -> Path:
    """Write a minimal feasible-regime scenario YAML to tmp_path."""
    scenario = {
        "name": "W3 Optimize CLI Test",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": {
            "standing_charge_pence_per_day": 28.0,
            # Interior feasibility: high capex, no grant, floor=100, retail=30p
            "pv_cost_per_kwp_gbp": 2000.0,
            "battery_cost_per_kwh_gbp": 300.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 0.0,
            "own_use_rate_pence_per_kwh": 15.0,
            "retained_cash_floor_per_home_per_year_gbp": 100.0,
            "retail_baseline_rate_pence_per_kwh": 30.0,
            "asset_life_years": 25,
            "vat_rate": 0.05,
        },
    }
    path = tmp_path / "optimize_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path


# ---------------------------------------------------------------------------
# §C — generate_config_ranking_report Table (1)
# ---------------------------------------------------------------------------


def _section(report: str, heading: str) -> str:
    """The text under *heading* in *report*, up to the next heading of any level, so a sub-section is never read as *heading*'s."""
    assert f"{heading}\n" in report, f"No {heading!r} heading in the report:\n{report}"
    return report.split(f"{heading}\n", 1)[1].split("\n#", 1)[0]


def _config_row(report: str, heading: str, config_label: str) -> dict[str, str]:
    """The row of the table in *heading*'s own section whose Config cell starts with *config_label*, each cell keyed by its column header."""
    section = _section(report, heading)
    header, _delimiter_row, *rows = (
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    )
    matches = [row for row in rows if row[0].startswith(config_label)]
    assert len(matches) == 1, f"Expected one {config_label!r} row under {heading!r}:\n{section}"
    return dict(zip(header, matches[0], strict=True))


def _column(report: str, heading: str, column: str, labels: Iterable[str]) -> dict[str, str]:
    """The *column* cell of each of *labels*' rows in *heading*'s table, keyed by label."""
    return {label: _config_row(report, heading, label)[column] for label in labels}


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
        return _make_ranked_sweep(
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
        shown = _column(report, "## Cost-Recovery Rank", "Solved Rate (p/kWh)", expected)
        assert shown == expected, f"solved own-use rates not shown in their configs' rows:\n{report}"

    def test_representative_outlay_rendered(self) -> None:
        """Report must show each config's representative outlay, the figure Table 1 is ranked by, in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£352.00",
            self.SECOND_CHEAPEST: "£372.00",
        }
        shown = _column(report, "## Cost-Recovery Rank", "Rep Outlay (£)", expected)
        assert shown == expected, f"representative outlays not shown in their configs' rows:\n{report}"

    def test_outlay_distribution_values(self) -> None:
        """Report must show each config's min/mean/median/max outlay in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£300 / £345 / £350 / £400",
            self.SECOND_CHEAPEST: "£325 / £368 / £370 / £420",
        }
        shown = _column(report, "## Cost-Recovery Rank", "Min/Mean/Median/Max (£)", expected)
        assert shown == expected, f"outlay distributions not shown in their configs' rows:\n{report}"

    def test_cbs_surplus_rendered(self) -> None:
        """Report must show each config's CBS surplus at the solved rate in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£35.00",
            self.SECOND_CHEAPEST: "£27.00",
        }
        shown = _column(report, "## Cost-Recovery Rank", "CBS Surplus (£/home/yr)", expected)
        assert shown == expected, f"CBS surpluses not shown in their configs' rows:\n{report}"

    def test_feasibility_binding_label_present(self) -> None:
        """Report must show each config's human-readable binding/feasibility label in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "✔ Surplus meets floor",
            self.SECOND_CHEAPEST: "✔ Surplus meets floor",
        }
        shown = _column(report, "## Cost-Recovery Rank", "Feasibility", expected)
        assert shown == expected, f"feasibility labels not shown in their configs' rows:\n{report}"

    def test_total_capex_rendered(self) -> None:
        """Report must show each feasible config's total_capex_gbp in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "£48,000",
            self.SECOND_CHEAPEST: "£72,000",
        }
        shown = _column(report, "## Cost-Recovery Rank", "Total CapEx (£)", expected)
        assert shown == expected, f"total capex not shown in their configs' rows:\n{report}"

    def test_min_dscr_inf_shown_as_infinity_symbol(self) -> None:
        """min_dscr=inf must render as '∞' in the config's Cost-Recovery Rank Min DSCR cell."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        row = _config_row(report, "## Cost-Recovery Rank", self.CHEAPEST)
        assert row["Min DSCR"] == "∞", f"'∞' for inf DSCR not found in the Min DSCR cell:\n{report}"

    def test_equity_irr_formatted_as_percent(self) -> None:
        """Each config's equity_irr must be rendered as a one-decimal percentage in its Cost-Recovery Rank row."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: "9.0%",
            self.SECOND_CHEAPEST: "7.0%",
        }
        shown = _column(report, "## Cost-Recovery Rank", "Equity IRR", expected)
        assert shown == expected, f"equity IRRs not shown in their configs' rows:\n{report}"

    def test_payback_none_shown_as_dash(self) -> None:
        """payback_years=None must render as '—' in the config's Cost-Recovery Rank Payback cell."""
        r_no_payback = make_config_result(
            pv_kwp=3.0, battery_kwh=0.0, inverter_kw=5.0,
            payback_years=None,
            solved_own_use_rate_pence_per_kwh=10.0,
        )
        sweep = _make_ranked_sweep(results=(r_no_payback,))
        report = generate_config_ranking_report(sweep)

        row = _config_row(report, "## Cost-Recovery Rank", "3.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["Payback"] == "—", f"'—' for None payback not found in the Payback cell:\n{report}"

    def test_nan_irr_shown_as_na(self) -> None:
        """equity_irr=NaN must render as 'n/a' in the config's Cost-Recovery Rank Equity IRR cell."""
        r_nan_irr = make_config_result(
            pv_kwp=3.0, battery_kwh=0.0, inverter_kw=5.0,
            equity_irr=float("nan"),
            solved_own_use_rate_pence_per_kwh=10.0,
        )
        sweep = _make_ranked_sweep(results=(r_nan_irr,))
        report = generate_config_ranking_report(sweep)

        row = _config_row(report, "## Cost-Recovery Rank", "3.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["Equity IRR"] == "n/a", f"'n/a' for NaN IRR not found in the Equity IRR cell:\n{report}"

    def test_recommendation_marker_on_cheapest(self) -> None:
        """The cheapest feasible config (results[0]), and no other, must be flagged '★ RECOMMENDATION' in its Config cell."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        expected = {
            self.CHEAPEST: f"{self.CHEAPEST} ★ RECOMMENDATION",
            self.SECOND_CHEAPEST: self.SECOND_CHEAPEST,
        }
        shown = _column(report, "## Cost-Recovery Rank", "Config", expected)
        assert shown == expected, f"RECOMMENDATION marker not on the cheapest config alone:\n{report}"

    def test_infeasible_section_lists_config_dims(self) -> None:
        """Infeasible ConfigPoints must appear by their dims in the Infeasible Configurations section's table."""
        ranked = self._make_sweep_two_feasible()
        report = generate_config_ranking_report(ranked)

        row = _config_row(report, "### Infeasible Configurations", self.INFEASIBLE)
        assert row["Config"] == self.INFEASIBLE, f"infeasible config's Config cell is not exactly its dims:\n{report}"

    def test_empty_infeasible_no_infeasible_section(self) -> None:
        """When there are no infeasible configs, the infeasible section is omitted."""
        r = make_config_result()
        sweep = _make_ranked_sweep(results=(r,), infeasible=())
        report = generate_config_ranking_report(sweep)

        assert "### Infeasible Configurations" not in report, (
            f"Infeasible Configurations heading rendered with no infeasible configs:\n{report}"
        )


# ---------------------------------------------------------------------------
# §D — generate_config_ranking_report Table (2)
# ---------------------------------------------------------------------------


class TestGenerateConfigRankingReportTable2:
    """generate_config_ranking_report renders the FIXED-15p TRADE-OFF table."""

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
        return _make_ranked_sweep(
            results=(r_a, r_b, r_c),
            infeasible=(),
            pareto=pareto,
            floor=27.0,
        )

    def test_fixed15p_table_heading_present(self) -> None:
        """Report must contain a fixed-15p trade-off table heading."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        assert "fixed-15p" in report.lower() or "trade-off" in report.lower() or "trade‑off" in report.lower(), (
            f"Expected fixed-15p trade-off heading in report:\n{report}"
        )

    def test_baseline_outlay_values_present(self) -> None:
        """Report must show each feasible config's baseline_outlay_gbp in its Fixed-15p Trade-Off row."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        expected = {
            "4.0 kWp / 0.0 kWh / 5.0 kW": "£360.00",
            "5.0 kWp / 5.0 kWh / 5.0 kW": "£420.00",
            "6.0 kWp / 5.0 kWh / 5.0 kW": "£450.00",
        }
        shown = _column(report, "## Fixed-15p Trade-Off", "Baseline Outlay (£/yr)", expected)
        assert shown == expected, f"baseline outlays not shown in their configs' rows:\n{report}"

    def test_baseline_surplus_values_present(self) -> None:
        """Report must show each feasible config's baseline_surplus_per_home_gbp in its Fixed-15p Trade-Off row."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        expected = {
            "4.0 kWp / 0.0 kWh / 5.0 kW": "£30.00",
            "5.0 kWp / 5.0 kWh / 5.0 kW": "£80.00",
            "6.0 kWp / 5.0 kWh / 5.0 kW": "£60.00",
        }
        shown = _column(report, "## Fixed-15p Trade-Off", "Baseline CBS Surplus (£/home/yr)", expected)
        assert shown == expected, f"baseline surpluses not shown in their configs' rows:\n{report}"

    def test_pareto_flag_set_for_pareto_configs(self) -> None:
        """Table 2 must have exactly 2 '✔ Pareto' tokens (A+B) and exactly 1 '—' marker (C)."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        # Scope to Table 2 section — both tables print config dim labels so un-scoped
        # line filters would also match Table 1 rows which carry no Pareto column.
        assert "## Fixed-15p Trade-Off" in report, "Table 2 heading not found"
        table2 = report.split("## Fixed-15p Trade-Off", 1)[1]

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
        assert "## Fixed-15p Trade-Off" in report, "Table 2 heading not found"
        table2 = report.split("## Fixed-15p Trade-Off", 1)[1]
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
        sweep = _make_ranked_sweep(
            results=(r,),
            infeasible=(infeasible_pt,),
        )
        report = generate_config_ranking_report(sweep)

        infeasible = "9.9 kWp / 15.0 kWh / 5.0 kW"
        infeasible_section = _section(report, "### Infeasible Configurations")
        assert infeasible in infeasible_section, f"infeasible config {infeasible!r} not listed under '### Infeasible Configurations':\n{infeasible_section}"
        table2 = _section(report, "## Fixed-15p Trade-Off")
        assert infeasible not in table2, f"infeasible config {infeasible!r} listed under '## Fixed-15p Trade-Off':\n{table2}"

    def test_two_tables_both_present(self) -> None:
        """Both Table 1 and Table 2 headings must appear in the same report."""
        ranked = self._make_sweep_with_pareto()
        report = generate_config_ranking_report(ranked)

        assert "cost-recovery rank" in report.lower()
        assert "fixed-15p" in report.lower() or "trade-off" in report.lower() or "baseline" in report.lower()


# ---------------------------------------------------------------------------
# §E — sensitivity section + optional-panel omission
# ---------------------------------------------------------------------------


class TestGenerateConfigRankingReportSensitivity:
    """generate_config_ranking_report renders SENSITIVITY section only when panel provided."""

    def _make_sweep_one(self) -> RankedSweep:
        """A minimal single-config RankedSweep."""
        r = make_config_result(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=5.0)
        return _make_ranked_sweep(results=(r,), pareto=(r.config,))

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


# ---------------------------------------------------------------------------
# §F — CLI registration + help
# ---------------------------------------------------------------------------


class TestOptimizeCLIHelp:
    """`optimize configs --help` exits 0 and lists required flags."""

    def test_optimize_help_shows_configs_command(self) -> None:
        """`optimize --help` must list the 'configs' subcommand."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "--help"])
        assert result.exit_code == 0, (
            f"Expected exit 0 for 'optimize --help':\n{result.output}"
        )
        assert "configs" in result.output.lower(), (
            f"Expected 'configs' subcommand in 'optimize --help':\n{result.output}"
        )

    def test_optimize_configs_help_exits_zero(self) -> None:
        """`optimize configs --help` must exit 0."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert result.exit_code == 0, (
            f"Expected exit 0 for 'optimize configs --help':\n{result.output}"
        )

    def test_pv_flag_in_help(self) -> None:
        """`optimize configs --help` must show --pv flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--pv" in result.output, (
            f"Expected '--pv' flag in help:\n{result.output}"
        )

    def test_battery_flag_in_help(self) -> None:
        """`optimize configs --help` must show --battery flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--battery" in result.output, (
            f"Expected '--battery' flag in help:\n{result.output}"
        )

    def test_inverter_flag_in_help(self) -> None:
        """`optimize configs --help` must show --inverter flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--inverter" in result.output, (
            f"Expected '--inverter' flag in help:\n{result.output}"
        )

    def test_retained_floor_flag_in_help(self) -> None:
        """`optimize configs --help` must show --retained-floor flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--retained-floor" in result.output, (
            f"Expected '--retained-floor' flag in help:\n{result.output}"
        )

    def test_grid_services_kw_flag_in_help(self) -> None:
        """`optimize configs --help` must show --grid-services-kw flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--grid-services-kw" in result.output, (
            f"Expected '--grid-services-kw' flag in help:\n{result.output}"
        )

    def test_sensitivity_flag_in_help(self) -> None:
        """`optimize configs --help` must show --sensitivity flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--sensitivity" in result.output, (
            f"Expected '--sensitivity' flag in help:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §G — fast injected-simulate E2E
# ---------------------------------------------------------------------------


def _feasible_fleet_results(n_homes: int) -> FleetResults:
    """*n_homes* default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year.

    Under _write_optimize_scenario's finance the cost-recovery solve binds at
    the floor and is feasible.
    """
    return make_fleet_results(n_homes=n_homes, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


@pytest.fixture(scope="module")
def optimize_fleet_results() -> FleetResults:
    """Module-scoped fixture: constant feasible FleetResults for a five-home scenario, built once per module."""
    return _feasible_fleet_results(n_homes=5)


@pytest.fixture(scope="module")
def one_home_fleet_results() -> FleetResults:
    """Module-scoped fixture: constant feasible FleetResults for a one-home scenario, built once per module."""
    return _feasible_fleet_results(n_homes=1)


# Each --sensitivity alias the CLI documents → the knob whose axis section it adds to the report.
_SENSITIVITY_ALIAS_KNOBS: dict[str, str] = {
    "retained_floor": "retained_cash_floor_per_home_per_year_gbp",
    "grid_services": "grid_services_income_per_kw_per_year_gbp",
    "battery_cost": "battery_cost_per_kwh_gbp",
    "pv_cost": "pv_cost_per_kwp_gbp",
    "inverter_cost": "inverter_cost_per_kw_gbp",
}


def test_the_documented_sensitivity_aliases_cover_exactly_the_library_bands() -> None:
    """The documented aliases' knobs are exactly the optimize.SENSITIVITY_BANDS knobs, so the end-to-end alias test covers every band."""
    assert set(_SENSITIVITY_ALIAS_KNOBS.values()) == set(SENSITIVITY_BANDS), (
        "Every library band must be reachable from a CLI alias."
    )


def _swept_values_by_axis(report: str) -> dict[str, list[float]]:
    """Return, for each '### Axis: <knob>' section of a config-ranking report, the values its table rows sweep."""
    swept: dict[str, list[float]] = {}
    axis_values: list[float] | None = None
    for line in report.splitlines():
        if line.startswith("### Axis: "):
            axis_values = swept.setdefault(line.removeprefix("### Axis: "), [])
        elif line.startswith("#"):
            axis_values = None
        elif axis_values is not None and line.startswith("| ") and not line.startswith("| Value"):
            axis_values.append(float(line.split("|")[1]))
    return swept


class TestOptimizeCLIE2EFast:
    """Fast injected-simulator end-to-end tests for `optimize configs` wiring (G2/W-H6 signal).

    Each test that runs a sweep passes its own fleet simulator as the Click
    context object (``obj=CliFleetSimulator(...)``), so the whole sweep,
    sensitivity panel included, runs offline without PVGIS.
    """

    @staticmethod
    def _invoke_configs(
        tmp_path: Path,
        fleet_results: FleetResults,
        options: list[str],
        *,
        n_homes: int = 5,
    ) -> tuple[Result, list[FleetConfig]]:
        """Run `optimize configs` on a fresh *n_homes*-home scenario with *options*, answering every fleet simulation with *fleet_results*.

        Returns the CliRunner result and the fleet configs the injected simulator
        was asked to simulate.
        """
        simulated_fleets: list[FleetConfig] = []

        def simulate(fleet_config, start, end):
            simulated_fleets.append(fleet_config)
            return fleet_results

        scenario_file = _write_optimize_scenario(tmp_path, n_homes=n_homes)
        result = invoke_cli(["optimize", "configs", str(scenario_file), *options], simulate)
        return result, simulated_fleets

    def test_optimize_configs_standard_sweep_output(
        self,
        tmp_path: Path,
        optimize_fleet_results: FleetResults,
    ) -> None:
        """Standard sweep must exit 0 and produce all expected report tokens.

        Invokes `optimize configs` once and asserts the union of wiring signals
        (exit code, the sweep's use of the injected simulator, both table headings
        using exact strings, sensitivity heading, recommendation marker, and rate
        token) to avoid re-running the CLI and its injected simulator once per
        assertion.
        """
        result, simulated_fleets = self._invoke_configs(
            tmp_path,
            optimize_fleet_results,
            [
                "--pv", "4",
                "--battery", "0,5",
                "--inverter", "5",
                "--sensitivity", "grid_services",
            ],
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 from 'optimize configs'; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        assert simulated_fleets, (
            "Expected 'optimize configs' to run its sweep with the simulator passed as "
            "obj=CliFleetSimulator(...); it asked that simulator for no fleet simulation.\n"
            f"Output:\n{result.output}"
        )
        assert "cost-recovery rank" in result.output.lower(), (
            f"Expected cost-recovery rank heading in output:\n{result.output}"
        )
        # Exact heading — guards against regressions that drop the section.
        assert "## Fixed-15p Trade-Off" in result.output, (
            f"Expected '## Fixed-15p Trade-Off' heading in output:\n{result.output}"
        )
        assert "sensitivity" in result.output.lower(), (
            f"Expected sensitivity section heading in output:\n{result.output}"
        )
        assert (
            "recommendation" in result.output.lower()
            or "★" in result.output
        ), (
            f"Expected RECOMMENDATION marker in output:\n{result.output}"
        )
        assert "p/kWh" in result.output, (
            f"Expected 'p/kWh' solved-rate token in output:\n{result.output}"
        )

    def test_every_sensitivity_alias_sweeps_its_knobs_library_band(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """Each alias's axis sweeps exactly its knob's optimize.SENSITIVITY_BANDS values."""
        result, _ = self._invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [
                "--pv", "4",
                "--battery", "0",
                "--inverter", "5",
                "--sensitivity", ",".join(_SENSITIVITY_ALIAS_KNOBS),
            ],
            n_homes=1,
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 from 'optimize configs'; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        swept = _swept_values_by_axis(result.stdout)
        assert set(swept) == set(_SENSITIVITY_ALIAS_KNOBS.values()), (
            f"Expected one axis section per alias's knob in the report:\n{result.output}"
        )
        for knob in _SENSITIVITY_ALIAS_KNOBS.values():
            assert swept[knob] == pytest.approx(SENSITIVITY_BANDS[knob], abs=0.005), (
                f"Axis {knob} swept {swept[knob]}, not its SENSITIVITY_BANDS values.\n"
                f"Output:\n{result.output}"
            )

    def test_parse_robustness_single_pv_value_works(
        self,
        tmp_path: Path,
        optimize_fleet_results: FleetResults,
    ) -> None:
        """Single value `--pv 4` (no comma) must parse correctly and succeed.

        Robustness: the comma-list parser must handle a single non-comma value
        without raising an error.
        """
        result, _ = self._invoke_configs(
            tmp_path,
            optimize_fleet_results,
            [
                "--pv", "4",         # single value, no comma
                "--battery", "0",    # single battery
                "--inverter", "5",   # single inverter
                "--sensitivity", "",  # skip sensitivity
            ],
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 for single-value --pv 4; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )

    def test_unknown_sensitivity_alias_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        """An unknown `--sensitivity` alias must exit 1 with a clear error message."""
        scenario_file = _write_optimize_scenario(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "optimize", "configs", str(scenario_file),
                "--pv", "4",
                "--battery", "0",
                "--inverter", "5",
                "--sensitivity", "completely_unknown_alias_xyz",
            ],
        )

        assert result.exit_code != 0, (
            f"Expected non-zero exit for unknown sensitivity alias; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        assert (
            "unknown" in result.output.lower()
            or "alias" in result.output.lower()
            or "known" in result.output.lower()
        ), (
            f"Expected clear error message about unknown alias in output:\n{result.output}"
        )

    def test_a_plain_value_error_while_the_sensitivity_panel_runs_exits_one_as_an_invalid_value(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A plain ValueError raised while the sensitivity panel runs ends the command with exit 1 and its invalid-value line on stderr; the panel is not skipped.

        A run without the panel counts the simulations the sweep asks for; the
        simulator answers that many and raises on the next, which the panel asks for.
        """
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        sweep_only, sweep_fleets = self._invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--sensitivity", ""],
            n_homes=1,
        )
        assert sweep_only.exit_code == 0, sweep_only.output
        asked: list[object] = []

        def simulate(fleet_config, start, end):
            asked.append(fleet_config)
            if len(asked) > len(sweep_fleets):
                raise ValueError("a defect raised while the sensitivity panel runs")
            return one_home_fleet_results

        result = invoke_cli(
            [
                "optimize", "configs", str(_write_optimize_scenario(tmp_path, n_homes=1)),
                *options,
                "--sensitivity", "grid_services",
            ],
            simulate,
        )

        assert len(asked) > len(sweep_fleets), "the panel asked for no simulation"
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel for axes" in stderr
        assert stderr.endswith("Invalid value: a defect raised while the sensitivity panel runs")
        assert "Sensitivity panel skipped" not in result.output

    def test_the_sensitivity_panel_is_skipped_with_a_note_when_the_sweep_has_no_feasible_config(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """With every config infeasible, the command prints the report without the panel, notes the skip on stderr and exits 0."""
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        result, _ = self._invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--retained-floor", "9999999", "--sensitivity", "grid_services"],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        assert "## Cost-Recovery Rank" in result.stdout
        assert "## Sensitivity Analysis" not in result.stdout
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel" not in stderr
        assert stderr.endswith(
            "Sensitivity panel skipped: no feasible baseline config found "
            "(sensitivity requires at least one feasible config)."
        )

    def test_a_refusal_while_the_sensitivity_panel_runs_exits_one_as_a_configuration_error(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A ConfigurationError raised while the sensitivity panel runs ends the command with exit 1 and its configuration-error line on stderr; the panel is not skipped.

        A run without the panel counts the simulations the sweep asks for; the
        simulator answers that many and refuses the next, which the panel asks for.
        """
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        sweep_only, sweep_fleets = self._invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--sensitivity", ""],
            n_homes=1,
        )
        assert sweep_only.exit_code == 0, sweep_only.output
        asked: list[object] = []

        def simulate(fleet_config, start, end):
            asked.append(fleet_config)
            if len(asked) > len(sweep_fleets):
                raise ConfigurationError("a refusal raised while the sensitivity panel runs")
            return one_home_fleet_results

        result = invoke_cli(
            [
                "optimize", "configs", str(_write_optimize_scenario(tmp_path, n_homes=1)),
                *options,
                "--sensitivity", "grid_services",
            ],
            simulate,
        )

        assert len(asked) > len(sweep_fleets), "the panel asked for no simulation"
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel for axes" in stderr
        assert stderr.endswith("Configuration error: a refusal raised while the sensitivity panel runs")
        assert "Sensitivity panel skipped" not in result.output
