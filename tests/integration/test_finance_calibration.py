# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for the finance spreadsheet calibration (task/48 – θ).

H6 integration gate: verifies that the financial layer matches the investor
spreadsheet under identical [FIN] inputs.

Golden constants are transcribed from named cells in:
  finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm
  (read 2026-06-16 via openpyxl data_only; .xlsm NOT git-tracked; NOT read at runtime).

Layout:
  - Fast (no-network) classes:
      TestSpreadsheetRevenueCurve — pure helper unit tests
      TestFinCalibrationScenarioParses — YAML scenario parsing
      TestCalibrationCapexMethodAgreement — H6 capex gate
      TestCalibrationDscrIrrMethodAgreement — H6 DSCR/IRR gate
      TestCalibrationG6Guards — G6 premise guards
      TestReconciliationNoteDocumented — docs note presence
  - @pytest.mark.slow class:
      TestCalibrationPhysicsColumn — real-PVGIS physics column (reported, not asserted ==)

NOTE: This file mixes fast and slow tests; it must NOT be added to
test_marker_registration.py's INTEGRATION_FILES list.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Golden constants — transcribed from named .xlsm cells (NOT read at runtime)
# Source: finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm
# Read: 2026-06-16 via `uv run --with openpyxl` (openpyxl not in dev env)
# ---------------------------------------------------------------------------

_FIN_GOLDEN = {
    # Sensitivity sheet — named solver inputs
    "inp_kWp": 5.5,              # Sensitivity!B6  (inp_kWp)
    "inp_Batt_kWh": 5.0,         # Sensitivity!B7  (inp_Batt_kWh) — 5 kWh basis
    "inp_kWhPerkWp": 1050.0,     # Sensitivity!B8  (inp_kWhPerkWp)
    "out_MinCash_WithBatt": 96334.55,    # Sensitivity!B10
    "out_RetSurplus_WithBatt": 207841.20, # Sensitivity!B12
    # Capital Stack
    "capital_stack_b6": 775000.0,        # Capital_Stack!B6 — Total Capex at 5 kWh
    #   100 × (5.5×£1000 + £1000 + 5kWh×£250) = 100 × £7,750 = £775,000
    # Workings sheet — per-roof build-up at 10 kWh basis
    "workings_c57": 9000.0,      # Workings!C57 — £9,000/roof at 10 kWh
    #   5.5×1000 + 1000 + 10×250 = 5500+1000+2500 = £9,000
    "workings_c94": 900000.0,    # Workings!C94 — 100 × £9,000 = £900,000 (10 kWh basis)
    # §2.3 delta: £900,000 − £775,000 = £125,000 = 100 × 5kWh × £250 (battery size, NOT error)
    # Debt Analytics
    "min_dscr": 2.10378435678433,   # Debt_Analytics!B16 (Presentation Funders!E8, Stress_Test!B9)
    "avg_dscr": 3.1735282491711,    # Debt_Analytics!B17
    # Equity IRR: no single labelled cell; from Debt_Analytics row 13 'Cash for IRR'
    #   B13=-244821, C13=155947, D13=163911, E13=172837, ...
    #   The sheet's equity is net of formation costs / fundraising fees / dividend deferral,
    #   so the sheet equity_irr (~69% prose estimate) differs from our model (~11%).
    #   G6 fallback: assert structural floor equity_irr > 0.
    "equity_irr_floor": 0.0,  # G6 fallback: assert > 0
    # [FIN] cost/rate assumptions
    "own_use_rate_pence_per_kwh": 15.0,
    "export_rate_pence_per_kwh": 6.0,
    "grant_gbp": 250000.0,
    "equity_fraction": 0.75,
    "loan_term_years": 15,
    "loan_rate": 0.07,
}

# [FIN] self-consumption fraction assumption (spreadsheet uses 0.70 for with-battery)
_FIN_SCF = 0.70


# ---------------------------------------------------------------------------
# Helper builders (mirrors test_finance_economics.py pattern)
# ---------------------------------------------------------------------------


def _make_home_config_fin(
    pv_kwp: float = 5.5,
    battery_kwh: float = 5.0,
) -> "HomeConfig":  # type: ignore[name-defined]
    """Build a [FIN]-aligned HomeConfig (5.5 kWp + 5.0 kWh, Bristol defaults)."""
    from solar_challenge.home import HomeConfig
    from solar_challenge.pv import PVConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.battery import BatteryConfig

    pv = PVConfig(capacity_kw=pv_kwp, azimuth=180, tilt=35)
    load = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1)
    batt = BatteryConfig(capacity_kwh=battery_kwh) if battery_kwh > 0.0 else None
    return HomeConfig(pv_config=pv, load_config=load, battery_config=batt)


