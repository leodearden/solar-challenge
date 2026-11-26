# SPDX-License-Identifier: AGPL-3.0-or-later
"""G1 and G2 of docs/prds/one-scenario-reader.md §5: every scenario entry point simulates load_scenario(path).with_window(flags).simulated_homes() over its simulation_bounds(), and refuses what the reader refuses.

Each row's id names the leaf that turned it green, so a red node-id names the leaf whose entry point
re-reads a block of the file for itself. The expected homes, bounds and refusal messages are the
reader's own, never a literal copy of them.
"""

from __future__ import annotations

import dataclasses
import functools
import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import default_runner
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.scenario_blocks import child_path, parse_community_config, parse_tariff_config
from solar_challenge.scenario_writer import location_block
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from solar_challenge.weather import WeatherCache, WeatherProvider
from solar_challenge.web.dashboard import dashboard_of
from solar_challenge.web.jobs import JobManager
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._cli_stderr_text import stderr_text
from tests._cli_table_text import table_text
from tests._synthetic_weather import synthetic_tmy
from tests._web_app import app_builder

_PERIOD = {"start_date": "2024-06-03", "end_date": "2024-06-09"}
_TARIFF = {"type": "economy_7"}
_SEG = {"rate_pence_per_kwh": 12.0}
_FINANCE = {"standing_charge_pence_per_day": 28.0}

_HOME_BLOCK = {"pv": {"capacity_kw": 3.5}, "battery": {"capacity_kwh": 5.0}, "load": {"annual_consumption_kwh": 3200}}
_LARGER_PV_HOME_BLOCK = {**_HOME_BLOCK, "pv": {"capacity_kw": 5.0}}

_EDINBURGH = LOCATION_PRESETS["edinburgh"]
_BRISTOL = Location.bristol()

_SHARED_BLOCKS: dict[str, Any] = {"period": _PERIOD, "tariff": _TARIFF, "seg": _SEG, "finance": _FINANCE}

HOME: dict[str, Any] = {"name": "one home", "location": location_block(_EDINBURGH), **_SHARED_BLOCKS, "home": _HOME_BLOCK}
HOMES: dict[str, Any] = {
    "name": "two homes",
    "location": location_block(_EDINBURGH),
    **_SHARED_BLOCKS,
    "homes": [_HOME_BLOCK, _LARGER_PV_HOME_BLOCK],
}
FLEET_DISTRIBUTION: dict[str, Any] = {
    "name": "a fleet page fleet",
    "period": _PERIOD,
    "location": location_block(_BRISTOL),
    "fleet_distribution": {
        "n_homes": 3,
        "seed": 7,
        "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 0.5, "min": 2.5, "max": 6.0}},
        "battery": {
            "capacity_kwh": {"type": "uniform", "min": 3.0, "max": 8.0},
            "dispatch_strategy": {"strategy_type": "self_consumption"},
        },
        "load": {"annual_consumption_kwh": 3300.0},
    },
    "tariff": _TARIFF,
    "seg": _SEG,
    "finance": _FINANCE,
}
FLEET_DISTRIBUTION_AT_EDINBURGH: dict[str, Any] = {**FLEET_DISTRIBUTION, "location": location_block(_EDINBURGH)}


@dataclasses.dataclass(frozen=True)
class _Flags:
    """The days a run's --start and --end replace, as the CLI's flags, the fleet form's start and end and the reader's with_window give them."""

    first_day: Optional[date] = None
    last_day: Optional[date] = None

    def cli_args(self) -> tuple[str, ...]:
        """The --start and --end arguments that replace these days."""
        start = ("--start", self.first_day.isoformat()) if self.first_day is not None else ()
        end = ("--end", self.last_day.isoformat()) if self.last_day is not None else ()
        return (*start, *end)

    def on_form(self, form: Mapping[str, Any]) -> dict[str, Any]:
        """*form* with its start and end replaced by these days."""
        replaced = dict(form)
        if self.first_day is not None:
            replaced["start"] = self.first_day.isoformat()
        if self.last_day is not None:
            replaced["end"] = self.last_day.isoformat()
        return replaced

    def applied(self, scenario: ScenarioConfig) -> ScenarioConfig:
        """*scenario* as the reader's with_window replaces these days."""
        return scenario.with_window(first_day=self.first_day, last_day=self.last_day)


_FLAG_VARIANTS = {
    "no-flags": _Flags(),
    "start-flag": _Flags(first_day=date(2024, 6, 5)),
    "end-flag": _Flags(last_day=date(2024, 6, 6)),
}


