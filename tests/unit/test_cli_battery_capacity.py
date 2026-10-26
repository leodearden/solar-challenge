# SPDX-License-Identifier: AGPL-3.0-or-later
"""The home commands read a battery capacity as solar_challenge.battery.has_battery does.

0 is no battery, and a negative or non-finite capacity is refused, naming the
argument, before anything is simulated.
"""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.cli.home import home_config_for_run
from solar_challenge.cli.main import app
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-01"

bristol_june_tmy = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1).bristol_tmy_fixture()


@pytest.fixture(autouse=True)
def _bristol_june_tmy_in_tmp_path(
    bristol_june_tmy: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work in tmp_path.

    Before the fix, a command reads the capacity as no battery and simulates,
    so it fails its assertion instead of reaching PVGIS.
    """
    monkeypatch.chdir(tmp_path)


def _write_home_with_battery() -> Path:
    """Write home.yaml in the working directory: 4 kW of PV, a 5 kWh battery and a deterministic 3400 kWh a year of load."""
    path = Path("home.yaml")
    path.write_text(
        yaml.safe_dump(
            {
                "home": {
                    "pv": {"capacity_kw": 4.0},
                    "battery": {"capacity_kwh": 5.0},
                    "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                }
            }
        )
    )
    return path


def _stderr_text(result: Result) -> str:
    """The result's stderr with its whitespace collapsed, undoing Rich's wrap at 80 columns."""
    return " ".join(result.stderr.split())


@pytest.mark.parametrize("value", ["nan", "inf"])
def test_home_quick_refuses_a_battery_kwh_that_is_not_a_capacity(value: str) -> None:
    """`home quick`'s BATTERY_KWH is refused, naming it, when it is not a finite capacity."""
    result = runner.invoke(app, ["home", "quick", "4", value, "--days", "1"])

    assert result.exit_code == 1
    assert (
        f"Configuration error: battery_kwh must be a finite number, got {float(value)!r}"
        in _stderr_text(result)
    )


@pytest.mark.parametrize(
    ("value", "requirement"),
    [("nan", "a finite number"), ("inf", "a finite number"), ("-1", "at least 0")],
)
def test_home_run_refuses_a_battery_kwh_override_that_is_not_a_capacity(value: str, requirement: str) -> None:
    """`home run --battery-kwh` is refused, naming the option, when it is negative or not finite, instead of removing the file's battery."""
    _write_home_with_battery()

    result = runner.invoke(
        app, ["home", "run", "home.yaml", "--start", _DAY, "--end", _DAY, "--battery-kwh", value]
    )

    assert result.exit_code == 1
    assert (
        f"Configuration error: --battery-kwh must be {requirement}, got {float(value)!r}"
        in _stderr_text(result)
    )


def test_a_zero_battery_kwh_override_removes_the_files_battery() -> None:
    """`--battery-kwh 0` is no battery, as the option's help says."""
    assert home_config_for_run(_write_home_with_battery(), battery_kwh=0.0).battery_config is None
