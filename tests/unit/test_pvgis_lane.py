# SPDX-License-Identifier: AGPL-3.0-or-later
"""PVGIS lane contract tests.

tests/integration/test_pvgis.py checks PVGIS's TMY response as PvgisTmy
returns it. The per-task verify never runs it, because its tests are slow.
The orchestrator offline lane's pvgis job runs it after every merge instead,
so a change in PVGIS's or pvlib's response files a fix task rather than going
unseen. That holds only while each of its tests checks PVGIS itself, never a
cached copy. The job also declares an outage probe, so that an outage of PVGIS
is escalated rather than filed, which holds only while the probe reports PVGIS
out of reach as an outage. The contracts the pvgis job shares with every lane
job are checked in tests/unit/test_offline_lane_contracts.py.
"""

import os
from pathlib import Path

import pandas as pd
import pvlib
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import CACHE_DIR_VARIABLE, DEFAULT_CACHE_DIR, TMY_HOURS, WeatherCache
from tests._collect_only import requires_uv
from tests._command_runner import describe_outcome, run_command
from tests._orchestrator_config import lane_command, lane_outage_probe
from tests._uv_env import SharedUvEnvironments

_PVGIS_CONTRACT_TESTS = "tests/integration/test_pvgis.py"
_DEAD_PROXY = "http://127.0.0.1:9"


def _clear_sky_tmy(location: Location) -> pd.DataFrame:
    """A TMY-shaped clear-sky year at *location*: TMY_HOURS hourly UTC rows with consistent ghi, dni and dhi."""
    hours = pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC")
    clear_sky = pvlib.location.Location(location.latitude, location.longitude).get_clearsky(
        hours, linke_turbidity=3.0
    )
    return clear_sky.assign(temp_air=10.0, wind_speed=2.0)


def _put_pvgis_behind_the_dead_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send the HTTP(S) requests of every child process the test starts to _DEAD_PROXY, PVGIS's included.

    It deliberately replaces the proxy the offline guard sets for child processes: a child's PVGIS requests are
    expected, so they must fail at the dead proxy instead of counting against the test.
    """
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, _DEAD_PROXY)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def test_no_pvgis_contract_test_passes_on_a_cached_tmy_while_pvgis_is_out_of_reach(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    """With PVGIS out of reach, no PVGIS contract test passes, though the working directory caches a clear-sky Bristol year.

    That year passes the module's shape and physics checks, so a test that read
    the cache instead of PVGIS would pass on it, checking a copy rather than
    PVGIS's current response.
    """
    bristol = Location.bristol()
    WeatherCache(cache_dir=pytester.path / DEFAULT_CACHE_DIR).put(_clear_sky_tmy(bristol), "tmy", bristol)
    _put_pvgis_behind_the_dead_proxy(monkeypatch)
    # The lane's pvgis job names no weather cache directory, and a test that read a cache would read the one above.
    monkeypatch.delenv(CACHE_DIR_VARIABLE, raising=False)

    result = pytester.runpytest_subprocess(
        project_root / _PVGIS_CONTRACT_TESTS, "-p", "no:cacheprovider", timeout=120
    )

    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == 0 and outcomes.get("failed", 0) + outcomes.get("errors", 0) > 0, (
        f"with PVGIS behind a dead proxy, the PVGIS contract tests ended {outcomes}. A test that passes either "
        "checked the TMY cached in its working directory, not PVGIS's current response: fetch it with "
        "PvgisTmy(None).get(...), as test_pvgis.py's bristol_tmy fixture does. Or it reached PVGIS "
        "around the dead proxy, because requests no longer honours HTTP(S)_PROXY, and this probe needs "
        "another way to keep PVGIS out of reach\n"
        f"stdout tail:\n{result.stdout.str()[-5000:]}"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_with_pvgis_out_of_reach_the_pvgis_jobs_outage_probe_reports_a_pvgis_outage(
    monkeypatch: pytest.MonkeyPatch, project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    """Run as the lane runs it after a red pass, the pvgis job's outage probe reports PVGIS as the dependency that is not usable.

    It runs in the uv environment of the job's command, which the job's red run has synced when the lane runs the probe.
    """
    _put_pvgis_behind_the_dead_proxy(monkeypatch)
    probe = lane_outage_probe(project_root, "pvgis")
    environment = shared_uv_probe_environments.for_command(lane_command(project_root, "pvgis").command)

    result = run_command(probe, environment, timeout_secs=300)

    assert result.returncode == os.EX_TEMPFAIL and result.stdout.startswith("PVGIS: "), (
        f"with PVGIS behind a dead proxy, the {probe.label}, {probe.command!r}, reported no PVGIS outage, so every "
        "PVGIS outage that outlasts a run and its confirm re-run files a fix task instead of one escalation the lane "
        f"closes itself\n{describe_outcome(result)}"
    )
