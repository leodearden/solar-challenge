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

from solar_challenge.battery import BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.scenario_knobs import KNOBS
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.simulation_params import parse_home_config, with_default_days
from solar_challenge.web.sweep_request import read_sweep_request
from tests._html_page import element_attributes
from tests._html_select_options import option_texts


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
        name: str | None = None,
    ) -> tuple[str, str]:
        """Record the home config and the window it runs, and return a fresh (job_id, run_id) pair."""
        self.submitted_homes.append(config)
        self.submitted_windows.append((start_date, end_date))
        n = len(self.submitted_homes)
        return f"job-{n}", f"run-{n}"

    def shutdown(self, wait: bool = False) -> None:
        """Stop nothing: the double runs no job."""


@pytest.fixture
def recording_job_manager() -> _RecordingJobManager:
    """The recording double the app's jobs run on."""
    return _RecordingJobManager()


@pytest.fixture
def jobs(recording_job_manager: _RecordingJobManager) -> Callable[[RunStorage], Any]:
    """Build this module's apps on the recording double."""
    return lambda storage: recording_job_manager


@pytest.fixture
def client(app: Flask, recording_job_manager: _RecordingJobManager) -> FlaskClient:
    """Create a Flask test client whose requests submit jobs to the recording double, not the package's mock_job_manager."""
    return app.test_client()


def _call_shape(method: Callable[..., object]) -> list[tuple[str, object, object]]:
    """The parameter names, kinds and defaults that decide which calls a method accepts."""
    return [(p.name, p.kind, p.default) for p in signature(method).parameters.values()]


class TestRecordingJobManager:
    """The recording double stays in step with the real JobManager it stands in for."""

    def test_submit_home_job_takes_the_parameters_the_real_one_takes(self) -> None:
        """A change to the real submit_home_job's parameters fails here, instead of passing silently behind the double."""
        assert _call_shape(_RecordingJobManager.submit_home_job) == _call_shape(JobManager.submit_home_job)


def _steps_the_sweep_page_offers(client: FlaskClient) -> tuple[int, int]:
    """The fewest and the most steps the sweep page's Steps box offers: its min and its max."""
    page = client.get("/scenarios/sweep").get_data(as_text=True)
    [steps_box] = [box for box in element_attributes(page, "input") if box.get("x-model") == "steps"]
    fewest, most = steps_box["min"], steps_box["max"]
    assert fewest is not None and most is not None
    return int(fewest), int(most)


def test_the_sweep_page_offers_exactly_the_parameters_a_sweep_accepts(client: FlaskClient) -> None:
    """The sweep page's parameter select offers exactly the knobs POST /api/simulate/sweep accepts; it answers every other knob with 400."""
    page = client.get("/scenarios/sweep").get_data(as_text=True)
    offered = list(option_texts(page, {"x-model": "parameter"}))
    assert offered, "the sweep page offers no parameter"

    answers = {name: client.post("/api/simulate/sweep", json={"parameter": name}).status_code for name in KNOBS}

    assert {name for name in KNOBS if answers[name] == 201} == set(offered)
    refused = {name: status for name, status in answers.items() if name not in offered}
    assert refused == dict.fromkeys(refused, 400)


