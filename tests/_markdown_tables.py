# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the cells of a markdown table out of a report, by the heading the table sits under.

A table is read from the line after its heading up to the next line that starts
with #, so a row label one table shares with another, such as the bill
distribution's and the solved outlay's Mean, is read from the table asked for.

Usage::

    from tests._markdown_tables import row_cells, table_rows

    assert table_rows(report, "## Householder Bill")[0] == ["Line Item", "Physics"]
    (cell,) = row_cells(report, "## Householder Bill", "Own-Use Payment")
"""


def table_rows(report: str, heading: str) -> list[list[str]]:
    """The cells of each row of the table under *heading*, its header row first, read up to the next # line.

    *heading* must be one whole line of *report*, exactly once.
    """
    lines = report.splitlines()
    assert lines.count(heading) == 1, f"Expected one {heading!r} line in the report:\n{report}"
    rows: list[list[str]] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("|") and not line.startswith("|-"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def row_cells(report: str, heading: str, label: str) -> list[str]:
    """The value cells of the one row labelled *label* in the table under *heading*: every cell after its label."""
    matching = [cells for cells in table_rows(report, heading) if cells[0] == label]
    assert len(matching) == 1, f"Expected one {label!r} row under {heading!r}:\n{report}"
    return matching[0][1:]
