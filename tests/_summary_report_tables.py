# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading generate_summary_report's markdown tables in a test: the one table under a heading, a row's cells, and the Energy Totals' demand.

Usage::

    from tests._summary_report_tables import cells, energy_totals_demand_kwh, table_under

    lines = generate_summary_report(results).splitlines()
    header, *rows = table_under(lines, "## Demand by load")
    assert sum(float(cells(row)[1]) for row in rows) == pytest.approx(energy_totals_demand_kwh(lines))
"""


def table_under(lines: list[str], heading: str) -> list[str]:
    """The lines of the markdown table right under the one *heading* in *lines*, up to the next blank line, its separator row left out: its header, then its rows."""
    assert lines.count(heading) == 1, f"{heading!r} is not in the report once"
    start = lines.index(heading) + 1
    end = lines.index("", start) if "" in lines[start:] else len(lines)
    header, _separator, *rows = lines[start:end]
    return [header, *rows]


def cells(row: str) -> list[str]:
    """The cells of a markdown table row, each stripped: "| Demand | 9.5 |" is ["Demand", "9.5"]."""
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def energy_totals_demand_kwh(lines: list[str]) -> float:
    """The Demand row's value in the report's Energy Totals table, in kWh."""
    (demand_row,) = [row for row in table_under(lines, "## Energy Totals (kWh)") if cells(row)[0] == "Demand"]
    return float(cells(demand_row)[1])
