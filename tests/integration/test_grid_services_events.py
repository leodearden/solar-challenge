# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: grid-services-at-events δ — supersede W2 flat term under model flag.

Tests the cross-task seam: capacity_at_events model → project_multi_year →
compute_grid_services_at_events → annual_income_gbp replaces (not adds to)
the flat per-kW term, gated by FinanceConfig.grid_services_model.

Covers, after the shared helpers:
- B3: supersede takes effect.
- Guard: capacity_at_events + events=None → ConfigurationError, before any simulation.
- C1, C2: each simulated age, seed or bisection trial, books its own fleet's
  event income.
- An event window the simulated period never enters warns once per projection.
- B4:backward-compat / flat bit-identical regression.
- B5: solve-still-holds + I4 rate-independence.
- ε: the finance report and the CLI render the capacity-at-events line.
"""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Callable, NamedTuple

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig, load_config, parse_finance_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import (
    FinanceConfig,
    MultiYearCurve,
    bill_distribution,
    project_economics,
    project_multi_year,
    solve_cost_recovery_rate,
)
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.flex import resolve_flex_band
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    EventWindow,
    GridServicesEventsConfig,
    compute_grid_services_at_events,
)
from solar_challenge.home import SimulationResults, SummaryStatistics
from solar_challenge.output import generate_finance_report
from tests._cli_fleet_simulator import invoke_finance_run
from tests._finance_builders import make_fleet_results_of, make_scenario_and_finance
from tests.integration._helpers import board_econ_scenario

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"


# ---------------------------------------------------------------------------
# Shared helpers (pre-1)
# ---------------------------------------------------------------------------


_A_YEAR_OF_HOURS_FROM_2024 = pd.date_range(
    "2024-01-01", periods=8760, freq="1h", tz="Europe/London"
)


def _make_spare_battery_sim_results(
    hours: pd.DatetimeIndex = _A_YEAR_OF_HOURS_FROM_2024, battery_soc_kwh: float = 3.0
) -> SimulationResults:
    """Build a SimulationResults on the hourly index *hours*, with constant
    battery_soc above min_soc_kwh and battery_discharge below max_discharge_kw.

    With the default battery_soc_kwh=3.0 (above min_soc_kwh=0.5 for a 5kWh×0.1 battery)
    and battery_discharge=0.5 kW (below max_discharge_kw=2.5), DEFAULT_EVENT_WINDOWS
    (winter-weekday-16-18h) selects real in-window steps of the default full-year
    index, and compute_fleet_spare_capacity_kw yields a positive event figure.
    """
    n_steps = len(hours)
    # NOTE: gen/demand/self-consumption magnitudes are arbitrary.  They cancel
    # in the flat-rate-0 delta isolation and do not feed the grid-services
    # computation (which only reads battery_soc and battery_discharge).  Each
    # kW row lasts an hour, so *hours* total 2,000 kWh of self-consumption,
    # 800 kWh of export and 1,400 kWh of import.
    sc_kw = 2000.0 / n_steps
    exp_kw = 800.0 / n_steps
    imp_kw = 1400.0 / n_steps
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=hours)

    return SimulationResults(
        generation=pd.Series(gen_kw, index=hours),
        demand=pd.Series(demand_kw, index=hours),
        self_consumption=pd.Series(sc_kw, index=hours),
        battery_charge=zeros.copy(),
        battery_discharge=pd.Series(0.5, index=hours),  # below max_discharge_kw=2.5
        battery_soc=pd.Series(battery_soc_kwh, index=hours),
        grid_import=pd.Series(imp_kw, index=hours),
        grid_export=pd.Series(exp_kw, index=hours),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _synthetic_fleet_results_in_window(homes: list) -> FleetResults:
    """Build FleetResults with in-window battery_soc/discharge per home."""
    per_home = [_make_spare_battery_sim_results() for _ in homes]
    return make_fleet_results_of(per_home, homes=homes)


def _constant_simulate(
    fr: FleetResults,
) -> Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]:
    """Return a constant simulate function: (fc, s, e) -> fr (age-independent)."""
    return lambda fc, s, e: fr


def _rev_at(
    scenario: ScenarioConfig,
    finance: FinanceConfig,
    simulate: Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults],
    year: int = 0,
) -> float:
    """Return fleet_revenue_gbp at a given year from project_multi_year."""
    curve = project_multi_year(scenario, finance, simulate=simulate)
    return curve.points[year].fleet_revenue_gbp


def _isolate_gs_component(
    scenario: ScenarioConfig,
    finance_events: FinanceConfig,
    finance_flat0: FinanceConfig,
    simulate: Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults],
    year: int = 0,
) -> float:
    """Isolate the grid_services component via the flat-rate-0 delta.

    Returns rev(capacity_at_events, year) - rev(flat, rate=0, year).
    Since own_use_revenue and seg_revenue are invariant
    across the two models (same simulate, same scenario), the delta equals
    exactly the grid_services contribution.
    """
    return _rev_at(scenario, finance_events, simulate, year) - _rev_at(
        scenario, finance_flat0, simulate, year
    )


# ---------------------------------------------------------------------------
# B3 — supersede takes effect
# ---------------------------------------------------------------------------


def test_b3_supersede_event_derived_figure_replaces_flat() -> None:
    """capacity_at_events model supersedes (replaces) the flat per-kW term.

    Isolated grid_services component from the delta (rev_events - rev_flat0)
    EQUALS compute_grid_services_at_events directly AND differs from the flat term.

    The capacity_at_events branch replaces the flat term: were the flat term still
    computed, the isolated delta would equal the flat increment (0, since flat
    rate=0) while the event-derived figure is positive.
    """
    scenario, finance_base = board_econ_scenario()
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
        grid_services_model="flat",
        grid_services_events=None,
        grid_services_income_per_kw_per_year_gbp=0.0,  # irrelevant in flat model
    )

    # Direct event-derived figure (the expected value for the delta)
    expected_gs = compute_grid_services_at_events(fr, events_cfg).annual_income_gbp
    assert expected_gs > 0.0, "Synthetic in-window fleet must yield positive event income"

    # Isolated component via the flat-rate-0 delta
    isolated_gs = _isolate_gs_component(scenario, finance_events, finance_flat0, simulate)

    # I3: isolated == event-derived (supersede, not add)
    assert isolated_gs == pytest.approx(expected_gs, rel=1e-6), (
        f"Isolated gs component ({isolated_gs:.4f}) must equal event-derived figure "
        f"({expected_gs:.4f}). The flat term must not be used."
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
# Guard — None events → ConfigurationError
# ---------------------------------------------------------------------------


def test_guard_capacity_at_events_with_events_none_raises_configuration_error() -> None:
    """capacity_at_events + grid_services_events=None is refused before any simulation.

    FinanceConfig still constructs the pair; project_multi_year refuses it with
    ConfigurationError before it simulates a fleet, so the injected simulate
    fails the test if it is called.
    """
    scenario, finance_base = board_econ_scenario()

    def _simulate_must_not_run(fc, s, e):
        pytest.fail("project_multi_year simulated a fleet before refusing the configuration")

    finance_none = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=None,
    )

    with pytest.raises(ConfigurationError, match="grid_services_events"):
        project_multi_year(scenario, finance_none, simulate=_simulate_must_not_run)


# ---------------------------------------------------------------------------
# C1, C2 — each simulated age books its own fleet's event income
# ---------------------------------------------------------------------------


def _soh_tracking_simulate(
    fleets_by_age: dict[int, FleetResults],
) -> Callable[..., FleetResults]:
    """A simulate whose battery SOC is 0.8 × capacity × each aged home's SOH; every other flow is the same at every age.

    It records each fleet it answers in *fleets_by_age*, keyed by the age
    project_multi_year aged the homes' PV to.
    """

    def _simulate(fleet_config, start_ts, end_ts):  # type: ignore[no-untyped-def]
        homes = fleet_config.homes
        fleet = make_fleet_results_of(
            [
                _make_spare_battery_sim_results(
                    battery_soc_kwh=0.8
                    * home.battery_config.capacity_kwh
                    * home.battery_config.soh
                )
                for home in homes
            ],
            homes=homes,
        )
        fleets_by_age[int(homes[0].pv_config.system_age_years)] = fleet
        return fleet

    return _simulate


class _SohTrackingProjections(NamedTuple):
    events: MultiYearCurve
    no_grid_services: MultiYearCurve
    events_fleets_by_age: dict[int, FleetResults]


@pytest.fixture(scope="module")
def soh_tracking_projections() -> _SohTrackingProjections:
    """Two 5 kWh default-fade batteries over 25 years, priced by the events model and by no grid services.

    At a 1 p/kWh own-use rate and no SEG rate, the event income is over a third
    of the age-0 revenue, so the SOH kink at the 0.5 floor bends the events
    revenue curve past the 1% bisection target.
    """
    scenario, finance = make_scenario_and_finance(
        n_homes=2, asset_life_years=25, battery_config=BatteryConfig(capacity_kwh=5.0)
    )
    finance_none = dataclasses.replace(finance, own_use_rate_pence_per_kwh=1.0)
    finance_events = dataclasses.replace(
        finance_none,
        grid_services_model="capacity_at_events",
        grid_services_events=GridServicesEventsConfig(),
    )
    events_fleets_by_age: dict[int, FleetResults] = {}
    return _SohTrackingProjections(
        events=project_multi_year(
            scenario, finance_events, simulate=_soh_tracking_simulate(events_fleets_by_age)
        ),
        no_grid_services=project_multi_year(
            scenario, finance_none, simulate=_soh_tracking_simulate({})
        ),
        events_fleets_by_age=events_fleets_by_age,
    )


def _booked_and_priced_event_income(
    projections: _SohTrackingProjections, age: int
) -> tuple[float, float]:
    """The event income the events curve books at *age*, and what that age's simulated fleet prices at."""
    booked = (
        projections.events.points[age].fleet_revenue_gbp
        - projections.no_grid_services.points[age].fleet_revenue_gbp
    )
    priced = compute_grid_services_at_events(
        projections.events_fleets_by_age[age], GridServicesEventsConfig()
    ).annual_income_gbp
    return booked, priced


