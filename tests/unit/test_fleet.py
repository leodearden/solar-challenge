"""Tests for fleet simulation."""

import dataclasses
import multiprocessing
import os
import pickle
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import parse_fleet_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    FleetRunner,
    FleetSummary,
    HomesDone,
    aggregate_home_summaries,
    calculate_fleet_summary,
    calculate_home_summaries,
    default_runner,
    fleet_home_seed,
    reusing,
)
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from solar_challenge.weather import WeatherCache, WeatherProvider, default_weather
from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_sim_results
from tests._fleet_runner import (
    HomeStart,
    MarkingHomeSimulator,
    ProcessEndingHomeSimulator,
    finish_marker,
    finished,
    marked_in_this_process,
    start_marker,
    started,
    wait_until_started,
)
from tests._seeded_tmy import ClearJuneDays
from tests._stored_run_fixtures import PRE_975_FLEET_SEG_REVENUE_KEYS
from tests._synthetic_weather import synthetic_june_weather

_ONE_JUNE_DAY = SimulationWindow(date(2024, 6, 1), date(2024, 6, 1), ONE_MINUTE, "Europe/London")
"""A one-day window, 1 June 2024 on a Europe/London minute clock, for summaries built by hand."""


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

    def test_homes_given_as_a_list_are_held_as_a_tuple(self):
        home = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

        fleet = FleetConfig(homes=[home])

        assert fleet.homes == (home,)
        assert type(fleet.homes) is tuple

    @pytest.mark.parametrize("field_name", [f.name for f in dataclasses.fields(FleetConfig)])
    def test_assigning_a_field_raises_frozen_instance_error(self, field_name):
        fleet = FleetConfig(homes=[HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())])

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(fleet, field_name, getattr(fleet, field_name))


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


#: Builds a fleet of three homes with one of FleetConfig's constructors, passing it the seed keyword it is given, if any.
_FleetBuild = Callable[..., FleetConfig]

_THREE_HOMES_BY_CONSTRUCTOR = [
    pytest.param(
        lambda **seed_keyword: FleetConfig.create_uniform(3, PVConfig(4.0), LoadConfig(3400.0), **seed_keyword),
        id="create_uniform",
    ),
    pytest.param(
        lambda **seed_keyword: FleetConfig.create_heterogeneous([4.0] * 3, [None] * 3, [3400.0] * 3, **seed_keyword),
        id="create_heterogeneous",
    ),
]


class TestFleetHomeSeeds:
    """Home i of a seeded fleet has load seed fleet_seed + i, by fleet.fleet_home_seed; an unseeded fleet's homes are unseeded (docs/prds/rng-hand-off.md C8, C9)."""

    @pytest.mark.parametrize(
        ("fleet_seed", "index", "expected"),
        [(None, 0, None), (None, 5, None), (7, 0, 7), (7, 2, 9), (-3, 4, 1)],
    )
    def test_fleet_home_seed_is_none_for_an_unseeded_fleet_and_the_fleet_seed_plus_the_index_otherwise(
        self, fleet_seed: int | None, index: int, expected: int | None
    ) -> None:
        assert fleet_home_seed(fleet_seed, index) == expected

    @pytest.mark.parametrize("build", _THREE_HOMES_BY_CONSTRUCTOR)
    def test_a_seeded_constructor_gives_home_i_the_load_seed_fleet_seed_plus_i(self, build: _FleetBuild) -> None:
        assert [home.load_config.seed for home in build(seed=7).homes] == [7, 8, 9]

    @pytest.mark.parametrize("build", _THREE_HOMES_BY_CONSTRUCTOR)
    def test_an_unseeded_constructor_leaves_every_load_unseeded(self, build: _FleetBuild) -> None:
        assert [home.load_config.seed for home in build(seed=None).homes] == [None, None, None]
        assert [home.load_config.seed for home in build().homes] == [None, None, None]

    def test_create_uniform_gives_each_home_the_template_with_its_own_seed(self) -> None:
        template = LoadConfig(annual_consumption_kwh=3400.0, household_occupants=4, name="template", use_stochastic=False)

        fleet = FleetConfig.create_uniform(3, PVConfig(4.0), template, seed=7)

        assert [home.load_config for home in fleet.homes] == [replace(template, seed=seed) for seed in (7, 8, 9)]

    @pytest.mark.parametrize("fleet_seed", [None, 7])
    def test_create_uniform_refuses_a_seeded_load_template(self, fleet_seed: int | None) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            FleetConfig.create_uniform(3, PVConfig(4.0), LoadConfig(3400.0, seed=42), seed=fleet_seed)

        assert "load_config.seed" in str(refusal.value)
        assert "42" in str(refusal.value)
        assert "seed=" in str(refusal.value)


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

    def test_results_given_as_lists_are_held_as_tuples_of_the_same_objects_unaliased(self, sample_results):
        per_home_results = list(sample_results.per_home_results)
        configs = list(sample_results.home_configs)

        results = FleetResults(per_home_results=per_home_results, home_configs=configs)
        configs.append(configs[0])

        assert type(results.per_home_results) is tuple
        assert type(results.home_configs) is tuple
        assert all(held is given for held, given in zip(results.per_home_results, per_home_results, strict=True))
        assert all(held is given for held, given in zip(results.home_configs, configs[:2], strict=True))
        assert results.home_configs == tuple(configs[:2])

    @pytest.mark.parametrize("field_name", [f.name for f in dataclasses.fields(FleetResults)])
    def test_assigning_a_field_raises_frozen_instance_error(self, sample_results, field_name):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(sample_results, field_name, getattr(sample_results, field_name))

    def test_a_pickled_fleet_unpickles_with_tuple_fields_and_the_same_homes(self, sample_results):
        unpickled = pickle.loads(pickle.dumps(sample_results))

        assert type(unpickled.per_home_results) is tuple
        assert type(unpickled.home_configs) is tuple
        assert unpickled.home_configs == sample_results.home_configs
        for got, sent in zip(unpickled.per_home_results, sample_results.per_home_results, strict=True):
            pd.testing.assert_frame_equal(got.to_dataframe(), sent.to_dataframe())


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

    def test_calculate_fleet_summary_takes_no_seg_rate(self, sample_results):
        """Each home's export revenue is priced when it is simulated, so the fleet's summary takes no SEG rate."""
        with pytest.raises(TypeError):
            calculate_fleet_summary(sample_results, seg_tariff_pence_per_kwh=15.0)

    def test_a_fleet_summary_has_no_seg_revenue_pair(self):
        """A fleet's export revenue is total_export_revenue_gbp: it has no second, SEG revenue total or mean."""
        assert {field.name for field in dataclasses.fields(FleetSummary)}.isdisjoint(PRE_975_FLEET_SEG_REVENUE_KEYS)

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

    def test_each_homes_summary_is_calculate_summary_of_its_results_in_the_fleets_order(self, sample_results):
        """Each home's summary is the one calculate_summary derives from that home's results, listed in per_home_results' order."""
        assert calculate_home_summaries(sample_results) == [
            calculate_summary(results) for results in sample_results.per_home_results
        ]

    def test_calculate_home_summaries_takes_no_seg_rate(self, sample_results):
        """Each home's export revenue is priced when it is simulated, so its summary takes no SEG rate."""
        with pytest.raises(TypeError):
            calculate_home_summaries(sample_results, seg_tariff_pence_per_kwh=15.0)

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
            window=_ONE_JUNE_DAY,
            total_import_cost_gbp=0.75,
            total_export_revenue_gbp=0.125,
            net_cost_gbp=0.625,
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
            window=_ONE_JUNE_DAY,
            total_import_cost_gbp=1.5,
            total_export_revenue_gbp=1.75,
            net_cost_gbp=-0.25,
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
            window=_ONE_JUNE_DAY,
            total_import_cost_gbp=1.5,
            total_export_revenue_gbp=3.75,
            net_cost_gbp=-2.25,
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
            total_net_cost_gbp=-1.875,
            total_import_cost_gbp=3.75,
            total_export_revenue_gbp=5.625,
        )

    def test_a_home_summary_s_retired_seg_revenue_moves_nothing_in_the_fleet_s(self, sample_results):
        """Home summaries carrying the retired seg_revenue_gbp, as stored ones can, aggregate as the same summaries without it."""
        home_summaries = calculate_home_summaries(sample_results)
        carrying_one = [
            replace(summary, seg_revenue_gbp=seg_revenue_gbp)
            for summary, seg_revenue_gbp in zip(home_summaries, (3.60, None, 10.80))
        ]

        assert aggregate_home_summaries(carrying_one) == aggregate_home_summaries(home_summaries)

    def test_aggregating_no_home_summaries_is_refused(self):
        """A fleet summary aggregates at least one home's summary."""
        with pytest.raises(ValueError, match="at least one home"):
            aggregate_home_summaries([])


