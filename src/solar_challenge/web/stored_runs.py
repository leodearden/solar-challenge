# SPDX-License-Identifier: AGPL-3.0-or-later
"""The documents a run's directory holds for each kind of run, and how they are written and read.

A home run's directory holds config.json, its HomeConfig; summary.json, its
SummaryStatistics; and data.parquet, the time series of its SimulationResults. A fleet
run's holds config.json, its FleetRunConfig: each home's HomeConfig in the fleet's order
with their count; summary.json, its FleetSummary; and homes/, each home's time series and
summary as home_{i}.parquet and home_{i}_summary.json. Each config and summary is its
dataclass's field tree in JSON. Every save writes the documents, each to a temporary file then
moved into place, and last format.json, {"format_version": RUN_FORMAT_VERSION}, so a directory
without it holds a run saved before runs carried a format version, or a save that did not
finish. A run is read only after its format.json names RUN_FORMAT_VERSION.

A document is read strictly, as StoredDocument.read reads it: each JSON value must be one
its field's annotation can be, and the dataclass built from them must accept them. A key
no field has, a missing field that has no default, a value of a JSON type its annotation
cannot be (an object for a dataclass, an array for a sequence, a number but no bool for a
number, null only for an Optional field, one of a Literal's values), an unknown union tag,
or a dataclass that refuses its values is refused with a StoredRunUnreadable naming the
run, the document, the field's dotted path and the reason. A missing field that has a
default takes it. Non-JSON text, a missing document and a time series that cannot be read
are refused the same way. StoredRunUnreadable is not a ValueError: a request's bad value is a ValueError the
boundary answers 400, while a stored run that cannot be read is answered 409 or flashed.

StoredHomeRun and StoredFleetRun are the runs as their directories store them: each
writes its documents and answers its run's CSV export. RunType names the types of run,
RUN_TYPES in order, and RUN_KINDS is the run type to behaviour table, one RunKind per
RunType; a kind also reads the summary and the HomeConfigs a run's record holds, and
builds from the HomeConfigs the scenario its YAML export answers with. A kind also names
the run created without a name. Where a run's directory lives, and the runs table that
records each run's type, are RunStorage's: nothing here reads SQL or Flask.

The documents are in the format of version RUN_FORMAT_VERSION, the version of the last step
in RUN_DOCUMENT_STEPS. Each RunDocumentStep brings a run's JSON documents, read as
read_run_documents reads them, from the version before its own to its own. Its apply is
pure, and applying it to its own result changes nothing and drops nothing. v2, the first,
drops each key a document's dataclass does not have, as the reader skipped such keys before
runs carried a format version, and reports each dropped value that is not null.
documents_in_current_format folds every step over a legacy run's documents in memory.
`solar-challenge web migrate` applies each step to every stored run's files and runs row
through step_run_documents, which checks that the documents it brings forward will read once
at RUN_FORMAT_VERSION; write_run_documents then writes the documents a step changed and the
run's format.json last. A run whose documents cannot be brought forward is left as it was, an
UnmigratedRun naming it.

A change to a stored dataclass's shape, such as a renamed or retired field or a new field
with no default, ships with a RunDocumentStep of the next version appended to
RUN_DOCUMENT_STEPS, the schema step of that version, and a legacy fixture in
tests/fixtures/stored_runs whose documents the step changes (contract C10);
tests/unit/test_web_run_document_steps.py runs every step over every fixture. Steps run in
order and v2 drops each key today's dataclasses lack, so a later step that reads a renamed or
retired field's old key must keep v2 from dropping it.
"""

import functools
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Any, Literal, TypeVar, Union, get_args, get_origin, get_type_hints

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


class StoredRunUnreadable(Exception):
    """A stored run that cannot be rebuilt from its documents; the message names the run, the document, the field and the reason.

    document is a file of the run's directory, e.g. "summary.json", "homes/home_0_summary.json"
    or "data.parquet", or the runs column holding a copy, e.g. "runs.summary_json". field is
    the dotted path of the refused value in the document, with [i] for an item; None means the
    document as a whole. It is not a ValueError: a request's bad value is a ValueError the
    boundary answers 400, while a stored run that cannot be read is answered 409 or flashed
    (docs/prds/run-store-one-owner.md §3.10).
    """

    def __init__(self, run_id: str, document: str, field: str | None, reason: str) -> None:
        super().__init__(f"The stored run {run_id!r} cannot be read: {_refused_value(document, field)} {reason}")
        self.run_id = run_id
        self.document = document
        self.field = field
        self.reason = reason


def _refused_value(document: str, field: str | None) -> str:
    """The value of *document* at *field* that a refusal names, the document as a whole when *field* is None."""
    return document if field is None else f"{document}'s {field}"


