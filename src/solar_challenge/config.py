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
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Mapping,
    Optional,
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
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import as_finite_float
from solar_challenge.scenario_blocks import (
    HOME_BLOCK_KEYS,
    block_label,
    child_path,
    parse_community_config,
    parse_finance_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
    refuse_unrecognised_keys,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow, covered_days


@dataclass(frozen=True)
class SimulationPeriod:
    """Defines the time period for a simulation.

    Attributes:
        start_date: Start date as string (YYYY-MM-DD) or Timestamp
        end_date: End date as string (YYYY-MM-DD) or Timestamp
    """

    start_date: Union[str, pd.Timestamp]
    end_date: Union[str, pd.Timestamp]

    def get_start_timestamp(self, timezone: str = "Europe/London") -> pd.Timestamp:
        """Get start date as Timestamp."""
        if isinstance(self.start_date, pd.Timestamp):
            return self.start_date
        ts = pd.Timestamp(self.start_date)
        if ts.tz is None:
            ts = ts.tz_localize(timezone)
        return ts

    def get_end_timestamp(self, timezone: str = "Europe/London") -> pd.Timestamp:
        """Get end date as Timestamp."""
        if isinstance(self.end_date, pd.Timestamp):
            return self.end_date
        ts = pd.Timestamp(self.end_date)
        if ts.tz is None:
            ts = ts.tz_localize(timezone)
        return ts


_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
"""The one string form a period's day takes: 'YYYY-MM-DD'."""


def _period_day(value: object, field: str) -> date:
    """The calendar day *value*, the period's *field*, gives: a datetime's or Timestamp's own date on its own clock, a date as it is, or a 'YYYY-MM-DD' string's day.

    Raises:
        ConfigurationError: For any other value, such as NaT, '2024' or '20240601', naming period.<field>,
            the value and the forms a period's day takes.
    """
    if isinstance(value, datetime) and value is not pd.NaT:
        return value.date()
    if type(value) is date:
        return value
    if isinstance(value, str) and _ISO_DAY.fullmatch(value):
        with contextlib.suppress(ValueError):
            return date.fromisoformat(value)
    raise ConfigurationError(
        f"period.{field} is {value!r}, which is not a day: "
        "give a date, a 'YYYY-MM-DD' string or a Timestamp"
    )


@dataclass(frozen=True)
class OutputConfig:
    """Configuration for simulation output.

    Attributes:
        csv_path: Path to save CSV results (optional)
        include_minute_data: Include 1-minute resolution data in output
        include_summary: Include summary statistics
        aggregation: Aggregation level for output (minute, daily, monthly, annual)
    """

    csv_path: Optional[str] = None
    include_minute_data: bool = True
    include_summary: bool = True
    aggregation: str = "minute"


@dataclass(frozen=True)
class ScenarioConfig:
    """Configuration for a simulation scenario.

    Attributes:
        name: Scenario identifier
        description: Human-readable description
        location: Geographic location (defaults to Bristol)
        period: Simulation period; construction refuses one whose days are not a date,
            a 'YYYY-MM-DD' string or a Timestamp, or whose last day precedes its first
        homes: Home configurations (for fleet simulation); a list is held as a tuple
        home: Single home configuration (for single-home simulation)
        output: Output preferences
        seg_tariff_pence_per_kwh: Smart Export Guarantee rate in pence/kWh (optional), read
            as SEGTariff reads its rate; a home whose own seg_tariff sets another rate is refused
        tariff_config: Refused when set: no simulation reads it, so a home's
            tariff is its HomeConfig.tariff_config
        finance: Financial appraisal parameters (None for no financial analysis)
    """

    name: str
    period: SimulationPeriod
    description: str = ""
    location: Optional[Location] = None
    homes: tuple[HomeConfig, ...] = ()
    home: Optional[HomeConfig] = None
    output: Optional[OutputConfig] = None
    seg_tariff_pence_per_kwh: Optional[float] = None
    tariff_config: Optional[TariffConfig] = None
    finance: Optional[FinanceConfig] = None

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
        if self.tariff_config is not None:
            raise ConfigurationError(
                f"Scenario '{self.name}' sets tariff_config, which no simulation reads: "
                "give each home its tariff as HomeConfig.tariff_config"
            )
        self._refuse_a_period_that_is_not_a_run_of_days()

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
        """The period's first and last calendar days at ONE_MINUTE, in the zone of location, or of the first home's location when location is None."""
        first_day, last_day = self._period_days()
        return SimulationWindow(first_day, last_day, ONE_MINUTE, self._timezone())

    def with_window(
        self, *, first_day: Optional[date] = None, last_day: Optional[date] = None
    ) -> "ScenarioConfig":
        """A copy whose period keeps each day not given, checked as construction checks."""
        changes: dict[str, str] = {}
        if first_day is not None:
            changes["start_date"] = first_day.isoformat()
        if last_day is not None:
            changes["end_date"] = last_day.isoformat()
        return replace(self, period=replace(self.period, **changes))

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

    def _period_days(self) -> tuple[date, date]:
        """The period's first and last calendar days, each read by _period_day, whose refusal is prefixed with the scenario's name."""
        try:
            return (
                _period_day(self.period.start_date, "start_date"),
                _period_day(self.period.end_date, "end_date"),
            )
        except ConfigurationError as exc:
            raise ConfigurationError(f"Scenario '{self.name}': {exc}") from exc

    def _refuse_a_period_that_is_not_a_run_of_days(self) -> None:
        """Raise ConfigurationError for a period day that is not a day, as _period_days does; then, naming the scenario and both fields and days, for a last day before the first, through covered_days, the one home of that rule."""
        first_day, last_day = self._period_days()
        try:
            covered_days(first_day, last_day)
        except ValueError as exc:
            raise ConfigurationError(
                f"Scenario '{self.name}' has period.start_date {first_day.isoformat()} and "
                f"period.end_date {last_day.isoformat()}: {exc}"
            ) from exc

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


def _parse_period(data: dict[str, Any], *, block_path: str) -> SimulationPeriod:
    """Parse simulation period from config data."""
    refuse_unrecognised_keys(block_path, data, _PERIOD_BLOCK_KEYS)
    if "start_date" not in data or "end_date" not in data:
        raise ConfigurationError("Simulation period requires 'start_date' and 'end_date'")
    return SimulationPeriod(
        start_date=data["start_date"],
        end_date=data["end_date"],
    )


_OUTPUT_BLOCK_KEYS: frozenset[str] = frozenset({
    "csv_path", "include_minute_data", "include_summary", "aggregation",
})


def _parse_output_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[OutputConfig]:
    """Parse output configuration from config data."""
    if data is None:
        return None
    refuse_unrecognised_keys(block_path, data, _OUTPUT_BLOCK_KEYS)
    return OutputConfig(
        csv_path=data.get("csv_path"),
        include_minute_data=data.get("include_minute_data", True),
        include_summary=data.get("include_summary", True),
        aggregation=data.get("aggregation", "minute"),
    )


def _parse_scenario(data: dict[str, Any], *, block_path: str) -> ScenarioConfig:
    """Parse a scenario from config data."""
    if "name" not in data:
        raise ConfigurationError("Scenario must have a 'name' field")
    if "period" not in data:
        raise ConfigurationError(f"Scenario '{data['name']}' must have a 'period' field")

    location = parse_location_block(
        data.get("location"), block_path=child_path(block_path, "location")
    )

    homes: list[HomeConfig] = []
    home: Optional[HomeConfig] = None

    if "homes" in data:
        for index, home_data in enumerate(data["homes"]):
            homes.append(
                parse_home_block(
                    home_data, location, block_path=child_path(block_path, f"homes[{index}]")
                )
            )
    elif "home" in data:
        home = parse_home_block(data["home"], location, block_path=child_path(block_path, "home"))
    else:
        raise ConfigurationError(
            f"Scenario '{data['name']}' must define either 'home' or 'homes'"
        )

    return ScenarioConfig(
        name=data["name"],
        description=data.get("description", ""),
        location=location,
        period=_parse_period(data["period"], block_path=child_path(block_path, "period")),
        homes=tuple(homes),
        home=home,
        output=_parse_output_config(
            data.get("output"), block_path=child_path(block_path, "output")
        ),
        seg_tariff_pence_per_kwh=parse_seg_rate(
            data.get("seg"), block_path=child_path(block_path, "seg")
        ),
        tariff_config=parse_tariff_config(
            data.get("tariff_config"), block_path=child_path(block_path, "tariff_config")
        ),
        finance=parse_finance_config(
            data.get("finance"), block_path=child_path(block_path, "finance")
        ),
    )


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
        raise ConfigurationError(
            f"{block_label(path)}: variable {inside['name']!r} is inside the longer string {text!r}; "
            "a placeholder must be the whole value"
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
            raise ConfigurationError(
                f"{block_label(each.path)}: variable {each.name!r} is not supplied and has no default"
            )


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
        ConfigurationError: If file cannot be read or parsed
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: dict[str, Any] = yaml.safe_load(f)
        if config is None:
            raise ConfigurationError(f"Empty configuration file: {path}")
        return config
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e


def load_config_json(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from a JSON file.

    Args:
        path: Path to JSON configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or parsed
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: dict[str, Any] = json.load(f)
        return config
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
            _parse_scenario(scenario, block_path=f"scenarios[{index}]")
            for index, scenario in enumerate(config["scenarios"])
        ]
    elif "scenario" in config:
        return [_parse_scenario(config["scenario"], block_path="scenario")]
    else:
        # Try to parse the entire config as a single scenario
        return [_parse_scenario(config, block_path="")]


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
    refuse_unrecognised_keys("", config, _FLAT_HOME_FILE_KEYS)
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


def parse_fleet_config(document: Mapping[str, Any]) -> FleetConfig:
    """Parse a fleet file's document, already loaded or variable-substituted.

    Supports two formats:
    - Explicit homes list: `homes: [...]`
    - Distribution-based generation: `fleet_distribution: {...}`

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    if "fleet_distribution" in document:
        distribution, settings = _read_fleet_distribution_file(document)
        homes = settings.generate_homes(distribution)
    elif "homes" in document:
        location = parse_location_block(document.get("location"))
        homes_data = document["homes"]
        if not homes_data:
            raise ConfigurationError("Fleet 'homes' list cannot be empty")
        homes = [
            parse_home_block(home_data, location, block_path=f"homes[{index}]")
            for index, home_data in enumerate(homes_data)
        ]
    else:
        raise ConfigurationError(
            "Fleet configuration requires either 'homes' list or 'fleet_distribution'"
        )

    return FleetConfig(homes=homes, name=document.get("name", ""))


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


def detect_fleet_sweep_spec(document: Mapping[str, Any]) -> Optional[SweepSpec]:
    """Find the SweepSpec of the document's YAML-defined sweep, the sweep parse_sweep_fleet_configs builds.

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        The SweepSpec detect_sweep_spec finds in its fleet_distribution: block, None when
        it has no such block or the block no sweep

    Raises:
        ConfigurationError: If its fleet_distribution: block is invalid
    """
    if "fleet_distribution" not in document:
        return None
    return detect_sweep_spec(parse_fleet_distribution_config(document["fleet_distribution"]))


def parse_sweep_fleet_configs(document: Mapping[str, Any]) -> list[tuple[float, FleetConfig]]:
    """The fleet each point of the document's YAML-defined sweep builds, with its sweep value.

    The sweep is the fleet_distribution: block's battery.capacity_kwh multiplier. Every
    point's homes get the file's top-level blocks as parse_fleet_config gives them, read
    once for the whole file.

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        (sweep value, FleetConfig named after it) for each sweep point, in sweep order

    Raises:
        ConfigurationError: If the document has no fleet_distribution: block or no
            sweep, or if configuration is invalid
    """
    if "fleet_distribution" not in document:
        raise ConfigurationError("A YAML-defined sweep requires a 'fleet_distribution' block")
    distribution, settings = _read_fleet_distribution_file(document)
    return [
        (value, FleetConfig(homes=settings.generate_homes(point), name=f"multiplier={value:.4f}"))
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
    raw = load_config(path)
    # yaml.safe_load returns None for an empty file; coerce to a dict so that
    # .get("community") works cleanly and returns None rather than raising
    # AttributeError.
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return parse_community_config(data.get("community"), block_path="community")
