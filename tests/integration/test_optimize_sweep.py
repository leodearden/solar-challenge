# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for run_sweep + ConfigResult/RankedSweep (W3, task B/#65).

All tests are offline/fast — no PVGIS/network is touched.  An injected synthetic
simulate (constant or pv-varying FleetResults) stands in for the real fleet
simulator.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import pandas as pd
import pytest

from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import (
    CostRecoverySolution,
    FinanceConfig,
    bill_distribution,
    project_economics,
    project_multi_year,
    solve_cost_recovery_rate,
)
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.home import calculate_summary
from solar_challenge.optimize import (
    ConfigPoint,
    ConfigResult,
    RankedSweep,
    enumerate_configs,
    pareto_baseline,
    run_sweep,
)
from tests._factories import make_config_result, make_cost_recovery_solution
from tests._finance_builders import make_fleet_results, make_scenario


# ---------------------------------------------------------------------------
# Offline scaffolding: the finance builders, this module's pinned scenario and
# fleet results over tests/_finance_builders.py
# ---------------------------------------------------------------------------


def _make_fleet_results(n_homes: int = 5, export_revenue_gbp: float = 0.0) -> FleetResults:
    """*n_homes* default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year."""
    return make_fleet_results(
        n_homes=n_homes,
        self_kwh=2000.0,
        export_kwh=800.0,
        import_kwh=1200.0,
        export_revenue_gbp=export_revenue_gbp,
    )


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    asset_life_years: int = 25,
) -> FinanceConfig:
    return FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life_years,
        loan_term_years=min(asset_life_years, 15),
        own_use_rate_pence_per_kwh=own_use_rate_pence_per_kwh,
        retained_cash_floor_per_home_per_year_gbp=retained_cash_floor,
        retail_baseline_rate_pence_per_kwh=retail_baseline_rate,
        pv_cost_per_kwp_gbp=pv_cost_per_kwp_gbp,
        grant_gbp=grant_gbp,
        vat_rate=0.05,
    )


def _make_scenario(n_homes: int = 5, finance: FinanceConfig | None = None) -> ScenarioConfig:
    """make_scenario's *n_homes* default homes carrying *finance*, pinned to a 5 p/kWh scenario SEG rate."""
    return make_scenario(n_homes=n_homes, seg_tariff_pence_per_kwh=5.0, finance=finance)


def _interior_finance(n_homes: int = 5) -> FinanceConfig:
    """Finance params that produce an interior 'floor' solve."""
    return _make_finance(
        pv_cost_per_kwp_gbp=2000.0,
        grant_gbp=0.0,
        own_use_rate_pence_per_kwh=15.0,
        retained_cash_floor=100.0,
        retail_baseline_rate=30.0,
    )


# ---------------------------------------------------------------------------
# step-01/02 — TestConfigResult: frozen dataclass construction
# ---------------------------------------------------------------------------


