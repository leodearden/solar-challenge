"""Tests for fleet chart functions and fleet results route."""

import json
import uuid
from pathlib import Path

import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.web.charts import fleet_aggregate_timeline, fleet_grid_impact
from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage

from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import headings, texts, texts_after
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


def _save_fleet_run(app: Flask, fleet: FleetResults, name: str | None = None) -> str:
    """Save *fleet* to *app*'s store as a completed fleet run named *name*, as a finished job saves it; return its run id."""
    run_id = str(uuid.uuid4())
    RunStorage(db_path=app.config["DATABASE"], data_dir=app.config["DATA_DIR"]).save_fleet_run(
        run_id=run_id,
        fleet_results=fleet,
        fleet_summary=calculate_fleet_summary(fleet),
        per_home_summaries=[calculate_summary(results) for results in fleet.per_home_results],
        name=name,
    )
    return run_id


def _one_day_homes(n_homes: int) -> list[SimulationResults]:
    """The first *n_homes* of two one-day homes: a net exporter, then a net importer.

    Every flow the fleet charts draw is non-zero in both homes, so adding the second changes each of the fleet's totals.
    """
    net_exporter = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
    net_importer = make_sim_results(self_kwh=6.0, export_kwh=2.0, import_kwh=40.0, days=1)
    return [net_exporter, net_importer][:n_homes]


def _fleet_of(homes: list[SimulationResults]) -> FleetResults:
    """A fleet of *homes*, each paired with a default home config."""
    return FleetResults(per_home_results=list(homes), home_configs=[make_home_config() for _ in homes])


class TestFleetChartFunctions:
    """Tests for the fleet-specific chart functions in charts.py."""

    def test_fleet_heatmap_returns_json(self) -> None:
        """Test fleet_heatmap returns a valid non-empty JSON string."""
        from solar_challenge.web.charts import fleet_heatmap

        summaries = [
            {
                "total_generation_kwh": 100,
                "total_demand_kwh": 80,
                "total_self_consumption_kwh": 60,
                "total_grid_import_kwh": 20,
                "total_grid_export_kwh": 40,
            }
            for _ in range(5)
        ]
        result = fleet_heatmap(summaries)
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed

    def test_fleet_heatmap_limits_to_50_homes(self) -> None:
        """Test fleet_heatmap limits display to first 50 homes."""
        from solar_challenge.web.charts import fleet_heatmap

        summaries = [
            {
                "total_generation_kwh": 100 + i,
                "total_demand_kwh": 80,
                "total_self_consumption_kwh": 60,
                "total_grid_import_kwh": 20,
                "total_grid_export_kwh": 40,
            }
            for i in range(70)
        ]
        result = fleet_heatmap(summaries)
        assert result and result != "{}"
        parsed = json.loads(result)
        # The heatmap z data should have at most 50 rows
        z_data = parsed["data"][0]["z"]
        assert len(z_data) <= 50

    def test_fleet_box_plots_returns_json(self) -> None:
        """Test fleet_box_plots returns a valid non-empty JSON string."""
        from solar_challenge.web.charts import fleet_box_plots

        summaries = [
            {
                "total_generation_kwh": 100 + i * 10,
                "total_demand_kwh": 80 + i * 5,
                "total_self_consumption_kwh": 60 + i * 3,
                "total_grid_import_kwh": 20 + i * 2,
                "total_grid_export_kwh": 40 + i * 5,
            }
            for i in range(10)
        ]
        result = fleet_box_plots(summaries)
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed
        # Should have 5 box traces (one per metric)
        assert len(parsed["data"]) == 5

    def test_fleet_distribution_histograms_returns_json(self) -> None:
        """Test fleet_distribution_histograms returns a valid non-empty JSON string."""
        from solar_challenge.web.charts import fleet_distribution_histograms

        summaries = [
            {
                "total_generation_kwh": 100 + i * 10,
                "self_consumption_ratio": 0.5 + i * 0.02,
                "grid_dependency_ratio": 0.3 + i * 0.01,
            }
            for i in range(20)
        ]
        result = fleet_distribution_histograms(summaries)
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed
        # Should have 3 histogram traces
        assert len(parsed["data"]) == 3

    @pytest.mark.parametrize("n_homes", [1, 2], ids=["one-home", "two-homes"])
    def test_fleet_aggregate_timeline_draws_each_flow_summed_across_the_fleets_homes(
        self, n_homes: int
    ) -> None:
        """Each trace is that flow summed across the fleet's homes."""
        homes = _one_day_homes(n_homes)

        drawn = {
            trace["name"]: trace["y"]
            for trace in json.loads(fleet_aggregate_timeline(_fleet_of(homes)))["data"]
        }

        assert drawn == {
            "PV Generation": sum(home.generation for home in homes).round(4).tolist(),
            "Demand": sum(home.demand for home in homes).round(4).tolist(),
            "Self-Consumption": sum(home.self_consumption for home in homes).round(4).tolist(),
            "Grid Import": sum(home.grid_import for home in homes).round(4).tolist(),
            "Grid Export": sum(home.grid_export for home in homes).round(4).tolist(),
        }

    @pytest.mark.parametrize("n_homes", [1, 2], ids=["one-home", "two-homes"])
    def test_fleet_grid_impact_draws_the_fleets_summed_import_less_its_summed_export(
        self, n_homes: int
    ) -> None:
        """The net is the fleet's summed import less its summed export, so the two-home fleet draws an import although its first home alone exports."""
        homes = _one_day_homes(n_homes)
        net = sum(home.grid_import for home in homes) - sum(home.grid_export for home in homes)

        drawn = {
            trace["name"]: trace["y"]
            for trace in json.loads(fleet_grid_impact(_fleet_of(homes)))["data"]
        }

        assert drawn == {
            "Grid Import": net.clip(lower=0).round(4).tolist(),
            "Grid Export": net.clip(upper=0).round(4).tolist(),
        }


