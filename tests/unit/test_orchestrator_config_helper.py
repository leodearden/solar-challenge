# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_orchestrator_config.py, the orchestrator contract tests' reader of dark-factory-orchestrator.yaml.

Each test reads a throwaway project's yaml: its git mapping, its lane jobs, and
the OrchestratorCommand values built from its verify slots and lane jobs.
"""

import textwrap
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from tests._orchestrator_config import (
    OrchestratorCommand,
    git_config,
    lane_command,
    lane_commands,
    lane_jobs_declaring_an_outage_probe,
    lane_outage_probe,
    offline_lane_jobs,
    verify_command,
)

_COMMAND = "uv run --locked --extra dev pytest -m 'not slow' -p no:cacheprovider"

_OUTAGE_PROBE = "uv run --locked --extra dev python scripts/check.py"

_SLOT_COMMANDS = {
    "lint_command": "true",
    "type_check_command": "uv run --locked --extra dev mypy src/solar_challenge",
    "test_command": _COMMAND,
}

_VERIFY_SLOTS = (
    pytest.param("lint_command"),
    pytest.param("type_check_command"),
    pytest.param("test_command"),
)

_GIT_MAPPINGS_WITHOUT_LANE_JOBS = (
    pytest.param({"main_branch": "main"}, id="no-offline-lane-commands-key"),
    pytest.param({"offline_lane_commands": None}, id="bare-offline-lane-commands-key"),
    pytest.param({"offline_lane_commands": []}, id="empty-offline-lane-commands-list"),
)


def _write_orchestrator_config(project_root: Path, config: Mapping[str, object]) -> None:
    """Make *config* the whole of *project_root*'s dark-factory-orchestrator.yaml: its top-level slots and its git mapping."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(yaml.safe_dump(dict(config)), encoding="utf-8")


def _with_lane_jobs(*jobs: Mapping[str, object]) -> dict[str, object]:
    """Return an orchestrator config whose git.offline_lane_commands lists *jobs*, in order, and that holds nothing else."""
    return {"git": {"offline_lane_commands": list(jobs)}}


def test_the_git_mapping_is_read_whole_from_the_project_roots_orchestrator_config(tmp_path: Path) -> None:
    (tmp_path / "dark-factory-orchestrator.yaml").write_text(
        textwrap.dedent(
            """\
            test_command: "pytest"
            git:
              main_branch: "main"
              offline_lane_enabled: true
              offline_lane_commands:
                - name: probe
                  command: "pytest"
            """
        ),
        encoding="utf-8",
    )

    assert git_config(tmp_path) == {
        "main_branch": "main",
        "offline_lane_enabled": True,
        "offline_lane_commands": [{"name": "probe", "command": "pytest"}],
    }


def test_every_lane_job_is_listed_whole_in_config_order(tmp_path: Path) -> None:
    lane_jobs = [
        {"name": "probe", "command": "pytest", "fix_task_priority": "medium"},
        {"name": "e2e", "command": "pytest tests/e2e"},
    ]
    _write_orchestrator_config(tmp_path, _with_lane_jobs(*lane_jobs))

    assert offline_lane_jobs(tmp_path) == lane_jobs


@pytest.mark.parametrize("git", _GIT_MAPPINGS_WITHOUT_LANE_JOBS)
def test_a_git_mapping_without_lane_jobs_lists_none(tmp_path: Path, git: Mapping[str, object]) -> None:
    _write_orchestrator_config(tmp_path, {"git": git})

    assert offline_lane_jobs(tmp_path) == []


@pytest.mark.parametrize("slot", _VERIFY_SLOTS)
def test_a_verify_slot_is_its_yaml_string_verbatim_run_in_the_project_root_as_a_task_verify(
    tmp_path: Path, slot: str
) -> None:
    _write_orchestrator_config(tmp_path, _SLOT_COMMANDS)

    assert verify_command(tmp_path, slot) == OrchestratorCommand(
        label=slot, command=_SLOT_COMMANDS[slot], directory=tmp_path, role="task"
    )


@pytest.mark.parametrize("slot", _VERIFY_SLOTS)
def test_a_verify_slot_the_yaml_lacks_fails_naming_the_slot(tmp_path: Path, slot: str) -> None:
    _write_orchestrator_config(tmp_path, {})

    with pytest.raises(AssertionError) as failure:
        verify_command(tmp_path, slot)

    assert repr(slot) in str(failure.value)


