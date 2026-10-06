# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for POST /api/simulate/sweep, which submits one home job per sweep point.

This module's client submits to a recording double that numbers job ids in submission
order and takes the real submit_home_job's parameters.
"""

from collections.abc import Callable
from inspect import signature
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.home import HomeConfig
from solar_challenge.web.simulation_params import parse_home_config


class _RecordingJobManager:
    """Stands in for the app's JobManager: records each home config a request submits, and the window it runs, and simulates nothing."""

    def __init__(self) -> None:
        self.submitted_homes: list[HomeConfig] = []
        self.submitted_windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def submit_home_job(
        self,
        config: HomeConfig,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        db_path: str,
        data_dir: str,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Record the home config and the window it runs, and return a fresh (job_id, run_id) pair."""
        self.submitted_homes.append(config)
        self.submitted_windows.append((start_date, end_date))
        n = len(self.submitted_homes)
        return f"job-{n}", f"run-{n}"


@pytest.fixture
def recording_job_manager(app: Flask) -> _RecordingJobManager:
    """Install a recording double as the app's job manager and return it."""
    job_manager = _RecordingJobManager()
    app.extensions["job_manager"] = job_manager
    return job_manager


@pytest.fixture
def client(app: Flask, recording_job_manager: _RecordingJobManager) -> FlaskClient:
    """Create a Flask test client whose requests submit jobs to the recording double, not the package's MagicMock."""
    return app.test_client()


def _call_shape(method: Callable[..., object]) -> list[tuple[str, object, object]]:
    """The parameter names, kinds and defaults that decide which calls a method accepts."""
    return [(p.name, p.kind, p.default) for p in signature(method).parameters.values()]


class TestRecordingJobManager:
    """The recording double stays in step with the real JobManager it stands in for."""

    def test_submit_home_job_takes_the_parameters_the_real_one_takes(self, app: Flask) -> None:
        """A change to the real submit_home_job's parameters fails here, instead of passing silently behind the double."""
        real_job_manager = app.extensions["job_manager"]
        double = _RecordingJobManager()

        assert _call_shape(double.submit_home_job) == _call_shape(real_job_manager.submit_home_job)


class TestSimulateSweep:
    """Tests for POST /api/simulate/sweep."""

    def test_valid_linear_sweep_returns_201(self, client: FlaskClient) -> None:
        """A linear sweep from a base config returns 201 with the parameter, values evenly spaced from min to max, and each point's job id in point order."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 2.0,
                "max": 8.0,
                "steps": 4,
                "mode": "linear",
                "base_config": {"battery_kwh": 5.0, "location": "bristol", "days": 7},
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["parameter"] == "pv_capacity_kw"
        assert data["values"] == [2.0, 4.0, 6.0, 8.0]
        assert data["job_ids"] == ["job-1", "job-2", "job-3", "job-4"]

    def test_valid_geometric_sweep_returns_201(self, client: FlaskClient) -> None:
        """A geometric sweep's values grow by a constant ratio from min to max."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 1.0,
                "max": 8.0,
                "steps": 4,
                "mode": "geometric",
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["values"] == [1.0, 2.0, 4.0, 8.0]

    @pytest.mark.parametrize(
        ("data", "content_type"),
        [
            pytest.param("not json", "text/plain", id="text-body"),
            pytest.param(None, "application/json", id="empty-json-body"),
        ],
    )
    def test_no_json_returns_400(self, client: FlaskClient, data: str | None, content_type: str) -> None:
        """A body that does not read as a JSON object, plain text or an empty JSON body, returns 400."""
        resp = client.post("/api/simulate/sweep", data=data, content_type=content_type)
        assert resp.status_code == 400

    def test_steps_less_than_2_returns_400(self, client: FlaskClient) -> None:
        """Steps < 2 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 10.0, "steps": 1},
        )
        assert resp.status_code == 400
        assert "Steps" in resp.get_json()["error"]

    def test_min_gte_max_returns_400(self, client: FlaskClient) -> None:
        """min >= max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 10.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Min" in resp.get_json()["error"]

    def test_min_equals_max_returns_400(self, client: FlaskClient) -> None:
        """min == max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 5.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400

    def test_geometric_negative_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min <= 0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": -1.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400
        assert "positive" in resp.get_json()["error"]

    def test_geometric_zero_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min=0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 0.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400

    def test_invalid_numeric_param_returns_400(self, client: FlaskClient) -> None:
        """Non-numeric min/max/steps returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": "abc", "max": 10.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Invalid numeric" in resp.get_json()["error"]

    @pytest.mark.parametrize(
        ("base_config", "type_name"),
        [
            pytest.param("abc", "str", id="string"),
            pytest.param("", "str", id="empty-string"),
            pytest.param(5, "int", id="number"),
            pytest.param([1], "list", id="array"),
            pytest.param([], "list", id="empty-array"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param(None, "NoneType", id="null"),
            pytest.param([["battery_kwh", 5.0]], "list", id="array-of-key-value-pairs"),
        ],
    )
    def test_base_config_that_is_not_a_json_object_returns_400_and_submits_nothing(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        base_config: object,
        type_name: str,
    ) -> None:
        """A base_config that is not a JSON object is refused naming base_config and its type, and no sweep point is submitted."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2, "base_config": base_config},
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "base_config" in error
        assert type_name in error
        assert recording_job_manager.submitted_homes == []

    def test_empty_object_body_submits_the_default_sweep(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """Every field is optional: {} sweeps PV capacity linearly from 1 to 10 kW in 5 steps, one home job per step."""
        resp = client.post("/api/simulate/sweep", json={})
        assert resp.status_code == 201
        default_pv_kw = [1.0, 3.25, 5.5, 7.75, 10.0]
        assert (resp.get_json()["parameter"], resp.get_json()["values"]) == ("pv_capacity_kw", default_pv_kw)
        assert [home.pv_config.capacity_kw for home in recording_job_manager.submitted_homes] == default_pv_kw


class TestSweepParameters:
    """What POST /api/simulate/sweep submits for a swept parameter: one home per point, carrying that point's value, or nothing at all when the parameter is unsupported or any of its points is invalid."""

    @pytest.mark.parametrize(
        ("parameter", "values", "swept_value_of"),
        [
            pytest.param(
                "pv_capacity_kw",
                [2.0, 5.0, 8.0],
                lambda home: home.pv_config.capacity_kw,
                id="pv",
            ),
            pytest.param(
                "battery_capacity_kwh",
                [5.0, 10.0, 15.0],
                lambda home: home.battery_config.capacity_kwh,
                id="battery",
            ),
            pytest.param(
                "annual_consumption_kwh",
                [2000.0, 3500.0, 5000.0],
                lambda home: home.load_config.annual_consumption_kwh,
                id="consumption",
            ),
        ],
    )
    def test_each_point_simulates_a_home_carrying_that_points_value(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        parameter: str,
        values: list[float],
        swept_value_of: Callable[[HomeConfig], float],
    ) -> None:
        """Each sweep point submits one home whose swept field holds that point's value."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": parameter,
                "min": values[0],
                "max": values[-1],
                "steps": len(values),
                "mode": "linear",
            },
        )

        assert response.status_code == 201
        assert response.get_json()["values"] == values
        assert [swept_value_of(home) for home in recording_job_manager.submitted_homes] == values

    @pytest.mark.parametrize("parameter", ["n_homes", "tilt", "no_such_parameter"])
    def test_unsupported_parameter_is_refused_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        parameter: str,
    ) -> None:
        """A parameter outside the supported set, even a real home-config key, gets 400 and submits nothing.

        The error names the refused parameter and every supported one.
        """
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": parameter, "min": 10.0, "max": 40.0, "steps": 3},
        )

        assert response.status_code == 400
        error = response.get_json()["error"]
        assert parameter in error
        for supported in ("pv_capacity_kw", "battery_capacity_kwh", "annual_consumption_kwh"):
            assert supported in error
        assert recording_job_manager.submitted_homes == []

    def test_a_later_invalid_point_refuses_the_sweep_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
    ) -> None:
        """A sweep whose last point exceeds the PV capacity a home accepts gets 400 naming that point, and submits none of its points.

        Its earlier points are valid, so a sweep that submitted each point as it validated it would already have started their jobs.
        """
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": "pv_capacity_kw", "min": 5.0, "max": 25.0, "steps": 3},
        )

        assert response.status_code == 400
        assert "pv_capacity_kw=25.0" in response.get_json()["error"]
        assert recording_job_manager.submitted_homes == []


def _home_window(home_config: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The window parse_home_config reads from home_config, the one POST /api/simulate/home runs."""
    _, start_date, end_date, _ = parse_home_config(home_config)
    return start_date, end_date


class TestSweepWindow:
    """The window every point of a sweep runs: the one its base_config sends, or 7 days when it sends none."""

    @pytest.mark.parametrize(
        "window",
        [
            pytest.param({"start": "2024-01-01", "end": "2024-03-31"}, id="start-and-end"),
            pytest.param({"start": "2024-02-01"}, id="start-only"),
            pytest.param({"end": "2024-03-31"}, id="end-only"),
            pytest.param({"days": 30}, id="days"),
            pytest.param({"days": None}, id="days-null"),
        ],
    )
    def test_every_point_runs_the_window_its_base_config_sends(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        window: dict[str, Any],
    ) -> None:
        """A base_config that sends any of days, start and end, even as null, has every point run the window parse_home_config reads from it."""
        response = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2, "base_config": window},
        )

        assert response.status_code == 201
        assert recording_job_manager.submitted_windows == [_home_window(window)] * 2

    @pytest.mark.parametrize(
        "base_config_fields",
        [
            pytest.param({"base_config": {"battery_kwh": 5.0}}, id="base-config-without-window-key"),
            pytest.param({"base_config": {}}, id="empty-base-config"),
            pytest.param({}, id="no-base-config"),
        ],
    )
    def test_a_request_that_sends_no_window_key_runs_every_point_for_7_days(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        base_config_fields: dict[str, Any],
    ) -> None:
        """A request that sends none of days, start and end has every point run the sweep's default 7 days.

        Its base_config may hold other keys, be empty, or be left out of the body altogether.
        """
        response = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2, **base_config_fields},
        )

        assert response.status_code == 201
        assert recording_job_manager.submitted_windows == [_home_window({"days": 7})] * 2

    def test_a_window_the_home_parser_refuses_gets_400_carrying_its_refusal_and_submits_nothing(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """A base_config window parse_home_config refuses gets 400 carrying that refusal, and no sweep point is submitted."""
        window = {"start": "not-a-date", "end": "2024-03-31"}
        with pytest.raises(ValueError) as refusal:
            parse_home_config(window)

        response = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2, "base_config": window},
        )

        assert response.status_code == 400
        assert str(refusal.value) in response.get_json()["error"]
        assert recording_job_manager.submitted_homes == []
