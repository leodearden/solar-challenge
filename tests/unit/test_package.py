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


def test_version_is_release_target():
    """Package version must be 0.5.0 (additive minor bump: CBS amount due).

    0.3.0 was the additive minor bump for bill() export.
    0.4.0 was the basis-C cost-recovery + arbitrage-fix release.
    0.5.0 adds BillBreakdown.own_use_vat_gbp and cbs_amount_due_gbp, the
    CBS-collectable slice of the householder's outlay (own-use payment plus VAT
    on it, excluding retailer-side import and standing charge), so the CBS can
    invoice own-use only. Platform PRD cbs-invoice-own-use-only task λ2 re-pins
    to this version.
    """
    assert solar_challenge.__version__ == "0.5.0"


def test_pyproject_version_matches_dunder():
    """pyproject.toml [project] version must equal solar_challenge.__version__."""
    project_root = Path(__file__).parent.parent.parent
    pyproject_version = load_project_table(project_root)["version"]
    assert pyproject_version == solar_challenge.__version__, (
        f"pyproject.toml [project] version {pyproject_version!r} != "
        f"solar_challenge.__version__ {solar_challenge.__version__!r}"
    )