class TestFinancialBreakdownPricing:
    """Tests that financial_breakdown uses engine-priced series, not hardcoded rates."""

    def test_uses_engine_priced_series(self) -> None:
        """financial_breakdown must aggregate import_cost/export_revenue series directly."""
        import numpy as np
        import pandas as pd
        from solar_challenge.home import SimulationResults
        from solar_challenge.web.charts import financial_breakdown

        # ~2 days at 1-min resolution
        index = pd.date_range(
            "2024-06-01", periods=2 * 24 * 60, freq="min", tz="Europe/London"
        )
        n = len(index)
        hours = np.arange(n) / 60.0

        # Sinusoidal generation (3 kW peak), flat 0.5 kW demand
        generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
        demand = np.full(n, 0.5)
        self_consumption = np.minimum(generation, demand)
        grid_import = np.maximum(0, demand - generation)
        grid_export = np.maximum(0, generation - demand)

        # Engine-priced series: DELIBERATELY inconsistent with hardcoded 0.245/0.15
        # import: 0.30 GBP/kWh  (kW / 60 * rate = per-minute GBP)
        # export: 0.05 GBP/kWh  (realistic SEG, ~3x smaller than hardcoded 0.15)
        engine_import_cost = grid_import / 60 * 0.30
        engine_export_revenue = grid_export / 60 * 0.05

        def _s(v: np.ndarray, name: str) -> pd.Series:
            return pd.Series(v, index=index, name=name)

        zeros = np.zeros(n)
        results = SimulationResults(
            generation=_s(generation, "generation_kw"),
            demand=_s(demand, "demand_kw"),
            self_consumption=_s(self_consumption, "self_consumption_kw"),
            battery_charge=_s(zeros, "battery_charge_kw"),
            battery_discharge=_s(zeros, "battery_discharge_kw"),
            battery_soc=_s(zeros, "battery_soc_kwh"),
            grid_import=_s(grid_import, "grid_import_kw"),
            grid_export=_s(grid_export, "grid_export_kw"),
            import_cost=_s(engine_import_cost, "import_cost_gbp"),
            export_revenue=_s(engine_export_revenue, "export_revenue_gbp"),
            tariff_rate=_s(zeros, "tariff_rate_per_kwh"),
            strategy_name="self_consumption",
        )

        output = financial_breakdown(results)
        assert output and output != "{}"
        parsed = json.loads(output)
        traces = {t["name"]: t for t in parsed["data"]}

        # Expected daily totals from engine series (NO /60 division — already per-minute GBP)
        expected_revenue = results.export_revenue.resample("D").sum().round(2)
        expected_cost = results.import_cost.resample("D").sum().round(2)

        # (1) Chart totals must match engine series daily sums
        assert sum(traces["Daily Revenue"]["y"]) == pytest.approx(
            expected_revenue.sum(), abs=0.02
        ), "Daily Revenue total must come from engine export_revenue series"
        assert sum(traces["Daily Cost"]["y"]) == pytest.approx(
            expected_cost.sum(), abs=0.02
        ), "Daily Cost total must come from engine import_cost series"

        # (2) Behavioral guard: chart follows the engine's 0.05 export rate, NOT
        # the old hardcoded 0.15.  With engine_export_revenue = grid_export/60*0.05,
        # the chart total must be ~3x BELOW grid_export_kwh * 0.15.
        total_grid_export_kwh = results.grid_export.sum() / 60
        revenue_total = sum(traces["Daily Revenue"]["y"])
        assert revenue_total != pytest.approx(
            total_grid_export_kwh * 0.15, rel=0.1
        ), "Daily Revenue must not match old hardcoded 0.15 export rate"
        assert revenue_total < total_grid_export_kwh * 0.15 * 0.5, (
            "Daily Revenue must be substantially below the old 0.15 rate "
            "(engine uses 0.05 GBP/kWh, ~3x smaller)"
        )


