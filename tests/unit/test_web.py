"""Tests for the Flask web dashboard module."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytest.importorskip("flask")
import pandas as pd
from flask import Flask
from flask.testing import FlaskClient

from tests._html_page import (
    doctype,
    element_count,
    element_ids,
    headings,
    texts,
    texts_after,
)
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
        page_texts = texts(page)
        texts_per_label = {label: page_texts.count(label) for label in labels}
        assert texts_per_label == dict.fromkeys(labels, 2)

    def test_dashboard_contains_quick_start_cards(self, client: FlaskClient) -> None:
        """GET / renders one heading per quick-start card: Run Single Home, Run Fleet Simulation and Build Scenario."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        titles = ("Run Single Home", "Run Fleet Simulation", "Build Scenario")
        page_headings = headings(page)
        headings_per_title = {title: page_headings.count(title) for title in titles}
        assert headings_per_title == dict.fromkeys(titles, 1)

    def test_dashboard_contains_stats_section(self, client: FlaskClient) -> None:
        """GET / renders one label per aggregate stat: Total Runs, Homes Simulated and Energy Modelled."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        labels = ("Total Runs", "Homes Simulated", "Energy Modelled")
        page_texts = texts(page)
        texts_per_label = {label: page_texts.count(label) for label in labels}
        assert texts_per_label == dict.fromkeys(labels, 1)

    def test_dashboard_contains_recent_runs_section(self, client: FlaskClient) -> None:
        """GET / with no saved runs renders the Recent Runs heading and its empty-state message."""
        response = client.get("/")
        page = response.get_data(as_text=True)
        assert headings(page).count("Recent Runs") == 1
        assert texts(page).count("No simulation runs yet.") == 1


class TestSimulateHomeRoute:
    """Tests for the GET /simulate/home route."""

    def test_simulate_home_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/home returns HTTP 200."""
        response = client.get("/simulate/home")
        assert response.status_code == 200

    def test_simulate_home_page_contains_form(self, client: FlaskClient) -> None:
        """GET /simulate/home renders the PV capacity, battery capacity and annual consumption inputs, and one submit button."""
        response = client.get("/simulate/home")
        page = response.get_data(as_text=True)
        assert {"pv_kw", "battery_kwh", "consumption_kwh"} <= element_ids(page)
        assert element_count(page, "button", {"type": "submit"}) == 1

    def test_simulate_home_page_contains_tabs(self, client: FlaskClient) -> None:
        """GET /simulate/home renders one tab list and, per tab, one panel shown while it is active."""
        response = client.get("/simulate/home")
        page = response.get_data(as_text=True)
        assert element_count(page, "nav", {"role": "tablist"}) == 1
        tab_ids = ("pv", "battery", "load", "heat_pump", "tariff", "location", "period")
        panels_per_tab = {
            tab_id: element_count(
                page, "div", {"role": "tabpanel", "x-show": f"activeTab === '{tab_id}'"}
            )
            for tab_id in tab_ids
        }
        assert panels_per_tab == dict.fromkeys(tab_ids, 1)


# ---------------------------------------------------------------------------
# Helpers for chart / results tests
# ---------------------------------------------------------------------------

