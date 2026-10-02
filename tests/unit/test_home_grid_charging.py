# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for grid charging a home battery on a time-of-use tariff."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig, TariffPeriod
from tests._synthetic_weather import sunless_weather


@pytest.fixture
def night_weather_data() -> pd.DataFrame:
    """No sun on 21 June, so any battery charge comes from the grid, not excess PV."""
    return sunless_weather("2024-06-21", temp_air=12.0)


class TestSimulateHomeStrategyPathGridCharging:
    """Test grid-charging wiring via the Strategy-pattern dispatch path.

    The Strategy path (else branch in home.simulate_home) is taken when
    BatteryConfig.dispatch_strategy is set, making use_tariff_tou False.
    Before the fix, simulate_timestep on this path never receives tariff=…,
    so grid_charge_ctx is always None and grid-charging is dead.
    After the fix (adding tariff=config.tariff_config), the full grid-charge
    chain fires: is_cheap + spread gates pass → battery charged from grid.
    """

    @pytest.fixture
    def strategy_grid_charge_config(self):
        """HomeConfig that routes to the Strategy (else) branch and enables grid-charging.

        - BatteryConfig.dispatch_strategy is set → use_tariff_tou = False → else branch.
        - GridChargeConfig(target_soc_fraction=0.9) enables arbitrage charging.
        - Tariff: 0.10 £/kWh overnight (00:00-07:00, off-peak) + 0.30 £/kWh during day
          (07:00-00:00, peak). rt_eff ≈ 0.9506 → is_cheap (0.10 ≤ 0.20 avg) ✓;
          spread gate (0.30 > 0.10/0.9506 ≈ 0.1052) ✓.
        """
        off_peak = TariffPeriod("00:00", "07:00", 0.10, "Off-peak")
        peak = TariffPeriod("07:00", "00:00", 0.30, "Peak")
        return HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                max_charge_kw=2.5,
                dispatch_strategy=DispatchStrategyConfig(
                    strategy_type="tou_optimized",
                    peak_hours=[(7, 24)],
                ),
                grid_charging=GridChargeConfig(target_soc_fraction=0.9),
            ),
            tariff_config=TariffConfig(
                periods=(off_peak, peak),
                name="E7-like",
            ),
            location=Location.bristol(),
        )

    def test_strategy_path_grid_charges_battery(
        self, strategy_grid_charge_config, night_weather_data
    ):
        """Strategy path: zero-PV + tariff threaded → battery_charge > 0 (grid charging active).

        RED before fix: home.py Strategy else-branch omits tariff= → grid_charge_ctx is
        None → no grid charging → battery_charge.sum() == 0. GREEN after fix.

        Also verifies the §3.1 split-accounting energy balance closes on the Strategy path:
        generation + grid_import ≈ demand + grid_export + (battery_charge - battery_discharge).
        validate_balance=True already enforces this per-timestep; the explicit series check
        below makes the guarantee visible as a reviewable assertion.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.battery_charge.sum() > 0, (
            "Expected battery_charge > 0: grid charging should engage via Strategy path "
            "when tariff=config.tariff_config is threaded into simulate_timestep"
        )
        # §3.1 split-accounting identity (generation + grid_import == demand + grid_export +
        # battery_net) should hold element-wise within floating-point tolerance.
        lhs = results.generation + results.grid_import
        rhs = (
            results.demand
            + results.grid_export
            + (results.battery_charge - results.battery_discharge)
        )
        imbalance = (lhs - rhs).abs().max()
        assert imbalance < 1e-6, (
            f"Energy balance violated: max imbalance = {imbalance:.2e} kW"
        )

    def test_soc_rises_overnight_from_grid(
        self, strategy_grid_charge_config, night_weather_data
    ):
        """SOC climbs above the observed starting SOC during the cheap overnight window.

        RED before fix: with tariff absent from the call, grid_charge_ctx is None,
        no charging occurs, SOC stays at whatever the battery initialises to.
        GREEN after fix: overnight charging raises SOC toward target 0.9 × capacity.

        Uses results.battery_soc.iloc[0] rather than a re-derived constant so the
        test stays decoupled from Battery's internal initial-SOC formula.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        initial_soc = results.battery_soc.iloc[0]
        assert results.battery_soc.max() > initial_soc, (
            f"Expected SOC to rise above observed initial {initial_soc:.3f} kWh; "
            f"max={results.battery_soc.max():.3f}"
        )

    def test_grid_charge_inert_without_tariff(self, night_weather_data):
        """Without tariff_config, grid-charging stays inert (battery_charge == 0 with zero PV).

        Guard/non-regression: pins the 'tariff_config=None → no behaviour change' contract.
        Green before and after the fix (the impl threads config.tariff_config which is None here).
        """
        config_no_tariff = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                max_charge_kw=2.5,
                dispatch_strategy=DispatchStrategyConfig(
                    strategy_type="tou_optimized",
                    peak_hours=[(7, 24)],
                ),
                grid_charging=GridChargeConfig(target_soc_fraction=0.9),
            ),
            tariff_config=None,
            location=Location.bristol(),
        )
        results = simulate_home(
            config_no_tariff,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.battery_charge.sum() == pytest.approx(0.0), (
            "Expected battery_charge == 0: without tariff, grid charging should be inert"
        )
        initial_soc = results.battery_soc.iloc[0]
        assert results.battery_soc.max() <= initial_soc + 1e-9, (
            "Expected SOC to not rise above observed initial SOC without tariff"
        )


# ---------------------------------------------------------------------------
# CR2 step-3: RED tests for per-home grid-charge cost channel
# ---------------------------------------------------------------------------

@pytest.fixture
def economy7_tariff_config() -> TariffConfig:
    """Economy 7 tariff: off-peak 0.09/kWh (00:30-07:30), peak 0.25/kWh."""
    return TariffConfig.economy_7()


@pytest.fixture
def tou_grid_charge_home_config(economy7_tariff_config: TariffConfig) -> HomeConfig:
    """HomeConfig with TOU tariff + grid-charging enabled battery (overnight charging scenario)."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            max_charge_kw=2.5,
            max_discharge_kw=2.5,
            dispatch_strategy=DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(7, 24)],
            ),
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        ),
        tariff_config=economy7_tariff_config,
        location=Location.bristol(),
    )


@pytest.fixture
def flat_tariff_no_gc_home_config() -> HomeConfig:
    """HomeConfig with flat tariff and no grid-charging (H5 invariant base)."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        battery_config=BatteryConfig(capacity_kwh=5.0),  # no grid_charging
        tariff_config=TariffConfig(
            periods=[TariffPeriod(name="flat", rate_per_kwh=0.28, start_time="00:00", end_time="00:00")],
        ),
        location=Location.bristol(),
    )


