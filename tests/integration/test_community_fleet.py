"""Integration tests for community energy sharing CLI and pipeline.

Tests the full stack:
  - output.generate_community_report (fast, unit-like)
  - scenarios/bristol-community.yaml contract
  - `fleet run` CLI wiring with community section + report
  - End-to-end pipeline A/B (community on vs off) with injected weather
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.main import app
from solar_challenge.community import (
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
