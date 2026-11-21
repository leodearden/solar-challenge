# SPDX-License-Identifier: AGPL-3.0-or-later
"""tests/conftest.py's lane_job_collection: a session collects each lane job once, whichever test modules ask for it."""

import shlex
import sys
from pathlib import Path

import pytest
import yaml

GIVES_EACH_COMMAND_THIS_PROCESS_ENVIRONMENT = """\
import os

import pytest


class _ThisProcessEnvironment:
    def for_command(self, command):
        return dict(os.environ)


@pytest.fixture(scope="session")
def shared_uv_probe_environments():
    return _ThisProcessEnvironment()
"""

APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG = """\
from pathlib import Path

with (Path(__file__).parent.parent / "collections.log").open("a", encoding="utf-8") as log:
    log.write("collected\\n")
"""


def _lane_project_logging_each_collection(lane_project: Path) -> Path:
    """Make *lane_project* a throwaway project whose one lane job, probe, runs this interpreter's pytest on suite/.

    The suite's conftest appends a line to the project's collections.log each time a collection loads it.
    """
    (lane_project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    command = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider suite"
    (lane_project / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"git": {"offline_lane_commands": [{"name": "probe", "command": command}]}}), encoding="utf-8"
    )
    suite = lane_project / "suite"
    suite.mkdir()
    (suite / "test_case.py").write_text("def test_case():\n    pass\n", encoding="utf-8")
    (suite / "conftest.py").write_text(APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG, encoding="utf-8")
    return lane_project


def _module_asking_for_the_probe_job_of(lane_project: Path) -> str:
    """Return a test module whose one test reads lane_job_collection's collection of *lane_project*'s probe job."""
    return f"""\
from pathlib import Path


def test_reads_the_probe_jobs_collection(lane_job_collection):
    collection = lane_job_collection(Path({str(lane_project)!r}), "probe")
    assert collection.node_ids() == ("suite/test_case.py::test_case",), collection.describe()
"""


def test_a_session_collects_a_lane_job_once_however_many_test_modules_ask_for_it(
    pytester_under_root_conftest: pytest.Pytester, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Two test modules of one session ask for a throwaway lane job, whose suite's conftest logs each collection.

    The job runs this interpreter's pytest and no uv, so the scenario's conftest
    gives each command this process's environment in place of the uv
    environments shared_uv_probe_environments builds.
    """
    lane_project = _lane_project_logging_each_collection(tmp_path_factory.mktemp("lane-project"))
    asking_module = _module_asking_for_the_probe_job_of(lane_project)
    pytester_under_root_conftest.makepyfile(
        **{
            "scenario/conftest": GIVES_EACH_COMMAND_THIS_PROCESS_ENVIRONMENT,
            "scenario/test_first": asking_module,
            "scenario/test_second": asking_module,
        }
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=2)
    collections = (lane_project / "collections.log").read_text(encoding="utf-8").splitlines()
    assert len(collections) == 1, (
        f"one session collected the probe lane job's suite {len(collections)} times for the two test modules that "
        "asked lane_job_collection for it; the modules of one session must share one collection, else each xdist "
        "worker collects a lane job once for every module that asks for it"
    )
