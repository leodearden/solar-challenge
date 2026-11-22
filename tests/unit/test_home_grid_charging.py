# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for grid charging a home battery on a time-of-use tariff."""

import dataclasses
from typing import Optional

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import (
    GRID_CHARGE_FORECASTS,
    GridChargeConfig,
    GridChargeForecast,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import PRESET_RATES, TariffConfig, TariffPeriod
from solar_challenge.timebase import HOURS_PER_MINUTE
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._finance_builders import make_sim_results
from tests._same_schedule_tariffs import (
    NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS,
    NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS,
)
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for


@pytest.fixture
def night_weather_data() -> pd.DataFrame:
    """No sun on 21 June, so any battery charge comes from the grid, not excess PV."""
    return sunless_weather("2024-06-21", temp_air=12.0)


class TestSimulateHomeStrategyPathGridCharging:
    """Test grid-charging wiring via the Strategy-pattern dispatch path.

    The Strategy path (else branch in home.simulate_home) is taken when
    BatteryConfig.dispatch_strategy is set, making use_tariff_tou False.
    simulate_timestep on this path receives tariff=config.tariff_config, so
    the full grid-charge chain fires: is_cheap + spread gates pass → battery
    charged from grid.
    """

    @pytest.fixture
    def strategy_grid_charge_config(self):
        """HomeConfig that routes to the Strategy (else) branch and enables grid-charging.

        - BatteryConfig.dispatch_strategy is set → use_tariff_tou = False → else branch.
        - GridChargeConfig(target_soc_fraction=0.9) enables arbitrage charging.
        - Tariff: 0.10 £/kWh overnight (00:00-07:00, off-peak) + 0.30 £/kWh during day
          (07:00-00:00, peak). rt_eff ≈ 0.9506 → is_cheap (0.10 ≤ 0.242, the
          duration-weighted mean (0.10 × 420 + 0.30 × 1020) / 1440) ✓;
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
                dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((7, 24),)),
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

        Without tariff= on the Strategy branch, grid_charge_ctx would be None and
        battery_charge.sum() would be 0.

        Also verifies the split-accounting energy balance of
        docs/prds/tou-grid-charging-battery-arbitrage.md §3.1 closes on the Strategy path:
        generation + grid_import ≈ demand + grid_export + (battery_charge - battery_discharge).
        validate_balance=True already enforces this per-timestep; the explicit series check
        below makes the guarantee visible as a reviewable assertion.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather=weather_for(strategy_grid_charge_config, night_weather_data),
        )
        assert results.battery_charge.sum() > 0, (
            "Expected battery_charge > 0: grid charging should engage via Strategy path "
            "when tariff=config.tariff_config is threaded into simulate_timestep"
        )
        # The split-accounting identity (generation + grid_import == demand + grid_export +
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

        Overnight charging raises SOC toward target 0.9 × capacity; with the tariff
        absent, no charging would occur and SOC would stay at its initial value.

        Uses results.battery_soc.iloc[0] rather than a re-derived constant so the
        test stays decoupled from Battery's internal initial-SOC formula.
        """
        results = simulate_home(
            strategy_grid_charge_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather=weather_for(strategy_grid_charge_config, night_weather_data),
        )
        initial_soc = results.battery_soc.iloc[0]
        assert results.battery_soc.max() > initial_soc, (
            f"Expected SOC to rise above observed initial {initial_soc:.3f} kWh; "
            f"max={results.battery_soc.max():.3f}"
        )

    def test_grid_charging_without_a_tariff_is_refused(self):
        """Without tariff_config there is no cheap period to grid-charge in, so building the home refuses the battery's grid_charging, not left inert."""
        with pytest.raises(ConfigurationError, match="grid_charging"):
            HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
                battery_config=BatteryConfig(
                    capacity_kwh=5.0,
                    max_charge_kw=2.5,
                    dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((7, 24),)),
                    grid_charging=GridChargeConfig(target_soc_fraction=0.9),
                ),
                tariff_config=None,
                location=Location.bristol(),
            )


# ---------------------------------------------------------------------------
# Per-home grid-charge cost channel
# ---------------------------------------------------------------------------

@pytest.fixture
def economy7_tariff_config() -> TariffConfig:
    """Economy 7 tariff at its preset rates: off-peak 00:30-07:30, peak the rest of the day."""
    return TariffConfig.economy_7()


