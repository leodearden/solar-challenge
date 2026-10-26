# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ChargeWindow and ScheduledChargeStrategy, a Victron GX's scheduled-charge windows.

In each window the strategy force-charges the battery from the grid to the window's target and
then holds it; outside every window its base strategy decides.
"""

import dataclasses
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchDecision,
    DispatchStrategy,
    GridChargeConfig,
    GridChargeContext,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
    compute_grid_charge_power_kw,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.flow import EnergyFlowResult, simulate_timestep
from solar_challenge.tariff import TariffConfig
from tests._unusable_numbers import UNUSABLE_NUMBERS

_NIGHTLY = ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, allow_discharge=False)
"""Every night from 00:30 for 7 hours, to 0.9 of the battery's capacity, holding at the target."""

_LONDON = ZoneInfo("Europe/London")

_TWO_AM_BST = datetime(2024, 7, 1, 2, 0, tzinfo=_LONDON)
"""A moment inside the nightly window."""

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
    battery_capacity_kwh: float = 5.0,
    grid_charge_ctx: Optional[GridChargeContext] = None,
) -> DispatchDecision:
    """strategy's decision for a one-minute step, on a 5.0 kWh battery unless battery_capacity_kwh says otherwise."""
    return strategy.decide_action(
        timestamp=timestamp,
        generation_kw=generation_kw,
        demand_kw=demand_kw,
        battery_soc_kwh=battery_soc_kwh,
        battery_capacity_kwh=battery_capacity_kwh,
        timestep_minutes=1.0,
        grid_charge_ctx=grid_charge_ctx,
    )


def _over_self_consumption(*windows: ChargeWindow) -> ScheduledChargeStrategy:
    """windows on London's wall clock, over SelfConsumptionStrategy."""
    return ScheduledChargeStrategy(SelfConsumptionStrategy(), windows, _LONDON)


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

    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word"), 0.0, 1.5])
    def test_it_refuses_a_target_as_grid_charge_config_does(self, value: object) -> None:
        with pytest.raises(ConfigurationError) as window_refusal:
            dataclasses.replace(_NIGHTLY, target_soc_fraction=value)
        with pytest.raises(ConfigurationError) as config_refusal:
            GridChargeConfig(target_soc_fraction=value)

        assert str(window_refusal.value) == str(config_refusal.value)

    @pytest.mark.parametrize(
        ("value", "held"), [pytest.param(1, 1.0, id="whole-number"), pytest.param("0.5", 0.5, id="quoted")]
    )
    def test_it_holds_its_target_as_the_float_it_reads(self, value: object, held: float) -> None:
        target = dataclasses.replace(_NIGHTLY, target_soc_fraction=value).target_soc_fraction

        assert target == held
        assert type(target) is float

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

        _decide(ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON), _TWO_AM_BST)

        assert base.calls == []

    def test_a_window_with_no_grid_charge_context_holds_through_a_shortfall(self) -> None:
        """SelfConsumptionStrategy would discharge 1.0 kW; the window keeps the charge."""
        strategy = _over_self_consumption(_NIGHTLY)

        assert _decide(SelfConsumptionStrategy(), _TWO_AM_BST, demand_kw=1.0) == DispatchDecision(0.0, 1.0)
        assert _decide(strategy, _TWO_AM_BST, demand_kw=1.0) == DispatchDecision(0.0, 0.0, 0.0)

    def test_a_window_charges_the_pv_excess(self) -> None:
        decision = _decide(_over_self_consumption(_NIGHTLY), _TWO_AM_BST, generation_kw=2.0, demand_kw=0.5)

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

    @pytest.mark.parametrize(
        ("night", "hours"),
        [
            pytest.param(date(2024, 1, 15), 7, id="an-ordinary-night"),
            pytest.param(date(2024, 3, 31), 6, id="the-clocks-go-forward"),
            pytest.param(date(2024, 10, 27), 8, id="the-clocks-go-back"),
        ],
    )
    def test_a_window_lasts_its_wall_clock_hours_so_a_clock_change_shortens_or_lengthens_it(
        self, night: date, hours: int
    ) -> None:
        """The nightly window spans 00:30 to 07:30 on London's wall clock, as a GX's does.

        That is 7 hours of one-minute UTC steps on an ordinary night, 6 when the clocks go forward from 01:00 to
        02:00 on 31 March 2024, and 8 when they go back from 02:00 to 01:00 on 27 October 2024, repeating an hour
        inside the window.
        """
        base = _base()
        strategy = ScheduledChargeStrategy(base, (_NIGHTLY,), _LONDON)
        noon_before = datetime.combine(night - timedelta(days=1), time(12, 0), tzinfo=timezone.utc)
        steps = [noon_before + timedelta(minutes=minute) for minute in range(24 * 60)]

        for step in steps:
            _decide(strategy, step)

        assert len(steps) - len(base.calls) == hours * 60

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
            pytest.param(_TWO_AM_BST, id="02:00"),
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
                timestamp=_TWO_AM_BST, **(arguments | {argument: value})
            )
        assert base.calls == []


