# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-task verify contract tests.

The orchestrator runs dark-factory-orchestrator.yaml's test_command in each
task's fresh worktree before merging it, so these tests run it the same way.
"""

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests._collect_only import requires_uv, run_collect_only
from tests._orchestrator_config import load_orchestrator_config

pytestmark = requires_uv

_WEB_TEST_MODULE = "tests/unit/test_web_app.py"

# The last lines of a collect-only listing carry pytest's errors and summary.
_OUTPUT_TAIL_CHARS = 5000


def _collect_with_test_command(
    project_root: Path, workdir: Path, *pytest_args: str
) -> subprocess.CompletedProcess[str]:
    """Run test_command verbatim, collect-only, with *pytest_args*, in a fresh uv environment under *workdir*.

    The environment holds exactly the extras the command names. The shared
    environment would prove nothing: `uv run` never uninstalls, so it keeps any
    extra an earlier `uv run` installed, and tests/unit/test_e2e_lane.py's
    nested run installs the web extra into it.
    """
    command = load_orchestrator_config(project_root)["test_command"]
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(workdir / "venv")
    return run_collect_only(command, project_root, *pytest_args, env=env)


def _modules_skipped_at_collection(junit_report: Path) -> dict[str, str]:
    """Map each module pytest skipped at collection to the reason it gave, per its JUnit report.

    A collect-only run executes no test, so every skipped testcase in its report
    is a module skipped at collection, named by the testcase.
    """
    skipped_modules: dict[str, str] = {}
    for case in ET.parse(junit_report).getroot().iter("testcase"):
        skipped = case.find("skipped")
        if skipped is not None:
            skipped_modules[case.attrib["name"]] = skipped.text or ""
    return skipped_modules


def test_verify_collects_the_web_tests_instead_of_skipping_them(project_root: Path, tmp_path: Path) -> None:
    """Run as the orchestrator runs it, test_command collects a web test module instead of skipping it.

    The module skips through pytest.importorskip("flask") unless test_command
    installs the web extra, and a collect-only run whose every module skipped
    exits NO_TESTS_COLLECTED, so the exit code alone tells the two apart.
    """
    assert (project_root / _WEB_TEST_MODULE).is_file(), (
        f"{_WEB_TEST_MODULE} is gone; point this probe at another test module that calls "
        "pytest.importorskip('flask')"
    )

    result = _collect_with_test_command(project_root, tmp_path, _WEB_TEST_MODULE)

    assert result.returncode == pytest.ExitCode.OK, (
        f"test_command {result.args!r} did not collect {_WEB_TEST_MODULE} (exit {result.returncode}); without "
        "the web extra that module, like every test module that needs the extra, skips through "
        "pytest.importorskip, so the verify passes while silently dropping their coverage\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_verify_collects_every_test_module_instead_of_skipping_any(project_root: Path, tmp_path: Path) -> None:
    """Run as the orchestrator runs it, test_command collects the whole default suite without skipping a module.

    A module whose optional dependency test_command does not install skips itself
    at collection through pytest.importorskip, yet the run still exits 0, so the
    verify would pass while silently dropping that module's coverage.
    """
    junit_report = tmp_path / "collection.xml"

    result = _collect_with_test_command(project_root, tmp_path, f"--junitxml={junit_report}")

    assert result.returncode == pytest.ExitCode.OK, (
        f"test_command {result.args!r} failed to collect the default suite (exit {result.returncode})\n"
        f"stdout tail:\n{result.stdout[-_OUTPUT_TAIL_CHARS:]}\nstderr:\n{result.stderr}"
    )
    skipped_modules = _modules_skipped_at_collection(junit_report)
    reasons = "\n".join(f"  {module}: {reason}" for module, reason in skipped_modules.items())
    assert not skipped_modules, (
        f"test_command {result.args!r} skipped {len(skipped_modules)} test modules at collection:\n{reasons}\n"
        "each skips itself through pytest.importorskip because test_command does not install what it needs, "
        "so the verify passes while silently dropping that coverage"
    )
