# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a simulated window is: the calendar days a series covers, how long each of its rows lasts, its clock's zone, and the one rule that turns the window's totals into a year's; and the rows a window gives, over its local calendar days."""

import calendar
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

MINUTES_PER_HOUR: int = 60
"""Minutes in one hour: hours times this is minutes, and a wall-clock time's minute of the day is its hour times this plus its minute."""

HOURS_PER_MINUTE: float = 1 / MINUTES_PER_HOUR
"""Hours in one minute: minutes times this is hours. It says nothing about a series' cadence; SimulationWindow.step_hours is how long one row lasts."""

MINUTES_PER_DAY: int = 24 * MINUTES_PER_HOUR
"""Minutes on a 24-hour wall clock, 00:00 to 23:59: the length of a minute-of-day table or profile. A local day across a clock change lasts 23 or 25 hours, so it is not how many one-minute rows every day of a zoned series has."""

ONE_MINUTE: timedelta = timedelta(minutes=1)
"""The cadence simulate_home runs at, which no setting changes (ruling L9, docs/prds/load-composition-and-calendar-days.md)."""


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


@dataclass(frozen=True, eq=False)
class LocalDay:
    """One calendar date of a window on the window's clock: the window's rows that start on that date, from the date's first instant, at the window's cadence.

    Compared by identity, since a generated == would compare its rows element by element.
    """

    date: date
    rows: pd.DatetimeIndex

    def minute_of_day(self) -> np.ndarray:
        """Each row's minute on the local wall clock, 0 to 1439: a day the clocks go back repeats the minutes of the hour they repeat, and a day they go forward lacks those of the hour they skip."""
        minutes: np.ndarray = (self.rows.hour * MINUTES_PER_HOUR + self.rows.minute).to_numpy()
        return minutes

    def instant(self, minute_of_day: int) -> pd.Timestamp:
        """The first row of this date whose local clock reads minute_of_day or later.

        Raises:
            ValueError: If minute_of_day is outside 0 to 1439, naming it; or if no row of this date reads it
                or later, naming the date and the minute.
        """
        if not 0 <= minute_of_day < MINUTES_PER_DAY:
            raise ValueError(
                f"LocalDay.instant reads a minute of the day from 0 to {MINUTES_PER_DAY - 1}: got {minute_of_day}"
            )
        reaching = np.flatnonzero(self.minute_of_day() >= minute_of_day)
        if reaching.size == 0:
            raise ValueError(
                f"No row of {self.date.isoformat()} reads minute {minute_of_day} of the day or later"
            )
        return self.rows[reaching[0]]


