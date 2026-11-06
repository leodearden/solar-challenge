# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the regenerator of tests/_fleet_generation_pins.py: write_goldens writes the goldens the repository commits, under the root it is given and nowhere else, whatever the working directory."""

import shutil
from pathlib import Path

import pytest

from tests._fleet_generation_pins import PINNED_FLEETS, REGENERATE_COMMAND, golden_path, write_goldens
from tests._repository_paths import REPOSITORY_ROOT


@pytest.fixture
def scratch_checkout(tmp_path: Path) -> Path:
    """A checkout of its own that holds the pinned fleet files of this repository and none of their goldens."""
    checkout = tmp_path / "checkout"
    for fleet in PINNED_FLEETS:
        (checkout / fleet).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPOSITORY_ROOT / fleet, checkout / fleet)
    return checkout


def test_write_goldens_writes_the_goldens_the_repository_commits_under_the_root_it_is_given(
    scratch_checkout: Path,
) -> None:
    written = write_goldens(scratch_checkout)

    assert written == [golden_path(scratch_checkout, fleet) for fleet in PINNED_FLEETS]
    changed = [
        fleet
        for fleet in PINNED_FLEETS
        if golden_path(scratch_checkout, fleet).read_bytes() != golden_path(REPOSITORY_ROOT, fleet).read_bytes()
    ]
    assert changed == [], (
        f"regenerating the golden of each of {changed} writes other bytes than the committed golden holds: "
        f"write them with `{REGENERATE_COMMAND}` and commit the rewritten goldens"
    )


def test_write_goldens_writes_nothing_under_the_working_directory(
    scratch_checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    write_goldens(scratch_checkout)

    assert list(elsewhere.iterdir()) == [], "write_goldens wrote under the working directory, not only under its root"
