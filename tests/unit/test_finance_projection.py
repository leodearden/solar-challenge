# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year, the multi-year projection's forward-march driver.

The projection runs on an injected synthetic simulate.  The tests cover the
curve's shape and energy aggregation, scenario-level SEG and short-window
annualisation, and the projection's SEG helper _reconcile_seg_homes.

All tests are offline/fast — no PVGIS/network is touched.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_load_config,
    make_pv_config,
    make_scenario_and_finance,
    make_sim_results,
)


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        from solar_challenge.finance import MultiYearCurve, project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_self_consumption_at_sampled_age(self) -> None:
        """fleet_self_consumption_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

        # Compute expected total from calculate_summary
        expected_sc = sum(
            calculate_summary(r).total_self_consumption_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)

        # At age 0 (a seed point), the value should match the injected summary
        assert curve.points[0].fleet_self_consumption_kwh == pytest.approx(
            expected_sc, rel=1e-4
        )

    def test_fleet_export_at_sampled_age(self) -> None:
        """fleet_export_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        exp_per_home = 500.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, export_kwh=exp_per_home)

        expected_export = sum(
            calculate_summary(r).total_grid_export_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_export_kwh == pytest.approx(expected_export, rel=1e-4)

    def test_fleet_import_at_sampled_age(self) -> None:
        """fleet_import_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        imp_per_home = 200.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, import_kwh=imp_per_home)

        expected_import = sum(
            calculate_summary(r).total_grid_import_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_import_kwh == pytest.approx(expected_import, rel=1e-4)


class TestReconcileSegHomes:
    """Unit tests for the _reconcile_seg_homes pure helper."""

    def test_none_scenario_rate_returns_homes_unchanged(self) -> None:
        """(a) When scenario_seg_rate is None, return the homes list unchanged."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]

        home = make_home_config()
        result = _reconcile_seg_homes([home], scenario_seg_rate=None)
        assert result == [home]
        assert result[0] is home  # same object, no copy

    def test_none_seg_home_gets_tariff_threaded(self) -> None:
        """(b) Home with seg_tariff=None + scenario_seg_rate=6.0 → seg_tariff set to SEGTariff(6.0).

        Other HomeConfig fields (pv_config, load_config, location, battery_config)
        are preserved unchanged via dataclasses.replace semantics.
        """
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        home = make_home_config()
        assert home.seg_tariff is None  # pre-condition

        result = _reconcile_seg_homes([home], scenario_seg_rate=6.0)
        assert len(result) == 1
        updated = result[0]
        # seg_tariff is threaded
        assert updated.seg_tariff is not None
        assert isinstance(updated.seg_tariff, SEGTariff)
        assert updated.seg_tariff.rate_pence_per_kwh == pytest.approx(6.0)
        # other fields preserved
        assert updated.pv_config == home.pv_config
        assert updated.load_config == home.load_config
        assert updated.location == home.location
        assert updated.battery_config == home.battery_config
        # input not mutated
        assert home.seg_tariff is None

    def test_home_with_existing_seg_and_none_scenario_rate_unchanged(self) -> None:
        """(c) Home with seg_tariff=SEGTariff(4.0) + scenario_seg_rate=None → unchanged."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="export", rate_pence_per_kwh=4.0)
        home = dataclasses.replace(make_home_config(), seg_tariff=tariff)
        result = _reconcile_seg_homes([home], scenario_seg_rate=None)
        assert result == [home]
        assert result[0].seg_tariff is tariff

    def test_consistent_rate_no_raise_home_unchanged(self) -> None:
        """(d) Home seg=SEGTariff(6.0) + scenario_seg_rate=6.0 (CLI-style) → no raise, same home."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="", rate_pence_per_kwh=6.0)
        home = dataclasses.replace(make_home_config(), seg_tariff=tariff)
        # Must not raise; home is returned as-is (rates match)
        result = _reconcile_seg_homes([home], scenario_seg_rate=6.0)
        assert len(result) == 1
        assert result[0] is home

    def test_inconsistent_rate_raises_value_error(self) -> None:
        """(e) Home seg=SEGTariff(4.0) + scenario_seg_rate=6.0 → raises ValueError naming both rates."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="", rate_pence_per_kwh=4.0)
        home = dataclasses.replace(make_home_config(), seg_tariff=tariff)
        import re

        with pytest.raises(ValueError, match=re.compile(r"inconsistent.*SEG", re.IGNORECASE)):
            _reconcile_seg_homes([home], scenario_seg_rate=6.0)


def _seg_aware_fleet_results_factory(
    self_kwh: float = 5.0,
    export_kwh: float = 5.0,
    import_kwh: float = 3.0,
    n_minutes: int = 1440,
) -> "Callable":  # type: ignore[name-defined]
    """Return a simulate closure that prices export_revenue from each home's seg_tariff.

    Mirrors home.py:336-349 (Task-85 zeroing): export_revenue is non-zero only
    when home.seg_tariff is set, summing to export_kwh × rate/100 per home.
    The kWh arguments are for the simulated period; _annualise_physics handles
    scaling to 365 days.  Use as ``simulate=lambda fc, s, e: factory(fc)``.
    """
    from typing import Callable  # noqa: F401

    def _simulate(
        fleet_config: "FleetConfig",  # type: ignore[name-defined]
        start: "pd.Timestamp",  # type: ignore[name-defined]
        end: "pd.Timestamp",  # type: ignore[name-defined]
    ) -> "FleetResults":  # type: ignore[name-defined]
        import pandas as pd
        from solar_challenge.fleet import FleetResults
        from solar_challenge.home import SimulationResults

        idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
        sc_kw = self_kwh / (n_minutes / 60.0)
        exp_kw = export_kwh / (n_minutes / 60.0)
        imp_kw = import_kwh / (n_minutes / 60.0)
        gen_kw = sc_kw + exp_kw
        demand_kw = sc_kw + imp_kw
        zeros = pd.Series(0.0, index=idx)

        per_home = []
        for home in fleet_config.homes:
            # Price export_revenue from seg_tariff if set (mirrors Task-85 zeroing in home.py)
            if home.seg_tariff is not None:
                rev_per_min = exp_kw / 60.0 * home.seg_tariff.rate_pence_per_kwh / 100.0
                export_rev: "pd.Series" = pd.Series(rev_per_min, index=idx)
            else:
                export_rev = zeros.copy()

            per_home.append(SimulationResults(
                generation=pd.Series(gen_kw, index=idx),
                demand=pd.Series(demand_kw, index=idx),
                self_consumption=pd.Series(sc_kw, index=idx),
                battery_charge=zeros.copy(),
                battery_discharge=zeros.copy(),
                battery_soc=zeros.copy(),
                grid_import=pd.Series(imp_kw, index=idx),
                grid_export=pd.Series(exp_kw, index=idx),
                import_cost=zeros.copy(),
                export_revenue=export_rev,
                tariff_rate=zeros.copy(),
            ))

        return FleetResults(per_home_results=per_home, home_configs=list(fleet_config.homes))

    return _simulate


class TestProjectHonoursScenarioLevelSeg:
    """Integration tests: project_multi_year and solve_cost_recovery_rate
    must honour ScenarioConfig.seg_tariff_pence_per_kwh."""

    _SEG_RATE = 6.0
    _N_HOMES = 2

    def _make_three_scenarios(self) -> tuple:
        """Build three ScenarioConfigs and shared FinanceConfig.

        Returns (scenario_seg, home_ref, baseline_none, finance) where:
        - scenario_seg: homes have seg_tariff=None, scenario rate=_SEG_RATE
        - home_ref: homes have seg_tariff=SEGTariff(_SEG_RATE), scenario rate=None
        - baseline_none: homes have seg_tariff=None, scenario rate=None
        - finance: shared FinanceConfig with default grant/loan params
        """
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.seg import SEGTariff

        homes_no_seg = [make_home_config() for _ in range(self._N_HOMES)]
        homes_with_seg = [
            dataclasses.replace(h, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=self._SEG_RATE))
            for h in homes_no_seg
        ]
        period = SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31")
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            loan_term_years=15,
            retail_baseline_rate_pence_per_kwh=30.0,
            vat_rate=0.05,
        )
        scenario_seg = ScenarioConfig(
            name="test-seg",
            period=period,
            description="Scenario-level SEG",
            homes=homes_no_seg,
            seg_tariff_pence_per_kwh=self._SEG_RATE,
        )
        home_ref = ScenarioConfig(
            name="test-home-ref",
            period=period,
            description="Per-home SEG",
            homes=homes_with_seg,
        )
        baseline_none = ScenarioConfig(
            name="test-baseline",
            period=period,
            description="No SEG",
            homes=homes_no_seg,
        )
        return scenario_seg, home_ref, baseline_none, finance

    def test_project_multi_year_honours_scenario_level_seg(self) -> None:
        """project_multi_year: scenario_seg fleet_revenue equals home_ref at year 0 (non-vacuous).

        scenario_seg (homes seg=None, scenario rate=R) must produce the same
        fleet_revenue_gbp as home_ref (homes seg=SEGTariff(R), scenario rate=None)
        after _reconcile_seg_homes threads the tariff onto homes.
        Both must exceed baseline_none (no SEG at all) — proving the SEG
        income is load-bearing.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario_seg, home_ref, baseline_none, finance = self._make_three_scenarios()
        sim = _seg_aware_fleet_results_factory()

        curve_seg = project_multi_year(scenario_seg, finance, simulate=sim)
        curve_ref = project_multi_year(home_ref, finance, simulate=sim)
        curve_base = project_multi_year(baseline_none, finance, simulate=sim)

        rev_seg = curve_seg.points[0].fleet_revenue_gbp
        rev_ref = curve_ref.points[0].fleet_revenue_gbp
        rev_base = curve_base.points[0].fleet_revenue_gbp

        # Equivalence: scenario-level SEG must produce the same revenue as per-home SEG
        assert rev_seg == pytest.approx(rev_ref, rel=1e-6), (
            f"scenario_seg revenue {rev_seg:.4f} != home_ref revenue {rev_ref:.4f}; "
            "project_multi_year must reconcile scenario.seg_tariff_pence_per_kwh onto homes"
        )
        # Non-vacuousness: SEG income must raise fleet_revenue vs no-SEG baseline
        assert rev_ref > rev_base, (
            f"SEG income must increase fleet_revenue vs no-SEG baseline "
            f"(home_ref={rev_ref:.4f}, baseline={rev_base:.4f})"
        )

    def test_solve_cost_recovery_rate_honours_scenario_level_seg(self) -> None:
        """solve_cost_recovery_rate: scenario_seg solution equals home_ref (non-vacuous).

        Asserts equivalence on (own_use_rate, net_surplus, binding, feasible).
        Also asserts that home_ref differs from baseline_none on at least one
        of {own_use_rate, net_surplus} — proving SEG is load-bearing regardless
        of the binding regime (no tuned numeric threshold needed; equality is
        two code paths computing export_kwh × rate / 100).
        """
        import math

        from solar_challenge.finance import solve_cost_recovery_rate  # type: ignore[attr-defined]

        scenario_seg, home_ref, baseline_none, finance = self._make_three_scenarios()
        sim = _seg_aware_fleet_results_factory()

        sol_seg = solve_cost_recovery_rate(scenario_seg, finance, simulate=sim)
        sol_ref = solve_cost_recovery_rate(home_ref, finance, simulate=sim)
        sol_base = solve_cost_recovery_rate(baseline_none, finance, simulate=sim)

        # Equivalence: scenario-level SEG must produce the same solve as per-home SEG
        assert sol_seg.own_use_rate_pence_per_kwh == pytest.approx(
            sol_ref.own_use_rate_pence_per_kwh, rel=1e-6
        ), (
            f"own_use_rate: scenario_seg={sol_seg.own_use_rate_pence_per_kwh:.4f} "
            f"!= home_ref={sol_ref.own_use_rate_pence_per_kwh:.4f}"
        )
        assert sol_seg.net_surplus_per_home_per_year_gbp == pytest.approx(
            sol_ref.net_surplus_per_home_per_year_gbp, rel=1e-6
        ), (
            f"net_surplus: scenario_seg={sol_seg.net_surplus_per_home_per_year_gbp:.4f} "
            f"!= home_ref={sol_ref.net_surplus_per_home_per_year_gbp:.4f}"
        )
        assert sol_seg.binding == sol_ref.binding, (
            f"binding: scenario_seg={sol_seg.binding!r} != home_ref={sol_ref.binding!r}"
        )
        assert sol_seg.feasible == sol_ref.feasible, (
            f"feasible: scenario_seg={sol_seg.feasible} != home_ref={sol_ref.feasible}"
        )
        # Outlay-path equivalence: representative_outlay and saving both flow through
        # the solve's age-0 outlay path; assert they match so a future
        # regression where the outlay path is export-dependent cannot go undetected.
        assert sol_seg.representative_outlay_gbp == pytest.approx(
            sol_ref.representative_outlay_gbp, rel=1e-6
        ), (
            f"representative_outlay: scenario_seg={sol_seg.representative_outlay_gbp:.4f} "
            f"!= home_ref={sol_ref.representative_outlay_gbp:.4f}"
        )
        assert sol_seg.saving_vs_baseline_gbp == pytest.approx(
            sol_ref.saving_vs_baseline_gbp, rel=1e-6
        ), (
            f"saving_vs_baseline: scenario_seg={sol_seg.saving_vs_baseline_gbp:.4f} "
            f"!= home_ref={sol_ref.saving_vs_baseline_gbp:.4f}"
        )

        # Non-vacuousness: SEG income must affect at least one solve metric vs no-SEG baseline
        rate_differs = not math.isclose(
            sol_ref.own_use_rate_pence_per_kwh,
            sol_base.own_use_rate_pence_per_kwh,
            rel_tol=1e-4,
            abs_tol=1e-6,
        )
        surplus_differs = not math.isclose(
            sol_ref.net_surplus_per_home_per_year_gbp,
            sol_base.net_surplus_per_home_per_year_gbp,
            rel_tol=1e-4,
            abs_tol=1e-6,
        )
        assert rate_differs or surplus_differs, (
            f"SEG income must change own_use_rate or net_surplus vs no-SEG baseline "
            f"(home_ref: rate={sol_ref.own_use_rate_pence_per_kwh:.4f}p, "
            f"surplus={sol_ref.net_surplus_per_home_per_year_gbp:.4f}; "
            f"baseline: rate={sol_base.own_use_rate_pence_per_kwh:.4f}p, "
            f"surplus={sol_base.net_surplus_per_home_per_year_gbp:.4f})"
        )

    def test_inconsistent_seg_inputs_raise_through_projection(self) -> None:
        """project_multi_year raises ValueError when per-home seg_tariff != scenario rate."""
        import re

        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        homes_inconsistent = [
            dataclasses.replace(
                make_home_config(),
                seg_tariff=SEGTariff(name="", rate_pence_per_kwh=4.0),
            )
            for _ in range(self._N_HOMES)
        ]
        scenario_inconsistent = ScenarioConfig(
            name="test-inconsistent",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Inconsistent SEG",
            homes=homes_inconsistent,
            seg_tariff_pence_per_kwh=6.0,  # 6.0 != 4.0 → should raise
        )
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            loan_term_years=15,
        )
        sim = _seg_aware_fleet_results_factory()

        with pytest.raises(ValueError, match=re.compile(r"inconsistent.*SEG", re.IGNORECASE)):
            project_multi_year(scenario_inconsistent, finance, simulate=sim)


