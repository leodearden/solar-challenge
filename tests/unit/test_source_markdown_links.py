# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every relative link in a scanned markdown file leads to a file or directory of the tree.

The scanned files are the markdown files, named *.md, that git lists outside RECORD_DIRECTORIES, the records, which link
files as they were when written. A link is written [text](target) or ![text](target), and a ](target) inside code reads
as one too. A target is a run without spaces, whose parentheses come in unnested pairs, as in v2_(final).md, or text
between < and >, which may hold spaces. It names a path unless it is a URL, with a scheme or a host, or names only a
place in the linking file itself, as #<heading> does. The path resolves as GitHub resolves it: from the linking file's
directory, or from the project root if it starts with /, with its %-escapes decoded. A #fragment after the path is
dropped, so only the path is checked. The path is looked up in the files git lists and the directories holding them, as
a fresh clone would hold them, so a file git ignores is not there to link to. A markdown file that is not UTF-8 text is
reported by its path, since its links cannot be read.
"""

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import pytest

from tests._hermetic_checkout import init_hermetic_checkout
from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._working_tree import WorkingTreePaths, working_tree_paths

_ANGLED_TARGET = r"<(?P<angled>[^<>\n]*)>"
_BARE_TARGET = r"(?P<bare>(?:[^()\s]|\([^()\s]*\))+)"
_LINK_TARGET = re.compile(rf"\]\((?:{_ANGLED_TARGET}|{_BARE_TARGET})")


@dataclass(frozen=True)
class _Link:
    """A link whose target names a path: the file holding it, relative to the project root, its line, and its target."""

    source: PurePosixPath
    line: int
    target: str

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {self.target}"

    @property
    def path(self) -> PurePosixPath:
        """The path, relative to the project root, that the target leads to.

        It is normalised lexically, so a target climbing above the root keeps its leading '..'.
        """
        written = unquote(urlsplit(self.target).path)
        base = PurePosixPath() if written.startswith("/") else self.source.parent
        return PurePosixPath(posixpath.normpath(base / written.lstrip("/")))


def _names_a_path(target: str) -> bool:
    """Return whether *target* has no scheme and no host, and a path of its own."""
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and bool(parts.path)


def _targets_on(line: str) -> list[str]:
    """Return the target of each link on *line*, in order: the text in a link's angle brackets, or else its bare run."""
    return [angled or bare for angled, bare in _LINK_TARGET.findall(line)]


def _links_in(source: PurePosixPath, text: str) -> list[_Link]:
    """Return the links in *text*, the content of markdown file *source*, whose targets name a path, in text order."""
    return [
        _Link(source=source, line=number, target=target)
        for number, line in enumerate(text.split("\n"), start=1)
        for target in _targets_on(line)
        if _names_a_path(target)
    ]


def _links(root: Path, sources: Iterable[PurePosixPath]) -> list[_Link]:
    """Return the links whose targets name a path in the *sources*, markdown files relative to *root*, file by file.

    A source that is not UTF-8 text raises ValueError, naming it.
    """
    links: list[_Link] = []
    for source in sources:
        text = utf8_text(root / source)
        if text is None:
            raise ValueError(f"{source} is not UTF-8 text, so its links cannot be read")
        links.extend(_links_in(source, text))
    return links


def _dangling(tree: WorkingTreePaths, links: Iterable[_Link]) -> list[str]:
    """Return "<link>: <reason>" for each of the *links* whose path the working *tree* does not hold, in their order."""
    return [f"{link}: {link.path} does not exist, or git ignores it" for link in links if not tree.holds(link.path)]


def _markdown_files(root: Path) -> list[PurePosixPath]:
    """Return the markdown files git lists in *root* outside RECORD_DIRECTORIES, in scanned_files' order."""
    return [path for path in scanned_files(root, RECORD_DIRECTORIES) if path.suffix == ".md"]


def test_every_relative_link_in_the_scanned_markdown_files_resolves(project_root: Path) -> None:
    links = _links(project_root, _markdown_files(project_root))
    records = ", ".join(str(directory) for directory in RECORD_DIRECTORIES)
    assert links, (
        f"found no link naming a path in any markdown file git lists outside the records ({records}), so this gate"
        " would pass vacuously; fix the listing or the grammar"
    )

    dangling = _dangling(working_tree_paths(project_root), links)

    assert dangling == [], "\n".join(
        [
            *dangling,
            "A renamed or moved file's links must follow it. Write a link's target relative to the linking file's"
            " directory, as in [the losses](pv-system-losses.md) from one doc to another, or"
            " [its test](../tests/unit/test_pv.py) from a doc to the code.",
        ]
    )


