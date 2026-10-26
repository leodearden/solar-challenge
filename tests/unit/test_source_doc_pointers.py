# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every path into docs/ that a scanned file names is a file or directory of the tree."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tests._hermetic_checkout import init_hermetic_checkout
from tests._pointer_scan import utf8_text
from tests._working_tree import working_tree_paths

_DOC_POINTER = re.compile(r"(?<![\w./-])docs/(?:[\w.-]+/)*[\w.-]*\w")


@dataclass(frozen=True)
class _DocPointer:
    """A path into docs/: the file naming it, relative to the project root, its line, and the path it names."""

    source: PurePosixPath
    line: int
    path: PurePosixPath

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {self.path}"


def _doc_pointers(root: Path, sources: Iterable[PurePosixPath]) -> list[_DocPointer]:
    """Return every path into docs/ in the *sources*, POSIX paths relative to *root*, file by file and in text order."""
    pointers: list[_DocPointer] = []
    for source in sources:
        text = utf8_text(root / source)
        if text is None:
            continue
        for match in _DOC_POINTER.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            pointers.append(_DocPointer(source=source, line=line, path=PurePosixPath(match[0])))
    return pointers


def _dangling(root: Path, pointers: Iterable[_DocPointer]) -> list[str]:
    """Return "<pointer>: <reason>" for each of the *pointers* whose path is not in *root*'s working tree, in their order."""
    tree = working_tree_paths(root)
    return [
        f"{pointer}: {pointer.path} does not exist, or git ignores it"
        for pointer in pointers
        if not tree.holds(pointer.path)
    ]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a git checkout holding the docs docs/guide.md and docs/prds/record.md."""
    init_hermetic_checkout(tmp_path)
    docs = tmp_path / "docs"
    (docs / "prds").mkdir(parents=True)
    (docs / "guide.md").write_text("# Title\n", encoding="utf-8")
    (docs / "prds" / "record.md").write_text("# Title\n", encoding="utf-8")
    return tmp_path


def _write_source(project: Path, source: str, text: str) -> PurePosixPath:
    """Write *text* to *source*, a POSIX path relative to *project*, and return that path."""
    path = project / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return PurePosixPath(source)


def test_finds_each_path_into_docs_in_any_text_on_its_line(project: Path) -> None:
    module = _write_source(
        project,
        "src/pkg/module.py",
        "# docs/guide.md §3 says why.\n"
        'DOC = "docs/prds/record.md"\n'
        "# The records are under docs/prds.\n"
        "# Not rooted at docs/: src/docs/gone.md, ../docs/gone.md, dark-factory/docs/code-quality.md,\n"
        "# https://example.org/docs/gone.md, readthedocs/gone.md and docs/<name>.md\n",
    )
    page = _write_source(project, "src/pkg/page.html", "<p>See docs/guide.md.</p>\n")

    assert [str(pointer) for pointer in _doc_pointers(project, [module, page])] == [
        "src/pkg/module.py:1: docs/guide.md",
        "src/pkg/module.py:2: docs/prds/record.md",
        "src/pkg/module.py:3: docs/prds",
        "src/pkg/page.html:1: docs/guide.md",
    ]


def test_reports_each_path_that_names_no_file_or_directory_of_the_tree_on_its_line(project: Path) -> None:
    source = _write_source(
        project,
        "src/pkg/module.py",
        "# docs/absent.md\n"
        "# docs/guide.md and docs/prds/record.md exist, and so does docs/prds.\n"
        "# docs/prds/absent.md §2\n"
        "# docs/absent\n",
    )

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/absent.md: docs/absent.md does not exist, or git ignores it",
        "src/pkg/module.py:3: docs/prds/absent.md: docs/prds/absent.md does not exist, or git ignores it",
        "src/pkg/module.py:4: docs/absent: docs/absent does not exist, or git ignores it",
    ]


def test_a_doc_or_directory_git_ignores_does_not_resolve(project: Path) -> None:
    (project / ".gitignore").write_text("generated/\n", encoding="utf-8")
    generated = project / "docs" / "generated"
    generated.mkdir()
    (generated / "made.md").write_text("# Made\n", encoding="utf-8")
    source = _write_source(project, "src/pkg/module.py", "# docs/generated/made.md\n# docs/generated\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/generated/made.md: docs/generated/made.md does not exist, or git ignores it",
        "src/pkg/module.py:2: docs/generated: docs/generated does not exist, or git ignores it",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = project / "src" / "pkg" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG\xff\xfe docs/absent.md")

    assert _doc_pointers(project, [PurePosixPath("src/pkg/logo.png")]) == []