@pytest.fixture
def tou_grid_charge_home_config(economy7_tariff_config: TariffConfig) -> HomeConfig:
    """HomeConfig with TOU tariff + grid-charging enabled battery (overnight charging scenario).

    Its battery dispatches on Economy 7's clock: it grid-charges in the cheap 00:30-07:30 and
    discharges in every other minute. A peak window of its own may not reach a cheap minute.
    """
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            max_charge_kw=2.5,
            max_discharge_kw=2.5,
            dispatch_strategy=TOUOptimizedStrategyConfig(),
            grid_charging=GridChargeConfig(target_soc_fraction=0.9),
        ),
        tariff_config=economy7_tariff_config,
        location=Location.bristol(),
    )


@pytest.fixture
def flat_tariff_no_gc_home_config() -> HomeConfig:
    """HomeConfig with flat tariff and no grid-charging."""
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
    """SimulationResults.grid_charge_cost field: defaults and construction."""

    def test_grid_charge_cost_field_defaults_to_none(self) -> None:
        """SimulationResults.grid_charge_cost defaults to None (back-compat)."""
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
        """SimulationResults accepts and returns a grid_charge_cost Series."""
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
    """calculate_summary_statistics aggregates SummaryStatistics.total_grid_charge_cost_gbp."""

    def _make_results(
        self, grid_charge_cost: pd.Series | None = None
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
        """total_grid_charge_cost_gbp == 0.0 when grid_charge_cost is None."""
        results = self._make_results(grid_charge_cost=None)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0)

    def test_total_grid_charge_cost_gbp_equals_series_sum(self) -> None:
        """total_grid_charge_cost_gbp == results.grid_charge_cost.sum() in £."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        gc_cost = pd.Series([0.01, 0.02, 0.03], index=idx)
        results = self._make_results(grid_charge_cost=gc_cost)
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(gc_cost.sum())


class TestCalculateSummaryGridCharge:
    """calculate_summary totals the energy the battery drew from the grid as SummaryStatistics.total_grid_charge_kwh."""

    def _make_results(self, grid_charge: pd.Series | None = None) -> SimulationResults:
        """Three minutes in which the battery charges only from the grid, so its charge and the grid import each carry grid_charge."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        charged_from_grid = grid_charge if grid_charge is not None else pd.Series([0.0, 0.0, 0.0], index=idx)
        return SimulationResults(
            generation=pd.Series([1.0, 1.0, 1.0], index=idx),
            demand=pd.Series([0.5, 0.5, 0.5], index=idx),
            self_consumption=pd.Series([0.5, 0.5, 0.5], index=idx),
            battery_charge=charged_from_grid,
            battery_discharge=pd.Series([0.0, 0.0, 0.0], index=idx),
            battery_soc=pd.Series([2.5, 2.5, 2.5], index=idx),
            grid_import=charged_from_grid,
            grid_export=pd.Series([0.5, 0.5, 0.5], index=idx),
            import_cost=pd.Series([0.0, 0.0, 0.0], index=idx),
            export_revenue=pd.Series([0.0, 0.0, 0.0], index=idx),
            tariff_rate=pd.Series([0.0, 0.0, 0.0], index=idx),
            grid_charge=grid_charge,
        )

    def test_total_grid_charge_kwh_is_zero_when_grid_charge_is_none(self) -> None:
        """A run without a grid_charge series, as every untariffed run is, drew nothing from the grid."""
        summary = calculate_summary(self._make_results(grid_charge=None))

        assert summary.total_grid_charge_kwh == 0.0

    def test_total_grid_charge_kwh_is_the_grid_charges_per_minute_kwh_summed(self) -> None:
        """1.2 kW, then 0.6 kW, then nothing, each for a minute: 0.02 + 0.01 kWh."""
        idx = pd.date_range("2024-01-01", periods=3, freq="1min")
        grid_charge = pd.Series([1.2, 0.6, 0.0], index=idx)

        summary = calculate_summary(self._make_results(grid_charge=grid_charge))

        assert summary.total_grid_charge_kwh == pytest.approx(0.03)


