# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end integration test for POST /api/simulate/fleet-from-distribution.

Uses a real JobManager (no mocks) to run a tiny 3-home, 1-day Bristol fleet
through the endpoint, polls the job to completion, and asserts the run lands
in history with n_homes == 3.  The test's weather cache serves a clear June day
on DAYS_WINDOW_START, where a ``days`` window starts, as Bristol's TMY, so the
job runs offline.
"""
import time
from pathlib import Path

import pytest

pytest.importorskip("flask")

from tests._web_app import build_test_app
from tests._web_job_days import web_job_days


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

_FLEET_DAYS = web_job_days(count=1)

_DIST_PAYLOAD = {
    "name": "E2E Dist Fleet",
    "n_homes": 3,
    "seed": 42,
    "location": "bristol",
    "days": _FLEET_DAYS.count,
    "pv": {
        "capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0},
    },
    "load": {
        "annual_consumption_kwh": 3500.0,
    },
    # Fleet-wide overlay — no-crash smoke coverage only.
    # Exercises the parse + dataclasses.replace path through the real pipeline
    # without erroring.  Effect verification (every HomeConfig carries the
    # TariffConfig / SEGTariff, battery-gated dispatch) lives in the unit tests
    # tests/unit/test_web_fleet_config.py::TestApplyFleetOverlay and
    # tests/unit/web_api/test_fleet_distribution.py::TestFleetFromDistribution.
    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 21]]},
    "seg": {"rate_pence_per_kwh": 5.0},
}

bristol_june_tmy = _FLEET_DAYS.bristol_tmy_fixture()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("bristol_june_tmy")
class TestFleetFromDistributionE2E:
    """End-to-end: a real 3-home distribution fleet runs to completion."""

    def test_distribution_fleet_completes_and_lands_in_history(
        self, tmp_path: Path
    ) -> None:
        """Submit a 3-home distribution fleet, poll to completion, assert history entry.

        Steps:
        1. POST to /api/simulate/fleet-from-distribution → 201 with job_id/run_id.
        2. Poll GET /api/jobs/<job_id> until status is completed/failed (≤180 s).
        3. Assert status == "completed".
        4. Assert the run appears in history with n_homes == 3.
        """
        client = build_test_app(tmp_path).test_client()

        # 1. Submit
        submit_resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json=_DIST_PAYLOAD,
        )
        assert submit_resp.status_code == 201, (
            f"Expected 201, got {submit_resp.status_code}: "
            f"{submit_resp.get_data(as_text=True)}"
        )
        body = submit_resp.get_json()
        assert "job_id" in body
        assert "run_id" in body
        job_id = body["job_id"]
        run_id = body["run_id"]

        # 2. Poll until completion
        deadline = time.monotonic() + 180  # 3-minute hard cap
        status = "queued"
        while time.monotonic() < deadline:
            status_resp = client.get(f"/api/jobs/{job_id}")
            assert status_resp.status_code == 200
            status_data = status_resp.get_json()
            status = status_data["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(1)

        # 3. Assert completed
        assert status == "completed", (
            f"Job did not complete within deadline; last status: {status}"
        )

        # 4. Assert history entry has n_homes == 3
        hist_resp = client.get("/api/history/runs?type=fleet&per_page=50")
        assert hist_resp.status_code == 200
        runs = hist_resp.get_json().get("runs", [])
        matching = [r for r in runs if r.get("id") == run_id]
        assert len(matching) == 1, (
            f"run_id {run_id!r} not found in history (got {[r.get('id') for r in runs]})"
        )
        n_homes = matching[0].get("n_homes")
        assert n_homes == 3, f"Expected n_homes=3 in history, got {n_homes}"
