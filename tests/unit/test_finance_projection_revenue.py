# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's CBS revenue.

They cover own-use income and SEG export income, each home's export priced at
the SEG rate its results record, with and without the self-consumption
override, under which the fleet's export and import are the override's split
of its generation and demand, grid-services income, grid-charge energy paid once on householder
import, and the refusal of a simulate whose fleet lacks the batteries it was
asked for or whose results record no pricing, all on an injected synthetic
simulate.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import FinanceConfig, householder_bill
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.home import HomeConfig, RunPricing, SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.projection import (
    YearPoint,
    project_multi_year,
    solve_cost_recovery_rate,
)
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_home_config,
    make_period,
    make_scenario_and_finance,
    make_scenario_of,
    make_sim_results,
)


def _fleet_whose_export_revenue_sums_to(
    export_revenue_gbp: float,
    homes: Sequence[HomeConfig],
    *,
    self_kwh: float,
    export_kwh: float,
    import_kwh: float,
    pricing: RunPricing,
) -> FleetResults:
    """Each of *homes* with make_sim_results of the totals at *pricing*, its export_revenue series replaced by one summing to *export_revenue_gbp*."""
    results = make_sim_results(self_kwh=self_kwh, export_kwh=export_kwh, import_kwh=import_kwh, pricing=pricing)
    rows = results.export_revenue.index
    with_revenue = dataclasses.replace(results, export_revenue=pd.Series(export_revenue_gbp / len(rows), index=rows))
    return make_fleet_results_of([with_revenue for _ in homes], homes=homes)


