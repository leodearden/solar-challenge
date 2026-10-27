# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every path into docs/ that a scanned file names is in the tree, and each section written right after one is in its doc.

The scanned files are those git lists, tests/ included, outside the _UNSCANNED paths. Those are the records, which
name docs as they were when written, and the two pointer-gate modules, whose docs/ paths name files of the throwaway
checkouts their tests build.

A pointer is a path rooted at docs/, a file or a directory. It is looked for anywhere in a file's text, comments,
docstrings and code alike. A file that is not UTF-8 text holds none. The path is looked up in the files git lists and
the directories holding them, as a fresh clone would hold them, so a file git ignores is not there to point at. A doc
in another repository is written from that repository's name, as in dark-factory/docs/code-quality.md, so it is not
rooted at docs/.

A section written right after the path, as in docs/<name>.md §3.1, must be the number of a heading of that Markdown
file, here ### 3.1 <title>. Between path and section there may be a closing backtick, a link's closing bracket and its
target, as in [docs/<name>.md](<name>.md) §3.1, a comma, and white space: spaces and tabs, around one line break at
most, as a wrapped docstring has. A comment marker after that line break is no white space, so a section wrapped onto
the next comment line is not read, and nor is one after a blank line. A number is runs of digits joined by dots, and a
full stop after it ends its sentence. A number with a letter after it, as §3.1a or §3.a, is no section. A heading is
an ATX heading outside a fenced code block, and its number is the one its text starts with, as 3 in ## 3. <title>. The
whole number must match: §3 is not the number of ### 3.1 <title>. A Markdown file that is not UTF-8 text has no
headings to read, so a section after it is reported. Only that section is looked up: not one written before the path,
as in §3 of docs/<name>.md, one named in words, as in §Contract, nor a later one of a list or range, as the §7.4 of
§7.3–§7.4.
"""

import functools
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import WorkingTreePaths, working_tree_paths

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
    (?:
        `?(?:\](?:\([^)\s]*\))?)?,?
        (?:[ \t]*\r?\n[ \t]*|[ \t]+)
        §(?P<section>{_SECTION_NUMBER})(?!\.?\w)
    )?
    """,
    re.VERBOSE,
)

_FENCE = re.compile(r" {0,3}(?P<fence>`{3,}|~{3,})")

_NUMBERED_HEADING = re.compile(rf" {{0,3}}#{{1,6}}[ \t]+(?P<number>{_SECTION_NUMBER})\.?(?:[ \t]|$)")


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
    """Return "<pointer>: <reason>" for each of the *pointers* that does not resolve in *root*'s working tree, in their order.

    The headings of each Markdown file are read when first asked for, and at most once.
    """
    tree = working_tree_paths(root)

    @functools.cache
    def heading_numbers_of(path: PurePosixPath) -> frozenset[str] | None:
        text = utf8_text(root / path)
        return None if text is None else _heading_numbers(text)

    return [
        f"{pointer}: {reason}"
        for pointer in pointers
        if (reason := _unresolved(tree, heading_numbers_of, pointer)) is not None
    ]


def _unresolved(
    tree: WorkingTreePaths,
    heading_numbers_of: Callable[[PurePosixPath], frozenset[str] | None],
    pointer: _DocPointer,
) -> str | None:
    """Return why *pointer* leads to no file, directory or heading in the working *tree*, or None if it leads to one.

    The tree must hold the path. A section after it must be the number of a heading of a Markdown file, and
    *heading_numbers_of* gives the numbers of a Markdown file's headings, or None if the file is not UTF-8 text.
    """
    if not tree.holds(pointer.path):
        return f"{pointer.path} does not exist, or git ignores it"
    if pointer.section is None:
        return None
    if pointer.path.suffix != ".md" or pointer.path not in tree.files:
        return f"{pointer.path} is not a Markdown file, so it has no heading numbered {pointer.section}"
    numbers = heading_numbers_of(pointer.path)
    if numbers is None:
        return f"{pointer.path} is not UTF-8 text, so it has no heading numbered {pointer.section}"
    if pointer.section not in numbers:
        return f"{pointer.path} has no heading numbered {pointer.section}"
    return None


