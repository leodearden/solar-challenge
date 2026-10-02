# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for SelfConsumptionStrategy, which charges the battery from excess PV and discharges it to cover any shortfall."""

from datetime import datetime

import pytest

from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    SelfConsumptionStrategy,
)


@pytest.fixture
def timestamp():
    """Create a sample timestamp for testing."""
    return datetime(2024, 1, 1, 12, 0, 0)


@pytest.fixture
def self_consumption_strategy():
    """Create a SelfConsumptionStrategy instance."""
    return SelfConsumptionStrategy()


class TestSelfConsumptionStrategyBasics:
    """Test basic SelfConsumptionStrategy functionality."""

    def test_can_instantiate(self, self_consumption_strategy):
        """SelfConsumptionStrategy can be instantiated."""
        assert isinstance(self_consumption_strategy, DispatchStrategy)
        assert isinstance(self_consumption_strategy, SelfConsumptionStrategy)

    def test_returns_dispatch_decision(self, self_consumption_strategy, timestamp):
        """decide_action returns a DispatchDecision."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
        )
        assert isinstance(decision, DispatchDecision)


class TestSelfConsumptionStrategyExcessPV:
    """Test self-consumption strategy with excess PV."""

    def test_excess_pv_charges_battery(self, self_consumption_strategy, timestamp):
        """When generation > demand, battery charges from excess."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 3.0 - 1.0 = 2.0 kW
        assert decision.charge_kw == 2.0
        assert decision.discharge_kw == 0.0

    def test_large_excess_charges(self, self_consumption_strategy, timestamp):
        """Large excess PV requests proportional charge."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=5.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 5.0 - 1.0 = 4.0 kW
        assert decision.charge_kw == 4.0
        assert decision.discharge_kw == 0.0

    def test_small_excess_charges(self, self_consumption_strategy, timestamp):
        """Small excess PV charges appropriately."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.1,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 1.1 - 1.0 = 0.1 kW
        assert decision.charge_kw == pytest.approx(0.1)
        assert decision.discharge_kw == 0.0

    def test_excess_pv_zero_demand(self, self_consumption_strategy, timestamp):
        """Excess with zero demand charges all generation."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=0.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 3.0 - 0.0 = 3.0 kW
        assert decision.charge_kw == 3.0
        assert decision.discharge_kw == 0.0


class TestSelfConsumptionStrategyShortfall:
    """Test self-consumption strategy with demand shortfall."""

    def test_shortfall_discharges_battery(self, self_consumption_strategy, timestamp):
        """When demand > generation, battery discharges to meet shortfall."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall = 3.0 - 1.0 = 2.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 2.0

    def test_large_shortfall_discharges(self, self_consumption_strategy, timestamp):
        """Large shortfall requests proportional discharge."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall = 5.0 - 1.0 = 4.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 4.0

    def test_small_shortfall_discharges(self, self_consumption_strategy, timestamp):
        """Small shortfall discharges appropriately."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=1.1,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall = 1.1 - 1.0 = 0.1 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(0.1)

    def test_shortfall_zero_generation(self, self_consumption_strategy, timestamp):
        """Shortfall with zero generation discharges for all demand."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall = 3.0 - 0.0 = 3.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 3.0


class TestSelfConsumptionStrategyBalanced:
    """Test self-consumption strategy when generation equals demand."""

    def test_balanced_no_action(self, self_consumption_strategy, timestamp):
        """When generation equals demand, no battery action."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_both_zero_no_action(self, self_consumption_strategy, timestamp):
        """When both generation and demand are zero, no action."""
        decision = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=0.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0


class TestSelfConsumptionStrategySOCIndependence:
    """Test that self-consumption strategy doesn't depend on SOC."""

    def test_decision_independent_of_soc_high(
        self, self_consumption_strategy, timestamp
    ):
        """Decision is same regardless of battery SOC (high SOC)."""
        decision_high = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=4.0,  # High SOC
            battery_capacity_kwh=5.0,
        )
        decision_low = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=1.0,  # Low SOC
            battery_capacity_kwh=5.0,
        )
        assert decision_high.charge_kw == decision_low.charge_kw
        assert decision_high.discharge_kw == decision_low.discharge_kw

    def test_decision_independent_of_capacity(
        self, self_consumption_strategy, timestamp
    ):
        """Decision is same regardless of battery capacity."""
        decision_small = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,  # Small battery
        )
        decision_large = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=5.0,
            battery_capacity_kwh=10.0,  # Large battery
        )
        assert decision_small.charge_kw == decision_large.charge_kw
        assert decision_small.discharge_kw == decision_large.discharge_kw


