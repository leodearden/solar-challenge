# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_collect_only.py's collect(), the collect-only probe the orchestrator contract tests share.

They pin that the command runs verbatim and only collects, keeps its project's ini addopts in force,
receives each extra pytest arg whole, and runs in the environment it is given, that environment's
PYTHONPATH kept; that what it collected is read from the collection-report plugin's report, never from
its output, and a run that wrote no report never reads as an empty collection; and that a failed run's
description carries pytest's error report however long the listing, and the output of a command that
failed before pytest started.
"""

import os
import shlex
import sys
import textwrap
from pathlib import Path, PurePosixPath

import pytest

from tests._collect_only import CollectedTest, collect

_PYTEST = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider"

_PROBE_VARIABLE = "COLLECT_ONLY_PROBE"

_IMPORT_ERROR_MESSAGE = "test_broken.py refuses to be imported"

_STARTUP_ERROR_MESSAGE = "the command failed before pytest started"

_DOUBLE_COLON_LINE = "warning: a::b"


def _module_of_failing_tests(*names: str) -> str:
    """Return the source of a test module defining one test per name in *names*, each failing if run."""
    return "".join(f"def {name}():\n    raise AssertionError('collect-only ran {name}')\n\n\n" for name in names)


@pytest.fixture
def project_with_ini_addopts(tmp_path: Path) -> Path:
    """A throwaway project whose ini addopts, like this repo's, ignore a test module."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --ignore=test_ignored.py\n", encoding="utf-8")
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
    """A throwaway project of a thousand tests, whose test_broken.py raises at import."""
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


def test_collects_the_tests_the_projects_addopts_select_without_running_them(project_with_ini_addopts: Path) -> None:
    """Clearing the ini's addopts would collect test_ignored.py, and each test raises if run."""
    collection = collect(_PYTEST, project_with_ini_addopts)

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert collection.node_ids() == (
        "test_kept.py::test_alpha",
        "test_kept.py::test_beta",
        "test_kept.py::test_gamma",
    ), collection.describe()


def test_each_extra_pytest_arg_reaches_pytest_whole(project_with_ini_addopts: Path) -> None:
    """Split on its spaces, the -k expression would leave pytest looking for files named or and beta.

    The tests read are those left after the expression deselects test_gamma.
    """
    collection = collect(_PYTEST, project_with_ini_addopts, "-k", "alpha or beta")

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert collection.node_ids() == ("test_kept.py::test_alpha", "test_kept.py::test_beta"), collection.describe()