class TestConfigResult:
    """ConfigResult frozen dataclass construction and validation."""

    def test_all_fields_read_back(self) -> None:
        """All fields read back correctly after construction."""
        config = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        solution = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0,
            feasible=True,
            binding="floor",
            representative_outlay_gbp=400.0,
            net_surplus_per_home_per_year_gbp=100.0,
        )
        cr = ConfigResult(
            config=config,
            solution=solution,
            representative_outlay_gbp=400.0,
            solved_own_use_rate_pence_per_kwh=15.0,
            surplus_at_solved_gbp=100.0,
            feasible=True,
            binding="floor",
            total_capex_gbp=10000.0,
            min_dscr=1.5,
            equity_irr=0.08,
            payback_years=12.0,
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=80.0,
        )

        assert cr.config is config
        assert cr.solution is solution
        assert cr.representative_outlay_gbp == pytest.approx(400.0)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(15.0)
        assert cr.surplus_at_solved_gbp == pytest.approx(100.0)
        assert cr.feasible is True
        assert cr.binding == "floor"
        assert cr.total_capex_gbp == pytest.approx(10000.0)
        assert cr.min_dscr == pytest.approx(1.5)
        assert cr.equity_irr == pytest.approx(0.08)
        assert cr.payback_years == pytest.approx(12.0)
        assert cr.baseline_outlay_gbp == pytest.approx(450.0)
        assert cr.baseline_surplus_per_home_gbp == pytest.approx(80.0)

    def test_payback_years_none_allowed(self) -> None:
        """payback_years=None is a valid sentinel (never pays back within asset life)."""
        cr = make_config_result(payback_years=None)
        assert cr.payback_years is None

    def test_min_dscr_inf_allowed(self) -> None:
        """min_dscr=inf is allowed (debt-free project)."""
        cr = make_config_result(min_dscr=float("inf"))
        assert math.isinf(cr.min_dscr)

    def test_equity_irr_nan_allowed(self) -> None:
        """equity_irr=nan is allowed (undefined IRR for zero-equity project)."""
        cr = make_config_result(equity_irr=float("nan"))
        assert math.isnan(cr.equity_irr)

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning any field raises dataclasses.FrozenInstanceError."""
        cr = make_config_result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cr.representative_outlay_gbp = 999.0  # type: ignore[misc]

    def test_config_point_accessible(self) -> None:
        """config.pv_kwp / battery_kwh / inverter_kw match the constructed values."""
        cr = make_config_result(pv_kwp=5.0, battery_kwh=10.0, inverter_kw=4.6)
        assert cr.config.pv_kwp == pytest.approx(5.0)
        assert cr.config.battery_kwh == pytest.approx(10.0)
        assert cr.config.inverter_kw == pytest.approx(4.6)

    def test_solution_field_accessible(self) -> None:
        """solution.own_use_rate_pence_per_kwh is readable through the ConfigResult."""
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=18.5, feasible=True, binding="floor", representative_outlay_gbp=400.0
        )

        cr = ConfigResult(
            config=ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6),
            solution=sol,
            representative_outlay_gbp=400.0,
            solved_own_use_rate_pence_per_kwh=18.5,
            surplus_at_solved_gbp=100.0,
            feasible=True,
            binding="floor",
            total_capex_gbp=10000.0,
            min_dscr=1.5,
            equity_irr=0.08,
            payback_years=12.0,
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=80.0,
        )
        assert cr.solution.own_use_rate_pence_per_kwh == pytest.approx(18.5)


# ---------------------------------------------------------------------------
# step-03/04 — TestRankedSweep: frozen dataclass construction
# ---------------------------------------------------------------------------


class TestRankedSweep:
    """RankedSweep frozen dataclass construction and validation."""

    def _make_one_feasible(self) -> ConfigResult:
        return make_config_result(
            pv_kwp=4.0,
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
        )

    def test_fields_read_back(self) -> None:
        """All fields read back after construction."""
        cr = self._make_one_feasible()
        infeasible_pt = ConfigPoint(pv_kwp=8.0, battery_kwh=10.0, inverter_kw=5.0)
        pareto_pt = cr.config

        rs = RankedSweep(
            results=(cr,),
            infeasible=(infeasible_pt,),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(pareto_pt,),
        )

        assert rs.results == (cr,)
        assert rs.infeasible == (infeasible_pt,)
        assert rs.retained_cash_floor_gbp == pytest.approx(100.0)
        assert rs.cheapest_feasible is cr.config
        assert rs.pareto_baseline == (pareto_pt,)

    def test_cheapest_feasible_equals_results_0_config(self) -> None:
        """When results non-empty, cheapest_feasible must equal results[0].config."""
        cr = self._make_one_feasible()
        rs = RankedSweep(
            results=(cr,),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(),
        )
        assert rs.cheapest_feasible is rs.results[0].config

    def test_cheapest_feasible_none_when_results_empty(self) -> None:
        """When results is empty, cheapest_feasible must be None."""
        rs = RankedSweep(
            results=(),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=None,
            pareto_baseline=(),
        )
        assert rs.cheapest_feasible is None

    def test_cheapest_feasible_mismatch_raises_value_error(self) -> None:
        """cheapest_feasible != results[0].config raises ValueError."""
        cr = self._make_one_feasible()
        wrong = ConfigPoint(pv_kwp=99.0, battery_kwh=0.0, inverter_kw=99.0)
        with pytest.raises(ValueError):
            RankedSweep(
                results=(cr,),
                infeasible=(),
                retained_cash_floor_gbp=100.0,
                cheapest_feasible=wrong,
                pareto_baseline=(),
            )

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning any field raises dataclasses.FrozenInstanceError."""
        cr = self._make_one_feasible()
        rs = RankedSweep(
            results=(cr,),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rs.retained_cash_floor_gbp = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# step-05/06 — W-H1 seam: single config, run_sweep vs direct W2 primitives
# ---------------------------------------------------------------------------


class TestRunSweepSingleConfig:
    """W-H1 seam: single config numbers equal direct W2 primitive calls."""

    def _setup(self) -> tuple:  # type: ignore[type-arg]
        """Return (scenario, finance, fake_fr, simulate, configs)."""
        n_homes = 5
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )
        return scenario, finance, fr, simulate, configs

    def test_solve_fields_match_direct_w2(self) -> None:
        """representative_outlay / solved_rate / surplus / feasible / binding == sol.*"""
        scenario, finance, fr, simulate, configs = self._setup()

        ranked = run_sweep(configs, simulate=simulate)
        assert len(ranked.results) == 1

        cr = ranked.results[0]

        # Direct W2 call for comparison: use configs[0][1] (the scenario after
        # enumerate_configs applied the install — homes may have been modified, e.g.
        # battery fabricated from battery_kwh=6.0 on homes that had no battery).
        # The finance block is preserved from the base scenario by enumerate_configs.
        sweep_scenario = configs[0][1]
        sol = solve_cost_recovery_rate(sweep_scenario, finance, simulate=simulate)

        assert cr.representative_outlay_gbp == pytest.approx(sol.representative_outlay_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(
            sol.own_use_rate_pence_per_kwh
        )
        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.feasible == sol.feasible
        assert cr.binding == sol.binding

    def test_solution_field_is_cost_recovery_solution(self) -> None:
        """result.solution is a CostRecoverySolution."""
        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert isinstance(ranked.results[0].solution, CostRecoverySolution)

    def test_baseline_econ_fields_match_direct_w2(self) -> None:
        """total_capex / min_dscr / equity_irr / payback_years match project_economics."""
        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        # Use configs[0][1] — the same scenario run_sweep uses (homes may differ
        # after _apply_install, e.g. battery fabricated).
        sweep_scenario = configs[0][1]
        curve = project_multi_year(sweep_scenario, finance, simulate=simulate)
        econ = project_economics(curve, sweep_scenario, finance)

        assert cr.baseline_surplus_per_home_gbp == pytest.approx(
            econ.net_surplus_per_home_per_year_gbp
        )
        assert cr.total_capex_gbp == pytest.approx(econ.total_capex_gbp)
        assert cr.min_dscr == pytest.approx(econ.min_dscr)
        # equity_irr and payback_years may be nan/None; check type equality
        if econ.payback_years is None:
            assert cr.payback_years is None
        else:
            assert cr.payback_years == pytest.approx(econ.payback_years)
        if math.isnan(econ.equity_irr):
            assert math.isnan(cr.equity_irr)
        else:
            assert cr.equity_irr == pytest.approx(econ.equity_irr)

    def test_baseline_outlay_matches_age0_bill_distribution(self) -> None:
        """baseline_outlay_gbp equals bill_distribution(...).representative.total_outlay_gbp
        from an age-0 simulation at own_use_rate=15p."""
        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        sweep_scenario = configs[0][1]

        # The fake simulate always returns fr (ignores fleet config including age)
        # so the age-0 baseline simulation returns the same fr.
        # Compute expected baseline_outlay directly using sweep_scenario's tariff.
        summaries = [
            calculate_summary(r, seg_tariff_pence_per_kwh=sweep_scenario.seg_tariff_pence_per_kwh)
            for r in fr.per_home_results
        ]
        sim_days = summaries[0].simulation_days
        dist = bill_distribution(summaries, finance, sim_days)
        expected_outlay = dist.representative.total_outlay_gbp

        assert cr.baseline_outlay_gbp == pytest.approx(expected_outlay)

    def test_cheapest_feasible_matches_config_point(self) -> None:
        """With one config, cheapest_feasible == that config's ConfigPoint."""
        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert ranked.cheapest_feasible is ranked.results[0].config


# ---------------------------------------------------------------------------
# step-07/08 — multi-config rank + feasibility + cheapest
# ---------------------------------------------------------------------------


class TestRunSweepMultiConfig:
    """Multi-config ranking: sorted by outlay, feasible/infeasible split, cheapest."""

    def _make_pv_varying_simulate(self) -> Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]:
        """Return a simulate that scales self_kwh/export with fc.homes[0].pv_config.capacity_kw.

        Its results are paired with the homes of the fleet it is asked to simulate.
        """

        def simulate(fc: FleetConfig, s: pd.Timestamp, e: pd.Timestamp) -> FleetResults:
            cap = fc.homes[0].pv_config.capacity_kw
            # Larger PV → more self-consumption and export → lower cost-recovery rate
            # → lower outlay (but we want variance for ordering tests)
            self_kwh = 1500.0 * (cap / 4.0)
            export_kwh = 600.0 * (cap / 4.0)
            return make_fleet_results(
                homes=fc.homes,
                self_kwh=self_kwh,
                export_kwh=export_kwh,
                import_kwh=1200.0,
            )

        return simulate

    def _make_infeasible_finance(self) -> FinanceConfig:
        """Finance params that produce infeasible_above_retail."""
        return _make_finance(
            pv_cost_per_kwp_gbp=20000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=10000.0,  # way above what retail rate can deliver
            retail_baseline_rate=30.0,
        )

    def test_results_sorted_ascending_by_outlay(self) -> None:
        """results is sorted ascending by representative_outlay_gbp."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario,
            pv_kwp=[3.0, 5.0],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )
        ranked = run_sweep(configs, simulate=simulate)

        outlays = [r.representative_outlay_gbp for r in ranked.results]
        assert outlays == sorted(outlays), "results must be sorted ascending by outlay"

    def test_all_results_feasible(self) -> None:
        """Every ConfigResult in results has feasible=True and binding!='infeasible_above_retail'."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        for r in ranked.results:
            assert r.feasible is True
            assert r.binding != "infeasible_above_retail"

    def test_cheapest_feasible_is_results_0_config(self) -> None:
        """cheapest_feasible == results[0].config when results non-empty."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        assert ranked.cheapest_feasible is ranked.results[0].config

    def test_infeasible_config_in_infeasible_not_results(self) -> None:
        """Infeasible configs appear in ranked.infeasible (not results); count adds up."""
        n_homes = 3
        # Feasible finance for most configs
        feasible_finance = _interior_finance(n_homes)
        # Infeasible finance for one
        infeasible_finance = self._make_infeasible_finance()

        # Build two scenarios: one feasible, one infeasible
        feasible_scenario = _make_scenario(n_homes=n_homes, finance=feasible_finance)
        infeasible_scenario = _make_scenario(n_homes=n_homes, finance=infeasible_finance)

        feasible_configs = enumerate_configs(
            feasible_scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        infeasible_pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        infeasible_configs = [(infeasible_pt, infeasible_scenario)]

        # Combine: 1 feasible + 1 infeasible
        all_configs = feasible_configs + infeasible_configs
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        ranked = run_sweep(all_configs, simulate=simulate)

        assert len(ranked.results) + len(ranked.infeasible) == len(all_configs)
        assert all(r.feasible for r in ranked.results)
        # The infeasible config's point should appear in ranked.infeasible
        assert len(ranked.infeasible) >= 1


    def test_reported_pareto_front_matches_pareto_baseline_of_results(self) -> None:
        """ranked.pareto_baseline equals pareto_baseline() over all evaluated configs
        (results + infeasible)."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        # pareto_baseline over all results (all feasible here) should match
        expected_pareto = pareto_baseline(list(ranked.results))
        assert set(ranked.pareto_baseline) == set(expected_pareto)