def _shown_on_stderr(result: Result) -> str:
    return stderr_text(result)


def _shown_in_table(result: Result) -> str:
    return table_text(result.stdout)


@dataclasses.dataclass(frozen=True)
class _Command:
    """A command that reads a scenario file: the words that run it, the id of its rows, the leaf that turned its rows green, and how it reports a refusal.

    A refusal is reported as the text refusal_prefix then the reader's message, in the text shown(result) gives.
    """

    name: str
    words: tuple[str, ...]
    leaf: str
    shown: Callable[[Result], str] = _shown_on_stderr
    refusal_prefix: str = "Configuration error: "


_HOME_RUN = _Command("home-run", ("home", "run"), "task958-delta")
_FLEET_RUN = _Command("fleet-run", ("fleet", "run"), "task957-gamma-seg_task960-zeta-period")
_FINANCE_RUN = _Command("finance-run", ("finance", "run"), "task959-epsilon")
_OPTIMIZE_CONFIGS = _Command("optimize-configs", ("optimize", "configs"), "task959-epsilon")
_VALIDATE_CONFIG = _Command(
    "validate-config", ("validate", "config"), "task957-gamma", shown=_shown_in_table, refusal_prefix="ERROR "
)

_DOCUMENTS: dict[str, Mapping[str, Any]] = {
    "home-doc": HOME,
    "homes-doc": HOMES,
    "fleet-distribution-doc": FLEET_DISTRIBUTION_AT_EDINBURGH,
}
_FLEET_DOCUMENTS = {name: document for name, document in _DOCUMENTS.items() if name != "home-doc"}


def _flags_only_rows(leaf: str) -> list[Any]:
    """One row of (flags) for each flag variant, its id '<flags>-<leaf>'."""
    return [pytest.param(flags, id=f"{flags_name}-{leaf}") for flags_name, flags in _FLAG_VARIANTS.items()]


def _command_document_rows(commands: Sequence[_Command], documents: Mapping[str, Mapping[str, Any]], *, tag: str) -> list[Any]:
    """One row of (command, document) for each command and document, its id '<command>-<document>-<tag>-<leaf>'."""
    return [
        pytest.param(command, document, id=f"{command.name}-{document_name}-{tag}-{command.leaf}")
        for command in commands
        for document_name, document in documents.items()
    ]


def _command_document_flags_rows(commands: Sequence[_Command], documents: Mapping[str, Mapping[str, Any]]) -> list[Any]:
    """One row of (command, document, flags) for each command, document and flag variant, its id '<command>-<document>-<flags>-<leaf>'."""
    return [
        pytest.param(command, document, flags, id=f"{command.name}-{document_name}-{flags_name}-{command.leaf}")
        for command in commands
        for document_name, document in documents.items()
        for flags_name, flags in _FLAG_VARIANTS.items()
    ]


