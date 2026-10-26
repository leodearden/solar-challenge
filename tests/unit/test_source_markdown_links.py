# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every relative link in a scanned markdown file leads to a file or directory of the tree.

The scanned files are the markdown files, named *.md, that git lists outside RECORD_DIRECTORIES, the records, which link
files as they were when written. A link is written [text](target) or ![text](target), and a ](target) inside code reads
as one too. Its target names a path unless it is a URL, with a scheme or a host, or names only a place in the linking
file itself, as #<heading> does. The path resolves as GitHub resolves it: from the linking file's directory, or from the
project root if it starts with /, with its %-escapes decoded. A #fragment after the path is dropped, so only the path is
checked. The path is looked up in the files git lists and the directories holding them, as a fresh clone would hold
them, so a file git ignores is not there to link to. A markdown file that is not UTF-8 text is reported by its path,
since its links cannot be read.
"""

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from tests._working_tree import WorkingTreePaths

_LINK_TARGET = re.compile(r"\]\((?P<target>[^)\s]+)")


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


def _links_in(source: PurePosixPath, text: str) -> list[_Link]:
    """Return the links in *text*, the content of markdown file *source*, whose targets name a path, in text order."""
    return [
        _Link(source=source, line=text.count("\n", 0, match.start()) + 1, target=match["target"])
        for match in _LINK_TARGET.finditer(text)
        if _names_a_path(match["target"])
    ]


def _dangling(tree: WorkingTreePaths, links: Iterable[_Link]) -> list[str]:
    """Return "<link>: <reason>" for each of the *links* whose path the working *tree* does not hold, in their order."""
    return [f"{link}: {link.path} does not exist, or git ignores it" for link in links if not tree.holds(link.path)]


def test_reads_each_link_target_that_names_a_path_on_its_line() -> None:
    text = (
        "# Intro\n"
        'See [setup](setup.md) and ![the flow](images/flow.png "Flow").\n'
        "[Amended: [the module](../src/pkg/module.py#L3) and its\n"
        "[`records`](records/) say why.]\n"
        "Not paths: [a URL](https://example.org/guide/setup.md), [mail](mailto:team@example.org),\n"
        "[a host](//example.org/setup.md), [a heading](#intro) and [nothing]().\n"
    )

    links = _links_in(PurePosixPath("guide/intro.md"), text)

    assert [str(link) for link in links] == [
        "guide/intro.md:2: setup.md",
        "guide/intro.md:2: images/flow.png",
        "guide/intro.md:3: ../src/pkg/module.py#L3",
        "guide/intro.md:4: records/",
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
