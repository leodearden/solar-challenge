# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each conftest a default run loads imports nothing from the web extra when it loads.

A run without the extra then skips each test module that needs it, through
pytest.importorskip, whereas an import error in a conftest aborts the whole run.
"""

from pathlib import Path

import pytest

from tests._blocked_imports import extra_modules, import_with_modules_blocked
from tests._repository_paths import REPOSITORY_ROOT


def _conftests_outside_the_e2e_suite() -> list[str]:
    """Return the module name of every conftest.py under tests/ but tests/e2e's.

    A default run never loads tests/e2e's, since tests/conftest.py's
    collect_ignore names its directory, and the lane's e2e job, which does,
    installs the web extra.
    """
    tests = REPOSITORY_ROOT / "tests"
    return sorted(
        ".".join(conftest.relative_to(REPOSITORY_ROOT).with_suffix("").parts)
        for conftest in tests.rglob("conftest.py")
        if not conftest.is_relative_to(tests / "e2e")
    )


@pytest.mark.parametrize("conftest", _conftests_outside_the_e2e_suite())
def test_importing_the_conftest_needs_no_web_extra(conftest: str, project_root: Path) -> None:
    result = import_with_modules_blocked(conftest, extra_modules(project_root, "web"), project_root)

    assert result.returncode == 0, f"{conftest} needs the web extra when it loads:\n{result.stderr}"
