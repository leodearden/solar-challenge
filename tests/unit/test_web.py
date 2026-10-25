"""Tests for the Flask web dashboard module."""

import logging
import uuid

import pytest
pytest.importorskip("flask")
from flask import Flask, render_template
from flask.testing import FlaskClient

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.storage import RunStatus, RunStorage
from tests._finance_builders import make_sim_results
from tests._html_page import (
    chart_figures,
    counts_of,
    current_page_links,
    doctype,
    element_count,
    element_ids,
    headings,
    texts,
    texts_after,
)
from tests._plotly_figure import annotations_by_text
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results
from tests._web_app import database_of
from tests._web_runs import store_fleet_run, store_home_run


def _home_config(name: str, *, battery_config: BatteryConfig | None = None) -> HomeConfig:
    """The 4 kW PV, 3500 kWh home named *name* that the page tests save, with *battery_config*'s battery, none by default."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3500),
        battery_config=battery_config,
        name=name,
    )


def _save_home_run(
    storage: RunStorage,
    name: str,
    results: SimulationResults,
    *,
    created_at: str | None = None,
    status: RunStatus = "completed",
    battery_config: BatteryConfig | None = None,
) -> str:
    """Save *results* to *storage* as a home run named *name*, as a finished job saves its run; return its run id.

    The run's home is _home_config's, with *battery_config*'s battery, none by default.
    *created_at*, an ISO timestamp, is the creation time the run is recorded with; it defaults to now.
    *status* is the status the run is recorded with; it defaults to completed.
    """
    run_id = str(uuid.uuid4())
    store_home_run(
        storage,
        run_id,
        _home_config(name, battery_config=battery_config),
        results,
        name=name,
        status=status,
        created_at=created_at,
    )
    return run_id


def _save_fleet_run(
    storage: RunStorage,
    name: str,
    per_home_results: list[SimulationResults],
    *,
    created_at: str | None = None,
) -> str:
    """Save a completed fleet run named *name* to *storage*, one home per item of *per_home_results*, as a finished job does; return its run id.

    *created_at*, an ISO timestamp, is the creation time the run is recorded with; it defaults to now.
    """
    run_id = str(uuid.uuid4())
    store_fleet_run(
        storage,
        run_id,
        FleetResults(
            per_home_results=per_home_results,
            home_configs=[_home_config(f"{name} home {number}") for number in range(1, len(per_home_results) + 1)],
        ),
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
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """GET / with saved runs renders the Recent Runs table, one row per run showing its name, and no empty-state message."""
        run_names = ("North Roof", "South Roof")
        for run_name in run_names:
            _save_home_run(storage, run_name, make_sinusoidal_sim_results(days=1))
        response = client.get("/")
        page = response.get_data(as_text=True)
        page_texts = texts(page)
        assert "recent-runs-table" in element_ids(page)
        assert counts_of(page_texts, run_names) == dict.fromkeys(run_names, 1)
        assert "No simulation runs yet." not in page_texts

    def test_dashboard_recent_runs_table_rows_show_each_run_newest_first(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """GET / lists the saved runs newest first by creation time in the Recent Runs table: each row reads the run's name, type, date and status, and its name links to the run's one results page, /results/<run_id>, whatever its kind."""
        results = make_sinusoidal_sim_results(days=1)
        fleet_run_id = _save_fleet_run(
            storage, "Community Fleet", [results, results], created_at="2024-06-02T09:00:00+00:00"
        )
        failed_run_id = _save_home_run(
            storage, "South Roof", results, created_at="2024-06-03T09:00:00+00:00", status="failed"
        )
        home_run_id = _save_home_run(storage, "North Roof", results, created_at="2024-06-01T09:00:00+00:00")
        response = client.get("/")
        page = response.get_data(as_text=True)
        assert texts_after(page, "Status", 12) == [
            "South Roof", "home", "2024-06-03", "failed",
            "Community Fleet", "fleet", "2024-06-02", "completed",
            "North Roof", "home", "2024-06-01", "completed",
        ]
        link_by_name = {
            "South Roof": f"/results/{failed_run_id}",
            "Community Fleet": f"/results/{fleet_run_id}",
            "North Roof": f"/results/{home_run_id}",
        }
        for name, link in link_by_name.items():
            assert element_count(page, "a", {"href": link}) == 1, name

    def test_dashboard_stats_count_and_total_only_the_completed_runs(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """GET / reads Total Runs as the completed runs, Homes Simulated as their homes, each home of a fleet run counted, and Energy Modelled as those homes' total generation in MWh; a failed run adds to none of them."""
        results = make_sinusoidal_sim_results(days=1)
        _save_home_run(storage, "North Roof", results)
        _save_fleet_run(storage, "Community Fleet", [results, results])
        _save_home_run(storage, "South Roof", results, status="failed")
        response = client.get("/")
        page = response.get_data(as_text=True)
        completed_homes = 3
        completed_homes_generation_mwh = completed_homes * calculate_summary(results).total_generation_kwh / 1000
        assert texts_after(page, "Total Runs", 1) == ["2"]
        assert texts_after(page, "Homes Simulated", 1) == [str(completed_homes)]
        assert texts_after(page, "Energy Modelled", 2) == [str(round(completed_homes_generation_mwh, 2)), "MWh"]

    def test_dashboard_stats_count_a_completed_run_whose_summary_does_not_decode_but_leave_out_its_generation(
        self, storage: RunStorage, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One damaged run does not fail the dashboard: it counts in Total Runs and Homes Simulated, Energy Modelled leaves its generation out, and a warning names it (the G7 waiver in docs/prds/run-store-one-owner.md)."""
        results = make_sinusoidal_sim_results(days=1)
        _save_home_run(storage, "North Roof", results)
        _save_fleet_run(storage, "Community Fleet", [results, results])
        damaged_run_id = _save_home_run(storage, "Damaged Roof", results)
        with storage.database.transaction() as conn:
            conn.execute("UPDATE runs SET summary_json = ? WHERE id = ?", ("{not json", damaged_run_id))
        caplog.set_level(logging.WARNING, logger="solar_challenge.web.storage")

        response = client.get("/")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        readable_homes_generation_mwh = 3 * calculate_summary(results).total_generation_kwh / 1000
        assert texts_after(page, "Total Runs", 1) == ["3"]
        assert texts_after(page, "Homes Simulated", 1) == ["4"]
        assert texts_after(page, "Energy Modelled", 2) == [str(round(readable_homes_generation_mwh, 2)), "MWh"]
        assert [record.levelno for record in caplog.records if damaged_run_id in record.getMessage()] == [
            logging.WARNING
        ]


class TestSidebarCurrentPage:
    """Which sidebar link each page marks as the current page, with aria-current="page", in each of its two sidebars, desktop and mobile."""

    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("/", id="dashboard"),
            pytest.param("/simulate/home", id="single-home"),
            pytest.param("/simulate/fleet", id="fleet"),
            pytest.param("/scenarios/builder", id="builder"),
            pytest.param("/scenarios/sweep", id="sweeps"),
            pytest.param("/history/runs", id="runs"),
            pytest.param("/history/compare", id="compare"),
            pytest.param("/assistant/", id="ai-assistant"),
        ],
    )
    def test_each_sidebar_page_marks_its_own_link_current_in_both_sidebars(
        self, client: FlaskClient, url: str
    ) -> None:
        """GET of each page the sidebar links to marks that page's link, and no other link, as the current page in each of its two sidebars, desktop and mobile."""
        response = client.get(url)
        assert response.status_code == 200
        assert current_page_links(response.get_data(as_text=True)) == [url, url]

    def test_the_layout_marks_the_link_of_the_endpoint_the_request_is_routed_to_with_nothing_from_the_view(
        self, app: Flask
    ) -> None:
        """base.html, rendered with no context for a request routed to the fleet page, marks the Fleet link in both sidebars: the sidebar takes the current page from the request, needing no identifier from the view that renders it."""
        with app.test_request_context("/simulate/fleet"):
            page = render_template("base.html")
        assert current_page_links(page) == ["/simulate/fleet", "/simulate/fleet"]

    def test_the_404_page_marks_no_link_current(self, client: FlaskClient) -> None:
        """GET of a URL no page is routed to answers the 404 page, which marks no sidebar link as the current page."""
        response = client.get("/nonexistent")
        assert response.status_code == 404
        assert current_page_links(response.get_data(as_text=True)) == []

    def test_the_500_page_marks_the_link_of_the_page_the_failed_request_was_routed_to(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """When the dashboard cannot read its runs, GET / answers the 500 page, which marks the Dashboard link as the current page in both sidebars: the request was routed to the dashboard, and the browser is still at its URL."""
        with database_of(app).transaction() as conn:
            conn.execute("DROP TABLE runs")
        app.config["PROPAGATE_EXCEPTIONS"] = False
        response = client.get("/")
        assert response.status_code == 500
        assert current_page_links(response.get_data(as_text=True)) == ["/", "/"]

    def test_the_home_results_page_marks_no_link_current(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """A saved home run's results page, which no sidebar link leads to, marks no sidebar link as the current page."""
        run_id = _save_home_run(storage, "North Roof", make_sinusoidal_sim_results(days=1))
        response = client.get(f"/results/{run_id}")
        assert response.status_code == 200
        assert current_page_links(response.get_data(as_text=True)) == []

    def test_the_fleet_results_page_marks_no_link_current(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """A saved fleet run's results page, which no sidebar link leads to, marks no sidebar link as the current page."""
        results = make_sinusoidal_sim_results(days=1)
        run_id = _save_fleet_run(storage, "Community Fleet", [results, results])
        response = client.get(f"/results/{run_id}")
        assert response.status_code == 200
        assert current_page_links(response.get_data(as_text=True)) == []


class TestHomeResultsRoute:
    """Tests for the GET /results/<run_id> route, of a home run."""

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
        response = client.get(f"/results/{run_id}", follow_redirects=True)

        assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
        assert "Run not found." in texts(response.get_data(as_text=True))

    def test_home_results_after_simulation(self, storage: RunStorage, client: FlaskClient) -> None:
        """A saved run's results page renders its Overview charts and energy totals.

        Both Overview chart containers are elements of the page, and the Total
        Generation and Total Demand cards read the saved summary's totals in kWh.
        """
        results = make_sinusoidal_sim_results(days=1)
        run_id = _save_home_run(storage, "Test Run", results)
        summary = calculate_summary(results)

        response = client.get(f"/results/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert {"chart-sankey", "chart-daily-balance"} <= element_ids(page)
        for label, total_kwh in (
            ("Total Generation", summary.total_generation_kwh),
            ("Total Demand", summary.total_demand_kwh),
        ):
            assert texts_after(page, label, 2) == [f"{total_kwh:.1f}", "kWh"], label

    def test_home_results_stat_cards_round_each_saved_total_and_ratio_once(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Each stat card rounds its saved value once, to the card's own precision.

        The run self-consumes 10 kWh, exports 9.046 kWh and imports 5.749 kWh in its one day.
        Each card below sits where rounding its value to 2 dp first (a ratio to 4 dp) would
        move the card's last digit: 9.046 kWh would show 9.1.
        """
        run_id = _save_home_run(
            storage,
            "North Roof",
            make_sim_results(self_kwh=10.0, export_kwh=9.046, import_kwh=5.749, days=1),
        )
        response = client.get(f"/results/{run_id}")
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
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Renaming a run in Run History retitles its results page.

        The run's home keeps the name it was saved with, so the page reads the run's name, not its home's.
        """
        run_id = _save_home_run(storage, "North Roof", make_sinusoidal_sim_results(days=1))
        rename = client.patch(f"/api/history/runs/{run_id}", json={"name": "South Roof"})
        assert rename.status_code == 200

        response = client.get(f"/results/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert headings(page)[0] == "South Roof"
        assert "Results: South Roof - Solar Challenge" in texts(page)

    def test_home_results_battery_soc_chart_marks_the_saved_batterys_soc_limits(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """10% and 95% of an 8 kWh battery at 90% SoH are 0.72 and 6.84 kWh, where 10% and 90% of its nameplate would be 0.8 and 7.2."""
        run_id = _save_home_run(
            storage,
            "North Roof",
            make_sinusoidal_sim_results(days=1),
            battery_config=BatteryConfig(
                capacity_kwh=8.0, min_soc_fraction=0.1, max_soc_fraction=0.95, soh=0.9
            ),
        )

        response = client.get(f"/results/{run_id}")

        assert response.status_code == 200
        figure = chart_figures(response.get_data(as_text=True))["chart-battery-soc"]
        assert {
            text: annotation["y"]
            for text, annotation in annotations_by_text(figure).items()
        } == pytest.approx({"Min SOC": 0.72, "Max SOC": 6.84})


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