class _Refused(Exception):
    """A value the strict reader refuses within one document: its dotted path, None for the document's root, and the reason."""

    def __init__(self, path: str | None, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class StoredDocument:
    """One document of a stored run: the run's id, the document's name and its decoded JSON content.

    The name is a file of the run's directory, e.g. "summary.json", or the runs column
    holding a copy, e.g. "runs.summary_json"; StoredRunUnreadable names it.
    """

    run_id: str
    name: str
    content: Any

    @classmethod
    def decoded(cls, run_id: str, name: str, text: str | bytes) -> "StoredDocument":
        """The document *name* of run *run_id* whose JSON text is *text*.

        Raises:
            StoredRunUnreadable: *text* is not JSON; its field is None.
        """
        try:
            return cls(run_id, name, json.loads(text))
        except ValueError as refusal:
            raise StoredRunUnreadable(run_id, name, None, f"is not JSON: {refusal}") from refusal

    def read(self, cls: type[T]) -> T:
        """The *cls*, a dataclass, whose field tree the document holds, each value read as its field's annotation declares.

        Raises:
            StoredRunUnreadable: The document holds a key no field has, lacks a field that has
                no default, holds a value of a JSON type its annotation cannot be or an unknown
                union tag, or a dataclass refuses its values, whose refusal is then the cause.
        """
        try:
            value = _read_value(self.content, cls, None)
        except _Refused as refused:
            raise StoredRunUnreadable(self.run_id, self.name, refused.path, refused.reason) from refused.__cause__
        assert isinstance(value, cls)
        return value


def _read_value(value: Any, annotation: Any, path: str | None) -> Any:
    """*value*, decoded JSON at *path* in its document, read as *annotation* declares.

    A union is read by _read_union. A dataclass is read from an object by _read_dataclass, a
    list or tuple from an array by _read_sequence, a dict's values from an object, a
    pd.Timestamp from its ISO text. A Literal, bool, int, float and str admit only values of
    their JSON type; an int or a float is any number but a bool, kept as decoded. Any admits
    anything as it is.

    Raises:
        _Refused: *value* cannot be *annotation*, or *annotation* has no stored form.
    """
    origin = get_origin(annotation)
    if annotation is Any:
        return value
    if origin in (Union, UnionType):
        return _read_union(value, annotation, path)
    if value is None:
        raise _Refused(path, f"is null, not {_stored_form(annotation)}")
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _read_dataclass(value, annotation, path)
    if origin in (list, tuple):
        return _read_sequence(value, annotation, path)
    if origin is dict:
        if not isinstance(value, dict):
            raise _Refused(path, f"is {_json_value(value)}, not an object")
        value_annotation = _value_annotation(annotation)
        return {key: _read_value(item, value_annotation, _child(path, key)) for key, item in value.items()}
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in get_args(annotation)):
            return value
    elif annotation is bool:
        if isinstance(value, bool):
            return value
    elif annotation in (int, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    elif annotation is str:
        if isinstance(value, str):
            return value
    elif isinstance(annotation, type) and issubclass(annotation, pd.Timestamp):
        if isinstance(value, str):
            try:
                return pd.Timestamp(value)
            except ValueError as refusal:
                raise _Refused(path, f"is {_json_value(value)}, not a timestamp: {refusal}") from refusal
    else:
        raise _Refused(path, f"has no stored form: the stored-run format reads no {annotation!r}")
    raise _Refused(path, f"is {_json_value(value)}, not {_stored_form(annotation)}")


def _read_union(value: Any, annotation: Any, path: str | None) -> Any:
    """*value* read as union *annotation*: null only when None is a member, else as the member _union_member picks.

    Raises:
        _Refused: *value* is null and None is no member; its members tag themselves and it is
            no object, or its tag names no member, refused at the tag's path; or the member
            refuses it.
    """
    if value is None:
        if type(None) in get_args(annotation):
            return None
        raise _Refused(path, f"is null, not {_stored_form(annotation)}")
    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    tag_field = _shared_tag_field(members)
    if tag_field is None:
        return _read_value(value, _union_member(annotation, value), path)
    if not isinstance(value, dict):
        raise _Refused(path, f"is {_json_value(value)}, not an object")
    try:
        member = _union_member(annotation, value)
    except ValueError as unknown_tag:
        tags = [_tags(each)[tag_field] for each in members]
        stored = "missing" if tag_field not in value else repr(value[tag_field])
        raise _Refused(_child(path, tag_field), f"is {stored}, not one of {tags}") from unknown_tag
    return _read_value(value, member, path)


def _read_dataclass(value: Any, cls: type, path: str | None) -> Any:
    """The *cls* the object *value* holds, each field read as its annotation declares.

    A field with a default that *value* lacks takes it. A field no constructor takes, a
    union's tag, is read as its annotation but not passed to *cls*.

    Raises:
        _Refused: *value* is no object; it holds a key no field has, the first such key's path;
            it lacks a field with no default; a field's value is refused; or *cls* refuses the
            values with a ValueError or TypeError, the cause, at *path*.
    """
    if not isinstance(value, dict):
        raise _Refused(path, f"is {_json_value(value)}, not an object, as a {cls.__name__} is stored")
    cls_fields = fields(cls)
    names = {each.name for each in cls_fields}
    for key in value:
        if key not in names:
            raise _Refused(_child(path, key), f"is not a field of {cls.__name__}")
    field_types = _field_types(cls)
    kwargs: dict[str, Any] = {}
    for each in cls_fields:
        if each.name not in value:
            if each.init and each.default is MISSING and each.default_factory is MISSING:
                raise _Refused(_child(path, each.name), f"is missing, and {cls.__name__} has no default for it")
            continue
        item = _read_value(value[each.name], field_types[each.name], _child(path, each.name))
        if each.init:
            kwargs[each.name] = item
    try:
        return cls(**kwargs)
    except (ValueError, TypeError) as refusal:
        raise _Refused(path, f"is refused by {cls.__name__}: {refusal}") from refusal


def _read_sequence(value: Any, annotation: Any, path: str | None) -> Any:
    """The list or tuple *annotation* declares, read from the array *value*.

    A fixed tuple, as tuple[int, int], reads an array of exactly its arity, each item by
    position; list[X] and tuple[X, ...] read each item as X.

    Raises:
        _Refused: *value* is no array, a fixed tuple's array has another length, or an item is refused.
    """
    if not isinstance(value, list):
        raise _Refused(path, f"is {_json_value(value)}, not an array")
    item_annotations = _item_annotations(annotation, len(value))
    if item_annotations is None:
        raise _Refused(path, f"holds {len(value)} items, not the {len(get_args(annotation))} of a {annotation!r}")
    items = [
        _read_value(item, item_annotation, _item(path, index))
        for index, (item, item_annotation) in enumerate(zip(value, item_annotations, strict=True))
    ]
    return tuple(items) if get_origin(annotation) is tuple else items


def _without_unknown_keys(value: Any, annotation: Any, path: str | None) -> tuple[Any, tuple[tuple[str, Any], ...]]:
    """*value*, decoded JSON at *path* in its document, without each key no field of its dataclass has; and each dropped key's path and value.

    *value* is walked as _read_value reads it: an object read as a dataclass keeps the keys its
    fields name, its tag's included; a union's value is walked as the member _union_member
    picks; an array's items and an object's values are walked as their annotations declare. A
    value of a JSON type its annotation cannot be, or of a tag no member of its union has, is
    kept as it is, for the strict reader to refuse. *value* itself is not changed.
    """
    origin = get_origin(annotation)
    if value is None:
        return value, ()
    if origin in (Union, UnionType):
        try:
            member = _union_member(annotation, value)
        except ValueError:
            return value, ()
        return _without_unknown_keys(value, member, path)
    if isinstance(annotation, type) and is_dataclass(annotation) and isinstance(value, dict):
        names = {each.name for each in fields(annotation)}
        field_types = _field_types(annotation)
        kept: dict[str, Any] = {}
        dropped: list[tuple[str, Any]] = []
        for key, item in value.items():
            if key in names:
                kept[key], dropped_within = _without_unknown_keys(item, field_types[key], _child(path, key))
                dropped.extend(dropped_within)
            else:
                dropped.append((_child(path, key), item))
        return kept, tuple(dropped)
    if origin in (list, tuple) and isinstance(value, list):
        item_annotations = _item_annotations(annotation, len(value))
        if item_annotations is None:
            return value, ()
        walked = [
            _without_unknown_keys(item, item_annotation, _item(path, index))
            for index, (item, item_annotation) in enumerate(zip(value, item_annotations, strict=True))
        ]
        return [item for item, _ in walked], tuple(each for _, dropped_within in walked for each in dropped_within)
    if origin is dict and isinstance(value, dict):
        value_annotation = _value_annotation(annotation)
        walked_values = {
            key: _without_unknown_keys(item, value_annotation, _child(path, key)) for key, item in value.items()
        }
        return (
            {key: item for key, (item, _) in walked_values.items()},
            tuple(each for _, dropped_within in walked_values.values() for each in dropped_within),
        )
    return value, ()


def _child(path: str | None, name: str) -> str:
    """The dotted path of field or key *name* of the object at *path*, None being the document's root."""
    return name if path is None else f"{path}.{name}"


def _item(path: str | None, index: int) -> str:
    """The path of item *index* of the array at *path*, None being the document's root."""
    return f"{'' if path is None else path}[{index}]"


def _json_value(value: Any) -> str:
    """*value*, decoded JSON, as a refusal names it: its JSON type, and a scalar's value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"the number {value!r}"
    if isinstance(value, str):
        return f"the string {value!r}"
    return "an array" if isinstance(value, list) else "an object"


def _stored_form(annotation: Any) -> str:
    """What JSON value *annotation* is stored as, as a refusal names it."""
    origin = get_origin(annotation)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return f"an object, as a {annotation.__name__} is stored"
    if origin in (list, tuple):
        return "an array"
    if origin is dict:
        return "an object"
    if origin is Literal:
        return f"one of {list(get_args(annotation))}"
    if origin in (Union, UnionType):
        return " or ".join(_stored_form(arg) for arg in get_args(annotation))
    if annotation is bool:
        return "true or false"
    if annotation in (int, float):
        return "a number"
    return "a string"


@functools.cache
def _field_types(cls: type) -> Mapping[str, Any]:
    """Return the type each field of dataclass *cls* is annotated with.

    Resolved once per class and shared by every later call, so the mapping is read-only.

    Raises:
        NameError: An annotation names a type cls's module does not bind.
    """
    return MappingProxyType(get_type_hints(cls))


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


def _item_annotations(sequence_annotation: Any, length: int) -> tuple[Any, ...] | None:
    """The annotation of each of the *length* items of an array stored as *sequence_annotation*.

    A fixed tuple, as tuple[int, int], annotates each item by position, and is None for an array
    of another length; list[X] and tuple[X, ...] annotate each item X.
    """
    args = get_args(sequence_annotation)
    if get_origin(sequence_annotation) is tuple and args and args[-1] is not Ellipsis:
        return args if length == len(args) else None
    return (_item_annotation(sequence_annotation),) * length


def _value_annotation(dict_annotation: Any) -> Any:
    """The annotation of each value of dict[K, V], V; Any for a bare dict."""
    args = get_args(dict_annotation)
    return args[1] if args else Any


@dataclass(frozen=True)
class FleetRunConfig:
    """A fleet run's config document: each home's HomeConfig, in the fleet's order, and their count.

    Raises:
        ValueError: n_homes is not the count of homes; the message names both.
    """

    homes: tuple[HomeConfig, ...]
    n_homes: int

    def __post_init__(self) -> None:
        if self.n_homes != len(self.homes):
            raise ValueError(f"FleetRunConfig's n_homes is {self.n_homes!r}, not its {len(self.homes)} homes")


def _home_run_configs(config_document: StoredDocument) -> tuple[HomeConfig, ...]:
    """The one HomeConfig a home run's config document holds, as StoredHomeRun.config_document wrote it.

    Raises:
        StoredRunUnreadable: The document is not a HomeConfig's field tree, as StoredDocument.read refuses it.
    """
    return (config_document.read(HomeConfig),)


def _fleet_run_configs(config_document: StoredDocument) -> tuple[HomeConfig, ...]:
    """Each HomeConfig a fleet run's config document holds, in the fleet's order, as StoredFleetRun.config_document wrote it.

    Raises:
        StoredRunUnreadable: The document is not a FleetRunConfig's field tree, as StoredDocument.read refuses it.
    """
    return config_document.read(FleetRunConfig).homes


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
        """Write the run into *run_dir*, creating it if need be: *config_document* as config.json, *summary_document* as summary.json, data.parquet, and last format.json.

        The two documents are the run's config_document() and summary_document(), which its
        save builds once for these files and its runs row alike. An earlier save's format.json
        is removed first, so the directory holds one only once this save has finished.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / _FORMAT_DOCUMENT).unlink(missing_ok=True)
        _write_json(run_dir / _CONFIG_DOCUMENT, config_document)
        _write_json(run_dir / _SUMMARY_DOCUMENT, summary_document)
        self.results.to_dataframe().to_parquet(run_dir / "data.parquet", engine="pyarrow")
        _write_format_marker(run_dir, RUN_FORMAT_VERSION)

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
        homes = tuple(self.fleet_results.home_configs)
        return _serialize_dataclass(FleetRunConfig(homes=homes, n_homes=len(homes)))

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its FleetSummary's field tree."""
        return _serialize_dataclass(self.summary)

    def write(self, run_dir: Path, config_document: dict[str, Any], summary_document: dict[str, Any]) -> None:
        """Write the run into *run_dir*, creating it if need be: *config_document* as config.json, *summary_document* as summary.json, in homes/ each home's time series and summary, and last format.json.

        The two documents are the run's config_document() and summary_document(), which its
        save builds once for these files and its runs row alike. An earlier save's format.json
        is removed first, so the directory holds one only once this save has finished.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / _FORMAT_DOCUMENT).unlink(missing_ok=True)
        (run_dir / _HOMES_DIR).mkdir(exist_ok=True)
        _write_json(run_dir / _CONFIG_DOCUMENT, config_document)
        _write_json(run_dir / _SUMMARY_DOCUMENT, summary_document)
        for index, (home_result, home_summary) in enumerate(
            zip(self.fleet_results.per_home_results, self.home_summaries, strict=True)
        ):
            home_result.to_dataframe().to_parquet(run_dir / _home_time_series(index), engine="pyarrow")
            _write_json(run_dir / _home_summary(index), _serialize_dataclass(home_summary))
        _write_format_marker(run_dir, RUN_FORMAT_VERSION)

    def export_frame(self) -> pd.DataFrame:
        """The fleet's total time series, as its CSV export holds them: FleetResults.to_aggregate_dataframe, the sum across its homes."""
        return self.fleet_results.to_aggregate_dataframe()


