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

import json
import re
import shutil
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Type, TypeVar, Union, get_type_hints

import pandas as pd

from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.web.database import get_db

T = TypeVar("T")


def _serialize_dataclass(obj: Any) -> dict[str, Any]:
    """Recursively serialize a dataclass to JSON-compatible dict.

    Handles nested dataclasses and converts special types like pd.Timestamp.

    Args:
        obj: Dataclass instance to serialize

    Returns:
        JSON-compatible dictionary
    """
    if not is_dataclass(obj):
        raise TypeError(f"Expected dataclass, got {type(obj)}")

    result: dict[str, Any] = {}
    for field_info in fields(obj):
        value = getattr(obj, field_info.name)

        # Handle None
        if value is None:
            result[field_info.name] = None
        # Handle nested dataclasses
        elif is_dataclass(value):
            result[field_info.name] = _serialize_dataclass(value)
        # Handle pd.Timestamp
        elif isinstance(value, pd.Timestamp):
            result[field_info.name] = value.isoformat()
        # Handle lists/tuples (may contain dataclasses)
        elif isinstance(value, (list, tuple)):
            result[field_info.name] = [
                _serialize_dataclass(item) if is_dataclass(item) else item
                for item in value
            ]
        # Handle dicts (may contain dataclasses)
        elif isinstance(value, dict):
            result[field_info.name] = {
                k: _serialize_dataclass(v) if is_dataclass(v) else v
                for k, v in value.items()
            }
        # Primitive types (int, float, str, bool)
        else:
            result[field_info.name] = value

    return result


