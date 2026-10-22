# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each conftest a default run loads imports nothing from the web extra when it loads.

A run without the extra then skips each test module that needs it, through
pytest.importorskip, whereas an import error in a conftest aborts the whole run.
"""

import subprocess
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._pyproject import load_project_table

_IMPORT_WITH_MODULES_BLOCKED = """\
import importlib
import sys

module, *blocked = sys.argv[1:]
for name in blocked:
    sys.modules[name] = None
importlib.import_module(module)
"""


def _web_extra_modules(project_root: Path) -> list[str]:
    """Return the installed top-level modules of the distributions that pyproject.toml's web extra requires."""
    web_extra = {
        canonicalize_name(Requirement(specifier).name)
        for specifier in load_project_table(project_root)["optional-dependencies"]["web"]
    }
    return sorted(
        module
        for module, distributions in packages_distributions().items()
        if any(canonicalize_name(distribution) in web_extra for distribution in distributions)
    )


def _conftests_outside_the_e2e_suite() -> list[str]:
    """Return the module name of every conftest.py under tests/ but tests/e2e's.

    A default run never loads tests/e2e's, since tests/conftest.py's
    collect_ignore names its directory, and the lane's e2e job, which does,
    installs the web extra.
    """
    tests = Path(__file__).resolve().parents[1]
    return sorted(
        ".".join(conftest.relative_to(tests.parent).with_suffix("").parts)
        for conftest in tests.rglob("conftest.py")
        if not conftest.is_relative_to(tests / "e2e")
    )


@pytest.mark.parametrize("conftest", _conftests_outside_the_e2e_suite())
def test_importing_the_conftest_needs_no_web_extra(conftest: str, project_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_WITH_MODULES_BLOCKED, conftest, *_web_extra_modules(project_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, f"{conftest} needs the web extra when it loads:\n{result.stderr}"
