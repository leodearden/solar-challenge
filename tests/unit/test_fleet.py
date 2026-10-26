"""Tests for fleet simulation."""

import multiprocessing
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import TypeVar

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import parse_fleet_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    FleetSummary,
    MultiSweepResults,
    aggregate_home_summaries,
    calculate_fleet_summary,
    calculate_home_summaries,
    collect_multi_sweep_results,
    simulate_fleet,
    simulate_fleet_iter,
    simulate_multi_sweep_iter,
)
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import WeatherCache, default_weather
from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_sim_results
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import synthetic_june_weather


class TestFleetConfigBasics:
    """Test FLEET-001: FleetConfig functionality."""

    def test_create_with_homes_list(self):
        """FleetConfig can be created with list of homes."""
        homes = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(),
            )
            for _ in range(3)
        ]
        config = FleetConfig(homes=homes, name="Test Fleet")

        assert len(config.homes) == 3
        assert config.name == "Test Fleet"

    def test_requires_at_least_one_home(self):
        """Fleet must have at least one home."""
        with pytest.raises(ConfigurationError, match="at least one home"):
            FleetConfig(homes=[])

    def test_validates_consistent_timezones(self):
        """All homes must have same timezone."""
        home1 = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            location=Location(latitude=51.5, longitude=-0.1, timezone="Europe/London"),
        )
        home2 = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            location=Location(latitude=40.7, longitude=-74.0, timezone="America/New_York"),
        )

        with pytest.raises(ConfigurationError, match="timezone"):
            FleetConfig(homes=[home1, home2])


class TestFleetConfigCreation:
    """Test fleet creation convenience methods."""

    def test_create_uniform_fleet(self):
        """FLEET-001: Create uniform fleet with same config."""
        config = FleetConfig.create_uniform(
            n_homes=5,
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            name="Uniform Fleet",
        )

        assert len(config.homes) == 5
        assert all(h.pv_config.capacity_kw == 4.0 for h in config.homes)
        assert all(h.battery_config is not None for h in config.homes)

    def test_create_heterogeneous_fleet(self):
        """FLEET-002: Create fleet with varied configs."""
        config = FleetConfig.create_heterogeneous(
            pv_capacities_kw=[3.0, 4.0, 5.0, 6.0],
            battery_capacities_kwh=[None, 5.0, 5.0, 10.0],
            annual_consumptions_kwh=[2800, 3400, 3400, 4200],
        )

        assert len(config.homes) == 4
        assert config.homes[0].pv_config.capacity_kw == 3.0
        assert config.homes[0].battery_config is None
        assert config.homes[1].battery_config is not None
        assert config.homes[3].pv_config.capacity_kw == 6.0

    def test_heterogeneous_requires_matching_lengths(self):
        """Heterogeneous config lists must have same length."""
        with pytest.raises(ConfigurationError, match="same length"):
            FleetConfig.create_heterogeneous(
                pv_capacities_kw=[3.0, 4.0],
                battery_capacities_kwh=[None, 5.0, 5.0],  # Wrong length
                annual_consumptions_kwh=[3400, 3400],
            )


def _home_whose_series_all_differ(offset: float) -> SimulationResults:
    """An hour of results whose every series varies and holds values no other series holds, each shifted by offset."""
    index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min")

    def series(position: int) -> pd.Series:
        return pd.Series(np.arange(60.0) + 100.0 * position + offset, index=index)

    return SimulationResults(
        generation=series(0),
        demand=series(1),
        self_consumption=series(2),
        battery_charge=series(3),
        battery_discharge=series(4),
        battery_soc=series(5),
        grid_import=series(6),
        grid_export=series(7),
        import_cost=series(8),
        export_revenue=series(9),
        tariff_rate=series(10),
    )


