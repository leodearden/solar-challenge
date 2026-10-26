# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_synthetic_checkout.py, on real throwaway git checkouts, with no mocks."""

import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import working_tree_files

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the helper makes its checkout with it"
)


def test_makes_a_new_checkout_in_which_git_lists_each_file_laid_out_with_its_content(tmp_path: Path) -> None:
    directory = tmp_path / "checkout"

    checkout = synthetic_checkout(
        directory,
        {"README.md": "§3 costs £5\n", "src/pkg/module.py": "VALUE = 1\n", "src/pkg/logo.png": b"\x89PNG\xff"},
    )

    assert checkout == directory
    tracked = subprocess.run(
        ["git", "ls-files", "--cached"], cwd=directory, capture_output=True, text=True, check=True
    ).stdout
    assert tracked == ""
    assert sorted(working_tree_files(checkout)) == [
        PurePosixPath("README.md"),
        PurePosixPath("src/pkg/logo.png"),
        PurePosixPath("src/pkg/module.py"),
    ]
    assert (checkout / "README.md").read_bytes() == "§3 costs £5\n".encode("utf-8")
    assert (checkout / "src" / "pkg" / "module.py").read_bytes() == b"VALUE = 1\n"
    assert (checkout / "src" / "pkg" / "logo.png").read_bytes() == b"\x89PNG\xff"


def test_git_lists_a_laid_out_file_that_the_user_config_excludes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    excludes = tmp_path / "excludes"
    excludes.write_text("excluded.txt\n", encoding="utf-8")
    user_config = tmp_path / "user.gitconfig"
    subprocess.run(["git", "config", "--file", str(user_config), "core.excludesFile", str(excludes)], check=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(user_config))
    plain = tmp_path / "plain"
    subprocess.run(["git", "init", "--quiet", str(plain)], check=True)
    (plain / "excluded.txt").write_text("", encoding="utf-8")

    checkout = synthetic_checkout(tmp_path / "checkout", {"excluded.txt": ""})

    assert working_tree_files(plain) == [], (
        "git lists excluded.txt in a plain `git init` checkout, so the user config excludes nothing and this case would"
        " pass whatever the helper does"
    )
    assert working_tree_files(checkout) == [PurePosixPath("excluded.txt")]


def test_write_file_adds_a_file_beside_those_laid_out_and_returns_its_path(tmp_path: Path) -> None:
    checkout = synthetic_checkout(tmp_path / "checkout", {"src/pkg/module.py": "VALUE = 1\n"})

    page = write_file(checkout, "src/pkg/page.html", "<p>Page</p>\n")
    notes = write_file(checkout, "src/pkg/deeper/notes.txt", b"\xff\xfe")

    assert page == PurePosixPath("src/pkg/page.html")
    assert notes == PurePosixPath("src/pkg/deeper/notes.txt")
    assert sorted(working_tree_files(checkout)) == [
        PurePosixPath("src/pkg/deeper/notes.txt"),
        PurePosixPath("src/pkg/module.py"),
        PurePosixPath("src/pkg/page.html"),
    ]
    assert (checkout / "src" / "pkg" / "page.html").read_text(encoding="utf-8") == "<p>Page</p>\n"
    assert (checkout / "src" / "pkg" / "deeper" / "notes.txt").read_bytes() == b"\xff\xfe"