def _heading_numbers(text: str) -> frozenset[str]:
    """Return the number each numbered ATX heading of the Markdown *text* starts with, but for those in a fenced code block."""
    headings = (_NUMBERED_HEADING.match(line) for line in _lines_outside_fences(text))
    return frozenset(heading["number"] for heading in headings if heading is not None)


def _lines_outside_fences(text: str) -> Iterator[str]:
    """Yield each line of the Markdown *text* that lies outside its fenced code blocks, the fence lines left out.

    A fence opens on three or more backticks or tildes, after at most three spaces. It closes on a run of the same
    character, at least as long, with nothing after it but white space.
    """
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE.match(line)
        if marker is None:
            if fence is None:
                yield line
        elif fence is None:
            fence = marker["fence"]
        elif marker["fence"].startswith(fence) and not line[marker.end() :].strip():
            fence = None


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
            "A renamed or moved doc's pointers must follow it, and a renumbered heading's sections must follow the"
            " heading. Name a doc by its path from the project root, docs/<name>.md, and a section of it by its"
            " heading's number right after the path, as in docs/<name>.md §3.1; this gate resolves both. Name"
            " another repository's doc from that repository's name, as in dark-factory/docs/code-quality.md.",
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
    return synthetic_checkout(tmp_path, {"docs/guide.md": "# Title\n", "docs/prds/record.md": "# Title\n"})


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
        write_file(project, source, "")

    assert set(scanned_files(project, _UNSCANNED)) == {PurePosixPath(source) for source in scanned}


def test_finds_each_path_into_docs_in_any_text_on_its_line(project: Path) -> None:
    module = write_file(
        project,
        "src/pkg/module.py",
        "# docs/guide.md §3 says why.\n"
        'DOC = "docs/prds/record.md"\n'
        "# The records are under docs/prds.\n"
        "# Not rooted at docs/: src/docs/gone.md, ../docs/gone.md, dark-factory/docs/code-quality.md,\n"
        "# https://example.org/docs/gone.md, readthedocs/gone.md, my-docs/gone.md, site.docs/gone.md\n"
        "# and docs/<name>.md\n",
    )
    page = write_file(project, "src/pkg/page.html", "<p>See docs/guide.md.</p>\n")

    assert [str(pointer) for pointer in _doc_pointers(project, [module, page])] == [
        "src/pkg/module.py:1: docs/guide.md §3",
        "src/pkg/module.py:2: docs/prds/record.md",
        "src/pkg/module.py:3: docs/prds",
        "src/pkg/page.html:1: docs/guide.md",
    ]


def test_reads_the_section_written_right_after_a_path(project: Path) -> None:
    notes = write_file(
        project,
        "docs/notes.md",
        "docs/guide.md §3 says why.\n"
        "`docs/guide.md` §3.1.\n"
        "[docs/guide.md](guide.md) §2\n"
        "[`docs/prds/record.md`](prds/record.md) §10.2's\n"
        "docs/guide.md, §5\n"
        "docs/guide.md\n"
        "§4, on the next line\n"
        "docs/guide.md §7.3–§7.4\n"
        "docs/guide.md \n"
        "        §6.2), as a wrapped docstring indents it\n"
        "docs/guide.md\r\n"
        "§8 after a CRLF line break\n"
        "docs/guide.md\t§9\n",
    )

    assert [str(pointer) for pointer in _doc_pointers(project, [notes])] == [
        "docs/notes.md:1: docs/guide.md §3",
        "docs/notes.md:2: docs/guide.md §3.1",
        "docs/notes.md:3: docs/guide.md §2",
        "docs/notes.md:4: docs/prds/record.md §10.2",
        "docs/notes.md:5: docs/guide.md §5",
        "docs/notes.md:6: docs/guide.md §4",
        "docs/notes.md:8: docs/guide.md §7.3",
        "docs/notes.md:9: docs/guide.md §6.2",
        "docs/notes.md:11: docs/guide.md §8",
        "docs/notes.md:13: docs/guide.md §9",
    ]


