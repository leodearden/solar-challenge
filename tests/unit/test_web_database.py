"""Tests for the web database and storage modules."""

import dataclasses
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import RUN_STATUSES, RUN_TYPES, get_db, init_db
from solar_challenge.web.storage import RunRecord, RunStorage

from tests._run_storage_layout import stored_run_dir


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def db_path(temp_dir):
    """Create a database path for testing."""
    return temp_dir / "test.db"


@pytest.fixture
def storage(db_path, temp_dir):
    """Create a RunStorage instance for testing, its run files in an empty directory beside its database."""
    init_db(db_path)
    data_dir = temp_dir / "data"
    data_dir.mkdir()
    return RunStorage(db_path=db_path, data_dir=data_dir)


@pytest.fixture
def sample_home_config():
    """Create a sample home configuration."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0),
        battery_config=BatteryConfig(capacity_kwh=5.0),
        location=Location.bristol(),
        name="Test Home",
    )


@pytest.fixture
def sample_simulation_results():
    """Create sample simulation results."""
    index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min")
    return SimulationResults(
        generation=pd.Series([2.0] * 60, index=index),
        demand=pd.Series([1.0] * 60, index=index),
        self_consumption=pd.Series([1.0] * 60, index=index),
        battery_charge=pd.Series([0.5] * 60, index=index),
        battery_discharge=pd.Series([0.0] * 60, index=index),
        battery_soc=pd.Series([2.5] * 60, index=index),
        grid_import=pd.Series([0.0] * 60, index=index),
        grid_export=pd.Series([0.5] * 60, index=index),
        import_cost=pd.Series([0.0] * 60, index=index),
        export_revenue=pd.Series([0.05] * 60, index=index),
        tariff_rate=pd.Series([0.10] * 60, index=index),
        strategy_name="greedy",
    )


@pytest.fixture
def sample_summary():
    """Create sample summary statistics."""
    return SummaryStatistics(
        total_generation_kwh=100.0,
        total_demand_kwh=80.0,
        total_self_consumption_kwh=60.0,
        total_grid_import_kwh=20.0,
        total_grid_export_kwh=40.0,
        total_battery_charge_kwh=10.0,
        total_battery_discharge_kwh=8.0,
        peak_generation_kw=4.5,
        peak_demand_kw=3.2,
        self_consumption_ratio=0.60,
        grid_dependency_ratio=0.25,
        export_ratio=0.40,
        simulation_days=1,
        total_import_cost_gbp=5.0,
        total_export_revenue_gbp=4.0,
        net_cost_gbp=1.0,
        strategy_name="greedy",
    )


RUNS_COLUMN_VALUES = [
    *(pytest.param("type", run_type, id=f"type-{run_type}") for run_type in RUN_TYPES),
    pytest.param("type", None, id="type-null"),
    *(pytest.param("status", run_status, id=f"status-{run_status}") for run_status in RUN_STATUSES),
    pytest.param("status", None, id="status-null"),
]

VALUES_OUTSIDE_THE_RUNS_COLUMN_DEFINITIONS = [
    pytest.param("type", "hom", id="type-typo"),
    pytest.param("type", "Home", id="type-capitalised"),
    pytest.param("status", "complete", id="status-typo"),
    pytest.param("status", "queued", id="status-a-job-status"),
]


class TestDatabaseInitialization:
    """Tests for database schema creation and initialization."""

    def test_init_db_creates_database_file(self, db_path):
        """Test init_db creates database file."""
        assert not db_path.exists()
        init_db(db_path)
        assert db_path.exists()

    def test_init_db_creates_runs_table(self, db_path):
        """Test init_db creates runs table."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
            )
            assert cursor.fetchone() is not None

    def test_init_db_creates_jobs_table(self, db_path):
        """Test init_db creates jobs table."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
            )
            assert cursor.fetchone() is not None

    def test_init_db_creates_chat_messages_table(self, db_path):
        """Test init_db creates chat_messages table."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
            )
            assert cursor.fetchone() is not None

    def test_init_db_creates_config_presets_table(self, db_path):
        """Test init_db creates config_presets table."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='config_presets'"
            )
            assert cursor.fetchone() is not None

    def test_init_db_creates_indexes(self, db_path):
        """Test init_db creates indexes."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            assert "idx_runs_created_at" in indexes
            assert "idx_runs_type" in indexes
            assert "idx_jobs_run_id" in indexes
            assert "idx_chat_messages_session_id" in indexes

    def test_init_db_is_idempotent(self, db_path):
        """Test init_db can be called multiple times safely."""
        init_db(db_path)
        init_db(db_path)  # Should not raise
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            # Should have our 4 tables (may also have sqlite_sequence for AUTOINCREMENT)
            expected_tables = {'runs', 'jobs', 'chat_messages', 'config_presets'}
            actual_tables = {t for t in tables if not t.startswith('sqlite_')}
            assert actual_tables == expected_tables

    def test_init_db_creates_parent_directory(self, temp_dir):
        """Test init_db creates parent directory if it doesn't exist."""
        nested_path = temp_dir / "nested" / "dir" / "test.db"
        assert not nested_path.parent.exists()
        init_db(nested_path)
        assert nested_path.exists()
        assert nested_path.parent.exists()

    @pytest.mark.parametrize(("column", "value"), RUNS_COLUMN_VALUES)
    def test_init_db_runs_table_accepts_each_run_type_and_run_status_and_null(self, db_path, column, value):
        """The runs table stores each run type or NULL as a run's type, and each run status or NULL as its status."""
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(f"INSERT INTO runs (id, {column}) VALUES (?, ?)", ("probe", value))
            stored = conn.execute(f"SELECT {column} FROM runs WHERE id = 'probe'").fetchone()[0]

        assert stored == value

    @pytest.mark.parametrize(("column", "value"), VALUES_OUTSIDE_THE_RUNS_COLUMN_DEFINITIONS)
    def test_init_db_runs_table_refuses_a_type_or_status_outside_its_definition(self, db_path, column, value):
        """The runs table refuses a type that is not a run type, and a status that is not a run status."""
        init_db(db_path)
        with get_db(db_path) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                conn.execute(f"INSERT INTO runs (id, {column}) VALUES (?, ?)", ("probe", value))

    def test_init_db_gives_a_run_inserted_without_a_status_the_status_running(self, db_path):
        """A run inserted without a status has the status 'running'."""
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO runs (id) VALUES ('no-status')")
            status = conn.execute("SELECT status FROM runs WHERE id = 'no-status'").fetchone()[0]

        assert status == "running"

    def test_run_type_and_run_status_definitions_are_pinned_because_saved_databases_keep_their_checks(self):
        """init_db creates the runs table only when it is missing, so a saved database keeps the CHECK constraints it was created with."""
        assert (RUN_TYPES, RUN_STATUSES) == (("home", "fleet", "sweep"), ("running", "completed", "failed"))