StoredRun = StoredHomeRun | StoredFleetRun


_HOMES_DIR = "homes"


def _home_time_series(index: int) -> str:
    """The name, in a fleet run's directory, of the time series of the home at *index* in the fleet's order."""
    return f"{_HOMES_DIR}/home_{index}.parquet"


def _home_summary(index: int) -> str:
    """The name, in a fleet run's directory, of the summary of the home at *index* in the fleet's order."""
    return f"{_HOMES_DIR}/home_{index}_summary.json"


_CONFIG_DOCUMENT = "config.json"
_SUMMARY_DOCUMENT = "summary.json"
_FORMAT_DOCUMENT = "format.json"


@dataclass(frozen=True)
class _FormatMarker:
    """A run's format.json: the version of the format its other documents are in."""

    format_version: int


_FORMAT_VERSION_FIELD = fields(_FormatMarker)[0].name

_NO_FORMAT_VERSION = (
    "is missing: the run was saved before stored runs carried a format version, or its save did not finish. "
    "`solar-challenge web migrate` migrates a store's runs, and reports each it cannot"
)


def _check_format_version(run_dir: Path, run_id: str) -> None:
    """Check that the format.json of run *run_id* in *run_dir* names RUN_FORMAT_VERSION, the format this code reads.

    Raises:
        StoredRunUnreadable: format.json is missing, is not JSON, is not a _FormatMarker's field
            tree as StoredDocument.read refuses it, or names another version, naming both.
    """
    if not (run_dir / _FORMAT_DOCUMENT).is_file():
        raise StoredRunUnreadable(run_id, _FORMAT_DOCUMENT, _FORMAT_VERSION_FIELD, _NO_FORMAT_VERSION)
    found = _json_document(run_dir, run_id, _FORMAT_DOCUMENT).read(_FormatMarker).format_version
    if found != RUN_FORMAT_VERSION:
        remedy = "run `solar-challenge web migrate`" if found < RUN_FORMAT_VERSION else "a newer solar-challenge saved it"
        raise StoredRunUnreadable(
            run_id,
            _FORMAT_DOCUMENT,
            _FORMAT_VERSION_FIELD,
            f"is {found!r}, not {RUN_FORMAT_VERSION}, the format version this solar-challenge reads: {remedy}",
        )


