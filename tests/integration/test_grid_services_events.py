# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: grid-services-at-events δ — supersede W2 flat term under model flag.

Tests the cross-task seam: capacity_at_events model → project_multi_year →
compute_grid_services_at_events → annual_income_gbp replaces (not adds to)
the flat per-kW term, gated by FinanceConfig.grid_services_model.

Pre-1 (scaffold): shared helpers, no test functions.
Step-1 (RED) → Step-2 (GREEN): B3 supersede takes effect.
Step-3 (RED) → Step-4 (GREEN): Guard — capacity_at_events + events=None → ConfigurationError.
Step-5 (RED) → Step-6 (GREEN): Compute-once / reuse-across-ages (PRD decision 7).
Step-7 (GREEN on arrival): B4 backward-compat / flat bit-identical regression.
Step-8 (GREEN on arrival): B5 solve-still-holds + I4 rate-independence.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


# ---------------------------------------------------------------------------
# Shared helpers (pre-1)
# ---------------------------------------------------------------------------


def _make_in_window_sim_results(n_steps: int = 8760) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a SimulationResults with constant battery_soc above min_soc_kwh and
    battery_discharge below max_discharge_kw, on a full-year hourly tz-aware index.

    With battery_soc=3.0 kWh (above min_soc_kwh=0.5 for a 5kWh×0.1 battery)
    and battery_discharge=0.5 kW (below max_discharge_kw=2.5), DEFAULT_EVENT_WINDOWS
    (winter-weekday-16-18h) selects real in-window steps and
    compute_fleet_spare_capacity_kw yields a positive event figure.
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
        battery_discharge=pd.Series(0.5, index=idx),  # below max_discharge_kw=2.5
        battery_soc=pd.Series(3.0, index=idx),  # above min_soc_kwh=0.5
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _synthetic_fleet_results_in_window(homes: list) -> "FleetResults":  # type: ignore[name-defined]
    """Build FleetResults with in-window battery_soc/discharge per home."""
    from solar_challenge.fleet import FleetResults

    per_home = [_make_in_window_sim_results() for _ in homes]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _constant_simulate(fr: "FleetResults") -> "Callable":  # type: ignore[name-defined]
    """Return a constant simulate function: (fc, s, e) -> fr (age-independent)."""
    return lambda fc, s, e: fr