class TestFleetResultsRoute:
    """Tests for the GET /results/fleet/<run_id> route."""

    @pytest.mark.parametrize(
        "run_id",
        [
            pytest.param("nonexistent-id", id="an-id-no-run-has"),
            pytest.param("bad.id", id="an-id-the-store-refuses"),
        ],
    )
    def test_fleet_results_unknown_run_redirects(self, client: FlaskClient, run_id: str) -> None:
        """The page of an id no run has redirects to the dashboard, which flashes Fleet run not found.

        'bad.id' is outside [A-Za-z0-9_-], so the store refuses it, and no run can have it.
        """
        response = client.get(f"/results/fleet/{run_id}", follow_redirects=True)

        assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
        assert "Fleet run not found." in texts(response.get_data(as_text=True))

    def test_fleet_results_route_exists(self, client: FlaskClient) -> None:
        """Test that the fleet results route is registered and accessible."""
        response = client.get("/results/fleet/some-fake-id")
        # Should redirect (302) because the run doesn't exist, but NOT 404
        # which would mean the route itself doesn't exist
        assert response.status_code == 302

    def test_fleet_results_page_shows_the_saved_fleet_summary_in_nine_stat_cards(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A saved two-home fleet run's results page shows nine stat cards, each reading the saved fleet summary.

        Each home self-consumes 18 kWh, exports 54 kWh and imports 27 kWh in its one day.
        """
        run_id = _save_fleet_run(
            app,
            make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
        )
        response = client.get(f"/results/fleet/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        expected_cards = {
            "Homes": ["2"],
            "Total Generation": ["144.0", "kWh"],
            "Total Demand": ["90.0", "kWh"],
            "Self-Consumption": ["36.0", "kWh"],
            "Grid Import": ["54.0", "kWh"],
            "Grid Export": ["108.0", "kWh"],
            "Fleet Self-Consumption": ["25", "%"],
            "Fleet Grid Dependency": ["60", "%"],
            "Simulation Days": ["1", "days"],
        }
        assert {
            label: texts_after(page, label, len(card))
            for label, card in expected_cards.items()
        } == expected_cards

    def test_fleet_results_stat_cards_round_each_saved_total_and_ratio_once(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Each stat card rounds the saved fleet summary's value once, to the card's own precision.

        Each of the two homes self-consumes 5 kWh, exports 4.523 kWh and imports 2.8745 kWh
        in its one day. Each card below sits where rounding its value to 2 dp first (a ratio
        to 4 dp) would move the card's last digit: the fleet's 9.046 kWh export would show 9.1.
        """
        run_id = _save_fleet_run(
            app,
            make_fleet_results(n_homes=2, self_kwh=5.0, export_kwh=4.523, import_kwh=2.8745, days=1),
        )
        response = client.get(f"/results/fleet/{run_id}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        expected_cards = {
            "Total Generation": ["19.0", "kWh"],
            "Total Demand": ["15.7", "kWh"],
            "Grid Import": ["5.7", "kWh"],
            "Grid Export": ["9.0", "kWh"],
            "Fleet Self-Consumption": ["53", "%"],
            "Fleet Grid Dependency": ["37", "%"],
        }
        assert {
            label: texts_after(page, label, len(card))
            for label, card in expected_cards.items()
        } == expected_cards

    def test_fleet_results_page_header_reads_the_saved_fleets_home_count_and_days(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """The header under the title reads the saved fleet's number of homes and simulated days."""
        run_id = _save_fleet_run(app, make_fleet_results(n_homes=3, days=2))

        response = client.get(f"/results/fleet/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert f"3 homes — 2-day simulation — Run ID: {run_id[:8]}…" in texts(page)

    def test_fleet_results_page_is_titled_with_the_name_its_run_was_saved_under(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """The page's h1 and its document title name the run as Run History lists it.

        The name's markup characters show as text.
        """
        run_id = _save_fleet_run(
            app, make_fleet_results(n_homes=2, days=1), name="Phase 1 <South> & Co"
        )

        response = client.get(f"/results/fleet/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert headings(page)[0] == "Phase 1 <South> & Co"
        assert "Results: Phase 1 <South> & Co - Solar Challenge" in texts(page)

    def test_fleet_results_page_title_follows_a_run_history_rename(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Renaming a run in Run History retitles its results page."""
        run_id = _save_fleet_run(
            app, make_fleet_results(n_homes=2, days=1), name="Probe Fleet Run"
        )
        rename = client.patch(f"/api/history/runs/{run_id}", json={"name": "Renamed Fleet"})
        assert rename.status_code == 200

        response = client.get(f"/results/fleet/{run_id}")

        assert response.status_code == 200
        assert headings(response.get_data(as_text=True))[0] == "Renamed Fleet"

    def test_fleet_results_page_of_a_run_with_no_database_row_is_titled_fleet_simulation(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run whose files outlived its database row, as after the database is recreated, still has a title: the page's own."""
        run_id = _save_fleet_run(
            app, make_fleet_results(n_homes=2, days=1), name="Probe Fleet Run"
        )
        with get_db(app.config["DATABASE"]) as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

        response = client.get(f"/results/fleet/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert headings(page)[0] == "Fleet Simulation"
        assert "Results: Fleet Simulation - Solar Challenge" in texts(page)
