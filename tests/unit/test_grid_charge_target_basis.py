# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 9: every capacity a dispatcher sees is SOH-derated, so a grid-charge target is a fraction of effective capacity.

docs/prds/dispatch-configuration-below-config.md §5.4 states it, and its §9 rows 9-10 sketch its boundary tests.

The fixture is the program's: a 10 kWh battery with 5 kW charge and discharge limits, at soh 1.0 or 0.7, on Economy 7
(TariffConfig.economy_7()), run for 180 minutes from 2024-01-15 01:00, inside the cheap night, with a demand of 0.3 kW
and no PV.
"""

from datetime import datetime
from typing import Literal, Optional

import pandas as pd
import pytest
from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    GridChargeConfig,
    GridChargeContext,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import simulate_timestep
from solar_challenge.tariff import TariffConfig

_E7 = TariffConfig.economy_7()

_MINUTES = pd.date_range("2024-01-15 01:00", periods=180, freq="min")


def _battery(soh: float, target: float, *, start: Literal["midpoint", "min_soc_kwh"]) -> Battery:
    """The fixture's battery at *soh*, grid-charging to *target*, its SOC at the midpoint of its limits or at min_soc_kwh."""
    config = BatteryConfig(
        capacity_kwh=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        soh=soh,
        grid_charging=GridChargeConfig(target),
    )
    if start == "midpoint":
        return Battery(config)
    return Battery(config, initial_soc_kwh=Battery(config).min_soc_kwh)


class _Recording(DispatchStrategy):
    """A TOUOptimizedStrategy([(16, 19)]) that records the battery capacity each decide_action is given and the decision it returns."""

    def __init__(self) -> None:
        self._strategy = TOUOptimizedStrategy([(16, 19)])
        self.capacities_kwh: list[float] = []
        self.decisions: list[DispatchDecision] = []

    @property
    def name(self) -> str:
        return self._strategy.name

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
        decision = self._strategy.decide_action(
            timestamp,
            generation_kw,
            demand_kw,
            battery_soc_kwh,
            battery_capacity_kwh,
            timestep_minutes,
            grid_charge_ctx=grid_charge_ctx,
        )
        self.capacities_kwh.append(battery_capacity_kwh)
        self.decisions.append(decision)
        return decision


class TestDecideActionSeesTheEffectiveCapacity:
    """simulate_timestep hands decide_action the battery's effective capacity, the basis of its SOC fractions."""

    @pytest.mark.parametrize("soh", [1.0, 0.7])
    def test_the_capacity_decide_action_is_given_is_derated_by_soh(self, soh: float) -> None:
        recorder = _Recording()

        simulate_timestep(
            0.0, 0.3, _battery(soh, 0.5, start="midpoint"), 1.0, _MINUTES[0].to_pydatetime(), recorder, tariff=_E7
        )

        assert recorder.capacities_kwh == pytest.approx([10.0 * soh])
