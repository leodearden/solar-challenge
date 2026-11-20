# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_once_per_run.py, through which the processes of one pytest run build a directory they share once."""

import os
import shlex
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests._once_per_run import built_once


def _files_in(directory: Path) -> dict[str, str]:
    """The text of each file *directory* holds, keyed by its name."""
    return {path.name: path.read_text() for path in directory.iterdir()}


def test_a_second_call_returns_the_built_directory_without_building_it_again(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    builds: list[Path] = []

    def build(directory: Path) -> None:
        builds.append(directory)
        (directory / "built").write_text("built")

    assert built_once(shared, build) == shared
    assert built_once(shared, build) == shared

    assert builds == [shared]
    assert _files_in(shared) == {"built": "built"}, (
        "the directory must hold only what its build wrote: the lock and the built marker sit beside it, not in it"
    )


def test_concurrent_callers_build_once_and_each_gets_the_complete_directory(tmp_path: Path) -> None:
    """A flock conflicts across open file descriptions even within one process, so threads contend for it as the workers of a run do."""
    shared = tmp_path / "shared"
    builds: list[Path] = []

    def build(directory: Path) -> None:
        builds.append(directory)
        (directory / "first").write_text("first")
        time.sleep(0.2)
        (directory / "last").write_text("last")

    with ThreadPoolExecutor(max_workers=4) as callers:
        seen = list(callers.map(lambda _: _files_in(built_once(shared, build)), range(4)))

    assert builds == [shared]
    assert seen == [{"first": "first", "last": "last"}] * 4, (
        "a caller was handed the directory before its build had finished"
    )


def test_a_build_that_raised_is_never_returned_nor_run_again_and_each_later_call_raises_its_error(
    tmp_path: Path,
) -> None:
    """So a run pays for a failing build once, however many of its processes ask for the directory."""
    shared = tmp_path / "shared"

    def failing_build(directory: Path) -> None:
        raise RuntimeError("the build failed")

    with pytest.raises(RuntimeError, match="the build failed"):
        built_once(shared, failing_build)

    builds: list[Path] = []

    def build(directory: Path) -> None:
        builds.append(directory)

    for _ in range(2):
        with pytest.raises(RuntimeError) as raised_again:
            built_once(shared, build)
        assert str(shared) in str(raised_again.value), "a later call's error must name the directory whose build raised"
        assert "RuntimeError: the build failed" in str(raised_again.value), (
            "a later call's error must carry the error the build raised"
        )

    assert builds == [], "a call after a build that raised must raise that build's error, never build again"


_BUILD_KILLED_MIDWAY = """
import sys
from pathlib import Path

from tests._once_per_run import built_once


def build(directory):
    (directory / "partial").write_text("partial")
    print("building", flush=True)
    sys.stdin.read()


built_once(Path(sys.argv[1]), build)
"""


def test_a_build_whose_process_was_killed_is_never_returned_and_the_next_call_builds_into_an_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    """The kernel frees the lock of a builder that dies, and its build wrote no marker, so the next call builds afresh."""
    shared = tmp_path / "shared"
    monkeypatch.setenv("PYTHONPATH", str(project_root), prepend=os.pathsep)

    with subprocess.Popen(
        [sys.executable, "-c", _BUILD_KILLED_MIDWAY, str(shared)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as builder:
        try:
            assert builder.stdout is not None
            assert builder.stdout.readline() == "building\n", "the builder process ended before its build began"
        finally:
            builder.kill()
    assert builder.returncode == -signal.SIGKILL, f"the builder process was not killed midway: it ended with {builder.returncode}"
    assert _files_in(shared) == {"partial": "partial"}, (
        "the killed build left nothing in the directory, so this test cannot tell whether the next call empties it"
    )

    held_on_entry: list[dict[str, str]] = []

    def build(directory: Path) -> None:
        held_on_entry.append(_files_in(directory))
        (directory / "built").write_text("built")

    assert built_once(shared, build) == shared
    assert held_on_entry == [{}], "the build after one whose process was killed must start from an empty directory"

    assert built_once(shared, build) == shared
    assert len(held_on_entry) == 1, "the directory, once built, must not be built again"


@pytest.mark.parametrize(
    "mode", [("-n", "2"), ("-n", "0"), ("-p", "no:xdist")], ids=["on-two-workers", "serially", "without-xdist"]
)
def test_a_directory_built_at_run_shared_path_is_built_once_in_each_run(
    pytester_importing_test_helpers: pytest.Pytester, mode: tuple[str, str]
) -> None:
    """Each run builds the directory once, however many of its workers ask for it, and no run takes an earlier run's.

    Its four tests ask for it through a session-scoped fixture, so on two workers each worker asks.
    """
    pytester_importing_test_helpers.makepyfile(
        """
        from pathlib import Path

        import pytest

        from tests._once_per_run import built_once, run_shared_path

        HERE = Path(__file__).parent


        def _build(directory):
            with (HERE / "builds.log").open("a") as log:
                print(directory, file=log)
            (directory / "built").write_text("built")


        @pytest.fixture(scope="session")
        def shared(request, tmp_path_factory):
            return built_once(run_shared_path(request, tmp_path_factory, "shared"), _build)


        @pytest.mark.parametrize("case", range(4))
        def test_reads_the_shared_directory(case, shared, request):
            assert (shared / "built").read_text() == "built"
            worker = getattr(request.config, "workerinput", {}).get("workerid", "master")
            (HERE / f"worker-of-case-{case}").write_text(worker)
        """
    )

    for run in ("first", "second"):
        result = pytester_importing_test_helpers.runpytest_subprocess(*mode, "-p", "no:cacheprovider")

        result.assert_outcomes(passed=4)
        if mode == ("-n", "2"):
            workers = sorted({path.read_text() for path in pytester_importing_test_helpers.path.glob("worker-of-case-*")})
            assert workers == ["gw0", "gw1"], (
                f"in the {run} run under {shlex.join(mode)}, the four tests ran on {workers}, "
                "so not both workers asked for the shared directory and this test cannot tell whether they share it"
            )

    builds = (pytester_importing_test_helpers.path / "builds.log").read_text().splitlines()
    assert len(builds) == 2, (
        f"two runs under {shlex.join(mode)} built the shared directory {len(builds)} times, where each run must "
        "build it once and none may take an earlier run's; builds.log names the directory of each build:\n"
        + "\n".join(builds)
    )