class TestFleetResults:
    """Test FLEET-004/005: Fleet results functionality."""

    @pytest.fixture
    def sample_results(self) -> FleetResults:
        """Create sample fleet results for 2 homes."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")

        home1_results = SimulationResults(
            generation=pd.Series([3.0] * 1440, index=index),
            demand=pd.Series([2.0] * 1440, index=index),
            self_consumption=pd.Series([2.0] * 1440, index=index),
            battery_charge=pd.Series([0.5] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([2.5] * 1440, index=index),
            grid_import=pd.Series([0.0] * 1440, index=index),
            grid_export=pd.Series([0.5] * 1440, index=index),
            import_cost=pd.Series([0.0] * 1440, index=index),
            export_revenue=pd.Series([0.0] * 1440, index=index),
            tariff_rate=pd.Series([0.0] * 1440, index=index),
        )

        home2_results = SimulationResults(
            generation=pd.Series([4.0] * 1440, index=index),
            demand=pd.Series([3.0] * 1440, index=index),
            self_consumption=pd.Series([3.0] * 1440, index=index),
            battery_charge=pd.Series([0.5] * 1440, index=index),
            battery_discharge=pd.Series([0.0] * 1440, index=index),
            battery_soc=pd.Series([2.5] * 1440, index=index),
            grid_import=pd.Series([0.0] * 1440, index=index),
            grid_export=pd.Series([0.5] * 1440, index=index),
            import_cost=pd.Series([0.0] * 1440, index=index),
            export_revenue=pd.Series([0.0] * 1440, index=index),
            tariff_rate=pd.Series([0.0] * 1440, index=index),
        )

        configs = [
            HomeConfig(pv_config=PVConfig(capacity_kw=3.0), load_config=LoadConfig()),
            HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
        ]

        return FleetResults(
            per_home_results=[home1_results, home2_results],
            home_configs=configs,
        )

    def test_len_returns_num_homes(self, sample_results):
        """len() returns number of homes."""
        assert len(sample_results) == 2

    def test_indexing_returns_home_results(self, sample_results):
        """Indexing returns per-home results."""
        assert isinstance(sample_results[0], SimulationResults)
        assert sample_results[0].generation.iloc[0] == 3.0
        assert sample_results[1].generation.iloc[0] == 4.0

    def test_total_generation_sums_homes(self, sample_results):
        """total_generation sums across all homes."""
        total = sample_results.total_generation
        # 3.0 + 4.0 = 7.0 kW constant
        assert (total == 7.0).all()

    def test_total_demand_sums_homes(self, sample_results):
        """total_demand sums across all homes."""
        total = sample_results.total_demand
        # 2.0 + 3.0 = 5.0 kW constant
        assert (total == 5.0).all()

    @pytest.mark.parametrize("n_homes", [1, 3], ids=["one-home", "three-homes"])
    def test_aggregate_frame_is_the_homes_frames_summed_over_five_of_their_columns(self, n_homes):
        """The aggregate frame is the homes' to_dataframe frames summed, over their generation, demand, self-consumption, grid import and grid export columns, in that order."""
        homes = [_home_whose_series_all_differ(offset=0.5 * k) for k in range(n_homes)]
        fleet = FleetResults(
            per_home_results=homes,
            home_configs=[HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())] * n_homes,
        )
        columns = [
            homes[0].generation.name,
            homes[0].demand.name,
            homes[0].self_consumption.name,
            homes[0].grid_import.name,
            homes[0].grid_export.name,
        ]
        home_frames = [home.to_dataframe()[columns] for home in homes]

        pd.testing.assert_frame_equal(fleet.to_aggregate_dataframe(), sum(home_frames[1:], home_frames[0]))

    def test_aggregate_frame_columns_are_the_fleet_csv_header(self, sample_results):
        """The five columns, in order, of the fleet CSV that the CLI and the web history export write from this frame."""
        assert list(sample_results.to_aggregate_dataframe().columns) == [
            "generation_kw",
            "demand_kw",
            "self_consumption_kw",
            "grid_import_kw",
            "grid_export_kw",
        ]

    def test_refuses_a_fleet_of_no_homes(self):
        """A fleet's results must hold at least one home, as its FleetConfig must."""
        with pytest.raises(ValueError, match="at least one home"):
            FleetResults(per_home_results=[], home_configs=[])

    @pytest.mark.parametrize("n_configs", [1, 3], ids=["fewer-configs-than-results", "more-configs-than-results"])
    def test_refuses_home_configs_that_do_not_pair_one_with_each_result(self, sample_results, n_configs):
        """home_configs must hold exactly one HomeConfig for each home's results, neither fewer nor more."""
        with pytest.raises(ValueError, match=f"got 2 per_home_results and {n_configs} home_configs"):
            FleetResults(
                per_home_results=sample_results.per_home_results,
                home_configs=[sample_results.home_configs[0]] * n_configs,
            )

    @pytest.mark.parametrize(
        ("break_invariant", "refusal"),
        [
            pytest.param(lambda fleet: fleet.per_home_results.clear(), "at least one home", id="emptied"),
            pytest.param(
                lambda fleet: fleet.home_configs.pop(), "got 2 per_home_results and 1 home_configs", id="unpaired"
            ),
        ],
    )
    @pytest.mark.parametrize(
        "read",
        [
            pytest.param(lambda fleet: fleet.total_generation, id="total_generation"),
            pytest.param(FleetResults.to_aggregate_dataframe, id="to_aggregate_dataframe"),
            pytest.param(calculate_fleet_summary, id="calculate_fleet_summary"),
            pytest.param(calculate_home_summaries, id="calculate_home_summaries"),
        ],
    )
    def test_a_fleet_emptied_or_unpaired_after_construction_is_refused_where_it_is_read(
        self, sample_results, break_invariant, refusal, read
    ):
        """A fleet whose per_home_results is emptied, or whose home_configs is unpaired from it, after construction is refused, naming the invariant, wherever its totals or summary are read."""
        break_invariant(sample_results)

        with pytest.raises(ValueError, match=refusal):
            read(sample_results)