def _write_json(path: Path, content: Any) -> None:
    """Write *content* to *path* as JSON indented by 2, whole or not at all: to a temporary file beside it, then moved over it."""
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(content, indent=2))
    os.replace(temporary, path)


def _write_format_marker(run_dir: Path, format_version: int) -> None:
    """Write *run_dir*'s format.json naming *format_version*, the format its other documents are in, which are written first."""
    _write_json(run_dir / _FORMAT_DOCUMENT, _serialize_dataclass(_FormatMarker(format_version)))


@dataclass(frozen=True)
class StoredRunDocuments:
    """The JSON documents of one stored run, each a StoredDocument that names itself.

    config is the run's config document and summary its summary document: config.json and
    summary.json in its directory, or runs.config_json and runs.summary_json in its runs row.
    home_summaries are a fleet run's homes' summary documents, in the fleet's order, and empty
    for a home run or a runs row. A document's content is None where its source holds none,
    e.g. the summary column of a run not yet finished.
    """

    config: StoredDocument
    summary: StoredDocument
    home_summaries: tuple[StoredDocument, ...] = ()

    def changed_from(self, earlier: "StoredRunDocuments") -> tuple[StoredDocument, ...]:
        """Each of these documents whose content differs from the same document's in *earlier*, the run's documents before a step brought them forward."""
        now = (self.config, self.summary, *self.home_summaries)
        before = (earlier.config, earlier.summary, *earlier.home_summaries)
        return tuple(document for document, was in zip(now, before, strict=True) if document.content != was.content)


