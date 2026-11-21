# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import a module in a fresh interpreter whose sys.modules blocks given modules, for the tests that pin which extras a module needs when it loads.

A blocked module is None in that interpreter's sys.modules, so importing it, or any module under it, raises
ImportError whether or not it is installed. extra_modules names the installed modules of one of pyproject.toml's
extras, the ones to block.

Usage::

    from tests._blocked_imports import extra_modules, import_with_modules_blocked

    result = import_with_modules_blocked("tests.unit.conftest", extra_modules(project_root, "web"), project_root)
    assert result.returncode == 0, result.stderr
"""

import subprocess
import sys
from collections.abc import Iterable
from importlib.metadata import packages_distributions
from pathlib import Path

from packaging.utils import canonicalize_name

from tests._pyproject import extra_requirements

_IMPORT_WITH_MODULES_BLOCKED = """\
import importlib
import sys

module, *blocked = sys.argv[1:]
for name in blocked:
    sys.modules[name] = None
importlib.import_module(module)
"""


def extra_modules(project_root: Path, extra: str) -> list[str]:
    """Return, sorted, the installed top-level modules of the distributions that *project_root*'s pyproject.toml's *extra* requires."""
    required = {canonicalize_name(requirement.name) for requirement in extra_requirements(project_root, [extra])}
    return sorted(
        module
        for module, distributions in packages_distributions().items()
        if any(canonicalize_name(distribution) in required for distribution in distributions)
    )


def import_with_modules_blocked(module: str, blocked: Iterable[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Import *module* in a fresh interpreter run in *cwd*, with each module of *blocked* None in its sys.modules; return the finished process."""
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_WITH_MODULES_BLOCKED, module, *blocked],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
