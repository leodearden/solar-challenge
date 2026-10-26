"""Tests for fleet chart functions and fleet results route."""

import json
import uuid

import pytest
pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.web.charts import (
    fleet_aggregate_timeline,
    fleet_box_plots,
    fleet_distribution_histograms,
    fleet_grid_impact,
    fleet_heatmap,
    power_flow_timeline,
)
from solar_challenge.web.storage import RunStorage

from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_sim_results
from tests._html_page import headings, texts, texts_after
from tests._plotly_figure import traces, traces_by_name
from tests._web_runs import store_fleet_run


def _save_fleet_run(storage: RunStorage, fleet: FleetResults, name: str | None = None) -> str:
    """Save *fleet* to *storage* as a completed fleet run named *name*, as a finished job saves it; return its run id."""
    run_id = str(uuid.uuid4())
    store_fleet_run(storage, run_id, fleet, name=name)
    return run_id


def _one_day_homes(n_homes: int) -> list[SimulationResults]:
    """The first *n_homes* of two one-day homes: a net exporter, then a net importer.

    Every flow the fleet charts draw is non-zero in both homes, so adding the second changes each of the fleet's totals.
    """
    net_exporter = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
    net_importer = make_sim_results(self_kwh=6.0, export_kwh=2.0, import_kwh=40.0, days=1)
    return [net_exporter, net_importer][:n_homes]


class TestFleetChartFunctions:
    """Tests for the fleet-specific chart functions in charts.py.

    The per-home charts' summaries are calculate_summary's, so renaming a field a chart reads fails their tests.
    """

    def test_fleet_heatmap_rows_are_each_homes_energy_totals(self) -> None:
        """Each row is one home's five energy totals, in the order the columns name them."""
        summaries = [calculate_summary(home) for home in _one_day_homes(2)]

        heatmap = traces(fleet_heatmap(summaries).content)[0]

        assert heatmap["x"] == ["Generation", "Demand", "Self-Consumption", "Grid Import", "Grid Export"]
        assert heatmap["y"] == ["Home 1", "Home 2"]
        assert heatmap["z"] == [[72.0, 45.0, 18.0, 27.0, 54.0], [8.0, 46.0, 6.0, 40.0, 2.0]]

    def test_fleet_heatmap_draws_only_the_first_50_homes(self) -> None:
        """Of 51 homes, the heatmap draws the first 50, in order."""
        summaries = [calculate_summary(make_sim_results(self_kwh=float(n), days=1)) for n in range(1, 52)]

        heatmap = traces(fleet_heatmap(summaries).content)[0]

        assert heatmap["y"] == [f"Home {n}" for n in range(1, 51)]
        assert [row[2] for row in heatmap["z"]] == [float(n) for n in range(1, 51)]

    def test_fleet_heatmap_rounds_each_total_to_two_decimal_places(self) -> None:
        """Each cell is the home's total rounded to 2 dp; the box plots draw the same totals unrounded, so the rounding is the heatmap's own."""
        home = make_sim_results(self_kwh=18.456, export_kwh=54.321, import_kwh=27.788, days=1)
        summaries = [calculate_summary(home)]

        heatmap = traces(fleet_heatmap(summaries).content)[0]
        boxes = traces(fleet_box_plots(summaries).content)

        assert [box["y"][0] for box in boxes] == pytest.approx([72.777, 46.244, 18.456, 27.788, 54.321])
        assert heatmap["z"] == [[72.78, 46.24, 18.46, 27.79, 54.32]]

    def test_fleet_box_plots_draw_each_energy_total_across_the_homes(self) -> None:
        """Each box is one energy total, drawn from each home's summary in the homes' order."""
        summaries = [calculate_summary(home) for home in _one_day_homes(2)]

        data = traces(fleet_box_plots(summaries).content)

        assert [(trace["name"], trace["y"]) for trace in data] == [
            ("Generation", [72.0, 8.0]),
            ("Demand", [45.0, 46.0]),
            ("Self-Consumption", [18.0, 6.0]),
            ("Grid Import", [27.0, 40.0]),
            ("Grid Export", [54.0, 2.0]),
        ]

    def test_fleet_distribution_histograms_draw_each_homes_generation_and_ratios(self) -> None:
        """The three histograms draw each home's generation, self-consumption ratio and grid dependency ratio."""
        summaries = [calculate_summary(home) for home in _one_day_homes(2)]

        data = traces(fleet_distribution_histograms(summaries).content)

        assert [(trace["name"], trace["x"]) for trace in data] == [
            ("Generation", [72.0, 8.0]),
            ("Self-Consumption", [18 / 72, 6 / 8]),
            ("Grid Dependency", [27 / 45, 40 / 46]),
        ]

    @pytest.mark.parametrize("n_homes", [1, 2], ids=["one-home", "two-homes"])
    def test_fleet_aggregate_timeline_draws_each_flow_summed_across_the_fleets_homes(
        self, n_homes: int
    ) -> None:
        """Each trace is that flow summed across the fleet's homes."""
        homes = _one_day_homes(n_homes)

        drawn = {
            name: trace["y"]
            for name, trace in traces_by_name(fleet_aggregate_timeline(make_fleet_results_of(homes)).content).items()
        }

        assert drawn == {
            "Generation": sum(home.generation for home in homes).round(4).tolist(),
            "Demand": sum(home.demand for home in homes).round(4).tolist(),
            "Self-Consumption": sum(home.self_consumption for home in homes).round(4).tolist(),
            "Grid Import": sum(home.grid_import for home in homes).round(4).tolist(),
            "Grid Export": sum(home.grid_export for home in homes).round(4).tolist(),
        }

    def test_fleet_aggregate_timeline_of_a_one_home_fleet_is_that_homes_power_flow_timeline(
        self,
    ) -> None:
        """A one-home fleet's totals are its home's flows, so its timeline is the home's power-flow timeline under the fleet's own title."""
        home = make_sim_results(days=365)

        home_figure = json.loads(power_flow_timeline(home).content)
        fleet_figure = json.loads(fleet_aggregate_timeline(make_fleet_results_of([home])).content)

        titles = (home_figure["layout"].pop("title"), fleet_figure["layout"].pop("title"))
        assert titles == ({"text": "Power Flow Timeline"}, {"text": "Fleet Aggregate Power Flow"})
        assert fleet_figure == home_figure

    @pytest.mark.parametrize("n_homes", [1, 2], ids=["one-home", "two-homes"])
    def test_fleet_grid_impact_draws_the_fleets_summed_import_less_its_summed_export(
        self, n_homes: int
    ) -> None:
        """The net is the fleet's summed import less its summed export, so the two-home fleet draws an import although its first home alone exports."""
        homes = _one_day_homes(n_homes)
        net = sum(home.grid_import for home in homes) - sum(home.grid_export for home in homes)

        drawn = {
            name: trace["y"]
            for name, trace in traces_by_name(fleet_grid_impact(make_fleet_results_of(homes)).content).items()
        }

        assert drawn == {
            "Grid Import": net.clip(lower=0).round(4).tolist(),
            "Grid Export": net.clip(upper=0).round(4).tolist(),
        }