class TestSelfConsumptionStrategyTimestampIndependence:
    """Test that self-consumption strategy doesn't depend on timestamp."""

    def test_decision_independent_of_time(self, self_consumption_strategy):
        """Decision is same regardless of timestamp."""
        morning = datetime(2024, 1, 1, 8, 0, 0)
        afternoon = datetime(2024, 1, 1, 14, 0, 0)
        evening = datetime(2024, 1, 1, 20, 0, 0)

        decision_morning = self_consumption_strategy.decide_action(
            timestamp=morning,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        decision_afternoon = self_consumption_strategy.decide_action(
            timestamp=afternoon,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        decision_evening = self_consumption_strategy.decide_action(
            timestamp=evening,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

        assert decision_morning.charge_kw == decision_afternoon.charge_kw
        assert decision_morning.charge_kw == decision_evening.charge_kw
        assert decision_morning.discharge_kw == decision_afternoon.discharge_kw
        assert decision_morning.discharge_kw == decision_evening.discharge_kw


class TestSelfConsumptionStrategyValidation:
    """Test SelfConsumptionStrategy input validation."""

    def test_negative_generation_raises(self, self_consumption_strategy, timestamp):
        """Negative generation raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=-1.0,
                demand_kw=1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_demand_raises(self, self_consumption_strategy, timestamp):
        """Negative demand raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=-1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_soc_raises(self, self_consumption_strategy, timestamp):
        """Negative battery SOC raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=-1.0,
                battery_capacity_kwh=5.0,
            )

    def test_zero_capacity_raises(self, self_consumption_strategy, timestamp):
        """Zero battery capacity raises error."""
        with pytest.raises(ValueError, match="positive"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=0.0,
                battery_capacity_kwh=0.0,
            )

    def test_negative_capacity_raises(self, self_consumption_strategy, timestamp):
        """Negative battery capacity raises error."""
        with pytest.raises(ValueError, match="positive"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=1.0,
                battery_capacity_kwh=-5.0,
            )

    def test_zero_timestep_raises(self, self_consumption_strategy, timestamp):
        """Zero timestep raises error."""
        with pytest.raises(ValueError, match="positive"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
                timestep_minutes=0.0,
            )

    def test_negative_timestep_raises(self, self_consumption_strategy, timestamp):
        """Negative timestep raises error."""
        with pytest.raises(ValueError, match="positive"):
            self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
                timestep_minutes=-60.0,
            )


class TestSelfConsumptionStrategyTimestepIndependence:
    """Test that timestep duration doesn't affect power decision."""

    def test_decision_independent_of_timestep_duration(
        self, self_consumption_strategy, timestamp
    ):
        """Power decision is same regardless of timestep duration."""
        decision_1min = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            timestep_minutes=1.0,
        )
        decision_60min = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
        )
        # Power (kW) should be same regardless of duration
        assert decision_1min.charge_kw == decision_60min.charge_kw
        assert decision_1min.discharge_kw == decision_60min.discharge_kw


class TestStrategyInterfaceContract:
    """Test that dispatch strategy adheres to interface contract."""

    def test_strategy_has_decide_action_method(self, self_consumption_strategy):
        """Strategy has decide_action method."""
        assert hasattr(self_consumption_strategy, "decide_action")
        assert callable(self_consumption_strategy.decide_action)

    def test_decide_action_returns_dispatch_decision(
        self, self_consumption_strategy, timestamp
    ):
        """decide_action returns DispatchDecision type."""
        result = self_consumption_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert isinstance(result, DispatchDecision)

    def test_decision_never_simultaneous_charge_discharge(
        self, self_consumption_strategy, timestamp
    ):
        """Strategy never returns simultaneous charge and discharge."""
        # Test various scenarios
        test_cases = [
            (3.0, 1.0),  # Excess
            (1.0, 3.0),  # Shortfall
            (2.0, 2.0),  # Balanced
            (0.0, 0.0),  # Both zero
            (5.0, 0.0),  # Max excess
            (0.0, 5.0),  # Max shortfall
        ]
        for gen, dem in test_cases:
            decision = self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=gen,
                demand_kw=dem,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )
            # Either charge_kw or discharge_kw must be zero (or both)
            assert decision.charge_kw == 0.0 or decision.discharge_kw == 0.0

    def test_decision_powers_are_non_negative(
        self, self_consumption_strategy, timestamp
    ):
        """Strategy always returns non-negative powers."""
        # Test various scenarios
        test_cases = [
            (3.0, 1.0),
            (1.0, 3.0),
            (2.0, 2.0),
            (0.1, 0.05),
            (10.0, 0.0),
            (0.0, 10.0),
        ]
        for gen, dem in test_cases:
            decision = self_consumption_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=gen,
                demand_kw=dem,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )
            assert decision.charge_kw >= 0.0
            assert decision.discharge_kw >= 0.0