class TestScheduledChargeStrategyGridCharge:
    """Offered a grid-charge context, a window grid-charges whatever the rates: to its target after the step's PV charge, within the max_charge_kw headroom that PV charge leaves."""

    def test_it_grid_charges_where_both_rate_gates_refuse(self) -> None:
        """2.0 kWh of 5.0 is 2.5 kWh short of the 0.9 target, more than the 2.5 kW cap can fill in a minute."""
        decision = _decide(
            _over_self_consumption(_NIGHTLY),
            _TWO_AM_BST,
            demand_kw=0.5,
            battery_soc_kwh=2.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert compute_grid_charge_power_kw(
            _FLAT_RATE_CTX, battery_soc_kwh=2.0, capacity_kwh=5.0, pv_charge_power_kw=0.0, timestep_minutes=1.0
        ) == 0.0
        assert decision == DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=2.5)

    def test_it_fills_the_gap_the_steps_pv_charge_leaves_to_the_target(self) -> None:
        """At 4.47 kWh a 0.6 kW excess stores 0.6/60 × 0.975 kWh; the grid stores the rest of the way to 4.5 kWh, at about 1.246 kW, under the 1.9 kW headroom."""
        decision = _decide(
            _over_self_consumption(_NIGHTLY),
            _TWO_AM_BST,
            generation_kw=0.6,
            battery_soc_kwh=4.47,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision.charge_kw == 0.6
        assert decision.grid_charge_kw == pytest.approx((4.5 - (4.47 + 0.6 / 60 * 0.975)) / 0.975 * 60, rel=1e-9)

    @pytest.mark.parametrize(
        ("excess_kw", "grid_charge_kw"),
        [
            pytest.param(1.0, 1.5, id="1.0-kW-excess-leaves-1.5-kW"),
            pytest.param(3.0, 0.0, id="3.0-kW-excess-leaves-none"),
        ],
    )
    def test_the_grid_charges_within_the_headroom_the_pv_charge_leaves(
        self, excess_kw: float, grid_charge_kw: float
    ) -> None:
        decision = _decide(
            _over_self_consumption(_NIGHTLY),
            _TWO_AM_BST,
            generation_kw=excess_kw,
            battery_soc_kwh=2.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision.grid_charge_kw == pytest.approx(grid_charge_kw)

    @pytest.mark.parametrize(
        "battery_soc_kwh",
        [
            pytest.param(4.5, id="at-the-target"),
            pytest.param(4.6, id="above-the-target"),
        ],
    )
    def test_at_or_above_its_target_a_window_holds(self, battery_soc_kwh: float) -> None:
        decision = _decide(
            _over_self_consumption(_NIGHTLY),
            _TWO_AM_BST,
            demand_kw=0.5,
            battery_soc_kwh=battery_soc_kwh,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision == DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=0.0)

    def test_offered_no_grid_charge_context_a_window_never_grid_charges(self) -> None:
        decision = _decide(_over_self_consumption(_NIGHTLY), _TWO_AM_BST, demand_kw=0.5, battery_soc_kwh=2.0)

        assert decision.grid_charge_kw == 0.0

    @pytest.mark.parametrize(
        ("battery_soc_kwh", "grid_charge_kw"),
        [
            pytest.param(3.48, 0.02 / 0.975 * 60, id="0.02-kWh-short"),
            pytest.param(3.5, 0.0, id="at-the-target"),
        ],
    )
    def test_the_target_is_a_fraction_of_the_capacity_decide_action_is_given(
        self, battery_soc_kwh: float, grid_charge_kw: float
    ) -> None:
        """7.0 kWh is a 10 kWh battery's capacity at SoH 0.7, so its 0.5 target is 3.5 kWh; the nominal 10 kWh's would be 5.0 kWh, which the 2.5 kW cap could not fill in a minute."""
        half = dataclasses.replace(_NIGHTLY, target_soc_fraction=0.5)

        decision = _decide(
            _over_self_consumption(half),
            _TWO_AM_BST,
            battery_soc_kwh=battery_soc_kwh,
            battery_capacity_kwh=7.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision.grid_charge_kw == pytest.approx(grid_charge_kw, rel=1e-9)

    @pytest.mark.parametrize(
        ("targets", "grid_charges"),
        [
            pytest.param((0.5, 0.9), False, id="0.5-listed-first-holds"),
            pytest.param((0.9, 0.5), True, id="0.9-listed-first-charges"),
        ],
    )
    def test_the_first_listed_open_window_governs_an_overlap(
        self, targets: tuple[float, float], grid_charges: bool
    ) -> None:
        """At 3.0 kWh of 5.0 the battery is above a 0.5 target and below a 0.9 one."""
        windows = [dataclasses.replace(_NIGHTLY, target_soc_fraction=target) for target in targets]

        decision = _decide(
            _over_self_consumption(*windows), _TWO_AM_BST, battery_soc_kwh=3.0, grid_charge_ctx=_FLAT_RATE_CTX
        )

        assert (decision.grid_charge_kw > 0.0) is grid_charges


_GRID_CHARGING_BATTERY = BatteryConfig(5.0, max_charge_kw=2.5, grid_charging=GridChargeConfig(0.9))
"""A 5.0 kWh battery that grid-charges, so the engine offers its strategy a grid-charge context on a tariff."""


def _window_minutes(
    battery: Battery,
    strategy: DispatchStrategy,
    *,
    minutes: int,
    generation_kw: float = 0.0,
    demand_kw: float = 0.0,
) -> list[EnergyFlowResult]:
    """Each flow of minutes one-minute steps from 00:30 on 2024-01-15 in London, as the nightly window opens, through simulate_timestep on Economy 7."""
    opens = datetime(2024, 1, 15, 0, 30, tzinfo=_LONDON)
    return [
        simulate_timestep(
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery=battery,
            timestep_minutes=1.0,
            timestamp=opens + timedelta(minutes=minute),
            strategy=strategy,
            tariff=TariffConfig.economy_7(),
        )
        for minute in range(minutes)
    ]


class TestScheduledChargeStrategyThroughTheEngine:
    """Through flow.simulate_timestep, a window's grid charge reaches its target and no further than max_charge_kw and max_soc_fraction allow."""

    def test_a_window_minute_fills_the_battery_to_its_target(self) -> None:
        """From 4.47 kWh, with no PV and 0.3 kW demand, the 0.03 kWh gap to 4.5 kWh needs 1.846 kW, under the 2.5 kW cap."""
        battery = Battery(_GRID_CHARGING_BATTERY, initial_soc_kwh=4.47)

        _window_minutes(battery, _over_self_consumption(_NIGHTLY), minutes=1, demand_kw=0.3)

        assert battery.soc_kwh == pytest.approx(4.5, abs=1e-12)

    def test_the_pv_and_grid_charge_share_max_charge_kw(self) -> None:
        battery = Battery(_GRID_CHARGING_BATTERY, initial_soc_kwh=2.0)

        (flow,) = _window_minutes(battery, _over_self_consumption(_NIGHTLY), minutes=1, generation_kw=1.0)

        assert flow.grid_charge > 0.0
        assert flow.battery_charge <= 2.5 / 60 * 0.975 + 1e-12

    def test_a_target_above_max_soc_fraction_stores_nothing_past_max_soc_kwh(self) -> None:
        """A window to 0.95 asks for grid power into a battery its 0.9 max_soc_fraction has filled; the battery stores none, so the step imports its shortfall alone."""
        battery = Battery(_GRID_CHARGING_BATTERY)
        to_095 = dataclasses.replace(_NIGHTLY, target_soc_fraction=0.95)

        flows = _window_minutes(battery, _over_self_consumption(to_095), minutes=240, demand_kw=0.3)

        assert battery.soc_kwh == pytest.approx(battery.max_soc_kwh)
        assert flows[-1].grid_charge == 0.0
        assert flows[-1].grid_import == pytest.approx(0.3 / 60)


_TO_HALF = dataclasses.replace(_NIGHTLY, target_soc_fraction=0.5)
"""The nightly window to 0.5 of the battery's capacity, 2.5 kWh of 5.0, holding at the target."""

_TO_HALF_DISCHARGING = dataclasses.replace(_TO_HALF, allow_discharge=True)
"""The nightly window to 0.5, discharging into a shortfall down to its target."""


class TestScheduledChargeStrategyAllowDischarge:
    """A window that allows discharge covers a shortfall from the battery while it is above the target, and only down to the target."""

    @pytest.mark.parametrize(
        ("battery_soc_kwh", "discharge_kw"),
        [
            pytest.param(3.0, 1.0, id="well-above-the-target-covers-the-shortfall"),
            pytest.param(2.505, pytest.approx(0.005 * 60), id="just-above-the-target-discharges-down-to-it"),
        ],
    )
    def test_above_its_target_it_discharges_into_a_shortfall_down_to_the_target(
        self, battery_soc_kwh: float, discharge_kw: float
    ) -> None:
        decision = _decide(
            _over_self_consumption(_TO_HALF_DISCHARGING),
            _TWO_AM_BST,
            demand_kw=1.0,
            battery_soc_kwh=battery_soc_kwh,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision.discharge_kw == discharge_kw
        assert decision.grid_charge_kw == 0.0

    @pytest.mark.parametrize(
        ("battery_soc_kwh", "grid_charges"),
        [
            pytest.param(2.5, False, id="at-the-target-holds"),
            pytest.param(2.4, True, id="below-the-target-charges"),
        ],
    )
    def test_at_or_below_its_target_it_does_not_discharge(self, battery_soc_kwh: float, grid_charges: bool) -> None:
        decision = _decide(
            _over_self_consumption(_TO_HALF_DISCHARGING),
            _TWO_AM_BST,
            demand_kw=1.0,
            battery_soc_kwh=battery_soc_kwh,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert decision.discharge_kw == 0.0
        assert (decision.grid_charge_kw > 0.0) is grid_charges

    def test_it_charges_a_pv_excess_above_its_target(self) -> None:
        decision = _decide(
            _over_self_consumption(_TO_HALF_DISCHARGING),
            _TWO_AM_BST,
            generation_kw=1.0,
            battery_soc_kwh=3.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert (decision.charge_kw, decision.discharge_kw) == (1.0, 0.0)

    def test_a_window_that_does_not_allow_discharge_holds_above_its_target(self) -> None:
        decision = _decide(
            _over_self_consumption(_TO_HALF),
            _TWO_AM_BST,
            demand_kw=1.0,
            battery_soc_kwh=3.0,
            grid_charge_ctx=_FLAT_RATE_CTX,
        )

        assert (decision.discharge_kw, decision.grid_charge_kw) == (0.0, 0.0)

    def test_through_the_engine_the_soc_comes_down_to_the_target_and_stays_there(self) -> None:
        """Each discharge to the target undershoots it by the discharge loss, at most (1/60 kWh)(1/0.975 - 1), about 4.3e-4 kWh, which the window tops up once.

        A window that discharged and topped up by turns would grid-charge about 0.75 kWh over these 2 hours.
        """
        battery = Battery(_GRID_CHARGING_BATTERY, initial_soc_kwh=3.0)

        flows = _window_minutes(battery, _over_self_consumption(_TO_HALF_DISCHARGING), minutes=120, demand_kw=1.0)

        assert min(flow.battery_soc for flow in flows) >= 2.5 - 1e-3
        assert battery.soc_kwh == pytest.approx(2.5, abs=1e-3)
        assert sum(flow.grid_charge for flow in flows) < 0.01
