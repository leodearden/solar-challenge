# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage service for persisting simulation runs to disk and database.

Provides RunStorage class for saving and loading simulation results with:
- JSON serialization for config and summary metadata
- Parquet format for time series data
- SQLite database for run metadata and indexing

Storage structure:
  {data_dir}/runs/{run_id}/
    ├── config.json         # HomeConfig serialized
    ├── summary.json        # SummaryStatistics serialized
    └── data.parquet        # SimulationResults time series
"""

import functools
import json
import re
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Any, Literal, Type, TypeVar, Union, get_args, get_origin, get_type_hints

import pandas as pd

import solar_challenge.config
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.web.database import RUN_STATUSES, RUN_TYPES, RunStatus, RunType, get_db

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

    Each field is rebuilt as its annotation declares: nested dataclasses,
    lists and tuples of them, pd.Timestamp values and optional members.

    Args:
        cls: The dataclass type to instantiate
        data: Dictionary with serialized data

    Returns:
        Instance of cls with deserialized data
    """
    if not is_dataclass(cls):
        raise TypeError(f"Expected dataclass type, got {cls}")

    field_types = _field_types(cls)

    kwargs: dict[str, Any] = {}
    for field_name, value in data.items():
        field_type = field_types.get(field_name)
        if field_type is None:
            # Field not in dataclass definition, skip
            continue

        kwargs[field_name] = None if value is None else _deserialize_value(value, field_type)

    return cls(**kwargs)


@functools.cache
def _field_types(cls: type) -> Mapping[str, Any]:
    """Return the type each field of dataclass *cls* is annotated with.

    Resolved once per class and shared by every later call, so the mapping is read-only.

    Names resolve in cls's module first, then in solar_challenge.config. config.py
    defines DispatchStrategyConfig and GridChargeConfig, which battery.py can name
    only under TYPE_CHECKING because config.py imports battery.py.

    Raises:
        NameError: An annotation names a type neither module binds.
    """
    namespace = {**vars(solar_challenge.config), **vars(sys.modules[cls.__module__])}
    return MappingProxyType(get_type_hints(cls, globalns=namespace))


def _deserialize_value(value: Any, annotation: Any) -> Any:
    """Rebuild one JSON-decoded value as its annotation declares.

    A union is read as its first non-None member. A dict becomes a dataclass.
    An array becomes a list or a tuple, with every item rebuilt the same way.
    An ISO string becomes a pd.Timestamp. Anything else is returned unchanged.
    """
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        member = next((arg for arg in get_args(annotation) if arg is not type(None)), Any)
        return _deserialize_value(value, member)
    if isinstance(value, dict) and isinstance(annotation, type) and is_dataclass(annotation):
        return _deserialize_dataclass(annotation, value)
    if isinstance(value, list) and origin in (list, tuple):
        item_annotation = _item_annotation(annotation)
        items = [_deserialize_value(item, item_annotation) for item in value]
        return tuple(items) if origin is tuple else items
    if isinstance(value, str) and isinstance(annotation, type) and issubclass(annotation, pd.Timestamp):
        return pd.Timestamp(value)
    return value


def _item_annotation(sequence_annotation: Any) -> Any:
    """Return the annotation shared by every item of list[X], tuple[X, ...] or tuple[X, X].

    Any when the items do not share one annotation, as in tuple[A, B].
    """
    item_annotations = {arg for arg in get_args(sequence_annotation) if arg is not Ellipsis}
    return item_annotations.pop() if len(item_annotations) == 1 else Any


def stored_home_config(config: Mapping[str, Any]) -> HomeConfig:
    """The HomeConfig a home run's stored config holds, as save_home_run wrote it."""
    return _deserialize_dataclass(HomeConfig, dict(config))


def stored_fleet_home_configs(config: Mapping[str, Any]) -> list[HomeConfig]:
    """The HomeConfigs a fleet run's stored config holds, as save_fleet_run wrote it."""
    return [stored_home_config(home) for home in config["homes"]]