def _make_sim_results(days: int = 3) -> "SimulationResults":
    """Create a minimal SimulationResults object for testing.

    Builds synthetic 1-minute resolution time series spanning the
    requested number of days, suitable for exercising chart functions.

    Args:
        days: Number of simulation days.

    Returns:
        SimulationResults with simple but valid data.
    """
    import numpy as np
    from solar_challenge.home import SimulationResults as SR

    freq = "min"
    index = pd.date_range("2024-06-01", periods=days * 1440, freq=freq, tz="Europe/London")

    # Simple synthetic profiles (sinusoidal generation, flat demand)
    hours = np.arange(len(index)) / 60.0
    generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
    demand = np.full(len(index), 0.5)
    self_consumption = np.minimum(generation, demand)
    grid_import = np.maximum(0, demand - generation)
    grid_export = np.maximum(0, generation - demand)
    battery_charge = np.zeros(len(index))
    battery_discharge = np.zeros(len(index))
    battery_soc = np.zeros(len(index))

    def _series(values: np.ndarray, name: str) -> pd.Series:
        return pd.Series(values, index=index, name=name)

    return SR(
        generation=_series(generation, "generation_kw"),
        demand=_series(demand, "demand_kw"),
        self_consumption=_series(self_consumption, "self_consumption_kw"),
        battery_charge=_series(battery_charge, "battery_charge_kw"),
        battery_discharge=_series(battery_discharge, "battery_discharge_kw"),
        battery_soc=_series(battery_soc, "battery_soc_kwh"),
        grid_import=_series(grid_import, "grid_import_kw"),
        grid_export=_series(grid_export, "grid_export_kw"),
        import_cost=_series(np.zeros(len(index)), "import_cost_gbp"),
        export_revenue=_series(np.zeros(len(index)), "export_revenue_gbp"),
        tariff_rate=_series(np.zeros(len(index)), "tariff_rate_per_kwh"),
        strategy_name="self_consumption",
    )


def _make_summary_dict() -> dict:
    """Return a minimal summary dictionary for testing sankey_diagram."""
    return {
        "total_generation_kwh": 100.0,
        "total_demand_kwh": 80.0,
        "total_self_consumption_kwh": 50.0,
        "total_grid_import_kwh": 30.0,
        "total_grid_export_kwh": 40.0,
        "total_battery_charge_kwh": 10.0,
        "total_battery_discharge_kwh": 8.0,
        "peak_generation_kw": 4.0,
        "peak_demand_kw": 2.5,
        "self_consumption_ratio": 0.5,
        "grid_dependency_ratio": 0.375,
        "export_ratio": 0.4,
        "simulation_days": 3,
    }


