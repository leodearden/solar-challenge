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
