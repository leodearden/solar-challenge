# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for CostRecoverySolution frozen dataclass and solve_cost_recovery_rate.

All tests are offline/fast — no PVGIS/network is touched.  An injected synthetic
simulate (constant FleetResults across ages) stands in for the real fleet simulator.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# §3.1 — CostRecoverySolution frozen dataclass (step-1 / step-2)
# ---------------------------------------------------------------------------


def _make_bill_breakdown() -> "BillBreakdown":  # type: ignore[name-defined]
    """Build a minimal BillBreakdown for fixture use."""
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
    """Build a minimal BillDistribution for fixture use."""
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


class TestCostRecoverySolution:
    """CostRecoverySolution frozen dataclass construction and validation."""

    def _make_valid(self) -> "CostRecoverySolution":  # type: ignore[name-defined]
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        return CostRecoverySolution(
            own_use_rate_pence_per_kwh=15.0,
            outlay=outlay,
            representative_outlay_gbp=outlay.representative.total_outlay_gbp,
            net_surplus_per_home_per_year_gbp=120.0,
            saving_vs_baseline_gbp=outlay.representative.saving_vs_baseline_gbp,
            saving_pct=outlay.representative.saving_pct,
            feasible=True,
            binding="floor",
        )

    def test_construction_valid_floor(self) -> None:
        """Valid CostRecoverySolution with binding='floor' constructs without errors."""
        sol = self._make_valid()
        assert sol.own_use_rate_pence_per_kwh == pytest.approx(15.0)
        assert sol.net_surplus_per_home_per_year_gbp == pytest.approx(120.0)
        assert sol.feasible is True
        assert sol.binding == "floor"
        assert sol.representative_outlay_gbp == pytest.approx(367.5)
        assert sol.saving_vs_baseline_gbp == pytest.approx(132.5)
        assert sol.saving_pct == pytest.approx(26.5)

    def test_construction_valid_rate_clamped_zero(self) -> None:
        """binding='rate_clamped_zero' constructs without errors."""
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        sol = CostRecoverySolution(
            own_use_rate_pence_per_kwh=0.0,
            outlay=outlay,
            representative_outlay_gbp=outlay.representative.total_outlay_gbp,
            net_surplus_per_home_per_year_gbp=500.0,
            saving_vs_baseline_gbp=outlay.representative.saving_vs_baseline_gbp,
            saving_pct=outlay.representative.saving_pct,
            feasible=True,
            binding="rate_clamped_zero",
        )
        assert sol.binding == "rate_clamped_zero"
        assert sol.own_use_rate_pence_per_kwh == pytest.approx(0.0)

    def test_construction_valid_infeasible_above_retail(self) -> None:
        """binding='infeasible_above_retail' constructs without errors."""
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        sol = CostRecoverySolution(
            own_use_rate_pence_per_kwh=30.0,
            outlay=outlay,
            representative_outlay_gbp=outlay.representative.total_outlay_gbp,
            net_surplus_per_home_per_year_gbp=-50.0,
            saving_vs_baseline_gbp=outlay.representative.saving_vs_baseline_gbp,
            saving_pct=outlay.representative.saving_pct,
            feasible=False,
            binding="infeasible_above_retail",
        )
        assert sol.binding == "infeasible_above_retail"
        assert sol.feasible is False

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning a field raises dataclasses.FrozenInstanceError."""
        sol = self._make_valid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            sol.own_use_rate_pence_per_kwh = 99.0  # type: ignore[misc]

    def test_invalid_binding_raises_value_error(self) -> None:
        """__post_init__ rejects an out-of-whitelist binding with ValueError."""
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        with pytest.raises(ValueError, match="binding"):
            CostRecoverySolution(
                own_use_rate_pence_per_kwh=15.0,
                outlay=outlay,
                representative_outlay_gbp=outlay.representative.total_outlay_gbp,
                net_surplus_per_home_per_year_gbp=100.0,
                saving_vs_baseline_gbp=100.0,
                saving_pct=20.0,
                feasible=True,
                binding="nope",
            )

    def test_negative_own_use_rate_raises_value_error(self) -> None:
        """__post_init__ rejects a negative own_use_rate_pence_per_kwh with ValueError."""
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        with pytest.raises(ValueError, match="own_use_rate"):
            CostRecoverySolution(
                own_use_rate_pence_per_kwh=-1.0,
                outlay=outlay,
                representative_outlay_gbp=outlay.representative.total_outlay_gbp,
                net_surplus_per_home_per_year_gbp=100.0,
                saving_vs_baseline_gbp=100.0,
                saving_pct=20.0,
                feasible=True,
                binding="floor",
            )

    def test_all_fields_read_back(self) -> None:
        """All 8 fields read back correctly after construction."""
        from solar_challenge.finance import CostRecoverySolution

        outlay = _make_bill_distribution()
        sol = CostRecoverySolution(
            own_use_rate_pence_per_kwh=12.5,
            outlay=outlay,
            representative_outlay_gbp=999.0,
            net_surplus_per_home_per_year_gbp=250.0,
            saving_vs_baseline_gbp=75.0,
            saving_pct=15.0,
            feasible=True,
            binding="floor",
        )
        assert sol.own_use_rate_pence_per_kwh == pytest.approx(12.5)
        assert sol.outlay is outlay
        assert sol.representative_outlay_gbp == pytest.approx(999.0)
        assert sol.net_surplus_per_home_per_year_gbp == pytest.approx(250.0)
        assert sol.saving_vs_baseline_gbp == pytest.approx(75.0)
        assert sol.saving_pct == pytest.approx(15.0)
        assert sol.feasible is True
        assert sol.binding == "floor"


# ---------------------------------------------------------------------------
# Helpers shared across solve tests (copied + adapted from test_finance_projection.py)
# ---------------------------------------------------------------------------


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


def _make_home_config(system_age_years: float = 0.0) -> "HomeConfig":  # type: ignore[name-defined]
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    return HomeConfig(
        pv_config=_make_pv_config(system_age_years),
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
    """Build a minimal SimulationResults with constant power series (annual-scale).

    Args:
        self_kwh: Annual self-consumed solar energy (kWh).
        export_kwh: Annual grid export energy (kWh).
        import_kwh: Annual grid import energy (kWh).
        export_revenue_gbp_per_year: Annual SEG export revenue (£/yr).
            Non-zero values allow ``_seg_export_income_gbp`` to see real SEG income.
        n_minutes: Simulation length in minutes (default 525600 = 365 days).
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)

    # export_revenue is monetary (£/minute); sum() = total GBP over the period.
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
) -> "FleetResults":  # type: ignore[name-defined]
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [
        _make_sim_results(self_kwh, export_kwh, import_kwh,
                          export_revenue_gbp_per_year=export_revenue_gbp_per_year)
        for _ in range(n_homes)
    ]
    return FleetResults(
        per_home_results=per_home,
        home_configs=homes,
    )


