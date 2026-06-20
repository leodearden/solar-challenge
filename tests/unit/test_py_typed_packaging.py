# SPDX-License-Identifier: AGPL-3.0-or-later
"""PEP 561 packaging contract tests.

These tests encode the user-observable invariant that ships the
``py.typed`` marker in the built wheel:

A wheel built with ``uv build --wheel`` must contain the file
``solar_challenge/py.typed`` in its ZIP archive.

CI requirement: ``uv`` and the setuptools/wheel build-backend
dependencies must be available offline (build-backend dependencies
should be cached in the CI environment).
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest


class TestWheelShipsPyTyped:
    """A wheel built by ``uv build --wheel`` must contain solar_challenge/py.typed."""

    @pytest.mark.build
    def test_built_wheel_ships_py_typed(self, project_root: Path, tmp_path: Path) -> None:
        """Build a wheel and assert solar_challenge/py.typed is in the ZIP archive.

        Builds into a temp directory so the repo's dist/ is never polluted.
        NOT marked ``slow`` — that marker is reserved for real PVGIS network
        calls.  This must run in the default ``-m 'not slow and not e2e'``
        gate because it IS the deliverable signal (manifest §H6 T1-part).

        Marked ``build`` so it can be selected or excluded independently
        (e.g. ``pytest -m build`` or ``pytest -m 'not build'``).  It is NOT
        excluded from the default run — CI must guarantee that ``uv`` and
        cached build-backend dependencies (setuptools, wheel) are present so
        this test cannot network-fetch or fail due to a missing tool.
        """
        result = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"uv build --wheel failed (returncode={result.returncode}).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        wheels = sorted(tmp_path.glob("*.whl"))
        assert len(wheels) == 1, (
            f"Expected exactly one .whl file in {tmp_path}, got: {wheels}\n"
            f"uv stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        with zipfile.ZipFile(wheels[0]) as zf:
            names = zf.namelist()
        assert "solar_challenge/py.typed" in names, (
            "The built wheel does not contain solar_challenge/py.typed.\n"
            "Ensure src/solar_challenge/py.typed exists (empty file, PEP 561)\n"
            "and that pyproject.toml has:\n\n"
            "    [tool.setuptools.package-data]\n"
            '    solar_challenge = ["py.typed"]\n\n'
            f"Wheel members:\n" + "\n".join(f"  {n}" for n in sorted(names))
        )
