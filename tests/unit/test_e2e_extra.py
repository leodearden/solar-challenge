# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for pyproject.toml's e2e extra."""

from pathlib import Path

import pytest
from packaging.version import Version

from tests._pyproject import declared_floor, load_project_table


@pytest.mark.parametrize(
    ("first_capable_release", "capability"),
    [
        pytest.param(
            Version("1.44.0"),
            "adds expect(locator).to_have_accessible_name(), which tests/e2e asserts with. With an "
            "older Playwright that assertion does not exist, so the e2e test fails with an AttributeError",
            id="to-have-accessible-name",
        ),
        pytest.param(
            Version("1.51.0"),
            "adds the visible option of locator.filter(), which tests/e2e passes. An older "
            "Playwright's filter() takes no visible argument, so the e2e test fails with a TypeError",
            id="locator-filter-visible",
        ),
    ],
)
def test_e2e_extra_floor_excludes_playwright_lacking(
    project_root: Path, first_capable_release: Version, capability: str
) -> None:
    """An install of the e2e extra that ignores uv.lock, such as pip install ".[e2e]", may resolve
    any Playwright the floor admits, so the floor must exclude every release that lacks an API
    tests/e2e calls. A too-old install then fails in the resolver, naming the version, rather
    than inside an e2e test.
    """
    e2e = load_project_table(project_root)["optional-dependencies"]["e2e"]
    floor = declared_floor(e2e, "playwright")

    assert floor is not None and floor >= first_capable_release, (
        f"[project.optional-dependencies] e2e = {e2e!r}, which sets no playwright floor at or "
        f"above {first_capable_release}, the first Playwright that {capability}. "
        f"Declare playwright>={first_capable_release} in the e2e extra."
    )
