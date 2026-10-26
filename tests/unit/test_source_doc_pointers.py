# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every path into docs/ that a scanned file names is a file or directory of the tree.

The scanned files are those git lists, tests/ included, outside the _UNSCANNED paths. Those are the records, which
name docs as they were when written, and the two pointer-gate modules, whose docs/ paths name files of the throwaway
checkouts their tests build.

A pointer is a path rooted at docs/, a file or a directory. It is looked for anywhere in a file's text, comments,
docstrings and code alike. A file that is not UTF-8 text holds none. The path is looked up in the files git lists and
the directories holding them, as a fresh clone would hold them, so a file git ignores is not there to point at. A doc
in another repository is written from that repository's name, as in dark-factory/docs/code-quality.md, so it is not
rooted at docs/. Only the path is checked: a section named after it, as in docs/<name>.md §3, is not looked up.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tests._hermetic_checkout import init_hermetic_checkout
from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._working_tree import working_tree_paths

_MODULES_NAMING_THROWAWAY_DOCS = (
    PurePosixPath("tests/unit/test_source_doc_pointers.py"),
    PurePosixPath("tests/unit/test_source_test_pointers.py"),
)

_UNSCANNED = (*RECORD_DIRECTORIES, *_MODULES_NAMING_THROWAWAY_DOCS)

_SECTION_NUMBER = r"\d+(?:\.\d+)*"

