# SPDX-License-Identifier: AGPL-3.0-or-later
"""External-consumer boundary tests (H1 + H6).

These tests prove that an EXTERNAL consumer can:
  - Install the solar_challenge wheel into a project-free environment (H6).
  - Import every symbol in the frozen public surface (solar_challenge.__all__)
    and have each one resolve and be callable/present (H1).
  - Confirm the wheel ships solar_challenge/py.typed (PEP 561).

The wheel is built once via a module-scoped fixture to avoid building twice.
The consumer-side proof runs inside an isolated uv env via _external_probe.py,
which is NOT collected by pytest (underscore-prefixed, matches _helpers.py).

Marked ``build`` (NOT ``slow``) so tests run in the default
``-m 'not slow and not e2e'`` gate while remaining independently selectable.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module-scoped shared fixture: build the wheel once for both tests.
# Cannot consume the function-scoped conftest project_root fixture — scope
# mismatch would error — so the project root is computed inline.
# Mirrors tests/unit/test_py_typed_packaging.py:42-58.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the solar_challenge wheel once and return its path.

    Builds into a temp directory so the repo's dist/ is never polluted.
    Uses tmp_path_factory (module-scoped) rather than tmp_path (function-scoped).
    The project root is computed as the grandparent of the tests/ directory.
    """
    project_root = Path(__file__).resolve().parents[2]
    out_dir = tmp_path_factory.mktemp("wheel_out")

    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"uv build --wheel failed (returncode={result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    wheels = sorted(out_dir.glob("*.whl"))
    assert len(wheels) == 1, (
        f"Expected exactly one .whl file in {out_dir}, got: {wheels}\n"
        f"uv stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    return wheels[0]


# ---------------------------------------------------------------------------
# H6: wheel ships py.typed (pairs with T1)
# ---------------------------------------------------------------------------


@pytest.mark.build
def test_built_wheel_is_typed(built_wheel: Path) -> None:
    """The built wheel ZIP archive must contain solar_challenge/py.typed (PEP 561 / H6).

    This pairs with T1 (task 77) which landed py.typed in the source tree and
    wired it into pyproject.toml's package-data.  This boundary test confirms
    the packaging contract survives the build step: an external consumer running
    ``pip install solar_challenge`` will get the py.typed marker and be able to
    enable ``--check-untyped-defs`` for this library.
    """
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()

    assert "solar_challenge/py.typed" in names, (
        "The built wheel does not contain solar_challenge/py.typed.\n"
        "Ensure src/solar_challenge/py.typed exists (empty file, PEP 561)\n"
        "and that pyproject.toml has:\n\n"
        "    [tool.setuptools.package-data]\n"
        '    solar_challenge = ["py.typed"]\n\n'
        f"Wheel members:\n" + "\n".join(f"  {n}" for n in sorted(names))
    )


# ---------------------------------------------------------------------------
# H1: every public symbol resolves and is callable/present in an isolated install
# ---------------------------------------------------------------------------


@pytest.mark.build
def test_isolated_install_resolves_and_calls_every_symbol(built_wheel: Path) -> None:
    """Install the wheel in a project-free env and resolve every __all__ symbol (H1).

    Runs tests/integration/_external_probe.py inside a ``uv run --no-project
    --isolated --with <wheel>`` environment.  The probe:
      - Asserts the package loaded from site-packages (not the worktree src/).
      - Iterates solar_challenge.__all__ and getattr-resolves each name.
      - Classifies: classes/routines → assert callable; else → assert not None.
      - Prints ``EXTERNAL-INSTALL-OK n/n`` and exits 0 on success.

    The test asserts returncode==0 AND the sentinel is in stdout.
    stdout+stderr are embedded in the failure message for debuggability.

    Design: ``--no-project --isolated`` gives a project-free ephemeral env
    (ignores the worktree's pyproject and venv); ``--with <wheel>`` installs
    the built wheel and resolves its declared deps from the uv cache.
    No ``--offline`` flag — cache-first-with-network-fallback is more robust.
    """
    project_root = Path(__file__).resolve().parents[2]
    probe_path = project_root / "tests" / "integration" / "_external_probe.py"

    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--isolated",
            "--with",
            str(built_wheel),
            "python",
            str(probe_path),
        ],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0 and "EXTERNAL-INSTALL-OK" in result.stdout, (
        f"External-consumer boundary test FAILED.\n"
        f"returncode: {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
