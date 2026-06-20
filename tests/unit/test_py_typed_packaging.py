# SPDX-License-Identifier: AGPL-3.0-or-later
"""PEP 561 packaging contract tests.

These tests encode the two machine-checkable invariants that ship the
``py.typed`` marker in the built wheel:

1. ``pyproject.toml`` declares a ``[tool.setuptools.package-data]`` table
   that includes ``py.typed`` for the ``solar_challenge`` package.
2. A wheel built with ``uv build --wheel`` actually contains the file
   ``solar_challenge/py.typed`` in its ZIP archive.

Parsing is text-based (regex) so it works under Python 3.10 where
``tomllib`` is unavailable, matching the style of
``tests/unit/test_project_metadata.py``.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_pyproject(project_root: Path) -> str:
    """Return the full text of pyproject.toml."""
    return (project_root / "pyproject.toml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPyprojectPackageDataStanza:
    """pyproject.toml must declare [tool.setuptools.package-data] for py.typed."""

    def test_pyproject_declares_py_typed_package_data(self, project_root: Path) -> None:
        """pyproject.toml must have a package-data entry shipping py.typed.

        Two sub-assertions:
        (a) A ``[tool.setuptools.package-data]`` table header is present.
        (b) Within/after it, a mapping ``solar_challenge = [...]`` whose
            list contains the ``py.typed`` token (flexible whitespace/quote
            style tolerated).

        If this test fails, add the following stanza to pyproject.toml
        adjacent to ``[tool.setuptools.packages.find]``::

            [tool.setuptools.package-data]
            solar_challenge = ["py.typed"]
        """
        text = _read_pyproject(project_root)

        # (a) Table header must exist
        assert re.search(r"\[tool\.setuptools\.package-data\]", text), (
            "Missing stanza in pyproject.toml — add:\n\n"
            "    [tool.setuptools.package-data]\n"
            '    solar_challenge = ["py.typed"]\n\n'
            "adjacent to [tool.setuptools.packages.find]."
        )

        # (b) solar_challenge list must contain "py.typed" (flexible spacing/quoting)
        pattern = r'solar_challenge\s*=\s*\[[^\]]*["\']py\.typed["\'][^\]]*\]'
        assert re.search(pattern, text), (
            "The [tool.setuptools.package-data] table does not map "
            'solar_challenge to a list containing "py.typed". '
            "Expected a line like:\n\n"
            '    solar_challenge = ["py.typed"]\n\n'
            f"Full pyproject.toml text:\n{text}"
        )


class TestWheelShipsPyTyped:
    """A wheel built by ``uv build --wheel`` must contain solar_challenge/py.typed."""

    def test_built_wheel_ships_py_typed(self, project_root: Path, tmp_path: Path) -> None:
        """Build a wheel and assert solar_challenge/py.typed is in the ZIP archive.

        Builds into a temp directory so the repo's dist/ is never polluted.
        NOT marked ``slow`` — that marker is reserved for real PVGIS network
        calls.  This must run in the default ``-m 'not slow and not e2e'``
        gate because it IS the deliverable signal (manifest §H6 T1-part).
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