class TestFleetSummary:
    """Test FLEET-006: Fleet summary statistics."""

    @pytest.fixture
    def sample_results(self) -> FleetResults:
        """Create sample fleet results."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")

        results = []
        configs = []
        for i, gen_kw in enumerate([3.0, 4.0, 5.0]):
            results.append(
                SimulationResults(
                    generation=pd.Series([gen_kw] * 1440, index=index),
                    demand=pd.Series([2.0] * 1440, index=index),
                    self_consumption=pd.Series([2.0] * 1440, index=index),
                    battery_charge=pd.Series([0.0] * 1440, index=index),
                    battery_discharge=pd.Series([0.0] * 1440, index=index),
                    battery_soc=pd.Series([0.0] * 1440, index=index),
                    grid_import=pd.Series([0.0] * 1440, index=index),
                    grid_export=pd.Series([gen_kw - 2.0] * 1440, index=index),
                    import_cost=pd.Series([0.0] * 1440, index=index),
                    export_revenue=pd.Series([0.0] * 1440, index=index),
                    tariff_rate=pd.Series([0.0] * 1440, index=index),
                )
            )
            configs.append(
                HomeConfig(pv_config=PVConfig(capacity_kw=gen_kw), load_config=LoadConfig())
            )

        return FleetResults(per_home_results=results, home_configs=configs)

    def test_calculates_fleet_totals(self, sample_results):
        """Calculates fleet-wide totals."""
        summary = calculate_fleet_summary(sample_results)

        assert summary.n_homes == 3

        # Total generation: (3+4+5) kW * 24 hours = 288 kWh
        assert summary.total_generation_kwh == pytest.approx(288.0, rel=0.01)

        # Total demand: 3 homes * 2 kW * 24 hours = 144 kWh
        assert summary.total_demand_kwh == pytest.approx(144.0, rel=0.01)

    def test_calculates_distribution_stats(self, sample_results):
        """Calculates distribution stats across homes."""
        summary = calculate_fleet_summary(sample_results)

        # Per-home generation: 72, 96, 120 kWh
        assert summary.per_home_generation_min_kwh == pytest.approx(72.0, rel=0.01)
        assert summary.per_home_generation_max_kwh == pytest.approx(120.0, rel=0.01)
        assert summary.per_home_generation_mean_kwh == pytest.approx(96.0, rel=0.01)
        assert summary.per_home_generation_median_kwh == pytest.approx(96.0, rel=0.01)

    def test_calculates_fleet_ratios(self, sample_results):
        """Calculates fleet-level efficiency ratios."""
        summary = calculate_fleet_summary(sample_results)

        # Self-consumption = 144 kWh (all demand met by PV)
        # Generation = 288 kWh
        # Fleet SC ratio = 144/288 = 0.5
        assert summary.fleet_self_consumption_ratio == pytest.approx(0.5, rel=0.01)

        # Grid dependency = 0 (no imports)
        assert summary.fleet_grid_dependency_ratio == 0.0

    def test_fleet_ratios_are_ratios_of_the_fleets_totals(self):
        """The fleet's ratios divide its summed totals; the mean of its homes' ratios would be 0.25 and 0.5."""
        fleet = make_fleet_results_of(
            [
                make_sim_results(self_kwh=0.0, export_kwh=0.0, import_kwh=10.0, days=1),
                make_sim_results(self_kwh=30.0, export_kwh=30.0, import_kwh=0.0, days=1),
            ]
        )

        summary = calculate_fleet_summary(fleet)

        totals = (
            summary.total_generation_kwh,
            summary.total_demand_kwh,
            summary.total_self_consumption_kwh,
            summary.total_grid_import_kwh,
        )
        assert totals == pytest.approx((60.0, 40.0, 30.0, 10.0))
        assert summary.fleet_self_consumption_ratio == pytest.approx(0.5)
        assert summary.fleet_grid_dependency_ratio == pytest.approx(0.25)

    @pytest.mark.parametrize(
        ("export_kwh", "import_kwh", "self_consumption_ratio", "grid_dependency_ratio"),
        [
            pytest.param(0.0, 5.0, 0.0, 1.0, id="no-generation"),
            pytest.param(5.0, 0.0, 0.0, 0.0, id="no-demand"),
        ],
    )
    def test_a_fleet_with_a_zero_denominator_reports_0_for_that_ratio(
        self, export_kwh, import_kwh, self_consumption_ratio, grid_dependency_ratio
    ):
        """A fleet that generated nothing, or demanded nothing, has 0.0 for the ratio over that total."""
        fleet = make_fleet_results(n_homes=2, self_kwh=0.0, export_kwh=export_kwh, import_kwh=import_kwh, days=1)

        summary = calculate_fleet_summary(fleet)

        assert summary.fleet_self_consumption_ratio == pytest.approx(self_consumption_ratio)
        assert summary.fleet_grid_dependency_ratio == pytest.approx(grid_dependency_ratio)

    def test_SEG_aggregates_with_tariff(self, sample_results):
        """SEG revenue totals and mean are computed when tariff is provided."""
        # Per-home grid_export: [1.0, 2.0, 3.0] kW constant for 24 h
        # Per-home export kWh: [24, 48, 72]
        # At 15p/kWh: [3.60, 7.20, 10.80] GBP
        # total = 21.60, mean = 7.20
        summary = calculate_fleet_summary(sample_results, seg_tariff_pence_per_kwh=15.0)

        assert summary.total_seg_revenue_gbp is not None
        assert summary.total_seg_revenue_gbp == pytest.approx(21.60, rel=0.01)

        assert summary.per_home_seg_revenue_mean_gbp is not None
        assert summary.per_home_seg_revenue_mean_gbp == pytest.approx(7.20, rel=0.01)

    def test_SEG_aggregates_without_tariff(self, sample_results):
        """SEG revenue fields are None when no tariff is provided."""
        summary = calculate_fleet_summary(sample_results)

        assert summary.total_seg_revenue_gbp is None
        assert summary.per_home_seg_revenue_mean_gbp is None

    def test_aggregates_financial_totals(self):
        """Fleet aggregates per-home financial totals correctly (P6ε §3.6/§10)."""
        index = pd.date_range("2024-06-21 00:00", periods=1440, freq="1min")

        # home1: import_cost=0.01/min, export_revenue=0.004/min
        # home2: import_cost=0.02/min, export_revenue=0.005/min
        results = [
            SimulationResults(
                generation=pd.Series([3.0] * 1440, index=index),
                demand=pd.Series([2.0] * 1440, index=index),
                self_consumption=pd.Series([2.0] * 1440, index=index),
                battery_charge=pd.Series([0.0] * 1440, index=index),
                battery_discharge=pd.Series([0.0] * 1440, index=index),
                battery_soc=pd.Series([0.0] * 1440, index=index),
                grid_import=pd.Series([0.0] * 1440, index=index),
                grid_export=pd.Series([1.0] * 1440, index=index),
                import_cost=pd.Series([0.01] * 1440, index=index),
                export_revenue=pd.Series([0.004] * 1440, index=index),
                tariff_rate=pd.Series([0.0] * 1440, index=index),
            ),
            SimulationResults(
                generation=pd.Series([4.0] * 1440, index=index),
                demand=pd.Series([2.0] * 1440, index=index),
                self_consumption=pd.Series([2.0] * 1440, index=index),
                battery_charge=pd.Series([0.0] * 1440, index=index),
                battery_discharge=pd.Series([0.0] * 1440, index=index),
                battery_soc=pd.Series([0.0] * 1440, index=index),
                grid_import=pd.Series([0.0] * 1440, index=index),
                grid_export=pd.Series([2.0] * 1440, index=index),
                import_cost=pd.Series([0.02] * 1440, index=index),
                export_revenue=pd.Series([0.005] * 1440, index=index),
                tariff_rate=pd.Series([0.0] * 1440, index=index),
            ),
        ]
        configs = [
            HomeConfig(pv_config=PVConfig(capacity_kw=3.0), load_config=LoadConfig()),
            HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
        ]
        fleet_results = FleetResults(per_home_results=results, home_configs=configs)

        summary = calculate_fleet_summary(fleet_results)

        # Fleet totals: sum of per-home series sums (no /60 conversion)
        # total_import = 0.01*1440 + 0.02*1440 = 14.4 + 28.8 = 43.20
        # total_export = 0.004*1440 + 0.005*1440 = 5.76 + 7.20 = 12.96
        # total_net = 43.20 - 12.96 = 30.24
        assert summary.total_import_cost_gbp == pytest.approx(43.20)
        assert summary.total_export_revenue_gbp == pytest.approx(12.96)
        assert summary.total_net_cost_gbp == pytest.approx(30.24)
        # Internal consistency: net == import - export
        assert summary.total_net_cost_gbp == pytest.approx(
            summary.total_import_cost_gbp - summary.total_export_revenue_gbp  # type: ignore[operator]
        )

    def test_financial_fields_default_none_when_not_computed(self):
        """New financial fields default to None on direct construction (backward-compat)."""
        # Construct FleetSummary with only pre-existing fields — omit the new kwargs
        summary = FleetSummary(
            n_homes=1,
            total_generation_kwh=72.0,
            total_demand_kwh=48.0,
            total_self_consumption_kwh=48.0,
            total_grid_import_kwh=0.0,
            total_grid_export_kwh=24.0,
            fleet_self_consumption_ratio=0.667,
            fleet_grid_dependency_ratio=0.0,
            per_home_generation_min_kwh=72.0,
            per_home_generation_max_kwh=72.0,
            per_home_generation_mean_kwh=72.0,
            per_home_generation_median_kwh=72.0,
            per_home_self_consumption_ratio_min=0.667,
            per_home_self_consumption_ratio_max=0.667,
            per_home_self_consumption_ratio_mean=0.667,
            simulation_days=1,
            # SEG fields omitted (already Optional[float] = None)
            # new financial fields omitted — must also default to None
        )

        assert summary.total_net_cost_gbp is None
        assert summary.total_import_cost_gbp is None
        assert summary.total_export_revenue_gbp is None

    @pytest.mark.parametrize("seg_tariff_pence_per_kwh", [None, 15.0], ids=["no-seg-tariff", "seg-tariff-15p"])
    def test_each_homes_summary_is_calculate_summary_of_its_results_in_the_fleets_order(
        self, sample_results, seg_tariff_pence_per_kwh
    ):
        """Each home's summary is the one calculate_summary derives from that home's results at the same SEG tariff, listed in per_home_results' order."""
        assert calculate_home_summaries(sample_results, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh) == [
            calculate_summary(results, seg_tariff_pence_per_kwh=seg_tariff_pence_per_kwh)
            for results in sample_results.per_home_results
        ]

    def test_home_summaries_aggregate_into_the_fleets_totals_ratios_and_per_home_statistics(self):
        """The fleet's totals sum its homes', its ratios divide those totals, and its per-home statistics range over its homes' generation and self-consumption ratios."""
        small_array = SummaryStatistics(
            total_generation_kwh=4.0,
            total_demand_kwh=6.0,
            total_self_consumption_kwh=3.0,
            total_grid_import_kwh=3.0,
            total_grid_export_kwh=1.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=1.0,
            peak_demand_kw=1.5,
            self_consumption_ratio=0.75,
            grid_dependency_ratio=0.5,
            export_ratio=0.25,
            simulation_days=1,
            total_import_cost_gbp=0.75,
            total_export_revenue_gbp=0.125,
            net_cost_gbp=0.625,
            seg_revenue_gbp=0.125,
        )
        medium_array = SummaryStatistics(
            total_generation_kwh=16.0,
            total_demand_kwh=8.0,
            total_self_consumption_kwh=2.0,
            total_grid_import_kwh=6.0,
            total_grid_export_kwh=14.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=3.0,
            peak_demand_kw=2.0,
            self_consumption_ratio=0.125,
            grid_dependency_ratio=0.75,
            export_ratio=0.875,
            simulation_days=1,
            total_import_cost_gbp=1.5,
            total_export_revenue_gbp=1.75,
            net_cost_gbp=-0.25,
            seg_revenue_gbp=1.75,
        )
        large_array = SummaryStatistics(
            total_generation_kwh=40.0,
            total_demand_kwh=16.0,
            total_self_consumption_kwh=10.0,
            total_grid_import_kwh=6.0,
            total_grid_export_kwh=30.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=6.0,
            peak_demand_kw=3.0,
            self_consumption_ratio=0.25,
            grid_dependency_ratio=0.375,
            export_ratio=0.75,
            simulation_days=1,
            total_import_cost_gbp=1.5,
            total_export_revenue_gbp=3.75,
            net_cost_gbp=-2.25,
            seg_revenue_gbp=3.75,
        )

        assert aggregate_home_summaries([small_array, medium_array, large_array]) == FleetSummary(
            n_homes=3,
            total_generation_kwh=60.0,
            total_demand_kwh=30.0,
            total_self_consumption_kwh=15.0,
            total_grid_import_kwh=15.0,
            total_grid_export_kwh=45.0,
            fleet_self_consumption_ratio=0.25,
            fleet_grid_dependency_ratio=0.5,
            per_home_generation_min_kwh=4.0,
            per_home_generation_max_kwh=40.0,
            per_home_generation_mean_kwh=20.0,
            per_home_generation_median_kwh=16.0,
            per_home_self_consumption_ratio_min=0.125,
            per_home_self_consumption_ratio_max=0.75,
            per_home_self_consumption_ratio_mean=0.375,
            simulation_days=1,
            total_seg_revenue_gbp=5.625,
            per_home_seg_revenue_mean_gbp=1.875,
            total_net_cost_gbp=-1.875,
            total_import_cost_gbp=3.75,
            total_export_revenue_gbp=5.625,
        )

    def test_seg_revenue_is_aggregated_over_the_homes_whose_summary_has_one(self, sample_results):
        """The fleet's SEG revenue total and per-home mean are taken over the homes whose summary has a SEG revenue, leaving out a home whose summary has none."""
        first, second, third = calculate_home_summaries(sample_results, seg_tariff_pence_per_kwh=15.0)
        assert [first.seg_revenue_gbp, second.seg_revenue_gbp, third.seg_revenue_gbp] == pytest.approx(
            [3.60, 7.20, 10.80]
        ), "premise: the homes export 24, 48 and 72 kWh, which earn 3.60, 7.20 and 10.80 GBP at 15p/kWh"

        summary = aggregate_home_summaries([first, replace(second, seg_revenue_gbp=None), third])

        assert summary.total_seg_revenue_gbp == pytest.approx(14.40)
        assert summary.per_home_seg_revenue_mean_gbp == pytest.approx(7.20)

    def test_aggregating_no_home_summaries_is_refused(self):
        """A fleet summary aggregates at least one home's summary."""
        with pytest.raises(ValueError, match="at least one home"):
            aggregate_home_summaries([])


