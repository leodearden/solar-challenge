"""Integration tests for dispatch strategy simulation.

These tests run full simulations with different dispatch strategies
and verify that strategy selection produces measurably different results.
"""

import pytest
import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    calculate_summary,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


def _make_config(
    strategy_config: DispatchStrategyConfig | None = None,
    name: str = "test home",
) -> HomeConfig:
    """Create a home config with the given dispatch strategy."""
    battery = BatteryConfig(
        capacity_kwh=5.0,
        max_charge_kw=2.5,
        max_discharge_kw=2.5,
        dispatch_strategy=strategy_config,
    )
    return HomeConfig(
        pv_config=PVConfig.default_4kw(),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
        battery_config=battery,
        location=Location.bristol(),
        name=name,
    )


# Short simulation period to keep tests fast
START = pd.Timestamp("2024-06-21")
END = pd.Timestamp("2024-06-23")  # 3 days


@pytest.mark.slow
@pytest.mark.integration
class TestSelfConsumptionStrategy:
    """Integration tests for self-consumption dispatch strategy."""

    @pytest.fixture
    def config(self) -> HomeConfig:
        return _make_config(
            DispatchStrategyConfig(strategy_type="self_consumption"),
            name="Self-consumption home",
        )

    def test_simulation_completes(self, config):
        """Self-consumption strategy simulation runs to completion."""
        results = simulate_home(config, START, END)
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440

    def test_energy_balance(self, config):
        """Energy balance validates with self-consumption strategy."""
        results = simulate_home(config, START, END, validate_balance=True)
        assert results is not None

    def test_battery_active(self, config):
        """Battery charges and discharges with self-consumption strategy."""
        results = simulate_home(config, START, END)
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

    def test_no_negative_values(self, config):
        """All output values are non-negative."""
        results = simulate_home(config, START, END)
        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.self_consumption >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()


@pytest.mark.slow
@pytest.mark.integration
class TestTOUOptimizedStrategy:
    """Integration tests for TOU-optimized dispatch strategy."""

    @pytest.fixture
    def config(self) -> HomeConfig:
        return _make_config(
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 20)],
            ),
            name="TOU-optimized home",
        )

    def test_simulation_completes(self, config):
        """TOU strategy simulation runs to completion."""
        results = simulate_home(config, START, END)
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440

    def test_energy_balance(self, config):
        """Energy balance validates with TOU strategy."""
        results = simulate_home(config, START, END, validate_balance=True)
        assert results is not None

    def test_battery_active(self, config):
        """Battery charges and discharges with TOU strategy."""
        results = simulate_home(config, START, END)
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

    def test_no_negative_values(self, config):
        """All output values are non-negative."""
        results = simulate_home(config, START, END)
        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()


