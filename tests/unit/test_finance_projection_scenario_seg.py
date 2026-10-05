# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for scenario-level SEG.

_reconcile_seg_homes threads ScenarioConfig.seg_tariff_pence_per_kwh onto the
homes and refuses an inconsistent per-home rate, and project_multi_year and
solve_cost_recovery_rate honour the scenario rate.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests._finance_builders import make_home_config


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
        from solar_challenge.config import ScenarioConfig, SimulationPeriod
        from solar_challenge.finance import FinanceConfig
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

        from solar_challenge.config import ScenarioConfig, SimulationPeriod
        from solar_challenge.finance import FinanceConfig, project_multi_year
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
