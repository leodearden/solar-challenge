# SPDX-License-Identifier: AGPL-3.0-or-later
"""The settings of a scenario that a sweep or a sensitivity axis varies, each named, and the one edit that sets it."""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Optional

from solar_challenge.battery import BatteryConfig, has_battery
from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.home import HomeConfig


@dataclass(frozen=True)
class Knob:
    """A setting of a scenario that a sweep or a sensitivity axis varies.

    Attributes:
        name: The knob's canonical name, under which KNOBS holds it and
            knob_named resolves it; it need not be the name of a field the knob edits.
        apply: The knob's one edit, pure: a new scenario with the setting at the
            value given, in the form (home or homes) of the scenario given, which
            it leaves unchanged.
    """

    name: str
    apply: Callable[[ScenarioConfig, float], ScenarioConfig]


def _home_knob(name: str, edit: Callable[[HomeConfig, float], HomeConfig]) -> Knob:
    """The knob *name* that makes *edit* to each stored home of a scenario."""

    def apply(scenario: ScenarioConfig, value: float) -> ScenarioConfig:
        return scenario.map_homes(lambda home: edit(home, value))

    return Knob(name, apply)


def _with_pv_capacity(home: HomeConfig, kw: float) -> HomeConfig:
    """*home* with its array's DC capacity at *kw*."""
    return replace(home, pv_config=replace(home.pv_config, capacity_kw=kw))


def _with_inverter_capacity(home: HomeConfig, kw: float) -> HomeConfig:
    """*home* with its array's AC inverter capacity at *kw*."""
    return replace(home, pv_config=replace(home.pv_config, inverter_capacity_kw=kw))


def _with_battery_capacity(home: HomeConfig, kwh: float) -> HomeConfig:
    """*home* with a battery of nameplate capacity *kwh*, or with none at exactly 0.

    Only the capacity is set.  A battery the home has keeps its power, state of
    charge, grid-charging and dispatch settings, so two homes at one capacity can
    cycle different windows; a home without one gains BatteryConfig's defaults at
    that capacity.  Any capacity above 0, however small, means a battery.
    """
    if not has_battery(kwh, "battery_capacity_kwh"):
        return replace(home, battery_config=None)
    if home.battery_config is not None:
        return replace(home, battery_config=replace(home.battery_config, capacity_kwh=kwh))
    return replace(home, battery_config=BatteryConfig(capacity_kwh=kwh))


def _with_annual_consumption(home: HomeConfig, kwh: float) -> HomeConfig:
    """*home* with its household consuming *kwh* a year."""
    return replace(home, load_config=replace(home.load_config, annual_consumption_kwh=kwh))


def _with_pv_degradation(home: HomeConfig, rate: float) -> HomeConfig:
    """*home* with its array degrading at *rate* a year."""
    return replace(home, pv_config=replace(home.pv_config, degradation_rate_per_year=rate))


def _with_seg_rate(scenario: ScenarioConfig, rate: float) -> ScenarioConfig:
    """*scenario* exporting at *rate* p/kWh from each home without a SEG tariff of its own; construction refuses a home whose own tariff sets another rate."""
    return replace(scenario, seg_tariff_pence_per_kwh=rate)


def _finance_knob(field: str) -> Knob:
    """The knob that sets the FinanceConfig field *field* of a scenario's finance block."""

    def apply(scenario: ScenarioConfig, value: float) -> ScenarioConfig:
        if scenario.finance is None:
            raise ConfigurationError(
                f"Knob {field!r} sets finance.{field}, but scenario {scenario.name!r} has no finance block"
            )
        return replace(scenario, finance=replace(scenario.finance, **{field: value}))  # type: ignore[arg-type]  # debt: ticket tkt_0RXDDPSS2PASXMGCK3XCD1FW0A

    return Knob(field, apply)