# ---------------------------------------------------------------------------
# step-13/14 — retained_cash_floor_gbp override threads to the solve
# ---------------------------------------------------------------------------


class TestRetainedCashFloorOverride:
    """retained_cash_floor_gbp param overrides scenario.finance.retained_cash_floor."""

    def _setup(self) -> tuple:  # type: ignore[type-arg]
        n_homes = 5
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        configs = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        return scenario, finance, fr, simulate, configs

    def test_floor_override_echoed_in_retained_cash_floor_gbp(self) -> None:
        """ranked.retained_cash_floor_gbp == the overriding value F."""
        scenario, finance, fr, simulate, configs = self._setup()
        F = finance.retained_cash_floor_per_home_per_year_gbp + 20.0
        ranked = run_sweep(configs, retained_cash_floor_gbp=F, simulate=simulate)
        assert ranked.retained_cash_floor_gbp == pytest.approx(F)

    def test_floor_override_matches_direct_solve_with_overridden_finance(self) -> None:
        """Result surplus equals direct solve_cost_recovery_rate with finance override."""
        scenario, finance, fr, simulate, configs = self._setup()
        F = finance.retained_cash_floor_per_home_per_year_gbp + 20.0
        ranked = run_sweep(configs, retained_cash_floor_gbp=F, simulate=simulate)
        cr = ranked.results[0]

        # Direct W2 call with the overridden floor.
        # Use configs[0][1] as the base — same scenario run_sweep uses after
        # enumerate_configs (homes may have been modified, e.g. battery fabricated).
        sweep_scenario = configs[0][1]
        finance_overridden = dataclasses.replace(
            finance, retained_cash_floor_per_home_per_year_gbp=F
        )
        scenario_overridden = dataclasses.replace(sweep_scenario, finance=finance_overridden)
        sol = solve_cost_recovery_rate(scenario_overridden, finance_overridden, simulate=simulate)

        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(
            sol.own_use_rate_pence_per_kwh
        )

    def test_no_floor_override_uses_scenario_finance_floor(self) -> None:
        """retained_cash_floor_gbp=None uses scenario.finance's own floor."""
        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)  # no floor override
        assert ranked.retained_cash_floor_gbp == pytest.approx(
            finance.retained_cash_floor_per_home_per_year_gbp
        )

    def test_floor_override_does_not_change_baseline_outlay(self) -> None:
        """baseline_outlay_gbp is unchanged by floor override (own_use_rate fixed at 15p)."""
        scenario, finance, fr, simulate, configs = self._setup()
        F_low = finance.retained_cash_floor_per_home_per_year_gbp
        F_high = F_low + 30.0

        configs_low = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        configs_high = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )

        ranked_low = run_sweep(configs_low, retained_cash_floor_gbp=F_low, simulate=simulate)
        ranked_high = run_sweep(configs_high, retained_cash_floor_gbp=F_high, simulate=simulate)

        assert ranked_low.results[0].baseline_outlay_gbp == pytest.approx(
            ranked_high.results[0].baseline_outlay_gbp
        )