def read_run_documents(run_dir: Path, run_id: str, run_type: RunType) -> StoredRunDocuments:
    """The JSON documents of the run *run_id* of type *run_type* that *run_dir* holds, as its kind's write lays them out.

    Each is decoded but not read as its dataclass, so a legacy run's documents can be stepped
    forward before they are read.

    Raises:
        StoredRunUnreadable: A document is missing or is not JSON, naming it; or a fleet run's
            config holds no array of homes to find its homes' summaries by.
    """
    return RUN_KINDS[run_type].documents(run_dir, run_id)


def _home_run_documents(run_dir: Path, run_id: str) -> StoredRunDocuments:
    """The JSON documents of home run *run_id* that *run_dir* holds, as StoredHomeRun.write lays them out: config.json and summary.json.

    Raises:
        StoredRunUnreadable: A document is missing or is not JSON, naming it.
    """
    return StoredRunDocuments(
        config=_json_document(run_dir, run_id, _CONFIG_DOCUMENT),
        summary=_json_document(run_dir, run_id, _SUMMARY_DOCUMENT),
    )


def _fleet_run_documents(run_dir: Path, run_id: str) -> StoredRunDocuments:
    """The JSON documents of fleet run *run_id* that *run_dir* holds, as StoredFleetRun.write lays them out.

    Those are config.json, summary.json and, in homes/, the summary of each home its config holds.

    Raises:
        StoredRunUnreadable: A document is missing or is not JSON, naming it; or the config holds
            no array of homes, naming homes.
    """
    config = _json_document(run_dir, run_id, _CONFIG_DOCUMENT)
    return StoredRunDocuments(
        config=config,
        summary=_json_document(run_dir, run_id, _SUMMARY_DOCUMENT),
        home_summaries=tuple(_json_document(run_dir, run_id, _home_summary(index)) for index in range(_home_count(config))),
    )


