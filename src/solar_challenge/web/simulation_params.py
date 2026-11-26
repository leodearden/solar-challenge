# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse the web dashboard's flat simulation-parameter dicts into engine configuration."""

from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd

from solar_challenge.battery import BatteryConfig, has_battery, require_valid_power_limit
from solar_challenge.errors import ConfigurationError
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.number_fields import as_finite_float, as_whole_number
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import (
    parse_dispatch_strategy_config,
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
    refuse_unencodable_text,
    refuse_unrecognised_keys,
    read_location,
    require_json_object,
)

_HOME_CONFIG = "Home config"

# Each parser's recognised top-level keys, and the value each reads as when absent.
_DATE_RANGE_DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "days": None,
    "start": "",
    "end": "",
})

#: The keys of a request body parse_date_range reads.
DATE_RANGE_KEYS: frozenset[str] = frozenset(_DATE_RANGE_DEFAULTS)

_HOME_CONFIG_DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "pv_kw": 4.0,
    "azimuth": 180,
    "tilt": 35,
    "system_age_years": 0.0,
    "degradation_rate_per_year": 0.005,
    "system_losses": None,
    "battery_kwh": 0.0,
    "max_charge_kw": None,
    "max_discharge_kw": None,
    "efficiency_pct": None,
    "consumption_kwh": None,
    "occupants": 3,
    "stochastic": False,
    "location": "bristol",
    "name": None,
    "dispatch_strategy": None,
    "heat_pump": None,
    "tariff": None,
    "seg": None,
})

#: The top-level keys of a home config: those parse_home_config and parse_date_range read.
_HOME_CONFIG_KEYS: frozenset[str] = frozenset(_HOME_CONFIG_DEFAULTS) | DATE_RANGE_KEYS


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
    """The window fields *data*, a request body, sends, keyed by field in _DATE_RANGE_DEFAULTS order.

    A null value, or the value _DATE_RANGE_DEFAULTS gives an absent field, is not sent.
    """
    return {
        field: data[field]
        for field, absent in _DATE_RANGE_DEFAULTS.items()
        if data.get(field) not in (None, absent)
    }


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

    A null ``days``, and an empty or null ``start`` or ``end``, read as not sent.

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


def _system_losses_setting(value: Any) -> dict[str, Any]:
    """The system_losses keyword PVConfig takes for a home body's system_losses *value*; null gives none, leaving PVConfig's default.

    Any other value passes as sent: PVConfig reads it, and refuses one that is not a finite number in its range, naming system_losses.
    """
    if value is None:
        return {}
    return {"system_losses": value}


def _read_power_limit(value: Any, direction: Literal["charge", "discharge"]) -> float | None:
    """Read a home body's maximum ``direction`` power, its ``max_<direction>_kw``: null is unset.

    Any other value must be a finite number, refused naming that field, that a battery accepts.
    """
    if value is None:
        return None
    kw = as_finite_float(value, f"max_{direction}_kw")
    require_valid_power_limit(kw, direction)
    return kw


def _read_efficiency(value: Any) -> float | None:
    """Read a home body's round-trip efficiency percentage as the round-trip fraction BatteryConfig.with_round_trip takes.

    Null is unset; any other value must be a finite number, refused naming efficiency_pct,
    and a percentage outside (0, 100] is refused in the units sent.
    """
    if value is None:
        return None
    efficiency_pct = as_finite_float(value, "efficiency_pct")
    if not (0 < efficiency_pct <= 100):
        raise ConfigurationError(f"Efficiency must be between 0 and 100, got {efficiency_pct}")
    return efficiency_pct / 100


def _parse_battery(params: Mapping[str, Any], capacity_kwh: float) -> BatteryConfig | None:
    """Read the battery a home body describes, its ``capacity_kwh`` read within the battery component's value_range: none when that is 0.

    Each setting is read whatever ``capacity_kwh`` is, so a value a battery refuses is
    refused without one too; a null setting is unset, leaving BatteryConfig's default.
    """
    settings: dict[str, Any] = {}
    if (max_charge_kw := _read_power_limit(params["max_charge_kw"], "charge")) is not None:
        settings["max_charge_kw"] = max_charge_kw
    if (max_discharge_kw := _read_power_limit(params["max_discharge_kw"], "discharge")) is not None:
        settings["max_discharge_kw"] = max_discharge_kw
    round_trip = _read_efficiency(params["efficiency_pct"])
    dispatch_strategy = parse_dispatch_strategy_config(params["dispatch_strategy"])
    if dispatch_strategy is not None:
        settings["dispatch_strategy"] = dispatch_strategy
    if has_battery(capacity_kwh, "battery_kwh"):
        battery = BatteryConfig(capacity_kwh=capacity_kwh, **settings)
        return battery if round_trip is None else battery.with_round_trip(round_trip)
    return None


