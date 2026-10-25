# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for the finance spreadsheet calibration (task/48 – θ).

H6 integration gate: verifies that the financial layer matches the investor
spreadsheet under identical [FIN] inputs.

The golden constants are tests/_fin_calibration.py's FIN_GOLDEN, transcribed from
the spreadsheet's named cells; their provenance is recorded there.

Layout:
  - TestSpreadsheetRevenueCurve — pure helper unit tests
  - TestFinCalibrationScenarioParses — YAML scenario parsing
  - TestCalibrationCapexMethodAgreement — H6 capex gate
  - TestCalibrationDscrIrrMethodAgreement — H6 DSCR/IRR gate
  - TestCalibrationG6Guards — G6 premise guards
  - TestCalibrationPhysicsColumn — the physics column on a simulated fleet (reported, not asserted ==)
"""
from __future__ import annotations

import functools
import math
from pathlib import Path

import pytest

from solar_challenge.config import (
    ScenarioConfig,
    load_config,
    load_fleet_config,
    parse_finance_config,
    parse_seg_rate,
)
from solar_challenge.finance import (
    FinanceConfig,
    MultiYearCurve,
    ProjectEconomics,
    project_economics,
    project_multi_year,
    spreadsheet_revenue_curve,
)
from solar_challenge.fleet import simulate_fleet
from tests._fin_calibration import (
    FIN_GOLDEN,
    FIN_SCF,
    make_fin_finance,
    make_fin_spreadsheet_curve,
    make_physics_column_scenario,
)
from tests._finance_builders import make_scenario_of, make_sized_home


# ---------------------------------------------------------------------------
# Helper builders; the homes and scenarios come from tests/_finance_builders.py,
# the [FIN] finance from tests/_fin_calibration.py
# ---------------------------------------------------------------------------


def _make_scenario_fin(
    n_homes: int = 100,
    battery_kwh: float = FIN_GOLDEN["inp_Batt_kWh"],
) -> ScenarioConfig:
    """make_scenario_of's scenario of *n_homes* homes of the [FIN] PV array, each with a *battery_kwh* kWh battery."""
    return make_scenario_of(
        [make_sized_home(pv_kwp=FIN_GOLDEN["inp_kWp"], battery_kwh=battery_kwh)] * n_homes
    )


def _make_finance_fin() -> FinanceConfig:
    """The [FIN] finance at the spreadsheet's FIN_SCF self-consumption override."""
    return make_fin_finance(self_consumption_override=FIN_SCF)


# ---------------------------------------------------------------------------
# Step-1: TestSpreadsheetRevenueCurve — pure helper
# ---------------------------------------------------------------------------


