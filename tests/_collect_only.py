# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a pytest command verbatim in collect-only mode, for the orchestrator contract tests.

Usage::

    from tests._collect_only import collected_node_ids, describe_outcome, requires_uv, run_collect_only

    result = run_collect_only(command, project_root)
    assert result.returncode == pytest.ExitCode.OK, describe_outcome(result)
    node_ids = collected_node_ids(result.stdout)
"""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

requires_uv = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is not installed; the orchestrator command under test runs through it"
)

_COLLECTION_REPORT_PLUGIN = "solar_challenge_collection_report"

_PLUGIN_DIRECTORY = Path(__file__).resolve().parent / "_pytest_plugins"

_OUTPUT_TAIL_CHARS = 5000


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
    output: str
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
        return _described(self.returncode, self.output)


def collect(command: str, cwd: Path, *pytest_args: str, env: Mapping[str, str] | None = None) -> Collection:
    """Run *command* as run_collect_only does, reading what its pytest collected from the collection-report plugin.

    The plugin's directory goes in front of the environment's PYTHONPATH, and
    the plugin's report is written to a temporary directory of collect()'s own.
    """
    collect_env = dict(os.environ if env is None else env)
    collect_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_PLUGIN_DIRECTORY), collect_env.get("PYTHONPATH")]))
    with tempfile.TemporaryDirectory(prefix="collection-report-") as report_directory:
        report_path = Path(report_directory) / "report.json"
        result = run_collect_only(
            command,
            cwd,
            "-p",
            _COLLECTION_REPORT_PLUGIN,
            f"--collection-report={report_path}",
            *pytest_args,
            env=collect_env,
        )
        report = _read_report(report_path) if report_path.exists() else None
    return Collection(command=command, returncode=result.returncode, output=result.stdout + result.stderr, report=report)


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
    command: str, cwd: Path, *pytest_args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run *command* verbatim in *cwd*, in *env* (default: this process's environment).

    The pytest the command invokes only collects, with *pytest_args* added to its
    arguments. The mode travels in PYTEST_ADDOPTS, so the command's own args and
    the project's ini addopts stay in force. It is --verbosity=-1 rather than -q
    because an ini -v cancels -q (tests/unit/test_collect_only.py pins this), so
    stdout lists one node id per line.
    """
    collect_env = dict(os.environ if env is None else env)
    collect_env["PYTEST_ADDOPTS"] = shlex.join(["--collect-only", "--verbosity=-1", *pytest_args])
    return subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        env=collect_env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def collected_node_ids(listing: str) -> list[str]:
    """Return the node ids, in order, in a run_collect_only stdout *listing*."""
    return [line for line in listing.splitlines() if "::" in line]


def _described(returncode: int, output: str) -> str:
    """Describe a run that ended with *returncode* after printing *output*, for an assertion message.

    The output is cut to its tail, where pytest reports collection errors and its summary.
    """
    return f"exit {returncode}\noutput tail:\n{output[-_OUTPUT_TAIL_CHARS:]}"


def describe_outcome(result: subprocess.CompletedProcess[str]) -> str:
    """Describe how a run_collect_only *result* ended, for an assertion message."""
    return _described(result.returncode, result.stdout + result.stderr)