class TestSimulateSweep:
    """Tests for POST /api/simulate/sweep."""

    def test_valid_linear_sweep_returns_201(self, client: FlaskClient) -> None:
        """A linear sweep from a base config returns 201 with a body of exactly three keys: the parameter, values evenly spaced from min to max, and each point's job id in point order."""
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
        assert resp.get_json() == {
            "parameter": "pv_capacity_kw",
            "values": [2.0, 4.0, 6.0, 8.0],
            "job_ids": ["job-1", "job-2", "job-3", "job-4"],
        }

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

    # One value for each field, refused by that field's number_fields reader; each reader's full matrix is tested there.
    @pytest.mark.parametrize(
        ("body", "message"),
        [
            pytest.param(
                {"min": 10**400, "max": 5, "steps": 2},
                f"min must be a finite number, got {10**400!r}",
                id="min-too-large-for-a-float",
            ),
            pytest.param(
                {"min": 1, "max": float("inf"), "steps": 2},
                "max must be a finite number, got inf",
                id="max-infinity",
            ),
            pytest.param(
                {"min": 1, "max": 5, "steps": 2.5},
                "steps must be a whole number, got 2.5",
                id="steps-fraction",
            ),
        ],
    )
    def test_a_number_it_cannot_use_is_refused_naming_the_field_and_the_value_sent_and_submits_nothing(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        body: dict[str, object],
        message: str,
    ) -> None:
        """A min, max or steps the sweep cannot use is a 400 naming the field and the value sent, never a 500, and no sweep point is submitted."""
        resp = client.post("/api/simulate/sweep", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": message}
        assert recording_job_manager.submitted_homes == []

    def test_a_sweep_may_have_as_many_points_as_the_sweep_page_offers(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """A sweep with as many points as the sweep page's Steps box offers submits one home per point."""
        _, most = _steps_the_sweep_page_offers(client)
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 10.0, "steps": most},
        )
        assert resp.status_code == 201
        assert len(recording_job_manager.submitted_homes) == most

    @pytest.mark.parametrize(
        "steps_the_page_does_not_offer",
        [
            pytest.param(lambda fewest, most: fewest - 1, id="fewer-than-the-page-offers"),
            pytest.param(lambda fewest, most: most + 1, id="more-than-the-page-offers"),
        ],
    )
    def test_a_step_count_the_sweep_page_does_not_offer_is_refused_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        steps_the_page_does_not_offer: Callable[[int, int], int],
    ) -> None:
        """One step fewer, or one more, than the sweep page's Steps box offers is a 400 naming steps, the range the page offers and the value sent; no point is submitted."""
        fewest, most = _steps_the_sweep_page_offers(client)
        steps = steps_the_page_does_not_offer(fewest, most)
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 10.0, "steps": steps},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": f"steps must be between {fewest} and {most}, got {steps}"}
        assert recording_job_manager.submitted_homes == []

    def test_min_gte_max_returns_400(self, client: FlaskClient) -> None:
        """min >= max returns 400 naming both."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 10.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "min" in error
        assert "max" in error

    def test_min_equals_max_returns_400(self, client: FlaskClient) -> None:
        """min == max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 5.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400

    def test_geometric_negative_min_returns_400(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """Geometric sweep with min <= 0 returns 400 naming min, and submits nothing."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": -1.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400
        assert "min" in resp.get_json()["error"]
        assert recording_job_manager.submitted_homes == []

    def test_geometric_zero_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min=0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 0.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400

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
        """Every field is optional: {} sweeps PV capacity geometrically over its starting range, 2 to 8 kW, in 5 steps, one home job per step."""
        resp = client.post("/api/simulate/sweep", json={})
        assert resp.status_code == 201
        default_pv_kw = [2.0, 2.828, 4.0, 5.657, 8.0]
        assert (resp.get_json()["parameter"], resp.get_json()["values"]) == ("pv_capacity_kw", default_pv_kw)
        assert [home.pv_config.capacity_kw for home in recording_job_manager.submitted_homes] == default_pv_kw

    def test_a_body_naming_only_the_battery_sweeps_it_geometrically_from_1_to_13_5_kwh_in_5_steps(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        resp = client.post("/api/simulate/sweep", json={"parameter": "battery_capacity_kwh"})
        assert resp.status_code == 201
        default_battery_kwh = [1.0, 1.917, 3.674, 7.043, 13.5]
        assert (resp.get_json()["parameter"], resp.get_json()["values"]) == (
            "battery_capacity_kwh",
            default_battery_kwh,
        )
        assert [home.battery_config.capacity_kwh for home in recording_job_manager.submitted_homes] == (
            default_battery_kwh
        )


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

    def test_a_max_outside_the_parameters_range_is_refused_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
    ) -> None:
        """A sweep whose max exceeds the PV capacity a home accepts gets read_sweep_request's own refusal of its range, not a point's, and submits none of its points."""
        body = {"parameter": "pv_capacity_kw", "min": 5.0, "max": 25.0, "steps": 3}
        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request(body)

        response = client.post("/api/simulate/sweep", json=body)

        assert (response.status_code, response.get_json()) == (400, {"error": str(refusal.value)})
        assert recording_job_manager.submitted_homes == []

    def test_a_base_config_the_home_parser_refuses_is_refused_naming_base_config_and_carrying_its_refusal(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
    ) -> None:
        """A base_config location no preset names refuses the sweep, named base_config, with parse_home_config's own refusal of the base, and submits nothing."""
        base_config = {"location": "londn"}
        with pytest.raises(ConfigurationError) as refusal:
            parse_home_config(with_default_days(base_config, 7))

        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": "pv_capacity_kw", "min": 1.0, "max": 5.0, "steps": 2, "base_config": base_config},
        )

        assert (response.status_code, response.get_json()) == (
            400,
            {"error": f"base_config: {refusal.value}"},
        )
        assert recording_job_manager.submitted_homes == []


