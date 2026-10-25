# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_hermetic_checkout.py, on real throwaway git checkouts, with no mocks."""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

from tests._hermetic_checkout import init_hermetic_checkout
from tests._working_tree import working_tree_files

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the helper makes its checkout with it"
)

_EXCLUDED = PurePosixPath("excluded-from-outside.txt")


@pytest.fixture
def outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an empty directory for the git configuration a case plants outside its checkouts.

    Git reads none of the host's configuration until a case plants its own: the user's and the system's config are
    one empty file, the user's default ignore file is missing, and git copies its default template.
    """
    empty_config = tmp_path / "empty.gitconfig"
    empty_config.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty_config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing-user-config"))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    monkeypatch.delenv("GIT_TEMPLATE_DIR", raising=False)
    directory = tmp_path / "outside"
    directory.mkdir()
    return directory


def _write_exclude_pattern(patterns: Path) -> Path:
    """Write *patterns*, a file of exclude patterns excluding _EXCLUDED, creating its directories; return it."""
    patterns.parent.mkdir(parents=True, exist_ok=True)
    patterns.write_text(f"{_EXCLUDED}\n", encoding="utf-8")
    return patterns


def _config_naming_an_excludes_file(outside: Path, name: str) -> Path:
    """Write the git config file *name* in *outside*, its core.excludesFile a file excluding _EXCLUDED; return it."""
    config = outside / name
    excludes = _write_exclude_pattern(outside / f"{name}.excludes")
    subprocess.run(["git", "config", "--file", str(config), "core.excludesFile", str(excludes)], check=True)
    return config


def _config_naming_a_template(outside: Path, name: str) -> Path:
    """Write the git config file *name* in *outside*, its init.templateDir a template whose info/exclude excludes
    _EXCLUDED; return it."""
    config = outside / name
    template = outside / f"{name}.template"
    _write_exclude_pattern(template / "info" / "exclude")
    subprocess.run(["git", "config", "--file", str(config), "init.templateDir", str(template)], check=True)
    return config


def _plant_in_the_user_ignore_file(outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_exclude_pattern(outside / "user-config" / "git" / "ignore")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(outside / "user-config"))


def _plant_in_an_excludes_file_the_user_config_names(outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(_config_naming_an_excludes_file(outside, "user.gitconfig")))


def _plant_in_an_excludes_file_the_system_config_names(outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(_config_naming_an_excludes_file(outside, "system.gitconfig")))


def _plant_in_the_template_info_exclude(outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_exclude_pattern(outside / "template" / "info" / "exclude")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(outside / "template"))


def _plant_in_a_template_the_user_config_names(outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(_config_naming_a_template(outside, "user.gitconfig")))


@pytest.mark.parametrize(
    "plant",
    [
        pytest.param(_plant_in_the_user_ignore_file, id="user-ignore-file"),
        pytest.param(_plant_in_an_excludes_file_the_user_config_names, id="user-config-excludes-file"),
        pytest.param(_plant_in_an_excludes_file_the_system_config_names, id="system-config-excludes-file"),
        pytest.param(_plant_in_the_template_info_exclude, id="template-info-exclude"),
        pytest.param(_plant_in_a_template_the_user_config_names, id="user-config-template-info-exclude"),
    ],
)
def test_git_reads_no_exclude_pattern_from_outside_the_checkout(
    plant: Callable[[Path, pytest.MonkeyPatch], None], outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant(outside, monkeypatch)
    plain = tmp_path / "plain"
    subprocess.run(["git", "init", "--quiet", str(plain)], check=True)
    hermetic = init_hermetic_checkout(tmp_path / "hermetic")
    for checkout in (plain, hermetic):
        (checkout / _EXCLUDED).write_text("written in the checkout", encoding="utf-8")

    assert working_tree_files(plain) == [], (
        f"git lists {_EXCLUDED} in a plain `git init` checkout, so this case excludes nothing from outside the"
        " checkout and would pass whatever the helper does"
    )
    assert working_tree_files(hermetic) == [_EXCLUDED], (
        f"git leaves {_EXCLUDED} out of the helper's checkout, so it read an exclude pattern from outside the checkout"
    )


def test_makes_a_missing_directory_and_its_parents_the_top_level_of_a_new_checkout(tmp_path: Path) -> None:
    directory = tmp_path / "parent" / "checkout"

    returned = init_hermetic_checkout(directory)

    assert returned == directory
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=directory, capture_output=True, text=True, check=True
    ).stdout
    assert Path(toplevel.strip()) == directory.resolve()


def test_keeps_the_files_an_existing_directory_holds_and_lists_them_as_untracked(tmp_path: Path) -> None:
    project = tmp_path / "project"
    kept = project / "nested" / "kept.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text("kept", encoding="utf-8")

    init_hermetic_checkout(project)

    assert working_tree_files(project) == [PurePosixPath("nested/kept.txt")]
    tracked = subprocess.run(
        ["git", "ls-files", "--cached"], cwd=project, capture_output=True, text=True, check=True
    ).stdout
    assert tracked == ""
    assert kept.read_text(encoding="utf-8") == "kept"
