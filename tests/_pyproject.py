# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to pyproject.toml for the packaging-metadata contract tests.

Usage::

    from tests._pyproject import declared_floor, load_project_table, load_pyproject

    requires_python = load_project_table(project_root)["requires-python"]
    mypy_target = load_pyproject(project_root)["tool"]["mypy"]["python_version"]
    setuptools_floor = declared_floor(load_pyproject(project_root)["build-system"]["requires"], "setuptools")
"""

import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def load_pyproject(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s whole pyproject.toml, parsed as TOML."""
    return tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))


def load_project_table(project_root: Path) -> dict[str, Any]:
    """Return the [project] table of *project_root*'s pyproject.toml, parsed as TOML."""
    project: dict[str, Any] = load_pyproject(project_root)["project"]
    return project


def declared_floor(requirements: Iterable[str], distribution: str) -> Version | None:
    """Return the highest >= bound that the PEP 508 *requirements* place on *distribution*, or None if they place none.

    Distribution names compare canonically, so "Setuptools>=77.0.0" bounds setuptools.
    """
    wanted = canonicalize_name(distribution)
    floors = [
        Version(clause.version)
        for requirement in map(Requirement, requirements)
        if canonicalize_name(requirement.name) == wanted
        for clause in requirement.specifier
        if clause.operator == ">="
    ]
    return max(floors, default=None)