_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21", tz="Europe/London"), count=1)
bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()


@pytest.fixture
def worker_start_method(request: pytest.FixtureRequest) -> Iterator[str]:
    """Make request.param the start method of the default multiprocessing context until the test ends: the fleet's worker pool uses that start method unless it is fork, which it replaces with forkserver."""
    previous = multiprocessing.get_start_method(allow_none=True)
    multiprocessing.set_start_method(request.param, force=True)
    yield request.param
    multiprocessing.set_start_method(previous, force=True)


_START_METHODS = [
    pytest.param(
        method,
        marks=pytest.mark.skipif(
            method not in multiprocessing.get_all_start_methods(), reason=f"{method} is not a start method here"
        ),
    )
    for method in ("fork", "forkserver", "spawn")
]


class TestFleetRunnerPolicy:
    """A FleetRunner's worker count is None or a whole number of at least 1, its pool's workers never start as a fork of the calling process, and default_runner() runs simulate_home in parallel over default_weather()."""

    @pytest.mark.parametrize("worker_start_method", _START_METHODS, indirect=True)
    def test_a_parallel_calls_homes_start_in_workers_holding_none_of_the_callers_memory_whatever_the_default_start_method(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleet = FleetConfig(homes=[_home("Home 1", 2.0), _home("Home 2", 3.0)], name="Two")
        runner = FleetRunner(
            weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=True, max_workers=2
        )

        with marked_in_this_process("caller"):
            runner.simulate(fleet, *_JUNE_DAYS.window())

        assert {
            name: (start.pid != os.getpid(), start.process_marks) for name, start in started(tmp_path).items()
        } == {"Home 1": (True, ()), "Home 2": (True, ())}

    @pytest.mark.parametrize("max_workers", [0, -1, 1.5, True])
    def test_a_worker_count_other_than_a_whole_number_of_at_least_one_is_refused_naming_it(
        self, max_workers: object
    ) -> None:
        with pytest.raises(ValueError) as caught:
            FleetRunner(weather=default_weather(), home_simulator=simulate_home, max_workers=max_workers)

        assert "max_workers" in str(caught.value)
        assert repr(max_workers) in str(caught.value)

    @pytest.mark.parametrize("max_workers", [None, 3])
    def test_no_worker_count_or_a_whole_number_of_at_least_one_is_kept(self, max_workers: int | None) -> None:
        runner = FleetRunner(weather=default_weather(), home_simulator=simulate_home, max_workers=max_workers)

        assert runner.max_workers == max_workers

    @pytest.mark.usefixtures("bristol_june_tmy")
    def test_the_default_runner_runs_simulate_home_in_parallel_over_the_default_weather(self) -> None:
        runner = default_runner()

        assert runner.home_simulator is simulate_home
        assert runner.parallel is True
        assert runner.max_workers is None
        pd.testing.assert_frame_equal(runner.weather.get(Location.bristol()), default_weather().get(Location.bristol()))


_BATH = Location(latitude=51.38, longitude=-2.36, name="Bath, UK")
_LOAD = LoadConfig(annual_consumption_kwh=3500.0, use_stochastic=False)


def _home(name: str, pv_kw: float, location: Location = Location.bristol()) -> HomeConfig:
    """A home named *name* with *pv_kw* of PV at *location*, whose MarkingHomeSimulator results total *pv_kw* of self-consumption."""
    return HomeConfig(pv_config=PVConfig(capacity_kw=pv_kw), load_config=_LOAD, location=location, name=name)


def _fleets_a_b_c() -> list[FleetConfig]:
    """Fleets A, B and C of two, one and three homes, named "A 1", "A 2"; "B 1"; "C 1", "C 2", "C 3", with 1 to 6 kW of PV in that order."""
    return [
        FleetConfig(homes=[_home("A 1", 1.0), _home("A 2", 2.0)], name="A"),
        FleetConfig(homes=[_home("B 1", 3.0)], name="B"),
        FleetConfig(homes=[_home("C 1", 4.0), _home("C 2", 5.0), _home("C 3", 6.0)], name="C"),
    ]


def _assert_marked_results_of(results: FleetResults, fleet: FleetConfig) -> None:
    """Assert *results* pairs *fleet*'s homes, in order, each with the results MarkingHomeSimulator gives it."""
    assert results.home_configs == fleet.homes
    assert [
        calculate_summary(home_results).total_self_consumption_kwh for home_results in results.per_home_results
    ] == pytest.approx([home.pv_config.capacity_kw for home in fleet.homes])


def _assert_every_started_home_finished(marker_dir: Path) -> None:
    """Assert each home a MarkingHomeSimulator over *marker_dir* started has finished."""
    assert finished(marker_dir) == set(started(marker_dir)), (
        "the call ended while a home it had started was still running"
    )


@dataclass
class _CountingWeather:
    """Serves a clear 21 June at Bristol and that day at half its irradiance at Bath, recording each location it is asked for, in the process that asks."""

    asked: list[Location] = field(default_factory=list)

    def get(self, location: Location) -> pd.DataFrame:
        self.asked.append(location)
        irradiance_scale = {Location.bristol(): 1.0, _BATH: 0.5}[location]
        return synthetic_june_weather(_JUNE_DAYS.first_day, irradiance_scale_per_day=(irradiance_scale,))


class TestFleetRunnerSimulates:
    """A FleetRunner runs each home of each fleet once through its home simulator, on weather it fetched here for the home's location, and pairs each fleet's results with its homes in order."""

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    @pytest.mark.parametrize("parallel", [False, True])
    def test_a_fleets_results_pair_its_homes_in_order_and_progress_counts_each_home_here(
        self, tmp_path: Path, parallel: bool, worker_start_method: str
    ) -> None:
        fleet = FleetConfig(homes=[_home("Home 1", 2.0), _home("Home 2", 3.0), _home("Home 3", 4.0)], name="Three")
        runner = FleetRunner(
            weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=parallel, max_workers=2
        )
        told: list[tuple[int, int, int]] = []

        results = runner.simulate(
            fleet, *_JUNE_DAYS.window(), progress=lambda done, total: told.append((done, total, os.getpid()))
        )

        _assert_marked_results_of(results, fleet)
        assert told == [(1, 3, os.getpid()), (2, 3, os.getpid()), (3, 3, os.getpid())]
        ran_here = [start.pid == os.getpid() for start in started(tmp_path).values()]
        assert ran_here == [not parallel] * 3

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    @pytest.mark.parametrize("parallel", [False, True])
    def test_each_fleet_comes_once_with_its_homes_results_in_order_and_progress_counts_every_home(
        self, tmp_path: Path, parallel: bool, worker_start_method: str
    ) -> None:
        fleets = _fleets_a_b_c()
        runner = FleetRunner(
            weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=parallel, max_workers=2
        )
        told: list[tuple[int, int]] = []

        each = list(
            runner.simulate_each(fleets, *_JUNE_DAYS.window(), progress=lambda done, total: told.append((done, total)))
        )

        assert sorted(index for index, _ in each) == [0, 1, 2]
        for index, results in each:
            _assert_marked_results_of(results, fleets[index])
        assert told == [(done, 6) for done in range(1, 7)]

    def test_a_fleets_results_hold_tuples_not_its_configurations_list(self, tmp_path: Path) -> None:
        homes = [_home("Home 1", 2.0), _home("Home 2", 3.0)]
        fleet = FleetConfig(homes=homes, name="Two")

        results = FleetRunner(
            weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=False
        ).simulate(fleet, *_JUNE_DAYS.window())

        assert type(results.home_configs) is tuple
        assert results.home_configs == tuple(homes)
        assert type(results.per_home_results) is tuple
        with pytest.raises(AttributeError):
            results.home_configs.append(homes[0])
        with pytest.raises(dataclasses.FrozenInstanceError):
            results.home_configs = ()

    def test_no_fleets_yield_nothing_and_fetch_no_weather(self, tmp_path: Path) -> None:
        weather = _CountingWeather()
        runner = FleetRunner(weather=weather, home_simulator=MarkingHomeSimulator(tmp_path))

        assert list(runner.simulate_each([], *_JUNE_DAYS.window())) == []
        assert weather.asked == []

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_a_call_asks_for_each_locations_weather_once_here_and_each_job_carries_its_homes_alone(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        first = FleetConfig(
            homes=[_home("Bristol 1", 2.0), _home("Bath 1", 3.0, _BATH), _home("Bristol 2", 4.0)], name="First"
        )
        second = FleetConfig(homes=[_home("Bath 2", 5.0, _BATH)], name="Second")
        one_fleet, each_fleet = tmp_path / "simulate", tmp_path / "simulate_each"
        one_fleet.mkdir()
        each_fleet.mkdir()

        asked_by_one = _CountingWeather()
        FleetRunner(weather=asked_by_one, home_simulator=MarkingHomeSimulator(one_fleet), max_workers=2).simulate(
            first, *_JUNE_DAYS.window()
        )
        asked_by_each = _CountingWeather()
        list(
            FleetRunner(
                weather=asked_by_each, home_simulator=MarkingHomeSimulator(each_fleet), max_workers=2
            ).simulate_each([first, second], *_JUNE_DAYS.window())
        )

        assert asked_by_one.asked == [Location.bristol(), _BATH]
        assert asked_by_each.asked == [Location.bristol(), _BATH]
        bristol, bath = ("Bristol, UK",), ("Bath, UK",)
        assert {name: start.locations for name, start in started(one_fleet).items()} == {
            "Bristol 1": bristol, "Bath 1": bath, "Bristol 2": bristol,
        }
        assert {name: start.locations for name, start in started(each_fleet).items()} == {
            "Bristol 1": bristol, "Bath 1": bath, "Bristol 2": bristol, "Bath 2": bath,
        }

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_a_call_of_one_home_runs_it_here_even_in_parallel(self, tmp_path: Path, worker_start_method: str) -> None:
        fleet = FleetConfig(homes=[_home("Alone", 2.0)], name="One")
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=True)

        results = runner.simulate(fleet, *_JUNE_DAYS.window())

        _assert_marked_results_of(results, fleet)
        assert started(tmp_path)["Alone"].pid == os.getpid()

    def test_a_home_runs_here_on_weather_holding_its_location_alone(self, tmp_path: Path) -> None:
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path))

        results = runner.simulate_home(_home("Alone", 2.0, _BATH), *_JUNE_DAYS.window())

        assert calculate_summary(results).total_self_consumption_kwh == pytest.approx(2.0)
        assert started(tmp_path) == {"Alone": HomeStart(pid=os.getpid(), locations=("Bath, UK",))}


