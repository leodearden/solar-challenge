# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 8-12: a decision's powers, and a step's generation and demand, are finite and at least 0, and simulate_timestep refuses a decision that asks for more than its step allows, before the battery moves."""

import dataclasses
import functools
import math
import re
from collections.abc import Callable
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
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
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

# Both engines, simulate_timestep_tou at Economy 7's 18:00 peak rate.
ENGINES = [
    pytest.param(simulate_timestep, id="simulate_timestep"),
    pytest.param(
        functools.partial(
            simulate_timestep_tou, timestamp=pd.Timestamp("2024-01-01 18:00"), tariff=TariffConfig.economy_7()
        ),
        id="simulate_timestep_tou",
    ),
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
    """§9 row 11, the input half: both engines refuse a generation or demand that is not finite and at least 0, naming it, before any strategy decides or any battery moves."""

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    @pytest.mark.parametrize("engine", ENGINES)
    def test_a_step_without_a_battery_refuses_the_power(
        self, engine: Callable[..., EnergyFlowResult], power: str, quantity: str, value: float
    ) -> None:
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            engine(**{"generation_kw": 1.0, "demand_kw": 1.0, power: value}, battery=None, timestep_minutes=1.0)

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    @pytest.mark.parametrize("engine", ENGINES)
    def test_a_step_with_a_battery_refuses_the_power_and_leaves_its_soc_unchanged(
        self, engine: Callable[..., EnergyFlowResult], power: str, quantity: str, value: float
    ) -> None:
        battery = Battery(BatteryConfig.default_5kwh())
        soc_kwh = battery.soc_kwh
        refusal = f"{quantity} must be non-negative and finite, got {value} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            engine(**{"generation_kw": 1.0, "demand_kw": 1.0, power: value}, battery=battery, timestep_minutes=1.0)
        assert battery.soc_kwh == soc_kwh

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize(("power", "quantity"), STEP_POWERS)
    def test_simulate_timestep_refuses_the_power_before_a_strategy_of_the_consumer_s_own_decides(
        self, power: str, quantity: str, value: float
    ) -> None:
        """Unlike the built-in strategies, _ConsumerStrategy checks none of its inputs, so the step's own check is all that refuses the power."""
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


BUILT_IN_STRATEGIES: dict[str, DispatchStrategy] = {
    "self_consumption": SelfConsumptionStrategy(),
    "tou_optimized": TOUOptimizedStrategy([(16, 20)]),
    # Below the home's peak demand on each day here, so the strategy discharges.
    "peak_shaving": PeakShavingStrategy(0.25),
    "scheduled_charge": ScheduledChargeStrategy(
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
}

# Every built-in strategy but self-consumption, which ignores grid_charge_ctx, charges from the grid toward the
# target its battery's grid_charging sets.
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

    Every bound meets decisions that reach it: each grid-charging strategy charges from the grid in each run whose
    battery sets a target, and between its runs each strategy charges from PV and discharges.
    """

    @pytest.mark.parametrize("run_id", list(HOME_RUNS))
    @pytest.mark.parametrize("strategy_id", list(BUILT_IN_STRATEGIES))
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
        assert any(_pv_charge_kw(_run(strategy_id, run_id)).gt(0).any() for run_id in HOME_RUNS)

    @pytest.mark.parametrize("strategy_id", list(BUILT_IN_STRATEGIES))
    def test_between_its_runs_the_strategy_discharges(self, strategy_id: str) -> None:
        assert any(_run(strategy_id, run_id).battery_discharge.gt(0).any() for run_id in HOME_RUNS)
