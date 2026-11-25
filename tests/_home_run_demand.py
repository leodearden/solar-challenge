# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demand `home run --output` writes for scenarios/example-economy7.yaml with a deterministic load, its home's ev: and tariff: blocks set by the test.

Usage::

    from tests._home_run_demand import home_run_demand_kw

    def test_home_run_charges_the_ev(tmp_path, weather_cache):
        demand_kw = home_run_demand_kw(
            tmp_path,
            weather_cache,
            ev_block={"charger_type": "7kW", "smart_charging_mode": "off_peak"},
            tariff_block={"type": "economy_10"},
            start="2024-01-10",
            end="2024-01-11",
        )
"""

import tempfile
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


def home_run_demand_kw(
    tmp_path: Path,
    weather_cache: WeatherCache,
    *,
    ev_block: dict[str, Any] | None,
    tariff_block: dict[str, Any] | None = None,
    start: str,
    end: str,
) -> pd.Series:
    """The demand_kw that `home run --output` writes from *start* to *end*, on the scenario's clock, for scenarios/example-economy7.yaml.

    The scenario's home gets a deterministic load, *ev_block* as its ev: block, and
    *tariff_block*, when given, as its tariff: block in place of Economy 7. The run reads
    synthetic_tmy(), which this puts in *weather_cache* at Bristol, the scenario's location.
    It writes its scenario and CSV in a directory of its own under *tmp_path*, so one test
    can make several runs.
    """
    document = yaml.safe_load((SCENARIOS_DIR / "example-economy7.yaml").read_text())
    home = document["home"]
    home["load"]["use_stochastic"] = False
    home["ev"] = ev_block
    if tariff_block is not None:
        home["tariff"] = tariff_block
    run_dir = Path(tempfile.mkdtemp(dir=tmp_path))
    config_file = run_dir / "scenario.yaml"
    config_file.write_text(yaml.safe_dump(document))
    output = run_dir / "results.csv"
    weather_cache.put(synthetic_tmy(), "tmy", Location.bristol())

    result = CliRunner().invoke(
        app,
        ["home", "run", str(config_file), "--start", start, "--end", end, "--output", str(output)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    demand_kw = pd.read_csv(output, index_col=0)["demand_kw"]
    demand_kw.index = pd.to_datetime(demand_kw.index, utc=True).tz_convert(document["location"]["timezone"])
    return demand_kw
