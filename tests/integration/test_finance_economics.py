# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for the finance economics module (task/47 – η).

Layout:
  - Fast (no-network) classes: H5 ProjectEconomics dataclass, capex build-up,
    debt service, per-year surplus/DSCR, IRR/payback/determinism, report
    rendering, CLI help/error paths.
  - One @pytest.mark.slow class for the real-PVGIS end-to-end path.

NOTE: This file intentionally mixes fast and slow tests; it must NOT be
added to test_marker_registration.py's INTEGRATION_FILES list.
"""
from __future__ import annotations

import math
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_point(year: int, revenue: float) -> "YearPoint":  # type: ignore[name-defined]
    """Build a synthetic YearPoint with given year and fleet_revenue_gbp."""
    from solar_challenge.finance import YearPoint
    return YearPoint(
        year=year,
        pv_soh=1.0,
        battery_soh=1.0,
        fleet_self_consumption_kwh=5000.0,
        fleet_export_kwh=2000.0,
        fleet_import_kwh=1000.0,
        fleet_revenue_gbp=revenue,
    )


def _make_curve(revenues: list[float]) -> "MultiYearCurve":  # type: ignore[name-defined]
    """Build a synthetic MultiYearCurve with given per-year revenues."""
    from solar_challenge.finance import MultiYearCurve
    points = tuple(_make_point(y, rev) for y, rev in enumerate(revenues))
    return MultiYearCurve(
        points=points,
        sampled_ages=(0,),
        interp_error_estimate=0.0,
    )


def _make_home_config(
    pv_kwp: float,
    battery_kwh: Optional[float] = None,
) -> "HomeConfig":  # type: ignore[name-defined]
    """Build a minimal HomeConfig for economics tests."""
    from solar_challenge.home import HomeConfig
    from solar_challenge.pv import PVConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.battery import BatteryConfig

    pv = PVConfig(capacity_kw=pv_kwp)
    load = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False, seed=1)
    batt = BatteryConfig(capacity_kwh=battery_kwh) if battery_kwh is not None else None
    return HomeConfig(pv_config=pv, load_config=load, battery_config=batt)


def _make_scenario(
    homes: Optional[list] = None,
) -> "ScenarioConfig":  # type: ignore[name-defined]
    """Build a minimal ScenarioConfig for economics tests."""
    from solar_challenge.config import ScenarioConfig, SimulationPeriod
    period = SimulationPeriod(
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    if homes is None:
        homes = [_make_home_config(4.0, battery_kwh=5.0)]
    return ScenarioConfig(
        name="Test",
        period=period,
        homes=homes,
    )


def _make_finance(
    *,
    pv_cost_per_kwp_gbp: float = 1000.0,
    roof_fit_cost_gbp: float = 1000.0,
    battery_cost_per_kwh_gbp: float = 250.0,
    grant_gbp: float = 0.0,
    equity_fraction: float = 0.75,
    loan_term_years: int = 15,
    loan_rate: float = 0.07,
    opex_per_home_per_year_gbp: float = 131.0,
    asset_life_years: int = 25,
) -> "FinanceConfig":  # type: ignore[name-defined]
    """Build a FinanceConfig for economics tests."""
    from solar_challenge.config import FinanceConfig
    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        pv_cost_per_kwp_gbp=pv_cost_per_kwp_gbp,
        roof_fit_cost_gbp=roof_fit_cost_gbp,
        battery_cost_per_kwh_gbp=battery_cost_per_kwh_gbp,
        grant_gbp=grant_gbp,
        equity_fraction=equity_fraction,
        loan_term_years=loan_term_years,
        loan_rate=loan_rate,
        opex_per_home_per_year_gbp=opex_per_home_per_year_gbp,
        asset_life_years=asset_life_years,
    )


# ---------------------------------------------------------------------------
# Step-1: ProjectEconomics frozen dataclass
# ---------------------------------------------------------------------------


class TestProjectEconomicsDataclass:
    """Fast tests for ProjectEconomics frozen dataclass (§3.1 fields)."""

    def _make_economics(
        self,
        *,
        per_year_surplus: tuple = (100.0, 200.0, 300.0),
        payback_years: Optional[float] = 5.0,
    ) -> "ProjectEconomics":  # type: ignore[name-defined]
        """Build a synthetic ProjectEconomics."""
        from solar_challenge.finance import ProjectEconomics
        return ProjectEconomics(
            total_capex_gbp=50000.0,
            grant_gbp=10000.0,
            equity_gbp=30000.0,
            debt_gbp=10000.0,
            annual_debt_service_gbp=900.0,
            per_year_surplus_gbp=per_year_surplus,
            min_dscr=1.2,
            equity_irr=0.08,
            payback_years=payback_years,
            net_surplus_per_home_per_year_gbp=150.0,
        )

    def test_construction_with_all_fields(self) -> None:
        """ProjectEconomics can be constructed with all §3.1 fields."""
        econ = self._make_economics()
        assert econ.total_capex_gbp == pytest.approx(50000.0)
        assert econ.grant_gbp == pytest.approx(10000.0)
        assert econ.equity_gbp == pytest.approx(30000.0)
        assert econ.debt_gbp == pytest.approx(10000.0)
        assert econ.annual_debt_service_gbp == pytest.approx(900.0)
        assert econ.min_dscr == pytest.approx(1.2)
        assert econ.equity_irr == pytest.approx(0.08)
        assert econ.payback_years == pytest.approx(5.0)
        assert econ.net_surplus_per_home_per_year_gbp == pytest.approx(150.0)

    def test_per_year_surplus_stored_as_tuple(self) -> None:
        """per_year_surplus_gbp must be stored as a tuple."""
        econ = self._make_economics(per_year_surplus=(100.0, 200.0, 300.0))
        assert isinstance(econ.per_year_surplus_gbp, tuple)

    def test_frozen_raises_on_assignment(self) -> None:
        """ProjectEconomics must be frozen (FrozenInstanceError on field assignment)."""
        import dataclasses
        econ = self._make_economics()
        with pytest.raises(dataclasses.FrozenInstanceError):
            econ.total_capex_gbp = 99999.0  # type: ignore[misc]

    def test_payback_years_none_allowed(self) -> None:
        """payback_years=None must be a valid (never-profitable) sentinel."""
        econ = self._make_economics(payback_years=None)
        assert econ.payback_years is None

    def test_empty_per_year_surplus_raises(self) -> None:
        """Empty per_year_surplus_gbp must raise ValueError in __post_init__."""
        from solar_challenge.finance import ProjectEconomics
        with pytest.raises(ValueError):
            ProjectEconomics(
                total_capex_gbp=50000.0,
                grant_gbp=0.0,
                equity_gbp=37500.0,
                debt_gbp=12500.0,
                annual_debt_service_gbp=900.0,
                per_year_surplus_gbp=(),  # empty!
                min_dscr=1.2,
                equity_irr=0.08,
                payback_years=5.0,
                net_surplus_per_home_per_year_gbp=150.0,
            )

    def test_negative_payback_years_raises(self) -> None:
        """Negative payback_years must raise ValueError in __post_init__."""
        from solar_challenge.finance import ProjectEconomics
        with pytest.raises(ValueError):
            ProjectEconomics(
                total_capex_gbp=50000.0,
                grant_gbp=0.0,
                equity_gbp=37500.0,
                debt_gbp=12500.0,
                annual_debt_service_gbp=900.0,
                per_year_surplus_gbp=(100.0,),
                min_dscr=1.2,
                equity_irr=0.08,
                payback_years=-1.0,  # negative!
                net_surplus_per_home_per_year_gbp=150.0,
            )


# ---------------------------------------------------------------------------
# Step-3: capex build-up + grant/equity/debt split
# ---------------------------------------------------------------------------


class TestProjectEconomicsCapex:
    """Fast tests for project_economics capex build-up and financing split."""

    def test_two_home_capex_exact(self) -> None:
        """total_capex_gbp must equal the exact 3-term sum for a 2-home fleet.

        Home A: pv=4.0kWp, battery=5.0kWh
        Home B: pv=3.0kWp, battery=None (PV-only, battery_kwh=0)
        pv_cost=1000, roof_fit=1000, battery_cost=250
        expected_capex = (4*1000 + 1000 + 5*250) + (3*1000 + 1000 + 0*250)
                       = (4000 + 1000 + 1250) + (3000 + 1000 + 0)
                       = 6250 + 4000 = 10250
        """
        from solar_challenge.finance import project_economics

        home_a = _make_home_config(pv_kwp=4.0, battery_kwh=5.0)
        home_b = _make_home_config(pv_kwp=3.0, battery_kwh=None)
        scenario = _make_scenario(homes=[home_a, home_b])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
        )
        # 25 revenue entries (asset_life_years=25)
        revenues = [10000.0] * 25
        curve = _make_curve(revenues)

        econ = project_economics(curve, scenario, finance)

        expected_capex = (4.0 * 1000.0 + 1000.0 + 5.0 * 250.0) + (3.0 * 1000.0 + 1000.0 + 0.0 * 250.0)
        assert econ.total_capex_gbp == pytest.approx(expected_capex)

    def test_no_inverter_term_in_capex(self) -> None:
        """Regression guard: capex must exactly equal the 3-term sum, no more.

        This ensures no inverter term slips in (that is task #49's scope).
        """
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=5.0, battery_kwh=10.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=800.0,
            roof_fit_cost_gbp=1200.0,
            battery_cost_per_kwh_gbp=300.0,
            grant_gbp=0.0,
        )
        curve = _make_curve([9000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        # 3-term only: 5*800 + 1200 + 10*300 = 4000+1200+3000=8200
        expected_3term = 5.0 * 800.0 + 1200.0 + 10.0 * 300.0
        assert econ.total_capex_gbp == pytest.approx(expected_3term)

    def test_grant_passthrough(self) -> None:
        """grant_gbp in ProjectEconomics must equal FinanceConfig.grant_gbp."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=4.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(grant_gbp=5000.0)
        curve = _make_curve([8000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert econ.grant_gbp == pytest.approx(5000.0)

    def test_equity_debt_split(self) -> None:
        """equity_gbp + debt_gbp must equal (capex - grant); equity fraction correct."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=4.0, battery_kwh=5.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=1000.0,
            equity_fraction=0.60,
        )
        curve = _make_curve([8000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        financed = max(econ.total_capex_gbp - 1000.0, 0.0)
        expected_equity = financed * 0.60
        expected_debt = financed * 0.40

        assert econ.equity_gbp == pytest.approx(expected_equity, rel=1e-9)
        assert econ.debt_gbp == pytest.approx(expected_debt, rel=1e-9)
        assert econ.equity_gbp + econ.debt_gbp == pytest.approx(financed, rel=1e-9)

    def test_grant_exceeds_capex_clamps_to_zero(self) -> None:
        """When grant >= capex, financed=0, equity=0, debt=0."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=2.0)
        scenario = _make_scenario(homes=[home])
        # capex = 2*1000 + 1000 + 0 = 3000; grant=50000 >> capex
        finance = _make_finance(grant_gbp=50000.0)
        curve = _make_curve([8000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert econ.equity_gbp == pytest.approx(0.0, abs=1e-9)
        assert econ.debt_gbp == pytest.approx(0.0, abs=1e-9)

    def test_empty_homes_raises_value_error(self) -> None:
        """project_economics must raise ValueError when scenario has no homes."""
        from solar_challenge.finance import project_economics

        # ScenarioConfig.__post_init__ requires homes OR home — use one then clear
        # We need to bypass: directly pass homes=[] would fail ScenarioConfig validation.
        # Use a single home scenario but call project_economics on a zero-home one
        # via a monkeypatch — but simpler: test that project_economics raises when
        # it finds no homes via the resolution path.
        # ScenarioConfig requires at least one home, so we test that by passing
        # a scenario whose homes list is empty after resolution by providing
        # scenario.homes=[] and scenario.home=None — but this is blocked by
        # __post_init__. We verify project_economics raises ValueError by
        # constructing a valid 1-home scenario and monkeypatching (not possible
        # without object.__setattr__).
        # Instead: test project_economics with a patched scenario-like object.
        import dataclasses

        valid_scenario = _make_scenario(homes=[_make_home_config(4.0)])
        finance = _make_finance()
        curve = _make_curve([8000.0] * 25)

        # Monkey-patch: clear homes list on a copy
        empty_scenario = dataclasses.replace(valid_scenario)
        # ScenarioConfig is not frozen — we can set homes directly
        object.__setattr__(empty_scenario, "homes", [])
        object.__setattr__(empty_scenario, "home", None)

        with pytest.raises(ValueError, match="at least one home"):
            project_economics(curve, empty_scenario, finance)


# ---------------------------------------------------------------------------
# Step-5: level-amortisation annuity debt service (H5)
# ---------------------------------------------------------------------------


class TestProjectEconomicsDebtService:
    """Fast tests for annual_debt_service_gbp: level annuity formula (H5)."""

    def test_annuity_formula_positive_rate(self) -> None:
        """annual_debt_service_gbp == debt*r/(1-(1+r)^-n) for known parameters."""
        from solar_challenge.finance import _annuity_payment, project_economics

        # Known debt, rate, term
        # capex = 1*1000 + 1000 + 0 = 2000; grant=0; equity_frac=0.5
        # financed=2000; equity=1000; debt=1000
        home = _make_home_config(pv_kwp=1.0, battery_kwh=None)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=0.5,
            loan_rate=0.07,
            loan_term_years=15,
        )
        curve = _make_curve([5000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        # capex = 1*1000 + 1000 = 2000; debt = 2000 * 0.5 = 1000
        expected_debt = 2000.0 * 0.5
        expected_annuity = _annuity_payment(expected_debt, 0.07, 15)
        # verify helper itself
        hand_annuity = expected_debt * 0.07 / (1.0 - (1.07) ** -15)
        assert expected_annuity == pytest.approx(hand_annuity, rel=1e-9)
        assert econ.annual_debt_service_gbp == pytest.approx(hand_annuity, rel=1e-9)

    def test_annuity_zero_rate(self) -> None:
        """loan_rate==0 → annual_debt_service == debt / loan_term_years."""
        from solar_challenge.finance import _annuity_payment, project_economics

        home = _make_home_config(pv_kwp=2.0, battery_kwh=None)
        scenario = _make_scenario(homes=[home])
        # capex = 2*800+1000=2600; grant=0; debt=2600*0.5=1300
        finance = _make_finance(
            pv_cost_per_kwp_gbp=800.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=0.5,
            loan_rate=0.0,
            loan_term_years=10,
        )
        curve = _make_curve([5000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        # debt = 2600 * 0.5 = 1300; annuity = 1300/10 = 130
        capex = 2.0 * 800.0 + 1000.0
        expected_debt = capex * 0.5
        expected_annuity = expected_debt / 10
        assert econ.annual_debt_service_gbp == pytest.approx(expected_annuity, rel=1e-9)

    def test_annuity_zero_debt(self) -> None:
        """When debt==0 (grant covers all), annual_debt_service_gbp==0."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=2.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(grant_gbp=999999.0)  # grant >> capex
        curve = _make_curve([5000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert econ.annual_debt_service_gbp == pytest.approx(0.0, abs=1e-9)

    def test_annuity_helper_direct(self) -> None:
        """_annuity_payment helper: closed-form check at known values."""
        from solar_challenge.finance import _annuity_payment

        # 1000 @ 10% for 10 years: payment = 1000 * 0.1 / (1 - 1.1^-10)
        principal = 1000.0
        rate = 0.10
        n = 10
        expected = principal * rate / (1.0 - (1.0 + rate) ** -n)
        result = _annuity_payment(principal, rate, n)
        assert result == pytest.approx(expected, rel=1e-9)

    def test_annuity_helper_zero_rate(self) -> None:
        """_annuity_payment: zero rate falls back to principal/n."""
        from solar_challenge.finance import _annuity_payment

        result = _annuity_payment(1000.0, 0.0, 8)
        assert result == pytest.approx(125.0, rel=1e-9)


# ---------------------------------------------------------------------------
# Step-7: per-year surplus + min_dscr + net_surplus_per_home
# ---------------------------------------------------------------------------


class TestProjectEconomicsSurplusDSCR:
    """Fast tests for per_year_surplus_gbp, min_dscr, net_surplus_per_home."""

    def _setup(self) -> tuple:
        """Build a canonical 2-home scenario for surplus/DSCR tests.

        Home A: pv=4kWp, battery=5kWh; Home B: pv=3kWp, no battery.
        finance: pv_cost=1000, roof_fit=1000, battery_cost=250, grant=0,
                 equity_fraction=0.75, loan_rate=0.07, loan_term=15,
                 opex_per_home=200, asset_life=25.
        capex = (4*1000+1000+5*250)+(3*1000+1000+0) = 6250+4000=10250
        financed = 10250; equity = 7687.5; debt = 2562.5
        annual_debt_service = _annuity_payment(2562.5, 0.07, 15)
        fleet_opex = 200 * 2 = 400
        revenues = [5000.0] * 25 (flat)
        per_year_surplus[y<15] = 5000 - 400 - debt_service
        per_year_surplus[y>=15] = 5000 - 400 = 4600
        """
        from solar_challenge.finance import _annuity_payment

        homes = [
            _make_home_config(pv_kwp=4.0, battery_kwh=5.0),
            _make_home_config(pv_kwp=3.0, battery_kwh=None),
        ]
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=0.75,
            loan_rate=0.07,
            loan_term_years=15,
            opex_per_home_per_year_gbp=200.0,
            asset_life_years=25,
        )
        revenues = [5000.0] * 25
        curve = _make_curve(revenues)
        scenario = _make_scenario(homes=homes)

        capex = 10250.0
        debt = capex * 0.25
        fleet_opex = 200.0 * 2
        annual_ds = _annuity_payment(debt, 0.07, 15)
        return scenario, finance, curve, fleet_opex, annual_ds

    def test_surplus_length_equals_asset_life(self) -> None:
        """len(per_year_surplus_gbp) must equal finance.asset_life_years."""
        from solar_challenge.finance import project_economics

        scenario, finance, curve, _, _ = self._setup()
        econ = project_economics(curve, scenario, finance)

        assert len(econ.per_year_surplus_gbp) == 25

    def test_surplus_loan_years_include_debt_service(self) -> None:
        """Surplus for loan years must deduct both opex and debt service."""
        from solar_challenge.finance import project_economics

        scenario, finance, curve, fleet_opex, annual_ds = self._setup()
        econ = project_economics(curve, scenario, finance)

        # For y<15: surplus = 5000 - fleet_opex - annual_ds
        for y in range(15):
            expected = 5000.0 - fleet_opex - annual_ds
            assert econ.per_year_surplus_gbp[y] == pytest.approx(expected, rel=1e-9), (
                f"Mismatch at year {y}"
            )

    def test_surplus_post_loan_years_no_debt_service(self) -> None:
        """Surplus for post-loan years must deduct only opex (no debt service)."""
        from solar_challenge.finance import project_economics

        scenario, finance, curve, fleet_opex, _ = self._setup()
        econ = project_economics(curve, scenario, finance)

        # For y>=15: surplus = 5000 - fleet_opex (4600)
        for y in range(15, 25):
            expected = 5000.0 - fleet_opex
            assert econ.per_year_surplus_gbp[y] == pytest.approx(expected, rel=1e-9), (
                f"Mismatch at year {y}"
            )

    def test_min_dscr_over_loan_years_only(self) -> None:
        """min_dscr must be computed over loan years only, not post-loan years.

        Use a curve where post-loan year has lowest (revenue-opex)/debt_service,
        but DSCR should ignore it.  All loan-year revenues are equal here,
        so min_dscr = (5000 - fleet_opex) / annual_ds.
        """
        from solar_challenge.finance import project_economics

        # Revenues: loan years have 5000, post-loan years have 1000 (very low)
        # Post-loan year 15..24 → (1000-400)/annual_ds which would be low
        # But min_dscr must only look at y<15
        homes = [
            _make_home_config(pv_kwp=4.0, battery_kwh=5.0),
            _make_home_config(pv_kwp=3.0, battery_kwh=None),
        ]
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=0.75,
            loan_rate=0.07,
            loan_term_years=15,
            opex_per_home_per_year_gbp=200.0,
            asset_life_years=25,
        )
        # Loan years: 5000 revenue; post-loan: 1000 revenue (very low)
        revenues = [5000.0] * 15 + [1000.0] * 10
        curve = _make_curve(revenues)
        scenario = _make_scenario(homes=homes)

        from solar_challenge.finance import _annuity_payment
        capex = 10250.0
        debt = capex * 0.25
        annual_ds = _annuity_payment(debt, 0.07, 15)
        fleet_opex = 200.0 * 2
        expected_dscr = (5000.0 - fleet_opex) / annual_ds

        econ = project_economics(curve, scenario, finance)

        # DSCR over loan years (all 5000 revenue) should be much > post-loan DSCR
        assert econ.min_dscr == pytest.approx(expected_dscr, rel=1e-6)
        # Sanity: post-loan DSCR would have been much lower (< 1.0 even)
        post_loan_dscr = (1000.0 - fleet_opex) / annual_ds  # negative!
        assert post_loan_dscr < econ.min_dscr, (
            "Post-loan DSCR is lower than loan DSCR — min_dscr should exclude it"
        )

    def test_min_dscr_zero_debt_service_is_inf(self) -> None:
        """When annual_debt_service_gbp==0, min_dscr must be float('inf')."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=2.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(grant_gbp=999999.0)  # no debt
        curve = _make_curve([5000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert math.isinf(econ.min_dscr)

    def test_net_surplus_per_home_per_year(self) -> None:
        """net_surplus_per_home_per_year_gbp == mean(per_year_surplus)/n_homes."""
        from solar_challenge.finance import project_economics

        scenario, finance, curve, _, _ = self._setup()
        econ = project_economics(curve, scenario, finance)

        expected_mean = sum(econ.per_year_surplus_gbp) / len(econ.per_year_surplus_gbp)
        expected_per_home = expected_mean / 2  # 2 homes
        assert econ.net_surplus_per_home_per_year_gbp == pytest.approx(expected_per_home, rel=1e-9)


# ---------------------------------------------------------------------------
# Step-9: equity_irr + payback + determinism (H5)
# ---------------------------------------------------------------------------


class TestProjectEconomicsIRRPayback:
    """Fast tests for equity_irr, payback_years, and determinism (H5)."""

    def test_irr_bisection_simple_cashflow(self) -> None:
        """_irr_bisection: [-100, 110] → IRR = 0.10."""
        from solar_challenge.finance import _irr_bisection

        result = _irr_bisection([-100.0, 110.0])
        assert result == pytest.approx(0.10, rel=1e-6)

    def test_irr_bisection_two_period(self) -> None:
        """_irr_bisection: [-100, 0, 121] → IRR = 0.10."""
        from solar_challenge.finance import _irr_bisection

        result = _irr_bisection([-100.0, 0.0, 121.0])
        assert result == pytest.approx(0.10, rel=1e-6)

    def test_irr_npv_consistency(self) -> None:
        """NPV of cashflows at equity_irr must be approximately zero."""
        from solar_challenge.finance import _npv, project_economics

        # Profitable project: flat 8000 revenue, small equity investment
        home = _make_home_config(pv_kwp=4.0, battery_kwh=5.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=0.75,
            loan_rate=0.07,
            loan_term_years=15,
            opex_per_home_per_year_gbp=100.0,
            asset_life_years=25,
        )
        curve = _make_curve([8000.0] * 25)

        econ = project_economics(curve, scenario, finance)

        if not math.isnan(econ.equity_irr):
            cashflows = [-econ.equity_gbp] + list(econ.per_year_surplus_gbp)
            npv_at_irr = _npv(econ.equity_irr, cashflows)
            # |NPV| < 1e-6 * equity
            assert abs(npv_at_irr) < 1e-6 * max(abs(econ.equity_gbp), 1.0)

    def test_payback_years_hand_computed(self) -> None:
        """payback_years equals the hand-computed first 1-based cumulative crossing."""
        from solar_challenge.finance import project_economics

        # Set up so payback is at a known year.
        # Use equity_fraction=1.0 (no debt) for simplicity.
        # capex = 1*1000+1000+0=2000; grant=0; equity=2000; debt=0; debt_service=0
        # flat revenue=600/yr; opex=100; surplus=500/yr
        # cumulative: -2000+500=-1500, +500=-1000, +500=-500, +500=0 → payback=year 4
        home = _make_home_config(pv_kwp=1.0, battery_kwh=None)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1000.0,
            roof_fit_cost_gbp=1000.0,
            battery_cost_per_kwh_gbp=250.0,
            grant_gbp=0.0,
            equity_fraction=1.0,
            loan_rate=0.07,
            loan_term_years=15,
            opex_per_home_per_year_gbp=100.0,
            asset_life_years=25,
        )
        # Revenue 600/yr; opex=100; surplus=500/yr; equity=2000
        curve = _make_curve([600.0] * 25)

        econ = project_economics(curve, scenario, finance)

        # capex=2000, equity=2000, debt=0
        # surplus each year = 600 - 100 - 0 = 500
        # cumulative: year1=-2000+500=-1500, y2=-1000, y3=-500, y4=0
        assert econ.payback_years == pytest.approx(4.0)

    def test_never_profitable_payback_is_none(self) -> None:
        """Never-profitable project → payback_years is None."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=4.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            grant_gbp=0.0,
            equity_fraction=1.0,
            loan_rate=0.0,
            loan_term_years=15,
            opex_per_home_per_year_gbp=9999.0,  # massive opex → always negative surplus
            asset_life_years=25,
        )
        # Low revenue, massive opex → surplus always negative
        curve = _make_curve([1.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert econ.payback_years is None

    def test_never_profitable_irr_is_nan(self) -> None:
        """Never-profitable project → equity_irr is NaN."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=4.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance(
            grant_gbp=0.0,
            equity_fraction=1.0,
            loan_rate=0.0,
            loan_term_years=15,
            opex_per_home_per_year_gbp=9999.0,
            asset_life_years=25,
        )
        curve = _make_curve([1.0] * 25)

        econ = project_economics(curve, scenario, finance)

        assert math.isnan(econ.equity_irr)

    def test_determinism(self) -> None:
        """Two project_economics calls with same inputs return bit-identical results."""
        from solar_challenge.finance import project_economics

        home = _make_home_config(pv_kwp=4.0, battery_kwh=5.0)
        scenario = _make_scenario(homes=[home])
        finance = _make_finance()
        curve = _make_curve([7000.0] * 25)

        econ1 = project_economics(curve, scenario, finance)
        econ2 = project_economics(curve, scenario, finance)

        # Bit-identical for all float fields
        assert econ1.total_capex_gbp == econ2.total_capex_gbp
        assert econ1.equity_irr == econ2.equity_irr or (
            math.isnan(econ1.equity_irr) and math.isnan(econ2.equity_irr)
        )
        assert econ1.payback_years == econ2.payback_years
        assert econ1.per_year_surplus_gbp == econ2.per_year_surplus_gbp
        assert econ1.min_dscr == econ2.min_dscr


# ---------------------------------------------------------------------------
# Step-11: generate_finance_report economics block
# ---------------------------------------------------------------------------


def _make_bill_distribution(multiplier: float = 1.0) -> "BillDistribution":  # type: ignore[name-defined]
    """Build a synthetic BillDistribution for report tests."""
    from solar_challenge.finance import BillBreakdown, BillDistribution

    rep = BillBreakdown(
        standing_charge_gbp=219.0 * multiplier,
        import_cost_gbp=276.0 * multiplier,
        vat_gbp=24.75 * multiplier,
        gross_bill_gbp=519.75 * multiplier,
        seg_export_income_gbp=73.8 * multiplier,
        self_consumption_saving_gbp=531.3 * multiplier,
        baseline_bill_gbp=980.0 * multiplier,
        net_annual_bill_gbp=445.95 * multiplier,
        saving_vs_baseline_gbp=534.05 * multiplier,
        saving_pct=54.5 * multiplier,
        self_consumption_fraction=0.55 * multiplier,
    )
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(rep.net_annual_bill_gbp,),
        min_gbp=300.0 * multiplier,
        mean_gbp=440.0 * multiplier,
        median_gbp=rep.net_annual_bill_gbp,
        max_gbp=600.0 * multiplier,
    )


def _make_project_economics(
    *,
    payback_years: Optional[float] = 10.0,
    equity_irr: float = 0.08,
) -> "ProjectEconomics":  # type: ignore[name-defined]
    """Build a synthetic ProjectEconomics for report tests."""
    from solar_challenge.finance import ProjectEconomics

    return ProjectEconomics(
        total_capex_gbp=250000.0,
        grant_gbp=50000.0,
        equity_gbp=150000.0,
        debt_gbp=50000.0,
        annual_debt_service_gbp=5500.0,
        per_year_surplus_gbp=tuple([8000.0] * 25),
        min_dscr=1.45,
        equity_irr=equity_irr,
        payback_years=payback_years,
        net_surplus_per_home_per_year_gbp=80.0,
    )


class TestGenerateFinanceReportEconomics:
    """Fast tests for output.generate_finance_report economics block (η)."""

    def test_economics_section_present(self) -> None:
        """Report with economics= must contain a Project Economics section."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics()
        report = generate_finance_report(dist, economics=econ)

        assert "Project Economics" in report or "project economics" in report.lower()

    def test_economics_capex_in_report(self) -> None:
        """Economics block must include total capex value."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics()
        report = generate_finance_report(dist, economics=econ)

        # capex = 250000.00 or similar formatting
        assert "250000" in report.replace(",", "").replace(" ", "")

    def test_economics_dscr_in_report(self) -> None:
        """Economics block must include min DSCR label."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics()
        report = generate_finance_report(dist, economics=econ)

        assert "DSCR" in report or "dscr" in report.lower()

    def test_economics_irr_in_report(self) -> None:
        """Economics block must include IRR label."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics()
        report = generate_finance_report(dist, economics=econ)

        assert "IRR" in report or "irr" in report.lower()

    def test_economics_payback_in_report(self) -> None:
        """Economics block must include payback label."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics()
        report = generate_finance_report(dist, economics=econ)

        assert "payback" in report.lower() or "Payback" in report

    def test_economics_none_payback_no_crash(self) -> None:
        """economics with payback_years=None must not crash and must render gracefully."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics(payback_years=None)
        # Should not raise
        report = generate_finance_report(dist, economics=econ)
        assert isinstance(report, str)
        # Should render a "never" or "—" or similar string, not "None"
        assert "None" not in report

    def test_economics_nan_irr_no_crash(self) -> None:
        """economics with equity_irr=nan must not crash."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        econ = _make_project_economics(equity_irr=float("nan"))
        report = generate_finance_report(dist, economics=econ)
        assert isinstance(report, str)

    def test_backward_compat_economics_none(self) -> None:
        """generate_finance_report() with no economics kwarg must return same as before."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        # Call without economics kwarg
        report_no_econ = generate_finance_report(dist)
        # Call with economics=None (explicit)
        report_econ_none = generate_finance_report(dist, economics=None)

        assert report_no_econ == report_econ_none

    def test_backward_compat_no_economics_section(self) -> None:
        """Report without economics kwarg must not contain Project Economics section."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        # No economics block should appear
        assert "Project Economics" not in report


# ---------------------------------------------------------------------------
# Step-13: CLI finance run --project (fast tests)
# ---------------------------------------------------------------------------


class TestFinanceProjectCLI:
    """Fast CLI tests for finance run --project (typer CliRunner, no simulation)."""

    def test_help_shows_project_flag(self) -> None:
        """`finance run --help` must show --project flag."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        assert "--project" in result.output or "project" in result.output.lower()

    def test_project_without_finance_block_exits_nonzero(self, tmp_path: "Path") -> None:
        """Invoking `finance run --project` on a scenario WITHOUT a finance: block exits non-zero."""
        import yaml
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        # Minimal scenario without finance:
        scenario = {
            "name": "No Finance Test",
            "location": {
                "latitude": 51.45,
                "longitude": -2.58,
                "timezone": "Europe/London",
            },
            "fleet_distribution": {
                "n_homes": 1,
                "seed": 1,
                "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
                "battery": {"capacity_kwh": None},
                "load": {"annual_consumption_kwh": 3400},
            },
        }
        scenario_file = tmp_path / "no_finance_project.yaml"
        scenario_file.write_text(yaml.dump(scenario))

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--project", str(scenario_file)])
        assert result.exit_code != 0


@pytest.mark.slow
class TestFinanceProjectCLIEndToEnd:
    """Slow end-to-end CLI test for finance run --project (real PVGIS)."""

    def test_finance_run_project_bristol(self) -> None:
        """E2E: `finance run --project scenarios/bristol-phase1.yaml` exits 0 with economics block."""
        from pathlib import Path
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario = Path("scenarios/bristol-phase1.yaml")
        if not scenario.exists():
            pytest.skip("bristol-phase1.yaml not found")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "finance",
                "run",
                "--project",
                str(scenario),
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-03",
            ],
        )
        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        output = result.output.lower()
        # Economics block headings must be present
        assert "project economics" in output
        assert "capex" in output
        assert "dscr" in output or "debt service" in output
        assert "irr" in output
        assert "payback" in output
