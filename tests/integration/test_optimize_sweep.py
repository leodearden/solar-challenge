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
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Shared offline scaffolding (adapted from tests/unit/test_cost_recovery_solve.py)
# ---------------------------------------------------------------------------


def _make_bill_breakdown() -> "BillBreakdown":  # type: ignore[name-defined]
    from solar_challenge.finance import BillBreakdown

    return BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=367.5,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=132.5,
        saving_pct=26.5,
        self_consumption_fraction=0.35,
    )


def _make_bill_distribution() -> "BillDistribution":  # type: ignore[name-defined]
    from solar_challenge.finance import BillDistribution

    rep = _make_bill_breakdown()
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(367.5,),
        min_gbp=367.5,
        mean_gbp=367.5,
        median_gbp=367.5,
        max_gbp=367.5,
    )


def _make_pv_config(system_age_years: float = 0.0) -> "PVConfig":  # type: ignore[name-defined]
    from solar_challenge.pv import PVConfig

    return PVConfig(
        capacity_kw=4.0,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )


def _make_load_config() -> "LoadConfig":  # type: ignore[name-defined]
    from solar_challenge.load import LoadConfig

    return LoadConfig(annual_consumption_kwh=3500.0)


def _make_home_config(
    capacity_kw: float = 4.0,
    system_age_years: float = 0.0,
) -> "HomeConfig":  # type: ignore[name-defined]
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location
    from solar_challenge.pv import PVConfig

    pv = PVConfig(
        capacity_kw=capacity_kw,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )
    return HomeConfig(
        pv_config=pv,
        load_config=_make_load_config(),
        location=Location.bristol(),
    )


def _make_sim_results(
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    export_revenue_gbp_per_year: float = 0.0,
    n_minutes: int = 525600,  # 365 days
) -> "SimulationResults":  # type: ignore[name-defined]
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)

    exp_rev_per_min = export_revenue_gbp_per_year / n_minutes if n_minutes > 0 else 0.0
    export_revenue_series = pd.Series(exp_rev_per_min, index=idx)

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
        export_revenue=export_revenue_series,
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _make_fleet_results(
    n_homes: int = 5,
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    export_revenue_gbp_per_year: float = 0.0,
    capacity_kw: float = 4.0,
) -> "FleetResults":  # type: ignore[name-defined]
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config(capacity_kw=capacity_kw) for _ in range(n_homes)]
    per_home = [
        _make_sim_results(self_kwh, export_kwh, import_kwh,
                          export_revenue_gbp_per_year=export_revenue_gbp_per_year)
        for _ in range(n_homes)
    ]
    return FleetResults(
        per_home_results=per_home,
        home_configs=homes,
    )


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    asset_life_years: int = 25,
) -> "FinanceConfig":  # type: ignore[name-defined]
    from solar_challenge.config import FinanceConfig

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


def _make_scenario(
    n_homes: int = 5,
    start: str = "2020-01-01",
    end: str = "2020-12-31",
    seg_tariff_pence: float = 5.0,
    finance: "Optional[FinanceConfig]" = None,  # type: ignore[name-defined]
) -> "ScenarioConfig":  # type: ignore[name-defined]
    from solar_challenge.config import ScenarioConfig, SimulationPeriod

    homes = [_make_home_config() for _ in range(n_homes)]
    return ScenarioConfig(
        name="sweep-test",
        period=SimulationPeriod(start_date=start, end_date=end),
        description="W3 sweep integration test scenario",
        homes=homes,
        seg_tariff_pence_per_kwh=seg_tariff_pence,
        finance=finance,
    )


def _interior_finance(n_homes: int = 5) -> "FinanceConfig":  # type: ignore[name-defined]
    """Finance params that produce an interior 'floor' solve."""
    return _make_finance(
        pv_cost_per_kwp_gbp=2000.0,
        grant_gbp=0.0,
        own_use_rate_pence_per_kwh=15.0,
        retained_cash_floor=100.0,
        retail_baseline_rate=30.0,
    )


