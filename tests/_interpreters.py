# SPDX-License-Identifier: AGPL-3.0-or-later
"""The interpreter-support claims: the Python minors requires-python admits and the .python-version pin."""

from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from tests._pyproject import load_project_table


def requires_python(project_root: Path) -> SpecifierSet:
    """Return pyproject.toml's requires-python as a PEP 440 specifier set."""
    return SpecifierSet(load_project_table(project_root)["requires-python"])


def admitted_minor_versions(requires_python: SpecifierSet) -> set[tuple[int, int]]:
    """Return the Python 3 minor versions, searched from 3.0 to 3.99, that *requires_python* admits."""
    return {(3, minor) for minor in range(100) if requires_python.contains(f"3.{minor}")}


def python_version_pin(project_root: Path) -> Version:
    """Return the interpreter version pinned by .python-version."""
    pv_file = project_root / ".python-version"
    assert pv_file.exists(), f".python-version missing at {pv_file}"
    return Version(pv_file.read_text(encoding="utf-8").strip())
