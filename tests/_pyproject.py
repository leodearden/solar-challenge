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
    """Return the >= bound that the PEP 508 *requirements* place on *distribution* wherever it is required, or None.

    Distribution names compare canonically, so "Setuptools>=77.0.0" bounds setuptools.

    Environment markers are not evaluated. Unmarked requirements apply in every environment, so when any exist the
    floor is the highest bound among them. Otherwise at least one marked requirement applies wherever *distribution*
    is required, so the floor is the lowest of their bounds, or None if any of them has none.
    """
    wanted = canonicalize_name(distribution)
    naming = [
        requirement
        for requirement in map(Requirement, requirements)
        if canonicalize_name(requirement.name) == wanted
    ]
    unmarked = [requirement for requirement in naming if requirement.marker is None]
    return _floor_when_all_apply(unmarked) if unmarked else _floor_when_any_applies(naming)


def _floor_when_all_apply(requirements: Iterable[Requirement]) -> Version | None:
    lower_bounds = [
        Version(clause.version)
        for requirement in requirements
        for clause in requirement.specifier
        if clause.operator == ">="
    ]
    return max(lower_bounds, default=None)


def _floor_when_any_applies(requirements: Iterable[Requirement]) -> Version | None:
    own_floors = [_floor_when_all_apply([requirement]) for requirement in requirements]
    bounded_floors = [floor for floor in own_floors if floor is not None]
    every_requirement_is_bounded = len(bounded_floors) == len(own_floors)
    return min(bounded_floors, default=None) if every_requirement_is_bounded else None