class TestSummaryStatisticsGridCharge:
    """SummaryStatistics refuses a total_grid_charge_kwh that is not a part of both its battery charge and its grid import."""

    @pytest.fixture
    def summary(self) -> SummaryStatistics:
        """A one-day run's summary, which a test gives the grid charge, battery charge and grid import it checks."""
        return calculate_summary(make_sim_results(days=1))

    @pytest.mark.parametrize(
        ("grid_charge_kwh", "battery_charge_kwh", "grid_import_kwh"),
        [
            pytest.param(2.5, 2.0, 9.75, id="more-than-the-battery-drew"),
            pytest.param(2.0, 2.0, 1.5, id="more-than-the-grid-supplied"),
            pytest.param(-0.5, 2.0, 9.75, id="negative"),
            pytest.param(float("nan"), 2.0, 9.75, id="not-a-number"),
        ],
    )
    def test_a_grid_charge_outside_the_charge_or_the_import_raises_naming_the_three_totals(
        self, summary: SummaryStatistics, grid_charge_kwh: float, battery_charge_kwh: float, grid_import_kwh: float
    ) -> None:
        """The error states the invariant and the totals that break it."""
        with pytest.raises(ValueError) as refused:
            dataclasses.replace(
                summary,
                total_grid_charge_kwh=grid_charge_kwh,
                total_battery_charge_kwh=battery_charge_kwh,
                total_grid_import_kwh=grid_import_kwh,
            )

        message = str(refused.value)
        assert "a part of both total_battery_charge_kwh and total_grid_import_kwh" in message
        assert f"total_grid_charge_kwh={grid_charge_kwh!r}" in message
        assert f"total_battery_charge_kwh={battery_charge_kwh!r}" in message
        assert f"total_grid_import_kwh={grid_import_kwh!r}" in message

    def test_a_grid_charge_that_is_all_of_the_charge_and_all_of_the_import_is_accepted(
        self, summary: SummaryStatistics
    ) -> None:
        """A sunless night on which the grid supplied only the battery: its grid charge is the whole of both."""
        night = dataclasses.replace(
            summary, total_grid_charge_kwh=2.0, total_battery_charge_kwh=2.0, total_grid_import_kwh=2.0
        )

        assert night.total_grid_charge_kwh == 2.0


