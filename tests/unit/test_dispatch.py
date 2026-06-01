"""Tests for battery dispatch strategy framework."""

import pytest
from datetime import datetime
from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
    PeakShavingStrategy,
    TariffPeriod,
    compute_grid_charge_power_kw,
)


class TestDispatchDecisionBasics:
    """Test basic DispatchDecision functionality."""

    def test_create_with_charge(self):
        """DispatchDecision can be created with charge power."""
        decision = DispatchDecision(charge_kw=2.5, discharge_kw=0.0)
        assert decision.charge_kw == 2.5
        assert decision.discharge_kw == 0.0

    def test_create_with_discharge(self):
        """DispatchDecision can be created with discharge power."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=3.0)
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 3.0

    def test_create_with_no_action(self):
        """DispatchDecision can be created with no action."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_decision_is_frozen(self):
        """DispatchDecision is immutable (frozen dataclass)."""
        decision = DispatchDecision(charge_kw=1.0, discharge_kw=0.0)
        with pytest.raises(Exception):  # FrozenInstanceError
            decision.charge_kw = 2.0


class TestDispatchDecisionValidation:
    """Test DispatchDecision validation."""

    def test_negative_charge_raises(self):
        """Negative charge power raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=-1.0, discharge_kw=0.0)

    def test_negative_discharge_raises(self):
        """Negative discharge power raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=0.0, discharge_kw=-1.0)

    def test_simultaneous_charge_discharge_raises(self):
        """Cannot charge and discharge at the same time."""
        with pytest.raises(ValueError, match="simultaneously"):
            DispatchDecision(charge_kw=1.0, discharge_kw=1.0)

    def test_simultaneous_small_values_raises(self):
        """Even small simultaneous charge/discharge raises error."""
        with pytest.raises(ValueError, match="simultaneously"):
            DispatchDecision(charge_kw=0.1, discharge_kw=0.1)


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


# =============================================================================
# TOU OPTIMIZED STRATEGY TESTS
# =============================================================================


@pytest.fixture
def standard_tou_strategy():
    """Create a standard TOU strategy with typical peak hours."""
    # Peak hours: 5 PM to 8 PM (17:00 to 20:00)
    return TOUOptimizedStrategy(peak_hours=[(17, 20)])


@pytest.fixture
def multi_peak_tou_strategy():
    """Create a TOU strategy with multiple peak periods."""
    # Peak hours: 7 AM to 9 AM and 5 PM to 8 PM
    return TOUOptimizedStrategy(peak_hours=[(7, 9), (17, 20)])


@pytest.fixture
def explicit_offpeak_tou_strategy():
    """Create a TOU strategy with explicit off-peak hours."""
    # Peak hours: 5 PM to 8 PM, Off-peak: 9 AM to 4 PM
    return TOUOptimizedStrategy(peak_hours=[(17, 20)], off_peak_hours=[(9, 16)])


class TestTOUOptimizedStrategyBasics:
    """Test basic TOUOptimizedStrategy functionality."""

    def test_can_instantiate(self, standard_tou_strategy):
        """TOUOptimizedStrategy can be instantiated."""
        assert isinstance(standard_tou_strategy, DispatchStrategy)
        assert isinstance(standard_tou_strategy, TOUOptimizedStrategy)

    def test_instantiate_with_peak_hours(self):
        """Can instantiate with peak hours definition."""
        strategy = TOUOptimizedStrategy(peak_hours=[(17, 20)])
        assert isinstance(strategy, TOUOptimizedStrategy)

    def test_instantiate_with_multiple_peak_periods(self):
        """Can instantiate with multiple peak periods."""
        strategy = TOUOptimizedStrategy(peak_hours=[(7, 9), (17, 20)])
        assert isinstance(strategy, TOUOptimizedStrategy)

    def test_instantiate_with_off_peak_hours(self):
        """Can instantiate with explicit off-peak hours."""
        strategy = TOUOptimizedStrategy(
            peak_hours=[(17, 20)], off_peak_hours=[(9, 16)]
        )
        assert isinstance(strategy, TOUOptimizedStrategy)

    def test_returns_dispatch_decision(self, standard_tou_strategy):
        """decide_action returns a DispatchDecision."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert isinstance(decision, DispatchDecision)


class TestTOUOptimizedStrategyValidation:
    """Test TOUOptimizedStrategy input validation."""

    def test_invalid_peak_hour_range_raises(self):
        """Peak hours outside 0-23 range raises error."""
        with pytest.raises(ValueError, match="must be in range 0-23"):
            TOUOptimizedStrategy(peak_hours=[(25, 28)])

    def test_negative_peak_hour_raises(self):
        """Negative peak hours raise error."""
        with pytest.raises(ValueError, match="must be in range 0-23"):
            TOUOptimizedStrategy(peak_hours=[(-1, 5)])

    def test_peak_start_after_end_raises(self):
        """Peak period with start >= end raises error."""
        with pytest.raises(ValueError, match="start must be before end"):
            TOUOptimizedStrategy(peak_hours=[(20, 17)])

    def test_peak_start_equals_end_raises(self):
        """Peak period with start == end raises error."""
        with pytest.raises(ValueError, match="start must be before end"):
            TOUOptimizedStrategy(peak_hours=[(17, 17)])

    def test_invalid_offpeak_hour_range_raises(self):
        """Off-peak hours outside 0-23 range raises error."""
        with pytest.raises(ValueError, match="must be in range 0-23"):
            TOUOptimizedStrategy(peak_hours=[(17, 20)], off_peak_hours=[(25, 30)])

    def test_offpeak_start_after_end_raises(self):
        """Off-peak period with start >= end raises error."""
        with pytest.raises(ValueError, match="start must be before end"):
            TOUOptimizedStrategy(peak_hours=[(17, 20)], off_peak_hours=[(6, 2)])

    def test_negative_generation_raises(self, standard_tou_strategy):
        """Negative generation raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_tou_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=-1.0,
                demand_kw=1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_demand_raises(self, standard_tou_strategy):
        """Negative demand raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_tou_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=-1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_soc_raises(self, standard_tou_strategy):
        """Negative battery SOC raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_tou_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=-1.0,
                battery_capacity_kwh=5.0,
            )

    def test_zero_capacity_raises(self, standard_tou_strategy):
        """Zero battery capacity raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="positive"):
            standard_tou_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=0.0,
                battery_capacity_kwh=0.0,
            )

    def test_zero_timestep_raises(self, standard_tou_strategy):
        """Zero timestep raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="positive"):
            standard_tou_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
                timestep_minutes=0.0,
            )


