# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electric vehicle charging configuration and load profile generation."""

import itertools
import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TypeAlias, TypeVar

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval, as_finite_float, as_whole_number, read_field
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR, LocalDay, SimulationWindow, minutes_of_day

_Word = TypeVar("_Word", bound=StrEnum)


def _member_named(vocabulary: type[_Word], value: object, *, field: str) -> _Word:
    """The member of *vocabulary* that *value* names: a member's value, exactly, or a member itself.

    Raises:
        ConfigurationError: If *value* is anything else; the message names *field*,
            the members' values in order and *value*.
    """
    if isinstance(value, str):
        try:
            return vocabulary(value)
        except ValueError:
            pass
    raise ConfigurationError.must_be(
        field, f"one of {', '.join(member.value for member in vocabulary)}", got=value
    )


class EVChargerType(StrEnum):
    """Standard UK domestic EV charger types, each valued as its rating's label.

    - SLOW: 3.6 kW single-phase (slow/granny charger)
    - FAST: 7 kW single-phase (typical home wallbox)
    - RAPID: 22 kW three-phase (high-power home installation)
    """

    SLOW = "3.6kW"
    FAST = "7kW"
    RAPID = "22kW"

    @classmethod
    def parse(cls, value: object, *, field: str) -> "EVChargerType":
        """Return the charger type *value* names, refusing any other value as :func:`_member_named` does."""
        return _member_named(cls, value, field=field)

    @property
    def power_kw(self) -> float:
        """The charger's power rating in kW."""
        return _CHARGER_POWER_KW[self]


_CHARGER_POWER_KW: dict[EVChargerType, float] = {
    EVChargerType.SLOW: 3.6,
    EVChargerType.FAST: 7.0,
    EVChargerType.RAPID: 22.0,
}

CHARGER_TYPES: tuple[str, ...] = tuple(charger.value for charger in EVChargerType)


class SmartChargingMode(StrEnum):
    """Where in each stay the EV charges.

    - NONE: from arrival
    - SOLAR: in the run of the stay with the most of the home's PV generation
    - OFF_PEAK: in the run of the stay with the most of the home tariff's cheap minutes
    """

    NONE = "none"
    SOLAR = "solar"
    OFF_PEAK = "off_peak"

    @classmethod
    def parse(cls, value: object, *, field: str) -> "SmartChargingMode":
        """Return the mode *value* names, refusing any other value as :func:`_member_named` does."""
        return _member_named(cls, value, field=field)


_OFF_PEAK_WITHOUT_A_TARIFF = (
    "smart_charging_mode 'off_peak' charges the EV in the tariff's cheap periods, "
    "but the home has no tariff; add a tariff or use smart_charging_mode 'none'"
)

_SOLAR_WITHOUT_GENERATION = (
    "smart_charging_mode 'solar' charges the EV in the run of its stay with the most PV generation, "
    "but no generation_kw was given; pass the home's PV generation or use smart_charging_mode 'none'"
)


_HOUR_OF_DAY = Interval(0, 23)