class TestSimulateHomeGridChargeCost:
    """simulate_home produces grid_charge_cost for time-of-use grid-charging homes."""

    def test_tou_grid_charging_home_produces_nonzero_cost(
        self,
        tou_grid_charge_home_config: HomeConfig,
        night_weather_data: pd.DataFrame,
    ) -> None:
        """TOU tariff + grid_charging battery → total_grid_charge_cost_gbp > 0."""
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather=weather_for(tou_grid_charge_home_config, night_weather_data),
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
        """grid_charge_cost only occurs at off-peak rate timesteps.

        Verifies the pricing relationship rather than just non-negativity.
        A regression pricing at the peak rate instead of the off-peak rate, or
        multiplying by the wrong rate series, would fail this test.
        """
        results = simulate_home(
            tou_grid_charge_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather=weather_for(tou_grid_charge_home_config, night_weather_data),
        )
        assert results.grid_charge_cost is not None

        off_peak_rate = PRESET_RATES["economy_7"].off_peak_rate
        rates = results.tariff_rate.to_numpy()
        costs = results.grid_charge_cost.to_numpy()

        # (1) At peak-rate timesteps (rate > off_peak_rate), no grid-charging cost must appear
        # (grid charging is only dispatched during cheap off-peak windows)
        peak_mask = rates > off_peak_rate
        np.testing.assert_allclose(
            costs[peak_mask],
            0.0,
            atol=1e-10,
            err_msg="Grid-charging cost must be zero at peak-rate timesteps",
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
            err_msg="All non-zero grid-charging costs must be at the off-peak rate",
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
            weather=weather_for(tou_grid_charge_home_config, night_weather_data),
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
        """Flat-rate tariff, no grid_charging → total_grid_charge_cost_gbp == 0.0."""
        results = simulate_home(
            flat_tariff_no_gc_home_config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            validate_balance=True,
            weather=weather_for(flat_tariff_no_gc_home_config, night_weather_data),
        )
        summary = calculate_summary(results)
        assert summary.total_grid_charge_cost_gbp == pytest.approx(0.0), (
            "Without grid_charging, the grid-charge cost must be 0.0"
        )


class TestSimulateHomeGridCharge:
    """simulate_home records the power the battery stores from the grid as grid_charge on every tariffed run."""

    @pytest.fixture
    def arbitrage_home_grid_charging_to_70_percent(self) -> HomeConfig:
        """The arbitrage home, grid charging to 70% instead of the scenario's 90%, so a sunny day leaves room for PV."""
        home = bristol_arbitrage_home()
        battery = home.battery_config
        assert battery is not None and battery.grid_charging is not None
        grid_charging = dataclasses.replace(battery.grid_charging, target_soc_fraction=0.7)
        return dataclasses.replace(home, battery_config=dataclasses.replace(battery, grid_charging=grid_charging))

    def test_grid_charge_is_only_the_part_of_the_battery_charge_drawn_from_the_grid(
        self, arbitrage_home_grid_charging_to_70_percent: HomeConfig
    ) -> None:
        """On a sunny Economy 7 day the battery charges from the grid and from PV, and grid_charge is the grid's part.

        It is the power the grid-charge cost is priced on, and is part of both the battery charge and the grid import.
        """
        results = simulate_home(
            arbitrage_home_grid_charging_to_70_percent,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather=weather_for(arbitrage_home_grid_charging_to_70_percent, synthetic_june_weather("2024-06-21")),
        )

        assert results.grid_charge is not None
        assert results.grid_charge_cost is not None
        assert 0 < results.grid_charge.sum() < results.battery_charge.sum()
        pd.testing.assert_series_equal(
            results.grid_charge * HOURS_PER_MINUTE * results.tariff_rate,
            results.grid_charge_cost,
            check_names=False,
        )
        assert (results.grid_charge <= results.battery_charge).all()
        assert (results.grid_charge <= results.grid_import).all()

    def test_an_untariffed_run_has_no_grid_charge_series(self, night_weather_data: pd.DataFrame) -> None:
        """A run without a tariff cannot grid charge, and has no grid_charge series, as it has no grid_charge_cost.

        Its home is the arbitrage home without the settings a tariff is needed for: its tariff,
        its battery's grid_charging and its tou_optimized dispatch.
        """
        arbitrage = bristol_arbitrage_home()
        assert arbitrage.battery_config is not None
        home = dataclasses.replace(
            arbitrage,
            battery_config=dataclasses.replace(arbitrage.battery_config, grid_charging=None),
            tariff_config=None,
            dispatch_strategy="greedy",
        )
        results = simulate_home(
            home,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather=weather_for(home, night_weather_data),
        )

        assert results.grid_charge_cost is None
        assert results.grid_charge is None


class TestSimulateHomeDispatchesOnTheTariffSchedule:
    """The arbitrage home on one schedule imports the same energy at the same cost, however the schedule's periods are listed.

    The offline stand-in for `home run` on scenarios/bristol-arbitrage.yaml with that tariff
    (docs/prds/tariff-coverage-classifier-presets.md §9 row 3).
    """

    @staticmethod
    def _winter_day_summary(tariff: TariffConfig) -> SummaryStatistics:
        home = dataclasses.replace(bristol_arbitrage_home(), tariff_config=tariff)
        results = simulate_home(
            home,
            start_date=pd.Timestamp("2024-01-10"),
            end_date=pd.Timestamp("2024-01-10"),
            weather=weather_for(home, sunless_weather("2024-01-10", temp_air=5.0)),
        )
        return calculate_summary(results)

    def test_a_schedule_as_four_or_five_periods_imports_the_same_at_the_same_cost(self) -> None:
        four = self._winter_day_summary(NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS)
        five = self._winter_day_summary(NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS)

        assert (four.total_grid_import_kwh, four.total_import_cost_gbp) == (
            five.total_grid_import_kwh,
            five.total_import_cost_gbp,
        )


# ---------------------------------------------------------------------------
# The forecast that sizes a home's grid charge
# ---------------------------------------------------------------------------

_FORECAST_DAYS = 16
_FIRST_FORECAST_DAY = pd.Timestamp("2024-06-01")
_DAY_15 = pd.Timestamp("2024-06-15", tz="Europe/London")
"""Local midnight of the run's 15th day, whose cheap window is the first with 14 earlier ones to read."""


def _forecast_home(grid_charging: Optional[GridChargeConfig]) -> HomeConfig:
    """An Economy 7 home with 4 kW of PV, a deterministic 3,400 kWh load and a 5 kWh battery dispatched on the tariff's clock, grid-charging as grid_charging says."""
    return HomeConfig(
        pv_config=PVConfig.default_4kw(),
        load_config=LoadConfig(3400.0, seed=42, use_stochastic=False),
        battery_config=BatteryConfig(5.0, grid_charging=grid_charging),
        tariff_config=TariffConfig.economy_7(),
        dispatch_strategy="tou_optimized",
    )


def _clear_days(home: HomeConfig, days: int = _FORECAST_DAYS, **simulate: object) -> SimulationResults:
    """home simulated over its first days of clear June days, from _FIRST_FORECAST_DAY."""
    weather = synthetic_june_weather(_FIRST_FORECAST_DAY, irradiance_scale_per_day=(1.0,) * days)
    last_day = _FIRST_FORECAST_DAY + pd.Timedelta(days=days - 1)
    return simulate_home(home, _FIRST_FORECAST_DAY, last_day, weather=weather_for(home, weather), **simulate)


def _sized_by(forecast: GridChargeForecast) -> HomeConfig:
    """The forecast home grid-charging to 90% in each cheap period, its fill sized by forecast."""
    return _forecast_home(GridChargeConfig(0.9, forecast=forecast))


@pytest.fixture(scope="module")
def pv_blind_run() -> SimulationResults:
    """The forecast home over 16 clear June days, each cheap period filling to the target."""
    return _clear_days(_sized_by("pv_blind"))


@pytest.fixture(scope="module")
def trailing_run() -> SimulationResults:
    """The forecast home over 16 clear June days, each cheap period's fill sized by the 14 days before it."""
    return _clear_days(_sized_by("trailing_14_days"))


@pytest.mark.filterwarnings("ignore:tariff_config is set but seg_tariff is None:UserWarning")
class TestGridChargeForecast:
    """simulate_home sizes each cheap period's grid charge by the battery's GridChargeConfig.forecast, and its results record that forecast."""

    def test_trailing_14_days_fills_as_pv_blind_does_until_it_has_14_days_to_read(
        self, pv_blind_run: SimulationResults, trailing_run: SimulationResults
    ) -> None:
        """No cheap window of the first 14 days has 14 earlier ones, so each fills to the target, minute for minute."""
        first_14_days = pv_blind_run.generation.index < _DAY_15

        pd.testing.assert_frame_equal(
            trailing_run.to_dataframe()[first_14_days], pv_blind_run.to_dataframe()[first_14_days]
        )

    def test_after_14_clear_days_trailing_14_days_grid_charges_less_and_pays_less_for_its_import(
        self, pv_blind_run: SimulationResults, trailing_run: SimulationResults
    ) -> None:
        """Fourteen clear days say day 15's and 16's PV fills the battery, so the fill buys less charge PV would strand."""
        assert pv_blind_run.grid_charge is not None and trailing_run.grid_charge is not None
        assert trailing_run.grid_charge[_DAY_15:].sum() < pv_blind_run.grid_charge[_DAY_15:].sum()
        assert trailing_run.import_cost[_DAY_15:].sum() < pv_blind_run.import_cost[_DAY_15:].sum()

    def test_a_strategy_given_to_simulate_home_is_offered_the_same_ceilings(
        self, trailing_run: SimulationResults
    ) -> None:
        """The battery's own TOU dispatch, given as strategy, is sized by the battery's forecast as the one the home selects is."""
        given = _clear_days(_sized_by("trailing_14_days"), strategy=TOUOptimizedStrategy(tariff=TariffConfig.economy_7()))

        pd.testing.assert_frame_equal(given.to_dataframe(), trailing_run.to_dataframe())

    @pytest.mark.parametrize("forecast", GRID_CHARGE_FORECASTS)
    def test_the_results_and_their_summary_record_the_forecast_that_sized_the_grid_charge(
        self, forecast: GridChargeForecast
    ) -> None:
        results = _clear_days(_sized_by(forecast), days=1)

        assert results.grid_charge_forecast == forecast
        assert calculate_summary(results).grid_charge_forecast == forecast

    @pytest.mark.parametrize(
        "home",
        [
            pytest.param(_forecast_home(None), id="battery-without-grid-charging"),
            pytest.param(dataclasses.replace(_forecast_home(None), battery_config=None), id="no-battery"),
        ],
    )
    def test_a_run_that_does_not_grid_charge_records_no_forecast(self, home: HomeConfig) -> None:
        results = _clear_days(home, days=1)

        assert results.grid_charge_forecast is None
        assert calculate_summary(results).grid_charge_forecast is None

    def test_from_dataframe_keeps_the_forecast_it_is_given(self, trailing_run: SimulationResults) -> None:
        rebuilt = SimulationResults.from_dataframe(
            trailing_run.to_dataframe(),
            strategy_name=trailing_run.strategy_name,
            grid_charge_forecast=trailing_run.grid_charge_forecast,
        )

        assert rebuilt.grid_charge_forecast == "trailing_14_days"

    def test_from_dataframe_given_no_forecast_records_none(self, trailing_run: SimulationResults) -> None:
        rebuilt = SimulationResults.from_dataframe(trailing_run.to_dataframe(), strategy_name=trailing_run.strategy_name)

        assert rebuilt.grid_charge_forecast is None
