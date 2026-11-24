# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read whole scenario, fleet and community documents into config's own document types.

A document's blocks are read by solar_challenge.scenario_blocks, and its fleet_distribution:
block by solar_challenge.fleet_distribution.
"""

import contextlib
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    TypeVar,
    Union,
)

import pandas as pd
import yaml

from solar_challenge.community import CommunityConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig
from solar_challenge.fleet_distribution import (
    FleetDistributionConfig,
    SweepSpec,
    detect_sweep_spec,
    expand_sweep_configs,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.gridservices import GridServicesBand
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import as_finite_float
from solar_challenge.scenario_blocks import (
    HOME_BLOCK_KEYS,
    RETIRED_DISPATCH_STRATEGY_KEY,
    block_label,
    child_path,
    parse_community_config,
    parse_finance_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
    read_text,
    refusal,
    refuse_retired_keys,
    refuse_unrecognised_keys,
    require_held_keys,
    require_keys,
    require_list,
    require_mapping,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, ONE_MINUTE, SimulationWindow


_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
"""The one string form a period's day takes: 'YYYY-MM-DD'."""


def period_day(value: object, path: str) -> date:
    """The calendar day *value*, the period day at *path*, gives: a datetime's or Timestamp's own date on its own clock, a date as it is, or a 'YYYY-MM-DD' string's day.

    Raises:
        ConfigurationError: For any other value, such as NaT, '2024' or '20240601', naming *path*,
            the value and the forms a period's day takes.
    """
    if isinstance(value, datetime) and value is not pd.NaT:
        return value.date()
    if type(value) is date:
        return value
    if isinstance(value, str) and _ISO_DAY.fullmatch(value):
        with contextlib.suppress(ValueError):
            return date.fromisoformat(value)
    raise refusal(path, f"{value!r} is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp")


def period_window(start_date: object, end_date: object, *, timezone: str, block_path: str = "period") -> SimulationWindow:
    """The one-minute window on *timezone* from *start_date* to *end_date*, each read by period_day at its path in the period at *block_path*; a pair of days SimulationWindow refuses, such as a last day before the first, raises ConfigurationError naming both paths and days and the window's reason."""
    start_path = child_path(block_path, "start_date")
    end_path = child_path(block_path, "end_date")
    first_day = period_day(start_date, start_path)
    last_day = period_day(end_date, end_path)
    try:
        return SimulationWindow(first_day, last_day, ONE_MINUTE, timezone)
    except ValueError as exc:
        raise refusal(
            start_path, f"{first_day.isoformat()} to {end_path} {last_day.isoformat()} gives no window: {exc}"
        ) from exc


