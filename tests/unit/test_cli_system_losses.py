# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home run --system-losses` sets the home's PV system losses, as its pv: block's system_losses key does and over the file's own value.

A value PVConfig refuses is refused as that key is, before anything is simulated.
"""

import dataclasses
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.cli.home import home_config_for_run
from solar_challenge.cli.main import app
from solar_challenge.pv import PVConfig
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-01"

bristol_june_tmy = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1).bristol_tmy_fixture()


@pytest.fixture(autouse=True)
def _bristol_june_tmy_in_tmp_path(
    bristol_june_tmy: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work in tmp_path.

    A run the option fails to stop simulates the seeded clear June day, so it exits 0
    instead of reaching PVGIS.
    """
    monkeypatch.chdir(tmp_path)


def _write_home(name: str, **pv: float) -> Path:
    """Write *name* in the working directory: 4 kW of PV with the *pv* keys set, and a deterministic 3400 kWh a year of load."""
    path = Path(name)
    path.write_text(
        yaml.safe_dump(
            {
                "home": {
                    "pv": {"capacity_kw": 4.0, **pv},
                    "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                }
            }
        )
    )
    return path


def _home_run(path: Path, *options: str) -> Result:
    """`home run` of the file at *path* over the seeded day, with *options*."""
    return runner.invoke(
        app,
        ["home", "run", str(path), "--start", _DAY, "--end", _DAY, *options],
        catch_exceptions=False,
    )


def test_the_option_sets_the_homes_system_losses_and_nothing_else() -> None:
    """The option replaces the file's system_losses and leaves the rest of the home as the file sets it."""
    path = _write_home("home.yaml", system_losses=0.3)
    home = home_config_for_run(path)

    assert home_config_for_run(path, system_losses=0.05) == dataclasses.replace(
        home, pv_config=dataclasses.replace(home.pv_config, system_losses=0.05)
    )


@pytest.mark.parametrize(
    "files_own",
    [
        pytest.param({}, id="file-sets-none"),
        pytest.param({"system_losses": 0.3}, id="file-sets-0.3"),
    ],
)
def test_home_run_with_the_option_prints_what_a_pv_block_setting_it_prints(
    files_own: dict[str, float],
) -> None:
    """`--system-losses 0` prints the results a file whose pv: block sets system_losses: 0.0 prints, whatever the file sets itself."""
    overridden = _home_run(_write_home("override.yaml", **files_own), "--system-losses", "0")
    in_file = _home_run(_write_home("in_file.yaml", system_losses=0.0))

    assert (overridden.exit_code, in_file.exit_code) == (0, 0)
    assert overridden.stdout == in_file.stdout


@pytest.mark.parametrize("value", ["1", "-0.01", "nan", "inf"])
def test_a_value_pvconfig_refuses_is_refused_as_a_pv_block_setting_it_is(value: str) -> None:
    """A `--system-losses` PVConfig refuses stops `home run` with the error a pv: block setting it gives, carrying PVConfig's own message, before anything is simulated."""
    with pytest.raises(ValueError) as pv_refusal:
        PVConfig(capacity_kw=4.0, system_losses=float(value))

    overridden = _home_run(_write_home("override.yaml"), "--system-losses", value)
    in_file = _home_run(_write_home("in_file.yaml", system_losses=float(value)))

    assert (overridden.exit_code, overridden.stdout) == (1, "")
    assert overridden.stderr == in_file.stderr
    assert str(pv_refusal.value) in " ".join(overridden.stderr.split())