def _deserialize_dataclass(cls: Type[T], data: dict[str, Any]) -> T:
    """Recursively deserialize a dict to a dataclass instance.

    Handles nested dataclasses, pd.Timestamp deserialization, and optional fields.

    Args:
        cls: The dataclass type to instantiate
        data: Dictionary with serialized data

    Returns:
        Instance of cls with deserialized data
    """
    if not is_dataclass(cls):
        raise TypeError(f"Expected dataclass type, got {cls}")

    # Use get_type_hints() to resolve string annotations to real types.
    # Pass the defining module's globals so forward references resolve correctly.
    import sys

    cls_module = sys.modules.get(cls.__module__, None)
    cls_globals = getattr(cls_module, "__dict__", None)
    try:
        resolved_hints = get_type_hints(cls, globalns=cls_globals)
    except NameError:
        # Fall back to field annotations if forward references can't resolve
        resolved_hints = {f.name: f.type for f in fields(cls)}

    kwargs: dict[str, Any] = {}
    for field_name, value in data.items():
        if value is None:
            kwargs[field_name] = None
            continue

        field_type = resolved_hints.get(field_name)
        if field_type is None:
            # Field not in dataclass definition, skip
            continue

        # Handle Optional[T] / Union types (unwrap to inner type)
        origin = getattr(field_type, "__origin__", None)
        if origin is Union:
            # Get non-None type from Optional[T]
            args = getattr(field_type, "__args__", ())
            field_type = next((arg for arg in args if arg is not type(None)), field_type)

        # Handle nested dataclasses (dict -> dataclass)
        if isinstance(value, dict):
            if isinstance(field_type, type) and is_dataclass(field_type):
                kwargs[field_name] = _deserialize_dataclass(field_type, value)
            else:
                kwargs[field_name] = value
        # Handle lists (may contain nested dataclasses)
        elif isinstance(value, list):
            list_origin = getattr(field_type, "__origin__", None)
            if list_origin in (list, tuple) and len(value) > 0 and isinstance(value[0], dict):
                list_args = getattr(field_type, "__args__", ())
                if list_args:
                    inner_type = list_args[0]
                    if isinstance(inner_type, type) and is_dataclass(inner_type):
                        kwargs[field_name] = [_deserialize_dataclass(inner_type, item) for item in value]
                    else:
                        kwargs[field_name] = value
                else:
                    kwargs[field_name] = value
            else:
                kwargs[field_name] = value
        # Handle pd.Timestamp strings
        elif isinstance(value, str) and isinstance(field_type, type) and issubclass(field_type, pd.Timestamp):
            kwargs[field_name] = pd.Timestamp(value)
        else:
            kwargs[field_name] = value

    return cls(**kwargs)


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
        if not re.match(r"^[a-zA-Z0-9_-]+$", run_id):
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

    def save_home_run(
        self,
        run_id: str,
        config: HomeConfig,
        results: SimulationResults,
        summary: SummaryStatistics,
        name: str | None = None,
        status: str = "completed",
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
            status: Run status (completed, failed, running)
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
                INSERT OR REPLACE INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            FileNotFoundError: If run directory or required files don't exist
            ValueError: If run data is corrupted or incomplete
        """
        run_dir = self._get_run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

        # Load config from JSON
        config_path = run_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r") as f:
            config_dict = json.load(f)
        config = _deserialize_dataclass(HomeConfig, config_dict)

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

        # Reconstruct SimulationResults from DataFrame
        # The DataFrame has columns matching the to_dataframe() output
        results = SimulationResults(
            generation=df["generation_kw"],
            demand=df["demand_kw"],
            self_consumption=df["self_consumption_kw"],
            battery_charge=df["battery_charge_kw"],
            battery_discharge=df["battery_discharge_kw"],
            battery_soc=df["battery_soc_kwh"],
            grid_import=df["grid_import_kw"],
            grid_export=df["grid_export_kw"],
            import_cost=df["import_cost_gbp"],
            export_revenue=df["export_revenue_gbp"],
            tariff_rate=df["tariff_rate_per_kwh"],
            strategy_name=summary.strategy_name,  # Get from summary
            heat_pump_load=df["heat_pump_load_kw"] if "heat_pump_load_kw" in df.columns else None,
        )

        return config, results, summary

    def save_fleet_run(
        self,
        run_id: str,
        fleet_results: FleetResults,
        fleet_summary: FleetSummary,
        per_home_summaries: list[SummaryStatistics],
        name: str | None = None,
        status: str = "completed",
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
            status: Run status (completed, failed, running)
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
                INSERT OR REPLACE INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            FileNotFoundError: If run directory or required files don't exist
            ValueError: If run data is corrupted or incomplete
        """
        run_dir = self._get_run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

        homes_dir = run_dir / "homes"
        if not homes_dir.exists():
            raise FileNotFoundError(f"Homes directory not found: {homes_dir}")

        # Load fleet config from JSON
        config_path = run_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r") as f:
            fleet_config_dict = json.load(f)

        # Deserialize home configs
        home_configs = [
            _deserialize_dataclass(HomeConfig, home_dict)
            for home_dict in fleet_config_dict["homes"]
        ]

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

            # Reconstruct SimulationResults from DataFrame
            result = SimulationResults(
                generation=df["generation_kw"],
                demand=df["demand_kw"],
                self_consumption=df["self_consumption_kw"],
                battery_charge=df["battery_charge_kw"],
                battery_discharge=df["battery_discharge_kw"],
                battery_soc=df["battery_soc_kwh"],
                grid_import=df["grid_import_kw"],
                grid_export=df["grid_export_kw"],
                import_cost=df["import_cost_gbp"],
                export_revenue=df["export_revenue_gbp"],
                tariff_rate=df["tariff_rate_per_kwh"],
                strategy_name=home_summary.strategy_name,
                heat_pump_load=df["heat_pump_load_kw"] if "heat_pump_load_kw" in df.columns else None,
            )
            per_home_results.append(result)

        # Construct FleetResults
        fleet_results = FleetResults(
            per_home_results=per_home_results,
            home_configs=home_configs,
        )

        return fleet_results, fleet_summary, per_home_summaries

    def list_runs(
        self,
        run_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List simulation runs with optional filtering.

        Queries SQLite database for run metadata with optional filters.

        Args:
            run_type: Filter by run type ('home', 'fleet', 'sweep'), None for all
            status: Filter by status ('running', 'completed', 'failed'), None for all
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

        Removes the database row and all associated files.

        Args:
            run_id: Unique run identifier

        Raises:
            FileNotFoundError: If run directory doesn't exist
        """
        run_dir = self._get_run_dir(run_id)

        # Delete from database first
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            if cursor.rowcount == 0:
                # Run not in database, but may have files
                pass

        # Delete run directory and all files
        if run_dir.exists():
            shutil.rmtree(run_dir)
