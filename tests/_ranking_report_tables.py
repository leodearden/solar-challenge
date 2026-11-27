# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the tables of a config-ranking report, board_report.generate_config_ranking_report's, which `optimize configs` prints, by heading and config label.

Usage::

    from tests._ranking_report_tables import TRADE_OFF, config_row

    row = config_row(report, TRADE_OFF, "4.0 kWp / 0.0 kWh / 5.0 kW")
    assert row["Baseline Outlay (£/yr)"] == "£375.00"
"""

from collections.abc import Iterable

TRADE_OFF = "## Configured-Rate Trade-Off"
"""The heading of the report's second table: each feasible config's baseline pair at its configured own-use rate."""


def section_under(report: str, heading: str) -> str:
    """The text under *heading* in *report*, up to the next heading of any level, so a sub-section is never read as *heading*'s."""
    assert f"{heading}\n" in report, f"No {heading!r} heading in the report:\n{report}"
    return report.split(f"{heading}\n", 1)[1].split("\n#", 1)[0]


def config_row(report: str, heading: str, config_label: str) -> dict[str, str]:
    """The row of the table in *heading*'s own section whose Config cell starts with *config_label*, each cell keyed by its column header."""
    section = section_under(report, heading)
    header, _delimiter_row, *rows = (
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    )
    matches = [row for row in rows if row[0].startswith(config_label)]
    assert len(matches) == 1, f"Expected one {config_label!r} row under {heading!r}:\n{section}"
    return dict(zip(header, matches[0], strict=True))


def config_column(report: str, heading: str, column: str, labels: Iterable[str]) -> dict[str, str]:
    """The *column* cell of each of *labels*' rows in *heading*'s table, keyed by label."""
    return {label: config_row(report, heading, label)[column] for label in labels}
