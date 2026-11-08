# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 8-12: a decision's powers are finite and at least 0, and simulate_timestep refuses one that asks for more than its step allows, before the battery moves."""

import dataclasses
import math
import re
from datetime import datetime
from typing import Optional

import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import DispatchDecision, DispatchStrategy, GridChargeContext
from solar_challenge.flow import simulate_timestep

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
