# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_lane_collection.py, the lane contract tests' collect-only probe of an offline-lane job.

Each runs a throwaway project's lane job through this interpreter's pytest, with no uv and no mocks.
"""

import os
import shlex
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from tests._lane_collection import collect_lane_job

_PYTEST = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider"

_PROBE_VARIABLE = "LANE_COLLECTION_PROBE"

_IMPORT_ERROR_MESSAGE = "test_broken.py refuses to be imported"


def _project_with_lane_job(project_root: Path, command: str, **job_fields: str) -> Path:
    """Make *project_root* a throwaway project whose one offline-lane job, named probe, runs *command*."""
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project_root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"git": {"offline_lane_commands": [{"name": "probe", "command": command, **job_fields}]}}),
        encoding="utf-8",
    )
    return project_root


def test_returns_the_jobs_command_and_the_node_ids_it_collects_in_order(tmp_path: Path) -> None:
    command = f"{_PYTEST} test_kept.py"
    project_root = _project_with_lane_job(tmp_path, command)
    (project_root / "test_kept.py").write_text(
        "def test_alpha():\n    pass\n\n\ndef test_beta():\n    pass\n", encoding="utf-8"
    )

    collection = collect_lane_job(project_root, "probe", env=os.environ)

    assert collection.command == command
    assert collection.node_ids == ("test_kept.py::test_alpha", "test_kept.py::test_beta"), collection.outcome


def test_a_job_with_a_cwd_collects_from_that_directory(tmp_path: Path) -> None:
    """Run from the project root instead, its command would name a file that is not there."""
    project_root = _project_with_lane_job(tmp_path, f"{_PYTEST} test_in_suite.py", cwd="suite")
    (project_root / "suite").mkdir()
    (project_root / "suite" / "test_in_suite.py").write_text("def test_case():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, "probe", env=os.environ)

    assert collection.node_ids == ("suite/test_in_suite.py::test_case",), collection.outcome


def test_the_jobs_command_runs_in_the_given_environment_not_this_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As an inherited UV_FROZEN must not reach a lane job's `uv run --locked`."""
    project_root = _project_with_lane_job(tmp_path, f"{_PYTEST} test_environment.py")
    (project_root / "test_environment.py").write_text(
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
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")
    environment = {name: value for name, value in os.environ.items() if name != _PROBE_VARIABLE}

    collection = collect_lane_job(project_root, "probe", env=environment)

    assert collection.node_ids == ("test_environment.py::test_environment[unset]",), collection.outcome


def test_a_job_whose_command_fails_to_collect_fails_naming_the_job_its_command_and_the_error(
    tmp_path: Path,
) -> None:
    command = f"{_PYTEST} test_broken.py"
    project_root = _project_with_lane_job(tmp_path, command)
    (project_root / "test_broken.py").write_text(f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        collect_lane_job(project_root, "probe", env=os.environ)

    assert "'probe'" in str(failure.value)
    assert repr(command) in str(failure.value)
    assert _IMPORT_ERROR_MESSAGE in str(failure.value)


def test_a_job_whose_command_collects_nothing_fails_naming_the_job_and_its_command(tmp_path: Path) -> None:
    """pytest exits NO_TESTS_COLLECTED, as when a job's marker expression deselects every test its path names."""
    command = f"{_PYTEST} test_empty.py"
    project_root = _project_with_lane_job(tmp_path, command)
    (project_root / "test_empty.py").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        collect_lane_job(project_root, "probe", env=os.environ)

    assert "'probe'" in str(failure.value)
    assert repr(command) in str(failure.value)


def test_a_job_whose_command_exits_cleanly_without_collecting_returns_no_node_ids_and_its_output(
    tmp_path: Path,
) -> None:
    """Whether a job that collected nothing broke the lane is each lane test's job-specific assertion."""
    project_root = _project_with_lane_job(
        tmp_path, shlex.join([sys.executable, "-c", "print('this command never ran pytest')"])
    )

    collection = collect_lane_job(project_root, "probe", env=os.environ)

    assert collection.node_ids == (), collection.outcome
    assert "this command never ran pytest" in collection.outcome


def test_node_ids_outside_a_directory_are_those_collected_from_files_not_under_it(tmp_path: Path) -> None:
    """suite_extra, whose name merely starts with suite's, is not under suite."""
    project_root = _project_with_lane_job(tmp_path, f"{_PYTEST} suite suite_extra")
    for directory, module in (("suite", "test_in_suite.py"), ("suite_extra", "test_beside_suite.py")):
        (project_root / directory).mkdir()
        (project_root / directory / module).write_text("def test_case():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, "probe", env=os.environ)

    assert collection.node_ids_outside("suite") == ("suite_extra/test_beside_suite.py::test_case",), (
        collection.outcome
    )


def test_node_ids_outside_a_test_file_are_those_collected_from_any_other_file(tmp_path: Path) -> None:
    """The file's own ids stay inside though a parameter id holds a '/' or '::', and test_contract_extra.py is another file."""
    project_root = _project_with_lane_job(tmp_path, f"{_PYTEST} test_contract.py test_contract_extra.py")
    (project_root / "test_contract.py").write_text(
        textwrap.dedent(
            """\
            import pytest


            @pytest.mark.parametrize("value", ["a/b", "x::y"])
            def test_param(value):
                pass


            class TestGroup:
                def test_method(self):
                    pass
            """
        ),
        encoding="utf-8",
    )
    (project_root / "test_contract_extra.py").write_text("def test_case():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, "probe", env=os.environ)

    assert collection.node_ids_outside("test_contract.py") == ("test_contract_extra.py::test_case",), (
        collection.outcome
    )