@pytest.mark.parametrize("slot", _VERIFY_SLOTS)
def test_a_verify_slot_whose_value_is_not_a_string_fails_naming_the_slot(tmp_path: Path, slot: str) -> None:
    _write_orchestrator_config(tmp_path, {slot: None})

    with pytest.raises(AssertionError) as failure:
        verify_command(tmp_path, slot)

    assert repr(slot) in str(failure.value)


def test_a_slot_that_is_not_a_verify_slot_fails_naming_it_though_the_yaml_holds_it(tmp_path: Path) -> None:
    _write_orchestrator_config(tmp_path, {"check_command": _COMMAND})

    with pytest.raises(AssertionError) as failure:
        verify_command(tmp_path, "check_command")

    assert "'check_command'" in str(failure.value)


def test_a_lane_job_with_neither_cwd_nor_enabled_is_its_command_verbatim_run_in_the_project_root_offline(
    tmp_path: Path,
) -> None:
    _write_orchestrator_config(
        tmp_path,
        _with_lane_jobs({"name": "e2e", "command": "pytest tests/e2e"}, {"name": "probe", "command": _COMMAND}),
    )

    assert lane_command(tmp_path, "probe") == OrchestratorCommand(
        label="lane job 'probe'", command=_COMMAND, directory=tmp_path, role="offline"
    )


def test_a_lane_job_with_a_cwd_runs_in_that_directory_under_the_project_root(tmp_path: Path) -> None:
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "cwd": "tests/e2e"}))

    assert lane_command(tmp_path, "probe") == OrchestratorCommand(
        label="lane job 'probe'", command=_COMMAND, directory=tmp_path / "tests" / "e2e", role="offline"
    )


def test_a_lane_job_whose_enabled_flag_is_true_is_the_command_it_is_without_the_flag(tmp_path: Path) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "enabled": True}))

    assert lane_command(tmp_path, "probe") == OrchestratorCommand(
        label="lane job 'probe'", command=_COMMAND, directory=tmp_path, role="offline"
    )


@pytest.mark.parametrize(
    ("git", "count"),
    [
        pytest.param(
            {"offline_lane_commands": [{"name": "e2e", "command": "pytest tests/e2e"}]}, 0, id="no-job-named-probe"
        ),
        pytest.param({"offline_lane_commands": None}, 0, id="bare-offline-lane-commands-key"),
        pytest.param({"main_branch": "main"}, 0, id="no-offline-lane-commands-key"),
        pytest.param(
            {
                "offline_lane_commands": [
                    {"name": "probe", "command": "pytest"},
                    {"name": "probe", "command": "pytest tests/unit"},
                ]
            },
            2,
            id="two-jobs-named-probe",
        ),
    ],
)
def test_a_lane_job_named_other_than_once_fails_naming_the_job_and_its_count(
    tmp_path: Path, git: Mapping[str, object], count: int
) -> None:
    _write_orchestrator_config(tmp_path, {"git": git})

    with pytest.raises(AssertionError) as failure:
        lane_command(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert f"{count} entries" in str(failure.value)


@pytest.mark.parametrize("cwd", [None, ["tests", "e2e"]], ids=["bare-cwd-key", "list"])
def test_a_lane_job_whose_cwd_is_not_a_path_string_fails_naming_the_job_and_its_cwd(
    tmp_path: Path, cwd: object
) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "cwd": cwd}))

    with pytest.raises(AssertionError) as failure:
        lane_command(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert repr(cwd) in str(failure.value)


def test_a_lane_job_whose_cwd_names_no_directory_fails_naming_the_job_and_the_directory_it_resolves_to(
    tmp_path: Path,
) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "cwd": "tests/e2e"}))

    with pytest.raises(AssertionError) as failure:
        lane_command(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert str(tmp_path / "tests" / "e2e") in str(failure.value)


def test_a_disabled_lane_job_fails_naming_the_job_since_the_lane_never_runs_it(tmp_path: Path) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "enabled": False}))

    with pytest.raises(AssertionError) as failure:
        lane_command(tmp_path, "probe")

    assert "'probe'" in str(failure.value)


