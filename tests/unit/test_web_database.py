"""Tests for the web database and storage modules."""

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import close_db, get_db, init_db
from solar_challenge.web.storage import RunStorage


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
    """Create a RunStorage instance for testing."""
    init_db(db_path)
    return RunStorage(db_path=db_path, data_dir=temp_dir)


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

    def test_close_db_closes_connection(self, db_path):
        """Test close_db closes cached connection."""
        # Note: close_db is designed for Flask's teardown_appcontext
        # and uses a global _connections cache. For this test,
        # we just verify it doesn't raise an error
        close_db(db_path)  # Should not raise even if connection doesn't exist


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

        run_dir = storage._get_run_dir(run_id)
        assert run_dir.exists()
        assert (run_dir / "config.json").exists()
        assert (run_dir / "summary.json").exists()
        assert (run_dir / "data.parquet").exists()

    def test_save_home_run_creates_database_entry(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test save_home_run creates database entry."""
        run_id = "test-run-003"

        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            name="Test Database Entry",
            status="completed",
        )

        with get_db(storage.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["id"] == run_id
            assert row["name"] == "Test Database Entry"
            assert row["type"] == "home"
            assert row["status"] == "completed"
            assert row["n_homes"] == 1

    def test_load_home_run_nonexistent_raises(self, storage):
        """Test loading nonexistent run raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            storage.load_home_run("nonexistent-run")

    def test_save_home_run_with_error_status(
        self, storage, sample_home_config, sample_simulation_results, sample_summary
    ):
        """Test saving a failed run with error message."""
        run_id = "test-run-004"

        storage.save_home_run(
            run_id=run_id,
            config=sample_home_config,
            results=sample_simulation_results,
            summary=sample_summary,
            status="failed",
            error_message="Test error message",
        )

        with get_db(storage.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, error_message FROM runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            assert row["status"] == "failed"
            assert row["error_message"] == "Test error message"


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

        run_dir = storage._get_run_dir(run_id)
        homes_dir = run_dir / "homes"
        assert homes_dir.exists()
        assert (homes_dir / "home_0.parquet").exists()
        assert (homes_dir / "home_1.parquet").exists()
        assert (homes_dir / "home_2.parquet").exists()
        assert (homes_dir / "home_0_summary.json").exists()
        assert (homes_dir / "home_1_summary.json").exists()
        assert (homes_dir / "home_2_summary.json").exists()

    def test_save_fleet_run_creates_database_entry(self, storage, sample_fleet_data):
        """Test save_fleet_run creates database entry."""
        run_id = "test-fleet-003"
        fleet_results, fleet_summary, per_home_summaries = sample_fleet_data

        storage.save_fleet_run(
            run_id=run_id,
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=per_home_summaries,
            name="Test Fleet Database Entry",
            status="completed",
        )

        with get_db(storage.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["type"] == "fleet"
            assert row["n_homes"] == 3
            assert row["name"] == "Test Fleet Database Entry"


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

        run_dir = storage._get_run_dir(run_id)
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

        run_dir = storage._get_run_dir(run_id)
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