class TestDatabaseConnectionManagement:
    """Tests for database connection management."""

    def test_get_db_returns_connection(self, db_path):
        """Test get_db returns a connection."""
        init_db(db_path)
        with get_db(db_path) as conn:
            assert conn is not None
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

    def test_get_db_enables_row_factory(self, db_path):
        """Test get_db enables dict-like row access."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 as value")
            row = cursor.fetchone()
            assert row["value"] == 1

    def test_get_db_commits_on_success(self, db_path):
        """Test get_db commits changes on success."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                ("test-id", "Test", "home", "completed"),
            )
        # Verify commit by reading in a new connection
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM runs WHERE id = ?", ("test-id",))
            assert cursor.fetchone()["id"] == "test-id"

    def test_get_db_rolls_back_on_error(self, db_path):
        """Test get_db rolls back changes on error."""
        init_db(db_path)
        with pytest.raises(Exception):
            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                    ("test-id", "Test", "home", "completed"),
                )
                raise Exception("Test error")
        # Verify rollback
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM runs WHERE id = ?", ("test-id",))
            assert cursor.fetchone() is None

class TestHomeRunRoundTrip:
    """Tests for home run save/load round-trip."""

    def test_save_and_load_home_run(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test saving and loading a home run preserves data."""
        run_id = "test-run-001"

        # Save the run
        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="Test Run",
            status="completed",
            duration_seconds=5.0,
        )

        # Load the run
        loaded_config, loaded_results, loaded_summary = storage.load_home_run(run_id)

        # Verify config equality
        assert loaded_config.pv_config.capacity_kw == sample_home_config.pv_config.capacity_kw
        assert loaded_config.load_config.annual_consumption_kwh == sample_home_config.load_config.annual_consumption_kwh
        assert loaded_config.battery_config.capacity_kwh == sample_home_config.battery_config.capacity_kwh
        assert loaded_config.location.latitude == sample_home_config.location.latitude
        assert loaded_config.name == sample_home_config.name

        # Verify summary equality
        assert loaded_summary.total_generation_kwh == sample_summary.total_generation_kwh
        assert loaded_summary.total_demand_kwh == sample_summary.total_demand_kwh
        assert loaded_summary.self_consumption_ratio == sample_summary.self_consumption_ratio
        assert loaded_summary.strategy_name == sample_summary.strategy_name

        # Verify time series data
        pd.testing.assert_series_equal(
            loaded_results.generation,
            sample_simulation_results.generation,
            check_names=False,
            check_freq=False,
        )
        pd.testing.assert_series_equal(
            loaded_results.demand,
            sample_simulation_results.demand,
            check_names=False,
            check_freq=False,
        )
        pd.testing.assert_series_equal(
            loaded_results.battery_soc,
            sample_simulation_results.battery_soc,
            check_names=False,
            check_freq=False,
        )

    def test_save_home_run_creates_files(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test save_home_run creates expected files."""
        run_id = "test-run-002"

        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
        )

        run_dir = stored_run_dir(storage, run_id)
        assert run_dir.exists()
        assert (run_dir / "config.json").exists()
        assert (run_dir / "summary.json").exists()
        assert (run_dir / "data.parquet").exists()

    def test_load_home_run_nonexistent_raises(self, storage):
        """Test loading nonexistent run raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            storage.load_home_run("nonexistent-run")


@pytest.fixture
def sample_fleet_data(sample_home_config, sample_simulation_results, sample_summary):
    """Create sample fleet data."""
    # Create 3 homes with slightly different configs
    home_configs = [
        HomeConfig(
            pv_config=PVConfig(capacity_kw=3.0 + i),
            load_config=LoadConfig(annual_consumption_kwh=3000.0 + i * 400),
            battery_config=BatteryConfig(capacity_kwh=5.0),
            name=f"Home {i}",
        )
        for i in range(3)
    ]

    # Create per-home results (same for simplicity)
    per_home_results = [sample_simulation_results] * 3

    # Create fleet results
    fleet_results = FleetResults(
        per_home_results=per_home_results,
        home_configs=home_configs,
    )

    # Create fleet summary with correct FleetSummary fields
    fleet_summary = FleetSummary(
        n_homes=3,
        total_generation_kwh=300.0,
        total_demand_kwh=240.0,
        total_self_consumption_kwh=180.0,
        total_grid_import_kwh=60.0,
        total_grid_export_kwh=120.0,
        fleet_self_consumption_ratio=0.60,
        fleet_grid_dependency_ratio=0.25,
        per_home_generation_min_kwh=95.0,
        per_home_generation_max_kwh=105.0,
        per_home_generation_mean_kwh=100.0,
        per_home_generation_median_kwh=100.0,
        per_home_self_consumption_ratio_min=0.55,
        per_home_self_consumption_ratio_max=0.65,
        per_home_self_consumption_ratio_mean=0.60,
        simulation_days=1,
    )

    # Create per-home summaries
    per_home_summaries = [sample_summary] * 3

    return fleet_results, fleet_summary, per_home_summaries


@pytest.fixture
def saves(storage, sample_home_config, sample_simulation_results, sample_summary, sample_fleet_data):
    """Each save by the type of run it stores, called with a run id and the save's other row arguments."""
    fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

    def save_home(run_id, **row_arguments):
        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            **row_arguments,
        )

    def save_fleet(run_id, **row_arguments):
        storage.save_fleet_run(
            run_id=run_id,
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
            **row_arguments,
        )

    return {"home": save_home, "fleet": save_fleet}


