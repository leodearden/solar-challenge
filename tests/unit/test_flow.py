"""Tests for energy flow calculations."""

from datetime import datetime
from typing import Optional

import pytest
import pandas as pd
import numpy as np
from solar_challenge.flow import (
    calculate_self_consumption,
    calculate_excess_pv,
    calculate_shortfall,
    simulate_timestep,
    simulate_timestep_tou,
    validate_energy_balance,
    EnergyFlowResult,
)
from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.tariff import TariffConfig
from solar_challenge.config import GridChargeConfig
from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
)


@pytest.fixture
def sample_index():
    """Create a sample datetime index."""
    return pd.date_range("2024-01-01", periods=5, freq="h")


@pytest.fixture
def sample_generation(sample_index):
    """Sample generation series: [0, 1, 3, 2, 0] kW."""
    return pd.Series([0.0, 1.0, 3.0, 2.0, 0.0], index=sample_index, name="gen")


@pytest.fixture
def sample_demand(sample_index):
    """Sample demand series: [0.5, 0.5, 1.0, 2.5, 1.0] kW."""
    return pd.Series([0.5, 0.5, 1.0, 2.5, 1.0], index=sample_index, name="demand")


class TestSelfConsumption:
    """Test self-consumption calculation."""

    def test_self_consumption_is_min(self, sample_generation, sample_demand):
        """Self-consumption is min(generation, demand)."""
        result = calculate_self_consumption(sample_generation, sample_demand)
        expected = pd.Series([0.0, 0.5, 1.0, 2.0, 0.0], index=sample_generation.index)
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_self_consumption_same_length(self, sample_generation, sample_demand):
        """Result has same length as inputs."""
        result = calculate_self_consumption(sample_generation, sample_demand)
        assert len(result) == len(sample_generation)

    def test_self_consumption_non_negative(self, sample_generation, sample_demand):
        """All values are non-negative."""
        result = calculate_self_consumption(sample_generation, sample_demand)
        assert (result >= 0).all()

    def test_mismatched_lengths_raises(self, sample_generation):
        """Different length series raises error."""
        short_demand = pd.Series([1.0, 2.0])
        with pytest.raises(ValueError, match="same length"):
            calculate_self_consumption(sample_generation, short_demand)

    def test_negative_generation_raises(self, sample_index, sample_demand):
        """Negative generation values raise error."""
        bad_gen = pd.Series([-1.0, 1.0, 1.0, 1.0, 1.0], index=sample_index)
        with pytest.raises(ValueError, match="negative"):
            calculate_self_consumption(bad_gen, sample_demand)

    def test_negative_demand_raises(self, sample_index, sample_generation):
        """Negative demand values raise error."""
        bad_demand = pd.Series([1.0, -1.0, 1.0, 1.0, 1.0], index=sample_index)
        with pytest.raises(ValueError, match="negative"):
            calculate_self_consumption(sample_generation, bad_demand)


class TestExcessPV:
    """Test excess PV calculation."""

    def test_excess_when_generation_higher(self, sample_generation, sample_demand):
        """Excess = generation - demand when positive."""
        result = calculate_excess_pv(sample_generation, sample_demand)
        # [0-0.5, 1-0.5, 3-1, 2-2.5, 0-1] = [-0.5, 0.5, 2, -0.5, -1] -> [0, 0.5, 2, 0, 0]
        expected = pd.Series([0.0, 0.5, 2.0, 0.0, 0.0], index=sample_generation.index)
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_excess_same_length(self, sample_generation, sample_demand):
        """Result has same length as inputs."""
        result = calculate_excess_pv(sample_generation, sample_demand)
        assert len(result) == len(sample_generation)

    def test_excess_non_negative(self, sample_generation, sample_demand):
        """All values are non-negative."""
        result = calculate_excess_pv(sample_generation, sample_demand)
        assert (result >= 0).all()


class TestShortfall:
    """Test shortfall calculation."""

    def test_shortfall_when_demand_higher(self, sample_generation, sample_demand):
        """Shortfall = demand - generation when positive."""
        result = calculate_shortfall(sample_generation, sample_demand)
        # [0.5-0, 0.5-1, 1-3, 2.5-2, 1-0] = [0.5, -0.5, -2, 0.5, 1] -> [0.5, 0, 0, 0.5, 1]
        expected = pd.Series([0.5, 0.0, 0.0, 0.5, 1.0], index=sample_generation.index)
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_shortfall_same_length(self, sample_generation, sample_demand):
        """Result has same length as inputs."""
        result = calculate_shortfall(sample_generation, sample_demand)
        assert len(result) == len(sample_generation)

    def test_shortfall_non_negative(self, sample_generation, sample_demand):
        """All values are non-negative."""
        result = calculate_shortfall(sample_generation, sample_demand)
        assert (result >= 0).all()