def _parse_heat_pump_block(data: object) -> HeatPumpConfig | None:
    """Read a request body's ``heat_pump`` value with the web form's keys, defaulting those it omits.

    The form sends ``type`` where config's YAML heat_pump block requires ``heat_pump_type``.
    ``None`` means no heat pump; any other value that is not a mapping raises
    ``ConfigurationError`` naming ``heat_pump`` and the type received. Each number must be
    finite, refused naming it as ``heat_pump.<key>``.
    """
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise ConfigurationError(f"heat_pump must be a mapping, got {type(data).__name__}")
    return HeatPumpConfig(
        heat_pump_type=data.get("type", "ASHP"),
        thermal_capacity_kw=as_finite_float(
            data.get("thermal_capacity_kw", 8.0), "heat_pump.thermal_capacity_kw"
        ),
        annual_heat_demand_kwh=as_finite_float(
            data.get("annual_heat_demand_kwh", 8000.0), "heat_pump.annual_heat_demand_kwh"
        ),
    )


def parse_home_config(data: object) -> tuple[HomeConfig, pd.Timestamp, pd.Timestamp, str | None]:
    """Parse JSON request body into HomeConfig and date range.

    Args:
        data: The home config, a parsed JSON value that must be an object.

    Returns:
        Tuple of (HomeConfig, start_date, end_date, name). The name is the body's, None
        when it sends none; the HomeConfig takes it, and is unnamed ("") when there is none.

    Raises:
        ConfigurationError: If *data* is not a JSON object (the error names the type
            received), if it has a top-level key outside the recognised set
            (the error names each such key), if a nested block (heat_pump,
            seg, tariff or dispatch_strategy) is neither null, which reads as
            absent, nor a mapping (the error names the block and the type
            received), if a float field is a boolean or not a finite number
            float() reads, or occupants is not a whole number, a boolean
            included (the error names the field, as heat_pump.<key> for a
            heat-pump number, and the value sent), if its days, start or
            end is one parse_date_range refuses, if location is one
            read_location refuses (the error is its own refusal), if
            pv_kw, battery_kwh or a sent consumption_kwh lies outside its
            fleet component's value_range, PV's, the battery's or the load's
            (the error names the field, the range and the value sent), or if
            required fields are missing or invalid; a seg, tariff or
            dispatch_strategy block its grammar refuses raises that
            grammar's own refusal. The battery
            settings (max_charge_kw, max_discharge_kw, efficiency_pct and
            dispatch_strategy) are read, and refused, whatever battery_kwh
            is; a null setting reads as unset. A null system_losses also
            reads as unset, leaving PVConfig's default. An azimuth, tilt,
            system_age_years, degradation_rate_per_year or system_losses
            that is not a finite number in PVConfig's range raises
            PVConfig's own refusal, naming it. A name
            sent as text holding a lone surrogate is refused with
            require_encodable_text's refusal, naming name; a name that is
            not text is not checked here.
    """
    data = require_json_object(data, _HOME_CONFIG)
    refuse_unrecognised_keys(data, _HOME_CONFIG_KEYS, _HOME_CONFIG)
    params = {**_HOME_CONFIG_DEFAULTS, **data}
    pv_kw = as_finite_float(params["pv_kw"], "pv_kw", within=FLEET_COMPONENTS["pv"].value_range)
    system_losses_setting = _system_losses_setting(params["system_losses"])
    battery_kwh_val = as_finite_float(
        params["battery_kwh"], "battery_kwh", within=FLEET_COMPONENTS["battery"].value_range
    )
    consumption_kwh_raw = params["consumption_kwh"]
    occupants = as_whole_number(params["occupants"], "occupants")
    stochastic = bool(params["stochastic"])
    name = params["name"]
    refuse_unencodable_text(name, "name")

    # Parse date range using shared helper
    start, end = parse_date_range(data)

    loc = read_location(params["location"])

    # Build component configs
    pv_config = PVConfig(
        capacity_kw=pv_kw,
        azimuth=params["azimuth"],
        tilt=params["tilt"],
        system_age_years=params["system_age_years"],
        degradation_rate_per_year=params["degradation_rate_per_year"],
        **system_losses_setting,
    )

    battery_config = _parse_battery(params, battery_kwh_val)

    annual_consumption: float | None = None
    if consumption_kwh_raw is not None:
        annual_consumption = as_finite_float(
            consumption_kwh_raw, "consumption_kwh", within=FLEET_COMPONENTS["load"].value_range
        )

    load_config = LoadConfig(
        annual_consumption_kwh=annual_consumption,
        household_occupants=occupants,
        use_stochastic=stochastic,
    )

    heat_pump_config = _parse_heat_pump_block(params["heat_pump"])

    # Build optional tariff config
    tariff_config = parse_tariff_config(params["tariff"])

    seg_tariff = parse_seg_tariff(params["seg"])

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
