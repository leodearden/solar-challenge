# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: W2 seam gate — grid-services band fills board scenario finance (task/55 δ).

Tests the cross-task seam: board scenario YAML → parse_finance_config →
project_multi_year → project_economics.mean_fleet_surplus_per_year_gbp.

Field-fill assertion on the YAML literal, then seam verification that the consuming math
(W2-CR2, project_multi_year._simulate_age) propagates the band value into project surplus.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import (
    ScenarioConfig,
    SimulationPeriod,
    load_config,
    parse_finance_config,
)
from solar_challenge.finance import FinanceConfig, project_economics, project_multi_year
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from tests._finance_builders import make_fleet_results_of
from tests.integration._helpers import board_econ_scenario

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


# ---------------------------------------------------------------------------
# Field-fill assertion
# ---------------------------------------------------------------------------


def test_board_scenario_grid_services_filled_from_central_band() -> None:
    """Board scenario finance.grid_services_income_per_kw_per_year_gbp must equal
    GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year == £12.0/kW.

    The YAML writes 12.0 directly, with a provenance comment.

    Also asserts the scenario's flex_band key lowers to "central" to document
    provenance: the value derives from this band.
    """
    cfg = load_config(SCENARIO)

    # Provenance: the YAML's flex_band must be "central"
    assert cfg["flex_band"].lower() == "central"

    # The finance field must match the resolved central band value (no magic numbers)
    finance = parse_finance_config(cfg.get("finance"))
    assert finance is not None
    central_rate = GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year
    assert finance.grid_services_income_per_kw_per_year_gbp == pytest.approx(central_rate), (
        f"Expected grid_services_income_per_kw_per_year_gbp == "
        f"GRID_SERVICES_RATE_BANDS.resolve('central').flat_gbp_per_kw_per_year == {central_rate}, "
        f"got {finance.grid_services_income_per_kw_per_year_gbp}"
    )


# ---------------------------------------------------------------------------
# Shared helpers for the seam-verification tests
# ---------------------------------------------------------------------------


def _make_synthetic_sim_results(n_steps: int = 8760) -> SimulationResults:
    """Build a single deterministic, age-independent SimulationResults.

    Uses hourly resolution (n_steps=8760): each kW row counts for the hour it
    lasts, so the year totals 2,000 kWh of self-consumption, 800 kWh of export
    and 1,400 kWh of import.
    All arrays are constant scalars; no PVGIS, no stochastic load.
    """
    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = 2000.0 / n_steps
    exp_kw = 800.0 / n_steps
    imp_kw = 1400.0 / n_steps
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


def _synthetic_fleet_results(homes: list) -> FleetResults:
    """Build a deterministic FleetResults with one SimulationResults per home."""
    per_home = [_make_synthetic_sim_results() for _ in homes]
    return make_fleet_results_of(per_home, homes=homes)


def _constant_simulate(
    fr: FleetResults,
) -> Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]:
    """Return a constant simulate function: (fc, s, e) -> fr (age-independent)."""
    return lambda fc, s, e: fr


def _board_scenario_on_the_flat_model() -> tuple[ScenarioConfig, FinanceConfig]:
    """board_econ_scenario's scenario and finance, the finance pinned to the flat grid-services model.

    The board YAML selects capacity_at_events, and these seam tests check the flat per-kW
    arithmetic.
    """
    scenario, finance = board_econ_scenario()
    return scenario, dataclasses.replace(finance, grid_services_model="flat", grid_services_events=None)


def _surplus_at(
    scenario: ScenarioConfig,
    finance: FinanceConfig,
    simulate: Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults],
) -> float:
    """Return mean_fleet_surplus_per_year_gbp from project_economics."""
    curve = project_multi_year(scenario, finance, simulate=simulate)
    return project_economics(curve, scenario, finance).mean_fleet_surplus_per_year_gbp


# ---------------------------------------------------------------------------
# Board surplus carries the central increment
# ---------------------------------------------------------------------------


