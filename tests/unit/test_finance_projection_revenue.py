# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's CBS revenue.

They cover own-use and SEG export income with and without the
self-consumption override, grid-services income, grid-charge energy paid once
on householder import, and the SEG income helper _seg_export_income_gbp, all
on an injected synthetic simulate.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_load_config,
    make_pv_config,
    make_scenario_and_finance,
    make_sim_results,
)


class TestProjectMultiYearRevenue:
    """fleet_revenue_gbp aggregation and self-consumption override switch."""

    def _make_revenue_scenario(
        self,
        n_homes: int = 2,
        self_consumption_override: float | None = None,
        seg_tariff_pence: float | None = 5.0,
    ) -> tuple:
        """Build scenario + finance for revenue tests."""
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

        homes = [make_home_config() for _ in range(n_homes)]
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            self_consumption_override=self_consumption_override,
            retail_baseline_rate_pence_per_kwh=30.0,
            vat_rate=0.05,
        )
        scenario = ScenarioConfig(
            name="revenue-test",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Revenue test",
            homes=homes,
            seg_tariff_pence_per_kwh=seg_tariff_pence,
        )
        return scenario, finance

    def test_fleet_revenue_at_sampled_age_matches_householder_bill_sum(self) -> None:
        """fleet_revenue_gbp at age 0 equals CBS formula: own_use + seg (no grid-charge term).

        Own-use is own_use_rate_pence_per_kwh × fleet own-use and SEG is the sum of
        _seg_export_income_gbp; neither is priced at retail_baseline_rate.
        """
        from solar_challenge.finance import (  # type: ignore[attr-defined]
            _annualise_physics,
            _seg_export_income_gbp,
            project_multi_year,
        )
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc, exp, imp = 3000.0, 1500.0, 500.0
        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp)

        # Expected CBS revenue (PRD §3.2)
        summaries = [calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
                     for r in fr.per_home_results]
        fleet_sc_kwh = sum(s.total_self_consumption_kwh for s in summaries)
        # No grid services: the homes have no battery
        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc_kwh / 100.0
        seg_revenue = sum(
            _seg_export_income_gbp(_annualise_physics(s, s.simulation_days), finance)
            for s in summaries
        )
        expected_revenue = own_use_revenue + seg_revenue

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        # At year 0 (a seeded age), the revenue should match the CBS formula
        assert curve.points[0].fleet_revenue_gbp == pytest.approx(expected_revenue, rel=1e-4)

    def test_grid_services_included_in_fleet_revenue(self) -> None:
        """fleet_revenue_gbp includes grid_services = rate × Σ max_discharge_kw when rate > 0."""
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.fleet import FleetResults
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import HomeConfig
        from solar_challenge.location import Location

        # Battery-equipped home so max_discharge_kw is available
        bat_config = BatteryConfig(capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5)
        home_with_bat = HomeConfig(
            pv_config=make_pv_config(),
            load_config=make_load_config(),
            location=Location.bristol(),
            battery_config=bat_config,
        )
        n_homes = 2
        homes = [home_with_bat] * n_homes
        grid_services_rate = 50.0  # £/kW/year

        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=5,
            loan_term_years=5,  # must be <= asset_life_years
            own_use_rate_pence_per_kwh=15.0,
            grid_services_income_per_kw_per_year_gbp=grid_services_rate,
        )
        scenario = ScenarioConfig(
            name="gs-test",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Grid services test",
            homes=homes,
        )

        # Synthetic fleet results with no grid_charge_cost
        fr_bat = FleetResults(
            per_home_results=[make_sim_results(self_kwh=3000.0, export_kwh=500.0, import_kwh=300.0)
                               for _ in range(n_homes)],
            home_configs=homes,
        )
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr_bat)

        # Expected grid_services contribution at age 0
        total_discharge_kw = n_homes * bat_config.max_discharge_kw
        expected_gs = grid_services_rate * total_discharge_kw
        assert curve.points[0].fleet_revenue_gbp >= expected_gs - 1e-6, (
            f"fleet_revenue_gbp ({curve.points[0].fleet_revenue_gbp:.4f}) should include "
            f"grid_services ({expected_gs:.4f} = {grid_services_rate} × {total_discharge_kw} kW)"
        )

    def test_self_consumption_override_drives_own_use_revenue(self) -> None:
        """With the override set, own-use revenue bills the own-use householder_bill charges.

        One home: 5,000 kWh generation, 4,500 kWh demand and 4,000 kWh basis-C own-use.
        The physics curve bills basis C at 15 p; the 0.50 override bills
        min(0.50 × 5,000, 4,500) = 2,500 kWh, where the cap does not bind.  SEG adds £0
        on both paths: the builder's exports earn £0, so the effective export rate is 0 p.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        fr = make_fleet_results(n_homes=1, self_kwh=4000.0, export_kwh=1000.0, import_kwh=500.0)

        def year_0(self_consumption_override: float | None) -> "YearPoint":  # type: ignore[name-defined]
            scenario, finance = self._make_revenue_scenario(
                n_homes=1, self_consumption_override=self_consumption_override
            )
            return project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr).points[0]

        physics = year_0(self_consumption_override=None)
        override = year_0(self_consumption_override=0.50)

        assert physics.fleet_self_consumption_kwh == pytest.approx(4000.0)
        assert physics.fleet_revenue_gbp == pytest.approx(600.0)
        assert override.fleet_self_consumption_kwh == pytest.approx(2500.0)
        assert override.fleet_revenue_gbp == pytest.approx(375.0)

    def test_override_bills_own_use_up_to_demand_and_exports_the_rest(self) -> None:
        """Override 0.90 implies 3,600 kWh of own-use per home against a 2,800 kWh demand.

        Own-use is capped at demand, so each home is billed 2,800 kWh of own-use at 15 p,
        and the rest of its 4,000 kWh generation, 1,200 kWh, is exported at its physics
        export rate (£72 / 2,400 kWh = 3 p).  Both are priced.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.fleet import FleetResults

        n_homes = 2
        fleet = FleetResults(
            per_home_results=[
                make_sim_results(
                    self_kwh=1600.0, export_kwh=2400.0, import_kwh=1200.0, export_revenue_gbp=72.0
                )
                for _ in range(n_homes)
            ],
            home_configs=[make_home_config() for _ in range(n_homes)],
        )
        scenario, finance = self._make_revenue_scenario(
            n_homes=n_homes, self_consumption_override=0.90
        )

        year_0 = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet).points[0]

        assert year_0.fleet_self_consumption_kwh == pytest.approx(n_homes * 2800.0)
        assert year_0.fleet_revenue_gbp == pytest.approx(
            n_homes * (15.0 * 2800.0 / 100.0 + 1200.0 * 3.0 / 100.0)
        )

    def test_fleet_revenue_non_negative(self) -> None:
        """fleet_revenue_gbp is non-negative for all years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = self._make_revenue_scenario(n_homes=1)
        # every CBS revenue term is non-negative
        fr = make_fleet_results(n_homes=1, self_kwh=2000.0, export_kwh=800.0, import_kwh=300.0)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.fleet_revenue_gbp >= 0.0


def _make_grid_charging_sim_results(
    sc_kwh: float = 2000.0,
    export_kwh: float = 400.0,
    import_to_load_kwh: float = 800.0,
    grid_charge_kwh: float = 200.0,
    peak_pence: float = 30.0,
    off_peak_pence: float = 9.0,
    n_steps: int = 8760,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Full-year TOU home whose battery grid-charges off-peak through the grid meter.

    Grid charge is metered import: grid_import = import_to_load + grid_charge, with
    load import priced at peak and grid charge at off-peak, and grid_charge_cost the
    grid-charge slice of import_cost.  self_consumption is B-style (it includes the
    grid-charged discharge), so basis-C own-use = demand − import = sc − grid_charge.
    Defaults give per home: total_import_cost_gbp £258.00, of which
    total_grid_charge_cost_gbp £18.00; basis-C own-use 1800 kWh.

    Hourly index with kW = kWh / (n_steps / 60), so calculate_summary's 1/60
    integration returns the kWh totals and simulation_days is 365.
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")

    def constant_kw(kwh: float) -> "pd.Series":
        return pd.Series(kwh / (n_steps / 60.0), index=idx)

    def constant_gbp(pence: float) -> "pd.Series":
        return pd.Series(pence / 100.0 / n_steps, index=idx)

    zeros = pd.Series(0.0, index=idx)
    grid_charge_pence = grid_charge_kwh * off_peak_pence
    return SimulationResults(
        generation=constant_kw(sc_kwh + export_kwh),
        demand=constant_kw(sc_kwh + import_to_load_kwh),
        self_consumption=constant_kw(sc_kwh),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=constant_kw(import_to_load_kwh + grid_charge_kwh),
        grid_export=constant_kw(export_kwh),
        import_cost=constant_gbp(import_to_load_kwh * peak_pence + grid_charge_pence),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=constant_gbp(grid_charge_pence),
    )


class TestGridChargeEnergyPaidOnce:
    """H9 under basis C: each grid-charged kWh is paid once, by the householder, as import.

    Three observation points on one TOU + grid-charging fleet: the householder ledger
    (householder_bill import_cost_gbp), the CBS ledger (project_multi_year
    fleet_revenue_gbp) and the metered truth (calculate_summary total_import_cost_gbp).
    See docs/cost-recovery-finance-model.md §4.
    """

    N_HOMES = 2

    def _fleet(self) -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        return FleetResults(
            per_home_results=[_make_grid_charging_sim_results() for _ in range(self.N_HOMES)],
            home_configs=[make_home_config() for _ in range(self.N_HOMES)],
        )

    @staticmethod
    def _without_grid_charge_cost_series(fleet: "FleetResults") -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        return FleetResults(
            per_home_results=[
                dataclasses.replace(r, grid_charge_cost=None) for r in fleet.per_home_results
            ],
            home_configs=fleet.home_configs,
        )

    @staticmethod
    def _householder_import_cost_gbp(
        summary: "SummaryStatistics",  # type: ignore[name-defined]
        finance: "FinanceConfig",  # type: ignore[name-defined]
    ) -> float:
        from solar_challenge.finance import householder_bill

        basis_c_own_use_kwh = summary.total_demand_kwh - summary.total_grid_import_kwh
        return householder_bill(
            summary, basis_c_own_use_kwh, finance, summary.simulation_days
        ).import_cost_gbp

    @staticmethod
    def _cbs_revenue_at_age_0(
        fleet: "FleetResults",  # type: ignore[name-defined]
        scenario: "ScenarioConfig",  # type: ignore[name-defined]
        finance: "FinanceConfig",  # type: ignore[name-defined]
    ) -> float:
        from solar_challenge.finance import project_multi_year

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)
        return curve.points[0].fleet_revenue_gbp

    def test_householder_import_cost_includes_grid_charging(self) -> None:
        """The householder pays the retailer for grid-charge energy inside import_cost_gbp.

        Pins which ledger bears the cost: the bill carries the full metered import cost,
        more than the builder's load-import-only £240 (800 kWh at 30p).
        """
        from solar_challenge.home import calculate_summary

        _, finance = make_scenario_and_finance(n_homes=self.N_HOMES, asset_life_years=5)
        load_import_only_gbp = 800.0 * 30.0 / 100.0
        for result in self._fleet().per_home_results:
            summary = calculate_summary(result)
            householder_import_gbp = self._householder_import_cost_gbp(summary, finance)
            assert householder_import_gbp == pytest.approx(summary.total_import_cost_gbp)
            assert householder_import_gbp > load_import_only_gbp

    def test_cbs_revenue_has_no_grid_charge_term(self) -> None:
        """CBS revenue on the grid-charging fleet is own-use + SEG + grid services, nothing else.

        The fleet earns no SEG and no grid services, so year-0 revenue is exactly
        own_use_rate × Σ basis-C own-use (demand − import) / 100.
        """
        from solar_challenge.home import calculate_summary

        scenario, finance = make_scenario_and_finance(n_homes=self.N_HOMES, asset_life_years=5)
        fleet = self._fleet()
        summaries = [calculate_summary(r) for r in fleet.per_home_results]
        assert all(s.total_export_revenue_gbp == 0.0 for s in summaries), "premise: no SEG"
        assert finance.grid_services_income_per_kw_per_year_gbp == 0.0, "premise: no grid services"

        own_use_kwh = sum(s.total_demand_kwh - s.total_grid_import_kwh for s in summaries)
        own_use_gbp = finance.own_use_rate_pence_per_kwh * own_use_kwh / 100.0
        cbs_gbp = self._cbs_revenue_at_age_0(fleet, scenario, finance)

        assert cbs_gbp == pytest.approx(own_use_gbp, abs=1e-9), (
            f"CBS revenue £{cbs_gbp:.2f} != own-use £{own_use_gbp:.2f} + SEG £0 + "
            f"grid services £0; extra term £{cbs_gbp - own_use_gbp:.2f}"
        )

    def test_grid_charge_energy_paid_once_across_ledgers(self) -> None:
        """Σ householder import cost + grid-charge cost borne by the CBS == metered import cost.

        The CBS share is the revenue drop against a twin fleet with identical energy and
        import cost but no grid_charge_cost series.
        """
        from solar_challenge.home import calculate_summary

        scenario, finance = make_scenario_and_finance(n_homes=self.N_HOMES, asset_life_years=5)
        fleet = self._fleet()
        summaries = [calculate_summary(r) for r in fleet.per_home_results]

        householder_gbp = sum(self._householder_import_cost_gbp(s, finance) for s in summaries)
        metered_gbp = sum(s.total_import_cost_gbp for s in summaries)
        cbs_gbp = self._cbs_revenue_at_age_0(
            self._without_grid_charge_cost_series(fleet), scenario, finance
        ) - self._cbs_revenue_at_age_0(fleet, scenario, finance)

        assert householder_gbp + cbs_gbp == pytest.approx(metered_gbp, abs=1e-9), (
            "grid-charge energy paid twice: householder import already includes it and "
            f"CBS revenue deducts it again (householder £{householder_gbp:.2f} + "
            f"CBS £{cbs_gbp:.2f} vs metered £{metered_gbp:.2f}; "
            f"excess £{householder_gbp + cbs_gbp - metered_gbp:.2f})"
        )


def _make_seg_summary(
    total_generation_kwh: float = 4000.0,
    total_grid_export_kwh: float = 800.0,
    total_export_revenue_gbp: float = 24.0,
) -> "SummaryStatistics":  # type: ignore[name-defined]
    """Minimal SummaryStatistics for testing _seg_export_income_gbp."""
    from solar_challenge.home import SummaryStatistics

    sc_kwh = total_generation_kwh - total_grid_export_kwh
    return SummaryStatistics(
        total_generation_kwh=total_generation_kwh,
        total_demand_kwh=sc_kwh + 1200.0,
        total_self_consumption_kwh=sc_kwh,
        total_grid_import_kwh=1200.0,
        total_grid_export_kwh=total_grid_export_kwh,
        total_battery_charge_kwh=0.0,
        total_battery_discharge_kwh=0.0,
        peak_generation_kw=2.0,
        peak_demand_kw=1.5,
        self_consumption_ratio=sc_kwh / total_generation_kwh if total_generation_kwh > 0 else 0.0,
        grid_dependency_ratio=0.3,
        export_ratio=total_grid_export_kwh / total_generation_kwh if total_generation_kwh > 0 else 0.0,
        simulation_days=365,
        total_import_cost_gbp=276.0,
        total_export_revenue_gbp=total_export_revenue_gbp,
        net_cost_gbp=276.0 - total_export_revenue_gbp,
    )


class TestSegExportIncomeGbp:
    """Direct unit tests for _seg_export_income_gbp.

    The helper's zero-export fallback and override-path arithmetic are not
    covered by hand-computed assertions in the projection tests (which use the
    function under test to compute expected values, making them wiring tests
    rather than contract tests).  These tests verify the helper's own logic.
    """

    def _make_finance_seg(
        self,
        self_consumption_override: "float | None" = None,
    ) -> "FinanceConfig":  # type: ignore[name-defined]
        from solar_challenge.config import FinanceConfig

        return FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=5,
            loan_term_years=5,
            self_consumption_override=self_consumption_override,
            own_use_rate_pence_per_kwh=15.0,
        )

    def test_physics_path_returns_annualised_export_revenue(self) -> None:
        """Physics path (no override): returns total_export_revenue_gbp directly."""
        from solar_challenge.finance import _annualise_physics, _seg_export_income_gbp  # type: ignore[attr-defined]

        summary = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=800.0,
            total_export_revenue_gbp=24.0,
        )
        finance = self._make_finance_seg(self_consumption_override=None)

        result = _seg_export_income_gbp(_annualise_physics(summary, 365), finance)

        assert result == pytest.approx(24.0, rel=1e-9)

    def test_override_zero_export_kwh_returns_zero(self) -> None:
        """Override path with zero physics export kWh: returns 0.0 (rate fallback).

        When total_grid_export_kwh == 0, the effective export rate cannot be
        derived from physics figures and falls back to 0.0 p/kWh.  The result
        must be exactly 0.0 regardless of the override fraction.
        """
        from solar_challenge.finance import _annualise_physics, _seg_export_income_gbp  # type: ignore[attr-defined]

        # Summary with no export at all (e.g. all generation self-consumed)
        summary_no_export = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=0.0,
            total_export_revenue_gbp=0.0,
        )
        finance = self._make_finance_seg(self_consumption_override=0.60)

        result = _seg_export_income_gbp(_annualise_physics(summary_no_export, 365), finance)

        # effective_export_rate_pence = 0.0 (fallback), so result = override_export * 0 = 0
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_override_nonzero_export_computes_override_kwh_times_effective_rate(self) -> None:
        """Override path with nonzero physics export: returns override_export_kwh × effective_rate.

        Contract (§3.2):
          own_use         = min(override × gen_kwh, demand_kwh)
          override_export = gen_kwh − own_use
          effective_rate  = (export_rev / export_kwh) × 100  p/kWh
          result          = override_export × effective_rate / 100

        Using override=0.60 (own-use 0.60×4000 = 2400 kWh, within the 4400 kWh
        demand) against physics that had 20% export (800 kWh, 24 £ → 3 p/kWh):
          override_export = 4000 - 2400 = 1600 kWh
          effective_rate  = (24/800)×100 = 3 p/kWh
          result          = 1600×3/100 = 48 £
        """
        from solar_challenge.finance import _annualise_physics, _seg_export_income_gbp  # type: ignore[attr-defined]

        summary = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=800.0,   # physics: 20% of gen
            total_export_revenue_gbp=24.0,  # => 3 p/kWh effective rate
        )
        # Override: 60% self-consumption → 40% export → 1600 kWh
        finance = self._make_finance_seg(self_consumption_override=0.60)

        result = _seg_export_income_gbp(_annualise_physics(summary, 365), finance)

        # hand-checked: 1600 * 3 / 100 = 48.0
        assert result == pytest.approx(48.0, rel=1e-9)

    def test_short_period_annualises_physics_export_revenue(self) -> None:
        """Physics path: short simulation period is annualised to 365 days."""
        from solar_challenge.finance import _annualise_physics, _seg_export_income_gbp  # type: ignore[attr-defined]

        # Build a summary with a 182-day simulation (half year)
        from solar_challenge.home import SummaryStatistics

        summary_182 = SummaryStatistics(
            total_generation_kwh=2000.0,
            total_demand_kwh=2600.0,
            total_self_consumption_kwh=1600.0,
            total_grid_import_kwh=1000.0,
            total_grid_export_kwh=400.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=2.0,
            peak_demand_kw=1.5,
            self_consumption_ratio=0.80,
            grid_dependency_ratio=0.38,
            export_ratio=0.20,
            simulation_days=182,
            total_import_cost_gbp=230.0,
            total_export_revenue_gbp=12.0,  # half-year figure
            net_cost_gbp=218.0,
        )
        finance = self._make_finance_seg(self_consumption_override=None)

        result = _seg_export_income_gbp(_annualise_physics(summary_182, 182), finance)

        expected = 12.0 * (365 / 182)
        assert result == pytest.approx(expected, rel=1e-6)
