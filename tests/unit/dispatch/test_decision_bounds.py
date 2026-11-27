# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 8-12, and docs/prds/event-dispatch-and-battery-sizing.md §9 B2: a decision's powers, and a step's generation and demand, are finite and at least 0, and simulate_timestep refuses a decision that asks for more than its step allows, its export included, before the battery moves; no built-in strategy's decision does."""

import dataclasses
import functools
import math
import re
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    PeakShavingStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    StepLimits,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import EnergyFlowResult, simulate_timestep
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.tariff import TariffConfig
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._fixed_decision_strategy import FixedDecisionStrategy
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for
from tests._ten_kwh_battery import ten_kwh_battery
from tests._tou_on_the_tariff_s_clock import on_the_tariff_s_clock

NOT_FINITE_AND_AT_LEAST_0 = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="-inf"),
    pytest.param(-1.0, id="negative"),
]

STEP_POWERS = [
    pytest.param("generation_kw", "Generation", id="generation_kw"),
    pytest.param("demand_kw", "Demand", id="demand_kw"),
]

_E7 = TariffConfig.economy_7()

# simulate_timestep under self-consumption dispatch, and under TOU dispatch on Economy 7's clock at its 18:00 peak rate.
DISPATCHES = [
    pytest.param(simulate_timestep, id="self_consumption"),
    pytest.param(
        functools.partial(
            simulate_timestep,
            timestamp=pd.Timestamp("2024-01-01 18:00"),
            **on_the_tariff_s_clock(_E7),
        ),
        id="tou_on_the_tariff_s_clock-peak",
    ),
]


