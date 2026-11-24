# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home run` reads its file as config.load_scenario reads it and applies its options to the typed scenario."""

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.config import load_home_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import LOCATION_PRESETS, parse_location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._repository_paths import SCENARIOS_DIR

_DAY = "2024-06-21"


@pytest.fixture(autouse=True)
def _in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Work in tmp_path, so each test writes its file under a short relative name that Rich prints unfolded."""
    monkeypatch.chdir(tmp_path)


def _written(document: dict[str, Any], name: str = "home.yaml") -> Path:
    """Write *document* as YAML to *name* in the working directory."""
    path = Path(name)
    path.write_text(yaml.safe_dump(document))
    return path


def _home_run(*arguments: str) -> tuple[Result, RecordingSimulate]:
    """`home run` with *arguments*, its simulation answered by a RecordingSimulate, which it returns beside the result."""
    recorder = RecordingSimulate()
    result = invoke_cli(["home", "run", *arguments], answering(recorder))
    return result, recorder


def _stderr_text(result: Result) -> str:
    """The result's stderr with its whitespace collapsed, undoing Rich's wrap at 80 columns."""
    return " ".join(result.stderr.split())


class TestHomeRunFullConfigParity:
    """Tests that `home run` threads tariff + SEG via canonical parser (step-3/step-4)."""

    def _write_home_config(self, tmp_dir: Path, seg_yaml: str) -> Path:
        """Write a temp YAML config with tariff, followed by *seg_yaml*.

        Uses economy_7 (not flat_rate) because flat_rate has a known gap at 23:59
        that causes a simulation error on a full-day run; economy_7 fully covers
        all 24 hours via a midnight-crossing peak period.
        """
        cfg_path = tmp_dir / "home_seg.yaml"
        cfg_path.write_text(
            """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
    use_stochastic: false
  tariff:
    type: economy_7

"""
            + seg_yaml
        )
        return cfg_path

    def _run_home(self, tmp_path: Path, seg_yaml: str, *extra_args: str) -> tuple[Result, RecordingSimulate]:
        """Run `home run --report` for _DAY on a config ending in *seg_yaml*, its simulation answered by a RecordingSimulate.

        *extra_args* are appended to the command line after ``--report``.
        Returns the CLI result and the recorder, whose homes are the HomeConfigs
        `home run` asked the invocation's runner to simulate.
        """
        recorder = RecordingSimulate()
        cfg_path = self._write_home_config(tmp_path, seg_yaml)
        result = invoke_cli(
            ["home", "run", str(cfg_path), "--start", _DAY, "--end", _DAY, "--report", *extra_args],
            answering(recorder),
        )
        return result, recorder

    def test_home_run_threads_tariff_and_seg(self, tmp_path: Path) -> None:
        """home run passes tariff + seg to the home it simulates, and its report has no second, SEG Revenue section."""
        result, recorder = self._run_home(tmp_path, "seg:\n  rate_pence_per_kwh: 15.0\n")

        assert result.exit_code == 0, f"CLI failed: {result.stdout}"

        (home_cfg,) = recorder.homes
        # Tariff must be honoured by the canonical parser
        assert home_cfg.tariff_config is not None, (
            "tariff_config should not be None — canonical parser must pick it up"
        )

        # SEG must be threaded onto the HomeConfig
        assert home_cfg.seg_tariff is not None, (
            "seg_tariff should not be None — SEG must be threaded from top-level seg block"
        )
        assert home_cfg.seg_tariff.rate_pence_per_kwh == 15.0

        assert "## SEG Revenue" not in result.stdout

    def test_home_run_resolves_seg_preset(self, tmp_path: Path) -> None:
        """A top-level ``seg: {preset: Octopus}`` block prices exports at Octopus's rate."""
        result, recorder = self._run_home(tmp_path, "seg:\n  preset: Octopus\n")

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        (home_cfg,) = recorder.homes
        assert home_cfg.seg_tariff is not None
        assert home_cfg.seg_tariff.rate_pence_per_kwh == SEG_PRESETS["Octopus"].rate_pence_per_kwh
        assert "## SEG Revenue" not in result.stdout

    def test_home_run_rejects_unknown_seg_preset(self, tmp_path: Path) -> None:
        """An unknown SEG preset is refused with exit 1 before anything is simulated."""
        result, recorder = self._run_home(tmp_path, "seg:\n  preset: Nonexistent\n")

        assert result.exit_code == 1
        assert "Nonexistent" in result.output
        assert recorder.homes == []

    def test_home_run_location_option_reaches_home_config(self, tmp_path: Path) -> None:
        """``--location`` places the simulated home where location.parse_location puts it."""
        result, recorder = self._run_home(
            tmp_path,
            "seg:\n  rate_pence_per_kwh: 15.0\n",
            "--location",
            "55.95,-3.19",
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        (home_cfg,) = recorder.homes
        assert home_cfg.location == parse_location("55.95,-3.19")


_DETERMINISTIC_LOAD = {"annual_consumption_kwh": 3400, "use_stochastic": False}


@pytest.mark.parametrize(
    ("document", "names"),
    [
        pytest.param({"pv": {"capacity_kw": 9}}, ("pv", "home:"), id="flat-home"),
        pytest.param({"hom": {"pv": {"capacity_kw": 9}}}, ("'hom'",), id="misspelt-home-key"),
        pytest.param({"home": None}, ("home: must be a mapping",), id="null-home"),
        pytest.param({"homes": [{}]}, ("fleet run",), id="one-home-list"),
        pytest.param({"homes": [{}, {}]}, ("fleet run", "2 homes"), id="two-home-list"),
        pytest.param(
            {
                "fleet_distribution": {
                    "n_homes": 2,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3500},
                }
            },
            ("fleet run",),
            id="fleet-distribution",
        ),
    ],
)
def test_a_file_home_run_cannot_simulate_is_refused_by_name_and_nothing_is_simulated(
    document: dict[str, Any], names: tuple[str, ...]
) -> None:
    result, recorder = _home_run(str(_written(document)), "--start", _DAY, "--end", _DAY)

    assert result.exit_code == 1
    stderr = _stderr_text(result)
    assert stderr.startswith("Configuration error:"), stderr
    assert [name for name in names if name not in stderr] == [], stderr
    assert recorder.fleets == []