def test_c1_each_sampled_age_books_its_own_fleets_event_income(
    soh_tracking_projections: _SohTrackingProjections,
) -> None:
    curve = soh_tracking_projections.events
    booked_by_age = {}
    for age in curve.sampled_ages:
        booked, priced = _booked_and_priced_event_income(soh_tracking_projections, age)
        assert booked == pytest.approx(priced, rel=1e-9), f"age {age}"
        booked_by_age[age] = booked

    assert booked_by_age[24] < booked_by_age[0]
    assert booked_by_age[24] == pytest.approx(
        booked_by_age[0] * curve.points[24].battery_soh / curve.points[0].battery_soh,
        rel=1e-9,
    )


def test_c2_bisection_trial_ages_book_their_own_fleets_event_income(
    soh_tracking_projections: _SohTrackingProjections,
) -> None:
    sampled_ages = soh_tracking_projections.events.sampled_ages
    assert len(sampled_ages) > 3, sampled_ages

    for age in sorted(set(sampled_ages) - {0, 12, 24}):
        booked, priced = _booked_and_priced_event_income(soh_tracking_projections, age)
        assert booked == pytest.approx(priced, rel=1e-9), f"age {age}"


# ---------------------------------------------------------------------------
# An event window the simulated period never enters warns once per projection
# ---------------------------------------------------------------------------


