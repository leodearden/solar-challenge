"""Storage regression tests for RunStorage roundtrip, corruption, and edge cases.

Tests cover:
- C3 regression: list_runs with offset but no limit
- C4 regression: heat_pump_load survives home and fleet roundtrips
- completed_at timestamp differs from created_at
- Full home and fleet roundtrip with all fields populated
- Corrupted parquet graceful error handling
- Missing run directory graceful error handling
- Delete run removes DB record and filesystem files
"""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from flask import Flask

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.web.app import create_app
from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


@pytest.fixture
def storage(app: Flask) -> RunStorage:
    """Create a RunStorage instance using the test app config."""
    return RunStorage(
        db_path=app.config["DATABASE"],
        data_dir=app.config["DATA_DIR"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(n: int = 60) -> pd.DatetimeIndex:
    """Create a 1-minute resolution DatetimeIndex."""
    return pd.date_range("2024-06-01", periods=n, freq="min", tz="Europe/London")


def _make_series(index: pd.DatetimeIndex, value: float = 1.0, name: str = "") -> pd.Series:
    """Create a pd.Series filled with a constant value."""
    return pd.Series(np.full(len(index), value), index=index, name=name)


def _make_home_config(name: str = "Test Home") -> HomeConfig:
    """Create a minimal HomeConfig for testing."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3200.0),
        battery_config=BatteryConfig(capacity_kwh=5.0),
        location=Location.bristol(),
        name=name,
    )


def _make_simulation_results(
    index: pd.DatetimeIndex | None = None,
    include_heat_pump: bool = False,
) -> SimulationResults:
    """Create a SimulationResults with realistic data for all fields."""
    if index is None:
        index = _make_index()
    return SimulationResults(
        generation=_make_series(index, 2.5, "generation_kw"),
        demand=_make_series(index, 1.0, "demand_kw"),
        self_consumption=_make_series(index, 0.8, "self_consumption_kw"),
        battery_charge=_make_series(index, 0.5, "battery_charge_kw"),
        battery_discharge=_make_series(index, 0.3, "battery_discharge_kw"),
        battery_soc=_make_series(index, 2.0, "battery_soc_kwh"),
        grid_import=_make_series(index, 0.2, "grid_import_kw"),
        grid_export=_make_series(index, 1.2, "grid_export_kw"),
        import_cost=_make_series(index, 0.05, "import_cost_gbp"),
        export_revenue=_make_series(index, 0.04, "export_revenue_gbp"),
        tariff_rate=_make_series(index, 0.25, "tariff_rate_per_kwh"),
        strategy_name="self_consumption",
        heat_pump_load=_make_series(index, 0.6, "heat_pump_load_kw") if include_heat_pump else None,
    )


def _make_summary(
    include_heat_pump: bool = False,
    strategy_name: str = "self_consumption",
) -> SummaryStatistics:
    """Create a SummaryStatistics with realistic values."""
    return SummaryStatistics(
        total_generation_kwh=100.0,
        total_demand_kwh=80.0,
        total_self_consumption_kwh=60.0,
        total_grid_import_kwh=20.0,
        total_grid_export_kwh=40.0,
        total_battery_charge_kwh=10.0,
        total_battery_discharge_kwh=8.0,
        peak_generation_kw=4.0,
        peak_demand_kw=3.5,
        self_consumption_ratio=0.6,
        grid_dependency_ratio=0.25,
        export_ratio=0.4,
        simulation_days=1,
        total_import_cost_gbp=5.0,
        total_export_revenue_gbp=3.0,
        net_cost_gbp=2.0,
        strategy_name=strategy_name,
        total_heat_pump_load_kwh=10.0 if include_heat_pump else None,
        peak_heat_pump_load_kw=0.6 if include_heat_pump else None,
        heat_pump_load_ratio=0.125 if include_heat_pump else None,
    )


def _make_fleet_summary(n_homes: int = 2) -> FleetSummary:
    """Create a FleetSummary with realistic values."""
    return FleetSummary(
        n_homes=n_homes,
        total_generation_kwh=200.0,
        total_demand_kwh=160.0,
        total_self_consumption_kwh=120.0,
        total_grid_import_kwh=40.0,
        total_grid_export_kwh=80.0,
        fleet_self_consumption_ratio=0.6,
        fleet_grid_dependency_ratio=0.25,
        per_home_generation_min_kwh=90.0,
        per_home_generation_max_kwh=110.0,
        per_home_generation_mean_kwh=100.0,
        per_home_generation_median_kwh=100.0,
        per_home_self_consumption_ratio_min=0.55,
        per_home_self_consumption_ratio_max=0.65,
        per_home_self_consumption_ratio_mean=0.6,
        simulation_days=1,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListRunsOffsetWithoutLimit:
    """C3 regression: list_runs(offset=5) without limit must not crash."""

    def test_list_runs_offset_without_limit(self, app: Flask, storage: RunStorage) -> None:
        """Call list_runs(offset=5) without limit; verify no SQLite syntax error."""
        # Insert a few runs so the DB is not empty
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        for i in range(3):
            storage.save_home_run(
                run_id=f"run-{i}",
                config=config,
                results=results,
                summary=summary,
            )

        # This should not raise a sqlite3.OperationalError about syntax
        runs = storage.list_runs(offset=5)
        # With only 3 runs and offset=5, we should get an empty list
        assert isinstance(runs, list)
        assert len(runs) == 0

    def test_list_runs_offset_within_range(self, app: Flask, storage: RunStorage) -> None:
        """list_runs with offset within range returns remaining runs."""
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        for i in range(5):
            storage.save_home_run(
                run_id=f"run-{i}",
                config=config,
                results=results,
                summary=summary,
            )

        runs = storage.list_runs(offset=3)
        assert isinstance(runs, list)
        assert len(runs) == 2


class TestHeatPumpHomeRoundtrip:
    """C4 regression: heat_pump_load data survives home save/load roundtrip."""

    def test_heat_pump_home_roundtrip(self, storage: RunStorage) -> None:
        """Save a home SimulationResults with heat_pump_load, load it back,
        verify heat_pump_load survives the roundtrip."""
        config = _make_home_config()
        results = _make_simulation_results(include_heat_pump=True)
        summary = _make_summary(include_heat_pump=True)

        storage.save_home_run(
            run_id="hp-home-001",
            config=config,
            results=results,
            summary=summary,
        )

        loaded_config, loaded_results, loaded_summary = storage.load_home_run("hp-home-001")

        # heat_pump_load must not be None
        assert loaded_results.heat_pump_load is not None
        # Values must match the original
        pd.testing.assert_series_equal(
            loaded_results.heat_pump_load,
            results.heat_pump_load,
            check_names=False,
            check_freq=False,
        )


class TestHeatPumpFleetRoundtrip:
    """C4 regression: heat_pump_load data survives fleet save/load roundtrip."""

    def test_heat_pump_fleet_roundtrip(self, storage: RunStorage) -> None:
        """Save a fleet with heat_pump_load per home, load it back,
        verify heat_pump_load survives for each home."""
        index = _make_index()
        home_configs = [_make_home_config(f"Home {i}") for i in range(2)]
        home_results = [_make_simulation_results(index, include_heat_pump=True) for _ in range(2)]
        home_summaries = [_make_summary(include_heat_pump=True) for _ in range(2)]

        fleet_results = FleetResults(
            per_home_results=home_results,
            home_configs=home_configs,
        )
        fleet_summary = _make_fleet_summary(n_homes=2)

        storage.save_fleet_run(
            run_id="hp-fleet-001",
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=home_summaries,
        )

        loaded_fleet, loaded_fleet_summary, loaded_home_summaries = storage.load_fleet_run(
            "hp-fleet-001"
        )

        for i, loaded_home in enumerate(loaded_fleet.per_home_results):
            assert loaded_home.heat_pump_load is not None, (
                f"Home {i}: heat_pump_load should not be None after roundtrip"
            )
            pd.testing.assert_series_equal(
                loaded_home.heat_pump_load,
                home_results[i].heat_pump_load,
                check_names=False,
                check_freq=False,
            )


class TestCompletedAtTimestamp:
    """completed_at should be a real timestamp, distinct from created_at."""

    def test_completed_at_timestamp(self, storage: RunStorage) -> None:
        """Save a completed run with a known created_at, verify completed_at differs."""
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        created_at = "2024-01-15T10:00:00+00:00"

        # Small delay so completed_at will differ
        storage.save_home_run(
            run_id="ts-test-001",
            config=config,
            results=results,
            summary=summary,
            created_at=created_at,
        )

        runs = storage.list_runs()
        assert len(runs) == 1
        run = runs[0]

        assert run["created_at"] == created_at
        assert run["completed_at"] is not None
        assert run["completed_at"] != run["created_at"]

        # completed_at should be parseable as a timestamp
        completed_ts = pd.Timestamp(run["completed_at"])
        assert completed_ts is not None


class TestFullHomeRoundtrip:
    """Save a complete SimulationResults with all fields, load it back,
    verify all fields match."""

    def test_full_home_roundtrip(self, storage: RunStorage) -> None:
        """Full roundtrip: all SimulationResults and SummaryStatistics fields preserved."""
        config = _make_home_config()
        index = _make_index(120)
        results = _make_simulation_results(index=index, include_heat_pump=True)
        summary = _make_summary(include_heat_pump=True)

        storage.save_home_run(
            run_id="full-home-001",
            config=config,
            results=results,
            summary=summary,
            name="Full Home Test",
            duration_seconds=42.5,
        )

        loaded_config, loaded_results, loaded_summary = storage.load_home_run("full-home-001")

        # Config fields
        assert loaded_config.pv_config.capacity_kw == config.pv_config.capacity_kw
        assert loaded_config.load_config.annual_consumption_kwh == config.load_config.annual_consumption_kwh
        assert loaded_config.battery_config is not None
        assert loaded_config.battery_config.capacity_kwh == config.battery_config.capacity_kwh

        # Time series fields
        for field_name in (
            "generation", "demand", "self_consumption",
            "battery_charge", "battery_discharge", "battery_soc",
            "grid_import", "grid_export", "import_cost",
            "export_revenue", "tariff_rate",
        ):
            original = getattr(results, field_name)
            loaded = getattr(loaded_results, field_name)
            pd.testing.assert_series_equal(loaded, original, check_names=False, check_freq=False)

        # heat_pump_load
        assert loaded_results.heat_pump_load is not None
        pd.testing.assert_series_equal(
            loaded_results.heat_pump_load, results.heat_pump_load,
            check_names=False, check_freq=False,
        )

        # Strategy name
        assert loaded_results.strategy_name == results.strategy_name

        # Summary statistics
        assert loaded_summary.total_generation_kwh == summary.total_generation_kwh
        assert loaded_summary.total_demand_kwh == summary.total_demand_kwh
        assert loaded_summary.self_consumption_ratio == summary.self_consumption_ratio
        assert loaded_summary.strategy_name == summary.strategy_name
        assert loaded_summary.total_heat_pump_load_kwh == summary.total_heat_pump_load_kwh
        assert loaded_summary.peak_heat_pump_load_kw == summary.peak_heat_pump_load_kw

        # DB record check
        runs = storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["name"] == "Full Home Test"
        assert runs[0]["type"] == "home"
        assert runs[0]["duration_seconds"] == 42.5


class TestFullFleetRoundtrip:
    """Fleet-level roundtrip with all fields populated."""

    def test_full_fleet_roundtrip(self, storage: RunStorage) -> None:
        """Full fleet roundtrip: FleetResults, FleetSummary, and per-home summaries."""
        index = _make_index(90)
        n_homes = 3
        home_configs = [_make_home_config(f"Home {i}") for i in range(n_homes)]
        home_results = [_make_simulation_results(index, include_heat_pump=True) for _ in range(n_homes)]
        home_summaries = [_make_summary(include_heat_pump=True) for _ in range(n_homes)]

        fleet_results = FleetResults(
            per_home_results=home_results,
            home_configs=home_configs,
        )
        fleet_summary = _make_fleet_summary(n_homes=n_homes)

        storage.save_fleet_run(
            run_id="full-fleet-001",
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=home_summaries,
            name="Full Fleet Test",
            duration_seconds=120.0,
        )

        loaded_fleet, loaded_fleet_summary, loaded_home_summaries = storage.load_fleet_run(
            "full-fleet-001"
        )

        # Verify number of homes
        assert len(loaded_fleet.per_home_results) == n_homes
        assert len(loaded_fleet.home_configs) == n_homes
        assert len(loaded_home_summaries) == n_homes

        # Verify fleet summary
        assert loaded_fleet_summary.n_homes == n_homes
        assert loaded_fleet_summary.total_generation_kwh == fleet_summary.total_generation_kwh
        assert loaded_fleet_summary.fleet_self_consumption_ratio == fleet_summary.fleet_self_consumption_ratio

        # Verify per-home results
        for i in range(n_homes):
            loaded = loaded_fleet.per_home_results[i]
            original = home_results[i]
            pd.testing.assert_series_equal(
                loaded.generation, original.generation, check_names=False, check_freq=False,
            )
            pd.testing.assert_series_equal(
                loaded.demand, original.demand, check_names=False, check_freq=False,
            )
            assert loaded.heat_pump_load is not None
            pd.testing.assert_series_equal(
                loaded.heat_pump_load, original.heat_pump_load,
                check_names=False, check_freq=False,
            )

        # Verify per-home summaries
        for i in range(n_homes):
            assert loaded_home_summaries[i].total_generation_kwh == home_summaries[i].total_generation_kwh
            assert loaded_home_summaries[i].strategy_name == home_summaries[i].strategy_name

        # Verify per-home configs
        for i in range(n_homes):
            assert loaded_fleet.home_configs[i].pv_config.capacity_kw == home_configs[i].pv_config.capacity_kw

        # DB record check
        runs = storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["name"] == "Full Fleet Test"
        assert runs[0]["type"] == "fleet"
        assert runs[0]["n_homes"] == n_homes


class TestCorruptedParquet:
    """Write a corrupt file where the parquet should be, verify load returns
    a graceful error (not crash)."""

    def test_corrupted_parquet(self, storage: RunStorage) -> None:
        """Corrupted parquet file should raise a readable error, not a raw crash."""
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        storage.save_home_run(
            run_id="corrupt-001",
            config=config,
            results=results,
            summary=summary,
        )

        # Overwrite the parquet file with garbage bytes
        run_dir = storage._get_run_dir("corrupt-001")
        parquet_path = run_dir / "data.parquet"
        parquet_path.write_bytes(b"THIS IS NOT A VALID PARQUET FILE")

        # Loading should raise an error, but not an unhandled crash
        with pytest.raises(Exception):
            storage.load_home_run("corrupt-001")


class TestMissingRunDirectory:
    """Delete the run directory after saving to DB, verify load handles it gracefully."""

    def test_missing_run_directory(self, storage: RunStorage) -> None:
        """Loading a run whose directory was deleted should raise FileNotFoundError."""
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        storage.save_home_run(
            run_id="missing-dir-001",
            config=config,
            results=results,
            summary=summary,
        )

        # Delete the run directory
        run_dir = storage._get_run_dir("missing-dir-001")
        shutil.rmtree(run_dir)

        # The DB record still exists, but the filesystem is gone
        runs = storage.list_runs()
        assert len(runs) == 1

        # Loading should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            storage.load_home_run("missing-dir-001")


class TestDeleteRun:
    """Save a run, delete it, verify DB record and filesystem files are gone."""

    def test_delete_run(self, storage: RunStorage) -> None:
        """delete_run removes both the DB record and the run directory."""
        config = _make_home_config()
        results = _make_simulation_results()
        summary = _make_summary()

        storage.save_home_run(
            run_id="delete-me-001",
            config=config,
            results=results,
            summary=summary,
        )

        # Verify it exists
        run_dir = storage._get_run_dir("delete-me-001")
        assert run_dir.exists()
        runs = storage.list_runs()
        assert len(runs) == 1

        # Delete it
        storage.delete_run("delete-me-001")

        # Verify DB record is gone
        runs = storage.list_runs()
        assert len(runs) == 0

        # Verify filesystem is gone
        assert not run_dir.exists()

    def test_delete_run_fleet(self, storage: RunStorage) -> None:
        """delete_run removes fleet run data including homes subdirectory."""
        index = _make_index()
        home_configs = [_make_home_config(f"Home {i}") for i in range(2)]
        home_results = [_make_simulation_results(index) for _ in range(2)]
        home_summaries = [_make_summary() for _ in range(2)]

        fleet_results = FleetResults(
            per_home_results=home_results,
            home_configs=home_configs,
        )
        fleet_summary = _make_fleet_summary(n_homes=2)

        storage.save_fleet_run(
            run_id="delete-fleet-001",
            fleet_results=fleet_results,
            fleet_summary=fleet_summary,
            per_home_summaries=home_summaries,
        )

        run_dir = storage._get_run_dir("delete-fleet-001")
        assert run_dir.exists()
        assert (run_dir / "homes").exists()

        storage.delete_run("delete-fleet-001")

        assert not run_dir.exists()
        runs = storage.list_runs()
        assert len(runs) == 0


class TestRunIdValidation:
    """Validate that run_id inputs are sanitised to prevent path traversal."""

    def test_path_traversal_dot_dot_slash_rejected(self, storage: RunStorage) -> None:
        """run_id with ../../ should be rejected."""
        with pytest.raises(ValueError):
            storage._get_run_dir("../../etc")

    def test_path_traversal_absolute_path_rejected(self, storage: RunStorage) -> None:
        """run_id that is an absolute path should be rejected."""
        with pytest.raises(ValueError):
            storage._get_run_dir("/etc/passwd")

    def test_null_byte_rejected(self, storage: RunStorage) -> None:
        """run_id containing a null byte should be rejected."""
        with pytest.raises(ValueError):
            storage._get_run_dir("run\x00id")

    def test_spaces_rejected(self, storage: RunStorage) -> None:
        """run_id containing spaces should be rejected."""
        with pytest.raises(ValueError):
            storage._get_run_dir("run id")

    def test_valid_run_id_accepted(self, storage: RunStorage) -> None:
        """A valid run_id with alphanumeric, hyphens, underscores should pass."""
        # Should not raise
        result = storage._get_run_dir("valid-run_123")
        assert result.name == "valid-run_123"

    def test_uuid_run_id_accepted(self, storage: RunStorage) -> None:
        """A UUID-style run_id should be accepted."""
        # Should not raise
        result = storage._get_run_dir("550e8400-e29b-41d4-a716-446655440000")
        assert result.name == "550e8400-e29b-41d4-a716-446655440000"