_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21", tz="Europe/London"), count=1)
bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()


@pytest.fixture
def worker_start_method(request: pytest.FixtureRequest) -> Iterator[str]:
    """Make request.param the start method of the default multiprocessing context, which the fleet's worker pool uses, until the test ends."""
    previous = multiprocessing.get_start_method(allow_none=True)
    multiprocessing.set_start_method(request.param, force=True)
    yield request.param
    multiprocessing.set_start_method(previous, force=True)


@pytest.mark.usefixtures("bristol_june_tmy")
class TestSimulateFleetIter:
    """Test simulate_fleet_iter iterator function."""

    @pytest.fixture
    def small_fleet_config(self) -> FleetConfig:
        """Create a small fleet config for testing."""
        return FleetConfig.create_uniform(
            n_homes=3,
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            name="Test Fleet",
        )

    def test_sequential_yields_in_order(self, small_fleet_config):
        """Sequential iteration yields results in order."""
        start, end = _JUNE_DAYS.window(1)

        indices = []
        results = []
        for idx, result in simulate_fleet_iter(
            small_fleet_config, start, end, parallel=False
        ):
            indices.append(idx)
            results.append(result)

        assert indices == [0, 1, 2]
        assert len(results) == 3
        assert all(isinstance(r, SimulationResults) for r in results)

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_parallel_yields_all_results(self, small_fleet_config, worker_start_method):
        """Parallel iteration yields all results (order may vary)."""
        start, end = _JUNE_DAYS.window(1)

        indices = []
        results = []
        for idx, result in simulate_fleet_iter(
            small_fleet_config, start, end, parallel=True, max_workers=2
        ):
            indices.append(idx)
            results.append(result)

        assert sorted(indices) == [0, 1, 2]
        assert len(results) == 3
        assert all(isinstance(r, SimulationResults) for r in results)

    def test_single_home_skips_parallel(self):
        """Single home fleet skips parallelization."""
        config = FleetConfig.create_uniform(
            n_homes=1,
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
        )
        start, end = _JUNE_DAYS.window(1)

        results = list(simulate_fleet_iter(config, start, end, parallel=True))

        assert len(results) == 1
        assert results[0][0] == 0