_JUNE_2024_HOURS = pd.date_range(
    "2024-06-01 00:00", "2024-06-30 23:00", freq="h", tz="Europe/London"
)


def test_a_projection_shows_each_unobserved_window_warning_once() -> None:
    """Every simulated age prices a June-only fleet, which neither event window enters.

    Each age's pricing warns of both windows in the same words, and the
    projection shows each window's warning once, attributed to its caller
    (docs/prds/grid-services-pricing-model.md §5.4).
    """
    march_window = EventWindow(
        months=(3,),
        weekdays=(0, 1, 2, 3, 4),
        hours=(16, 17, 18),
        events_per_year=12,
        event_hours=3.0,
    )
    scenario, finance = make_scenario_and_finance(
        n_homes=2, asset_life_years=25, battery_config=BatteryConfig(capacity_kwh=5.0)
    )
    finance_events = dataclasses.replace(
        finance,
        grid_services_model="capacity_at_events",
        grid_services_events=GridServicesEventsConfig(
            event_windows=(DEFAULT_EVENT_WINDOWS[0], march_window)
        ),
    )

    def _june_only_simulate(fleet_config, start_ts, end_ts):  # type: ignore[no-untyped-def]
        homes = fleet_config.homes
        return make_fleet_results_of(
            [_make_spare_battery_sim_results(hours=_JUNE_2024_HOURS) for _ in homes],
            homes=homes,
        )

    with pytest.warns(UserWarning) as record:
        curve = project_multi_year(scenario, finance_events, simulate=_june_only_simulate)

    # Premise: several ages are priced, so a warning shown per age would repeat.
    assert len(curve.sampled_ages) >= 3, curve.sampled_ages
    for names_the_window in ("months=(11, 12, 1, 2)", "months=(3,)"):
        window_warnings = [w for w in record if names_the_window in str(w.message)]
        assert len(window_warnings) == 1, [str(w.message) for w in window_warnings]
        assert window_warnings[0].filename == __file__


