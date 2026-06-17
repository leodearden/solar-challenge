# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: W2 seam gate — grid-services band fills board scenario finance (task/55 δ).

Tests the cross-task seam: board scenario YAML → _parse_finance_config →
project_multi_year → project_economics.mean_fleet_surplus_per_year_gbp.

Step-1 (RED) → Step-2 (GREEN): field-fill assertion on the YAML literal.
Steps 3–6 (GREEN on arrival): seam-verification that the consuming math
(W2-CR2, project_multi_year._simulate_age) propagates the band value into project surplus.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


# ---------------------------------------------------------------------------
# Step-1 RED / Step-2 GREEN: field-fill assertion
# ---------------------------------------------------------------------------


def test_board_scenario_grid_services_filled_from_central_band() -> None:
    """Board scenario finance.grid_services_income_per_kw_per_year_gbp must equal
    resolve_grid_services_band("central") == £12.0/kW.

    RED on base: YAML field is currently 0.0 != 12.0.
    GREEN after step-2 YAML edit (12.0 written directly with provenance comment).

    Also asserts the scenario's flex_band key lowers to "central" to document
    provenance: the value derives from this band.
    """
    from solar_challenge.config import _parse_finance_config, load_config  # type: ignore[attr-defined]
    from solar_challenge.flex import resolve_grid_services_band

    cfg = load_config(SCENARIO)

    # Provenance: the YAML's flex_band must be "central"
    assert cfg["flex_band"].lower() == "central"

    # The finance field must match the resolved central band value (no magic numbers)
    finance = _parse_finance_config(cfg.get("finance"))
    assert finance is not None
    assert finance.grid_services_income_per_kw_per_year_gbp == pytest.approx(
        resolve_grid_services_band("central")
    ), (
        f"Expected grid_services_income_per_kw_per_year_gbp == "
        f"resolve_grid_services_band('central') == {resolve_grid_services_band('central')}, "
        f"got {finance.grid_services_income_per_kw_per_year_gbp}"
    )


# ---------------------------------------------------------------------------
# Shared helpers for steps 3–6 seam-verification
# ---------------------------------------------------------------------------


def _make_synthetic_sim_results(n_steps: int = 8760) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a single deterministic, age-independent SimulationResults.

    Uses hourly resolution (n_steps=8760) — energy = sum*(1/60) still correct.
    All arrays are constant scalars; no PVGIS, no stochastic load.
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = 2000.0 / (n_steps / 60.0)
    exp_kw = 800.0 / (n_steps / 60.0)
    imp_kw = 1400.0 / (n_steps / 60.0)
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


def _synthetic_fleet_results(homes: list) -> "FleetResults":  # type: ignore[name-defined]
    """Build a deterministic FleetResults with one SimulationResults per home."""
    from solar_challenge.fleet import FleetResults

    per_home = [_make_synthetic_sim_results() for _ in homes]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _constant_simulate(fr: "FleetResults") -> "Callable":  # type: ignore[name-defined]
    """Return a constant simulate function: (fc, s, e) -> fr (age-independent)."""
    return lambda fc, s, e: fr


def _board_econ_scenario() -> tuple:  # type: ignore[return]
    """Build (scenario, finance_loaded) from the board YAML.

    Mirrors the canonical consumer path in cli/finance.py:
      load_config → _parse_finance_config → load_fleet_config → ScenarioConfig
    """
    from solar_challenge.config import (  # type: ignore[attr-defined]
        ScenarioConfig,
        SimulationPeriod,
        _parse_finance_config,
        load_config,
        load_fleet_config,
    )

    cfg = load_config(SCENARIO)
    finance = _parse_finance_config(cfg.get("finance"))
    fleet = load_fleet_config(SCENARIO)
    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    scenario = ScenarioConfig(
        name="Board-GridServices-Test",
        period=period,
        homes=list(fleet.homes),
    )
    return scenario, finance


def _surplus_at(
    scenario: "ScenarioConfig",  # type: ignore[name-defined]
    finance: "FinanceConfig",  # type: ignore[name-defined]
    simulate: "Callable",  # type: ignore[name-defined]
) -> float:
    """Return mean_fleet_surplus_per_year_gbp from project_economics."""
    from solar_challenge.finance import project_economics, project_multi_year

    curve = project_multi_year(scenario, finance, simulate=simulate)
    return project_economics(curve, scenario, finance).mean_fleet_surplus_per_year_gbp


# ---------------------------------------------------------------------------
# Step-3 (GREEN on arrival): board surplus carries the central increment
# ---------------------------------------------------------------------------