@dataclass(frozen=True)
class EVConfig:
    """Configuration for electric vehicle charging.

    Construction reads the hours as whole numbers and the required charge as a finite
    number, and the charger type and smart charging mode as their EVChargerType and
    SmartChargingMode members, and holds what it read; a member reads as its string. It
    refuses a value outside its range, a charger type or smart charging mode that names no
    member, by the field's name and its allowed values, or a charge the stay cannot
    deliver, with a ConfigurationError.

    Attributes:
        charger_type: Charger power rating (3.6kW, 7kW, or 22kW), held as its EVChargerType
        arrival_hour: Hour of day when EV arrives home (0-23), default 18, 6pm
        departure_hour: Hour of day when EV departs (0-23), default 7am
        required_charge_kwh: Energy required per day in kWh, default 35 kWh
            (typical UK EV doing ~100 miles/day at 3.5 miles/kWh)
        smart_charging_mode: Charging schedule optimization strategy, held as its
            SmartChargingMode
        name: Optional identifier for the EV configuration
    """

    charger_type: str
    arrival_hour: int = 18
    departure_hour: int = 7
    required_charge_kwh: float = 35.0
    smart_charging_mode: str = "none"
    name: str = ""

    def __post_init__(self) -> None:
        """Read each number setting, then the charger type and mode as their members, then refuse a charge the stay cannot deliver."""
        read_field(self, "arrival_hour", as_whole_number, _HOUR_OF_DAY)
        read_field(self, "departure_hour", as_whole_number, _HOUR_OF_DAY)
        read_field(self, "required_charge_kwh", as_finite_float, Interval(0, 100, low_open=True))
        object.__setattr__(self, "charger_type", EVChargerType.parse(self.charger_type, field="charger_type"))
        object.__setattr__(
            self,
            "smart_charging_mode",
            SmartChargingMode.parse(self.smart_charging_mode, field="smart_charging_mode"),
        )

        charger_power_kw = self.get_charger_power_kw()
        available_hours = self._calculate_available_hours()
        max_charge_kwh = charger_power_kw * available_hours

        if self.required_charge_kwh > max_charge_kwh:
            raise ConfigurationError(
                f"Cannot deliver {self.required_charge_kwh} kWh with {self.charger_type} "
                f"charger in {available_hours:.1f} hours (max: {max_charge_kwh:.1f} kWh). "
                "Either reduce required_charge_kwh or adjust arrival/departure hours."
            )

    def _calculate_available_hours(self) -> float:
        """Calculate available charging hours between arrival and departure.

        Returns:
            Available hours (handles overnight charging)
        """
        if self.departure_hour > self.arrival_hour:
            # Same day: e.g., arrive 8am, depart 5pm = 9 hours
            return float(self.departure_hour - self.arrival_hour)
        else:
            # Overnight: e.g., arrive 6pm (18), depart 7am (7) = 13 hours
            return float(24 - self.arrival_hour + self.departure_hour)

    def get_charger_power_kw(self) -> float:
        """Get charger power rating in kW.

        Returns:
            Charger power in kW
        """
        return EVChargerType(self.charger_type).power_kw

    def get_available_charging_hours(self) -> float:
        """Get available charging window in hours.

        Returns:
            Available charging hours between arrival and departure
        """
        return self._calculate_available_hours()


def _off_peak_tariff(tariff: TariffConfig | None) -> TariffConfig:
    """*tariff*, whose cheap minutes an off_peak EV charges in.

    Raises:
        ConfigurationError: If tariff is None.
    """
    if tariff is None:
        raise ConfigurationError(_OFF_PEAK_WITHOUT_A_TARIFF)
    return tariff


def require_tariff_for_smart_charging(ev_config: EVConfig, tariff: TariffConfig | None) -> None:
    """Refuse an EV whose smart charging mode reads the tariff, off_peak, when there is no tariff to read.

    Raises:
        ConfigurationError: ev_config's smart_charging_mode is 'off_peak' and tariff is None.
    """
    if SmartChargingMode(ev_config.smart_charging_mode) is SmartChargingMode.OFF_PEAK:
        _off_peak_tariff(tariff)


RowWeights: TypeAlias = Callable[[pd.DatetimeIndex], np.ndarray]
"""A preference weight for each of the rows it is given, in their order: a session takes the run of its stay whose weights sum highest."""


def _no_preference(rows: pd.DatetimeIndex) -> np.ndarray:
    """A weight of 0 on every row, so every run of a stay ties and the earliest wins."""
    return np.zeros(len(rows))


def _cheap_minutes(tariff: TariffConfig) -> RowWeights:
    """A weight of 1 on each row whose local minute of the day is one of *tariff*'s cheap minutes, 0 on the others."""
    cheap = np.zeros(MINUTES_PER_DAY)
    cheap[sorted(tariff.cheap_minutes_of_day)] = 1.0

    def weights(rows: pd.DatetimeIndex) -> np.ndarray:
        on_rows: np.ndarray = cheap[minutes_of_day(rows)]
        return on_rows

    return weights


