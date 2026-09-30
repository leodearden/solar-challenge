# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the AI assistant's tool handlers, called directly rather than from a chat turn."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask

from tests.unit.web_assistant._fakes import seed_run


class TestExplainMetric:
    """Tests for the explain_metric(metric) -> dict[str, str] handler."""

    def test_known_metric_self_consumption_ratio(self) -> None:
        """explain_metric('self_consumption_ratio') returns dict with non-empty definition and band."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("self_consumption_ratio")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "definition" in result, f"Missing 'definition' key: {result}"
        assert "uk_benchmark_band" in result, f"Missing 'uk_benchmark_band' key: {result}"
        assert isinstance(result["definition"], str) and result["definition"], (
            "definition must be a non-empty string"
        )
        assert isinstance(result["uk_benchmark_band"], str) and result["uk_benchmark_band"], (
            "uk_benchmark_band must be a non-empty string"
        )

    def test_known_metric_self_sufficiency(self) -> None:
        """explain_metric('self_sufficiency') returns dict with non-empty definition and band."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("self_sufficiency")
        assert "definition" in result
        assert "uk_benchmark_band" in result
        assert result["definition"]
        assert result["uk_benchmark_band"]

    def test_key_normalization_hyphen(self) -> None:
        """'self-consumption ratio' normalizes to same canonical entry as 'self_consumption_ratio'."""
        from solar_challenge.web.assistant import explain_metric

        r1 = explain_metric("self_consumption_ratio")
        r2 = explain_metric("self-consumption ratio")
        assert r1 == r2, (
            f"Expected same result for canonical and hyphenated form; "
            f"got {r1!r} vs {r2!r}"
        )

    def test_key_normalization_case(self) -> None:
        """'Self_Consumption_Ratio' normalizes to same canonical entry."""
        from solar_challenge.web.assistant import explain_metric

        r1 = explain_metric("self_consumption_ratio")
        r2 = explain_metric("Self_Consumption_Ratio")
        assert r1 == r2, (
            f"Expected case-insensitive lookup; got {r1!r} vs {r2!r}"
        )

    def test_unknown_metric_returns_graceful_dict(self) -> None:
        """An unrecognized metric returns a dict with both keys present mentioning 'unknown'."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("nonexistent_metric_xyz")
        assert isinstance(result, dict), "Must return a dict, not raise"
        assert "definition" in result, f"Missing 'definition' in graceful response: {result}"
        assert "uk_benchmark_band" in result, (
            f"Missing 'uk_benchmark_band' in graceful response: {result}"
        )
        # Must mention the metric is unknown
        combined = (result["definition"] + " " + result["uk_benchmark_band"]).lower()
        assert "unknown" in combined or "not found" in combined or "not recognised" in combined, (
            f"Graceful response should mention metric is unknown/not found: {result}"
        )

    def test_unknown_metric_does_not_raise(self) -> None:
        """explain_metric with an unknown name must NOT raise any exception."""
        from solar_challenge.web.assistant import explain_metric

        try:
            explain_metric("totally_made_up_metric_12345")
        except Exception as exc:
            raise AssertionError(
                f"explain_metric should not raise for unknown metric, got: {exc!r}"
            ) from exc

    def test_all_known_metrics_have_both_keys(self) -> None:
        """Every entry in METRIC_TABLE has non-empty definition and uk_benchmark_band."""
        from solar_challenge.web.assistant import METRIC_TABLE

        assert METRIC_TABLE, "Expected METRIC_TABLE to be non-empty"
        for name, entry in METRIC_TABLE.items():
            assert "definition" in entry, f"Entry {name!r} missing 'definition'"
            assert "uk_benchmark_band" in entry, f"Entry {name!r} missing 'uk_benchmark_band'"
            assert entry["definition"], f"Entry {name!r} has empty definition"
            assert entry["uk_benchmark_band"], f"Entry {name!r} has empty uk_benchmark_band"


class TestSuggestConfig:
    """Tests for suggest_config(annual_consumption_kwh, goal) -> dict[str, Any]."""

    def test_returns_dict_with_sizing_keys(self) -> None:
        """suggest_config returns a dict with recommended_pv_kwp and recommended_battery_kwh."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "recommended_pv_kwp" in result, f"Missing 'recommended_pv_kwp': {result}"
        assert "recommended_battery_kwh" in result, f"Missing 'recommended_battery_kwh': {result}"

    def test_numeric_outputs_are_positive_floats(self) -> None:
        """recommended_pv_kwp and recommended_battery_kwh must be positive floats."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        pv = result["recommended_pv_kwp"]
        batt = result["recommended_battery_kwh"]
        assert isinstance(pv, (int, float)) and pv > 0, (
            f"recommended_pv_kwp must be positive float, got {pv!r}"
        )
        assert isinstance(batt, (int, float)) and batt > 0, (
            f"recommended_battery_kwh must be positive float, got {batt!r}"
        )

    def test_higher_consumption_gives_larger_pv(self) -> None:
        """Higher annual consumption → larger recommended PV (scaling check)."""
        from solar_challenge.web.assistant import suggest_config

        low_result = suggest_config(1900.0, "self_sufficiency")
        high_result = suggest_config(4200.0, "self_sufficiency")
        assert high_result["recommended_pv_kwp"] > low_result["recommended_pv_kwp"], (
            f"Expected larger PV for higher consumption: "
            f"got {high_result['recommended_pv_kwp']} vs {low_result['recommended_pv_kwp']}"
        )

    def test_caveat_contains_run_a_simulation(self) -> None:
        """Result dict must include a caveat/note string containing 'run a simulation'."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "bill_savings")
        # Look for a string value that mentions "run a simulation"
        found = any(
            isinstance(v, str) and "run a simulation" in v.lower()
            for v in result.values()
        )
        assert found, (
            f"Expected at least one string value containing 'run a simulation': {result}"
        )

    def test_note_cites_no_internal_document(self) -> None:
        """The model relays the note to the user, who cannot open the project's PRD or resolve its section numbers."""
        from solar_challenge.web.assistant import suggest_config

        note = suggest_config(3100.0, "self_sufficiency")["note"]
        assert "PRD" not in note, f"note cites the internal PRD: {note!r}"
        assert "§" not in note, f"note cites a section of an internal document: {note!r}"

    def test_accepts_self_sufficiency_goal(self) -> None:
        """suggest_config with goal='self_sufficiency' must not raise."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        assert isinstance(result, dict)

    def test_accepts_bill_savings_goal(self) -> None:
        """suggest_config with goal='bill_savings' must not raise."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "bill_savings")
        assert isinstance(result, dict)

    def test_accepts_unknown_goal_without_raising(self) -> None:
        """suggest_config with an unrecognised goal must not raise."""
        from solar_challenge.web.assistant import suggest_config

        try:
            result = suggest_config(3100.0, "mystery_goal")
            assert isinstance(result, dict)
        except Exception as exc:
            raise AssertionError(
                f"suggest_config should not raise for unknown goal; got: {exc!r}"
            ) from exc

    def test_battery_scales_with_consumption(self) -> None:
        """Higher annual consumption → larger recommended battery."""
        from solar_challenge.web.assistant import suggest_config

        low = suggest_config(1900.0, "self_sufficiency")
        high = suggest_config(4200.0, "self_sufficiency")
        assert high["recommended_battery_kwh"] > low["recommended_battery_kwh"], (
            f"Expected larger battery for higher consumption: "
            f"{high['recommended_battery_kwh']} vs {low['recommended_battery_kwh']}"
        )

    def test_self_sufficiency_goal_gives_larger_sizing_than_bill_savings(self) -> None:
        """suggest_config('self_sufficiency') yields strictly larger PV & battery than 'bill_savings'."""
        from solar_challenge.web.assistant import suggest_config

        consumption = 3100.0
        ss = suggest_config(consumption, "self_sufficiency")
        bs = suggest_config(consumption, "bill_savings")
        assert ss["recommended_pv_kwp"] > bs["recommended_pv_kwp"], (
            f"Expected self_sufficiency PV ({ss['recommended_pv_kwp']}) "
            f"> bill_savings PV ({bs['recommended_pv_kwp']})"
        )
        assert ss["recommended_battery_kwh"] > bs["recommended_battery_kwh"], (
            f"Expected self_sufficiency battery ({ss['recommended_battery_kwh']}) "
            f"> bill_savings battery ({bs['recommended_battery_kwh']})"
        )


