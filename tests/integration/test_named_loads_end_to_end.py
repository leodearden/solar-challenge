# SPDX-License-Identifier: AGPL-3.0-or-later
"""B8 of docs/prds/load-composition-and-calendar-days.md: a home's named loads, end to end.

`home run --report --output` of a home with a heat pump and an EV prints a Demand by load table
whose rows are each load, summing to the run's demand, and writes each load's column.
"""

from pathlib import Path

import pytest

from solar_challenge.weather import WeatherCache
from tests._home_run_demand import home_run
from tests._summary_report_tables import cells, energy_totals_demand_kwh, table_under

_OFF_PEAK_EV = {
    "charger_type": "7kW",
    "arrival_hour": 18,
    "departure_hour": 7,
    "required_charge_kwh": 35,
    "smart_charging_mode": "off_peak",
}


def test_home_run_report_lists_each_load_summing_to_the_demand(tmp_path: Path, weather_cache: WeatherCache) -> None:
    run = home_run(
        tmp_path,
        weather_cache,
        ev_block=_OFF_PEAK_EV,
        heat_pump_block={"heat_pump_type": "ASHP"},
        start="2024-03-30",
        end="2024-04-01",
    )
    lines = run.report.splitlines()

    _header, *rows = table_under(lines, "## Demand by load")

    assert [cells(row)[0] for row in rows] == ["Household", "Heat pump", "EV charging"]
    assert sum(float(cells(row)[1]) for row in rows) == pytest.approx(energy_totals_demand_kwh(lines), abs=0.1)
    assert len(run.frame) == 4_260
    assert {"heat_pump_load_kw", "ev_load_kw"} <= set(run.frame.columns)