def test_loaded_board_surplus_carries_central_increment() -> None:
    """Board-as-shipped surplus minus (same with grid_services=0.0) equals
    GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year × Σ max_discharge_kw (== £3000).

    Uses constant simulate (PVGIS-free, age-independent) → exact delta to rel=1e-9.
    The board fleet has 100 homes × 2.5 kW battery → Σ = 250 kW.
    """
    scenario, finance_loaded = _board_scenario_on_the_flat_model()
    homes = scenario.homes
    fr = _synthetic_fleet_results(homes)
    simulate = _constant_simulate(fr)

    # Σ max_discharge_kw for battery homes
    sigma = sum(
        h.battery_config.max_discharge_kw
        for h in homes
        if h.battery_config is not None
    )
    assert sigma == pytest.approx(250.0), f"Expected Σ=250 kW, got {sigma}"

    # Surplus difference: loaded (12.0) vs zeroed (0.0)
    finance_zeroed = dataclasses.replace(
        finance_loaded,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )
    surplus_loaded = _surplus_at(scenario, finance_loaded, simulate)
    surplus_zeroed = _surplus_at(scenario, finance_zeroed, simulate)

    expected_increment = GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year * sigma  # £3000
    assert surplus_loaded - surplus_zeroed == pytest.approx(
        expected_increment, rel=1e-9
    ), (
        f"Expected surplus increment = £{expected_increment:.2f} "
        f"(central × {sigma} kW); "
        f"got £{surplus_loaded - surplus_zeroed:.6f}"
    )


# ---------------------------------------------------------------------------
# Each band moves surplus by its increment
# ---------------------------------------------------------------------------


def test_each_band_moves_project_surplus_by_its_increment() -> None:
    """For each band {low, central, high} the surplus delta equals
    GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year × Σ max_discharge_kw (rel=1e-9).

    Additionally asserts strict monotonicity: surplus(low) < surplus(central) < surplus(high).
    """
    scenario, finance_base = _board_scenario_on_the_flat_model()
    homes = scenario.homes
    fr = _synthetic_fleet_results(homes)
    simulate = _constant_simulate(fr)

    sigma = sum(
        h.battery_config.max_discharge_kw
        for h in homes
        if h.battery_config is not None
    )

    finance_zero = dataclasses.replace(
        finance_base, grid_services_income_per_kw_per_year_gbp=0.0
    )
    surplus_zero = _surplus_at(scenario, finance_zero, simulate)

    band_surpluses: dict[str, float] = {}
    for band in ("low", "central", "high"):
        rate = GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year
        finance_band = dataclasses.replace(
            finance_base, grid_services_income_per_kw_per_year_gbp=rate
        )
        s = _surplus_at(scenario, finance_band, simulate)
        band_surpluses[band] = s

        expected = rate * sigma
        assert s - surplus_zero == pytest.approx(expected, rel=1e-9), (
            f"Band '{band}': expected surplus increment £{expected:.2f} "
            f"(rate={rate} × σ={sigma}); got £{s - surplus_zero:.6f}"
        )

    # Strict monotonicity
    assert band_surpluses["low"] < band_surpluses["central"] < band_surpluses["high"], (
        f"Expected surplus(low) < surplus(central) < surplus(high); "
        f"got low={band_surpluses['low']:.2f}, "
        f"central={band_surpluses['central']:.2f}, "
        f"high={band_surpluses['high']:.2f}"
    )


# ---------------------------------------------------------------------------
# Unset grid_services is a θ-safe no-op
# ---------------------------------------------------------------------------


