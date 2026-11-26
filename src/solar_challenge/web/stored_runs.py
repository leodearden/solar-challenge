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
whose index SimulationResults.window refuses are refused the same way. So is a time series
holding a series SimulationResults refuses, one not of numbers or an amount series holding no
number in a row; the refusal's field is then that series' column.
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
read_run_documents reads them with a StoredTimeSeries, a read-only accessor of the run's time
series, from the version before its own to its own. Its apply is pure, and applying it to its
own result changes nothing and drops nothing. v2, the first,
drops each key a document's dataclass does not have, by without_unknown_keys, as the reader
skipped such keys before runs carried a format version, and reports each dropped value that is
not null. v3 reads each stored home's dispatch as it ran before HomeConfig refused a setting its
dispatch ignores, and reports each value it rewrites, with the value it holds now. v4 drops each
battery's grid_charging that its run ignored on a tariff with no cheap period, one whose periods
all charge the same rate, and reports each value it rewrites the same way. v5 sets each summary
saved before summaries carried a window to the window of its run's stored time series, as
calculate_summary took it from the same results' index, and drops each summary's simulation_days,
reporting only a day count other than its window's days; v2 keeps a summary's simulation_days
for it, as _RETIRED_KEYS_A_LATER_STEP_READS names. v6 drops each fleet summary's
total_seg_revenue_gbp and per_home_seg_revenue_mean_gbp, a second copy of its export revenue,
reporting each value that is not null; v2 keeps the pair for it the same way. v7 drops each
stored battery's efficiency, the round trip its charge_efficiency and discharge_efficiency were
derived from, wherever the battery is, reporting each value that is not null; v2 keeps a
battery's efficiency for it the same way. v8 moves each stored home's dispatch_strategy into its
battery, whose own setting it is: a battery naming no strategy whose home asked for tou_optimized
takes tou_optimized on its tariff's clock, as the home ran, reported with the value it holds now,
and every other battery that names no strategy names self_consumption, the dispatch it ran,
unreported; then it drops every home's key, unreported. v2 keeps a home's dispatch_strategy for
v3 and v8 the same way. v9 drops each stored home summary's seg_revenue_gbp, a home run's summary
and each fleet home summary, reporting each value that is not null; v2 keeps it for v9 the same
way. v10 gives each stored home summary lacking a load_energy_kwh its household's energy, its
demand less its heat pump's, and its heat pump's when it holds one, keeps a load_energy_kwh a
summary holds, and drops each summary's total_heat_pump_load_kwh, peak_heat_pump_load_kw and
heat_pump_load_ratio, reporting only a heat-pump total its load_energy_kwh does not hold; v2
keeps the three for v10 the same way.
documents_in_current_format folds every step over a legacy run's documents in memory.
`solar-challenge web migrate` brings the stored runs' files and runs rows forward through
bring_run_documents_forward, by each step after the format they are in up to a later one, and
checks that the documents it brings forward will read once at RUN_FORMAT_VERSION. A run's files
are in the format their format.json names, as stored_format_version reads it, and in
FIRST_FORMAT_VERSION when it has none. write_run_documents then writes the documents the steps
changed and the run's format.json last; a fault that stops it part way is a
RunDocumentsWriteStopped naming the documents it wrote. A run whose documents cannot be brought
forward is left as it was, an UnmigratedRun naming it.

A change to a stored dataclass's shape, such as a renamed or retired field or a new field
with no default, ships with a RunDocumentStep of the next version appended to
RUN_DOCUMENT_STEPS, the schema step of that version, and a legacy fixture in
tests/fixtures/stored_runs whose documents the step changes (contract C10);
tests/unit/test_web_run_document_steps.py runs every step over every fixture. Steps run in
order and v2 drops each key today's dataclasses lack, so a later step that reads a renamed or
retired field's old key must keep v2 from dropping it. A step must also change nothing in
documents a later step brought forward, nor in those a save in the current format writes: a
runs row records no format of its own, so migration brings one it cannot bring forward from
its store's format forward from the first. A step that cannot keep to this must first give
each runs row a format version of its own, with its schema step
(docs/prds/run-store-one-owner.md §3.10).
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

from solar_challenge.battery import BatteryConfig
from solar_challenge.demand import LoadKind
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SeriesRefused, SimulationResults, SummaryStatistics
from solar_challenge.scenario_writer import fleet_scenario, home_scenario
from solar_challenge.timebase import SimulationWindow
from solar_challenge.web.field_tree import (
    DropsUnknownKey,
    FieldTreeRefused,
    field_tree,
    read_field_tree,
    without_unknown_keys,
)
from solar_challenge.web.run_names import is_run_name
from solar_challenge.web.stored_json import UndecodableJson, decoded_json

RunType = Literal["home", "fleet"]  # the type of a run, held by the runs table's type column
RUN_TYPES: tuple[RunType, ...] = get_args(RunType)

T = TypeVar("T")