@dataclass(frozen=True)
class SimulationWindow:
    """The calendar days a simulated series covers, its first and last local dates both counted; how long each of its rows lasts; and its clock's zone name, None for a naive index.

    A yearly figure is a window total times annualisation_scale; rows() is the series' index, and local_days() splits its rows by date.
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

    @classmethod
    def of_index(cls, index: pd.Index) -> "SimulationWindow":
        """The window index describes: its first and last rows' dates on its own clock, the cadence its rows are spaced at, and its zone's name.

        Raises:
            ValueError: If index is not a DatetimeIndex, naming its type and dtype; if it is
                empty; if it has one row and no fixed-duration freq; or if its rows are not
                evenly spaced, naming the first position whose gap differs and both gaps.
        """
        if not isinstance(index, pd.DatetimeIndex):
            raise ValueError(
                "SimulationWindow.of_index reads a DatetimeIndex: "
                f"got {type(index).__name__} of dtype {index.dtype}"
            )
        if len(index) == 0:
            raise ValueError("SimulationWindow.of_index needs at least one row: got an empty index")
        return cls(
            first_day=index[0].date(),
            last_day=index[-1].date(),
            cadence=_cadence(index),
            timezone=None if index.tz is None else str(index.tz),
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

    def row_energy_kwh(self, power_kw: pd.Series) -> pd.Series:
        """Each row's kWh of a kW series on this window's rows: its kW times the hours the row lasts."""
        return power_kw * self.step_hours

    def energy_kwh(self, power_kw: pd.Series) -> float:
        """The kWh a kW series on this window's rows delivers: its rows' kWh summed."""
        return float(self.row_energy_kwh(power_kw).sum())

    def rows(self) -> pd.DatetimeIndex:
        """The window's rows: from its first day's first instant up to, not including, the first instant after its last day, at its cadence, on its clock, at microsecond resolution, the resolution of the timedelta its cadence is.

        Raises:
            ValueError: If the cadence does not divide one hour, naming it.
        """
        return self._rows_over(self._day_starts())

    def local_days(self) -> Iterator[LocalDay]:
        """One LocalDay per date from first_day to last_day, in order, splitting rows() at each date's first instant.

        Raises:
            ValueError: If the cadence does not divide one hour, naming it, when called rather than on the first next().
        """
        starts = self._day_starts()
        rows = self._rows_over(starts)
        bounds = itertools.pairwise(rows.searchsorted(starts))
        return (
            LocalDay(self.first_day + timedelta(days=offset), rows[begin:end])
            for offset, (begin, end) in enumerate(bounds)
        )

    def _rows_over(self, day_starts: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """The rows from the first of day_starts up to, not including, the last, at the window's cadence, at microsecond resolution."""
        return pd.date_range(
            day_starts[0], day_starts[-1], freq=pd.Timedelta(self.cadence), inclusive="left", unit="us"
        )

    def _day_starts(self) -> pd.DatetimeIndex:
        """Each date's first instant on the window's clock, from first_day to the day after last_day; the one place the window is checked for its rows.

        A date's first instant is its local midnight; where the clocks skip midnight, the instant they jump to; and where they repeat it, the first 00:00, the earlier of its two readings, whichever of them the zone counts as daylight saving time. A window with no zone has 24-hour days.

        Raises:
            ValueError: If the cadence does not divide one hour, naming it.
        """
        if timedelta(hours=1) % self.cadence != timedelta(0):
            raise ValueError(
                "SimulationWindow's rows need a cadence that divides one hour, so that every local day, "
                f"23, 24 or 25 hours long, holds whole rows: got cadence={self.cadence!r}, "
                f"{self.step_minutes:g} minutes"
            )
        midnights = pd.date_range(
            datetime.combine(self.first_day, time.min), periods=self.days + 1, freq="D", unit="us"
        )
        if self.timezone is None:
            return midnights
        read_as_dst, read_as_standard = (
            midnights.tz_localize(
                self.timezone, ambiguous=np.full(len(midnights), as_dst), nonexistent="shift_forward"
            )
            for as_dst in (True, False)
        )
        return read_as_dst.where(read_as_dst <= read_as_standard, read_as_standard)


def _cadence(index: pd.DatetimeIndex) -> timedelta:
    """How long each row of index lasts: its freq when that is a fixed duration, else the one gap between its rows in absolute time."""
    if _is_fixed_duration(index.freq):
        return _as_timedelta(pd.Timedelta(index.freq))
    if len(index) == 1:
        raise ValueError(
            "SimulationWindow.of_index cannot read a cadence from one row without a fixed-duration freq: "
            f"got {index[0]} with freq {index.freq}"
        )
    gaps = np.diff(index.asi8)
    uneven = np.flatnonzero(gaps != gaps[0])
    if uneven.size:
        first_uneven = int(uneven[0])
        raise ValueError(
            "SimulationWindow.of_index needs evenly spaced rows: "
            f"the gap before position {first_uneven + 1} is {_duration(gaps[first_uneven], index.unit)}, "
            f"where the first gap is {_duration(gaps[0], index.unit)}"
        )
    return _as_timedelta(_duration(gaps[0], index.unit))


def _is_fixed_duration(freq: object) -> bool:
    """Whether freq lasts the same absolute time wherever it falls: a Tick, but never a Day, which pandas 2 counts as a Tick though a zoned index's days run 23 or 25 hours across a clock change."""
    return isinstance(freq, pd.offsets.Tick) and not isinstance(freq, pd.offsets.Day)


def _duration(count: int, unit: str) -> pd.Timedelta:
    """count ticks of unit, the resolution an index's asi8 counts in, as a duration."""
    return pd.Timedelta(int(count), unit=unit)


def _as_timedelta(duration: pd.Timedelta) -> timedelta:
    """duration as the standard library's timedelta, the only kind a window holds."""
    converted: timedelta = duration.to_pytimedelta()
    return converted
