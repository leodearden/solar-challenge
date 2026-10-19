"""Basic package tests."""

from pathlib import Path

import solar_challenge
from tests._pyproject import load_project_table


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


def test_pyproject_version_matches_dunder():
    """pyproject.toml [project] version must equal solar_challenge.__version__."""
    project_root = Path(__file__).parent.parent.parent
    pyproject_version = load_project_table(project_root)["version"]
    assert pyproject_version == solar_challenge.__version__, (
        f"pyproject.toml [project] version {pyproject_version!r} != "
        f"solar_challenge.__version__ {solar_challenge.__version__!r}"
    )
