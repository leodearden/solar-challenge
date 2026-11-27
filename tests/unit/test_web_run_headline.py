# SPDX-License-Identifier: AGPL-3.0-or-later
"""The headline the web shows for a run, which run_headline reads from its summary of either kind.

run_headline maps a summary of either kind to the figures the web shows for its run: the five
energy totals, the self-consumption, grid dependency and export ratios, and the share of the
generation the battery stored from PV, which a fleet run has none of. It refuses a summary
whose figure for any of them is not a finite number.

web/run_headline.py is a leaf below the run store, so the run store and the charts both import
it from below (task 1413): importing it, in a fresh ``python -I`` interpreter, loads no
solar_challenge.web module but the package and itself.
"""

import dataclasses
import math
from fractions import Fraction

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetSummary, calculate_fleet_summary
from solar_challenge.home import SummaryStatistics
from solar_challenge.web.run_headline import RunHeadline, run_headline
from tests._finance_builders import make_fleet_results
from tests._modules_loaded_by_importing import web_modules_loaded_by_importing
from tests._run_summaries import fleet_summary, home_summary


def test_importing_run_headline_loads_no_other_web_module() -> None:
    assert web_modules_loaded_by_importing("solar_challenge.web.run_headline") == {
        "solar_challenge.web",
        "solar_challenge.web.run_headline",
    }