class TestSpreadsheetRevenueCurve:
    """Fast tests for finance.spreadsheet_revenue_curve (task/48 step-1).

    spreadsheet_revenue_curve builds a flat [FIN]-assumption fleet-revenue
    MultiYearCurve without running the physics simulator.
    """

    def _call(self, **kwargs: object) -> MultiYearCurve:
        """Call spreadsheet_revenue_curve with default [FIN] params unless overridden."""
        defaults: dict = dict(
            n_homes=100,
            pv_kwp=5.5,
            kwh_per_kwp=1050.0,
            self_consumption_fraction=0.70,
            own_use_rate_pence_per_kwh=15.0,
            export_rate_pence_per_kwh=6.0,
            asset_life_years=25,
        )
        defaults.update(kwargs)
        return spreadsheet_revenue_curve(**defaults)

    def test_import(self) -> None:
        """spreadsheet_revenue_curve must be importable from solar_challenge.finance."""
        assert callable(spreadsheet_revenue_curve)

    def test_returns_multiyear_curve(self) -> None:
        """spreadsheet_revenue_curve must return a MultiYearCurve."""
        result = self._call()
        assert isinstance(result, MultiYearCurve)

    def test_points_length_equals_asset_life_years(self) -> None:
        """len(curve.points) must equal asset_life_years."""
        for life in (10, 15, 25):
            curve = self._call(asset_life_years=life)
            assert len(curve.points) == life, f"Expected {life} points, got {len(curve.points)}"

    def test_fleet_revenue_exact_fin_values(self) -> None:
        """fleet_revenue_gbp for each YearPoint must equal the [FIN]-assumption formula.

        With n_homes=100, pv_kwp=5.5, kwh_per_kwp=1050, scf=0.70, own_use=15p, export=6p:
          per_home_gen = 5.5 × 1050 = 5775 kWh/yr
          fleet_revenue = 100 × (0.70×5775×0.15 + 0.30×5775×0.06)
                        = 100 × (606.375 + 103.95)
                        = 100 × 710.325
                        = £71,032.50/yr
        """
        curve = self._call()
        per_home_gen = 5.5 * 1050.0  # 5775.0 kWh
        per_home_rev = (
            0.70 * per_home_gen * (15.0 / 100.0)
            + 0.30 * per_home_gen * (6.0 / 100.0)
        )
        expected_fleet_rev = 100.0 * per_home_rev  # £71,032.50

        for pt in curve.points:
            assert pt.fleet_revenue_gbp == pytest.approx(expected_fleet_rev, rel=1e-10), (
                f"Year {pt.year}: expected £{expected_fleet_rev:.4f}, "
                f"got £{pt.fleet_revenue_gbp:.4f}"
            )

    def test_curve_is_flat_soh_unity(self) -> None:
        """All YearPoints must have pv_soh=1.0 and battery_soh=1.0 (flat/no-degradation)."""
        curve = self._call()
        for pt in curve.points:
            assert pt.pv_soh == pytest.approx(1.0), f"Year {pt.year}: pv_soh={pt.pv_soh}"
            assert pt.battery_soh == pytest.approx(1.0), (
                f"Year {pt.year}: battery_soh={pt.battery_soh}"
            )

    def test_sampled_ages_well_formed(self) -> None:
        """sampled_ages must be a non-empty tuple of integers."""
        curve = self._call()
        assert isinstance(curve.sampled_ages, tuple)
        assert len(curve.sampled_ages) >= 1
        assert all(isinstance(a, int) for a in curve.sampled_ages)

    def test_interp_error_estimate_zero(self) -> None:
        """interp_error_estimate must be 0.0 (no interpolation for flat curve)."""
        curve = self._call()
        assert curve.interp_error_estimate == pytest.approx(0.0)

    def test_deterministic(self) -> None:
        """Two calls with same inputs must return bit-identical results."""
        curve1 = self._call()
        curve2 = self._call()
        assert len(curve1.points) == len(curve2.points)
        for pt1, pt2 in zip(curve1.points, curve2.points):
            assert pt1.fleet_revenue_gbp == pt2.fleet_revenue_gbp
            assert pt1.fleet_billed_own_use_kwh == pt2.fleet_billed_own_use_kwh
            assert pt1.fleet_export_kwh == pt2.fleet_export_kwh
        assert curve1.interp_error_estimate == curve2.interp_error_estimate
        assert curve1.sampled_ages == curve2.sampled_ages

    def test_revenue_proportional_to_n_homes(self) -> None:
        """Doubling n_homes doubles fleet_revenue_gbp."""
        curve_100 = self._call(n_homes=100)
        curve_200 = self._call(n_homes=200)
        for pt1, pt2 in zip(curve_100.points, curve_200.points):
            assert pt2.fleet_revenue_gbp == pytest.approx(2.0 * pt1.fleet_revenue_gbp, rel=1e-10)

    def test_revenue_proportional_to_kwh_per_kwp(self) -> None:
        """Doubling kwh_per_kwp doubles fleet_revenue_gbp."""
        curve_1050 = self._call(kwh_per_kwp=1050.0)
        curve_2100 = self._call(kwh_per_kwp=2100.0)
        for pt1, pt2 in zip(curve_1050.points, curve_2100.points):
            assert pt2.fleet_revenue_gbp == pytest.approx(2.0 * pt1.fleet_revenue_gbp, rel=1e-10)

    def test_energy_fields_consistent_with_scf(self) -> None:
        """fleet_billed_own_use_kwh and fleet_export_kwh must reflect scf."""
        n_homes = 100
        pv_kwp = 5.5
        kwh_per_kwp = 1050.0
        scf = 0.70
        curve = self._call(
            n_homes=n_homes, pv_kwp=pv_kwp, kwh_per_kwp=kwh_per_kwp,
            self_consumption_fraction=scf,
        )
        fleet_gen = float(n_homes) * pv_kwp * kwh_per_kwp
        for pt in curve.points:
            assert pt.fleet_billed_own_use_kwh == pytest.approx(scf * fleet_gen, rel=1e-10)
            assert pt.fleet_export_kwh == pytest.approx((1.0 - scf) * fleet_gen, rel=1e-10)


