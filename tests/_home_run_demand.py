# SPDX-License-Identifier: AGPL-3.0-or-later
"""What `home run --report --output` prints and writes for scenarios/example-economy7.yaml with a deterministic load, its home's ev:, heat_pump: and tariff: blocks set by the test: the report and the whole frame, or the frame's demand.

Usage::

    from tests._home_run_demand import home_run, home_run_demand_kw, home_run_frame

    def test_home_run_charges_the_ev(tmp_path, weather_cache):
        demand_kw = home_run_demand_kw(
            tmp_path,
            weather_cache,
            ev_block={"charger_type": "7kW", "smart_charging_mode": "off_peak"},
            tariff_block={"type": "economy_10"},
            start="2024-01-10",
            end="2024-01-11",
        )

    def test_home_run_reports_the_heat_pump(tmp_path, weather_cache):
        run = home_run(
            tmp_path,
            weather_cache,
            ev_block=None,
            heat_pump_block={"heat_pump_type": "ASHP"},
            start="2024-01-10",
            end="2024-01-11",
        )
        assert "| Heat pump |" in run.report
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._repository_paths import SCENARIOS_DIR
from tests._synthetic_weather import synthetic_tmy


@dataclass(frozen=True)
class HomeRun:
    """What one `home run --report --output` printed and wrote."""

    report: str
    frame: pd.DataFrame


def home_run(
    tmp_path: Path,
    weather_cache: WeatherCache,
    *,
    ev_block: dict[str, Any] | None,
    heat_pump_block: dict[str, Any] | None = None,
    tariff_block: dict[str, Any] | None = None,
    start: str,
    end: str,
) -> HomeRun:
    """What `home run --report --output` prints, and the CSV frame it writes on the scenario's clock, from *start* to *end* for scenarios/example-economy7.yaml.

    The scenario's home gets a deterministic load, *ev_block* as its ev: block,
    *heat_pump_block*, when given, as its heat_pump: block, and *tariff_block*, when given,
    as its tariff: block in place of Economy 7. The run reads synthetic_tmy(), which this
    puts in *weather_cache* at Bristol, the scenario's location. It writes its scenario and
    CSV in a directory of its own under *tmp_path*, so one test can make several runs.
    """
    document = yaml.safe_load((SCENARIOS_DIR / "example-economy7.yaml").read_text())
    home = document["home"]
    home["load"]["use_stochastic"] = False
    home["ev"] = ev_block
    if heat_pump_block is not None:
        home["heat_pump"] = heat_pump_block
    if tariff_block is not None:
        home["tariff"] = tariff_block
    run_dir = Path(tempfile.mkdtemp(dir=tmp_path))
    config_file = run_dir / "scenario.yaml"
    config_file.write_text(yaml.safe_dump(document))
    output = run_dir / "results.csv"
    weather_cache.put(synthetic_tmy(), "tmy", Location.bristol())

    result = CliRunner().invoke(
        app,
        ["home", "run", str(config_file), "--start", start, "--end", end, "--report", "--output", str(output)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    frame = pd.read_csv(output, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(document["location"]["timezone"])
    return HomeRun(report=result.output, frame=frame)


def home_run_frame(
    tmp_path: Path,
    weather_cache: WeatherCache,
    *,
    ev_block: dict[str, Any] | None,
    heat_pump_block: dict[str, Any] | None = None,
    tariff_block: dict[str, Any] | None = None,
    start: str,
    end: str,
) -> pd.DataFrame:
    """The CSV frame of home_run's run of the scenario with *ev_block*, *heat_pump_block* and *tariff_block*, from *start* to *end*."""
    return home_run(
        tmp_path,
        weather_cache,
        ev_block=ev_block,
        heat_pump_block=heat_pump_block,
        tariff_block=tariff_block,
        start=start,
        end=end,
    ).frame


def home_run_demand_kw(
    tmp_path: Path,
    weather_cache: WeatherCache,
    *,
    ev_block: dict[str, Any] | None,
    tariff_block: dict[str, Any] | None = None,
    start: str,
    end: str,
) -> pd.Series:
    """The demand_kw of home_run_frame's run of the scenario with *ev_block* and *tariff_block*, from *start* to *end*."""
    frame = home_run_frame(
        tmp_path, weather_cache, ev_block=ev_block, tariff_block=tariff_block, start=start, end=end
    )
    demand_kw: pd.Series = frame["demand_kw"]
    return demand_kw
