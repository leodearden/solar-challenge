# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse the web dashboard's flat simulation-parameter dicts into engine configuration."""

from collections.abc import Mapping
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd

from solar_challenge.battery import BatteryConfig, require_valid_power_limit
from solar_challenge.config import (
    ConfigurationError,
    parse_dispatch_strategy_config,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.web.number_fields import as_finite_float, as_int, as_int_within
from solar_challenge.web.shared import require_json_object, resolve_location

_FULL_YEAR_START = date(2024, 1, 1)
_FULL_YEAR_END = date(2024, 12, 31)
_DAYS_WINDOW_START = date(2024, 6, 1)

#: The most days a simulation window may span: the full 2024 calendar year that days=365 and a request
#: without dates run; rationale in docs/web-ui-design.md (Period).
MAX_WINDOW_DAYS: int = (_FULL_YEAR_END - _FULL_YEAR_START).days + 1

# Each parser's recognised top-level keys, and the value each reads as when absent.
_DATE_RANGE_DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "days": None,
    "start": "",
    "end": "",
})

_HOME_CONFIG_DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "pv_kw": 4.0,
    "azimuth": 180,
    "tilt": 35,
    "system_age_years": 0.0,
    "degradation_rate_per_year": 0.005,
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


def read_iso_date(value: Any, field: str) -> date:
    """Read *value*, the setting named *field*, as an ISO 8601 calendar date (``YYYY-MM-DD``).

    Raises:
        ValueError: If *value* is not a string date.fromisoformat reads; the
            error names *field* and the value.
    """
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}") from exc


def _read_date(value: Any, field: str, default: date) -> date:
    """Read a request body's ``field`` as an ISO 8601 calendar date; a falsy value reads as ``default``.

    Raises:
        ValueError: From :func:`read_iso_date`, for a value that is not an ISO
            8601 date, naming the field and the value sent.
    """
    if not value:
        return default
    return read_iso_date(value, field)


def _days_window(days: int) -> tuple[date, date]:
    """The window a ``days`` request runs: the full 2024 calendar year for 365, else *days* days from 2024-06-01."""
    if days == 365:
        return _FULL_YEAR_START, _FULL_YEAR_END
    return _DAYS_WINDOW_START, _DAYS_WINDOW_START + timedelta(days=days - 1)


def _refuse_reversed_or_overlong_window(start: date, end: date) -> None:
    """Refuse a window that ends before it starts or spans more than MAX_WINDOW_DAYS days, naming start and end."""
    if end < start:
        raise ValueError(f"end must not be before start, got start '{start}' and end '{end}'")
    span = (end - start).days + 1
    if span > MAX_WINDOW_DAYS:
        raise ValueError(
            f"start to end must span at most {MAX_WINDOW_DAYS} days, "
            f"got start '{start}' and end '{end}', {span:,} days"
        )


def parse_date_range(data: Mapping[str, Any]) -> tuple[str, str]:
    """Extract a (start, end) date-string pair from a JSON request body.

    Three resolution modes (checked in order):

    1. ``days == 365``  → **sentinel for a full calendar year**: the 2024
       calendar year ``("2024-01-01", "2024-12-31")``, 366 days since 2024 is a
       leap year, so callers can request a full-year run without explicit dates.
    2. ``days`` key present (an integer from 1 to :data:`MAX_WINDOW_DAYS` other
       than 365, read as int() reads it) → *days*-day window anchored at
       2024-06-01.
    3. Otherwise → read ``start`` / ``end`` as ISO 8601 dates (``YYYY-MM-DD``);
       a falsy one reads as ``"2024-01-01"`` / ``"2024-12-31"``.

    Whichever mode resolves it, the window must end on or after its start and
    span at most :data:`MAX_WINDOW_DAYS` days.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of ``(start, end)`` as ``"YYYY-MM-DD"`` strings, ``end`` inclusive.

    Raises:
        ValueError: If ``days`` is present but is one int() cannot read or is
            outside 1 to MAX_WINDOW_DAYS, or if ``start`` or ``end`` is not an
            ISO 8601 date, naming the field and the value sent; or if the
            window ends before it starts or spans more than MAX_WINDOW_DAYS
            days, naming start and end as read.
    """
    params = {**_DATE_RANGE_DEFAULTS, **data}
    if params["days"] is not None:
        start, end = _days_window(as_int_within(params["days"], "days", 1, MAX_WINDOW_DAYS))
    else:
        start = _read_date(params["start"], "start", _FULL_YEAR_START)
        end = _read_date(params["end"], "end", _FULL_YEAR_END)
    _refuse_reversed_or_overlong_window(start, end)
    return start.isoformat(), end.isoformat()