def _real_number_finance_fields() -> tuple[str, ...]:
    """FinanceConfig's fields annotated float or Optional[float], in field order."""
    hints = typing.get_type_hints(FinanceConfig)
    return tuple(
        field.name for field in dataclasses.fields(FinanceConfig) if hints[field.name] in (float, Optional[float])
    )


_LEADING_FINANCE_FIELDS = ("grid_services_income_per_kw_per_year_gbp",)


def _registry(
    knobs: Iterable[Knob], aliases: Mapping[str, str]
) -> tuple[Mapping[str, Knob], Mapping[str, str]]:
    """*knobs* by name, in order, and *aliases*, each read-only.

    Raises:
        RuntimeError: Naming the names involved, if two knobs share a name, an
            alias is a knob's name, or an alias names no knob: a defect of this
            module, not of a scenario or a command line.
    """
    by_name: dict[str, Knob] = {}
    for knob in knobs:
        if knob.name in by_name:
            raise RuntimeError(f"Two knobs are named {knob.name!r}")
        by_name[knob.name] = knob
    canonical = sorted(alias for alias in aliases if alias in by_name)
    if canonical:
        raise RuntimeError(f"Aliases {canonical} are knobs' canonical names")
    dangling = sorted(f"{alias} -> {name}" for alias, name in aliases.items() if name not in by_name)
    if dangling:
        raise RuntimeError(f"Aliases name no knob: {', '.join(dangling)}")
    return MappingProxyType(by_name), MappingProxyType(dict(aliases))


KNOBS, ALIASES = _registry(
    (
        _home_knob("pv_capacity_kw", _with_pv_capacity),
        _home_knob("inverter_capacity_kw", _with_inverter_capacity),
        _home_knob("battery_capacity_kwh", _with_battery_capacity),
        _home_knob("annual_consumption_kwh", _with_annual_consumption),
        _home_knob("degradation_rate_per_year", _with_pv_degradation),
        Knob("seg_tariff_pence_per_kwh", _with_seg_rate),
        *(_finance_knob(field) for field in _LEADING_FINANCE_FIELDS),
        *(
            _finance_knob(field)
            for field in _real_number_finance_fields()
            if field not in _LEADING_FINANCE_FIELDS
        ),
    ),
    {
        "degradation": "degradation_rate_per_year",
        "seg": "seg_tariff_pence_per_kwh",
        "grid_services": "grid_services_income_per_kw_per_year_gbp",
        "retained_floor": "retained_cash_floor_per_home_per_year_gbp",
        "battery_cost": "battery_cost_per_kwh_gbp",
        "pv_cost": "pv_cost_per_kwp_gbp",
        "inverter_cost": "inverter_cost_per_kw_gbp",
    },
)
"""KNOBS holds each knob under its canonical name, install and load settings first; ALIASES maps each alias to a canonical name."""


def names_with_aliases(knobs: Iterable[Knob]) -> str:
    """Each of *knobs*' canonical name, its aliases after it in parentheses, comma-separated in the order given."""
    return ", ".join(_name_with_aliases(knob) for knob in knobs)


def _name_with_aliases(knob: Knob) -> str:
    """*knob*'s canonical name, its aliases after it in parentheses when it has any."""
    aliases = [alias for alias, name in ALIASES.items() if name == knob.name]
    return f"{knob.name} ({', '.join(aliases)})" if aliases else knob.name


def _canonical_name(name: str) -> str:
    """The canonical name *name* resolves to: an alias's knob name, else *name* itself."""
    return ALIASES.get(name, name)


def is_knob_name(name: str) -> bool:
    """Whether *name* names a knob, as its canonical name or as an alias."""
    return _canonical_name(name) in KNOBS


def knob_named(name: str) -> Knob:
    """The knob *name* names, as its canonical name or as an alias.

    Raises:
        ConfigurationError: If *name* names no knob, listing every knob with its aliases.
    """
    if not is_knob_name(name):
        raise ConfigurationError(
            f"Unknown knob {name!r}; the knobs, each with its aliases: {names_with_aliases(KNOBS.values())}"
        )
    return KNOBS[_canonical_name(name)]
