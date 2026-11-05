# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 9: every capacity a dispatcher sees is SOH-derated, so a grid-charge target is a fraction of effective capacity.

docs/prds/dispatch-configuration-below-config.md §5.4 states it, and its §9 rows 9-10 sketch its boundary tests.

The fixture is the program's: a 10 kWh battery with 5 kW charge and discharge limits, at soh 1.0 or 0.7, on Economy 7
(TariffConfig.economy_7()), run for 180 minutes from 2024-01-15 01:00, inside the cheap night, with a demand of 0.3 kW
and no PV.
"""

from collections.abc import Callable
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
from solar_challenge.flow import simulate_timestep, simulate_timestep_tou
from solar_challenge.tariff import TariffConfig

_E7 = TariffConfig.economy_7()

_MINUTES = pd.date_range("2024-01-15 01:00", periods=180, freq="min")

_STARTS = ["midpoint", "min_soc_kwh"]


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


def _strategy_path(battery: Battery, minute: pd.Timestamp, strategy: Optional[DispatchStrategy] = None) -> None:
    """Simulate *minute* through simulate_timestep, dispatched by *strategy*, else by a TOUOptimizedStrategy([(16, 19)])."""
    simulate_timestep(
        0.0, 0.3, battery, 1.0, minute.to_pydatetime(), strategy or TOUOptimizedStrategy([(16, 19)]), tariff=_E7
    )


def _function_path(battery: Battery, minute: pd.Timestamp) -> None:
    """Simulate *minute* through simulate_timestep_tou."""
    simulate_timestep_tou(0.0, 0.3, battery, minute, _E7, 1.0)


_PATHS = [
    pytest.param(_function_path, id="simulate_timestep_tou"),
    pytest.param(_strategy_path, id="simulate_timestep"),
]


def _run(path: Callable[[Battery, pd.Timestamp], None], battery: Battery) -> Battery:
    """*battery* after the fixture's 180 minutes through *path*."""
    for minute in _MINUTES:
        path(battery, minute)
    return battery


class TestDecideActionSeesTheEffectiveCapacity:
    """simulate_timestep hands decide_action the battery's effective capacity, the basis of its SOC fractions."""

    @pytest.mark.parametrize("soh", [1.0, 0.7])
    def test_the_capacity_decide_action_is_given_is_derated_by_soh(self, soh: float) -> None:
        recorder = _Recording()

        simulate_timestep(
            0.0, 0.3, _battery(soh, 0.5, start="midpoint"), 1.0, _MINUTES[0].to_pydatetime(), recorder, tariff=_E7
        )

        assert recorder.capacities_kwh == pytest.approx([10.0 * soh])


class TestGridChargeEndsAtTheTargetFractionOfEffectiveCapacity:
    """§9 row 9: a target of 0.5 fills the battery to half its effective capacity on both dispatch paths, from either start."""

    @pytest.mark.parametrize("path", _PATHS)
    @pytest.mark.parametrize("soh", [1.0, 0.7])
    @pytest.mark.parametrize("start", _STARTS)
    def test_the_run_ends_at_the_target_fraction(
        self, path: Callable[[Battery, pd.Timestamp], None], soh: float, start: Literal["midpoint", "min_soc_kwh"]
    ) -> None:
        battery = _run(path, _battery(soh, 0.5, start=start))

        assert battery.soc_fraction == pytest.approx(0.5, abs=1e-6)


class TestATargetAboveTheCeilingStopsAsking:
    """§9 row 10: a target of 0.95, above max_soc_fraction 0.9, fills the battery to max_soc_kwh, after which the strategy asks for no grid power."""

    @pytest.mark.parametrize("path", _PATHS)
    @pytest.mark.parametrize("soh", [1.0, 0.7])
    @pytest.mark.parametrize("start", _STARTS)
    def test_the_run_ends_at_max_soc_kwh(
        self, path: Callable[[Battery, pd.Timestamp], None], soh: float, start: Literal["midpoint", "min_soc_kwh"]
    ) -> None:
        battery = _run(path, _battery(soh, 0.95, start=start))

        assert battery.soc_kwh == pytest.approx(battery.max_soc_kwh, abs=1e-9)

    @pytest.mark.parametrize("soh", [1.0, 0.7])
    @pytest.mark.parametrize("start", _STARTS)
    def test_the_next_cheap_minute_s_decision_asks_for_no_grid_power(
        self, soh: float, start: Literal["midpoint", "min_soc_kwh"]
    ) -> None:
        battery = _run(_strategy_path, _battery(soh, 0.95, start=start))
        recorder = _Recording()

        _strategy_path(battery, _MINUTES[-1] + pd.Timedelta(minutes=1), recorder)

        assert [decision.grid_charge_kw for decision in recorder.decisions] == [0.0]
