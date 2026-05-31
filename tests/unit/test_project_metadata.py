# SPDX-License-Identifier: AGPL-3.0-or-later
"""Python version metadata contract tests.

These tests encode machine-checkable invariants that keep pyproject.toml's
requires-python specifier, the .python-version pin, and the Programming
Language classifiers mutually consistent.  Parsing is text-based so it
works under Python 3.10 where tomllib is unavailable, matching the style
of tests/unit/test_license_compliance.py.
"""

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_pyproject(project_root: Path) -> str:
    """Return the full text of pyproject.toml."""
    return (project_root / "pyproject.toml").read_text(encoding="utf-8")


def _extract_requires_python(text: str) -> str:
    """Extract the requires-python value (without surrounding quotes)."""
    m = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
    assert m, "could not find requires-python in pyproject.toml"
    return m.group(1)


def _extract_classifiers(text: str) -> list[str]:
    """Return every classifier value found in pyproject.toml."""
    return re.findall(r'"(Programming Language :: Python :: [^"]+)"', text)


def _parse_version_pin(pin: str) -> tuple[int, int]:
    """Parse a version string like '3.12' or '3.12.3' into (major, minor)."""
    parts = pin.strip().split(".")
    assert len(parts) >= 2, f"unexpected .python-version content: {pin!r}"
    return int(parts[0]), int(parts[1])


def _parse_requires_python_bounds(specifier: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Return (lower_bound, upper_bound) as (major, minor) tuples or None.

    Parses specifiers like '>=3.10,<3.13'.  Only handles >= and < forms
    that appear in this project's pyproject.toml.
    """
    lower: tuple[int, int] | None = None
    upper: tuple[int, int] | None = None
    for part in specifier.split(","):
        part = part.strip()
        m_ge = re.match(r">=\s*(\d+)\.(\d+)", part)
        m_lt = re.match(r"<\s*(\d+)\.(\d+)", part)
        if m_ge:
            lower = (int(m_ge.group(1)), int(m_ge.group(2)))
        elif m_lt:
            upper = (int(m_lt.group(1)), int(m_lt.group(2)))
    return lower, upper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_requires_python_has_upper_bound(project_root: Path) -> None:
    """requires-python must include an upper bound (<X.Y).

    An unbounded specifier lets uv resolve undeclared interpreters (e.g.
    free-threaded 3.14) which changes multiprocessing defaults and triggers
    GIL-re-enable warnings from optional deps.
    """
    text = _read_pyproject(project_root)
    specifier = _extract_requires_python(text)
    assert "<" in specifier, (
        f"requires-python={specifier!r} has no upper bound (<X.Y); "
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
    """.python-version pin must satisfy the requires-python lower and upper bounds."""
    text = _read_pyproject(project_root)
    specifier = _extract_requires_python(text)
    lower, upper = _parse_requires_python_bounds(specifier)

    # Fail loudly if the specifier uses a form that _parse_requires_python_bounds
    # does not recognise (e.g. >X.Y, <=X.Y, ==X.Y, ~=X.Y, patch-level versions).
    # Silently returning None and skipping the bound check gives false confidence
    # that the pin is within range when the parser is simply unaware of the form.
    assert lower is not None, (
        f"Could not parse a lower bound (>=X.Y) from requires-python={specifier!r}; "
        "update _parse_requires_python_bounds to handle this specifier form"
    )
    assert upper is not None, (
        f"Could not parse an upper bound (<X.Y) from requires-python={specifier!r}; "
        "update _parse_requires_python_bounds to handle this specifier form"
    )

    pv_file = project_root / ".python-version"
    assert pv_file.exists(), ".python-version missing (run test_python_version_file_exists first)"
    pin = _parse_version_pin(pv_file.read_text(encoding="utf-8"))

    assert pin >= lower, (
        f".python-version {pin} is below requires-python lower bound {lower}"
    )
    assert pin < upper, (
        f".python-version {pin} is not below requires-python upper bound {upper}"
    )


def test_python_version_listed_in_classifiers(project_root: Path) -> None:
    """.python-version minor version must appear as a Programming Language classifier."""
    text = _read_pyproject(project_root)
    classifiers = _extract_classifiers(text)

    pv_file = project_root / ".python-version"
    assert pv_file.exists(), ".python-version missing (run test_python_version_file_exists first)"
    major, minor = _parse_version_pin(pv_file.read_text(encoding="utf-8"))
    version_str = f"{major}.{minor}"

    matching = [c for c in classifiers if c.endswith(f":: {version_str}")]
    assert matching, (
        f"No 'Programming Language :: Python :: {version_str}' classifier found in "
        f"pyproject.toml; add it or adjust .python-version to a declared version. "
        f"Found classifiers: {classifiers}"
    )
