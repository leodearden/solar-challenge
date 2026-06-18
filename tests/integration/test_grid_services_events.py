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
    # NOTE: gen/demand/self-consumption magnitudes are arbitrary.  They cancel
    # in the flat-rate-0 delta isolation and do not feed the grid-services
    # computation (which only reads battery_soc and battery_discharge).  The
    # /60.0 divisor is a leftover scaling that makes the kW values larger than
    # physically meaningful for hourly data; a future refactor can drop it.
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

    Delegates to ``tests.integration._helpers.board_econ_scenario`` — the
    canonical shared implementation — to avoid duplication with
    ``test_flex_grid_services._board_econ_scenario``.
    """
    from tests.integration._helpers import board_econ_scenario

    return board_econ_scenario("Board-EventsGridServices-Test")


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


# ---------------------------------------------------------------------------
# Coverage extension: memo reuse on bisection path
# ---------------------------------------------------------------------------


def _age_nonlinear_simulate(homes: list) -> "Callable":  # type: ignore[name-defined]
    """Return a simulate function whose fleet_revenue decays quadratically with age.

    Parses the age from fleet_config.name (``"proj-age-{age}"``).  The quadratic
    decay ensures the PCHIP midpoint error between sampled ages exceeds the
    default ``error_target_pct=1.0 %``, which triggers bisection and adds trial
    nodes beyond the initial three seed ages.

    ``battery_soc`` and ``battery_discharge`` stay constant across all ages so
    ``compute_grid_services_at_events`` always returns a positive figure —
    the test cares only that the event function is called exactly once (memo
    reuse), not that the figure changes with age.
    """
    import re as _re

    def _sim(fc: object, start_ts: object, end_ts: object) -> "FleetResults":  # type: ignore[name-defined]
        import pandas as pd
        from solar_challenge.fleet import FleetResults
        from solar_challenge.home import SimulationResults

        m = _re.search(r"proj-age-(\d+)", str(getattr(fc, "name", "")))
        age = int(m.group(1)) if m else 0

        # Quadratic decay: revenue at age=0 is 4× revenue at age=24 → PCHIP
        # midpoint error ≈ 4 % between seed ages 0 and 12 → bisection fires.
        scale = max(0.05, (1.0 - age / 30.0) ** 2)
        n_steps = 8760
        idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
        zeros = pd.Series(0.0, index=idx)
        sc_kw = 2.0 * scale
        exp_kw = 0.5 * scale
        imp_kw = 0.3 * scale

        sim_r = SimulationResults(
            generation=pd.Series(sc_kw + exp_kw, index=idx),
            demand=pd.Series(sc_kw + imp_kw, index=idx),
            self_consumption=pd.Series(sc_kw, index=idx),
            battery_charge=zeros.copy(),
            battery_discharge=pd.Series(0.5, index=idx),   # constant below max_discharge_kw=2.5
            battery_soc=pd.Series(3.0, index=idx),          # constant above min_soc_kwh=0.5
            grid_import=pd.Series(imp_kw, index=idx),
            grid_export=pd.Series(exp_kw, index=idx),
            import_cost=zeros.copy(),
            export_revenue=zeros.copy(),
            tariff_rate=zeros.copy(),
            grid_charge_cost=None,
        )
        fc_homes = list(getattr(fc, "homes", []))
        per_home = [sim_r for _ in fc_homes]
        return FleetResults(per_home_results=per_home, home_configs=fc_homes)  # type: ignore[call-arg]

    return _sim


def test_compute_once_memo_reused_on_bisection_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_grid_services_at_events is called exactly once even when bisection
    adds trial nodes beyond the initial three seed ages.

    Uses an age-nonlinear simulate (quadratic revenue decay) so the PCHIP
    midpoint error between seed ages exceeds error_target_pct → bisection fires
    and _simulate_age is called for additional mid-point ages.  The memo must
    still be populated only on the first call (age-0) and reused on all
    subsequent calls — including every bisection trial node.

    Covers the concern raised in review: the original compute-once test uses
    _constant_simulate, which never triggers bisection, leaving the bisection
    code path unexercised.
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

    events_cfg = GridServicesEventsConfig(band="central")
    finance_events = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=events_cfg,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )

    simulate = _age_nonlinear_simulate(homes)

    from solar_challenge.finance import project_multi_year

    curve = project_multi_year(scenario, finance_events, simulate=simulate)

    # Bisection should have fired — more than the initial 3 seed ages sampled.
    assert len(curve.sampled_ages) > 3, (
        f"Expected bisection to add trial nodes (sampled_ages={curve.sampled_ages}); "
        "check that _age_nonlinear_simulate produces sufficient PCHIP deviation."
    )

    # Even with bisection nodes, compute_grid_services_at_events is called once.
    assert call_count["n"] == 1, (
        f"compute_grid_services_at_events must be called exactly once per "
        f"project_multi_year run even when bisection adds trial nodes; "
        f"got {call_count['n']} calls (sampled_ages={curve.sampled_ages})."
    )


# ---------------------------------------------------------------------------
# Step-7 (GREEN on arrival): B4 — flat model bit-identical regression
# ---------------------------------------------------------------------------


def test_b4_flat_model_bit_identical_with_or_without_events_config() -> None:
    """B4 backward-compat regression: flat model YearPoint stream is bit-identical
    whether or not grid_services_events is attached; flat ≠ capacity_at_events.

    (1) FinanceConfig.grid_services_model default is "flat".
    (2) Flat with events=None vs flat with events config attached → identical curves.
        The event config is inert unless grid_services_model=='capacity_at_events'.
    (3) Flat curve ≠ capacity_at_events curve for the same fleet (teeth).

    GREEN on arrival: the single conditional in step-2/step-6 preserves the flat path
    char-for-char and ignores grid_services_events when model is "flat".
    """
    from solar_challenge.config import FinanceConfig  # type: ignore[attr-defined]
    from solar_challenge.finance import project_multi_year
    from solar_challenge.gridservices import GridServicesEventsConfig

    scenario, finance_base = _board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)
    simulate = _constant_simulate(fr)

    # (1) default model is "flat"
    assert finance_base.grid_services_model == "flat", (
        "FinanceConfig.grid_services_model default must be 'flat'"
    )

    # (2) flat: no events config vs attached events config → bit-identical
    finance_flat_no_events = dataclasses.replace(finance_base, grid_services_events=None)
    finance_flat_with_events = dataclasses.replace(
        finance_base,
        grid_services_events=GridServicesEventsConfig(band="central"),
    )
    curve_no_events = project_multi_year(scenario, finance_flat_no_events, simulate=simulate)
    curve_with_events = project_multi_year(scenario, finance_flat_with_events, simulate=simulate)
    assert curve_no_events.points == curve_with_events.points, (
        "Flat model must produce bit-identical YearPoint tuples with/without "
        "grid_services_events attached — the event config is inert in flat mode."
    )

    # (3) flat ≠ capacity_at_events (teeth — confirms supersede is real)
    finance_events = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=GridServicesEventsConfig(band="central"),
        grid_services_income_per_kw_per_year_gbp=0.0,
    )
    curve_events = project_multi_year(scenario, finance_events, simulate=simulate)

    rev_flat = curve_no_events.points[0].fleet_revenue_gbp
    rev_events = curve_events.points[0].fleet_revenue_gbp
    assert rev_flat != rev_events, (
        f"Flat (£{rev_flat:.4f}) and capacity_at_events (£{rev_events:.4f}) "
        "must differ for the same fleet — confirms the supersede takes effect."
    )


# ---------------------------------------------------------------------------
# Step-8 (GREEN on arrival): B5 — solve-still-holds + I4 rate-independence
# ---------------------------------------------------------------------------


def test_b5_solve_cost_recovery_converges_and_i4_rate_independence() -> None:
    """B5 solve-still-holds + I4 rate-independence contract guard on the W2 seam.

    (1) solve_cost_recovery_rate on the capacity_at_events scenario converges —
        returns a CostRecoverySolution with a finite own_use_rate and valid binding.
    (2) Event income flows through: net_surplus under capacity_at_events exceeds
        net_surplus under flat-rate-0 for the same fleet.
    (3) I4 rate-independence: isolated grid_services component is invariant to
        own_use_rate_pence_per_kwh (event income does not depend on the CBS tariff,
        so the affine reconstruction in solve_cost_recovery_rate stays valid).

    GREEN on arrival: event income (like the flat term) is rate-independent
    (own_use_rate never enters physical dispatch or gridservices computation),
    so the existing affine reconstruction (finance.py:1789-1802) remains exact.
    """
    import math

    from solar_challenge.finance import (
        project_economics,
        project_multi_year,
        solve_cost_recovery_rate,
    )
    from solar_challenge.gridservices import GridServicesEventsConfig

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
    finance_flat0 = dataclasses.replace(
        finance_base,
        grid_services_income_per_kw_per_year_gbp=0.0,
    )

    # (1) solve converges (finite rate, valid binding)
    sol = solve_cost_recovery_rate(scenario, finance_events, simulate=simulate)
    assert math.isfinite(sol.own_use_rate_pence_per_kwh), (
        f"Solved own-use rate must be finite; got {sol.own_use_rate_pence_per_kwh!r}"
    )
    # Assert the property actually under test: a non-empty binding string is
    # returned on every code path.  Avoid pinning the exact enumeration of
    # binding values so the test does not fail spuriously when new values are
    # added to solve_cost_recovery_rate.
    assert isinstance(sol.binding, str) and sol.binding, (
        f"solve_cost_recovery_rate must return a non-empty binding string; "
        f"got {sol.binding!r}"
    )

    # (2) event income flows through: capacity_at_events surplus > flat-rate-0 surplus
    curve_events = project_multi_year(scenario, finance_events, simulate=simulate)
    curve_flat0 = project_multi_year(scenario, finance_flat0, simulate=simulate)
    surplus_events = project_economics(
        curve_events, scenario, finance_events
    ).net_surplus_per_home_per_year_gbp
    surplus_flat0 = project_economics(
        curve_flat0, scenario, finance_flat0
    ).net_surplus_per_home_per_year_gbp
    assert surplus_events > surplus_flat0, (
        f"capacity_at_events surplus (£{surplus_events:.4f}/home/yr) must exceed "
        f"flat-rate-0 surplus (£{surplus_flat0:.4f}/home/yr) — event income flows through."
    )

    # (3) I4 rate-independence: isolated gs component invariant to own_use_rate
    finance_events_r5 = dataclasses.replace(finance_events, own_use_rate_pence_per_kwh=5.0)
    finance_events_r20 = dataclasses.replace(finance_events, own_use_rate_pence_per_kwh=20.0)
    finance_flat0_r5 = dataclasses.replace(finance_flat0, own_use_rate_pence_per_kwh=5.0)
    finance_flat0_r20 = dataclasses.replace(finance_flat0, own_use_rate_pence_per_kwh=20.0)

    gs_at_r5 = _isolate_gs_component(scenario, finance_events_r5, finance_flat0_r5, simulate)
    gs_at_r20 = _isolate_gs_component(scenario, finance_events_r20, finance_flat0_r20, simulate)

    assert gs_at_r5 == pytest.approx(gs_at_r20, rel=1e-9), (
        f"Isolated grid_services component must be invariant to own_use_rate; "
        f"at r=5 p/kWh: £{gs_at_r5:.6f}, at r=20 p/kWh: £{gs_at_r20:.6f}"
    )