def test_loaded_board_surplus_carries_central_increment() -> None:
    """Board-as-shipped surplus minus (same with grid_services=0.0) equals
    resolve_grid_services_band("central") × Σ max_discharge_kw (== £3000).

    Uses constant simulate (PVGIS-free, age-independent) → exact delta to rel=1e-9.
    The board fleet has 100 homes × 2.5 kW battery → Σ = 250 kW.
    """
    from solar_challenge.flex import resolve_grid_services_band

    scenario, finance_loaded = _board_econ_scenario()
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

    expected_increment = resolve_grid_services_band("central") * sigma  # £3000
    assert surplus_loaded - surplus_zeroed == pytest.approx(
        expected_increment, rel=1e-9
    ), (
        f"Expected surplus increment = £{expected_increment:.2f} "
        f"(central × {sigma} kW); "
        f"got £{surplus_loaded - surplus_zeroed:.6f}"
    )


# ---------------------------------------------------------------------------
# Step-4 (GREEN on arrival): each band moves surplus by its increment
# ---------------------------------------------------------------------------


def test_each_band_moves_project_surplus_by_its_increment() -> None:
    """For each band {low, central, high} the surplus delta equals
    resolve_grid_services_band(band) × Σ max_discharge_kw (rel=1e-9).

    Additionally asserts strict monotonicity: surplus(low) < surplus(central) < surplus(high).
    """
    from solar_challenge.flex import resolve_grid_services_band

    scenario, finance_base = _board_econ_scenario()
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
        rate = resolve_grid_services_band(band)
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
# Step-5 (GREEN on arrival): unset grid_services is θ-safe no-op
# ---------------------------------------------------------------------------


def test_unset_grid_services_is_theta_safe_noop() -> None:
    """Omitting grid_services_income_per_kw_per_year_gbp (via both the production
    parser default and the FinanceConfig dataclass default) must be bit-identical
    to explicit 0.0 on project surplus.

    Encodes the seam's θ-safe contract: the additive default is a true no-op,
    so existing non-flex economics and the θ calibration are unperturbed.

    Non-tautological: finance_base (from the board YAML) carries 12.0, so the
    two omitted-path configs (finance_omitted, finance_dataclass_default) must
    resolve to 0.0 via their respective defaults — not 12.0 — to pass.  A future
    change that shifts _parse_finance_config's data.get fallback OR
    FinanceConfig's grid_services_income_per_kw_per_year_gbp field default
    away from 0.0 would be caught here.
    """
    from solar_challenge.config import (  # type: ignore[attr-defined]
        FinanceConfig,
        _parse_finance_config,
        load_config,
    )

    scenario, finance_base = _board_econ_scenario()
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

    # Path 1 — production-parser omitted path: pop the key from the finance dict
    # and drive _parse_finance_config's data.get(..., 0.0) fallback.
    cfg = load_config(SCENARIO)
    finance_dict = dict(cfg["finance"])
    finance_dict.pop("grid_services_income_per_kw_per_year_gbp")
    assert "grid_services_income_per_kw_per_year_gbp" not in finance_dict, (
        "Key must be absent so the parser fallback fires"
    )
    finance_omitted = _parse_finance_config(finance_dict)
    assert finance_omitted is not None
    assert finance_omitted.grid_services_income_per_kw_per_year_gbp == 0.0, (
        "_parse_finance_config's data.get fallback must resolve to 0.0 when key is absent"
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
# Step-6 (GREEN on arrival): battery vs no-battery home differ by flex increment
# ---------------------------------------------------------------------------


def test_battery_and_no_battery_home_differ_by_flex_increment() -> None:
    """Hermetic 2-home scenario: one home with battery (2.5 kW), one without.

    With central grid_services: surplus − surplus(0.0) == central × 2.5 == £30.
    Proves only the battery home contributes to Σ max_discharge_kw.
    """
    from solar_challenge.battery import BatteryConfig  # type: ignore[attr-defined]
    from solar_challenge.config import (  # type: ignore[attr-defined]
        ScenarioConfig,
        SimulationPeriod,
    )
    from solar_challenge.flex import resolve_grid_services_band
    from solar_challenge.home import HomeConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.pv import PVConfig

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

    # Finance config: board-like but with controllable grid_services
    from solar_challenge.config import _parse_finance_config, load_config  # type: ignore[attr-defined]
    cfg = load_config(SCENARIO)
    finance_base = _parse_finance_config(cfg.get("finance"))
    assert finance_base is not None

    finance_zero = dataclasses.replace(
        finance_base, grid_services_income_per_kw_per_year_gbp=0.0
    )
    central_rate = resolve_grid_services_band("central")
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