# ---------------------------------------------------------------------------
# step-15/16 — guards: ValueError for empty configs and None finance
# ---------------------------------------------------------------------------


class TestRunSweepGuards:
    """Guards: ValueError for empty configs and None finance."""

    def test_raises_value_error_on_empty_configs(self) -> None:
        """run_sweep raises ValueError when configs list is empty."""
        with pytest.raises(ValueError, match="(?i)empty|no config"):
            run_sweep([])

    def test_raises_value_error_when_finance_is_none(self) -> None:
        """run_sweep raises ValueError when any scenario.finance is None."""
        n_homes = 3
        # Scenario with no finance block
        scenario_no_finance = _make_scenario(n_homes=n_homes, finance=None)
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        configs = [(pt, scenario_no_finance)]

        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        with pytest.raises(ValueError, match="(?i)finance"):
            run_sweep(configs, simulate=simulate)


# ---------------------------------------------------------------------------
# Amendment tests — coverage gaps surfaced by code review
# ---------------------------------------------------------------------------


class TestRunSweepRateClampedZero:
    """run_sweep ranks a config whose cost-recovery rate clamps at zero as feasible."""

    def test_rate_clamped_zero_config_lands_in_results(self) -> None:
        """A config whose cost-recovery solve clamps the rate at 0 is feasible, so
        run_sweep ranks it in results and reports nothing infeasible.

        The grant covers the capex and each home's SEG income beats its share of
        opex plus the retained-cash floor, so the surplus clears the floor at 0 p/kWh.
        """
        finance = _make_finance(
            pv_cost_per_kwp_gbp=200.0,
            grant_gbp=50000.0,
            retained_cash_floor=10.0,
            retail_baseline_rate=30.0,
        )
        scenario = _make_scenario(n_homes=5, finance=finance)
        fr = _make_fleet_results(n_homes=5, export_revenue_gbp=200.0)
        configs = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
        )

        ranked = run_sweep(configs, simulate=lambda fc, s, e: fr)

        assert [r.binding for r in ranked.results] == ["rate_clamped_zero"]
        assert ranked.results[0].solved_own_use_rate_pence_per_kwh == pytest.approx(0.0)
        assert ranked.infeasible == ()
        assert ranked.cheapest_feasible is ranked.results[0].config


