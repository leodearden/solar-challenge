# SPDX-License-Identifier: AGPL-3.0-or-later
"""One knob value gives one home at every entry point, the web sweep, `fleet sweep --param` and optimize's install grid: docs/prds/sweep-knob-registry.md §5 row I1 and §4.3 K9."""

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import NonCallableMagicMock

import pytest
import yaml

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig, parse_scenario, substitute_config_variables
from solar_challenge.home import HomeConfig, run_window
from solar_challenge.optimize import enumerate_configs
from solar_challenge.scenario_knobs import KNOBS
from solar_challenge.web.simulation_params import parse_home_config
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._fleet_sweep_paths import two_home_fleet_distribution
from tests._job_manager_double import autospecced_job_manager
from tests._web_app import app_builder

_KNOB = KNOBS["battery_capacity_kwh"]
_CAPACITY_KWH = 7.5
_DAY = "2024-06-21"

_POWER = {"max_charge_kw": 3.3, "max_discharge_kw": 3.3}
_BATTERY_BLOCK = {"capacity_kwh": 2.5, **_POWER}

_WEB_SWEEP = "web sweep"
_FLEET_SWEEP = "fleet sweep --param"
_INSTALL_GRID = "optimize install grid"


@dataclass(frozen=True)
class _Base:
    """One base, stated as a fleet document and as the web form of its home."""

    document: Mapping[str, object]
    base_config: Mapping[str, object]


_BASES = [
    pytest.param(
        _Base(
            document={"fleet_distribution": two_home_fleet_distribution(battery=_BATTERY_BLOCK)},
            base_config={"battery_kwh": 2.5, **_POWER, "days": 1},
        ),
        id="a-battery-of-non-default-power",
    ),
    pytest.param(
        _Base(
            document={"fleet_distribution": two_home_fleet_distribution()},
            base_config={**_POWER, "days": 1},
        ),
        id="no-battery",
    ),
]


@pytest.fixture
def job_manager() -> NonCallableMagicMock:
    """The dashboard's JobManager, autospecced, whose home submissions answer a job and run id each."""
    job_manager = autospecced_job_manager()
    job_manager.submit_home_job.return_value = ("job-home", "run-home")
    return job_manager


@pytest.fixture
def client(tmp_path: Path, closes_at_teardown: ExitStack, job_manager: NonCallableMagicMock) -> FlaskClient:
    """A client of the real dashboard app over *job_manager*."""
    return app_builder(closes_at_teardown)(tmp_path / "dashboard", jobs=lambda storage: job_manager).test_client()


@dataclass(frozen=True)
class _EntryPoints:
    """What each entry point simulates at the knob's value, and the base it read."""

    homes: Mapping[str, Sequence[HomeConfig]]
    bases: Mapping[str, ScenarioConfig]


def _web_base(base_config: Mapping[str, object]) -> ScenarioConfig:
    """The single-home scenario the web reads *base_config* as."""
    home, start_date, end_date, _ = parse_home_config(base_config)
    return ScenarioConfig(name="web base", period=run_window(home.location, start_date, end_date), home=home)


def _document_base(document: Mapping[str, object]) -> ScenarioConfig:
    """The scenario `fleet sweep --param` and the install grid read *document* as."""
    return parse_scenario(substitute_config_variables(dict(document)))


def _web_sweep_homes(client: FlaskClient, job_manager: NonCallableMagicMock, base_config: Mapping[str, object]) -> list[HomeConfig]:
    """The home the web sweep submits at the knob's value."""
    response = client.post(
        "/api/simulate/sweep",
        json={
            "parameter": _KNOB.name, "min": _CAPACITY_KWH, "max": 10.0, "steps": 2, "mode": "linear",
            "base_config": dict(base_config),
        },
    )
    assert response.status_code == 201, response.get_json()
    return [job_manager.submit_home_job.call_args_list[0].kwargs["config"]]