class StoredRunUnreadable(Exception):
    """A stored run that cannot be rebuilt from its documents; the message names the run, the document, the field and the reason.

    document is a file of the run's directory, e.g. "summary.json", "homes/home_0_summary.json"
    or "data.parquet", or the runs column holding a copy, e.g. "runs.summary_json". field is
    the dotted path of the refused value in the document, with [i] for an item, or the column
    of a time series' refused series; None means the document as a whole. It is not a
    ValueError: a request's bad value is a ValueError the boundary answers 400, while a
    stored run that cannot be read is answered 409 or flashed
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
            StoredRunUnreadable: decoded_json refuses *text*, as not JSON or nested too deeply to
                decode; the reason is decoded_json's, followed by json.loads's refusal, which is
                the cause; its field is None.
        """
        try:
            return cls(run_id, name, decoded_json(text))
        except UndecodableJson as undecodable:
            raise StoredRunUnreadable(
                run_id, name, None, f"{undecodable.reason}: {undecodable.refusal}"
            ) from undecodable.refusal

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

        Raises:
            SeriesRefused: An amount series of the results holds no number in a row, as
                SimulationResults.to_dataframe refuses it; nothing has been written then, and an
                earlier save in run_dir is left as it was.
        """
        frame = self.results.to_dataframe()
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / _FORMAT_DOCUMENT).unlink(missing_ok=True)
        _write_json(run_dir / _CONFIG_DOCUMENT, config_document)
        _write_json(run_dir / _SUMMARY_DOCUMENT, summary_document)
        frame.to_parquet(run_dir / _HOME_TIME_SERIES, engine="pyarrow")
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
        homes = self.fleet_results.home_configs
        return field_tree(FleetRunConfig(homes=homes, n_homes=len(homes)))

    def summary_document(self) -> dict[str, Any]:
        """The run's summary.json document: its FleetSummary's field tree."""
        return field_tree(self.summary)

    def write(self, run_dir: Path, config_document: dict[str, Any], summary_document: dict[str, Any]) -> None:
        """Write the run into *run_dir*, creating it if need be: *config_document* as config.json, *summary_document* as summary.json, in homes/ each home's time series and summary, and last format.json.

        The two documents are the run's config_document() and summary_document(), which its
        save builds once for these files and its runs row alike. An earlier save's format.json
        is removed first, so the directory holds one only once this save has finished. Each
        home's time series is built once to check it before any file is written, one home at a
        time, and again as it is written.

        Raises:
            SeriesRefused: The results of the first home, in the fleet's order, that hold an
                amount series with no number in a row, as SimulationResults.to_dataframe refuses
                them; nothing has been written then, and an earlier save in run_dir is left as it
                was.
        """
        for home_result in self.fleet_results.per_home_results:
            _check_time_series(home_result)
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
_HOME_TIME_SERIES = "data.parquet"
"""The name, in a home run's directory, of the run's time series."""


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


def _marked_format_version(run_dir: Path, run_id: str) -> int | None:
    """The format version the format.json of run *run_id* in *run_dir* names; None when format.json is not a file there.

    Raises:
        StoredRunUnreadable: format.json cannot be read, is not JSON, or is not a _FormatMarker's
            field tree as StoredDocument.read refuses it.
    """
    if not (run_dir / _FORMAT_DOCUMENT).is_file():
        return None
    return _json_document(run_dir, run_id, _FORMAT_DOCUMENT).read(_FormatMarker).format_version


def stored_format_version(run_dir: Path, run_id: str) -> int:
    """The format version the documents of run *run_id* in *run_dir* are in: the one its format.json names, FIRST_FORMAT_VERSION when format.json is not a file there.

    A run saved before runs carried a format version has no format.json, so a migration that
    leaves such a run as it was leaves it in FIRST_FORMAT_VERSION.

    Raises:
        StoredRunUnreadable: format.json cannot be read, is not JSON, or is not a _FormatMarker's
            field tree as StoredDocument.read refuses it; the document is format.json.
    """
    found = _marked_format_version(run_dir, run_id)
    return FIRST_FORMAT_VERSION if found is None else found


def _check_format_version(run_dir: Path, run_id: str) -> None:
    """Check that the format.json of run *run_id* in *run_dir* names RUN_FORMAT_VERSION, the format this code reads.

    Raises:
        StoredRunUnreadable: format.json is missing, is not JSON, is not a _FormatMarker's field
            tree as StoredDocument.read refuses it, or names another version, naming both.
    """
    found = _marked_format_version(run_dir, run_id)
    if found is None:
        raise StoredRunUnreadable(run_id, _FORMAT_DOCUMENT, _FORMAT_VERSION_FIELD, _NO_FORMAT_VERSION)
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
class StoredTimeSeries:
    """A stored run's time series as a run-document step reads them: the run's id and its directory, None when the run has none.

    It reads a series' file only when asked, and writes nothing.
    """

    run_id: str
    run_dir: Path | None

    def window(self, name: str) -> SimulationWindow:
        """The window of the run's time series *name*, e.g. "data.parquet": SimulationWindow.of_index of that file's index, its columns left unread.

        Raises:
            StoredRunUnreadable: The run has no directory, or the file is missing, cannot be
                read, or has an index SimulationWindow.of_index refuses, as _read_time_series
                refuses it; the field is None.
        """
        return _read_time_series(self.run_dir, self.run_id, name, _window_of_the_index)


def _window_of_the_index(path: Path) -> SimulationWindow:
    """The window SimulationWindow.of_index reads from the index of the parquet at *path*, none of its columns read.

    Raises:
        ValueError: SimulationWindow.of_index refuses the index, or the file is not a parquet.
        OSError: The file cannot be read.
    """
    return SimulationWindow.of_index(pd.read_parquet(path, engine="pyarrow", columns=[]).index)


@dataclass(frozen=True)
class StoredRunDocuments:
    """A stored run as a run-document step reads it: its JSON documents, each a StoredDocument that names itself, and a read-only accessor of its time series.

    config is the run's config document and summary its summary document: config.json and
    summary.json in its directory, or runs.config_json and runs.summary_json in its runs row.
    time_series is the run's StoredTimeSeries, bound to its directory, whose files a step
    reads only when it needs one. home_summaries are a fleet run's homes' summary documents, in
    the fleet's order, and empty for a home run or a runs row. A document's content is None
    where its source holds none, e.g. the summary column of a run not yet finished.
    """

    config: StoredDocument
    summary: StoredDocument
    time_series: StoredTimeSeries
    home_summaries: tuple[StoredDocument, ...] = ()

    def changed_from(self, earlier: "StoredRunDocuments") -> tuple[StoredDocument, ...]:
        """Each of these JSON documents whose content differs from the same document's in *earlier*, the run's documents before a step brought them forward."""
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
    """The JSON documents of home run *run_id* that *run_dir* holds, as StoredHomeRun.write lays them out: config.json and summary.json, with its time series in *run_dir*.

    Raises:
        StoredRunUnreadable: A document is missing or is not JSON, naming it.
    """
    return StoredRunDocuments(
        config=_json_document(run_dir, run_id, _CONFIG_DOCUMENT),
        summary=_json_document(run_dir, run_id, _SUMMARY_DOCUMENT),
        time_series=StoredTimeSeries(run_id, run_dir),
    )


def _fleet_run_documents(run_dir: Path, run_id: str) -> StoredRunDocuments:
    """The JSON documents of fleet run *run_id* that *run_dir* holds, as StoredFleetRun.write lays them out.

    Those are config.json, summary.json and, in homes/, the summary of each home its config
    holds, with its time series in *run_dir*.

    Raises:
        StoredRunUnreadable: A document is missing or is not JSON, naming it; or the config holds
            no array of homes, naming homes.
    """
    config = _json_document(run_dir, run_id, _CONFIG_DOCUMENT)
    return StoredRunDocuments(
        config=config,
        summary=_json_document(run_dir, run_id, _SUMMARY_DOCUMENT),
        time_series=StoredTimeSeries(run_id, run_dir),
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


def _check_time_series(results: SimulationResults) -> None:
    """Check that SimulationResults.to_dataframe builds a frame from the series of *results*.

    Raises:
        SeriesRefused: As SimulationResults.to_dataframe does, for the first amount series holding
            no number in a row.
    """
    _ = results.to_dataframe()


def _check_window(results: SimulationResults) -> None:
    """Check that SimulationResults.window reads a window from the index of *results*.

    Raises:
        ValueError: As SimulationResults.window does, for an index no window describes.
    """
    _ = results.window


def _read_time_series(run_dir: Path | None, run_id: str, name: str, read: Callable[[Path], T]) -> T:
    """*read* of the file of the time series *name* of run *run_id* in *run_dir*, refused as a stored run's time series is.

    Raises:
        StoredRunUnreadable: *run_dir* is None or the file is missing ("is missing"); *read*
            raises an OSError, as for a file it cannot read ("is unreadable: ..."), or a
            ValueError, as for a file that is not a run's time series ("is not the time series
            of a run: ..."), the error being the cause. The field is None.
    """
    path = None if run_dir is None else run_dir / name
    if path is None or not path.is_file():
        raise StoredRunUnreadable(run_id, name, None, "is missing")
    try:
        return read(path)
    except ValueError as refusal:
        raise StoredRunUnreadable(run_id, name, None, f"is not the time series of a run: {refusal}") from refusal
    except OSError as unreadable:
        raise StoredRunUnreadable(run_id, name, None, f"is unreadable: {unreadable}") from unreadable


def _time_series(run_dir: Path, run_id: str, name: str, summary: SummaryStatistics) -> SimulationResults:
    """The results the time series *name* of run *run_id* holds, read from its file in *run_dir*, simulated under *summary*'s strategy_name, their grid charge sized by its grid_charge_forecast.

    Raises:
        StoredRunUnreadable: The file is missing, cannot be read, e.g. for its permissions or a
            damaged page, is not a parquet of a SimulationResults' columns, or has an index
            SimulationResults.window refuses: not a DatetimeIndex, empty, one row with no
            fixed-duration freq, or rows not evenly spaced at a positive cadence. The error is
            the cause, and the field is None. Or it holds a series SimulationResults refuses:
            one not of numbers, of a dtype no integer's or float's, or an amount series holding
            no number in a row; the field is then that series' column, and SimulationResults'
            refusal is the cause.
    """

    def results_of(path: Path) -> SimulationResults:
        try:
            results = SimulationResults.from_dataframe(
                pd.read_parquet(path, engine="pyarrow"),
                strategy_name=summary.strategy_name,
                grid_charge_forecast=summary.grid_charge_forecast,
            )
        except SeriesRefused as refused:
            raise StoredRunUnreadable(run_id, name, refused.column, refused.reason) from refused
        _check_window(results)
        return results

    return _read_time_series(run_dir, run_id, name, results_of)


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
    results = _time_series(run_dir, run_id, _HOME_TIME_SERIES, summary)
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
    per_home_results = tuple(
        _time_series(run_dir, run_id, _home_time_series(index), home_summary)
        for index, home_summary in enumerate(home_summaries)
    )
    return StoredFleetRun(
        run_id=run_id,
        fleet_results=FleetResults(per_home_results=per_home_results, home_configs=config.homes),
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
class RewrittenValue:
    """A value that a run-document step rewrote, a field its document still holds: the run's id, the document, the field's dotted path, the value it held and the one it holds now."""

    run_id: str
    document: str
    field: str
    was: Any
    now: Any

    def __str__(self) -> str:
        """The rewritten value as `solar-challenge web migrate` reports it: the run, the document's field and both values, in JSON."""
        return (
            f"run {self.run_id!r}: {_refused_value(self.document, self.field)} was {json.dumps(self.was)}, "
            f"now {json.dumps(self.now)}"
        )


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
class PartlyBroughtForwardRun:
    """A stored run whose files a run-document step brought forward only in part, before a fault stopped it.

    documents names each of its documents written in the new format, in the order written, while
    its format.json still names the format it was in.

    Raises:
        ValueError: documents names no document; the message names the run.
    """

    run_id: str
    documents: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.documents:
            raise ValueError(
                f"A run brought forward in part names each document of it that was written, so run {self.run_id!r} "
                "cannot name none"
            )

    def __str__(self) -> str:
        """The run as `solar-challenge web migrate` reports it: the run, then each document written, in order."""
        return f"run {self.run_id!r}: {', '.join(self.documents)}"