class TestADecisionRefusesAPowerThatIsNotFiniteAndAtLeast0:
    """§9 row 11, the decision's half: each of a decision's four powers is finite and at least 0, whatever its step."""

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize("field", ["charge_kw", "discharge_kw", "grid_charge_kw", "export_kw"])
    def test_the_decision_refuses_the_power_naming_its_field_and_value(self, field: str, value: float) -> None:
        powers = {"charge_kw": 0.0, "discharge_kw": 0.0, "grid_charge_kw": 0.0, "export_kw": 0.0, field: value}
        refusal = f"{field} must be non-negative and finite, got {value!r} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            DispatchDecision(**powers)

    def test_finite_powers_at_least_0_construct_and_the_exclusivity_refusals_still_fire(self) -> None:
        assert dataclasses.astuple(DispatchDecision(0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0, 0.0)
        assert dataclasses.astuple(DispatchDecision(1.5, 0.0, 2.0)) == (1.5, 0.0, 2.0, 0.0)
        assert dataclasses.astuple(DispatchDecision(0.0, 1.0, 0.0, 2.0)) == (0.0, 1.0, 0.0, 2.0)
        with pytest.raises(ValueError, match="^Cannot charge and discharge simultaneously"):
            DispatchDecision(1.0, 1.0, 0.0)
        with pytest.raises(ValueError, match="^Cannot grid-charge and discharge simultaneously"):
            DispatchDecision(0.0, 1.0, 1.0)

    def test_an_export_alongside_a_pv_charge_is_refused(self) -> None:
        refusal = "Cannot charge and export simultaneously: charge=1.0 kW, export=1.0 kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            DispatchDecision(1.0, 0.0, 0.0, 1.0)

    def test_an_export_alongside_a_grid_charge_is_refused(self) -> None:
        refusal = "Cannot grid-charge and export simultaneously: grid_charge=1.0 kW, export=1.0 kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            DispatchDecision(0.0, 0.0, 1.0, 1.0)


class TestTheStepRefusesAPowerThatIsNotFiniteAndAtLeast0:
    """§9 row 11, the input half: simulate_timestep refuses, under either dispatch, a generation or demand that is not finite and at least 0, naming it, before any strategy decides or any battery moves."""

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    @pytest.mark.parametrize("step", DISPATCHES)
    def test_a_step_without_a_battery_refuses_the_power(
        self, step: Callable[..., EnergyFlowResult], power: str, quantity: str, value: float
    ) -> None:
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            step(**{"generation_kw": 1.0, "demand_kw": 1.0, power: value}, battery=None, timestep_minutes=1.0)

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    @pytest.mark.parametrize("step", DISPATCHES)
    def test_a_step_with_a_battery_refuses_the_power_and_leaves_its_soc_unchanged(
        self, step: Callable[..., EnergyFlowResult], power: str, quantity: str, value: float
    ) -> None:
        battery = Battery(BatteryConfig.default_5kwh())
        soc_kwh = battery.soc_kwh
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            step(**{"generation_kw": 1.0, "demand_kw": 1.0, power: value}, battery=battery, timestep_minutes=1.0)
        assert battery.soc_kwh == soc_kwh

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    def test_simulate_timestep_refuses_the_power_before_a_strategy_of_the_consumer_s_own_decides(
        self, power: str, quantity: str, value: float
    ) -> None:
        """Unlike the built-in strategies, FixedDecisionStrategy checks none of its inputs, so the step's own check is all that refuses the power."""
        battery = Battery(BatteryConfig.default_5kwh())
        soc_kwh = battery.soc_kwh
        strategy = FixedDecisionStrategy(DispatchDecision(0.0, 0.0))
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            simulate_timestep(
                **{"generation_kw": 1.0, "demand_kw": 1.0, power: value},
                battery=battery,
                timestep_minutes=1.0,
                strategy=strategy,
            )
        assert strategy.calls == []
        assert battery.soc_kwh == soc_kwh


_EXPORT_BOUND = (
    "the discharge limit's headroom after the step's shortfall, within any site export limit less the step's PV excess"
)
"""What require_admissible calls the bound of export_kw."""


def _refusal(*breaches: str) -> str:
    """simulate_timestep's refusal of a decision by the strategy named 'over_limit' that makes *breaches*, given in field order."""
    return "Dispatch strategy 'over_limit' decided more than the step allows: " + "; ".join(breaches)


def _hour_under(
    decision: DispatchDecision, *, generation_kw: float, demand_kw: float, battery: Battery
) -> EnergyFlowResult:
    """Step one hour, so a power in kW is the same energy in kWh, on *battery* under a strategy named 'over_limit' that returns *decision*."""
    return simulate_timestep(
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery=battery,
        timestep_minutes=60,
        strategy=FixedDecisionStrategy(decision, name="over_limit"),
    )


class TestAStepRefusesADecisionBeyondItsLimitsBeforeTheBatteryMoves:
    """§9 rows 8-10: simulate_timestep refuses a decision that asks for more than its step allows, naming the strategy and each breach, and leaves the battery's SOC as it was."""

    def test_a_grid_charge_above_the_headroom_the_pv_charge_leaves_is_refused(self) -> None:
        """§9 row 8: a 5 kW PV charge takes all of the battery's 2.5 kW charge limit, leaving no headroom for the 5 kW grid charge."""
        battery = ten_kwh_battery(1.0)
        refusal = _refusal("grid_charge_kw=5.0 kW is above 0.0 kW, the charge limit's headroom after charge_kw")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(5.0, 0.0, 5.0), generation_kw=10.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0

    def test_a_pv_charge_above_the_excess_is_refused(self) -> None:
        """§9 row 9: with no PV the step has no excess to charge from."""
        battery = ten_kwh_battery(1.0)
        refusal = _refusal("charge_kw=2.5 kW is above 0.0 kW, the step's PV excess")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(2.5, 0.0, 0.0), generation_kw=0.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0

    def test_a_discharge_above_the_shortfall_is_refused(self) -> None:
        """§9 row 10: 2.5 kW of discharge against a 1.0 kW shortfall."""
        battery = ten_kwh_battery(5.0)
        refusal = _refusal("discharge_kw=2.5 kW is above 1.0 kW, the step's shortfall")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(0.0, 2.5, 0.0), generation_kw=0.0, demand_kw=1.0, battery=battery)
        assert battery.soc_kwh == 5.0

    def test_every_breach_of_one_decision_is_named_in_one_refusal(self) -> None:
        battery = ten_kwh_battery(1.0)
        refusal = _refusal(
            "charge_kw=2.5 kW is above 0.0 kW, the step's PV excess",
            "grid_charge_kw=2.5 kW is above 0.0 kW, the charge limit's headroom after charge_kw",
        )
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(2.5, 0.0, 2.5), generation_kw=0.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0


