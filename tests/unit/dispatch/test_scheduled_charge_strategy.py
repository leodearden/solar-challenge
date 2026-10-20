# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ChargeWindow and ScheduledChargeStrategy, a Victron GX's scheduled-charge windows.

In each window the strategy force-charges the battery from the grid to the window's target and
then holds it; outside every window its base strategy decides.
"""

import dataclasses
import math
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchDecision,
    DispatchStrategy,
    GridChargeContext,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.errors import ConfigurationError

_NIGHTLY = ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, allow_discharge=False)
"""Every night from 00:30 for 7 hours, to 0.9 of the battery's capacity, holding at the target."""

_LONDON = ZoneInfo("Europe/London")

_FLAT_RATE_CTX = GridChargeContext(
    current_rate=0.25,
    peak_rate=0.25,
    is_cheap_period=False,
    target_soc_fraction=0.9,
    max_charge_kw=2.5,
    round_trip_efficiency=0.95,
    charge_efficiency=0.975,
)
"""A grid-charge context both of compute_grid_charge_power_kw's rate gates refuse: it is no cheap period, and its rate has no spread."""


@dataclasses.dataclass(frozen=True)
class _Call:
    """The arguments one decide_action call received."""

    timestamp: datetime
    generation_kw: float
    demand_kw: float
    battery_soc_kwh: float
    battery_capacity_kwh: float
    timestep_minutes: float
    grid_charge_ctx: Optional[GridChargeContext]


class _RecordingStrategy(DispatchStrategy):
    """Test double: a base strategy that records each call it receives and returns one decision whatever the step."""

    def __init__(self, decision: DispatchDecision) -> None:
        self.decision = decision
        self.calls: list[_Call] = []

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "recording"

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
        """Record the call, then return the decision this double was built with."""
        self.calls.append(
            _Call(
                timestamp,
                generation_kw,
                demand_kw,
                battery_soc_kwh,
                battery_capacity_kwh,
                timestep_minutes,
                grid_charge_ctx,
            )
        )
        return self.decision


def _base() -> _RecordingStrategy:
    """A recording base whose decision no window makes: a 0.7 kW discharge."""
    return _RecordingStrategy(DispatchDecision(charge_kw=0.0, discharge_kw=0.7))


def _decide(
    strategy: DispatchStrategy,
    timestamp: datetime,
    *,
    generation_kw: float = 0.0,
    demand_kw: float = 0.0,
    battery_soc_kwh: float = 2.0,
    grid_charge_ctx: Optional[GridChargeContext] = None,
) -> DispatchDecision:
    """strategy's decision for a one-minute step on a 5.0 kWh battery."""
    return strategy.decide_action(
        timestamp=timestamp,
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery_soc_kwh=battery_soc_kwh,
        battery_capacity_kwh=5.0,
        timestep_minutes=1.0,
        grid_charge_ctx=grid_charge_ctx,
    )


