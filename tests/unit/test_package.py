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
    """Package version must be 0.3.0 (additive minor bump for bill() export)."""
    assert solar_challenge.__version__ == "0.3.0"


def test_pyproject_version_matches_dunder():
    """pyproject.toml version must equal solar_challenge.__version__.

    Parses pyproject.toml with a regex (tomllib-free; compatible with Py3.10+).
    Only the [project] table version field is matched.
    """
    project_root = Path(__file__).parent.parent.parent
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    # Match `version = "..."` in the [project] section
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m is not None, "Could not find 'version = ...' in pyproject.toml"
    pyproject_version = m.group(1)
    assert pyproject_version == solar_challenge.__version__, (
        f"pyproject.toml version {pyproject_version!r} != "
        f"solar_challenge.__version__ {solar_challenge.__version__!r}"
    )
