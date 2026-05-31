"""Tests for fleet chart functions and fleet results route."""

import json
from pathlib import Path

import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


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

    def test_fleet_summary_cards_data(self) -> None:
        """Test fleet_summary_cards_data extracts correct fields."""
        from solar_challenge.web.charts import fleet_summary_cards_data

        summary = type("FleetSummaryMock", (), {
            "n_homes": 10,
            "total_generation_kwh": 1000.0,
            "total_demand_kwh": 800.0,
            "total_self_consumption_kwh": 600.0,
            "fleet_self_consumption_ratio": 0.75,
            "fleet_grid_dependency_ratio": 0.25,
            "simulation_days": 30,
        })()
        cards = fleet_summary_cards_data(summary)
        assert isinstance(cards, list)
        assert len(cards) > 0
        labels = [c["label"] for c in cards]
        assert "Homes" in labels
        assert "Total Generation" in labels
        assert "Simulation Days" in labels

    def test_fleet_summary_cards_data_values(self) -> None:
        """Test fleet_summary_cards_data returns correct values."""
        from solar_challenge.web.charts import fleet_summary_cards_data

        summary = type("FleetSummaryMock", (), {
            "n_homes": 5,
            "total_generation_kwh": 500.0,
            "total_demand_kwh": 400.0,
            "total_self_consumption_kwh": 300.0,
            "fleet_self_consumption_ratio": 0.6,
            "fleet_grid_dependency_ratio": 0.25,
            "simulation_days": 7,
        })()
        cards = fleet_summary_cards_data(summary)
        homes_card = next(c for c in cards if c["label"] == "Homes")
        assert homes_card["value"] == 5

    def test_fleet_aggregate_timeline_returns_json(self) -> None:
        """Test fleet_aggregate_timeline returns valid JSON."""
        import numpy as np
        import pandas as pd
        from solar_challenge.home import SimulationResults
        from solar_challenge.web.charts import fleet_aggregate_timeline

        index = pd.date_range("2024-06-01", periods=1440, freq="min", tz="Europe/London")
        hours = np.arange(len(index)) / 60.0
        generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
        demand = np.full(len(index), 0.5)
        self_consumption = np.minimum(generation, demand)
        grid_import = np.maximum(0, demand - generation)
        grid_export = np.maximum(0, generation - demand)
        zeros = np.zeros(len(index))

        def _s(v: np.ndarray, n: str) -> pd.Series:
            return pd.Series(v, index=index, name=n)

        results = SimulationResults(
            generation=_s(generation, "generation_kw"),
            demand=_s(demand, "demand_kw"),
            self_consumption=_s(self_consumption, "self_consumption_kw"),
            battery_charge=_s(zeros, "battery_charge_kw"),
            battery_discharge=_s(zeros, "battery_discharge_kw"),
            battery_soc=_s(zeros, "battery_soc_kwh"),
            grid_import=_s(grid_import, "grid_import_kw"),
            grid_export=_s(grid_export, "grid_export_kw"),
            import_cost=_s(zeros, "import_cost_gbp"),
            export_revenue=_s(zeros, "export_revenue_gbp"),
            tariff_rate=_s(zeros, "tariff_rate_per_kwh"),
            strategy_name="self_consumption",
        )

        output = fleet_aggregate_timeline(results)
        assert output and output != "{}"
        parsed = json.loads(output)
        assert "data" in parsed

    def test_fleet_grid_impact_returns_json(self) -> None:
        """Test fleet_grid_impact returns valid JSON."""
        import numpy as np
        import pandas as pd
        from solar_challenge.home import SimulationResults
        from solar_challenge.web.charts import fleet_grid_impact

        index = pd.date_range("2024-06-01", periods=1440, freq="min", tz="Europe/London")
        hours = np.arange(len(index)) / 60.0
        generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
        demand = np.full(len(index), 0.5)
        self_consumption = np.minimum(generation, demand)
        grid_import = np.maximum(0, demand - generation)
        grid_export = np.maximum(0, generation - demand)
        zeros = np.zeros(len(index))

        def _s(v: np.ndarray, n: str) -> pd.Series:
            return pd.Series(v, index=index, name=n)

        results = SimulationResults(
            generation=_s(generation, "generation_kw"),
            demand=_s(demand, "demand_kw"),
            self_consumption=_s(self_consumption, "self_consumption_kw"),
            battery_charge=_s(zeros, "battery_charge_kw"),
            battery_discharge=_s(zeros, "battery_discharge_kw"),
            battery_soc=_s(zeros, "battery_soc_kwh"),
            grid_import=_s(grid_import, "grid_import_kw"),
            grid_export=_s(grid_export, "grid_export_kw"),
            import_cost=_s(zeros, "import_cost_gbp"),
            export_revenue=_s(zeros, "export_revenue_gbp"),
            tariff_rate=_s(zeros, "tariff_rate_per_kwh"),
            strategy_name="self_consumption",
        )

        output = fleet_grid_impact(results)
        assert output and output != "{}"
        parsed = json.loads(output)
        assert "data" in parsed
        # Should have two traces: import and export
        assert len(parsed["data"]) == 2


class TestFinancialBreakdownPricing:
    """Tests that financial_breakdown uses engine-priced series, not hardcoded rates."""

    def test_uses_engine_priced_series(self) -> None:
        """financial_breakdown must aggregate import_cost/export_revenue series directly."""
        pytest.importorskip("plotly")
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

    def test_fleet_results_unknown_run_redirects(self, client: FlaskClient) -> None:
        """Test accessing fleet results for a non-existent run redirects."""
        response = client.get("/results/fleet/nonexistent-id")
        assert response.status_code in (302, 404)

    def test_fleet_results_route_exists(self, client: FlaskClient) -> None:
        """Test that the fleet results route is registered and accessible."""
        response = client.get("/results/fleet/some-fake-id")
        # Should redirect (302) because the run doesn't exist, but NOT 404
        # which would mean the route itself doesn't exist
        assert response.status_code == 302
