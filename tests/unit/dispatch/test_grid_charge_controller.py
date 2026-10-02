# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rate-aware grid-charge controller, from its GridChargeContext to the grid_charge_ctx keyword every strategy takes."""

from datetime import datetime

import pytest

from solar_challenge.dispatch import (
    GridChargeContext,
    PeakShavingStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
    compute_grid_charge_power_kw,
)


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
    """Test that each strategy's decide_action takes grid_charge_ctx keyword-only, with charge_kw and discharge_kw the same as without it."""

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
        """TOUOptimized: charge_kw/discharge_kw unchanged; grid_charge_kw uses controller.

        TOUOptimizedStrategy wires the controller, so grid_charge_kw > 0 when a
        favourable ctx is supplied.  charge_kw and discharge_kw remain
        byte-identical to the no-ctx baseline.
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