def _make_scenario(
    n_homes: int = 5,
    asset_life_years: int = 25,
    start: str = "2020-01-01",
    end: str = "2020-12-31",
    seg_tariff_pence: float = 5.0,
) -> "ScenarioConfig":  # type: ignore[name-defined]
    from solar_challenge.config import ScenarioConfig, SimulationPeriod

    homes = [_make_home_config() for _ in range(n_homes)]
    return ScenarioConfig(
        name="cr4-test",
        period=SimulationPeriod(start_date=start, end_date=end),
        description="CR4 unit test scenario",
        homes=homes,
        seg_tariff_pence_per_kwh=seg_tariff_pence,
    )


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    asset_life_years: int = 25,
    n_homes: int = 5,
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


# ---------------------------------------------------------------------------
# §3.2 — solve_cost_recovery_rate interior ('floor') regime (step-3 / step-4)
# ---------------------------------------------------------------------------


class TestSolveCostRecoveryRateInterior:
    """Interior 'floor' regime: surplus(0) < floor < surplus(retail)."""

    def _setup_interior(
        self,
        n_homes: int = 5,
    ) -> tuple:
        """Return (scenario, finance, fr, simulate) with an interior solve.

        Tuned so that:
        - surplus(r=0) < floor (too little revenue without own-use payment)
        - surplus(r=retail=30p) > floor (enough revenue at retail rate)
        Hence r* is strictly between 0 and 30p.
        """
        # 5 homes × 4 kWp each → 20 kWp; moderate capex
        # self_kwh=2000/home/yr → fleet_sc=10_000 kWh/yr @ 1 day sim (annualised)
        # But we use 365-day sim (525600 minutes) so no annualisation needed
        scenario = _make_scenario(n_homes=n_homes)
        # High capex + small grant → high r* (but below retail)
        finance = _make_finance(
            pv_cost_per_kwp_gbp=2000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=100.0,
            retail_baseline_rate=30.0,
            n_homes=n_homes,
        )
        fr = _make_fleet_results(
            n_homes=n_homes,
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
        )
        simulate = lambda fc, s, e: fr  # noqa: E731
        return scenario, finance, fr, simulate

    def test_h1_binding_floor_surplus_equals_floor(self) -> None:
        """H1: interior regime → feasible=True, binding='floor', surplus≈floor."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.feasible is True
        assert sol.binding == "floor"
        assert sol.net_surplus_per_home_per_year_gbp == pytest.approx(
            finance.retained_cash_floor_per_home_per_year_gbp, abs=1e-6
        )

    def test_outlay_is_bill_distribution(self) -> None:
        """outlay is a BillDistribution instance."""
        from solar_challenge.finance import BillDistribution, solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert isinstance(sol.outlay, BillDistribution)

    def test_representative_outlay_matches_bill_distribution(self) -> None:
        """representative_outlay_gbp == outlay.representative.total_outlay_gbp."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.representative_outlay_gbp == pytest.approx(
            sol.outlay.representative.total_outlay_gbp
        )

    def test_saving_fields_match_representative(self) -> None:
        """saving_vs_baseline_gbp and saving_pct match outlay.representative's fields."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.saving_vs_baseline_gbp == pytest.approx(
            sol.outlay.representative.saving_vs_baseline_gbp
        )
        assert sol.saving_pct == pytest.approx(
            sol.outlay.representative.saving_pct
        )

    def test_own_use_rate_in_valid_range(self) -> None:
        """Interior solve: 0 < own_use_rate <= retail_baseline_rate."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.own_use_rate_pence_per_kwh > 0.0
        assert sol.own_use_rate_pence_per_kwh <= finance.retail_baseline_rate_pence_per_kwh + 1e-9

    def test_h1_cross_check_re_sim_matches_solve(self) -> None:
        """H1 cross-check: re-sim at solved rate gives same net_surplus (flat fleet ⇒ analytic==re-sim)."""
        from solar_challenge.finance import (
            project_economics,
            project_multi_year,
            solve_cost_recovery_rate,
        )

        scenario, finance, fr, simulate = self._setup_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        # Re-run project_multi_year at the solved rate
        finance_solved = dataclasses.replace(
            finance,
            own_use_rate_pence_per_kwh=sol.own_use_rate_pence_per_kwh,
        )
        curve_solved = project_multi_year(scenario, finance_solved, simulate=simulate)
        econ_solved = project_economics(curve_solved, scenario, finance_solved)

        assert econ_solved.net_surplus_per_home_per_year_gbp == pytest.approx(
            sol.net_surplus_per_home_per_year_gbp, abs=1e-6
        )

    def test_determinism(self) -> None:
        """Two identical calls produce equal field values."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._setup_interior()
        sol1 = solve_cost_recovery_rate(scenario, finance, simulate=simulate)
        sol2 = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol1.own_use_rate_pence_per_kwh == pytest.approx(sol2.own_use_rate_pence_per_kwh)
        assert sol1.net_surplus_per_home_per_year_gbp == pytest.approx(
            sol2.net_surplus_per_home_per_year_gbp
        )
        assert sol1.binding == sol2.binding
        assert sol1.feasible == sol2.feasible

    def test_h2_higher_capex_yields_higher_rate_and_higher_outlay(self) -> None:
        """H2: higher capex → strictly higher own_use_rate AND representative_outlay_gbp."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, _, fr, _ = self._setup_interior()

        # Low capex (stays interior with low rate)
        finance_low = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=100.0,
            retail_baseline_rate=30.0,
        )
        # High capex (same scene/fr, still interior)
        finance_high = _make_finance(
            pv_cost_per_kwp_gbp=2000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=100.0,
            retail_baseline_rate=30.0,
        )

        simulate = lambda fc, s, e: fr  # noqa: E731

        sol_low = solve_cost_recovery_rate(scenario, finance_low, simulate=simulate)
        sol_high = solve_cost_recovery_rate(scenario, finance_high, simulate=simulate)

        assert sol_high.own_use_rate_pence_per_kwh > sol_low.own_use_rate_pence_per_kwh
        assert sol_high.representative_outlay_gbp > sol_low.representative_outlay_gbp