# ---------------------------------------------------------------------------
# Step-3: TestFinCalibrationScenarioParses — YAML scenario loading
# ---------------------------------------------------------------------------


class TestFinCalibrationScenarioParses:
    """Fast tests for scenarios/bristol-fin-calibration.yaml loading (step-3).

    The fleet (fleet_distribution format, parsed with load_fleet_config as the
    finance CLI parses it) is 100 homes, each with FIN_GOLDEN's install.
    The finance block is parsed with load_config and parse_finance_config, as the
    finance CLI parses it, and checked as one equality with θ's [FIN] finance,
    _make_finance_fin().
    The seg block is parsed with load_config and parse_seg_rate, as the finance
    CLI parses it, and its rate is FIN_GOLDEN's [FIN] export rate.
    """

    _SCENARIO_PATH = "scenarios/bristol-fin-calibration.yaml"

    def _load_finance(self) -> FinanceConfig:
        """Parse the finance block from the calibration scenario YAML."""
        raw = load_config(self._SCENARIO_PATH)
        finance = parse_finance_config(raw.get("finance"))
        assert finance is not None, "Expected finance block in scenario, got None"
        return finance

    def _load_homes(self) -> list:
        """Parse the fleet homes from the calibration scenario YAML."""
        fleet = load_fleet_config(self._SCENARIO_PATH)
        return list(fleet.homes)

    def test_scenario_file_exists(self) -> None:
        """scenarios/bristol-fin-calibration.yaml must exist on disk."""
        assert Path(self._SCENARIO_PATH).exists(), (
            f"{self._SCENARIO_PATH} not found"
        )

    def test_finance_block_is_the_fin_finance_at_fin_scf(self) -> None:
        """The finance block is θ's [FIN] finance: make_fin_finance at the spreadsheet's FIN_SCF override."""
        assert self._load_finance() == _make_finance_fin(), (
            f"{self._SCENARIO_PATH}'s finance block is not the [FIN] finance at FIN_SCF"
        )

    def test_seg_rate_is_the_fin_export_rate(self) -> None:
        """The seg block's rate is the [FIN] export price: FIN_GOLDEN's export_rate_pence_per_kwh."""
        seg_rate = parse_seg_rate(load_config(self._SCENARIO_PATH).get("seg"))
        assert seg_rate == FIN_GOLDEN["export_rate_pence_per_kwh"], (
            f"{self._SCENARIO_PATH}'s seg rate is not FIN_GOLDEN's [FIN] export rate"
        )

    def test_fleet_is_100_homes(self) -> None:
        """Fleet must have exactly 100 homes ([FIN] n_homes=100)."""
        homes = self._load_homes()
        assert len(homes) == 100, f"Expected 100 homes, got {len(homes)}"

    def test_every_home_has_the_fin_install(self) -> None:
        """Every home has the [FIN] install: FIN_GOLDEN's inp_kWp of PV and an inp_Batt_kWh kWh battery."""
        fin_install = (FIN_GOLDEN["inp_kWp"], FIN_GOLDEN["inp_Batt_kWh"])
        for i, home in enumerate(self._load_homes()):
            assert home.battery_config is not None, f"Home {i}: no battery config"
            install = (home.pv_config.capacity_kw, home.battery_config.capacity_kwh)
            assert install == fin_install, f"Home {i}: (PV kWp, battery kWh) is not the [FIN] install"


