# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long one row of a simulated series lasts."""

import pandas as pd
import pytest

from solar_challenge.timebase import HOURS_PER_MINUTE, step_hours


def test_a_single_row_lasts_one_minute() -> None:
    index = pd.date_range("2024-06-21 12:00", periods=1, freq="h", tz="Europe/London")

    assert step_hours(index) == HOURS_PER_MINUTE == pytest.approx(1 / 60)


@pytest.mark.parametrize(
    ("freq", "hours"),
    [("min", 1 / 60), ("15min", 0.25), ("h", 1.0), ("2h", 2.0)],
)
def test_a_row_lasts_the_gap_between_the_first_two_rows(freq: str, hours: float) -> None:
    index = pd.date_range("2024-06-21 12:00", periods=3, freq=freq, tz="Europe/London")

    assert step_hours(index) == pytest.approx(hours)