def _make_scenario_fin(
    n_homes: int = 100,
    pv_kwp: float = 5.5,
    battery_kwh: float = 5.0,
) -> "ScenarioConfig":  # type: ignore[name-defined]
    """Build a homogeneous [FIN]-aligned ScenarioConfig for calibration tests."""
    from solar_challenge.config import ScenarioConfig, SimulationPeriod
    period = SimulationPeriod(start_date="2024-01-01", end_date="2024-12-31")
    homes = [_make_home_config_fin(pv_kwp=pv_kwp, battery_kwh=battery_kwh)
             for _ in range(n_homes)]
    return ScenarioConfig(name="FIN-Calibration", period=period, homes=homes)


def _make_finance_fin(
    *,
    self_consumption_override: float = _FIN_SCF,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Build the [FIN]-aligned FinanceConfig with named-cell defaults."""
    from solar_challenge.config import FinanceConfig
    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        pv_cost_per_kwp_gbp=1000.0,
        roof_fit_cost_gbp=1000.0,
        battery_cost_per_kwh_gbp=250.0,
        inverter_cost_per_kw_gbp=0.0,
        grant_gbp=_FIN_GOLDEN["grant_gbp"],
        equity_fraction=_FIN_GOLDEN["equity_fraction"],
        loan_term_years=_FIN_GOLDEN["loan_term_years"],
        loan_rate=_FIN_GOLDEN["loan_rate"],
        opex_per_home_per_year_gbp=131.0,
        asset_life_years=25,
        self_consumption_override=self_consumption_override,
    )


# ---------------------------------------------------------------------------
# Step-1: TestSpreadsheetRevenueCurve — pure helper
# ---------------------------------------------------------------------------


class TestSpreadsheetRevenueCurve:
    """Fast tests for finance.spreadsheet_revenue_curve (task/48 step-1).

    spreadsheet_revenue_curve builds a flat [FIN]-assumption fleet-revenue
    MultiYearCurve without running the physics simulator.
    """

    def _call(self, **kwargs: object) -> "MultiYearCurve":  # type: ignore[name-defined]
        """Call spreadsheet_revenue_curve with default [FIN] params unless overridden."""
        from solar_challenge.finance import spreadsheet_revenue_curve

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
        return spreadsheet_revenue_curve(**defaults)  # type: ignore[return-value]

    def test_import(self) -> None:
        """spreadsheet_revenue_curve must be importable from solar_challenge.finance."""
        from solar_challenge.finance import spreadsheet_revenue_curve  # noqa: F401
        assert callable(spreadsheet_revenue_curve)

    def test_returns_multiyear_curve(self) -> None:
        """spreadsheet_revenue_curve must return a MultiYearCurve."""
        from solar_challenge.finance import MultiYearCurve

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
            assert pt1.fleet_self_consumption_kwh == pt2.fleet_self_consumption_kwh
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
        """fleet_self_consumption_kwh and fleet_export_kwh must reflect scf."""
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
            assert pt.fleet_self_consumption_kwh == pytest.approx(scf * fleet_gen, rel=1e-10)
            assert pt.fleet_export_kwh == pytest.approx((1.0 - scf) * fleet_gen, rel=1e-10)


# ---------------------------------------------------------------------------
# Step-3: TestFinCalibrationScenarioParses — YAML scenario loading
# ---------------------------------------------------------------------------


class TestFinCalibrationScenarioParses:
    """Fast tests for scenarios/bristol-fin-calibration.yaml loading (step-3).

    The scenario uses fleet_distribution format (100 identical homes), which is
    parsed via load_fleet_config (matching how the finance CLI loads scenarios).
    Finance block is parsed separately via _parse_finance_config + load_config,
    exactly as the finance CLI does internally.
    """

    _SCENARIO_PATH = "scenarios/bristol-fin-calibration.yaml"

    def _load_finance(self) -> "FinanceConfig":  # type: ignore[name-defined]
        """Parse the finance block from the calibration scenario YAML."""
        from pathlib import Path
        from solar_challenge.config import _parse_finance_config, load_config

        path = Path(self._SCENARIO_PATH)
        if not path.exists():
            pytest.fail(
                f"Scenario file not found: {self._SCENARIO_PATH}. "
                "Create it with step-4 impl."
            )
        raw = load_config(path)
        finance = _parse_finance_config(raw.get("finance"))
        assert finance is not None, "Expected finance block in scenario, got None"
        return finance

    def _load_homes(self) -> list:
        """Parse the fleet homes from the calibration scenario YAML."""
        from pathlib import Path
        from solar_challenge.config import load_fleet_config

        path = Path(self._SCENARIO_PATH)
        if not path.exists():
            pytest.fail(
                f"Scenario file not found: {self._SCENARIO_PATH}. "
                "Create it with step-4 impl."
            )
        fleet = load_fleet_config(path)
        return list(fleet.homes)

    def test_scenario_file_exists(self) -> None:
        """scenarios/bristol-fin-calibration.yaml must exist on disk."""
        from pathlib import Path
        assert Path(self._SCENARIO_PATH).exists(), (
            f"{self._SCENARIO_PATH} not found — create it in step-4"
        )

    def test_finance_parses_without_error(self) -> None:
        """The scenario YAML must parse finance block without raising exceptions."""
        finance = self._load_finance()
        assert finance is not None

    def test_scenario_has_finance_block(self) -> None:
        """Parsed scenario must have a finance block (not None)."""
        finance = self._load_finance()
        assert finance is not None

    def test_finance_self_consumption_override(self) -> None:
        """finance.self_consumption_override must be 0.70 ([FIN] with-battery assumption)."""
        finance = self._load_finance()
        assert finance.self_consumption_override == pytest.approx(_FIN_SCF), (
            f"Expected self_consumption_override=0.70, "
            f"got {finance.self_consumption_override}"
        )

    def test_finance_grant_gbp(self) -> None:
        """finance.grant_gbp must be £250,000 ([FIN] grant)."""
        finance = self._load_finance()
        assert finance.grant_gbp == pytest.approx(_FIN_GOLDEN["grant_gbp"])

    def test_finance_equity_fraction(self) -> None:
        """finance.equity_fraction must be 0.75 ([FIN] equity split)."""
        finance = self._load_finance()
        assert finance.equity_fraction == pytest.approx(_FIN_GOLDEN["equity_fraction"])

    def test_finance_loan_term_years(self) -> None:
        """finance.loan_term_years must be 15 ([FIN] loan term)."""
        finance = self._load_finance()
        assert finance.loan_term_years == _FIN_GOLDEN["loan_term_years"]

    def test_finance_loan_rate(self) -> None:
        """finance.loan_rate must be 0.07 ([FIN] loan interest rate)."""
        finance = self._load_finance()
        assert finance.loan_rate == pytest.approx(_FIN_GOLDEN["loan_rate"])

    def test_finance_pv_cost_per_kwp(self) -> None:
        """finance.pv_cost_per_kwp_gbp must be £1000 ([FIN] PV cost)."""
        finance = self._load_finance()
        assert finance.pv_cost_per_kwp_gbp == pytest.approx(1000.0)

    def test_finance_battery_cost_per_kwh(self) -> None:
        """finance.battery_cost_per_kwh_gbp must be £250 ([FIN] battery cost)."""
        finance = self._load_finance()
        assert finance.battery_cost_per_kwh_gbp == pytest.approx(250.0)

    def test_finance_asset_life_years(self) -> None:
        """finance.asset_life_years must be 25."""
        finance = self._load_finance()
        assert finance.asset_life_years == 25

    def test_fleet_is_100_homes(self) -> None:
        """Fleet must have exactly 100 homes ([FIN] n_homes=100)."""
        homes = self._load_homes()
        assert len(homes) == 100, f"Expected 100 homes, got {len(homes)}"

    def test_fleet_is_homogeneous_5_5kwp(self) -> None:
        """All homes must have pv_kwp=5.5 ([FIN] inp_kWp=5.5)."""
        homes = self._load_homes()
        assert len(homes) == 100, f"Expected 100 homes, got {len(homes)}"
        for i, h in enumerate(homes):
            assert h.pv_config.capacity_kw == pytest.approx(5.5), (
                f"Home {i}: expected pv_kwp=5.5, got {h.pv_config.capacity_kw}"
            )

    def test_fleet_is_homogeneous_5kwh_battery(self) -> None:
        """All homes must have battery_kwh=5.0 ([FIN] inp_Batt_kWh=5)."""
        homes = self._load_homes()
        for i, h in enumerate(homes):
            assert h.battery_config is not None, f"Home {i}: no battery config"
            assert h.battery_config.capacity_kwh == pytest.approx(5.0), (
                f"Home {i}: expected battery_kwh=5.0, got {h.battery_config.capacity_kwh}"
            )


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

    def _make_spreadsheet_curve(self, asset_life_years: int = 25) -> "MultiYearCurve":  # type: ignore[name-defined]
        """Build the [FIN]-assumption spreadsheet revenue curve."""
        from solar_challenge.finance import spreadsheet_revenue_curve

        return spreadsheet_revenue_curve(
            n_homes=100,
            pv_kwp=_FIN_GOLDEN["inp_kWp"],
            kwh_per_kwp=_FIN_GOLDEN["inp_kWhPerkWp"],
            self_consumption_fraction=_FIN_SCF,
            own_use_rate_pence_per_kwh=_FIN_GOLDEN["own_use_rate_pence_per_kwh"],
            export_rate_pence_per_kwh=_FIN_GOLDEN["export_rate_pence_per_kwh"],
            asset_life_years=asset_life_years,
        )

    def test_capex_5kwh_matches_capital_stack_b6(self) -> None:
        """Capex for 100 × 5.5kWp + 5kWh must equal Capital_Stack!B6 = £775,000 exactly.

        Arithmetic: 100 × (5.5×£1000 + £1000 + 5.0kWh×£250) = 100×£7,750 = £775,000
        Cell ref: Capital_Stack!B6 = £775,000
        """
        from solar_challenge.finance import project_economics

        scenario = _make_scenario_fin(n_homes=100, pv_kwp=5.5, battery_kwh=5.0)
        finance = _make_finance_fin()
        curve = self._make_spreadsheet_curve()

        econ = project_economics(curve, scenario, finance)

        assert econ.total_capex_gbp == pytest.approx(
            _FIN_GOLDEN["capital_stack_b6"], abs=1.0
        ), (
            f"Capex (5 kWh) expected Capital_Stack!B6=£{_FIN_GOLDEN['capital_stack_b6']:,.2f}, "
            f"got £{econ.total_capex_gbp:,.2f}"
        )

    def test_capex_5kwh_exact_arithmetic(self) -> None:
        """Exact arithmetic check: 100×(5.5×1000+1000+5×250)=775000 matches cell."""
        from solar_challenge.finance import project_economics

        scenario = _make_scenario_fin(n_homes=100, pv_kwp=5.5, battery_kwh=5.0)
        finance = _make_finance_fin()
        curve = self._make_spreadsheet_curve()

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
        from solar_challenge.finance import project_economics, spreadsheet_revenue_curve

        # 10 kWh fleet (Workings build-up basis)
        scenario_10kwh = _make_scenario_fin(n_homes=100, pv_kwp=5.5, battery_kwh=10.0)
        finance = _make_finance_fin()
        curve = spreadsheet_revenue_curve(
            n_homes=100,
            pv_kwp=5.5,
            kwh_per_kwp=1050.0,
            self_consumption_fraction=_FIN_SCF,
            own_use_rate_pence_per_kwh=15.0,
            export_rate_pence_per_kwh=6.0,
            asset_life_years=25,
        )

        econ_10kwh = project_economics(curve, scenario_10kwh, finance)

        assert econ_10kwh.total_capex_gbp == pytest.approx(
            _FIN_GOLDEN["workings_c94"], abs=1.0
        ), (
            f"Capex (10 kWh) expected Workings!C94=£{_FIN_GOLDEN['workings_c94']:,.0f}, "
            f"got £{econ_10kwh.total_capex_gbp:,.2f}"
        )

    def test_capex_delta_is_battery_size_difference(self) -> None:
        """§2.3 delta: capex_10kwh − capex_5kwh == £125,000 == 100×5kWh×£250.

        This is the §2.3 '£775k ↔ £900k' reconciliation:
        Pure battery-size difference (inp_Batt_kWh=5 vs Workings 10 kWh), NOT an error.
        """
        from solar_challenge.finance import project_economics, spreadsheet_revenue_curve

        curve = spreadsheet_revenue_curve(
            n_homes=100, pv_kwp=5.5, kwh_per_kwp=1050.0,
            self_consumption_fraction=_FIN_SCF,
            own_use_rate_pence_per_kwh=15.0, export_rate_pence_per_kwh=6.0,
            asset_life_years=25,
        )
        finance = _make_finance_fin()

        econ_5 = project_economics(curve, _make_scenario_fin(battery_kwh=5.0), finance)
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

    def test_capex_report_values(self) -> None:
        """Sanity: report the capex values in assertion message for documentation."""
        from solar_challenge.finance import project_economics

        scenario = _make_scenario_fin(n_homes=100, pv_kwp=5.5, battery_kwh=5.0)
        finance = _make_finance_fin()
        curve = self._make_spreadsheet_curve()

        econ = project_economics(curve, scenario, finance)

        # Report: document the values in test output for the reconciliation note
        print(
            f"\n[CAPEX REPORT] Capital_Stack!B6={_FIN_GOLDEN['capital_stack_b6']:,.0f}; "
            f"project_economics={econ.total_capex_gbp:,.2f}; "
            f"delta={abs(econ.total_capex_gbp - _FIN_GOLDEN['capital_stack_b6']):.4f}"
        )
        # Must be within £1
        assert abs(econ.total_capex_gbp - _FIN_GOLDEN["capital_stack_b6"]) < 1.0


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
    abstracts away. Per PRD §13 / task G6 latitude:
      - HARD assert: min_dscr ≥ 1.20 (covenant floor)
      - HARD assert: equity_irr > 0 (structural sanity)
      - REPORTED: actual values vs spreadsheet cells (Debt_Analytics!B16/B17)
    The digit-match (min_dscr ≈ 2.10378) is DELIBERATELY NOT asserted here.
    See docs/finance-spreadsheet-reconciliation.md for full rationale.
    """

    def _build_econ(self) -> "ProjectEconomics":  # type: ignore[name-defined]
        """Build [FIN]-assumption ProjectEconomics for DSCR/IRR tests."""
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
        scenario = _make_scenario_fin(n_homes=100, pv_kwp=5.5, battery_kwh=5.0)
        finance = _make_finance_fin()
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
        import math

        econ = self._build_econ()
        assert not math.isnan(econ.equity_irr), "equity_irr must not be NaN"
        assert econ.equity_irr > _FIN_GOLDEN["equity_irr_floor"], (
            f"equity_irr={econ.equity_irr:.4f} must be > 0 (structural sanity)"
        )

    def test_determinism(self) -> None:
        """Two project_economics calls with same [FIN] inputs must be bit-identical."""
        econ1 = self._build_econ()
        econ2 = self._build_econ()
        assert econ1.min_dscr == econ2.min_dscr
        assert econ1.equity_irr == econ2.equity_irr
        assert econ1.per_year_surplus_gbp == econ2.per_year_surplus_gbp

    def test_dscr_reported_vs_spreadsheet(self) -> None:
        """Report: [FIN]-assumption min_dscr vs Debt_Analytics!B16 (NOT asserted equal).

        The [FIN]-assumption curve yields min_dscr ≈ 4.02 because it uses flat
        revenues (no formation costs, no dividend deferral).
        Debt_Analytics!B16 = 2.10378 accounts for those deductions.
        Per G6, only the covenant floor (1.20) is asserted; the cell value is REPORTED.
        """
        econ = self._build_econ()

        fin_dscr = _FIN_GOLDEN["min_dscr"]
        model_dscr = econ.min_dscr

        # REPORT: document both values for reconciliation note
        print(
            f"\n[DSCR REPORT] "
            f"Debt_Analytics!B16={fin_dscr:.6f}; "
            f"[FIN]-assumption model={model_dscr:.6f}; "
            f"ratio={model_dscr/fin_dscr:.4f}"
        )
        print(
            "  G6 note: model DSCR > spreadsheet because the sheet deducts "
            "equity fundraising fees / formation costs / dividend deferral "
            "from the numerator (revenue-opex). Pure layer does not model these."
        )

        # HARD assert: covenant floor only
        assert model_dscr >= 1.20
        # SOFT assert: documented comment (not a real assertion)
        # model_dscr ≠ fin_dscr — this is the §2.3 self-consumption tension mirror

    def test_irr_reported_vs_spreadsheet_cashflow(self) -> None:
        """Report: [FIN]-assumption equity_irr vs spreadsheet 'Cash for IRR' row.

        Debt_Analytics row 13 'Cash for IRR': B13=-244821, C13=155947, D13=163911, ...
        Prose estimate: spreadsheet equity_irr ~69% (net of formation costs / fees).
        Our model equity_irr ~11% (pure annuity + surplus, full equity investment).
        Per G6, only equity_irr > 0 is asserted; the spreadsheet value is REPORTED.
        """
        import math

        econ = self._build_econ()

        # Documented spreadsheet cashflow (Debt_Analytics!B13:...)
        # B13=-244821, C13=155947, D13=163911, E13=172837 (equity net of fees)
        _sheet_equity_cashflow_start = -244821.0  # Debt_Analytics!B13
        # IRR not directly asserted — documented for reconciliation

        print(
            f"\n[IRR REPORT] "
            f"[FIN]-assumption equity_irr={econ.equity_irr*100:.2f}%; "
            f"equity_gbp=£{econ.equity_gbp:,.2f}; "
            f"sheet equity_cashflow_start=£{_sheet_equity_cashflow_start:,.0f}; "
            f"spreadsheet equity_irr ~69% (net of formation/fee deductions)"
        )

        # HARD assert: structural sanity only
        assert not math.isnan(econ.equity_irr)
        assert econ.equity_irr > 0.0