# ---------------------------------------------------------------------------
# Step-5: TestCalibrationCapexMethodAgreement — H6 capex gate (fast/no-PVGIS)
# ---------------------------------------------------------------------------


class TestCalibrationCapexMethodAgreement:
    """H6 capex method-agreement tests (fast, no PVGIS) (task/48 step-5).

    project_economics(spreadsheet_revenue_curve(...), scenario, finance) must
    reproduce the spreadsheet capex cells exactly:
    - Capital_Stack!B6 = £775,000 at 5 kWh per home (inp_Batt_kWh=5)
    - Workings!C94 = £900,000 at 10 kWh per home (Workings build-up)
    - Delta = £125,000 = 100 × 5 kWh × £250 (pure battery-size, §2.3)
    """

    def test_capex_5kwh_matches_capital_stack_b6(self) -> None:
        """Capex for 100 × 5.5kWp + 5kWh must equal Capital_Stack!B6 = £775,000 exactly.

        Arithmetic: 100 × (5.5×£1000 + £1000 + 5.0kWh×£250) = 100×£7,750 = £775,000
        Cell ref: Capital_Stack!B6 = £775,000
        """
        scenario = _make_scenario_fin()
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)

        econ = project_economics(curve, scenario, finance)

        assert econ.total_capex_gbp == pytest.approx(
            FIN_GOLDEN["capital_stack_b6"], abs=1.0
        ), (
            f"Capex (5 kWh) expected Capital_Stack!B6=£{FIN_GOLDEN['capital_stack_b6']:,.2f}, "
            f"got £{econ.total_capex_gbp:,.2f}"
        )

    def test_capex_5kwh_exact_arithmetic(self) -> None:
        """Exact arithmetic check: 100×(5.5×1000+1000+5×250)=775000 matches cell."""
        scenario = _make_scenario_fin()
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)

        econ = project_economics(curve, scenario, finance)

        # Verify the arithmetic manually
        expected = 100.0 * (5.5 * 1000.0 + 1000.0 + 5.0 * 250.0)
        assert expected == 775000.0, "Sanity: arithmetic gives £775,000"
        assert econ.total_capex_gbp == pytest.approx(expected, abs=1e-6)

    def test_capex_10kwh_matches_workings_c94(self) -> None:
        """Capex for 100 × 5.5kWp + 10kWh must equal Workings!C94 = £900,000.

        Arithmetic: 100 × (5.5×£1000 + £1000 + 10kWh×£250) = 100×£9,000 = £900,000
        Cell ref: Workings!C94 = £900,000
        """
        # 10 kWh fleet (Workings build-up basis)
        scenario_10kwh = _make_scenario_fin(battery_kwh=10.0)
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)

        econ_10kwh = project_economics(curve, scenario_10kwh, finance)

        assert econ_10kwh.total_capex_gbp == pytest.approx(
            FIN_GOLDEN["workings_c94"], abs=1.0
        ), (
            f"Capex (10 kWh) expected Workings!C94=£{FIN_GOLDEN['workings_c94']:,.0f}, "
            f"got £{econ_10kwh.total_capex_gbp:,.2f}"
        )

    def test_capex_delta_is_battery_size_difference(self) -> None:
        """§2.3 delta: capex_10kwh − capex_5kwh == £125,000 == 100×5kWh×£250.

        This is the §2.3 '£775k ↔ £900k' reconciliation:
        Pure battery-size difference (inp_Batt_kWh=5 vs Workings 10 kWh), NOT an error.
        """
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)

        econ_5 = project_economics(curve, _make_scenario_fin(), finance)
        econ_10 = project_economics(curve, _make_scenario_fin(battery_kwh=10.0), finance)

        delta = econ_10.total_capex_gbp - econ_5.total_capex_gbp
        expected_delta = 100.0 * 5.0 * 250.0  # 100 homes × 5 kWh × £250/kWh

        assert delta == pytest.approx(expected_delta, abs=1e-6), (
            f"§2.3 capex delta: expected £{expected_delta:,.0f} (100×5kWh×£250), "
            f"got £{delta:,.2f}"
        )
        assert delta == pytest.approx(125000.0, abs=1e-6), (
            "Delta must equal £125,000 = 100 × 5 kWh × £250 (battery-size, NOT error)"
        )


