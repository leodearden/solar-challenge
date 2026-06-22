# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests: no-flex cost-recovery reconciliation calibration (task/62 – CR6).

H6 integration gate: verifies the no-flex calibration anchor, structural invariants,
and flex-lowers-rate directionality for solve_cost_recovery_rate.

Layout:
  - Fast (no-network) classes:
      TestNoFlexAnchorReconciliation — [FIN] no-flex structural anchor
      TestStructuralInvariants — H1 (surplus==floor) + H2 (capex monotone)
      TestFlexLowersSolvedRate — directional assert: flex ⟹ strictly lower rate
      TestThetaStaysGreen — in-file θ-isolation smoke (spreadsheet → economics)
  - @pytest.mark.slow class:
      TestPhysicsReconciliationColumn — real-PVGIS physics column (reported, not asserted ==)

NOTE: This file mixes fast and slow tests; it must NOT be added to
test_marker_registration.py's INTEGRATION_FILES list.  (test_finance_calibration.py
has the same structure and is also excluded for this reason.)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# [FIN] Golden constants (reused from θ / test_finance_calibration.py)
# ---------------------------------------------------------------------------

_FIN_GOLDEN = {
    "inp_kWp": 5.5,
    "inp_Batt_kWh": 5.0,
    "inp_kWhPerkWp": 1050.0,
    "capital_stack_b6": 775000.0,   # 100 × (5.5×£1000 + £1000 + 5kWh×£250) = £775,000
    "min_dscr": 2.10378435678433,   # Debt_Analytics!B16
    "own_use_rate_pence_per_kwh": 15.0,
    "export_rate_pence_per_kwh": 6.0,
    "grant_gbp": 250000.0,
    "equity_fraction": 0.75,
    "loan_term_years": 15,
    "loan_rate": 0.07,
}

_FIN_SCF = 0.70  # spreadsheet with-battery self-consumption fraction assumption


# ---------------------------------------------------------------------------
# Stub helpers — replace NotImplementedError bodies with real implementations
# in step-2 (GREEN).
# ---------------------------------------------------------------------------


def _make_sim_results_cr6(
    self_kwh: float,
    export_kwh: float,
    import_kwh: float,
    n_steps: int = 8760,  # hourly resolution; energy = sum*(1/60) still correct
    grid_charge_cost_per_home_gbp: float | None = None,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a synthetic SimulationResults.

    Hourly resolution (n_steps=8760 ≈ 1 yr) keeps memory ~60× lower than the
    former 1-minute default while preserving energy totals exactly:
      home.py computes total_kwh = series.sum() * (1/60)
      sc_kw = self_kwh / (n_steps/60)  →  sum*1/60 = self_kwh  ✓

    grid_charge_cost_per_home_gbp=None → total_grid_charge_cost_gbp==0.0 (home.py:154),
    so a flat-rate fleet has cbs_grid_charge_cost==0 by construction.
    export_revenue=0 → SEG income = 0 in _seg_export_income_gbp (physics path).
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = self_kwh / (n_steps / 60.0)   # kW s.t. sum*(1/60) = self_kwh
    exp_kw = export_kwh / (n_steps / 60.0)
    imp_kw = import_kwh / (n_steps / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)

    if grid_charge_cost_per_home_gbp is not None:
        # home.py sums grid_charge_cost directly (£, not kW): sum = gbp ✓
        charge_per_step = grid_charge_cost_per_home_gbp / n_steps
        grid_charge_cost: pd.Series | None = pd.Series(charge_per_step, index=idx)
    else:
        grid_charge_cost = None  # flat-rate → cbs_grid_charge_cost==0

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
        export_revenue=zeros.copy(),  # SEG=0 → no-flex CBS-revenue identity holds
        tariff_rate=zeros.copy(),
        grid_charge_cost=grid_charge_cost,
    )


def _make_fleet_results_fin_cr6(
    n_homes: int = 100,
    self_kwh: float = 2000.0,
    export_kwh: float = 3775.0,
    import_kwh: float = 1400.0,
) -> "FleetResults":  # type: ignore[name-defined]
    """Build a [FIN]-aligned synthetic FleetResults.

    Default values tuned to produce solved rate ≈15p under [FIN] capex/grant:
      - 100 homes × 5.5 kWp + 5 kWh (HomeConfig)
      - fleet_sc = n_homes × self_kwh = 200,000 kWh
      - Required revenue = opex(13100) + debt_svc(14410) + floor×n(2700) = £30,210
      - r* = 30210 / (200000/100) = 15.1 p/kWh → interior 'floor' regime, feasible=True

    No-flex by construction: grid_charge_cost=None, export_revenue=0, grid_services=0.
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
    per_home = [
        _make_sim_results_cr6(self_kwh, export_kwh, import_kwh)
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _make_home_config_fin_cr6(
    pv_kwp: float = 5.5,
    battery_kwh: float = 5.0,
) -> "HomeConfig":  # type: ignore[name-defined]
    """Build a [FIN]-aligned HomeConfig for CR6 tests (Bristol defaults)."""
    from solar_challenge.home import HomeConfig
    from solar_challenge.pv import PVConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.battery import BatteryConfig

    pv = PVConfig(capacity_kw=pv_kwp, azimuth=180, tilt=35)
    load = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1)
    batt = BatteryConfig(capacity_kwh=battery_kwh) if battery_kwh > 0.0 else None
    return HomeConfig(pv_config=pv, load_config=load, battery_config=batt)


def _make_scenario_fin_cr6(
    n_homes: int = 100,
    pv_kwp: float = 5.5,
    battery_kwh: float = 5.0,
) -> "ScenarioConfig":  # type: ignore[name-defined]
    """Build a homogeneous [FIN]-aligned ScenarioConfig (100 homes, 2024 full year)."""
    from solar_challenge.config import ScenarioConfig, SimulationPeriod

    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    homes = [_make_home_config_fin_cr6(pv_kwp=pv_kwp, battery_kwh=battery_kwh)
             for _ in range(n_homes)]
    return ScenarioConfig(name="CR6-Calibration", period=period, homes=homes)


def _make_finance_cr6(
    *,
    grid_services: float = 0.0,
    retained_cash_floor: float = 27.0,
    own_use_rate: float = 15.0,
    retail_rate: float = 23.0,
    pv_cost_per_kwp: float = 1000.0,
    grant_gbp: float = 250000.0,
    equity_fraction: float = 0.75,
    loan_term_years: int = 15,
    loan_rate: float = 0.07,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Unified FinanceConfig factory for CR6 tests.

    All three former builders (_make_finance_fin_cr6 / _make_finance_interior_cr6 /
    _make_finance_flex_cr6) were ~95% identical; they now call this factory with
    their distinct defaults, preventing silent drift on shared fields.

    Default values match [FIN] (capex=£775k, grant=£250k, retail=23p, floor=£27).
    Interior/flex tests pass explicit overrides (pv_cost=2000, grant=0, retail=30, floor=50).
    """
    from solar_challenge.config import FinanceConfig

    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        pv_cost_per_kwp_gbp=pv_cost_per_kwp,
        roof_fit_cost_gbp=1000.0,
        battery_cost_per_kwh_gbp=250.0,
        inverter_cost_per_kw_gbp=0.0,
        grant_gbp=grant_gbp,
        equity_fraction=equity_fraction,
        loan_term_years=loan_term_years,
        loan_rate=loan_rate,
        opex_per_home_per_year_gbp=131.0,
        asset_life_years=25,
        own_use_rate_pence_per_kwh=own_use_rate,
        retained_cash_floor_per_home_per_year_gbp=retained_cash_floor,
        retail_baseline_rate_pence_per_kwh=retail_rate,
        vat_rate=0.05,
        grid_services_income_per_kw_per_year_gbp=grid_services,
        # self_consumption_override=None (default) → physics path for SEG
    )


