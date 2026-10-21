# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a pytest command verbatim in collect-only mode, for the orchestrator contract tests.

The command is a tests/_command_runner.Command, such as an OrchestratorCommand,
or a ShellCommand for one no dark-factory-orchestrator.yaml names, and it starts
through tests/_command_runner.run_command. collect() reads what the command
collected from the collection-report plugin, never from the command's output.
It loads the plugin by its name, COLLECTION_REPORT_PLUGIN, given to -p, from
COLLECTION_REPORT_PLUGIN_DIRECTORY (tests/_pytest_plugins) on PYTHONPATH. The
plugin's module docstring defines the report. run_collect_only, which collect()
runs through, returns only the finished process, for a probe that reads just a
command's exit code and output.

Usage::

    from tests._collect_only import collect, requires_uv, run_collect_only
    from tests._command_runner import ShellCommand, describe_outcome
    from tests._orchestrator_config import lane_command, verify_command

    collection = collect(lane_command(project_root, "e2e"), env=environment)
    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    node_ids = collection.node_ids()
    outside = collection.node_ids_outside("tests/e2e")
    skipped = collection.written_report().skipped_collectors

    collection = collect(ShellCommand("python -m pytest tests/unit", project_root), "-k", "battery")

    result = run_collect_only(verify_command(project_root, "test_command"), env=environment)
    assert result.returncode == 0, describe_outcome(result)
"""

import json
import os
import shlex
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess

import pytest

from tests._command_runner import Command, describe_outcome, run_command

requires_uv = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is not installed; the orchestrator command under test runs through it"
)

COLLECTION_REPORT_PLUGIN = "solar_challenge_collection_report"

COLLECTION_REPORT_PLUGIN_DIRECTORY = Path(__file__).resolve().parent / "_pytest_plugins"

# So that a hung probe fails its test instead of stalling the verify.
_COLLECT_TIMEOUT_SECS = 300


@dataclass(frozen=True)
class CollectedTest:
    """A test a collection selected: its node id, its file relative to the rootdir as node ids are, and its parametrize id, None if it is not parametrised."""

    node_id: str
    path: PurePosixPath
    parametrize_id: str | None


@dataclass(frozen=True)
class CollectionReport:
    """What the collection-report plugin reported.

    That is the tests the collection selected, in collection order, and the
    (node id, skip reason) of each collector it skipped, a module or a
    directory, in the order pytest reported them.
    """

    tests: tuple[CollectedTest, ...]
    skipped_collectors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Collection:
    """How a collect() run of *command* ended: its exit code, its stdout and stderr, and its report, None if it wrote none."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    report: CollectionReport | None

    def written_report(self) -> CollectionReport:
        """Return the run's report, asserting it wrote one: a run that wrote none never reads as an empty collection."""
        assert self.report is not None, (
            f"{self.command!r} wrote no collection report: its pytest never ran its collection "
            f"(uv refused, the shell failed, or an import crashed the session)\n{self.describe()}"
        )
        return self.report

    def node_ids(self) -> tuple[str, ...]:
        """Return the node ids of the tests the run collected, in collection order."""
        return tuple(test.node_id for test in self.written_report().tests)

    def node_ids_outside(self, path: str) -> tuple[str, ...]:
        """Return the node ids of the tests whose file is neither *path* nor under it; *path* is relative to the rootdir, as node ids are."""
        return tuple(test.node_id for test in self.written_report().tests if not test.path.is_relative_to(path))

    def describe(self) -> str:
        """Describe how the run ended, for an assertion message."""
        return describe_outcome(self)


def collect(
    command: Command,
    *pytest_args: str,
    env: Mapping[str, str] | None = None,
    timeout_secs: float = _COLLECT_TIMEOUT_SECS,
) -> Collection:
    """Run *command* as run_collect_only does, reading what its pytest collected from the collection-report plugin.

    The plugin's directory goes in front of the environment's PYTHONPATH, and
    the plugin's report is written to a temporary directory of collect()'s own.
    """
    collect_env = dict(os.environ if env is None else env)
    collect_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(COLLECTION_REPORT_PLUGIN_DIRECTORY), collect_env.get("PYTHONPATH")])
    )
    with tempfile.TemporaryDirectory(prefix="collection-report-") as report_directory:
        report_path = Path(report_directory) / "report.json"
        result = run_collect_only(
            command,
            "-p",
            COLLECTION_REPORT_PLUGIN,
            f"--collection-report={report_path}",
            *pytest_args,
            env=collect_env,
            timeout_secs=timeout_secs,
        )
        report = _read_report(report_path) if report_path.exists() else None
    return Collection(
        command=command.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        report=report,
    )


def _read_report(path: Path) -> CollectionReport:
    """Read the collection-report plugin's report at *path*; the plugin's module docstring defines its format."""
    report = json.loads(path.read_text(encoding="utf-8"))
    return CollectionReport(
        tests=tuple(
            CollectedTest(
                node_id=test["node_id"], path=PurePosixPath(test["path"]), parametrize_id=test["parametrize_id"]
            )
            for test in report["tests"]
        ),
        skipped_collectors=tuple((skipped["node_id"], skipped["reason"]) for skipped in report["skipped_collectors"]),
    )


def run_collect_only(
    command: Command,
    *pytest_args: str,
    env: Mapping[str, str] | None = None,
    timeout_secs: float = _COLLECT_TIMEOUT_SECS,
) -> CompletedProcess[str]:
    """Run *command* verbatim through run_command, in *env* (default: this process's environment).

    The pytest the command invokes only collects, with *pytest_args* added to its
    arguments. The mode travels in PYTEST_ADDOPTS, so the command's own args and
    the project's ini addopts stay in force. A command still running after
    *timeout_secs* raises run_command's CommandTimedOut.
    """
    collect_env = dict(os.environ if env is None else env)
    collect_env["PYTEST_ADDOPTS"] = shlex.join(["--collect-only", *pytest_args])
    return run_command(command, collect_env, timeout_secs=timeout_secs)