class TestSweepRequestAnswers:
    """What POST /api/simulate/sweep answers for a sweep request its reader reads or refuses."""

    def test_a_mode_no_sweep_spaces_its_points_by_is_refused_naming_mode_and_each_mode(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        response = client.post("/api/simulate/sweep", json={"min": 1, "max": 4, "steps": 3, "mode": "log"})

        assert response.status_code == 400
        error = response.get_json()["error"]
        for named in ("mode", "'log'", "linear", "geometric"):
            assert named in error
        assert recording_job_manager.submitted_homes == []

    def test_a_battery_max_above_its_components_range_gets_the_readers_range_refusal(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        body = {"parameter": "battery_capacity_kwh", "min": 0, "max": 200, "steps": 3, "mode": "linear"}
        with pytest.raises(ConfigurationError) as refusal:
            read_sweep_request(body)

        response = client.post("/api/simulate/sweep", json=body)

        assert (response.status_code, response.get_json()) == (400, {"error": str(refusal.value)})
        assert recording_job_manager.submitted_homes == []

    def test_a_body_without_a_mode_sweeps_geometrically(self, client: FlaskClient) -> None:
        response = client.post("/api/simulate/sweep", json={"min": 1, "max": 4, "steps": 3})

        assert response.status_code == 201
        assert response.get_json()["values"] == [1.0, 2.0, 4.0]


#: The field of a sweep page's base_config that holds each parameter's value, and the fleet component whose range bounds it.
_FORM_KEY_AND_COMPONENT = {
    "pv_capacity_kw": ("pv_kw", "pv"),
    "battery_capacity_kwh": ("battery_kwh", "battery"),
    "annual_consumption_kwh": ("consumption_kwh", "load"),
}

#: The base_config the sweep page posts until its user changes one.
_PAGE_BASE_CONFIG = {"battery_kwh": 5.0, "location": "bristol", "days": 7}


class TestSweepPointHomes:
    """The home each point of a sweep submits: the base_config's home with the parameter at the point's value."""

    @pytest.mark.parametrize("parameter", tuple(_FORM_KEY_AND_COMPONENT))
    def test_each_points_home_is_the_one_its_form_would_post(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager, parameter: str
    ) -> None:
        """Each point's home equals the one parse_home_config reads from the base_config with the parameter's form field at the point's value."""
        form_key, component = _FORM_KEY_AND_COMPONENT[parameter]
        value_range = FLEET_COMPONENTS[component].value_range

        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": parameter,
                "min": value_range.low,
                "max": value_range.high,
                "steps": 3,
                "mode": "linear",
                "base_config": _PAGE_BASE_CONFIG,
            },
        )

        assert response.status_code == 201
        assert recording_job_manager.submitted_homes == [
            parse_home_config({**_PAGE_BASE_CONFIG, form_key: value})[0] for value in response.get_json()["values"]
        ]

    def test_a_base_without_a_battery_gives_each_battery_point_a_default_battery(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """A base_config without a battery, whatever battery power it sends, gives a battery point BatteryConfig's defaults at its capacity, and the 0 kWh point no battery."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "battery_capacity_kwh",
                "min": 0,
                "max": 10,
                "steps": 2,
                "mode": "linear",
                "base_config": {"battery_kwh": 0, "max_charge_kw": 3, "days": 7},
            },
        )

        assert response.status_code == 201
        no_battery, ten_kwh = recording_job_manager.submitted_homes
        assert no_battery.battery_config is None
        assert ten_kwh.battery_config == BatteryConfig(capacity_kwh=10.0)


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
            pytest.param(
                {"days": None, "start": "2024-03-01", "end": "2024-03-05"},
                id="null-days-with-start-and-end",
            ),
        ],
    )
    def test_every_point_runs_the_window_its_base_config_sends(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        window: dict[str, Any],
    ) -> None:
        """A base_config that sends a days, or a start or end, has every point run the window parse_home_config reads from it, never the sweep's default 7 days."""
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
            pytest.param({"base_config": {"days": None}}, id="null-days"),
            pytest.param({"base_config": {"start": "", "end": None}}, id="empty-and-null-dates"),
            pytest.param({"base_config": {}}, id="empty-base-config"),
            pytest.param({}, id="no-base-config"),
        ],
    )
    def test_a_request_that_sends_no_window_runs_every_point_for_7_days(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        base_config_fields: dict[str, Any],
    ) -> None:
        """A request that sends no window, as parse_date_range reads one, has every point run the sweep's default 7 days.

        Its base_config may hold other keys, a null days, or an empty or null start or end; or it may be empty, or be left out of the body altogether.
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


_POINTS_URL = "/api/simulate/sweep/points"


class TestSweepPoints:
    """POST /api/simulate/sweep/points previews the values POST /api/simulate/sweep runs, reading the same body, and submits nothing."""

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"parameter": "pv_capacity_kw", "min": 1, "max": 9, "steps": 4, "mode": "geometric"},
                id="geometric-pv",
            ),
            pytest.param(
                {"parameter": "battery_capacity_kwh", "min": 0, "max": 10, "steps": 3, "mode": "linear"},
                id="linear-battery",
            ),
            pytest.param({"parameter": "battery_capacity_kwh"}, id="battery-defaults"),
        ],
    )
    def test_the_points_are_the_parameter_and_values_the_submit_runs(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager, body: dict[str, object]
    ) -> None:
        body = {**body, "base_config": _PAGE_BASE_CONFIG}

        points = client.post(_POINTS_URL, json=body)
        submitted_by_the_points = list(recording_job_manager.submitted_homes)
        submit = client.post("/api/simulate/sweep", json=body)

        assert (points.status_code, submit.status_code) == (200, 201)
        assert points.get_json() == {
            "parameter": submit.get_json()["parameter"],
            "values": submit.get_json()["values"],
        }
        assert submitted_by_the_points == []

    def test_the_points_read_no_base_config(self, client: FlaskClient) -> None:
        """A base_config the submit would refuse changes nothing the points answer."""
        body = {"min": 1, "max": 4, "steps": 3}

        with_a_refused_base = client.post(_POINTS_URL, json={**body, "base_config": {"location": "londn"}})
        without_one = client.post(_POINTS_URL, json=body)

        assert (with_a_refused_base.status_code, with_a_refused_base.get_json()) == (200, without_one.get_json())

    def test_a_sweep_the_reader_refuses_gets_the_same_400_from_both_and_submits_nothing(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        body = {"parameter": "battery_capacity_kwh", "min": 0, "max": 10, "steps": 3, "mode": "geometric"}

        points = client.post(_POINTS_URL, json=body)
        submit = client.post("/api/simulate/sweep", json=body)

        assert (points.status_code, points.get_json()) == (400, submit.get_json())
        assert submit.status_code == 400
        assert recording_job_manager.submitted_homes == []