def _home_count(config_document: StoredDocument) -> int:
    """The number of homes a fleet run's config document holds: the length of its homes array.

    Raises:
        StoredRunUnreadable: The document is no object holding an array of homes, naming homes.
    """
    content = config_document.content
    homes = content.get("homes") if isinstance(content, dict) else None
    if not isinstance(homes, list):
        raise StoredRunUnreadable(
            config_document.run_id, config_document.name, "homes", "is not an array of the fleet's homes"
        )
    return len(homes)


def _json_document(run_dir: Path, run_id: str, name: str) -> StoredDocument:
    """The JSON document *name* of run *run_id*, read from its file in *run_dir*.

    Raises:
        StoredRunUnreadable: The file is missing, or its text is not JSON; the field is None.
    """
    try:
        text = (run_dir / name).read_bytes()
    except FileNotFoundError as missing:
        raise StoredRunUnreadable(run_id, name, None, "is missing") from missing
    return StoredDocument.decoded(run_id, name, text)


def _time_series(run_dir: Path, run_id: str, name: str, strategy_name: str) -> SimulationResults:
    """The results the time series *name* of run *run_id* holds, read from its file in *run_dir*, simulated under *strategy_name*.

    Raises:
        StoredRunUnreadable: The file is missing, or is not a parquet of a SimulationResults'
            columns, the reader's refusal being the cause; the field is None.
    """
    path = run_dir / name
    if not path.is_file():
        raise StoredRunUnreadable(run_id, name, None, "is missing")
    try:
        return SimulationResults.from_dataframe(pd.read_parquet(path, engine="pyarrow"), strategy_name=strategy_name)
    except ValueError as refusal:
        raise StoredRunUnreadable(run_id, name, None, f"is not the time series of a run: {refusal}") from refusal


def _read_home_run(run_dir: Path, run_id: str) -> StoredHomeRun:
    """The home run *run_id* that *run_dir* holds, read from the documents StoredHomeRun.write writes, its format.json first.

    Raises:
        StoredRunUnreadable: Its format.json does not name RUN_FORMAT_VERSION, or a document is
            missing or cannot be read, naming it.
    """
    _check_format_version(run_dir, run_id)
    documents = _home_run_documents(run_dir, run_id)
    config = documents.config.read(HomeConfig)
    summary = documents.summary.read(SummaryStatistics)
    results = _time_series(run_dir, run_id, "data.parquet", summary.strategy_name)
    return StoredHomeRun(run_id=run_id, config=config, results=results, summary=summary)


def _read_fleet_run(run_dir: Path, run_id: str) -> StoredFleetRun:
    """The fleet run *run_id* that *run_dir* holds, read from the documents StoredFleetRun.write writes, its format.json first.

    Raises:
        StoredRunUnreadable: Its format.json does not name RUN_FORMAT_VERSION, or a document is
            missing or cannot be read, naming it.
    """
    _check_format_version(run_dir, run_id)
    documents = _fleet_run_documents(run_dir, run_id)
    config = documents.config.read(FleetRunConfig)
    summary = documents.summary.read(FleetSummary)
    home_summaries = tuple(each.read(SummaryStatistics) for each in documents.home_summaries)
    per_home_results = [
        _time_series(run_dir, run_id, _home_time_series(index), home_summary.strategy_name)
        for index, home_summary in enumerate(home_summaries)
    ]
    return StoredFleetRun(
        run_id=run_id,
        fleet_results=FleetResults(per_home_results=per_home_results, home_configs=list(config.homes)),
        summary=summary,
        home_summaries=home_summaries,
    )


