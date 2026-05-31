# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slow end-to-end integration test for POST /api/simulate/fleet-from-distribution.

Uses a real JobManager (no mocks) to run a tiny 3-home, 1-day Bristol fleet
through the endpoint, polls the job to completion, and asserts the run lands
in history with n_homes == 3.
"""
import time
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


# ---------------------------------------------------------------------------
# Fixtures — real app, real JobManager (no mock)
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a real Flask app with temporary database and data dir."""
    db_path = str(tmp_path / "test_dist.db")
    data_dir = str(tmp_path / "data")
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-dist",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": db_path,
            "DATA_DIR": data_dir,
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a test client against the real app."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

_DIST_PAYLOAD = {
    "name": "E2E Dist Fleet",
    "n_homes": 3,
    "seed": 42,
    "location": "bristol",
    "days": 1,
    "pv": {
        "capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0},
    },
    "load": {
        "annual_consumption_kwh": 3500.0,
    },
}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFleetFromDistributionE2E:
    """End-to-end slow test: real 3-home distribution fleet runs to completion."""

    def test_distribution_fleet_completes_and_lands_in_history(
        self, client: FlaskClient
    ) -> None:
        """Submit a 3-home distribution fleet, poll to completion, assert history entry.

        Steps:
        1. POST to /api/simulate/fleet-from-distribution → 201 with job_id/run_id.
        2. Poll GET /api/jobs/<job_id> until status is completed/failed (≤180 s).
        3. Assert status == "completed".
        4. Assert the run appears in history with n_homes == 3.
        """
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
