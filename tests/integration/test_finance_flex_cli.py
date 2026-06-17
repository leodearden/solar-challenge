# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for task-70: --flex-band CLI flag wiring into finance run.

All tests are offline (simulate_fleet is patched) and run without @pytest.mark.slow
so they execute in the offline verify loop.  This file must NOT be added to
tests/unit/test_marker_registration.py's INTEGRATION_FILES allow-list.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# §A — Helper factories (adapted from test_cost_recovery_cli.py)
# ---------------------------------------------------------------------------


def _make_bill_breakdown(total_outlay: float = 367.5) -> "BillBreakdown":  # type: ignore[name-defined]
    """Build a minimal BillBreakdown for fixture use."""
    from solar_challenge.finance import BillBreakdown

    return BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=total_outlay,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=132.5,
        saving_pct=26.5,
        self_consumption_fraction=0.35,
    )


def _make_bill_distribution(
    min_gbp: float = 300.0,
    mean_gbp: float = 367.5,
    median_gbp: float = 367.5,
    max_gbp: float = 420.0,
) -> "BillDistribution":  # type: ignore[name-defined]
    """Build a minimal BillDistribution for fixture use."""
    from solar_challenge.finance import BillDistribution

    rep = _make_bill_breakdown(total_outlay=mean_gbp)
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(min_gbp, mean_gbp, max_gbp),
        per_home_saving_gbp=(0.0, 132.5, 265.0),
        per_home_self_consumption_fraction=(0.3, 0.35, 0.4),
        n_homes=5,
        median_net_bill_gbp=median_gbp,
    )


def _make_home_config() -> "HomeConfig":  # type: ignore[name-defined]
    """Build a minimal HomeConfig for fixture use."""
    from solar_challenge.config import (
        BatteryConfig,
        HomeConfig,
        LoadConfig,
        PVConfig,
    )
    from solar_challenge.location import Location

    return HomeConfig(
        pv=PVConfig(capacity_kw=4.0, azimuth=180, tilt=35),
        battery=BatteryConfig(capacity_kwh=5.0),
        load=LoadConfig(annual_consumption_kwh=3500),
        location=Location.bristol(),
    )


def _make_sim_results(
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    n_minutes: int = 525600,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a minimal SimulationResults series."""
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)
    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _make_fleet_results(n_homes: int = 5) -> "FleetResults":  # type: ignore[name-defined]
    """Build a minimal FleetResults for offline testing."""
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [_make_sim_results() for _ in range(n_homes)]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _write_scenario(
    tmp_path: "Path",  # type: ignore[name-defined]
    *,
    name: str = "Flex CLI Test",
    flex_band: "str | None" = None,
    n_homes: int = 5,
) -> "Path":  # type: ignore[name-defined]
    """Write a minimal fleet scenario YAML to tmp_path.

    When flex_band is not None, the top-level ``flex_band`` key is written so
    the CLI can pick it up as the scenario-level default.
    """
    import yaml

    scenario: dict = {  # type: ignore[type-arg]
        "name": name,
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": 5.0},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": {
            "standing_charge_pence_per_day": 28.0,
        },
    }
    if flex_band is not None:
        scenario["flex_band"] = flex_band

    path = tmp_path / "test_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path


# ---------------------------------------------------------------------------
# §B — Module-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flex_fleet_results() -> "FleetResults":  # type: ignore[name-defined]
    """Module-scoped: build FleetResults once per module."""
    return _make_fleet_results()


# ---------------------------------------------------------------------------
# §C — Help test (step-1 RED driver)
# ---------------------------------------------------------------------------


class TestFinanceFlexCLIHelp:
    """Verify the --flex-band option is advertised in the finance run help."""

    def test_help_lists_flex_band_option(self) -> None:
        """finance run --help must mention --flex-band."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])

        assert result.exit_code == 0, (
            f"Expected exit 0 from --help, got {result.exit_code}.\n{result.output}"
        )
        assert "--flex-band" in result.output, (
            f"--flex-band not found in finance run --help:\n{result.output}"
        )
