# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run Python source, or import a module, in a fresh interpreter whose sys.modules blocks given modules, for the tests that pin which modules something needs when it loads or runs.

A blocked module is None in that interpreter's sys.modules, so importing it, or any module under it, raises
ImportError whether or not it is installed. extra_modules names the installed modules of one of pyproject.toml's
extras, the ones to block.

Usage::

    from tests._blocked_imports import extra_modules, import_with_modules_blocked, run_with_modules_blocked

    result = import_with_modules_blocked("tests.unit.conftest", extra_modules(project_root, "web"), project_root)
    assert result.returncode == 0, result.stderr

    run_pytest = "import sys, pytest; raise SystemExit(pytest.main(sys.argv[1:]))"
    result = run_with_modules_blocked(run_pytest, ["--fixtures", __file__], ["pandas"], project_root, timeout=120)
    assert result.returncode == 0, result.stderr
"""

import subprocess
import sys
from collections.abc import Iterable, Sequence
from importlib.metadata import packages_distributions
from pathlib import Path

from packaging.utils import canonicalize_name

from tests._pyproject import extra_requirements

_RUN_WITH_MODULES_BLOCKED = """\
import sys

source, *rest = sys.argv[1:]
separator = rest.index("--")
for name in rest[:separator]:
    sys.modules[name] = None
sys.argv[1:] = rest[separator + 1 :]
main = type(sys)("__main__")
sys.modules["__main__"] = main
exec(source, vars(main))
"""

_IMPORT_MODULE = """\
import importlib
import sys

importlib.import_module(sys.argv[1])
"""


def extra_modules(project_root: Path, extra: str) -> list[str]:
    """Return, sorted, the installed top-level modules of the distributions that *project_root*'s pyproject.toml's *extra* requires."""
    required = {canonicalize_name(requirement.name) for requirement in extra_requirements(project_root, [extra])}
    return sorted(
        module
        for module, distributions in packages_distributions().items()
        if any(canonicalize_name(distribution) in required for distribution in distributions)
    )


def run_with_modules_blocked(
    source: str, args: Sequence[str], blocked: Iterable[str], cwd: Path, *, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run *source* as `python -c` would with *args*, in a fresh interpreter run in *cwd*, with each module of *blocked* None in its sys.modules before the source runs; return the finished process."""
    return subprocess.run(
        [sys.executable, "-c", _RUN_WITH_MODULES_BLOCKED, source, *blocked, "--", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def import_with_modules_blocked(module: str, blocked: Iterable[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Import *module* in a fresh interpreter run in *cwd*, with each module of *blocked* None in its sys.modules; return the finished process."""
    return run_with_modules_blocked(_IMPORT_MODULE, [module], blocked, cwd, timeout=60)
