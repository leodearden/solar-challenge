# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for TOUOptimizedStrategy, which discharges the battery only in its peak hours and grid-charges it in cheap periods."""

from datetime import datetime

import pytest

from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    TOUOptimizedStrategy,
    compute_grid_charge_power_kw,
)


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

    def test_off_peak_hours_is_refused(self):
        """Every hour outside peak_hours is off-peak, so an off-peak window is
        refused rather than silently ignored."""
        with pytest.raises(TypeError, match="off_peak_hours"):
            TOUOptimizedStrategy(peak_hours=[(17, 20)], off_peak_hours=[(0, 7)])

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
