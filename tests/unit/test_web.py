"""Tests for the Flask web dashboard module."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import make_sim_results
from tests._fleet_form import (
    FALSY_NON_NULL_VALUES,
    FLEET_FORM_BLOCKS,
    valid_distribution_form,
)
from tests._html_page import (
    counts_of,
    doctype,
    element_count,
    element_ids,
    headings,
    texts,
    texts_after,
)
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_job_manager(app: Flask) -> MagicMock:
    """Replace the real JobManager on the app with a MagicMock (opt-in per-test).

    This fixture is NOT wired into the module-level ``client`` fixture so that
    tests exercising real DB/JobManager-backed paths (dashboard, history, jobs)
    are unaffected.  Request it alongside ``client`` only in tests that want to
    avoid spawning real background simulations.
    """
    jm = MagicMock()
    jm.submit_home_job.return_value = ("job-home-001", "run-home-001")
    jm.submit_fleet_job.return_value = ("job-fleet-001", "run-fleet-001")
    app.extensions["job_manager"] = jm
    return jm


def _run_storage(app: Flask) -> RunStorage:
    """The RunStorage *app* keeps its runs in: the one create_app registers, which its pages read."""
    storage: RunStorage = app.extensions["storage"]
    return storage


def _home_config(name: str) -> HomeConfig:
    """The 4 kW PV, 3500 kWh home named *name* that the page tests save."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3500),
        name=name,
    )


def _save_home_run(
    app: Flask,
    name: str,
    results: SimulationResults,
    *,
    created_at: str | None = None,
    status: str = "completed",
) -> str:
    """Save *results* to *app*'s store as a home run named *name*, as a finished job saves its run; return its run id.

    *created_at*, an ISO timestamp, is the creation time the run is recorded with; it defaults to now.
    *status* is the status the run is recorded with; it defaults to completed.
    """
    run_id = str(uuid.uuid4())
    _run_storage(app).save_home_run(
        run_id=run_id,
        config=_home_config(name),
        results=results,
        summary=calculate_summary(results),
        name=name,
        status=status,
        created_at=created_at,
    )
    return run_id


def _save_fleet_run(
    app: Flask,
    name: str,
    per_home_results: list[SimulationResults],
    *,
    created_at: str | None = None,
) -> str:
    """Save a completed fleet run named *name* to *app*'s store, one home per item of *per_home_results*, as a finished job does; return its run id.

    *created_at*, an ISO timestamp, is the creation time the run is recorded with; it defaults to now.
    """
    run_id = str(uuid.uuid4())
    fleet = FleetResults(
        per_home_results=per_home_results,
        home_configs=[_home_config(f"{name} home {number}") for number in range(1, len(per_home_results) + 1)],
    )
    _run_storage(app).save_fleet_run(
        run_id=run_id,
        fleet_results=fleet,
        fleet_summary=calculate_fleet_summary(fleet),
        per_home_summaries=[calculate_summary(results) for results in per_home_results],
        name=name,
        created_at=created_at,
    )
    return run_id


