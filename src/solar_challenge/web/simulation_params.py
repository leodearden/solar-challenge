# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse the web dashboard's flat simulation-parameter dicts into engine configuration."""

from typing import Any

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import (
    ConfigurationError,
    _parse_dispatch_strategy_config,
    _parse_tariff_config,
)
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from solar_challenge.web.shared import resolve_location


def parse_date_range(data: dict[str, Any]) -> tuple[str, str]:
    """Extract a (start, end) date-string pair from a JSON request body.

    Three resolution modes (checked in order):

    1. ``days == 365``  → **sentinel for a full calendar year**: returns the
       complete 2024 calendar year ``("2024-01-01", "2024-12-31")``.  Because
       2024 is a leap year this window spans 366 days; ``365`` is intentionally
       a *named sentinel* (not a literal day count) so callers can request a
       full-year run without specifying explicit dates.
    2. ``days`` key present (any *positive* integer ≠ 365) → *days*-day window
       anchored at 2024-06-01.  ``days <= 0`` raises ``ValueError``.
    3. Otherwise → use ``start`` / ``end`` keys with defaults
       ``"2024-01-01"`` / ``"2024-12-31"``.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of ``(start, end)`` as ``"YYYY-MM-DD"`` strings.

    Raises:
        ValueError: If ``days`` is present but not a positive integer.
    """
    days_raw = data.get("days")
    start_raw = data.get("start", "")
    end_raw = data.get("end", "")

    if days_raw is not None:
        days = int(days_raw)
        if days <= 0:
            raise ValueError(f"days must be a positive integer, got {days}")
        if days == 365:
            return "2024-01-01", "2024-12-31"
        ref = pd.Timestamp("2024-06-01")
        start = ref.strftime("%Y-%m-%d")
        end = (ref + pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")
        return start, end

    start = str(start_raw) if start_raw else "2024-01-01"
    end = str(end_raw) if end_raw else "2024-12-31"
    return start, end


def parse_seg_tariff(seg_data: dict[str, Any] | None) -> SEGTariff | None:
    """Parse a 'seg' sub-dict from the request body into a SEGTariff.

    Resolution priority (mirrors config._parse_tariff_config naming convention):
    1. ``{"preset": "<key>"}`` — resolved via :func:`resolve_seg_tariff`; raises
       ``ValueError`` for unknown presets.
    2. ``{"rate_pence_per_kwh": <float>}`` — constructs
       ``SEGTariff(name="Custom", rate_pence_per_kwh=float(rate))``;
       :class:`SEGTariff`'s ``__post_init__`` raises ``ValueError`` for negative
       rates, which this function lets propagate.
    3. Absent or falsy ``seg_data`` → ``None`` (back-compatible default).

    Args:
        seg_data: The value of ``data.get("seg")`` from the request body, or None.

    Returns:
        A :class:`SEGTariff` instance, or ``None`` if *seg_data* is absent/falsy.

    Raises:
        ValueError: For unknown preset keys or negative rates.
    """
    if not seg_data:
        return None
    preset = seg_data.get("preset")
    # "custom" is the UI sentinel meaning "use explicit rate_pence_per_kwh instead of
    # a named preset".  Treat it as absent so direct API callers sending
    # {"preset": "custom", "rate_pence_per_kwh": 5.5} get the same fall-through
    # behaviour as the front-end rather than an HTTP 400 from resolve_seg_tariff.
    if preset and str(preset) != "custom":
        return resolve_seg_tariff(str(preset))
    if "rate_pence_per_kwh" in seg_data:
        # Use key-presence check (not value-is-not-None) so that a null/NaN value
        # serialised by the browser as JSON null triggers float(None) → TypeError
        # → HTTP 400, rather than silently ignoring the user's SEG selection.
        return SEGTariff(name="Custom", rate_pence_per_kwh=float(seg_data["rate_pence_per_kwh"]))
    return None


def parse_home_config(data: dict[str, Any]) -> tuple[HomeConfig, pd.Timestamp, pd.Timestamp, str | None]:
    """Parse JSON request body into HomeConfig and date range.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of (HomeConfig, start_date, end_date, name).

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    pv_kw = float(data.get("pv_kw", 4.0))
    azimuth = float(data.get("azimuth", 180))
    tilt = float(data.get("tilt", 35))
    # Range validation for system_age_years (>= 0) and degradation_rate_per_year
    # ([0, 1]) is delegated to PVConfig.__post_init__, which raises ValueError.
    # That ValueError propagates out of this function unchanged.
    # PVConfig is the single source of truth for these bounds.
    system_age_years = float(data.get("system_age_years", 0.0))
    degradation_rate_per_year = float(data.get("degradation_rate_per_year", 0.005))
    battery_kwh_val = float(data.get("battery_kwh", 0.0))
    max_charge_kw_raw = data.get("max_charge_kw")
    max_discharge_kw_raw = data.get("max_discharge_kw")
    efficiency_pct_raw = data.get("efficiency_pct")
    consumption_kwh_raw = data.get("consumption_kwh")
    occupants = int(data.get("occupants", 3))
    stochastic = bool(data.get("stochastic", False))
    location_preset = str(data.get("location", "bristol"))
    name = data.get("name")

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

    battery_config: BatteryConfig | None = None
    if battery_kwh_val > 0:
        battery_kwargs: dict[str, Any] = {"capacity_kwh": battery_kwh_val}
        if max_charge_kw_raw is not None:
            battery_kwargs["max_charge_kw"] = float(max_charge_kw_raw)
        if max_discharge_kw_raw is not None:
            battery_kwargs["max_discharge_kw"] = float(max_discharge_kw_raw)
        if efficiency_pct_raw is not None:
            eff = float(efficiency_pct_raw)
            if not (0 < eff <= 100):
                raise ValueError(f"Efficiency must be between 0 and 100, got {eff}")
            battery_kwargs["efficiency_pct"] = eff
        try:
            dispatch_data = data.get("dispatch_strategy")
            if dispatch_data:
                battery_kwargs["dispatch_strategy"] = _parse_dispatch_strategy_config(dispatch_data)
        except ConfigurationError as exc:
            raise ValueError(str(exc)) from exc
        battery_config = BatteryConfig(**battery_kwargs)

    annual_consumption: float | None = None
    if consumption_kwh_raw is not None:
        annual_consumption = float(consumption_kwh_raw)

    load_config = LoadConfig(
        annual_consumption_kwh=annual_consumption,
        household_occupants=occupants,
        use_stochastic=stochastic,
    )

    # Build optional heat pump config.
    #
    # Note on key naming: the web JSON contract uses "type" (a shorter, idiomatic
    # form-field name) whereas the YAML/config.py contract uses "heat_pump_type".
    # The mapping is intentional and happens here on the single `hp_data.get("type")`
    # call.  This is the only place that translation is needed.
    #
    # Note on implementation pattern: tariff and dispatch configs are built via
    # shared config._parse_tariff_config / _parse_dispatch_strategy_config helpers
    # because those helpers exist in config.py.  config._parse_heat_pump_config
    # exists too, but it reads the YAML contract (it requires the 'heat_pump_type'
    # and 'thermal_capacity_kw' keys), not the web's "type" key and its defaults,
    # so HeatPumpConfig is built directly here.  HeatPumpConfig.__post_init__
    # already raises ValueError on invalid inputs, and ValueError is this
    # function's own error contract — no extra wrapping is needed here.
    heat_pump_config: HeatPumpConfig | None = None
    hp_data = data.get("heat_pump")
    if hp_data:
        heat_pump_config = HeatPumpConfig(
            heat_pump_type=hp_data.get("type", "ASHP"),
            thermal_capacity_kw=float(hp_data.get("thermal_capacity_kw", 8.0)),
            annual_heat_demand_kwh=float(hp_data.get("annual_heat_demand_kwh", 8000.0)),
        )

    # Build optional tariff config
    try:
        tariff_config = _parse_tariff_config(data.get("tariff"))
    except ConfigurationError as exc:
        raise ValueError(str(exc)) from exc

    # Build optional SEG export-rate config (ValueError or TypeError on bad input)
    seg_tariff = parse_seg_tariff(data.get("seg"))

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
