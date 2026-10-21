"""TOU-optimized battery dispatch of an Economy 7 home, simulated over clear June days.

Every simulation is given clear June days as Bristol's weather, so these tests run offline.
The home has no seg_tariff, so simulate_home's warning that export revenue is 0.0 is ignored.
tests/integration/test_tou_dispatch_synthetic_weather.py compares TOU-optimized with greedy dispatch.
"""

import pytest
import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import (
    HomeConfig,
    SimulationResults,
    calculate_summary,
    simulate_home,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import weather_for

_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=7)


@pytest.mark.filterwarnings("ignore:tariff_config is set but seg_tariff is None:UserWarning")
class TestTOUOptimizedDispatch:
    """An Economy 7 home with a 5 kWh battery under TOU-optimized dispatch, over clear June days."""

    @pytest.fixture
    def tou_home(self) -> HomeConfig:
        """4 kW PV with a 5 kWh battery on Economy 7, dispatched TOU-optimized."""
        return HomeConfig(
            pv_config=PVConfig.default_4kw(),
            load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
            battery_config=BatteryConfig.default_5kwh(),
            location=Location.bristol(),
            tariff_config=TariffConfig.economy_7(),
            name="TOU-optimized home",
            dispatch_strategy="tou_optimized",
        )

    def test_tou_dispatch_completes(self, tou_home):
        """TOU-optimized dispatch strategy completes successfully."""
        start, end = _JUNE_DAYS.window(3)

        results = simulate_home(tou_home, start, end, weather=weather_for(tou_home, _JUNE_DAYS.hourly_weather()))

        # All result fields populated
        assert isinstance(results, SimulationResults)
        assert len(results.generation) == 3 * 1440
        assert len(results.demand) == 3 * 1440

        # Battery should be active
        assert results.battery_charge.sum() > 0
        assert results.battery_discharge.sum() > 0

        # Financial fields should be calculated
        assert results.import_cost.sum() > 0
        assert results.tariff_rate.sum() > 0

    def test_tou_dispatch_balances_energy_with_no_negative_values(self, tou_home):
        """Energy balances every minute, and no output is negative, with TOU dispatch."""
        start, end = _JUNE_DAYS.window(2)

        results = simulate_home(
            tou_home, start, end, validate_balance=True, weather=weather_for(tou_home, _JUNE_DAYS.hourly_weather())
        )

        assert (results.generation >= 0).all()
        assert (results.demand >= 0).all()
        assert (results.self_consumption >= 0).all()
        assert (results.battery_charge >= 0).all()
        assert (results.battery_discharge >= 0).all()
        assert (results.battery_soc >= 0).all()
        assert (results.grid_import >= 0).all()
        assert (results.grid_export >= 0).all()
        assert (results.import_cost >= 0).all()
        assert (results.export_revenue >= 0).all()

    def test_summary_statistics_with_tou(self, tou_home):
        """Summary statistics should be reasonable with TOU dispatch."""
        start, end = _JUNE_DAYS.window(7)

        results = simulate_home(tou_home, start, end, weather=weather_for(tou_home, _JUNE_DAYS.hourly_weather()))
        summary = calculate_summary(results)

        # 7 days of simulation
        assert summary.simulation_days == 7

        # 4 kW system in June should generate ~12-20 kWh/day in UK
        assert 50 < summary.total_generation_kwh < 200  # 7-30 kWh/day range

        # 3,400 kWh/year ≈ 9.3 kWh/day
        assert 40 < summary.total_demand_kwh < 100  # 6-14 kWh/day range

        # Financial values should be reasonable
        assert summary.total_import_cost_gbp >= 0
        assert summary.total_export_revenue_gbp >= 0
        # Net cost can be negative (profit) in summer with high solar generation

        # Ratios should be valid
        assert 0 <= summary.self_consumption_ratio <= 1
        assert 0 <= summary.grid_dependency_ratio <= 1
        assert 0 <= summary.export_ratio <= 1