@pytest.mark.usefixtures("bristol_june_tmy")
class TestFleetRunnerParallelMatchesSequential:
    """A FleetRunner's parallel run of a seeded stochastic fleet gives each home exactly its sequential run's results, in home order, whichever worker draws its demand."""

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
        runner = FleetRunner(weather=default_weather(), home_simulator=simulate_home)

        in_sequence = replace(runner, parallel=False).simulate(fleet, start, end)
        distinct_demands = {tuple(results.demand) for results in in_sequence.per_home_results}
        assert len(distinct_demands) == len(fleet.homes), (
            f"premise: the {len(fleet.homes)} homes, differing only in their seed, drew "
            f"{len(distinct_demands)} distinct demand profiles; profiles drawn from their own seeds differ, "
            "the deterministic Elexon fallback's do not"
        )

        in_parallel = replace(runner, parallel=True, max_workers=workers).simulate(fleet, start, end)
        for home, from_workers, from_sequence in zip(
            fleet.homes, in_parallel.per_home_results, in_sequence.per_home_results, strict=True
        ):
            pd.testing.assert_frame_equal(
                from_workers.to_dataframe(),
                from_sequence.to_dataframe(),
                check_exact=True,
                obj=f"{home.name}'s results from {worker_start_method} workers",
            )


