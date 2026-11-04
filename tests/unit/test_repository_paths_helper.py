# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_repository_paths.py: SCENARIOS_DIR is the repository's committed scenarios directory, as an absolute path."""

from pathlib import Path

import pytest

from tests._repository_paths import SCENARIOS_DIR


def test_scenarios_dir_is_the_scenarios_directory_under_the_project_root(project_root: Path) -> None:
    assert SCENARIOS_DIR == (project_root / "scenarios").resolve()


def test_scenarios_dir_finds_the_committed_scenarios_from_any_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert SCENARIOS_DIR.is_absolute()
    assert (SCENARIOS_DIR / "bristol-phase1.yaml").is_file(), (
        f"no committed scenario bristol-phase1.yaml in {SCENARIOS_DIR}"
    )
