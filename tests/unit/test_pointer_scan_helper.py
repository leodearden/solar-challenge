# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pointer_scan.py, on a real throwaway git checkout, with no mocks."""

import shutil
from pathlib import Path, PurePosixPath

import pytest

from tests._pointer_scan import scanned_files, utf8_text
from tests._synthetic_checkout import synthetic_checkout

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the helper lists the tree's files with it"
)


def test_lists_the_files_git_lists_but_those_at_or_under_an_unscanned_path(tmp_path: Path) -> None:
    checkout = synthetic_checkout(
        tmp_path / "checkout",
        dict.fromkeys(
            [
                "README.md",
                "src/module.py",
                "records/old.md",
                "records/nested/older.md",
                "records-new/kept.md",
                "src/records/kept.md",
                "skipped.txt",
            ],
            "",
        ),
    )

    scanned = scanned_files(checkout, [PurePosixPath("records"), PurePosixPath("skipped.txt")])

    assert sorted(scanned) == sorted(
        PurePosixPath(path) for path in ["README.md", "records-new/kept.md", "src/module.py", "src/records/kept.md"]
    )


def test_reads_a_utf8_files_text_and_nothing_from_another(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("§3 costs £5\n", encoding="utf-8")
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\xff\xfe")

    assert utf8_text(note) == "§3 costs £5\n"
    assert utf8_text(logo) is None
