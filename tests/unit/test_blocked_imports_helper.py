# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_blocked_imports.py, which imports a module in a fresh interpreter whose sys.modules blocks given modules.

Each import names a standard-library module, which every interpreter has installed, so a refusal comes from the block alone.
"""

from pathlib import Path

import pytest

from tests._blocked_imports import extra_modules, import_with_modules_blocked


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


def test_extra_modules_are_the_installed_top_level_modules_of_the_distributions_the_extra_requires(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\n"
        'probe = ["packaging>=20", "not-an-installed-distribution>=1"]\n',
        encoding="utf-8",
    )

    assert extra_modules(tmp_path, "probe") == ["packaging"]