def test_reads_each_link_target_that_names_a_path_on_its_line() -> None:
    text = (
        "# Intro\n"
        'See [setup](setup.md) and ![the flow](images/flow.png "Flow").\n'
        "[Amended: [the module](../src/pkg/module.py#L3) and its\n"
        "[`records`](records/) say why.]\n"
        "Not paths: [a URL](https://example.org/guide/setup.md), [mail](mailto:team@example.org),\n"
        "[a host](//example.org/setup.md), [a heading](#intro) and [nothing]().\n"
        "[A spaced URL](<https://example.org/a b>) and [no target](<>) are no paths either.\n"
        "Spaces and parentheses: [notes](<my notes.md>), [a release](v2_(final).md) and (see [setup](setup.md)).\n"
    )

    links = _links_in(PurePosixPath("guide/intro.md"), text)

    assert [str(link) for link in links] == [
        "guide/intro.md:2: setup.md",
        "guide/intro.md:2: images/flow.png",
        "guide/intro.md:3: ../src/pkg/module.py#L3",
        "guide/intro.md:4: records/",
        "guide/intro.md:8: my notes.md",
        "guide/intro.md:8: v2_(final).md",
        "guide/intro.md:8: setup.md",
    ]


def test_resolves_a_target_from_the_linking_files_directory_or_from_the_root_after_a_slash() -> None:
    intro = _links_in(
        PurePosixPath("guide/intro.md"),
        "[a](setup.md) [b](./images/flow.png) [c](../src/pkg/module.py#L3) [d](records/)\n"
        "[e](/guide/setup.md) [f](..) [g](../../outside.md) [h](my%20notes.md)\n",
    )
    readme = _links_in(PurePosixPath("README.md"), "[i](guide/intro.md)\n")

    assert [str(link.path) for link in [*intro, *readme]] == [
        "guide/setup.md",
        "guide/images/flow.png",
        "src/pkg/module.py",
        "guide/records",
        "guide/setup.md",
        ".",
        "../outside.md",
        "guide/my notes.md",
        "guide/intro.md",
    ]


def test_reports_each_link_that_leads_to_no_file_or_directory_of_the_tree_on_its_line() -> None:
    tree = WorkingTreePaths(
        files=frozenset(PurePosixPath(path) for path in ["README.md", "guide/intro.md", "guide/setup.md"]),
        directories=frozenset(PurePosixPath(path) for path in [".", "guide"]),
    )
    links = _links_in(
        PurePosixPath("guide/intro.md"),
        "[a](setup.md#steps) [b](../guide) [c](..)\n[d](absent.md)\n[e](../../README.md) [f](/guide/absent.md)\n",
    )

    assert _dangling(tree, links) == [
        "guide/intro.md:2: absent.md: guide/absent.md does not exist, or git ignores it",
        "guide/intro.md:3: ../../README.md: ../README.md does not exist, or git ignores it",
        "guide/intro.md:3: /guide/absent.md: guide/absent.md does not exist, or git ignores it",
    ]


def test_reads_the_links_of_a_utf8_file_and_reports_one_that_is_not_by_its_path(tmp_path: Path) -> None:
    (tmp_path / "guide").mkdir()
    (tmp_path / "guide" / "intro.md").write_text("See [setup](setup.md).\n", encoding="utf-8")
    (tmp_path / "guide" / "latin.md").write_bytes(b"Caf\xe9: [setup](setup.md)\n")

    assert [str(link) for link in _links(tmp_path, [PurePosixPath("guide/intro.md")])] == ["guide/intro.md:1: setup.md"]
    with pytest.raises(ValueError, match=r"^guide/latin\.md is not UTF-8 text"):
        _links(tmp_path, [PurePosixPath("guide/intro.md"), PurePosixPath("guide/latin.md")])


def test_scans_every_markdown_file_git_lists_outside_the_records(tmp_path: Path) -> None:
    checkout = init_hermetic_checkout(tmp_path / "checkout")
    scanned = [PurePosixPath(path) for path in ["README.md", "guide/intro.md", "src/pkg/LICENSE.md", "tests/notes.md"]]
    unscanned = [
        *(directory / "record.md" for directory in RECORD_DIRECTORIES),
        PurePosixPath("guide/notes.txt"),
        PurePosixPath("src/pkg/module.py"),
    ]
    for relative_path in [*scanned, *unscanned]:
        path = checkout / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    assert sorted(_markdown_files(checkout)) == sorted(scanned)
