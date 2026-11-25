# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for DispatchStrategy.charges_from_the_grid, whether a strategy charges the battery from the grid when it is offered a GridChargeContext."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchStrategy,
    GridChargeContext,
    PeakShavingStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from tests._consumer_dispatch_strategy import ConsumerStrategy

_LONDON = ZoneInfo("Europe/London")

_NIGHTLY = ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, False)
"""Every night from 00:30 for 7 hours, to 0.9 of the battery's capacity, holding at the target."""

_CHEAP_CTX = GridChargeContext(
    current_rate=0.09,
    peak_rate=0.25,
    is_cheap_period=True,
    target_soc_kwh=4.5,
    max_charge_kw=2.5,
    round_trip_efficiency=0.9,
    charge_efficiency=0.95,
)
"""A cheap period whose spread pays for the round trip, so a strategy that grid-charges does."""


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        pytest.param(SelfConsumptionStrategy(), False, id="self_consumption"),
        pytest.param(TOUOptimizedStrategy([(16, 19)]), True, id="tou_optimized"),
        pytest.param(PeakShavingStrategy(3.0), True, id="peak_shaving"),
        pytest.param(
            ScheduledChargeStrategy(SelfConsumptionStrategy(), (_NIGHTLY,), _LONDON),
            True,
            id="a-window-over-self_consumption",
        ),
        pytest.param(
            ScheduledChargeStrategy(SelfConsumptionStrategy(), (), _LONDON),
            False,
            id="no-window-over-self_consumption",
        ),
        pytest.param(
            ScheduledChargeStrategy(TOUOptimizedStrategy([(16, 19)]), (), _LONDON),
            True,
            id="no-window-over-tou_optimized",
        ),
    ],
)
def test_a_strategy_declares_whether_it_charges_from_the_grid_as_it_decides(
    strategy: DispatchStrategy, expected: bool
) -> None:
    decision = strategy.decide_action(
        timestamp=datetime(2024, 1, 15, 2, 0, tzinfo=_LONDON),
        generation_kw=0.0,
        demand_kw=0.0,
        battery_soc_kwh=1.0,
        battery_capacity_kwh=5.0,
        timestep_minutes=1.0,
        grid_charge_ctx=_CHEAP_CTX,
    )

    assert strategy.charges_from_the_grid == expected
    assert (decision.grid_charge_kw > 0) == expected, decision


def test_a_strategy_the_library_does_not_know_charges_from_the_grid() -> None:
    assert ConsumerStrategy().charges_from_the_grid is True
