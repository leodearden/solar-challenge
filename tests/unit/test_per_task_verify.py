# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-task verify contract tests.

The orchestrator runs dark-factory-orchestrator.yaml's test_command in each
task's fresh worktree before merging it, so these tests run it the same way.
"""

from pathlib import Path

import pytest

from tests._collect_only import Collection, collect, requires_uv
from tests._orchestrator_config import verify_command
from tests._uv_env import SharedUvEnvironments

pytestmark = requires_uv

_WEB_TEST_MODULE = "tests/unit/test_web_app.py"


def _collect_with_test_command(
    project_root: Path, environments: SharedUvEnvironments, *pytest_args: str
) -> Collection:
    """Run test_command verbatim, collect-only, with *pytest_args*, in a fresh uv environment holding exactly the extras it names.

    The two tests here run the same command, so they share one environment. An
    environment shared with a command of other extras would prove nothing:
    `uv run` syncs inexactly, so it keeps any extra an earlier `uv run` installed.
    """
    command = verify_command(project_root, "test_command")
    return collect(command, *pytest_args, env=environments.for_command(command.command))


def test_verify_collects_the_web_tests_instead_of_skipping_them(
    project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    """Run as the orchestrator runs it, test_command collects a web test module instead of skipping it.

    The module skips through pytest.importorskip("flask") unless test_command
    installs the web extra, and a collect-only run whose every module skipped
    exits NO_TESTS_COLLECTED, so the exit code alone tells the two apart.
    """
    assert (project_root / _WEB_TEST_MODULE).is_file(), (
        f"{_WEB_TEST_MODULE} is gone; point this probe at another test module that calls "
        "pytest.importorskip('flask')"
    )

    collection = _collect_with_test_command(project_root, shared_uv_probe_environments, _WEB_TEST_MODULE)

    assert collection.returncode == pytest.ExitCode.OK, (
        f"test_command {collection.command!r} did not collect {_WEB_TEST_MODULE}; without "
        "the web extra that module, like every test module that needs the extra, skips through "
        "pytest.importorskip, so the verify passes while silently dropping their coverage\n"
        f"{collection.describe()}"
    )


def test_verify_collects_every_test_module_instead_of_skipping_any(
    project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    """Run as the orchestrator runs it, test_command collects the whole default suite without skipping a module.

    A module whose optional dependency test_command does not install skips itself
    at collection through pytest.importorskip, as does a directory whose conftest
    does, yet the run still exits 0, so the verify would pass while silently
    dropping that coverage.
    """
    collection = _collect_with_test_command(project_root, shared_uv_probe_environments)

    assert collection.returncode == pytest.ExitCode.OK, (
        f"test_command {collection.command!r} failed to collect the default suite\n{collection.describe()}"
    )
    skipped = collection.written_report().skipped_collectors
    reasons = "\n".join(f"  {node_id}: {reason}" for node_id, reason in skipped)
    assert not skipped, (
        f"test_command {collection.command!r} skipped {len(skipped)} test modules or directories at collection:\n"
        f"{reasons}\n"
        "each skips itself through pytest.importorskip because test_command does not install what it needs, "
        "so the verify passes while silently dropping that coverage"
    )