class TestHeterogeneousFloorEcho:
    """retained_cash_floor_gbp echoes the FIRST config's floor when None and
    configs carry heterogeneous finance blocks."""

    def test_heterogeneous_floor_echoes_first_config(self) -> None:
        """When retained_cash_floor_gbp=None and configs have differing finance floors,
        ranked.retained_cash_floor_gbp equals the FIRST config's floor."""
        n_homes = 3
        floor_a = 80.0
        floor_b = 120.0
        finance_a = _make_finance(
            pv_cost_per_kwp_gbp=2000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=floor_a,
            retail_baseline_rate=30.0,
        )
        finance_b = _make_finance(
            pv_cost_per_kwp_gbp=2000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=floor_b,
            retail_baseline_rate=30.0,
        )
        scenario_a = _make_scenario(n_homes=n_homes, finance=finance_a)
        scenario_b = _make_scenario(n_homes=n_homes, finance=finance_b)

        configs_a = enumerate_configs(scenario_a, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6])
        configs_b = enumerate_configs(scenario_b, pv_kwp=[5.0], battery_kwh=[6.0], inverter_kw=[3.6])
        configs = configs_a + configs_b  # first config has floor_a

        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        ranked = run_sweep(configs, simulate=simulate)

        # Documented behaviour: echoes the first config's floor when no global override
        assert ranked.retained_cash_floor_gbp == pytest.approx(floor_a)