@dataclass(frozen=True)
class StepResult:
    """What run-document steps made of a run's documents: the documents, brought forward, each value they dropped that is not null, and each value they rewrote."""

    documents: StoredRunDocuments
    dropped: tuple[DroppedValue, ...] = ()
    rewritten: tuple[RewrittenValue, ...] = ()


@dataclass(frozen=True)
class RunDocumentStep:
    """The step that brings a stored run's documents from format version - 1 to version.

    Attributes:
        version: The format version the step's result is in.
        description: What the step changes, as `solar-challenge web migrate` reports it.
        apply: The documents of a run of a type, brought forward. It is pure: it changes none
            of its input. It changes, drops and rewrites nothing in documents already in its own
            format, as its own result is, or in a later one a later step brought them to.
            Migration relies on this to bring a runs row, which records no format of its own,
            forward from the first format (storage.migrate_runs_table_documents), and
            tests/unit/test_web_run_document_steps.py checks it over every fixture.
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
    return replace(
        documents,
        config=edit(documents.config, kind.config_type),
        summary=edit(documents.summary, kind.summary_type),
        home_summaries=tuple(edit(each, SummaryStatistics) for each in documents.home_summaries),
    )


_SIMULATION_DAYS = "simulation_days"
"""The key of the day count a SummaryStatistics stored before format 5 holds, the days of its window; v5 drops it."""

_FLEET_SEG_REVENUE_KEYS = ("total_seg_revenue_gbp", "per_home_seg_revenue_mean_gbp")
"""The SEG revenue total and per-home mean a FleetSummary stored before format 6 holds, a second copy of its total_export_revenue_gbp; v6 drops them."""

_BATTERY_ROUND_TRIP = "efficiency"
"""The key of the round-trip efficiency a BatteryConfig stored before format 7 holds, from which its charge_efficiency and discharge_efficiency were derived; v7 drops it."""

_HOME_DISPATCH = "dispatch_strategy"
"""The key of the dispatch a HomeConfig stored before format 8 asked for by name, 'greedy' or 'tou_optimized'; v3 reads it as its run ran, and v8 moves it into the home's battery, then drops it."""

