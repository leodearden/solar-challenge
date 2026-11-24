# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electric vehicle charging configuration and load profile generation."""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias, TypeVar

import numpy as np
import pandas as pd

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval, as_finite_float, as_whole_number, read_field
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR

_MinuteFlags: TypeAlias = np.ndarray[tuple[int], np.dtype[np.bool_]]

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
    """Smart charging scheduling strategies.

    - NONE: Dumb charging - start immediately on arrival
    - SOLAR: Solar-aware - shift charging to daylight hours
    - OFF_PEAK: Off-peak tariff - shift charging to the home tariff's cheap minutes
    """

    NONE = "none"
    SOLAR = "solar"
    OFF_PEAK = "off_peak"

    @classmethod
    def parse(cls, value: object, *, field: str) -> "SmartChargingMode":
        """Return the mode *value* names, refusing any other value as :func:`_member_named` does."""
        return _member_named(cls, value, field=field)


_PREFERRED_WINDOWS: dict[SmartChargingMode, tuple[tuple[int, int], ...]] = {
    SmartChargingMode.NONE: (),
    SmartChargingMode.SOLAR: ((10 * MINUTES_PER_HOUR, 16 * MINUTES_PER_HOUR),),
}
"""The preferred charging windows of none and solar, the modes that read no tariff, as [start, end) minutes of the day; generate_ev_charging_profile's docstring states them as clock times. Off_peak prefers its tariff's cheap minutes."""

_OFF_PEAK_WITHOUT_A_TARIFF = (
    "smart_charging_mode 'off_peak' charges the EV in the tariff's cheap periods, "
    "but the home has no tariff; add a tariff or use smart_charging_mode 'none'"
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


def require_tariff_for_smart_charging(ev_config: EVConfig, tariff: TariffConfig | None) -> None:
    """Refuse an EV whose smart charging mode reads the tariff, off_peak, when there is no tariff to read, by reading its preferred minutes as its charging profile does.

    Raises:
        ConfigurationError: ev_config's smart_charging_mode is 'off_peak' and tariff is None.
    """
    _preferred_minutes(SmartChargingMode(ev_config.smart_charging_mode), tariff)


def _preferred_minutes(mode: SmartChargingMode, tariff: TariffConfig | None) -> _MinuteFlags:
    """One flag for each minute of the day, set where *mode* prefers to charge: off_peak at *tariff*'s cheap minutes, the other modes in their _PREFERRED_WINDOWS row.

    Raises:
        ConfigurationError: *mode* is off_peak and *tariff* is None; this is require_tariff_for_smart_charging's refusal.
    """
    preferred = np.zeros(MINUTES_PER_DAY, dtype=np.bool_)
    if mode is SmartChargingMode.OFF_PEAK:
        if tariff is None:
            raise ConfigurationError(_OFF_PEAK_WITHOUT_A_TARIFF)
        preferred[list(tariff.cheap_minutes_of_day)] = True
        return preferred
    for start, end in _PREFERRED_WINDOWS[mode]:
        preferred[start:end] = True
    return preferred


def _earliest_best_start(preferred: _MinuteFlags, charge_minutes: int) -> int:
    """The offset of the earliest run of *charge_minutes* flags in *preferred* that holds the most set flags."""
    covered = np.concatenate(([0], np.cumsum(preferred)))
    coverage = covered[charge_minutes:] - covered[: covered.size - charge_minutes]
    return int(np.argmax(coverage))


def _daily_session(config: EVConfig, preferred: _MinuteFlags) -> range:
    """The minutes of one day's charging session, counted from the midnight before arrival, covering as many of the day's *preferred* minutes as it can."""
    arrival = config.arrival_hour * MINUTES_PER_HOUR
    stay_minutes = round(config.get_available_charging_hours() * MINUTES_PER_HOUR)
    hours_needed = config.required_charge_kwh / config.get_charger_power_kw()
    charge_minutes = min(math.ceil(hours_needed * MINUTES_PER_HOUR), stay_minutes)
    stay = (arrival + np.arange(stay_minutes)) % MINUTES_PER_DAY
    start = arrival + _earliest_best_start(preferred[stay], charge_minutes)
    return range(start, start + charge_minutes)


def generate_ev_charging_profile(
    config: EVConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str | None = "Europe/London",
    *,
    tariff: TariffConfig | None = None,
) -> pd.Series:
    """Generate EV charging load profile.

    Each day of the period the car is home from ``arrival_hour`` until
    ``departure_hour``, the next day when ``departure_hour`` is not after
    ``arrival_hour``. It charges in one unbroken session at the charger's full
    power, for as many whole minutes as ``required_charge_kwh`` needs. The
    session lies inside that stay, so the charge is always delivered before
    departure. Of all such sessions it is the one covering the most minutes the
    mode prefers, on either day of an overnight stay, and the earliest on a
    tie. "solar" prefers 10:00-16:00, the window ``_PREFERRED_WINDOWS`` holds.
    "off_peak" prefers the tariff's cheap minutes,
    ``TariffConfig.cheap_minutes_of_day``. "none" prefers no time, so it
    charges from arrival, and so does "off_peak" on a tariff with no cheap
    minute, such as a flat rate. A stay holding one window too short for the
    charge uses it whole, charging the rest just before it opens, or from
    arrival when that is later.

    The period is laid out as 1,440 minutes a day from its first midnight, so
    after a clock change inside it the times above run an hour off the wall
    clock. It holds only its own days' sessions: one still running when the
    period ends is cut there, and the first morning has none from the evening
    before.

    Args:
        config: EV configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: Timezone for the simulation, None for a naive index
        tariff: The home's tariff, whose cheap minutes an "off_peak" EV charges
            in; the other modes do not read it

    Returns:
        Time series of charging power in kW at 1-minute resolution

    Raises:
        ConfigurationError: The EV's smart_charging_mode is "off_peak" and
            there is no tariff, the refusal require_tariff_for_smart_charging
            makes, before anything is built.
    """
    preferred = _preferred_minutes(SmartChargingMode(config.smart_charging_mode), tariff)
    date_range = pd.date_range(
        start=start_date,
        end=end_date,
        freq="D",
        tz=timezone,
    )
    n_minutes = len(date_range) * MINUTES_PER_DAY
    session = _daily_session(config, preferred)

    # One spare day holds the last day's session whole, until the cut below.
    power_kw = np.zeros(n_minutes + MINUTES_PER_DAY, dtype=np.float64)
    for day_start in range(0, n_minutes, MINUTES_PER_DAY):
        power_kw[day_start + session.start : day_start + session.stop] = config.get_charger_power_kw()

    time_index = pd.date_range(
        start=start_date,
        periods=n_minutes,
        freq="1min",
        tz=timezone,
    )
    return pd.Series(power_kw[:n_minutes], index=time_index, name=config.name or "EV Charging")