class TestIndexRoute:
    """Tests for the GET / route."""

    def test_get_index_returns_200(self, client: FlaskClient) -> None:
        """Test GET / returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_get_index_returns_html(self, client: FlaskClient) -> None:
        """GET / returns an HTML document: the page declares the html doctype."""
        response = client.get("/")
        assert doctype(response.get_data(as_text=True)) == "html"

    def test_get_index_content_type_html(self, client: FlaskClient) -> None:
        """Test GET / returns text/html content type."""
        response = client.get("/")
        assert "text/html" in response.content_type


class TestDashboardRoute:
    """Tests for the dashboard page rendered at GET /."""

    def test_dashboard_returns_200(self, client: FlaskClient) -> None:
        """Test GET / returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_dashboard_contains_dashboard_text(self, client: FlaskClient) -> None:
        """GET / renders one Dashboard heading, the page's title."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        assert headings(page).count("Dashboard") == 1

    def test_dashboard_contains_sidebar_navigation(self, client: FlaskClient) -> None:
        """GET / renders the Simulate, Scenarios and History group labels once in each of its two sidebars, desktop and mobile."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        labels = ("Simulate", "Scenarios", "History")
        assert counts_of(texts(page), labels) == dict.fromkeys(labels, 2)

    def test_dashboard_contains_quick_start_cards(self, client: FlaskClient) -> None:
        """GET / renders one heading per quick-start card: Run Single Home, Run Fleet Simulation and Build Scenario."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        titles = ("Run Single Home", "Run Fleet Simulation", "Build Scenario")
        assert counts_of(headings(page), titles) == dict.fromkeys(titles, 1)

    def test_dashboard_contains_stats_section(self, client: FlaskClient) -> None:
        """GET / renders one label per aggregate stat: Total Runs, Homes Simulated and Energy Modelled."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        labels = ("Total Runs", "Homes Simulated", "Energy Modelled")
        assert counts_of(texts(page), labels) == dict.fromkeys(labels, 1)

    def test_dashboard_contains_recent_runs_section(self, client: FlaskClient) -> None:
        """GET / with no saved runs renders the Recent Runs heading and its empty-state message."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        assert headings(page).count("Recent Runs") == 1
        assert texts(page).count("No simulation runs yet.") == 1

    def test_dashboard_lists_saved_runs_in_recent_runs_table(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """GET / with saved runs renders the Recent Runs table, one row per run showing its name, and no empty-state message."""
        run_names = ("North Roof", "South Roof")
        for run_name in run_names:
            _save_home_run(app, run_name, make_sinusoidal_sim_results(days=1))
        response = client.get("/")
        page = response.get_data(as_text=True)
        page_texts = texts(page)
        assert "recent-runs-table" in element_ids(page)
        assert counts_of(page_texts, run_names) == dict.fromkeys(run_names, 1)
        assert "No simulation runs yet." not in page_texts

    def test_dashboard_recent_runs_table_rows_show_each_run_newest_first(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """GET / lists the saved runs newest first by creation time in the Recent Runs table: each row reads the run's name, type, date and status, and its name links to the run's home or fleet results page."""
        results = make_sinusoidal_sim_results(days=1)
        fleet_run_id = _save_fleet_run(
            app, "Community Fleet", [results, results], created_at="2024-06-02T09:00:00+00:00"
        )
        failed_run_id = _save_home_run(
            app, "South Roof", results, created_at="2024-06-03T09:00:00+00:00", status="failed"
        )
        home_run_id = _save_home_run(app, "North Roof", results, created_at="2024-06-01T09:00:00+00:00")
        response = client.get("/")
        page = response.get_data(as_text=True)
        assert texts_after(page, "Status", 12) == [
            "South Roof", "home", "2024-06-03", "failed",
            "Community Fleet", "fleet", "2024-06-02", "completed",
            "North Roof", "home", "2024-06-01", "completed",
        ]
        link_by_name = {
            "South Roof": f"/results/home/{failed_run_id}",
            "Community Fleet": f"/results/fleet/{fleet_run_id}",
            "North Roof": f"/results/home/{home_run_id}",
        }
        for name, link in link_by_name.items():
            assert element_count(page, "a", {"href": link}) == 1, name

    def test_dashboard_stats_count_and_total_only_the_completed_runs(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """GET / reads Total Runs as the completed runs, Homes Simulated as their homes, each home of a fleet run counted, and Energy Modelled as those homes' total generation in MWh; a failed run adds to none of them."""
        results = make_sinusoidal_sim_results(days=1)
        _save_home_run(app, "North Roof", results)
        _save_fleet_run(app, "Community Fleet", [results, results])
        _save_home_run(app, "South Roof", results, status="failed")
        response = client.get("/")
        page = response.get_data(as_text=True)
        completed_homes = 3
        completed_homes_generation_mwh = completed_homes * calculate_summary(results).total_generation_kwh / 1000
        assert texts_after(page, "Total Runs", 1) == ["2"]
        assert texts_after(page, "Homes Simulated", 1) == [str(completed_homes)]
        assert texts_after(page, "Energy Modelled", 2) == [str(round(completed_homes_generation_mwh, 2)), "MWh"]


