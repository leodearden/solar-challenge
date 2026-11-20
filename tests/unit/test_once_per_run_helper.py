# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_once_per_run.py, through which the processes of one pytest run build a directory they share once."""

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


def test_a_build_that_raised_is_never_returned_and_the_next_call_builds_into_an_empty_directory(tmp_path: Path) -> None:
    shared = tmp_path / "shared"

    def failing_build(directory: Path) -> None:
        (directory / "partial").write_text("partial")
        raise RuntimeError("the build failed")

    with pytest.raises(RuntimeError, match="the build failed"):
        built_once(shared, failing_build)

    held_on_entry: list[dict[str, str]] = []

    def build(directory: Path) -> None:
        held_on_entry.append(_files_in(directory))
        (directory / "built").write_text("built")

    assert built_once(shared, build) == shared
    assert held_on_entry == [{}], "the build after one that raised must start from an empty directory"

    assert built_once(shared, build) == shared
    assert len(held_on_entry) == 1, "the directory, once built, must not be built again"