# ---------------------------------------------------------------------------
# §3.3 — feasibility clamps (step-5 / step-6)
# ---------------------------------------------------------------------------


class TestSolveCostRecoveryRateClamps:
    """Clamp and feasibility regimes: rate_clamped_zero and infeasible_above_retail."""

    def test_over_feasible_binding_rate_clamped_zero(self) -> None:
        """Over-feasible: surplus(0) > floor → binding='rate_clamped_zero', rate==0, feasible=True.

        Set-up: zero capex (grant >= capex) + large SEG income (via export_revenue_gbp_per_year)
        ensures fleet_revenue(r=0) = SEG > fleet_opex + floor×n_homes, so surplus(r=0) > floor
        without needing any own-use payment.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        n_homes = 5
        # fleet_opex = 131 × 5 = 655 GBP/yr; floor×n_homes = 10 × 5 = 50 GBP/yr
        # Need SEG > 705 GBP/yr → set export_revenue_gbp_per_year=200/home → 1000/fleet >> 705
        scenario = _make_scenario(n_homes=n_homes)
        finance = _make_finance(
            pv_cost_per_kwp_gbp=200.0,
            grant_gbp=50000.0,   # grants cover all capex → zero financed
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=10.0,
            retail_baseline_rate=30.0,
            n_homes=n_homes,
        )
        # SEG income = 200 GBP/yr per home → 1000 GBP/yr fleet, beats opex+floor=705
        fr = _make_fleet_results(
            n_homes=n_homes,
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
            export_revenue_gbp_per_year=200.0,
        )
        simulate = lambda fc, s, e: fr  # noqa: E731

        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.binding == "rate_clamped_zero"
        assert sol.own_use_rate_pence_per_kwh == pytest.approx(0.0)
        assert sol.feasible is True
        assert sol.net_surplus_per_home_per_year_gbp >= finance.retained_cash_floor_per_home_per_year_gbp

    def test_under_feasible_binding_infeasible_above_retail(self) -> None:
        """Under-feasible: surplus(retail) < floor → feasible=False, rate==retail, infeasible."""
        from solar_challenge.finance import solve_cost_recovery_rate

        n_homes = 5
        scenario = _make_scenario(n_homes=n_homes)
        # Extremely high capex, no grant, very high floor → impossible
        finance = _make_finance(
            pv_cost_per_kwp_gbp=20000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=10000.0,  # way above what retail rate can deliver
            retail_baseline_rate=30.0,
            n_homes=n_homes,
        )
        fr = _make_fleet_results(
            n_homes=n_homes,
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
        )
        simulate = lambda fc, s, e: fr  # noqa: E731

        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.feasible is False
        assert sol.binding == "infeasible_above_retail"
        assert sol.own_use_rate_pence_per_kwh == pytest.approx(
            finance.retail_baseline_rate_pence_per_kwh
        )
        assert sol.net_surplus_per_home_per_year_gbp < finance.retained_cash_floor_per_home_per_year_gbp
