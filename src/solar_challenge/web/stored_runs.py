# SPDX-License-Identifier: AGPL-3.0-or-later
"""The documents a run's directory holds for each kind of run, and how they are written and read.

A home run's directory holds config.json, its HomeConfig; summary.json, its
SummaryStatistics; and data.parquet, the time series of its SimulationResults. A fleet
run's holds config.json, each home's HomeConfig in the fleet's order with their count;
summary.json, its FleetSummary; and homes/, each home's time series and summary as
home_{i}.parquet and home_{i}_summary.json. Each config and summary is its dataclass's
field tree in JSON.

StoredHomeRun and StoredFleetRun are the runs as their directories store them: each
writes its documents and answers its run's CSV export. RunType names the types of run,
RUN_TYPES in order, and RUN_KINDS is the run type to behaviour table, one RunKind per
RunType; a kind also decodes the summary and the HomeConfigs a run's record holds, and
builds from the HomeConfigs the scenario its YAML export answers with. A kind also names
the run created without a name. Where a run's directory lives, and the runs table that
records each run's type, are RunStorage's: nothing here reads SQL or Flask.
"""

import functools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Any, Literal, Type, TypeVar, Union, get_args, get_origin, get_type_hints

import pandas as pd

from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.scenario_writer import fleet_scenario, home_scenario
from solar_challenge.web.run_names import is_run_name

RunType = Literal["home", "fleet"]  # the type of a run, held by the runs table's type column
RUN_TYPES: tuple[RunType, ...] = get_args(RunType)

T = TypeVar("T")


def _serialize_dataclass(obj: Any) -> dict[str, Any]:
    """Serialize a dataclass instance to a JSON-compatible dict.

    Each field is emitted as _serialize_value emits it.

    Args:
        obj: Dataclass instance to serialize

    Returns:
        JSON-compatible dictionary
    """
    if not is_dataclass(obj):
        raise TypeError(f"Expected dataclass, got {type(obj)}")

    return {
        field_info.name: _serialize_value(getattr(obj, field_info.name))
        for field_info in fields(obj)
    }