class TestAStepRefusesAnExportBeyondItsLimitBeforeTheBatteryMoves:
    """docs/prds/event-dispatch-and-battery-sizing.md §9 B2: simulate_timestep refuses an export_kw above the headroom the battery's 2.5 kW discharge limit leaves after the step's shortfall, naming the strategy, the field, its value and its limit, and leaves the battery's SOC as it was."""

    def test_an_export_above_the_headroom_the_shortfall_leaves_is_refused(self) -> None:
        battery = ten_kwh_battery(5.0)
        refusal = _refusal(f"export_kw=2.0 kW is above 1.5 kW, {_EXPORT_BOUND}")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(0.0, 1.0, 0.0, 2.0), generation_kw=0.0, demand_kw=1.0, battery=battery)
        assert battery.soc_kwh == 5.0

    def test_an_export_on_a_step_whose_shortfall_takes_the_whole_discharge_limit_is_refused(self) -> None:
        battery = ten_kwh_battery(5.0)
        refusal = _refusal(f"export_kw=0.5 kW is above 0.0 kW, {_EXPORT_BOUND}")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(0.0, 2.5, 0.0, 0.5), generation_kw=0.0, demand_kw=3.0, battery=battery)
        assert battery.soc_kwh == 5.0

    def test_an_export_and_a_discharge_beyond_their_limits_are_both_named_in_field_order(self) -> None:
        battery = ten_kwh_battery(5.0)
        refusal = _refusal(
            "discharge_kw=2.0 kW is above 1.0 kW, the step's shortfall",
            f"export_kw=2.0 kW is above 1.5 kW, {_EXPORT_BOUND}",
        )
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(0.0, 2.0, 0.0, 2.0), generation_kw=0.0, demand_kw=1.0, battery=battery)
        assert battery.soc_kwh == 5.0