def _row_weights(config: EVConfig, tariff: TariffConfig | None, generation_kw: RowWeights | None) -> RowWeights:
    """The weights *config*'s smart charging mode places its sessions by: none, no preference; off_peak, *tariff*'s cheap minutes; solar, *generation_kw*.

    Raises:
        ConfigurationError: off_peak with no tariff, require_tariff_for_smart_charging's refusal; or solar with no generation_kw.
    """
    mode = SmartChargingMode(config.smart_charging_mode)
    if mode is SmartChargingMode.OFF_PEAK:
        return _cheap_minutes(_off_peak_tariff(tariff))
    if mode is SmartChargingMode.SOLAR:
        if generation_kw is None:
            raise ConfigurationError(_SOLAR_WITHOUT_GENERATION)
        return generation_kw
    return _no_preference


def _weights_on(rows: pd.DatetimeIndex, weights_on: RowWeights) -> np.ndarray:
    """The weights *weights_on* gives *rows*, as floats.

    Raises:
        ValueError: If it gives other than one weight for each of *rows*, naming both counts, or a weight that
            is not a finite number, naming the first such row and its weight.
    """
    weights = np.asarray(weights_on(rows), dtype=np.float64)
    if weights.shape != (len(rows),):
        raise ValueError(
            f"The EV's row weights hold {weights.size} values for {len(rows)} rows: "
            "a RowWeights callable gives one weight for each row it is given"
        )
    not_finite = np.flatnonzero(~np.isfinite(weights))
    if not_finite.size:
        first = not_finite[0]
        raise ValueError(
            f"The EV's row weights hold {weights[first]} at {rows[first]}: "
            "a RowWeights callable gives a finite number for each row it is given"
        )
    return weights


@dataclass(frozen=True, eq=False)
class _DayOnRows:
    """One LocalDay's rows as the positions from *begin* in the rows of every day read with it, and their local minutes of the day.

    Compared by identity, as LocalDay is.
    """

    day: LocalDay
    begin: int
    minutes: np.ndarray

    def first_reading(self, minute_of_day: int) -> int:
        """The position of the row LocalDay.instant(minute_of_day) is: the day's first row whose local clock reads minute_of_day or later.

        Raises:
            ValueError: If no row of the day reads minute_of_day or later, naming the date and the minute.
        """
        reaching = np.flatnonzero(self.minutes >= minute_of_day)
        if reaching.size == 0:
            raise ValueError(f"No row of {self.day.date.isoformat()} reads minute {minute_of_day} of the day or later")
        return self.begin + int(reaching[0])


def _days_on_rows(days: Sequence[LocalDay], minutes: np.ndarray) -> list[_DayOnRows]:
    """Each of *days*, whose rows joined in order have the local minutes of the day *minutes*, as its positions in them."""
    begins = itertools.accumulate((len(day.rows) for day in days), initial=0)
    return [
        _DayOnRows(day, begin, minutes[begin : begin + len(day.rows)]) for day, begin in zip(days, begins, strict=False)
    ]


def _stays(config: EVConfig, days: Sequence[_DayOnRows]) -> Iterator[tuple[int, int]]:
    """The (arrival, departure) positions of the stay from each of *days* but the last, on the days' wall clock: departure is the next day's when departure_hour is not after arrival_hour."""
    overnight = config.departure_hour <= config.arrival_hour
    for arrival_day, next_day in itertools.pairwise(days):
        departure_day = next_day if overnight else arrival_day
        yield (
            arrival_day.first_reading(config.arrival_hour * MINUTES_PER_HOUR),
            departure_day.first_reading(config.departure_hour * MINUTES_PER_HOUR),
        )


_ROW_TOLERANCE = 1e-9
"""How far, in rows, a charge's row count may sit from a whole number and still be read as that whole number."""


@dataclass(frozen=True)
class _ChargeRows:
    """The rows one stay's charge takes: *whole* rows at the charger's rating, then one row at *fraction* of it when *fraction* is above 0."""

    whole: int
    fraction: float

    @property
    def count(self) -> int:
        """The rows the session spans, its fractional row included."""
        return self.whole + (1 if self.fraction > 0.0 else 0)


def _charge_rows(config: EVConfig, step_hours: float) -> _ChargeRows:
    """The rows of *step_hours* that deliver *config*'s required charge at its charger's rating."""
    rows_needed = config.required_charge_kwh / (config.get_charger_power_kw() * step_hours)
    whole = math.floor(rows_needed + _ROW_TOLERANCE)
    remainder = rows_needed - whole
    return _ChargeRows(whole, remainder if remainder > _ROW_TOLERANCE else 0.0)


