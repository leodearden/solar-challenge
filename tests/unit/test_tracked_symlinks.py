# SPDX-License-Identifier: AGPL-3.0-or-later
"""No symlink the git index tracks points outside the checkout, where its target would depend on where the checkout sits."""

import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from tests._hermetic_checkout import init_hermetic_checkout

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the tree's symlinks are listed with it"
)


def _git(checkout: Path, *arguments: str) -> str:
    """Return what git, run with *arguments* in *checkout*, writes to its standard output; raise CalledProcessError if it fails."""
    return subprocess.run(["git", *arguments], cwd=checkout, capture_output=True, text=True, check=True).stdout


def _tracked_symlinks(checkout: Path) -> dict[str, str]:
    """Map the path of each symlink in *checkout*'s git index to the target text the index holds for it."""
    links: dict[str, str] = {}
    for entry in filter(None, _git(checkout, "ls-files", "--stage", "-z").split("\0")):
        metadata, path = entry.split("\t", 1)
        mode, blob, _stage = metadata.split(" ")
        if mode == "120000":
            links[path] = _git(checkout, "cat-file", "blob", blob)
    return links


def _resolve(links: dict[str, str], link: str, following: frozenset[str] = frozenset()) -> list[str] | None:
    """Return the names on the path from the checkout root to where *link* leads, or None if it leads outside the checkout.

    *links* maps each tracked link to its target. A target is read from its link's own directory. Each tracked link
    on the way is followed as the system follows it, except one the walk is already *following*.
    """
    target = PurePosixPath(links[link])
    if target.is_absolute():
        return None
    following = following | {link}
    reached = list(PurePosixPath(link).parent.parts)
    for name in target.parts:
        if name == "..":
            if not reached:
                return None
            reached.pop()
            continue
        path = "/".join([*reached, name])
        if path in links and path not in following:
            followed = _resolve(links, path, following)
            if followed is None:
                return None
            reached = followed
        else:
            reached.append(name)
    return reached


def _tracked_symlinks_pointing_outside(checkout: Path) -> dict[str, str]:
    """Map the path of each symlink in *checkout*'s git index whose target leaves the checkout to that target."""
    links = _tracked_symlinks(checkout)
    return {link: target for link, target in links.items() if _resolve(links, link) is None}


def test_no_tracked_symlink_points_outside_the_checkout(project_root: Path) -> None:
    outside = _tracked_symlinks_pointing_outside(project_root)

    assert outside == {}, (
        "these tracked symlinks point outside the checkout, so each resolves to a different place from the main"
        f" checkout and from each worktree under .worktrees/: {outside}; track the content itself, or a symlink"
        " to a path inside the tree"
    )


def test_reports_only_the_symlinks_whose_target_leaves_the_checkout(tmp_path: Path) -> None:
    checkout = init_hermetic_checkout(tmp_path / "checkout")
    (checkout / "nested").mkdir()
    (checkout / "not_a_link").write_text("../outside", encoding="utf-8")
    (checkout / "inside").symlink_to("nested", target_is_directory=True)
    (checkout / "nested" / "up_and_back").symlink_to("../inside", target_is_directory=True)
    (checkout / "nested" / "to_the_root").symlink_to("..", target_is_directory=True)
    (checkout / "loop").symlink_to("loop")
    (checkout / "climbing").symlink_to("../outside")
    (checkout / "nested" / "climbing_twice").symlink_to("../../outside")
    (checkout / "parent").symlink_to("..", target_is_directory=True)
    (checkout / "absolute").symlink_to("/outside")
    (checkout / "climbing_through_a_link").symlink_to("nested/to_the_root/..", target_is_directory=True)
    (checkout / "through_an_outside_link").symlink_to("parent/outside")
    subprocess.run(["git", "add", "--all"], cwd=checkout, check=True)

    assert _tracked_symlinks_pointing_outside(checkout) == {
        "absolute": "/outside",
        "climbing": "../outside",
        "nested/climbing_twice": "../../outside",
        "parent": "..",
        "climbing_through_a_link": "nested/to_the_root/..",
        "through_an_outside_link": "parent/outside",
    }
