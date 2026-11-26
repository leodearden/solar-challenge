# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse the web dashboard's flat simulation-parameter dicts into engine configuration."""

from collections.abc import Callable, Mapping
from datetime import date
from functools import partial
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd

from solar_challenge.battery import BatteryConfig, has_battery, require_valid_power_limit
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.number_fields import as_finite_float, as_whole_number
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import (
    PV_CAPACITY_KW_WHEN_OMITTED,
    parse_dispatch_strategy_config,
    parse_heat_pump_block,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    MAX_WINDOW_DAYS,
    WINDOW_DAYS,
    days_window,
)
from solar_challenge.web.request_boundary import (
    WEB_DEFAULT_LOCATION,
    present_fields,
    refuse_unrecognised_keys,
    read_boolean,
    read_location,
    read_optional_string,
    require_json_object,
)

_HOME_CONFIG = "Home config"

# The window fields parse_date_range reads, in the order a refusal of days sent with dates names the dates.
_DATE_RANGE_FIELDS = ("days", "start", "end")

#: The keys of a request body parse_date_range reads.
DATE_RANGE_KEYS: frozenset[str] = frozenset(_DATE_RANGE_FIELDS)

# The PV settings a home body sends under PVConfig's own field names.
_PV_SETTING_KEYS = ("azimuth", "tilt", "system_age_years", "degradation_rate_per_year", "system_losses")

#: The top-level keys of a home config: those parse_home_config and parse_date_range read.
HOME_CONFIG_KEYS: frozenset[str] = frozenset({
    "pv_kw",
    *_PV_SETTING_KEYS,
    "battery_kwh",
    "max_charge_kw",
    "max_discharge_kw",
    "efficiency_pct",
    "dispatch_strategy",
    "consumption_kwh",
    "occupants",
    "stochastic",
    "heat_pump",
    "tariff",
    "seg",
    "location",
    "name",
}) | DATE_RANGE_KEYS

# The home fields whose value when not sent is the web's own, as the wire value its reader reads.
_HOME_WEB_DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "location": WEB_DEFAULT_LOCATION,
    # A web run is repeatable by default: the dashboard takes no load seed and compares stored
    # runs, so a body that does not ask for the stochastic model gets the deterministic profile.
    # LoadConfig's use_stochastic=True is the library's default.
    "stochastic": False,
})


