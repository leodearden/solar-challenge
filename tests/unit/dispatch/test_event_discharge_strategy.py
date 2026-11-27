# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a battery's grid-services event windows and the strategy that discharges it at full power in them.

docs/prds/event-dispatch-and-battery-sizing.md §5.2 defines EventDischargeWindow and
EventDischargeStrategy; §9 B4 is the behaviour they pin.
"""

import dataclasses
import math
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    EventDischargeStrategy,
    EventDischargeWindow,
    GridChargeContext,
    PeakShavingStrategy,
    SelfConsumptionStrategy,
    SelfConsumptionStrategyConfig,
    StepLimits,
    TOUOptimizedStrategy,
    build_dispatch_strategy,
    with_event_discharge,
)
from solar_challenge.errors import ConfigurationError

LONDON = ZoneInfo("Europe/London")
WINDOW = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17, 18))
"""An event on 2024-01-15 from 17:00 to 19:00."""
MAX_DISCHARGE_KW = 2.5
BATTERY = {"battery_soc_kwh": 5.0, "battery_capacity_kwh": 10.0, "timestep_minutes": 1.0}

STEPS = [
    pytest.param(3.0, 1.0, id="excess"),
    pytest.param(0.0, 1.0, id="shortfall"),
    pytest.param(1.0, 1.0, id="balanced"),
    pytest.param(0.0, 4.0, id="shortfall-beyond-the-limit"),
]
"""(generation_kw, demand_kw) of a step."""

CHEAP_CTX = GridChargeContext(
    current_rate=0.09,
    peak_rate=0.25,
    is_cheap_period=True,
    target_soc_kwh=9.0,
    max_charge_kw=2.5,
    round_trip_efficiency=0.9,
    charge_efficiency=0.95,
)
"""A cheap period whose spread pays for the round trip, below the target, so a base that grid-charges would."""

CONTEXTS = [pytest.param(None, id="no-grid-charge"), pytest.param(CHEAP_CTX, id="cheap-period")]

BASES = [
    pytest.param(SelfConsumptionStrategy(), id="self_consumption"),
    pytest.param(TOUOptimizedStrategy([(16, 20)]), id="tou_optimized"),
    pytest.param(PeakShavingStrategy(0.25), id="peak_shaving"),
]


def _wrapped(base: DispatchStrategy, *windows: EventDischargeWindow) -> EventDischargeStrategy:
    return EventDischargeStrategy(base, windows or (WINDOW,), max_discharge_kw=MAX_DISCHARGE_KW)


def _decide(
    strategy: DispatchStrategy,
    timestamp: datetime,
    generation_kw: float,
    demand_kw: float,
    grid_charge_ctx: Optional[GridChargeContext],
) -> DispatchDecision:
    return strategy.decide_action(
        timestamp, generation_kw, demand_kw, **BATTERY, grid_charge_ctx=grid_charge_ctx
    )


def _full_power_decision(generation_kw: float, demand_kw: float) -> tuple[DispatchDecision, StepLimits]:
    limits = StepLimits.for_step(
        generation_kw, demand_kw, max_charge_kw=MAX_DISCHARGE_KW, max_discharge_kw=MAX_DISCHARGE_KW
    )
    decision = DispatchDecision(
        charge_kw=0.0, discharge_kw=limits.shortfall_kw, grid_charge_kw=0.0, export_kw=limits.max_export_kw
    )
    return decision, limits


class TestEventDischargeWindow:
    def test_it_holds_its_days_and_hours_as_tuples(self) -> None:
        window = EventDischargeWindow(days=[date(2024, 1, 15), date(2024, 1, 16)], hours=[17, 18])

        assert window.days == (date(2024, 1, 15), date(2024, 1, 16))
        assert window.hours == (17, 18)
        assert isinstance(window.days, tuple)
        assert isinstance(window.hours, tuple)

    def test_it_is_frozen(self) -> None:
        window = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17,))

        with pytest.raises(dataclasses.FrozenInstanceError):
            window.days = (date(2024, 1, 16),)

    def test_two_equal_windows_are_equal_and_hash_equal(self) -> None:
        first = EventDischargeWindow(days=[date(2024, 1, 15)], hours=[17, 18])
        second = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17, 18))

        assert first == second
        assert hash(first) == hash(second)

    def test_two_windows_listing_the_same_days_and_hours_in_another_order_are_equal_and_hash_equal(self) -> None:
        first = EventDischargeWindow(days=(date(2024, 1, 15), date(2024, 1, 16)), hours=(17, 18))
        second = EventDischargeWindow(days=(date(2024, 1, 16), date(2024, 1, 15)), hours=(18, 17))

        assert first == second
        assert hash(first) == hash(second)
        assert second.days == (date(2024, 1, 15), date(2024, 1, 16))
        assert second.hours == (17, 18)

    @pytest.mark.parametrize(
        ("days", "hours", "field", "repeated"),
        [
            pytest.param((date(2024, 1, 15), date(2024, 1, 15)), (17,), "days", "2024-01-15", id="days"),
            pytest.param((date(2024, 1, 15),), (18, 17, 18), "hours", "18", id="hours"),
        ],
    )
    def test_a_field_that_repeats_an_element_is_refused_naming_it_and_the_element(
        self, days: tuple[date, ...], hours: tuple[int, ...], field: str, repeated: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=rf"^{field} must hold each \w+ once; it repeats {repeated}$"):
            EventDischargeWindow(days=days, hours=hours)

    @pytest.mark.parametrize(
        ("days", "hours", "field"),
        [
            pytest.param((), (17,), "days", id="days"),
            pytest.param((date(2024, 1, 15),), (), "hours", id="hours"),
        ],
    )
    def test_an_empty_field_is_refused_naming_it(
        self, days: tuple[date, ...], hours: tuple[int, ...], field: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=rf"^{field} must hold at least one"):
            EventDischargeWindow(days=days, hours=hours)

    @pytest.mark.parametrize("hour", [24, -1, 1.5, True], ids=["24", "-1", "1.5", "True"])
    def test_an_hour_that_is_not_a_whole_clock_hour_is_refused_naming_it(self, hour: object) -> None:
        with pytest.raises(ConfigurationError, match=r"^hours\[0\] must be"):
            EventDischargeWindow(days=(date(2024, 1, 15),), hours=(hour,))

    @pytest.mark.parametrize(
        "day",
        [datetime(2024, 1, 15, 17), pd.Timestamp("2024-01-15"), "2024-01-15"],
        ids=["datetime", "pd.Timestamp", "str"],
    )
    def test_a_day_that_is_not_exactly_a_date_is_refused_naming_it(self, day: object) -> None:
        with pytest.raises(ConfigurationError, match=r"^days\[0\] must be a date, got "):
            EventDischargeWindow(days=(day,), hours=(17,))

    @pytest.mark.parametrize(
        ("days", "hours", "field"),
        [
            pytest.param("2024-01-15", (17,), "days", id="days-str"),
            pytest.param({date(2024, 1, 15)}, (17,), "days", id="days-set"),
            pytest.param((date(2024, 1, 15),), "17", "hours", id="hours-str"),
            pytest.param((date(2024, 1, 15),), {17}, "hours", id="hours-set"),
        ],
    )
    def test_a_field_that_is_not_a_list_is_refused_naming_it(self, days: object, hours: object, field: str) -> None:
        with pytest.raises(ConfigurationError, match=rf"^{field} must be a list of "):
            EventDischargeWindow(days=days, hours=hours)


class TestEventDischargeStrategy:
    @pytest.mark.parametrize("grid_charge_ctx", CONTEXTS)
    @pytest.mark.parametrize(("generation_kw", "demand_kw"), STEPS)
    @pytest.mark.parametrize(
        "timestamp",
        [datetime(2024, 1, 15, 17, 0, tzinfo=LONDON), datetime(2024, 1, 15, 18, 59, tzinfo=LONDON)],
        ids=["17:00", "18:59"],
    )
    @pytest.mark.parametrize("base", BASES)
    def test_inside_a_window_it_serves_the_home_and_exports_the_discharge_limits_headroom(
        self,
        base: DispatchStrategy,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        grid_charge_ctx: Optional[GridChargeContext],
    ) -> None:
        strategy = _wrapped(base)
        expected, limits = _full_power_decision(generation_kw, demand_kw)

        decision = _decide(strategy, timestamp, generation_kw, demand_kw, grid_charge_ctx)

        assert decision == expected
        limits.require_admissible(decision, strategy.name)

    @pytest.mark.parametrize(
        ("generation_kw", "demand_kw", "export_kw"),
        [
            pytest.param(0.0, 1.0, 1.5, id="shortfall"),
            pytest.param(3.0, 1.0, 2.5, id="excess"),
            pytest.param(0.0, 4.0, 0.0, id="shortfall-beyond-the-limit"),
        ],
    )
    def test_its_export_is_the_limit_less_the_shortfall(
        self, generation_kw: float, demand_kw: float, export_kw: float
    ) -> None:
        strategy = _wrapped(SelfConsumptionStrategy())

        decision = _decide(strategy, datetime(2024, 1, 15, 17, 30, tzinfo=LONDON), generation_kw, demand_kw, None)

        assert decision.export_kw == export_kw

    @pytest.mark.parametrize("grid_charge_ctx", CONTEXTS)
    @pytest.mark.parametrize(("generation_kw", "demand_kw"), STEPS)
    @pytest.mark.parametrize(
        "timestamp",
        [
            datetime(2024, 1, 15, 16, 59, tzinfo=LONDON),
            datetime(2024, 1, 15, 19, 0, tzinfo=LONDON),
            datetime(2024, 1, 16, 17, 0, tzinfo=LONDON),
            datetime(2024, 1, 14, 17),
        ],
        ids=["right-day-16:59", "right-day-19:00", "right-hour-other-day", "naive-other-day"],
    )
    @pytest.mark.parametrize("base", BASES)
    def test_outside_every_window_its_base_decides_unchanged(
        self,
        base: DispatchStrategy,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        grid_charge_ctx: Optional[GridChargeContext],
    ) -> None:
        strategy = _wrapped(base)

        decision = _decide(strategy, timestamp, generation_kw, demand_kw, grid_charge_ctx)

        assert decision == _decide(base, timestamp, generation_kw, demand_kw, grid_charge_ctx)

    def test_a_timestamp_is_read_on_its_own_clock_not_in_utc(self) -> None:
        strategy = _wrapped(SelfConsumptionStrategy(), EventDischargeWindow(days=(date(2024, 6, 20),), hours=(17,)))
        expected, _ = _full_power_decision(0.0, 1.0)
        in_london = datetime(2024, 6, 20, 17, 30, tzinfo=LONDON)
        in_utc = datetime(2024, 6, 20, 16, 30, tzinfo=timezone.utc)
        assert in_london == in_utc

        assert _decide(strategy, in_london, 0.0, 1.0, None) == expected
        assert _decide(strategy, in_utc, 0.0, 1.0, None) == _decide(SelfConsumptionStrategy(), in_utc, 0.0, 1.0, None)

    def test_a_naive_timestamp_is_read_on_its_own_clock(self) -> None:
        strategy = _wrapped(SelfConsumptionStrategy())
        expected, _ = _full_power_decision(0.0, 1.0)

        assert _decide(strategy, datetime(2024, 1, 15, 17, 30), 0.0, 1.0, None) == expected

    @pytest.mark.parametrize(
        "timestamp",
        [datetime(2024, 1, 15, 17, 30, tzinfo=LONDON), datetime(2024, 2, 1, 8, 15, tzinfo=LONDON)],
        ids=["first-window", "second-window"],
    )
    def test_a_minute_in_any_of_its_windows_is_inside(self, timestamp: datetime) -> None:
        strategy = _wrapped(
            SelfConsumptionStrategy(), WINDOW, EventDischargeWindow(days=(date(2024, 2, 1),), hours=(8,))
        )
        expected, _ = _full_power_decision(0.0, 1.0)

        assert _decide(strategy, timestamp, 0.0, 1.0, None) == expected

    @pytest.mark.parametrize("base", BASES)
    def test_its_name_wraps_its_bases(self, base: DispatchStrategy) -> None:
        assert _wrapped(base).name == f"event_discharge({base.name})"

    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            pytest.param(SelfConsumptionStrategy(), False, id="self_consumption"),
            pytest.param(TOUOptimizedStrategy([(16, 20)]), True, id="tou_optimized"),
        ],
    )
    def test_it_charges_from_the_grid_as_its_base_does(self, base: DispatchStrategy, expected: bool) -> None:
        assert _wrapped(base).charges_from_the_grid is expected

    @pytest.mark.parametrize("max_discharge_kw", [0.0, -1.0, math.nan, True], ids=["0", "-1", "nan", "True"])
    def test_a_discharge_limit_that_is_not_a_positive_finite_number_is_refused_naming_it(
        self, max_discharge_kw: float
    ) -> None:
        with pytest.raises(ConfigurationError, match=r"^max_discharge_kw must be "):
            EventDischargeStrategy(SelfConsumptionStrategy(), (WINDOW,), max_discharge_kw=max_discharge_kw)

    def test_a_window_that_is_not_an_event_discharge_window_is_refused_naming_it(self) -> None:
        with pytest.raises(ConfigurationError, match=r"^windows\[0\] must be an EventDischargeWindow, got "):
            EventDischargeStrategy(
                SelfConsumptionStrategy(), ({"days": [], "hours": []},), max_discharge_kw=MAX_DISCHARGE_KW
            )


SITE_EXPORT_LIMIT_KW = 3.0
IN_THE_WINDOW = datetime(2024, 1, 15, 17, 30, tzinfo=LONDON)

LIMITED_STEPS = [
    pytest.param(0.0, 1.0, id="shortfall"),
    pytest.param(3.0, 1.0, id="excess-below-the-limit"),
    pytest.param(4.5, 1.0, id="excess-above-the-limit"),
]
"""(generation_kw, demand_kw) of a step at which a 3 kW site export limit, or the 2.5 kW discharge limit, binds."""


def _limited_full_power_decision(generation_kw: float, demand_kw: float) -> tuple[DispatchDecision, StepLimits]:
    limits = StepLimits.for_step(
        generation_kw,
        demand_kw,
        max_charge_kw=MAX_DISCHARGE_KW,
        max_discharge_kw=MAX_DISCHARGE_KW,
        site_export_limit_kw=SITE_EXPORT_LIMIT_KW,
    )
    decision = DispatchDecision(
        charge_kw=0.0, discharge_kw=limits.shortfall_kw, grid_charge_kw=0.0, export_kw=limits.max_export_kw
    )
    return decision, limits


class TestASiteExportLimit:
    """docs/prds/event-dispatch-and-battery-sizing.md §5.4: under a site export limit a window exports exactly the export limit StepLimits.for_step gives the step, PV excess included."""

    @pytest.mark.parametrize(("generation_kw", "demand_kw"), LIMITED_STEPS)
    def test_inside_a_window_it_exports_the_export_limit_the_site_limit_leaves(
        self, generation_kw: float, demand_kw: float
    ) -> None:
        strategy = EventDischargeStrategy(
            SelfConsumptionStrategy(),
            (WINDOW,),
            max_discharge_kw=MAX_DISCHARGE_KW,
            site_export_limit_kw=SITE_EXPORT_LIMIT_KW,
        )
        expected, limits = _limited_full_power_decision(generation_kw, demand_kw)

        decision = _decide(strategy, IN_THE_WINDOW, generation_kw, demand_kw, None)

        assert decision == expected
        limits.require_admissible(decision, strategy.name)

    def test_the_limit_lowers_the_export_of_a_step_where_it_binds(self) -> None:
        unlimited = _decide(_wrapped(SelfConsumptionStrategy()), IN_THE_WINDOW, 3.0, 1.0, None)
        limited, _ = _limited_full_power_decision(3.0, 1.0)

        assert (unlimited.export_kw, limited.export_kw) == (2.5, 1.0)

    @pytest.mark.parametrize(("generation_kw", "demand_kw"), STEPS)
    def test_with_no_limit_its_decision_is_the_discharge_limits_alone(
        self, generation_kw: float, demand_kw: float
    ) -> None:
        strategy = EventDischargeStrategy(
            SelfConsumptionStrategy(), (WINDOW,), max_discharge_kw=MAX_DISCHARGE_KW, site_export_limit_kw=None
        )

        assert _decide(strategy, IN_THE_WINDOW, generation_kw, demand_kw, None) == _full_power_decision(
            generation_kw, demand_kw
        )[0]

    @pytest.mark.parametrize("site_export_limit_kw", [-1.0, math.nan, True], ids=["-1", "nan", "True"])
    def test_a_limit_that_is_not_a_finite_number_of_at_least_0_is_refused_naming_it(
        self, site_export_limit_kw: float
    ) -> None:
        with pytest.raises(ConfigurationError, match=r"^site_export_limit_kw must be "):
            EventDischargeStrategy(
                SelfConsumptionStrategy(),
                (WINDOW,),
                max_discharge_kw=MAX_DISCHARGE_KW,
                site_export_limit_kw=site_export_limit_kw,
            )

    def test_with_event_discharge_wraps_at_the_limit(self) -> None:
        strategy = with_event_discharge(
            SelfConsumptionStrategy(),
            (WINDOW,),
            max_discharge_kw=MAX_DISCHARGE_KW,
            site_export_limit_kw=SITE_EXPORT_LIMIT_KW,
        )

        assert _decide(strategy, IN_THE_WINDOW, 3.0, 1.0, None) == _limited_full_power_decision(3.0, 1.0)[0]

    def test_build_dispatch_strategy_wraps_at_the_limit(self) -> None:
        strategy = build_dispatch_strategy(
            SelfConsumptionStrategyConfig(),
            grid_charging=None,
            tariff=None,
            event_discharge=(WINDOW,),
            max_discharge_kw=MAX_DISCHARGE_KW,
            site_export_limit_kw=SITE_EXPORT_LIMIT_KW,
        )

        assert _decide(strategy, IN_THE_WINDOW, 3.0, 1.0, None) == _limited_full_power_decision(3.0, 1.0)[0]
