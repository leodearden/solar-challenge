# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ChargeWindow and ScheduledChargeStrategy, a Victron GX's scheduled-charge windows.

In each window the strategy force-charges the battery from the grid to the window's target and
then holds it; outside every window its base strategy decides.
"""

import dataclasses
import math
from datetime import datetime, time, timedelta, timezone

import pytest

from solar_challenge.dispatch import ChargeWindow
from solar_challenge.errors import ConfigurationError

_NIGHTLY = ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, allow_discharge=False)
"""Every night from 00:30 for 7 hours, to 0.9 of the battery's capacity, holding at the target."""


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
