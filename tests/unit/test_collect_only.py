# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_collect_only.py, the collect-only runner the orchestrator contract tests share.

They pin that the command only collects, keeps its project's ini addopts in force, lists one node id
per line, receives each extra pytest arg whole, and runs in the environment it is given; and that a
failed run's description carries pytest's error report however long the listing, and the stderr of
a command that failed before pytest started.
"""

import os
import shlex
import sys
import textwrap
from pathlib import Path

import pytest

from tests._collect_only import collected_node_ids, describe_outcome, run_collect_only

_PYTEST = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider"

_PROBE_VARIABLE = "COLLECT_ONLY_PROBE"

_IMPORT_ERROR_MESSAGE = "test_broken.py refuses to be imported"

_STARTUP_ERROR_MESSAGE = "the command failed before pytest started"


def _module_of_failing_tests(*names: str) -> str:
    """Return the source of a test module defining one test per name in *names*, each failing if run."""
    return "".join(f"def {name}():\n    raise AssertionError('collect-only ran {name}')\n\n\n" for name in names)


@pytest.fixture
def project_with_ini_addopts(tmp_path: Path) -> Path:
    """A throwaway project whose ini addopts, like this repo's, raise the verbosity and ignore a test module."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -v --ignore=test_ignored.py\n", encoding="utf-8")
    (tmp_path / "test_kept.py").write_text(
        _module_of_failing_tests("test_alpha", "test_beta", "test_gamma"), encoding="utf-8"
    )
    (tmp_path / "test_ignored.py").write_text(_module_of_failing_tests("test_ignored"), encoding="utf-8")
    return tmp_path


@pytest.fixture
def project_echoing_its_environment(tmp_path: Path) -> Path:
    """A throwaway project whose one test's node id ends in the COLLECT_ONLY_PROBE it was collected under, or "unset"."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_environment.py").write_text(
        textwrap.dedent(
            f"""\
            import os

            import pytest


            @pytest.mark.parametrize("probe", [os.environ.get({_PROBE_VARIABLE!r}, "unset")])
            def test_environment(probe):
                raise AssertionError("collect-only ran test_environment")
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def project_with_a_long_listing_and_a_broken_module(tmp_path: Path) -> Path:
    """A throwaway project listing a thousand node ids, whose test_broken.py raises at import."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_many.py").write_text(
        textwrap.dedent(
            """\
            import pytest


            @pytest.mark.parametrize("case", range(1000))
            def test_case(case):
                raise AssertionError("collect-only ran test_case")
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "test_broken.py").write_text(f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8")
    return tmp_path


def test_lists_the_node_ids_the_projects_addopts_select_without_running_them(
    project_with_ini_addopts: Path,
) -> None:
    """The ini's -v would turn a -q listing into a tree with no node ids; clearing its addopts would collect test_ignored.py."""
    result = run_collect_only(_PYTEST, project_with_ini_addopts)

    assert result.returncode == pytest.ExitCode.OK, describe_outcome(result)
    assert collected_node_ids(result.stdout) == [
        "test_kept.py::test_alpha",
        "test_kept.py::test_beta",
        "test_kept.py::test_gamma",
    ], describe_outcome(result)


def test_each_extra_pytest_arg_reaches_pytest_whole(project_with_ini_addopts: Path) -> None:
    """Split on its spaces, the -k expression would leave pytest looking for files named or and beta."""
    result = run_collect_only(_PYTEST, project_with_ini_addopts, "-k", "alpha or beta")

    assert result.returncode == pytest.ExitCode.OK, describe_outcome(result)
    assert collected_node_ids(result.stdout) == [
        "test_kept.py::test_alpha",
        "test_kept.py::test_beta",
    ], describe_outcome(result)


def test_by_default_the_command_runs_in_this_process_environment(
    project_echoing_its_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")

    result = run_collect_only(_PYTEST, project_echoing_its_environment)

    assert result.returncode == pytest.ExitCode.OK, describe_outcome(result)
    assert collected_node_ids(result.stdout) == [
        "test_environment.py::test_environment[inherited]",
    ], describe_outcome(result)


def test_a_given_environment_replaces_this_process_environment(
    project_echoing_its_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is not merged over this process's, so a caller can drop a variable, as test_per_task_verify.py drops VIRTUAL_ENV."""
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")
    environment = {name: value for name, value in os.environ.items() if name != _PROBE_VARIABLE}

    result = run_collect_only(_PYTEST, project_echoing_its_environment, env=environment)

    assert result.returncode == pytest.ExitCode.OK, describe_outcome(result)
    assert collected_node_ids(result.stdout) == [
        "test_environment.py::test_environment[unset]",
    ], describe_outcome(result)


def test_a_failed_collection_is_described_by_its_error_report_however_long_the_listing(
    project_with_a_long_listing_and_a_broken_module: Path,
) -> None:
    """pytest reports collection errors after the listing, so a description bounded to the listing's tail keeps them."""
    result = run_collect_only(_PYTEST, project_with_a_long_listing_and_a_broken_module)

    description = describe_outcome(result)

    assert result.returncode == pytest.ExitCode.INTERRUPTED, description
    assert _IMPORT_ERROR_MESSAGE in description, description
    assert len(description) < len(result.stdout), (
        f"the description is {len(description)} characters long, no shorter than the "
        f"{len(result.stdout)}-character listing it describes"
    )


def test_a_command_that_fails_before_pytest_starts_is_described_by_its_stderr(tmp_path: Path) -> None:
    """As when uv cannot build the environment, the listing is empty and only stderr says what went wrong."""
    command = shlex.join([sys.executable, "-c", f"import sys; sys.exit({_STARTUP_ERROR_MESSAGE!r})"])

    description = describe_outcome(run_collect_only(command, tmp_path))

    assert _STARTUP_ERROR_MESSAGE in description, description