def _make_finance_fin_cr6(
    *,
    grid_services: float = 0.0,
    retained_cash_floor: float = 27.0,
    own_use_rate: float = 15.0,
    retail_rate: float = 23.0,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """[FIN]-aligned FinanceConfig (capex=£775k, grant=£250k, retail=23p, floor=£27).

    Capex = 100 × (5.5×£1000 + £1000 + 5kWh×£250) = £775,000
    Grant = £250,000 → financed = £525,000
    Equity (0.75) = £393,750; Debt (0.25) = £131,250
    Debt service (7%, 15yr) ≈ £14,410/yr
    """
    return _make_finance_cr6(
        grid_services=grid_services,
        retained_cash_floor=retained_cash_floor,
        own_use_rate=own_use_rate,
        retail_rate=retail_rate,
        pv_cost_per_kwp=1000.0,
        grant_gbp=_FIN_GOLDEN["grant_gbp"],
        equity_fraction=_FIN_GOLDEN["equity_fraction"],
        loan_term_years=int(_FIN_GOLDEN["loan_term_years"]),
        loan_rate=_FIN_GOLDEN["loan_rate"],
    )


# ---------------------------------------------------------------------------
# Step-1 RED / step-2 GREEN: TestNoFlexAnchorReconciliation
# ---------------------------------------------------------------------------


class TestNoFlexAnchorReconciliation:
    """[FIN] no-flex calibration anchor (step-1 RED / step-2 GREEN).

    Hard-asserts structural/by-construction properties only:
    - sol.feasible is True
    - No-flex CBS-revenue identity: fleet_revenue = own_use_rate × fleet_sc / 100
      (grid_services=0, cbs_grid_charge=0)
    - 0 ≤ sol.own_use_rate ≤ retail (valid clamped range)

    REPORTS (printed, NOT asserted): solved rate ≈15p, saving ≈£324,
    surplus = £27 floor (assumption-dependent; physics scf ≠ 0.70/sheet).
    """

    def _build_fin_anchor(self) -> tuple:  # type: ignore[type-arg]
        """Build (scenario, finance, fr, simulate) for the [FIN] no-flex anchor."""
        scenario = _make_scenario_fin_cr6(n_homes=100)
        finance = _make_finance_fin_cr6(
            grid_services=0.0,
            retained_cash_floor=27.0,
            own_use_rate=15.0,
            retail_rate=23.0,
        )
        fr = _make_fleet_results_fin_cr6(
            n_homes=100,
            self_kwh=2000.0,
            export_kwh=3775.0,
            import_kwh=1400.0,
        )
        simulate = lambda fc, s, e: fr  # noqa: E731
        return scenario, finance, fr, simulate

    def test_no_flex_cbs_revenue_identity(self) -> None:
        """No-flex identity: fleet_revenue_gbp == own_use_rate × fleet_sc / 100.

        With flat-rate tariff (grid_charge_cost=None → total_grid_charge_cost=0),
        grid_services=0, and export_revenue=0 (SEG=0 in synthetic):
          fleet_revenue = own_use × sc / 100 + 0 + 0 − 0 (by construction)
        """
        from solar_challenge.finance import project_multi_year

        scenario, finance, fr, simulate = self._build_fin_anchor()

        # Run project_multi_year to inspect a YearPoint's fleet_revenue_gbp
        curve = project_multi_year(scenario, finance, simulate=simulate)
        year0 = curve.points[0]

        # No-flex CBS-revenue identity (by construction of the synthetic fleet)
        # SEG=0 (export_revenue=0 in _make_sim_results_cr6), grid_services=0, grid_charge=0
        expected_revenue = (
            finance.own_use_rate_pence_per_kwh
            * year0.fleet_self_consumption_kwh
            / 100.0
        )
        assert year0.fleet_revenue_gbp == pytest.approx(expected_revenue, rel=1e-9), (
            f"No-flex identity: expected £{expected_revenue:.4f}, "
            f"got £{year0.fleet_revenue_gbp:.4f}"
        )

    def test_no_flex_solve_feasible(self) -> None:
        """Hard: sol.feasible is True on [FIN] no-flex fleet."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._build_fin_anchor()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.feasible is True, (
            f"Expected feasible=True for [FIN] no-flex fleet; got binding={sol.binding!r}"
        )

    def test_no_flex_solve_rate_in_valid_range(self) -> None:
        """Hard: 0 ≤ solved own_use_rate ≤ retail_baseline_rate."""
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._build_fin_anchor()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert 0.0 <= sol.own_use_rate_pence_per_kwh <= finance.retail_baseline_rate_pence_per_kwh

    def test_no_flex_solve_report(self) -> None:
        """REPORT the no-flex anchor numbers (printed; tolerance documented; NOT pinned).

        The reported values depend on synthetic self-consumption assumptions.
        Physics self-consumption (≈20–35%) ≠ spreadsheet 0.70, so the exact
        rate/saving differ from [FEAS] figures. This test prints and PASSES always.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, simulate = self._build_fin_anchor()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        # REPORTED (not pinned): solved rate target ≈15p, saving target ≈£324
        print(
            f"\n[NO-FLEX ANCHOR REPORT] (synthetic scf≈0.346; assumption-dependent)"
            f"\n  Solved own-use rate: {sol.own_use_rate_pence_per_kwh:.2f} p/kWh"
            f"  (target ≈15p; reported, not pinned)"
            f"\n  Saving vs baseline:  £{sol.saving_vs_baseline_gbp:.0f}"
            f"  (target ≈£324; reported, not pinned)"
            f"\n  Net surplus/home/yr: £{sol.net_surplus_per_home_per_year_gbp:.2f}"
            f"  (= £27 floor when binding='floor')"
            f"\n  Binding:             {sol.binding}"
            f"\n  Feasible:            {sol.feasible}"
            f"\n  [Corrected premise: £27 surplus is no-flex; NOT '15p + Central flex → £27']"
        )
        # Structural guards: the reported values must land in valid ranges
        assert isinstance(sol.feasible, bool)
        assert sol.binding in ("floor", "rate_clamped_zero", "infeasible_above_retail"), (
            f"Unexpected binding value: {sol.binding!r}"
        )
        assert 0.0 <= sol.own_use_rate_pence_per_kwh <= finance.retail_baseline_rate_pence_per_kwh, (
            f"Solved rate {sol.own_use_rate_pence_per_kwh:.4f} outside [0, {finance.retail_baseline_rate_pence_per_kwh}]"
        )


# ---------------------------------------------------------------------------
# Step-7 RED / step-8 GREEN: flex helper functions
# ---------------------------------------------------------------------------


def _make_finance_flex_cr6(
    *,
    grid_services: float = 0.0,
    retained_cash_floor: float = 50.0,
    pv_cost_per_kwp: float = 2000.0,
    grant_gbp: float = 0.0,
    retail_rate: float = 30.0,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Interior FinanceConfig with optional flex (grid_services) — thin wrapper."""
    return _make_finance_cr6(
        grid_services=grid_services,
        retained_cash_floor=retained_cash_floor,
        retail_rate=retail_rate,
        pv_cost_per_kwp=pv_cost_per_kwp,
        grant_gbp=grant_gbp,
    )


def _make_arbitrage_fleet_cr6(
    n_homes: int = 5,
    self_kwh: float = 2400.0,    # elevated sc vs flat-rate 2000 kWh
    export_kwh: float = 400.0,
    import_kwh: float = 800.0,
    grid_charge_cost_per_home_gbp: float = 50.0,  # CBS pays to charge battery from grid
) -> "FleetResults":  # type: ignore[name-defined]
    """Build an 'arbitrage-on' synthetic FleetResults representing W1 TOU time-shift.

    Arbitrage on: elevated self-consumption (TOU charging of battery raises sc)
    + CBS grid-charge cost (cbs_grid_charge_cost > 0 from a non-None grid_charge_cost series).

    Net benefit direction at r = retail = 30p:
      uplift_sc = (2400 − 2000) × 30/100 = £120/home
      grid_charge = £50/home
      net_benefit = £70/home > 0 → revenue higher → rate lower ✓

    Reuses _make_sim_results_cr6 with grid_charge_cost_per_home_gbp set,
    avoiding duplication of the series-building block.
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
    per_home = [
        _make_sim_results_cr6(
            self_kwh, export_kwh, import_kwh,
            grid_charge_cost_per_home_gbp=grid_charge_cost_per_home_gbp,
        )
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


# ---------------------------------------------------------------------------
# Step-3 RED / step-4 GREEN: TestStructuralInvariants — H1 and H2
# ---------------------------------------------------------------------------


def _make_interior_fleet_cr6(
    n_homes: int = 5,
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
) -> "FleetResults":  # type: ignore[name-defined]
    """Build a small synthetic FleetResults tuned to the interior 'floor' regime.

    Interior guarantee (with _make_finance_interior_cr6 defaults):
      fleet_sc = n_homes × self_kwh = 5 × 2000 = 10,000 kWh
      capex = 5 × (5.5×£2000 + £1000 + 5×£250) = 5 × £13,250 = £66,250
      debt = 66250 × 0.25 = £16,562.50; debt_svc ≈ £1,820/yr
      opex = 5 × £131 = £655/yr; total_costs ≈ £2,475/yr
      required_revenue = 2475 + 50×5 = £2,725/yr
      r* = (2725 − 0) / (10000/100) = £2,725 / 100 = 27.25p
      BUT retail=30p → interior: 0 < 27.25 < 30 ✓

    No-flex: grid_charge_cost=None, export_revenue=0.
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
    per_home = [
        _make_sim_results_cr6(self_kwh, export_kwh, import_kwh)
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _make_finance_interior_cr6(
    retained_cash_floor: float = 50.0,
    pv_cost_per_kwp: float = 2000.0,
    grant_gbp: float = 0.0,
    retail_rate: float = 30.0,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Interior-regime FinanceConfig for H1/H2 structural invariant tests — thin wrapper.

    Interior regime guaranteed by: high capex (no grant) + moderate floor →
    surplus(r=0) < floor AND surplus(r=retail=30p) > floor.

    With n=5 homes, self=2000kWh:
      fleet_sc = 10,000 kWh
      At r=0: surplus = (0−opex−debt)/5 ≈ (0−655−1820)/5 ≈ −495/home << floor=50
      At r=retail=30p: surplus = (30×10000/100−2475)/5 ≈ (3000−2475)/5 ≈ 105/home >> floor=50
    ∴ interior ✓
    """
    return _make_finance_cr6(
        retained_cash_floor=retained_cash_floor,
        retail_rate=retail_rate,
        pv_cost_per_kwp=pv_cost_per_kwp,
        grant_gbp=grant_gbp,
    )


class TestStructuralInvariants:
    """H1 (surplus==floor) and H2 (capex→rate monotone) structural invariants.

    All tests are fast + hermetic: programmatic configs + injected simulate.
    """

    def _build_interior(
        self,
        n_homes: int = 5,
        self_kwh: float = 2000.0,
        pv_cost_per_kwp: float = 2000.0,
        grant_gbp: float = 0.0,
        retained_cash_floor: float = 50.0,
        retail_rate: float = 30.0,
    ) -> tuple:  # type: ignore[type-arg]
        """Return (scenario, finance, simulate) for an interior 'floor' regime."""
        from solar_challenge.config import ScenarioConfig, SimulationPeriod

        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
        homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
        scenario = ScenarioConfig(name="CR6-Interior", period=period, homes=homes)
        finance = _make_finance_interior_cr6(
            retained_cash_floor=retained_cash_floor,
            pv_cost_per_kwp=pv_cost_per_kwp,
            grant_gbp=grant_gbp,
            retail_rate=retail_rate,
        )
        fr = _make_interior_fleet_cr6(
            n_homes=n_homes,
            self_kwh=self_kwh,
        )
        simulate = lambda fc, s, e: fr  # noqa: E731
        return scenario, finance, simulate

    def test_h1_surplus_equals_floor(self) -> None:
        """H1: interior regime → binding=='floor', feasible=True, surplus≈floor (exact).

        The closed-form affine solve guarantees surplus(r*) = floor to float ε.
        Cross-check: re-run project_multi_year at the solved rate; the affine
        reconstruction and re-sim must agree to float ε (mirrors CR4 H1 cross-check).
        """
        import dataclasses
        from solar_challenge.finance import (
            project_economics,
            project_multi_year,
            solve_cost_recovery_rate,
        )

        scenario, finance, simulate = self._build_interior()
        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        # H1 hard assertions
        assert sol.binding == "floor", (
            f"Expected binding='floor' (interior regime); got {sol.binding!r}"
        )
        assert sol.feasible is True
        assert sol.net_surplus_per_home_per_year_gbp == pytest.approx(
            finance.retained_cash_floor_per_home_per_year_gbp, abs=1e-6
        ), (
            f"H1: expected surplus=floor={finance.retained_cash_floor_per_home_per_year_gbp}; "
            f"got {sol.net_surplus_per_home_per_year_gbp:.8f}"
        )

        # H1 cross-check: re-sim at solved rate must agree to float ε
        finance_solved = dataclasses.replace(
            finance,
            own_use_rate_pence_per_kwh=sol.own_use_rate_pence_per_kwh,
        )
        curve_solved = project_multi_year(scenario, finance_solved, simulate=simulate)
        econ_solved = project_economics(curve_solved, scenario, finance_solved)
        assert econ_solved.net_surplus_per_home_per_year_gbp == pytest.approx(
            sol.net_surplus_per_home_per_year_gbp, abs=1e-6
        )

    def test_h2_capex_monotone_on_fin_fleet(self) -> None:
        """H2: higher capex → strictly higher solved own_use_rate AND representative_outlay.

        Both configs use the same injected energy mix (SAME fleet) over the SAME
        scenario — only capex differs — so the strict monotonicity comes from the
        affine solve's capex→debt→required-own-use→outlay coupling.

        Tuned so BOTH configs stay in the interior 'floor' regime (r* ∈ (0, retail)).
        RED until step-6 tunes the fixture pair.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, _, simulate = self._build_interior()

        # Low-capex config (interior, low rate)
        finance_low = _make_finance_interior_cr6(
            pv_cost_per_kwp=1000.0,
            grant_gbp=0.0,
            retained_cash_floor=50.0,
            retail_rate=30.0,
        )
        # High-capex config (SAME scenario+fr, still interior, higher rate)
        finance_high = _make_finance_interior_cr6(
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retained_cash_floor=50.0,
            retail_rate=30.0,
        )

        sol_low = solve_cost_recovery_rate(scenario, finance_low, simulate=simulate)
        sol_high = solve_cost_recovery_rate(scenario, finance_high, simulate=simulate)

        # H2 hard assertions: capex → rate (strictly higher) AND outlay (strictly higher)
        assert sol_high.own_use_rate_pence_per_kwh > sol_low.own_use_rate_pence_per_kwh, (
            f"H2: higher capex must yield strictly higher rate; "
            f"low={sol_low.own_use_rate_pence_per_kwh:.4f}, "
            f"high={sol_high.own_use_rate_pence_per_kwh:.4f}"
        )
        assert sol_high.representative_outlay_gbp > sol_low.representative_outlay_gbp, (
            f"H2: higher capex must yield strictly higher outlay; "
            f"low=£{sol_low.representative_outlay_gbp:.2f}, "
            f"high=£{sol_high.representative_outlay_gbp:.2f}"
        )


# ---------------------------------------------------------------------------
# Step-7 RED / step-8 GREEN: TestFlexLowersSolvedRate
# ---------------------------------------------------------------------------


class TestFlexLowersSolvedRate:
    """Directional asserts: flex revenue ⟹ strictly lower solved own-use rate.

    Two independent flex channels:
    (a) grid-services income (exogenous £/kW/yr): adding grid_services lowers r*.
    (b) arbitrage/time-shift (endogenous physics): elevated sc minus CBS grid-charge
        cost lowers r* relative to flat-rate fleet.

    Both are demonstrated on the SAME interior fleet.
    RED until both channels are tuned in step-8.
    """

    def _build_base_interior(self) -> tuple:  # type: ignore[type-arg]
        """Base interior fleet (no flex, same fleet used for both directional tests)."""
        from solar_challenge.config import ScenarioConfig, SimulationPeriod

        n_homes = 5
        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
        homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
        scenario = ScenarioConfig(name="CR6-Flex-Base", period=period, homes=homes)
        return scenario, n_homes

    def test_grid_services_lowers_solved_rate(self) -> None:
        """(a) Grid-services: r0 (no services) > r1 (Central services > 0).

        More exogenous revenue ⟹ lower required own-use rate (affine monotone).
        Both solve at grid_services=0 and grid_services=Central use SAME energy mix.
        RED until magnitudes tuned in step-8.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, n_homes = self._build_base_interior()
        fr = _make_interior_fleet_cr6(n_homes=n_homes)
        simulate = lambda fc, s, e: fr  # noqa: E731

        # No grid-services (baseline)
        finance_no_gs = _make_finance_interior_cr6(
            retained_cash_floor=50.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )
        # Central grid-services value (non-zero, > 0 → lowers r*)
        # grid_services_income is computed as: income × Σ battery.max_discharge_kw
        # Each 5kWh BatteryConfig has max_discharge_kw = 2.5 (default)
        # → total = 5 × 2.5 = 12.5 kW; with income=100 → £1250/yr
        finance_with_gs = _make_finance_flex_cr6(
            grid_services=100.0,
            retained_cash_floor=50.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )

        sol0 = solve_cost_recovery_rate(scenario, finance_no_gs, simulate=simulate)
        sol1 = solve_cost_recovery_rate(scenario, finance_with_gs, simulate=simulate)

        assert sol1.own_use_rate_pence_per_kwh < sol0.own_use_rate_pence_per_kwh, (
            f"Grid-services must lower solved rate: "
            f"r0={sol0.own_use_rate_pence_per_kwh:.4f}, r1={sol1.own_use_rate_pence_per_kwh:.4f}"
        )

    def test_arbitrage_lowers_solved_rate(self) -> None:
        """(b) Arbitrage/time-shift: arbitrage-on fleet gives lower r* than flat-rate fleet.

        'Arbitrage-on' is modelled by an elevated self_kwh and a non-zero
        CBS grid-charge cost (cbs_grid_charge_cost > 0 → from a non-None grid_charge_cost
        series in SimulationResults). The net uplift (extra_sc × own_use − grid_charge)
        exceeds zero so the CBS earns more net revenue, requiring a lower solved r*.

        RED until the arbitrage-on synthetic aggregates are tuned in step-8.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, n_homes = self._build_base_interior()

        # Flat-rate fleet (baseline): grid_charge_cost=None → cbs_grid_charge=0
        fr_flat = _make_interior_fleet_cr6(n_homes=n_homes, self_kwh=2000.0)
        simulate_flat = lambda fc, s, e: fr_flat  # noqa: E731

        # Arbitrage-on fleet: elevated sc + CBS grid-charge cost (time-shift economics)
        # Net benefit = (uplift_sc × r) / 100 − grid_charge_cost
        # We need net_benefit > 0 at r=retail → uplift_sc × retail/100 > grid_charge/home
        fr_arb = _make_arbitrage_fleet_cr6(n_homes=n_homes)
        simulate_arb = lambda fc, s, e: fr_arb  # noqa: E731

        finance = _make_finance_interior_cr6(
            retained_cash_floor=50.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )

        sol_flat = solve_cost_recovery_rate(scenario, finance, simulate=simulate_flat)
        sol_arb = solve_cost_recovery_rate(scenario, finance, simulate=simulate_arb)

        assert sol_arb.own_use_rate_pence_per_kwh < sol_flat.own_use_rate_pence_per_kwh, (
            f"Arbitrage/time-shift must lower solved rate: "
            f"flat={sol_flat.own_use_rate_pence_per_kwh:.4f}, "
            f"arb={sol_arb.own_use_rate_pence_per_kwh:.4f}"
        )


# ---------------------------------------------------------------------------
# Step-9 RED / step-10 GREEN: TestThetaStaysGreen + TestPhysicsReconciliationColumn
# ---------------------------------------------------------------------------


class TestThetaStaysGreen:
    """In-file θ-isolation smoke: spreadsheet→economics path unchanged by CR6.

    CR6 adds no src/ changes, so the θ (task/48) spreadsheet calibration
    gate should be untouched. This cheap in-file guard re-verifies:
    - total_capex_gbp == £775,000 (Capital_Stack!B6) to abs=1.0
    - min_dscr ≥ 1.20 (covenant floor)
    NOT a duplication of θ: no new physics path here, just the spreadsheet column.
    RED until wired in step-10 (currently stubs reference θ helpers that need import).
    """

    def _build_theta_econ(self) -> "ProjectEconomics":  # type: ignore[name-defined]
        """Build [FIN]-assumption ProjectEconomics via spreadsheet_revenue_curve."""
        from solar_challenge.finance import project_economics, spreadsheet_revenue_curve

        curve = spreadsheet_revenue_curve(
            n_homes=100,
            pv_kwp=_FIN_GOLDEN["inp_kWp"],
            kwh_per_kwp=_FIN_GOLDEN["inp_kWhPerkWp"],
            self_consumption_fraction=_FIN_SCF,
            own_use_rate_pence_per_kwh=_FIN_GOLDEN["own_use_rate_pence_per_kwh"],
            export_rate_pence_per_kwh=_FIN_GOLDEN["export_rate_pence_per_kwh"],
            asset_life_years=25,
        )
        scenario = _make_scenario_fin_cr6(n_homes=100, pv_kwp=5.5, battery_kwh=5.0)
        finance = _make_finance_fin_cr6()
        return project_economics(curve, scenario, finance)

    def test_spreadsheet_path_capex_and_dscr_unchanged(self) -> None:
        """θ-isolation: capex==£775k (Capital_Stack!B6) and min_dscr≥1.20 still hold.

        Verifies CR6 leaves the spreadsheet→economics path untouched.
        capex check: 100 × (5.5×£1000 + £1000 + 5kWh×£250) = £775,000.
        dscr check: covenant floor (not the exact spreadsheet digit-match).
        """
        econ = self._build_theta_econ()

        assert econ.total_capex_gbp == pytest.approx(
            _FIN_GOLDEN["capital_stack_b6"], abs=1.0
        ), (
            f"θ-isolation: capex expected £{_FIN_GOLDEN['capital_stack_b6']:,.0f}, "
            f"got £{econ.total_capex_gbp:,.2f}"
        )
        assert econ.min_dscr >= 1.20, (
            f"θ-isolation: min_dscr={econ.min_dscr:.4f} below covenant floor 1.20"
        )


# ---------------------------------------------------------------------------
# Task-84 grid-charge simulation builder (step-3 / step-4)
# ---------------------------------------------------------------------------


def _make_grid_charge_sim_results_cr6(
    self_kwh: float,
    export_kwh: float,
    import_to_load_kwh: float,
    grid_charge_kwh: float,
    grid_charge_cost_per_home_gbp: float,
    n_steps: int = 8760,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a synthetic SimulationResults for grid-charging (arbitrage) homes.

    Energy accounting:
        total_grid_import = import_to_load + grid_charge  (both cross grid boundary)
        demand             = sc + import_to_load           (battery discharge in sc)
        basis C own-use   = demand − grid_import = sc − grid_charge < sc

    This exposes the B-vs-C gap: total_self_consumption (B-style, discharge-inclusive)
    is self_kwh, while demand − import is self_kwh − grid_charge_kwh.

    grid_charge_cost series is non-None so total_grid_charge_cost_gbp > 0 in the summary.
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = self_kwh / (n_steps / 60.0)
    exp_kw = export_kwh / (n_steps / 60.0)
    imp_to_load_kw = import_to_load_kwh / (n_steps / 60.0)
    grid_charge_kw = grid_charge_kwh / (n_steps / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_to_load_kw          # demand = sc + import_to_load
    total_imp_kw = imp_to_load_kw + grid_charge_kw  # inflated by grid_charge
    zeros = pd.Series(0.0, index=idx)

    charge_per_step = grid_charge_cost_per_home_gbp / n_steps

    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(total_imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=pd.Series(charge_per_step, index=idx),
    )


def _make_grid_charge_fleet_cr6(
    n_homes: int = 5,
    self_kwh: float = 2000.0,
    export_kwh: float = 400.0,
    import_to_load_kwh: float = 800.0,
    grid_charge_kwh: float = 200.0,
    grid_charge_cost_per_home_gbp: float = 30.0,
) -> "FleetResults":  # type: ignore[name-defined]
    """Build a grid-charging FleetResults for basis-C reconciliation tests.

    With defaults:
        total_self_consumption_kwh = 2000 kWh/home  (B-style)
        total_demand_kwh           = 2000 + 800 = 2800 kWh/home
        total_grid_import_kwh      = 800 + 200 = 1000 kWh/home
        _cbs_own_use_kwh           = 2800 − 1000 = 1800 kWh/home   (basis C)
        gap                        = 2000 − 1800 = 200 kWh/home     (= grid_charge)
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
    per_home = [
        _make_grid_charge_sim_results_cr6(
            self_kwh=self_kwh,
            export_kwh=export_kwh,
            import_to_load_kwh=import_to_load_kwh,
            grid_charge_kwh=grid_charge_kwh,
            grid_charge_cost_per_home_gbp=grid_charge_cost_per_home_gbp,
        )
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


# ---------------------------------------------------------------------------
# Task-84 RED / GREEN: TestCbsOwnUseKwhHelper — unit test for _cbs_own_use_kwh
# ---------------------------------------------------------------------------


class TestArbitrageBasisCReconciliation:
    """Basis-C reconciliation for grid-charging (arbitrage) fleets (task-84 step-3/4).

    Verifies three properties on a fleet where grid_charge_kwh > 0:
    (c) _cbs_own_use_kwh(s) < s.total_self_consumption_kwh (B-vs-C gap exposed)
    (a) project_multi_year().points[0].fleet_self_consumption_kwh == sum(_cbs_own_use_kwh)
        AND strictly < sum(total_self_consumption_kwh)
    Plus a flat/no-grid-charge control showing no gap.

    (a) is the RED-until-step-4 assertion: before the fix, _simulate_age
    aggregates total_self_consumption_kwh (B-style) rather than basis C.
    """

    _N_HOMES = 5
    _SELF_KWH = 2000.0
    _GRID_CHARGE_KWH = 200.0  # per home → basis C = 2000 - 200 = 1800

    def _build_grid_charge(self) -> tuple:  # type: ignore[type-arg]
        """Return (scenario, finance, fr, summaries) for the grid-charging fleet."""
        from solar_challenge.config import ScenarioConfig, SimulationPeriod
        from solar_challenge.home import calculate_summary

        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
        homes = [_make_home_config_fin_cr6() for _ in range(self._N_HOMES)]
        scenario = ScenarioConfig(name="CR6-Arb-BasisC", period=period, homes=homes)
        finance = _make_finance_interior_cr6(
            retained_cash_floor=27.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )
        fr = _make_grid_charge_fleet_cr6(
            n_homes=self._N_HOMES,
            self_kwh=self._SELF_KWH,
            grid_charge_kwh=self._GRID_CHARGE_KWH,
        )
        summaries = [calculate_summary(r) for r in fr.per_home_results]
        return scenario, finance, fr, summaries

    def test_c_helper_gap_on_grid_charge_homes(self) -> None:
        """(c) For each home: _cbs_own_use_kwh(s) < total_sc AND == demand - import."""
        from solar_challenge.finance import _cbs_own_use_kwh

        _, _, _, summaries = self._build_grid_charge()
        for s in summaries:
            basis_c = _cbs_own_use_kwh(s)
            # Basis C must be strictly less than B-style total_self_consumption_kwh
            assert basis_c < s.total_self_consumption_kwh, (
                f"Expected basis-C {basis_c:.1f} < sc {s.total_self_consumption_kwh:.1f}"
            )
            # And equals demand - import exactly
            assert basis_c == pytest.approx(
                s.total_demand_kwh - s.total_grid_import_kwh, rel=1e-9
            )

    def test_a_fleet_sc_is_basis_c(self) -> None:
        """(a) project_multi_year fleet_sc == sum(_cbs_own_use_kwh) < sum(total_sc).

        RED until step-4: before the fix _simulate_age uses total_self_consumption_kwh.
        """
        from solar_challenge.finance import _cbs_own_use_kwh, project_multi_year

        scenario, finance, fr, summaries = self._build_grid_charge()
        simulate = lambda fc, s, e: fr  # noqa: E731

        curve = project_multi_year(scenario, finance, simulate=simulate)
        year0 = curve.points[0]

        expected_basis_c = sum(_cbs_own_use_kwh(s) for s in summaries)
        b_style_sum = sum(s.total_self_consumption_kwh for s in summaries)

        # (a) fleet_self_consumption_kwh must equal the basis-C sum (not B-style)
        assert year0.fleet_self_consumption_kwh == pytest.approx(expected_basis_c, rel=1e-9), (
            f"fleet_sc should be basis-C {expected_basis_c:.1f} kWh "
            f"but got {year0.fleet_self_consumption_kwh:.1f} kWh "
            f"(B-style = {b_style_sum:.1f} kWh)"
        )
        # And must be strictly less than B-style
        assert year0.fleet_self_consumption_kwh < b_style_sum

    def test_flat_control_no_gap(self) -> None:
        """Flat-rate control: _cbs_own_use_kwh == total_sc when grid_charge==0."""
        from solar_challenge.finance import _cbs_own_use_kwh
        from solar_challenge.home import calculate_summary

        # Use the existing flat-rate builder (grid_charge_cost=None)
        flat_sr = _make_sim_results_cr6(self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)
        s = calculate_summary(flat_sr)
        # No grid charging → demand - import = sc + import - import = sc
        assert _cbs_own_use_kwh(s) == pytest.approx(s.total_self_consumption_kwh, rel=1e-9)

    def _build_grid_charge_interior(self) -> tuple:  # type: ignore[type-arg]
        """Return (scenario, finance, fr, summaries) for the interior grid-charging fleet.

        Interior-tuned: self_kwh=2800, grid_charge_kwh=200 → basis C = 2600/home
        fleet_sc (basis C) = 5 × 2600 = 13,000 kWh
        r* = (floor×n + opex + debt_svc + cbs_gc) / (fleet_sc/100) ≈ 21.2p < retail=30p
        → binding='floor', feasible=True.
        """
        from solar_challenge.config import ScenarioConfig, SimulationPeriod
        from solar_challenge.home import calculate_summary

        n_homes = 5
        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
        homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
        scenario = ScenarioConfig(name="CR6-Arb-Interior", period=period, homes=homes)
        finance = _make_finance_interior_cr6(
            retained_cash_floor=27.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )
        fr = _make_grid_charge_fleet_cr6(
            n_homes=n_homes,
            self_kwh=2800.0,         # sc (B-style, discharge-inclusive)
            export_kwh=400.0,
            import_to_load_kwh=800.0,
            grid_charge_kwh=200.0,   # → basis C = 2800 - 200 = 2600 kWh/home
            grid_charge_cost_per_home_gbp=30.0,
        )
        summaries = [calculate_summary(r) for r in fr.per_home_results]
        return scenario, finance, fr, summaries

    def test_b_solve_binds_floor_grid_charge(self) -> None:
        """(b) Interior grid-charging fleet: solve binding=='floor', surplus==27.0.

        After step-4, solve_cost_recovery_rate uses basis-C fleet_sc in the affine
        slope, so the interior condition holds for the grid-charging fleet and the
        closed-form identity surplus(r*) == floor is exact to float ε.
        """
        from solar_challenge.finance import solve_cost_recovery_rate

        scenario, finance, fr, summaries = self._build_grid_charge_interior()
        simulate = lambda fc, s, e: fr  # noqa: E731

        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.binding == "floor", (
            f"Expected binding='floor' for interior grid-charging fleet; got {sol.binding!r}"
        )
        assert sol.feasible is True
        assert sol.net_surplus_per_home_per_year_gbp == pytest.approx(27.0, abs=1e-6), (
            f"Expected net_surplus=27.0 (floor); got {sol.net_surplus_per_home_per_year_gbp:.8f}"
        )

    def test_b_bill_basis_c(self) -> None:
        """(b) bill_distribution uses basis C for own_use_payment after the fix.

        RED until step-6: before the fix, bill_distribution passes total_sc (B-style),
        giving own_use_payment = rate × total_sc/100, so the == assertion fails.
        After step-6 the == assertion passes and < assertion confirms the gap.
        """
        import dataclasses
        from solar_challenge.finance import (
            _cbs_own_use_kwh,
            bill_distribution,
            solve_cost_recovery_rate,
        )

        scenario, finance, fr, summaries = self._build_grid_charge_interior()
        simulate = lambda fc, s, e: fr  # noqa: E731

        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)
        rate = sol.own_use_rate_pence_per_kwh

        # Build bill distribution at the solved rate
        finance_solved = dataclasses.replace(finance, own_use_rate_pence_per_kwh=rate)
        sim_days = summaries[0].simulation_days
        dist = bill_distribution(summaries, finance_solved, sim_days)
        rep_bill = dist.representative

        # Find the summary that is the representative (median-outlay home)
        # bill_distribution selects by median total_outlay; all homes are identical
        # so any summary will do; use summaries[0].
        rep_summary = summaries[0]
        basis_c_kwh = _cbs_own_use_kwh(rep_summary)
        b_style_kwh = rep_summary.total_self_consumption_kwh

        # After step-6: own_use_payment == rate × basis_c / 100
        assert rep_bill.own_use_payment_gbp == pytest.approx(
            rate * basis_c_kwh / 100.0, rel=1e-9
        ), (
            f"own_use_payment should be rate×basis_c/100 = {rate:.4f}×{basis_c_kwh:.1f}/100 "
            f"= {rate * basis_c_kwh / 100:.4f} GBP; "
            f"got {rep_bill.own_use_payment_gbp:.4f} GBP "
            f"(B-style would be {rate * b_style_kwh / 100:.4f})"
        )
        # Gap: basis-C payment < B-style payment (on grid-charging homes)
        assert rep_bill.own_use_payment_gbp < rate * b_style_kwh / 100.0

    def test_b_flat_control_still_binds_floor(self) -> None:
        """Flat-rate fleet control: solve still binding='floor' with same finance."""
        from solar_challenge.finance import solve_cost_recovery_rate

        # Use the no-grid-charge interior fleet with the same finance config
        from solar_challenge.config import ScenarioConfig, SimulationPeriod

        n_homes = 5
        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
        homes = [_make_home_config_fin_cr6() for _ in range(n_homes)]
        scenario = ScenarioConfig(name="CR6-Flat-Control", period=period, homes=homes)
        finance = _make_finance_interior_cr6(
            retained_cash_floor=27.0,
            pv_cost_per_kwp=2000.0,
            grant_gbp=0.0,
            retail_rate=30.0,
        )
        fr = _make_interior_fleet_cr6(n_homes=n_homes, self_kwh=2000.0)
        simulate = lambda fc, s, e: fr  # noqa: E731

        sol = solve_cost_recovery_rate(scenario, finance, simulate=simulate)

        assert sol.binding == "floor", (
            f"Flat control: expected binding='floor'; got {sol.binding!r}"
        )
        assert sol.feasible is True


class TestCbsOwnUseKwhHelper:
    """Unit tests for the module-level helper _cbs_own_use_kwh (basis C).

    Basis C: own_use_kwh = max(total_demand_kwh − total_grid_import_kwh, 0.0)
    Tests cover the normal case and the clamp-to-zero case.
    """

    def test_normal_case(self) -> None:
        """demand=3400, import=1600 → basis C = 1800 kWh."""
        from solar_challenge.finance import _cbs_own_use_kwh

        s = _make_sim_results_cr6(
            self_kwh=1800.0,
            export_kwh=400.0,
            import_kwh=1600.0,
        )
        from solar_challenge.home import calculate_summary
        summary = calculate_summary(s)
        # total_demand = sc + import = 1800 + 1600 = 3400
        # total_grid_import = 1600
        # basis C = 3400 - 1600 = 1800
        assert _cbs_own_use_kwh(summary) == pytest.approx(1800.0, rel=1e-9)

    def test_clamp_to_zero(self) -> None:
        """Degenerate: import > demand → basis C clamped to 0.0."""
        from solar_challenge.finance import _cbs_own_use_kwh

        # Build a summary with demand=500, import=900 by construction.
        # demand = sc + import → sc = demand - import = 500 - 900 = -400 (impossible in physics)
        # Instead, build manually via _make_sim_results_cr6 with sc=0, import>demand:
        # Use sc=500, import=900 → demand=1400 (still basis C > 0).
        # We need a summary where demand < import to test the clamp.
        # Build summary directly to set total_demand_kwh=500, total_grid_import_kwh=900.
        import pandas as pd
        from solar_challenge.home import SimulationResults, calculate_summary

        n_steps = 8760
        idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")
        zeros = pd.Series(0.0, index=idx)
        # demand_kw such that sum*(1/60) = 500 kWh
        demand_kw = 500.0 / (n_steps / 60.0)
        # import_kw such that sum*(1/60) = 900 kWh
        import_kw = 900.0 / (n_steps / 60.0)
        # gen_kw = 0 (no generation)
        sr = SimulationResults(
            generation=zeros.copy(),
            demand=pd.Series(demand_kw, index=idx),
            self_consumption=zeros.copy(),
            battery_charge=zeros.copy(),
            battery_discharge=zeros.copy(),
            battery_soc=zeros.copy(),
            grid_import=pd.Series(import_kw, index=idx),
            grid_export=zeros.copy(),
            import_cost=zeros.copy(),
            export_revenue=zeros.copy(),
            tariff_rate=zeros.copy(),
            grid_charge_cost=None,
        )
        summary = calculate_summary(sr)
        # total_demand = 500, total_grid_import = 900 → demand - import = -400 → clamp to 0.0
        from solar_challenge.finance import _cbs_own_use_kwh
        assert summary.total_demand_kwh == pytest.approx(500.0, rel=1e-9)
        assert summary.total_grid_import_kwh == pytest.approx(900.0, rel=1e-9)
        assert _cbs_own_use_kwh(summary) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.slow
class TestPhysicsReconciliationColumn:
    """Real-PVGIS physics column — REPORTED, not asserted == spreadsheet (step-9 RED / step-10 GREEN).

    Runs a 2-home, 3-day fleet simulation via real simulate_fleet to document
    the physics-vs-assumption self-consumption gap that motivates 'reported not pinned'.
    Mirrors θ's TestCalibrationPhysicsColumn.
    Marked @pytest.mark.slow — excluded from -m 'not slow' runs.
    """

    def test_physics_path_reported(self) -> None:
        """Physics path: valid CostRecoverySolution returned; rate/saving/surplus printed.

        Hard-asserts ONLY structural properties (not physics-path rate == anything):
        - CostRecoverySolution is returned (no exception)
        - sol.feasible is a bool
        - sol.binding in {'floor', 'rate_clamped_zero', 'infeasible_above_retail'}

        REPORTS (printed, NOT pinned): physics-path solved rate, saving, surplus.
        Motivates 'reported not pinned' — physics scf (≈20–35%) ≠ sheet 0.70.
        """
        from solar_challenge.config import ScenarioConfig, SimulationPeriod
        from solar_challenge.finance import CostRecoverySolution, solve_cost_recovery_rate

        # 2-home fleet, 3-day window, 5.5kWp+5kWh (real simulate_fleet via default simulate=None)
        homes = [_make_home_config_fin_cr6(pv_kwp=5.5, battery_kwh=5.0)] * 2
        period = SimulationPeriod(start_date="2024-01-01", end_date="2024-01-03")
        scenario = ScenarioConfig(
            name="CR6-Physics-Test",
            period=period,
            homes=homes,
        )
        finance = _make_finance_fin_cr6()

        # Real physics simulation (simulate=None → real simulate_fleet)
        sol = solve_cost_recovery_rate(scenario, finance)

        # STRUCTURAL assertions only
        assert isinstance(sol, CostRecoverySolution)
        assert isinstance(sol.feasible, bool)
        assert sol.binding in ("floor", "rate_clamped_zero", "infeasible_above_retail"), (
            f"Unexpected binding value: {sol.binding!r}"
        )

        # REPORT (printed, NOT asserted as equal to anything)
        print(
            f"\n[PHYSICS RECONCILIATION REPORT] (2 homes, 3-day window)"
            f"\n  Physics-path solved rate: {sol.own_use_rate_pence_per_kwh:.2f} p/kWh"
            f"  (synthetic ≈15p; gap = physics scf << 0.70)"
            f"\n  Physics saving vs baseline: £{sol.saving_vs_baseline_gbp:.0f}"
            f"\n  Net surplus/home/yr: £{sol.net_surplus_per_home_per_year_gbp:.2f}"
            f"\n  Binding: {sol.binding}, Feasible: {sol.feasible}"
            f"\n  [Reported not pinned: physics scf ≠ 0.70/sheet — see §3.3 of"
            f" docs/finance-spreadsheet-reconciliation.md for rationale]"
        )