@dataclass(frozen=True)
class RunKind:
    """What a run of one type has, how its stored documents are read, and how its config is exported.

    Attributes:
        config_type: The class of the config document a run of the type has.
        summary_type: The class of the summary a run of the type has.
        documents: The JSON documents of the run stored in a directory under an id, as its
            write lays them out, decoded but not read; it raises StoredRunUnreadable naming a
            document that is missing or not JSON.
        read: The run stored in a directory under an id, read from its documents; it raises
            StoredRunUnreadable naming a document that is missing or cannot be read.
        home_configs: Each home's HomeConfig, in order, read from a config document of the
            run, e.g. the copy its record holds; it raises StoredRunUnreadable when the
            document cannot be read.
        scenario_document: The scenario, under a name, that a run of the type with those
            HomeConfigs exports as YAML; it raises ValueError when the scenario grammar cannot
            express them.
        default_name: The name a run of the type with those HomeConfigs is created under
            when it is given none; is_run_name holds for it.
    """

    config_type: type[HomeConfig] | type[FleetRunConfig]
    summary_type: type[SummaryStatistics] | type[FleetSummary]
    documents: Callable[[Path, str], StoredRunDocuments]
    read: Callable[[Path, str], StoredRun]
    home_configs: Callable[[StoredDocument], tuple[HomeConfig, ...]]
    scenario_document: Callable[[Sequence[HomeConfig], str], dict[str, Any]]
    default_name: Callable[[Sequence[HomeConfig]], str]

    def summary(self, summary_document: StoredDocument) -> SummaryStatistics | FleetSummary:
        """The summary *summary_document* holds: the field tree of a summary_type, read as one.

        Raises:
            StoredRunUnreadable: The document is not a summary_type's field tree, as
                StoredDocument.read refuses it, e.g. it lacks a field summary_type requires, or
                summary_type refuses the figures it holds.
        """
        return summary_document.read(self.summary_type)


RUN_KINDS: Mapping[RunType, RunKind] = MappingProxyType(
    {
        "home": RunKind(
            config_type=HomeConfig,
            summary_type=SummaryStatistics,
            documents=_home_run_documents,
            read=_read_home_run,
            home_configs=_home_run_configs,
            scenario_document=_home_run_scenario,
            default_name=_home_run_default_name,
        ),
        "fleet": RunKind(
            config_type=FleetRunConfig,
            summary_type=FleetSummary,
            documents=_fleet_run_documents,
            read=_read_fleet_run,
            home_configs=_fleet_run_configs,
            scenario_document=_fleet_run_scenario,
            default_name=_fleet_run_default_name,
        ),
    }
)
"""The kind of run each RunType names, keyed by that type."""


@dataclass(frozen=True)
class DroppedValue:
    """A value that is not null which a run-document step dropped: the run's id, the document, the field's dotted path and the value."""

    run_id: str
    document: str
    field: str
    value: Any

    def __str__(self) -> str:
        """The dropped value as `solar-challenge web migrate` reports it: the run, the document's field and the value, in JSON."""
        return f"run {self.run_id!r}: {_refused_value(self.document, self.field)} was {json.dumps(self.value)}"


@dataclass(frozen=True)
class UnmigratedRun:
    """A stored run that a run-document step left as it was, as its documents cannot be brought to a format the strict reader reads.

    It names the run, the refused document and field, None for the document as a whole, and the
    reason, as the StoredRunUnreadable refusing them does.
    """

    run_id: str
    document: str
    field: str | None
    reason: str

    @classmethod
    def of(cls, refusal: StoredRunUnreadable) -> "UnmigratedRun":
        """The run *refusal* refuses, left unmigrated, named as *refusal* names it."""
        return cls(refusal.run_id, refusal.document, refusal.field, refusal.reason)

    def __str__(self) -> str:
        """The run as `solar-challenge web migrate` reports it: the run, the refused document's field and the reason."""
        return f"run {self.run_id!r}: {_refused_value(self.document, self.field)} {self.reason}"


@dataclass(frozen=True)
class StepResult:
    """What a run-document step made of a run's documents: the documents, brought forward, and each value it dropped that is not null."""

    documents: StoredRunDocuments
    dropped: tuple[DroppedValue, ...] = ()


@dataclass(frozen=True)
class RunDocumentStep:
    """The step that brings a stored run's documents from format version - 1 to version.

    Attributes:
        version: The format version the step's result is in.
        description: What the step changes, as `solar-challenge web migrate` reports it.
        apply: The documents of a run of a type, brought forward. It is pure: it changes none
            of its input, and applying it to its own result changes nothing and drops nothing.
    """

    version: int
    description: str
    apply: Callable[[RunType, StoredRunDocuments], StepResult]