def test_reads_no_section_written_any_other_way(project: Path) -> None:
    texts = [
        "docs/guide.md §Contract",
        "docs/guide.md §3a",
        "docs/guide.md §3.1a",
        "docs/guide.md §2.10b",
        "docs/guide.md §3.a",
        "docs/guide.md § 3",
        "docs/guide.md§3",
        "docs/guide.md and §3",
        "§3 of docs/guide.md",
        "docs/guide.md\n\n§4 after a blank line",
        "# docs/guide.md\n# §4 on a comment line",
    ]
    notes = write_file(project, "docs/notes.md", "".join(f"{text}\n" for text in texts))

    assert [pointer.section for pointer in _doc_pointers(project, [notes])] == [None] * len(texts)


def test_reports_each_path_that_names_no_file_or_directory_of_the_tree_on_its_line(project: Path) -> None:
    source = write_file(
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
    write_file(project, ".gitignore", "generated/\n")
    write_file(project, "docs/generated/made.md", "# Made\n")
    source = write_file(project, "src/pkg/module.py", "# docs/generated/made.md\n# docs/generated\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/generated/made.md: docs/generated/made.md does not exist, or git ignores it",
        "src/pkg/module.py:2: docs/generated: docs/generated does not exist, or git ignores it",
    ]


def test_reports_each_section_that_numbers_no_heading_of_its_doc(project: Path) -> None:
    write_file(
        project,
        "docs/model.md",
        "# 1. Scope\n"
        "## 2 Inputs\n"
        "### 2.1. Weather\n"
        "#### 2.10 Tariffs ####\n"
        "##### 3.2\n"
        "## Contract\n"
        "#4. No space after its marker, so no heading\n"
        "    ## 5. Indented four spaces, so code, not a heading\n",
    )
    source = write_file(
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
    write_file(
        project,
        "docs/model.md",
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
    )
    source = write_file(
        project, "src/pkg/module.py", "".join(f"# docs/model.md §{number}\n" for number in range(1, 6))
    )

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/model.md §1: docs/model.md has no heading numbered 1",
        "src/pkg/module.py:3: docs/model.md §3: docs/model.md has no heading numbered 3",
        "src/pkg/module.py:4: docs/model.md §4: docs/model.md has no heading numbered 4",
    ]


def test_reports_a_section_after_a_path_that_is_no_markdown_file(project: Path) -> None:
    write_file(project, "docs/data.csv", "# 1. A comment, not a heading\n")
    source = write_file(project, "src/pkg/module.py", "# docs/data.csv §1\n# docs/prds §1\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/data.csv §1: "
        "docs/data.csv is not a Markdown file, so it has no heading numbered 1",
        "src/pkg/module.py:2: docs/prds §1: docs/prds is not a Markdown file, so it has no heading numbered 1",
    ]


def test_reports_each_section_after_a_markdown_file_that_is_not_utf8_text(project: Path) -> None:
    write_file(project, "docs/latin1.md", "# 1. Café\n".encode("latin-1"))
    source = write_file(
        project, "src/pkg/module.py", "# docs/latin1.md §1\n# docs/latin1.md §2\n# docs/latin1.md has no section\n"
    )

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/latin1.md §1: "
        "docs/latin1.md is not UTF-8 text, so it has no heading numbered 1",
        "src/pkg/module.py:2: docs/latin1.md §2: "
        "docs/latin1.md is not UTF-8 text, so it has no heading numbered 2",
    ]


def test_resolves_a_section_after_a_markdown_file_that_starts_with_a_byte_order_mark(project: Path) -> None:
    write_file(project, "docs/marked.md", "# 1. Intro\n".encode("utf-8-sig"))
    source = write_file(project, "src/pkg/module.py", "# docs/marked.md §1\n# docs/marked.md §2\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:2: docs/marked.md §2: docs/marked.md has no heading numbered 2",
    ]


def test_a_line_of_a_fenced_code_block_opened_right_after_a_byte_order_mark_is_no_heading(project: Path) -> None:
    write_file(project, "docs/marked.md", "```\n## 1. In a fence\n```\n## 2. After it\n".encode("utf-8-sig"))
    source = write_file(project, "src/pkg/module.py", "# docs/marked.md §1\n# docs/marked.md §2\n")

    assert _dangling(project, _doc_pointers(project, [source])) == [
        "src/pkg/module.py:1: docs/marked.md §1: docs/marked.md has no heading numbered 1",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = write_file(project, "src/pkg/logo.png", b"\x89PNG\xff\xfe docs/absent.md")

    assert _doc_pointers(project, [logo]) == []