class TestHomeResultsRoute:
    """Tests for the GET /results/home/<run_id> route."""

    @pytest.mark.parametrize(
        "run_id",
        [
            pytest.param("nonexistent-id", id="an-id-no-run-has"),
            pytest.param("bad.id", id="an-id-the-store-refuses"),
        ],
    )
    def test_home_results_unknown_run_redirects(self, client: FlaskClient, run_id: str) -> None:
        """The page of an id no run has redirects to the dashboard, which flashes Run not found.

        'bad.id' is outside [A-Za-z0-9_-], so the store refuses it, and no run can have it.
        """
        response = client.get(f"/results/home/{run_id}", follow_redirects=True)

        assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
        assert "Run not found." in texts(response.get_data(as_text=True))

    def test_home_results_after_simulation(self, app: Flask, client: FlaskClient) -> None:
        """A saved run's results page renders its Overview charts and energy totals.

        Both Overview chart containers are elements of the page, and the Total
        Generation and Total Demand cards read the saved summary's totals in kWh.
        """
        results = make_sinusoidal_sim_results(days=1)
        run_id = _save_home_run(app, "Test Run", results)
        summary = calculate_summary(results)

        response = client.get(f"/results/home/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert {"chart-sankey", "chart-daily-balance"} <= element_ids(page)
        for label, total_kwh in (
            ("Total Generation", summary.total_generation_kwh),
            ("Total Demand", summary.total_demand_kwh),
        ):
            assert texts_after(page, label, 2) == [f"{total_kwh:.1f}", "kWh"], label

    def test_home_results_stat_cards_round_each_saved_total_and_ratio_once(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Each stat card rounds its saved value once, to the card's own precision.

        The run self-consumes 10 kWh, exports 9.046 kWh and imports 5.749 kWh in its one day.
        Each card below sits where rounding its value to 2 dp first (a ratio to 4 dp) would
        move the card's last digit: 9.046 kWh would show 9.1.
        """
        run_id = _save_home_run(
            app,
            "North Roof",
            make_sim_results(self_kwh=10.0, export_kwh=9.046, import_kwh=5.749, days=1),
        )
        response = client.get(f"/results/home/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        expected_cards = {
            "Total Generation": ["19.0", "kWh"],
            "Total Demand": ["15.7", "kWh"],
            "Grid Import": ["5.7", "kWh"],
            "Grid Export": ["9.0", "kWh"],
            "Self-Consumption Ratio": ["53", "%"],
            "Grid Dependency": ["37", "%"],
            "Export Ratio": ["47", "%"],
        }
        assert {
            label: texts_after(page, label, len(card))
            for label, card in expected_cards.items()
        } == expected_cards

    def test_home_results_page_title_follows_a_run_history_rename(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Renaming a run in Run History retitles its results page.

        The run's home keeps the name it was saved with, so the page reads the run's name, not its home's.
        """
        run_id = _save_home_run(app, "North Roof", make_sinusoidal_sim_results(days=1))
        rename = client.patch(f"/api/history/runs/{run_id}", json={"name": "South Roof"})
        assert rename.status_code == 200

        response = client.get(f"/results/home/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert headings(page)[0] == "South Roof"
        assert "Results: South Roof - Solar Challenge" in texts(page)

    def test_home_results_page_of_a_run_with_no_database_row_is_titled_home_simulation(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run whose files outlived its database row still has a title: the page's own, not its home's name."""
        run_id = _save_home_run(app, "North Roof", make_sinusoidal_sim_results(days=1))
        with get_db(app.config["DATABASE"]) as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

        response = client.get(f"/results/home/{run_id}")

        assert response.status_code == 200
        assert headings(response.get_data(as_text=True))[0] == "Home Simulation"


class TestFleetApiEndpoints:
    """Tests for fleet-related API endpoints."""

    def test_preview_distribution_normal(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/preview-distribution with normal distribution."""
        response = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "normal",
                "params": {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0},
                "n_samples": 50,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "samples" in data
        assert len(data["samples"]) == 50

    def test_preview_distribution_invalid_type(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/preview-distribution with invalid type returns 400."""
        response = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "invalid_type", "params": {}},
        )
        assert response.status_code == 400

    def test_simulate_fleet_from_distribution(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Test POST /api/simulate/fleet-from-distribution returns 201 with job_id/run_id.

        Uses mock_job_manager to avoid spawning a real 10-home background simulation
        (PVGIS network I/O, DB writes) that would race with tmp_path teardown.
        """
        response = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                "n_homes": 10,
                "pv": {
                    "capacity_kw": {
                        "type": "normal",
                        "mean": 4.0,
                        "std": 1.0,
                        "min": 2.0,
                        "max": 8.0,
                    }
                },
                "load": {
                    "annual_consumption_kwh": {
                        "type": "uniform",
                        "min": 2000,
                        "max": 5000,
                    }
                },
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["job_id"] == "job-fleet-001"
        assert data["run_id"] == "run-fleet-001"
        mock_job_manager.submit_fleet_job.assert_called_once()

    def test_simulate_fleet_from_distribution_empty_body(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/fleet-from-distribution with empty body returns 400."""
        response = client.post(
            "/api/simulate/fleet-from-distribution",
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.parametrize(("value", "type_name"), FALSY_NON_NULL_VALUES)
    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    @pytest.mark.parametrize(
        "endpoint",
        [
            pytest.param("/api/simulate/fleet-from-distribution", id="simulate"),
            pytest.param("/api/fleet/export-yaml", id="export-yaml"),
        ],
    )
    def test_fleet_form_endpoints_refuse_a_falsy_block_other_than_null_naming_it(
        self,
        client: FlaskClient,
        mock_job_manager: MagicMock,
        endpoint: str,
        key: str,
        value: object,
        type_name: str,
    ) -> None:
        """Every block of the fleet form, the pv/battery/load distributions and the tariff/dispatch_strategy/seg overlays alike, refuses a falsy value other than null as a value that is not a mapping, naming the block and the type sent, at the simulate endpoint and the export alike; no fleet is queued."""
        response = client.post(endpoint, json={**valid_distribution_form(), key: value})

        assert response.status_code == 400
        assert response.get_json() == {"error": f"{key} must be a mapping, got {type_name}"}
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    def test_simulate_fleet_from_distribution_reads_a_null_block_as_absent(
        self, client: FlaskClient, mock_job_manager: MagicMock, key: str
    ) -> None:
        """A null block, any of the six, gets the answer the form without it gets."""
        without_block = {k: v for k, v in valid_distribution_form().items() if k != key}

        null_block = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**valid_distribution_form(), key: None},
        )
        absent_block = client.post("/api/simulate/fleet-from-distribution", json=without_block)

        assert (null_block.status_code, null_block.get_json()) == (
            absent_block.status_code,
            absent_block.get_json(),
        )
        submissions = mock_job_manager.submit_fleet_job.call_args_list
        if null_block.status_code == 201:
            assert len(submissions) == 2
            assert submissions[0] == submissions[1]
        else:
            assert submissions == []

    def test_simulate_fleet_from_distribution_refuses_an_empty_battery_block_naming_its_missing_capacity(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """An empty battery block is a present block, not an absent one: a battery without its capacity distribution, it is a 400 naming battery.capacity_kwh, and no fleet is queued."""
        response = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**valid_distribution_form(), "battery": {}},
        )

        assert response.status_code == 400
        assert "battery.capacity_kwh" in response.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()


# ---------------------------------------------------------------------------
# Error page tests
# ---------------------------------------------------------------------------


class TestErrorPages:
    """Tests for custom 404 and 500 error pages."""

    def test_nonexistent_route_returns_404(self, client: FlaskClient) -> None:
        """Test GET /nonexistent returns 404 status code."""
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_nonexistent_route_returns_html_template(self, client: FlaskClient) -> None:
        """Test GET /nonexistent returns a rendered 404 template, not a raw error."""
        response = client.get("/nonexistent")
        assert response.status_code == 404
        assert "text/html" in response.content_type
        html = response.data.decode("utf-8")
        # Should contain the custom 404 template content
        assert headings(html).count("Page Not Found") == 1
        # Should NOT be a raw error string like "Not Found"
        assert doctype(html) == "html"

    def test_404_page_renders_within_app_layout(self, client: FlaskClient) -> None:
        """Test custom 404 page is rendered within the base app layout."""
        response = client.get("/nonexistent")
        assert response.status_code == 404
        html = response.data.decode("utf-8")
        page_texts = texts(html)
        # The base template includes sidebar navigation and footer
        assert "Solar Challenge" in page_texts
        # Check it extends the base layout (has nav and footer elements)
        assert element_count(html, "nav") >= 1
        assert element_count(html, "footer") >= 1
        # Contains the 404-specific content
        assert texts_after(html, "404", 1) == ["Page Not Found"]
        assert page_texts.count("Back to Dashboard") == 1

    def test_500_page_renders_within_app_layout(self, app: Flask) -> None:
        """Test custom 500 page is rendered within the base app layout."""
        # Register a route that always raises an exception
        @app.route("/trigger-500")
        def trigger_500() -> str:
            raise RuntimeError("Deliberate test error")

        # Temporarily disable TESTING exception propagation so the
        # 500 error handler fires and renders the template.
        app.config["TESTING"] = False
        try:
            with app.test_client() as test_client:
                response = test_client.get("/trigger-500")
                assert response.status_code == 500
                html = response.data.decode("utf-8")
                page_texts = texts(html)
                # Should render within the base layout
                assert "Solar Challenge" in page_texts
                assert element_count(html, "footer") >= 1
                # Contains the 500-specific content
                assert texts_after(html, "500", 1) == ["Internal Server Error"]
                assert page_texts.count("Back to Dashboard") == 1
        finally:
            app.config["TESTING"] = True
