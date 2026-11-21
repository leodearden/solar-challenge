# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_lane_collection.py, the lane contract tests' collect-only probes.

There is one of an offline-lane job, one of a default collection of tests/, one
of a suite under a mark expression, and one of every test under tests/ under a
mark expression. Each runs a throwaway project's lane job, tests/ or suite
through this interpreter's pytest, with no uv and no mocks. The lane job's
probe also comes in a form that collects each job once for every call given one
collections directory.
"""

import os
import shlex
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

import pytest

from tests._collect_only import CollectedTest
from tests._lane_collection import (
    collect_lane_job,
    collect_lane_job_once,
    default_collection_node_ids_under,
    every_test_matching,
    suite_node_ids_matching,
    suite_tests_matching,
)
from tests._throwaway_lane_project import PROBE_JOB, throwaway_lane_project

_PYTEST = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider"

_PYTEST_INVOCATION = (sys.executable, "-m", "pytest")

_PROBE_VARIABLE = "LANE_COLLECTION_PROBE"

_ENVIRONMENT_PROBE_MODULE = textwrap.dedent(
    f"""\
    import os

    import pytest


    @pytest.mark.parametrize("probe", [os.environ.get({_PROBE_VARIABLE!r}, "unset")])
    def test_environment(probe):
        raise AssertionError("collect-only ran test_environment")
    """
)

_IMPORT_ERROR_MESSAGE = "test_broken.py refuses to be imported"

_SUITE = "tests/suite"

_SUITE_NODE_ID = f"{_SUITE}/test_in_suite.py::test_case"

_APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG = """\
from pathlib import Path

with (Path(__file__).parent / "collections.log").open("a", encoding="utf-8") as log:
    log.write("collected\\n")
"""


def _this_process_environment(command: str) -> Mapping[str, str]:
    """env_for for the probe jobs here, which run this interpreter's pytest and no uv: this process's environment, whatever the command."""
    return os.environ


def _project_with_a_suite(project_root: Path, *, ini: str = "[pytest]\n", conftest: str = "") -> Path:
    """Make *project_root* a throwaway project with *ini* as its pytest.ini and *conftest* as its tests/conftest.py.

    Its tests/ holds the suite, with one test, and one test beside it, which a
    default collection reaches too, so a probe's ids are visibly the suite's alone.
    """
    tests = project_root / "tests"
    suite = project_root / _SUITE
    suite.mkdir(parents=True)
    (project_root / "pytest.ini").write_text(ini, encoding="utf-8")
    (tests / "conftest.py").write_text(conftest, encoding="utf-8")
    (suite / "test_in_suite.py").write_text("def test_case():\n    pass\n", encoding="utf-8")
    (tests / "test_beside.py").write_text("def test_case():\n    pass\n", encoding="utf-8")
    return project_root


def _project_logging_each_collection(root: Path, test_module_source: str) -> Path:
    """Make *root* a throwaway project whose PROBE_JOB collects its test_kept.py, written from *test_module_source*.

    Its conftest appends a line to its collections.log each time a collection loads it.
    """
    root.mkdir()
    throwaway_lane_project(root, f"{_PYTEST} test_kept.py")
    (root / "test_kept.py").write_text(test_module_source, encoding="utf-8")
    (root / "conftest.py").write_text(_APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG, encoding="utf-8")
    return root


def _collections_logged(root: Path) -> int:
    """Return how many collections *root*'s conftest logged, 0 when it logged none."""
    log = root / "collections.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def test_returns_the_jobs_command_and_the_node_ids_it_collects_in_order(tmp_path: Path) -> None:
    command = f"{_PYTEST} test_kept.py"
    project_root = throwaway_lane_project(tmp_path, command)
    (project_root / "test_kept.py").write_text(
        "def test_alpha():\n    pass\n\n\ndef test_beta():\n    pass\n", encoding="utf-8"
    )

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert collection.command == command
    assert collection.node_ids() == ("test_kept.py::test_alpha", "test_kept.py::test_beta"), collection.describe()