class TestEnergyBalance:
    """Test that flow calculations maintain energy balance."""

    def test_self_consumption_plus_excess_equals_generation(
        self, sample_generation, sample_demand
    ):
        """Self-consumption + excess = generation."""
        self_consumption = calculate_self_consumption(sample_generation, sample_demand)
        excess = calculate_excess_pv(sample_generation, sample_demand)
        total = self_consumption + excess
        pd.testing.assert_series_equal(
            total, sample_generation, check_names=False, atol=1e-10
        )

    def test_self_consumption_plus_shortfall_equals_demand(
        self, sample_generation, sample_demand
    ):
        """Self-consumption + shortfall = demand."""
        self_consumption = calculate_self_consumption(sample_generation, sample_demand)
        shortfall = calculate_shortfall(sample_generation, sample_demand)
        total = self_consumption + shortfall
        pd.testing.assert_series_equal(
            total, sample_demand, check_names=False, atol=1e-10
        )


@pytest.fixture
def default_battery():
    """Create a default battery for testing."""
    config = BatteryConfig.default_5kwh()
    return Battery(config)


class TestSimulateTimestep:
    """Test single timestep simulation."""

    def test_no_battery_excess_exports(self):
        """Without battery, excess PV exports to grid."""
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=None,
            timestep_minutes=60,
        )
        # 3 kW - 1 kW = 2 kW excess for 1 hour = 2 kWh export
        assert result.generation == 3.0
        assert result.demand == 1.0
        assert result.self_consumption == 1.0
        assert result.grid_export == 2.0
        assert result.grid_import == 0.0
        assert result.battery_charge == 0.0
        assert result.battery_discharge == 0.0

    def test_no_battery_shortfall_imports(self):
        """Without battery, shortfall imports from grid."""
        result = simulate_timestep(
            generation_kw=1.0,
            demand_kw=3.0,
            battery=None,
            timestep_minutes=60,
        )
        # 3 kW - 1 kW = 2 kW shortfall for 1 hour = 2 kWh import
        assert result.generation == 1.0
        assert result.demand == 3.0
        assert result.self_consumption == 1.0
        assert result.grid_export == 0.0
        assert result.grid_import == 2.0

    def test_with_battery_excess_charges(self, default_battery):
        """With battery, excess PV charges battery first."""
        initial_soc = default_battery.soc_kwh
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # 2 kWh excess, battery can absorb it
        assert result.battery_charge > 0
        assert default_battery.soc_kwh > initial_soc
        # Export should be reduced
        assert result.grid_export < 2.0

    def test_with_battery_shortfall_discharges(self, default_battery):
        """With battery, shortfall discharges battery first."""
        initial_soc = default_battery.soc_kwh
        result = simulate_timestep(
            generation_kw=1.0,
            demand_kw=3.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # 2 kWh shortfall, battery can provide it
        assert result.battery_discharge > 0
        assert default_battery.soc_kwh < initial_soc
        # Import should be reduced
        assert result.grid_import < 2.0


class TestBatteryChargeFromExcess:
    """Test battery charging from excess (FLOW-003)."""

    def test_excess_directed_to_battery(self, default_battery):
        """Excess PV is directed to battery first."""
        result = simulate_timestep(
            generation_kw=2.0,
            demand_kw=0.5,
            battery=default_battery,
            timestep_minutes=60,
        )
        # 1.5 kWh excess
        assert result.battery_charge > 0

    def test_respects_battery_charge_rate(self):
        """Charging respects battery max rate."""
        config = BatteryConfig(capacity_kwh=10.0, max_charge_kw=1.0)
        battery = Battery(config, initial_soc_kwh=1.0)

        result = simulate_timestep(
            generation_kw=5.0,  # Way more than 1 kW charge rate
            demand_kw=0.0,
            battery=battery,
            timestep_minutes=60,
        )
        # Charge limited to ~1 kW * 1 hour * efficiency
        assert result.battery_charge <= 1.0 * 0.975 + 0.01


class TestGridExport:
    """Test remaining excess for grid export (FLOW-004)."""

    def test_export_equals_excess_minus_charged(self, default_battery):
        """Export = excess - battery_charged."""
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # Compute excess directly from generation and demand
        excess = max(0, result.generation - result.demand)
        assert result.grid_export == pytest.approx(
            excess - result.battery_charge, rel=0.01
        )

    def test_export_when_battery_full(self):
        """Export when battery is full."""
        config = BatteryConfig.default_5kwh()
        battery = Battery(config, initial_soc_kwh=4.5)  # At max SOC

        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=battery,
            timestep_minutes=60,
        )
        # Battery can't charge more, so all excess exports
        assert result.battery_charge == 0.0
        assert result.grid_export == 2.0


