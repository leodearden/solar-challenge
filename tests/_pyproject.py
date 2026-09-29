# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to pyproject.toml for the packaging-metadata contract tests.

Usage::

    from tests._pyproject import load_project_table, load_pyproject

    requires_python = load_project_table(project_root)["requires-python"]
    mypy_target = load_pyproject(project_root)["tool"]["mypy"]["python_version"]
"""

import tomllib
from pathlib import Path
from typing import Any


def load_pyproject(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s whole pyproject.toml, parsed as TOML."""
    return tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))


def load_project_table(project_root: Path) -> dict[str, Any]:
    """Return the [project] table of *project_root*'s pyproject.toml, parsed as TOML."""
    project: dict[str, Any] = load_pyproject(project_root)["project"]
    return project