def _written(tmp_path: Path, document: Mapping[str, Any], *, name: str = "scenario.yaml") -> Path:
    """The path of *document*, written to *name* under *tmp_path* as YAML.

    The document goes through JSON first so that a block it holds twice is two blocks in the
    file, as a user's file has them, not an &anchor and its *alias.
    """
    path = tmp_path / name
    path.write_text(yaml.safe_dump(json.loads(json.dumps(document)), sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("document", "location"),
    [
        pytest.param(HOME, _EDINBURGH, id="home-doc"),
        pytest.param(HOMES, _EDINBURGH, id="homes-doc"),
        pytest.param(FLEET_DISTRIBUTION_AT_EDINBURGH, _EDINBURGH, id="fleet-distribution-doc"),
        pytest.param(FLEET_DISTRIBUTION, _BRISTOL, id="fleet-page-doc"),
    ],
)
def test_the_reader_gives_each_documents_homes_its_location_tariff_and_seg_over_its_period(
    tmp_path: Path, document: Mapping[str, Any], location: Location
) -> None:
    """Every CLI row below compares against homes that carry the document's location, tariff and SEG over its period, none of them the reader's default, so an entry point that drops one of them (task 957, γ) or runs the default year (task 956, β) cannot equal them.

    The fleet page's document sits at Bristol, the reader's default, because the fleet form has no location
    control; its dashboard rows therefore discriminate on the tariff, the SEG and the period alone.
    """
    scenario = load_scenario(_written(tmp_path, document))

    window = scenario.window()
    homes = scenario.simulated_homes()
    assert scenario.get_location() == location
    assert {home.location for home in homes} == {location}
    assert {home.tariff_config for home in homes} == {parse_tariff_config(_TARIFF)}
    assert {home.seg_tariff.rate_pence_per_kwh for home in homes if home.seg_tariff is not None} == {12.0}
    assert all(home.seg_tariff is not None for home in homes)
    assert (window.first_day, window.last_day) == (date(2024, 6, 3), date(2024, 6, 9))
    assert (window.first_day, window.last_day) != (DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)


@pytest.mark.parametrize(
    ("command", "document", "flags"),
    [
        *_command_document_flags_rows([_HOME_RUN], {"home-doc": HOME}),
        *_command_document_flags_rows([_FLEET_RUN, _FINANCE_RUN], _DOCUMENTS),
    ],
)
def test_each_command_simulates_the_readers_homes_over_its_bounds(
    tmp_path: Path, command: _Command, document: Mapping[str, Any], flags: _Flags
) -> None:
    """The command asks its runner for the homes and window of the reader's scenario with the flags' days replaced, and for nothing else."""
    path = _written(tmp_path, document)
    recorder = RecordingSimulate()

    result = invoke_cli([*command.words, str(path), *flags.cli_args()], answering(recorder))

    expected = flags.applied(load_scenario(path))
    assert result.exit_code == 0, result.output
    assert [fleet.homes for fleet in recorder.fleets] == [expected.simulated_homes()]
    assert recorder.bounds == [expected.simulation_bounds()]


def _as_installed_and_aged_like(read_home: HomeConfig, recorded_home: HomeConfig) -> HomeConfig:
    """*read_home* with the PV and battery fields an optimize point and a projection age set taken from *recorded_home*: PV capacity, inverter and age, and battery capacity and SOH.

    Age and SOH are set aside because run_cost_recovery simulates the projection's ages, and
    that ageing is projection.py's own, not the reader's. Every other field of the result is
    the reader's, so equal to *recorded_home* only when the sweep left the rest alone.
    """
    assert read_home.battery_config is not None and recorded_home.battery_config is not None
    return dataclasses.replace(
        read_home,
        pv_config=dataclasses.replace(
            read_home.pv_config,
            capacity_kw=recorded_home.pv_config.capacity_kw,
            inverter_capacity_kw=recorded_home.pv_config.inverter_capacity_kw,
            system_age_years=recorded_home.pv_config.system_age_years,
        ),
        battery_config=dataclasses.replace(
            read_home.battery_config,
            capacity_kwh=recorded_home.battery_config.capacity_kwh,
            soh=recorded_home.battery_config.soh,
        ),
    )


def _install_point(home: HomeConfig) -> tuple[float, Optional[float], float]:
    """The PV capacity, inverter capacity and battery capacity of *home*, which has a battery."""
    assert home.battery_config is not None
    return (home.pv_config.capacity_kw, home.pv_config.inverter_capacity_kw, home.battery_config.capacity_kwh)


@pytest.mark.parametrize(
    ("command", "document", "flags"),
    _command_document_flags_rows([_OPTIMIZE_CONFIGS], _FLEET_DOCUMENTS),
)
def test_optimize_configs_simulates_the_readers_homes_at_its_install_point_over_its_bounds(
    tmp_path: Path, command: _Command, document: Mapping[str, Any], flags: _Flags
) -> None:
    """Every fleet optimize asks for is the reader's homes in every field its install point and the projection's ages leave alone, at the one install point asked for, over the reader's bounds."""
    path = _written(tmp_path, document)
    recorder = RecordingSimulate()
    install_point = ("--pv", "4", "--battery", "5", "--inverter", "3.68", "--sensitivity", "")

    result = invoke_cli([*command.words, str(path), *install_point, *flags.cli_args()], answering(recorder))

    expected = flags.applied(load_scenario(path))
    assert result.exit_code == 0, result.output
    assert recorder.fleets
    assert set(recorder.bounds) == {expected.simulation_bounds()}
    assert {_install_point(home) for home in recorder.homes} == {(4.0, 3.68, 5.0)}
    for fleet in recorder.fleets:
        read_homes = tuple(
            _as_installed_and_aged_like(read_home, recorded_home)
            for read_home, recorded_home in zip(expected.simulated_homes(), fleet.homes, strict=True)
        )
        assert fleet.homes == read_homes


@pytest.mark.parametrize(
    "document", [pytest.param(document, id=f"{name}-{_VALIDATE_CONFIG.leaf}") for name, document in _DOCUMENTS.items()]
)
def test_validate_config_reads_each_document_as_valid(tmp_path: Path, document: Mapping[str, Any]) -> None:
    """validate config reads each document as valid and simulates nothing."""
    recorder = RecordingSimulate()

    result = invoke_cli(["validate", "config", str(_written(tmp_path, document))], answering(recorder))

    assert result.exit_code == 0, result.output
    assert "OK Configuration is valid" in table_text(result.stdout)
    assert recorder.fleets == []


@pytest.mark.parametrize(
    ("command", "document"),
    [
        *_command_document_rows([_HOME_RUN], {"home-doc": HOME}, tag="finanse"),
        *_command_document_rows([_FLEET_RUN, _FINANCE_RUN, _VALIDATE_CONFIG], _DOCUMENTS, tag="finanse"),
        *_command_document_rows([_OPTIMIZE_CONFIGS], _FLEET_DOCUMENTS, tag="finanse"),
    ],
)
def test_every_command_refuses_a_document_the_reader_refuses_with_the_readers_message(
    tmp_path: Path, command: _Command, document: Mapping[str, Any]
) -> None:
    """A document with a misspelt top-level key is refused by the command with the message load_scenario refuses it with, and nothing is simulated."""
    path = _written(tmp_path, {**document, "finanse": document["finance"]})
    with pytest.raises(ConfigurationError) as refused:
        load_scenario(path)
    message = str(refused.value)
    recorder = RecordingSimulate()

    result = invoke_cli([*command.words, str(path)], answering(recorder))

    assert result.exit_code == 1, result.output
    assert recorder.fleets == []
    assert f"{command.refusal_prefix}{message}" in command.shown(result)


_BAD_COMMUNITY: dict[str, Any] = {"sharing_mode": "p2p"}

_COMMUNITY_REFUSAL_DOCUMENTS: dict[str, tuple[Mapping[str, Any], str]] = {
    "bare": ({**HOMES, "community": _BAD_COMMUNITY}, ""),
    "scenario-block": ({"scenario": {**HOMES, "community": _BAD_COMMUNITY}}, "scenario"),
    "scenarios-entry": ({"scenarios": [HOMES, {**HOMES, "community": _BAD_COMMUNITY}]}, "scenarios[1]"),
}
"""Each document whose one bad community: block sits in a scenario, with the path of that scenario."""


def _command_community_rows(command: _Command, document_names: Sequence[str]) -> list[Any]:
    """One row of (command, document, scenario path) for each named community document, its id '<command>-<document>-community-task1739'."""
    return [
        pytest.param(command, *_COMMUNITY_REFUSAL_DOCUMENTS[name], id=f"{command.name}-{name}-community-task1739")
        for name in document_names
    ]


@pytest.mark.parametrize(
    ("command", "document", "scenario_path"),
    [
        *_command_community_rows(_VALIDATE_CONFIG, list(_COMMUNITY_REFUSAL_DOCUMENTS)),
        *_command_community_rows(_FLEET_RUN, ["bare", "scenario-block"]),
    ],
)
def test_a_community_block_is_refused_at_its_scenarios_path_with_the_community_readers_message(
    tmp_path: Path, command: _Command, document: Mapping[str, Any], scenario_path: str
) -> None:
    """A community: block is refused by the command with the message the community block reader gives it at its scenario's path, wherever that scenario sits, and nothing is simulated."""
    path = _written(tmp_path, document)
    with pytest.raises(ConfigurationError) as refused:
        parse_community_config(_BAD_COMMUNITY, block_path=child_path(scenario_path, "community"))
    message = str(refused.value)
    recorder = RecordingSimulate()

    result = invoke_cli([*command.words, str(path)], answering(recorder))

    assert result.exit_code == 1, result.output
    assert recorder.fleets == []
    assert f"{command.refusal_prefix}{message}" in command.shown(result)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({**HOMES, "community": {}}, id="bare-task1739"),
        pytest.param({"scenario": {**HOMES, "community": {}}}, id="scenario-block-task1739"),
    ],
)
def test_fleet_run_applies_the_community_block_wherever_its_one_scenario_sits(
    tmp_path: Path, document: Mapping[str, Any]
) -> None:
    """fleet run nets the reader's homes as a community, and writes the community report, whether the scenario holding the community: block is bare or a scenario: block."""
    path = _written(tmp_path, document)
    report = tmp_path / "community.md"
    recorder = RecordingSimulate()

    result = invoke_cli(["fleet", "run", str(path), "--community-report", str(report)], answering(recorder))

    assert result.exit_code == 0, result.output
    assert "Community Sharing Results" in result.stdout
    assert report.exists()
    assert [fleet.homes for fleet in recorder.fleets] == [load_scenario(path).simulated_homes()]