class TestGetRunResults:
    """Tests for get_run_results(run_id_or_name, db_path) -> dict."""

    def test_lookup_by_id_returns_seeded_fields(self, tmp_path: Path) -> None:
        """get_run_results(run_id, db_path) returns dict with seeded row fields."""
        from solar_challenge.web.assistant import get_run_results

        db_path = tmp_path / "grr_test.db"
        summary = {"total_generation_kwh": 1234.5, "self_consumption_ratio": 0.62}
        seed_run(
            db_path,
            run_id="run-abc-123",
            name="test-run",
            type="home",
            status="completed",
            created_at="2026-01-01T12:00:00+00:00",
            summary=summary,
        )

        result = get_run_results("run-abc-123", db_path)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result.get("run_id") == "run-abc-123", f"run_id mismatch: {result}"
        assert result.get("name") == "test-run", f"name mismatch: {result}"
        assert result.get("type") == "home", f"type mismatch: {result}"
        assert result.get("status") == "completed", f"status mismatch: {result}"
        assert result.get("created_at") == "2026-01-01T12:00:00+00:00", (
            f"created_at mismatch: {result}"
        )
        assert result.get("summary") == summary, (
            f"summary dict mismatch: expected {summary!r}, got {result.get('summary')!r}"
        )

    def test_lookup_by_name_resolves_same_row(self, tmp_path: Path) -> None:
        """get_run_results(name, db_path) resolves to the same row as lookup by id."""
        from solar_challenge.web.assistant import get_run_results

        db_path = tmp_path / "grr_name_test.db"
        summary = {"self_sufficiency": 0.45}
        seed_run(
            db_path,
            run_id="run-xyz-456",
            name="my-named-run",
            type="fleet",
            status="completed",
            created_at="2026-02-01T08:00:00+00:00",
            summary=summary,
        )

        result_by_id = get_run_results("run-xyz-456", db_path)
        result_by_name = get_run_results("my-named-run", db_path)

        # Both should resolve to the same row
        assert result_by_id.get("run_id") == "run-xyz-456"
        assert result_by_name.get("run_id") == "run-xyz-456", (
            f"Name lookup should resolve same row as id lookup; got: {result_by_name}"
        )
        assert result_by_name.get("name") == "my-named-run", (
            f"name field should be 'my-named-run': {result_by_name}"
        )

    def test_unknown_id_returns_graceful_dict(self, tmp_path: Path) -> None:
        """get_run_results with unknown id returns a graceful dict, does NOT raise."""
        from solar_challenge.web.assistant import get_run_results

        db_path = tmp_path / "grr_unknown_test.db"
        seed_run(
            db_path,
            run_id="run-known",
            name="known-run",
            status="completed",
            created_at="2026-01-01T00:00:00+00:00",
            summary={},
        )

        try:
            result = get_run_results("totally-unknown-id-xyz", db_path)
        except Exception as exc:
            raise AssertionError(
                f"get_run_results should not raise for unknown id; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        # Must signal not-found somehow (error key OR found=False)
        is_graceful = "error" in result or result.get("found") is False
        assert is_graceful, (
            f"Expected graceful not-found signal (error or found=False); got: {result}"
        )

    def test_name_collision_returns_newest_run(self, tmp_path: Path) -> None:
        """When two rows share a name, get_run_results returns the one with the later created_at."""
        from solar_challenge.web.assistant import get_run_results

        db_path = tmp_path / "grr_collision_test.db"
        # Older run seeded first
        seed_run(
            db_path,
            run_id="run-old-collision",
            name="shared-run-name",
            status="completed",
            created_at="2026-01-01T00:00:00+00:00",
            summary={"total_generation_kwh": 100.0},
        )
        # Newer run with same name seeded second
        seed_run(
            db_path,
            run_id="run-new-collision",
            name="shared-run-name",
            status="completed",
            created_at="2026-03-01T00:00:00+00:00",
            summary={"total_generation_kwh": 200.0},
        )

        result = get_run_results("shared-run-name", db_path)

        assert result.get("run_id") == "run-new-collision", (
            f"Name tie-break should return newest run (run-new-collision); "
            f"got run_id={result.get('run_id')!r}"
        )

    def test_null_summary_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """A run stored with NULL summary_json returns summary=={} and does not raise."""
        from solar_challenge.web.assistant import get_run_results
        from solar_challenge.web.database import get_db, init_db

        db_path = tmp_path / "grr_null_summary.db"
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, name, type, status, created_at, summary_json) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                ("run-null-summary", "null-summary-run", "home", "completed",
                 "2026-01-01T00:00:00+00:00"),
            )

        try:
            result = get_run_results("run-null-summary", db_path)
        except Exception as exc:
            raise AssertionError(
                f"get_run_results should not raise for NULL summary_json; got: {exc!r}"
            ) from exc

        assert result.get("summary") == {}, (
            f"Expected summary=={{}} for NULL summary_json; got {result.get('summary')!r}"
        )

    def test_corrupt_db_path_returns_error_dict(self, tmp_path: Path) -> None:
        """get_run_results with a nonexistent/unreadable db_path returns {'error':...}, no raise."""
        from solar_challenge.web.assistant import get_run_results

        bad_path = tmp_path / "nonexistent" / "missing.db"  # parent dir does not exist

        try:
            result = get_run_results("any-run-id", bad_path)
        except Exception as exc:
            raise AssertionError(
                f"get_run_results should not raise for bad db_path; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, (
            f"Expected 'error' key for unreadable db_path; got {result}"
        )