def _home_off_bristol_with_top_level_tariff_and_seg() -> Path:
    """Write home.yaml: 4 kW of PV and a deterministic 3400 kWh a year of load at 53.48, -2.24, on a top-level Economy 7 tariff and a 15p SEG rate."""
    return _written(
        {
            "location": {"latitude": 53.48, "longitude": -2.24, "timezone": "Europe/London"},
            "tariff": {"type": "economy_7"},
            "seg": {"rate_pence_per_kwh": 15.0},
            "home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD},
        }
    )


def _committed_bristol_arbitrage() -> Path:
    """The committed scenarios/bristol-arbitrage.yaml."""
    return SCENARIOS_DIR / "bristol-arbitrage.yaml"


@pytest.mark.parametrize(
    "home_file",
    [
        pytest.param(_home_off_bristol_with_top_level_tariff_and_seg, id="top-level-tariff-off-bristol"),
        pytest.param(_committed_bristol_arbitrage, id="bristol-arbitrage"),
    ],
)
def test_home_run_simulates_the_home_load_home_config_reads(home_file: Callable[[], Path]) -> None:
    path = home_file()

    result, recorder = _home_run(str(path), "--start", _DAY, "--end", _DAY)

    assert result.exit_code == 0, result.output
    assert recorder.homes == [load_home_config(path)]


def _with_pv_kw_9(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, pv_config=dataclasses.replace(home.pv_config, capacity_kw=9.0))


def _with_consumption_5000_kwh(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, load_config=dataclasses.replace(home.load_config, annual_consumption_kwh=5000.0))


def _in_edinburgh(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, location=LOCATION_PRESETS["edinburgh"])


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        pytest.param(("--pv-kw", "9"), _with_pv_kw_9, id="pv-kw"),
        pytest.param(("--consumption-kwh", "5000"), _with_consumption_5000_kwh, id="consumption-kwh"),
        pytest.param(("--location", "edinburgh"), _in_edinburgh, id="location"),
    ],
)
def test_each_option_replaces_only_its_own_setting_of_the_files_home(
    options: tuple[str, ...], expected: Callable[[HomeConfig], HomeConfig]
) -> None:
    path = _written(
        {
            "home": {
                "pv": {"capacity_kw": 4.0, "tilt": 20},
                "battery": {"capacity_kwh": 5.0},
                "load": _DETERMINISTIC_LOAD,
            }
        }
    )

    result, recorder = _home_run(str(path), "--start", _DAY, "--end", _DAY, *options)

    assert result.exit_code == 0, result.output
    assert recorder.homes == [expected(load_home_config(path))]