@dataclass(frozen=True)
class ScenarioConfig:
    """Configuration for a simulation scenario.

    Attributes:
        name: Scenario identifier
        description: Human-readable description
        location: Geographic location (defaults to Bristol)
        period: The days and clock the scenario simulates: a one-minute window on the
            scenario's zone, its location's, else its first home's
        homes: Home configurations (for fleet simulation); a list is held as a tuple
        home: Single home configuration (for single-home simulation)
        seg_tariff_pence_per_kwh: Smart Export Guarantee rate in pence/kWh (optional), read
            as SEGTariff reads its rate; a home whose own seg_tariff sets another rate is refused
        finance: Financial appraisal parameters (None for no financial analysis)
        flex_band: The grid-services uncertainty band a finance run reports flexibility in,
            held as the GridServicesBand it names (None for none)
    """

    name: str
    period: SimulationWindow
    description: str = ""
    location: Optional[Location] = None
    homes: tuple[HomeConfig, ...] = ()
    home: Optional[HomeConfig] = None
    seg_tariff_pence_per_kwh: Optional[float] = None
    finance: Optional[FinanceConfig] = None
    flex_band: Optional[GridServicesBand] = None

    def __post_init__(self) -> None:
        """Validate scenario configuration."""
        object.__setattr__(self, "homes", tuple(self.homes))
        if not self.homes and self.home is None:
            raise ConfigurationError(
                f"Scenario '{self.name}' must define either 'home' or 'homes'"
            )
        if self.homes and self.home is not None:
            raise ConfigurationError(
                f"Scenario '{self.name}' cannot define both 'home' and 'homes'"
            )
        self._read_the_seg_rate()
        self._refuse_a_home_seg_rate_other_than_the_scenarios()
        self._refuse_a_period_this_scenario_cannot_simulate()
        self._read_the_flex_band()

    @property
    def is_fleet(self) -> bool:
        """Whether this is a fleet simulation."""
        return len(self.homes) > 1 or (len(self.homes) == 1 and self.home is None)

    def get_location(self) -> Location:
        """Get location, defaulting to Bristol."""
        return self.location if self.location is not None else Location.bristol()

    def simulated_homes(self) -> tuple[HomeConfig, ...]:
        """The homes this scenario simulates, in order; one with no SEG tariff of its own exports at the scenario's rate."""
        tariff = self._seg_tariff()
        if tariff is None:
            return self._stored_homes()
        return tuple(
            home if home.seg_tariff is not None else replace(home, seg_tariff=tariff)
            for home in self._stored_homes()
        )

    def map_homes(self, transform: Callable[[HomeConfig], HomeConfig]) -> "ScenarioConfig":
        """This scenario in the same form, *transform* applied to each stored home, and checked as construction checks."""
        if self.home is not None:
            return replace(self, home=transform(self.home))
        return replace(self, homes=tuple(transform(home) for home in self.homes))

    def window(self) -> SimulationWindow:
        """The period: the days the scenario simulates at ONE_MINUTE, on the clock of location, or of the first home's location when location is None."""
        return self.period

    def with_window(self, *, first_day: Optional[date] = None, last_day: Optional[date] = None) -> "ScenarioConfig":
        """A copy whose period keeps each day not given, checked as construction checks; each day given is exactly a date.

        Raises:
            ConfigurationError: For days that give no window, such as a datetime or a last day
                before the first, naming the scenario, the arguments given and the window's reason.
        """
        try:
            period = replace(
                self.period,
                first_day=self.period.first_day if first_day is None else first_day,
                last_day=self.period.last_day if last_day is None else last_day,
            )
        except ValueError as exc:
            given = {"first_day": first_day, "last_day": last_day}
            arguments = ", ".join(f"{parameter}={day!r}" for parameter, day in given.items() if day is not None)
            raise ConfigurationError(f"Scenario '{self.name}': with_window({arguments}) gives no window: {exc}") from exc
        return replace(self, period=period)

    def simulation_bounds(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        """The window's first and last days' local midnights: the start and end, end inclusive, that simulate_home and a fleet simulator take."""
        window = self.window()
        return (
            pd.Timestamp(window.first_day, tz=window.timezone),
            pd.Timestamp(window.last_day, tz=window.timezone),
        )

    def _timezone(self) -> str:
        """The zone of the window's clock: location's, else the first stored home's location's."""
        location = self.location if self.location is not None else self._stored_homes()[0].location
        return location.timezone

    def _refuse_a_period_this_scenario_cannot_simulate(self) -> None:
        """Raise ConfigurationError, naming the scenario, for a period that is not a SimulationWindow, naming its type; at a cadence other than ONE_MINUTE, naming both; or on a zone other than _timezone()'s, naming both."""
        period: object = self.period
        if not isinstance(period, SimulationWindow):
            raise ConfigurationError(
                f"Scenario '{self.name}': period is a timebase.SimulationWindow, got {type(period).__name__} {period!r}"
            )
        if period.cadence != ONE_MINUTE:
            raise ConfigurationError(
                f"Scenario '{self.name}': period.cadence is {period.cadence!r}, "
                f"but a scenario simulates at ONE_MINUTE, {ONE_MINUTE!r}"
            )
        timezone = self._timezone()
        if period.timezone != timezone:
            raise ConfigurationError(
                f"Scenario '{self.name}': period.timezone is {period.timezone!r}, but the scenario's clock is "
                f"{timezone!r}, its location's, else its first home's"
            )

    def _stored_homes(self) -> tuple[HomeConfig, ...]:
        """The homes as stored: (home,) in the single-home form, else homes, in order."""
        return (self.home,) if self.home is not None else self.homes

    def _seg_tariff(self) -> Optional[SEGTariff]:
        """The tariff a home with none of its own exports at: the scenario's rate, unnamed; None when the scenario sets no rate."""
        if self.seg_tariff_pence_per_kwh is None:
            return None
        return SEGTariff(name="", rate_pence_per_kwh=self.seg_tariff_pence_per_kwh)

    def _read_the_seg_rate(self) -> None:
        """Hold seg_tariff_pence_per_kwh as the float SEGTariff reads, raising ConfigurationError, naming the scenario and the rate, for one SEGTariff refuses."""
        try:
            tariff = self._seg_tariff()
        except ConfigurationError as exc:
            raise ConfigurationError(
                f"Scenario '{self.name}' sets seg_tariff_pence_per_kwh="
                f"{self.seg_tariff_pence_per_kwh!r}, which SEGTariff refuses: {exc}"
            ) from exc
        if tariff is not None:
            object.__setattr__(self, "seg_tariff_pence_per_kwh", tariff.rate_pence_per_kwh)

    def _read_the_flex_band(self) -> None:
        """Hold flex_band as the GridServicesBand it names, raising ConfigurationError, naming the scenario and the value, for one naming no band."""
        if self.flex_band is not None:
            band = GridServicesBand.parse(self.flex_band, what=f"Scenario '{self.name}' flex_band")
            object.__setattr__(self, "flex_band", band)

    def _refuse_a_home_seg_rate_other_than_the_scenarios(self) -> None:
        """Raise ConfigurationError naming the first home, by its path 'home' or 'homes[i]', whose own SEG rate is not math.isclose to the scenario's."""
        rate = self.seg_tariff_pence_per_kwh
        if rate is None:
            return
        for index, home in enumerate(self._stored_homes()):
            if home.seg_tariff is None or math.isclose(home.seg_tariff.rate_pence_per_kwh, rate):
                continue
            path = "home" if self.home is not None else f"homes[{index}]"
            named = f"{path} ({home.name!r})" if home.name else path
            raise ConfigurationError(
                f"Inconsistent SEG rate: {named} has its own seg_tariff at "
                f"{home.seg_tariff.rate_pence_per_kwh}p/kWh but scenario '{self.name}' sets "
                f"seg_tariff_pence_per_kwh={rate}p/kWh. Set only one, or use matching rates."
            )


_PERIOD_BLOCK_KEYS: frozenset[str] = frozenset({"start_date", "end_date"})


def _parse_period(data: dict[str, Any], *, timezone: str, block_path: str) -> SimulationWindow:
    """Read the simulation period at *block_path* as period_window reads it on *timezone*, refusing it first unless it gives both days, naming each it leaves out."""
    refuse_unrecognised_keys(block_path, data, _PERIOD_BLOCK_KEYS)
    require_keys(block_path, data, ["start_date", "end_date"])
    return period_window(data["start_date"], data["end_date"], timezone=timezone, block_path=block_path)


@dataclass(frozen=True)
class _ScenarioLevelBlocks:
    """A scenario's blocks other than its homes source, as parse_scenario reads them: what its ScenarioConfig holds and every home it builds is given."""

    name: str
    description: str
    location: Location
    period: SimulationWindow
    tariff: Optional[TariffConfig]
    seg_tariff_pence_per_kwh: Optional[float]
    finance: Optional[FinanceConfig]
    flex_band: Optional[GridServicesBand]

    def home_built_from(self, block: Any, *, block_path: str) -> HomeConfig:
        """The home the home block at *block_path* describes, at the scenario's location and on its tariff unless it sets its own."""
        return parse_home_block(block, self.location, block_path=block_path, fleet_tariff=self.tariff)

    def homes_generated_by(self, distribution: FleetDistributionConfig) -> tuple[HomeConfig, ...]:
        """The homes *distribution* generates, at the scenario's location and on its tariff."""
        return tuple(generate_homes_from_distribution(distribution, self.location, fleet_tariff=self.tariff))

    def scenario(self, *, home: Optional[HomeConfig] = None, homes: tuple[HomeConfig, ...] = ()) -> ScenarioConfig:
        """The scenario of these blocks holding *home* or *homes*."""
        return ScenarioConfig(
            name=self.name,
            description=self.description,
            location=self.location,
            period=self.period,
            homes=homes,
            home=home,
            seg_tariff_pence_per_kwh=self.seg_tariff_pence_per_kwh,
            finance=self.finance,
            flex_band=self.flex_band,
        )


def _one_home(blocks: _ScenarioLevelBlocks, data: Any, *, block_path: str) -> ScenarioConfig:
    """The single-home scenario of the home: block at *block_path*."""
    return blocks.scenario(home=blocks.home_built_from(data, block_path=block_path))


def _listed_homes(blocks: _ScenarioLevelBlocks, data: Any, *, block_path: str) -> ScenarioConfig:
    """The fleet scenario of the homes: list at *block_path*, refused unless it lists at least one home."""
    listed = require_list(block_path, data)
    if not listed:
        raise refusal(block_path, "must list at least one home")
    return blocks.scenario(
        homes=tuple(blocks.home_built_from(entry, block_path=f"{block_path}[{index}]") for index, entry in enumerate(listed))
    )


def _generated_homes(blocks: _ScenarioLevelBlocks, data: Any, *, block_path: str) -> ScenarioConfig:
    """The fleet scenario of the homes the fleet_distribution: block at *block_path* generates."""
    return blocks.scenario(homes=blocks.homes_generated_by(parse_fleet_distribution_config(data, block_path=block_path)))


class _HomesSourceReader(Protocol):
    """A builder of the scenario whose homes one homes source's block, at *block_path*, gives."""

    def __call__(self, blocks: _ScenarioLevelBlocks, data: Any, *, block_path: str) -> ScenarioConfig: ...


_HOMES_SOURCES: Mapping[str, _HomesSourceReader] = MappingProxyType({
    "home": _one_home,
    "homes": _listed_homes,
    "fleet_distribution": _generated_homes,
})
"""Each key a scenario's homes come from, with the builder of the scenario that key's block gives."""

_SCENARIO_LEVEL_KEYS: frozenset[str] = frozenset({
    "name", "description", "location", "period", "tariff", "seg", "finance", "flex_band", "community",
})

_SCENARIO_KEYS: frozenset[str] = _SCENARIO_LEVEL_KEYS | _HOMES_SOURCES.keys()

_RETIRED_SCENARIO_KEYS: Mapping[str, str] = MappingProxyType({
    "output": "no command reads an output block; pass --output to the command instead",
    "tariff_config": "a scenario's tariff is its top-level tariff: block, which every home without its own takes",
    **RETIRED_DISPATCH_STRATEGY_KEY,
    **{
        key: f"a home's {key} block goes under home: (or each homes[i]); the flat home-file form is retired"
        for key in sorted(HOME_BLOCK_KEYS - _SCENARIO_KEYS)
    },
})
"""Each key a scenario no longer reads, with why it is refused and what replaces it."""


def _refuse_keys_no_scenario_reads(data: object, *, block_path: str) -> dict[str, Any]:
    """Return the scenario at *block_path*, refusing it unless it is a mapping holding only the keys a scenario reads.

    A retired key is refused first, naming its path and what replaces it.
    """
    scenario = refuse_retired_keys(block_path, data, _RETIRED_SCENARIO_KEYS)
    return refuse_unrecognised_keys(block_path, scenario, _SCENARIO_KEYS)


def _parse_flex_band(value: object, *, block_path: str) -> Optional[GridServicesBand]:
    """The band the flex_band at *block_path* names, a string read case-insensitively; None when it is absent or null."""
    if value is None:
        return None
    return GridServicesBand.parse(value.lower() if isinstance(value, str) else value, what=block_path)


def _read_scenario_level_blocks(document: object, *, block_path: str) -> tuple[dict[str, Any], _ScenarioLevelBlocks]:
    """The scenario at *block_path*, refused unless it holds only the keys a scenario reads, and its blocks other than its homes source, read in order."""
    scenario = _refuse_keys_no_scenario_reads(document, block_path=block_path)
    location = parse_location_block(scenario.get("location"), block_path=child_path(block_path, "location"))
    period_path = child_path(block_path, "period")
    period = (
        period_window(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, timezone=location.timezone, block_path=period_path)
        if scenario.get("period") is None
        else _parse_period(scenario["period"], timezone=location.timezone, block_path=period_path)
    )
    return scenario, _ScenarioLevelBlocks(
        name=read_text(scenario, "name", block_path=block_path),
        description=read_text(scenario, "description", block_path=block_path),
        location=location,
        period=period,
        tariff=parse_tariff_config(scenario.get("tariff"), block_path=child_path(block_path, "tariff")),
        seg_tariff_pence_per_kwh=parse_seg_rate(scenario.get("seg"), block_path=child_path(block_path, "seg")),
        finance=parse_finance_config(scenario.get("finance"), block_path=child_path(block_path, "finance")),
        flex_band=_parse_flex_band(scenario.get("flex_band"), block_path=child_path(block_path, "flex_band")),
    )


def _homes_source(scenario: Mapping[str, Any], *, block_path: str) -> str:
    """The one key of _HOMES_SOURCES the scenario at *block_path* sets, refusing it, naming the sources, unless it sets exactly one."""
    given = [key for key in _HOMES_SOURCES if key in scenario]
    if len(given) == 1:
        return given[0]
    sources = ", ".join(repr(key) for key in _HOMES_SOURCES)
    if not given:
        raise refusal(block_path, f"requires the scenario's homes, from exactly one of {sources}")
    raise refusal(
        block_path,
        f"sets {', '.join(repr(key) for key in given)}, but a scenario's homes come from exactly one of {sources}",
    )


def parse_scenario(document: object, *, block_path: str = "") -> ScenarioConfig:
    """Read the scenario mapping at *block_path*: a bare scenario document, or a scenario: block or scenarios: entry.

    A scenario is name and description (strings, "" when absent), location (Bristol when
    absent), period (DEFAULT_FIRST_DAY to DEFAULT_LAST_DAY on the location's clock when absent),
    tariff, seg, finance, flex_band and community, then exactly one homes source: home, homes or
    fleet_distribution. Every home is built at the location, on the tariff unless it sets an equal
    one, and simulated at the seg rate unless it sets its own. Blocks are read in that order, a
    null one as absent; community: is left to load_community_config. The grammar is
    docs/prds/one-scenario-reader.md §4.2.

    Raises:
        ConfigurationError: naming the block's path: for a retired key, naming what replaces it,
            then a key no scenario reads; then for the first block, in that order, its reader
            refuses; then for a scenario setting no homes source or more than one.
    """
    scenario, blocks = _read_scenario_level_blocks(document, block_path=block_path)
    source = _homes_source(scenario, block_path=block_path)
    return _HOMES_SOURCES[source](blocks, scenario[source], block_path=child_path(block_path, source))


_PLACEHOLDER_PATTERN = re.compile(r"\$\{(?P<name>[^}:]+)(?::(?P<default>[^}]*))?\}")


@dataclass(frozen=True)
class _Placeholder:
    """A ${NAME} or ${NAME:default} placeholder: the whole string value at *path* in a document."""

    path: str
    name: str
    default: Optional[float]

    def value(self, variables: Mapping[str, float]) -> Optional[float]:
        """The value *variables* gives NAME, else the default, else None."""
        return variables.get(self.name, self.default)


def _read_placeholder(path: str, text: str) -> Optional[_Placeholder]:
    """The placeholder that *text*, the string value at *path*, is; None if *text* holds none.

    Raises:
        ConfigurationError: naming the key path and the variable, for a placeholder inside a
            longer string, or for a default that is not a finite number.
    """
    whole = _PLACEHOLDER_PATTERN.fullmatch(text)
    if whole is not None:
        name, default = whole["name"], whole["default"]
        default_field = f"{block_label(path)}: the default of variable {name!r}"
        return _Placeholder(path, name, None if default is None else as_finite_float(default, default_field))
    inside = _PLACEHOLDER_PATTERN.search(text)
    if inside is not None:
        raise refusal(
            path,
            f"variable {inside['name']!r} is inside the longer string {text!r}; a placeholder must be the whole value",
        )
    return None


_Document = TypeVar("_Document")


@dataclass(frozen=True)
class _Substitution(Generic[_Document]):
    """A document with each placeholder that has a value replaced by it, read whole through document().

    *partial* is that document, in which a placeholder with no value stays as its text.
    *placeholders* is every placeholder the document held, in document order.
    """

    partial: _Document
    placeholders: tuple[_Placeholder, ...] = ()

    def document(self, variables: Mapping[str, float]) -> _Document:
        """*partial*, once a placeholder names each of *variables*, the variables it was substituted with, and each placeholder has a value.

        Raises:
            ConfigurationError: listing the placeholders, for a supplied variable none of them
                names; then, naming its key path and its variable, for a placeholder neither
                supplied nor defaulted.
        """
        _refuse_unmatched_variables(variables, self.placeholders)
        _refuse_placeholders_without_a_value(variables, self.placeholders)
        return self.partial


def _placeholders_of(parts: Iterable[_Substitution[Any]]) -> tuple[_Placeholder, ...]:
    """The placeholders of each of *parts*, in order."""
    return tuple(placeholder for part in parts for placeholder in part.placeholders)


def _substitute_variables(data: Any, variables: Mapping[str, float], path: str) -> _Substitution[Any]:
    """*data*, the document at *path*, with each placeholder that has a value replaced by it, and every placeholder *data* holds; *data* is left unchanged.

    A placeholder's value is the one *variables* gives its variable, else its default; a
    placeholder with neither stays as its text.
    """
    if isinstance(data, str):
        placeholder = _read_placeholder(path, data)
        if placeholder is None:
            return _Substitution(data)
        value = placeholder.value(variables)
        return _Substitution(data if value is None else value, (placeholder,))
    if isinstance(data, dict):
        return _substitute_mapping(data, variables, path)
    if isinstance(data, list):
        items = [_substitute_variables(item, variables, f"{path}[{index}]") for index, item in enumerate(data)]
        return _Substitution([each.partial for each in items], _placeholders_of(items))
    return _Substitution(data)


_Key = TypeVar("_Key")


def _substitute_mapping(
    data: Mapping[_Key, Any], variables: Mapping[str, float], path: str
) -> _Substitution[dict[_Key, Any]]:
    """*data*, the mapping at *path*, as a new dict of its keys and their values substituted, and the placeholders those hold; its keys are not read."""
    entries = {
        key: _substitute_variables(child, variables, child_path(path, str(key)))
        for key, child in data.items()
    }
    return _Substitution(
        {key: entry.partial for key, entry in entries.items()}, _placeholders_of(entries.values())
    )


def _refuse_unmatched_variables(
    variables: Mapping[str, float], placeholders: tuple[_Placeholder, ...]
) -> None:
    """Refuse *variables* if one of them is named by none of *placeholders*, the document's, listing those."""
    unmatched = sorted(repr(name) for name in variables.keys() - {each.name for each in placeholders})
    if unmatched:
        listed = ", ".join(f"{each.name!r} at {block_label(each.path)}" for each in placeholders)
        held = f"its placeholders: {listed}" if placeholders else "it holds no placeholders"
        raise ConfigurationError(
            f"Variables with no placeholder in the document: {', '.join(unmatched)}; {held}"
        )


def _refuse_placeholders_without_a_value(
    variables: Mapping[str, float], placeholders: tuple[_Placeholder, ...]
) -> None:
    """Refuse the first of *placeholders* that neither *variables* nor its default gives a value, naming its key path and its variable."""
    for each in placeholders:
        if each.value(variables) is None:
            raise refusal(each.path, f"variable {each.name!r} is not supplied and has no default")


def substitute_config_variables(
    config: dict[str, Any], variables: Optional[dict[str, float]] = None
) -> dict[str, Any]:
    """Return *config* with each placeholder in it replaced by its variable's value; *config* is left unchanged.

    A placeholder, ${NAME} or ${NAME:default}, is the whole of a string value in the document.
    It is replaced by the value *variables* gives NAME, else by its default.

    Args:
        config: Configuration dictionary
        variables: Dict mapping variable names to values (default: empty)

    Returns:
        Configuration with variables substituted

    Raises:
        ConfigurationError: naming its key path and its variable, for a placeholder inside a
            longer string or a default that is not a finite number, as the document is read, in
            document order; then, listing the document's placeholders, for a supplied variable
            none of them names; then, naming its key path and its variable, for a placeholder
            neither supplied nor defaulted.
    """
    supplied = variables or {}
    substitution = _substitute_mapping(config, supplied, "")
    return substitution.document(supplied)


def load_config_yaml(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Args:
        path: Path to YAML configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or parsed, naming the file; or if its
            document is not a mapping, naming the top level and the document's type
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: object = yaml.safe_load(f)
        if config is None:
            raise ConfigurationError(f"Empty configuration file: {path}")
        return require_mapping("", config)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e


def load_config_json(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from a JSON file.

    Args:
        path: Path to JSON configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or parsed, naming the file; or if its
            document is not a mapping, naming the top level and the document's type
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: object = json.load(f)
        return require_mapping("", config)
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in {path}: {e}") from e


def load_config(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from YAML or JSON file.

    Auto-detects format by file extension.

    Args:
        path: Path to configuration file (.yaml, .yml, or .json)

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or format unknown
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        return load_config_yaml(path)
    elif suffix == ".json":
        return load_config_json(path)
    else:
        raise ConfigurationError(
            f"Unknown configuration file format: {suffix}. "
            "Supported formats: .yaml, .yml, .json"
        )


def load_scenarios(path: Union[str, Path]) -> list[ScenarioConfig]:
    """Load scenarios from a configuration file.

    Args:
        path: Path to configuration file

    Returns:
        List of ScenarioConfig objects

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)

    if "scenarios" in config:
        return [
            parse_scenario(scenario, block_path=f"scenarios[{index}]")
            for index, scenario in enumerate(require_list("scenarios", config["scenarios"]))
        ]
    elif "scenario" in config:
        return [parse_scenario(config["scenario"], block_path="scenario")]
    else:
        # Try to parse the entire config as a single scenario
        return [parse_scenario(config)]


_FLAT_HOME_FILE_KEYS: frozenset[str] = HOME_BLOCK_KEYS | {"location"}


def load_home_config(path: Union[str, Path]) -> HomeConfig:
    """Load a single home configuration from file.

    The file holds a ``home:`` block, or is itself a home block beside an
    optional ``location:`` block.

    Args:
        path: Path to configuration file

    Returns:
        HomeConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)
    location = parse_location_block(config.get("location"))

    if "home" in config:
        return parse_home_block(config["home"], location)
    refuse_unrecognised_keys("", refuse_retired_keys("", config, RETIRED_DISPATCH_STRATEGY_KEY), _FLAT_HOME_FILE_KEYS)
    flat_home = {key: value for key, value in config.items() if key != "location"}
    return parse_home_block(flat_home, location, block_path="")


@dataclass(frozen=True)
class _FleetFileSettings:
    """What a fleet file gives every home its fleet_distribution: block generates.

    Attributes:
        location: The file's location: block, Bristol when it has none
        tariff: The file's top-level tariff: block, None when it has none
    """

    location: Location
    tariff: Optional[TariffConfig]

    def generate_homes(self, distribution: FleetDistributionConfig) -> list[HomeConfig]:
        """The homes *distribution* generates, each given the file's settings."""
        return generate_homes_from_distribution(
            distribution, self.location, fleet_tariff=self.tariff
        )


def _read_fleet_distribution_file(
    document: Mapping[str, Any],
) -> tuple[FleetDistributionConfig, _FleetFileSettings]:
    """Read the fleet_distribution: block of *document*, with what the file gives every home it generates.

    The one place that decides which top-level blocks those homes get. It reads location:,
    fleet_distribution: and tariff: in that order.
    """
    location = parse_location_block(document.get("location"))
    distribution = parse_fleet_distribution_config(document["fleet_distribution"])
    tariff = parse_tariff_config(document.get("tariff"))
    return distribution, _FleetFileSettings(location=location, tariff=tariff)


def parse_fleet_config(document: object) -> FleetConfig:
    """Parse a fleet file's document, already loaded or variable-substituted.

    Supports two formats:
    - Explicit homes list: `homes: [...]`
    - Distribution-based generation: `fleet_distribution: {...}`

    Args:
        document: The fleet file's document, refused unless it is a mapping

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid, naming the block: a document that is
            no mapping, homes that are no list or list no home, or a document giving neither
            homes nor fleet_distribution
    """
    document = require_mapping("", document)
    if "fleet_distribution" in document:
        distribution, settings = _read_fleet_distribution_file(document)
        homes = settings.generate_homes(distribution)
    elif "homes" in document:
        location = parse_location_block(document.get("location"))
        homes_data = require_list("homes", document["homes"])
        if not homes_data:
            raise refusal("homes", "must list at least one home")
        homes = [
            parse_home_block(home_data, location, block_path=f"homes[{index}]")
            for index, home_data in enumerate(homes_data)
        ]
    else:
        raise refusal("", "requires 'homes' or 'fleet_distribution'")

    return FleetConfig(homes=tuple(homes), name=document.get("name", ""))


def load_fleet_config(path: Union[str, Path]) -> FleetConfig:
    """Load a fleet configuration from file, as parse_fleet_config parses its document.

    Args:
        path: Path to configuration file

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    return parse_fleet_config(load_config(path))


def detect_fleet_sweep_spec(document: object) -> Optional[SweepSpec]:
    """Find the SweepSpec of the document's YAML-defined sweep, the sweep parse_sweep_fleet_configs builds.

    Args:
        document: The fleet file's document, refused unless it is a mapping

    Returns:
        The SweepSpec detect_sweep_spec finds in its fleet_distribution: block, None when
        it has no such block or the block no sweep

    Raises:
        ConfigurationError: If the document is not a mapping, or its fleet_distribution: block
            is invalid
    """
    document = require_mapping("", document)
    if "fleet_distribution" not in document:
        return None
    return detect_sweep_spec(parse_fleet_distribution_config(document["fleet_distribution"]))


def parse_sweep_fleet_configs(document: object) -> list[tuple[float, FleetConfig]]:
    """The fleet each point of the document's YAML-defined sweep builds, with its sweep value.

    The sweep is the fleet_distribution: block's battery.capacity_kwh multiplier. Every
    point's homes get the file's top-level blocks as parse_fleet_config gives them, read
    once for the whole file.

    Args:
        document: The fleet file's document, refused unless it is a mapping

    Returns:
        (sweep value, FleetConfig named after it) for each sweep point, in sweep order

    Raises:
        ConfigurationError: If the document is not a mapping or holds no fleet_distribution:
            block, naming the top level; if the block is not a mapping or holds no sweep,
            naming the block; or if configuration is invalid
    """
    document = require_mapping("", document)
    require_held_keys("", document, ["fleet_distribution"])
    distribution, settings = _read_fleet_distribution_file(document)
    return [
        (value, FleetConfig(homes=tuple(settings.generate_homes(point)), name=f"multiplier={value:.4f}"))
        for value, point in expand_sweep_configs(distribution)
    ]


def load_community_config(path: Union[str, Path]) -> Optional[CommunityConfig]:
    """Load a community configuration from a YAML or JSON file.

    Reads the file with :func:`load_config` and parses the top-level
    ``community:`` block, if present.  Returns ``None`` when the file
    contains no ``community:`` key (e.g. a plain fleet/scenario document).

    Args:
        path: Path to a ``.yaml``, ``.yml``, or ``.json`` configuration file.

    Returns:
        :class:`CommunityConfig` when a ``community:`` block is present;
        ``None`` otherwise.

    Raises:
        ConfigurationError: If the file cannot be read or the community block
            is invalid.
    """
    return parse_community_config(load_config(path).get("community"), block_path="community")