class TestTOUOptimizedStrategyOffPeak:
    """Test TOU strategy during off-peak hours."""

    def test_offpeak_excess_pv_charges(self, standard_tou_strategy):
        """During off-peak with excess PV, battery charges."""
        # 12:00 PM - off-peak time
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 3.0 - 1.0 = 2.0 kW
        assert decision.charge_kw == 2.0
        assert decision.discharge_kw == 0.0

    def test_offpeak_shortfall_preserves_battery(self, standard_tou_strategy):
        """During off-peak with shortfall, battery is preserved for peak periods."""
        # 12:00 PM - off-peak time
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Off-peak: let cheap grid power handle shortfall, preserve battery for peak
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_offpeak_balanced_no_action(self, standard_tou_strategy):
        """During off-peak with balanced gen/demand, no action."""
        # 12:00 PM - off-peak time
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_early_morning_is_offpeak(self, standard_tou_strategy):
        """Early morning hours are off-peak."""
        # 6:00 AM - should be off-peak
        timestamp = datetime(2024, 1, 1, 6, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should charge from excess (off-peak behavior)
        assert decision.charge_kw == 2.0
        assert decision.discharge_kw == 0.0


class TestTOUOptimizedStrategyPeak:
    """Test TOU strategy during peak hours."""

    def test_peak_excess_pv_charges(self, standard_tou_strategy):
        """During peak with excess PV, still charges (free energy)."""
        # 6:00 PM - peak time (17:00-20:00)
        timestamp = datetime(2024, 1, 1, 18, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 3.0 - 1.0 = 2.0 kW - charges even during peak
        assert decision.charge_kw == 2.0
        assert decision.discharge_kw == 0.0

    def test_peak_shortfall_discharges(self, standard_tou_strategy):
        """During peak with shortfall, battery discharges to offset costs."""
        # 6:00 PM - peak time
        timestamp = datetime(2024, 1, 1, 18, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall = 3.0 - 1.0 = 2.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 2.0

    def test_peak_balanced_no_action(self, standard_tou_strategy):
        """During peak with balanced gen/demand, no action."""
        # 6:00 PM - peak time
        timestamp = datetime(2024, 1, 1, 18, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_peak_start_hour(self, standard_tou_strategy):
        """Peak period start hour (17:00) is detected correctly."""
        # 5:00 PM - start of peak
        timestamp = datetime(2024, 1, 1, 17, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should discharge (peak behavior)
        assert decision.discharge_kw == 2.0

    def test_peak_end_hour_is_offpeak(self, standard_tou_strategy):
        """Peak period end hour (20:00) is actually off-peak."""
        # 8:00 PM - just after peak ends (17:00-20:00 means up to 19:59)
        timestamp = datetime(2024, 1, 1, 20, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Off-peak: preserve battery, no discharge
        assert decision.discharge_kw == 0.0

    def test_before_peak_is_offpeak(self, standard_tou_strategy):
        """Hour before peak start is off-peak."""
        # 4:00 PM - just before peak
        timestamp = datetime(2024, 1, 1, 16, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should charge from excess (off-peak behavior)
        assert decision.charge_kw == 2.0


class TestTOUOptimizedStrategyMultiplePeaks:
    """Test TOU strategy with multiple peak periods."""

    def test_morning_peak_detected(self, multi_peak_tou_strategy):
        """Morning peak period (7-9 AM) is detected."""
        # 8:00 AM - in morning peak
        timestamp = datetime(2024, 1, 1, 8, 0, 0)
        decision = multi_peak_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should discharge (peak behavior)
        assert decision.discharge_kw == 2.0

    def test_evening_peak_detected(self, multi_peak_tou_strategy):
        """Evening peak period (5-8 PM) is detected."""
        # 6:00 PM - in evening peak
        timestamp = datetime(2024, 1, 1, 18, 0, 0)
        decision = multi_peak_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should discharge (peak behavior)
        assert decision.discharge_kw == 2.0

    def test_between_peaks_is_offpeak(self, multi_peak_tou_strategy):
        """Time between peak periods is off-peak."""
        # 12:00 PM - between morning and evening peak
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = multi_peak_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should charge from excess (off-peak behavior)
        assert decision.charge_kw == 2.0

    def test_after_all_peaks_is_offpeak(self, multi_peak_tou_strategy):
        """Time after all peak periods is off-peak."""
        # 11:00 PM - after both peaks
        timestamp = datetime(2024, 1, 1, 23, 0, 0)
        decision = multi_peak_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Should charge from excess (off-peak behavior)
        assert decision.charge_kw == 2.0


class TestTOUOptimizedStrategySOCIndependence:
    """Test that TOU strategy doesn't depend on SOC for basic decisions."""

    def test_decision_independent_of_soc(self, standard_tou_strategy):
        """Decision is same regardless of battery SOC."""
        timestamp = datetime(2024, 1, 1, 18, 0, 0)  # Peak time

        decision_high = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=4.0,  # High SOC
            battery_capacity_kwh=5.0,
        )
        decision_low = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=0.5,  # Low SOC
            battery_capacity_kwh=5.0,
        )

        assert decision_high.charge_kw == decision_low.charge_kw
        assert decision_high.discharge_kw == decision_low.discharge_kw


class TestTOUOptimizedStrategyEdgeCases:
    """Test TOU strategy edge cases."""

    def test_midnight_hour_zero(self, standard_tou_strategy):
        """Midnight (hour 0) is handled correctly."""
        timestamp = datetime(2024, 1, 1, 0, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Midnight is off-peak, preserve battery
        assert decision.discharge_kw == 0.0

    def test_hour_23_before_midnight(self, standard_tou_strategy):
        """Hour 23 (11 PM) is handled correctly."""
        timestamp = datetime(2024, 1, 1, 23, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # 11 PM is off-peak, preserve battery
        assert decision.discharge_kw == 0.0

    def test_zero_generation_zero_demand_offpeak(self, standard_tou_strategy):
        """Zero generation and demand during off-peak."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=0.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_zero_generation_zero_demand_peak(self, standard_tou_strategy):
        """Zero generation and demand during peak."""
        timestamp = datetime(2024, 1, 1, 18, 0, 0)
        decision = standard_tou_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=0.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0


# =============================================================================
# PEAK SHAVING STRATEGY TESTS
# =============================================================================


@pytest.fixture
def standard_peak_shaving_strategy():
    """Create a standard peak shaving strategy with 2 kW limit."""
    return PeakShavingStrategy(import_limit_kw=2.0)


@pytest.fixture
def low_limit_peak_shaving_strategy():
    """Create a peak shaving strategy with low 0.5 kW limit."""
    return PeakShavingStrategy(import_limit_kw=0.5)


@pytest.fixture
def high_limit_peak_shaving_strategy():
    """Create a peak shaving strategy with high 5 kW limit."""
    return PeakShavingStrategy(import_limit_kw=5.0)


class TestPeakShavingStrategyBasics:
    """Test basic PeakShavingStrategy functionality."""

    def test_can_instantiate(self, standard_peak_shaving_strategy):
        """PeakShavingStrategy can be instantiated."""
        assert isinstance(standard_peak_shaving_strategy, DispatchStrategy)
        assert isinstance(standard_peak_shaving_strategy, PeakShavingStrategy)

    def test_instantiate_with_import_limit(self):
        """Can instantiate with import limit."""
        strategy = PeakShavingStrategy(import_limit_kw=3.0)
        assert isinstance(strategy, PeakShavingStrategy)

    def test_returns_dispatch_decision(self, standard_peak_shaving_strategy):
        """decide_action returns a DispatchDecision."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert isinstance(decision, DispatchDecision)


class TestPeakShavingStrategyValidation:
    """Test PeakShavingStrategy input validation."""

    def test_zero_import_limit_raises(self):
        """Zero import limit raises error."""
        with pytest.raises(ValueError, match="positive"):
            PeakShavingStrategy(import_limit_kw=0.0)

    def test_negative_import_limit_raises(self):
        """Negative import limit raises error."""
        with pytest.raises(ValueError, match="positive"):
            PeakShavingStrategy(import_limit_kw=-1.0)

    def test_negative_generation_raises(self, standard_peak_shaving_strategy):
        """Negative generation raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_peak_shaving_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=-1.0,
                demand_kw=2.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_demand_raises(self, standard_peak_shaving_strategy):
        """Negative demand raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_peak_shaving_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=-1.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
            )

    def test_negative_soc_raises(self, standard_peak_shaving_strategy):
        """Negative battery SOC raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="non-negative"):
            standard_peak_shaving_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=2.0,
                battery_soc_kwh=-1.0,
                battery_capacity_kwh=5.0,
            )

    def test_zero_capacity_raises(self, standard_peak_shaving_strategy):
        """Zero battery capacity raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="positive"):
            standard_peak_shaving_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=2.0,
                battery_soc_kwh=0.0,
                battery_capacity_kwh=0.0,
            )

    def test_zero_timestep_raises(self, standard_peak_shaving_strategy):
        """Zero timestep raises error."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="positive"):
            standard_peak_shaving_strategy.decide_action(
                timestamp=timestamp,
                generation_kw=1.0,
                demand_kw=2.0,
                battery_soc_kwh=2.5,
                battery_capacity_kwh=5.0,
                timestep_minutes=0.0,
            )


class TestPeakShavingStrategyExcessPV:
    """Test peak shaving with excess PV generation."""

    def test_excess_pv_charges(self, standard_peak_shaving_strategy):
        """When generation > demand, battery charges from excess."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=5.0,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 5.0 - 2.0 = 3.0 kW
        assert decision.charge_kw == 3.0
        assert decision.discharge_kw == 0.0

    def test_large_excess_charges(self, standard_peak_shaving_strategy):
        """Large excess PV charges appropriately."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=10.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 10.0 - 1.0 = 9.0 kW
        assert decision.charge_kw == 9.0
        assert decision.discharge_kw == 0.0

    def test_small_excess_charges(self, standard_peak_shaving_strategy):
        """Small excess PV charges appropriately."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.1,
            demand_kw=2.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 2.1 - 2.0 = 0.1 kW
        assert decision.charge_kw == pytest.approx(0.1)
        assert decision.discharge_kw == 0.0


class TestPeakShavingStrategyBelowThreshold:
    """Test peak shaving when import is below threshold."""

    def test_shortfall_below_threshold_no_discharge(
        self, standard_peak_shaving_strategy
    ):
        """When shortfall < threshold, no battery discharge."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=2.5,  # Shortfall = 1.5 kW < 2.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall is 1.5 kW, which is below 2.0 kW threshold
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_shortfall_exactly_at_threshold_no_discharge(
        self, standard_peak_shaving_strategy
    ):
        """When shortfall exactly equals threshold, no discharge."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.0,  # Shortfall = 2.0 kW = threshold
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall equals threshold, no shaving needed
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_small_shortfall_below_threshold(self, standard_peak_shaving_strategy):
        """Small shortfall below threshold requires no action."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=2.0,
            demand_kw=2.5,  # Shortfall = 0.5 kW < 2.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0


class TestPeakShavingStrategyAboveThreshold:
    """Test peak shaving when import exceeds threshold."""

    def test_shortfall_above_threshold_discharges(
        self, standard_peak_shaving_strategy
    ):
        """When shortfall > threshold, battery discharges to shave peak."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=5.0,  # Shortfall = 4.0 kW > 2.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = shortfall - threshold = 4.0 - 2.0 = 2.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 2.0

    def test_large_peak_discharge_amount(self, standard_peak_shaving_strategy):
        """Large peak results in large discharge to shave."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=10.0,  # Shortfall = 10.0 kW > 2.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 10.0 - 2.0 = 8.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 8.0

    def test_small_peak_above_threshold(self, standard_peak_shaving_strategy):
        """Small peak slightly above threshold."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=3.5,  # Shortfall = 2.5 kW > 2.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 2.5 - 2.0 = 0.5 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(0.5)


class TestPeakShavingStrategyDifferentLimits:
    """Test peak shaving with different import limits."""

    def test_low_limit_triggers_more_discharge(self, low_limit_peak_shaving_strategy):
        """Low import limit (0.5 kW) triggers discharge more often."""
        # Limit is 0.5 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = low_limit_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=2.0,  # Shortfall = 1.0 kW > 0.5 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 1.0 - 0.5 = 0.5 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(0.5)

    def test_high_limit_allows_more_import(self, high_limit_peak_shaving_strategy):
        """High import limit (5 kW) allows more grid import."""
        # Limit is 5.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = high_limit_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=5.0,  # Shortfall = 4.0 kW < 5.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Shortfall below threshold, no discharge
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_high_limit_shaves_large_peaks(self, high_limit_peak_shaving_strategy):
        """High limit still shaves very large peaks."""
        # Limit is 5.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = high_limit_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=10.0,  # Shortfall = 10.0 kW > 5.0 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 10.0 - 5.0 = 5.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 5.0


class TestPeakShavingStrategyBalanced:
    """Test peak shaving when generation equals demand."""

    def test_balanced_no_action(self, standard_peak_shaving_strategy):
        """When generation equals demand, no battery action."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=3.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_both_zero_no_action(self, standard_peak_shaving_strategy):
        """When both generation and demand are zero, no action."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=0.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0


class TestPeakShavingStrategySOCIndependence:
    """Test that peak shaving doesn't depend on SOC."""

    def test_decision_independent_of_soc(self, standard_peak_shaving_strategy):
        """Decision is same regardless of battery SOC."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)

        decision_high = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=4.0,  # High SOC
            battery_capacity_kwh=5.0,
        )
        decision_low = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=0.5,  # Low SOC
            battery_capacity_kwh=5.0,
        )

        assert decision_high.charge_kw == decision_low.charge_kw
        assert decision_high.discharge_kw == decision_low.discharge_kw


class TestPeakShavingStrategyTimestampIndependence:
    """Test that peak shaving doesn't depend on timestamp."""

    def test_decision_independent_of_time(self, standard_peak_shaving_strategy):
        """Decision is same regardless of timestamp."""
        morning = datetime(2024, 1, 1, 8, 0, 0)
        afternoon = datetime(2024, 1, 1, 14, 0, 0)
        evening = datetime(2024, 1, 1, 20, 0, 0)

        decision_morning = standard_peak_shaving_strategy.decide_action(
            timestamp=morning,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        decision_afternoon = standard_peak_shaving_strategy.decide_action(
            timestamp=afternoon,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        decision_evening = standard_peak_shaving_strategy.decide_action(
            timestamp=evening,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

        assert decision_morning.charge_kw == decision_afternoon.charge_kw
        assert decision_morning.charge_kw == decision_evening.charge_kw
        assert decision_morning.discharge_kw == decision_afternoon.discharge_kw
        assert decision_morning.discharge_kw == decision_evening.discharge_kw


class TestDispatchDecisionGridCharge:
    """Test grid_charge_kw field on DispatchDecision."""

    def test_default_grid_charge_kw_is_zero(self):
        """Existing 2-keyword construction still valid; grid_charge_kw defaults to 0.0."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        assert decision.grid_charge_kw == 0.0

    def test_grid_charge_kw_stored(self):
        """grid_charge_kw field stores the supplied value."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=2.0)
        assert decision.grid_charge_kw == 2.0

    def test_negative_grid_charge_kw_raises(self):
        """Negative grid_charge_kw raises ValueError with 'non-negative' message."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=-0.5)

    def test_grid_charge_and_discharge_simultaneously_raises(self):
        """grid_charge_kw > 0 and discharge_kw > 0 is physically impossible."""
        with pytest.raises(ValueError, match="grid.charge|discharge"):
            DispatchDecision(charge_kw=0.0, discharge_kw=1.0, grid_charge_kw=2.0)

    def test_grid_charge_with_pv_charge_is_allowed(self):
        """grid_charge_kw > 0 alongside charge_kw > 0 is permitted (both charging)."""
        decision = DispatchDecision(charge_kw=1.5, discharge_kw=0.0, grid_charge_kw=2.0)
        assert decision.charge_kw == 1.5
        assert decision.grid_charge_kw == 2.0


class TestGridChargeContext:
    """Test GridChargeContext frozen dataclass."""

    def _make_ctx(self, **overrides):  # type: ignore[no-untyped-def]
        """Build a default GridChargeContext, applying keyword overrides."""
        defaults = dict(
            current_rate=0.10,
            peak_rate=0.40,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=5.0,
            round_trip_efficiency=0.81,
            charge_efficiency=0.9,
        )
        defaults.update(overrides)
        return GridChargeContext(**defaults)

    def test_can_construct_with_all_fields(self):
        """GridChargeContext can be created with all seven keyword fields."""
        ctx = self._make_ctx()
        assert ctx.current_rate == pytest.approx(0.10)
        assert ctx.peak_rate == pytest.approx(0.40)
        assert ctx.is_cheap_period is True
        assert ctx.target_soc_fraction == pytest.approx(0.9)
        assert ctx.max_charge_kw == pytest.approx(5.0)
        assert ctx.round_trip_efficiency == pytest.approx(0.81)
        assert ctx.charge_efficiency == pytest.approx(0.9)

    def test_fields_round_trip(self):
        """All field values round-trip correctly."""
        ctx = GridChargeContext(
            current_rate=0.07,
            peak_rate=0.32,
            is_cheap_period=False,
            target_soc_fraction=0.8,
            max_charge_kw=3.3,
            round_trip_efficiency=0.85,
            charge_efficiency=0.95,
        )
        assert ctx.current_rate == pytest.approx(0.07)
        assert ctx.peak_rate == pytest.approx(0.32)
        assert ctx.is_cheap_period is False
        assert ctx.target_soc_fraction == pytest.approx(0.8)
        assert ctx.max_charge_kw == pytest.approx(3.3)
        assert ctx.round_trip_efficiency == pytest.approx(0.85)
        assert ctx.charge_efficiency == pytest.approx(0.95)

    def test_is_frozen(self):
        """GridChargeContext is immutable (frozen dataclass)."""
        ctx = self._make_ctx()
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.current_rate = 0.20  # type: ignore[misc]

    def test_zero_round_trip_efficiency_raises(self):
        """round_trip_efficiency=0 raises ValueError (would cause ZeroDivisionError)."""
        with pytest.raises(ValueError, match="round_trip_efficiency"):
            self._make_ctx(round_trip_efficiency=0.0)

    def test_negative_round_trip_efficiency_raises(self):
        """Negative round_trip_efficiency raises ValueError."""
        with pytest.raises(ValueError, match="round_trip_efficiency"):
            self._make_ctx(round_trip_efficiency=-0.1)

    def test_round_trip_efficiency_above_one_raises(self):
        """round_trip_efficiency > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="round_trip_efficiency"):
            self._make_ctx(round_trip_efficiency=1.01)

    def test_zero_charge_efficiency_raises(self):
        """charge_efficiency=0 raises ValueError (would cause ZeroDivisionError)."""
        with pytest.raises(ValueError, match="charge_efficiency"):
            self._make_ctx(charge_efficiency=0.0)

    def test_negative_charge_efficiency_raises(self):
        """Negative charge_efficiency raises ValueError."""
        with pytest.raises(ValueError, match="charge_efficiency"):
            self._make_ctx(charge_efficiency=-0.5)

    def test_charge_efficiency_above_one_raises(self):
        """charge_efficiency > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="charge_efficiency"):
            self._make_ctx(charge_efficiency=1.1)

    def test_efficiency_exactly_one_is_valid(self):
        """Efficiency values of exactly 1.0 are at the boundary and are valid."""
        ctx = self._make_ctx(round_trip_efficiency=1.0, charge_efficiency=1.0)
        assert ctx.round_trip_efficiency == pytest.approx(1.0)
        assert ctx.charge_efficiency == pytest.approx(1.0)


class TestComputeGridChargePowerKw:
    """Tests for compute_grid_charge_power_kw — all branches of PRD §3.2."""

    # Helper: build a "favourable" context that would yield non-zero charge power.
    # is_cheap=True, spread is profitable (peak >> current/rt_eff),
    # target not yet reached.
    _CTX_FAVOURABLE = GridChargeContext(
        current_rate=0.10,
        peak_rate=0.40,
        is_cheap_period=True,
        target_soc_fraction=0.9,
        max_charge_kw=20.0,
        round_trip_efficiency=0.81,
        charge_efficiency=0.9,
    )

    def test_not_cheap_returns_zero(self):
        """When is_cheap_period=False, returns 0.0 regardless of other fields."""
        ctx = GridChargeContext(
            current_rate=0.05,
            peak_rate=0.40,
            is_cheap_period=False,   # not cheap
            target_soc_fraction=0.9,
            max_charge_kw=20.0,
            round_trip_efficiency=0.81,
            charge_efficiency=0.9,
        )
        result = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert result == 0.0

    def test_spread_gate_fails_returns_zero(self):
        """When peak_rate <= current_rate/round_trip_efficiency, returns 0.0."""
        # peak_rate=0.10, current_rate=0.10, rt_eff=0.81
        # threshold = 0.10 / 0.81 ≈ 0.1235; peak_rate=0.10 <= 0.1235 → gate fails
        ctx = GridChargeContext(
            current_rate=0.10,
            peak_rate=0.10,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=20.0,
            round_trip_efficiency=0.81,
            charge_efficiency=0.9,
        )
        result = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert result == 0.0

    def test_flat_tariff_spread_gate_fails(self):
        """flat tariff (peak_rate == current_rate) → spread gate fails → 0.0."""
        ctx = GridChargeContext(
            current_rate=0.25,
            peak_rate=0.25,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=20.0,
            round_trip_efficiency=0.90,
            charge_efficiency=0.9,
        )
        result = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=0.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert result == 0.0

    def test_soc_at_target_returns_zero(self):
        """When battery_soc_kwh >= target_soc_fraction * capacity_kwh, returns 0.0."""
        # target = 0.9 * 10 = 9.0 kWh; soc = 9.0 kWh → gap = 0
        result = compute_grid_charge_power_kw(
            self._CTX_FAVOURABLE,
            battery_soc_kwh=9.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert result == 0.0

    def test_soc_above_target_returns_zero(self):
        """When SOC already above target, returns 0.0."""
        result = compute_grid_charge_power_kw(
            self._CTX_FAVOURABLE,
            battery_soc_kwh=9.5,  # above 9.0 target
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert result == 0.0

    def test_gap_power_wins(self):
        """When residual budget is large, min picks gap_power.

        Params: is_cheap=True, peak=0.40, current=0.10, rt_eff=0.81,
        charge_eff=0.9, target=0.9, capacity=10, soc=2.0,
        max_charge_kw=20, pv_charge_kw=0, timestep=60.

        gap_kwh = 0.9*10 - 2.0 = 7.0
        gap_power = 7.0 / 0.9 / 1.0 = 7.7778 kW
        residual  = 20.0 - 0.0 = 20.0 kW
        result    = min(7.7778, 20.0) = 7.7778 kW
        """
        result = compute_grid_charge_power_kw(
            self._CTX_FAVOURABLE,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        # gap_power = 7.0 / 0.9 / 1.0
        expected = 7.0 / 0.9 / 1.0
        assert result == pytest.approx(expected)

    def test_residual_clamp_wins(self):
        """When max_charge_kw is tight, min picks residual.

        Same as above but max_charge_kw=5.0, pv_charge_kw=1.0.
        residual = 5.0 - 1.0 = 4.0 kW < gap_power ≈ 7.78 kW
        result = 4.0 kW
        """
        ctx = GridChargeContext(
            current_rate=0.10,
            peak_rate=0.40,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=5.0,
            round_trip_efficiency=0.81,
            charge_efficiency=0.9,
        )
        result = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=1.0,
            timestep_minutes=60.0,
        )
        assert result == pytest.approx(4.0)

    def test_timestep_scaling(self):
        """Halving timestep_minutes doubles gap_power when residual is non-binding.

        At timestep=30 min, dt_h=0.5, gap_power = 7.0/0.9/0.5 = 15.556 kW.
        With max_charge_kw=20, residual=20, min picks gap_power ≈ 15.556.
        Compare to 60-min case ≈ 7.778; ratio should be ~2.
        """
        result_30 = compute_grid_charge_power_kw(
            self._CTX_FAVOURABLE,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=30.0,
        )
        result_60 = compute_grid_charge_power_kw(
            self._CTX_FAVOURABLE,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        # Halved timestep → doubled gap_power (residual non-binding in both cases)
        assert result_30 == pytest.approx(result_60 * 2.0)

    def test_zero_timestep_raises(self):
        """timestep_minutes=0 raises ValueError (would cause ZeroDivisionError)."""
        with pytest.raises(ValueError, match="positive"):
            compute_grid_charge_power_kw(
                self._CTX_FAVOURABLE,
                battery_soc_kwh=2.0,
                capacity_kwh=10.0,
                pv_charge_power_kw=0.0,
                timestep_minutes=0.0,
            )

    def test_negative_timestep_raises(self):
        """Negative timestep_minutes raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            compute_grid_charge_power_kw(
                self._CTX_FAVOURABLE,
                battery_soc_kwh=2.0,
                capacity_kwh=10.0,
                pv_charge_power_kw=0.0,
                timestep_minutes=-1.0,
            )

    def test_residual_clamp_is_battery_side(self):
        """Residual clamp uses battery-side headroom (conservative, per PRD §3.2).

        When charge_efficiency < 1 and residual limits the result, the function
        returns ``residual_kw`` (battery-side headroom) directly, NOT
        ``residual_kw / charge_efficiency`` (which would be the grid-side
        power needed to fully occupy that headroom). This is intentional: the
        controller conservatively caps grid draw at the battery's acceptance
        capacity in raw kW terms, avoiding over-committing grid import.

        Setup: charge_efficiency=0.8, max_charge_kw=5, pv_charge=1 →
            residual_battery = 4.0 kW (battery-side)
            gap_power        = 7.0/0.8/1.0 = 8.75 kW (grid-side, non-binding)
            result           = min(8.75, 4.0) = 4.0  (battery-side residual)
        True grid draw for full headroom would be 4.0/0.8 = 5.0 kW — NOT returned.
        """
        ctx = GridChargeContext(
            current_rate=0.10,
            peak_rate=0.40,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=5.0,
            round_trip_efficiency=0.81,
            charge_efficiency=0.8,  # deliberately different from 0.9 to surface frame
        )
        result = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=2.0,
            capacity_kwh=10.0,
            pv_charge_power_kw=1.0,  # residual = 5.0 - 1.0 = 4.0 kW battery-side
            timestep_minutes=60.0,
        )
        # Returns battery-side residual (4.0), not grid-side equivalent (4.0/0.8=5.0)
        assert result == pytest.approx(4.0)
        assert result != pytest.approx(4.0 / 0.8)  # not 5.0


class TestDecideActionAcceptsGridChargeCtx:
    """Test that decide_action accepts keyword-only grid_charge_ctx and ignores it.

    In this task the param is accept-and-ignore; real logic lands in α2/α3.
    """

    # A "favourable" context that would normally trigger grid charging
    _CHEAP_CTX = GridChargeContext(
        current_rate=0.10,
        peak_rate=0.40,
        is_cheap_period=True,
        target_soc_fraction=0.9,
        max_charge_kw=5.0,
        round_trip_efficiency=0.81,
        charge_efficiency=0.9,
    )

    # Shared scenario: shortfall, so discharge decision without ctx
    _TS = datetime(2024, 1, 1, 12, 0, 0)

    def _baseline_sc(self):
        """SelfConsumptionStrategy decision without grid_charge_ctx."""
        s = SelfConsumptionStrategy()
        return s.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

    def _baseline_tou(self):
        """TOUOptimizedStrategy (off-peak) decision without grid_charge_ctx."""
        s = TOUOptimizedStrategy(peak_hours=[(17, 20)])
        return s.decide_action(
            timestamp=self._TS,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

    def _baseline_ps(self):
        """PeakShavingStrategy decision without grid_charge_ctx."""
        s = PeakShavingStrategy(import_limit_kw=2.0)
        return s.decide_action(
            timestamp=self._TS,
            generation_kw=0.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

    # --- SelfConsumptionStrategy ---

    def test_sc_with_ctx_same_as_without(self):
        """SelfConsumption: decision identical with/without grid_charge_ctx."""
        s = SelfConsumptionStrategy()
        with_ctx = s.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            grid_charge_ctx=self._CHEAP_CTX,
        )
        without = self._baseline_sc()
        assert with_ctx.charge_kw == without.charge_kw
        assert with_ctx.discharge_kw == without.discharge_kw
        assert with_ctx.grid_charge_kw == 0.0

    def test_sc_ctx_none_same_as_without(self):
        """SelfConsumption: explicit grid_charge_ctx=None is the same as omitting."""
        s = SelfConsumptionStrategy()
        with_none = s.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            grid_charge_ctx=None,
        )
        without = self._baseline_sc()
        assert with_none.charge_kw == without.charge_kw
        assert with_none.discharge_kw == without.discharge_kw

    def test_sc_ctx_is_keyword_only(self):
        """SelfConsumption: passing grid_charge_ctx positionally raises TypeError."""
        s = SelfConsumptionStrategy()
        with pytest.raises(TypeError):
            s.decide_action(  # type: ignore[call-arg]
                self._TS, 1.0, 3.0, 2.5, 5.0, 1.0, self._CHEAP_CTX
            )

    # --- TOUOptimizedStrategy ---

    def test_tou_with_ctx_same_as_without(self):
        """TOUOptimized: charge_kw/discharge_kw unchanged; grid_charge_kw uses controller (α2).

        In α the param was accept-and-ignore.  In α2 TOUOptimizedStrategy wires
        the controller, so grid_charge_kw is now > 0 when a favourable ctx is
        supplied.  charge_kw and discharge_kw remain byte-identical to the
        no-ctx baseline.
        """
        s = TOUOptimizedStrategy(peak_hours=[(17, 20)])
        with_ctx = s.decide_action(
            timestamp=self._TS,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            grid_charge_ctx=self._CHEAP_CTX,
        )
        without = self._baseline_tou()
        assert with_ctx.charge_kw == without.charge_kw
        assert with_ctx.discharge_kw == without.discharge_kw
        # α2: TOU now grid-charges when a favourable ctx is supplied
        assert with_ctx.grid_charge_kw > 0.0

    def test_tou_ctx_is_keyword_only(self):
        """TOUOptimized: passing grid_charge_ctx positionally raises TypeError."""
        s = TOUOptimizedStrategy(peak_hours=[(17, 20)])
        with pytest.raises(TypeError):
            s.decide_action(  # type: ignore[call-arg]
                self._TS, 3.0, 1.0, 2.5, 5.0, 1.0, self._CHEAP_CTX
            )

    # --- PeakShavingStrategy ---

    def test_ps_with_ctx_same_as_without(self):
        """PeakShaving: decision identical with/without grid_charge_ctx."""
        s = PeakShavingStrategy(import_limit_kw=2.0)
        with_ctx = s.decide_action(
            timestamp=self._TS,
            generation_kw=0.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            grid_charge_ctx=self._CHEAP_CTX,
        )
        without = self._baseline_ps()
        assert with_ctx.charge_kw == without.charge_kw
        assert with_ctx.discharge_kw == without.discharge_kw
        assert with_ctx.grid_charge_kw == 0.0

    def test_ps_ctx_is_keyword_only(self):
        """PeakShaving: passing grid_charge_ctx positionally raises TypeError."""
        s = PeakShavingStrategy(import_limit_kw=2.0)
        with pytest.raises(TypeError):
            s.decide_action(  # type: ignore[call-arg]
                self._TS, 0.0, 5.0, 2.5, 5.0, 1.0, self._CHEAP_CTX
            )


class TestPeakShavingStrategyEdgeCases:
    """Test peak shaving edge cases."""

    def test_zero_generation_large_demand(self, standard_peak_shaving_strategy):
        """Zero generation with large demand."""
        # Limit is 2.0 kW
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=5.0,  # All from grid, shortfall = 5.0 kW
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 5.0 - 2.0 = 3.0 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 3.0

    def test_high_generation_zero_demand(self, standard_peak_shaving_strategy):
        """High generation with zero demand."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=timestamp,
            generation_kw=5.0,
            demand_kw=0.0,  # All excess
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Excess = 5.0 kW, should charge
        assert decision.charge_kw == 5.0
        assert decision.discharge_kw == 0.0

    def test_very_low_import_limit(self):
        """Strategy works with very low import limit."""
        strategy = PeakShavingStrategy(import_limit_kw=0.1)
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        decision = strategy.decide_action(
            timestamp=timestamp,
            generation_kw=0.0,
            demand_kw=1.0,  # Shortfall = 1.0 kW > 0.1 kW limit
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        # Discharge = 1.0 - 0.1 = 0.9 kW
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(0.9)


class TestTOUOptimizedStrategyGridCharging:
    """Test grid-charging via GridChargeContext in TOUOptimizedStrategy.decide_action.

    All cases reuse the standard_tou_strategy fixture (peak_hours=[(17, 20)]).
    Favourable context: current_rate=0.10, peak_rate=0.35 — spread gate passes
    because 0.35 > 0.10/0.9 ≈ 0.111.
    """

    _FAVOURABLE_CTX = GridChargeContext(
        current_rate=0.10,
        peak_rate=0.35,
        is_cheap_period=True,
        target_soc_fraction=0.9,
        max_charge_kw=3.0,
        round_trip_efficiency=0.9,
        charge_efficiency=0.95,
    )

    def test_offpeak_shortfall_grid_charges(self, standard_tou_strategy):
        """(1) Off-peak shortfall: no PV, grid charges at full controller rate."""
        ctx = self._FAVOURABLE_CTX
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 3, 0, 0),
            generation_kw=0.0,
            demand_kw=1.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        expected_grid = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=1.0,
            capacity_kwh=5.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw > 0.0
        assert decision.grid_charge_kw == pytest.approx(expected_grid)

    def test_offpeak_excess_pv_grid_charges_residual(self, standard_tou_strategy):
        """(2) Off-peak excess PV: grid fills remaining headroom after PV charge.

        Hand-computed literal: residual_kw = max_charge_kw(3.0) - pv(2.0) = 1.0 kW.
        gate3 gap_power_kw = (4.5-1.0)/0.95/1.0 ≈ 3.68 kW > residual → residual clamps.
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 3, 0, 0),
            generation_kw=3.0,
            demand_kw=1.0,  # excess_kw = 2.0
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.charge_kw == pytest.approx(2.0)
        assert decision.discharge_kw == 0.0
        # Residual clamp: max_charge_kw(3.0) - pv_charge_power_kw(2.0) = 1.0 kW
        assert decision.grid_charge_kw == pytest.approx(1.0)

    def test_no_ctx_no_grid_charge(self, standard_tou_strategy):
        """(3) Guard: grid_charge_ctx=None → grid_charge_kw stays 0.0."""
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 3, 0, 0),
            generation_kw=0.0,
            demand_kw=1.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=None,
        )
        assert decision.grid_charge_kw == 0.0

    def test_spread_gate_failure_no_grid_charge(self, standard_tou_strategy):
        """(4) Guard: spread gate fails → grid_charge_kw==0.0.

        peak_rate=0.31, current_rate=0.30, rt_eff=0.9:
        0.31 <= 0.30/0.9 ≈ 0.333 → Gate 2 blocks.
        """
        ctx = GridChargeContext(
            current_rate=0.30,
            peak_rate=0.31,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=3.0,
            round_trip_efficiency=0.9,
            charge_efficiency=0.95,
        )
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 3, 0, 0),
            generation_kw=0.0,
            demand_kw=1.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.grid_charge_kw == 0.0

    def test_peak_period_no_grid_charge(self, standard_tou_strategy):
        """(5) Guard: peak period (is_cheap_period=False) → discharge preserved, no grid charge."""
        ctx = GridChargeContext(
            current_rate=0.35,
            peak_rate=0.35,
            is_cheap_period=False,  # peak, not cheap
            target_soc_fraction=0.9,
            max_charge_kw=3.0,
            round_trip_efficiency=0.9,
            charge_efficiency=0.95,
        )
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 18, 0, 0),  # peak hour
            generation_kw=1.0,
            demand_kw=3.0,  # shortfall = 2.0
            battery_soc_kwh=3.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.discharge_kw == pytest.approx(2.0)
        assert decision.grid_charge_kw == 0.0

    def test_regression_no_ctx_offpeak_excess(self, standard_tou_strategy):
        """(6a) Regression: ctx=None, off-peak excess PV → same as before (charge only)."""
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == pytest.approx(2.0)
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw == 0.0

    def test_regression_no_ctx_peak_shortfall(self, standard_tou_strategy):
        """(6b) Regression: ctx=None, peak shortfall → same as before (discharge only)."""
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 18, 0, 0),
            generation_kw=1.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(2.0)
        assert decision.grid_charge_kw == 0.0

    def test_discharge_guard_prevents_grid_charge(self, standard_tou_strategy):
        """Discharge guard: peak shortfall with is_cheap_period=True is blocked by strategy.

        The strategy-level ``discharge_kw == 0.0`` guard is the active gate here,
        NOT Gate1 (is_cheap_period) inside the controller — because is_cheap_period=True
        would pass Gate1.  This test verifies that the guard cannot be regressed away
        without raising a ValueError from DispatchDecision (grid_charge_kw>0 + discharge_kw>0).
        """
        # Favourable context that WOULD trigger grid charging if discharge_kw were 0
        ctx = GridChargeContext(
            current_rate=0.10,
            peak_rate=0.35,
            is_cheap_period=True,  # caller says cheap — Gate1 passes
            target_soc_fraction=0.9,
            max_charge_kw=3.0,
            round_trip_efficiency=0.9,
            charge_efficiency=0.95,
        )
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 18, 0, 0),  # peak hour
            generation_kw=0.5,
            demand_kw=2.5,  # shortfall = 2.0 → discharge_kw = 2.0
            battery_soc_kwh=2.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        # Discharge is preserved; strategy-level guard suppresses grid charge
        assert decision.discharge_kw == pytest.approx(2.0)
        assert decision.grid_charge_kw == 0.0

    def test_soc_at_target_no_grid_charge(self, standard_tou_strategy):
        """Gate 3: battery already at target SOC → controller returns 0.0."""
        ctx = self._FAVOURABLE_CTX
        # soc == target_soc_fraction * capacity → gap_kwh = 0.0
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 3, 0, 0),  # off-peak
            generation_kw=0.0,
            demand_kw=1.0,
            battery_soc_kwh=4.5,   # = 0.9 * 5.0
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.grid_charge_kw == 0.0

    def test_is_cheap_period_true_overrides_peak_hours(self, standard_tou_strategy):
        """Seam test: ctx.is_cheap_period=True is the authority on grid-charging,
        even when the timestamp falls inside the strategy's configured peak_hours.

        The strategy's peak_hours govern charge_kw/discharge_kw decisions; they do
        NOT suppress grid charging when the caller-supplied ctx says is_cheap_period=True.
        This locks the dual-source-of-truth seam to an explicit contract: ctx wins.
        """
        ctx = self._FAVOURABLE_CTX  # is_cheap_period=True, spread passes
        # Peak hour (18:00 in peak_hours=[(17,20)]), balanced load → no shortfall
        decision = standard_tou_strategy.decide_action(
            timestamp=datetime(2024, 1, 1, 18, 0, 0),  # peak per strategy
            generation_kw=2.0,
            demand_kw=2.0,  # balanced → discharge_kw=0.0, charge_kw=0.0
            battery_soc_kwh=1.0,   # well below target (4.5 kWh) → gate3 passes
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        # ctx.is_cheap_period=True + discharge_kw=0.0 → grid charging fires
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw > 0.0


class TestPeakShavingStrategyGridCharging:
    """Test grid-charging via GridChargeContext in PeakShavingStrategy.decide_action.

    All cases reuse the standard_peak_shaving_strategy fixture (import_limit_kw=2.0).
    Favourable context: current_rate=0.10, peak_rate=0.35 — spread gate passes
    because 0.35 > 0.10/0.9 ≈ 0.111.
    All scenarios use battery_capacity_kwh=5.0, timestep_minutes=60.0.
    """

    _FAVOURABLE_CTX = GridChargeContext(
        current_rate=0.10,
        peak_rate=0.35,
        is_cheap_period=True,
        target_soc_fraction=0.9,
        max_charge_kw=3.0,
        round_trip_efficiency=0.9,
        charge_efficiency=0.95,
    )

    _TS = datetime(2024, 1, 1, 12, 0, 0)

    # -------------------------------------------------------------------------
    # Positive cases (RED today — decide_action currently ignores ctx)
    # -------------------------------------------------------------------------

    def test_below_threshold_grid_charges(self, standard_peak_shaving_strategy):
        """(1) Below-threshold shortfall / not shaving: grid charges at controller rate.

        shortfall=1.5 < import_limit=2.0 → no discharge.
        pv_charge=0.0 → residual = max_charge(3.0) - 0.0 = 3.0.
        gap_power = (4.5-1.0)/0.95/1.0 ≈ 3.68 > residual → residual clamps to 3.0.
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=2.5,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        expected_grid = compute_grid_charge_power_kw(
            ctx,
            battery_soc_kwh=1.0,
            capacity_kwh=5.0,
            pv_charge_power_kw=0.0,
            timestep_minutes=60.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw > 0.0
        assert decision.grid_charge_kw == pytest.approx(expected_grid)

    def test_excess_pv_residual_clamp_budget_sharing(
        self, standard_peak_shaving_strategy
    ):
        """(2) Excess-PV residual-clamp / budget-sharing: grid fills remaining headroom.

        gen=3.0, demand=2.0 → excess=1.0 → charge_kw=1.0.
        residual = max_charge(3.0) - pv_charge(1.0) = 2.0 kW.
        gap_power = (4.5-1.0)/0.95/1.0 ≈ 3.68 > residual → residual clamps to 2.0.
        charge_kw + grid_charge_kw = 1.0 + 2.0 = 3.0 = max_charge_kw (budget shared).
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=3.0,
            demand_kw=2.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.charge_kw == pytest.approx(1.0)
        assert decision.discharge_kw == 0.0
        # Residual clamp: max_charge_kw(3.0) - pv_charge_power_kw(1.0) = 2.0 kW
        assert decision.grid_charge_kw == pytest.approx(2.0)
        # Total charge ≤ max_charge_kw (budget shared between PV and grid)
        assert decision.charge_kw + decision.grid_charge_kw == pytest.approx(3.0)

    def test_balanced_grid_charges(self, standard_peak_shaving_strategy):
        """(3) Balanced (gen == demand): no PV charge, grid charges at controller rate.

        gen=2.0, demand=2.0 → excess=0, shortfall=0 → charge_kw=0.0, discharge_kw=0.0.
        grid_charge_kw > 0.0 because the favourable ctx passes all controller gates.
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=2.0,
            demand_kw=2.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw > 0.0

    # -------------------------------------------------------------------------
    # Precedence / suppression (PRD §11 OQ3)
    # -------------------------------------------------------------------------

    def test_shaving_suppresses_grid_charge(self, standard_peak_shaving_strategy):
        """Discharge guard (PRD §11 OQ3): peak-shaving discharge suppresses grid-charge.

        gen=1.0, demand=5.0 → shortfall=4.0 > import_limit=2.0 → discharge=2.0 kW.
        discharge_kw > 0 → grid-charge gate is blocked; grid_charge_kw stays 0.0.
        Also verifies the call does NOT raise (guards against an unconditional
        controller call that would trip DispatchDecision's mutual-exclusion validation).
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(2.0)
        assert decision.grid_charge_kw == 0.0

    # -------------------------------------------------------------------------
    # Guard cases
    # -------------------------------------------------------------------------

    def test_no_ctx_no_grid_charge(self, standard_peak_shaving_strategy):
        """Guard: grid_charge_ctx=None → grid_charge_kw stays 0.0."""
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=2.5,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=None,
        )
        assert decision.grid_charge_kw == 0.0

    def test_not_cheap_period_no_grid_charge(self, standard_peak_shaving_strategy):
        """Guard: is_cheap_period=False → grid_charge_kw stays 0.0."""
        ctx = GridChargeContext(
            current_rate=0.35,
            peak_rate=0.35,
            is_cheap_period=False,
            target_soc_fraction=0.9,
            max_charge_kw=3.0,
            round_trip_efficiency=0.9,
            charge_efficiency=0.95,
        )
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=2.5,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.grid_charge_kw == 0.0

    def test_spread_gate_failure_no_grid_charge(self, standard_peak_shaving_strategy):
        """Guard: spread gate fails → grid_charge_kw==0.0.

        current_rate=0.30, peak_rate=0.31, rt_eff=0.9:
        0.31 <= 0.30/0.9 ≈ 0.333 → Gate 2 blocks.
        """
        ctx = GridChargeContext(
            current_rate=0.30,
            peak_rate=0.31,
            is_cheap_period=True,
            target_soc_fraction=0.9,
            max_charge_kw=3.0,
            round_trip_efficiency=0.9,
            charge_efficiency=0.95,
        )
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=2.5,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.grid_charge_kw == 0.0

    def test_soc_at_target_no_grid_charge(self, standard_peak_shaving_strategy):
        """Gate 3: battery already at target SOC → controller returns 0.0.

        soc=4.5 = 0.9 * 5.0 → gap_kwh = 0.0 → controller returns 0.0.
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=1.0,
            demand_kw=2.5,
            battery_soc_kwh=4.5,  # = 0.9 * 5.0
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.grid_charge_kw == 0.0

    # -------------------------------------------------------------------------
    # Regression: ctx omitted → behaviour unchanged from pre-α3 baseline
    # -------------------------------------------------------------------------

    def test_regression_no_ctx_excess_pv(self, standard_peak_shaving_strategy):
        """Regression: ctx=None, excess PV → charge only, no grid charge."""
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=3.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == pytest.approx(2.0)
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw == 0.0

    def test_regression_no_ctx_shaving(self, standard_peak_shaving_strategy):
        """Regression: ctx=None, shaving → discharge only, no grid charge."""
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=0.0,
            demand_kw=5.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == pytest.approx(3.0)
        assert decision.grid_charge_kw == 0.0