def _board_econ_scenario() -> tuple:  # type: ignore[return]
    """Build (scenario, finance_loaded) from the board YAML.

    Mirrors test_flex_grid_services._board_econ_scenario verbatim.
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
        name="Board-EventsGridServices-Test",
        period=period,
        homes=list(fleet.homes),
    )
    return scenario, finance


def _rev_at(
    scenario: "ScenarioConfig",  # type: ignore[name-defined]
    finance: "FinanceConfig",  # type: ignore[name-defined]
    simulate: "Callable",  # type: ignore[name-defined]
    year: int = 0,
) -> float:
    """Return fleet_revenue_gbp at a given year from project_multi_year."""
    from solar_challenge.finance import project_multi_year

    curve = project_multi_year(scenario, finance, simulate=simulate)
    return curve.points[year].fleet_revenue_gbp


def _isolate_gs_component(
    scenario: "ScenarioConfig",  # type: ignore[name-defined]
    finance_events: "FinanceConfig",  # type: ignore[name-defined]
    finance_flat0: "FinanceConfig",  # type: ignore[name-defined]
    simulate: "Callable",  # type: ignore[name-defined]
    year: int = 0,
) -> float:
    """Isolate the grid_services component via the flat-rate-0 delta.

    Returns rev(capacity_at_events, year) - rev(flat, rate=0, year).
    Since own_use_revenue, seg_revenue, and cbs_grid_charge are invariant
    across the two models (same simulate, same scenario), the delta equals
    exactly the grid_services contribution.
    """
    return _rev_at(scenario, finance_events, simulate, year) - _rev_at(
        scenario, finance_flat0, simulate, year
    )


# ---------------------------------------------------------------------------
# Step-1 (RED) → Step-2 (GREEN): B3 — supersede takes effect
# ---------------------------------------------------------------------------


def test_b3_supersede_event_derived_figure_replaces_flat() -> None:
    """capacity_at_events model supersedes (replaces) the flat per-kW term.

    Isolated grid_services component from the delta (rev_events - rev_flat0)
    EQUALS compute_grid_services_at_events directly AND differs from the flat term.

    RED on base: _simulate_age always computes the flat term, so the isolated delta
    equals the flat increment (0, since flat rate=0) and the event-derived figure
    is positive — first assertion fails.
    GREEN after step-2: the capacity_at_events branch replaces the flat term.
    """
    from solar_challenge.gridservices import (
        GridServicesEventsConfig,
        compute_grid_services_at_events,
    )

    scenario, finance_base = _board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)
    simulate = _constant_simulate(fr)

    events_cfg = GridServicesEventsConfig(band="central")
    finance_events = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=events_cfg,
        grid_services_income_per_kw_per_year_gbp=0.0,  # irrelevant in events model
    )
    finance_flat0 = dataclasses.replace(
        finance_base,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )

    # Direct event-derived figure (the expected value for the delta)
    expected_gs = compute_grid_services_at_events(fr, events_cfg).annual_income_gbp
    assert expected_gs > 0.0, "Synthetic in-window fleet must yield positive event income"

    # Isolated component via the flat-rate-0 delta
    isolated_gs = _isolate_gs_component(scenario, finance_events, finance_flat0, simulate)

    # I3: isolated == event-derived (supersede, not add)
    assert isolated_gs == pytest.approx(expected_gs, rel=1e-6), (
        f"Isolated gs component ({isolated_gs:.4f}) must equal event-derived figure "
        f"({expected_gs:.4f}). RED if _simulate_age still uses the flat term."
    )

    # Teeth: event figure ≠ flat term for a non-zero flat rate
    flat_rate = finance_base.grid_services_income_per_kw_per_year_gbp
    sigma = sum(
        h.battery_config.max_discharge_kw
        for h in homes
        if h.battery_config is not None
    )
    flat_gs = flat_rate * sigma
    assert isolated_gs != pytest.approx(flat_gs, rel=1e-3), (
        f"Isolated gs ({isolated_gs:.4f}) must differ from flat term "
        f"({flat_gs:.4f}) — confirms the two models produce different values."
    )


# ---------------------------------------------------------------------------
# Step-3 (RED) → Step-4 (GREEN): Guard — None events → ConfigurationError
# ---------------------------------------------------------------------------


def test_guard_capacity_at_events_with_events_none_raises_configuration_error() -> None:
    """capacity_at_events + grid_services_events=None must raise ConfigurationError.

    α permits grid_services_events=None even when model='capacity_at_events'
    (α only validates the selector field; δ is the consumer that must guard this).

    RED after step-2: the transient `assert finance.grid_services_events is not None`
    raises AssertionError — pytest.raises(ConfigurationError) does not match.
    GREEN after step-4: assert replaced with explicit ConfigurationError guard.
    """
    from solar_challenge.config import ConfigurationError  # type: ignore[attr-defined]

    scenario, finance_base = _board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)
    simulate = _constant_simulate(fr)

    finance_none = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=None,
    )

    from solar_challenge.finance import project_multi_year

    with pytest.raises(ConfigurationError):
        project_multi_year(scenario, finance_none, simulate=simulate)


# ---------------------------------------------------------------------------
# Step-5 (RED) → Step-6 (GREEN): Compute-once / reuse-across-ages
# ---------------------------------------------------------------------------


def test_compute_once_event_figure_reused_across_ages(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_grid_services_at_events is called exactly ONCE per project_multi_year run.

    Monkeypatches a counting wrapper on solar_challenge.gridservices.
    compute_grid_services_at_events. The lazy `from solar_challenge.gridservices
    import ...` inside _simulate_age re-resolves the attribute on each call, so the
    patch is observed.

    With asset_life_years=25 → seed_ages=[0,12,24] (3 ages) + bisection trial
    nodes → ≥3 _simulate_age calls without memoization.

    RED after step-4: per-age implementation calls the function for every
    _simulate_age invocation → call count ≥ 3.
    GREEN after step-6: first-call memoization → count == 1.
    """
    import solar_challenge.gridservices as gs_module
    from solar_challenge.gridservices import (
        GridServicesEventsConfig,
        compute_grid_services_at_events as original_fn,
    )

    call_count: dict[str, int] = {"n": 0}

    def counting_wrapper(fleet_results, cfg):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return original_fn(fleet_results, cfg)

    monkeypatch.setattr(gs_module, "compute_grid_services_at_events", counting_wrapper)

    scenario, finance_base = _board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)
    simulate = _constant_simulate(fr)

    events_cfg = GridServicesEventsConfig(band="central")
    finance_events = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=events_cfg,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )

    from solar_challenge.finance import project_multi_year

    project_multi_year(scenario, finance_events, simulate=simulate)

    assert call_count["n"] == 1, (
        f"compute_grid_services_at_events must be called exactly once per "
        f"project_multi_year run; got {call_count['n']}. "
        f"RED if not memoized (step-6 adds the closure-captured memo dict)."
    )