_SUMMARY_SEG_REVENUE = "seg_revenue_gbp"
"""The key of the SEG revenue a SummaryStatistics stored before format 9 may hold, a second copy of its total_export_revenue_gbp; v9 drops it."""

_SUMMARY_HEAT_PUMP_TOTAL = "total_heat_pump_load_kwh"

_SUMMARY_HEAT_PUMP_KEYS = (_SUMMARY_HEAT_PUMP_TOTAL, "peak_heat_pump_load_kw", "heat_pump_load_ratio")
"""The heat pump's figures a SummaryStatistics stored before format 10 holds, its total, its peak and its share of the demand; v10 carries the total into the summary's load_energy_kwh and drops the three."""

_LOAD_ENERGY = "load_energy_kwh"

_RETIRED_KEYS_A_LATER_STEP_READS: Mapping[type, frozenset[str]] = MappingProxyType(
    {
        SummaryStatistics: frozenset({_SIMULATION_DAYS, _SUMMARY_SEG_REVENUE, *_SUMMARY_HEAT_PUMP_KEYS}),
        FleetSummary: frozenset(_FLEET_SEG_REVENUE_KEYS),
        BatteryConfig: frozenset({_BATTERY_ROUND_TRIP}),
        HomeConfig: frozenset({_HOME_DISPATCH}),
    }
)
"""By dataclass, each key of its stored objects, wherever they are, that it no longer has and a later step reads, which v2 keeps: v5 compares a summary's simulation_days with its window's days, then drops it, and v6 drops a fleet summary's SEG revenue pair, v7 a battery's efficiency and v9 a home summary's seg_revenue_gbp, each reporting each value that is not null; v3 reads a home's dispatch_strategy as its run ran, and v8 moves it into the home's battery; v10 carries a home summary's heat-pump total into its load_energy_kwh, then drops its three heat-pump figures."""


def _not_read_by_a_later_step(owner: type, key: str) -> bool:
    """Whether v2 drops *key*, a key no field of *owner* has: unless _RETIRED_KEYS_A_LATER_STEP_READS names it for *owner*."""
    return key not in _RETIRED_KEYS_A_LATER_STEP_READS.get(owner, frozenset())


def _unknown_keys_dropped(
    run_type: RunType, documents: StoredRunDocuments, drops: DropsUnknownKey
) -> StepResult:
    """*documents* without each key their dataclasses do not have that *drops* holds for, and each dropped value that is not null.

    Each document is walked as the dataclass _each_document pairs it with, by without_unknown_keys,
    which asks *drops* of each such key with the dataclass whose stored object holds it; a key it
    spares is kept, unreported.
    """
    dropped: list[DroppedValue] = []

    def document_without_unknown_keys(document: StoredDocument, cls: type) -> StoredDocument:
        content, unknown_keys = without_unknown_keys(document.content, cls, drops=drops)
        dropped.extend(
            DroppedValue(document.run_id, document.name, key.path, key.value)
            for key in unknown_keys
            if key.value is not None
        )
        return replace(document, content=content)

    brought_forward = _each_document(run_type, documents, document_without_unknown_keys)
    return StepResult(documents=brought_forward, dropped=tuple(dropped))