# ---------------------------------------------------------------------------
# B4 — flat model bit-identical regression
# ---------------------------------------------------------------------------


def test_b4_flat_model_bit_identical_with_or_without_events_config() -> None:
    """B4 backward-compat regression: flat model YearPoint stream is bit-identical
    whether or not grid_services_events is attached; flat ≠ capacity_at_events.

    (1) FinanceConfig.grid_services_model default is "flat".
    (2) Flat with events=None vs flat with events config attached → identical curves.
        The event config is inert unless grid_services_model=='capacity_at_events'.
    (3) Flat curve ≠ capacity_at_events curve for the same fleet (teeth).

    The single conditional on the model preserves the flat path char-for-char and
    ignores grid_services_events when model is "flat".
    """
    scenario, finance_base = board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)
    simulate = _constant_simulate(fr)

    # (1) FinanceConfig.grid_services_model field default is "flat"
    # (decoupled from the board YAML, which ships capacity_at_events after task-76 ε flip)
    _gs_field = next(
        f for f in dataclasses.fields(finance_base) if f.name == "grid_services_model"
    )
    assert _gs_field.default == "flat", (
        "FinanceConfig.grid_services_model field default must be 'flat'"
    )

    # (2) flat: no events config vs attached events config → bit-identical
    # Build from an explicitly flat base (board YAML ships capacity_at_events after ε flip)
    finance_flat_base = dataclasses.replace(
        finance_base, grid_services_model="flat", grid_services_events=None
    )
    finance_flat_no_events = finance_flat_base  # events already None
    finance_flat_with_events = dataclasses.replace(
        finance_flat_base,
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
# B5 — solve-still-holds + I4 rate-independence
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

    Event income (like the flat term) is rate-independent
    (own_use_rate never enters physical dispatch or gridservices computation),
    so the existing affine reconstruction (finance.py:1789-1802) remains exact.
    """
    scenario, finance_base = board_econ_scenario()
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
        grid_services_model="flat",
        grid_services_events=None,
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


# ---------------------------------------------------------------------------
# ε — finance report renders capacity-at-events line
# ---------------------------------------------------------------------------


def test_epsilon_finance_report_renders_capacity_at_events_line() -> None:
    """generate_finance_report with grid_services_at_events renders the event-derived line.

    Builds a synthetic BillDistribution + a positive-spare FleetResults,
    computes the event figure, then asserts the rendered report contains:
      - "Grid services (capacity-at-events)" label
      - the formatted annual £ (event-derived)
      - the per-window avail_kW value

    The Optional[GridServicesAtEvents] param renders the line inside the existing
    flex-value block.
    """
    # Build a minimal synthetic BillDistribution (mirrors test_flex_timeshift pattern)
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

    # Build an in-window FleetResults from the board homes
    scenario, _finance_base = board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)

    # Compute the event figure (precondition: must be positive)
    events_cfg = GridServicesEventsConfig(band="central")
    gse = compute_grid_services_at_events(fr, events_cfg)
    assert gse.annual_income_gbp > 0.0, (
        "Synthetic in-window fleet must yield positive annual event income"
    )

    # Call generate_finance_report with the grid_services_at_events param
    report = generate_finance_report(
        dist,
        scenario_name="Epsilon-Events-Test",
        flex_band=resolve_flex_band("central"),
        flex_band_name="central",
        grid_services_at_events=gse,
    )

    # The line must appear in the flex-value block
    assert "Grid services (capacity-at-events)" in report, (
        "Report must contain the 'Grid services (capacity-at-events)' label"
    )
    # Formatted annual £ must appear (comma-separated, no decimals)
    expected_gbp_str = f"£{gse.annual_income_gbp:,.0f}"
    assert expected_gbp_str in report, (
        f"Report must contain the event-derived annual income '{expected_gbp_str}'"
    )
    # Per-window avail_kW (summed across windows) must appear (1 dp format expected)
    # per_window_avail_kw is tuple[float,...]; sum gives total fleet avail kW.
    expected_kw_str = f"{sum(gse.per_window_avail_kw):.1f}"
    assert expected_kw_str in report, (
        f"Report must contain per-window avail_kW '{expected_kw_str} kW'"
    )


# ---------------------------------------------------------------------------
# ε — CLI finance run emits event-derived line
# ---------------------------------------------------------------------------


def test_epsilon_finance_run_cli_emits_event_derived_grid_services_line() -> None:
    """finance run scenarios/bristol-phase1-flex.yaml emits the capacity-at-events line.

    Invokes the CLI against the board scenario, answering every fleet simulation
    with an in-window synthetic FleetResults, and asserts:
      - exit_code == 0
      - "Grid services (capacity-at-events)" line in output
      - a positive event-derived £ figure in output
      - (after YAML flip) the supersede inequality: event income ≠ flat_rate × Σ kW

    The board YAML selects capacity_at_events and the CLI passes the computed
    grid_services_at_events to generate_finance_report.
    """
    scenario_path = Path("scenarios/bristol-phase1-flex.yaml")

    # In-window FleetResults from the board homes
    scenario, _finance = board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)

    result = invoke_finance_run([str(scenario_path)], fr)

    assert result.exit_code == 0, (
        f"CLI exited {result.exit_code}. Output:\n{result.output}"
    )

    # Main assertion: the capacity-at-events line must appear
    assert "Grid services (capacity-at-events)" in result.output, (
        f"Expected 'Grid services (capacity-at-events)' line in output.\n{result.output}"
    )

    # The rendered event-derived £ must be present (positive)
    assert "£" in result.output, "Output must contain a £ figure"

    # Supersede inequality (only checkable after ε flips the board YAML to
    # capacity_at_events; skips gracefully if still flat)
    raw = load_config(scenario_path)
    finance = parse_finance_config(raw.get("finance"))
    assert finance is not None
    if finance.grid_services_events is not None:
        flat_rate = finance.grid_services_income_per_kw_per_year_gbp
        sigma = sum(
            h.battery_config.max_discharge_kw
            for h in homes if h.battery_config is not None
        )
        gse_direct = compute_grid_services_at_events(fr, finance.grid_services_events)
        assert gse_direct.annual_income_gbp != pytest.approx(flat_rate * sigma, rel=1e-3), (
            f"Event-derived income (£{gse_direct.annual_income_gbp:.2f}) must differ from "
            f"flat term (£{flat_rate} × {sigma} kW = £{flat_rate * sigma:.2f}); "
            "confirms the supersede takes effect."
        )
