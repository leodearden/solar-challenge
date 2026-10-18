# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for pyproject.toml's e2e extra."""

from pathlib import Path

import pytest
from packaging.version import Version

from tests._pyproject import declared_floor, load_project_table


@pytest.mark.parametrize(
    ("distribution", "first_capable_release", "capability"),
    [
        pytest.param(
            "playwright",
            Version("1.44.0"),
            "adds expect(locator).to_have_accessible_name(), which tests/e2e asserts with. With an "
            "older Playwright that assertion does not exist, so the e2e test fails with an AttributeError",
            id="to-have-accessible-name",
        ),
        pytest.param(
            "playwright",
            Version("1.51.0"),
            "adds the visible option of locator.filter(), which tests/e2e passes. An older "
            "Playwright's filter() takes no visible argument, so the e2e test fails with a TypeError",
            id="locator-filter-visible",
        ),
        pytest.param(
            "pytest-playwright",
            Version("0.5.0"),
            "adds the new_context fixture, which tests/e2e requests to open a page with JavaScript off. With an "
            "older pytest-playwright pytest finds no fixture of that name, so the e2e test errors at setup",
            id="new-context-fixture",
        ),
        pytest.param(
            "pytest-playwright",
            Version("0.6.0"),
            "exports CreateContextCallback, the type of the new_context fixture, from its package, which tests/e2e "
            "imports with `from pytest_playwright import CreateContextCallback`. With an older pytest-playwright that "
            "import raises an ImportError, so pytest cannot collect the e2e module and every test in it errors",
            id="create-context-callback-import",
        ),
    ],
)
def test_e2e_extra_floor_excludes_releases_lacking(
    project_root: Path, distribution: str, first_capable_release: Version, capability: str
) -> None:
    """An install of the e2e extra that ignores uv.lock, such as pip install ".[e2e]", may resolve
    any release of a distribution the extra requires that its floor admits, so each floor must
    exclude every release that lacks an API tests/e2e uses. A too-old install then fails in the
    resolver, naming the version, rather than inside an e2e test.
    """
    e2e = load_project_table(project_root)["optional-dependencies"]["e2e"]
    floor = declared_floor(e2e, distribution)

    assert floor is not None and floor >= first_capable_release, (
        f"[project.optional-dependencies] e2e = {e2e!r}, which sets no {distribution} floor at or "
        f"above {first_capable_release}, the first {distribution} release that {capability}. "
        f"Declare {distribution}>={first_capable_release} in the e2e extra."
    )
