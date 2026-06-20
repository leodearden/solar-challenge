# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consumption-recipe doc smoke-check.

Verifies that docs/domain-library-consumption.md exists and is non-empty —
a deliverable-presence guard for the consumer-facing recipe document.

The authoritative public surface is ``solar_challenge.__all__`` (defined in
``src/solar_challenge/__init__.py``), which is frozen and contract-tested by
``tests/unit/test_init_lazy_surface.py``.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOC_REL_PATH = "docs/domain-library-consumption.md"


# ---------------------------------------------------------------------------
# Tests
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
