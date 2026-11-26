# SPDX-License-Identifier: AGPL-3.0-or-later
"""A test double for a dispatch strategy that exports: inside its hours it covers each step's shortfall and exports all the headroom StepLimits leaves.

Outside its hours its base strategy decides, so a run under it is the base's run with battery export in those hours,
the run docs/prds/event-dispatch-and-battery-sizing.md §5.1 settles. Its hours are read on each step's own clock, so
a run whose rows are on London's wall clock exports in London's hours.

Usage::

    from tests._exporting_strategy import ExportingStrategy

    strategy = ExportingStrategy(SelfConsumptionStrategy(), range(17, 19), home.battery_config)
    results = simulate_home(home, start, end, weather=weather, strategy=strategy)
"""

from datetime import datetime
from typing import Optional

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import DispatchDecision, DispatchStrategy, GridChargeContext, StepLimits


class ExportingStrategy(DispatchStrategy):
    """Inside its hours it covers each step's shortfall and exports all the headroom its battery's discharge limit leaves; outside them its base decides."""

    def __init__(self, base: DispatchStrategy, hours: range, battery: BatteryConfig) -> None:
        self._base = base
        self._hours = hours
        self._battery = battery

    @property
    def name(self) -> str:
        """Return its base's name, exporting."""
        return f"exporting({self._base.name})"

    @property
    def charges_from_the_grid(self) -> bool:
        """Whether its base charges from the grid: it only adds export."""
        return self._base.charges_from_the_grid

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Inside its hours, the step's shortfall and its whole export limit; else its base's decision."""
        if timestamp.hour in self._hours:
            limits = StepLimits.for_step(
                generation_kw,
                demand_kw,
                max_charge_kw=self._battery.max_charge_kw,
                max_discharge_kw=self._battery.max_discharge_kw,
            )
            return DispatchDecision(0.0, limits.shortfall_kw, 0.0, limits.max_export_kw)
        return self._base.decide_action(
            timestamp=timestamp,
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery_soc_kwh=battery_soc_kwh,
            battery_capacity_kwh=battery_capacity_kwh,
            timestep_minutes=timestep_minutes,
            grid_charge_ctx=grid_charge_ctx,
        )
