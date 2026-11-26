# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finance report renders one value column per own-use basis it is given, and refuses sections that disagree (review-all S25 γ, B9).

``generate_finance_report`` reads a mapping of AssumptionSections keyed by
OwnUseBasis.  Every table of its bill, economics and cost-recovery blocks has
one value column per section, in OwnUseBasis order whatever the mapping's
order, headed by the section's label: Physics, or Spreadsheet with the override
its figures were computed under.  No heading names a mode.  It refuses, naming the values, an empty mapping (R1), a key its
section's finance is not on (R2), sections that carry different computations
(R3), and bills annualised from different windows (R4).
"""
from __future__ import annotations

from collections.abc import Callable

import pytest

from solar_challenge.board_report import ASSUMPTION_LABELS, AssumptionSection, generate_finance_report
from solar_challenge.finance import OwnUseBasis
from tests._assumption_sections import make_assumption_section, sections_of
from tests._factories import (
    make_bill_breakdown,
    make_bill_distribution,
    make_bill_distribution_from_statistics,
    make_cost_recovery_solution,
    make_project_economics,
)
from tests._finance_builders import make_window
from tests._markdown_tables import row_cells, table_rows

_BILL_HEADING = "## Householder Bill"
_DISTRIBUTION_HEADING = "## Per-Home Bill Distribution (Total Annual Outlay, £)"
_ECONOMICS_HEADING = "## Project Economics"
_COST_RECOVERY_HEADING = "## Cost-Recovery Analysis"
_SOLVED_OUTLAY_HEADING = "## Per-Home Total Outlay at Solved Rate (£)"

_FIRST_HEADERS = {
    _BILL_HEADING: "Line Item",
    _DISTRIBUTION_HEADING: "Metric",
    _ECONOMICS_HEADING: "Item",
    _COST_RECOVERY_HEADING: "Item",
    _SOLVED_OUTLAY_HEADING: "Metric",
}
"""Each table's heading, and the header of its label column."""

_SPREADSHEET_AT_70 = "Spreadsheet (70% self-consumption)"


def _physics_section() -> AssumptionSection:
    """A SIMULATED section paying £367.50, capex £250,000, solved at 15 p/kWh with a mean outlay of £300.00."""
    return make_assumption_section(
        OwnUseBasis.SIMULATED,
        bill=make_bill_distribution(representative=make_bill_breakdown(total_outlay_gbp=367.5)),
        economics=make_project_economics(total_capex_gbp=250_000.0),
        cost_recovery=make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, outlay=make_bill_distribution(mean_gbp=300.0)
        ),
    )


def _spreadsheet_section() -> AssumptionSection:
    """An OVERRIDE section at 70%, its every home paying £420.00, capex £300,000, solved at 18 p/kWh with a mean outlay of £320.00."""
    return make_assumption_section(
        OwnUseBasis.OVERRIDE,
        bill=make_bill_distribution_from_statistics(
            representative_outlay_gbp=420.0, min_gbp=420.0, mean_gbp=420.0, median_gbp=420.0, max_gbp=420.0
        ),
        economics=make_project_economics(total_capex_gbp=300_000.0),
        cost_recovery=make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=18.0, outlay=make_bill_distribution(mean_gbp=320.0)
        ),
    )


def _headings(report: str) -> list[str]:
    """Every line of *report* that starts with #."""
    return [line for line in report.splitlines() if line.startswith("#")]


class TestRefusals:
    """The report refuses, in this order and naming the values, sections it cannot render as one table per block."""

    def test_r1_no_section_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one section"):
            generate_finance_report({})

    def test_r2_an_override_key_over_a_simulated_finance_is_refused(self) -> None:
        with pytest.raises(ValueError, match="OVERRIDE") as refusal:
            generate_finance_report({OwnUseBasis.OVERRIDE: make_assumption_section(OwnUseBasis.SIMULATED)})

        assert "SIMULATED" in str(refusal.value)
        assert "None" in str(refusal.value)

    def test_r2_a_simulated_key_over_an_overridden_finance_is_refused(self) -> None:
        section = make_assumption_section(OwnUseBasis.OVERRIDE, override=0.6)

        with pytest.raises(ValueError, match="SIMULATED") as refusal:
            generate_finance_report({OwnUseBasis.SIMULATED: section})

        assert "OVERRIDE" in str(refusal.value)
        assert "0.6" in str(refusal.value)

    @pytest.mark.parametrize(
        ("computation", "carrying_it"),
        [
            ("economics", lambda: make_assumption_section(economics=make_project_economics())),
            ("cost_recovery", lambda: make_assumption_section(cost_recovery=make_cost_recovery_solution())),
        ],
        ids=["economics", "cost_recovery"],
    )
    def test_r3_sections_carrying_different_computations_are_refused(
        self, computation: str, carrying_it: Callable[[], AssumptionSection]
    ) -> None:
        with_it = carrying_it()
        without_it = make_assumption_section(OwnUseBasis.OVERRIDE)

        with pytest.raises(ValueError, match=computation):
            generate_finance_report(sections_of(with_it, without_it))

    def test_r4_bills_annualised_from_different_windows_are_refused(self) -> None:
        year, thirty_days = make_window(), make_window(days=30)
        physics = make_assumption_section(
            OwnUseBasis.SIMULATED, bill=make_bill_distribution(annualised_from=year)
        )
        spreadsheet = make_assumption_section(
            OwnUseBasis.OVERRIDE, bill=make_bill_distribution(annualised_from=thirty_days)
        )

        with pytest.raises(ValueError, match="annualised") as refusal:
            generate_finance_report(sections_of(physics, spreadsheet))

        assert repr(year) in str(refusal.value)
        assert repr(thirty_days) in str(refusal.value)