def test_unset_grid_services_is_theta_safe_noop() -> None:
    """Omitting grid_services_income_per_kw_per_year_gbp, whether from the finance
    block the production parser reads or from a direct FinanceConfig construction,
    must be bit-identical to explicit 0.0 on project surplus.

    Encodes the seam's θ-safe contract: the additive default is a true no-op,
    so existing non-flex economics and the θ calibration are unperturbed.

    Non-tautological: finance_base (from the board YAML) carries 12.0, so the
    two omitted-path configs (finance_omitted, finance_dataclass_default) must
    resolve to 0.0 — not 12.0 — to pass.  parse_finance_config leaves an omitted
    key to FinanceConfig's declared default, so a future change that shifts
    FinanceConfig's grid_services_income_per_kw_per_year_gbp field default away
    from 0.0, or that has the parser supply its own value for an omitted key,
    would be caught here.
    """
    scenario, finance_base = _board_scenario_on_the_flat_model()
    homes = scenario.homes
    fr = _synthetic_fleet_results(homes)
    simulate = _constant_simulate(fr)

    # Sanity: finance_base (board YAML) carries 12.0, not 0.0 — confirms the
    # omitted paths below are genuinely different from finance_base.
    assert finance_base.grid_services_income_per_kw_per_year_gbp == pytest.approx(12.0)

    # Baseline: explicit 0.0 via dataclasses.replace.
    finance_explicit_zero = dataclasses.replace(
        finance_base, grid_services_income_per_kw_per_year_gbp=0.0
    )
    surplus_explicit = _surplus_at(scenario, finance_explicit_zero, simulate)

    # Path 1 — production-parser omitted path: pop the key from the finance dict,
    # so parse_finance_config leaves it to FinanceConfig's declared default.
    cfg = load_config(SCENARIO)
    finance_dict = dict(cfg["finance"])
    finance_dict.pop("grid_services_income_per_kw_per_year_gbp")
    # Also remove event-model keys so FinanceConfig's declared default, the flat
    # model, applies.
    # No-op before task-76 ε flip (board YAML is flat); preserves the
    # "all grid-services keys unset" intent after the flip.
    finance_dict.pop("grid_services_model", None)
    finance_dict.pop("grid_services_events", None)
    assert "grid_services_income_per_kw_per_year_gbp" not in finance_dict, (
        "Key must be absent so FinanceConfig's declared default applies"
    )
    finance_omitted = parse_finance_config(finance_dict)
    assert finance_omitted is not None
    assert finance_omitted.grid_services_income_per_kw_per_year_gbp == 0.0, (
        "parse_finance_config must leave an absent key to FinanceConfig's default of 0.0"
    )

    # Path 2 — FinanceConfig dataclass default path: reconstruct from finance_base's
    # fields but omit the grid-services key so the FinanceConfig field default fires.
    kwargs = {
        f.name: getattr(finance_base, f.name)
        for f in dataclasses.fields(finance_base)
        if f.name != "grid_services_income_per_kw_per_year_gbp"
    }
    finance_dataclass_default = FinanceConfig(**kwargs)
    assert finance_dataclass_default.grid_services_income_per_kw_per_year_gbp == 0.0, (
        "FinanceConfig field default must be 0.0"
    )

    # Both omitted paths must yield project surplus bit-identical to explicit 0.0.
    surplus_omitted = _surplus_at(scenario, finance_omitted, simulate)
    surplus_dataclass = _surplus_at(scenario, finance_dataclass_default, simulate)

    assert surplus_omitted == surplus_explicit, (
        f"Parser-omitted path must be bit-identical to explicit 0.0; "
        f"omitted={surplus_omitted}, explicit={surplus_explicit}"
    )
    assert surplus_dataclass == surplus_explicit, (
        f"Dataclass-default path must be bit-identical to explicit 0.0; "
        f"dataclass_default={surplus_dataclass}, explicit={surplus_explicit}"
    )


# ---------------------------------------------------------------------------
# Battery vs no-battery home differ by flex increment
# ---------------------------------------------------------------------------


def test_battery_and_no_battery_home_differ_by_flex_increment() -> None:
    """Hermetic 2-home scenario: one home with battery (2.5 kW), one without.

    With central grid_services: surplus − surplus(0.0) == central × 2.5 == £30.
    Proves only the battery home contributes to Σ max_discharge_kw.
    """
    # Build a 2-home scenario: home_a has battery, home_b does not
    pv = PVConfig(capacity_kw=5.0, azimuth=180, tilt=35)
    load = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1)
    batt = BatteryConfig(capacity_kwh=5.0, max_discharge_kw=2.5)

    home_a = HomeConfig(pv_config=pv, load_config=load, battery_config=batt)
    home_b = HomeConfig(pv_config=pv, load_config=load, battery_config=None)
    homes = [home_a, home_b]

    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    scenario = ScenarioConfig(
        name="Hermetic-BattVsNoBatt",
        period=period,
        homes=homes,
    )

    # Synthetic FleetResults: 2 per-home results
    fr = _synthetic_fleet_results(homes)
    simulate = _constant_simulate(fr)

    # Finance config: the board's on the flat model, with controllable grid_services
    _board_scenario, finance_base = _board_scenario_on_the_flat_model()

    finance_zero = dataclasses.replace(
        finance_base, grid_services_income_per_kw_per_year_gbp=0.0
    )
    central_rate = GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year
    finance_central = dataclasses.replace(
        finance_base, grid_services_income_per_kw_per_year_gbp=central_rate
    )

    surplus_zero = _surplus_at(scenario, finance_zero, simulate)
    surplus_central = _surplus_at(scenario, finance_central, simulate)

    # Only home_a (2.5 kW battery) contributes → Σ = 2.5 kW
    expected_increment = central_rate * 2.5  # == £30
    assert surplus_central - surplus_zero == pytest.approx(expected_increment, rel=1e-9), (
        f"Expected surplus increment £{expected_increment:.2f} "
        f"(central={central_rate} × 2.5 kW battery); "
        f"got £{surplus_central - surplus_zero:.6f}"
    )
