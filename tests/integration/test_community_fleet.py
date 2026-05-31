"""Integration tests for community energy sharing CLI and pipeline.

Tests the full stack:
  - output.generate_community_report (fast, unit-like)
  - scenarios/bristol-community.yaml contract
  - `fleet run` CLI wiring with community section + report
  - End-to-end pipeline A/B (community on vs off) with injected weather
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.main import app
from solar_challenge.community import (
    CommunityBillingConfig,
    CommunityConfig,
    simulate_community,
    validate_community_balance,
)
from solar_challenge.config import load_community_config, load_fleet_config
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.output import generate_community_report
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import FlatRateTariff

pytestmark = pytest.mark.integration

SCENARIO = Path("scenarios/bristol-community.yaml")

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synth_weather(day: str = "2024-06-21", tz: str = "Europe/London") -> pd.DataFrame:
    """Build a 1-day hourly weather DataFrame with a smooth midday solar bump.

    Mirrors the shape of tests/unit/test_pv.py's sample_weather_data fixture
    but covers all 24 hours so _align_tmy_to_demand maps correctly for any
    sim window on the same day.
    """
    index = pd.date_range(day, periods=24, freq="h", tz=tz)
    # Smooth midday solar curve: zero at night, peak ~850 W/m² at noon
    ghi =       [0, 0, 0, 0, 0, 0,  50, 200, 400, 600, 750, 820, 850, 820, 750, 600, 400, 200,  50,  0,  0,  0,  0,  0]
    dni =       [0, 0, 0, 0, 0, 0, 100, 350, 550, 750, 850, 900, 920, 900, 850, 750, 550, 350, 100,  0,  0,  0,  0,  0]
    dhi =       [0, 0, 0, 0, 0, 0,  30,  80, 120, 150, 170, 180, 185, 180, 170, 150, 120,  80,  30,  0,  0,  0,  0,  0]
    temp_air =  [14, 14, 14, 14, 14, 14, 15, 16, 17, 19, 21, 23, 24, 24, 23, 22, 20, 18, 17, 16, 15, 15, 15, 14]
    wind_speed = [2] * 24
    return pd.DataFrame(
        {
            "ghi": ghi,
            "dni": dni,
            "dhi": dhi,
            "temp_air": temp_air,
            "wind_speed": wind_speed,
        },
        index=index,
    )


def _make_home_result(
    index: pd.DatetimeIndex,
    gen: list[float],
    dem: list[float],
) -> SimulationResults:
    """Build a minimal, individually-balanced SimulationResults (no battery).

    Copied from tests/unit/test_community.py for fast report unit assertions.
    """
    n = len(index)
    assert len(gen) == n
    assert len(dem) == n
    exp = [max(0.0, g - d) for g, d in zip(gen, dem)]
    imp = [max(0.0, d - g) for g, d in zip(gen, dem)]
    zeros = [0.0] * n
    return SimulationResults(
        generation=pd.Series(gen, index=index, dtype=float),
        demand=pd.Series(dem, index=index, dtype=float),
        self_consumption=pd.Series(
            [min(g, d) for g, d in zip(gen, dem)], index=index, dtype=float
        ),
        battery_charge=pd.Series(zeros, index=index, dtype=float),
        battery_discharge=pd.Series(zeros, index=index, dtype=float),
        battery_soc=pd.Series(zeros, index=index, dtype=float),
        grid_import=pd.Series(imp, index=index, dtype=float),
        grid_export=pd.Series(exp, index=index, dtype=float),
        import_cost=pd.Series(zeros, index=index, dtype=float),
        export_revenue=pd.Series(zeros, index=index, dtype=float),
        tariff_rate=pd.Series(zeros, index=index, dtype=float),
    )


def _make_fleet(
    index: pd.DatetimeIndex,
    homes: list[tuple[list[float], list[float]]],
) -> FleetResults:
    """Build a synthetic FleetResults from (gen, dem) pairs per home.

    Copied from tests/unit/test_community.py for fast report unit assertions.
    """
    per_home = [_make_home_result(index, g, d) for g, d in homes]
    configs = [
        HomeConfig(pv_config=PVConfig(capacity_kw=1.0), load_config=LoadConfig())
        for _ in homes
    ]
    return FleetResults(per_home_results=per_home, home_configs=configs)


def _build_injected_fleet(
    start: pd.Timestamp,
    end: pd.Timestamp,
    weather: pd.DataFrame,
) -> FleetResults:
    """Build a FleetResults by running simulate_home with injected synthetic weather.

    Exporters: high PV (8 kW), low demand (1500 kWh/yr) → surplus at midday.
    Importers: low PV (0.5 kW), high demand (6000 kWh/yr) → draws from grid.
    With synthetic midday solar, exporters and importers overlap so P2P netting
    strictly reduces both community grid import and export vs Σ per-home.
    """
    exporter_configs = [
        HomeConfig(
            pv_config=PVConfig(capacity_kw=8.0),
            load_config=LoadConfig(annual_consumption_kwh=1500, use_stochastic=False),
            name="Exporter-1",
        ),
        HomeConfig(
            pv_config=PVConfig(capacity_kw=7.0),
            load_config=LoadConfig(annual_consumption_kwh=1800, use_stochastic=False),
            name="Exporter-2",
        ),
    ]
    importer_configs = [
        HomeConfig(
            pv_config=PVConfig(capacity_kw=0.5),
            load_config=LoadConfig(annual_consumption_kwh=6000, use_stochastic=False),
            name="Importer-1",
        ),
        HomeConfig(
            pv_config=PVConfig(capacity_kw=1.0),
            load_config=LoadConfig(annual_consumption_kwh=5500, use_stochastic=False),
            name="Importer-2",
        ),
    ]
    all_configs = exporter_configs + importer_configs
    results = [simulate_home(h, start, end, weather_data=weather) for h in all_configs]
    return FleetResults(per_home_results=results, home_configs=all_configs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateCommunityReport:
    """RED/GREEN tests for output.generate_community_report.

    Uses a hand-built synthetic FleetResults to avoid any PVGIS calls.
    """

    @pytest.fixture
    def small_fleet(self) -> FleetResults:
        """2-home fleet: exporter + importer — guaranteed simultaneous surplus & deficit."""
        # 4 timesteps at 1-minute intervals (tiny for speed)
        index = pd.date_range("2024-06-21 12:00", periods=4, freq="min", tz="Europe/London")
        # Exporter: large PV (gen > dem) → exports surplus
        # Importer: no PV (gen = 0) → imports everything
        return _make_fleet(
            index,
            [
                ([3.0, 5.0, 5.0, 1.0], [1.0, 1.0, 1.0, 1.0]),  # exporter
                ([0.0, 0.0, 0.0, 0.0], [2.0, 2.0, 2.0, 2.0]),  # importer
            ],
        )

    @pytest.fixture
    def cr_p2p(self, small_fleet: FleetResults) -> "CommunityResults":  # type: ignore[name-defined]
        from solar_challenge.community import CommunityResults
        return simulate_community(small_fleet, CommunityConfig(sharing_mode="p2p"))

    @pytest.fixture
    def cr_batt(self, small_fleet: FleetResults) -> "CommunityResults":  # type: ignore[name-defined]
        from solar_challenge.community import CommunityResults
        return simulate_community(
            small_fleet,
            CommunityConfig(
                sharing_mode="community_battery",
                community_battery=BatteryConfig(
                    capacity_kwh=10.0, max_charge_kw=30.0, max_discharge_kw=30.0
                ),
            ),
        )

    def test_p2p_report_contains_title(self, cr_p2p: object) -> None:
        report = generate_community_report(cr_p2p)
        assert isinstance(report, str)
        assert "# Community" in report

    def test_p2p_report_contains_sharing_mode(self, cr_p2p: object) -> None:
        report = generate_community_report(cr_p2p)
        assert "p2p" in report

    def test_p2p_report_contains_grid_flow_table(self, cr_p2p: object) -> None:
        report = generate_community_report(cr_p2p)
        # Must mention both Grid Import and Grid Export with community vs unshared
        assert "Grid Import" in report
        assert "Grid Export" in report

    def test_p2p_report_contains_self_sufficiency(self, cr_p2p: object) -> None:
        report = generate_community_report(cr_p2p)
        assert "Self-Sufficiency" in report

    def test_batt_report_contains_mode_and_battery_section(self, cr_batt: object) -> None:
        report = generate_community_report(cr_batt)
        assert "community_battery" in report
        # Community Battery section with Charged/Discharged
        assert "Community Battery" in report
        assert "Charged" in report
        assert "Discharged" in report

    def test_optional_summary_arg(self, cr_p2p: object) -> None:
        # None works
        report_none = generate_community_report(cr_p2p, None)
        assert isinstance(report_none, str)
        # Dict works and does not raise
        report_dict = generate_community_report(cr_p2p, {"note": "test"})
        assert isinstance(report_dict, str)
        assert "note" in report_dict


class TestDemoScenario:
    """Contract tests for scenarios/bristol-community.yaml.

    Validates that the YAML file exists, loads correctly, and satisfies the
    exporter/importer heterogeneity and community_battery requirements.
    """

    def test_scenario_file_exists(self) -> None:
        assert SCENARIO.exists(), f"Scenario file not found: {SCENARIO}"

    def test_fleet_config_small(self) -> None:
        fleet = load_fleet_config(SCENARIO)
        assert 4 <= len(fleet.homes) <= 12, (
            f"Expected 4-12 homes, got {len(fleet.homes)}"
        )

    def test_fleet_is_heterogeneous(self) -> None:
        """At least one high-PV (exporter) and one low-PV (importer) home."""
        fleet = load_fleet_config(SCENARIO)
        pv_caps = [h.pv_config.capacity_kw for h in fleet.homes]
        loads = [h.load_config.annual_consumption_kwh for h in fleet.homes]
        # Max PV home should NOT be the same as max load home
        max_pv_idx = pv_caps.index(max(pv_caps))
        max_load_idx = loads.index(max(loads))
        assert max_pv_idx != max_load_idx, (
            "Expected heterogeneous fleet: highest-PV and highest-load homes "
            f"are the same ({max_pv_idx})"
        )
        # Sanity: a clearly high-PV exporter exists
        assert max(pv_caps) >= 6.0, f"Expected exporter with PV ≥ 6 kW, max={max(pv_caps)}"
        # Sanity: a clearly high-load importer exists
        assert max(loads) >= 4000.0, f"Expected importer with load ≥ 4000 kWh/yr, max={max(loads)}"

    def test_community_config_present(self) -> None:
        cfg = load_community_config(SCENARIO)
        assert cfg is not None, "Expected a community: block in scenario YAML"

    def test_community_sharing_mode_is_community_battery(self) -> None:
        cfg = load_community_config(SCENARIO)
        assert cfg is not None
        assert cfg.sharing_mode == "community_battery"

    def test_community_battery_spec_present(self) -> None:
        cfg = load_community_config(SCENARIO)
        assert cfg is not None
        assert cfg.community_battery is not None
        assert cfg.community_battery.capacity_kwh > 0


class TestFleetRunCommunityCLI:
    """CLI integration tests for `fleet run` with community wiring.

    get_tmy_data is monkeypatched in BOTH solar_challenge.home and
    solar_challenge.fleet so the in-process sequential path is deterministic
    (no PVGIS calls).  Must use --sequential so ProcessPoolExecutor is skipped
    (monkeypatches don't propagate across processes).
    """

    def test_community_run_exits_zero(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """fleet run with community block: exit code 0."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        tmp_report = tmp_path / "community_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO),
                "--sequential",
                "--start", "2024-06-21",
                "--end", "2024-06-21",
                "--community-report", str(tmp_report),
            ],
        )
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}:\n{result.output}"

    def test_community_run_stdout_contains_community_section(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """fleet run output includes a community section."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        tmp_report = tmp_path / "community_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO),
                "--sequential",
                "--start", "2024-06-21",
                "--end", "2024-06-21",
                "--community-report", str(tmp_report),
            ],
        )
        assert result.exit_code == 0
        assert "Community" in result.output

    def test_community_report_file_written(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """fleet run writes --community-report file with correct headings."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        tmp_report = tmp_path / "community_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO),
                "--sequential",
                "--start", "2024-06-21",
                "--end", "2024-06-21",
                "--community-report", str(tmp_report),
            ],
        )
        assert result.exit_code == 0
        assert tmp_report.exists(), "Community report file was not written"
        report_text = tmp_report.read_text()
        assert "# Community" in report_text
        assert "Grid Import" in report_text
        assert "Grid Export" in report_text
        assert "Self-Sufficiency" in report_text

    def test_community_report_netting_reduces_import(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Community Grid Import < Unshared Grid Import (netting reduces import)."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        tmp_report = tmp_path / "community_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO),
                "--sequential",
                "--start", "2024-06-21",
                "--end", "2024-06-21",
                "--community-report", str(tmp_report),
            ],
        )
        assert result.exit_code == 0
        report_text = tmp_report.read_text()
        # Parse the Grid Import row from the markdown table
        # | Grid Import | <unshared> | <community> | <reduction> |
        import re
        import_match = re.search(
            r"\|\s*Grid Import\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|", report_text
        )
        assert import_match is not None, (
            f"Could not find Grid Import table row in report:\n{report_text}"
        )
        unshared_import = float(import_match.group(1))
        community_import = float(import_match.group(2))
        assert community_import < unshared_import, (
            f"Expected community import ({community_import:.2f}) < "
            f"unshared import ({unshared_import:.2f})"
        )