def test_a_job_with_a_cwd_collects_from_that_directory(tmp_path: Path) -> None:
    """Run from the project root instead, its command would name a file that is not there."""
    project_root = throwaway_lane_project(tmp_path, f"{_PYTEST} test_in_suite.py", cwd="suite")
    (project_root / "suite").mkdir()
    (project_root / "suite" / "test_in_suite.py").write_text("def test_case():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert collection.node_ids() == ("suite/test_in_suite.py::test_case",), collection.describe()


def test_a_jobs_setup_steps_are_not_run_when_it_is_collected(tmp_path: Path) -> None:
    """Only the job's suite step runs, collecting only.

    A setup step provisions, as the e2e job's browser install does, and run in a
    verify it would write outside the test's tmp_path or reach the network.
    """
    project_root = throwaway_lane_project(tmp_path, f"touch setup-ran && {_PYTEST} test_kept.py")
    (project_root / "test_kept.py").write_text("def test_alpha():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert not (project_root / "setup-ran").exists()
    assert collection.command == f"{_PYTEST} test_kept.py"
    assert collection.node_ids() == ("test_kept.py::test_alpha",), collection.describe()


def test_the_jobs_command_runs_in_the_environment_env_for_returns_for_it_not_this_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command runs in the environment env_for returns when given that very command, not in this process's.

    So an environment keyed on the command, as a shared uv environment is, fits
    what runs, and an inherited UV_FROZEN never reaches a lane job's `uv run --locked`.
    """
    project_root = throwaway_lane_project(tmp_path, f"{_PYTEST} test_environment.py")
    (project_root / "test_environment.py").write_text(_ENVIRONMENT_PROBE_MODULE, encoding="utf-8")
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")
    asked_for: list[str] = []

    def env_for(command: str) -> dict[str, str]:
        asked_for.append(command)
        return {name: value for name, value in os.environ.items() if name != _PROBE_VARIABLE}

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=env_for)

    assert asked_for == [collection.command]
    assert collection.node_ids() == ("test_environment.py::test_environment[unset]",), collection.describe()


def test_a_job_whose_command_fails_to_collect_fails_naming_the_job_its_command_and_the_error(
    tmp_path: Path,
) -> None:
    command = f"{_PYTEST} test_broken.py"
    project_root = throwaway_lane_project(tmp_path, command)
    (project_root / "test_broken.py").write_text(f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert repr(PROBE_JOB) in str(failure.value)
    assert repr(command) in str(failure.value)
    assert _IMPORT_ERROR_MESSAGE in str(failure.value)


def test_a_job_whose_command_collects_nothing_fails_naming_the_job_and_its_command(tmp_path: Path) -> None:
    """pytest exits NO_TESTS_COLLECTED, as when a job's marker expression deselects every test its path names."""
    command = f"{_PYTEST} test_empty.py"
    project_root = throwaway_lane_project(tmp_path, command)
    (project_root / "test_empty.py").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert repr(PROBE_JOB) in str(failure.value)
    assert repr(command) in str(failure.value)


def test_a_job_whose_command_never_runs_pytest_has_no_node_ids_to_read(tmp_path: Path) -> None:
    """The command exits 0, yet reading its node ids fails, naming it and showing its output; it never reads as an empty suite.

    Its one word pytest is an argument it prints, which makes it the job's suite
    step. It prints its phrase in two parts, so only its output, not its text,
    holds the phrase whole.
    """
    command = shlex.join([sys.executable, "-c", "import sys; print('this command never ran', sys.argv[1])", "pytest"])
    project_root = throwaway_lane_project(tmp_path, command)

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    with pytest.raises(AssertionError) as failure:
        collection.node_ids()
    assert repr(command) in str(failure.value)
    assert "this command never ran pytest" in str(failure.value)


def test_node_ids_outside_a_directory_are_those_collected_from_files_not_under_it(tmp_path: Path) -> None:
    """suite_extra, whose name merely starts with suite's, is not under suite."""
    project_root = throwaway_lane_project(tmp_path, f"{_PYTEST} suite suite_extra")
    for directory, module in (("suite", "test_in_suite.py"), ("suite_extra", "test_beside_suite.py")):
        (project_root / directory).mkdir()
        (project_root / directory / module).write_text("def test_case():\n    pass\n", encoding="utf-8")

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert collection.node_ids_outside("suite") == ("suite_extra/test_beside_suite.py::test_case",), (
        collection.describe()
    )


def test_node_ids_outside_a_test_file_are_those_collected_from_any_other_file(tmp_path: Path) -> None:
    """The file's own ids stay inside though a parameter id holds a '/' or '::', and test_contract_extra.py is another file."""
    project_root = throwaway_lane_project(tmp_path, f"{_PYTEST} test_contract.py test_contract_extra.py")
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

    collection = collect_lane_job(project_root, PROBE_JOB, env_for=_this_process_environment)

    assert collection.node_ids_outside("test_contract.py") == ("test_contract_extra.py::test_case",), (
        collection.describe()
    )


def test_a_second_call_given_the_same_collections_directory_reads_the_collection_back_without_collecting_again(
    tmp_path: Path,
) -> None:
    project_root = _project_logging_each_collection(tmp_path / "project", "def test_case():\n    pass\n")
    collections = tmp_path / "collections"

    first = collect_lane_job_once(collections, project_root, PROBE_JOB, env_for=_this_process_environment)
    second = collect_lane_job_once(collections, project_root, PROBE_JOB, env_for=_this_process_environment)

    assert second == first
    assert second.node_ids() == ("test_kept.py::test_case",), second.describe()
    assert _collections_logged(project_root) == 1, (
        f"two calls given one collections directory collected the job {_collections_logged(project_root)} times; "
        "the second must read the first's collection back"
    )


def test_one_collections_directory_keeps_the_collection_of_each_project_and_job_apart(tmp_path: Path) -> None:
    """Asking project a for a job its yaml lacks fails first, and then each project's probe job is asked for.

    A key ignoring the job's name would raise that recorded failure for a's probe
    job, and a key ignoring the project would hand b a's collection.
    """
    project_a = _project_logging_each_collection(tmp_path / "a", "def test_in_a():\n    pass\n")
    project_b = _project_logging_each_collection(tmp_path / "b", "def test_in_b():\n    pass\n")
    collections = tmp_path / "collections"

    with pytest.raises(AssertionError, match="'absent'"):
        collect_lane_job_once(collections, project_a, "absent", env_for=_this_process_environment)
    in_a = collect_lane_job_once(collections, project_a, PROBE_JOB, env_for=_this_process_environment)
    in_b = collect_lane_job_once(collections, project_b, PROBE_JOB, env_for=_this_process_environment)

    assert in_a.node_ids() == ("test_kept.py::test_in_a",), in_a.describe()
    assert in_b.node_ids() == ("test_kept.py::test_in_b",), in_b.describe()
    assert (_collections_logged(project_a), _collections_logged(project_b)) == (1, 1)


def test_a_collection_that_failed_is_not_collected_again_and_each_later_call_raises_its_error(tmp_path: Path) -> None:
    """The job's pytest stops on test_kept.py's error at import, so the first call fails collect_lane_job's assert."""
    project_root = _project_logging_each_collection(
        tmp_path / "project", "raise RuntimeError('test_kept.py refuses to be imported')\n"
    )
    collections = tmp_path / "collections"

    with pytest.raises(AssertionError, match="failed to collect"):
        collect_lane_job_once(collections, project_root, PROBE_JOB, env_for=_this_process_environment)
    with pytest.raises(RuntimeError, match="failed to collect"):
        collect_lane_job_once(collections, project_root, PROBE_JOB, env_for=_this_process_environment)

    assert _collections_logged(project_root) == 1, (
        f"the job was collected {_collections_logged(project_root)} times, though its first collection failed; "
        "a later call must raise that failure, never collect again"
    )


def test_a_default_collection_reaches_a_suite_nothing_excludes_and_returns_only_its_node_ids(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path)

    assert default_collection_node_ids_under(project_root, _SUITE) == (_SUITE_NODE_ID,)


def test_a_suite_the_tests_conftest_collect_ignore_names_is_never_reached(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path, conftest='collect_ignore = ["suite"]\n')

    assert default_collection_node_ids_under(project_root, _SUITE) == ()


def test_the_ini_addopts_are_cleared_as_dark_factorys_reruns_clear_them(tmp_path: Path) -> None:
    """dark-factory's serial and confirm reruns append `-o addopts=`, so an ini addopts --ignore does not keep a suite out of them."""
    project_root = _project_with_a_suite(tmp_path, ini=f"[pytest]\naddopts = --ignore={_SUITE}\n")

    assert default_collection_node_ids_under(project_root, _SUITE) == (_SUITE_NODE_ID,)


def test_an_inherited_pytest_addopts_does_not_hide_the_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = _project_with_a_suite(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", f"--ignore={_SUITE}")

    assert default_collection_node_ids_under(project_root, _SUITE) == (_SUITE_NODE_ID,)


def test_a_default_collection_that_fails_fails_describing_its_error(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path)
    (project_root / _SUITE / "test_broken.py").write_text(
        f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8"
    )

    with pytest.raises(AssertionError) as failure:
        default_collection_node_ids_under(project_root, _SUITE)

    assert _IMPORT_ERROR_MESSAGE in str(failure.value)


@pytest.mark.parametrize("suite", [f"{_SUITE}/deeper", "tests/absent"], ids=["deeper", "absent"])
def test_a_suite_that_is_not_a_directory_directly_under_tests_is_refused_naming_it(tmp_path: Path, suite: str) -> None:
    """Probed, either would read as never reached.

    A deeper suite is ignored with its parent directory, and an absent one holds no tests.
    """
    project_root = _project_with_a_suite(tmp_path)
    (project_root / _SUITE / "deeper").mkdir()
    (project_root / _SUITE / "deeper" / "test_deeper.py").write_text("def test_case():\n    pass\n", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        default_collection_node_ids_under(project_root, suite)

    assert repr(suite) in str(failure.value)


def test_a_mark_selection_returns_only_the_suites_node_ids_its_expression_matches(tmp_path: Path) -> None:
    """The test beside the suite is never collected: only the suite's path is given."""
    project_root = _project_with_a_suite(tmp_path, ini="[pytest]\nmarkers =\n    slow: selected by its mark\n")
    (project_root / _SUITE / "test_slow.py").write_text(
        "import pytest\n\n\n@pytest.mark.slow\ndef test_case():\n    pass\n", encoding="utf-8"
    )

    assert suite_node_ids_matching(project_root, _SUITE, "slow") == (f"{_SUITE}/test_slow.py::test_case",)
    assert suite_node_ids_matching(project_root, _SUITE, "not slow") == (_SUITE_NODE_ID,)


def test_a_mark_selections_tests_carry_their_files_and_parametrize_ids(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path, ini="[pytest]\nmarkers =\n    slow: selected by its mark\n")
    (project_root / _SUITE / "test_matrix.py").write_text(
        textwrap.dedent(
            """\
            import pytest


            @pytest.mark.slow
            @pytest.mark.parametrize("minor", ["3.12", "3.13"])
            def test_matrix(minor):
                pass
            """
        ),
        encoding="utf-8",
    )

    module = PurePosixPath(f"{_SUITE}/test_matrix.py")
    assert suite_tests_matching(project_root, _SUITE, "slow") == (
        CollectedTest(f"{module}::test_matrix[3.12]", module, "3.12"),
        CollectedTest(f"{module}::test_matrix[3.13]", module, "3.13"),
    )


def test_a_mark_selection_matching_none_of_the_suites_tests_returns_no_node_ids(tmp_path: Path) -> None:
    """pytest exits NO_TESTS_COLLECTED, as for `-m 'not slow'` on a lane suite whose every test is slow."""
    project_root = _project_with_a_suite(tmp_path)

    assert suite_node_ids_matching(project_root, _SUITE, "slow") == ()


def test_a_mark_selection_reaches_a_suite_the_tests_conftest_collect_ignore_names(tmp_path: Path) -> None:
    """Its explicit path overrides collect_ignore, as an offline-lane job's command does."""
    project_root = _project_with_a_suite(tmp_path, conftest='collect_ignore = ["suite"]\n')

    assert suite_node_ids_matching(project_root, _SUITE, "not slow") == (_SUITE_NODE_ID,)


def test_a_mark_selection_that_fails_to_collect_fails_describing_its_error(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path)
    (project_root / _SUITE / "test_broken.py").write_text(
        f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8"
    )

    with pytest.raises(AssertionError) as failure:
        suite_node_ids_matching(project_root, _SUITE, "not slow")

    assert _IMPORT_ERROR_MESSAGE in str(failure.value)


def test_every_test_matching_reaches_each_directory_and_test_module_under_tests_a_collect_ignored_suite_included(
    tmp_path: Path,
) -> None:
    """Naming tests/ alone would miss the suite collect_ignore names, and so would naming tests/ beside it.

    pytest drops a path argument that an ancestor argument's ignore rules
    exclude. <project>/tests/data holds no test module, and reaching it is harmless.
    """
    project_root = _project_with_a_suite(tmp_path, conftest='collect_ignore = ["suite"]\n')
    (project_root / "tests" / "data").mkdir()
    (project_root / "tests" / "data" / "readings.csv").write_text("minute,kwh\n", encoding="utf-8")

    tests = every_test_matching(
        project_root, "not slow", pytest_invocation=_PYTEST_INVOCATION, env_for=_this_process_environment
    )

    assert tuple(test.node_id for test in tests) == (_SUITE_NODE_ID, "tests/test_beside.py::test_case")


def test_every_test_matching_returns_only_the_tests_its_expression_selects(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path, ini="[pytest]\nmarkers =\n    slow: selected by its mark\n")
    (project_root / "tests" / "other").mkdir()
    (project_root / "tests" / "other" / "test_slow.py").write_text(
        "import pytest\n\n\n@pytest.mark.slow\ndef test_case():\n    pass\n", encoding="utf-8"
    )

    tests = every_test_matching(
        project_root, "slow", pytest_invocation=_PYTEST_INVOCATION, env_for=_this_process_environment
    )

    module = PurePosixPath("tests/other/test_slow.py")
    assert tests == (CollectedTest(f"{module}::test_case", module, None),)


def test_every_test_matching_collects_in_the_environment_env_for_returns_for_its_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env_for is given the very command that runs, as collect_lane_job's is, so an environment keyed on it fits what runs."""
    project_root = _project_with_a_suite(tmp_path)
    (project_root / _SUITE / "test_environment.py").write_text(_ENVIRONMENT_PROBE_MODULE, encoding="utf-8")
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")
    asked_for: list[str] = []

    def env_for(command: str) -> dict[str, str]:
        asked_for.append(command)
        return {name: value for name, value in os.environ.items() if name != _PROBE_VARIABLE}

    tests = every_test_matching(project_root, "not slow", pytest_invocation=_PYTEST_INVOCATION, env_for=env_for)

    assert len(asked_for) == 1, asked_for
    assert asked_for[0].startswith(shlex.join(_PYTEST_INVOCATION)), asked_for
    assert f"{_SUITE}/test_environment.py::test_environment[unset]" in {test.node_id for test in tests}


def test_every_test_matching_that_fails_to_collect_fails_describing_its_error(tmp_path: Path) -> None:
    project_root = _project_with_a_suite(tmp_path)
    (project_root / _SUITE / "test_broken.py").write_text(
        f"raise ImportError({_IMPORT_ERROR_MESSAGE!r})\n", encoding="utf-8"
    )

    with pytest.raises(AssertionError) as failure:
        every_test_matching(
            project_root, "not slow", pytest_invocation=_PYTEST_INVOCATION, env_for=_this_process_environment
        )

    assert _IMPORT_ERROR_MESSAGE in str(failure.value)


def test_every_test_matching_whose_expression_selects_nothing_returns_no_tests(tmp_path: Path) -> None:
    """pytest exits NO_TESTS_COLLECTED, as for `-m slow` on a tree that holds no slow test."""
    project_root = _project_with_a_suite(tmp_path)

    tests = every_test_matching(
        project_root, "slow", pytest_invocation=_PYTEST_INVOCATION, env_for=_this_process_environment
    )

    assert tests == ()
