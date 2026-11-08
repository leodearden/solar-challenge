# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 8-12: a decision's powers are finite and at least 0, and simulate_timestep refuses one that asks for more than its step allows, before the battery moves."""

import dataclasses
import math
import re
from datetime import datetime, time, timedelta
from typing import Optional
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
    TOUOptimizedStrategy,
)
from solar_challenge.flow import EnergyFlowResult, simulate_timestep
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.tariff import TariffConfig
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for

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


class _ConsumerStrategy(DispatchStrategy):
    """Test double: a strategy of a consumer's own, which checks none of its inputs, records each call's generation and demand, and returns one decision whatever the step."""

    def __init__(self, decision: DispatchDecision, name: str = "consumer") -> None:
        self._decision = decision
        self._name = name
        self.calls: list[tuple[float, float]] = []

    @property
    def name(self) -> str:
        """Return the name this double was built with."""
        return self._name

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
        """Record generation_kw and demand_kw, and return the decision this double was built with."""
        self.calls.append((generation_kw, demand_kw))
        return self._decision


class TestADecisionRefusesAPowerThatIsNotFiniteAndAtLeast0:
    """§9 row 11, the decision's half: each of a decision's three powers is finite and at least 0, whatever its step."""

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize("field", ["charge_kw", "discharge_kw", "grid_charge_kw"])
    def test_the_decision_refuses_the_power_naming_its_field_and_value(self, field: str, value: float) -> None:
        powers = {"charge_kw": 0.0, "discharge_kw": 0.0, "grid_charge_kw": 0.0, field: value}
        refusal = f"{field} must be non-negative and finite, got {value!r} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            DispatchDecision(**powers)

    def test_finite_powers_at_least_0_construct_and_the_exclusivity_refusals_still_fire(self) -> None:
        assert dataclasses.astuple(DispatchDecision(0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
        assert dataclasses.astuple(DispatchDecision(1.5, 0.0, 2.0)) == (1.5, 0.0, 2.0)
        with pytest.raises(ValueError, match="^Cannot charge and discharge simultaneously"):
            DispatchDecision(1.0, 1.0, 0.0)
        with pytest.raises(ValueError, match="^Cannot grid-charge and discharge simultaneously"):
            DispatchDecision(0.0, 1.0, 1.0)


class TestTheStepRefusesAPowerThatIsNotFiniteAndAtLeast0:
    """§9 row 11, the input half: simulate_timestep refuses a generation or demand that is not finite and at least 0, naming it, before any strategy or battery.

    _ConsumerStrategy checks none of its inputs, so the step's own check is all that refuses the power.
    """

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    def test_a_step_with_a_battery_refuses_the_power_before_its_strategy_decides_and_its_battery_moves(
        self, power: str, quantity: str, value: float
    ) -> None:
        battery = Battery(BatteryConfig.default_5kwh())
        soc_kwh = battery.soc_kwh
        strategy = _ConsumerStrategy(DispatchDecision(0.0, 0.0))
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

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    def test_a_step_without_a_battery_refuses_the_power(self, power: str, quantity: str, value: float) -> None:
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            simulate_timestep(
                **{"generation_kw": 1.0, "demand_kw": 1.0, power: value}, battery=None, timestep_minutes=1.0
            )


def _refusal(*breaches: str) -> str:
    """simulate_timestep's refusal of a decision by the strategy named 'over_limit' that makes *breaches*, given in field order."""
    return "Dispatch strategy 'over_limit' decided more than the step allows: " + "; ".join(breaches)


def _ten_kwh_battery(soc_kwh: float) -> Battery:
    """A 10 kWh battery at *soc_kwh*, with the default 2.5 kW limits and 0.975 efficiencies."""
    return Battery(BatteryConfig(capacity_kwh=10.0, max_charge_kw=2.5), initial_soc_kwh=soc_kwh)


def _hour_under(
    decision: DispatchDecision, *, generation_kw: float, demand_kw: float, battery: Battery
) -> EnergyFlowResult:
    """Step one hour, so a power in kW is the same energy in kWh, on *battery* under a strategy named 'over_limit' that returns *decision*."""
    return simulate_timestep(
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery=battery,
        timestep_minutes=60,
        strategy=_ConsumerStrategy(decision, name="over_limit"),
    )


class TestAStepRefusesADecisionBeyondItsLimitsBeforeTheBatteryMoves:
    """§9 rows 8-10: simulate_timestep refuses a decision that asks for more than its step allows, naming the strategy and each breach, and leaves the battery's SOC as it was."""

    def test_a_grid_charge_above_the_headroom_the_pv_charge_leaves_is_refused(self) -> None:
        """§9 row 8: a 5 kW PV charge takes all of the battery's 2.5 kW charge limit, leaving no headroom for the 5 kW grid charge."""
        battery = _ten_kwh_battery(1.0)
        refusal = _refusal("grid_charge_kw=5.0 kW is above 0.0 kW, the charge limit's headroom after charge_kw")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(5.0, 0.0, 5.0), generation_kw=10.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0

    def test_a_pv_charge_above_the_excess_is_refused(self) -> None:
        """§9 row 9: with no PV the step has no excess to charge from."""
        battery = _ten_kwh_battery(1.0)
        refusal = _refusal("charge_kw=2.5 kW is above 0.0 kW, the step's PV excess")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(2.5, 0.0, 0.0), generation_kw=0.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0

    def test_a_discharge_above_the_shortfall_is_refused(self) -> None:
        """§9 row 10: 2.5 kW of discharge against a 1.0 kW shortfall."""
        battery = _ten_kwh_battery(5.0)
        refusal = _refusal("discharge_kw=2.5 kW is above 1.0 kW, the step's shortfall")
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(0.0, 2.5, 0.0), generation_kw=0.0, demand_kw=1.0, battery=battery)
        assert battery.soc_kwh == 5.0

    def test_every_breach_of_one_decision_is_named_in_one_refusal(self) -> None:
        battery = _ten_kwh_battery(1.0)
        refusal = _refusal(
            "charge_kw=2.5 kW is above 0.0 kW, the step's PV excess",
            "grid_charge_kw=2.5 kW is above 0.0 kW, the charge limit's headroom after charge_kw",
        )
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            _hour_under(DispatchDecision(2.5, 0.0, 2.5), generation_kw=0.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == 1.0


class TestAStepAdmitsADecisionWithinItsLimits:
    """A decision at its step's limits runs, and so does a PV charge above the battery's charge limit, an offer the battery clamps."""

    def test_a_decision_at_both_of_its_charge_limits_runs(self) -> None:
        """1.0 kW of PV charge takes the whole excess, and 1.5 kW of grid charge the whole headroom it leaves of 2.5 kW."""
        battery = _ten_kwh_battery(1.0)
        _hour_under(DispatchDecision(1.0, 0.0, 1.5), generation_kw=1.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == pytest.approx(1.0 + (1.0 + 1.5) * battery.charge_efficiency)

    def test_a_pv_charge_above_the_charge_limit_runs_at_the_limit(self) -> None:
        battery = _ten_kwh_battery(1.0)
        _hour_under(DispatchDecision(5.0, 0.0, 0.0), generation_kw=10.0, demand_kw=0.0, battery=battery)
        assert battery.soc_kwh == pytest.approx(1.0 + battery.max_charge_kw * 1.0 * battery.charge_efficiency)


BUILT_IN_STRATEGIES = [
    pytest.param(SelfConsumptionStrategy(), id="self_consumption"),
    pytest.param(TOUOptimizedStrategy([(16, 20)]), id="tou_optimized"),
    pytest.param(PeakShavingStrategy(1.0), id="peak_shaving"),
    pytest.param(
        ScheduledChargeStrategy(
            TOUOptimizedStrategy([(16, 20)]),
            (
                ChargeWindow(
                    days="daily",
                    start=time(1, 0),
                    duration=timedelta(hours=4),
                    target_soc_fraction=0.8,
                    allow_discharge=False,
                ),
                ChargeWindow(
                    days="daily",
                    start=time(17, 0),
                    duration=timedelta(hours=2),
                    target_soc_fraction=0.3,
                    allow_discharge=True,
                ),
            ),
            ZoneInfo("Europe/London"),
        ),
        id="scheduled_charge",
    ),
]

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


HOME_RUNS = [
    pytest.param(run_home, weather, pd.Timestamp(start), pd.Timestamp(end), id=f"{day}-{grid_charging}")
    for day, home, weather, start, end in _DAYS
    for grid_charging, run_home in (("grid_charging", home), ("no_grid_charging", _without_grid_charging(home)))
]


class TestNoBuiltInStrategyTripsABound:
    """§9 row 12: each built-in strategy keeps every decision within its step's limits, so its run, its balance checked every minute, completes."""

    @pytest.mark.parametrize(("home", "weather", "start", "end"), HOME_RUNS)
    @pytest.mark.parametrize("strategy", BUILT_IN_STRATEGIES)
    def test_the_run_completes(
        self, strategy: DispatchStrategy, home: HomeConfig, weather: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
    ) -> None:
        results = simulate_home(
            home, start, end, validate_balance=True, weather=weather_for(home, weather), strategy=strategy
        )
        assert results.strategy_name == strategy.name