class TestChargeWindow:
    """A ChargeWindow refuses a field it cannot schedule, and covers the wall-clock minutes from its start for its duration on each day it opens."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("days", frozenset(), id="no-days"),
            pytest.param("days", frozenset({7}), id="day-7"),
            pytest.param("days", frozenset({-1}), id="day-minus-1"),
            pytest.param("days", frozenset({True}), id="a-bool-is-not-a-weekday"),
            pytest.param("days", "weekdays", id="a-string-other-than-daily"),
            pytest.param("start", time(0, 30, tzinfo=timezone.utc), id="a-start-on-a-zone-of-its-own"),
            pytest.param("duration", timedelta(0), id="no-duration"),
            pytest.param("duration", timedelta(minutes=-1), id="a-negative-duration"),
            pytest.param("duration", timedelta(days=1, minutes=1), id="longer-than-a-day"),
            pytest.param("target_soc_fraction", 0.0, id="target-0"),
            pytest.param("target_soc_fraction", 1.5, id="target-above-1"),
            pytest.param("target_soc_fraction", math.nan, id="target-nan"),
        ],
    )
    def test_it_refuses_a_field_naming_the_field_and_its_value(self, field: str, value: object) -> None:
        """A window's clock is its strategy's zone, so its start has none; only 'daily' stands for every day."""
        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(_NIGHTLY, **{field: value})

        message = str(refusal.value)
        assert field in message
        assert repr(value) in message

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("days", "daily", id="daily"),
            pytest.param("days", frozenset({4}), id="fridays"),
            pytest.param("duration", timedelta(days=1), id="a-whole-day"),
            pytest.param("target_soc_fraction", 1.0, id="target-1"),
        ],
    )
    def test_it_builds_at_each_edge_it_admits(self, field: str, value: object) -> None:
        assert getattr(dataclasses.replace(_NIGHTLY, **{field: value}), field) == value

    @pytest.mark.parametrize(
        ("moment", "covered"),
        [
            pytest.param(datetime(2024, 1, 15, 0, 30), True, id="its-opening-minute"),
            pytest.param(datetime(2024, 1, 15, 7, 29), True, id="its-last-minute"),
            pytest.param(datetime(2024, 1, 15, 0, 29), False, id="the-minute-before-it-opens"),
            pytest.param(datetime(2024, 1, 15, 7, 30), False, id="the-minute-it-closes"),
        ],
    )
    def test_a_daily_window_covers_its_start_up_to_its_end(self, moment: datetime, covered: bool) -> None:
        assert _NIGHTLY.covers(moment) is covered

    @pytest.mark.parametrize(
        ("moment", "covered"),
        [
            pytest.param(datetime(2024, 1, 19, 22, 0), True, id="friday-22:00"),
            pytest.param(datetime(2024, 1, 20, 1, 59), True, id="saturday-01:59"),
            pytest.param(datetime(2024, 1, 20, 2, 0), False, id="saturday-02:00"),
            pytest.param(datetime(2024, 1, 20, 22, 0), False, id="saturday-22:00"),
            pytest.param(datetime(2024, 1, 19, 1, 0), False, id="friday-01:00-which-a-thursday-opening-covers"),
        ],
    )
    def test_a_window_crossing_midnight_covers_the_next_morning_only_after_a_day_it_opens(
        self, moment: datetime, covered: bool
    ) -> None:
        """A window opening on Fridays (weekday 4; 2024-01-19 is one) at 22:00 for 4 hours runs into Saturday's first two hours."""
        friday_nights = ChargeWindow(frozenset({4}), time(22, 0), timedelta(hours=4), 0.9, allow_discharge=False)

        assert friday_nights.covers(moment) is covered

    @pytest.mark.parametrize(
        "moment",
        [
            pytest.param(datetime(2024, 1, 15, 0, 0), id="midnight"),
            pytest.param(datetime(2024, 1, 15, 23, 59), id="23:59"),
        ],
    )
    def test_a_daily_24_hour_window_covers_every_minute(self, moment: datetime) -> None:
        all_day = dataclasses.replace(_NIGHTLY, start=time(0, 0), duration=timedelta(days=1))

        assert all_day.covers(moment)