def _make_cost_recovery_solution(
    own_use_rate: float = 15.0,
    feasible: bool = True,
    binding: str = "floor",
    outlay_gbp: float = 400.0,
    surplus: float = 100.0,
) -> "CostRecoverySolution":  # type: ignore[name-defined]
    from solar_challenge.finance import BillBreakdown, BillDistribution, CostRecoverySolution

    rep = BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=outlay_gbp,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=100.0,
        saving_pct=20.0,
        self_consumption_fraction=0.35,
    )
    dist = BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(outlay_gbp,),
        min_gbp=outlay_gbp,
        mean_gbp=outlay_gbp,
        median_gbp=outlay_gbp,
        max_gbp=outlay_gbp,
    )
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate,
        outlay=dist,
        representative_outlay_gbp=outlay_gbp,
        net_surplus_per_home_per_year_gbp=surplus,
        saving_vs_baseline_gbp=100.0,
        saving_pct=20.0,
        feasible=feasible,
        binding=binding,
    )


def _make_config_result(
    pv_kwp: float = 4.0,
    battery_kwh: float = 6.0,
    inverter_kw: float = 3.6,
    feasible: bool = True,
    binding: str = "floor",
    representative_outlay_gbp: float = 400.0,
    solved_own_use_rate_pence_per_kwh: float = 15.0,
    surplus_at_solved_gbp: float = 100.0,
    total_capex_gbp: float = 10000.0,
    min_dscr: float = 1.5,
    equity_irr: float = 0.08,
    payback_years: Optional[float] = 12.0,
    baseline_outlay_gbp: float = 450.0,
    baseline_surplus_per_home_gbp: float = 80.0,
) -> "ConfigResult":  # type: ignore[name-defined]
    """Synthetic ConfigResult builder for pure helper tests (no simulation needed)."""
    from solar_challenge.optimize import ConfigPoint, ConfigResult

    config = ConfigPoint(pv_kwp=pv_kwp, battery_kwh=battery_kwh, inverter_kw=inverter_kw)
    solution = _make_cost_recovery_solution(
        own_use_rate=solved_own_use_rate_pence_per_kwh,
        feasible=feasible,
        binding=binding,
        outlay_gbp=representative_outlay_gbp,
        surplus=surplus_at_solved_gbp,
    )
    return ConfigResult(
        config=config,
        solution=solution,
        representative_outlay_gbp=representative_outlay_gbp,
        solved_own_use_rate_pence_per_kwh=solved_own_use_rate_pence_per_kwh,
        surplus_at_solved_gbp=surplus_at_solved_gbp,
        feasible=feasible,
        binding=binding,
        total_capex_gbp=total_capex_gbp,
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        baseline_outlay_gbp=baseline_outlay_gbp,
        baseline_surplus_per_home_gbp=baseline_surplus_per_home_gbp,
    )


# ---------------------------------------------------------------------------
# step-01/02 — TestConfigResult: frozen dataclass construction
# ---------------------------------------------------------------------------


