# SPDX-License-Identifier: AGPL-3.0-or-later
"""PVGIS lane contract tests.

tests/integration/test_pvgis.py checks PVGIS's TMY response as get_tmy_data
returns it. The per-task verify never runs it, because its tests are slow.
The orchestrator offline lane's pvgis job runs it after every merge instead,
so a change in PVGIS's or pvlib's response files a fix task rather than going
unseen. That holds only while each of its tests checks PVGIS itself, never a
cached copy.
"""

from pathlib import Path

import pandas as pd
import pvlib
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import DEFAULT_CACHE_DIR, TMY_HOURS, WeatherCache
from tests._collect_only import requires_uv
from tests._lane_collection import collect_lane_job
from tests._orchestrator_config import lane_job_enabled, sole_offline_lane_job

_PVGIS_JOB = "pvgis"
_PVGIS_CONTRACT_TESTS = "tests/integration/test_pvgis.py"
_DEAD_PROXY = "http://127.0.0.1:9"


def test_offline_lane_runs_one_enabled_pvgis_job(project_root: Path) -> None:
    """The offline lane runs exactly one pvgis job, and it is enabled."""
    job = sole_offline_lane_job(project_root, _PVGIS_JOB)

    assert lane_job_enabled(job), (
        f"the {_PVGIS_JOB!r} lane job is disabled, so a change in PVGIS's or pvlib's response goes unseen again"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_pvgis_job_collects_the_pvgis_contract_tests_and_nothing_else(
    project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the pvgis job collects at least one test, every one in tests/integration/test_pvgis.py.

    The job's uv environment is fresh, as the lane's is, so it holds only the
    extras the job names.
    """
    collection = collect_lane_job(project_root, _PVGIS_JOB, env=uv_probe_environment)

    assert collection.node_ids, (
        f"the {_PVGIS_JOB!r} lane job {collection.command!r} collected no tests, so the lane stays green "
        f"while the PVGIS contract tests go unrun\n{collection.outcome}"
    )
    outside_contract_tests = collection.node_ids_outside(_PVGIS_CONTRACT_TESTS)
    assert not outside_contract_tests, (
        f"the {_PVGIS_JOB!r} lane job {collection.command!r} collected tests outside {_PVGIS_CONTRACT_TESTS}, "
        f"which either the per-task verify already runs or hit PVGIS for other reasons: {outside_contract_tests}"
    )


def _clear_sky_tmy(location: Location) -> pd.DataFrame:
    """A TMY-shaped clear-sky year at *location*: TMY_HOURS hourly UTC rows with consistent ghi, dni and dhi."""
    hours = pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC")
    clear_sky = pvlib.location.Location(location.latitude, location.longitude).get_clearsky(
        hours, linke_turbidity=3.0
    )
    return clear_sky.assign(temp_air=10.0, wind_speed=2.0)


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
    # Deliberately replaces the offline guard's recording proxy: the inner session's PVGIS fetches are expected,
    # and the guard would record them against this test. Every fetch fails at the dead proxy instead.
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, _DEAD_PROXY)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    result = pytester.runpytest_subprocess(
        project_root / _PVGIS_CONTRACT_TESTS, "-p", "no:cacheprovider", timeout=120
    )

    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == 0 and outcomes.get("failed", 0) + outcomes.get("errors", 0) > 0, (
        f"with PVGIS behind a dead proxy, the PVGIS contract tests ended {outcomes}. A test that passes either "
        "checked the TMY cached in its working directory, not PVGIS's current response: fetch it with "
        "get_tmy_data(..., use_cache=False), as test_pvgis.py's bristol_tmy fixture does. Or it reached PVGIS "
        "around the dead proxy, because requests no longer honours HTTP(S)_PROXY, and this probe needs "
        "another way to keep PVGIS out of reach\n"
        f"stdout tail:\n{result.stdout.str()[-5000:]}"
    )