class TestScheduledChargeStrategyWindows:
    """Outside every window the base decides; inside one the window does, read on the strategy's zone."""

    def test_outside_every_window_the_base_decides_with_the_arguments_given(self) -> None:
        base = _base()
        noon = datetime(2024, 7, 1, 12, 0, tzinfo=_LONDON)

        decision = ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON).decide_action(
            timestamp=noon,
            generation_kw=0.4,
            demand_kw=1.4,
            battery_soc_kwh=2.0,
            battery_capacity_kwh=5.0,
            timestep_minutes=5.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision is base.decision
        assert base.calls == [_Call(noon, 0.4, 1.4, 2.0, 5.0, 5.0, _FLAT_RATE_CTX)]
        assert base.calls[0].timestamp is noon
        assert base.calls[0].grid_charge_ctx is _FLAT_RATE_CTX

    def test_inside_a_window_the_base_is_not_consulted(self) -> None:
        base = _base()

        _decide(ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON), datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON))

        assert base.calls == []

    def test_a_window_with_no_grid_charge_context_holds_through_a_shortfall(self) -> None:
        """SelfConsumptionStrategy would discharge 1.0 kW; the window keeps the charge."""
        two_am = datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON)
        strategy = ScheduledChargeStrategy(SelfConsumptionStrategy(), (_NIGHTLY,), _LONDON)

        assert _decide(SelfConsumptionStrategy(), two_am, demand_kw=1.0) == DispatchDecision(0.0, 1.0)
        assert _decide(strategy, two_am, demand_kw=1.0) == DispatchDecision(0.0, 0.0, 0.0)

    def test_a_window_charges_the_pv_excess(self) -> None:
        two_am = datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON)
        strategy = ScheduledChargeStrategy(SelfConsumptionStrategy(), (_NIGHTLY,), _LONDON)

        decision = _decide(strategy, two_am, generation_kw=2.0, demand_kw=0.5)

        assert (decision.charge_kw, decision.discharge_kw) == (1.5, 0.0)

    @pytest.mark.parametrize(
        ("timestamp", "zone", "base_decides"),
        [
            pytest.param(
                datetime(2024, 7, 1, 23, 30, tzinfo=timezone.utc), _LONDON, False, id="00:30-BST-on-London"
            ),
            pytest.param(
                datetime(2024, 7, 1, 23, 30, tzinfo=timezone.utc), ZoneInfo("UTC"), True, id="23:30-on-UTC"
            ),
            pytest.param(
                datetime(2024, 1, 15, 0, 30, tzinfo=timezone.utc), _LONDON, False, id="00:30-GMT-on-London"
            ),
            pytest.param(
                datetime(2024, 1, 15, 0, 30, tzinfo=timezone.utc), ZoneInfo("UTC"), False, id="00:30-on-UTC"
            ),
        ],
    )
    def test_a_window_is_read_on_the_wall_clock_of_the_strategys_zone(
        self, timestamp: datetime, zone: ZoneInfo, base_decides: bool
    ) -> None:
        """23:30 UTC on 1 July is 00:30 BST, when the nightly window opens in London; in January London keeps UTC."""
        base = _base()

        _decide(ScheduledChargeStrategy(base, (_NIGHTLY,), zone), timestamp)

        assert bool(base.calls) is base_decides

    def test_a_naive_timestamp_is_refused_naming_the_zone(self) -> None:
        strategy = ScheduledChargeStrategy(_base(), (_NIGHTLY,), _LONDON)

        with pytest.raises(ValueError, match="Europe/London"):
            _decide(strategy, datetime(2024, 7, 1, 2, 0))

    @pytest.mark.parametrize(
        "zone",
        [
            pytest.param("Europe/London", id="a-zone-name"),
            pytest.param(timezone.utc, id="a-fixed-offset"),
        ],
    )
    def test_a_zone_that_is_no_zoneinfo_is_refused_naming_it(self, zone: object) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            ScheduledChargeStrategy(_base(), (_NIGHTLY,), zone)

        assert repr(zone) in str(refusal.value)

    @pytest.mark.parametrize(
        ("base", "name"),
        [
            pytest.param(SelfConsumptionStrategy(), "scheduled_charge(self_consumption)", id="self_consumption"),
            pytest.param(TOUOptimizedStrategy([(17, 20)]), "scheduled_charge(tou_optimized)", id="tou_optimized"),
        ],
    )
    def test_its_name_wraps_its_bases(self, base: DispatchStrategy, name: str) -> None:
        assert ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON).name == name

    @pytest.mark.parametrize(
        "timestamp",
        [
            pytest.param(datetime(2024, 7, 1, 0, 30, tzinfo=_LONDON), id="00:30"),
            pytest.param(datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON), id="02:00"),
            pytest.param(datetime(2024, 7, 1, 12, 0, tzinfo=_LONDON), id="12:00"),
        ],
    )
    def test_with_no_windows_the_base_decides_every_step(self, timestamp: datetime) -> None:
        base = _base()

        decision = _decide(ScheduledChargeStrategy(base, (), _LONDON), timestamp)

        assert decision is base.decision
        assert len(base.calls) == 1


class TestScheduledChargeStrategyInputs:
    """Inside a window, where its base is not consulted, the strategy refuses the inputs its sibling strategies refuse, with their messages."""

    @pytest.mark.parametrize(
        ("argument", "value", "message"),
        [
            pytest.param("generation_kw", -1.0, "non-negative", id="negative-generation"),
            pytest.param("demand_kw", -1.0, "non-negative", id="negative-demand"),
            pytest.param("battery_soc_kwh", -1.0, "non-negative", id="negative-soc"),
            pytest.param("battery_capacity_kwh", 0.0, "positive", id="no-capacity"),
            pytest.param("timestep_minutes", 0.0, "positive", id="no-timestep"),
        ],
    )
    def test_a_bad_input_inside_a_window_is_refused(self, argument: str, value: float, message: str) -> None:
        base = _base()
        arguments: dict[str, float] = {
            "generation_kw": 0.0,
            "demand_kw": 0.5,
            "battery_soc_kwh": 2.0,
            "battery_capacity_kwh": 5.0,
            "timestep_minutes": 1.0,
        }

        with pytest.raises(ValueError, match=message):
            ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON).decide_action(
                timestamp=datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON), **(arguments | {argument: value})
            )
        assert base.calls == []
