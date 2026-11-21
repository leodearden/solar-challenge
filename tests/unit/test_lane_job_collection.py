# SPDX-License-Identifier: AGPL-3.0-or-later
"""tests/conftest.py's lane_job_collection: a run collects each lane job once, whichever of its workers and test modules ask for it.

Whichever test asks first, it fails each asking test that lacks a premise of
that collection: @requires_uv, or the callers_uv_lock_mode_is_frozen fixture.
Each scenario is one pytest run, under a copy of the root conftest, whose test
modules ask for a throwaway lane job. The job runs this interpreter's pytest
and no uv, so the scenario's conftest gives each command this process's
environment in place of the uv environments shared_uv_probe_environments builds.
"""

import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._throwaway_lane_project import PROBE_JOB, throwaway_lane_project

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

REQUIRES_UV = "@requires_uv"

FREEZES_THE_CALLERS_UV_LOCK_MODE = '@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")'


def _lane_project_logging_each_collection(lane_project: Path) -> Path:
    """Make *lane_project* a throwaway project whose one lane job, PROBE_JOB, runs this interpreter's pytest on suite/.

    The suite's conftest appends a line to the project's collections.log each time a collection loads it.
    """
    throwaway_lane_project(lane_project, f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider suite")
    suite = lane_project / "suite"
    suite.mkdir()
    (suite / "test_case.py").write_text("def test_case():\n    pass\n", encoding="utf-8")
    (suite / "conftest.py").write_text(APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG, encoding="utf-8")
    return lane_project


def _module_asking_for_the_probe_job_of(lane_project: Path, *decorators: str) -> str:
    """Return a test module whose one test, under *decorators*, reads lane_job_collection's collection of *lane_project*'s probe job.

    Before it asks, the test writes the id of the worker it runs on, "master" in
    a run without workers, to the file named for its module with the suffix .worker.
    """
    decorations = "".join(f"{decorator}\n" for decorator in decorators)
    return f"""\
from pathlib import Path

import pytest

from tests._collect_only import requires_uv


{decorations}def test_reads_the_probe_jobs_collection(lane_job_collection, request):
    worker = getattr(request.config, "workerinput", {{}}).get("workerid", "master")
    Path(__file__).with_suffix(".worker").write_text(worker, encoding="utf-8")
    collection = lane_job_collection(Path({str(lane_project)!r}), {PROBE_JOB!r})
    assert collection.node_ids() == ("suite/test_case.py::test_case",), collection.describe()
"""


def _run_scenario(pytester: pytest.Pytester, asking_modules: Mapping[str, str], *pytest_args: str) -> pytest.RunResult:
    """Run one pytest run, given *pytest_args*, of *asking_modules*, each written under scenario/ by its name, beside the scenario's conftest."""
    modules = {f"scenario/{name}": source for name, source in asking_modules.items()}
    pytester.makepyfile(**{"scenario/conftest": GIVES_EACH_COMMAND_THIS_PROCESS_ENVIRONMENT, **modules})
    return pytester.runpytest_subprocess(*pytest_args, "-p", "no:cacheprovider", "--tb=short")


@requires_uv
@pytest.mark.parametrize("mode", [("-n", "0"), ("-n", "2")], ids=["serially", "on-two-workers"])
def test_a_run_collects_a_lane_job_once_however_many_of_its_workers_and_test_modules_ask_for_it(
    pytester_under_root_conftest: pytest.Pytester, tmp_path_factory: pytest.TempPathFactory, mode: tuple[str, str]
) -> None:
    """Two test modules of one run ask for a throwaway lane job, whose suite's conftest logs each collection; on two workers, each worker runs one.

    Each asks with both premises every asking test carries, so this runs only where uv is installed.
    """
    lane_project = _lane_project_logging_each_collection(tmp_path_factory.mktemp("lane-project"))
    asking_module = _module_asking_for_the_probe_job_of(lane_project, REQUIRES_UV, FREEZES_THE_CALLERS_UV_LOCK_MODE)

    result = _run_scenario(
        pytester_under_root_conftest, {"test_first": asking_module, "test_second": asking_module}, *mode
    )

    result.assert_outcomes(passed=2)
    if mode == ("-n", "2"):
        recorded = (pytester_under_root_conftest.path / "scenario").glob("*.worker")
        workers = sorted(path.read_text(encoding="utf-8") for path in recorded)
        assert workers == ["gw0", "gw1"], (
            f"the two asking tests ran on {workers}, so not both workers asked for the lane job and this test cannot "
            "tell whether they share its collection"
        )
    collections = (lane_project / "collections.log").read_text(encoding="utf-8").splitlines()
    assert len(collections) == 1, (
        f"a run under {shlex.join(mode)} collected the {PROBE_JOB!r} lane job's suite {len(collections)} times for "
        "the two tests that asked lane_job_collection for it; the workers and test modules of one run must share one "
        "collection, else each worker collects the job itself"
    )


@requires_uv
def test_asking_without_freezing_the_callers_uv_lock_mode_fails_naming_its_fixture_before_or_after_the_collection(
    pytester_under_root_conftest: pytest.Pytester,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Of three modules asking for one job in one session, the two that do not freeze the caller's uv lock mode fail.

    The first asks before the frozen module collects the job and the last asks after, so whatever order a worker
    runs its tests in, no test reads a collection collected without the lock mode a caller's shell may freeze.
    """
    monkeypatch.delenv("UV_FROZEN", raising=False)
    lane_project = _lane_project_logging_each_collection(tmp_path_factory.mktemp("lane-project"))
    unfrozen = _module_asking_for_the_probe_job_of(lane_project, REQUIRES_UV)
    frozen = _module_asking_for_the_probe_job_of(lane_project, REQUIRES_UV, FREEZES_THE_CALLERS_UV_LOCK_MODE)

    result = _run_scenario(pytester_under_root_conftest, {"test_a": unfrozen, "test_b": frozen, "test_c": unfrozen})

    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(["scenario/test_a.py F*", "scenario/test_b.py .*", "scenario/test_c.py F*"])
    result.stdout.fnmatch_lines(
        ["E   AssertionError: *callers_uv_lock_mode_is_frozen*", "E   AssertionError: *callers_uv_lock_mode_is_frozen*"]
    )


def test_asking_where_uv_is_not_installed_fails_naming_requires_uv(
    pytester_under_root_conftest: pytest.Pytester,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no uv on PATH, a test that asks without @requires_uv, which would skip it there, fails naming it."""
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("path-without-uv")))
    lane_project = _lane_project_logging_each_collection(tmp_path_factory.mktemp("lane-project"))
    asking_module = _module_asking_for_the_probe_job_of(lane_project, FREEZES_THE_CALLERS_UV_LOCK_MODE)

    result = _run_scenario(pytester_under_root_conftest, {"test_only": asking_module})

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["E   AssertionError: *@requires_uv*"])