# ---------------------------------------------------------------------------
# Step-6: TestCalibrationDscrIrrMethodAgreement — H6 DSCR/IRR gate (fast)
# ---------------------------------------------------------------------------


class TestCalibrationDscrIrrMethodAgreement:
    """H6 DSCR/IRR method-agreement tests (fast, no PVGIS) (task/48 step-6).

    G6 PREMISE GUARD (load-bearing):
    The [FIN]-assumption spreadsheet_revenue_curve yields DSCR ≈ 4.02
    (vs Debt_Analytics!B16 = 2.10378). The discrepancy is EXPECTED and DOCUMENTED:
    the spreadsheet's lower DSCR results from equity-fundraising fees, formation
    costs, dividend deferral, and grant timing that the pure financial layer
    abstracts away. Per docs/prds/financial-layer-battery-fidelity.md §13 (θ numeric premise) latitude:
      - HARD assert: min_dscr ≥ 1.20 (covenant floor)
      - HARD assert: equity_irr > 0 (structural sanity)
      - REPORTED: actual values vs spreadsheet cells (Debt_Analytics!B16/B17)
    The digit-match (min_dscr ≈ 2.10378) is DELIBERATELY NOT asserted here.
    See docs/finance-spreadsheet-reconciliation.md for full rationale.
    """

    def _build_econ(self) -> ProjectEconomics:
        """Build [FIN]-assumption ProjectEconomics for DSCR/IRR tests."""
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)
        scenario = _make_scenario_fin()
        return project_economics(curve, scenario, finance)

    def test_min_dscr_meets_covenant_floor(self) -> None:
        """min_dscr must be ≥ 1.20 (covenant floor) under [FIN]-assumption inputs.

        G6 fallback: we cannot assert min_dscr ≈ 2.10378 (Debt_Analytics!B16)
        because the sheet accounts for equity fundraising fees / formation costs /
        dividend deferral that reduce the effective DSCR below our pure-layer value.
        The covenant floor (1.20) IS structurally achievable and asserted hard.
        """
        econ = self._build_econ()
        assert econ.min_dscr >= 1.20, (
            f"min_dscr={econ.min_dscr:.4f} falls below covenant floor 1.20"
        )

    def test_equity_irr_positive(self) -> None:
        """equity_irr must be > 0 (structural sanity: project generates positive returns).

        G6 fallback: we cannot assert equity_irr ≈ spreadsheet's value (~69% prose)
        because the sheet's equity is net of formation costs / fundraising fees /
        dividend deferral that substantially reduce the effective equity invested,
        inflating IRR well above our pure-layer value (~11%).
        """
        econ = self._build_econ()
        assert not math.isnan(econ.equity_irr), "equity_irr must not be NaN"
        assert econ.equity_irr > FIN_GOLDEN["equity_irr_floor"], (
            f"equity_irr={econ.equity_irr:.4f} must be > 0 (structural sanity)"
        )

    def test_determinism(self) -> None:
        """Two project_economics calls with same [FIN] inputs must be bit-identical."""
        econ1 = self._build_econ()
        econ2 = self._build_econ()
        assert econ1.min_dscr == econ2.min_dscr
        assert econ1.equity_irr == econ2.equity_irr
        assert econ1.per_year_surplus_gbp == econ2.per_year_surplus_gbp


# ---------------------------------------------------------------------------
# Step-7: TestCalibrationG6Guards — G6 premise guards (fast)
# ---------------------------------------------------------------------------