class TestColumns:
    """Each table has one value column per section, in OwnUseBasis order, headed by its section's label; no heading names a mode."""

    def test_columns_follow_the_basis_order_whatever_the_mappings_order(self) -> None:
        report = generate_finance_report(
            {OwnUseBasis.OVERRIDE: _spreadsheet_section(), OwnUseBasis.SIMULATED: _physics_section()}
        )

        for heading, first_header in _FIRST_HEADERS.items():
            assert table_rows(report, heading)[0] == [first_header, "Physics", _SPREADSHEET_AT_70], heading
        assert row_cells(report, _BILL_HEADING, "**Total Outlay**") == ["**£367.50**", "**£420.00**"]
        assert row_cells(report, _DISTRIBUTION_HEADING, "Max") == ["£367.50", "£420.00"]
        assert row_cells(report, _ECONOMICS_HEADING, "Total CapEx") == ["£250,000", "£300,000"]
        assert row_cells(report, _COST_RECOVERY_HEADING, "Solved Own-Use Rate") == ["15.00 p/kWh", "18.00 p/kWh"]
        assert row_cells(report, _SOLVED_OUTLAY_HEADING, "Mean") == ["£300.00", "£320.00"]

    @pytest.mark.parametrize(
        ("section", "label"),
        [(_physics_section, "Physics"), (_spreadsheet_section, _SPREADSHEET_AT_70)],
        ids=["physics", "spreadsheet"],
    )
    def test_a_one_mode_report_has_one_value_column_headed_by_its_mode(
        self, section: Callable[[], AssumptionSection], label: str
    ) -> None:
        report = generate_finance_report(sections_of(section()))

        for heading, first_header in _FIRST_HEADERS.items():
            table = table_rows(report, heading)
            assert table[0] == [first_header, label], heading
            assert all(len(row) == 2 for row in table), heading

    @pytest.mark.parametrize(
        "sections",
        [
            pytest.param(lambda: sections_of(_physics_section()), id="physics"),
            pytest.param(lambda: sections_of(_spreadsheet_section()), id="spreadsheet"),
            pytest.param(lambda: sections_of(_physics_section(), _spreadsheet_section()), id="both"),
        ],
    )
    def test_no_heading_names_a_mode(self, sections: Callable[[], dict[OwnUseBasis, AssumptionSection]]) -> None:
        report = generate_finance_report(sections())

        assert [line for line in _headings(report) if "Physics" in line or "Spreadsheet" in line] == []

    @pytest.mark.parametrize(
        ("override", "label"),
        [(0.6, "Spreadsheet (60% self-consumption)"), (0.455, "Spreadsheet (45.5% self-consumption)")],
    )
    def test_a_spreadsheet_column_is_headed_by_its_own_override(self, override: float, label: str) -> None:
        report = generate_finance_report(sections_of(make_assumption_section(OwnUseBasis.OVERRIDE, override=override)))

        assert table_rows(report, _BILL_HEADING)[0] == ["Line Item", label]

    def test_the_extrapolation_notice_renders_once_under_the_title(self) -> None:
        thirty_days = make_bill_distribution(annualised_from=make_window(days=30))

        report = generate_finance_report(
            sections_of(
                make_assumption_section(OwnUseBasis.SIMULATED, bill=thirty_days),
                make_assumption_section(OwnUseBasis.OVERRIDE, bill=thirty_days),
            )
        )

        lines = report.splitlines()
        assert report.count("*Yearly figures are extrapolated") == 1
        assert lines[0] == "# Finance Report"
        assert lines[1] == ""
        assert lines[2].startswith("*Yearly figures are extrapolated")


def test_each_basis_is_labelled_by_its_assumption() -> None:
    assert dict(ASSUMPTION_LABELS) == {OwnUseBasis.SIMULATED: "Physics", OwnUseBasis.OVERRIDE: "Spreadsheet"}