def _with_a_5kwh_battery(home: HomeConfig) -> HomeConfig:
    """*home* fitted with a 5 kWh battery that has no soh override, as an unaged scenario's home is."""
    return replace(home, battery_config=BatteryConfig(capacity_kwh=5.0))


def _battery_at_soh(home: HomeConfig, soh: float) -> HomeConfig:
    """*home* with its battery's soh override set to *soh*, as finance._aged_homes sets it: 1.0 at age 0."""
    assert home.battery_config is not None, f"{home.name!r} has no battery whose soh to set"
    return replace(home, battery_config=replace(home.battery_config, soh=soh))


_BATTERY_HOME = _with_a_5kwh_battery(_home("Battery", 4.0))
_PV_HOME = _home("PV only", 3.0)
_HELD_HOMES = (_BATTERY_HOME, _PV_HOME)
_AGE_0_HOMES = (_battery_at_soh(_BATTERY_HOME, 1.0), _PV_HOME)
_ONE_DAY = pd.Timedelta(days=1)
_NO_SHIFT = pd.Timedelta(0)
_JUNE_DAY = _JUNE_DAYS.first_day.date()


def _held_results(homes: Sequence[HomeConfig] = _HELD_HOMES) -> FleetResults:
    """A distinct make_sim_results of _JUNE_DAYS' one day on one-minute rows, the window simulate_home runs a Bristol home over for that day, for each of *homes*, paired with them."""
    return make_fleet_results_of(
        [make_sim_results(days=1, first_day=_JUNE_DAY, cadence=ONE_MINUTE) for _ in homes], homes=homes
    )