class TestRunHeadline:
    """run_headline: the figures the web shows for a run's summary, its energy totals and ratios and the share of its generation the battery stored from PV.

    Each figure a headline reads from a summary is one no other field of that summary holds,
    so a headline read from the wrong field shows.
    """

    def test_a_home_run_s_headline_is_its_totals_its_ratios_and_the_share_of_its_generation_it_stored_from_pv(
        self,
    ) -> None:
        """The battery stored 4 of its 10 kWh from the grid, so a share read from its whole charge shows."""
        summary = home_summary(total_generation_kwh=987.65, self_consumption_ratio=0.37, total_grid_charge_kwh=4.0)

        assert run_headline(summary) == RunHeadline(
            generation_kwh=summary.total_generation_kwh,
            demand_kwh=summary.total_demand_kwh,
            self_consumption_kwh=summary.total_self_consumption_kwh,
            grid_import_kwh=summary.total_grid_import_kwh,
            grid_export_kwh=summary.total_grid_export_kwh,
            self_consumption_ratio=summary.self_consumption_ratio,
            grid_dependency_ratio=summary.grid_dependency_ratio,
            export_ratio=summary.export_ratio,
            pv_stored_share=summary.total_pv_charge_kwh / summary.total_generation_kwh,
        )

    def test_a_fleet_run_s_headline_is_its_totals_its_fleet_ratios_and_its_export_over_its_generation_and_no_pv_share(
        self,
    ) -> None:
        """A fleet summary holds no export ratio and no battery totals."""
        summary = fleet_summary(total_generation_kwh=1975.3, fleet_self_consumption_ratio=0.43, total_grid_export_kwh=70.0)

        assert run_headline(summary) == RunHeadline(
            generation_kwh=summary.total_generation_kwh,
            demand_kwh=summary.total_demand_kwh,
            self_consumption_kwh=summary.total_self_consumption_kwh,
            grid_import_kwh=summary.total_grid_import_kwh,
            grid_export_kwh=summary.total_grid_export_kwh,
            self_consumption_ratio=summary.fleet_self_consumption_ratio,
            grid_dependency_ratio=summary.fleet_grid_dependency_ratio,
            export_ratio=summary.total_grid_export_kwh / summary.total_generation_kwh,
            pv_stored_share=None,
        )

    def test_a_simulated_fleet_s_headline_holds_its_own_ratios_and_no_pv_stored_share(self) -> None:
        """B11: each of two homes self-consumes 18 and exports 54 of the 72 kWh it generates, and imports 27 of the 45 it uses."""
        fleet = make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)

        headline = run_headline(calculate_fleet_summary(fleet))

        assert (headline.self_consumption_ratio, headline.grid_dependency_ratio, headline.export_ratio) == pytest.approx(
            (0.25, 0.6, 0.75)
        )
        assert headline.pv_stored_share is None

    def test_a_share_of_a_generation_of_nothing_is_nothing_as_calculate_summary_s_export_ratio_is(self) -> None:
        assert run_headline(home_summary(total_generation_kwh=0.0)).pv_stored_share == 0.0
        assert run_headline(fleet_summary(total_generation_kwh=0.0)).export_ratio == 0.0

    def test_a_share_of_a_generation_held_as_a_fraction_is_a_float(self) -> None:
        """as_finite_real admits any numbers.Real, so a total may be a Fraction, whose share would be a Fraction, not the float a share is."""
        summary = home_summary(
            total_generation_kwh=Fraction(100),
            total_battery_charge_kwh=Fraction(10),
            total_grid_charge_kwh=Fraction(0),
        )

        share = run_headline(summary).pv_stored_share

        assert isinstance(share, float)
        assert share == 0.1

    @pytest.mark.parametrize("value", [pytest.param(Fraction(1, 4), id="fraction"), pytest.param(2, id="int")])
    def test_a_headline_holds_each_figure_as_the_float_it_equals(self, value: Fraction | int) -> None:
        """as_finite_real admits any numbers.Real, so a headline given a Fraction or an int holds the float it equals, as its annotation says."""
        headline = RunHeadline(**{figure.name: value for figure in dataclasses.fields(RunHeadline)})

        figures = {figure.name: getattr(headline, figure.name) for figure in dataclasses.fields(headline)}

        assert {name: (type(held), held) for name, held in figures.items()} == {
            name: (float, float(value)) for name in figures
        }

    def test_a_headline_with_no_pv_stored_share_is_a_headline(self) -> None:
        headline = dataclasses.replace(run_headline(home_summary()), pv_stored_share=None)

        assert headline.pv_stored_share is None

    @pytest.mark.parametrize(
        "figure",
        [
            "generation_kwh",
            "demand_kwh",
            "self_consumption_kwh",
            "grid_import_kwh",
            "grid_export_kwh",
            "self_consumption_ratio",
            "grid_dependency_ratio",
            "export_ratio",
        ],
    )
    def test_a_headline_with_no_value_for_a_figure_every_run_has_is_refused_naming_it(self, figure: str) -> None:
        """Only pv_stored_share, which a fleet run has none of, may be None."""
        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(run_headline(home_summary()), **{figure: None})

        assert f"RunHeadline.{figure} must be a finite number, got None" in str(refusal.value)

    def test_a_headline_whose_pv_stored_share_is_not_a_finite_number_is_refused_naming_it_and_its_value(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(run_headline(home_summary()), pv_stored_share=math.nan)

        assert "RunHeadline.pv_stored_share must be a finite number, got nan" in str(refusal.value)

    @pytest.mark.parametrize(
        ("summary", "figure", "value"),
        [
            pytest.param(home_summary(total_generation_kwh=None), "generation_kwh", None, id="home-generation-null"),
            pytest.param(home_summary(self_consumption_ratio="0.6"), "self_consumption_ratio", "0.6", id="home-ratio-text"),
            pytest.param(fleet_summary(total_generation_kwh=math.nan), "generation_kwh", math.nan, id="fleet-generation-nan"),
            pytest.param(fleet_summary(total_generation_kwh=math.inf), "generation_kwh", math.inf, id="fleet-generation-inf"),
            pytest.param(
                fleet_summary(fleet_self_consumption_ratio=True), "self_consumption_ratio", True, id="fleet-ratio-bool"
            ),
            pytest.param(
                home_summary(total_generation_kwh=10**400),
                "generation_kwh",
                10**400,
                id="home-generation-too-large-for-a-float",
            ),
            pytest.param(
                fleet_summary(fleet_self_consumption_ratio=-(10**400)),
                "self_consumption_ratio",
                -(10**400),
                id="fleet-ratio-below-every-float",
            ),
            pytest.param(home_summary(total_demand_kwh=math.nan), "demand_kwh", math.nan, id="home-demand-nan"),
            pytest.param(home_summary(export_ratio=math.inf), "export_ratio", math.inf, id="home-export-ratio-inf"),
            pytest.param(
                fleet_summary(fleet_grid_dependency_ratio="0.25"),
                "grid_dependency_ratio",
                "0.25",
                id="fleet-grid-dependency-ratio-text",
            ),
            pytest.param(
                fleet_summary(total_grid_export_kwh=None),
                "export_ratio",
                None,
                id="fleet-export-null-so-its-export-ratio",
            ),
            pytest.param(
                home_summary(total_battery_charge_kwh=math.inf),
                "pv_stored_share",
                math.inf,
                id="home-battery-charge-inf-so-its-pv-stored-share",
            ),
        ],
    )
    def test_a_summary_whose_headline_figure_is_not_a_finite_number_is_refused_naming_the_figure_and_its_value(
        self, summary: SummaryStatistics | FleetSummary, figure: str, value: object
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            run_headline(summary)

        assert f"RunHeadline.{figure} must be a finite number, got {value!r}" in str(refusal.value)

    def test_a_figure_a_summary_holds_as_a_whole_number_is_a_headline_figure(self) -> None:
        """A stored summary's JSON may hold a figure as a whole number, 100 rather than 100.0, which decodes as an int."""
        summary = home_summary(
            total_generation_kwh=100,
            total_demand_kwh=80,
            total_self_consumption_kwh=60,
            total_grid_import_kwh=20,
            total_grid_export_kwh=40,
            total_battery_charge_kwh=10,
            total_grid_charge_kwh=0,
            self_consumption_ratio=0,
            grid_dependency_ratio=0,
            export_ratio=1,
        )

        assert run_headline(summary) == RunHeadline(
            generation_kwh=100,
            demand_kwh=80,
            self_consumption_kwh=60,
            grid_import_kwh=20,
            grid_export_kwh=40,
            self_consumption_ratio=0,
            grid_dependency_ratio=0,
            export_ratio=1,
            pv_stored_share=0.1,
        )