def _each_document(
    run_type: RunType, documents: StoredRunDocuments, edit: Callable[[StoredDocument, type], StoredDocument]
) -> StoredRunDocuments:
    """*documents*, each replaced by *edit* of it and the dataclass it holds in a run of *run_type*.

    That is the config_type of the type's kind for the config, its summary_type for the summary,
    and SummaryStatistics for each home summary.
    """
    kind = RUN_KINDS[run_type]
    return StoredRunDocuments(
        config=edit(documents.config, kind.config_type),
        summary=edit(documents.summary, kind.summary_type),
        home_summaries=tuple(edit(each, SummaryStatistics) for each in documents.home_summaries),
    )


def _drop_unknown_keys(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v2's step: *documents* without each key their dataclasses do not have, and each dropped value that is not null.

    Each document is walked as the dataclass _each_document pairs it with, by _without_unknown_keys.
    """
    dropped: list[DroppedValue] = []

    def without_unknown_keys(document: StoredDocument, cls: type) -> StoredDocument:
        content, dropped_within = _without_unknown_keys(document.content, cls, None)
        dropped.extend(
            DroppedValue(document.run_id, document.name, path, value)
            for path, value in dropped_within
            if value is not None
        )
        return replace(document, content=content)

    brought_forward = _each_document(run_type, documents, without_unknown_keys)
    return StepResult(documents=brought_forward, dropped=tuple(dropped))


def _check_readable(run_type: RunType, documents: StoredRunDocuments) -> None:
    """Check that each of *documents* that holds content reads strictly as the dataclass _each_document pairs it with.

    Raises:
        StoredRunUnreadable: A document does not, as StoredDocument.read refuses it.
    """

    def read(document: StoredDocument, cls: type) -> StoredDocument:
        if document.content is not None:
            document.read(cls)
        return document

    _each_document(run_type, documents, read)


RUN_DOCUMENT_STEPS: tuple[RunDocumentStep, ...] = (
    RunDocumentStep(
        2,
        "Drop each key of a stored run's documents that its dataclass no longer has, "
        "as runs were read before they carried a format version",
        _drop_unknown_keys,
    ),
)
"""Every step of the stored-run format, in ascending order of version."""


def _format_version(steps: Sequence[RunDocumentStep]) -> int:
    """The version of the last of *steps*, whose versions ascend.

    Raises:
        ValueError: There are no steps, or their versions do not ascend; the message names the versions.
    """
    versions = [step.version for step in steps]
    if not versions or any(later <= earlier for earlier, later in zip(versions, versions[1:])):
        raise ValueError(f"The run-document steps' versions are {versions}, not ascending")
    return versions[-1]


RUN_FORMAT_VERSION = _format_version(RUN_DOCUMENT_STEPS)
"""The format version this code reads and writes: the last run-document step's."""


def documents_in_current_format(run_type: RunType, documents: StoredRunDocuments) -> StoredRunDocuments:
    """*documents*, of a run of type *run_type* stored before it carried a format version, brought forward by every step in order.

    It changes none of *documents* and writes nothing; the values the steps drop are not reported.
    """
    return _brought_forward(run_type, documents, RUN_DOCUMENT_STEPS)


def _brought_forward(
    run_type: RunType, documents: StoredRunDocuments, steps: Sequence[RunDocumentStep]
) -> StoredRunDocuments:
    """*documents*, of a run of type *run_type*, brought forward by each of *steps* in order."""
    return functools.reduce(lambda current, step: step.apply(run_type, current).documents, steps, documents)


def step_run_documents(step: RunDocumentStep, run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """*documents*, of a run of type *run_type* in the format before *step*'s version, brought forward by *step*, one of RUN_DOCUMENT_STEPS.

    The result is checked as the strict reader will read it once every later step has brought it
    to RUN_FORMAT_VERSION, so a run whose documents no step makes readable is refused before
    any of it is written. It changes none of *documents* and writes nothing.

    Raises:
        StoredRunUnreadable: The documents, so brought forward, cannot be read as the run's
            dataclasses, naming the document and the field.
    """
    result = step.apply(run_type, documents)
    later_steps = RUN_DOCUMENT_STEPS[RUN_DOCUMENT_STEPS.index(step) + 1 :]
    _check_readable(run_type, _brought_forward(run_type, result.documents, later_steps))
    return result


def write_run_documents(run_dir: Path, documents: Sequence[StoredDocument], format_version: int) -> None:
    """Write each of *documents*, the JSON documents of the run in *run_dir*, over its file there, then last format.json naming *format_version*.

    Each document's name is its file's path in *run_dir*, as read_run_documents names it, and
    each file is written whole or not at all, to a temporary file then moved over it.
    """
    for document in documents:
        _write_json(run_dir / document.name, document.content)
    _write_format_marker(run_dir, format_version)
