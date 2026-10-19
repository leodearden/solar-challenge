# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for pyproject.toml's dev extra."""

from pathlib import Path

import pytest
from packaging.version import Version

from tests._pyproject import declared_floor, load_project_table


@pytest.mark.parametrize(
    ("distribution", "first_capable_release", "capability"),
    [
        pytest.param(
            "mypy",
            Version("1.4.0"),
            "gives an unused `# type: ignore` the error code unused-ignore, which "
            "tests/unit/test_surface_forms_type_check.py's probe of an unused ignore asserts. An older mypy "
            "reports that line with no error code, so the probe fails",
            id="unused-ignore-error-code",
        ),
        pytest.param(
            "mypy",
            Version("1.11.0"),
            "accepts a type alias to a PEP 604 union as isinstance's second argument, as tests/_surface_forms.py "
            "passes _TypeVariable. An older mypy reports `Parameterized generics cannot be used with class or "
            "instance checks` there, so tests/unit/test_surface_forms_type_check.py's check of the helper fails",
            id="isinstance-union-alias",
        ),
    ],
)
def test_dev_extra_floor_excludes_releases_lacking(
    project_root: Path, distribution: str, first_capable_release: Version, capability: str
) -> None:
    """An install of the dev extra that ignores uv.lock, such as pip install -e ".[dev]", may resolve
    any release of a distribution the extra requires that its floor admits, so each floor must
    exclude every release that lacks a capability the test suite relies on. A too-old install then
    fails in the resolver, naming the version, rather than inside a test.
    """
    dev = load_project_table(project_root)["optional-dependencies"]["dev"]
    floor = declared_floor(dev, distribution)

    assert floor is not None and floor >= first_capable_release, (
        f"[project.optional-dependencies] dev = {dev!r}, which sets no {distribution} floor at or "
        f"above {first_capable_release}, the first {distribution} release that {capability}. "
        f"Declare {distribution}>={first_capable_release} in the dev extra."
    )