def _session_kw(stay_weights: np.ndarray, charge: _ChargeRows, power_kw: float) -> np.ndarray:
    """Each row's kW in a stay of *stay_weights*' rows: its run of *charge*'s rows whose weights sum highest, the earliest on a tie, or every row at full power when the stay is shorter than the charge."""
    session = np.zeros(stay_weights.size)
    if charge.count > stay_weights.size:
        session[:] = power_kw
        return session
    start = int(np.argmax(sliding_window_view(stay_weights, charge.count).sum(axis=1)))
    session[start : start + charge.whole] = power_kw
    if charge.fraction > 0.0:
        session[start + charge.whole] = charge.fraction * power_kw
    return session


def _widened(window: SimulationWindow) -> SimulationWindow:
    """*window* with a day added either side: the day before holds the stay the first morning's session comes from, the day after its last stay's departure."""
    return SimulationWindow(
        window.first_day - timedelta(days=1), window.last_day + timedelta(days=1), window.cadence, window.timezone
    )


def generate_ev_charging_profile(
    config: EVConfig,
    window: SimulationWindow,
    *,
    tariff: TariffConfig | None = None,
    generation_kw: RowWeights | None = None,
) -> pd.Series:
    """The EV's charging power in kW on window.rows().

    The car is home for one stay from each date's ``arrival_hour`` on the window's wall
    clock until ``departure_hour``, on the next date when ``departure_hour`` is not after
    ``arrival_hour``. The stays run from the one arriving the day before the window to the
    one arriving on its last day, so the first morning holds the session of the evening
    before the window, and a session still running when the window ends is cut there. A
    clock change inside a stay shortens or lengthens it by the hour it skips or repeats.

    Each stay charges in one unbroken session at the charger's full power, on whole rows
    of the window's cadence and then one last row at the fraction of full power the rest
    of the charge needs, so it delivers exactly ``required_charge_kwh``. A stay too short
    for that, as a clock change can make one, charges on every one of its rows. Of the
    sessions that fit, it takes the one whose rows' weights sum highest, the earliest on a
    tie. "none" weighs every row alike, so it charges from arrival. "off_peak" weighs the
    tariff's cheap minutes, ``TariffConfig.cheap_minutes_of_day``, 1 and the others 0, so
    on a tariff with no cheap minute, such as a flat rate, it charges from arrival too.
    "solar" weighs each row by ``generation_kw``, the home's PV generation, not its surplus
    over the household's load.

    Args:
        config: EV configuration
        window: The calendar days, the cadence of their rows and their clock's zone
        tariff: The home's tariff, whose cheap minutes an "off_peak" EV charges in; the
            other modes do not read it
        generation_kw: The home's PV generation in kW on the rows it is given, which a
            "solar" EV charges in the most of; the other modes do not read it. It is asked
            once, for the rows from the day before the window to the day after it.

    Returns:
        The charging power in kW on window.rows(), named after the EV

    Raises:
        ConfigurationError: Before anything is built, for an "off_peak" EV with no
            tariff, the refusal require_tariff_for_smart_charging makes, or a "solar" EV
            with no generation_kw.
        ValueError: If generation_kw gives other than one weight for each row it is
            given, naming both counts, or a weight that is not a finite number, naming
            the first such row and its weight; or if the window's cadence does not
            divide one hour, as window.rows() refuses it.
    """
    weights_on = _row_weights(config, tariff, generation_kw)
    widened = _widened(window)
    widened_rows = widened.rows()
    weights = _weights_on(widened_rows, weights_on)
    days = _days_on_rows(list(widened.local_days()), minutes_of_day(widened_rows))
    charge = _charge_rows(config, window.step_hours)
    power_kw = np.zeros(len(widened_rows))
    for begin, end in _stays(config, days):
        power_kw[begin:end] += _session_kw(weights[begin:end], charge, config.get_charger_power_kw())
    rows = window.rows()
    begin = widened_rows.searchsorted(rows[0])
    return pd.Series(power_kw[begin : begin + len(rows)], index=rows, name=config.name or "EV Charging")