@pytest.mark.parametrize(
    "document", [pytest.param(document, id=f"{name}-{_HOME_RUN.leaf}") for name, document in _FLEET_DOCUMENTS.items()]
)
def test_home_run_refuses_a_fleet_document_naming_fleet_run(tmp_path: Path, document: Mapping[str, Any]) -> None:
    """home run refuses a document that holds a fleet, naming `fleet run` as the command that simulates it, and simulates nothing."""
    recorder = RecordingSimulate()

    result = invoke_cli([*_HOME_RUN.words, str(_written(tmp_path, document))], answering(recorder))

    assert result.exit_code == 1, result.output
    assert "`fleet run`" in stderr_text(result)
    assert recorder.fleets == []


_ALL_JOBS_DONE_WITHIN_SECONDS = 60


@pytest.mark.parametrize("flags", _flags_only_rows("task961-eta"))
def test_the_fleet_import_then_the_fleet_form_runs_the_readers_homes_over_its_bounds(
    tmp_path: Path, closes_at_teardown: ExitStack, flags: _Flags
) -> None:
    """The fleet page's import loads everything of the fleet document that reaches a home, and running the form it answers, with the flags' days, simulates the reader's homes over the reader's bounds."""
    path = _written(tmp_path, FLEET_DISTRIBUTION)
    recorder = RecordingSimulate()
    app = app_builder(closes_at_teardown)(
        tmp_path / "dashboard", jobs=functools.partial(JobManager, runner=answering(recorder))
    )
    client = app.test_client()

    imported = client.post("/api/fleet/import-yaml", data=path.read_text(encoding="utf-8"), content_type="text/yaml")
    assert imported.status_code == 200, imported.get_data(as_text=True)
    answer = imported.get_json()
    assert answer["not_loaded"] == ["finance"]
    submitted = client.post("/api/simulate/fleet-from-distribution", json=flags.on_form(answer["form"]))
    assert submitted.status_code == 201, submitted.get_data(as_text=True)
    assert dashboard_of(app).jobs.wait_until_idle(timeout=_ALL_JOBS_DONE_WITHIN_SECONDS)

    expected = flags.applied(load_scenario(path))
    assert [fleet.homes for fleet in recorder.fleets] == [expected.simulated_homes()]
    assert recorder.bounds == [expected.simulation_bounds()]


