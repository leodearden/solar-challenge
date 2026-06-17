# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for W1 γ: board fleet scenario Economy-7 + grid-charging time-shift.

Proves:
(a) Threading sanity: load_fleet_config(flex scenario) yields battery homes with
    Economy-7 tariff (0.09/0.25, 00:30-07:30) + grid_charging + dispatch tou_optimized.
(b) G6 signal: zero-PV winter-day A/B (grid_charging ON vs OFF) → import_cost_gbp(ON) <
    import_cost_gbp(OFF) AND annualised delta ∈ [£100, £330].
(c) Finance report: generate_finance_report gains optional flex_band block; default None
    reproduces bit-identical output.

Marked integration (NOT slow): injected zero-PV weather bypasses PVGIS entirely.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

pytestmark = pytest.mark.integration

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zero_pv_weather(
    day: str = "2024-01-15",
    tz: str = "Europe/London",
) -> pd.DataFrame:
    """Build a 1-day hourly weather DataFrame with zero irradiance.

    All GHI/DNI/DHI are zero → PV generation is zero, so net_cost == import_cost.
    Isolates the import-arbitrage signal: grid-charge ON pre-loads the battery
    overnight at the off-peak rate and discharges into the evening peak.

    Copied from tests/integration/test_grid_charge_arbitrage.py.
    """
    index = pd.date_range(day, periods=24, freq="h", tz=tz)
    return pd.DataFrame(
        {
            "ghi": [0.0] * 24,
            "dni": [0.0] * 24,
            "dhi": [0.0] * 24,
            "temp_air": [8.0] * 24,  # mild winter temperature
            "wind_speed": [2.0] * 24,
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# Step-1: threading sanity (RED until bristol-phase1-flex.yaml exists)
# ---------------------------------------------------------------------------


def test_board_scenario_inherits_tou_tariff_and_grid_charging() -> None:
    """All battery homes in the flex scenario inherit Economy-7 tariff, grid_charging,
    and tou_optimized dispatch_strategy.

    Verifies the β/β′ seam threading (load_fleet_config at config.py:2030):
    scenario-level `tariff:` → every generated home; `fleet_distribution.battery.
    grid_charging:` → every battery home; `fleet_distribution.dispatch_strategy:` →
    every home.
    """
    from solar_challenge.config import load_fleet_config

    fleet = load_fleet_config(SCENARIO)
    battery_homes = [h for h in fleet.homes if h.battery_config is not None]
    assert battery_homes, "Expected at least some homes with a battery in the flex scenario"

    for home in battery_homes:
        # ---- Tariff must be set (scenario-level 'tariff:' key) -----------------
        assert home.tariff_config is not None, (
            f"Home {home.name!r} must inherit Economy-7 tariff from scenario 'tariff:' key"
        )
        # Off-peak rate at 03:00 (inside 00:30–07:30 window)
        off_peak_ts = pd.Timestamp("2024-01-15 03:00:00", tz="Europe/London")
        off_peak_rate = home.tariff_config.get_rate(off_peak_ts)
        assert abs(off_peak_rate - 0.09) < 1e-9, (
            f"Expected off-peak rate 0.09 £/kWh at 03:00, got {off_peak_rate}"
        )
        # Peak rate at 18:00 (outside off-peak window)
        peak_ts = pd.Timestamp("2024-01-15 18:00:00", tz="Europe/London")
        peak_rate = home.tariff_config.get_rate(peak_ts)
        assert abs(peak_rate - 0.25) < 1e-9, (
            f"Expected peak rate 0.25 £/kWh at 18:00, got {peak_rate}"
        )

        # ---- Grid charging must be set with target_soc_fraction 0.9 -----------
        assert home.battery_config is not None  # narrowing for mypy
        assert home.battery_config.grid_charging is not None, (
            f"Home {home.name!r} battery must have grid_charging enabled "
            "(fleet_distribution.battery.grid_charging.target_soc_fraction: 0.9)"
        )
        assert home.battery_config.grid_charging.target_soc_fraction == 0.9, (
            f"Expected target_soc_fraction=0.9, "
            f"got {home.battery_config.grid_charging.target_soc_fraction}"
        )

        # ---- Dispatch strategy must be tou_optimized --------------------------
        assert home.dispatch_strategy == "tou_optimized", (
            f"Home {home.name!r}: expected dispatch_strategy='tou_optimized', "
            f"got {home.dispatch_strategy!r}"
        )


# ---------------------------------------------------------------------------
# Step-3: G6 time-shift signal (RED until scenario + band arithmetic confirmed)
# ---------------------------------------------------------------------------


def test_time_shift_lowers_householder_bill_within_band() -> None:
    """Grid-charging ON lowers import_cost_gbp vs OFF; annualised delta ∈ [£100, £330].

    Uses zero-PV injected winter-day weather (PVGIS-free, deterministic).
    A/B: grid_charging ON (the representative battery home from the flex scenario)
    vs OFF (grid_charging=None via dataclasses.replace).

    Assert:
    - validate_balance=True holds (energy balance closed) in both runs
    - battery charged in ON run, grid imported in ON run
    - import_cost_gbp(ON) < import_cost_gbp(OFF)
    - annualised delta ∈ [£100, £330]  (PRD §9.1 Seam 3 / §11 PASS gate)
    """
    from solar_challenge.config import FinanceConfig, load_config, load_fleet_config
    from solar_challenge.finance import householder_bill
    from solar_challenge.home import calculate_summary, simulate_home

    fleet = load_fleet_config(SCENARIO)

    # Pick the first battery home deterministically
    home_on: Optional[object] = None
    for h in fleet.homes:
        if h.battery_config is not None:
            home_on = h
            break
    assert home_on is not None, "Expected at least one battery home in the flex scenario"

    # Derive OFF variant — same as ON but with grid_charging removed
    off_batt = dataclasses.replace(home_on.battery_config, grid_charging=None)  # type: ignore[union-attr]
    home_off = dataclasses.replace(home_on, battery_config=off_batt)

    start = end = pd.Timestamp("2024-01-15")
    weather = _zero_pv_weather("2024-01-15")

    res_on = simulate_home(home_on, start, end, weather_data=weather, validate_balance=True)  # type: ignore[arg-type]
    res_off = simulate_home(home_off, start, end, weather_data=weather, validate_balance=True)

    # ---- Corroborating assertions (mechanism must fire) -----------------------
    assert res_on.battery_charge.sum() > 0, (
        "Grid-charge ON: expected non-zero battery charging (grid → battery overnight)"
    )
    assert res_on.grid_import.sum() > 0, (
        "Grid-charge ON: expected non-zero grid import (off-peak charging)"
    )

    # ---- Build summaries and parse finance config ----------------------------
    summary_on = calculate_summary(res_on)
    summary_off = calculate_summary(res_off)

    raw = load_config(SCENARIO)
    finance_data = raw.get("finance", {})
    finance = FinanceConfig(
        standing_charge_pence_per_day=finance_data.get("standing_charge_pence_per_day", 60.0),
        own_use_rate_pence_per_kwh=finance_data.get("own_use_rate_pence_per_kwh", 15.0),
        retained_cash_floor_per_home_per_year_gbp=finance_data.get(
            "retained_cash_floor_per_home_per_year_gbp", 27.0
        ),
        grid_services_income_per_kw_per_year_gbp=finance_data.get(
            "grid_services_income_per_kw_per_year_gbp", 0.0
        ),
    )

    # ---- Householder bill A/B (suppress <360-day annualisation warning) ------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        bill_on = householder_bill(
            summary_on, summary_on.total_self_consumption_kwh, finance, simulation_days=1
        )
        bill_off = householder_bill(
            summary_off, summary_off.total_self_consumption_kwh, finance, simulation_days=1
        )

    # ---- G6 gate: import_cost_gbp(ON) < import_cost_gbp(OFF) ----------------
    assert bill_on.import_cost_gbp < bill_off.import_cost_gbp, (
        f"Expected grid_charge ON import_cost ({bill_on.import_cost_gbp:.2f} £) < "
        f"OFF ({bill_off.import_cost_gbp:.2f} £)"
    )

    # ---- G6 gate: annualised delta ∈ [£100, £330] ---------------------------
    delta = bill_off.import_cost_gbp - bill_on.import_cost_gbp
    assert 100.0 <= delta <= 330.0, (
        f"Expected annualised time-shift saving ∈ [£100, £330], got £{delta:.2f}"
    )


# ---------------------------------------------------------------------------
# Step-5: finance report flex block (RED until output.py is extended)
# ---------------------------------------------------------------------------


def test_finance_report_renders_flex_value_block() -> None:
    """generate_finance_report with flex_band appends a Flexibility Value block.

    Additive: default None → output bit-identical (no flex block).
    """
    from solar_challenge.config import FinanceConfig
    from solar_challenge.finance import bill_distribution, householder_bill
    from solar_challenge.flex import resolve_flex_band
    from solar_challenge.home import SummaryStatistics
    from solar_challenge.output import generate_finance_report

    # Build a minimal synthetic summary (mirrors _make_summary in test_finance_bill.py)
    sc_ratio = 2200.0 / 4000.0
    gd_ratio = 1200.0 / 3400.0
    ex_ratio = 1800.0 / 4000.0
    summary = SummaryStatistics(
        total_generation_kwh=4000.0,
        total_demand_kwh=3400.0,
        total_self_consumption_kwh=2200.0,
        total_grid_import_kwh=1200.0,
        total_grid_export_kwh=1800.0,
        total_battery_charge_kwh=0.0,
        total_battery_discharge_kwh=0.0,
        peak_generation_kw=3.5,
        peak_demand_kw=2.0,
        self_consumption_ratio=sc_ratio,
        grid_dependency_ratio=gd_ratio,
        export_ratio=ex_ratio,
        simulation_days=365,
        total_import_cost_gbp=276.0,
        total_export_revenue_gbp=73.8,
        net_cost_gbp=202.2,
        seg_revenue_gbp=73.8,
    )
    finance = FinanceConfig(
        standing_charge_pence_per_day=60.0,
        own_use_rate_pence_per_kwh=15.0,
    )
    dist = bill_distribution([summary], finance, 365)

    # ---- Baseline: no flex_band → bit-identical output -----------------------
    baseline = generate_finance_report(dist, scenario_name="Flex")
    assert "Flexibility Value" not in baseline, (
        "Default (no flex_band) must NOT render the Flexibility Value block"
    )

    # ---- With central flex_band: block must appear with expected figures ------
    central = resolve_flex_band("central")
    report = generate_finance_report(
        dist,
        scenario_name="Flex",
        flex_band=central,
        flex_band_name="central",
    )
    assert "Flexibility Value" in report, (
        "With flex_band=central, '## Flexibility Value' block must appear"
    )
    assert "250" in report, (
        "Central band time_shift_gbp=250 must appear in the report"
    )
    assert "30" in report, (
        "Central band grid_services_per_home_gbp=30 must appear in the report"
    )
    assert "12" in report, (
        "Central band grid_services_per_kw_gbp=12 must appear in the report"
    )
    assert "central" in report.lower(), (
        "'central' band name must appear in the report"
    )

    # ---- Additive: default still returns baseline exactly --------------------
    assert generate_finance_report(dist, scenario_name="Flex") == baseline, (
        "generate_finance_report without flex_band must return bit-identical output"
    )
