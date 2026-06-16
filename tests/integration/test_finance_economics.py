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