def _zero_pv_kw() -> None:
    dataclasses.replace(PVConfig(capacity_kw=4.0), capacity_kw=0.0)


def _zero_consumption_kwh() -> None:
    dataclasses.replace(LoadConfig(), annual_consumption_kwh=0.0)


@pytest.mark.parametrize(
    ("option", "construction"),
    [
        pytest.param("--pv-kw", _zero_pv_kw, id="pv-kw"),
        pytest.param("--consumption-kwh", _zero_consumption_kwh, id="consumption-kwh"),
    ],
)
def test_an_option_its_homes_config_refuses_is_refused_naming_the_option(
    option: str, construction: Callable[[], None]
) -> None:
    """The refusal is the config's own message under the option's name, since the user wrote no block for it."""
    with pytest.raises(ConfigurationError) as oracle:
        construction()

    result, recorder = _home_run("--start", _DAY, "--end", _DAY, option, "0")

    assert (result.exit_code, result.stdout) == (1, "")
    assert _stderr_text(result) == f"Configuration error: {option}: {oracle.value}"
    assert recorder.fleets == []


def _london(day: object) -> pd.Timestamp:
    """The local midnight starting *day* in Europe/London."""
    return pd.Timestamp(day, tz="Europe/London")


def _home_without_a_period() -> Path:
    """Write home.yaml: 4 kW of PV and a deterministic 3400 kWh a year of load, with no period:."""
    return _written({"home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD}})


@pytest.mark.parametrize(
    ("home_file", "flags", "first", "last"),
    [
        pytest.param(_committed_bristol_arbitrage, (), "2024-01-15", "2024-01-15", id="the-files-period"),
        pytest.param(
            _committed_bristol_arbitrage, ("--start", "2024-01-10"), "2024-01-10", "2024-01-15", id="start-flag"
        ),
        pytest.param(_committed_bristol_arbitrage, ("--end", "2024-01-20"), "2024-01-15", "2024-01-20", id="end-flag"),
        pytest.param(
            _committed_bristol_arbitrage,
            ("--start", "2024-01-10", "--end", "2024-01-20"),
            "2024-01-10",
            "2024-01-20",
            id="both-flags",
        ),
        pytest.param(_home_without_a_period, (), DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, id="no-period"),
        pytest.param(None, ("--end", "2024-01-31"), DEFAULT_FIRST_DAY, "2024-01-31", id="no-file-end-flag"),
    ],
)
def test_home_run_simulates_the_files_period_each_flag_replacing_only_its_own_day(
    home_file: Callable[[], Path] | None, flags: tuple[str, ...], first: object, last: object
) -> None:
    files = () if home_file is None else (str(home_file()),)

    result, recorder = _home_run(*files, *flags)

    assert result.exit_code == 0, result.output
    assert recorder.bounds == [(_london(first), _london(last))]


def test_home_run_names_the_window_it_simulates() -> None:
    result, _ = _home_run(str(_committed_bristol_arbitrage()), "--start", "2024-01-10")

    assert result.exit_code == 0, result.output
    assert "Simulating 6 days from 2024-01-10 to 2024-01-15" in _stderr_text(result)


def test_a_flag_day_that_leaves_no_window_is_refused_and_nothing_is_simulated() -> None:
    result, recorder = _home_run(str(_committed_bristol_arbitrage()), "--start", "2024-01-20")

    assert result.exit_code == 1
    stderr = _stderr_text(result)
    assert stderr.startswith("Configuration error:"), stderr
    assert [day for day in ("2024-01-20", "2024-01-15") if day not in stderr] == [], stderr
    assert recorder.fleets == []


def test_a_flag_that_is_not_a_date_is_a_usage_error() -> None:
    result, recorder = _home_run("--start", "2024-13-01")

    assert result.exit_code == 2
    assert recorder.fleets == []