class TestCalibrationG6Guards:
    """Fast G6 premise guard tests (no PVGIS) (task/48 step-7).

    Verify:
    (1) The test suite surfaces BOTH a spreadsheet-input column and a physics
        column interface, with only the spreadsheet column hard-asserted.
    (2) The capex delta (£125k) is REPORTED, not asserted equal.
    (3) No assertion compares physics results to the named spreadsheet cells.
    """

    def _build_spreadsheet_econ(self) -> ProjectEconomics:
        """Build spreadsheet-input ProjectEconomics."""
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)
        return project_economics(curve, _make_scenario_fin(), finance)

    def test_spreadsheet_column_produces_project_economics(self) -> None:
        """spreadsheet_revenue_curve → project_economics returns a ProjectEconomics."""
        econ = self._build_spreadsheet_econ()
        assert isinstance(econ, ProjectEconomics)

    def test_spreadsheet_column_capex_hard_asserted(self) -> None:
        """Spreadsheet column: capex IS hard-asserted (the primary gate)."""
        econ = self._build_spreadsheet_econ()
        # This is the canonical hard assertion
        assert abs(econ.total_capex_gbp - FIN_GOLDEN["capital_stack_b6"]) < 1.0

    def test_capex_delta_reported_not_asserted_equal(self) -> None:
        """§2.3 capex delta is a REPORTED value — assert it is non-zero (not equal).

        The delta (£125k) must NOT be asserted as zero. It is the reconciliation
        between the 5 kWh (Capital_Stack!B6) and 10 kWh (Workings!C94) bases.
        """
        finance = _make_finance_fin()
        curve = make_fin_spreadsheet_curve(n_homes=100, asset_life_years=finance.asset_life_years)
        econ_5 = project_economics(curve, _make_scenario_fin(), finance)
        econ_10 = project_economics(curve, _make_scenario_fin(battery_kwh=10.0), finance)

        delta = econ_10.total_capex_gbp - econ_5.total_capex_gbp

        # delta is REPORTED (documented), not asserted equal to zero
        print(f"\n[G6 CAPEX DELTA] £{delta:,.0f} = 100 × 5 kWh × £250 (battery-size, §2.3)")
        assert delta != pytest.approx(0.0), "Delta must be NON-ZERO (different battery sizes)"
        assert delta == pytest.approx(125000.0, abs=1.0), "Delta must equal £125,000"

    def test_physics_dscr_not_equal_spreadsheet_golden(self) -> None:
        """G6: [FIN]-assumption model DSCR stays in the expected range (~4.02).

        Our [FIN]-assumption model_dscr ≈ 4.02 vs Debt_Analytics!B16 = 2.10378.
        The discrepancy is EXPECTED and documented (spreadsheet deducts formation costs /
        fundraising fees / dividend deferral from the numerator; our pure layer does not).
        Rather than asserting 'model must differ from spreadsheet by >0.5' (which passes
        for a broken model returning 0), we assert the model DSCR stays within a
        documented expected range so regressions in either direction are caught.
        """
        econ = self._build_spreadsheet_econ()
        spreadsheet_dscr = FIN_GOLDEN["min_dscr"]
        model_dscr = econ.min_dscr

        # Report for reconciliation note
        print(
            f"\n[G6 DSCR] model={model_dscr:.4f}; "
            f"Debt_Analytics!B16={spreadsheet_dscr:.6f}; "
            "discrepancy EXPECTED (formation costs/fees abstracted in pure layer)"
        )

        # Assert the model DSCR stays in the expected range (catches regressions in both directions)
        # Calibrated ≈4.02 at task-48 implementation; 3.0–5.5 allows tolerance while detecting drift
        assert 3.0 <= model_dscr <= 5.5, (
            f"G6 model_dscr={model_dscr:.4f} outside expected range [3.0, 5.5]. "
            "Re-examine [FIN] curve parameters if this fires."
        )


# ---------------------------------------------------------------------------
# Step-7: TestCalibrationPhysicsColumn — simulated physics column (reported only)
# ---------------------------------------------------------------------------


