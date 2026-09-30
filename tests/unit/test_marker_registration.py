"""Guard tests for pytest marker registration and slow-marker selection.

These tests enforce that:
1. The ``integration`` marker is registered in pyproject.toml.
2. All network-touching integration test classes are deselected under
   ``-m 'not slow'``.
3. Specific network-touching unit-test classes are also deselected under
   ``-m 'not slow'``, while pure-logic unit-test classes remain selected.

All assertions run pytest in a subprocess so they reflect the *effective*
pytest configuration, not just TOML parsing.  These tests must NOT be marked
``slow`` themselves — they must always run in the fast offline loop.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Repo root is three levels up from tests/unit/this_file.py
REPO_ROOT = Path(__file__).resolve().parents[2]

INTEGRATION_FILES = [
    "tests/integration/test_pvgis.py",
    "tests/integration/test_home_simulation.py",
    "tests/integration/test_fleet_simulation.py",
    "tests/integration/test_dispatch_strategies.py",
    "tests/integration/test_tou_dispatch.py",
    "tests/integration/test_tariff_integration.py",
    "tests/integration/test_ev_fleet.py",
]


class TestMarkerRegistration:
    """Verify that required pytest markers are registered."""

    def test_integration_marker_is_registered(self):
        """``integration`` marker must be registered in pyproject.toml."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--markers"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        # ``pytest --markers`` always exits 0; just read the output.
        output = result.stdout
        assert "@pytest.mark.integration" in output, (
            "The 'integration' marker is not registered. "
            "Add it to [tool.pytest.ini_options].markers in pyproject.toml. "
            f"Full markers output:\n{output}"
        )

    def test_slow_marker_is_registered(self):
        """``slow`` marker must be registered (sanity anchor)."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--markers"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout
        assert "@pytest.mark.slow" in output, (
            "The 'slow' marker is not registered — something has gone wrong "
            f"with the baseline pyproject.toml. Full output:\n{output}"
        )


class TestIntegrationSuiteExcludedUnderNotSlow:
    """Verify that all integration test classes are deselected by ``-m 'not slow'``."""

    def test_integration_suite_excluded_under_not_slow(self):
        """No integration test should be collected under ``-m 'not slow'``.

        This check is intentionally dynamic — it does not enumerate class names.
        Instead it verifies that the unfiltered collection finds *something*
        (positive control that imports work and tests exist), then asserts that
        the ``not slow`` filtered collection finds nothing (exit code 5).
        This prevents a vacuous pass when a collection error silently empties
        the output, and avoids a hand-maintained allowlist that would miss a
        newly added network-touching class.
        """
        # Positive control: collect WITHOUT filter — must succeed and find tests.
        baseline = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                *INTEGRATION_FILES,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert baseline.returncode == 0, (
            "Unfiltered collection of integration files failed — check for "
            f"import errors.\nstdout:\n{baseline.stdout}\nstderr:\n{baseline.stderr}"
        )
        # The baseline must actually find some tests; if it found none, the
        # positive control is vacuous and something is wrong with the file list.
        assert "no tests ran" not in baseline.stdout.lower(), (
            "Unfiltered collection found no tests in integration files — "
            "check that INTEGRATION_FILES is correct."
        )

        # Filtered run: collect WITH ``-m 'not slow'`` — should find nothing.
        # pytest exit code 5 means "no tests collected", which is the expected
        # outcome once every integration class is marked slow.
        filtered = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-m",
                "not slow",
                *INTEGRATION_FILES,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert filtered.returncode == 5, (
            "Expected exit code 5 (no tests collected) under ``-m 'not slow'`` "
            f"but got {filtered.returncode}. One or more integration test "
            "classes is missing the ``@pytest.mark.slow`` decorator.\n"
            f"stdout:\n{filtered.stdout}\nstderr:\n{filtered.stderr}"
        )


class TestNetworkedUnitClassesExcludedButPureKept:
    """Verify selective ``slow`` marking in the home and fleet unit tests.

    NOTE — hand-maintained allowlists: UNIT_TEST_FILES, NETWORKED_UNIT_CLASSES and
    PURE_UNIT_CLASSES are enumerated here rather than derived dynamically because
    test_home_heat_pump.py and test_fleet.py mix slow and fast classes in the same
    file, so a whole-file "count must be zero" assertion is not possible.  The
    trade-off is that a newly added network-touching class that lacks
    ``@pytest.mark.slow`` will NOT be detected unless someone also adds it to
    NETWORKED_UNIT_CLASSES.  Reviewers adding new simulation-driven test classes to
    these files should update the list below to keep the guard effective.  Anyone
    moving a listed class to another module must add that module to UNIT_TEST_FILES,
    because a NETWORKED class outside those files passes its check vacuously.
    """

    # The modules that define every class named in the two lists below.
    UNIT_TEST_FILES = [
        "tests/unit/test_home.py",
        "tests/unit/test_home_heat_pump.py",
        "tests/unit/test_fleet.py",
    ]

    # Network-touching classes in the unit suite — must be deselected.
    NETWORKED_UNIT_CLASSES = [
        "TestHeatPumpIntegration",
        "TestSimulateFleetIter",
        "TestParallelMatchesSequential",
        "TestSimulateHomeWeatherData",
        "TestMultiSweepIter",
        "TestCollectMultiSweepResults",
    ]

    # Pure-logic classes — must remain selected (guard against over-marking).
    PURE_UNIT_CLASSES = [
        "TestCalculateSummary",  # test_home.py
        "TestHeatPumpConfig",    # test_home_heat_pump.py — pure config construction, no network
        "TestFleetSummary",      # test_fleet.py
    ]

    def test_networked_unit_classes_excluded_but_pure_kept(self):
        """Networked unit classes deselected; pure-logic classes still collected."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-m",
                "not slow",
                *self.UNIT_TEST_FILES,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Collecting {self.UNIT_TEST_FILES} under ``-m 'not slow'`` failed with exit "
            f"code {result.returncode}, so the class checks below would be vacuous.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        output = result.stdout

        # Network-touching classes must be DESELECTED.
        for class_name in self.NETWORKED_UNIT_CLASSES:
            assert class_name not in output, (
                f"Networked unit class {class_name!r} was still collected under "
                "``-m 'not slow'`` — add ``@pytest.mark.slow`` to that class."
            )

        # Pure-logic classes must still be COLLECTED.
        for class_name in self.PURE_UNIT_CLASSES:
            assert class_name in output, (
                f"Pure unit class {class_name!r} was NOT collected under "
                "``-m 'not slow'`` — do NOT mark it slow."
            )