@pytest.mark.usefixtures("bristol_june_tmy")
class TestParallelMatchesSequential:
    """A seeded stochastic fleet's parallel run gives each home exactly its sequential run's results, whichever worker draws its demand."""

    @pytest.mark.parametrize("worker_start_method", ["forkserver", "spawn"], indirect=True)
    def test_seeded_stochastic_homes_get_their_sequential_results_from_parallel_workers(
        self, worker_start_method: str
    ) -> None:
        start, end = _JUNE_DAYS.window(1)
        workers = 2
        fleet = parse_fleet_config(
            {
                "fleet_distribution": {
                    "n_homes": 4,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3400.0, "use_stochastic": True},
                }
            }
        )
        assert len(fleet.homes) > workers, (
            f"premise: {len(fleet.homes)} homes over {workers} workers, so some worker draws "
            "one home's demand after another's"
        )

        in_sequence = simulate_fleet(fleet, start, end, parallel=False)
        distinct_demands = {tuple(results.demand) for results in in_sequence.per_home_results}
        assert len(distinct_demands) == len(fleet.homes), (
            f"premise: the {len(fleet.homes)} homes, differing only in their seed, drew "
            f"{len(distinct_demands)} distinct demand profiles; profiles drawn from their own seeds differ, "
            "the deterministic Elexon fallback's do not"
        )

        in_parallel = simulate_fleet(fleet, start, end, parallel=True, max_workers=workers)
        for home, from_workers, from_sequence in zip(
            fleet.homes, in_parallel.per_home_results, in_sequence.per_home_results, strict=True
        ):
            pd.testing.assert_frame_equal(
                from_workers.to_dataframe(),
                from_sequence.to_dataframe(),
                check_exact=True,
                obj=f"{home.name}'s results from {worker_start_method} workers",
            )