def _drop_unknown_keys(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v2's step: *documents* without each key their dataclasses do not have, and each dropped value that is not null.

    A key _RETIRED_KEYS_A_LATER_STEP_READS names for the dataclass whose stored object holds it is
    kept, unreported, for the later step that reads it.
    """
    return _unknown_keys_dropped(run_type, documents, _not_read_by_a_later_step)


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


_FORMAT_2_HOME_DISPATCH = ("greedy", "tou_optimized")
"""The home dispatch strategies a run at format 2 could ask for by name; it dispatched any other as greedy."""

_FieldChange = tuple[str, Any, Any]
"""A field a step rewrote, as its dotted path, the value it held before and the value it holds now."""

_HomeRule = Callable[[Any], tuple[Any, list[_FieldChange]]]
"""A step's rule for one stored HomeConfig object: the object brought forward, and each field it changed."""


def _homes_brought_forward(run_type: RunType, documents: StoredRunDocuments, rule: _HomeRule) -> StepResult:
    """*documents* with each home's object in the config brought forward by *rule*, and each value it rewrote.

    A home run's config is one home's object and a fleet run's holds one in each item of its
    homes. The summaries and any content that is not such an object are left as they are.
    """
    config = documents.config
    if run_type == "home":
        content, changes = rule(config.content)
    else:
        content, changes = _fleet_homes_brought_forward(config.content, rule)
    rewritten = tuple(RewrittenValue(config.run_id, config.name, field, was, now) for field, was, now in changes)
    return StepResult(documents=replace(documents, config=replace(config, content=content)), rewritten=rewritten)


def _fleet_homes_brought_forward(config: Any, rule: _HomeRule) -> tuple[Any, list[_FieldChange]]:
    """A fleet run's *config* with each item of its homes brought forward by *rule*, and each change, at homes[i]."""
    if not isinstance(config, dict) or not isinstance(config.get("homes"), list):
        return config, []
    brought_forward = [rule(home) for home in config["homes"]]
    homes = [home for home, _ in brought_forward]
    changes = [
        (f"homes[{index}].{field}", was, now)
        for index, (_, home_changes) in enumerate(brought_forward)
        for field, was, now in home_changes
    ]
    if homes == config["homes"]:
        return config, []
    return {**config, "homes": homes}, changes


def _dispatch_as_it_ran(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v3's step: *documents* with each home's config set to the dispatch its run ran by, as _home_as_it_ran sets it, and each value it rewrote."""
    return _homes_brought_forward(run_type, documents, _home_as_it_ran)


def _home_as_it_ran(home: Any) -> tuple[Any, list[_FieldChange]]:
    """*home*, a stored HomeConfig object, set to the dispatch its run ran by, and each field it changed.

    A home dispatch_strategy outside _FORMAT_2_HOME_DISPATCH ran greedy. A battery home asking
    for tou_optimized, whose battery names no strategy, ran the tariff's rates when it had a
    tariff, which honours grid_charging, and greedy when it had none. Otherwise its battery ran
    its own strategy, self-consumption when it names none, which ignored grid_charging under
    self-consumption or with no tariff.
    """
    if not isinstance(home, dict):
        return home, []
    changes: list[_FieldChange] = []
    strategy = home.get("dispatch_strategy")
    if isinstance(strategy, str) and strategy not in _FORMAT_2_HOME_DISPATCH:
        changes.append(("dispatch_strategy", strategy, "greedy"))
        home = {**home, "dispatch_strategy": "greedy"}
    battery = home.get("battery_config")
    if not isinstance(battery, dict):
        return home, changes
    battery_strategy, tariff = battery.get("dispatch_strategy"), home.get("tariff_config")
    if home.get("dispatch_strategy") == "tou_optimized" and battery_strategy is None:
        if tariff is not None:
            return home, changes
        changes.append(("dispatch_strategy", "tou_optimized", "greedy"))
        home = {**home, "dispatch_strategy": "greedy"}
    tag = battery_strategy.get("strategy_type") if isinstance(battery_strategy, dict) else "self_consumption"
    grid_charging = battery.get("grid_charging")
    if grid_charging is None or (tag != "self_consumption" and tariff is not None):
        return home, changes
    changes.append(("battery_config.grid_charging", grid_charging, None))
    return {**home, "battery_config": {**battery, "grid_charging": None}}, changes


def _grid_charging_without_a_cheap_period_dropped(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v4's step: *documents* with each home's config rid of the grid_charging its run ignored, as _home_without_grid_charging_on_one_rate drops it, and each value it rewrote."""
    return _homes_brought_forward(run_type, documents, _home_without_grid_charging_on_one_rate)


def _home_without_grid_charging_on_one_rate(home: Any) -> tuple[Any, list[_FieldChange]]:
    """*home*, a stored HomeConfig object, with its battery's grid_charging dropped when its tariff's periods all charge one rate, and each field it changed.

    That is the home as its run ran. A tariff's periods tile the day, so each covers a minute,
    and at format 3 its cheap_minutes_of_day was empty exactly when its periods shared one rate:
    neither GridChargeContext.is_cheap_period nor TOU dispatch on the tariff's clock then ever
    charged from the grid. v3 had already dropped grid_charging under self-consumption dispatch or with no
    tariff, so any left at format 3 is on a dispatch that grid-charges. The rule reads format
    3's JSON, not a TariffConfig, so a later change to the tariff's classifier cannot change the
    step. A home it cannot read as a grid-charging battery on such a tariff is left as it is.
    """
    if not isinstance(home, dict):
        return home, []
    battery = home.get("battery_config")
    if not isinstance(battery, dict) or battery.get("grid_charging") is None:
        return home, []
    if not _periods_charge_one_rate(home.get("tariff_config")):
        return home, []
    change = ("battery_config.grid_charging", battery["grid_charging"], None)
    return {**home, "battery_config": {**battery, "grid_charging": None}}, [change]


def _periods_charge_one_rate(tariff: Any) -> bool:
    """Whether *tariff*, a stored TariffConfig object, has periods: a list, not empty, of objects whose rate_per_kwh is each the same number, an int or a float, never a bool."""
    periods = tariff.get("periods") if isinstance(tariff, dict) else None
    if not isinstance(periods, list) or not periods or not all(isinstance(period, dict) for period in periods):
        return False
    rates = [period.get("rate_per_kwh") for period in periods]
    return all(_is_a_number(rate) for rate in rates) and all(rate == rates[0] for rate in rates)


def _is_a_number(value: Any) -> bool:
    """Whether *value*, decoded from a stored document's JSON, is a number: an int or a float, never a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _summaries_at_format_5(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v5's step: *documents* with each SummaryStatistics document given a window and rid of its simulation_days, as _summary_at_format_5 brings it forward, and each day count it dropped that differs from its window's days.

    A home run's summary summarises its data.parquet, and a fleet run's home_summaries[i] its
    homes/home_i.parquet; each window is read through *documents*' time_series, so a summary
    holding one reads no series. calculate_summary took a summary's window from the index of the
    same results its run stored, so the window is the one the run had, and a stored day count
    other than its days, such as one counted across the autumn clock change, is the one value
    the run's page shows differently. A fleet run's summary, its FleetSummary with its
    simulation_days, and every config are left as they are.

    Raises:
        StoredRunUnreadable: The time series of a summary lacking a window cannot be read, as
            StoredTimeSeries.window refuses it.
    """
    time_series = documents.time_series
    if run_type == "home":
        summary, dropped = _summary_at_format_5(documents.summary, time_series, _HOME_TIME_SERIES)
        return StepResult(replace(documents, summary=summary), dropped=dropped)
    brought_forward = [
        _summary_at_format_5(summary, time_series, _home_time_series(index))
        for index, summary in enumerate(documents.home_summaries)
    ]
    return StepResult(
        replace(documents, home_summaries=tuple(summary for summary, _ in brought_forward)),
        dropped=tuple(value for _, dropped in brought_forward for value in dropped),
    )


def _summary_at_format_5(
    summary: StoredDocument, time_series: StoredTimeSeries, name: str
) -> tuple[StoredDocument, tuple[DroppedValue, ...]]:
    """*summary*, a stored SummaryStatistics object, given a window by _with_a_window and rid of its simulation_days; and the DroppedValue of that day count when it is not null and is not the window's days.

    Any other content is left as it is.

    Raises:
        StoredRunUnreadable: As _with_a_window does.
    """
    summary = _with_a_window(summary, time_series, name)
    content = summary.content
    if not isinstance(content, dict) or _SIMULATION_DAYS not in content:
        return summary, ()
    days = content[_SIMULATION_DAYS]
    without_days = replace(summary, content={key: value for key, value in content.items() if key != _SIMULATION_DAYS})
    if days is None or days == _stored_window_days(content["window"]):
        return without_days, ()
    return without_days, (DroppedValue(summary.run_id, summary.name, _SIMULATION_DAYS, days),)


def _stored_window_days(window: Any) -> int | None:
    """The days of *window*, a stored SimulationWindow object, read as the strict reader reads it; None when it does not read as one."""
    try:
        return read_field_tree(window, SimulationWindow).days
    except FieldTreeRefused:
        return None


def _with_a_window(summary: StoredDocument, time_series: StoredTimeSeries, name: str) -> StoredDocument:
    """*summary*, a stored SummaryStatistics object, given the window of *time_series*' series *name* when it holds none, the key absent or null; any other content is left as it is.

    The window is written in field_tree's JSON form, as a save writes it.

    Raises:
        StoredRunUnreadable: The series cannot be read, as StoredTimeSeries.window refuses it.
    """
    content = summary.content
    if not isinstance(content, dict) or content.get("window") is not None:
        return summary
    return replace(summary, content={**content, "window": field_tree(time_series.window(name))})


def _fleet_seg_revenue_dropped(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v6's step: *documents* with a fleet run's summary rid of each key of _FLEET_SEG_REVENUE_KEYS, and each dropped value that is not null.

    A home run's documents, a fleet run's config and home summaries, and a fleet summary that is
    not an object are left as they are.
    """
    summary = documents.summary
    content = summary.content
    if run_type != "fleet" or not isinstance(content, dict):
        return StepResult(documents)
    dropped = tuple(
        DroppedValue(summary.run_id, summary.name, key, content[key])
        for key in _FLEET_SEG_REVENUE_KEYS
        if content.get(key) is not None
    )
    without_the_pair = {key: value for key, value in content.items() if key not in _FLEET_SEG_REVENUE_KEYS}
    return StepResult(replace(documents, summary=replace(summary, content=without_the_pair)), dropped=dropped)


def _is_a_battery_round_trip(owner: type, key: str) -> bool:
    """Whether *key* of a stored object of *owner* is a BatteryConfig's efficiency, _BATTERY_ROUND_TRIP."""
    return (owner, key) == (BatteryConfig, _BATTERY_ROUND_TRIP)


def _battery_round_trips_dropped(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v7's step: *documents* without each stored BatteryConfig's efficiency, wherever the battery is, and each dropped value that is not null.

    The charge_efficiency and discharge_efficiency it was derived from are kept, and so is every
    other key, a document that is not an object, and every other document.
    """
    return _unknown_keys_dropped(run_type, documents, _is_a_battery_round_trip)


def _home_dispatch_moved_to_its_battery(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v8's step: *documents* with each home's config rid of its dispatch_strategy, moved into its battery as _home_with_its_dispatch_in_its_battery moves it, and each value it rewrote."""
    return _homes_brought_forward(run_type, documents, _home_with_its_dispatch_in_its_battery)


def _home_with_its_dispatch_in_its_battery(home: Any) -> tuple[Any, list[_FieldChange]]:
    """*home*, a stored HomeConfig object, rid of its dispatch_strategy, and each field it changed.

    v3 left a home asking for tou_optimized beside a battery naming its own strategy, which its run
    dispatched by; beside a battery naming none on a tariff, which ran tou_optimized on the
    tariff's clock; or with no battery, which dispatched none. Every other home asked for greedy,
    whose battery naming none ran self-consumption. So every home loses the key, if it holds one;
    and, whether or not it held one, a battery naming no strategy whose home asked for tou_optimized
    takes tou_optimized on its tariff's clock, the one field reported, while any other battery
    naming none names self_consumption, unreported. A home that is not an object is left as it is.
    """
    if not isinstance(home, dict):
        return home, []
    without_the_key = {key: value for key, value in home.items() if key != _HOME_DISPATCH}
    battery = home.get("battery_config")
    if not isinstance(battery, dict) or battery.get("dispatch_strategy") is not None:
        return without_the_key, []
    if home.get(_HOME_DISPATCH) == "tou_optimized":
        strategy = _tou_optimized_on_the_tariffs_clock()
        changes = [("battery_config.dispatch_strategy", None, _tou_optimized_on_the_tariffs_clock())]
    else:
        strategy, changes = {"strategy_type": "self_consumption"}, []
    return {**without_the_key, "battery_config": {**battery, "dispatch_strategy": strategy}}, changes


def _tou_optimized_on_the_tariffs_clock() -> dict[str, Any]:
    """A battery's dispatch_strategy of tou_optimized on its tariff's clock, as format 8 stores it: a new object each call."""
    return {"strategy_type": "tou_optimized", "peak_hours": None}


def _is_a_summary_seg_revenue(owner: type, key: str) -> bool:
    """Whether *key* of a stored object of *owner* is a SummaryStatistics' seg_revenue_gbp, _SUMMARY_SEG_REVENUE."""
    return (owner, key) == (SummaryStatistics, _SUMMARY_SEG_REVENUE)


def _summary_seg_revenues_dropped(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v9's step: *documents* without each stored SummaryStatistics' seg_revenue_gbp, a home run's summary and each of a fleet run's home summaries, and each dropped value that is not null; a fleet's FleetSummary and every config are left as they are."""
    return _unknown_keys_dropped(run_type, documents, _is_a_summary_seg_revenue)


def _summaries_given_load_energy(run_type: RunType, documents: StoredRunDocuments) -> StepResult:
    """v10's step: *documents* with each SummaryStatistics document brought forward as _summary_given_load_energy brings it, and each heat-pump total it dropped that its load_energy_kwh does not hold.

    Those are a home run's summary and each of a fleet run's home summaries; a fleet's
    FleetSummary and every config are left as they are.
    """
    dropped: list[DroppedValue] = []

    def given_load_energy(document: StoredDocument, cls: type) -> StoredDocument:
        if cls is not SummaryStatistics:
            return document
        content, dropped_total = _summary_given_load_energy(document.content)
        if dropped_total is not None:
            dropped.append(DroppedValue(document.run_id, document.name, _SUMMARY_HEAT_PUMP_TOTAL, dropped_total))
        return replace(document, content=content)

    return StepResult(documents=_each_document(run_type, documents, given_load_energy), dropped=tuple(dropped))


def _summary_given_load_energy(summary: Any) -> tuple[Any, Any]:
    """*summary*, a stored SummaryStatistics object, given a load_energy_kwh and rid of _SUMMARY_HEAT_PUMP_KEYS; and its dropped heat-pump total, None unless its load_energy_kwh does not hold it.

    A summary holding a load_energy_kwh keeps it. Otherwise it is given its household's energy,
    its total_demand_kwh less its heat pump's total, and that total when it holds one: a summary
    whose demand is not a number, or whose heat-pump total is neither null nor a number, is left
    as it is, as is one that is not an object, for the strict reader to refuse. A household's
    energy below 0 is kept, for the strict reader to refuse by its path.
    """
    if not isinstance(summary, dict):
        return summary, None
    heat_pump_kwh = summary.get(_SUMMARY_HEAT_PUMP_TOTAL)
    load_energy = summary.get(_LOAD_ENERGY)
    if load_energy is None:
        demand_kwh = summary.get("total_demand_kwh")
        if not _is_a_number(demand_kwh) or not (heat_pump_kwh is None or _is_a_number(heat_pump_kwh)):
            return summary, None
        load_energy = (
            {LoadKind.HOUSEHOLD.value: demand_kwh}
            if heat_pump_kwh is None
            else {LoadKind.HOUSEHOLD.value: demand_kwh - heat_pump_kwh, LoadKind.HEAT_PUMP.value: heat_pump_kwh}
        )
    held = load_energy.get(LoadKind.HEAT_PUMP.value) if isinstance(load_energy, dict) else None
    dropped_total = heat_pump_kwh if heat_pump_kwh is not None and held != heat_pump_kwh else None
    without_the_figures = {key: value for key, value in summary.items() if key not in _SUMMARY_HEAT_PUMP_KEYS}
    return {**without_the_figures, _LOAD_ENERGY: load_energy}, dropped_total


RUN_DOCUMENT_STEPS: tuple[RunDocumentStep, ...] = (
    RunDocumentStep(
        2,
        "Drop each key of a stored run's documents that its dataclass no longer has, "
        "as runs were read before they carried a format version",
        _drop_unknown_keys,
    ),
    RunDocumentStep(
        3,
        "Read each stored home's dispatch as it ran: drop each battery's grid_charging that its run "
        "ignored, under self-consumption dispatch or with no tariff, and read as greedy a home "
        "dispatch_strategy its run did not dispatch by",
        _dispatch_as_it_ran,
    ),
    RunDocumentStep(
        4,
        "Drop each battery's grid_charging that its run ignored on a tariff with no cheap period, "
        "one whose periods all charge the same rate",
        _grid_charging_without_a_cheap_period_dropped,
    ),
    RunDocumentStep(
        5,
        "Set each stored summary saved before summaries carried a window to the window of its run's stored time "
        "series, and drop each summary's simulation_days, its window's days",
        _summaries_at_format_5,
    ),
    RunDocumentStep(
        6,
        "Drop each stored fleet summary's total_seg_revenue_gbp and per_home_seg_revenue_mean_gbp, "
        "a second copy of its total_export_revenue_gbp",
        _fleet_seg_revenue_dropped,
    ),
    RunDocumentStep(
        7,
        "Drop each stored battery's efficiency, the round trip its charge_efficiency and discharge_efficiency "
        "were derived from, which BatteryConfig no longer has",
        _battery_round_trips_dropped,
    ),
    RunDocumentStep(
        8,
        "Move each stored home's dispatch_strategy into its battery, where a battery that names no strategy "
        "takes tou_optimized on its tariff's clock when its home asked for it, and every other battery that "
        "names no strategy names self_consumption, then drop the home's key, which no HomeConfig has",
        _home_dispatch_moved_to_its_battery,
    ),
    RunDocumentStep(
        9,
        "Drop each stored home summary's seg_revenue_gbp, a second copy of its total_export_revenue_gbp, "
        "which SummaryStatistics no longer has",
        _summary_seg_revenues_dropped,
    ),
    RunDocumentStep(
        10,
        "Give each stored summary saved before summaries held each load's energy a load_energy_kwh, its "
        "household's energy, its demand less its heat pump's, and its heat pump's, and drop each summary's "
        "total_heat_pump_load_kwh, peak_heat_pump_load_kw and heat_pump_load_ratio, which SummaryStatistics "
        "no longer has",
        _summaries_given_load_energy,
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

FIRST_FORMAT_VERSION = RUN_DOCUMENT_STEPS[0].version - 1
"""The format version of a run stored before runs carried one, which has no format.json: the one before the first run-document step's."""


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


def bring_run_documents_forward(
    run_type: RunType, documents: StoredRunDocuments, from_version: int, to_version: int
) -> StepResult:
    """*documents*, of a run of type *run_type* in format *from_version*, brought forward to *to_version* by each of RUN_DOCUMENT_STEPS after *from_version* up to *to_version*, in order.

    The result holds each value those steps dropped that is not null and each value they
    rewrote, in the steps' order. It is checked as the strict reader will read it once the steps
    after *to_version* have brought it to RUN_FORMAT_VERSION, so a run whose documents no step
    makes readable is refused before any of it is written; documents already in *to_version* are
    only checked. It changes none of *documents* and writes nothing.

    Raises:
        StoredRunUnreadable: The documents, so brought forward, cannot be read as the run's
            dataclasses, naming the document and the field.
        ValueError: *from_version* is past *to_version*, or *to_version* past RUN_FORMAT_VERSION;
            the message names both versions.
    """
    if from_version > to_version or to_version > RUN_FORMAT_VERSION:
        raise ValueError(
            f"A run's documents cannot be brought forward from format version {from_version} to {to_version}: "
            f"the target must be at or after the format they are in, and at or before {RUN_FORMAT_VERSION}, "
            "the format version this solar-challenge reads"
        )
    result = StepResult(documents)
    for step in RUN_DOCUMENT_STEPS:
        if from_version < step.version <= to_version:
            stepped = step.apply(run_type, result.documents)
            result = StepResult(stepped.documents, result.dropped + stepped.dropped, result.rewritten + stepped.rewritten)
    later_steps = [step for step in RUN_DOCUMENT_STEPS if step.version > to_version]
    _check_readable(run_type, _brought_forward(run_type, result.documents, later_steps))
    return result


class RunDocumentsWriteStopped(Exception):
    """An OSError that stopped write_run_documents part way; the message is the OSError's.

    written names each document written before the fault, each whole, in the order written;
    format.json, written last, is never among them. fault is the OSError, which is also its cause.
    """

    def __init__(self, written: tuple[str, ...], fault: OSError) -> None:
        super().__init__(str(fault))
        self.written = written
        self.fault = fault


def write_run_documents(run_dir: Path, documents: Sequence[StoredDocument], format_version: int) -> None:
    """Write each of *documents*, the JSON documents of the run in *run_dir*, over its file there, then last format.json naming *format_version*.

    Each document's name is its file's path in *run_dir*, as read_run_documents names it, and
    each file is written whole or not at all, to a temporary file then moved over it.

    Raises:
        RunDocumentsWriteStopped: A file cannot be written, e.g. on a full disk, the OSError
            being its fault; its written names each document written before it, and format.json
            has not been written.
    """
    written: list[str] = []
    try:
        for document in documents:
            _write_json(run_dir / document.name, document.content)
            written.append(document.name)
        _write_format_marker(run_dir, format_version)
    except OSError as fault:
        raise RunDocumentsWriteStopped(tuple(written), fault) from fault