def _fleet_sweep_homes(tmp_path: Path, document: Mapping[str, object]) -> list[HomeConfig]:
    """The homes `fleet sweep --param` simulates at its first point, the knob's value."""
    fleet_file = tmp_path / "fleet.yaml"
    fleet_file.write_text(yaml.safe_dump(dict(document)))
    recorder = RecordingSimulate()
    result = invoke_cli(
        [
            "fleet", "sweep", str(fleet_file), "--param", _KNOB.name, "--min", str(_CAPACITY_KWH), "--max", "10",
            "--steps", "2", "--mode", "linear", "--start", _DAY, "--end", _DAY,
        ],
        answering(recorder),
    )
    assert result.exit_code == 0, result.output
    return list(recorder.fleets[0].homes)


def _install_grid_homes(base: ScenarioConfig) -> list[HomeConfig]:
    """The homes optimize's install grid simulates at a battery of the knob's value."""
    ((_, scenario),) = enumerate_configs(base, [4.0], [_CAPACITY_KWH], [3.68])
    return list(scenario.simulated_homes())


def _run_entry_points(
    base: _Base, client: FlaskClient, job_manager: NonCallableMagicMock, tmp_path: Path
) -> _EntryPoints:
    """Each entry point's homes at the knob's value, and the base each read, from *base*."""
    web_base = _web_base(base.base_config)
    document_base = _document_base(base.document)
    return _EntryPoints(
        homes={
            _WEB_SWEEP: _web_sweep_homes(client, job_manager, base.base_config),
            _FLEET_SWEEP: _fleet_sweep_homes(tmp_path, base.document),
            _INSTALL_GRID: _install_grid_homes(document_base),
        },
        bases={_WEB_SWEEP: web_base, _FLEET_SWEEP: document_base, _INSTALL_GRID: document_base},
    )


def _batteries(homes: Sequence[HomeConfig]) -> tuple[BatteryConfig | None, ...]:
    """Each of *homes*' battery, in order."""
    return tuple(home.battery_config for home in homes)


def _each_the_same(batteries: Mapping[str, tuple[Any, ...]], battery: object) -> dict[str, tuple[Any, ...]]:
    """*batteries* with each entry's every battery replaced by *battery*."""
    return {name: (battery,) * len(found) for name, found in batteries.items()}


@pytest.mark.parametrize("base", _BASES)
def test_each_entry_point_sets_the_battery_capacity_with_the_knobs_own_edit(
    base: _Base, client: FlaskClient, job_manager: NonCallableMagicMock, tmp_path: Path
) -> None:
    """Each entry point's batteries are those KNOBS['battery_capacity_kwh'].apply gives at the value on the base it read."""
    entry_points = _run_entry_points(base, client, job_manager, tmp_path)

    expected = {
        name: _batteries(_KNOB.apply(entry_base, _CAPACITY_KWH).simulated_homes())
        for name, entry_base in entry_points.bases.items()
    }
    assert {name: _batteries(homes) for name, homes in entry_points.homes.items()} == expected


@pytest.mark.parametrize("base", _BASES)
def test_the_three_entry_points_give_one_battery_between_them(
    base: _Base, client: FlaskClient, job_manager: NonCallableMagicMock, tmp_path: Path
) -> None:
    """The web form and the fleet document state one base battery, and the three entry points give one battery from it at the knob's value."""
    entry_points = _run_entry_points(base, client, job_manager, tmp_path)
    base_batteries = {name: _batteries(entry_base.simulated_homes()) for name, entry_base in entry_points.bases.items()}
    (base_battery,) = base_batteries[_WEB_SWEEP]
    assert base_batteries == _each_the_same(base_batteries, base_battery)

    batteries = {name: _batteries(homes) for name, homes in entry_points.homes.items()}
    (battery,) = batteries[_WEB_SWEEP]
    assert batteries == _each_the_same(batteries, battery)


def test_the_battery_base_keeps_a_power_a_fresh_battery_at_the_knobs_value_lacks() -> None:
    """The knob's battery on the battery base is not BatteryConfig(capacity_kwh=7.5), so the gate tells keeping the home's battery from building a fresh one."""
    base = _document_base({"fleet_distribution": two_home_fleet_distribution(battery=_BATTERY_BLOCK)})

    expected = _batteries(_KNOB.apply(base, _CAPACITY_KWH).simulated_homes())

    assert BatteryConfig(capacity_kwh=_CAPACITY_KWH) not in expected
    assert None not in expected
