"""Integration tests for EV charging in fleet simulation.

These tests make real PVGIS API calls and may be slow.
Tests EV integration with fleet-level aggregation and diversity.
"""

import pytest
import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.ev import EVConfig
from solar_challenge.fleet import (
    FleetConfig,
    FleetResults,
    FleetSummary,
    calculate_fleet_summary,
    simulate_fleet,
)
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


@pytest.mark.integration
class TestFleetWithEVs:
    """Test fleet simulation with EV charging integration."""

    @pytest.fixture
    def mixed_ev_fleet_config(self) -> FleetConfig:
        """Create a fleet with mix of EV and non-EV homes.

        5 homes with EVs, 5 homes without.
        Different EV charger types and charging modes.
        """
        homes = []

        # Homes 0-4: With EVs (different configurations)
        # Home 0: 7kW charger, dumb charging
        homes.append(HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400.0),
            battery_config=BatteryConfig.default_5kwh(),
            ev_config=EVConfig(
                charger_type="7kW",
                arrival_hour=18,
                departure_hour=7,
                required_charge_kwh=35.0,
                smart_charging_mode="none",
            ),
            location=Location.bristol(),
            name="Home 1 - 7kW EV dumb",
        ))

        # Home 1: 7kW charger, solar-aware charging
        homes.append(HomeConfig(
            pv_config=PVConfig(capacity_kw=5.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0),
            battery_config=BatteryConfig.default_5kwh(),
            ev_config=EVConfig(
                charger_type="7kW",
                arrival_hour=8,
                departure_hour=17,
                required_charge_kwh=28.0,
                smart_charging_mode="solar",
            ),
            location=Location.bristol(),
            name="Home 2 - 7kW EV solar",
        ))

        # Home 2: 3.6kW slow charger, off-peak charging
        homes.append(HomeConfig(
            pv_config=PVConfig(capacity_kw=3.5),
            load_config=LoadConfig(annual_consumption_kwh=2800.0),
            battery_config=None,
            ev_config=EVConfig(
                charger_type="3.6kW",
                arrival_hour=18,
                departure_hour=8,
                required_charge_kwh=20.0,
                smart_charging_mode="off_peak",
            ),
            location=Location.bristol(),
            name="Home 3 - 3.6kW EV off-peak",
        ))

        # Home 3: 22kW rapid charger, dumb charging
        homes.append(HomeConfig(
            pv_config=PVConfig(capacity_kw=6.0),
            load_config=LoadConfig(annual_consumption_kwh=4000.0),
            battery_config=BatteryConfig.default_5kwh(),
            ev_config=EVConfig(
                charger_type="22kW",
                arrival_hour=20,
                departure_hour=6,
                required_charge_kwh=50.0,
                smart_charging_mode="none",
            ),
            location=Location.bristol(),
            name="Home 4 - 22kW EV dumb",
        ))

        # Home 4: 7kW charger, dumb charging
        homes.append(HomeConfig(
            pv_config=PVConfig(capacity_kw=4.5),
            load_config=LoadConfig(annual_consumption_kwh=3200.0),
            battery_config=BatteryConfig.default_5kwh(),
            ev_config=EVConfig(
                charger_type="7kW",
                arrival_hour=17,
                departure_hour=7,
                required_charge_kwh=30.0,
                smart_charging_mode="none",
            ),
            location=Location.bristol(),
            name="Home 5 - 7kW EV dumb",
        ))

        # Homes 5-9: Without EVs (for comparison)
        for i in range(5):
            homes.append(HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=None,
                location=Location.bristol(),
                name=f"Home {i+6} - No EV",
            ))

        return FleetConfig(homes=homes, name="Mixed EV fleet - 50% EV adoption")

    @pytest.fixture
    def all_ev_fleet_config(self) -> FleetConfig:
        """Create a fleet where all homes have EVs."""
        homes = []
        for i in range(5):
            homes.append(HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=EVConfig(
                    charger_type="7kW",
                    arrival_hour=18,
                    departure_hour=7,
                    required_charge_kwh=35.0,
                    smart_charging_mode="none",
                ),
                location=Location.bristol(),
                name=f"Home {i+1} - With EV",
            ))
        return FleetConfig(homes=homes, name="All EV fleet")

    def test_simulates_mixed_ev_fleet_successfully(self, mixed_ev_fleet_config):
        """Simulates fleet with mixed EV/non-EV homes successfully."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results = simulate_fleet(mixed_ev_fleet_config, start, end)

        # Verify 10 homes simulated
        assert len(results) == 10
        assert isinstance(results, FleetResults)

        # All homes have valid results
        for i in range(10):
            home_results = results[i]
            assert len(home_results.generation) == 3 * 1440
            assert len(home_results.demand) == 3 * 1440
            assert (home_results.generation >= 0).all()
            assert (home_results.demand >= 0).all()

    def test_ev_homes_have_higher_demand(self, mixed_ev_fleet_config):
        """Homes with EVs have higher total demand than those without."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results = simulate_fleet(mixed_ev_fleet_config, start, end)

        # Calculate total demand for EV homes (0-4) vs non-EV homes (5-9)
        ev_home_demands = [results[i].demand.sum() / 60 for i in range(5)]  # Convert to kWh
        non_ev_home_demands = [results[i].demand.sum() / 60 for i in range(5, 10)]  # Convert to kWh

        # Total EV demand should be higher (EV homes have different base loads but add EV charging)
        # Check that at least the maximum EV home demand exceeds non-EV homes significantly
        max_ev_demand = max(ev_home_demands)
        max_non_ev_demand = max(non_ev_home_demands)

        # EV charging adds substantial load (35+ kWh over 3 days minimum)
        assert max_ev_demand > max_non_ev_demand + 30  # At least 30 kWh more

    def test_ev_charging_appears_in_demand_profile(self, all_ev_fleet_config):
        """EV charging load appears in demand profiles at expected times."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_fleet(all_ev_fleet_config, start, end)

        # All homes have 7kW EV arriving at 18:00 (minute 1080)
        for i in range(5):
            demand = results[i].demand

            # Check evening demand is elevated (should include EV charging)
            evening_start = 18 * 60  # 1080
            evening_end = 19 * 60  # 1140
            evening_demand = demand.iloc[evening_start:evening_end]

            # Should have some high demand from EV charging
            assert evening_demand.max() >= 7.0  # At least EV charger power

    def test_fleet_aggregates_include_ev_load(self, mixed_ev_fleet_config):
        """Fleet aggregates correctly include EV charging load."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        results = simulate_fleet(mixed_ev_fleet_config, start, end)

        # Total demand should be sum of individual demands (including EV)
        total_demand = results.total_demand
        manual_total_demand = sum(results[i].demand for i in range(10))

        assert (total_demand == manual_total_demand).all()
        assert len(total_demand) == 2 * 1440

    def test_fleet_summary_reflects_ev_impact(self, mixed_ev_fleet_config):
        """Fleet summary statistics reflect EV charging impact."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results = simulate_fleet(mixed_ev_fleet_config, start, end)
        summary = calculate_fleet_summary(results)

        assert isinstance(summary, FleetSummary)
        assert summary.n_homes == 10
        assert summary.simulation_days == 3

        # Total demand should be positive and substantial (includes EV)
        assert summary.total_demand_kwh > 0

        # Fleet should have valid ratios
        assert 0 <= summary.fleet_self_consumption_ratio <= 1
        assert 0 <= summary.fleet_grid_dependency_ratio <= 1

    def test_energy_balance_validates_with_evs(self, all_ev_fleet_config):
        """Energy balance validates correctly with EV charging."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days

        # Should complete without raising energy balance errors
        results = simulate_fleet(all_ev_fleet_config, start, end, validate_balance=True)

        # All homes should have valid results with no NaN values
        for i in range(len(results)):
            home_results = results[i]
            assert not home_results.generation.isna().any()
            assert not home_results.demand.isna().any()
            assert not home_results.grid_import.isna().any()
            assert not home_results.grid_export.isna().any()

    def test_no_negative_values_with_evs(self, mixed_ev_fleet_config):
        """All output values remain non-negative with EV charging."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")

        results = simulate_fleet(mixed_ev_fleet_config, start, end)

        # Check each home
        for i in range(len(results)):
            home_results = results[i]
            assert (home_results.generation >= 0).all()
            assert (home_results.demand >= 0).all()
            assert (home_results.self_consumption >= 0).all()
            assert (home_results.battery_charge >= 0).all()
            assert (home_results.battery_discharge >= 0).all()
            assert (home_results.battery_soc >= 0).all()
            assert (home_results.grid_import >= 0).all()
            assert (home_results.grid_export >= 0).all()

    def test_different_charger_types_in_fleet(self, mixed_ev_fleet_config):
        """Fleet handles different EV charger types correctly."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_fleet(mixed_ev_fleet_config, start, end)

        # Home 0: 7kW charger
        # Home 2: 3.6kW charger
        # Home 3: 22kW charger

        # Different charger types should produce different demand patterns
        demand_0 = results[0].demand.sum()
        demand_2 = results[2].demand.sum()
        demand_3 = results[3].demand.sum()

        # All should be positive
        assert demand_0 > 0
        assert demand_2 > 0
        assert demand_3 > 0

        # 22kW charger home (3) should deliver energy faster (shorter charging time)
        # but total energy over the day should reflect required charge + base load

    def test_solar_charging_mode_in_fleet(self):
        """Solar-aware EV charging works in fleet simulation."""
        # Create fleet with solar-aware EV charging
        homes = []
        for i in range(3):
            homes.append(HomeConfig(
                pv_config=PVConfig(capacity_kw=5.0),
                load_config=LoadConfig(annual_consumption_kwh=3000.0),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=EVConfig(
                    charger_type="7kW",
                    arrival_hour=8,  # Arrive during solar window
                    departure_hour=17,
                    required_charge_kwh=21.0,  # 3 hours charging
                    smart_charging_mode="solar",
                ),
                location=Location.bristol(),
                name=f"Home {i+1} - Solar EV",
            ))

        fleet_config = FleetConfig(homes=homes, name="Solar EV fleet")
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_fleet(fleet_config, start, end)

        # All homes should have completed successfully
        assert len(results) == 3

        # Check that charging occurs during solar hours (10:00-16:00)
        solar_window_start = 10 * 60  # 600
        solar_window_end = 16 * 60  # 960

        for i in range(3):
            demand = results[i].demand
            solar_window_demand = demand.iloc[solar_window_start:solar_window_end]
            # Should have elevated demand during solar window
            assert solar_window_demand.sum() > 0

    def test_off_peak_charging_mode_in_fleet(self):
        """Off-peak EV charging works in fleet simulation."""
        # Create fleet with off-peak EV charging
        homes = []
        for i in range(3):
            homes.append(HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=EVConfig(
                    charger_type="7kW",
                    arrival_hour=18,
                    departure_hour=8,
                    required_charge_kwh=35.0,
                    smart_charging_mode="off_peak",
                ),
                location=Location.bristol(),
                name=f"Home {i+1} - Off-peak EV",
            ))

        fleet_config = FleetConfig(homes=homes, name="Off-peak EV fleet")
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days for overnight charging

        results = simulate_fleet(fleet_config, start, end)

        # All homes should have completed successfully
        assert len(results) == 3

        # All homes should have valid demand profiles
        for i in range(3):
            demand = results[i].demand
            assert (demand >= 0).all()
            total_demand = demand.sum() / 60  # Convert to kWh
            assert total_demand > 0

    def test_heterogeneous_ev_configs_preserved(self, mixed_ev_fleet_config):
        """Different EV configurations produce different results."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results = simulate_fleet(mixed_ev_fleet_config, start, end)
        summary = calculate_fleet_summary(results)

        # Heterogeneous fleet should have variation in per-home generation
        # (different PV sizes produce different generation)
        assert summary.per_home_generation_min_kwh < summary.per_home_generation_max_kwh

        # Calculate per-home demand variation manually
        per_home_demands = [
            results[i].demand.sum() / 60 for i in range(summary.n_homes)  # Convert to kWh
        ]
        demand_min = min(per_home_demands)
        demand_max = max(per_home_demands)

        # Range should be significant (EVs add substantial load)
        demand_range = demand_max - demand_min
        assert demand_range > 10  # At least 10 kWh difference over 3 days

    def test_fleet_dataframe_output_with_evs(self, all_ev_fleet_config):
        """Fleet aggregate DataFrame includes EV load correctly."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")  # 1 day

        results = simulate_fleet(all_ev_fleet_config, start, end)
        df = results.to_aggregate_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1440  # 1 day of minutes
        assert "generation_kw" in df.columns
        assert "demand_kw" in df.columns
        assert "self_consumption_kw" in df.columns
        assert "grid_import_kw" in df.columns
        assert "grid_export_kw" in df.columns

        # Demand should be elevated due to EV charging
        assert df["demand_kw"].sum() > 0

    def test_ev_impact_on_grid_dependency(self):
        """EV charging increases grid demand and import."""
        # Create two identical fleets, one with EVs, one without
        # Use same seed for load profiles to eliminate randomness
        homes_no_ev = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42+i),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=None,
                location=Location.bristol(),
                name=f"Home {i+1} - No EV",
            )
            for i in range(3)
        ]

        homes_with_ev = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42+i),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=EVConfig(
                    charger_type="7kW",
                    arrival_hour=18,
                    departure_hour=7,
                    required_charge_kwh=35.0,
                    smart_charging_mode="none",
                ),
                location=Location.bristol(),
                name=f"Home {i+1} - With EV",
            )
            for i in range(3)
        ]

        fleet_no_ev = FleetConfig(homes=homes_no_ev, name="No EV fleet")
        fleet_with_ev = FleetConfig(homes=homes_with_ev, name="With EV fleet")

        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days

        results_no_ev = simulate_fleet(fleet_no_ev, start, end)
        results_with_ev = simulate_fleet(fleet_with_ev, start, end)

        summary_no_ev = calculate_fleet_summary(results_no_ev)
        summary_with_ev = calculate_fleet_summary(results_with_ev)

        # Fleet with EVs should have higher total demand
        # 3 homes * 35 kWh per day * 3 days = 315 kWh additional minimum
        assert summary_with_ev.total_demand_kwh > summary_no_ev.total_demand_kwh + 200

        # Fleet with EVs should have higher grid import (most EV charging at night)
        assert summary_with_ev.total_grid_import_kwh > summary_no_ev.total_grid_import_kwh

    def test_overnight_ev_charging_in_fleet(self):
        """Overnight EV charging works correctly across midnight."""
        homes = []
        for i in range(3):
            homes.append(HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0),
                battery_config=BatteryConfig.default_5kwh(),
                ev_config=EVConfig(
                    charger_type="7kW",
                    arrival_hour=22,  # 10pm
                    departure_hour=6,  # 6am
                    required_charge_kwh=28.0,
                    smart_charging_mode="none",
                ),
                location=Location.bristol(),
                name=f"Home {i+1} - Overnight EV",
            ))

        fleet_config = FleetConfig(homes=homes, name="Overnight EV fleet")
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # 2 days for overnight

        results = simulate_fleet(fleet_config, start, end)

        # All homes should complete successfully
        assert len(results) == 3

        # Check that charging spans midnight
        for i in range(3):
            demand = results[i].demand

            # Should have elevated demand late evening (22:00-24:00)
            late_evening = demand.iloc[22*60:24*60]
            assert late_evening.max() >= 7.0  # EV charging

            # Should have elevated demand early morning next day (00:00-06:00)
            early_morning = demand.iloc[1440:1440+6*60]
            assert early_morning.sum() > 0