class TestBatteryDischargeToMeetShortfall:
    """Test battery discharge to meet shortfall (FLOW-006)."""

    def test_shortfall_draws_from_battery(self, default_battery):
        """Shortfall draws from battery first."""
        result = simulate_timestep(
            generation_kw=0.5,
            demand_kw=2.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # 1.5 kWh shortfall
        assert result.battery_discharge > 0

    def test_respects_battery_discharge_rate(self):
        """Discharging respects battery max rate."""
        config = BatteryConfig(capacity_kwh=10.0, max_discharge_kw=1.0)
        battery = Battery(config, initial_soc_kwh=5.0)

        result = simulate_timestep(
            generation_kw=0.0,
            demand_kw=5.0,  # Way more than 1 kW discharge rate
            battery=battery,
            timestep_minutes=60,
        )
        # Discharge limited to ~1 kW * 1 hour
        assert result.battery_discharge <= 1.0 + 0.01


class TestGridImport:
    """Test grid import for remaining shortfall (FLOW-007)."""

    def test_import_equals_shortfall_minus_discharged(self, default_battery):
        """Import = shortfall - battery_discharged."""
        result = simulate_timestep(
            generation_kw=1.0,
            demand_kw=3.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # Compute shortfall directly from generation and demand
        shortfall = max(0, result.demand - result.generation)
        assert result.grid_import == pytest.approx(
            shortfall - result.battery_discharge, rel=0.01
        )

    def test_import_when_battery_empty(self):
        """Import when battery is empty."""
        config = BatteryConfig.default_5kwh()
        battery = Battery(config, initial_soc_kwh=0.5)  # At min SOC

        result = simulate_timestep(
            generation_kw=1.0,
            demand_kw=3.0,
            battery=battery,
            timestep_minutes=60,
        )
        # Battery can't discharge more, so all shortfall imports
        assert result.battery_discharge == 0.0
        assert result.grid_import == 2.0


class TestSelfConsumptionWithBattery:
    """Test self-consumption includes battery discharge."""

    def test_self_consumption_includes_battery_discharge(self, default_battery):
        """Self-consumption includes battery discharge (stored PV used later)."""
        result = simulate_timestep(
            generation_kw=1.0,
            demand_kw=3.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # Direct consumption is min(gen, demand) = 1.0 kWh
        # Battery discharge should be added to self-consumption
        direct_consumption = min(result.generation, result.demand)
        assert result.self_consumption == pytest.approx(
            direct_consumption + result.battery_discharge, rel=0.01
        )

    def test_self_consumption_capped_at_demand(self):
        """Self-consumption cannot exceed demand."""
        config = BatteryConfig(capacity_kwh=10.0, max_discharge_kw=5.0)
        battery = Battery(config, initial_soc_kwh=5.0)

        result = simulate_timestep(
            generation_kw=2.0,
            demand_kw=3.0,
            battery=battery,
            timestep_minutes=60,
        )
        # Self-consumption should never exceed demand
        assert result.self_consumption <= result.demand

    def test_self_consumption_without_battery(self):
        """Without battery, self-consumption equals min(gen, demand)."""
        result = simulate_timestep(
            generation_kw=2.0,
            demand_kw=3.0,
            battery=None,
            timestep_minutes=60,
        )
        expected = min(result.generation, result.demand)
        assert result.self_consumption == pytest.approx(expected, rel=0.01)

    def test_self_consumption_zero_generation(self, default_battery):
        """With zero generation, self-consumption equals battery discharge."""
        result = simulate_timestep(
            generation_kw=0.0,
            demand_kw=2.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        # Direct consumption = 0, so self-consumption = battery_discharge
        assert result.self_consumption == pytest.approx(
            result.battery_discharge, rel=0.01
        )

    def test_self_consumption_zero_demand(self, default_battery):
        """With zero demand, self-consumption is zero."""
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=0.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        assert result.self_consumption == 0.0


class TestEnergyBalanceValidation:
    """Test energy balance validation (FLOW-008)."""

    def test_valid_balance_passes(self):
        """Valid energy balance passes validation."""
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=None,
            timestep_minutes=60,
        )
        assert validate_energy_balance(result)

    def test_valid_balance_with_battery(self, default_battery):
        """Valid energy balance with battery passes."""
        result = simulate_timestep(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=default_battery,
            timestep_minutes=60,
        )
        assert validate_energy_balance(result)

    def test_configurable_tolerance(self):
        """Tolerance is configurable."""
        result = EnergyFlowResult(
            generation=1.0,
            demand=1.0,
            self_consumption=1.0,
            battery_charge=0.0,
            battery_discharge=0.0,
            grid_export=0.0001,  # Tiny imbalance
            grid_import=0.0,
            battery_soc=0.0,
        )
        # Should pass with default tolerance
        assert validate_energy_balance(result, tolerance=0.001)

        # Should fail with very tight tolerance
        with pytest.raises(ValueError, match="balance violated"):
            validate_energy_balance(result, tolerance=0.00001)


# ---------------------------------------------------------------------------
# Shared scaffolding for grid-charge tests (pre-1)
# ---------------------------------------------------------------------------

@pytest.fixture
def economy7_tariff() -> TariffConfig:
    """Economy 7 tariff (off-peak 0.09 @ 00:30-07:30, peak 0.25)."""
    return TariffConfig.economy_7()


@pytest.fixture
def off_peak_ts() -> pd.Timestamp:
    """A timestamp in the off-peak period (03:00)."""
    return pd.Timestamp("2024-01-01 03:00")


@pytest.fixture
def peak_ts() -> pd.Timestamp:
    """A timestamp in the peak period (18:00)."""
    return pd.Timestamp("2024-01-01 18:00")


@pytest.fixture
def grid_charge_battery() -> Battery:
    """Battery with grid charging enabled; initial SOC below target so gap > 0."""
    config = BatteryConfig(
        capacity_kwh=5.0,
        max_charge_kw=2.5,
        max_discharge_kw=2.5,
        grid_charging=GridChargeConfig(target_soc_fraction=0.9),
    )
    # target_kwh = 0.9 * 5 = 4.5; initial = 2.0 → gap = 2.5 kWh
    return Battery(config, initial_soc_kwh=2.0)


class _RecordingStrategy(DispatchStrategy):
    """Test double: records the grid_charge_ctx passed in and returns a fixed decision."""

    def __init__(
        self,
        charge_kw: float = 0.0,
        discharge_kw: float = 0.0,
        grid_charge_kw: float = 0.0,
    ) -> None:
        self._decision = DispatchDecision(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            grid_charge_kw=grid_charge_kw,
        )
        self.received_ctx: Optional[GridChargeContext] = None

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "recording"

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float = 1.0,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Record grid_charge_ctx and return the pre-configured decision."""
        self.received_ctx = grid_charge_ctx
        return self._decision


# ---------------------------------------------------------------------------
# step-1: RED tests for simulate_timestep_tou grid-charge split accounting
# ---------------------------------------------------------------------------

class TestSimulateTimestepTouGridCharge:
    """Function-path grid-charge tests using real Economy 7 + GridChargeConfig.

    Tests (a) and (b) fail on current code (which ignores grid_charging).
    Tests (c)-(e) are forward-/backward-compat guards.
    """

    def test_grid_only_charge_step(
        self, economy7_tariff: TariffConfig, off_peak_ts: pd.Timestamp, grid_charge_battery: Battery
    ) -> None:
        """(a) Cheap period, gen=demand=0: battery must charge from grid."""
        result = simulate_timestep_tou(
            generation_kw=0.0,
            demand_kw=0.0,
            battery=grid_charge_battery,
            timestamp=off_peak_ts,
            tariff=economy7_tariff,
            timestep_minutes=60,
        )
        assert result.battery_charge > 0, "Battery should charge from grid during cheap period"
        assert result.grid_export == pytest.approx(0.0)
        # shortfall=0, discharge=0 → grid_import == grid_charge_stored == battery_charge
        assert result.grid_import == pytest.approx(result.battery_charge)
        assert validate_energy_balance(result)

    def test_pv_and_grid_split(
        self, economy7_tariff: TariffConfig, off_peak_ts: pd.Timestamp
    ) -> None:
        """(b) Modest PV excess + grid top-up: split accounting is applied."""
        # Reference run: same conditions but grid_charging disabled
        config_no_gc = BatteryConfig(
            capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5, grid_charging=None
        )
        bat_ref = Battery(config_no_gc, initial_soc_kwh=2.0)
        ref = simulate_timestep_tou(
            generation_kw=1.0, demand_kw=0.5, battery=bat_ref,
            timestamp=off_peak_ts, tariff=economy7_tariff, timestep_minutes=60,
        )
        pv_charge_stored = ref.battery_charge  # ≈ 0.4875 kWh (excess * 0.975)

        # Main run: grid charging enabled
        config_gc = BatteryConfig(
            capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5,
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        )
        bat_gc = Battery(config_gc, initial_soc_kwh=2.0)
        result = simulate_timestep_tou(
            generation_kw=1.0, demand_kw=0.5, battery=bat_gc,
            timestamp=off_peak_ts, tariff=economy7_tariff, timestep_minutes=60,
        )
        # Grid also topped up → total charge > pv-only
        assert result.battery_charge > pv_charge_stored, \
            "With grid charging, battery_charge should exceed pv-only charge"
        # Export: only the PV portion reduces export (split formula)
        excess_kwh = (1.0 - 0.5) * (60 / 60)
        assert result.grid_export == pytest.approx(max(0.0, excess_kwh - pv_charge_stored))
        assert validate_energy_balance(result)

    def test_max_charge_kw_not_exceeded(
        self, economy7_tariff: TariffConfig, off_peak_ts: pd.Timestamp
    ) -> None:
        """(c) Large PV excess (> max_charge_kw): residual=0, grid_charge≈0, rate <= max_kw."""
        config = BatteryConfig(
            capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5,
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        )
        battery = Battery(config, initial_soc_kwh=2.0)
        result = simulate_timestep_tou(
            generation_kw=5.0,   # well above max_charge_kw=2.5
            demand_kw=0.0,
            battery=battery,
            timestamp=off_peak_ts,
            tariff=economy7_tariff,
            timestep_minutes=60,
        )
        duration_hours = 60.0 / 60.0
        # Total stored energy / dt must not exceed the hardware charge-rate limit
        assert result.battery_charge / duration_hours <= 2.5 + 1e-9
        assert validate_energy_balance(result)

    def test_every_timestep_balance(self, economy7_tariff: TariffConfig) -> None:
        """(d) Energy balance holds at every step in a 24-hour off-peak→peak sweep."""
        config = BatteryConfig(
            capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5,
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        )
        battery = Battery(config, initial_soc_kwh=2.0)
        timestamps = pd.date_range("2024-01-01 00:00", periods=24, freq="h")
        gen_kw = [
            0.0, 0.0, 0.0, 0.0, 0.2, 0.5, 1.5, 2.5,
            3.0, 3.5, 4.0, 3.8, 3.0, 2.0, 1.5, 1.0,
            0.5, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        ]
        dem_kw = [
            0.3, 0.3, 0.3, 0.3, 0.4, 0.5, 0.6, 0.7,
            0.8, 1.0, 1.0, 1.0, 0.9, 0.8, 0.7, 0.8,
            1.2, 1.5, 2.0, 1.8, 1.5, 1.0, 0.6, 0.4,
        ]
        for ts, gen, dem in zip(timestamps, gen_kw, dem_kw):
            result = simulate_timestep_tou(
                generation_kw=gen, demand_kw=dem, battery=battery,
                timestamp=ts, tariff=economy7_tariff, timestep_minutes=60,
            )
            assert validate_energy_balance(result), \
                f"Energy balance violated at {ts} (gen={gen}, dem={dem})"

    def test_backward_compat_bit_identical(self, off_peak_ts: pd.Timestamp) -> None:
        """(e) grid_charging=None: exact backward-compatible values are preserved."""
        config = BatteryConfig.default_5kwh()   # no grid_charging field
        battery = Battery(config)               # initial SOC = midpoint = 2.5 kWh
        result = simulate_timestep_tou(
            generation_kw=3.0,
            demand_kw=1.0,
            battery=battery,
            timestamp=off_peak_ts,
            tariff=TariffConfig.economy_7(),
            timestep_minutes=60,
        )
        # excess = 2 kWh; battery.charge(2.0, 60) = 2.0 * 0.975 = 1.95 kWh
        # grid_export = max(0, 2.0 - 1.95) = 0.05 kWh; shortfall=0 → grid_import=0
        assert result.battery_charge == pytest.approx(1.95)
        assert result.grid_export == pytest.approx(0.05)
        assert result.grid_import == pytest.approx(0.0)
        assert result.self_consumption == pytest.approx(1.0)