@dataclass(frozen=True)
class RunRecord:
    """One row of the runs table, each column in the field of the same name.

    config_json and summary_json are the JSON texts a save wrote; None while the run has none.
    type holds one of RUN_TYPES and status one of RUN_STATUSES, each None for NULL; a record
    given another value raises ValueError.
    """

    id: str
    name: str | None
    type: RunType | None
    config_json: str | None
    summary_json: str | None
    status: RunStatus | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    n_homes: int | None
    notes: str | None

    def __post_init__(self) -> None:
        _require_one_of("type", self.type, RUN_TYPES)
        _require_one_of("status", self.status, RUN_STATUSES)

    def decoded_config(self) -> Any:
        """The value config_json encodes; {} when the run has no config text or it is not JSON."""
        return _decoded_or_empty(self.config_json)

    def decoded_summary(self) -> Any:
        """The value summary_json encodes; {} when the run has no summary text or it is not JSON."""
        return _decoded_or_empty(self.summary_json)


def _require_one_of(field_name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    """Raise ValueError naming RunRecord's field *field_name* unless *value* is None or one of *allowed*."""
    if value is not None and value not in allowed:
        raise ValueError(f"RunRecord.{field_name} is {value!r}, not one of {list(allowed)} or None")


def _decoded_or_empty(text: str | None) -> Any:
    """The value JSON *text* encodes; {} when *text* is None, empty or not JSON."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _record_of_row(row: sqlite3.Row | None) -> RunRecord | None:
    """The RunRecord of a runs row read with SELECT *, or None when no row was read."""
    return None if row is None else RunRecord(**dict(row))


RunLabel = Literal["name", "notes"]  # a label of a run that Run History lets a user edit
RUN_LABELS: tuple[RunLabel, ...] = get_args(RunLabel)


class RunStorage:
    """Storage service for simulation runs.

    Manages persistence of simulation results to filesystem and SQLite database.

    Attributes:
        db_path: Path to SQLite database file
        data_dir: Root directory for run data files
    """

    def __init__(self, db_path: str | Path, data_dir: str | Path):
        """Initialize storage service.

        Args:
            db_path: Path to SQLite database file
            data_dir: Root directory for storing run data
        """
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)

    def _validate_run_id(self, run_id: str) -> None:
        """Validate run_id to prevent path traversal attacks.

        Args:
            run_id: Run identifier to validate

        Raises:
            ValueError: If run_id contains invalid characters or resolves
                outside the runs directory
        """
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", run_id):
            raise ValueError(
                f"Invalid run_id: {run_id!r}. "
                "Only alphanumeric characters, hyphens, and underscores are allowed."
            )
        runs_dir = (self.data_dir / "runs").resolve()
        resolved = (runs_dir / run_id).resolve()
        if not resolved.parent == runs_dir:
            raise ValueError(
                f"Invalid run_id: {run_id!r}. "
                "Resolved path is outside the runs directory."
            )

    def _get_run_dir(self, run_id: str) -> Path:
        """Get the directory path for a run's data files.

        Args:
            run_id: Unique run identifier

        Returns:
            Path to run directory

        Raises:
            ValueError: If run_id is invalid or would escape the runs directory
        """
        self._validate_run_id(run_id)
        return self.data_dir / "runs" / run_id

    def _stored_run_dir(self, run_id: str) -> Path:
        """The directory holding the files of the run stored under *run_id*.

        Raises:
            FileNotFoundError: No run is stored under *run_id*: the store refuses the id, so
                no save can have written one (the refusal is the cause), or no directory holds it.
        """
        try:
            run_dir = self._get_run_dir(run_id)
        except ValueError as refusal:
            raise FileNotFoundError(f"No run is stored under {run_id!r}: {refusal}") from refusal
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir

    def save_home_run(
        self,
        run_id: str,
        config: HomeConfig,
        results: SimulationResults,
        summary: SummaryStatistics,
        name: str | None = None,
        status: RunStatus = "completed",
        error_message: str | None = None,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a home simulation run to storage.

        Creates directory structure, serializes config and summary to JSON,
        saves time series to parquet, and upserts metadata into database.

        Args:
            run_id: Unique run identifier
            config: Home configuration
            results: Simulation results with time series
            summary: Summary statistics
            name: Optional run name (defaults to config.name)
            status: Run status
            error_message: Optional error message for failed runs
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.
        """
        # Create run directory
        run_dir = self._get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Serialize config to JSON
        config_dict = _serialize_dataclass(config)
        config_path = run_dir / "config.json"
        with config_path.open("w") as f:
            json.dump(config_dict, f, indent=2)

        # Serialize summary to JSON
        summary_dict = _serialize_dataclass(summary)
        summary_path = run_dir / "summary.json"
        with summary_path.open("w") as f:
            json.dump(summary_dict, f, indent=2)

        # Save time series DataFrame to parquet
        df = results.to_dataframe()
        parquet_path = run_dir / "data.parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

        # Upsert run metadata into database
        if created_at is None:
            created_at = datetime.now(timezone.utc).isoformat()
        run_name = name or config.name or "Unnamed Run"

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    type = excluded.type,
                    config_json = excluded.config_json,
                    summary_json = excluded.summary_json,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    completed_at = excluded.completed_at,
                    duration_seconds = excluded.duration_seconds,
                    n_homes = excluded.n_homes
                """,
                (
                    run_id,
                    run_name,
                    "home",
                    json.dumps(config_dict),
                    json.dumps(summary_dict),
                    status,
                    error_message,
                    created_at,
                    datetime.now(timezone.utc).isoformat() if status == "completed" else None,
                    duration_seconds,
                    1,  # n_homes for a single home run
                    None,  # notes field, can be added later
                ),
            )

    def load_home_run(
        self,
        run_id: str,
    ) -> tuple[HomeConfig, SimulationResults, SummaryStatistics]:
        """Load a home simulation run from storage.

        Reconstructs HomeConfig, SimulationResults, and SummaryStatistics from
        serialized JSON and parquet files.

        Args:
            run_id: Unique run identifier

        Returns:
            Tuple of (config, results, summary)

        Raises:
            FileNotFoundError: If no run is stored under run_id (the store refuses the id,
                or its directory is missing), or a required file is missing.
            ValueError: If run data is corrupted or incomplete.
        """
        run_dir = self._stored_run_dir(run_id)

        # Load config from JSON
        config_path = run_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r") as f:
            config_dict = json.load(f)
        config = stored_home_config(config_dict)

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

        return config, results, summary

    def save_fleet_run(
        self,
        run_id: str,
        fleet_results: FleetResults,
        fleet_summary: FleetSummary,
        per_home_summaries: list[SummaryStatistics],
        name: str | None = None,
        status: RunStatus = "completed",
        error_message: str | None = None,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a fleet simulation run to storage.

        Creates directory structure with homes/ subdirectory, saves per-home
        parquet files, fleet summary JSON, and fleet config JSON.

        Args:
            run_id: Unique run identifier
            fleet_results: Fleet simulation results with per-home data
            fleet_summary: Fleet-level summary statistics
            per_home_summaries: List of SummaryStatistics for each home
            name: Optional run name
            status: Run status
            error_message: Optional error message for failed runs
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.
        """
        # Create run directory and homes subdirectory
        run_dir = self._get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        homes_dir = run_dir / "homes"
        homes_dir.mkdir(exist_ok=True)

        # Save fleet config (list of HomeConfigs) to JSON
        fleet_config_dict = {
            "homes": [_serialize_dataclass(home) for home in fleet_results.home_configs],
            "n_homes": len(fleet_results.home_configs),
        }
        config_path = run_dir / "config.json"
        with config_path.open("w") as f:
            json.dump(fleet_config_dict, f, indent=2)

        # Save fleet summary to JSON
        summary_dict = _serialize_dataclass(fleet_summary)
        summary_path = run_dir / "summary.json"
        with summary_path.open("w") as f:
            json.dump(summary_dict, f, indent=2)

        # Save per-home results to parquet files in homes/ subdirectory
        for i, (home_result, home_summary) in enumerate(zip(fleet_results.per_home_results, per_home_summaries, strict=True)):
            # Save time series data
            df = home_result.to_dataframe()
            parquet_path = homes_dir / f"home_{i}.parquet"
            df.to_parquet(parquet_path, engine="pyarrow")

            # Save per-home summary
            home_summary_dict = _serialize_dataclass(home_summary)
            home_summary_path = homes_dir / f"home_{i}_summary.json"
            with home_summary_path.open("w") as f:
                json.dump(home_summary_dict, f, indent=2)

        # Upsert run metadata into database
        if created_at is None:
            created_at = datetime.now(timezone.utc).isoformat()
        run_name = name or "Unnamed Fleet Run"

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    type = excluded.type,
                    config_json = excluded.config_json,
                    summary_json = excluded.summary_json,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    completed_at = excluded.completed_at,
                    duration_seconds = excluded.duration_seconds,
                    n_homes = excluded.n_homes
                """,
                (
                    run_id,
                    run_name,
                    "fleet",
                    json.dumps(fleet_config_dict),
                    json.dumps(summary_dict),
                    status,
                    error_message,
                    created_at,
                    datetime.now(timezone.utc).isoformat() if status == "completed" else None,
                    duration_seconds,
                    len(fleet_results.home_configs),
                    None,
                ),
            )

    def load_fleet_run(
        self,
        run_id: str,
    ) -> tuple[FleetResults, FleetSummary, list[SummaryStatistics]]:
        """Load a fleet simulation run from storage.

        Reconstructs FleetResults, FleetSummary, and per-home SummaryStatistics
        from serialized JSON and parquet files.

        Args:
            run_id: Unique run identifier

        Returns:
            Tuple of (fleet_results, fleet_summary, per_home_summaries)

        Raises:
            FileNotFoundError: If no run is stored under run_id (the store refuses the id,
                or its directory is missing), or a required file is missing.
            ValueError: If run data is corrupted or incomplete.
        """
        run_dir = self._stored_run_dir(run_id)

        homes_dir = run_dir / "homes"
        if not homes_dir.exists():
            raise FileNotFoundError(f"Homes directory not found: {homes_dir}")

        # Load fleet config from JSON
        config_path = run_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r") as f:
            fleet_config_dict = json.load(f)

        home_configs = stored_fleet_home_configs(fleet_config_dict)

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

        return fleet_results, fleet_summary, per_home_summaries

    def run_record(self, run_id: str) -> RunRecord | None:
        """The record of run *run_id*: its row in the runs table. None when no run has that id."""
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _record_of_row(row)

    def run_name(self, run_id: str) -> str | None:
        """The name run *run_id* is saved under, the one Run History lists and renames.

        None when no run has that id, or its name is NULL.
        """
        record = self.run_record(run_id)
        return None if record is None else record.name

    def latest_run_named(self, name: str) -> RunRecord | None:
        """The run named *name* that was created last. None when no run has that name."""
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE name = ? ORDER BY created_at DESC LIMIT 1", (name,)
            ).fetchone()
        return _record_of_row(row)

    def update_run_labels(
        self, run_id: str, labels: Mapping[RunLabel, str | None]
    ) -> RunRecord | None:
        """Write each of *labels* to run *run_id*, None as NULL; a label not in *labels* keeps its value.

        Returns:
            The run's record as written, or None when no run has that id.

        Raises:
            ValueError: Writing nothing, when a key of *labels* is not one of RUN_LABELS.
        """
        unknown = sorted(set(labels) - set(RUN_LABELS))
        if unknown:
            raise ValueError(f"Not run labels: {unknown}; the run labels are {list(RUN_LABELS)}")
        with get_db(self.db_path) as conn:
            for label, value in labels.items():
                conn.execute(f"UPDATE runs SET {label} = ? WHERE id = ?", (value, run_id))
        return self.run_record(run_id)

    def list_runs(
        self,
        run_type: RunType | None = None,
        status: RunStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List simulation runs with optional filtering.

        Queries SQLite database for run metadata with optional filters.

        Args:
            run_type: Filter by run type, None for all
            status: Filter by status, None for all
            limit: Maximum number of results to return, None for all
            offset: Number of results to skip (for pagination)

        Returns:
            List of run metadata dictionaries with keys matching the database schema
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Build query with optional filters
            query = "SELECT * FROM runs WHERE 1=1"
            params: list[Any] = []

            if run_type is not None:
                query += " AND type = ?"
                params.append(run_type)

            if status is not None:
                query += " AND status = ?"
                params.append(status)

            # Order by created_at descending (most recent first)
            query += " ORDER BY created_at DESC"

            # Add limit and offset
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            if offset > 0:
                if limit is None:
                    query += " LIMIT -1"
                query += " OFFSET ?"
                params.append(offset)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Convert Row objects to dictionaries
            return [dict(row) for row in rows]

    def delete_run(self, run_id: str) -> None:
        """Delete a simulation run from storage.

        Removes the database row and all associated files, whichever exist: a delete
        of an id that has neither changes nothing.

        Args:
            run_id: Unique run identifier

        Raises:
            ValueError: If the store refuses run_id. No run can be saved under a refused
                id, so a delete under one is a caller bug.
        """
        run_dir = self._get_run_dir(run_id)

        # Delete from database first
        with get_db(self.db_path) as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

        # Delete run directory and all files
        if run_dir.exists():
            shutil.rmtree(run_dir)
