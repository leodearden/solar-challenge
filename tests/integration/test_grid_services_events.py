# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: grid-services-at-events δ — supersede W2 flat term under model flag.

Tests the cross-task seam: capacity_at_events model → project_multi_year →
compute_grid_services_at_events → annual_income_gbp replaces (not adds to)
the flat per-kW term, gated by FinanceConfig.grid_services_model.

Covers, after the shared helpers:
- B3: supersede takes effect.
- Guard (C6): finance run refuses a capacity_at_events scenario with no
  grid_services_events block before any simulation.
- C1, C2: each simulated age, seed or bisection trial, books its own fleet's
  event income.
- An event window the simulated period never enters warns once per projection.
- B4: the flat model refuses an events configuration and prices the fleet
  differently from the events model.
- B5: solve-still-holds + I4 rate-independence.
- ε: the finance report and the CLI render the Grid Services Income section.
- α′ (PRD §9 C13): the events table's reliability and displaced-self-use rows,
  and finance run's mean-over-event-days income beside them.
- B10, B11 (review-all S25 δ): finance run renders the income each mode's
  projection booked at year 1 and year N beside this window's fleet, with no
  flexibility band; and the flexibility-value block's grid-services row reads
  the booked income.
"""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Callable, NamedTuple

import pandas as pd
import pytest
import yaml

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.board_report import GridServicesIncome, generate_finance_report
from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import BillDistribution, FinanceConfig, bill_distribution
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    GRID_SERVICES_RATE_BANDS,
    EventWindow,
    GridServicesAtEvents,
    GridServicesEventsConfig,
    compute_grid_services_at_events,
)
from solar_challenge.home import RunPricing, SimulationResults, SummaryStatistics
from solar_challenge.projection import (
    MultiYearCurve,
    project_economics,
    project_multi_year,
    scenario_fleet,
    solve_cost_recovery_rate,
)
from tests._assumption_sections import make_assumption_section, sections_of
from tests._cli_fleet_simulator import answering, invoke_cli, invoke_finance_run
from tests._finance_builders import make_fleet_results_of, make_scenario_and_finance, make_window
from tests._markdown_tables import row_cells
from tests.integration._helpers import SCENARIO, board_econ_scenario


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
    and battery_discharge=0.2 kW (below max_discharge_kw=2.5), DEFAULT_EVENT_WINDOWS
    (winter-weekday-16-18h) selects real in-window steps of the default full-year
    index, and compute_fleet_spare_capacity_kw yields a positive event figure.
    """
    n_steps = len(hours)
    # NOTE: gen/demand/self-consumption magnitudes are arbitrary.  They cancel
    # in the flat-rate-0 delta isolation and do not feed the grid-services
    # computation (which only reads battery_soc and battery_discharge).  Each
    # kW row lasts an hour, so *hours* total 2,000 kWh of self-consumption,
    # 800 kWh of export and 1,400 kWh of import.  The 0.2 kW discharge totals
    # at most 1,752 kWh over a year of hours, under the 2,000 kWh of
    # self-consumption that counts it.
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
        battery_discharge=pd.Series(0.2, index=hours),  # below max_discharge_kw=2.5
        battery_soc=pd.Series(battery_soc_kwh, index=hours),
        grid_import=pd.Series(imp_kw, index=hours),
        grid_export=pd.Series(exp_kw, index=hours),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
        pricing=RunPricing(None, None),
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
        grid_services_income_per_kw_per_year_gbp=0.0,  # the only rate the events model admits
    )
    finance_flat0 = dataclasses.replace(
        finance_base,
        grid_services_model="flat",
        grid_services_events=None,
        grid_services_income_per_kw_per_year_gbp=0.0,  # flat at rate 0: no grid-services income
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
    flat_rate = GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year
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
# Guard (C6) — None events → ConfigurationError before any simulation
# ---------------------------------------------------------------------------


def test_finance_run_refuses_the_events_model_without_events_before_simulating(
    tmp_path: Path,
) -> None:
    """C6: finance run on the board scenario with its grid_services_events block deleted exits 1 naming the block, and simulates no fleet."""
    document = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
    del document["finance"]["grid_services_events"]
    path = tmp_path / SCENARIO.name
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    simulated: list[FleetConfig] = []

    def _recording_simulate(
        fleet_config: FleetConfig, start_ts: pd.Timestamp, end_ts: pd.Timestamp
    ) -> FleetResults:
        simulated.append(fleet_config)
        return _synthetic_fleet_results_in_window(fleet_config.homes)

    result = invoke_cli(["finance", "run", str(path)], answering(_recording_simulate))

    stderr = " ".join(result.stderr.split())
    assert result.exit_code == 1, result.output
    assert "Configuration error:" in stderr
    assert "grid_services_events" in stderr
    assert simulated == []


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


def test_b4_the_flat_model_refuses_an_events_configuration_and_differs_from_the_events_model() -> None:
    """B4: the flat model is FinanceConfig's default, refuses an events configuration it
    would not read, and prices the same fleet differently from capacity_at_events.

    (1) FinanceConfig.grid_services_model default is "flat".
    (2) Attaching grid_services_events under the flat model is refused at construction,
        naming grid_services_events.
    (3) Flat curve ≠ capacity_at_events curve for the same fleet (teeth).
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

    # (2) flat with an events configuration attached → refused
    # Build from an explicitly flat base (board YAML ships capacity_at_events after ε flip)
    finance_flat_base = dataclasses.replace(
        finance_base, grid_services_model="flat", grid_services_events=None
    )
    with pytest.raises(ConfigurationError, match="grid_services_events"):
        dataclasses.replace(
            finance_flat_base,
            grid_services_events=GridServicesEventsConfig(band="central"),
        )

    # (3) flat ≠ capacity_at_events (teeth — confirms supersede is real)
    finance_events = dataclasses.replace(
        finance_base,
        grid_services_model="capacity_at_events",
        grid_services_events=GridServicesEventsConfig(band="central"),
        grid_services_income_per_kw_per_year_gbp=0.0,
    )
    curve_flat = project_multi_year(scenario, finance_flat_base, simulate=simulate)
    curve_events = project_multi_year(scenario, finance_events, simulate=simulate)

    rev_flat = curve_flat.points[0].fleet_revenue_gbp
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
    so the existing affine reconstruction (projection.solve_cost_recovery_rate's
    surplus_at) remains exact.
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
        curve_events, scenario_fleet(scenario), finance_events
    ).net_surplus_per_home_per_year_gbp
    surplus_flat0 = project_economics(
        curve_flat0, scenario_fleet(scenario), finance_flat0
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


def _synthetic_bill_distribution() -> BillDistribution:
    """A one-home BillDistribution over 365 days (mirrors tests/integration/test_flex_timeshift.py's pattern)."""
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
        total_import_cost_gbp=276.0,
        total_export_revenue_gbp=73.8,
        net_cost_gbp=202.2,
        window=make_window(days=365),
        pricing=RunPricing(0.23, 4.1),
    )
    finance = FinanceConfig(
        standing_charge_pence_per_day=60.0,
        own_use_rate_pence_per_kwh=15.0,
    )
    return bill_distribution([summary], finance)


def test_epsilon_finance_report_renders_capacity_at_events_line() -> None:
    """generate_finance_report with an events GridServicesIncome renders the event-derived section.

    Builds a synthetic BillDistribution + a positive-spare FleetResults,
    computes the event figure, then asserts the rendered report contains:
      - the "## Grid Services Income" section
      - the formatted annual £ (event-derived)
      - the per-window avail_kW value

    The section renders without a flexibility band.
    """
    dist = _synthetic_bill_distribution()

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

    batteries = [home.battery_config for home in homes if home.battery_config is not None]
    report = generate_finance_report(
        sections_of(make_assumption_section(bill=dist)),
        scenario_name="Epsilon-Events-Test",
        grid_services=GridServicesIncome(
            pricing=events_cfg,
            annual_income_gbp=gse.annual_income_gbp,
            battery_homes=len(batteries),
            battery_discharge_kw=sum(battery.max_discharge_kw for battery in batteries),
            at_events=gse,
        ),
    )

    assert "## Grid Services Income" in report.splitlines(), (
        "Report must contain the '## Grid Services Income' section"
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
      - the "## Grid Services Income" section and its model line in output
      - a positive event-derived £ figure in output
      - the supersede inequality: event income ≠ flat_rate × Σ kW

    The board YAML selects capacity_at_events and the CLI passes the income its
    pricing books to generate_finance_report.
    """
    # In-window FleetResults from the board homes
    scenario, finance = board_econ_scenario()
    homes = scenario.homes
    fr = _synthetic_fleet_results_in_window(homes)

    result = invoke_finance_run([str(SCENARIO)], fr)

    assert result.exit_code == 0, (
        f"CLI exited {result.exit_code}. Output:\n{result.output}"
    )

    lines = result.output.splitlines()
    assert "## Grid Services Income" in lines, result.output
    assert "Model: **capacity at events, central band, operational delivery baseline**" in lines, result.output

    # The rendered event-derived £ must be present (positive)
    assert "£" in result.output, "Output must contain a £ figure"

    assert finance.grid_services_events is not None, (
        f"{SCENARIO} (grid_services_model={finance.grid_services_model!r}) has no "
        "grid_services_events block, so the supersede inequality cannot be checked"
    )
    flat_rate = GRID_SERVICES_RATE_BANDS.resolve("central").flat_gbp_per_kw_per_year
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


# ---------------------------------------------------------------------------
# α′ — the events table's reliability and displaced-self-use rows (PRD §9 C13)
# ---------------------------------------------------------------------------


def _events_report(gse: GridServicesAtEvents) -> str:
    """The finance report of one section, with *gse* booked on one 2.5 kW battery home at the default events pricing."""
    return generate_finance_report(
        sections_of(make_assumption_section(bill=_synthetic_bill_distribution())),
        scenario_name="Alpha-Prime-Events-Test",
        grid_services=GridServicesIncome(
            pricing=GridServicesEventsConfig(),
            annual_income_gbp=gse.annual_income_gbp,
            battery_homes=1,
            battery_discharge_kw=2.5,
            at_events=gse,
        ),
    )


_PER_WINDOW_NOTE = "is one event window's figure"


def test_the_events_table_renders_reliability_and_displacement_rows() -> None:
    """One event window: its figures, and a note that the income is gross of the displaced self-use, which a home simulated without a tariff values at £0."""
    report = _events_report(
        GridServicesAtEvents(
            annual_income_gbp=14.958,
            per_window_avail_kw=(1.5,),
            per_window_income_gbp=(14.958,),
            per_window_avail_p50_kw=(2.0,),
            per_window_avail_p90_kw=(1.0,),
            per_window_displaced_self_use_kwh_per_event=(2.3,),
            per_window_displaced_import_gbp_per_year=(8.1,),
        )
    )

    lines = report.splitlines()
    for row in (
        "| Capacity on 50% of event days | 2.0 kW |",
        "| Capacity on 90% of event days | 1.0 kW |",
        "| Evening self-use displaced, per event | 2.3 kWh |",
        "| Evening self-use displaced, value per year | £8 |",
    ):
        assert row in lines, report
    assert "gross of the evening self-use an event displaces" in report, report
    assert "£0 for a home simulated without one" in report, report
    assert _PER_WINDOW_NOTE not in report, report


def test_several_event_windows_show_no_per_window_figure_summed() -> None:
    """Two windows: the 50%, 90% and per-event rows show —, since summed over windows they describe no set of event days; the value per year is the windows' total."""
    report = _events_report(
        GridServicesAtEvents(
            annual_income_gbp=19.944,
            per_window_avail_kw=(1.5, 0.5),
            per_window_income_gbp=(14.958, 4.986),
            per_window_avail_p50_kw=(2.0, 0.5),
            per_window_avail_p90_kw=(1.0, 0.3),
            per_window_displaced_self_use_kwh_per_event=(2.25, 0.75),
            per_window_displaced_import_gbp_per_year=(8.1, 1.9),
        )
    )

    lines = report.splitlines()
    for row in (
        "| Capacity on 50% of event days | — |",
        "| Capacity on 90% of event days | — |",
        "| Evening self-use displaced, per event | — |",
        "| Evening self-use displaced, value per year | £10 |",
    ):
        assert row in lines, report
    assert _PER_WINDOW_NOTE in report, report


def test_c13_finance_run_books_the_mean_over_event_days_beside_its_reliability_and_displacement() -> None:
    """finance run on the board scenario, every battery home at its floor through 8 January's window and 1.0 kW clear of it on 9 January.

    Per home: avail 0 on 8 January and min(2.5 − 0.5, (3.5 − 0.5) / 3) = 1.0 kW on
    9 January, so with N battery homes A = (0, N): the income books the mean N / 2
    (× £9.972), p50 is N and p90 0. On 9 January each home displaces min(1.0 × 3,
    2 h × 1.0 kW before the 21:00 recharge) = 2.0 kWh at 0.25 £/kWh: N kWh per
    event, and mean(0, 0.5 N) × 12 = £3N a year.
    """
    scenario, _finance = board_econ_scenario()
    battery_homes = [home for home in scenario.homes if home.battery_config is not None]
    for home in battery_homes:
        battery = home.battery_config
        assert (battery.capacity_kwh, battery.max_discharge_kw) == (5.0, 2.5)
        assert Battery(battery).min_soc_kwh == pytest.approx(0.5)
    n = len(battery_homes)
    hours = pd.date_range("2024-01-08", periods=48, freq="1h", tz="Europe/London")
    window_hours = hours.hour.isin([16, 17, 18])
    sim = dataclasses.replace(
        _make_spare_battery_sim_results(hours=hours),
        battery_soc=pd.Series(3.5, index=hours).mask((hours.day == 8) & window_hours, 0.5),
        battery_discharge=pd.Series(0.0, index=hours)
        .mask(window_hours, 0.5)
        .mask(hours.hour.isin([19, 20]), 1.0),
        battery_charge=pd.Series(0.0, index=hours).mask(hours.hour == 21, 1.0),
        tariff_rate=pd.Series(0.25, index=hours),
    )
    fr = make_fleet_results_of([sim for _ in scenario.homes], homes=scenario.homes)

    result = invoke_finance_run(
        [str(SCENARIO), "--flex-band", "central", "--start", "2024-01-08", "--end", "2024-01-09"], fr
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for row in (
        f"| Annual fleet income | £{n / 2 * 9.972:,.0f} |",
        f"| Per-event available capacity | {n / 2:.1f} kW |",
        f"| Capacity on 50% of event days | {float(n):.1f} kW |",
        "| Capacity on 90% of event days | 0.0 kW |",
        f"| Evening self-use displaced, per event | {float(n):.1f} kWh |",
        f"| Evening self-use displaced, value per year | £{3 * n:,.0f} |",
    ):
        assert row in lines, result.output


# ---------------------------------------------------------------------------
# B10, B11 — the booked income renders with the economics; the flex row reads it
# ---------------------------------------------------------------------------


_TWO_JANUARY_WEEKDAYS = pd.date_range("2024-01-08", periods=2 * 24 * 60, freq="1min", tz="Europe/London")
"""Monday 8 and Tuesday 9 January 2024, two winter-weekday event days, at one minute: the window simulate_home runs, so
finance run's projection answers its age-0 fleet from the bill run's results (fleet.reusing refuses any other)."""

_WINDOW_HEADING = "### This window's fleet, the same under every assumption"
_BOOKED_HEADING = "### Booked by the projection (£ a year)"


def _board_scenario_without_its_flex_band(tmp_path: Path) -> Path:
    """A copy of the board scenario under *tmp_path* with its top-level flex_band deleted."""
    document = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
    del document["flex_band"]
    path = tmp_path / SCENARIO.name
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _soh_tracking_january_simulate(
    answered: list[FleetResults], by_age: dict[int, FleetResults]
) -> Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]:
    """A simulate answering each home over _TWO_JANUARY_WEEKDAYS with its battery at 0.8 × capacity × its SOH.

    It appends each answer to *answered*, in the order asked, and keys it in
    *by_age* by the age of the fleet's PV.
    """

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        per_home = []
        for home in fleet_config.homes:
            battery = home.battery_config
            assert battery is not None, home
            soc_kwh = 0.8 * battery.capacity_kwh * battery.resolved_soh
            per_home.append(_make_spare_battery_sim_results(hours=_TWO_JANUARY_WEEKDAYS, battery_soc_kwh=soc_kwh))
        results = make_fleet_results_of(per_home, homes=fleet_config.homes)
        answered.append(results)
        by_age[int(fleet_config.homes[0].pv_config.system_age_years)] = results
        return results

    return simulate


def test_b10_finance_run_renders_the_booked_grid_services_income_with_the_economics(tmp_path: Path) -> None:
    """finance run --project --assumptions both on the board scenario without a flex band renders the Grid Services Income section.

    Its model line names the pricing; each mode's booked year-1 and year-N
    income is the pricing of the fleet that mode's projection simulated at
    ages 0 and N − 1; this window's table is the bill run's breakdown.
    """
    path = _board_scenario_without_its_flex_band(tmp_path)
    _scenario, finance = board_econ_scenario()
    pricing = finance.grid_services_events
    assert pricing is not None
    answered: list[FleetResults] = []
    by_age: dict[int, FleetResults] = {}

    result = invoke_cli(
        ["finance", "run", str(path), "--project", "--assumptions", "both", "--start", "2024-01-08", "--end", "2024-01-09"],
        answering(_soh_tracking_january_simulate(answered, by_age)),
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "## Grid Services Income" in lines, result.output
    assert "Model: **capacity at events, central band, operational delivery baseline**" in lines, result.output

    breakdown = compute_grid_services_at_events(answered[0], pricing)
    assert len(breakdown.per_window_avail_kw) == 1
    for label, cell in (
        ("Annual fleet income", f"£{breakdown.annual_income_gbp:,.0f}"),
        ("Capacity on 50% of event days", f"{breakdown.per_window_avail_p50_kw[0]:.1f} kW"),
        ("Capacity on 90% of event days", f"{breakdown.per_window_avail_p90_kw[0]:.1f} kW"),
        ("Evening self-use displaced, per event", f"{breakdown.per_window_displaced_self_use_kwh_per_event[0]:.1f} kWh"),
        ("Evening self-use displaced, value per year", f"£{sum(breakdown.per_window_displaced_import_gbp_per_year):,.0f}"),
    ):
        assert row_cells(result.output, _WINDOW_HEADING, label) == [cell], label
    assert "gross of the evening self-use an event displaces" in result.output

    last_year = finance.asset_life_years
    year_1, year_n = pricing.annual_income_gbp(by_age[0]), pricing.annual_income_gbp(by_age[last_year - 1])
    assert year_n < year_1
    assert f"£{year_n:,.0f}" != f"£{year_1:,.0f}"
    assert row_cells(result.output, _BOOKED_HEADING, "Year 1") == [f"£{year_1:,.0f}"] * 2
    assert row_cells(result.output, _BOOKED_HEADING, f"Year {last_year}") == [f"£{year_n:,.0f}"] * 2
    assert "Flexibility Value" not in result.output


def test_b11_the_flex_blocks_grid_services_row_reads_the_booked_events_income() -> None:
    """finance run --flex-band central on the board scenario: the grid-services row is the events income per battery home and per kW."""
    scenario, finance = board_econ_scenario()
    assert finance.grid_services_events is not None
    fr = _synthetic_fleet_results_in_window(list(scenario.homes))
    batteries = [home.battery_config for home in scenario.homes if home.battery_config is not None]
    income = compute_grid_services_at_events(fr, finance.grid_services_events).annual_income_gbp
    homes, kw = len(batteries), sum(battery.max_discharge_kw for battery in batteries)
    assert income > 0.0

    result = invoke_finance_run([str(SCENARIO), "--flex-band", "central"], fr)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert f"| Grid services (booked) | £{income / homes:.0f} | £{income / kw:.1f}/kW |" in lines, result.output
    assert f"| **Headline total** | **£{250 + income / homes:.0f}** | — |" in lines, result.output
    assert "PRD §6" not in result.output