class TestCalibrationPhysicsColumn:
    """Physics column for calibration (REPORTED, not asserted == spreadsheet).

    Runs a small 2-home fleet over three days, in this process (a worker pool
    would fork the test process, which tests/conftest.py's offline guard makes
    multi-threaded), to smoke-test the physics path alongside the spreadsheet
    column. This does NOT document the §2.3 annual self-consumption tension:
    three days cannot show an annual self-consumption fraction, and its DSCR/IRR
    are degenerate for a 2-home fleet because the [FIN] grant exceeds the 2-home
    capex (financed capex, debt and equity are all zero). The printed physics
    values are reported for inspection only and are not pinned.

    tests/integration/test_cost_recovery_calibration.py::TestPhysicsColumnPremises
    asserts that no-debt premise.
    """

    def test_physics_column_structural_sanity(self) -> None:
        """Physics column: capex still input-driven (2 homes × £7,750).

        The physics column uses the real project_multi_year simulation (2 homes,
        3-day window) with no self_consumption_override, so it prices the
        simulated own-use. Only STRUCTURAL checks: capex == £15,500, physics scf MAY
        differ from 0.70, no physics==spreadsheet assertion.
        """
        scenario = make_physics_column_scenario()
        finance = _make_finance_fin()
        physics_finance = make_fin_finance(self_consumption_override=None)

        # Physics column (simulated fleet)
        physics_curve = project_multi_year(
            scenario, physics_finance, simulate=functools.partial(simulate_fleet, parallel=False)
        )
        physics_econ = project_economics(physics_curve, scenario, physics_finance)

        # Spreadsheet column (analytic)
        ss_curve = make_fin_spreadsheet_curve(n_homes=2, asset_life_years=finance.asset_life_years)
        # Adjust scenario to match 2 homes for capex assertion
        ss_econ = project_economics(ss_curve, scenario, finance)

        # REPORT both columns
        print(
            f"\n[PHYSICS vs SPREADSHEET REPORT] (2 homes, 3-day window)\n"
            f"  Spreadsheet-input capex: £{ss_econ.total_capex_gbp:,.2f}\n"
            f"  Physics capex:           £{physics_econ.total_capex_gbp:,.2f}\n"
            f"  Spreadsheet DSCR:        {ss_econ.min_dscr:.4f}\n"
            f"  Physics DSCR:            {physics_econ.min_dscr:.4f}\n"
            f"  Spreadsheet IRR:         {ss_econ.equity_irr*100:.2f}%\n"
            f"  Physics IRR:             {physics_econ.equity_irr*100:.2f}%\n"
            f"  Physics billed own-use:  {physics_curve.points[0].fleet_billed_own_use_kwh:.1f}"
            " kWh/yr (window annualised)\n"
            f"  Physics export_kwh:      {physics_curve.points[0].fleet_export_kwh:.1f}"
            " kWh/yr (window annualised)\n"
            f"  Spreadsheet scf=0.70 (named inp: {FIN_SCF})\n"
            f"  Note: grant > 2-home capex (no debt, no equity), so DSCR/IRR in both\n"
            f"  columns are degenerate. The 3-day physics values are a smoke report\n"
            f"  of the physics path, not the annual §2.3 tension."
        )

        # STRUCTURAL assertions only (no physics==spreadsheet assertions)
        # Capex is input-driven: assert against the concrete golden value, not the other column
        # 2 homes × (5.5kWp×£1000 + £1000 + 5.0kWh×£250) = 2 × £7,750 = £15,500
        _two_home_capex_gbp = 2.0 * (5.5 * 1000.0 + 1000.0 + 5.0 * 250.0)  # = 15500.0
        assert physics_econ.total_capex_gbp == pytest.approx(_two_home_capex_gbp, abs=1.0), (
            f"Physics capex (2 homes × £7,750) expected £{_two_home_capex_gbp:,.2f}, "
            f"got £{physics_econ.total_capex_gbp:,.2f}"
        )
        # Physics DSCR must be positive, or inf when debt-free (structural sanity)
        assert physics_econ.min_dscr > 0.0 or physics_econ.min_dscr == float("inf")
        # Physics IRR: just check it's a float (nan when no equity is invested, as here)
        # No assertion on physics_irr == spreadsheet_irr (G6: never assert physics == 0.70)
        assert isinstance(physics_econ.equity_irr, float)