class TestConfigResult:
    """ConfigResult frozen dataclass construction and validation."""

    def test_all_fields_read_back(self) -> None:
        """All fields read back correctly after construction."""
        from solar_challenge.optimize import ConfigPoint, ConfigResult

        config = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        solution = _make_cost_recovery_solution(
            own_use_rate=15.0,
            feasible=True,
            binding="floor",
            outlay_gbp=400.0,
            surplus=100.0,
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
        cr = _make_config_result(payback_years=None)
        assert cr.payback_years is None

    def test_min_dscr_inf_allowed(self) -> None:
        """min_dscr=inf is allowed (debt-free project)."""
        cr = _make_config_result(min_dscr=float("inf"))
        assert math.isinf(cr.min_dscr)

    def test_equity_irr_nan_allowed(self) -> None:
        """equity_irr=nan is allowed (undefined IRR for zero-equity project)."""
        cr = _make_config_result(equity_irr=float("nan"))
        assert math.isnan(cr.equity_irr)

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning any field raises dataclasses.FrozenInstanceError."""
        cr = _make_config_result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cr.representative_outlay_gbp = 999.0  # type: ignore[misc]

    def test_config_point_accessible(self) -> None:
        """config.pv_kwp / battery_kwh / inverter_kw match the constructed values."""
        cr = _make_config_result(pv_kwp=5.0, battery_kwh=10.0, inverter_kw=4.6)
        assert cr.config.pv_kwp == pytest.approx(5.0)
        assert cr.config.battery_kwh == pytest.approx(10.0)
        assert cr.config.inverter_kw == pytest.approx(4.6)

    def test_solution_field_accessible(self) -> None:
        """solution.own_use_rate_pence_per_kwh is readable through the ConfigResult."""
        sol = _make_cost_recovery_solution(own_use_rate=18.5, feasible=True, binding="floor")
        from solar_challenge.optimize import ConfigPoint, ConfigResult

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

    def _make_one_feasible(self) -> "ConfigResult":  # type: ignore[name-defined]
        return _make_config_result(
            pv_kwp=4.0,
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
        )

    def test_fields_read_back(self) -> None:
        """All fields read back after construction."""
        from solar_challenge.optimize import ConfigPoint, RankedSweep

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
        from solar_challenge.optimize import RankedSweep

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
        from solar_challenge.optimize import RankedSweep

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
        from solar_challenge.optimize import ConfigPoint, RankedSweep

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
        from solar_challenge.optimize import RankedSweep

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
        from solar_challenge.optimize import enumerate_configs

        configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )
        return scenario, finance, fr, simulate, configs

    def test_solve_fields_match_direct_w2(self) -> None:
        """representative_outlay / solved_rate / surplus / feasible / binding == sol.*"""
        from solar_challenge.finance import solve_cost_recovery_rate
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()

        ranked = run_sweep(configs, simulate=simulate)
        assert len(ranked.results) == 1

        cr = ranked.results[0]

        # Direct W2 call for comparison
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert cr.representative_outlay_gbp == pytest.approx(sol.representative_outlay_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(
            sol.own_use_rate_pence_per_kwh
        )
        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.feasible == sol.feasible
        assert cr.binding == sol.binding

    def test_solution_field_is_cost_recovery_solution(self) -> None:
        """result.solution is a CostRecoverySolution."""
        from solar_challenge.finance import CostRecoverySolution
        from solar_challenge.optimize import run_sweep

        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert isinstance(ranked.results[0].solution, CostRecoverySolution)

    def test_baseline_econ_fields_match_direct_w2(self) -> None:
        """total_capex / min_dscr / equity_irr / payback_years match project_economics."""
        from solar_challenge.finance import project_economics, project_multi_year
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        curve = project_multi_year(scenario, finance, simulate=simulate)
        econ = project_economics(curve, scenario, finance)

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
        from solar_challenge.finance import bill_distribution
        from solar_challenge.home import calculate_summary
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        # The fake simulate always returns fr (ignores fleet config including age)
        # so the age-0 baseline simulation returns the same fr.
        # Compute expected baseline_outlay directly.
        summaries = [
            calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
            for r in fr.per_home_results
        ]
        sim_days = 365
        dist = bill_distribution(summaries, finance, sim_days)
        expected_outlay = dist.representative.total_outlay_gbp

        assert cr.baseline_outlay_gbp == pytest.approx(expected_outlay)

    def test_cheapest_feasible_matches_config_point(self) -> None:
        """With one config, cheapest_feasible == that config's ConfigPoint."""
        from solar_challenge.optimize import run_sweep

        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert ranked.cheapest_feasible is ranked.results[0].config


# ---------------------------------------------------------------------------
# step-07/08 — multi-config rank + feasibility + cheapest
# ---------------------------------------------------------------------------


class TestRunSweepMultiConfig:
    """Multi-config ranking: sorted by outlay, feasible/infeasible split, cheapest."""

    def _make_pv_varying_simulate(self, n_homes: int = 5):  # type: ignore[return]
        """Return a simulate that scales self_kwh/export with fc.homes[0].pv_config.capacity_kw."""

        def simulate(fc, s, e):  # type: ignore[return]
            cap = fc.homes[0].pv_config.capacity_kw
            # Larger PV → more self-consumption and export → lower cost-recovery rate
            # → lower outlay (but we want variance for ordering tests)
            self_kwh = 1500.0 * (cap / 4.0)
            export_kwh = 600.0 * (cap / 4.0)
            return _make_fleet_results(
                n_homes=n_homes,
                self_kwh=self_kwh,
                export_kwh=export_kwh,
                import_kwh=1200.0,
                capacity_kw=cap,
            )

        return simulate

    def _make_infeasible_finance(self) -> "FinanceConfig":  # type: ignore[name-defined]
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
        simulate = self._make_pv_varying_simulate(n_homes)

        from solar_challenge.optimize import enumerate_configs, run_sweep

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
        simulate = self._make_pv_varying_simulate(n_homes)

        from solar_challenge.optimize import enumerate_configs, run_sweep

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
        simulate = self._make_pv_varying_simulate(n_homes)

        from solar_challenge.optimize import enumerate_configs, run_sweep

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

        from solar_challenge.optimize import ConfigPoint, enumerate_configs, run_sweep

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


# ---------------------------------------------------------------------------
# step-09/10 — _rank_feasible: deterministic tie-break
# ---------------------------------------------------------------------------


class TestRankFeasible:
    """Pure _rank_feasible: sort key (outlay asc, surplus desc, pv asc, batt asc, inv asc)."""

    def test_primary_sort_by_outlay_ascending(self) -> None:
        """Primary sort is by representative_outlay_gbp ascending."""
        from solar_challenge.optimize import _rank_feasible

        low = _make_config_result(representative_outlay_gbp=300.0, pv_kwp=4.0)
        high = _make_config_result(representative_outlay_gbp=500.0, pv_kwp=5.0)
        result = _rank_feasible([high, low])
        assert result[0].representative_outlay_gbp == pytest.approx(300.0)
        assert result[1].representative_outlay_gbp == pytest.approx(500.0)

    def test_tie_break_surplus_descending(self) -> None:
        """On equal outlay, higher surplus comes first (descending)."""
        from solar_challenge.optimize import _rank_feasible

        a = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=200.0,
            pv_kwp=4.0,
        )
        b = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=4.0,
        )
        result = _rank_feasible([b, a])
        assert result[0].surplus_at_solved_gbp == pytest.approx(200.0)
        assert result[1].surplus_at_solved_gbp == pytest.approx(100.0)

    def test_tie_break_pv_ascending(self) -> None:
        """On equal outlay and surplus, smaller pv_kwp comes first (ascending)."""
        from solar_challenge.optimize import _rank_feasible

        small = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=3.0,
        )
        large = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=5.0,
        )
        result = _rank_feasible([large, small])
        assert result[0].config.pv_kwp == pytest.approx(3.0)
        assert result[1].config.pv_kwp == pytest.approx(5.0)

    def test_tie_break_battery_ascending(self) -> None:
        """On equal outlay/surplus/pv, smaller battery_kwh comes first."""
        from solar_challenge.optimize import _rank_feasible

        small = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=4.0,
            battery_kwh=4.0,
        )
        large = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=4.0,
            battery_kwh=10.0,
        )
        result = _rank_feasible([large, small])
        assert result[0].config.battery_kwh == pytest.approx(4.0)
        assert result[1].config.battery_kwh == pytest.approx(10.0)

    def test_tie_break_inverter_ascending(self) -> None:
        """On equal outlay/surplus/pv/battery, smaller inverter_kw comes first."""
        from solar_challenge.optimize import _rank_feasible

        small = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=4.0,
            battery_kwh=6.0,
            inverter_kw=3.0,
        )
        large = _make_config_result(
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
            pv_kwp=4.0,
            battery_kwh=6.0,
            inverter_kw=5.0,
        )
        result = _rank_feasible([large, small])
        assert result[0].config.inverter_kw == pytest.approx(3.0)
        assert result[1].config.inverter_kw == pytest.approx(5.0)

    def test_stable_reproducible_across_repeated_calls(self) -> None:
        """Same input always produces same output ordering."""
        from solar_challenge.optimize import _rank_feasible

        items = [
            _make_config_result(representative_outlay_gbp=400.0, surplus_at_solved_gbp=150.0, pv_kwp=5.0),
            _make_config_result(representative_outlay_gbp=300.0, surplus_at_solved_gbp=100.0, pv_kwp=4.0),
            _make_config_result(representative_outlay_gbp=400.0, surplus_at_solved_gbp=200.0, pv_kwp=4.0),
        ]
        result1 = _rank_feasible(items)
        result2 = _rank_feasible(items)
        assert [r.config for r in result1] == [r.config for r in result2]