class TestFleetResultsRoute:
    """Tests for the GET /results/<run_id> route, of a fleet run."""

    @pytest.mark.parametrize(
        "run_id",
        [
            pytest.param("nonexistent-id", id="an-id-no-run-has"),
            pytest.param("bad.id", id="an-id-the-store-refuses"),
        ],
    )
    def test_fleet_results_unknown_run_redirects(self, client: FlaskClient, run_id: str) -> None:
        """The page of an id no run has redirects to the dashboard, which flashes Run not found.

        'bad.id' is outside [A-Za-z0-9_-], so the store refuses it, and no run can have it.
        """
        response = client.get(f"/results/{run_id}", follow_redirects=True)

        assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
        assert "Run not found." in texts(response.get_data(as_text=True))

    def test_fleet_results_route_exists(self, client: FlaskClient) -> None:
        """Test that the fleet results route is registered and accessible."""
        response = client.get("/results/some-fake-id")
        # Should redirect (302) because the run doesn't exist, but NOT 404
        # which would mean the route itself doesn't exist
        assert response.status_code == 302

    def test_fleet_results_page_shows_the_saved_fleet_summary_in_nine_stat_cards(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """A saved two-home fleet run's results page shows nine stat cards, each reading the saved fleet summary.

        Each home self-consumes 18 kWh, exports 54 kWh and imports 27 kWh in its one day.
        """
        run_id = _save_fleet_run(
            storage,
            make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
        )
        response = client.get(f"/results/{run_id}")
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
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Each stat card rounds the saved fleet summary's value once, to the card's own precision.

        Each of the two homes self-consumes 5 kWh, exports 4.523 kWh and imports 2.8745 kWh
        in its one day. Each card below sits where rounding its value to 2 dp first (a ratio
        to 4 dp) would move the card's last digit: the fleet's 9.046 kWh export would show 9.1.
        """
        run_id = _save_fleet_run(
            storage,
            make_fleet_results(n_homes=2, self_kwh=5.0, export_kwh=4.523, import_kwh=2.8745, days=1),
        )
        response = client.get(f"/results/{run_id}")
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
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """The header under the title reads the saved fleet's number of homes and simulated days."""
        run_id = _save_fleet_run(storage, make_fleet_results(n_homes=3, days=2))

        response = client.get(f"/results/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert f"3 homes — 2-day simulation — Run ID: {run_id[:8]}…" in texts(page)

    def test_fleet_results_page_is_titled_with_the_name_its_run_was_saved_under(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """The page's h1 and its document title name the run as Run History lists it.

        The name's markup characters show as text.
        """
        run_id = _save_fleet_run(
            storage, make_fleet_results(n_homes=2, days=1), name="Phase 1 <South> & Co"
        )

        response = client.get(f"/results/{run_id}")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert headings(page)[0] == "Phase 1 <South> & Co"
        assert "Results: Phase 1 <South> & Co - Solar Challenge" in texts(page)

    def test_fleet_results_page_title_follows_a_run_history_rename(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Renaming a run in Run History retitles its results page."""
        run_id = _save_fleet_run(
            storage, make_fleet_results(n_homes=2, days=1), name="Probe Fleet Run"
        )
        rename = client.patch(f"/api/history/runs/{run_id}", json={"name": "Renamed Fleet"})
        assert rename.status_code == 200

        response = client.get(f"/results/{run_id}")

        assert response.status_code == 200
        assert headings(response.get_data(as_text=True))[0] == "Renamed Fleet"