def test_by_default_the_command_runs_in_this_process_environment(
    project_echoing_its_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")

    collection = collect(_PYTEST, project_echoing_its_environment)

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert collection.node_ids() == ("test_environment.py::test_environment[inherited]",), collection.describe()


def test_a_given_environment_replaces_this_process_environment(
    project_echoing_its_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is not merged over this process's, so a caller can drop a variable, as test_per_task_verify.py drops VIRTUAL_ENV."""
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")
    environment = {name: value for name, value in os.environ.items() if name != _PROBE_VARIABLE}

    collection = collect(_PYTEST, project_echoing_its_environment, env=environment)

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert collection.node_ids() == ("test_environment.py::test_environment[unset]",), collection.describe()


def test_the_given_environments_pythonpath_stays_importable(tmp_path: Path) -> None:
    """The report plugin's directory goes in front of the environment's PYTHONPATH, not in its place."""
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "probe_helper.py").write_text("", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project / "test_importing.py").write_text(
        "import probe_helper\n\n\ndef test_case():\n    pass\n", encoding="utf-8"
    )

    collection = collect(_PYTEST, project, env={**os.environ, "PYTHONPATH": str(helpers)})

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert collection.node_ids() == ("test_importing.py::test_case",), collection.describe()


def test_an_output_line_holding_a_double_colon_is_not_a_test(tmp_path: Path) -> None:
    """As a uv or pytest warning naming a node id would print; a conftest's collection-finish line prints at every verbosity."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        f"def pytest_report_collectionfinish(config, start_path, items):\n    return {_DOUBLE_COLON_LINE!r}\n",
        encoding="utf-8",
    )
    (tmp_path / "test_two.py").write_text(_module_of_failing_tests("test_alpha", "test_beta"), encoding="utf-8")

    collection = collect(_PYTEST, tmp_path)

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    assert _DOUBLE_COLON_LINE in collection.output, collection.describe()
    assert collection.node_ids() == ("test_two.py::test_alpha", "test_two.py::test_beta"), collection.describe()


def test_each_collected_test_carries_its_file_and_its_parametrize_id(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "test_ids.py").write_text(
        textwrap.dedent(
            """\
            import pytest


            @pytest.mark.parametrize("minor", ["3.12", "3.13"])
            def test_matrix(minor):
                raise AssertionError("collect-only ran test_matrix")


            def test_plain():
                raise AssertionError("collect-only ran test_plain")
            """
        ),
        encoding="utf-8",
    )

    collection = collect(_PYTEST, tmp_path)

    assert collection.returncode == pytest.ExitCode.OK, collection.describe()
    module = PurePosixPath("sub/test_ids.py")
    assert collection.written_report().tests == (
        CollectedTest("sub/test_ids.py::test_matrix[3.12]", module, "3.12"),
        CollectedTest("sub/test_ids.py::test_matrix[3.13]", module, "3.13"),
        CollectedTest("sub/test_ids.py::test_plain", module, None),
    ), collection.describe()


def test_a_command_that_never_runs_pytest_has_no_report_and_reading_its_node_ids_fails_naming_it(
    tmp_path: Path,
) -> None:
    """It never reads as an empty collection, as when uv refuses a stale lock before pytest starts."""
    collection = collect("false", tmp_path)

    assert collection.report is None, collection.describe()
    with pytest.raises(AssertionError) as failure:
        collection.node_ids()
    assert repr("false") in str(failure.value)


def test_a_collection_that_selects_nothing_is_an_empty_report_not_a_missing_one(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_one.py").write_text(_module_of_failing_tests("test_case"), encoding="utf-8")

    collection = collect(_PYTEST, tmp_path, "-k", "nomatch")

    assert collection.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, collection.describe()
    assert collection.report is not None, collection.describe()
    assert collection.report.tests == (), collection.describe()


def test_loaded_without_a_report_path_the_plugin_leaves_the_run_as_it_was(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plugin's load location, restated: -p solar_challenge_collection_report with tests/_pytest_plugins on PYTHONPATH."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "_pytest_plugins"), prepend=os.pathsep)
    pytester.makepyfile("def test_passes():\n    pass\n")

    result = pytester.runpytest_subprocess("-p", "solar_challenge_collection_report", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)
    assert not list(pytester.path.rglob("*.json"))


def test_a_failed_collection_is_described_by_its_error_report_however_long_the_listing(
    project_with_a_long_listing_and_a_broken_module: Path,
) -> None:
    """pytest reports collection errors after the listing, so a description bounded to the output's tail keeps them."""
    collection = collect(_PYTEST, project_with_a_long_listing_and_a_broken_module)

    description = collection.describe()

    assert collection.returncode == pytest.ExitCode.INTERRUPTED, description
    assert _IMPORT_ERROR_MESSAGE in description, description
    assert len(description) < len(collection.output), (
        f"the description is {len(description)} characters long, no shorter than the "
        f"{len(collection.output)}-character output it describes"
    )


def test_a_command_that_fails_before_pytest_starts_is_described_by_its_output(tmp_path: Path) -> None:
    """As when uv cannot build the environment: there is no listing, and only what the command printed says what went wrong."""
    command = shlex.join([sys.executable, "-c", f"import sys; sys.exit({_STARTUP_ERROR_MESSAGE!r})"])

    description = collect(command, tmp_path).describe()

    assert _STARTUP_ERROR_MESSAGE in description, description