# ---------------------------------------------------------------------------
# step-11/12 — _pareto_baseline: non-dominated set
# ---------------------------------------------------------------------------


class TestParetoBaseline:
    """Pure _pareto_baseline: non-dominated on (baseline_outlay down, baseline_surplus up)."""

    def test_dominated_point_excluded(self) -> None:
        """A strictly dominated point is not in the Pareto set."""
        from solar_challenge.optimize import _pareto_baseline

        # A dominates B: A has lower outlay AND higher surplus
        a = _make_config_result(baseline_outlay_gbp=300.0, baseline_surplus_per_home_gbp=200.0, pv_kwp=4.0)
        b = _make_config_result(baseline_outlay_gbp=400.0, baseline_surplus_per_home_gbp=100.0, pv_kwp=5.0)
        # c is incomparable to a: lower outlay AND lower surplus
        c = _make_config_result(baseline_outlay_gbp=250.0, baseline_surplus_per_home_gbp=150.0, pv_kwp=6.0)

        pareto = _pareto_baseline([a, b, c])
        pareto_configs = [p for p in pareto]

        # B is dominated by A (A has 300<=400 and 200>=100 with at least one strict)
        assert a.config in pareto_configs
        assert b.config not in pareto_configs
        # c is on the front (lower outlay but lower surplus than a → incomparable)
        assert c.config in pareto_configs

    def test_non_dominated_all_included(self) -> None:
        """All non-dominated points are included."""
        from solar_challenge.optimize import _pareto_baseline

        # Three points forming a Pareto front: outlay↓, surplus↑
        a = _make_config_result(baseline_outlay_gbp=100.0, baseline_surplus_per_home_gbp=400.0, pv_kwp=4.0)
        b = _make_config_result(baseline_outlay_gbp=200.0, baseline_surplus_per_home_gbp=600.0, pv_kwp=5.0)
        c = _make_config_result(baseline_outlay_gbp=300.0, baseline_surplus_per_home_gbp=800.0, pv_kwp=6.0)

        pareto = _pareto_baseline([a, b, c])
        assert len(pareto) == 3

    def test_ordered_by_baseline_outlay_ascending(self) -> None:
        """Returned tuple is sorted by baseline_outlay ascending (deterministic)."""
        from solar_challenge.optimize import _pareto_baseline

        a = _make_config_result(baseline_outlay_gbp=400.0, baseline_surplus_per_home_gbp=100.0, pv_kwp=4.0)
        b = _make_config_result(baseline_outlay_gbp=200.0, baseline_surplus_per_home_gbp=300.0, pv_kwp=5.0)
        c = _make_config_result(baseline_outlay_gbp=300.0, baseline_surplus_per_home_gbp=200.0, pv_kwp=6.0)

        pareto = _pareto_baseline([a, b, c])
        # All three are non-dominated; should be sorted ascending by outlay
        outlays = [cr.baseline_outlay_gbp for cr in [
            next(cr_full for cr_full in [a, b, c] if cr_full.config == p)
            for p in pareto
        ]]
        assert outlays == sorted(outlays)

    def test_includes_infeasible_configs_when_non_dominated(self) -> None:
        """Infeasible configs (binding='infeasible_above_retail') appear in pareto when
        their (baseline_outlay, baseline_surplus) pair is non-dominated."""
        from solar_challenge.optimize import _pareto_baseline

        feasible = _make_config_result(
            baseline_outlay_gbp=400.0,
            baseline_surplus_per_home_gbp=100.0,
            feasible=True,
            binding="floor",
            pv_kwp=4.0,
        )
        infeasible = _make_config_result(
            baseline_outlay_gbp=300.0,
            baseline_surplus_per_home_gbp=50.0,
            feasible=False,
            binding="infeasible_above_retail",
            pv_kwp=5.0,
        )
        pareto = _pareto_baseline([feasible, infeasible])
        pareto_configs = list(pareto)
        # infeasible has lower outlay but lower surplus → incomparable → on front
        assert infeasible.config in pareto_configs

    def test_integration_ranked_pareto_consistent(self) -> None:
        """run_sweep populates pareto_baseline consistently with _pareto_baseline
        over all evaluated configs (results + infeasible)."""
        from solar_challenge.optimize import _pareto_baseline, enumerate_configs, run_sweep

        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        # _pareto_baseline over all results (all feasible here) should match
        expected_pareto = _pareto_baseline(list(ranked.results))
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
        from solar_challenge.optimize import enumerate_configs

        configs = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        return scenario, finance, fr, simulate, configs

    def test_floor_override_echoed_in_retained_cash_floor_gbp(self) -> None:
        """ranked.retained_cash_floor_gbp == the overriding value F."""
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        F = finance.retained_cash_floor_per_home_per_year_gbp + 20.0
        ranked = run_sweep(configs, retained_cash_floor_gbp=F, simulate=simulate)
        assert ranked.retained_cash_floor_gbp == pytest.approx(F)

    def test_floor_override_matches_direct_solve_with_overridden_finance(self) -> None:
        """Result surplus equals direct solve_cost_recovery_rate with finance override."""
        from solar_challenge.finance import solve_cost_recovery_rate
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        F = finance.retained_cash_floor_per_home_per_year_gbp + 20.0
        ranked = run_sweep(configs, retained_cash_floor_gbp=F, simulate=simulate)
        cr = ranked.results[0]

        # Direct W2 call with the overridden floor
        finance_overridden = dataclasses.replace(
            finance, retained_cash_floor_per_home_per_year_gbp=F
        )
        scenario_overridden = dataclasses.replace(scenario, finance=finance_overridden)
        sol = solve_cost_recovery_rate(scenario_overridden, finance_overridden, simulate=simulate)

        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(
            sol.own_use_rate_pence_per_kwh
        )

    def test_no_floor_override_uses_scenario_finance_floor(self) -> None:
        """retained_cash_floor_gbp=None uses scenario.finance's own floor."""
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)  # no floor override
        assert ranked.retained_cash_floor_gbp == pytest.approx(
            finance.retained_cash_floor_per_home_per_year_gbp
        )

    def test_floor_override_does_not_change_baseline_outlay(self) -> None:
        """baseline_outlay_gbp is unchanged by floor override (own_use_rate fixed at 15p)."""
        from solar_challenge.optimize import run_sweep

        scenario, finance, fr, simulate, configs = self._setup()
        F_low = finance.retained_cash_floor_per_home_per_year_gbp
        F_high = F_low + 30.0

        from solar_challenge.optimize import enumerate_configs

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
        from solar_challenge.optimize import run_sweep

        with pytest.raises(ValueError, match="(?i)empty|no config"):
            run_sweep([])

    def test_raises_value_error_when_finance_is_none(self) -> None:
        """run_sweep raises ValueError when any scenario.finance is None."""
        from solar_challenge.optimize import ConfigPoint, enumerate_configs, run_sweep

        n_homes = 3
        # Scenario with no finance block
        scenario_no_finance = _make_scenario(n_homes=n_homes, finance=None)
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        configs = [(pt, scenario_no_finance)]

        fr = _make_fleet_results(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        with pytest.raises(ValueError, match="(?i)finance"):
            run_sweep(configs, simulate=simulate)