@pytest.mark.usefixtures("bristol_june_tmy")
class TestMultiSweepIter:
    """Test simulate_multi_sweep_iter for cross-sweep parallelism."""

    @pytest.fixture
    def sweep_configs(self) -> list[tuple[float, FleetConfig]]:
        """Create sweep configs with 2 sweeps of 3 homes each."""
        configs = []
        for sweep_val in [1.0, 2.0]:
            fleet = FleetConfig.create_uniform(
                n_homes=3,
                pv_config=PVConfig(capacity_kw=4.0 * sweep_val),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                name=f"sweep_{sweep_val}",
            )
            configs.append((sweep_val, fleet))
        return configs

    def test_sequential_yields_all_results(self, sweep_configs):
        """Sequential iteration yields all results from all sweeps."""
        start, end = _JUNE_DAYS.window(1)

        results = list(simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=False
        ))

        # Should have 6 results (2 sweeps * 3 homes)
        assert len(results) == 6

        # Check that all sweep/home combinations are present
        sweep_home_pairs = {(r[0], r[1]) for r in results}
        expected_pairs = {(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)}
        assert sweep_home_pairs == expected_pairs

        # All results should be SimulationResults
        assert all(isinstance(r[2], SimulationResults) for r in results)

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_parallel_yields_all_results(self, sweep_configs, worker_start_method):
        """Parallel iteration yields all results from all sweeps."""
        start, end = _JUNE_DAYS.window(1)

        results = list(simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=True, max_workers=2
        ))

        # Should have 6 results (2 sweeps * 3 homes)
        assert len(results) == 6

        # Check that all sweep/home combinations are present
        sweep_home_pairs = {(r[0], r[1]) for r in results}
        expected_pairs = {(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)}
        assert sweep_home_pairs == expected_pairs

    def test_empty_configs_returns_nothing(self):
        """Empty sweep configs yields nothing."""
        start, end = _JUNE_DAYS.window(1)

        results = list(simulate_multi_sweep_iter([], start, end))
        assert results == []

    def test_results_contain_correct_sweep_index(self, sweep_configs):
        """Results correctly identify which sweep they belong to."""
        start, end = _JUNE_DAYS.window(1)

        results = list(simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=False
        ))

        # Group by sweep_index
        sweep_0_results = [r for r in results if r[0] == 0]
        sweep_1_results = [r for r in results if r[0] == 1]

        assert len(sweep_0_results) == 3
        assert len(sweep_1_results) == 3