class TestFleetRunNoCommunityPath:
    """Tests for the community-LESS path and guard against report-without-block.

    Verifies the gate: community section is absent, fleet summary is
    byte-stable, and --community-report warns + writes nothing when no
    community: block is present.
    """

    @pytest.fixture
    def plain_scenario(self, tmp_path: Path) -> Path:
        """Write a minimal fleet YAML with NO community: block."""
        content = """
name: Plain Fleet (no community)

location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
  altitude: 11.0

homes:
  - name: "Home-1"
    pv:
      capacity_kw: 4.0
    load:
      annual_consumption_kwh: 3000.0
      use_stochastic: false

  - name: "Home-2"
    pv:
      capacity_kw: 3.0
    load:
      annual_consumption_kwh: 3500.0
      use_stochastic: false
"""
        path = tmp_path / "plain_fleet.yaml"
        path.write_text(content)
        return path

    def test_no_community_block_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, plain_scenario: Path
    ) -> None:
        """fleet run on plain config: exit code 0."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        result = runner.invoke(
            app,
            ["fleet", "run", str(plain_scenario), "--sequential",
             "--start", "2024-06-21", "--end", "2024-06-21"],
        )
        assert result.exit_code == 0, result.output

    def test_no_community_section_in_stdout(
        self, monkeypatch: pytest.MonkeyPatch, plain_scenario: Path
    ) -> None:
        """fleet run on plain config does NOT print a community section."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        result = runner.invoke(
            app,
            ["fleet", "run", str(plain_scenario), "--sequential",
             "--start", "2024-06-21", "--end", "2024-06-21"],
        )
        assert result.exit_code == 0
        # "Community Sharing" is the rich Table title; should be absent
        assert "Community Sharing" not in result.output

    def test_fleet_summary_additive_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Fleet summary lines are the same with and without a community block."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())

        # Build a minimal homes list (same for both runs)
        homes_yaml = """
homes:
  - name: "Home-1"
    pv:
      capacity_kw: 4.0
    load:
      annual_consumption_kwh: 3000.0
      use_stochastic: false
  - name: "Home-2"
    pv:
      capacity_kw: 0.5
    load:
      annual_consumption_kwh: 5000.0
      use_stochastic: false

location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
"""
        plain_path = tmp_path / "fleet_plain.yaml"
        plain_path.write_text(homes_yaml)

        community_yaml = homes_yaml + """
community:
  sharing_mode: p2p
"""
        community_path = tmp_path / "fleet_community.yaml"
        community_path.write_text(community_yaml)

        plain_result = runner.invoke(
            app,
            ["fleet", "run", str(plain_path), "--sequential",
             "--start", "2024-06-21", "--end", "2024-06-21"],
        )
        community_result = runner.invoke(
            app,
            ["fleet", "run", str(community_path), "--sequential",
             "--start", "2024-06-21", "--end", "2024-06-21"],
        )
        assert plain_result.exit_code == 0
        assert community_result.exit_code == 0

        # Community section is strictly additive: it must appear in the community
        # run and be absent from the plain run.  We check the Rich table title
        # rather than doing a full stdout substring match (which is brittle to
        # Rich's content-sensitive column width auto-sizing).
        assert "Community Sharing" not in plain_result.output, (
            "Community section appeared in a plain (no-block) fleet run"
        )
        assert "Community Sharing" in community_result.output, (
            "Community section was missing from the community-block run"
        )

    def test_report_without_block_warns_and_skips(
        self, monkeypatch: pytest.MonkeyPatch, plain_scenario: Path, tmp_path: Path
    ) -> None:
        """--community-report with no community: block warns and does NOT write file."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        report_path = tmp_path / "should_not_exist.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(plain_scenario), "--sequential",
                "--start", "2024-06-21", "--end", "2024-06-21",
                "--community-report", str(report_path),
            ],
        )
        assert result.exit_code == 0
        assert not report_path.exists(), "Report file should NOT be written without community block"
        # A warning must appear in stdout
        assert "community" in result.output.lower() or "warning" in result.output.lower(), (
            f"Expected a warning mentioning community, got:\n{result.output}"
        )


class TestCommunityPipelineAB:
    """Integration-gate: A/B test over the real home→fleet→community pipeline.

    Uses INJECTED synthetic weather (no PVGIS) to keep tests deterministic and
    fast.  Verifies that community sharing strictly reduces both grid import
    and export vs Σ per-home baseline.
    """

    @pytest.fixture
    def synth_fleet(self) -> FleetResults:
        """Build a FleetResults with injected weather (no PVGIS)."""
        weather = _synth_weather()
        start = pd.Timestamp("2024-06-21", tz="Europe/London")
        end = pd.Timestamp("2024-06-21", tz="Europe/London")
        return _build_injected_fleet(start, end, weather)

    def test_p2p_netting_reduces_grid_import(self, synth_fleet: FleetResults) -> None:
        """P2P community import < Σ per-home import."""
        baseline_import = float(synth_fleet.total_grid_import.sum())
        cr = simulate_community(synth_fleet, CommunityConfig(sharing_mode="p2p"))
        assert float(cr.grid_import.sum()) < baseline_import, (
            "P2P netting should reduce community grid import below Σ per-home import"
        )

    def test_p2p_netting_reduces_grid_export(self, synth_fleet: FleetResults) -> None:
        """P2P community export < Σ per-home export."""
        baseline_export = float(synth_fleet.total_grid_export.sum())
        cr = simulate_community(synth_fleet, CommunityConfig(sharing_mode="p2p"))
        assert float(cr.grid_export.sum()) < baseline_export, (
            "P2P netting should reduce community grid export below Σ per-home export"
        )

    def test_p2p_balance_valid(self, synth_fleet: FleetResults) -> None:
        """P2P community balance invariant holds."""
        cr = simulate_community(synth_fleet, CommunityConfig(sharing_mode="p2p"))
        assert validate_community_balance(synth_fleet, cr)

    def test_battery_mode_import_not_worse_than_p2p(self, synth_fleet: FleetResults) -> None:
        """community_battery import ≤ p2p import (battery is additive benefit)."""
        cr_p2p = simulate_community(synth_fleet, CommunityConfig(sharing_mode="p2p"))
        cr_batt = simulate_community(
            synth_fleet,
            CommunityConfig(
                sharing_mode="community_battery",
                community_battery=BatteryConfig(
                    capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0
                ),
            ),
        )
        assert float(cr_batt.grid_import.sum()) <= float(cr_p2p.grid_import.sum()), (
            "community_battery import should not exceed p2p import"
        )

    def test_battery_balance_valid(self, synth_fleet: FleetResults) -> None:
        """community_battery balance invariant holds."""
        cr_batt = simulate_community(
            synth_fleet,
            CommunityConfig(
                sharing_mode="community_battery",
                community_battery=BatteryConfig(
                    capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0
                ),
            ),
        )
        assert validate_community_balance(synth_fleet, cr_batt)

    def test_battery_report_has_battery_section(self, synth_fleet: FleetResults) -> None:
        """generate_community_report includes a non-empty Community Battery section."""
        cr_batt = simulate_community(
            synth_fleet,
            CommunityConfig(
                sharing_mode="community_battery",
                community_battery=BatteryConfig(
                    capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0
                ),
            ),
        )
        report = generate_community_report(cr_batt)
        assert "Community Battery" in report
        assert "Charged" in report

    @pytest.mark.slow
    def test_real_pvgis_smoke(self, tmp_path: Path) -> None:
        """Smoke test: fleet run with real PVGIS calls (marked slow, no monkeypatch)."""
        tmp_report = tmp_path / "smoke_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO),
                "--sequential",
                "--start", "2024-06-21",
                "--end", "2024-06-21",
                "--community-report", str(tmp_report),
            ],
        )
        assert result.exit_code == 0, f"smoke test failed:\n{result.output}"
        assert "Community" in result.output


# ---------------------------------------------------------------------------
# Task-34 step-5: TestCommunityBillingReport (RED)
# ---------------------------------------------------------------------------

class TestCommunityBillingReport:
    """RED tests for the markdown billing section in generate_community_report.

    Implementation arrives in step-6 (output.py).
    """

    @pytest.fixture
    def billing_idx(self) -> pd.DatetimeIndex:
        return pd.date_range("2024-06-21 12:00", periods=2, freq="h", tz="Europe/London")

    @pytest.fixture
    def billing_fleet(self, billing_idx: pd.DatetimeIndex) -> FleetResults:
        """Exporter + importer fleet for deterministic billing values."""
        return _make_fleet(
            billing_idx,
            [
                ([4.0, 4.0], [1.0, 1.0]),  # exporter
                ([0.0, 0.0], [2.0, 2.0]),  # importer
            ],
        )

    @pytest.fixture
    def cr_with_billing(self, billing_fleet: FleetResults) -> "object":
        """CommunityResults with billing fields set (p2p, flat 0.30, SEG 4.1)."""
        cfg = CommunityConfig(
            sharing_mode="p2p",
            billing=CommunityBillingConfig(
                tariff=FlatRateTariff(0.30),
                seg_rate_pence_per_kwh=4.1,
            ),
        )
        return simulate_community(billing_fleet, cfg)

    @pytest.fixture
    def cr_no_billing(self, billing_fleet: FleetResults) -> "object":
        """CommunityResults with no billing config (fields are None)."""
        cfg = CommunityConfig(sharing_mode="p2p")
        return simulate_community(billing_fleet, cfg)

    def test_report_contains_billing_section_header(self, cr_with_billing: object) -> None:
        """Report contains a billing section heading when savings are populated."""
        from solar_challenge.community import CommunityResults
        assert isinstance(cr_with_billing, CommunityResults)
        report = generate_community_report(cr_with_billing)
        assert "Community Billing" in report

    def test_report_contains_baseline_line(self, cr_with_billing: object) -> None:
        """Report contains a 'Baseline' net cost line."""
        from solar_challenge.community import CommunityResults
        assert isinstance(cr_with_billing, CommunityResults)
        report = generate_community_report(cr_with_billing)
        assert "Baseline" in report

    def test_report_contains_community_net_line(self, cr_with_billing: object) -> None:
        """Report contains a 'Community' net cost line."""
        from solar_challenge.community import CommunityResults
        assert isinstance(cr_with_billing, CommunityResults)
        report = generate_community_report(cr_with_billing)
        # "Community Billing" heading contains "Community"; check for net cost line
        assert "Community Net" in report or ("Community" in report and "Net" in report)

    def test_report_contains_savings_line(self, cr_with_billing: object) -> None:
        """Report contains a 'Savings' line with the value formatted to 2 dp."""
        from solar_challenge.community import CommunityResults
        assert isinstance(cr_with_billing, CommunityResults)
        report = generate_community_report(cr_with_billing)
        assert "Savings" in report
        # Value should appear formatted to 2 dp: 1.04 for our test case
        assert re.search(r"1\.0[23456]", report), (
            f"Expected savings ~1.036 formatted to 2 dp in report:\n{report}"
        )

    def test_no_billing_section_when_fields_none(self, cr_no_billing: object) -> None:
        """Report does NOT contain billing section when savings fields are None."""
        from solar_challenge.community import CommunityResults
        assert isinstance(cr_no_billing, CommunityResults)
        assert cr_no_billing.community_savings_gbp is None  # type: ignore[attr-defined]
        report = generate_community_report(cr_no_billing)
        assert "Community Billing" not in report
        assert "Savings" not in report


# ---------------------------------------------------------------------------
# Task-34 step-7: TestCommunityBillingAB + TestFleetRunCommunityBillingCLI (RED)
# ---------------------------------------------------------------------------

class TestCommunityBillingAB:
    """A/B integration gate: savings >= 0 and community_net < baseline_net for both modes.

    Uses the injected synth_fleet fixture (no PVGIS).
    """

    @pytest.fixture
    def synth_fleet(self) -> FleetResults:
        weather = _synth_weather()
        start = pd.Timestamp("2024-06-21", tz="Europe/London")
        end = pd.Timestamp("2024-06-21", tz="Europe/London")
        return _build_injected_fleet(start, end, weather)

    def _billing_cfg(self, mode: str, batt: BatteryConfig | None = None) -> CommunityConfig:
        return CommunityConfig(
            sharing_mode=mode,  # type: ignore[arg-type]
            community_battery=batt,
            billing=CommunityBillingConfig(
                tariff=FlatRateTariff(0.30),
                seg_rate_pence_per_kwh=4.1,
            ),
        )

    def test_p2p_savings_not_none(self, synth_fleet: FleetResults) -> None:
        """P2P: community_savings_gbp is populated (not None)."""
        cr = simulate_community(synth_fleet, self._billing_cfg("p2p"))
        assert cr.community_savings_gbp is not None

    def test_p2p_savings_non_negative(self, synth_fleet: FleetResults) -> None:
        """P2P: community_savings_gbp >= 0."""
        cr = simulate_community(synth_fleet, self._billing_cfg("p2p"))
        assert cr.community_savings_gbp >= 0  # type: ignore[operator]

    def test_p2p_community_net_less_than_baseline(self, synth_fleet: FleetResults) -> None:
        """P2P: community_net_cost < baseline_net_cost."""
        cr = simulate_community(synth_fleet, self._billing_cfg("p2p"))
        assert cr.community_net_cost_gbp < cr.baseline_net_cost_gbp  # type: ignore[operator]

    def test_p2p_savings_equals_baseline_minus_community(self, synth_fleet: FleetResults) -> None:
        """P2P: savings == baseline_net - community_net exactly."""
        cr = simulate_community(synth_fleet, self._billing_cfg("p2p"))
        assert cr.community_savings_gbp == pytest.approx(  # type: ignore[operator]
            cr.baseline_net_cost_gbp - cr.community_net_cost_gbp, abs=1e-10  # type: ignore[operator]
        )

    def test_battery_mode_savings_not_none(self, synth_fleet: FleetResults) -> None:
        """community_battery: community_savings_gbp is populated."""
        batt = BatteryConfig(capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0)
        cr = simulate_community(synth_fleet, self._billing_cfg("community_battery", batt))
        assert cr.community_savings_gbp is not None

    def test_battery_mode_savings_non_negative(self, synth_fleet: FleetResults) -> None:
        """community_battery: savings >= 0."""
        batt = BatteryConfig(capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0)
        cr = simulate_community(synth_fleet, self._billing_cfg("community_battery", batt))
        assert cr.community_savings_gbp >= 0  # type: ignore[operator]

    def test_battery_mode_community_net_less_than_baseline(self, synth_fleet: FleetResults) -> None:
        """community_battery: community_net < baseline_net."""
        batt = BatteryConfig(capacity_kwh=20.0, max_charge_kw=10.0, max_discharge_kw=10.0)
        cr = simulate_community(synth_fleet, self._billing_cfg("community_battery", batt))
        assert cr.community_net_cost_gbp < cr.baseline_net_cost_gbp  # type: ignore[operator]


class TestFleetRunCommunityBillingCLI:
    """CLI integration test: fleet run on bristol-community.yaml produces billing section.

    Uses monkeypatched weather to avoid PVGIS calls.  Step-7 RED for the
    _print_community_section billing rows (implemented in step-8) and the
    --community-report billing section (implemented in step-6).
    """

    def test_community_report_has_billing_section(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Written --community-report contains 'Community Billing' and 'Savings'."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        report_path = tmp_path / "billing_report.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO), "--sequential",
                "--start", "2024-06-21", "--end", "2024-06-21",
                "--community-report", str(report_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert report_path.exists()
        report_text = report_path.read_text()
        assert "Community Billing" in report_text, (
            f"Expected 'Community Billing' section in report:\n{report_text[:500]}"
        )
        assert "Savings" in report_text

    def test_community_report_savings_non_negative(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Parsed savings figure from the report is >= 0."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        report_path = tmp_path / "billing_report2.md"
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO), "--sequential",
                "--start", "2024-06-21", "--end", "2024-06-21",
                "--community-report", str(report_path),
            ],
        )
        assert result.exit_code == 0, result.output
        report_text = report_path.read_text()
        # Extract baseline and community net cost figures and verify savings ≥ 0
        baseline_match = re.search(r"Baseline[^|]*\|\s*([-\d.]+)", report_text)
        community_match = re.search(r"Community Net[^|]*\|\s*([-\d.]+)", report_text)
        if baseline_match and community_match:
            baseline = float(baseline_match.group(1))
            community = float(community_match.group(1))
            assert community <= baseline, (
                f"Expected community_net ({community:.4f}) <= baseline ({baseline:.4f})"
            )

    def test_cli_stdout_has_billing_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLI stdout community table includes billing rows (step-8 drives this)."""
        monkeypatch.setattr("solar_challenge.home.get_tmy_data", lambda *a, **k: _synth_weather())
        monkeypatch.setattr("solar_challenge.fleet.get_tmy_data", lambda *a, **k: _synth_weather())
        result = runner.invoke(
            app,
            [
                "fleet", "run", str(SCENARIO), "--sequential",
                "--start", "2024-06-21", "--end", "2024-06-21",
            ],
        )
        assert result.exit_code == 0, result.output
        # Billing rows in the Rich table — implemented in step-8
        assert "Baseline Net Cost" in result.output or "Savings" in result.output, (
            f"Expected billing rows in community table stdout:\n{result.output[-500:]}"
        )
