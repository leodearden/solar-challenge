# SPDX-License-Identifier: AGPL-3.0-or-later
"""`fleet run` on a scenario whose events configuration is dispatched discharges every battery home in the drawn event windows.

docs/prds/event-dispatch-and-battery-sizing.md §5.3's enrolment, seen through the CLI: on a sunless
winter week every kWh the fleet exports is battery export, so the aggregate CSV's grid export
shows where the batteries discharged. An observed configuration, the default, exports nothing.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.config import load_scenario
from solar_challenge.gridservices import EventWindow, drawn_event_days
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import sunless_tmy

_FIRST_DAY = date(2024, 1, 15)
_LAST_DAY = date(2024, 1, 19)
_EVENT_WINDOW = EventWindow(
    months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), events_per_year=35, event_hours=3.0
)
"""35 events over 2024's 87 eligible days: over the scenario's five weekdays, 35 × 5/87 draws 2."""
_EVENT_WINDOW_BLOCK = {
    "months": list(_EVENT_WINDOW.months),
    "weekdays": list(_EVENT_WINDOW.weekdays),
    "hours": list(_EVENT_WINDOW.hours),
    "events_per_year": _EVENT_WINDOW.events_per_year,
    "event_hours": _EVENT_WINDOW.event_hours,
}
_EVENT_DAY_SEED = 5


def _battery_home(name: str, capacity_kwh: float) -> dict[str, Any]:
    """A battery home on Economy 7 that grid-charges overnight and holds its charge for a 16:00 to 20:00 peak."""
    return {
        "name": name,
        "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
        "battery": {
            "capacity_kwh": capacity_kwh,
            "max_charge_kw": 2.5,
            "max_discharge_kw": 2.5,
            "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 20]]},
            "grid_charging": {"target_soc_fraction": 0.9},
        },
        "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        "tariff": {"type": "economy_7"},
    }


def _document(participation: Optional[str]) -> dict[str, Any]:
    events: dict[str, Any] = {
        "type": "capacity_at_events",
        "event_day_seed": _EVENT_DAY_SEED,
        "event_windows": [_EVENT_WINDOW_BLOCK],
    }
    if participation is not None:
        events["participation"] = participation
    return {
        "name": "Event enrolment",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
            "altitude": 11.0,
            "name": "Bristol, UK",
        },
        "period": {"start_date": _FIRST_DAY.isoformat(), "end_date": _LAST_DAY.isoformat()},
        "homes": [
            _battery_home("battery-5", 5.0),
            _battery_home("battery-8", 8.0),
            {
                "name": "pv-only",
                "pv": {"capacity_kw": 3.0, "azimuth": 180, "tilt": 35},
                "load": {"annual_consumption_kwh": 2800, "use_stochastic": False},
            },
        ],
        "seg": {"rate_pence_per_kwh": 15.0},
        "finance": {"standing_charge_pence_per_day": 60.0, "grid_services_model": events},
    }


def _aggregate_grid_export(
    tmp_path: Path, weather_cache: WeatherCache, participation: Optional[str]
) -> tuple[bytes, pd.Series]:
    """`fleet run`'s aggregate CSV for the scenario with *participation*, as written, and its grid export column."""
    label = participation or "omitted"
    scenario = tmp_path / f"enrolment-{label}.yaml"
    scenario.write_text(yaml.safe_dump(_document(participation)), encoding="utf-8")
    weather_cache.put(sunless_tmy(temp_air=5.0), "tmy", load_scenario(scenario).get_location())
    output = tmp_path / f"aggregate-{label}.csv"

    result = CliRunner().invoke(
        app, ["--sequential", "fleet", "run", str(scenario), "--output", str(output)], catch_exceptions=False
    )

    assert result.exit_code == 0, result.output
    frame = pd.read_csv(output, index_col=0)
    index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)).tz_convert("Europe/London")
    export = pd.Series(frame["grid_export_kw"].to_numpy(), index=index)
    return output.read_bytes(), export


def _scenario_days() -> tuple[date, ...]:
    return tuple(_FIRST_DAY + timedelta(days=offset) for offset in range((_LAST_DAY - _FIRST_DAY).days + 1))


def test_a_dispatched_fleet_exports_on_the_drawn_event_days_in_the_window_hours_and_nowhere_else(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    drawn = drawn_event_days(_EVENT_WINDOW, _scenario_days(), _EVENT_DAY_SEED, position=0)
    assert 0 < len(drawn) < len(_scenario_days())

    _, export = _aggregate_grid_export(tmp_path, weather_cache, "dispatched")

    in_the_windows = pd.Index(export.index.date).isin(drawn) & export.index.hour.isin(_EVENT_WINDOW.hours)
    assert (export[~in_the_windows] == 0).all()
    exporting_days = {day for day, kw in zip(export.index.date, export) if kw > 0}
    assert exporting_days == set(drawn)


def test_an_observed_fleet_and_one_that_omits_participation_export_nothing_and_write_the_same_csv(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    observed_csv, observed_export = _aggregate_grid_export(tmp_path, weather_cache, "observed")
    omitted_csv, _ = _aggregate_grid_export(tmp_path, weather_cache, None)

    assert (observed_export == 0).all()
    assert observed_csv == omitted_csv