_SHORT_WINDOW_DAYS = 3


def _make_full_year_and_short_window_fleets() -> tuple:
    """Return (scenario, finance, battery_config, fleet_full_year, fleet_short).

    Two battery homes at the same daily rates over a full year and over a
    _SHORT_WINDOW_DAYS window, so the short fleet's kWh and SEG £ totals are
    the annual ones × _SHORT_WINDOW_DAYS / 365.  Inject either fleet with
    ``simulate=lambda fc, s, e: fleet``.
    """
    from solar_challenge.battery import BatteryConfig
    from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
    from solar_challenge.fleet import FleetResults
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    battery_config = BatteryConfig(
        capacity_kwh=10.0,
        max_charge_kw=3.5,
        max_discharge_kw=3.5,
        calendar_fade_rate_per_year=0.005,
        cycle_fade_per_equivalent_full_cycle=0.0002,
        soh_floor=0.60,
    )
    homes = [
        HomeConfig(
            pv_config=make_pv_config(),
            load_config=make_load_config(),
            location=Location.bristol(),
            battery_config=battery_config,
        )
        for _ in range(2)
    ]
    scenario = ScenarioConfig(
        name="short-window-test",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Short-window annualisation test",
        homes=homes,
    )
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=25,
        grid_services_income_per_kw_per_year_gbp=10.0,
    )

    def fleet_over(window_days: int) -> "FleetResults":  # type: ignore[name-defined]
        share_of_year = window_days / 365
        return FleetResults(
            per_home_results=[
                make_sim_results(
                    self_kwh=3000.0 * share_of_year,
                    export_kwh=1000.0 * share_of_year,
                    import_kwh=500.0 * share_of_year,
                    discharge_kwh=800.0 * share_of_year,
                    export_revenue_gbp=150.0 * share_of_year,
                    days=window_days,
                )
                for _ in homes
            ],
            home_configs=homes,
        )

    return scenario, finance, battery_config, fleet_over(365), fleet_over(_SHORT_WINDOW_DAYS)