@pytest.mark.parametrize("enabled", [None, "false"], ids=["bare-enabled-key", "quoted-false"])
def test_a_lane_job_whose_enabled_flag_is_not_a_boolean_fails_naming_the_job_and_its_flag(
    tmp_path: Path, enabled: object
) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, "enabled": enabled}))

    with pytest.raises(AssertionError) as failure:
        lane_command(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert repr(enabled) in str(failure.value)


def test_every_lane_job_is_a_lane_command_as_lane_command_builds_it_in_config_order(tmp_path: Path) -> None:
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    _write_orchestrator_config(
        tmp_path,
        _with_lane_jobs(
            {"name": "probe", "command": _COMMAND},
            {"name": "e2e", "command": "pytest tests/e2e", "cwd": "tests/e2e", "enabled": True},
        ),
    )

    assert lane_commands(tmp_path) == (lane_command(tmp_path, "probe"), lane_command(tmp_path, "e2e"))


@pytest.mark.parametrize("git", _GIT_MAPPINGS_WITHOUT_LANE_JOBS)
def test_a_git_mapping_without_lane_jobs_gives_no_lane_commands(tmp_path: Path, git: Mapping[str, object]) -> None:
    _write_orchestrator_config(tmp_path, {"git": git})

    assert lane_commands(tmp_path) == ()


def test_the_lane_commands_of_a_lane_with_a_disabled_job_fail_naming_that_job(tmp_path: Path) -> None:
    _write_orchestrator_config(
        tmp_path,
        _with_lane_jobs(
            {"name": "probe", "command": _COMMAND},
            {"name": "dormant", "command": _COMMAND, "enabled": False},
        ),
    )

    with pytest.raises(AssertionError) as failure:
        lane_commands(tmp_path)

    assert "'dormant'" in str(failure.value)


def test_a_lane_jobs_outage_probe_is_its_yaml_string_verbatim_run_in_the_jobs_directory_offline(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    _write_orchestrator_config(
        tmp_path,
        _with_lane_jobs({"name": "probe", "command": _COMMAND, "cwd": "tests/e2e", "outage_probe": _OUTAGE_PROBE}),
    )

    assert lane_outage_probe(tmp_path, "probe") == OrchestratorCommand(
        label="outage probe of the lane job 'probe'",
        command=_OUTAGE_PROBE,
        directory=tmp_path / "tests" / "e2e",
        role="offline",
    )


@pytest.mark.parametrize(
    "declared",
    [{}, {"outage_probe": None}, {"outage_probe": ""}, {"outage_probe": ["python", "scripts/check.py"]}],
    ids=["no-outage-probe-key", "bare-outage-probe-key", "empty-string", "list"],
)
def test_a_lane_job_declaring_no_outage_probe_fails_naming_the_job(
    tmp_path: Path, declared: Mapping[str, object]
) -> None:
    _write_orchestrator_config(tmp_path, _with_lane_jobs({"name": "probe", "command": _COMMAND, **declared}))

    with pytest.raises(AssertionError) as failure:
        lane_outage_probe(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert repr(declared.get("outage_probe")) in str(failure.value)


def test_the_lane_jobs_declaring_an_outage_probe_are_those_whose_probe_is_not_none_in_config_order(
    tmp_path: Path,
) -> None:
    """A malformed probe, such as an empty string, counts as declared, so lane_outage_probe reports it."""
    _write_orchestrator_config(
        tmp_path,
        _with_lane_jobs(
            {"name": "a", "command": _COMMAND, "outage_probe": _OUTAGE_PROBE},
            {"name": "b", "command": _COMMAND},
            {"name": "c", "command": _COMMAND, "outage_probe": ""},
        ),
    )

    assert lane_jobs_declaring_an_outage_probe(tmp_path) == ("a", "c")


@pytest.mark.parametrize("git", _GIT_MAPPINGS_WITHOUT_LANE_JOBS)
def test_a_git_mapping_without_lane_jobs_has_no_job_declaring_an_outage_probe(
    tmp_path: Path, git: Mapping[str, object]
) -> None:
    _write_orchestrator_config(tmp_path, {"git": git})

    assert lane_jobs_declaring_an_outage_probe(tmp_path) == ()