@pytest.mark.usefixtures("bristol_june_tmy")
class TestCollectMultiSweepResults:
    """Test collect_multi_sweep_results for organizing results."""

    @pytest.fixture
    def sweep_configs(self) -> list[tuple[float, FleetConfig]]:
        """Create sweep configs with 2 sweeps of 2 homes each."""
        configs = []
        for sweep_val in [1.0, 2.0]:
            fleet = FleetConfig.create_uniform(
                n_homes=2,
                pv_config=PVConfig(capacity_kw=4.0 * sweep_val),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                name=f"sweep_{sweep_val}",
            )
            configs.append((sweep_val, fleet))
        return configs

    def test_organizes_results_by_sweep(self, sweep_configs):
        """Results are organized by sweep index."""
        start, end = _JUNE_DAYS.window(1)

        result_iter = simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=False
        )

        multi_results = collect_multi_sweep_results(sweep_configs, result_iter)

        assert len(multi_results) == 2
        assert multi_results.sweep_values == [1.0, 2.0]

        # Check each sweep result
        sweep_val_0, fleet_results_0 = multi_results[0]
        assert sweep_val_0 == 1.0
        assert len(fleet_results_0) == 2

        sweep_val_1, fleet_results_1 = multi_results[1]
        assert sweep_val_1 == 2.0
        assert len(fleet_results_1) == 2

    def test_calls_callback_on_sweep_complete(self, sweep_configs):
        """Callback is called when each sweep completes."""
        start, end = _JUNE_DAYS.window(1)

        completed_sweeps = []

        def on_complete(sweep_idx, sweep_val, fleet_results):
            completed_sweeps.append({
                "index": sweep_idx,
                "value": sweep_val,
                "n_homes": len(fleet_results),
            })

        result_iter = simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=False
        )

        collect_multi_sweep_results(
            sweep_configs, result_iter, on_sweep_complete=on_complete
        )

        # Both sweeps should have triggered callback
        assert len(completed_sweeps) == 2
        indices = {c["index"] for c in completed_sweeps}
        assert indices == {0, 1}

    def test_iter_results_in_order(self, sweep_configs):
        """iter_results yields results in sweep order."""
        start, end = _JUNE_DAYS.window(1)

        result_iter = simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=False
        )

        multi_results = collect_multi_sweep_results(sweep_configs, result_iter)

        values = []
        for sweep_val, _ in multi_results.iter_results():
            values.append(sweep_val)

        assert values == [1.0, 2.0]

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_home_results_in_correct_order(self, sweep_configs, worker_start_method):
        """Home results within each sweep are in correct order."""
        start, end = _JUNE_DAYS.window(1)

        # Use parallel to get out-of-order results
        result_iter = simulate_multi_sweep_iter(
            sweep_configs, start, end, parallel=True, max_workers=4
        )

        multi_results = collect_multi_sweep_results(sweep_configs, result_iter)

        # Each sweep's results should have home_configs matching
        for sweep_idx in range(len(sweep_configs)):
            _, fleet_results = multi_results[sweep_idx]
            assert len(fleet_results.home_configs) == 2
            assert len(fleet_results.per_home_results) == 2


class TestMultiSweepResults:
    """Test MultiSweepResults dataclass."""

    def test_len_returns_num_sweeps(self):
        """len() returns number of sweeps."""
        results = MultiSweepResults(
            sweep_results={0: (1.0, None), 1: (2.0, None)},
            sweep_values=[1.0, 2.0],
        )
        assert len(results) == 2

    def test_getitem_returns_sweep_result(self):
        """Indexing returns (sweep_value, FleetResults) tuple."""
        # Create minimal FleetResults
        index = pd.date_range("2024-06-21 00:00", periods=10, freq="1min")
        home_result = SimulationResults(
            generation=pd.Series([1.0] * 10, index=index),
            demand=pd.Series([1.0] * 10, index=index),
            self_consumption=pd.Series([1.0] * 10, index=index),
            battery_charge=pd.Series([0.0] * 10, index=index),
            battery_discharge=pd.Series([0.0] * 10, index=index),
            battery_soc=pd.Series([0.0] * 10, index=index),
            grid_import=pd.Series([0.0] * 10, index=index),
            grid_export=pd.Series([0.0] * 10, index=index),
            import_cost=pd.Series([0.0] * 10, index=index),
            export_revenue=pd.Series([0.0] * 10, index=index),
            tariff_rate=pd.Series([0.0] * 10, index=index),
        )
        fleet_results = FleetResults(
            per_home_results=[home_result],
            home_configs=[HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())],
        )

        results = MultiSweepResults(
            sweep_results={0: (1.5, fleet_results)},
            sweep_values=[1.5],
        )

        sweep_val, fr = results[0]
        assert sweep_val == 1.5
        assert len(fr) == 1


_Result = TypeVar("_Result")


def _emptying_the_cache_after_the_first(results: Iterator[_Result], cache: WeatherCache) -> Iterator[_Result]:
    """Yield results, emptying cache once the first has been drawn and before the rest are."""
    yield next(results)
    cache.clear()
    yield from results