@dataclass
class _CountingSimulate:
    """A FleetSimulate that records each (fleet, start, end) it is asked for and answers make_fleet_results of the fleet's homes over one day, keeping its last answer."""

    asked: list[tuple[FleetConfig, pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    returned: FleetResults | None = None

    def __call__(self, fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        self.asked.append((fleet, start, end))
        self.returned = make_fleet_results(homes=fleet.homes, days=1)
        return self.returned


class TestReusingAnswersAFleetThatSimulatesAsTheResultsFleet:
    """reusing answers a fleet whose homes at their starting soh are its results' homes, at its window's instants on their clocks, from those results paired with the asked homes, refusing results that do not cover each home's run window; any other fleet or window goes to its simulate."""

    def test_the_results_homes_at_their_starting_soh_over_the_same_window_are_answered_from_the_results_paired_with_the_asked_homes(
        self,
    ) -> None:
        sim = _CountingSimulate()
        start, end = _JUNE_DAYS.window()
        results = _held_results()
        asked = FleetConfig(homes=list(_AGE_0_HOMES), name="proj-age-0")
        assert asked.homes != results.home_configs, "premise: the asked battery's soh is 1.0, the held battery's None"

        answer = reusing(sim, results, start, end)(asked, start, end)

        assert sim.asked == []
        assert len(answer) == len(results)
        for answered, held in zip(answer.per_home_results, results.per_home_results, strict=True):
            assert answered is held
        assert answer.home_configs == asked.homes

    @pytest.mark.parametrize(
        ("asked_homes", "start_moved_by", "end_moved_by"),
        [
            pytest.param(
                (_battery_at_soh(_BATTERY_HOME, 0.9), _PV_HOME), _NO_SHIFT, _NO_SHIFT, id="soh-0.9-against-none"
            ),
            pytest.param(_AGE_0_HOMES, _NO_SHIFT, _ONE_DAY, id="a-later-end"),
            pytest.param(_AGE_0_HOMES, -_ONE_DAY, _NO_SHIFT, id="an-earlier-start"),
            pytest.param(
                (_AGE_0_HOMES[0], replace(_PV_HOME, pv_config=replace(_PV_HOME.pv_config, system_age_years=1.0))),
                _NO_SHIFT,
                _NO_SHIFT,
                id="an-aged-pv",
            ),
        ],
    )
    def test_a_fleet_that_may_simulate_otherwise_or_another_window_is_simulated(
        self, asked_homes: tuple[HomeConfig, ...], start_moved_by: pd.Timedelta, end_moved_by: pd.Timedelta
    ) -> None:
        sim = _CountingSimulate()
        start, end = _JUNE_DAYS.window()
        asked = FleetConfig(homes=list(asked_homes), name="proj-age-0")
        asked_start, asked_end = start + start_moved_by, end + end_moved_by

        answer = reusing(sim, _held_results(), start, end)(asked, asked_start, asked_end)

        assert sim.asked == [(asked, asked_start, asked_end)]
        assert answer is sim.returned

    def test_the_same_instants_on_another_clock_are_simulated(self) -> None:
        sim = _CountingSimulate()
        start, end = _JUNE_DAYS.window()
        asked = FleetConfig(homes=list(_AGE_0_HOMES), name="proj-age-0")
        asked_start, asked_end = start.tz_convert("UTC"), end.tz_convert("UTC")
        assert (asked_start, asked_end) == (start, end), "premise: the instants of the window reusing wraps with"

        answer = reusing(sim, _held_results(), start, end)(asked, asked_start, asked_end)

        assert sim.asked == [(asked, asked_start, asked_end)]
        assert answer is sim.returned

    def test_a_home_whose_load_is_stochastic_and_unseeded_is_answered_with_the_results_draw(self) -> None:
        sim = _CountingSimulate()
        start, end = _JUNE_DAYS.window()
        unseeded = replace(_BATTERY_HOME, load_config=replace(_LOAD, use_stochastic=True))
        assert unseeded.load_config.seed is None, "premise: each simulation of the home's load takes a fresh draw"
        results = _held_results((unseeded,))

        answer = reusing(sim, results, start, end)(
            FleetConfig(homes=[_battery_at_soh(unseeded, 1.0)], name="proj-age-0"), start, end
        )

        assert sim.asked == []
        assert answer.per_home_results[0] is results.per_home_results[0]

    @pytest.mark.parametrize(
        "moment",
        [
            pytest.param(pd.Timestamp("2024-06-21"), id="naive"),
            pytest.param(pd.Timestamp("2024-06-21", tz="UTC"), id="utc"),
            pytest.param(pd.Timestamp("2024-06-20 23:30", tz="UTC"), id="utc-the-evening-before"),
        ],
    )
    def test_results_over_each_homes_run_window_are_reused_whatever_clock_the_window_is_given_on(
        self, moment: pd.Timestamp
    ) -> None:
        sim = _CountingSimulate()
        results = _held_results()

        answer = reusing(sim, results, moment, moment)(
            FleetConfig(homes=list(_AGE_0_HOMES), name="proj-age-0"), moment, moment
        )

        assert sim.asked == []
        for answered, held in zip(answer.per_home_results, results.per_home_results, strict=True):
            assert answered is held

    @pytest.mark.parametrize(
        ("held_home", "held_first_day", "held_cadence", "moment", "home_run_window"),
        [
            pytest.param(
                _BATTERY_HOME,
                date(2024, 6, 20),
                ONE_MINUTE,
                _JUNE_DAYS.first_day,
                SimulationWindow(_JUNE_DAY, _JUNE_DAY, ONE_MINUTE, "Europe/London"),
                id="the-day-before",
            ),
            pytest.param(
                _BATTERY_HOME,
                _JUNE_DAY,
                ONE_MINUTE,
                pd.Timestamp("2024-06-21 23:30", tz="UTC"),
                SimulationWindow(date(2024, 6, 22), date(2024, 6, 22), ONE_MINUTE, "Europe/London"),
                id="a-utc-moment-on-the-homes-next-day",
            ),
            pytest.param(
                _BATTERY_HOME,
                _JUNE_DAY,
                timedelta(hours=1),
                _JUNE_DAYS.first_day,
                SimulationWindow(_JUNE_DAY, _JUNE_DAY, ONE_MINUTE, "Europe/London"),
                id="hourly-rows",
            ),
            pytest.param(
                replace(
                    _BATTERY_HOME,
                    location=Location(latitude=40.71, longitude=-74.01, timezone="America/New_York", name="New York"),
                ),
                _JUNE_DAY,
                ONE_MINUTE,
                pd.Timestamp("2024-06-21", tz="America/New_York"),
                SimulationWindow(_JUNE_DAY, _JUNE_DAY, ONE_MINUTE, "America/New_York"),
                id="a-home-on-another-clock",
            ),
        ],
    )
    def test_results_that_do_not_cover_each_homes_run_window_are_refused_naming_both_windows(
        self,
        held_home: HomeConfig,
        held_first_day: date,
        held_cadence: timedelta,
        moment: pd.Timestamp,
        home_run_window: SimulationWindow,
    ) -> None:
        sim = _CountingSimulate()
        held = make_fleet_results_of(
            [make_sim_results(days=1, first_day=held_first_day, cadence=held_cadence)], homes=[held_home]
        )

        with pytest.raises(ValueError) as refused:
            reusing(sim, held, moment, moment)(
                FleetConfig(homes=[_battery_at_soh(held_home, 1.0)], name="proj-age-0"), moment, moment
            )

        message = str(refused.value)
        assert repr(held.per_home_results[0].window) in message
        assert repr(home_run_window) in message
        assert repr(held_home.name) in message
        assert sim.asked == []

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            pytest.param(*_JUNE_DAYS.window(), id="on-the-homes-clock"),
            pytest.param(*(pd.Timestamp("2024-06-21"),) * 2, id="naive"),
            pytest.param(*(pd.Timestamp("2024-06-21", tz="UTC"),) * 2, id="utc"),
        ],
    )
    @pytest.mark.usefixtures("bristol_june_tmy")
    def test_what_it_answers_is_what_the_runner_simulates_for_the_asked_fleet(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> None:
        runner = FleetRunner(weather=default_weather(), home_simulator=simulate_home, parallel=False)
        fleet = FleetConfig(
            homes=[_with_a_5kwh_battery(_home("Home 1", 4.0)), _with_a_5kwh_battery(_home("Home 2", 3.0))],
            name="bill run",
        )
        held = runner.simulate(fleet, start, end)
        asked = FleetConfig(homes=[_battery_at_soh(home, 1.0) for home in fleet.homes], name="proj-age-0")

        answer = reusing(runner.simulate, held, start, end)(asked, start, end)

        assert [
            answered is from_held
            for answered, from_held in zip(answer.per_home_results, held.per_home_results, strict=True)
        ] == [True, True], "premise: the asked fleet is answered from held, not simulated again"
        assert answer.home_configs == asked.homes
        simulated = runner.simulate(asked, start, end)
        for home, answered, from_runner in zip(
            asked.homes, answer.per_home_results, simulated.per_home_results, strict=True
        ):
            pd.testing.assert_frame_equal(
                answered.to_dataframe(),
                from_runner.to_dataframe(),
                check_exact=True,
                obj=f"{home.name}'s answered results",
            )


def _uniform_fleet(n_homes: int, name: str) -> FleetConfig:
    """A fleet named *name* of *n_homes* homes named Home 1 onwards, each with 4 kW of PV."""
    return FleetConfig.create_uniform(n_homes=n_homes, pv_config=PVConfig(capacity_kw=4.0), load_config=_LOAD, name=name)


def _one_home_then_five() -> list[FleetConfig]:
    """A fleet "One" of the home "Alone", then _uniform_fleet(5, "Five"): six homes in two fleets, each home named differently."""
    return [FleetConfig(homes=[_home("Alone", 2.0)], name="One"), _uniform_fleet(5, "Five")]


def _raising_at_the_second_home(raised: BaseException) -> HomesDone:
    """A progress sink that raises *raised* when told the second home has finished."""

    def homes_done(done: int, total: int) -> None:
        if done == 2:
            raise raised

    return homes_done


def _raising_at_the_second_home_once_a_third_has_started(raised: BaseException, marker_dir: Path) -> HomesDone:
    """A progress sink that, when told the second home has finished, waits until a third home has started in *marker_dir*, then raises *raised*."""

    def homes_done(done: int, total: int) -> None:
        if done == 2:
            wait_until_started(marker_dir, at_least=3, within=10)
            raise raised

    return homes_done


def _raising_its_own_broken_process_pool(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
) -> SimulationResults:
    """A home simulator that raises BrokenProcessPool at every home, as one whose own process pool broke would."""
    raise BrokenProcessPool(f"{config.name}'s own process pool broke")


class TestFleetRunnerNamesAFailedHomeAndCancelsTheRest:
    """A home's failure re-raises its own exception with a note naming the home and its fleet, a progress sink's exception propagates as it was raised, and either way no home not yet handed to the pool starts and the call ends only once every home started has finished; a BrokenProcessPool, whether a worker process broke the pool or a home raised it, in parallel or in turn, names a home only as one left unfinished."""

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_a_failed_home_is_named_on_its_own_exception_and_the_homes_still_pending_are_cancelled(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleet = _uniform_fleet(7, "Seven")
        home_simulator = MarkingHomeSimulator(
            tmp_path,
            failing=frozenset({"Home 1"}),
            seconds=0.2,
            held_until=(
                ("Home 1", start_marker(tmp_path, "Home 2")),
                ("Home 2", finish_marker(tmp_path, "Home 1")),
            ),
        )
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=True, max_workers=2)

        with pytest.raises(ValueError) as caught:
            runner.simulate(fleet, *_JUNE_DAYS.window())

        assert type(caught.value) is ValueError
        assert str(caught.value) == "Home 1 cannot be simulated"
        assert caught.value.__notes__ == ["simulating home 0 ('Home 1') of fleet 0 ('Seven')"]
        _assert_every_started_home_finished(tmp_path)
        assert len(started(tmp_path)) < len(fleet.homes), (
            "a later home reaches the pool only once another home's results are read here, so the seventh home "
            "never started"
        )

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_on_one_worker_a_failed_home_is_named_on_its_own_exception_and_no_later_home_starts(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleet = _uniform_fleet(5, "Five")
        home_simulator = MarkingHomeSimulator(tmp_path, failing=frozenset({"Home 1"}), seconds=0.2)
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=True, max_workers=1)

        with pytest.raises(ValueError) as caught:
            runner.simulate(fleet, *_JUNE_DAYS.window())

        assert caught.value.__notes__ == ["simulating home 0 ('Home 1') of fleet 0 ('Five')"]
        _assert_every_started_home_finished(tmp_path)
        assert set(started(tmp_path)) == {"Home 1"}, (
            "the pool was handed Home 1 alone, and is handed a later home only once a finished home's results have "
            "been read here, so reading Home 1's failure raised before any later home was handed on"
        )

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_a_pool_a_worker_process_broke_names_a_home_only_as_unfinished(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleet = _uniform_fleet(4, "Four")
        home_simulator = ProcessEndingHomeSimulator(
            MarkingHomeSimulator(tmp_path, seconds=0.2), ending=frozenset({"Home 2"})
        )
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=True, max_workers=2)

        with pytest.raises(BrokenProcessPool) as caught:
            runner.simulate(fleet, *_JUNE_DAYS.window())

        assert type(caught.value) is BrokenProcessPool
        (note,) = caught.value.__notes__
        assert note in {
            f"the process pool broke before home {index} ({home.name!r}) of fleet 0 ('Four') finished; "
            "the process that ended may have been simulating another home"
            for index, home in enumerate(fleet.homes)
        }

    def test_in_turn_a_broken_process_pool_a_home_raised_names_it_only_as_unfinished_as_in_parallel(self) -> None:
        runner = FleetRunner(
            weather=_CountingWeather(), home_simulator=_raising_its_own_broken_process_pool, parallel=False
        )

        with pytest.raises(BrokenProcessPool) as caught:
            runner.simulate(_uniform_fleet(3, "Three"), *_JUNE_DAYS.window())

        assert str(caught.value) == "Home 1's own process pool broke"
        assert caught.value.__notes__ == [
            "the process pool broke before home 0 ('Home 1') of fleet 0 ('Three') finished; "
            "the process that ended may have been simulating another home"
        ]

    def test_in_turn_a_failed_home_is_named_on_its_own_exception_and_no_later_home_starts(self, tmp_path: Path) -> None:
        fleet = _uniform_fleet(5, "Five")
        home_simulator = MarkingHomeSimulator(tmp_path, failing=frozenset({"Home 3"}))
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=False)

        with pytest.raises(ValueError) as caught:
            runner.simulate(fleet, *_JUNE_DAYS.window())

        assert caught.value.__notes__ == ["simulating home 2 ('Home 3') of fleet 0 ('Five')"]
        assert set(started(tmp_path)) == {"Home 1", "Home 2", "Home 3"}

    def test_a_failed_home_of_a_later_fleet_is_named_with_its_place_in_that_fleet(self, tmp_path: Path) -> None:
        fleets = [
            FleetConfig(homes=[_home("A 1", 1.0), _home("A 2", 2.0)], name="A"),
            FleetConfig(homes=[_home("B 1", 3.0), _home("B 2", 4.0)], name="B"),
        ]
        home_simulator = MarkingHomeSimulator(tmp_path, failing=frozenset({"B 2"}))
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=False)

        with pytest.raises(ValueError) as caught:
            list(runner.simulate_each(fleets, *_JUNE_DAYS.window()))

        assert caught.value.__notes__ == ["simulating home 1 ('B 2') of fleet 1 ('B')"]

    def test_in_turn_a_progress_sinks_exception_propagates_as_raised_and_no_later_home_starts(
        self, tmp_path: Path
    ) -> None:
        raised = RuntimeError("the progress display failed")
        runner = FleetRunner(
            weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path, seconds=0.2), parallel=False
        )

        with pytest.raises(RuntimeError) as caught:
            runner.simulate(_uniform_fleet(5, "Five"), *_JUNE_DAYS.window(), progress=_raising_at_the_second_home(raised))

        assert caught.value is raised
        assert getattr(caught.value, "__notes__", []) == []
        assert set(started(tmp_path)) == {"Home 1", "Home 2"}

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_a_progress_sinks_exception_propagates_as_raised_and_the_homes_still_pending_are_cancelled(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleet = _uniform_fleet(6, "Six")
        raised = RuntimeError("the progress display failed")
        runner = FleetRunner(
            weather=_CountingWeather(),
            home_simulator=MarkingHomeSimulator(tmp_path, seconds=0.2),
            parallel=True,
            max_workers=1,
        )

        with pytest.raises(RuntimeError) as caught:
            runner.simulate(
                fleet,
                *_JUNE_DAYS.window(),
                progress=_raising_at_the_second_home_once_a_third_has_started(raised, tmp_path),
            )

        assert caught.value is raised
        assert getattr(caught.value, "__notes__", []) == []
        _assert_every_started_home_finished(tmp_path)
        assert set(started(tmp_path)) == {"Home 1", "Home 2", "Home 3"}, (
            "the pool holds one home per worker, and the next home is handed to it from this process only as a "
            "finished home's results are read, so when the sink raised at the second home only the third had been "
            "handed on"
        )


class TestFleetRunnerYieldsEachFleetAsItsLastHomeFinishes:
    """simulate_each yields each fleet as its last home finishes, not at the end of the call, and once the iterator is closed early no home not yet handed to the pool starts and the call returns once every home started has finished."""

    def test_in_turn_each_fleet_is_yielded_once_its_last_home_finishes_and_before_a_later_home_starts(
        self, tmp_path: Path
    ) -> None:
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=False)
        told: list[tuple[int, int]] = []
        at_each_fleet: list[tuple[int, list[tuple[int, int]], set[str]]] = []

        for index, _ in runner.simulate_each(
            _fleets_a_b_c(), *_JUNE_DAYS.window(), progress=lambda done, total: told.append((done, total))
        ):
            at_each_fleet.append((index, list(told), set(started(tmp_path))))

        assert at_each_fleet == [
            (0, [(1, 6), (2, 6)], {"A 1", "A 2"}),
            (1, [(1, 6), (2, 6), (3, 6)], {"A 1", "A 2", "B 1"}),
            (2, [(done, 6) for done in range(1, 7)], {"A 1", "A 2", "B 1", "C 1", "C 2", "C 3"}),
        ]

    def test_in_turn_closing_the_iterator_after_the_first_fleet_does_not_run_the_homes_left(
        self, tmp_path: Path
    ) -> None:
        fleets = _one_home_then_five()
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=MarkingHomeSimulator(tmp_path), parallel=False)
        each = runner.simulate_each(fleets, *_JUNE_DAYS.window())

        index, results = next(each)
        started_when_yielded = set(started(tmp_path))
        each.close()

        assert index == 0
        _assert_marked_results_of(results, fleets[0])
        assert started_when_yielded == {"Alone"}
        assert set(started(tmp_path)) == started_when_yielded

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_closing_the_iterator_after_the_first_fleet_cancels_the_homes_still_pending(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleets = _one_home_then_five()
        home_simulator = MarkingHomeSimulator(tmp_path, seconds=0.2)
        runner = FleetRunner(weather=_CountingWeather(), home_simulator=home_simulator, parallel=True, max_workers=1)
        each = runner.simulate_each(fleets, *_JUNE_DAYS.window())

        index, results = next(each)
        wait_until_started(tmp_path, at_least=2, within=10)
        each.close()

        assert index == 0
        _assert_marked_results_of(results, fleets[0])
        _assert_every_started_home_finished(tmp_path)
        assert set(started(tmp_path)) == {"Alone", "Home 1"}, (
            "when fleet One was yielded, only Home 1 had been handed to the one worker, so closing the iterator left "
            "Home 2 onward unstarted"
        )

    @pytest.mark.parametrize("worker_start_method", ["forkserver"], indirect=True)
    def test_in_parallel_a_later_fleet_whose_homes_finish_first_is_yielded_before_an_earlier_fleet_still_running(
        self, tmp_path: Path, worker_start_method: str
    ) -> None:
        fleets = [
            FleetConfig(homes=[_home("A 1", 1.0), _home("A 2", 2.0)], name="A"),
            FleetConfig(homes=[_home("B 1", 3.0)], name="B"),
        ]
        release = tmp_path / "a fleet was yielded"
        runner = FleetRunner(
            weather=_CountingWeather(),
            home_simulator=MarkingHomeSimulator(tmp_path, held_until=(("A 1", release),)),
            parallel=True,
            max_workers=2,
        )
        yielded: list[int] = []

        for index, results in runner.simulate_each(fleets, *_JUNE_DAYS.window()):
            yielded.append(index)
            release.touch()
            _assert_marked_results_of(results, fleets[index])

        assert yielded == [1, 0], (
            "A 1 held one worker until a fleet was yielded, so B 1 ran on the other worker and fleet B finished "
            "while fleet A was still running"
        )


def _emptying_after_the_first_home(cache: WeatherCache) -> HomesDone:
    """A progress sink that empties *cache* once the first home of the call has finished, before any other home runs in a sequential call."""

    def homes_done(done: int, total: int) -> None:
        if done == 1:
            cache.clear()

    return homes_done


class TestParallelFleetWeather:
    """A fleet run fetches its homes' TMYs from the test's weather_cache in this process before any home runs, and each home's job carries its location's: so each home gets exactly what simulate_home gives it here, whether the run is sequential or its workers start by forkserver (Linux's default from Python 3.14) or spawn (macOS's)."""

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
        weather_cache.put(synthetic_june_weather(_JUNE_DAYS.first_day, irradiance_scale_per_day=(0.5,)), "tmy", _BATH)

    @pytest.fixture
    def bristol_and_bath_fleet(self) -> FleetConfig:
        """A Bristol home and a Bath home, each with 4 kW of PV."""
        return FleetConfig(
            homes=[
                HomeConfig(
                    pv_config=PVConfig(capacity_kw=4.0),
                    load_config=_LOAD,
                    location=location,
                    name=location.name,
                )
                for location in (Location.bristol(), _BATH)
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
                    load_config=_LOAD,
                    location=Location.bristol(),
                ),
            ),
            (
                4.0,
                FleetConfig.create_uniform(
                    n_homes=2,
                    pv_config=PVConfig(capacity_kw=4.0),
                    load_config=_LOAD,
                    location=_BATH,
                ),
            ),
        ]

    def test_a_runners_jobs_carry_the_weather_it_fetched_before_its_first_home_ran(
        self, bristol_and_bath_fleet: FleetConfig, weather_cache: WeatherCache
    ) -> None:
        """A sequential FleetRunner.simulate whose cache is emptied once its first home has finished gives each home exactly what simulate_home gives it here: a job that read the default weather itself would find the cache empty and be refused at PVGIS."""
        start, end = _JUNE_DAYS.window(1)
        alone = [
            simulate_home(home, start, end, weather=default_weather()) for home in bristol_and_bath_fleet.homes
        ]
        runner = FleetRunner(weather=default_weather(), home_simulator=simulate_home, parallel=False)

        in_fleet = runner.simulate(
            bristol_and_bath_fleet, start, end, progress=_emptying_after_the_first_home(weather_cache)
        )

        for home, from_fleet, expected in zip(bristol_and_bath_fleet.homes, in_fleet.per_home_results, alone, strict=True):
            pd.testing.assert_frame_equal(
                from_fleet.to_dataframe(), expected.to_dataframe(), check_exact=True, obj=f"{home.name}'s results"
            )

    def test_each_fleets_jobs_carry_the_weather_the_runner_fetched_before_its_first_home_ran(
        self, bristol_and_bath_sweeps: list[tuple[float, FleetConfig]], weather_cache: WeatherCache
    ) -> None:
        """A sequential FleetRunner.simulate_each over two fleets whose cache is emptied once the first home has finished gives each home exactly what simulate_home gives it here: a job that read the default weather itself would find the cache empty and be refused at PVGIS."""
        start, end = _JUNE_DAYS.window(1)
        fleets = [fleet for _, fleet in bristol_and_bath_sweeps]
        alone = [[simulate_home(home, start, end, weather=default_weather()) for home in fleet.homes] for fleet in fleets]
        runner = FleetRunner(weather=default_weather(), home_simulator=simulate_home, parallel=False)

        by_index = dict(
            runner.simulate_each(fleets, start, end, progress=_emptying_after_the_first_home(weather_cache))
        )

        assert sorted(by_index) == [0, 1]
        for fleet_index, expected_homes in enumerate(alone):
            for home_index, (from_fleet, expected) in enumerate(
                zip(by_index[fleet_index].per_home_results, expected_homes, strict=True)
            ):
                pd.testing.assert_frame_equal(
                    from_fleet.to_dataframe(),
                    expected.to_dataframe(),
                    check_exact=True,
                    obj=f"home {home_index} of fleet {fleet_index}",
                )

    @pytest.mark.parametrize("worker_start_method", ["forkserver", "spawn"], indirect=True)
    def test_a_runner_gives_each_home_of_a_fleet_the_results_simulate_home_gives_it_here(
        self, bristol_and_bath_fleet: FleetConfig, worker_start_method: str
    ) -> None:
        """FleetRunner.simulate, sequential or parallel, gives a Bristol home and a Bath home exactly what simulate_home gives each in this process."""
        start, end = _JUNE_DAYS.window(1)
        alone = [
            simulate_home(home, start, end, weather=default_weather()) for home in bristol_and_bath_fleet.homes
        ]
        assert alone[1].total_amounts()["generation_kwh"] < alone[0].total_amounts()["generation_kwh"], (
            "premise: Bath's TMY is less sunny than Bristol's, so a home simulated from the other location's TMY is caught"
        )

        for parallel in (False, True):
            runner = FleetRunner(
                weather=default_weather(), home_simulator=simulate_home, parallel=parallel, max_workers=2
            )
            fleet_results = runner.simulate(bristol_and_bath_fleet, start, end)
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
    def test_a_runner_gives_each_home_of_each_fleet_the_results_simulate_home_gives_it_here(
        self, bristol_and_bath_sweeps: list[tuple[float, FleetConfig]], worker_start_method: str
    ) -> None:
        """FleetRunner.simulate_each, sequential or parallel, gives each home of a Bristol fleet and a Bath fleet exactly what simulate_home gives it in this process."""
        start, end = _JUNE_DAYS.window(1)
        fleets = [fleet for _, fleet in bristol_and_bath_sweeps]
        for parallel in (False, True):
            runner = FleetRunner(
                weather=default_weather(), home_simulator=simulate_home, parallel=parallel, max_workers=2
            )
            by_index = dict(runner.simulate_each(fleets, start, end))
            assert sorted(by_index) == [0, 1]
            for fleet_index, (pv_kw, fleet) in enumerate(bristol_and_bath_sweeps):
                for home, in_fleet in zip(fleet.homes, by_index[fleet_index].per_home_results, strict=True):
                    pd.testing.assert_frame_equal(
                        in_fleet.to_dataframe(),
                        simulate_home(home, start, end, weather=default_weather()).to_dataframe(),
                        check_exact=True,
                        obj=f"{home.name} of the {pv_kw} kW fleet with parallel={parallel}",
                    )
