# SPDX-License-Identifier: AGPL-3.0-or-later
"""Python version metadata contract tests.

These tests encode machine-checkable invariants that keep pyproject.toml's
requires-python specifier, the .python-version pin, and the Programming
Language classifiers mutually consistent.  pyproject.toml is parsed as TOML
and requires-python is evaluated as a PEP 440 specifier set.
"""

import re
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from tests._pyproject import load_project_table

# Interpreters beyond the .python-version pin that downstream consumers
# (solar-challenge-platform) install the library on.
_CONSUMER_INTERPRETERS: tuple[tuple[int, int], ...] = ((3, 13), (3, 14))

_PYTHON_MINOR_CLASSIFIER = re.compile(r"Programming Language :: Python :: (\d+)\.(\d+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _requires_python(project_root: Path) -> SpecifierSet:
    """Return pyproject.toml's requires-python as a PEP 440 specifier set."""
    return SpecifierSet(load_project_table(project_root)["requires-python"])


def _admitted_minor_versions(requires_python: SpecifierSet) -> set[tuple[int, int]]:
    """Return the Python 3 minor versions, searched from 3.0 to 3.99, that *requires_python* admits."""
    return {(3, minor) for minor in range(100) if requires_python.contains(f"3.{minor}")}


def _classifier_minor_versions(project_root: Path) -> set[tuple[int, int]]:
    """Return the (major, minor) pairs named by 'Programming Language :: Python :: X.Y' classifiers."""
    matches = (
        _PYTHON_MINOR_CLASSIFIER.fullmatch(classifier)
        for classifier in load_project_table(project_root)["classifiers"]
    )
    return {(int(m.group(1)), int(m.group(2))) for m in matches if m}


def _python_version_pin(project_root: Path) -> Version:
    """Return the interpreter version pinned by .python-version."""
    pv_file = project_root / ".python-version"
    assert pv_file.exists(), ".python-version missing (run test_python_version_file_exists first)"
    return Version(pv_file.read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_requires_python_has_upper_bound(project_root: Path) -> None:
    """requires-python must include an upper bound (<X.Y).

    An unbounded specifier lets uv resolve interpreters the suite has never
    run on (e.g. a future 3.15), where changed interpreter defaults or new
    warnings from optional deps would go unnoticed.
    """
    requires_python = _requires_python(project_root)
    assert any(spec.operator in {"<", "<="} for spec in requires_python), (
        f"requires-python={str(requires_python)!r} has no upper bound (<X.Y); "
        "add one matching the Programming Language classifiers"
    )


def test_python_version_file_exists(project_root: Path) -> None:
    """A non-empty .python-version file must exist at the project root.

    This pins uv/pyenv to a specific interpreter and stops the resolver
    from wandering outside the declared requires-python range.
    """
    pv_file = project_root / ".python-version"
    assert pv_file.exists(), (
        ".python-version does not exist; create it with a 3.X version string"
    )
    content = pv_file.read_text(encoding="utf-8").strip()
    assert content, ".python-version exists but is empty"


def test_python_version_within_requires_python(project_root: Path) -> None:
    """.python-version pin must satisfy requires-python."""
    requires_python = _requires_python(project_root)
    pin = _python_version_pin(project_root)

    assert requires_python.contains(pin), (
        f".python-version {pin} is outside requires-python={str(requires_python)!r}"
    )


def test_python_version_listed_in_classifiers(project_root: Path) -> None:
    """.python-version minor version must appear as a Programming Language classifier."""
    pin = _python_version_pin(project_root)
    declared = _classifier_minor_versions(project_root)

    assert (pin.major, pin.minor) in declared, (
        f"No 'Programming Language :: Python :: {pin.major}.{pin.minor}' classifier found in "
        f"pyproject.toml; add it or adjust .python-version to a declared version. "
        f"Declared X.Y classifiers: {sorted(declared)}"
    )


@pytest.mark.parametrize(
    "version",
    _CONSUMER_INTERPRETERS,
    ids=[f"{major}.{minor}" for major, minor in _CONSUMER_INTERPRETERS],
)
def test_requires_python_admits_consumer_interpreter(
    project_root: Path, version: tuple[int, int]
) -> None:
    """requires-python must admit every interpreter downstream consumers install the library on."""
    requires_python = _requires_python(project_root)

    assert version in _admitted_minor_versions(requires_python), (
        f"Python {version} is outside requires-python={str(requires_python)!r}; "
        "downstream consumers need the library installable on this interpreter"
    )


def test_classifiers_match_requires_python_range(project_root: Path) -> None:
    """The X.Y classifiers must name exactly the minor versions requires-python admits."""
    requires_python = _requires_python(project_root)
    admitted = _admitted_minor_versions(requires_python)
    declared = _classifier_minor_versions(project_root)

    assert declared == admitted, (
        f"Programming Language classifiers {sorted(declared)} disagree with "
        f"requires-python={str(requires_python)!r}: missing classifiers "
        f"{sorted(admitted - declared)}, extra classifiers {sorted(declared - admitted)}"
    )
