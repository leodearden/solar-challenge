# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consumption-recipe doc checks.

Verifies that docs/domain-library-consumption.md exists, is non-empty, and
names the package version as its current release in every place it spells
that tag.

The authoritative public surface is ``solar_challenge.__all__`` (defined in
``src/solar_challenge/__init__.py``), which is frozen by
``tests/unit/test_public_api_surface.py``, whose ``FROZEN_SET`` pins every
public name.  The same module also checks the lazy loader.
"""

import re
from pathlib import Path

import solar_challenge

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOC_REL_PATH = "docs/domain-library-consumption.md"

CURRENT_RELEASE_TAG_SPELLINGS: dict[str, re.Pattern[str]] = {
    "the Pinned dependency recipe's worked example": re.compile(
        r'solar-challenge\.git@(solar-challenge-v[^"\s]+)"'
    ),
    "the tag list's current release": re.compile(
        r"^(solar-challenge-v\S+)\s+← current release", re.MULTILINE
    ),
    "the Upgrade workflow's commit-message example": re.compile(
        r"`chore\(deps\): bump solar-challenge to (solar-challenge-v[^`\s]+)`"
    ),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_consumption_doc_exists(project_root: Path) -> None:
    """The consumption-recipe doc must exist and be non-empty.

    This is a deliberate deliverable-presence smoke check.  The authoritative
    public-surface contract is separately enforced by
    ``tests/unit/test_public_api_surface.py`` (whose ``FROZEN_SET`` pins
    every public name) and by the import-time guard in
    ``src/solar_challenge/__init__.py``, so no symbol-list mirroring is
    needed here.
    """
    doc_path = project_root / DOC_REL_PATH
    assert doc_path.exists(), (
        f"{DOC_REL_PATH} does not exist; create it with the pinned-dependency "
        "recipe and consumption caveats (docs/prds/domain-library-extraction.md §3.4)"
    )
    content = doc_path.read_text(encoding="utf-8").strip()
    assert content, f"{DOC_REL_PATH} exists but is empty"


def test_every_current_release_tag_the_guide_spells_is_the_package_version(
    project_root: Path,
) -> None:
    """Each spelling of the current release tag names ``__version__``, once.

    A spelling the guide drops or doubles fails too, so a reworded anchor
    cannot let the check pass with nothing to compare.
    """
    text = (project_root / DOC_REL_PATH).read_text(encoding="utf-8")
    expected = f"solar-challenge-v{solar_challenge.__version__}"
    mismatched = {
        spelling: found
        for spelling, pattern in CURRENT_RELEASE_TAG_SPELLINGS.items()
        if (found := pattern.findall(text)) != [expected]
    }
    assert not mismatched, (
        f"{DOC_REL_PATH} must spell the current release tag {expected!r} "
        "exactly once in each of these places, but found:\n"
        + "\n".join(
            f"  {spelling}: {found!r}" for spelling, found in mismatched.items()
        )
        + "\nEdit the guide's spelling, or bump __version__ and pyproject.toml together."
    )
