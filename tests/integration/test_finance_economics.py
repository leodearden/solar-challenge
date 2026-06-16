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
    import pandas as pd
    period = SimulationPeriod(
        start=pd.Timestamp("2024-01-01"),
        end=pd.Timestamp("2024-12-31"),
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