class TestListRecentRuns:
    """Tests for list_recent_runs(limit, db_path) -> dict."""

    def test_returns_newest_first_bounded_by_limit(self, tmp_path: Path) -> None:
        """list_recent_runs returns runs newest-first, count bounded by limit."""
        from solar_challenge.web.assistant import list_recent_runs

        db_path = tmp_path / "lrr_test.db"
        # Seed 5 runs with distinct created_at timestamps
        for i in range(5):
            seed_run(
                db_path,
                run_id=f"run-{i:03d}",
                name=f"run-name-{i}",
                status="completed",
                created_at=f"2026-01-{i + 1:02d}T12:00:00+00:00",
                summary={"total_generation_kwh": float(i * 100)},
            )

        result = list_recent_runs(3, db_path)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "runs" in result, f"Expected 'runs' key; got {result}"
        runs = result["runs"]
        assert isinstance(runs, list), f"Expected list, got {type(runs)}"
        assert len(runs) == 3, f"Expected exactly 3 runs (limit=3); got {len(runs)}"

        # Newest first: run-004 → run-003 → run-002
        assert runs[0]["created_at"] > runs[1]["created_at"], (
            f"Expected descending created_at; got {runs[0]['created_at']!r} then {runs[1]['created_at']!r}"
        )
        assert runs[1]["created_at"] > runs[2]["created_at"], (
            f"Expected descending created_at; got {runs[1]['created_at']!r} then {runs[2]['created_at']!r}"
        )

    def test_each_row_has_identifying_fields(self, tmp_path: Path) -> None:
        """Each entry carries id/run_id, name, type, status, created_at."""
        from solar_challenge.web.assistant import list_recent_runs

        db_path = tmp_path / "lrr_fields_test.db"
        seed_run(
            db_path,
            run_id="run-fields-001",
            name="fields-run",
            type="fleet",
            status="completed",
            created_at="2026-03-15T09:00:00+00:00",
            summary={"self_consumption_ratio": 0.70},
        )

        result = list_recent_runs(10, db_path)
        runs = result["runs"]
        assert runs, "Expected at least one run"
        row = runs[0]

        # Must carry identifying fields
        assert row.get("name") == "fields-run", f"name mismatch: {row}"
        assert row.get("status") == "completed", f"status mismatch: {row}"
        assert row.get("created_at") == "2026-03-15T09:00:00+00:00", f"created_at mismatch: {row}"
        # Either 'id' or 'run_id' key must be present
        has_id = "id" in row or "run_id" in row
        assert has_id, f"Expected 'id' or 'run_id' field; got keys: {list(row.keys())}"

    def test_empty_db_returns_empty_list(self, tmp_path: Path) -> None:
        """list_recent_runs on empty DB returns {'runs': []} without raising."""
        from solar_challenge.web.assistant import list_recent_runs
        from solar_challenge.web.database import init_db

        db_path = tmp_path / "lrr_empty_test.db"
        init_db(db_path)

        try:
            result = list_recent_runs(10, db_path)
        except Exception as exc:
            raise AssertionError(
                f"list_recent_runs should not raise on empty DB; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "runs" in result, f"Expected 'runs' key; got {result}"
        assert result["runs"] == [], (
            f"Expected empty list for empty DB; got {result['runs']}"
        )

    def test_limit_is_clamped_to_sane_max(self, tmp_path: Path) -> None:
        """A very large limit is clamped so returned count <= clamp ceiling."""
        from solar_challenge.web.assistant import list_recent_runs

        db_path = tmp_path / "lrr_clamp_test.db"
        # Seed 60 rows — more than any sane clamp ceiling (50)
        for i in range(60):
            seed_run(
                db_path,
                run_id=f"clamp-run-{i:03d}",
                name=f"clamp-{i}",
                status="completed",
                created_at=f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00",
                summary={},
            )

        result = list_recent_runs(9999, db_path)
        runs = result["runs"]
        # Returned count must be <= some sane upper bound (the implementation clamps to 1..50)
        assert len(runs) <= 50, (
            f"Expected clamped count (<= 50); got {len(runs)}"
        )

    def test_non_positive_limit_returns_results(self, tmp_path: Path) -> None:
        """A non-positive limit is handled gracefully (clamped to default, no raise)."""
        from solar_challenge.web.assistant import list_recent_runs

        db_path = tmp_path / "lrr_nonpos_test.db"
        seed_run(
            db_path,
            run_id="run-np-001",
            name="np-run",
            status="completed",
            created_at="2026-01-01T00:00:00+00:00",
            summary={},
        )

        try:
            result = list_recent_runs(0, db_path)
        except Exception as exc:
            raise AssertionError(
                f"list_recent_runs should not raise for limit=0; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "runs" in result, f"Expected 'runs' key; got {result}"
        # Non-positive limit is clamped to a default (>0 results expected)
        assert len(result["runs"]) >= 1, (
            f"Expected at least 1 result when limit clamped from 0; got {len(result['runs'])}"
        )

    def test_null_summary_json_does_not_raise(self, tmp_path: Path) -> None:
        """A run stored with NULL summary_json is returned with None metrics, no crash."""
        from solar_challenge.web.assistant import list_recent_runs
        from solar_challenge.web.database import get_db, init_db

        db_path = tmp_path / "lrr_null_summary.db"
        init_db(db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, name, type, status, created_at, summary_json) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                ("lrr-null-summary", "null-summary-run", "home", "completed",
                 "2026-01-01T00:00:00+00:00"),
            )

        try:
            result = list_recent_runs(5, db_path)
        except Exception as exc:
            raise AssertionError(
                f"list_recent_runs should not raise for NULL summary_json; got: {exc!r}"
            ) from exc

        runs = result.get("runs", [])
        assert len(runs) == 1, f"Expected 1 run; got {len(runs)}"
        row = runs[0]
        # total_generation_kwh and self_consumption_ratio default to None when summary is NULL
        assert row.get("total_generation_kwh") is None, (
            f"Expected None for total_generation_kwh with NULL summary; got {row.get('total_generation_kwh')!r}"
        )

    def test_corrupt_db_path_returns_error_dict(self, tmp_path: Path) -> None:
        """list_recent_runs with a nonexistent db_path returns {'runs':[],'error':...}, no raise."""
        from solar_challenge.web.assistant import list_recent_runs

        bad_path = tmp_path / "nonexistent" / "missing.db"  # parent dir does not exist

        try:
            result = list_recent_runs(5, bad_path)
        except Exception as exc:
            raise AssertionError(
                f"list_recent_runs should not raise for bad db_path; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "runs" in result, f"Expected 'runs' key for corrupt db; got {result}"
        assert result["runs"] == [], f"Expected empty runs list for corrupt db; got {result['runs']}"
        assert "error" in result, (
            f"Expected 'error' key for unreadable db_path; got {result}"
        )


class TestRunHomeSimulation:
    """Tests for run_home_simulation(params, job_manager, db_path, data_dir) -> dict."""

    def _make_jm(self) -> MagicMock:
        """Return a MagicMock job_manager with submit_home_job stubbed."""
        jm = MagicMock()
        jm.submit_home_job.return_value = ("job-h", "run-h")
        return jm

    def test_returns_run_id_and_results_url(self, tmp_path: Path) -> None:
        """run_home_simulation returns {run_id, results_url} with correct values."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        params = {"pv_kw": 4, "battery_kwh": 5, "days": 7, "location": "bristol"}
        result = run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result.get("run_id") == "run-h", (
            f"Expected run_id='run-h'; got {result.get('run_id')!r}"
        )
        assert result.get("results_url") == "/results/home/run-h", (
            f"Expected results_url='/results/home/run-h'; got {result.get('results_url')!r}"
        )

    def test_submit_home_job_called_with_correct_config(self, tmp_path: Path) -> None:
        """submit_home_job called once; config has correct pv_kw and battery_kwh."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        params = {"pv_kw": 4, "battery_kwh": 5, "days": 7, "location": "bristol"}
        run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_home_job.assert_called_once()
        call_kwargs = jm.submit_home_job.call_args

        # config should be a HomeConfig with pv 4.0 and battery 5.0
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[0]
        assert hasattr(config, "pv_config"), (
            f"Expected config to have pv_config; got {type(config)}"
        )
        assert config.pv_config.capacity_kw == 4.0, (
            f"Expected pv capacity_kw=4.0; got {config.pv_config.capacity_kw}"
        )
        assert config.battery_config is not None, "Expected battery_config to be set"
        assert config.battery_config.capacity_kwh == 5.0, (
            f"Expected battery capacity_kwh=5.0; got {config.battery_config.capacity_kwh}"
        )

    def test_days_drives_start_end_window(self, tmp_path: Path) -> None:
        """days parameter is reflected in the start/end dates passed to submit_home_job."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        params_7 = {"pv_kw": 4, "days": 7, "location": "bristol"}
        params_30 = {"pv_kw": 4, "days": 30, "location": "bristol"}

        run_home_simulation(params_7, jm, str(tmp_path / "t7.db"), str(tmp_path))
        call_7 = jm.submit_home_job.call_args
        start_7 = call_7.kwargs.get("start_date") or call_7.args[1]
        end_7 = call_7.kwargs.get("end_date") or call_7.args[2]
        span_7 = (end_7 - start_7).days

        jm.reset_mock()
        jm.submit_home_job.return_value = ("job-h", "run-h")

        run_home_simulation(params_30, jm, str(tmp_path / "t30.db"), str(tmp_path))
        call_30 = jm.submit_home_job.call_args
        start_30 = call_30.kwargs.get("start_date") or call_30.args[1]
        end_30 = call_30.kwargs.get("end_date") or call_30.args[2]
        span_30 = (end_30 - start_30).days

        assert span_30 > span_7, (
            f"Expected 30-day span ({span_30}) > 7-day span ({span_7})"
        )

    def test_invalid_pv_kw_returns_graceful_error(self, tmp_path: Path) -> None:
        """Invalid pv_kw (out of 0.5-20 range) returns error dict; submit not called; no raise."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        params = {"pv_kw": 999, "battery_kwh": 5, "days": 7, "location": "bristol"}

        try:
            result = run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))
        except Exception as exc:
            raise AssertionError(
                f"run_home_simulation should not raise on invalid params; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, f"Expected 'error' key; got {result}"
        jm.submit_home_job.assert_not_called()

    def test_submit_failure_returns_error_naming_it(self, tmp_path: Path) -> None:
        """A submit_home_job that raises yields an error dict naming the failure, and no run link."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        submit_failure = "job queue unavailable"
        jm.submit_home_job.side_effect = RuntimeError(submit_failure)

        result = run_home_simulation(
            {"pv_kw": 4, "battery_kwh": 5, "days": 7, "location": "bristol"},
            jm,
            str(tmp_path / "t.db"),
            str(tmp_path),
        )

        assert submit_failure in result["error"]
        assert "run_id" not in result

    def test_days_defaults_to_7_when_omitted(self, tmp_path: Path) -> None:
        """When 'days' is absent the window passed to submit_home_job is 7 days, not the full year."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        # No 'days' key — handler must default to 7
        params: dict[str, Any] = {"pv_kw": 4, "location": "bristol"}
        run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_home_job.assert_called_once()
        call_kwargs = jm.submit_home_job.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[1]
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[2]
        span = (end_date - start_date).days

        assert span == 6, (
            f"Expected 7-day window (span=6) when 'days' omitted; got span={span}. "
            "Handler must default to 7 days, not the full calendar year."
        )
        assert span != 365, (
            "Handler is using the full-year fallback instead of the documented 7-day default"
        )

    def test_explicit_days_honored_over_default(self, tmp_path: Path) -> None:
        """A caller-supplied 'days' value is not overwritten by the default."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        # Explicit days=30 must produce a 30-day window (span=29)
        params: dict[str, Any] = {"pv_kw": 4, "days": 30, "location": "bristol"}
        run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_home_job.assert_called_once()
        call_kwargs = jm.submit_home_job.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[1]
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[2]
        span = (end_date - start_date).days

        assert span == 29, (
            f"Expected 30-day window (span=29) when days=30; got span={span}. "
            "Caller-supplied 'days' must not be clobbered by the default."
        )

    def test_home_days_none_defaults_to_7(self, tmp_path: Path) -> None:
        """Explicit days=None is treated as absent — handler falls back to 7-day window."""
        from solar_challenge.web.assistant import run_home_simulation

        jm = self._make_jm()
        # Model may emit {"days": null} — must be normalised to 7, not the full-year fallback
        params: dict[str, Any] = {"pv_kw": 4, "location": "bristol", "days": None}
        run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_home_job.assert_called_once()
        call_kwargs = jm.submit_home_job.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[1]
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[2]
        span = (end_date - start_date).days

        assert span == 6, (
            f"Expected 7-day window (span=6) when days=None; got span={span}. "
            "Explicit None must normalise to the 7-day default, not the full calendar year."
        )
        assert span != 365, (
            "Handler uses full-year fallback for days=None instead of the 7-day default"
        )


class TestRunFleetSimulation:
    """Tests for run_fleet_simulation(params, job_manager, db_path, data_dir) -> dict."""

    def _make_jm(self) -> MagicMock:
        """Return a MagicMock job_manager with submit_fleet_job stubbed."""
        jm = MagicMock()
        jm.submit_fleet_job.return_value = ("job-f", "run-f")
        return jm

    def test_returns_run_id_and_results_url(self, tmp_path: Path) -> None:
        """run_fleet_simulation returns {run_id, results_url} for fleet."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        params = {"n_homes": 3, "pv_kw": 4, "battery_kwh": 5, "location": "bristol", "days": 7}
        result = run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result.get("run_id") == "run-f", (
            f"Expected run_id='run-f'; got {result.get('run_id')!r}"
        )
        assert result.get("results_url") == "/results/fleet/run-f", (
            f"Expected results_url='/results/fleet/run-f'; got {result.get('results_url')!r}"
        )

    def test_submit_fleet_job_called_with_correct_configs_list(self, tmp_path: Path) -> None:
        """submit_fleet_job called once; configs is list of length n_homes with correct pv."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        params = {"n_homes": 3, "pv_kw": 4, "battery_kwh": 5, "location": "bristol", "days": 7}
        run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args

        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert isinstance(configs, list), f"Expected configs to be a list; got {type(configs)}"
        assert len(configs) == 3, f"Expected 3-length configs list; got {len(configs)}"
        for i, cfg in enumerate(configs):
            assert hasattr(cfg, "pv_config"), (
                f"configs[{i}] expected to have pv_config; got {type(cfg)}"
            )
            assert cfg.pv_config.capacity_kw == 4.0, (
                f"configs[{i}].pv_config.capacity_kw expected 4.0; got {cfg.pv_config.capacity_kw}"
            )

    def test_n_homes_clamped_to_max_100(self, tmp_path: Path) -> None:
        """n_homes=9999 results in configs list clamped to <= 100."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        params = {"n_homes": 9999, "pv_kw": 4, "location": "bristol", "days": 7}
        run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) <= 100, (
            f"Expected n_homes clamped to <= 100; got {len(configs)}"
        )

    def test_n_homes_zero_clamped_to_at_least_1(self, tmp_path: Path) -> None:
        """n_homes=0 is clamped to at least 1 (no empty fleet)."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        params = {"n_homes": 0, "pv_kw": 4, "location": "bristol", "days": 7}
        run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) >= 1, (
            f"Expected n_homes=0 clamped to >= 1; got {len(configs)}"
        )

    def test_invalid_pv_kw_returns_graceful_error(self, tmp_path: Path) -> None:
        """Invalid pv_kw returns error dict; submit_fleet_job NOT called; no raise."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        params = {"n_homes": 3, "pv_kw": 999, "location": "bristol", "days": 7}

        try:
            result = run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))
        except Exception as exc:
            raise AssertionError(
                f"run_fleet_simulation should not raise on invalid params; got: {exc!r}"
            ) from exc

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, f"Expected 'error' key; got {result}"
        jm.submit_fleet_job.assert_not_called()

    def test_submit_failure_returns_error_naming_it(self, tmp_path: Path) -> None:
        """A submit_fleet_job that raises yields an error dict naming the failure, and no run link."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        submit_failure = "job queue unavailable"
        jm.submit_fleet_job.side_effect = RuntimeError(submit_failure)

        result = run_fleet_simulation(
            {"n_homes": 3, "pv_kw": 4, "location": "bristol", "days": 7},
            jm,
            str(tmp_path / "t.db"),
            str(tmp_path),
        )

        assert submit_failure in result["error"]
        assert "run_id" not in result

    def test_fleet_days_defaults_to_7_when_omitted(self, tmp_path: Path) -> None:
        """When 'days' is absent the fleet window passed to submit_fleet_job is 7 days, not the full year."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        # No 'days' key — handler must default to 7
        params: dict[str, Any] = {"n_homes": 3, "pv_kw": 4, "location": "bristol"}
        run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[1]
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[2]
        span = (end_date - start_date).days

        assert span == 6, (
            f"Expected 7-day window (span=6) when 'days' omitted; got span={span}. "
            "Fleet handler must default to 7 days, not the full calendar year."
        )
        assert span != 365, (
            "Fleet handler is using the full-year fallback instead of the documented 7-day default"
        )

    def test_fleet_days_none_defaults_to_7(self, tmp_path: Path) -> None:
        """Explicit days=None in fleet params is treated as absent — handler falls back to 7."""
        from solar_challenge.web.assistant import run_fleet_simulation

        jm = self._make_jm()
        # Model may emit {"days": null} — must be normalised to 7, not the full-year fallback
        params: dict[str, Any] = {"n_homes": 3, "pv_kw": 4, "location": "bristol", "days": None}
        run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[1]
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[2]
        span = (end_date - start_date).days

        assert span == 6, (
            f"Expected 7-day window (span=6) when days=None; got span={span}. "
            "Explicit None must normalise to the 7-day default, not the full calendar year."
        )
        assert span != 365, (
            "Fleet handler uses full-year fallback for days=None instead of the 7-day default"
        )