class TestAStepAdmitsADecisionWithinItsLimits:
    """A decision at its step's limits runs, and so does a PV charge above the battery's charge limit, an offer the battery clamps."""

    def test_a_decision_at_both_of_its_charge_limits_runs(self) -> None:
        """1.0 kW of PV charge takes the whole excess, and 1.5 kW of grid charge the whole headroom it leaves of 2.5 kW."""
        battery = ten_kwh_battery(1.0)
        _hour_under(DispatchDecision(1.0, 0.0, 1.5), generation_kw=1.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == pytest.approx(1.0 + (1.0 + 1.5) * battery.charge_efficiency)

    def test_a_pv_charge_above_the_charge_limit_runs_at_the_limit(self) -> None:
        battery = ten_kwh_battery(1.0)
        _hour_under(DispatchDecision(5.0, 0.0, 0.0), generation_kw=10.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == pytest.approx(1.0 + battery.max_charge_kw * 1.0 * battery.charge_efficiency)


_MAX_CHARGE_KW = 2.5
_MAX_DISCHARGE_KW = 2.5

# Task 1362's pair: two powers an ulp apart, whose energies over a minute are equal.
_POWER_KW = 3.9243814029178457
_AN_ULP_ABOVE_KW = math.nextafter(_POWER_KW, math.inf)


class _Step(NamedTuple):
    """A step's generation and demand, the PV excess and shortfall they leave, and the export the shortfall leaves room for under a 2.5 kW discharge limit, all in kW."""

    generation_kw: float
    demand_kw: float
    excess_kw: float
    shortfall_kw: float
    max_export_kw: float


STEPS = [
    pytest.param(_Step(3.0, 1.0, excess_kw=2.0, shortfall_kw=0.0, max_export_kw=2.5), id="excess"),
    pytest.param(_Step(1.0, 3.0, excess_kw=0.0, shortfall_kw=2.0, max_export_kw=0.5), id="shortfall"),
    pytest.param(_Step(1.5, 1.5, excess_kw=0.0, shortfall_kw=0.0, max_export_kw=2.5), id="balanced"),
    pytest.param(
        _Step(
            _POWER_KW,
            _AN_ULP_ABOVE_KW,
            excess_kw=0.0,
            shortfall_kw=4.440892098500626e-16,
            max_export_kw=2.4999999999999996,
        ),
        id="short-by-an-ulp",
    ),
    pytest.param(
        _Step(_AN_ULP_ABOVE_KW, _POWER_KW, excess_kw=4.440892098500626e-16, shortfall_kw=0.0, max_export_kw=2.5),
        id="over-by-an-ulp",
    ),
    pytest.param(
        _Step(0.1 + 0.2, 0.3, excess_kw=5.551115123125783e-17, shortfall_kw=0.0, max_export_kw=2.5),
        id="0.1+0.2-over-0.3",
    ),
    pytest.param(_Step(0.0, 2.0, excess_kw=0.0, shortfall_kw=2.0, max_export_kw=0.5), id="no-pv"),
    pytest.param(_Step(2.0, 0.0, excess_kw=2.0, shortfall_kw=0.0, max_export_kw=2.5), id="no-demand"),
    pytest.param(
        _Step(0.0, 3.0, excess_kw=0.0, shortfall_kw=3.0, max_export_kw=0.0), id="shortfall-beyond-the-discharge-limit"
    ),
]


class TestTheLimitsForAStep:
    """StepLimits.for_step: a step's PV excess and its shortfall are each the difference of its powers in kW, or 0, even an ulp's difference, its charge limit is the battery's, and its export limit is the battery's discharge limit less the shortfall, or 0."""

    @pytest.mark.parametrize("step", STEPS)
    def test_the_limits_are_the_step_s_excess_shortfall_charge_limit_and_export_limit(self, step: _Step) -> None:
        assert StepLimits.for_step(
            step.generation_kw, step.demand_kw, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW
        ) == StepLimits(
            excess_kw=step.excess_kw,
            shortfall_kw=step.shortfall_kw,
            max_charge_kw=_MAX_CHARGE_KW,
            max_export_kw=step.max_export_kw,
        )

    @pytest.mark.parametrize("step", STEPS)
    def test_with_no_site_export_limit_the_limits_are_those_of_the_battery_alone(self, step: _Step) -> None:
        assert StepLimits.for_step(
            step.generation_kw,
            step.demand_kw,
            max_charge_kw=_MAX_CHARGE_KW,
            max_discharge_kw=_MAX_DISCHARGE_KW,
            site_export_limit_kw=None,
        ) == StepLimits.for_step(
            step.generation_kw, step.demand_kw, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW
        )


class TestTheLimitsForAStepUnderASiteExportLimit:
    """docs/prds/event-dispatch-and-battery-sizing.md §5.4: a site export limit caps the export limit at the site limit less the step's PV excess, or 0, under the 2.5 kW discharge limit's headroom."""

    @pytest.mark.parametrize(
        ("generation_kw", "demand_kw", "site_export_limit_kw", "max_export_kw"),
        [
            pytest.param(0.0, 1.0, 1.0, 1.0, id="shortfall-step-limit-below-the-headroom"),
            pytest.param(3.0, 1.0, 3.0, 1.0, id="excess-step-limit-above-the-excess"),
            pytest.param(4.0, 1.0, 3.0, 0.0, id="excess-at-the-limit"),
            pytest.param(5.0, 1.0, 3.0, 0.0, id="excess-above-the-limit"),
            pytest.param(0.0, 1.0, 0.0, 0.0, id="zero-limit"),
            pytest.param(0.0, 1.0, 10.0, 1.5, id="shortfall-step-limit-above-the-headroom"),
            pytest.param(3.0, 1.0, 10.0, 2.5, id="excess-step-limit-above-excess-plus-the-headroom"),
        ],
    )
    def test_the_export_limit_is_the_least_of_the_two_headrooms(
        self, generation_kw: float, demand_kw: float, site_export_limit_kw: float, max_export_kw: float
    ) -> None:
        limits = StepLimits.for_step(
            generation_kw,
            demand_kw,
            max_charge_kw=_MAX_CHARGE_KW,
            max_discharge_kw=_MAX_DISCHARGE_KW,
            site_export_limit_kw=site_export_limit_kw,
        )

        assert limits == dataclasses.replace(
            StepLimits.for_step(
                generation_kw, demand_kw, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW
            ),
            max_export_kw=max_export_kw,
        )

    def test_an_export_above_the_site_reduced_limit_is_refused_naming_it_its_value_and_the_limit(self) -> None:
        limits = StepLimits.for_step(
            3.0, 1.0, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW, site_export_limit_kw=3.0
        )
        refusal = _refusal(f"export_kw=1.5 kW is above 1.0 kW, {_EXPORT_BOUND}")

        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            limits.require_admissible(DispatchDecision(0.0, 0.0, 0.0, 1.5), "over_limit")


def _on_2024_01_15_at(hour: int) -> datetime:
    """*hour* o'clock on 2024-01-15, on London's wall clock."""
    return datetime(2024, 1, 15, hour, tzinfo=ZoneInfo("Europe/London"))


def _scheduled_in(window: ChargeWindow) -> ScheduledChargeStrategy:
    """A strategy that *window* decides while it is open, on London's wall clock, and self-consumption decides otherwise."""
    return ScheduledChargeStrategy(SelfConsumptionStrategy(), (window,), ZoneInfo("Europe/London"))


_CHARGE_WINDOW_01_TO_05 = ChargeWindow(
    days="daily",
    start=time(1, 0),
    duration=timedelta(hours=4),
    target_soc_fraction=0.8,
    allow_discharge=False,
)
_DISCHARGE_WINDOW_17_TO_19 = ChargeWindow(
    days="daily",
    start=time(17, 0),
    duration=timedelta(hours=2),
    target_soc_fraction=0.3,
    allow_discharge=True,
)

# Each built-in strategy, at a moment of each of its kinds of decision.
BUILT_IN_DECIDERS = [
    pytest.param(SelfConsumptionStrategy(), _on_2024_01_15_at(12), id="self_consumption"),
    pytest.param(TOUOptimizedStrategy([(16, 20)]), _on_2024_01_15_at(18), id="tou_optimized-peak"),
    pytest.param(TOUOptimizedStrategy([(16, 20)]), _on_2024_01_15_at(3), id="tou_optimized-off_peak"),
    pytest.param(PeakShavingStrategy(0.25), _on_2024_01_15_at(18), id="peak_shaving"),
    pytest.param(
        _scheduled_in(_DISCHARGE_WINDOW_17_TO_19), _on_2024_01_15_at(18), id="scheduled_charge-discharge_window"
    ),
    pytest.param(_scheduled_in(_CHARGE_WINDOW_01_TO_05), _on_2024_01_15_at(3), id="scheduled_charge-charge_window"),
]

GRID_CHARGE_CONTEXTS = [
    pytest.param(None, id="no_grid_charging"),
    pytest.param(
        GridChargeContext(
            current_rate=0.1,
            peak_rate=0.3,
            is_cheap_period=True,
            target_soc_kwh=4.5,
            max_charge_kw=_MAX_CHARGE_KW,
            round_trip_efficiency=0.95,
            charge_efficiency=0.975,
        ),
        id="cheap_period",
    ),
]


def _decision(
    strategy: DispatchStrategy,
    timestamp: datetime,
    generation_kw: float,
    demand_kw: float,
    grid_charge_ctx: Optional[GridChargeContext] = None,
) -> DispatchDecision:
    """*strategy*'s decision at *timestamp* for a minute of *generation_kw* and *demand_kw*, with a 5 kWh battery at 2.5 kWh."""
    return strategy.decide_action(
        timestamp=timestamp,
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery_soc_kwh=2.5,
        battery_capacity_kwh=5.0,
        timestep_minutes=1.0,
        grid_charge_ctx=grid_charge_ctx,
    )


class TestEveryBuiltInDecisionIsWithinTheLimitsForItsStep:
    """§9 row 12, a step at a time: each built-in strategy's decision is within StepLimits.for_step's limits for its step, even where its powers are an ulp apart.

    At 2.5 kWh of 5.0, the battery is above the discharge window's target, so that window discharges on a shortfall,
    and below the charge window's, so that window charges from the grid.
    """

    @pytest.mark.parametrize("grid_charge_ctx", GRID_CHARGE_CONTEXTS)
    @pytest.mark.parametrize(("strategy", "timestamp"), BUILT_IN_DECIDERS)
    @pytest.mark.parametrize("step", STEPS)
    def test_the_decision_passes_the_limits_for_its_step(
        self,
        step: _Step,
        strategy: DispatchStrategy,
        timestamp: datetime,
        grid_charge_ctx: Optional[GridChargeContext],
    ) -> None:
        decision = _decision(strategy, timestamp, step.generation_kw, step.demand_kw, grid_charge_ctx)
        StepLimits.for_step(
            step.generation_kw, step.demand_kw, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW
        ).require_admissible(decision, strategy.name)
        assert decision.export_kw == 0.0

    @pytest.mark.parametrize("step", STEPS)
    def test_self_consumption_asks_for_exactly_the_step_s_excess_or_shortfall(self, step: _Step) -> None:
        limits = StepLimits.for_step(
            step.generation_kw, step.demand_kw, max_charge_kw=_MAX_CHARGE_KW, max_discharge_kw=_MAX_DISCHARGE_KW
        )
        decision = _decision(SelfConsumptionStrategy(), _on_2024_01_15_at(12), step.generation_kw, step.demand_kw)
        assert decision == DispatchDecision(charge_kw=limits.excess_kw, discharge_kw=limits.shortfall_kw)


BUILT_IN_STRATEGIES: dict[str, DispatchStrategy] = {
    "self_consumption": SelfConsumptionStrategy(),
    "tou_optimized": TOUOptimizedStrategy([(16, 20)]),
    # Below the home's peak demand on each day here, so the strategy discharges.
    "peak_shaving": PeakShavingStrategy(0.25),
    "scheduled_charge": ScheduledChargeStrategy(
        TOUOptimizedStrategy([(16, 20)]),
        (_CHARGE_WINDOW_01_TO_05, _DISCHARGE_WINDOW_17_TO_19),
        ZoneInfo("Europe/London"),
    ),
}

# Every built-in strategy but self-consumption charges from the grid toward the target its battery's grid_charging
# sets. Self-consumption ignores grid_charge_ctx, so simulate_home refuses it on a battery that sets grid_charging,
# and it runs only the runs without one.
GRID_CHARGING_STRATEGIES = ["tou_optimized", "peak_shaving", "scheduled_charge"]

_SCENARIO_HOME = bristol_arbitrage_home()
_TWO_CLEAR_JUNE_DAYS = synthetic_june_weather("2024-06-20", (1.0, 1.0))
_DAYS = [
    (
        "2024-01-15-sunless-scenario_economy_7",
        _SCENARIO_HOME,
        sunless_weather("2024-01-15", temp_air=5.0),
        "2024-01-15",
        "2024-01-15",
    ),
    (
        "2024-06-20_to_21-clear-economy_7",
        dataclasses.replace(_SCENARIO_HOME, tariff_config=TariffConfig.economy_7()),
        _TWO_CLEAR_JUNE_DAYS,
        "2024-06-20",
        "2024-06-21",
    ),
    (
        "2024-06-20_to_21-clear-economy_10",
        dataclasses.replace(_SCENARIO_HOME, tariff_config=TariffConfig.economy_10()),
        _TWO_CLEAR_JUNE_DAYS,
        "2024-06-20",
        "2024-06-21",
    ),
]


def _without_grid_charging(home: HomeConfig) -> HomeConfig:
    """*home* with its battery's grid_charging replaced by None."""
    assert home.battery_config is not None
    return dataclasses.replace(home, battery_config=dataclasses.replace(home.battery_config, grid_charging=None))


# Each day's home as _DAYS gives it, its battery's grid_charging the scenario's; then each without it.
GRID_CHARGING_RUNS: dict[str, tuple[HomeConfig, pd.DataFrame, pd.Timestamp, pd.Timestamp]] = {
    f"{day}-grid_charging": (home, weather, pd.Timestamp(start), pd.Timestamp(end))
    for day, home, weather, start, end in _DAYS
}
HOME_RUNS = GRID_CHARGING_RUNS | {
    f"{day}-no_grid_charging": (_without_grid_charging(home), weather, pd.Timestamp(start), pd.Timestamp(end))
    for day, home, weather, start, end in _DAYS
}

# Each built-in strategy's runs: every run for one that charges from the grid, only those without grid_charging else.
_RUNS_OF: dict[str, list[str]] = {
    strategy_id: [
        run_id
        for run_id in HOME_RUNS
        if strategy_id in GRID_CHARGING_STRATEGIES or run_id not in GRID_CHARGING_RUNS
    ]
    for strategy_id in BUILT_IN_STRATEGIES
}


@functools.cache
def _run(strategy_id: str, run_id: str) -> SimulationResults:
    """HOME_RUNS[run_id] under BUILT_IN_STRATEGIES[strategy_id], its balance checked every minute, simulated once for every test that reads it."""
    home, weather, start, end = HOME_RUNS[run_id]
    return simulate_home(
        home,
        start,
        end,
        validate_balance=True,
        weather=weather_for(home, weather),
        strategy=BUILT_IN_STRATEGIES[strategy_id],
    )


def _grid_charge_kw(results: SimulationResults) -> pd.Series:
    """The power *results*' battery stored from the grid each minute; every run here has a tariff, so it is set."""
    assert results.grid_charge is not None
    return results.grid_charge


def _pv_charge_kw(results: SimulationResults) -> pd.Series:
    """The power *results*' battery stored from PV each minute: its charge less its grid charge."""
    return results.battery_charge - _grid_charge_kw(results)


class TestNoBuiltInStrategyTripsABound:
    """§9 row 12: each built-in strategy keeps every decision within its step's limits, so each of its runs, its balance checked every minute, completes.

    Self-consumption ignores grid_charge_ctx, so simulate_home refuses it on a battery that sets grid_charging, and it
    runs only the runs without one; every other strategy runs every run.

    Every bound meets decisions that reach it: each grid-charging strategy charges from the grid in each run whose
    battery sets a target, and between its runs each strategy charges from PV and discharges.
    """

    @pytest.mark.parametrize(
        ("strategy_id", "run_id"),
        [
            pytest.param(strategy_id, run_id, id=f"{strategy_id}-{run_id}")
            for strategy_id, run_ids in _RUNS_OF.items()
            for run_id in run_ids
        ],
    )
    def test_the_run_completes(self, strategy_id: str, run_id: str) -> None:
        assert _run(strategy_id, run_id).strategy_name == BUILT_IN_STRATEGIES[strategy_id].name

    @pytest.mark.parametrize("run_id", list(GRID_CHARGING_RUNS))
    @pytest.mark.parametrize("strategy_id", GRID_CHARGING_STRATEGIES)
    def test_a_grid_charging_strategy_charges_from_the_grid_in_a_run_whose_battery_sets_a_target(
        self, strategy_id: str, run_id: str
    ) -> None:
        assert _grid_charge_kw(_run(strategy_id, run_id)).gt(0).any()

    @pytest.mark.parametrize("strategy_id", list(BUILT_IN_STRATEGIES))
    def test_between_its_runs_the_strategy_charges_from_pv(self, strategy_id: str) -> None:
        """A battery that a strategy fills from the grid overnight takes no PV the next day, so not every sunny run charges from PV."""
        assert any(_pv_charge_kw(_run(strategy_id, run_id)).gt(0).any() for run_id in _RUNS_OF[strategy_id])

    @pytest.mark.parametrize("strategy_id", list(BUILT_IN_STRATEGIES))
    def test_between_its_runs_the_strategy_discharges(self, strategy_id: str) -> None:
        assert any(_run(strategy_id, run_id).battery_discharge.gt(0).any() for run_id in _RUNS_OF[strategy_id])
