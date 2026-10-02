# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for PeakShavingStrategy, which discharges the battery only to hold grid import at its limit and grid-charges it in cheap periods."""

from datetime import datetime

import pytest

from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    PeakShavingStrategy,
    compute_grid_charge_power_kw,
)


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
    # Positive cases
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

    def test_excess_pv_saturates_budget_no_grid_charge(
        self, standard_peak_shaving_strategy
    ):
        """Residual-saturation edge: excess PV alone meets/exceeds max_charge_kw.

        gen=5.0, demand=1.0 → excess=4.0 > max_charge_kw=3.0.
        residual = max_charge_kw(3.0) - pv_charge(4.0) = -1.0 → clamped to 0.0.
        grid_charge_kw must be 0.0 even in a favourable cheap period because the
        inverter budget is already exhausted (or over-committed) by PV.
        charge_kw reports the raw excess (4.0) — the battery layer clamps downstream.
        """
        ctx = self._FAVOURABLE_CTX
        decision = standard_peak_shaving_strategy.decide_action(
            timestamp=self._TS,
            generation_kw=5.0,
            demand_kw=1.0,
            battery_soc_kwh=1.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=60.0,
            grid_charge_ctx=ctx,
        )
        assert decision.charge_kw == pytest.approx(4.0)
        assert decision.discharge_kw == 0.0
        assert decision.grid_charge_kw == 0.0