@pytest.mark.slow
@pytest.mark.integration
class TestPeakShavingStrategy:
    """Integration tests for peak-shaving dispatch strategy."""

    @pytest.fixture
    def config(self) -> HomeConfig:
        return _make_config(
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=0.1,
            ),
            name="Peak-shaving home",
        )

    def test_simulation_completes(self, config):
        """Peak-shaving strategy simulation runs to completion."""
        results = simulate_home(config, START, END)
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440

    def test_energy_balance(self, config):
        """Energy balance validates with peak-shaving strategy."""
        results = simulate_home(config, START, END, validate_balance=True)
        assert results is not None

    def test_battery_active(self, config):
        """Battery charges and discharges with peak-shaving strategy."""
        results = simulate_home(config, START, END)
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

    def test_no_negative_values(self, config):
        """All output values are non-negative."""
        results = simulate_home(config, START, END)
        assert (results.generation >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()


@pytest.mark.slow
@pytest.mark.integration
class TestStrategyComparison:
    """Compare results across different dispatch strategies."""

    @pytest.fixture
    def self_consumption_results(self) -> SimulationResults:
        config = _make_config(
            DispatchStrategyConfig(strategy_type="self_consumption"),
        )
        return simulate_home(config, START, END)

    @pytest.fixture
    def tou_results(self) -> SimulationResults:
        config = _make_config(
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 20)],
            ),
        )
        return simulate_home(config, START, END)

    @pytest.fixture
    def peak_shaving_results(self) -> SimulationResults:
        config = _make_config(
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=0.1,
            ),
        )
        return simulate_home(config, START, END)

    def test_generation_identical_across_strategies(
        self,
        self_consumption_results,
        tou_results,
        peak_shaving_results,
    ):
        """PV generation is independent of dispatch strategy."""
        pd.testing.assert_series_equal(
            self_consumption_results.generation,
            tou_results.generation,
        )
        pd.testing.assert_series_equal(
            self_consumption_results.generation,
            peak_shaving_results.generation,
        )

    def test_demand_identical_across_strategies(
        self,
        self_consumption_results,
        tou_results,
        peak_shaving_results,
    ):
        """Load demand is independent of dispatch strategy."""
        pd.testing.assert_series_equal(
            self_consumption_results.demand,
            tou_results.demand,
        )
        pd.testing.assert_series_equal(
            self_consumption_results.demand,
            peak_shaving_results.demand,
        )

    def test_strategies_produce_different_battery_profiles(
        self,
        self_consumption_results,
        tou_results,
        peak_shaving_results,
    ):
        """Different strategies produce different battery charge/discharge profiles."""
        # At least one pair should differ in charge profile
        sc_charge = self_consumption_results.battery_charge
        tou_charge = tou_results.battery_charge
        ps_charge = peak_shaving_results.battery_charge

        # Not all strategies can produce identical profiles
        profiles_differ = (
            not sc_charge.equals(tou_charge)
            or not sc_charge.equals(ps_charge)
            or not tou_charge.equals(ps_charge)
        )
        assert profiles_differ, "At least two strategies should produce different profiles"

    def test_strategies_produce_different_grid_flows(
        self,
        self_consumption_results,
        tou_results,
        peak_shaving_results,
    ):
        """Different strategies produce different grid import/export patterns."""
        sc_import = self_consumption_results.grid_import.sum()
        tou_import = tou_results.grid_import.sum()
        ps_import = peak_shaving_results.grid_import.sum()

        imports_differ = (
            abs(sc_import - tou_import) > 0.001
            or abs(sc_import - ps_import) > 0.001
            or abs(tou_import - ps_import) > 0.001
        )
        assert imports_differ, "At least two strategies should produce different grid imports"

    def test_peak_shaving_discharges_battery(
        self,
        peak_shaving_results,
    ):
        """Peak-shaving strategy actively discharges battery to limit imports."""
        assert peak_shaving_results.battery_discharge.sum() > 0

    def test_summary_statistics_valid_all_strategies(
        self,
        self_consumption_results,
        tou_results,
        peak_shaving_results,
    ):
        """Summary statistics are valid for all strategies."""
        for results in [
            self_consumption_results,
            tou_results,
            peak_shaving_results,
        ]:
            summary = calculate_summary(results)
            assert summary.simulation_days == 3
            assert summary.total_generation_kwh > 0
            assert summary.total_demand_kwh > 0
            assert 0 <= summary.self_consumption_ratio <= 1
            assert 0 <= summary.grid_dependency_ratio <= 1
            assert 0 <= summary.export_ratio <= 1


@pytest.mark.slow
@pytest.mark.integration
class TestDefaultStrategyBackwardCompatibility:
    """Verify that no strategy config gives same results as explicit self-consumption."""

    def test_no_strategy_matches_self_consumption(self):
        """Home with no dispatch strategy behaves like self-consumption."""
        no_strategy_config = HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            location=Location.bristol(),
            name="No strategy",
        )
        explicit_sc_config = _make_config(
            DispatchStrategyConfig(strategy_type="self_consumption"),
        )

        no_strategy = simulate_home(no_strategy_config, START, END)
        explicit_sc = simulate_home(explicit_sc_config, START, END)

        pd.testing.assert_series_equal(
            no_strategy.battery_charge,
            explicit_sc.battery_charge,
        )
        pd.testing.assert_series_equal(
            no_strategy.grid_import,
            explicit_sc.grid_import,
        )
