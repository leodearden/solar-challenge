# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for pyproject.toml's [build-system] table."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from tests._pyproject import load_pyproject

_FIRST_SETUPTOOLS_WITH_RECURSIVE_PACKAGE_DATA_GLOBS = Version("62.3.0")


def test_build_system_requires_a_setuptools_whose_package_data_globs_recurse(
    project_root: Path,
) -> None:
    """[tool.setuptools.package-data] ships the dashboard's folders through `**` globs, so the
    build-system floor must admit only a setuptools that expands `**` through nested directories.
    """
    requires = load_pyproject(project_root)["build-system"]["requires"]
    build_requirements = {
        canonicalize_name(requirement.name): requirement
        for requirement in map(Requirement, requires)
    }
    assert "setuptools" in build_requirements, (
        f"[build-system] requires {requires!r}, which has no setuptools entry to carry the "
        f"setuptools>={_FIRST_SETUPTOOLS_WITH_RECURSIVE_PACKAGE_DATA_GLOBS} floor that the `**` "
        "globs in [tool.setuptools.package-data] need."
    )
    setuptools = build_requirements["setuptools"]
    floors = [Version(clause.version) for clause in setuptools.specifier if clause.operator == ">="]

    assert floors and max(floors) >= _FIRST_SETUPTOOLS_WITH_RECURSIVE_PACKAGE_DATA_GLOBS, (
        f"[build-system] requires {str(setuptools)!r}, which admits a setuptools older than "
        f"{_FIRST_SETUPTOOLS_WITH_RECURSIVE_PACKAGE_DATA_GLOBS}. An older setuptools reads `**` as "
        "a single directory level, so its wheel silently lacks the dashboard's top-level and "
        "deeply nested files. Declare a "
        f"setuptools>={_FIRST_SETUPTOOLS_WITH_RECURSIVE_PACKAGE_DATA_GLOBS} floor."
    )