class TestFleetRunRoundTrip:
    """Tests for fleet run save/load round-trip."""

    def test_save_and_load_fleet_run(self, storage, sample_fleet_data):
        """Test saving and loading a fleet run preserves data."""
        run_id = "test-fleet-001"
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        # Save the fleet run
        storage.save_fleet_run(
            run_id=run_id,
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
            name="Test Fleet",
            status="completed",
            duration_seconds=10.0,
        )

        # Load the fleet run
        loaded_fleet_results, loaded_fleet_summary, loaded_per_home_summaries = (
            storage.load_fleet_run(run_id)
        )

        # Verify fleet summary equality
        assert loaded_fleet_summary.total_generation_kwh == fleet_summary.total_generation_kwh
        assert loaded_fleet_summary.fleet_self_consumption_ratio == fleet_summary.fleet_self_consumption_ratio
        assert loaded_fleet_summary.n_homes == fleet_summary.n_homes

        # Verify home configs equality
        assert len(loaded_fleet_results.home_configs) == 3
        for i, (loaded, original) in enumerate(zip(
            loaded_fleet_results.home_configs,
            fleet_results.home_configs,
            strict=True,
        )):
            assert loaded.pv_config.capacity_kw == original.pv_config.capacity_kw
            assert loaded.name == original.name

        # Verify per-home results
        assert len(loaded_fleet_results.per_home_results) == 3
        for loaded_result, original_result in zip(
            loaded_fleet_results.per_home_results,
            fleet_results.per_home_results,
            strict=True,
        ):
            pd.testing.assert_series_equal(
                loaded_result.generation,
                original_result.generation,
                check_names=False,
                check_freq=False,
            )

        # Verify per-home summaries
        assert len(loaded_per_home_summaries) == 3
        for loaded, original in zip(loaded_per_home_summaries, per_home_summaries, strict=True):
            assert loaded.total_generation_kwh == original.total_generation_kwh

    def test_save_fleet_run_creates_homes_directory(self, storage, sample_fleet_data):
        """Test save_fleet_run creates homes subdirectory."""
        run_id = "test-fleet-002"
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        storage.save_fleet_run(
            run_id=run_id,
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
        )

        run_dir = stored_run_dir(storage, run_id)
        homes_dir = run_dir / "homes"
        assert homes_dir.exists()
        assert (homes_dir / "home_0.parquet").exists()
        assert (homes_dir / "home_1.parquet").exists()
        assert (homes_dir / "home_2.parquet").exists()
        assert (homes_dir / "home_0_summary.json").exists()
        assert (homes_dir / "home_1_summary.json").exists()
        assert (homes_dir / "home_2_summary.json").exists()


