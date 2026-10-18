# SPDX-License-Identifier: AGPL-3.0-or-later
"""A step under a strategy that moves more energy than the step has shortfall to serve or excess to absorb.

simulate_timestep executes the decision it is given. The result still counts the demand
as served once, so self-consumption stops at the demand, and it never settles a negative
amount with the grid: a discharge past the shortfall imports nothing, and a charge past
the excess exports nothing. The energy balance does not hold for such a step; the result
reports the battery's flows as they were.
"""

from datetime import datetime
from typing import Optional

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import DispatchDecision, DispatchStrategy, GridChargeContext
from solar_challenge.flow import EnergyFlowResult, simulate_timestep


class _FixedDecision(DispatchStrategy):
    """Test double: a strategy that returns one decision whatever the step."""

    def __init__(self, decision: DispatchDecision) -> None:
        self._decision = decision

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "fixed_decision"

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
        """Return the decision this double was built with."""
        return self._decision


def _hour_under(
    decision: DispatchDecision, *, generation_kw: float, demand_kw: float, soc_kwh: float
) -> EnergyFlowResult:
    """Step one hour, so a power in kW is the same energy in kWh, on a default 5 kWh battery at *soc_kwh*, under a strategy that returns *decision*."""
    return simulate_timestep(
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery=Battery(BatteryConfig.default_5kwh(), initial_soc_kwh=soc_kwh),
        timestep_minutes=60,
        strategy=_FixedDecision(decision),
    )


class TestStepUnderAStrategyThatMovesMoreEnergyThanTheStepNeeds:
    """The caps and clamps that keep such a step's result within its bounds."""

    def test_a_discharge_past_the_shortfall_serves_the_demand_once_and_imports_nothing(self) -> None:
        """1 kWh generated against 2 kWh demanded leaves a 1 kWh shortfall; the strategy discharges 2 kW."""
        result = _hour_under(
            DispatchDecision(charge_kw=0.0, discharge_kw=2.0),
            generation_kw=1.0,
            demand_kw=2.0,
            soc_kwh=4.0,
        )
        assert result.battery_discharge > result.demand - result.generation
        assert result.self_consumption == result.demand
        assert result.grid_import == 0.0

    def test_a_charge_past_the_excess_exports_nothing(self) -> None:
        """3 kWh generated against 1 kWh demanded leaves a 2 kWh excess; the strategy charges at 2.5 kW, which stores 2.4375 kWh."""
        result = _hour_under(
            DispatchDecision(charge_kw=2.5, discharge_kw=0.0),
            generation_kw=3.0,
            demand_kw=1.0,
            soc_kwh=1.0,
        )
        assert result.battery_charge > result.generation - result.demand
        assert result.grid_export == 0.0