def test_the_fleet_import_refuses_a_document_the_reader_refuses_with_the_readers_message(
    tmp_path: Path, closes_at_teardown: ExitStack
) -> None:
    """task961-eta: the import answers a 400 carrying load_scenario's own refusal of a document with a misspelt top-level key, and runs nothing."""
    path = _written(tmp_path, {**FLEET_DISTRIBUTION, "finanse": FLEET_DISTRIBUTION["finance"]})
    with pytest.raises(ConfigurationError) as refused:
        load_scenario(path)
    recorder = RecordingSimulate()
    client = app_builder(closes_at_teardown)(
        tmp_path / "dashboard", jobs=functools.partial(JobManager, runner=answering(recorder))
    ).test_client()

    imported = client.post("/api/fleet/import-yaml", data=path.read_text(encoding="utf-8"), content_type="text/yaml")

    assert (imported.status_code, imported.get_json()) == (400, {"error": str(refused.value)})
    assert recorder.fleets == []


@dataclasses.dataclass
class _KeepingHomeSimulator:
    """A HomeSimulator that simulates each home as home.simulate_home does and keeps the results it returns in kept."""

    kept: list[SimulationResults] = dataclasses.field(default_factory=list)

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        results = simulate_home(config, start_date, end_date, weather=weather)
        self.kept.append(results)
        return results


@pytest.mark.parametrize("flags", _flags_only_rows("task894-s12-beta_task956-beta"))
def test_home_run_simulates_the_scenarios_window(tmp_path: Path, weather_cache: WeatherCache, flags: _Flags) -> None:
    """G2: home run's real simulate_home runs over the window of the scenario the reader reads, the flags' days replacing the file's: simulate_home builds its window first (S12 β, task 894) and the scenario gives the window (S6 β, task 956)."""
    path = _written(tmp_path, HOME)
    weather_cache.put(synthetic_tmy(), "tmy", load_scenario(path).get_location())
    keeping = _KeepingHomeSimulator()
    runner = dataclasses.replace(default_runner(), home_simulator=keeping, parallel=False)

    result = invoke_cli([*_HOME_RUN.words, str(path), *flags.cli_args()], runner)

    assert result.exit_code == 0, result.output
    (results,) = keeping.kept
    assert results.window == flags.applied(load_scenario(path)).window()
