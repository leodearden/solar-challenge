# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the inputs every built-in strategy's decide_action refuses before deciding anything."""

import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchDecision,
    DispatchStrategy,
    PeakShavingStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)

LONDON = ZoneInfo("Europe/London")
TIMESTAMP = datetime(2024, 1, 1, 12, 0, tzinfo=LONDON)
WINDOW_OPEN_AT_TIMESTAMP = ChargeWindow(
    days="daily", start=time(11, 0), duration=timedelta(hours=2), target_soc_fraction=0.9, allow_discharge=False
)

STRATEGIES = [
    pytest.param(SelfConsumptionStrategy(), id="self_consumption"),
    pytest.param(TOUOptimizedStrategy(peak_hours=[(17, 20)]), id="tou_optimized"),
    pytest.param(PeakShavingStrategy(import_limit_kw=2.0), id="peak_shaving"),
    pytest.param(
        ScheduledChargeStrategy(SelfConsumptionStrategy(), (WINDOW_OPEN_AT_TIMESTAMP,), LONDON),
        id="scheduled_charge",
    ),
]

VALID_INPUTS = {
    "generation_kw": 2.0,
    "demand_kw": 1.0,
    "battery_soc_kwh": 2.5,
    "battery_capacity_kwh": 5.0,
    "timestep_minutes": 1.0,
}

REFUSALS = [
    pytest.param("generation_kw", "Generation must be non-negative and finite", "kW", id="generation"),
    pytest.param("demand_kw", "Demand must be non-negative and finite", "kW", id="demand"),
    pytest.param("battery_soc_kwh", "Battery SOC must be non-negative and finite", "kWh", id="soc"),
    pytest.param("battery_capacity_kwh", "Battery capacity must be positive and finite", "kWh", id="capacity"),
    pytest.param("timestep_minutes", "Timestep must be positive and finite", "minutes", id="timestep"),
]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_valid_inputs_get_a_decision(strategy: DispatchStrategy) -> None:
    assert isinstance(strategy.decide_action(timestamp=TIMESTAMP, **VALID_INPUTS), DispatchDecision)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize(("name", "bound", "unit"), REFUSALS)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_an_input_that_is_not_finite_is_refused_naming_its_bound_and_value(
    strategy: DispatchStrategy, name: str, bound: str, unit: str, value: float
) -> None:
    message = f"{bound}, got {value} {unit}"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        strategy.decide_action(timestamp=TIMESTAMP, **{**VALID_INPUTS, name: value})
