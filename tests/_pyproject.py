# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to pyproject.toml for the packaging-metadata contract tests.

Usage::

    from tests._pyproject import load_project_table

    requires_python = load_project_table(project_root)["requires-python"]
"""

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def load_project_table(project_root: Path) -> dict[str, Any]:
    """Return the [project] table of *project_root*'s pyproject.toml, parsed as TOML."""
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    project: dict[str, Any] = pyproject["project"]
    return project
