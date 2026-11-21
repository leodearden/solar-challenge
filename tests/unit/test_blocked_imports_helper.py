# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_blocked_imports.py, which runs Python source, or imports a module, in a fresh interpreter whose sys.modules blocks given modules.

Each import names a standard-library module, which every interpreter has installed, so a refusal comes from the block alone.
"""

from pathlib import Path

import pytest

from tests._blocked_imports import extra_modules, import_with_modules_blocked, run_with_modules_blocked

_BLOCKED_TOGETHER = ("json", "email")


@pytest.mark.parametrize(
    ("module", "blocked", "refusal"),
    [
        pytest.param(
            "json", ["json"], "ModuleNotFoundError: import of json halted; None in sys.modules", id="the-blocked-module"
        ),
        pytest.param(
            "email.message",
            ["email"],
            "ModuleNotFoundError: No module named 'email.message'; 'email' is not a package",
            id="a-module-under-a-blocked-package",
        ),
    ],
)
def test_importing_a_blocked_module_or_a_module_under_it_fails(
    module: str, blocked: list[str], refusal: str, project_root: Path
) -> None:
    result = import_with_modules_blocked(module, blocked, project_root)

    assert result.returncode != 0 and refusal in result.stderr, (
        f"importing {module} with {blocked} blocked exited {result.returncode}:\n{result.stderr}"
    )


def test_importing_a_module_with_nothing_blocked_succeeds(project_root: Path) -> None:
    result = import_with_modules_blocked("json", [], project_root)

    assert result.returncode == 0, f"importing json with nothing blocked exited {result.returncode}:\n{result.stderr}"


def test_the_source_runs_with_the_args_as_its_sys_argv_after_the_program_name(project_root: Path) -> None:
    result = run_with_modules_blocked(
        "import sys; print(sys.argv[1:])", ["a", "--", "b"], ["json"], project_root, timeout=60
    )

    assert result.returncode == 0 and result.stdout == "['a', '--', 'b']\n", (
        f"printing sys.argv[1:] with args ['a', '--', 'b'] and json blocked exited {result.returncode} "
        f"and printed {result.stdout!r}:\n{result.stderr}"
    )


@pytest.mark.parametrize("module", _BLOCKED_TOGETHER)
def test_the_source_cannot_import_any_blocked_module(module: str, project_root: Path) -> None:
    refusal = f"ModuleNotFoundError: import of {module} halted; None in sys.modules"

    result = run_with_modules_blocked(f"import {module}", [], _BLOCKED_TOGETHER, project_root, timeout=60)

    assert result.returncode != 0 and refusal in result.stderr, (
        f"running `import {module}` with {' and '.join(_BLOCKED_TOGETHER)} blocked exited {result.returncode}:\n"
        f"{result.stderr}"
    )


def test_the_process_exits_with_the_status_the_source_raises(project_root: Path) -> None:
    result = run_with_modules_blocked("raise SystemExit(3)", [], [], project_root, timeout=60)

    assert result.returncode == 3, (
        f"running `raise SystemExit(3)` with nothing blocked exited {result.returncode}:\n{result.stderr}"
    )


def test_extra_modules_are_the_installed_top_level_modules_of_the_distributions_the_extra_requires(
    tmp_path: Path,
) -> None:
    """PyYAML is a core dependency, so every environment has it; its modules, yaml and _yaml, are not named like it, and the probe spells it neither as its metadata does (PyYAML) nor canonically (pyyaml), so the match needs both canonicalize_name calls."""
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\n"
        'probe = ["PYYAML>=6", "packaging>=20", "not-an-installed-distribution>=1"]\n',
        encoding="utf-8",
    )

    assert extra_modules(tmp_path, "probe") == ["_yaml", "packaging", "yaml"]
