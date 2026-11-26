# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/event-dispatch-and-battery-sizing.md §5.1, §5.8 invariants 1-3 and §9 B1-B3: battery export in the dispatch engine.

A decision's export_kw asks the battery for power beyond the home's shortfall. simulate_timestep serves the home
first from what the battery delivers and books the rest as grid export, and as battery_export, a part of both
battery_discharge and grid_export (B1, invariants 2 and 3). A run that asks for no export is byte-identical to the
engine before battery export existed (B3, invariant 1). B2, an export beyond its step's limit, is refused with the
other bounds, in tests/unit/dispatch/test_decision_bounds.py.
"""

import functools
import hashlib
import itertools
import math
import random
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchStrategy,
    GridChargeConfig,
    PeakShavingStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import EnergyFlowResult, simulate_timestep
from solar_challenge.tariff import TariffConfig
from tests._tou_on_the_tariff_s_clock import on_the_tariff_s_clock

_E7 = TariffConfig.economy_7()
_LONDON = ZoneInfo("Europe/London")

# Measured at the base f0b4cba5: on a minute at this generation and demand, a 10 kWh battery at 5.0 kWh under
# self-consumption delivers 0.020849925363509925 kWh against a shortfall of 0.020849925363509922 kWh, an ulp more,
# because (d - g) * h is not d * h - g * h.
_ULP_PAIR_GENERATION_KW = 1.9723046813928018
_ULP_PAIR_DEMAND_KW = 3.2233002032033973

# Task 1362's pair: two powers an ulp apart, whose energies over a minute are equal.
_POWER_KW = 3.9243814029178457
_AN_ULP_ABOVE_KW = math.nextafter(_POWER_KW, math.inf)

# Steps whose generation and demand are an ulp, or a rounding, apart, as (generation_kw, demand_kw).
_EDGE_STEPS = (
    (_ULP_PAIR_GENERATION_KW, _ULP_PAIR_DEMAND_KW),
    (_POWER_KW, _AN_ULP_ABOVE_KW),
    (_AN_ULP_ABOVE_KW, _POWER_KW),
    (0.1 + 0.2, 0.3),
)

_MINUTES_PER_DAY = 1440
_EDGE_MINUTES = range(30, _MINUTES_PER_DAY, 90)
_DAY_START = datetime(2024, 1, 15, tzinfo=_LONDON)


def _day_of_steps(seed: int) -> tuple[tuple[float, float], ...]:
    """A day of minutes' (generation_kw, demand_kw), each drawn from 0 to 3 kW by random.Random(seed), with _EDGE_STEPS spliced in turn into _EDGE_MINUTES."""
    rng = random.Random(seed)
    steps = [(rng.uniform(0.0, 3.0), rng.uniform(0.0, 3.0)) for _ in range(_MINUTES_PER_DAY)]
    for minute, edge in zip(_EDGE_MINUTES, itertools.cycle(_EDGE_STEPS)):
        steps[minute] = edge
    return tuple(steps)


_STEPS = _day_of_steps(seed=1702)


class _Dispatch(NamedTuple):
    """A strategy, the tariff its steps are priced at, and its battery's grid charging."""

    strategy: DispatchStrategy
    tariff: Optional[TariffConfig] = None
    grid_charging: Optional[GridChargeConfig] = None


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

BUILT_IN_DISPATCHES: dict[str, _Dispatch] = {
    "self_consumption": _Dispatch(SelfConsumptionStrategy()),
    "tou_optimized": _Dispatch(**on_the_tariff_s_clock(_E7), grid_charging=GridChargeConfig()),
    "peak_shaving": _Dispatch(PeakShavingStrategy(0.25), _E7, GridChargeConfig()),
    "scheduled_charge": _Dispatch(
        ScheduledChargeStrategy(
            TOUOptimizedStrategy([(16, 20)]), (_CHARGE_WINDOW_01_TO_05, _DISCHARGE_WINDOW_17_TO_19), _LONDON
        ),
        _E7,
        GridChargeConfig(),
    ),
}


@functools.cache
def _flows_of_the_day(dispatch_id: str) -> tuple[EnergyFlowResult, ...]:
    """Each minute's flows of _STEPS from 2024-01-15 00:00 in London under BUILT_IN_DISPATCHES[dispatch_id], on one 10 kWh battery carried from minute to minute."""
    dispatch = BUILT_IN_DISPATCHES[dispatch_id]
    battery = Battery(BatteryConfig(capacity_kwh=10.0, grid_charging=dispatch.grid_charging))
    return tuple(
        simulate_timestep(
            generation_kw,
            demand_kw,
            battery,
            1.0,
            _DAY_START + timedelta(minutes=minute),
            dispatch.strategy,
            tariff=dispatch.tariff,
        )
        for minute, (generation_kw, demand_kw) in enumerate(_STEPS)
    )


# EnergyFlowResult's fields before battery export existed, named so that no later field enters the digest.
_PRE_EXPORT_FIELDS = (
    "generation",
    "demand",
    "self_consumption",
    "battery_charge",
    "battery_discharge",
    "grid_export",
    "grid_import",
    "battery_soc",
    "grid_charge",
)


def _digest(flows: Sequence[EnergyFlowResult]) -> str:
    """The sha256 of each step's _PRE_EXPORT_FIELDS, each written exactly by float.hex."""
    sha = hashlib.sha256()
    for flow in flows:
        sha.update((" ".join(float.hex(getattr(flow, name)) for name in _PRE_EXPORT_FIELDS) + "\n").encode())
    return sha.hexdigest()


# Recorded by running this test at the base f0b4cba5, before battery export existed.
_DIGESTS_BEFORE_BATTERY_EXPORT = {
    "self_consumption": "a5dafa22d81d1141e8805e8a2611d12818955180cd82a66c0cd36924f1550d05",
    "tou_optimized": "a7241dbd06f4ee75fe409818b81ccf7141f56e90a6332a90aa34b3455a128783",
    "peak_shaving": "b497f21cdbefd027baa89d70473fed1a18c77b38f02ede2829fb0a728116a8f1",
    "scheduled_charge": "3a0f9c0b3981695c77b84936bd460a2ccad34f151c9139ebeefada57411696dc",
}


class TestARunThatAsksForNoExportIsUnchanged:
    """B3, invariant 1: a built-in strategy asks for no export, so every step's flows are those of the engine before battery export, to the last bit."""

    @pytest.mark.parametrize("dispatch_id", list(BUILT_IN_DISPATCHES))
    def test_every_built_in_strategy_s_flows_are_byte_identical_to_the_engine_before_battery_export(
        self, dispatch_id: str
    ) -> None:
        assert _digest(_flows_of_the_day(dispatch_id)) == _DIGESTS_BEFORE_BATTERY_EXPORT[dispatch_id]