class TestChartFunctions:
    """Tests for the centralized chart functions in charts.py."""

    def test_daily_energy_balance_returns_json(self) -> None:
        """Test daily_energy_balance returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import daily_energy_balance

        results = _make_sim_results(days=3)
        output = daily_energy_balance(results)
        assert isinstance(output, str)
        assert len(output) > 2  # more than just "{}"
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_sankey_returns_json(self) -> None:
        """Test sankey_diagram returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import sankey_diagram

        summary = _make_summary_dict()
        output = sankey_diagram(summary)
        assert isinstance(output, str)
        assert len(output) > 2
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_power_flow_timeline_returns_json(self) -> None:
        """Test power_flow_timeline returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import power_flow_timeline

        results = _make_sim_results(days=2)
        output = power_flow_timeline(results)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_battery_soc_chart_returns_json(self) -> None:
        """Test battery_soc_chart returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import battery_soc_chart

        results = _make_sim_results(days=2)
        output = battery_soc_chart(results, battery_capacity_kwh=10.0)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_financial_breakdown_returns_json(self) -> None:
        """Test financial_breakdown returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import financial_breakdown

        results = _make_sim_results(days=3)
        output = financial_breakdown(results)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_monthly_summary_returns_none_for_short_sim(self) -> None:
        """Test monthly_summary returns None when simulation < 90 days."""
        from solar_challenge.web.charts import monthly_summary

        results = _make_sim_results(days=30)
        output = monthly_summary(results)
        assert output is None

    def test_seasonal_comparison_returns_none_for_short_sim(self) -> None:
        """Test seasonal_comparison returns None when simulation < 180 days."""
        from solar_challenge.web.charts import seasonal_comparison

        results = _make_sim_results(days=60)
        output = seasonal_comparison(results)
        assert output is None

    def test_heat_pump_analysis_returns_none_without_hp(self) -> None:
        """Test heat_pump_analysis returns None when no heat pump data."""
        from solar_challenge.web.charts import heat_pump_analysis

        results = _make_sim_results(days=2)
        output = heat_pump_analysis(results)
        assert output is None

    def test_adaptive_downsample_preserves_small_data(self) -> None:
        """Test _adaptive_downsample returns data unchanged when small."""
        from solar_challenge.web.charts import _adaptive_downsample

        index = pd.date_range("2024-01-01", periods=100, freq="min")
        df = pd.DataFrame({"a": range(100)}, index=index)
        result = _adaptive_downsample(df, max_points=200)
        assert len(result) == 100

    def test_adaptive_downsample_reduces_large_data(self) -> None:
        """Test _adaptive_downsample reduces rows for large data."""
        from solar_challenge.web.charts import _adaptive_downsample

        index = pd.date_range("2024-01-01", periods=10000, freq="min")
        df = pd.DataFrame({"a": range(10000)}, index=index)
        result = _adaptive_downsample(df, max_points=500)
        assert len(result) < 10000


class TestHomeResultsRoute:
    """Tests for the GET /results/home/<run_id> route."""

    def test_home_results_unknown_run_redirects(self, client: FlaskClient) -> None:
        """Test accessing results for a non-existent run redirects."""
        response = client.get("/results/home/nonexistent-id")
        assert response.status_code in (302, 404)

    def test_home_results_after_simulation(self, app: Flask, client: FlaskClient) -> None:
        """A saved run's results page renders its Overview charts and energy totals.

        Both Overview chart containers are elements of the page, and the Total
        Generation and Total Demand cards read the saved summary's totals in kWh.
        """
        import uuid
        from solar_challenge.home import HomeConfig, calculate_summary
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig
        from solar_challenge.web.storage import RunStorage

        # Create a test run directly via storage
        run_id = str(uuid.uuid4())
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500),
            name="Test Run",
        )
        results = _make_sim_results(days=1)
        summary = calculate_summary(results)

        with app.app_context():
            storage = RunStorage(
                db_path=app.config["DATABASE"],
                data_dir=app.config["DATA_DIR"],
            )
            storage.save_home_run(
                run_id=run_id,
                config=config,
                results=results,
                summary=summary,
                name="Test Run",
            )

        response = client.get(f"/results/home/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert {"chart-sankey", "chart-daily-balance"} <= element_ids(page)
        for label, total_kwh in (
            ("Total Generation", summary.total_generation_kwh),
            ("Total Demand", summary.total_demand_kwh),
        ):
            assert texts_after(page, label, 2) == [f"{total_kwh:.1f}", "kWh"], label


class TestFleetConfigRoute:
    """Tests for the GET /simulate/fleet route."""

    def test_fleet_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet returns HTTP 200."""
        response = client.get("/simulate/fleet")
        assert response.status_code == 200

    def test_fleet_page_contains_distribution_editors(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders three distribution editors, one per card, and the n_homes input."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "dist.type"}) == 3
        assert "n_homes" in element_ids(page)

    def test_fleet_page_contains_pv_battery_load_sections(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders one heading per distribution card: PV Capacity, Battery Capacity and Annual Consumption."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        subjects = ("PV Capacity", "Battery Capacity", "Annual Consumption")
        page_headings = headings(page)
        headings_per_subject = {subject: page_headings.count(subject) for subject in subjects}
        assert headings_per_subject == dict.fromkeys(subjects, 1)

    def test_fleet_page_contains_action_buttons(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders the Import YAML and Export YAML controls and one button that runs the fleet simulation."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        page_texts = texts(page)
        assert page_texts.count("Import YAML") == 1
        assert element_count(page, "input", {"type": "file", "@change": "importYaml($event)"}) == 1
        assert page_texts.count("Export YAML") == 1
        assert element_count(page, "button", {"@click": "exportYaml()"}) == 1
        assert element_count(page, "button", {"@click": "submitFleet()"}) == 1

    def test_fleet_page_has_correct_page_identifier(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders the sidebar with the simulate-fleet page identifier, so the Simulate group's links show on this page."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        simulate_links_condition = (
            "(openGroup === 'simulate' || 'simulate-fleet'.startsWith('simulate')) && sidebarOpen"
        )
        assert element_count(page, "div", {"x-show": simulate_links_condition}) == 1


VALID_DISTRIBUTION_FORM: dict = {
    "n_homes": 2,
    "seed": 1,
    "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
    "battery": {"capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0}},
    "load": {"annual_consumption_kwh": 3500.0},
}


class TestFleetConfigHelpers:
    """Tests for fleet_config.py helper functions."""

    def test_sample_distribution_normal(self) -> None:
        """Test normal distribution sampling produces correct count and bounds."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}
        )
        assert len(samples) == 100
        assert all(1.0 <= s <= 8.0 for s in samples)

    def test_sample_distribution_normal_custom_count(self) -> None:
        """Test normal distribution with custom n_samples."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}, n_samples=50
        )
        assert len(samples) == 50

    def test_sample_distribution_uniform(self) -> None:
        """Test uniform distribution sampling produces correct count and bounds."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution("uniform", {"min": 2.0, "max": 6.0})
        assert len(samples) == 100
        assert all(2.0 <= s <= 6.0 for s in samples)

    def test_sample_distribution_weighted_discrete(self) -> None:
        """Test weighted discrete distribution sampling."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "weighted_discrete",
            {"values": [{"value": 3.0, "weight": 50}, {"value": 5.0, "weight": 50}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_shuffled_pool(self) -> None:
        """Test shuffled pool distribution sampling."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "shuffled_pool",
            {"entries": [{"value": 3.0, "count": 30}, {"value": 5.0, "count": 70}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_unknown_type_raises(self) -> None:
        """Test that unknown distribution type raises ValueError."""
        from solar_challenge.web.fleet_config import sample_distribution

        with pytest.raises(ValueError, match="Unknown distribution type"):
            sample_distribution("bogus", {})

    @pytest.mark.parametrize(
        ("dist_type", "params", "message"),
        [
            pytest.param(
                "normal", "x", "params must be a mapping, got str", id="normal-str-params"
            ),
            pytest.param(
                "uniform",
                [2.0, 6.0],
                "params must be a mapping, got list",
                id="uniform-list-params",
            ),
            pytest.param(
                "normal", None, "params must be a mapping, got NoneType", id="normal-null-params"
            ),
            pytest.param(
                "weighted_discrete",
                {"values": ["x"]},
                "values[0] must be a mapping, got str",
                id="weighted-discrete-str-row",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": [{"value": 3.0, "count": 1}, 1]},
                "entries[1] must be a mapping, got int",
                id="shuffled-pool-int-row-after-a-valid-one",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": "ab"},
                "values must be a list, got str",
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": {"value": 3.0}},
                "entries must be a list, got dict",
                id="shuffled-pool-object-entries",
            ),
        ],
    )
    def test_sample_distribution_refuses_malformed_params(
        self, dist_type: str, params: object, message: str
    ) -> None:
        """Params that are not a mapping, a row that is not a mapping, or a row list that is not a list, is refused, naming it and the type sent."""
        from solar_challenge.web.fleet_config import sample_distribution

        with pytest.raises(ValueError, match=re.escape(message)):
            sample_distribution(dist_type, params)

    def test_form_to_fleet_distribution_config(self) -> None:
        """Test converting form data to fleet distribution config."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        form_data = {
            "n_homes": 50,
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
        }
        config = form_to_fleet_distribution_config(form_data)
        assert config["n_homes"] == 50
        assert "pv" in config
        assert "load" in config

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("pv", "x", id="pv-str"),
            pytest.param("pv", [4.0], id="pv-list"),
            pytest.param("battery", "x", id="battery-str"),
            pytest.param("battery", True, id="battery-bool"),
            pytest.param("load", "x", id="load-str"),
            pytest.param("load", 3500, id="load-int"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_non_mapping_component_block(
        self, key: str, value: object
    ) -> None:
        """A truthy pv/battery/load block that is not a mapping is refused, naming the block and the type sent."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        with pytest.raises(
            ValueError, match=re.escape(f"{key} must be a mapping, got {type(value).__name__}")
        ):
            form_to_fleet_distribution_config({**VALID_DISTRIBUTION_FORM, key: value})

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("pv", None, id="pv-null"),
            pytest.param("pv", "", id="pv-empty-string"),
            pytest.param("battery", None, id="battery-null"),
            pytest.param("battery", False, id="battery-false"),
            pytest.param("load", None, id="load-null"),
            pytest.param("load", [], id="load-empty-list"),
        ],
    )
    def test_form_to_fleet_distribution_config_reads_a_falsy_component_block_as_absent(
        self, key: str, value: object
    ) -> None:
        """A falsy pv/battery/load block converts exactly as if the block were left out."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        without_block = {k: v for k, v in VALID_DISTRIBUTION_FORM.items() if k != key}
        assert form_to_fleet_distribution_config(
            {**VALID_DISTRIBUTION_FORM, key: value}
        ) == form_to_fleet_distribution_config(without_block)

    @pytest.mark.parametrize(
        ("spec", "converted"),
        [
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2}, {"value": 5.0}],
                },
                {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [2.0, 1.0]},
                id="weighted-discrete",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3.0, "count": 2}, {"value": 5.0}],
                },
                {"type": "shuffled_pool", "values": [3.0, 5.0], "counts": [2, 1]},
                id="shuffled-pool",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_converts_distribution_rows(
        self, spec: dict, converted: dict
    ) -> None:
        """A weighted_discrete/shuffled_pool row list converts to parallel value and weight/count lists, a missing weight or count reading as 1."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        config = form_to_fleet_distribution_config(
            {**VALID_DISTRIBUTION_FORM, "pv": {"capacity_kw": spec}}
        )
        assert config["pv"] == {"capacity_kw": converted}

    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            pytest.param(
                {"type": "weighted_discrete", "values": ["x"]},
                "values[0] must be a mapping, got str",
                id="weighted-discrete-str-row",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [{"value": 4.0, "weight": 1}, 3500]},
                "values[1] must be a mapping, got int",
                id="weighted-discrete-int-row-after-a-valid-one",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [1]},
                "entries[0] must be a mapping, got int",
                id="shuffled-pool-int-row",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [[4.0, 2]]},
                "entries[0] must be a mapping, got list",
                id="shuffled-pool-list-row",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": "ab"},
                "values must be a list, got str",
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": {"value": 4.0}},
                "values must be a list, got dict",
                id="weighted-discrete-object-values",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": None},
                "entries must be a list, got NoneType",
                id="shuffled-pool-null-entries",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_malformed_distribution_rows(
        self, spec: dict, message: str
    ) -> None:
        """A weighted_discrete/shuffled_pool row that is not a mapping, or a row list that is not a list, is refused, naming it and the type sent."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        with pytest.raises(ValueError, match=re.escape(message)):
            form_to_fleet_distribution_config(
                {**VALID_DISTRIBUTION_FORM, "pv": {"capacity_kw": spec}}
            )

    def test_fleet_distribution_to_yaml(self) -> None:
        """Test converting fleet config to YAML string."""
        from solar_challenge.web.fleet_config import fleet_distribution_to_yaml

        config = {
            "n_homes": 100,
            "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
            "load": {"annual_consumption_kwh": {"type": "uniform", "min": 2000, "max": 5000}},
        }
        yaml_str = fleet_distribution_to_yaml(config)
        assert "n_homes: 100" in yaml_str
        assert isinstance(yaml_str, str)

    def test_yaml_to_fleet_distribution(self) -> None:
        """Test parsing YAML string to fleet distribution config."""
        from solar_challenge.web.fleet_config import yaml_to_fleet_distribution

        yaml_str = """
fleet_distribution:
  n_homes: 100
  pv:
    capacity_kw:
      type: normal
      mean: 4.0
      std: 1.0
  load:
    annual_consumption_kwh:
      type: uniform
      min: 2000
      max: 5000
"""
        config = yaml_to_fleet_distribution(yaml_str)
        assert config["n_homes"] == 100
        assert "pv" in config
        assert "load" in config

    def test_yaml_to_fleet_distribution_invalid_raises(self) -> None:
        """Test that invalid YAML raises ValueError."""
        from solar_challenge.web.fleet_config import yaml_to_fleet_distribution

        with pytest.raises(ValueError):
            yaml_to_fleet_distribution("not: a: valid: fleet: config")

    def test_yaml_roundtrip(self) -> None:
        """Test that export/import YAML round-trips correctly."""
        from solar_challenge.web.fleet_config import (
            fleet_distribution_to_yaml,
            yaml_to_fleet_distribution,
        )

        original = {
            "n_homes": 50,
            "seed": 42,
            "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
            "load": {"annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800}},
        }
        yaml_str = fleet_distribution_to_yaml(original)
        restored = yaml_to_fleet_distribution(yaml_str)
        assert restored["n_homes"] == 50
        assert restored["pv"]["capacity_kw"]["type"] == "uniform"
        assert restored["load"]["annual_consumption_kwh"]["type"] == "normal"


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

    def test_export_fleet_yaml(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/export-yaml returns YAML content."""
        response = client.post(
            "/api/fleet/export-yaml",
            json={
                "n_homes": 100,
                "pv": {"capacity_kw": {"type": "uniform", "min": 3, "max": 6}},
            },
        )
        assert response.status_code == 200
        assert "text/yaml" in response.content_type
        assert b"n_homes" in response.data

    def test_import_fleet_yaml(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/import-yaml parses YAML correctly."""
        yaml_content = """
fleet_distribution:
  n_homes: 50
  pv:
    capacity_kw:
      type: normal
      mean: 4.0
      std: 1.0
"""
        response = client.post(
            "/api/fleet/import-yaml",
            data=yaml_content,
            content_type="text/yaml",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["n_homes"] == 50

    def test_import_fleet_yaml_invalid(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/import-yaml with invalid YAML returns 400."""
        response = client.post(
            "/api/fleet/import-yaml",
            data="just: some: random: yaml",
            content_type="text/yaml",
        )
        assert response.status_code == 400


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


class TestSimulateHomePageRendering:
    """Tests for the /simulate/home page rendering quality."""

    def test_simulate_home_no_raw_js_in_body(self, client: FlaskClient) -> None:
        """Test /simulate/home does not expose raw JavaScript in the page body.

        JavaScript should be contained within <script> tags, not visible
        as text content in the rendered HTML body.
        """
        response = client.get("/simulate/home")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # The page uses Alpine.js. Check that raw JS function bodies are not
        # leaked outside of <script> tags. We do this by checking that certain
        # JS-only patterns don't appear outside <script> blocks.

        # Remove all script blocks first, then check remaining HTML body
        import re
        # Remove all script tag contents
        body_without_scripts = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            html,
            flags=re.DOTALL,
        )

        # These are JS-specific patterns that should NOT appear in visible body text
        assert "function()" not in body_without_scripts, (
            "Raw 'function()' found outside <script> tags"
        )
        assert "async () =>" not in body_without_scripts, (
            "Raw arrow function found outside <script> tags"
        )
        assert "addEventListener" not in body_without_scripts, (
            "Raw 'addEventListener' found outside <script> tags"
        )

    def test_simulate_home_has_proper_html_structure(self, client: FlaskClient) -> None:
        """Test /simulate/home has proper HTML document structure."""
        response = client.get("/simulate/home")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # Should have a proper HTML document
        assert doctype(html) == "html"
        assert element_count(html, "head") == 1
        assert element_count(html, "body") == 1
