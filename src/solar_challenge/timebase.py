# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a simulated window is: the calendar days a series covers, how long each of its rows lasts, its clock's zone, and the one rule that turns the window's totals into a year's."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

HOURS_PER_MINUTE = 1 / 60
"""Hours in one minute: minutes times this is hours. It says nothing about a series' cadence; SimulationWindow.step_hours is how long one row lasts."""


def step_hours(index: pd.DatetimeIndex) -> float:
    """The hours one row of index lasts: the gap between its first two rows, or one minute when it has fewer."""
    if len(index) < 2:
        return HOURS_PER_MINUTE
    return float((index[1] - index[0]).total_seconds()) / 3600.0


def covered_days(first_day: date, last_day: date) -> int:
    """The calendar days from first_day to last_day, both counted.

    Raises ValueError, naming both, when last_day is before first_day.
    """
    if last_day < first_day:
        raise ValueError(
            f"last_day {last_day.isoformat()} is before first_day {first_day.isoformat()}: "
            "a window's days run from its first day to its last"
        )
    return last_day.toordinal() - first_day.toordinal() + 1


@dataclass(frozen=True)
class SimulationWindow:
    """The calendar days a simulated series covers, its first and last local dates both counted; how long each of its rows lasts; and its clock's zone name, None for a naive index.

    A yearly figure is a window total times annualisation_scale.
    """

    first_day: date
    last_day: date
    cadence: timedelta
    timezone: str | None = None

    def __post_init__(self) -> None:
        """Refuse a last_day before first_day through covered_days, the one home of that rule, which names both days; and refuse a cadence that is not positive, naming it."""
        covered_days(self.first_day, self.last_day)
        if self.cadence <= timedelta(0):
            raise ValueError(
                "SimulationWindow's cadence is how long one row lasts, so it is positive: "
                f"got cadence={self.cadence!r}"
            )

    @property
    def days(self) -> int:
        """The calendar days the window covers."""
        return covered_days(self.first_day, self.last_day)

    @property
    def year_days(self) -> float:
        """The days in the year a window total is scaled to: its own year's when the window lies in one calendar year, else a mean year's."""
        if self.first_day.year != self.last_day.year:
            return 365.25
        return 366.0 if calendar.isleap(self.first_day.year) else 365.0

    @property
    def annualisation_scale(self) -> float:
        """What a window total is multiplied by to give a yearly figure."""
        return self.year_days / self.days

    @property
    def extrapolated(self) -> bool:
        """Whether the window runs other than from 1 January to 31 December, so a yearly figure from it is extrapolated."""
        starts_on_new_years_day = (self.first_day.month, self.first_day.day) == (1, 1)
        ends_on_new_years_eve = (self.last_day.month, self.last_day.day) == (12, 31)
        return not (starts_on_new_years_day and ends_on_new_years_eve)

    @property
    def step_hours(self) -> float:
        """How long each row lasts, in hours: a kW sample times this is its row's kWh."""
        return self.cadence / timedelta(hours=1)

    @property
    def step_minutes(self) -> float:
        """How long each row lasts, in minutes."""
        return self.cadence / timedelta(minutes=1)

    def energy_kwh(self, power_kw: pd.Series) -> float:
        """The kWh a kW series on this window's rows delivers: each row's kW times the hours it lasts, summed."""
        return float((power_kw * self.step_hours).sum())
