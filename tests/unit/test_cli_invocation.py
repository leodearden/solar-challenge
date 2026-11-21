# SPDX-License-Identifier: AGPL-3.0-or-later
"""What one CLI invocation runs with: the runner the root's --workers and --sequential build, and the runner every simulating command reads from the invocation.

No test here seeds any weather. Each command's simulations are answered by the
invocation's runner, a RecordingSimulate, so a command that bypassed it would
reach default_weather() and fail under the offline guard.
"""

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app, main
from solar_challenge.cli.utils import CliInvocation, invocation, root_invocation
from solar_challenge.fleet import FleetRunner, FleetSimulator, default_runner
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.weather import PvgisTmy, default_weather
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli

_DAY = "2024-06-21"

_DETERMINISTIC_LOAD = {"annual_consumption_kwh": 3400, "use_stochastic": False}

_ONE_HOME_SCENARIO = {
    "name": "Invocation",
    "homes": [{"name": "Only Home", "pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD}],
    "finance": {"standing_charge_pence_per_day": 28.0},
}

_TWO_HOME_FLEET = {
    "name": "Pair",
    "homes": [
        {"name": "North", "pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD},
        {"name": "South", "pv": {"capacity_kw": 3.0}, "battery": {"capacity_kwh": 5.0}, "load": _DETERMINISTIC_LOAD},
    ],
}

_TWO_HOMES_SWEEPING_THEIR_BATTERY = {
    "fleet_distribution": {
        "n_homes": 2,
        "seed": 42,
        "pv": {"capacity_kw": 4.0},
        "battery": {
            "capacity_kwh": {
                "type": "proportional_to",
                "source": "pv.capacity_kw",
                "multiplier": {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"},
            }
        },
        "load": _DETERMINISTIC_LOAD,
    }
}

_ONE_JUNE_DAY = ("--start", _DAY, "--end", _DAY)


def _what_the_runner_runs_with(runner: FleetSimulator) -> tuple[object, ...]:
    """runner's fields, its weather read as the cache directory its PvgisTmy reads: WeatherCache has no value equality, so no two default_runner() values are ==."""
    assert isinstance(runner, FleetRunner)
    assert isinstance(runner.weather, PvgisTmy) and runner.weather.cache is not None
    return (runner.weather.cache.cache_dir, runner.home_simulator, runner.parallel, runner.max_workers)


class TestRootWorkerPolicy:
    """The root's --workers and --sequential build the runner of an invocation nobody injected one into."""

    def test_help_lists_the_worker_options(self) -> None:
        result = CliRunner().invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--workers" in result.stdout
        assert "--sequential" in result.stdout

    def test_no_workers_is_a_usage_error_naming_the_option(self) -> None:
        result = CliRunner().invoke(app, ["--workers", "0", "config", "locations"])

        assert result.exit_code == 2
        assert "--workers" in " ".join(result.output.split())

    @pytest.mark.parametrize(
        ("root_options", "parallel", "max_workers", "quiet"),
        [
            pytest.param(("--sequential", "--workers", "3"), False, 3, False, id="sequential-on-3-workers"),
            pytest.param(("--quiet",), True, None, True, id="quiet"),
        ],
    )
    def test_the_root_callback_builds_the_invocation_from_the_options_it_parses(
        self, root_options: tuple[str, ...], parallel: bool, max_workers: int | None, quiet: bool
    ) -> None:
        """main, as a probe app's callback, gives the command nobody injected an invocation the invocation its options describe."""
        seen: list[CliInvocation] = []
        probe = typer.Typer()
        probe.callback()(main)

        @probe.command()
        def show(ctx: typer.Context) -> None:
            seen.append(invocation(ctx))

        result = CliRunner().invoke(probe, [*root_options, "show"])

        assert result.exit_code == 0, result.output
        assert [(_what_the_runner_runs_with(cli.runner), cli.quiet) for cli in seen] == [
            ((default_weather().cache.cache_dir, simulate_home, parallel, max_workers), quiet)
        ]

    def test_the_options_apply_to_default_runners_policy(self) -> None:
        """--sequential --workers 3 give replace(default_runner(), parallel=False, max_workers=3), compared field by field."""
        built = root_invocation(None, quiet=False, workers=3, sequential=True)

        assert _what_the_runner_runs_with(built.runner) == _what_the_runner_runs_with(
            dataclasses.replace(default_runner(), parallel=False, max_workers=3)
        )
        assert _what_the_runner_runs_with(built.runner) == (
            default_weather().cache.cache_dir, simulate_home, False, 3
        )
        assert built.quiet is False

    def test_without_the_options_the_runner_is_default_runners_policy(self) -> None:
        built = root_invocation(None, quiet=True, workers=None, sequential=False)

        assert _what_the_runner_runs_with(built.runner) == (
            default_weather().cache.cache_dir, simulate_home, True, None
        )
        assert built.quiet is True

    def test_an_injected_invocation_keeps_its_runner(self) -> None:
        injected = CliInvocation(runner=answering(RecordingSimulate()))

        built = root_invocation(injected, quiet=False, workers=2, sequential=True)

        assert built.runner is injected.runner
        assert built.quiet is False

    def test_quiet_silences_an_injected_invocation_and_keeps_its_runner(self) -> None:
        injected = CliInvocation(runner=answering(RecordingSimulate()))

        built = root_invocation(injected, quiet=True, workers=None, sequential=False)

        assert built.runner is injected.runner
        assert built.quiet is True

    def test_fleet_run_takes_no_worker_option_of_its_own(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        Path("fleet.yaml").write_text(yaml.safe_dump(_TWO_HOME_FLEET))

        result = CliRunner().invoke(app, ["fleet", "run", "fleet.yaml", "--workers", "2"])

        assert result.exit_code == 2
        assert "No such option" in " ".join(result.output.split())

    def test_an_obj_that_is_not_an_invocation_is_refused_naming_both_types(self) -> None:
        with pytest.raises(TypeError) as refusal:
            root_invocation({"runner": None}, quiet=False, workers=None, sequential=False)

        assert "CliInvocation" in str(refusal.value)
        assert "dict" in str(refusal.value)


HomeAsked = tuple[str, float, float | None]
"""A home the runner was asked for: its name, its PV kW and its battery kWh, None for no battery."""


@dataclasses.dataclass(frozen=True)
class _SimulatingRun:
    """A run of a simulating command: the files it reads, written in its working directory first, its argv, and the distinct fleets it asks the invocation's runner for, in the order first asked."""

    files: Mapping[str, object]
    argv: tuple[str, ...]
    fleets_asked: tuple[tuple[HomeAsked, ...], ...]


_SIMULATING_RUNS = (
    pytest.param(
        _SimulatingRun(
            files={"scenario.yaml": _ONE_HOME_SCENARIO},
            argv=("finance", "run", "scenario.yaml", *_ONE_JUNE_DAY),
            fleets_asked=((("Only Home", 4.0, None),),),
        ),
        id="finance-run",
    ),
    pytest.param(
        _SimulatingRun(
            files={"scenario.yaml": _ONE_HOME_SCENARIO},
            argv=(
                "optimize", "configs", "scenario.yaml",
                "--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", "", *_ONE_JUNE_DAY,
            ),
            fleets_asked=((("Only Home", 4.0, None),),),
        ),
        id="optimize-configs",
    ),
    pytest.param(
        _SimulatingRun(
            files={"scenario.yaml": _ONE_HOME_SCENARIO},
            argv=("--sequential", "--workers", "2", "finance", "run", "scenario.yaml", *_ONE_JUNE_DAY),
            fleets_asked=((("Only Home", 4.0, None),),),
        ),
        id="finance-run-under-the-root-worker-options",
    ),
    pytest.param(
        _SimulatingRun(
            files={"fleet.yaml": _TWO_HOME_FLEET},
            argv=("fleet", "run", "fleet.yaml", *_ONE_JUNE_DAY),
            fleets_asked=((("North", 4.0, None), ("South", 3.0, 5.0)),),
        ),
        id="fleet-run",
    ),
    pytest.param(
        _SimulatingRun(
            files={"fleet.yaml": _TWO_HOMES_SWEEPING_THEIR_BATTERY},
            argv=("fleet", "sweep", "fleet.yaml", *_ONE_JUNE_DAY),
            fleets_asked=(
                (("Home 1", 4.0, 5.0), ("Home 2", 4.0, 5.0)),
                (("Home 1", 4.0, 10.0), ("Home 2", 4.0, 10.0)),
            ),
        ),
        id="fleet-sweep",
    ),
    pytest.param(
        _SimulatingRun(
            files={"home.yaml": {"home": {"name": "My Home", "pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD}}},
            argv=("home", "run", "home.yaml", *_ONE_JUNE_DAY),
            fleets_asked=((("My Home", 4.0, None),),),
        ),
        id="home-run",
    ),
    pytest.param(
        _SimulatingRun(
            files={},
            argv=("home", "quick", "4", "5", "--days", "1"),
            fleets_asked=((("Quick Simulation", 4.0, 5.0),),),
        ),
        id="home-quick",
    ),
)


def _home_asked(home: HomeConfig) -> HomeAsked:
    """home as the runner was asked for it: its name, PV kW and battery kWh."""
    battery_kwh = None if home.battery_config is None else home.battery_config.capacity_kwh
    return (home.name, home.pv_config.capacity_kw, battery_kwh)


def _distinct_fleets_asked(recorder: RecordingSimulate) -> tuple[tuple[HomeAsked, ...], ...]:
    """Each distinct fleet recorder was asked for, as its homes, in the order first asked."""
    return tuple(dict.fromkeys(tuple(_home_asked(home) for home in fleet.homes) for fleet in recorder.fleets))


class TestEverySimulatingCommandRunsTheInvocationsSimulator:
    """Each command that simulates asks the invocation's runner, whatever the root's worker options say."""

    @pytest.mark.parametrize("run", _SIMULATING_RUNS)
    def test_the_command_asks_the_invocations_runner(
        self, run: _SimulatingRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for name, document in run.files.items():
            Path(name).write_text(yaml.safe_dump(document))
        recorder = RecordingSimulate()

        result = invoke_cli(list(run.argv), answering(recorder))

        assert result.exit_code == 0, result.output
        assert _distinct_fleets_asked(recorder) == run.fleets_asked