def parse_seg_tariff(seg_data: object) -> SEGTariff | None:
    """Read a request body's ``seg`` value with :func:`~solar_challenge.config.parse_seg_rate`'s grammar.

    ``None`` means no SEG.  A value that grammar refuses raises ``ValueError``
    carrying its message, the error every web caller answers with HTTP 400.
    """
    try:
        rate = parse_seg_rate(seg_data)
    except ConfigurationError as exc:
        raise ValueError(str(exc)) from exc
    if rate is None:
        return None
    return SEGTariff(name="", rate_pence_per_kwh=rate)


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
    """Read a home body's round-trip efficiency percentage as the fraction BatteryConfig takes.

    Null is unset; any other value must be a finite number, refused naming efficiency_pct,
    and a percentage outside (0, 100] is refused in the units sent.
    """
    if value is None:
        return None
    efficiency_pct = as_finite_float(value, "efficiency_pct")
    if not (0 < efficiency_pct <= 100):
        raise ValueError(f"Efficiency must be between 0 and 100, got {efficiency_pct}")
    return efficiency_pct / 100


def _parse_battery(params: Mapping[str, Any], capacity_kwh: float) -> BatteryConfig | None:
    """Read the battery a home body describes: none unless ``capacity_kwh`` is positive.

    Each setting is read whatever ``capacity_kwh`` is, so a value a battery refuses is
    refused without one too; a null setting is unset, leaving BatteryConfig's default.
    """
    settings: dict[str, Any] = {}
    if (max_charge_kw := _read_power_limit(params["max_charge_kw"], "charge")) is not None:
        settings["max_charge_kw"] = max_charge_kw
    if (max_discharge_kw := _read_power_limit(params["max_discharge_kw"], "discharge")) is not None:
        settings["max_discharge_kw"] = max_discharge_kw
    if (efficiency := _read_efficiency(params["efficiency_pct"])) is not None:
        settings["efficiency"] = efficiency
    try:
        settings["dispatch_strategy"] = parse_dispatch_strategy_config(params["dispatch_strategy"])
    except ConfigurationError as exc:
        raise ValueError(str(exc)) from exc
    if capacity_kwh > 0:
        return BatteryConfig(capacity_kwh=capacity_kwh, **settings)
    return None


def _parse_heat_pump_block(data: object) -> HeatPumpConfig | None:
    """Read a request body's ``heat_pump`` value with the web form's keys, defaulting those it omits.

    The form sends ``type`` where config's YAML heat_pump block requires ``heat_pump_type``.
    ``None`` means no heat pump; any other value that is not a mapping raises
    ``ValueError`` naming ``heat_pump`` and the type received. Each number must be
    finite, refused naming it as ``heat_pump.<key>``.
    """
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise ValueError(f"heat_pump must be a mapping, got {type(data).__name__}")
    return HeatPumpConfig(
        heat_pump_type=data.get("type", "ASHP"),
        thermal_capacity_kw=as_finite_float(
            data.get("thermal_capacity_kw", 8.0), "heat_pump.thermal_capacity_kw"
        ),
        annual_heat_demand_kwh=as_finite_float(
            data.get("annual_heat_demand_kwh", 8000.0), "heat_pump.annual_heat_demand_kwh"
        ),
    )


def _refuse_unrecognised_keys(data: Mapping[str, Any]) -> None:
    recognised = _HOME_CONFIG_DEFAULTS.keys() | _DATE_RANGE_DEFAULTS.keys()
    unrecognised = sorted(data.keys() - recognised)
    if unrecognised:
        raise ValueError(
            f"Unrecognised home config keys: {', '.join(map(repr, unrecognised))}; "
            f"recognised keys: {', '.join(sorted(recognised))}"
        )