class TestProjectMultiYearAnnualisesShortWindow:
    """A window under 360 days projects as the 365-day year it samples.

    project_multi_year scales each home's window totals to a 365-day year, so a
    short window at the same daily rates as a full year gives the same curve, with
    or without the override, and under the override its own-use is the one
    householder_bill charges for that year.  It warns once per projection that it
    annualised.
    """

    @pytest.mark.parametrize(
        "self_consumption_override",
        [
            pytest.param(None, id="physics"),
            pytest.param(0.5, id="override-cap-not-binding"),
            pytest.param(0.9, id="override-cap-binding"),
        ],
    )
    def test_short_window_projects_the_equivalent_full_year_curve(
        self, self_consumption_override: "float | None"
    ) -> None:
        """Every YearPoint field, energy, revenue and SOH alike, matches the full-year curve."""
        from solar_challenge.finance import project_multi_year
        from solar_challenge.home import calculate_summary

        scenario, finance, battery_config, fleet_full_year, fleet_short = (
            _make_full_year_and_short_window_fleets()
        )
        finance = dataclasses.replace(finance, self_consumption_override=self_consumption_override)
        short_summary = calculate_summary(fleet_short.per_home_results[0])
        assert short_summary.simulation_days == _SHORT_WINDOW_DAYS
        assert short_summary.total_export_revenue_gbp > 0.0, "premise: the window earns SEG income"

        curve_full = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_full_year)
        curve_short = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short)

        # Premise: SOH stays above the floor, so window-length discharge would show as higher SOH.
        assert curve_full.points[-1].battery_soh > battery_config.soh_floor
        assert curve_short.sampled_ages == curve_full.sampled_ages
        for short, full in zip(curve_short.points, curve_full.points, strict=True):
            assert dataclasses.asdict(short) == pytest.approx(dataclasses.asdict(full), rel=1e-9)

    @pytest.mark.parametrize(
        ("self_consumption_override", "annual_own_use_kwh"),
        [
            pytest.param(0.5, 2000.0, id="cap-not-binding"),
            pytest.param(0.9, 2700.0, id="cap-binding"),
        ],
    )
    def test_short_window_override_own_use_is_what_the_annual_bills_charge(
        self, self_consumption_override: float, annual_own_use_kwh: float
    ) -> None:
        """Under the override, year 0's own-use is the annual own-use householder_bill charges.

        Each home generates 4,000 kWh and demands 2,700 kWh a year, so the override bills
        min(override × 4,000, 2,700) kWh a year.  The projection and householder_bill both
        start from the 3-day window's summary, so both must annualise it.
        """
        import warnings

        from solar_challenge.finance import householder_bill, project_multi_year
        from solar_challenge.home import calculate_summary

        scenario, finance, _, fleet_full_year, fleet_short = _make_full_year_and_short_window_fleets()
        finance = dataclasses.replace(finance, self_consumption_override=self_consumption_override)
        annual = calculate_summary(fleet_full_year.per_home_results[0])
        assert (annual.total_generation_kwh, annual.total_demand_kwh) == pytest.approx((4000.0, 2700.0))
        summaries = [calculate_summary(r) for r in fleet_short.per_home_results]
        assert {s.simulation_days for s in summaries} == {_SHORT_WINDOW_DAYS}

        with warnings.catch_warnings():
            # The short window, the missing tariff and the cap all warn; none is under test here.
            warnings.simplefilter("ignore", UserWarning)
            year_0 = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short).points[0]
            bills = [
                householder_bill(
                    s,
                    annual_self_consumption_kwh=s.total_demand_kwh - s.total_grid_import_kwh,
                    finance=finance,
                    simulation_days=s.simulation_days,
                )
                for s in summaries
            ]

        billed_own_use_kwh = (
            sum(b.own_use_payment_gbp for b in bills) * 100.0 / finance.own_use_rate_pence_per_kwh
        )
        assert billed_own_use_kwh == pytest.approx(len(summaries) * annual_own_use_kwh)
        assert year_0.fleet_self_consumption_kwh == pytest.approx(billed_own_use_kwh)

    def test_short_window_warns_once_naming_the_window(self) -> None:
        """Annualising a short window raises one UserWarning per projection, naming its days."""
        import re

        from solar_challenge.finance import project_multi_year

        scenario, finance, _, _, fleet_short = _make_full_year_and_short_window_fleets()
        names_the_window = re.compile(rf"\b{_SHORT_WINDOW_DAYS} days\b")

        with pytest.warns(UserWarning, match=names_the_window) as record:
            curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short)

        # Premise: several ages are simulated, so a warning raised per node would repeat.
        assert len(curve.sampled_ages) >= 3
        window_warnings = [
            str(w.message) for w in record if names_the_window.search(str(w.message))
        ]
        assert len(window_warnings) == 1, window_warnings

    def test_full_year_window_does_not_warn(self) -> None:
        """A full-year window is not annualised, so a board run stays warning-free."""
        import warnings

        from solar_challenge.finance import project_multi_year

        scenario, finance, _, fleet_full_year, _ = _make_full_year_and_short_window_fleets()

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_full_year)

        assert [str(w.message) for w in record if issubclass(w.category, UserWarning)] == []
