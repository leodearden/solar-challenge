"""Basic package tests."""

import re
from pathlib import Path

import solar_challenge


def test_version_exists():
    """Package has a version string."""
    assert hasattr(solar_challenge, "__version__")
    assert isinstance(solar_challenge.__version__, str)


def test_version_format():
    """Version follows semantic versioning format."""
    version = solar_challenge.__version__
    parts = version.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_version_is_release_target():
    """Package version must be 0.4.0 (minor bump: basis-C cost-recovery + arbitrage fix).

    0.3.0 was the additive minor bump for bill() export.
    0.4.0 is the basis-C release: own_use = demand − import across the money path
    (_simulate_age fleet_sc and bill_distribution annual_sc both use _cbs_own_use_kwh),
    fixing silent CBS under-recovery on TOU-arbitrage / grid-charging homes. Platform
    P7 task α2 re-pins to this version.
    """
    assert solar_challenge.__version__ == "0.4.0"


def _pyproject_project_version(text: str) -> str:
    """Extract version from the [project] section of pyproject.toml text.

    Scopes the search to the [project] table (not a later [tool.*] or
    [build-system] table that might also contain a ``version =`` line),
    so a future table reorder cannot match the wrong field.
    """
    # Isolate [project] section: starts at "[project]" and ends at the next
    # section header (a bare "[" at start of line) or end-of-file.
    block_match = re.search(
        r'^\[project\](.*?)(?=^\[|\Z)', text, re.DOTALL | re.MULTILINE
    )
    assert block_match is not None, "No [project] section in pyproject.toml"
    project_block = block_match.group(1)
    m = re.search(r'^version\s*=\s*"([^"]+)"', project_block, re.MULTILINE)
    assert m is not None, "No 'version = ...' in [project] section of pyproject.toml"
    return m.group(1)


def test_pyproject_version_matches_dunder():
    """pyproject.toml [project] version must equal solar_challenge.__version__.

    Uses a section-scoped parse so a future pyproject edit adding another
    ``version =`` line in a different table cannot match spuriously.
    """
    project_root = Path(__file__).parent.parent.parent
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    pyproject_version = _pyproject_project_version(text)
    assert pyproject_version == solar_challenge.__version__, (
        f"pyproject.toml [project] version {pyproject_version!r} != "
        f"solar_challenge.__version__ {solar_challenge.__version__!r}"
    )
