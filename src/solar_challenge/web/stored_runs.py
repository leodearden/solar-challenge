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

A document is read strictly, as StoredDocument.read reads it, by web/field_tree.py's
read_field_tree, and a value it refuses becomes a StoredRunUnreadable naming the run, the
document, the field's dotted path and the reason. Non-JSON text, JSON nested too deeply to
decode, a document that is missing or cannot be read, a time series that cannot be read, and one
whose index SimulationResults.window refuses are refused the same way.
StoredRunUnreadable is not a ValueError: a request's bad value is a ValueError the boundary
answers 400, while a stored run that cannot be read is answered 409 or flashed.

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
drops each key a document's dataclass does not have, by without_unknown_keys, as the reader
skipped such keys before runs carried a format version, and reports each dropped value that is
not null.
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
from dataclasses import dataclass, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeVar, get_args

import pandas as pd

from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.scenario_writer import fleet_scenario, home_scenario
from solar_challenge.web.field_tree import FieldTreeRefused, field_tree, read_field_tree, without_unknown_keys
from solar_challenge.web.run_names import is_run_name

RunType = Literal["home", "fleet"]  # the type of a run, held by the runs table's type column
RUN_TYPES: tuple[RunType, ...] = get_args(RunType)

T = TypeVar("T")


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
            StoredRunUnreadable: *text* is not JSON, or is nested too deeply for json.loads to
                decode; its field is None.
        """
        try:
            return cls(run_id, name, json.loads(text))
        except ValueError as refusal:
            raise StoredRunUnreadable(run_id, name, None, f"is not JSON: {refusal}") from refusal
        except RecursionError as refusal:
            raise StoredRunUnreadable(
                run_id, name, None, f"is nested too deeply to decode as JSON: {refusal}"
            ) from refusal

    def read(self, cls: type[T]) -> T:
        """The *cls*, a dataclass, whose field tree the document holds, read strictly by read_field_tree.

        Raises:
            StoredRunUnreadable: read_field_tree refuses the document's content, naming the
                refused value's path and the reason; a dataclass's refusal of its values is then
                the cause.
        """
        try:
            return read_field_tree(self.content, cls)
        except FieldTreeRefused as refused:
            raise StoredRunUnreadable(self.run_id, self.name, refused.path, refused.reason) from refused.__cause__


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
        return field_tree(self.config)

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its SummaryStatistics' field tree."""
        return field_tree(self.summary)

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
        return field_tree(FleetRunConfig(homes=homes, n_homes=len(homes)))

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its FleetSummary's field tree."""
        return field_tree(self.summary)

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
            _write_json(run_dir / _home_summary(index), field_tree(home_summary))
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
    """Write *content* to *path* as JSON indented by 2, whole or not at all: to a temporary file beside it, then moved over it.

    A write that fails leaves *path* as it was and no temporary file.

    Raises:
        OSError: The file cannot be written, e.g. on a full disk.
    """
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(content, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_format_marker(run_dir: Path, format_version: int) -> None:
    """Write *run_dir*'s format.json naming *format_version*, the format its other documents are in, which are written first."""
    _write_json(run_dir / _FORMAT_DOCUMENT, field_tree(_FormatMarker(format_version)))


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
        StoredRunUnreadable: The file is missing, cannot be read, e.g. for its permissions, the
            error being the cause, or its text is not JSON; the field is None.
    """
    try:
        text = (run_dir / name).read_bytes()
    except FileNotFoundError as missing:
        raise StoredRunUnreadable(run_id, name, None, "is missing") from missing
    except OSError as unreadable:
        raise StoredRunUnreadable(run_id, name, None, f"is unreadable: {unreadable}") from unreadable
    return StoredDocument.decoded(run_id, name, text)


def _check_window(results: SimulationResults) -> None:
    """Check that SimulationResults.window reads a window from the index of *results*.

    Raises:
        ValueError: As SimulationResults.window does, for an index no window describes.
    """
    _ = results.window


def _time_series(run_dir: Path, run_id: str, name: str, strategy_name: str) -> SimulationResults:
    """The results the time series *name* of run *run_id* holds, read from its file in *run_dir*, simulated under *strategy_name*.

    Raises:
        StoredRunUnreadable: The file is missing, cannot be read, e.g. for its permissions or a
            damaged page, is not a parquet of a SimulationResults' columns, or has an index
            SimulationResults.window refuses: not a DatetimeIndex, empty, one row with no
            fixed-duration freq, or rows not evenly spaced at a positive cadence. The error is
            the cause, and the field is None.
    """
    path = run_dir / name
    if not path.is_file():
        raise StoredRunUnreadable(run_id, name, None, "is missing")
    try:
        results = SimulationResults.from_dataframe(pd.read_parquet(path, engine="pyarrow"), strategy_name=strategy_name)
        _check_window(results)
    except ValueError as refusal:
        raise StoredRunUnreadable(run_id, name, None, f"is not the time series of a run: {refusal}") from refusal
    except OSError as unreadable:
        raise StoredRunUnreadable(run_id, name, None, f"is unreadable: {unreadable}") from unreadable
    return results


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

    Each document is walked as the dataclass _each_document pairs it with, by without_unknown_keys.
    """
    dropped: list[DroppedValue] = []

    def document_without_unknown_keys(document: StoredDocument, cls: type) -> StoredDocument:
        content, unknown_keys = without_unknown_keys(document.content, cls)
        dropped.extend(
            DroppedValue(document.run_id, document.name, key.path, key.value)
            for key in unknown_keys
            if key.value is not None
        )
        return replace(document, content=content)

    brought_forward = _each_document(run_type, documents, document_without_unknown_keys)
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

    Raises:
        OSError: A file cannot be written, e.g. on a full disk; each document before it has
            been written, and format.json has not.
    """
    for document in documents:
        _write_json(run_dir / document.name, document.content)
    _write_format_marker(run_dir, format_version)