class TestSavedRunRow:
    """Tests for the runs row each save writes, home and fleet alike."""

    @pytest.mark.parametrize(
        ("kind", "n_homes"),
        [pytest.param("home", 1, id="home"), pytest.param("fleet", 3, id="fleet")],
    )
    def test_a_save_writes_each_column_of_its_runs_row_from_its_arguments(
        self, storage, saves, kind, n_homes
    ):
        """Each column of a run's row holds the save's argument for it, or the value the save gives it.

        The config and summary texts are pinned by
        tests/unit/test_web_storage_roundtrip.py::TestPersistedJson, so they are blanked here.
        A failed run has no completed_at.
        """
        saves[kind](
            "saved-run",
            name="North Roof",
            status="failed",
            error_message="Simulation diverged",
            duration_seconds=5.0,
            created_at="2026-01-01T00:00:00+00:00",
        )

        saved = dataclasses.replace(storage.run_record("saved-run"), config_json=None, summary_json=None)
        assert saved == RunRecord(
            id="saved-run",
            name="North Roof",
            type=kind,
            config_json=None,
            summary_json=None,
            status="failed",
            error_message="Simulation diverged",
            created_at="2026-01-01T00:00:00+00:00",
            completed_at=None,
            duration_seconds=5.0,
            n_homes=n_homes,
            notes=None,
        )

    def test_a_home_save_given_no_name_names_its_run_after_its_home_or_else_unnamed_run(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """A home run saved with no name takes its home's name, or 'Unnamed Run' when its home has none."""
        for run_id, config in (
            ("named-home", sample_home_config),
            ("unnamed-home", dataclasses.replace(sample_home_config, name="")),
        ):
            storage.save_home_run(
                run_id=run_id,
                config=config,
                results=sample_simulation_results,
                summary=sample_summary,
            )

        assert [storage.run_name("named-home"), storage.run_name("unnamed-home")] == [
            "Test Home",
            "Unnamed Run",
        ]

    def test_a_fleet_save_given_no_name_names_its_run_unnamed_fleet_run(self, storage, saves):
        """A fleet run saved with no name is named 'Unnamed Fleet Run'."""
        saves["fleet"]("fleet-run")

        assert storage.run_name("fleet-run") == "Unnamed Fleet Run"

    @pytest.mark.parametrize("kind", ["home", "fleet"])
    def test_a_save_stamps_a_completed_run_with_the_time_it_completed(self, storage, saves, kind):
        """A run saved as completed has the time of the save as its completed_at."""
        before = datetime.now(timezone.utc)
        saves[kind]("completed-run", status="completed")
        after = datetime.now(timezone.utc)

        record = storage.run_record("completed-run")
        assert record.status == "completed"
        assert before <= datetime.fromisoformat(record.completed_at) <= after

    @pytest.mark.parametrize("status", [status for status in RUN_STATUSES if status != "completed"])
    @pytest.mark.parametrize("kind", ["home", "fleet"])
    def test_a_save_of_a_run_that_is_not_completed_leaves_completed_at_null(
        self, storage, saves, kind, status
    ):
        """A run saved with any status but completed has no completed_at.

        The statuses come from RUN_STATUSES, so a new status is covered without editing the test.
        """
        saves[kind]("unfinished-run", status=status)

        record = storage.run_record("unfinished-run")
        assert (record.status, record.completed_at) == (status, None)

    @pytest.mark.parametrize("kind", ["home", "fleet"])
    def test_a_save_given_no_created_at_is_created_at_the_time_it_saves(self, storage, saves, kind):
        """A run saved with no created_at has the time of the save as its created_at."""
        before = datetime.now(timezone.utc)
        saves[kind]("new-run")
        after = datetime.now(timezone.utc)

        record = storage.run_record("new-run")
        assert before <= datetime.fromisoformat(record.created_at) <= after


class TestListRuns:
    """Tests for listing and filtering runs."""

    def test_list_runs_empty_database(self, storage):
        """Test list_runs returns empty list for empty database."""
        runs = storage.list_runs()
        assert runs == []

    def test_list_runs_returns_all_runs(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test list_runs returns all saved runs."""
        for i in range(3):
            storage.save_home_run(
                run_id=f"run-{i}",
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
                name=f"Run {i}",
            )

        runs = storage.list_runs()
        assert len(runs) == 3

    def test_list_runs_filter_by_type(
        self, storage, sample_home_config, sample_simulation_results, sample_summary, sample_fleet_data
    ):
        """Test list_runs filters by run type."""
        # Save 2 home runs
        for i in range(2):
            storage.save_home_run(
                run_id=f"home-{i}",
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
            )

        # Save 1 fleet run
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data
        storage.save_fleet_run(
            run_id="fleet-0",
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
        )

        # Filter by home type
        home_runs = storage.list_runs(run_type="home")
        assert len(home_runs) == 2
        assert all(run["type"] == "home" for run in home_runs)

        # Filter by fleet type
        fleet_runs = storage.list_runs(run_type="fleet")
        assert len(fleet_runs) == 1
        assert fleet_runs[0]["type"] == "fleet"

    def test_list_runs_filter_by_status(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test list_runs filters by status."""
        # Save completed runs
        for i in range(2):
            storage.save_home_run(
                run_id=f"completed-{i}",
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
                status="completed",
            )

        # Save failed run
        storage.save_home_run(
            run_id="failed-0",
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            status="failed",
            error_message="Test error",
        )

        # Filter by completed status
        completed_runs = storage.list_runs(status="completed")
        assert len(completed_runs) == 2
        assert all(run["status"] == "completed" for run in completed_runs)

        # Filter by failed status
        failed_runs = storage.list_runs(status="failed")
        assert len(failed_runs) == 1
        assert failed_runs[0]["status"] == "failed"

    def test_list_runs_limit_and_offset(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test list_runs pagination with limit and offset."""
        # Save 5 runs
        for i in range(5):
            storage.save_home_run(
                run_id=f"run-{i}",
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
                name=f"Run {i}",
            )

        # Get first 2 runs
        runs = storage.list_runs(limit=2)
        assert len(runs) == 2

        # Get next 2 runs with offset
        runs = storage.list_runs(limit=2, offset=2)
        assert len(runs) == 2

        # Get last run with offset (SQLite requires LIMIT when using OFFSET)
        runs = storage.list_runs(limit=10, offset=4)
        assert len(runs) == 1

    def test_list_runs_ordered_by_created_at(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test list_runs returns results ordered by created_at DESC."""
        # Save runs with different IDs
        for i in range(3):
            storage.save_home_run(
                run_id=f"run-{i}",
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
                name=f"Run {i}",
            )

        runs = storage.list_runs()
        # Most recent should be first (run-2)
        assert runs[0]["id"] == "run-2"
        assert runs[1]["id"] == "run-1"
        assert runs[2]["id"] == "run-0"


class TestDeleteRun:
    """Tests for deleting runs."""

    def test_delete_run_removes_database_entry(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test delete_run removes database entry."""
        run_id = "test-delete-001"

        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
        )

        # Verify it exists
        runs = storage.list_runs()
        assert len(runs) == 1

        # Delete it
        storage.delete_run(run_id)

        # Verify it's gone
        runs = storage.list_runs()
        assert len(runs) == 0

    def test_delete_run_removes_files(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test delete_run removes all files."""
        run_id = "test-delete-002"

        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
        )

        run_dir = stored_run_dir(storage, run_id)
        assert run_dir.exists()

        # Delete it
        storage.delete_run(run_id)

        # Verify files are gone
        assert not run_dir.exists()

    def test_delete_run_removes_fleet_files(self, storage, sample_fleet_data):
        """Test delete_run removes fleet run files including homes subdirectory."""
        run_id = "test-delete-003"
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        storage.save_fleet_run(
            run_id=run_id,
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
        )

        run_dir = stored_run_dir(storage, run_id)
        homes_dir = run_dir / "homes"
        assert run_dir.exists()
        assert homes_dir.exists()

        # Delete it
        storage.delete_run(run_id)

        # Verify all files are gone
        assert not run_dir.exists()
        assert not homes_dir.exists()

    def test_delete_nonexistent_run_no_error(self, storage):
        """Test deleting nonexistent run doesn't raise error."""
        # Should not raise
        storage.delete_run("nonexistent-run-id")


class TestRunRecord:
    """Tests for RunStorage.run_record, one run's row read by its id."""

    def test_run_record_reads_every_column_of_the_row_into_the_field_of_its_name(self, storage):
        """Each column of the run's row is read into the RunRecord field of the same name.

        No save writes notes, and a save stamps completed_at with the clock, so the test
        inserts the row to give every column a fixed, distinct value.
        """
        with get_db(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, name, type, config_json, summary_json, status, error_message,"
                " created_at, completed_at, duration_seconds, n_homes, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "fleet-row",
                    "Community Fleet",
                    "fleet",
                    '{"homes": [], "n_homes": 3}',
                    '{"n_homes": 3, "total_generation_kwh": 300.0}',
                    "failed",
                    "Simulation diverged",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:05:00+00:00",
                    300.0,
                    3,
                    "Second attempt",
                ),
            )

        assert storage.run_record("fleet-row") == RunRecord(
            id="fleet-row",
            name="Community Fleet",
            type="fleet",
            config_json='{"homes": [], "n_homes": 3}',
            summary_json='{"n_homes": 3, "total_generation_kwh": 300.0}',
            status="failed",
            error_message="Simulation diverged",
            created_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:05:00+00:00",
            duration_seconds=300.0,
            n_homes=3,
            notes="Second attempt",
        )

    def test_run_record_of_an_id_no_run_has_is_none(self, storage):
        """An id no run has answers None."""
        assert storage.run_record("no-such-run") is None


@pytest.fixture
def north_roof_record():
    """A completed home run's record, with no config or summary text until a test gives it some."""
    return RunRecord(
        id="north-roof",
        name="North Roof",
        type="home",
        config_json=None,
        summary_json=None,
        status="completed",
        error_message=None,
        created_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        duration_seconds=60.0,
        n_homes=1,
        notes=None,
    )


class TestRunRecordDecoding:
    """Tests for RunRecord.decoded_config and RunRecord.decoded_summary, a run's JSON texts decoded."""

    def test_decoded_config_and_summary_are_the_values_their_texts_encode(self, north_roof_record):
        """Each decodes its own text: the config's from config_json, the summary's from summary_json."""
        record = dataclasses.replace(
            north_roof_record,
            config_json='{"pv_config": {"capacity_kw": 4.0}}',
            summary_json='{"total_generation_kwh": 100.0}',
        )

        assert (record.decoded_config(), record.decoded_summary()) == (
            {"pv_config": {"capacity_kw": 4.0}},
            {"total_generation_kwh": 100.0},
        )

    @pytest.mark.parametrize("text", [None, "", "{not json"], ids=["null", "empty", "not-json"])
    def test_decoded_config_and_summary_are_empty_when_their_text_is_null_empty_or_not_json(
        self, north_roof_record, text
    ):
        """A text that is NULL, empty or not JSON decodes as {}."""
        record = dataclasses.replace(north_roof_record, config_json=text, summary_json=text)

        assert (record.decoded_config(), record.decoded_summary()) == ({}, {})


class TestRunRecordTypeAndStatus:
    """Tests for RunRecord's type and status, each one of the runs table's definitions or None."""

    @pytest.mark.parametrize(("column", "value"), RUNS_COLUMN_VALUES)
    def test_a_run_record_holds_each_run_type_and_run_status_and_none(self, north_roof_record, column, value):
        """A record holds each run type or None as its type, and each run status or None as its status."""
        record = dataclasses.replace(north_roof_record, **{column: value})

        assert getattr(record, column) == value

    @pytest.mark.parametrize(("column", "value"), VALUES_OUTSIDE_THE_RUNS_COLUMN_DEFINITIONS)
    def test_a_run_record_refuses_a_type_or_status_outside_its_definition(self, north_roof_record, column, value):
        """A type that is not a run type, or a status that is not a run status, raises ValueError naming the field, the value and the values allowed."""
        allowed = {"type": "['home', 'fleet', 'sweep']", "status": "['running', 'completed', 'failed']"}[column]
        refusal = f"RunRecord.{column} is {value!r}, not one of {allowed} or None"

        with pytest.raises(ValueError, match=re.escape(refusal)):
            dataclasses.replace(north_roof_record, **{column: value})


class TestRunName:
    """Tests for RunStorage.run_name, the name Run History lists and renames a run under."""

    def test_run_name_is_the_name_each_run_was_saved_under(
        self,
        storage,
        sample_home_config,
        sample_simulation_results,
        sample_summary,
        sample_fleet_data,
    ):
        """Each run answers the name it was saved under.

        A home run answers the run's name, not its home's ('Test Home').
        """
        storage.save_home_run(
            run_id="named-home",
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="North Roof",
        )
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data
        storage.save_fleet_run(
            run_id="named-fleet",
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
            name="Community Fleet",
        )

        assert {run_id: storage.run_name(run_id) for run_id in ("named-home", "named-fleet")} == {
            "named-home": "North Roof",
            "named-fleet": "Community Fleet",
        }

    def test_run_name_of_an_id_no_run_has_is_none(self, storage):
        """An id no run has answers None."""
        assert storage.run_name("no-such-run") is None

    def test_run_name_of_a_run_whose_name_is_null_is_none(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """A run whose name is NULL answers None, not a default name.

        Every save writes a name, so the test clears the saved one in the database.
        """
        run_id = "null-name-home"
        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="North Roof",
        )
        with get_db(storage.db_path) as conn:
            conn.execute("UPDATE runs SET name = NULL WHERE id = ?", (run_id,))

        assert storage.run_name(run_id) is None


class TestLatestRunNamed:
    """Tests for RunStorage.latest_run_named, the most recently created run with a given name."""

    def test_latest_run_named_is_the_most_recently_created_run_with_that_name(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """The run with the name that was created last answers, whichever order the runs were saved in.

        The newest run is saved neither first nor last, so only its creation time singles it
        out. The run created after it has another name, so it pins the name filter.
        """
        for run_id, name, created_at in (
            ("middle", "Shared Name", "2026-02-01T00:00:00+00:00"),
            ("newest", "Shared Name", "2026-03-01T00:00:00+00:00"),
            ("oldest", "Shared Name", "2026-01-01T00:00:00+00:00"),
            ("other-name", "Other Name", "2026-05-01T00:00:00+00:00"),
        ):
            storage.save_home_run(
                run_id=run_id,
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
                name=name,
                created_at=created_at,
            )

        assert storage.latest_run_named("Shared Name") == storage.run_record("newest")

    def test_latest_run_named_of_a_name_no_run_has_is_none(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """A name no run has answers None."""
        storage.save_home_run(
            run_id="north-roof",
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="North Roof",
        )

        assert storage.latest_run_named("South Roof") is None


class TestUpdateRunLabels:
    """Tests for RunStorage.update_run_labels, which writes a run's name and notes as Run History edits them."""

    @pytest.fixture
    def north_roof_run_id(self, storage, sample_home_config, sample_simulation_results, sample_summary):
        """The id of a home run saved under the name 'North Roof', its notes NULL as every save leaves them."""
        run_id = "north-roof"
        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="North Roof",
        )
        return run_id

    def test_update_run_labels_writes_each_label_given_and_answers_the_updated_record(
        self, storage, north_roof_run_id
    ):
        """Each label given is written, and the run's record as written is answered."""
        updated = storage.update_run_labels(north_roof_run_id, {"name": "South Roof", "notes": "Checked"})

        assert updated == storage.run_record(north_roof_run_id)
        assert (updated.name, updated.notes) == ("South Roof", "Checked")

    def test_update_run_labels_leaves_each_label_not_given_unchanged(self, storage, north_roof_run_id):
        """A label absent from the labels keeps its value."""
        storage.update_run_labels(north_roof_run_id, {"notes": "Checked"})
        after_notes = storage.run_record(north_roof_run_id)
        storage.update_run_labels(north_roof_run_id, {"name": "South Roof"})
        after_name = storage.run_record(north_roof_run_id)

        assert [(after_notes.name, after_notes.notes), (after_name.name, after_name.notes)] == [
            ("North Roof", "Checked"),
            ("South Roof", "Checked"),
        ]

    def test_update_run_labels_writes_a_none_label_as_null(self, storage, north_roof_run_id):
        """A label given as None is cleared to NULL."""
        storage.update_run_labels(north_roof_run_id, {"notes": "Checked"})
        storage.update_run_labels(north_roof_run_id, {"notes": None})

        assert storage.run_record(north_roof_run_id).notes is None

    def test_update_run_labels_with_no_labels_answers_the_record_unchanged(self, storage, north_roof_run_id):
        """No labels write nothing, and answer the run's record as it was."""
        before = storage.run_record(north_roof_run_id)

        assert storage.update_run_labels(north_roof_run_id, {}) == before

    def test_update_run_labels_of_an_id_no_run_has_is_none(self, storage):
        """An id no run has answers None, and no run is written under it."""
        assert storage.update_run_labels("no-such-run", {"name": "South Roof"}) is None
        assert storage.run_record("no-such-run") is None

    def test_update_run_labels_refuses_a_key_that_is_not_a_run_label_and_writes_nothing(
        self, storage, north_roof_run_id
    ):
        """A key that is not a run label raises ValueError naming it, before any label is written.

        The keys become column names in SQL, so the valid label beside the refused key is not
        written either.
        """
        before = storage.run_record(north_roof_run_id)

        with pytest.raises(
            ValueError, match=r"Not run labels: \['status'\]; the run labels are \['name', 'notes'\]"
        ):
            storage.update_run_labels(north_roof_run_id, {"status": "failed", "notes": "Checked"})

        assert storage.run_record(north_roof_run_id) == before


class TestDatabasePragmas:
    """Tests for SQLite pragma settings."""

    def test_wal_mode_enabled_after_init(self, db_path):
        """Test that WAL journal mode is active after init_db."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode == "wal"

    def test_foreign_keys_enabled_in_connection(self, db_path):
        """Test that foreign keys are enforced in get_db connections."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys")
            fk_status = cursor.fetchone()[0]
            assert fk_status == 1

    def test_foreign_key_enforcement_rejects_invalid_reference(self, db_path):
        """Test that FK enforcement actually rejects invalid references."""
        init_db(db_path)
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            # Try to insert a job referencing a non-existent run
            import pytest
            with pytest.raises(Exception):
                cursor.execute(
                    "INSERT INTO jobs (id, run_id, status) VALUES (?, ?, ?)",
                    ("job-1", "nonexistent-run", "queued"),
                )


REFUSED_RUN_IDS = [
    pytest.param("../", id="parent-directory"),
    pytest.param("../../etc", id="two-directories-up"),
    pytest.param("/absolute/path", id="absolute-path"),
    pytest.param("/etc/passwd", id="absolute-path-of-a-file"),
    pytest.param("run\x00id", id="null-byte"),
    pytest.param("", id="empty"),
    pytest.param("run.id", id="dot"),
    pytest.param("run id", id="space"),
    pytest.param("abc\n", id="trailing-newline"),
]

ACCEPTED_RUN_IDS = [
    pytest.param("abc", id="letters"),
    pytest.param("test-run-001", id="hyphens"),
    pytest.param("my_run_123", id="underscores"),
    pytest.param("valid-run_123", id="hyphen-and-underscore"),
    pytest.param("550e8400-e29b-41d4-a716-446655440000", id="uuid"),
]

RUN_LOADERS = [
    pytest.param(RunStorage.load_home_run, id="home"),
    pytest.param(RunStorage.load_fleet_run, id="fleet"),
]


class TestRunIdValidation:
    """The run ids the store refuses and accepts, as its saves, loads and deletes see them."""

    @pytest.mark.parametrize("run_id", REFUSED_RUN_IDS)
    def test_a_home_save_under_an_id_the_store_refuses_raises_value_error_and_writes_nothing(
        self, storage, sample_home_config, sample_simulation_results, sample_summary, run_id
    ):
        """A home save under an id the store refuses raises ValueError, and writes no file and no runs row."""
        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.save_home_run(
                run_id=run_id,
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
            )

        assert list(storage.data_dir.iterdir()) == []
        assert storage.list_runs() == []

    @pytest.mark.parametrize("run_id", REFUSED_RUN_IDS)
    def test_a_fleet_save_under_an_id_the_store_refuses_raises_value_error_and_writes_nothing(
        self, storage, sample_fleet_data, run_id
    ):
        """A fleet save under an id the store refuses raises ValueError, and writes no file and no runs row."""
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.save_fleet_run(
                run_id=run_id,
                fleet_results=fleet_results,
                fleet_summary=fleet_summary,
                per_home_summaries=per_home_summaries,
            )

        assert list(storage.data_dir.iterdir()) == []
        assert storage.list_runs() == []

    @pytest.mark.parametrize("run_id", REFUSED_RUN_IDS)
    @pytest.mark.parametrize("load", RUN_LOADERS)
    def test_a_load_of_an_id_the_store_refuses_raises_file_not_found_error(
        self, storage, load, run_id
    ):
        """A load of an id the store refuses raises FileNotFoundError, as a load of an id no run has does, and carries the refusal."""
        with pytest.raises(FileNotFoundError, match="Invalid run_id"):
            load(storage, run_id)

    @pytest.mark.parametrize("run_id", REFUSED_RUN_IDS)
    def test_a_delete_of_an_id_the_store_refuses_raises_value_error(self, storage, run_id):
        """A delete of an id the store refuses raises ValueError: no run can be saved under the id, so the caller has a bug."""
        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.delete_run(run_id)

    @pytest.fixture
    def outside(self, temp_dir):
        """An empty directory beside the store's data directory, beyond its runs directory."""
        outside = temp_dir / "outside"
        outside.mkdir()
        return outside

    @pytest.fixture
    def linked_run_id(self, storage, outside):
        """An id whose run directory links to *outside*, so that it resolves beyond the runs directory."""
        run_id = "linked"
        run_dir = stored_run_dir(storage, run_id)
        run_dir.parent.mkdir()
        run_dir.symlink_to(outside, target_is_directory=True)
        return run_id

    def test_a_home_save_under_an_id_whose_run_directory_links_outside_the_runs_directory_raises_value_error_and_writes_nothing(
        self,
        storage,
        outside,
        linked_run_id,
        sample_home_config,
        sample_simulation_results,
        sample_summary,
    ):
        """A home save under an id whose run directory links outside the runs directory raises ValueError, and writes nothing through the link and no runs row."""
        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.save_home_run(
                run_id=linked_run_id,
                config=sample_home_config,
                results=sample_simulation_results,
                summary=sample_summary,
            )

        assert list(outside.iterdir()) == []
        assert storage.list_runs() == []

    def test_a_fleet_save_under_an_id_whose_run_directory_links_outside_the_runs_directory_raises_value_error_and_writes_nothing(
        self, storage, outside, linked_run_id, sample_fleet_data
    ):
        """A fleet save under an id whose run directory links outside the runs directory raises ValueError, and writes nothing through the link and no runs row."""
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.save_fleet_run(
                run_id=linked_run_id,
                fleet_results=fleet_results,
                fleet_summary=fleet_summary,
                per_home_summaries=per_home_summaries,
            )

        assert list(outside.iterdir()) == []
        assert storage.list_runs() == []

    @pytest.mark.parametrize("load", RUN_LOADERS)
    def test_a_load_of_an_id_whose_run_directory_links_outside_the_runs_directory_raises_file_not_found_error(
        self, storage, linked_run_id, load
    ):
        """A load of an id whose run directory links outside the runs directory raises FileNotFoundError, and carries the refusal rather than a missing file's error."""
        with pytest.raises(FileNotFoundError, match="Invalid run_id"):
            load(storage, linked_run_id)

    def test_a_delete_of_an_id_whose_run_directory_links_outside_the_runs_directory_raises_value_error_and_removes_nothing(
        self, storage, outside, linked_run_id
    ):
        """A delete of an id whose run directory links outside the runs directory raises ValueError, and removes neither what the link leads to nor the link."""
        (outside / "kept.txt").write_text("kept")

        with pytest.raises(ValueError, match="Invalid run_id"):
            storage.delete_run(linked_run_id)

        assert (outside / "kept.txt").read_text() == "kept"
        assert stored_run_dir(storage, linked_run_id).is_symlink()

    @pytest.mark.parametrize("run_id", ACCEPTED_RUN_IDS)
    def test_a_home_run_saved_under_an_accepted_id_loads_back_from_the_directory_the_id_names(
        self, storage, sample_home_config, sample_simulation_results, sample_summary, run_id
    ):
        """A home run saved under an accepted id loads back equal, from the run directory the id names."""
        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
        )

        loaded_config, _, loaded_summary = storage.load_home_run(run_id)

        assert (loaded_config, loaded_summary) == (sample_home_config, sample_summary)
        assert stored_run_dir(storage, run_id).is_dir()