def parse_home_config(data: object) -> tuple[HomeConfig, pd.Timestamp, pd.Timestamp, str | None]:
    """Parse JSON request body into HomeConfig and date range.

    Args:
        data: The home config, a parsed JSON value that must be an object.

    Returns:
        Tuple of (HomeConfig, start_date, end_date, name).

    Raises:
        ValueError: If *data* is not a JSON object (the error names the type
            received), if it has a top-level key outside the recognised set
            (the error names each such key), if a nested block (heat_pump,
            seg, tariff or dispatch_strategy) is neither null, which reads as
            absent, nor a mapping (the error names the block and the type
            received), if a float field is a boolean or not a finite number
            float() reads, or occupants is one int() cannot read (the error
            names the field, as heat_pump.<key> for a heat-pump number, and
            the value sent), if its days, start or end is one
            parse_date_range refuses, or if required fields are missing or
            invalid. The battery settings (max_charge_kw, max_discharge_kw,
            efficiency_pct and dispatch_strategy) are read, and refused,
            whatever battery_kwh is; a null setting reads as unset.
    """
    data = require_json_object(data, "Home config")
    _refuse_unrecognised_keys(data)
    params = {**_HOME_CONFIG_DEFAULTS, **data}
    pv_kw = as_finite_float(params["pv_kw"], "pv_kw")
    azimuth = as_finite_float(params["azimuth"], "azimuth")
    tilt = as_finite_float(params["tilt"], "tilt")
    # Range validation for system_age_years (>= 0) and degradation_rate_per_year
    # ([0, 1]) is delegated to PVConfig.__post_init__, which raises ValueError.
    # That ValueError propagates out of this function unchanged.
    # PVConfig is the single source of truth for these bounds.
    system_age_years = as_finite_float(params["system_age_years"], "system_age_years")
    degradation_rate_per_year = as_finite_float(
        params["degradation_rate_per_year"], "degradation_rate_per_year"
    )
    battery_kwh_val = as_finite_float(params["battery_kwh"], "battery_kwh")
    consumption_kwh_raw = params["consumption_kwh"]
    occupants = as_int(params["occupants"], "occupants")
    stochastic = bool(params["stochastic"])
    location_preset = str(params["location"])
    name = params["name"]

    # Parse date range using shared helper
    start, end = parse_date_range(data)

    # Validate inputs
    if not (0.5 <= pv_kw <= 20.0):
        raise ValueError(f"PV capacity must be 0.5-20 kW, got {pv_kw}")
    if battery_kwh_val < 0:
        raise ValueError(f"Battery capacity cannot be negative, got {battery_kwh_val}")

    # Resolve location
    loc = resolve_location(location_preset)

    # Build component configs
    pv_config = PVConfig(
        capacity_kw=pv_kw,
        azimuth=azimuth,
        tilt=tilt,
        system_age_years=system_age_years,
        degradation_rate_per_year=degradation_rate_per_year,
    )

    battery_config = _parse_battery(params, battery_kwh_val)

    annual_consumption: float | None = None
    if consumption_kwh_raw is not None:
        annual_consumption = as_finite_float(consumption_kwh_raw, "consumption_kwh")

    load_config = LoadConfig(
        annual_consumption_kwh=annual_consumption,
        household_occupants=occupants,
        use_stochastic=stochastic,
    )

    heat_pump_config = _parse_heat_pump_block(params["heat_pump"])

    # Build optional tariff config
    try:
        tariff_config = parse_tariff_config(params["tariff"])
    except ConfigurationError as exc:
        raise ValueError(str(exc)) from exc

    seg_tariff = parse_seg_tariff(params["seg"])

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        heat_pump_config=heat_pump_config,
        tariff_config=tariff_config,
        seg_tariff=seg_tariff,
        location=loc,
        name=name or "Web Simulation",
    )

    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    return home_config, start_date, end_date, name