@pytest.mark.slow
class TestRunHomeSimulationWithRealJobManager:
    """SLOW: real 1-day Bristol home sim via real JobManager (excluded from fast verify).

    Excluded from the standard verify loop by the 'slow' marker.  Run with
    ``pytest -m slow`` when you need the anti-fake-done end-to-end proof.
    """

    def test_run_home_simulation_real_job_lands_in_runs(
        self, app: Flask, tmp_path: Path
    ) -> None:
        """run_home_simulation() with the real JobManager creates a completed run."""
        import time as _time

        from solar_challenge.web.assistant import get_run_results, run_home_simulation

        db_path: str = app.config["DATABASE"]
        data_dir: str = app.config["DATA_DIR"]
        job_manager = app.extensions["job_manager"]

        result = run_home_simulation(
            {
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
            job_manager,
            db_path,
            data_dir,
        )

        assert "error" not in result, (
            f"run_home_simulation returned an error: {result.get('error')}"
        )
        run_id: str = result.get("run_id", "")
        results_url: str = result.get("results_url", "")
        assert run_id, f"Expected non-empty run_id; got {run_id!r}"
        assert results_url == f"/results/home/{run_id}", (
            f"Expected results_url='/results/home/{run_id}'; got {results_url!r}"
        )

        # Poll (monotonic deadline ≤ 120 s) until the real sim completes.
        deadline = _time.monotonic() + 120
        status = "running"
        while _time.monotonic() < deadline:
            run_data = get_run_results(run_id, db_path)
            status = run_data.get("status", "")
            if status in ("completed", "failed"):
                break
            _time.sleep(2)

        assert status == "completed", (
            f"1-day Bristol sim did not reach 'completed' within 120 s; "
            f"last status: {status!r}"
        )

        # Assert the completed run is fetchable with a non-None generation metric
        run_data = get_run_results(run_id, db_path)
        assert "error" not in run_data, f"get_run_results returned error: {run_data}"
        summary = run_data.get("summary", {})
        assert summary.get("total_generation_kwh") is not None, (
            f"Expected non-None total_generation_kwh in completed run summary; "
            f"got summary={summary!r}"
        )