def read_iso_date(value: Any, field: str) -> date:
    """Read *value*, the setting named *field*, as an ISO 8601 calendar date (``YYYY-MM-DD``).

    Raises:
        ConfigurationError: If *value* is not a string date.fromisoformat reads; the
            error names *field* and the value.
    """
    if not isinstance(value, str):
        raise _not_an_iso_date(value, field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _not_an_iso_date(value, field) from exc


def _not_an_iso_date(value: object, field: str) -> ConfigurationError:
    return ConfigurationError.must_be(field, "an ISO 8601 date (YYYY-MM-DD)", got=value)


def _read_date(value: Any, field: str, default: date) -> date:
    """Read a request body's ``field`` as an ISO 8601 calendar date; *value* is None for a date not sent, which reads as ``default``.

    Raises:
        ConfigurationError: From :func:`read_iso_date`, for a value that is not an ISO
            8601 date, naming the field and the value sent.
    """
    if value is None:
        return default
    return read_iso_date(value, field)


def refuse_reversed_or_overlong_window(
    start: date, end: date, *, start_field: str, end_field: str
) -> None:
    """Refuse a window that ends before it starts or spans more than MAX_WINDOW_DAYS days, naming *start_field* and *end_field*."""
    if end < start:
        raise ConfigurationError(
            f"{end_field} must not be before {start_field}, "
            f"got {start_field} '{start}' and {end_field} '{end}'"
        )
    span = (end - start).days + 1
    if span > MAX_WINDOW_DAYS:
        raise ConfigurationError(
            f"{start_field} to {end_field} must span at most {MAX_WINDOW_DAYS} days, "
            f"got {start_field} '{start}' and {end_field} '{end}', {span:,} days"
        )


def _window_sent(data: Mapping[str, Any]) -> dict[str, Any]:
    """The window fields *data*, a request body, sends as present_fields reads it, keyed by field in _DATE_RANGE_FIELDS order."""
    fields = present_fields(data)
    return {field: fields[field] for field in _DATE_RANGE_FIELDS if field in fields}


def _refuse_days_with_dates(days: Any, dates: Mapping[str, Any]) -> None:
    """Refuse a *days* sent with any of *dates*: days and start/end are two ways to set one window, so a body may send only one."""
    if days is not None and dates:
        named = " and ".join(f"{field} {value!r}" for field, value in dates.items())
        raise ConfigurationError(f"days must not be sent with start or end, got days {days!r} with {named}")


def parse_date_range(data: Mapping[str, Any]) -> tuple[str, str]:
    """Extract a (start, end) date-string pair from a JSON request body.

    A body sets its window in one of two ways, never both:

    - ``days``: a whole number from 1 to
      :data:`~solar_challenge.web.fleet_components.MAX_DAYS`, run as
      :func:`~solar_challenge.web.fleet_components.days_window` runs it.
      :data:`~solar_challenge.web.fleet_components.FULL_YEAR_DAYS_SENTINEL`,
      the largest, is the sentinel for the full year,
      :data:`~solar_challenge.timebase.DEFAULT_FIRST_DAY` to
      :data:`~solar_challenge.timebase.DEFAULT_LAST_DAY`. Any other runs that
      many days from :data:`~solar_challenge.timebase.SHORT_WINDOW_START`, on
      past DEFAULT_LAST_DAY when it is longer than the rest of that year.
    - ``start`` / ``end``: ISO 8601 dates (``YYYY-MM-DD``); one not sent reads
      as :data:`DEFAULT_FIRST_DAY` / :data:`DEFAULT_LAST_DAY`.

    A ``days``, ``start`` or ``end`` sent as null or ``""`` reads as not sent
    (:func:`~solar_challenge.web.request_boundary.present_fields`).

    Whichever way sets it, the window must end on or after its start and span
    at most :data:`~solar_challenge.web.fleet_components.MAX_WINDOW_DAYS` days.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of ``(start, end)`` as ``"YYYY-MM-DD"`` strings, ``end`` inclusive.

    Raises:
        ConfigurationError: If ``days`` is sent with a start or end, naming days and
            each of them as sent; if ``days`` is not a whole number from 1 to
            MAX_DAYS, or if ``start`` or ``end`` is not an ISO 8601
            date, naming the field and the value sent; or if the window ends
            before it starts or spans more than MAX_WINDOW_DAYS days, naming
            start and end as read.
    """
    sent = _window_sent(data)
    days = sent.pop("days", None)
    _refuse_days_with_dates(days, sent)
    if days is not None:
        start, end = days_window(as_whole_number(days, "days", within=WINDOW_DAYS))
    else:
        start = _read_date(sent.get("start"), "start", DEFAULT_FIRST_DAY)
        end = _read_date(sent.get("end"), "end", DEFAULT_LAST_DAY)
    refuse_reversed_or_overlong_window(start, end, start_field="start", end_field="end")
    return start.isoformat(), end.isoformat()


def with_default_days(data: Mapping[str, Any], days: int) -> dict[str, Any]:
    """A copy of *data*, a request body, with days=*days* when the body sends no window of its own.

    No window means none of the window fields parse_date_range reads sent. A
    body that sends one is returned as sent, so the window it sends is read, or
    refused, as sent.
    """
    if _window_sent(data):
        return dict(data)
    return {**data, "days": days}


def parse_seg_tariff(seg_data: object) -> SEGTariff | None:
    """Read a request body's ``seg`` value with :func:`~solar_challenge.scenario_blocks.parse_seg_rate`'s grammar.

    ``None`` means no SEG.  A value that grammar refuses raises its ``ConfigurationError``,
    the refusal every web caller answers with HTTP 400.
    """
    rate = parse_seg_rate(seg_data)
    if rate is None:
        return None
    return SEGTariff(name="", rate_pence_per_kwh=rate)


def _read_power_limit(value: Any, direction: Literal["charge", "discharge"]) -> float:
    """Read a home body's maximum ``direction`` power, its ``max_<direction>_kw``: a finite number, refused naming that field, that a battery accepts."""
    kw = as_finite_float(value, f"max_{direction}_kw")
    require_valid_power_limit(kw, direction)
    return kw


def _read_efficiency(value: Any) -> float | None:
    """Read a home body's round-trip efficiency percentage as the round-trip fraction BatteryConfig.with_round_trip takes.

    None, not sent, is unset; any other value must be a finite number, refused naming efficiency_pct,
    and a percentage outside (0, 100] is refused in the units sent.
    """
    if value is None:
        return None
    efficiency_pct = as_finite_float(value, "efficiency_pct")
    if not (0 < efficiency_pct <= 100):
        raise ConfigurationError(f"Efficiency must be between 0 and 100, got {efficiency_pct}")
    return efficiency_pct / 100


# How a home body's sent fields reach a dataclass: each body key's dataclass field and the reader of its value.
_SettingReaders = Mapping[str, tuple[str, Callable[[Any], Any]]]


def _sent_settings(params: Mapping[str, Any], readers: _SettingReaders) -> dict[str, Any]:
    """The keyword arguments a dataclass receives from *params*, a home body's present fields.

    Each key of *readers* that *params* sends sets its dataclass field to the value its reader
    reads, in *readers*' order, so a refused value is refused there; a key not sent sets
    nothing, leaving the dataclass's own default.
    """
    return {field: read(params[key]) for key, (field, read) in readers.items() if key in params}


# The PV settings, sent under PVConfig's own field names and passed as sent: PVConfig refuses a
# value it cannot hold, naming it.
_PV_SETTINGS: _SettingReaders = MappingProxyType({key: (key, lambda value: value) for key in _PV_SETTING_KEYS})

_LOAD_SETTINGS: _SettingReaders = MappingProxyType({
    "occupants": ("household_occupants", partial(as_whole_number, field="occupants")),
    "consumption_kwh": (
        "annual_consumption_kwh",
        partial(as_finite_float, field="consumption_kwh", within=FLEET_COMPONENTS["load"].value_range),
    ),
    "stochastic": ("use_stochastic", partial(read_boolean, field="stochastic")),
})

# The battery settings BatteryConfig takes; efficiency_pct, a round trip, is applied by with_round_trip.
_BATTERY_SETTINGS: _SettingReaders = MappingProxyType({
    "max_charge_kw": ("max_charge_kw", partial(_read_power_limit, direction="charge")),
    "max_discharge_kw": ("max_discharge_kw", partial(_read_power_limit, direction="discharge")),
    "dispatch_strategy": ("dispatch_strategy", parse_dispatch_strategy_config),
})


def _parse_battery(params: Mapping[str, Any], capacity_kwh: float | None) -> BatteryConfig | None:
    """Read the battery a home body describes, its ``capacity_kwh`` read within the battery component's value_range: none when that is not sent (None) or 0.

    Each setting is read whatever ``capacity_kwh`` is, so a value a battery refuses is
    refused without one too; a setting not sent is unset, leaving BatteryConfig's default.
    """
    settings = _sent_settings(params, _BATTERY_SETTINGS)
    round_trip = _read_efficiency(params.get("efficiency_pct"))
    if capacity_kwh is not None and has_battery(capacity_kwh, "battery_kwh"):
        battery = BatteryConfig(capacity_kwh=capacity_kwh, **settings)
        return battery if round_trip is None else battery.with_round_trip(round_trip)
    return None


def _read_sent_number(params: Mapping[str, Any], field: str, component: str) -> float | None:
    """Read *params*' *field* as a finite number within the *component* fleet component's value_range; None when it is not sent."""
    if field not in params:
        return None
    return as_finite_float(params[field], field, within=FLEET_COMPONENTS[component].value_range)


def parse_home_config(data: object) -> tuple[HomeConfig, pd.Timestamp, pd.Timestamp, str | None]:
    """Parse JSON request body into HomeConfig and date range.

    A top-level field sent as null or "" (a cleared input) reads as not sent
    (:func:`~solar_challenge.web.request_boundary.present_fields`), once the
    body's keys are checked, so an unrecognised key is refused whatever it holds.

    A field not sent takes its engine dataclass's default, PVConfig's,
    LoadConfig's, BatteryConfig's or HomeConfig's, but for the web's own two:
    location, Bristol, and stochastic, off, a web run being repeatable. A pv_kw
    not sent is :data:`~solar_challenge.scenario_blocks.PV_CAPACITY_KW_WHEN_OMITTED`,
    as a pv: block's omitted capacity is; a battery_kwh not sent is no battery;
    and a consumption_kwh not sent is the TDCV estimate for the occupants.

    Args:
        data: The home config, a parsed JSON value that must be an object.

    Returns:
        Tuple of (HomeConfig, start_date, end_date, name). The name is the body's, None
        when it sends none; the HomeConfig takes it, and is unnamed ("") when there is none.

    Raises:
        ConfigurationError: If *data* is not a JSON object (the error names the type
            received), if it has a top-level key outside the recognised set
            (the error names each such key), if a float field is a boolean
            or not a finite number float() reads, or occupants is not a
            whole number, a boolean included (the error names the field and
            the value sent), if its days, start or end is one
            parse_date_range refuses, if location is one read_location
            refuses (the error is its own refusal), if pv_kw, battery_kwh or
            a sent consumption_kwh lies outside its fleet component's
            value_range, PV's, the battery's or the load's (the error names
            the field, the range and the value sent). A nested block sent (heat_pump, seg,
            tariff or dispatch_strategy) is read by the block's grammar, and
            a block that grammar refuses, one that is not a mapping or
            carries an unrecognised key included, raises the grammar's own
            refusal: parse_heat_pump_block's for heat_pump. The battery
            settings (max_charge_kw, max_discharge_kw, efficiency_pct and
            dispatch_strategy) are read, and refused, whatever battery_kwh
            is. An azimuth, tilt,
            system_age_years, degradation_rate_per_year or system_losses
            that is not a finite number in PVConfig's range raises
            PVConfig's own refusal, naming it. A name that is not a JSON
            string, or text holding a lone surrogate, raises read_string's
            refusal naming name; a stochastic that is not true or false
            raises read_boolean's, naming stochastic.
    """
    data = require_json_object(data, _HOME_CONFIG)
    refuse_unrecognised_keys(data, HOME_CONFIG_KEYS, _HOME_CONFIG)
    params = {**_HOME_WEB_DEFAULTS, **present_fields(data)}
    pv_kw = as_finite_float(
        params.get("pv_kw", PV_CAPACITY_KW_WHEN_OMITTED), "pv_kw", within=FLEET_COMPONENTS["pv"].value_range
    )
    battery_kwh = _read_sent_number(params, "battery_kwh", "battery")
    load_config = LoadConfig(**_sent_settings(params, _LOAD_SETTINGS))
    name = read_optional_string(params.get("name"), "name")

    start, end = parse_date_range(params)

    loc = read_location(params["location"])

    pv_config = PVConfig(capacity_kw=pv_kw, **_sent_settings(params, _PV_SETTINGS))

    battery_config = _parse_battery(params, battery_kwh)

    heat_pump_config = parse_heat_pump_block(params.get("heat_pump"))

    tariff_config = parse_tariff_config(params.get("tariff"))

    seg_tariff = parse_seg_tariff(params.get("seg"))

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        heat_pump_config=heat_pump_config,
        tariff_config=tariff_config,
        seg_tariff=seg_tariff,
        location=loc,
        name=name or "",
    )

    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    return home_config, start_date, end_date, name