class TestProjectMultiYearRevenue:
    """fleet_revenue_gbp aggregation and self-consumption override switch."""

    def _make_revenue_scenario(
        self,
        n_homes: int = 2,
        self_consumption_override: float | None = None,
        seg_tariff_pence: float | None = 5.0,
    ) -> tuple:
        """Build scenario + finance for revenue tests."""
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
            period=make_period(),
            description="Revenue test",
            homes=homes,
            seg_tariff_pence_per_kwh=seg_tariff_pence,
        )
        return scenario, finance

    def test_fleet_revenue_at_sampled_age_matches_householder_bill_sum(self) -> None:
        """fleet_revenue_gbp at age 0 equals CBS formula: own_use + seg (no grid-charge term).

        Own-use is own_use_rate_pence_per_kwh × fleet own-use and SEG is each home's
        export at the 5 p SEG rate its results record; neither is priced at
        retail_baseline_rate.
        """
        n_homes = 2
        sc, exp, imp = 3000.0, 1500.0, 500.0
        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)
        fr = make_fleet_results(
            n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp, pricing=RunPricing(None, 5.0)
        )

        # Expected CBS revenue (docs/prds/cost-recovery-householder-billing.md §3.2)
        summaries = [calculate_summary(r) for r in fr.per_home_results]
        fleet_sc_kwh = sum(s.total_self_consumption_kwh for s in summaries)
        # No grid services: the homes have no battery
        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc_kwh / 100.0
        seg_revenue = sum(s.total_grid_export_kwh * 5.0 / 100.0 for s in summaries)
        expected_revenue = own_use_revenue + seg_revenue

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        # At year 0 (a seeded age), the revenue should match the CBS formula
        assert curve.points[0].fleet_revenue_gbp == pytest.approx(expected_revenue, rel=1e-4)

    def test_grid_services_included_in_fleet_revenue(self) -> None:
        """fleet_revenue_gbp includes grid_services = rate × Σ max_discharge_kw when rate > 0."""
        # Battery-equipped homes so max_discharge_kw is available
        bat_config = BatteryConfig(capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5)
        n_homes = 2
        grid_services_rate = 50.0  # £/kW/year

        scenario, finance = make_scenario_and_finance(
            n_homes=n_homes, asset_life_years=5, battery_config=bat_config
        )
        finance = dataclasses.replace(finance, grid_services_income_per_kw_per_year_gbp=grid_services_rate)

        # Synthetic fleet results with no grid_charge_cost
        fr_bat = make_fleet_results(homes=scenario.homes, self_kwh=3000.0, export_kwh=500.0, import_kwh=300.0)
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
        on both paths: its results carry no SEG rate, whatever the scenario's.
        """
        fr = make_fleet_results(n_homes=1, self_kwh=4000.0, export_kwh=1000.0, import_kwh=500.0)

        def year_0(self_consumption_override: float | None) -> YearPoint:
            scenario, finance = self._make_revenue_scenario(
                n_homes=1, self_consumption_override=self_consumption_override
            )
            return project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr).points[0]

        physics = year_0(self_consumption_override=None)
        override = year_0(self_consumption_override=0.50)

        assert physics.fleet_billed_own_use_kwh == pytest.approx(4000.0)
        assert physics.fleet_revenue_gbp == pytest.approx(600.0)
        assert override.fleet_billed_own_use_kwh == pytest.approx(2500.0)
        assert override.fleet_revenue_gbp == pytest.approx(375.0)

    def test_override_bills_own_use_up_to_demand_and_exports_the_rest(self) -> None:
        """Override 0.90 implies 3,600 kWh of own-use per home against a 2,800 kWh demand.

        Own-use is capped at demand, so each home is billed 2,800 kWh of own-use at 15 p,
        and the rest of its 4,000 kWh generation, 1,200 kWh, is exported at its physics
        export rate (£72 / 2,400 kWh = 3 p).  Both are priced, and the year reports
        the export its SEG income was priced on and no import.
        """
        n_homes = 2
        fleet = make_fleet_results(
            n_homes=n_homes, self_kwh=1600.0, export_kwh=2400.0, import_kwh=1200.0, pricing=RunPricing(None, 3.0)
        )
        scenario, finance = self._make_revenue_scenario(
            n_homes=n_homes, self_consumption_override=0.90
        )

        year_0 = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet).points[0]

        assert year_0.fleet_billed_own_use_kwh == pytest.approx(n_homes * 2800.0)
        assert year_0.fleet_revenue_gbp == pytest.approx(
            n_homes * (15.0 * 2800.0 / 100.0 + 1200.0 * 3.0 / 100.0)
        )
        assert year_0.fleet_export_kwh == pytest.approx(n_homes * 1200.0)
        assert year_0.fleet_import_kwh == pytest.approx(0.0)

    def test_fleet_revenue_non_negative(self) -> None:
        """fleet_revenue_gbp is non-negative for all years."""
        scenario, finance = self._make_revenue_scenario(n_homes=1)
        # every CBS revenue term is non-negative
        fr = make_fleet_results(n_homes=1, self_kwh=2000.0, export_kwh=800.0, import_kwh=300.0)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.fleet_revenue_gbp >= 0.0


class TestSegIncomeAtTheHomesRate:
    """The CBS earns each home's export at the SEG rate its results record.

    The export is the simulated export on the physics basis, and generation −
    own-use with the override set, whatever the simulated export.  A home whose
    results record no SEG rate earns none.  A home's export_revenue series never
    moves the income, and results that record no pricing at all are refused.
    The default finance has no grid services.
    """

    @pytest.mark.parametrize(
        ("self_kwh", "export_kwh", "discharge_kwh"),
        [
            pytest.param(4000.0, 0.0, 600.0, id="no-simulated-export"),
            pytest.param(3999.0, 1.0, 599.0, id="1-kwh-simulated-export"),
        ],
    )
    def test_the_overrides_export_earns_the_homes_seg_rate_whatever_it_simulated(
        self, self_kwh: float, export_kwh: float, discharge_kwh: float
    ) -> None:
        """At override 0.7 the 4,000 kWh generation against 3,400 kWh demand exports 1,200 kWh, which earns £49.20 at 4.1 p."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        finance = dataclasses.replace(finance, self_consumption_override=0.7, own_use_rate_pence_per_kwh=0.0)

        curve = project_multi_year(
            scenario,
            finance,
            simulate=lambda fc, s, e: make_fleet_results(
                homes=fc.homes,
                self_kwh=self_kwh,
                export_kwh=export_kwh,
                import_kwh=0.0,
                discharge_kwh=discharge_kwh,
                pricing=RunPricing(None, 4.1),
            ),
        )

        assert curve.points[0].fleet_revenue_gbp == pytest.approx(1200.0 * 4.1 / 100.0)

    @pytest.mark.parametrize(
        ("pricing", "seg_income_gbp"),
        [
            pytest.param(RunPricing(None, 5.0), 800.0 * 5.0 / 100.0, id="5p"),
            pytest.param(RunPricing(None, None), 0.0, id="no-seg-rate"),
        ],
    )
    def test_the_simulated_export_earns_the_homes_seg_rate(self, pricing: RunPricing, seg_income_gbp: float) -> None:
        """800 kWh exported at 5 p adds £40 to the own-use revenue of 15 p × 100 kWh = £15; with no SEG rate it adds nothing."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        assert finance.own_use_rate_pence_per_kwh == 15.0, "premise: own-use at 15 p"

        curve = project_multi_year(
            scenario,
            finance,
            simulate=lambda fc, s, e: make_fleet_results(
                homes=fc.homes, self_kwh=100.0, export_kwh=800.0, import_kwh=300.0, pricing=pricing
            ),
        )

        assert curve.points[0].fleet_revenue_gbp == pytest.approx(15.0 + seg_income_gbp)

    @pytest.mark.parametrize(
        ("pricing", "seg_income_gbp"),
        [
            pytest.param(RunPricing(None, 5.0), 800.0 * 5.0 / 100.0, id="5p"),
            pytest.param(RunPricing(None, None), 0.0, id="no-seg-rate"),
        ],
    )
    def test_an_export_revenue_series_does_not_move_the_seg_income(
        self, pricing: RunPricing, seg_income_gbp: float
    ) -> None:
        """The home's export_revenue series sums to −£50, yet it projects 15 p × 100 kWh = £15 of own-use a year plus its 800 kWh at the SEG rate its results record: £40 at 5 p, nothing with none."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        assert finance.own_use_rate_pence_per_kwh == 15.0, "premise: own-use at 15 p"
        assert finance.self_consumption_override is None, "premise: the physics basis"

        curve = project_multi_year(
            scenario,
            finance,
            simulate=lambda fc, s, e: _fleet_whose_export_revenue_sums_to(
                -50.0, fc.homes, self_kwh=100.0, export_kwh=800.0, import_kwh=300.0, pricing=pricing
            ),
        )

        assert [point.fleet_revenue_gbp for point in curve.points] == pytest.approx([15.0 + seg_income_gbp] * 5)

    def test_a_negative_export_at_a_seg_rate_is_refused_naming_it(self) -> None:
        """seg.calculate_seg_revenue prices the SEG income, as it prices simulate_home's, and refuses an export below 0 kWh."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)

        with pytest.raises(ValueError, match="Export energy must be non-negative, got -"):
            project_multi_year(
                scenario,
                finance,
                simulate=lambda fc, s, e: make_fleet_results(
                    homes=fc.homes, self_kwh=500.0, export_kwh=-100.0, import_kwh=300.0, pricing=RunPricing(None, 5.0)
                ),
            )

    @pytest.mark.parametrize(
        "run_it",
        [
            pytest.param(project_multi_year, id="project_multi_year"),
            pytest.param(solve_cost_recovery_rate, id="solve_cost_recovery_rate"),
        ],
    )
    def test_results_that_record_no_pricing_are_refused_naming_calculate_summary(
        self, run_it: Callable[..., object]
    ) -> None:
        scenario, finance = make_scenario_and_finance(asset_life_years=5)

        with pytest.raises(ValueError) as excinfo:
            run_it(scenario, finance, simulate=lambda fc, s, e: make_fleet_results(homes=fc.homes, pricing=None))

        assert "pricing" in str(excinfo.value)
        assert "calculate_summary" in str(excinfo.value)


class TestSimulateMustReturnTheFleetsBatteries:
    """project_multi_year refuses a simulate whose FleetResults lack the batteries of the fleet it asked for.

    Grid-services income is priced from the batteries of the home_configs that
    simulate returns, so an answer without the asked homes' batteries would price
    it silently wrong: a battery-less answer prices a flat rate at £0.  Each age
    asks for the scenario's batteries at that age's state of health, which the
    comparison sets aside.
    """

    _BATTERY = BatteryConfig(capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5)

    @staticmethod
    def _homes_with(*batteries: BatteryConfig) -> list[HomeConfig]:
        """A default home fitted with each of *batteries*, in order."""
        return [make_home_config(battery_config=battery) for battery in batteries]

    def _scenario_and_flat_finance(
        self, batteries: tuple[BatteryConfig, ...] = (_BATTERY, _BATTERY)
    ) -> tuple[ScenarioConfig, FinanceConfig]:
        """The homes fitted with *batteries*, two with _BATTERY by default, and a finance paying £12 per kW of battery discharge power per year."""
        _, finance = make_scenario_and_finance(asset_life_years=5)
        scenario = make_scenario_of(self._homes_with(*batteries))
        return scenario, dataclasses.replace(finance, grid_services_income_per_kw_per_year_gbp=12.0)

    @staticmethod
    def _battery_less(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        """Answer any fleet with two default homes, which have no battery."""
        return make_fleet_results(n_homes=2)

    def test_an_answer_without_the_batteries_is_refused_naming_the_fleet_the_home_and_both_batteries(self) -> None:
        scenario, finance = self._scenario_and_flat_finance()
        asked = dataclasses.replace(self._BATTERY, soh=None)

        with pytest.raises(ValueError) as excinfo:
            project_multi_year(scenario, finance, simulate=self._battery_less)

        message = str(excinfo.value)
        assert "proj-age-0" in message
        assert "home 0" in message
        assert repr(asked) in message
        assert "None" in message.replace(repr(asked), "")

    def test_an_answer_with_other_batteries_is_refused_naming_both(self) -> None:
        """A 10 kWh battery is refused, although its discharge power would price the same flat income."""
        scenario, finance = self._scenario_and_flat_finance()
        other = BatteryConfig(capacity_kwh=10.0)
        assert other.max_discharge_kw == self._BATTERY.max_discharge_kw, "premise: the same discharge power"
        answer = make_fleet_results(homes=[make_home_config(battery_config=other)] * 2)

        with pytest.raises(ValueError) as excinfo:
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: answer)

        message = str(excinfo.value)
        assert repr(dataclasses.replace(other, soh=None)) in message
        assert repr(dataclasses.replace(self._BATTERY, soh=None)) in message

    def test_the_refusal_names_the_first_home_whose_batteries_differ_and_both_of_its_batteries(self) -> None:
        """Asked for a 5 and a 7.5 kWh battery and answered with a 5 and a 10 kWh one, it names home 1, 7.5 and 10 kWh."""
        asked_second, answered_second = BatteryConfig(capacity_kwh=7.5), BatteryConfig(capacity_kwh=10.0)
        scenario, finance = self._scenario_and_flat_finance((self._BATTERY, asked_second))
        answer = make_fleet_results(homes=self._homes_with(self._BATTERY, answered_second))

        with pytest.raises(ValueError) as excinfo:
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: answer)

        message = str(excinfo.value)
        assert "home 1" in message
        assert repr(dataclasses.replace(asked_second, soh=None)) in message
        assert repr(dataclasses.replace(answered_second, soh=None)) in message

    def test_the_asked_batteries_answered_in_another_order_are_refused_at_the_first_home(self) -> None:
        """Asked for a 5 and a 10 kWh battery and answered with the two swapped, it names home 0."""
        larger = BatteryConfig(capacity_kwh=10.0)
        scenario, finance = self._scenario_and_flat_finance((self._BATTERY, larger))
        answer = make_fleet_results(homes=self._homes_with(larger, self._BATTERY))

        with pytest.raises(ValueError) as excinfo:
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: answer)

        assert "home 0" in str(excinfo.value)

    def test_an_answer_of_another_number_of_homes_is_refused_naming_both_counts(self) -> None:
        scenario, finance = self._scenario_and_flat_finance()

        with pytest.raises(ValueError) as excinfo:
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: make_fleet_results(n_homes=3))

        message = str(excinfo.value)
        assert "proj-age-0" in message
        assert re.search(r"\b3\b", message)
        assert re.search(r"\b2\b", message)

    def test_the_cost_recovery_solve_refuses_it_as_the_projection_does(self) -> None:
        scenario, finance = self._scenario_and_flat_finance()

        with pytest.raises(ValueError) as from_projection:
            project_multi_year(scenario, finance, simulate=self._battery_less)
        with pytest.raises(ValueError) as from_solve:
            solve_cost_recovery_rate(scenario, finance, simulate=self._battery_less)

        assert "proj-age-0" in str(from_solve.value)
        assert str(from_solve.value) == str(from_projection.value)

    def test_the_scenarios_unaged_batteries_are_accepted_at_every_age(self) -> None:
        """An answer of the scenario's own homes at every age prices the 0.5.0 tag's flat income, 12 × 2 × 2.5 = £60.

        Those are the established canned simulate's homes, whose batteries carry
        no state of health while each age asks for its own.
        """
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=5, battery_config=self._BATTERY)
        assert finance.grid_services_income_per_kw_per_year_gbp == 0.0, "premise: no grid services by default"
        flat = dataclasses.replace(finance, grid_services_income_per_kw_per_year_gbp=12.0)
        answer = make_fleet_results(homes=scenario.homes, self_kwh=3000.0, export_kwh=500.0, import_kwh=300.0)

        def year_0_revenue_gbp(priced: FinanceConfig) -> float:
            return project_multi_year(scenario, priced, simulate=lambda fc, s, e: answer).points[0].fleet_revenue_gbp

        assert year_0_revenue_gbp(flat) - year_0_revenue_gbp(finance) == pytest.approx(60.0)


def _make_grid_charging_sim_results(
    sc_kwh: float = 2000.0,
    export_kwh: float = 400.0,
    import_to_load_kwh: float = 800.0,
    grid_charge_kwh: float = 200.0,
    peak_pence: float = 30.0,
    off_peak_pence: float = 9.0,
    n_steps: int = 8760,
) -> SimulationResults:
    """Full-year TOU home whose battery grid-charges off-peak through the grid meter.

    Grid charge is metered import: grid_import = import_to_load + grid_charge, with
    load import priced at peak and grid charge at off-peak, and grid_charge_cost the
    grid-charge slice of import_cost.  self_consumption is B-style (it includes the
    grid-charged discharge), so basis-C own-use = demand − import = sc − grid_charge.
    Defaults give per home: total_import_cost_gbp £258.00, of which
    total_grid_charge_cost_gbp £18.00; basis-C own-use 1800 kWh.  Every row imports
    at the same blended rate, £258.00 / 1,000 kWh = 0.258 £/kWh, which each
    tariff_rate row holds and the pricing records as the tariff's time-weighted
    rate, with no SEG.

    Hourly index with kW = kWh / n_steps, so calculate_summary, which integrates
    each row over the hour it lasts, returns the kWh totals and simulation_days is 365:
    the whole of 2021, which is not a leap year, so its totals are its year's.
    """
    idx = pd.date_range("2021-01-01", periods=n_steps, freq="1h", tz="Europe/London")

    def constant_kw(kwh: float) -> pd.Series:
        return pd.Series(kwh / n_steps, index=idx)

    def constant_gbp(pence: float) -> pd.Series:
        return pd.Series(pence / 100.0 / n_steps, index=idx)

    zeros = pd.Series(0.0, index=idx)
    grid_charge_pence = grid_charge_kwh * off_peak_pence
    import_pence = import_to_load_kwh * peak_pence + grid_charge_pence
    blended_rate_gbp_per_kwh = import_pence / (import_to_load_kwh + grid_charge_kwh) / 100.0
    return SimulationResults(
        generation=constant_kw(sc_kwh + export_kwh),
        demand=constant_kw(sc_kwh + import_to_load_kwh),
        self_consumption=constant_kw(sc_kwh),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=constant_kw(import_to_load_kwh + grid_charge_kwh),
        grid_export=constant_kw(export_kwh),
        import_cost=constant_gbp(import_pence),
        export_revenue=zeros.copy(),
        tariff_rate=pd.Series(blended_rate_gbp_per_kwh, index=idx),
        grid_charge_cost=constant_gbp(grid_charge_pence),
        pricing=RunPricing(blended_rate_gbp_per_kwh, None),
    )


class TestGridChargeEnergyPaidOnce:
    """H9 under basis C: each grid-charged kWh is paid once, by the householder, as import.

    Three observation points on one TOU + grid-charging fleet: the householder ledger
    (householder_bill import_cost_gbp), the CBS ledger (project_multi_year
    fleet_revenue_gbp) and the metered truth (calculate_summary total_import_cost_gbp).
    See docs/cost-recovery-finance-model.md §4.
    """

    N_HOMES = 2

    def _fleet(self) -> FleetResults:
        return make_fleet_results_of([_make_grid_charging_sim_results() for _ in range(self.N_HOMES)])

    @staticmethod
    def _without_grid_charge_cost_series(fleet: FleetResults) -> FleetResults:
        return FleetResults(
            per_home_results=[
                dataclasses.replace(r, grid_charge_cost=None) for r in fleet.per_home_results
            ],
            home_configs=fleet.home_configs,
        )

    @staticmethod
    def _householder_import_cost_gbp(
        summary: SummaryStatistics,
        finance: FinanceConfig,
    ) -> float:
        basis_c_own_use_kwh = summary.total_demand_kwh - summary.total_grid_import_kwh
        return householder_bill(
            summary, basis_c_own_use_kwh, finance
        ).import_cost_gbp

    @staticmethod
    def _cbs_revenue_at_age_0(
        fleet: FleetResults,
        scenario: ScenarioConfig,
        finance: FinanceConfig,
    ) -> float:
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)
        return curve.points[0].fleet_revenue_gbp

    def test_householder_import_cost_includes_grid_charging(self) -> None:
        """The householder pays the retailer for grid-charge energy inside import_cost_gbp.

        Pins which ledger bears the cost: the bill carries the full metered import cost,
        more than the builder's load-import-only £240 (800 kWh at 30p).
        """
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