class TestParallelFleetWeather:
    """A fleet run fetches its homes' TMYs from the test's weather_cache in this process before any home runs, and each home's job carries its location's: so each home gets exactly what simulate_home gives it here, whether the run is sequential or its workers start by forkserver (Linux's default from Python 3.14) or spawn (macOS's)."""

    _BATH = Location(latitude=51.38, longitude=-2.36, name="Bath, UK")
    _LOAD =LoadConfig(annual_consumption_kwh=3500.0, use_stochastic=False)

    @pytest.fixture(autouse=True)
    def bristol_and_bath_tmys(
        self, weather_cache: WeatherCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serve a clear 21 June as Bristol's TMY and the same day at half its irradiance as Bath's.

        Workers receive their weather in the job. The test runs in an empty working directory,
        so whatever a worker writes under its working directory stays out of the repository.
        """
        monkeypatch.chdir(tmp_path)
        _JUNE_DAYS.seed_as_bristol_tmy(weather_cache)
        weather_cache.put(synthetic_june_weather(_JUNE_DAYS.first_day, irradiance_scale_per_day=(0.5,)), "tmy", self._BATH)

    @pytest.fixture
    def bristol_and_bath_fleet(self) -> FleetConfig:
        """A Bristol home and a Bath home, each with 4 kW of PV."""
        return FleetConfig(
            homes=[
                HomeConfig(
                    pv_config=PVConfig(capacity_kw=4.0),
                    load_config=self._LOAD,
                    location=location,
                    name=location.name,
                )
                for location in (Location.bristol(), self._BATH)
            ]
        )

    @pytest.fixture
    def bristol_and_bath_sweeps(self) -> list[tuple[float, FleetConfig]]:
        """A sweep of two Bristol homes with 2 kW of PV and a sweep of two Bath homes with 4 kW."""
        return [
            (
                2.0,
                FleetConfig.create_uniform(
                    n_homes=2,
                    pv_config=PVConfig(capacity_kw=2.0),
                    load_config=self._LOAD,
                    location=Location.bristol(),
                ),
            ),
            (
                4.0,
                FleetConfig.create_uniform(
                    n_homes=2,
                    pv_config=PVConfig(capacity_kw=4.0),
                    load_config=self._LOAD,
                    location=self._BATH,
                ),
            ),
        ]

    def test_fleet_jobs_carry_the_weather_fetched_before_the_first_home_ran(
        self, bristol_and_bath_fleet: FleetConfig, weather_cache: WeatherCache
    ) -> None:
        """A sequential simulate_fleet_iter whose cache is emptied once its first home has run gives each home exactly what simulate_home gives it here: a job that read the default weather itself would find the cache empty and be refused at PVGIS."""
        start, end = _JUNE_DAYS.window(1)
        alone = [
            simulate_home(home, start, end, weather=default_weather()) for home in bristol_and_bath_fleet.homes
        ]

        in_fleet = dict(
            _emptying_the_cache_after_the_first(
                simulate_fleet_iter(bristol_and_bath_fleet, start, end, parallel=False), weather_cache
            )
        )

        for index, (home, expected) in enumerate(zip(bristol_and_bath_fleet.homes, alone, strict=True)):
            pd.testing.assert_frame_equal(
                in_fleet[index].to_dataframe(), expected.to_dataframe(), check_exact=True, obj=f"{home.name}'s results"
            )

    def test_multi_sweep_jobs_carry_the_weather_fetched_before_the_first_home_ran(
        self, bristol_and_bath_sweeps: list[tuple[float, FleetConfig]], weather_cache: WeatherCache
    ) -> None:
        """A sequential simulate_multi_sweep_iter whose cache is emptied once its first home has run gives each home exactly what simulate_home gives it here: a job that read the default weather itself would find the cache empty and be refused at PVGIS."""
        start, end = _JUNE_DAYS.window(1)
        alone = {
            (sweep_index, home_index): simulate_home(home, start, end, weather=default_weather())
            for sweep_index, (_, fleet) in enumerate(bristol_and_bath_sweeps)
            for home_index, home in enumerate(fleet.homes)
        }

        in_sweeps = {
            (sweep_index, home_index): results
            for sweep_index, home_index, results in _emptying_the_cache_after_the_first(
                simulate_multi_sweep_iter(bristol_and_bath_sweeps, start, end, parallel=False), weather_cache
            )
        }

        for (sweep_index, home_index), expected in alone.items():
            pd.testing.assert_frame_equal(
                in_sweeps[sweep_index, home_index].to_dataframe(),
                expected.to_dataframe(),
                check_exact=True,
                obj=f"home {home_index} of sweep {sweep_index}",
            )

    @pytest.mark.parametrize("worker_start_method", ["forkserver", "spawn"], indirect=True)
    def test_fleet_gives_each_home_the_results_simulate_home_gives_it_here(
        self, bristol_and_bath_fleet: FleetConfig, worker_start_method: str
    ) -> None:
        """simulate_fleet, sequential or parallel, gives a Bristol home and a Bath home exactly what simulate_home gives each in this process."""
        start, end = _JUNE_DAYS.window(1)
        alone = [
            simulate_home(home, start, end, weather=default_weather()) for home in bristol_and_bath_fleet.homes
        ]
        assert alone[1].total_amounts()["generation_kwh"] < alone[0].total_amounts()["generation_kwh"], (
            "premise: Bath's TMY is less sunny than Bristol's, so a home simulated from the other location's TMY is caught"
        )

        for parallel in (False, True):
            fleet_results = simulate_fleet(bristol_and_bath_fleet, start, end, parallel=parallel, max_workers=2)
            for home, in_fleet, expected in zip(
                bristol_and_bath_fleet.homes, fleet_results.per_home_results, alone, strict=True
            ):
                pd.testing.assert_frame_equal(
                    in_fleet.to_dataframe(),
                    expected.to_dataframe(),
                    check_exact=True,
                    obj=f"{home.name}'s results with parallel={parallel}",
                )

    @pytest.mark.parametrize("worker_start_method", ["forkserver", "spawn"], indirect=True)
    def test_multi_sweep_gives_each_home_the_results_simulate_home_gives_it_here(
        self, bristol_and_bath_sweeps: list[tuple[float, FleetConfig]], worker_start_method: str
    ) -> None:
        """simulate_multi_sweep_iter, sequential or parallel, gives each home of a Bristol sweep and a Bath sweep exactly what simulate_home gives it in this process."""
        start, end = _JUNE_DAYS.window(1)
        for parallel in (False, True):
            collected = collect_multi_sweep_results(
                bristol_and_bath_sweeps,
                simulate_multi_sweep_iter(bristol_and_bath_sweeps, start, end, parallel=parallel, max_workers=2),
            )
            for (pv_kw, fleet), (_, fleet_results) in zip(bristol_and_bath_sweeps, collected.iter_results(), strict=True):
                for home, in_sweep in zip(fleet.homes, fleet_results.per_home_results, strict=True):
                    pd.testing.assert_frame_equal(
                        in_sweep.to_dataframe(),
                        simulate_home(home, start, end, weather=default_weather()).to_dataframe(),
                        check_exact=True,
                        obj=f"{home.name} of the {pv_kw} kW sweep with parallel={parallel}",
                    )
