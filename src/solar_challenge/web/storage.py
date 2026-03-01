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
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.web.database import get_db


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

    def _get_run_dir(self, run_id: str) -> Path:
        """Get the directory path for a run's data files.

        Args:
            run_id: Unique run identifier

        Returns:
            Path to run directory
        """
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
    ) -> None:
        """Save a home simulation run to storage.

        Creates directory structure, serializes config and summary to JSON,
        saves time series to parquet, and inserts metadata into database.

        Args:
            run_id: Unique run identifier
            config: Home configuration
            results: Simulation results with time series
            summary: Summary statistics
            name: Optional run name (defaults to config.name)
            status: Run status (completed, failed, running)
            error_message: Optional error message for failed runs
            duration_seconds: Optional simulation duration
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

        # Insert run metadata into database
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
                    created_at if status == "completed" else None,
                    duration_seconds,
                    1,  # n_homes for a single home run
                    None,  # notes field, can be added later
                ),
            )