def _serialize_value(value: Any) -> Any:
    """Emit one value in its JSON-compatible form.

    A dataclass becomes a dict. A pd.Timestamp becomes its ISO string. A list or
    tuple becomes a list, and a dict keeps its keys, with every item serialized the
    same way. Anything else, None included, is returned unchanged.
    """
    if is_dataclass(value):
        return _serialize_dataclass(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _deserialize_dataclass(cls: Type[T], data: dict[str, Any]) -> T:
    """Recursively deserialize a dict to a dataclass instance.

    Each field its constructor takes that the dict holds is rebuilt as its annotation
    declares: nested dataclasses, lists and tuples of them, pd.Timestamp values and
    optional members. Any other key, a field no constructor takes or one the class does
    not have, is skipped.

    Args:
        cls: The dataclass type to instantiate
        data: Dictionary with serialized data

    Returns:
        Instance of cls with deserialized data
    """
    if not is_dataclass(cls):
        raise TypeError(f"Expected dataclass type, got {cls}")

    field_types = _field_types(cls)
    kwargs = {
        each.name: None if data[each.name] is None else _deserialize_value(data[each.name], field_types[each.name])
        for each in fields(cls)
        if each.init and each.name in data
    }
    return cls(**kwargs)


@functools.cache
def _field_types(cls: type) -> Mapping[str, Any]:
    """Return the type each field of dataclass *cls* is annotated with.

    Resolved once per class and shared by every later call, so the mapping is read-only.

    Raises:
        NameError: An annotation names a type cls's module does not bind.
    """
    return MappingProxyType(get_type_hints(cls))


def _deserialize_value(value: Any, annotation: Any) -> Any:
    """Rebuild one JSON-decoded value as its annotation declares.

    A union is read as the member _union_member picks. A dict becomes a dataclass.
    An array becomes a list or a tuple, with every item rebuilt the same way.
    An ISO string becomes a pd.Timestamp. Anything else is returned unchanged.
    """
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return _deserialize_value(value, _union_member(annotation, value))
    if isinstance(value, dict) and isinstance(annotation, type) and is_dataclass(annotation):
        return _deserialize_dataclass(annotation, value)
    if isinstance(value, list) and origin in (list, tuple):
        item_annotation = _item_annotation(annotation)
        items = [_deserialize_value(item, item_annotation) for item in value]
        return tuple(items) if origin is tuple else items
    if isinstance(value, str) and isinstance(annotation, type) and issubclass(annotation, pd.Timestamp):
        return pd.Timestamp(value)
    return value


def _union_member(annotation: Any, value: Any) -> Any:
    """The member of union *annotation* a stored, non-null *value* is rebuilt as.

    When the union's non-None members are dataclasses that each tag themselves with the
    same field, the member is the one whose tag is *value*'s; otherwise it is the first
    non-None member.

    Raises:
        ValueError: For members tagged with a field when no member's tag is *value*'s,
            naming the field, *value*'s value of it and the members' tags.
    """
    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    tag_field = _shared_tag_field(members)
    if tag_field is None:
        return next(iter(members), Any)
    tags = [_tags(member)[tag_field] for member in members]
    stored = value.get(tag_field) if isinstance(value, dict) else None
    if stored not in tags:
        raise ValueError(f"{tag_field} {stored!r} is not one of {tags}")
    return members[tags.index(stored)]


def _shared_tag_field(members: Sequence[Any]) -> str | None:
    """The one field each of *members* tags itself with; None when they share no such field, or more than one."""
    shared = set.intersection(*(set(_tags(member)) for member in members)) if members else set()
    return shared.pop() if len(shared) == 1 else None


def _tags(cls: Any) -> dict[str, Any]:
    """Each field of *cls*, a dataclass, that tags it: no constructor takes it and it is annotated with a one-value Literal, with that value.

    Empty for anything other than a dataclass.
    """
    if not (isinstance(cls, type) and is_dataclass(cls)):
        return {}
    field_types = _field_types(cls)
    return {
        each.name: get_args(field_types[each.name])[0]
        for each in fields(cls)
        if not each.init
        and get_origin(field_types[each.name]) is Literal
        and len(get_args(field_types[each.name])) == 1
    }


def _item_annotation(sequence_annotation: Any) -> Any:
    """Return the annotation shared by every item of list[X], tuple[X, ...] or tuple[X, X].

    Any when the items do not share one annotation, as in tuple[A, B].
    """
    item_annotations = {arg for arg in get_args(sequence_annotation) if arg is not Ellipsis}
    return item_annotations.pop() if len(item_annotations) == 1 else Any


def _home_run_configs(config_document: Mapping[str, Any]) -> tuple[HomeConfig, ...]:
    """The one HomeConfig a home run's config document holds, as StoredHomeRun.config_document wrote it."""
    return (_deserialize_dataclass(HomeConfig, dict(config_document)),)


def _fleet_run_configs(config_document: Mapping[str, Any]) -> tuple[HomeConfig, ...]:
    """Each HomeConfig a fleet run's config document holds, in the fleet's order, as StoredFleetRun.config_document wrote it."""
    return tuple(_deserialize_dataclass(HomeConfig, dict(home)) for home in config_document["homes"])


def _home_run_scenario(home_configs: Sequence[HomeConfig], name: str) -> dict[str, Any]:
    """The scenario *name* a home run of the one HomeConfig in *home_configs* exports: home_scenario of it.

    Raises:
        ValueError: *home_configs* does not hold exactly one HomeConfig, or the scenario grammar
            cannot express it.
    """
    (home,) = home_configs
    return home_scenario(home, name=name)


def _fleet_run_scenario(home_configs: Sequence[HomeConfig], name: str) -> dict[str, Any]:
    """The scenario *name* a fleet run of *home_configs* exports: fleet_scenario of them, in order.

    Raises:
        ValueError: The scenario grammar cannot express the homes, as fleet_scenario refuses them.
    """
    return fleet_scenario(home_configs, name=name)


def _home_run_default_name(home_configs: Sequence[HomeConfig]) -> str:
    """The name a home run of *home_configs* given none is created under: its first home's name when that can name a run, else "Web Simulation"."""
    first_home_name = home_configs[0].name if home_configs else None
    return first_home_name if is_run_name(first_home_name) else "Web Simulation"


def _fleet_run_default_name(home_configs: Sequence[HomeConfig]) -> str:
    """The name a fleet run given none is created under, whatever its *home_configs*: "Fleet Simulation"."""
    return "Fleet Simulation"


@dataclass(frozen=True)
class StoredHomeRun:
    """A home run as its directory stores it: the run's HomeConfig, its results and their summary."""

    run_id: str
    config: HomeConfig
    results: SimulationResults
    summary: SummaryStatistics

    def config_document(self) -> dict[str, Any]:
        """The run's config.json document: its HomeConfig's field tree."""
        return _serialize_dataclass(self.config)

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its SummaryStatistics' field tree."""
        return _serialize_dataclass(self.summary)

    def write(self, run_dir: Path, config_document: dict[str, Any], summary_document: dict[str, Any]) -> None:
        """Write the run into *run_dir*, creating it if need be: *config_document* as config.json, *summary_document* as summary.json, and data.parquet.

        The two documents are the run's config_document() and summary_document(), which its
        save builds once for these files and its runs row alike.
        """
        # Create run directory
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write config to JSON
        config_path = run_dir / "config.json"
        with config_path.open("w") as f:
            json.dump(config_document, f, indent=2)

        # Write summary to JSON
        summary_path = run_dir / "summary.json"
        with summary_path.open("w") as f:
            json.dump(summary_document, f, indent=2)

        # Save time series DataFrame to parquet
        df = self.results.to_dataframe()
        parquet_path = run_dir / "data.parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

    def export_frame(self) -> pd.DataFrame:
        """The run's time series, as its CSV export holds them: one column per series of its results."""
        return self.results.to_dataframe()


@dataclass(frozen=True)
class StoredFleetRun:
    """A fleet run as its directory stores it: each home's HomeConfig and results, the fleet's summary and each home's summary, in the fleet's order."""

    run_id: str
    fleet_results: FleetResults
    summary: FleetSummary
    home_summaries: tuple[SummaryStatistics, ...]

    def __post_init__(self) -> None:
        """Refuse, with a ValueError naming both counts, home_summaries that do not pair one summary with each home's results."""
        n_homes = len(self.fleet_results.per_home_results)
        if len(self.home_summaries) != n_homes:
            raise ValueError(
                "StoredFleetRun pairs one summary with each home's results: "
                f"got {n_homes} homes' results and {len(self.home_summaries)} home_summaries"
            )

    def config_document(self) -> dict[str, Any]:
        """The run's config.json document: each home's HomeConfig field tree, in the fleet's order, and their count."""
        return {
            "homes": [_serialize_dataclass(home) for home in self.fleet_results.home_configs],
            "n_homes": len(self.fleet_results.home_configs),
        }

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its FleetSummary's field tree."""
        return _serialize_dataclass(self.summary)

    def write(self, run_dir: Path, config_document: dict[str, Any], summary_document: dict[str, Any]) -> None:
        """Write the run into *run_dir*, creating it if need be: *config_document* as config.json, *summary_document* as summary.json, and in homes/ each home's time series and summary.

        The two documents are the run's config_document() and summary_document(), which its
        save builds once for these files and its runs row alike.
        """
        # Create run directory and homes subdirectory
        run_dir.mkdir(parents=True, exist_ok=True)
        homes_dir = run_dir / "homes"
        homes_dir.mkdir(exist_ok=True)

        # Save fleet config (list of HomeConfigs) to JSON
        config_path = run_dir / "config.json"
        with config_path.open("w") as f:
            json.dump(config_document, f, indent=2)

        # Save fleet summary to JSON
        summary_path = run_dir / "summary.json"
        with summary_path.open("w") as f:
            json.dump(summary_document, f, indent=2)

        # Save per-home results to parquet files in homes/ subdirectory
        for i, (home_result, home_summary) in enumerate(zip(self.fleet_results.per_home_results, self.home_summaries, strict=True)):
            # Save time series data
            df = home_result.to_dataframe()
            parquet_path = homes_dir / f"home_{i}.parquet"
            df.to_parquet(parquet_path, engine="pyarrow")

            # Save per-home summary
            home_summary_dict = _serialize_dataclass(home_summary)
            home_summary_path = homes_dir / f"home_{i}_summary.json"
            with home_summary_path.open("w") as f:
                json.dump(home_summary_dict, f, indent=2)

    def export_frame(self) -> pd.DataFrame:
        """The fleet's total time series, as its CSV export holds them: FleetResults.to_aggregate_dataframe, the sum across its homes."""
        return self.fleet_results.to_aggregate_dataframe()


StoredRun = StoredHomeRun | StoredFleetRun


def _read_home_run(run_dir: Path, run_id: str) -> StoredHomeRun:
    """The home run *run_id* that *run_dir* holds, read from the documents StoredHomeRun.write writes.

    Raises:
        FileNotFoundError: A document the run needs is missing; the message names its path.
        ValueError: A document is corrupted or incomplete.
    """
    # Load config from JSON
    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r") as f:
        config_dict = json.load(f)
    (config,) = _home_run_configs(config_dict)

    # Load summary from JSON
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    with summary_path.open("r") as f:
        summary_dict = json.load(f)
    summary = _deserialize_dataclass(SummaryStatistics, summary_dict)

    # Load time series from parquet
    parquet_path = run_dir / "data.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(f"Data file not found: {parquet_path}")
    df = pd.read_parquet(parquet_path, engine="pyarrow")
    results = SimulationResults.from_dataframe(df, strategy_name=summary.strategy_name)

    return StoredHomeRun(run_id=run_id, config=config, results=results, summary=summary)


def _read_fleet_run(run_dir: Path, run_id: str) -> StoredFleetRun:
    """The fleet run *run_id* that *run_dir* holds, read from the documents StoredFleetRun.write writes.

    Raises:
        FileNotFoundError: A document the run needs is missing; the message names its path.
        ValueError: A document is corrupted or incomplete.
    """
    homes_dir = run_dir / "homes"
    if not homes_dir.exists():
        raise FileNotFoundError(f"Homes directory not found: {homes_dir}")

    # Load fleet config from JSON
    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r") as f:
        fleet_config_dict = json.load(f)

    home_configs = list(_fleet_run_configs(fleet_config_dict))

    # Load fleet summary from JSON
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    with summary_path.open("r") as f:
        summary_dict = json.load(f)
    fleet_summary = _deserialize_dataclass(FleetSummary, summary_dict)

    # Load per-home results from homes/ subdirectory
    n_homes = len(home_configs)
    per_home_results: list[SimulationResults] = []
    per_home_summaries: list[SummaryStatistics] = []

    for i in range(n_homes):
        # Load time series data
        parquet_path = homes_dir / f"home_{i}.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(f"Home {i} data file not found: {parquet_path}")
        df = pd.read_parquet(parquet_path, engine="pyarrow")

        # Load per-home summary
        home_summary_path = homes_dir / f"home_{i}_summary.json"
        if not home_summary_path.exists():
            raise FileNotFoundError(f"Home {i} summary not found: {home_summary_path}")
        with home_summary_path.open("r") as f:
            home_summary_dict = json.load(f)
        home_summary = _deserialize_dataclass(SummaryStatistics, home_summary_dict)
        per_home_summaries.append(home_summary)
        per_home_results.append(
            SimulationResults.from_dataframe(df, strategy_name=home_summary.strategy_name)
        )

    # Construct FleetResults
    fleet_results = FleetResults(
        per_home_results=per_home_results,
        home_configs=home_configs,
    )

    return StoredFleetRun(
        run_id=run_id,
        fleet_results=fleet_results,
        summary=fleet_summary,
        home_summaries=tuple(per_home_summaries),
    )


@dataclass(frozen=True)
class RunKind:
    """What a run of one type has, how its stored documents are read, and how its config is exported.

    Attributes:
        summary_type: The class of the summary a run of the type has.
        read: The run stored in a directory under an id, read from its documents; it raises
            FileNotFoundError when a document it needs is missing.
        home_configs: Each home's HomeConfig, in order, decoded from the config document
            the run's record holds.
        scenario_document: The scenario, under a name, that a run of the type with those
            HomeConfigs exports as YAML; it raises ValueError when the scenario grammar cannot
            express them.
        default_name: The name a run of the type with those HomeConfigs is created under
            when it is given none; is_run_name holds for it.
    """

    summary_type: type[SummaryStatistics] | type[FleetSummary]
    read: Callable[[Path, str], StoredRun]
    home_configs: Callable[[Mapping[str, Any]], tuple[HomeConfig, ...]]
    scenario_document: Callable[[Sequence[HomeConfig], str], dict[str, Any]]
    default_name: Callable[[Sequence[HomeConfig]], str]

    def summary(self, summary_document: Mapping[str, Any]) -> SummaryStatistics | FleetSummary:
        """The summary *summary_document* holds: the field tree of a summary_type, rebuilt as one.

        Raises:
            TypeError, ValueError: The document is not a summary_type's field tree, e.g. lacks
                a field summary_type requires, or summary_type refuses the figures it holds.
        """
        return _deserialize_dataclass(self.summary_type, dict(summary_document))


RUN_KINDS: Mapping[RunType, RunKind] = MappingProxyType(
    {
        "home": RunKind(
            summary_type=SummaryStatistics,
            read=_read_home_run,
            home_configs=_home_run_configs,
            scenario_document=_home_run_scenario,
            default_name=_home_run_default_name,
        ),
        "fleet": RunKind(
            summary_type=FleetSummary,
            read=_read_fleet_run,
            home_configs=_fleet_run_configs,
            scenario_document=_fleet_run_scenario,
            default_name=_fleet_run_default_name,
        ),
    }
)
"""The kind of run each RunType names, keyed by that type."""
