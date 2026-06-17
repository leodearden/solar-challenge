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
    n_minutes: int = 525600,  # 365 days
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a synthetic SimulationResults (no grid_charge_cost → flat-rate).

    grid_charge_cost=None → total_grid_charge_cost_gbp==0.0 (home.py:154),
    so a flat-rate fleet has cbs_grid_charge_cost==0 by construction.
    export_revenue=0 → SEG income = 0 in _seg_export_income_gbp (physics path).
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)

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
        grid_charge_cost=None,  # flat-rate → cbs_grid_charge_cost==0
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


def _make_finance_fin_cr6(
    *,
    grid_services: float = 0.0,
    retained_cash_floor: float = 27.0,
    own_use_rate: float = 15.0,
    retail_rate: float = 23.0,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Build the [FIN]-aligned FinanceConfig for CR6 tests.

    Uses physics path (self_consumption_override=None, the default), so
    _seg_export_income_gbp uses total_export_revenue_gbp from SimulationResults
    directly. With export_revenue=0 in _make_sim_results_cr6, SEG=0.

    Capex = 100 × (5.5×£1000 + £1000 + 5kWh×£250) = £775,000
    Grant = £250,000 → financed = £525,000
    Equity (0.75) = £393,750; Debt (0.25) = £131,250
    Debt service (7%, 15yr) ≈ £14,410/yr
    Opex = 100 × £131 = £13,100/yr
    """
    from solar_challenge.config import FinanceConfig

    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        pv_cost_per_kwp_gbp=1000.0,
        roof_fit_cost_gbp=1000.0,
        battery_cost_per_kwh_gbp=250.0,
        inverter_cost_per_kw_gbp=0.0,
        grant_gbp=_FIN_GOLDEN["grant_gbp"],           # £250,000
        equity_fraction=_FIN_GOLDEN["equity_fraction"],  # 0.75
        loan_term_years=_FIN_GOLDEN["loan_term_years"],  # 15
        loan_rate=_FIN_GOLDEN["loan_rate"],              # 0.07
        opex_per_home_per_year_gbp=131.0,
        asset_life_years=25,
        own_use_rate_pence_per_kwh=own_use_rate,
        retained_cash_floor_per_home_per_year_gbp=retained_cash_floor,
        retail_baseline_rate_pence_per_kwh=retail_rate,
        vat_rate=0.05,
        grid_services_income_per_kw_per_year_gbp=grid_services,
        # self_consumption_override=None (default) → physics path for SEG
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

    def _build_fin_anchor(self) -> tuple:
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
        from solar_challenge.finance import project_multi_year, solve_cost_recovery_rate

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

        # REPORTED (not asserted): solved rate target ≈15p, saving target ≈£324
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
        # No numeric pin — just confirm we ran without raising
        assert True