_DOC_POINTER = re.compile(
    rf"""
    (?<![\w./-])
    (?P<path>docs/(?:[\w.-]+/)*[\w.-]*\w)
    (?:`?(?:\](?:\([^)\s]*\))?)?,?\s+§(?P<section>{_SECTION_NUMBER})(?!\w))?
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _DocPointer:
    """A path into docs/: the file naming it, relative to the project root, its line, the path it names and its section.

    The section is the number written right after the path, as 3.1 in docs/<name>.md §3.1, or None if none is.
    """

    source: PurePosixPath
    line: int
    path: PurePosixPath
    section: str | None

    def __str__(self) -> str:
        pointer = f"{self.source}:{self.line}: {self.path}"
        return pointer if self.section is None else f"{pointer} §{self.section}"


def _doc_pointers(root: Path, sources: Iterable[PurePosixPath]) -> list[_DocPointer]:
    """Return every path into docs/ in the *sources*, POSIX paths relative to *root*, file by file and in text order."""
    pointers: list[_DocPointer] = []
    for source in sources:
        text = utf8_text(root / source)
        if text is None:
            continue
        for match in _DOC_POINTER.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            pointers.append(
                _DocPointer(source=source, line=line, path=PurePosixPath(match["path"]), section=match["section"])
            )
    return pointers


def _dangling(root: Path, pointers: Iterable[_DocPointer]) -> list[str]:
    """Return "<pointer>: <reason>" for each of the *pointers* whose path is not in *root*'s working tree, in their order."""
    tree = working_tree_paths(root)
    return [
        f"{pointer}: {pointer.path} does not exist, or git ignores it"
        for pointer in pointers
        if not tree.holds(pointer.path)
    ]


def test_every_pointer_from_the_scanned_files_into_docs_resolves(project_root: Path) -> None:
    pointers = _doc_pointers(project_root, scanned_files(project_root, _UNSCANNED))
    unscanned = ", ".join(str(path) for path in _UNSCANNED)
    assert pointers, (
        f"found no path into docs/ in any file git lists outside the unscanned paths ({unscanned}), so this gate"
        " would pass vacuously; fix the listing or the grammar"
    )
    assert any(pointer.section is not None for pointer in pointers), (
        "found no section written right after a path into docs/ in any file git lists outside the unscanned paths"
        f" ({unscanned}), so the section check would pass vacuously; fix the listing or the grammar"
    )

    dangling = _dangling(project_root, pointers)

    assert dangling == [], "\n".join(
        [
            *dangling,
            "A renamed or moved doc's pointers must follow it. Name a doc by its path from the project root,"
            " docs/<name>.md, which this gate resolves, and another repository's doc from that repository's name,"
            " as in dark-factory/docs/code-quality.md.",
        ]
    )


def test_every_path_the_gate_leaves_unscanned_is_in_the_tree(project_root: Path) -> None:
    tree = working_tree_paths(project_root)

    absent = [path for path in _UNSCANNED if not tree.holds(path)]

    assert absent == [], "\n".join(
        [
            *(f"{path} is not in the tree, so leaving it unscanned exempts nothing" for path in absent),
            "Rename or drop each such entry where it is declared: _MODULES_NAMING_THROWAWAY_DOCS in this module, or"
            " RECORD_DIRECTORIES in tests/_pointer_scan.py.",
        ]
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a git checkout holding docs/guide.md and docs/prds/record.md."""
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


def test_scans_every_file_git_lists_but_the_records_and_the_modules_naming_throwaway_docs(project: Path) -> None:
    scanned = {
        "CLAUDE.md",
        "docs/guide.md",
        "scripts/measure.py",
        "src/pkg/module.py",
        "tests/_helper.py",
        "tests/unit/test_any.py",
    }
    unscanned = [
        "docs/prds/record.md",
        "docs/research/survey.md",
        "plans/plan.md",
        "review/briefing.yaml",
        "tests/unit/test_source_doc_pointers.py",
        "tests/unit/test_source_test_pointers.py",
    ]
    for source in [*scanned, *unscanned]:
        _write_source(project, source, "")

    assert set(scanned_files(project, _UNSCANNED)) == {PurePosixPath(source) for source in scanned}


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
        "src/pkg/module.py:1: docs/guide.md §3",
        "src/pkg/module.py:2: docs/prds/record.md",
        "src/pkg/module.py:3: docs/prds",
        "src/pkg/page.html:1: docs/guide.md",
    ]


def test_reads_the_section_written_right_after_a_path(project: Path) -> None:
    notes = _write_source(
        project,
        "docs/notes.md",
        "docs/guide.md §3 says why.\n"
        "`docs/guide.md` §3.1.\n"
        "[docs/guide.md](guide.md) §2\n"
        "[`docs/prds/record.md`](prds/record.md) §10.2's\n"
        "docs/guide.md, §5\n"
        "docs/guide.md\n"
        "§4, on the next line\n"
        "docs/guide.md §7.3–§7.4\n",
    )

    assert [str(pointer) for pointer in _doc_pointers(project, [notes])] == [
        "docs/notes.md:1: docs/guide.md §3",
        "docs/notes.md:2: docs/guide.md §3.1",
        "docs/notes.md:3: docs/guide.md §2",
        "docs/notes.md:4: docs/prds/record.md §10.2",
        "docs/notes.md:5: docs/guide.md §5",
        "docs/notes.md:6: docs/guide.md §4",
        "docs/notes.md:8: docs/guide.md §7.3",
    ]


def test_reads_no_section_written_any_other_way(project: Path) -> None:
    notes = _write_source(
        project,
        "docs/notes.md",
        "docs/guide.md §Contract\n"
        "docs/guide.md §3a\n"
        "docs/guide.md § 3\n"
        "docs/guide.md and §3\n"
        "§3 of docs/guide.md\n",
    )

    assert [pointer.section for pointer in _doc_pointers(project, [notes])] == [None, None, None, None, None]


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
        "src/pkg/module.py:3: docs/prds/absent.md §2: docs/prds/absent.md does not exist, or git ignores it",
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


def test_reports_each_section_that_numbers_no_heading_of_its_doc(project: Path) -> None:
    (project / "docs" / "model.md").write_text(
        "# 1. Scope\n"
        "## 2 Inputs\n"
        "### 2.1. Weather\n"
        "#### 2.10 Tariffs ####\n"
        "##### 3.2\n"
        "## Contract\n"
        "#4. No space after its marker, so no heading\n"
        "    ## 5. Indented four spaces, so code, not a heading\n",
        encoding="utf-8",
    )
    source = _write_source(
        project,
        "src/pkg/module.py",
        "# docs/model.md §1, docs/model.md §2, docs/model.md §2.1, docs/model.md §2.10 and docs/model.md §3.2\n"
        "# docs/model.md §2.2\n"
        "# docs/model.md §3\n"
        "# docs/model.md §4\n"
        "# docs/model.md §5\n",
    )

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:2: docs/model.md §2.2: docs/model.md has no heading numbered 2.2",
        "src/pkg/module.py:3: docs/model.md §3: docs/model.md has no heading numbered 3",
        "src/pkg/module.py:4: docs/model.md §4: docs/model.md has no heading numbered 4",
        "src/pkg/module.py:5: docs/model.md §5: docs/model.md has no heading numbered 5",
    ]


def test_a_line_of_a_fenced_code_block_is_no_heading(project: Path) -> None:
    (project / "docs" / "model.md").write_text(
        "```python\n"
        "## 1. In a backtick fence\n"
        "```\n"
        "## 2. After it\n"
        "  ~~~~\n"
        "## 3. In a tilde fence of four, indented two spaces\n"
        "```\n"
        "~~~\n"
        "~~~~ text\n"
        "## 4. Still in it: no backtick, shorter or worded marker closes it\n"
        "~~~~~\n"
        "## 5. After it\n",
        encoding="utf-8",
    )
    source = _write_source(
        project, "src/pkg/module.py", "".join(f"# docs/model.md §{number}\n" for number in range(1, 6))
    )

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/model.md §1: docs/model.md has no heading numbered 1",
        "src/pkg/module.py:3: docs/model.md §3: docs/model.md has no heading numbered 3",
        "src/pkg/module.py:4: docs/model.md §4: docs/model.md has no heading numbered 4",
    ]


def test_reports_a_section_after_a_path_that_is_no_markdown_file(project: Path) -> None:
    (project / "docs" / "data.csv").write_text("# 1. A comment, not a heading\n", encoding="utf-8")
    source = _write_source(project, "src/pkg/module.py", "# docs/data.csv §1\n# docs/prds §1\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/data.csv §1: "
        "docs/data.csv is not a Markdown file, so it has no heading numbered 1",
        "src/pkg/module.py:2: docs/prds §1: docs/prds is not a Markdown file, so it has no heading numbered 1",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = project / "src" / "pkg" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG\xff\xfe docs/absent.md")

    assert _doc_pointers(project, [PurePosixPath("src/pkg/logo.png")]) == []