class TestSimulationResultsGridChargeCost:
    """RED tests for the new SimulationResults.grid_charge_cost field (CR2 step-3a)."""

    def test_grid_charge_cost_field_defaults_to_none(self) -> None:
        """(a-i) SimulationResults.grid_charge_cost defaults to None (back-compat)."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        results = SimulationResults(
            generation=pd.Series([0.0, 0.0, 0.0], index=idx),
            demand=pd.Series([0.0, 0.0, 0.0], index=idx),
            self_consumption=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.0, 0.0, 0.0], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
        )
        assert results.grid_charge_cost is None

    def test_grid_charge_cost_round_trips(self) -> None:
        """(a-ii) SimulationResults accepts and returns a grid_charge_cost Series."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        gc_cost = pd.Series([0.01, 0.02, 0.03], index=idx, name="grid_charge_cost_gbp")
        results = SimulationResults(
            generation=pd.Series([0.0, 0.0, 0.0], index=idx),
            demand=pd.Series([0.0, 0.0, 0.0], index=idx),
            self_consumption=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.0, 0.0, 0.0], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_charge_cost=gc_cost,
        )
        assert results.grid_charge_cost is not None
        pd.testing.assert_series_equal(results.grid_charge_cost, gc_cost)


class TestCalculateSummaryGridChargeCost:
    """RED tests for SummaryStatistics.total_grid_charge_cost_gbp (CR2 step-3b)."""

    def _make_results(
        self, grid_charge_cost: "pd.Series | None" = None
    ) -> SimulationResults:
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        return SimulationResults(
            generation=pd.Series([1.0, 1.0, 1.0], index=idx),
            demand=pd.Series([0.5, 0.5, 0.5], index=idx),
            self_consumption=pd.Series([0.5, 0.5, 0.5], index=idx),
            battery_charge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([2.5, 2.5, 2.5], index=idx),
            grid_import=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_export=pd.Series([0.5, 0.5, 0.5], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_charge_cost=grid_charge_cost,
        )

    def test_total_grid_charge_cost_gbp_zero_when_none(self) -> None:
        """(b-i) total_grid_charge_cost_gbp == 0.0 when grid_charge_cost is None."""
        results = self._make_results(grid_charge_cost=None)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0)

    def test_total_grid_charge_cost_gbp_equals_series_sum(self) -> None:
        """(b-ii) total_grid_charge_cost_gbp == results.grid_charge_cost.sum() in £."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        gc_cost = pd.Series([0.01, 0.02, 0.03], index=idx)
        results = self._make_results(grid_charge_cost=gc_cost)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(gc_cost.sum())


class TestSimulateHomeGridChargeCost:
    """RED tests for simulate_home producing grid_charge_cost (CR2 step-3c/d)."""

    def test_tou_grid_charging_home_produces_nonzero_cost(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_data: pd.DataFrame,
    ) -> None:
        """(c) TOU tariff + grid_charging battery → total_grid_charge_cost_gbp > 0."""
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.grid_charge_cost is not None, (
            "grid_charge_cost should be a Series when tariff_config is set"
        )
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp > 0.0, (
            "With TOU tariff + grid-charging battery + zero PV, the grid-charge cost must be > 0"
        )

    def test_tou_grid_charging_cost_priced_at_offpeak_rate(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_data: pd.DataFrame,
        economy7_tariff_config: TariffConfig,
    ) -> None:
        """(c-ii) grid_charge_cost only occurs at off-peak rate timesteps.

        Verifies the pricing relationship rather than just non-negativity.
        A regression pricing at peak rate (0.25 £/kWh instead of 0.09) or
        multiplying by the wrong rate series would fail this test.
        """
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.grid_charge_cost is not None

        off_peak_rate = 0.09  # £/kWh (Economy 7 off-peak rate)
        rates = results.tariff_rate.to_numpy()
        costs = results.grid_charge_cost.to_numpy()

        # (1) At peak-rate timesteps (rate > off_peak_rate), no grid-charging cost must appear
        # (grid charging is only dispatched during cheap off-peak windows)
        peak_mask = rates > off_peak_rate  # Economy7 peak rate == 0.25, off-peak == 0.09
        np.testing.assert_allclose(
            costs[peak_mask],
            0.0,
            atol=1e-10,
            err_msg="Grid-charging cost must be zero at peak-rate (0.25 £/kWh) timesteps",
        )

        # (2) All non-zero costs must correspond to off-peak rate timesteps
        # (catches: wrong rate series applied, or peak-rate used instead of off-peak)
        nonzero_cost_mask = costs > 0.0
        assert nonzero_cost_mask.any(), (
            "Some grid-charging cost must have been incurred during off-peak window"
        )
        np.testing.assert_allclose(
            rates[nonzero_cost_mask],
            off_peak_rate,
            rtol=1e-9,
            err_msg="All non-zero grid-charging costs must be at the off-peak rate (0.09 £/kWh)",
        )

    def test_grid_charge_cost_numerical_pricing_formula(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_data: pd.DataFrame,
    ) -> None:
        """Per-timestep grid_charge_cost == battery_charge_kWh × rate in a zero-PV scenario.

        In the zero-PV (night-only) scenario battery_charge == grid_charge because no
        PV is available to top up the battery.  This lets us verify the production line
        ``grid_charge_costs = [r.grid_charge * rate …]`` numerically by recomputing the
        expected cost from ``results.battery_charge`` (kW) and ``results.tariff_rate``
        (£/kWh):

            expected[i] = battery_charge_kW[i] / 60 × tariff_rate[i]

        A bug substituting r.grid_import for r.grid_charge (which exceeds battery_charge
        when household demand also draws from the grid), or using the wrong rate series,
        would show up here as a per-timestep mismatch.
        """
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        assert results.grid_charge_cost is not None

        # In zero-PV scenario: PV charge contribution = 0, so battery_charge == grid_charge.
        # results.battery_charge is in kW; dividing by 60 gives kWh/timestep.
        expected_gc_cost = results.battery_charge / 60.0 * results.tariff_rate

        np.testing.assert_allclose(
            results.grid_charge_cost.to_numpy(),
            expected_gc_cost.to_numpy(),
            rtol=1e-9,
            err_msg=(
                "grid_charge_cost per-timestep should equal "
                "battery_charge_kW / 60 × tariff_rate in zero-PV scenario"
            ),
        )

    def test_flat_no_grid_charging_produces_zero_cost(
        self,
        flat_tariff_no_gc_home_config: HomeConfig,
        night_weather_data: pd.DataFrame,
    ) -> None:
        """(d) Flat-rate tariff, no grid_charging → total_grid_charge_cost_gbp == 0.0 (H5)."""
        results = simulate_home(
            flat_tariff_no_gc_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather_data=night_weather_data,
        )
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0), (
            "Without grid_charging, the grid-charge cost must be 0.0 (H5 invariant)"
        )
