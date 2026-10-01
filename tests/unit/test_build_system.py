# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for pyproject.toml's [build-system] table."""

from pathlib import Path

import pytest
from packaging.version import Version

from tests._pyproject import declared_floor, load_pyproject


@pytest.mark.parametrize(
    ("first_capable_release", "capability"),
    [
        pytest.param(
            Version("62.3.0"),
            "expands the `**` globs in [tool.setuptools.package-data] through nested directories. "
            "An older setuptools reads `**` as a single directory level, so its wheel silently "
            "lacks the dashboard's top-level and deeply nested files",
            id="recursive-package-data-globs",
        ),
        pytest.param(
            Version("77.0.0"),
            "accepts [project] license as an SPDX expression string (PEP 639). An older "
            "setuptools accepts only the TOML-table form, so it rejects pyproject.toml and the "
            "build fails",
            id="spdx-license-expression",
        ),
    ],
)
def test_build_system_floor_excludes_setuptools_lacking(
    project_root: Path, first_capable_release: Version, capability: str
) -> None:
    """A resolver may pick any setuptools the floor admits (a build constraint, an offline cache,
    a distro's packaged setuptools), so the floor must exclude every release that lacks a
    capability pyproject.toml relies on.
    """
    requires = load_pyproject(project_root)["build-system"]["requires"]
    floor = declared_floor(requires, "setuptools")

    assert floor is not None and floor >= first_capable_release, (
        f"[build-system] requires {requires!r}, which sets no setuptools floor at or above "
        f"{first_capable_release}, the first setuptools that {capability}. "
        f"Declare a setuptools>={first_capable_release} floor."
    )
