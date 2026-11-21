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
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.cli.utils import CliInvocation, root_invocation
from solar_challenge.fleet import FleetRunner, FleetSimulator, default_runner
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.weather import PvgisTmy, default_weather
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli

_DAY = "2024-06-21"


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

    def test_an_obj_that_is_not_an_invocation_is_refused_naming_both_types(self) -> None:
        with pytest.raises(TypeError) as refusal:
            root_invocation({"runner": None}, quiet=False, workers=None, sequential=False)

        assert "CliInvocation" in str(refusal.value)
        assert "dict" in str(refusal.value)


_ONE_HOME_SCENARIO = {
    "name": "Invocation",
    "homes": [
        {
            "name": "Only Home",
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        }
    ],
    "finance": {"standing_charge_pence_per_day": 28.0},
}

_ONE_JUNE_DAY = ("--start", _DAY, "--end", _DAY)

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
