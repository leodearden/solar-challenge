# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consumption-recipe doc contract tests.

Two CI-observable invariants for docs/domain-library-consumption.md:

  (A) The doc exists and contains the exact pinned-dependency recipe line
      from PRD §3.4 (copy-paste contract artifact).

  (B) The doc's sentinel-delimited frozen-surface listing equals
      solar_challenge.__all__ with no duplicates (drift guard).

Parsing uses HTML-comment sentinels and a bare-identifier regex so the
check is robust to doc restructuring and human-readable grouping comments.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOC_REL_PATH = "docs/domain-library-consumption.md"

# Verbatim from PRD §3.4 line 193 — the copy-paste contract artifact.
PINNED_DEPENDENCY_LINE = (
    "solar-challenge @ git+file:///home/leo/src/my-solar-challenge@<release-tag>"
)

# Sentinel comments that delimit the machine-checked surface listing.
_BEGIN_SENTINEL = "<!-- BEGIN-API-SURFACE -->"
_END_SENTINEL = "<!-- END-API-SURFACE -->"

# Matches one bare identifier per line (captures the name; skips fence markers,
# blank lines, and #-prefixed group comments).
_BARE_IDENT_RE = re.compile(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_doc(project_root: Path) -> str:
    """Return the full text of the consumption recipe doc."""
    doc_path = project_root / DOC_REL_PATH
    return doc_path.read_text(encoding="utf-8")


def _parse_surface_names(doc_text: str) -> list[str]:
    """Extract bare identifier names from the sentinel-delimited surface block.

    Asserts both sentinels are present (with a descriptive message), then
    collects every line matching the bare-identifier regex within that region.
    Fence markers (```), blank lines, and #-prefixed group comments are
    naturally excluded by the regex.
    """
    assert _BEGIN_SENTINEL in doc_text, (
        f"'{_BEGIN_SENTINEL}' sentinel not found in {DOC_REL_PATH}; "
        "add the <!-- BEGIN-API-SURFACE --> / <!-- END-API-SURFACE --> block"
    )
    assert _END_SENTINEL in doc_text, (
        f"'{_END_SENTINEL}' sentinel not found in {DOC_REL_PATH}; "
        "add the <!-- BEGIN-API-SURFACE --> / <!-- END-API-SURFACE --> block"
    )

    begin_idx = doc_text.index(_BEGIN_SENTINEL) + len(_BEGIN_SENTINEL)
    end_idx = doc_text.index(_END_SENTINEL)
    region = doc_text[begin_idx:end_idx]

    return _BARE_IDENT_RE.findall(region)


# ---------------------------------------------------------------------------
# Tests — Behavior A: recipe contract
# ---------------------------------------------------------------------------

def test_consumption_doc_exists(project_root: Path) -> None:
    """The consumption-recipe doc must exist and be non-empty."""
    doc_path = project_root / DOC_REL_PATH
    assert doc_path.exists(), (
        f"{DOC_REL_PATH} does not exist; create it with the pinned-dependency "
        "recipe and consumption caveats (PRD §3.4)"
    )
    content = doc_path.read_text(encoding="utf-8").strip()
    assert content, f"{DOC_REL_PATH} exists but is empty"


def test_doc_contains_pinned_dependency_recipe(project_root: Path) -> None:
    """The doc must contain the exact pinned-dependency recipe line from PRD §3.4.

    This is a copy-paste contract artifact: the template line
    'solar-challenge @ git+file:///home/leo/src/my-solar-challenge@<release-tag>'
    must appear verbatim so consumers can copy it and substitute a real tag.
    """
    doc_text = _read_doc(project_root)
    assert PINNED_DEPENDENCY_LINE in doc_text, (
        f"Exact pinned-dependency recipe line not found in {DOC_REL_PATH}.\n"
        f"Expected substring:\n  {PINNED_DEPENDENCY_LINE!r}\n"
        "Add the line verbatim (PRD §3.4 line 193)."
    )


