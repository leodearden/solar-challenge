# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's curve shape, fleet energy aggregation,
its refusal of a simulated age whose aggregates are not all finite, and its
refusal of a call that passes no simulator; and for project_fleet, the
projection of a resolved fleet with its age-0 summaries and the grid-services
income it booked at each simulated age.

The projection runs on an injected synthetic simulate, with no PVGIS or network.
"""
from __future__ import annotations

import dataclasses
import math
import warnings
from typing import Callable

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.gridservices import GridServicesEventsConfig
from solar_challenge.home import calculate_summary
from solar_challenge.projection import (
    FleetProjection,
    MultiYearCurve,
    project_fleet,
    project_multi_year,
    scenario_fleet,
)
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_scenario_and_finance,
    make_sim_results,
)


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_billed_own_use_at_sampled_age(self) -> None:
        """fleet_billed_own_use_kwh at a sampled age is the fleet's basis-C own-use, the sum of demand - import."""
        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

        summaries = [calculate_summary(r) for r in fr.per_home_results]
        expected_own_use = sum(s.total_demand_kwh - s.total_grid_import_kwh for s in summaries)

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)

        # At age 0 (a seed point), the value should match the injected summary
        assert curve.points[0].fleet_billed_own_use_kwh == pytest.approx(
            expected_own_use, rel=1e-4
        )

    def test_fleet_export_at_sampled_age(self) -> None:
        """fleet_export_kwh at a sampled age equals sum of per-home totals."""
        n_homes = 2
        exp_per_home = 500.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, export_kwh=exp_per_home)

        expected_export = sum(
            calculate_summary(r).total_grid_export_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_export_kwh == pytest.approx(expected_export, rel=1e-4)

    def test_fleet_import_at_sampled_age(self) -> None:
        """fleet_import_kwh at a sampled age equals sum of per-home totals."""
        n_homes = 2
        imp_per_home = 200.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, import_kwh=imp_per_home)

        expected_import = sum(
            calculate_summary(r).total_grid_import_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_import_kwh == pytest.approx(expected_import, rel=1e-4)


class TestProjectMultiYearRequiresASimulator:
    """project_multi_year runs only the simulator its caller passes, never one of its own."""

    def test_a_call_without_simulate_raises_type_error_naming_simulate(self) -> None:
        """A call that passes no simulator is refused by name, and no fleet is simulated."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)

        with pytest.raises(TypeError, match="simulate"):
            project_multi_year(scenario, finance)


_L1_REFUSAL = "HomeLedger L1: every figure is finite and >= 0: got "
"""How a home's ledger begins its refusal of a figure that is negative or not finite."""

_INFINITE_IMPORT_REFUSED = "demand_kwh=inf, own_use_kwh=nan, import_kwh=inf, import_cost_gbp=inf"
"""What an untariffed home's ledger refuses for an infinite import.

Demand counts the import, so it is infinite too; basis-C own-use, demand −
import, is inf − inf = NaN; and the import is priced at the retail rate.
"""


class TestProjectMultiYearRefusesNonFiniteAggregates:
    """A simulated age whose figures are not all finite is refused, unless a home's summary has already refused its totals.

    A home's own-use, export or import is refused by the home's ledger (L1),
    naming each figure it refuses.  Every other aggregate, a home's battery
    discharge among them, is refused by the age's own check, which names the
    age and each such aggregate with its value.
    """

    @pytest.mark.parametrize("asset_life_years", [1, 25])
    @pytest.mark.parametrize(
        ("totals", "refused"),
        [
            pytest.param(
                {"self_kwh": math.inf},
                "generation_kwh=inf, demand_kwh=inf, own_use_kwh=inf",
                id="infinite-self-consumption",
            ),
            pytest.param({"export_kwh": math.inf}, "generation_kwh=inf, export_kwh=inf", id="infinite-export"),
            pytest.param({"import_kwh": math.inf}, _INFINITE_IMPORT_REFUSED, id="infinite-import-makes-own-use-nan"),
        ],
    )
    def test_a_non_finite_ledger_figure_at_a_seed_age_is_refused_by_the_homes_ledger(
        self, asset_life_years: int, totals: dict[str, float], refused: str
    ) -> None:
        """A fleet whose totals are infinite at every age is refused at age 0, the first seed.

        Generation counts the self-consumption and the export, and demand the
        self-consumption and the import, so each is infinite beside them.  An
        infinite export leaves the SEG income finite: the fleet's results record
        no SEG rate, so it earns £0.
        """
        scenario, finance = make_scenario_and_finance(asset_life_years=asset_life_years)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(
                scenario, finance, simulate=lambda fc, s, e: make_fleet_results(homes=fc.homes, **totals)
            )

        assert str(exc_info.value) == _L1_REFUSAL + refused

    def test_a_non_finite_ledger_figure_at_a_bisection_trial_age_is_refused(self) -> None:
        """A fleet that is finite at the seeds 0, 12 and 24 is refused at age 6, the adaptive loop's first trial.

        A NaN trial's deviation is never above the error target, and max() drops
        it from the error estimate, so unrefused it would vanish from the bisection
        and the projection would return a curve built from the finite seeds.  Only
        age 6's fleet imports without bound, so its homes' ledgers are what refuse.
        """
        scenario, finance = make_scenario_and_finance(asset_life_years=25)

        def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            age = fleet_config.homes[0].pv_config.system_age_years
            return make_fleet_results(homes=fleet_config.homes, import_kwh=math.inf if age == 6.0 else 12.0)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(scenario, finance, simulate=simulate)

        assert str(exc_info.value) == _L1_REFUSAL + _INFINITE_IMPORT_REFUSED

    @pytest.mark.parametrize("asset_life_years", [1, 25])
    def test_a_non_finite_battery_discharge_is_refused_naming_its_home(self, asset_life_years: int) -> None:
        """A home whose battery discharge is infinite is refused at age 0, by its place in the fleet.

        Only the discharge series changes, so demand, own-use and revenue stay
        finite and no UserWarning fires. The discharge is -inf because a +inf
        one is more than the self-consumption that counts it, which the home's
        summary refuses before finance can name the home.
        """
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=asset_life_years)
        finite = make_sim_results()
        infinite_discharge = dataclasses.replace(finite, battery_discharge=finite.battery_discharge - math.inf)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(
                scenario,
                finance,
                simulate=lambda fc, s, e: make_fleet_results_of([finite, infinite_discharge], homes=fc.homes),
            )

        assert str(exc_info.value) == (
            "every aggregate of the fleet simulated at age 0 must be finite: got per_home_discharge[1]=-inf"
        )

    @pytest.mark.parametrize("asset_life_years", [1, 25])
    def test_an_infinite_battery_discharge_above_its_self_consumption_is_refused_by_its_summary(
        self, asset_life_years: int
    ) -> None:
        """A home whose battery discharge is +inf is refused as its summary is built, naming both totals.

        The discharge is more than the self-consumption that counts it, so
        SummaryStatistics refuses it before finance's own check of the fleet's
        aggregates, which names the home, runs.
        """
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=asset_life_years)
        finite = make_sim_results()
        infinite_discharge = dataclasses.replace(finite, battery_discharge=finite.battery_discharge + math.inf)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(
                scenario,
                finance,
                simulate=lambda fc, s, e: make_fleet_results_of([finite, infinite_discharge], homes=fc.homes),
            )

        self_consumption_kwh = calculate_summary(finite).total_self_consumption_kwh
        message = str(exc_info.value)
        assert "total_battery_discharge_kwh is a part of total_self_consumption_kwh" in message
        assert message.endswith(
            f"got total_battery_discharge_kwh=inf, total_self_consumption_kwh={self_consumption_kwh!r}"
        )


_OWN_USE_OF_EACH_HOME_AT_AGE_0_KWH = (2_000.0, 1_000.0)
"""Each home's own-use at age 0, in fleet order: unequal, so the order of the age-0 summaries shows."""


def _declining_two_home_simulate(curvature: float) -> tuple[FleetSimulate, list[FleetResults]]:
    """A simulate whose two homes' own-use falls as exp(-curvature × age), and the FleetResults it returns at age 0.

    Each answer pairs the asked homes with their results, as FleetRunner.simulate does.
    """
    age0_results: list[FleetResults] = []

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        age = fleet_config.homes[0].pv_config.system_age_years
        factor = math.exp(-curvature * age)
        results = make_fleet_results_of(
            [make_sim_results(self_kwh=own_use * factor) for own_use in _OWN_USE_OF_EACH_HOME_AT_AGE_0_KWH],
            homes=fleet_config.homes,
        )
        if age == 0.0:
            age0_results.append(results)
        return results

    return simulate, age0_results


def _curve_of_project_fleet(
    scenario: ScenarioConfig, finance: FinanceConfig, *, simulate: FleetSimulate, error_target_pct: float
) -> MultiYearCurve:
    return project_fleet(scenario_fleet(scenario), finance, simulate=simulate, error_target_pct=error_target_pct).curve


_ENTRY_POINTS = [
    pytest.param(_curve_of_project_fleet, id="project_fleet"),
    pytest.param(project_multi_year, id="project_multi_year"),
]


class TestProjectFleet:
    """project_fleet projects a resolved fleet, giving project_multi_year's curve and the fleet's age-0 summaries."""

    def test_its_curve_is_project_multi_year_of_the_scenario(self) -> None:
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=25)
        simulate, _ = _declining_two_home_simulate(curvature=0.02)

        projection = project_fleet(scenario_fleet(scenario), finance, simulate=simulate)

        assert isinstance(projection, FleetProjection)
        assert projection.curve == project_multi_year(scenario, finance, simulate=simulate)

    def test_its_age0_summaries_are_each_homes_summary_of_the_age0_fleet_in_fleet_order(self) -> None:
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=25)
        simulate, age0_results = _declining_two_home_simulate(curvature=0.02)

        projection = project_fleet(scenario_fleet(scenario), finance, simulate=simulate)

        (age0_fleet,) = age0_results
        assert projection.age0_summaries == tuple(calculate_summary(r) for r in age0_fleet.per_home_results)
        assert [s.total_self_consumption_kwh for s in projection.age0_summaries] == pytest.approx(
            list(_OWN_USE_OF_EACH_HOME_AT_AGE_0_KWH)
        )

    def test_a_call_without_simulate_raises_type_error_naming_simulate(self) -> None:
        scenario, finance = make_scenario_and_finance(asset_life_years=5)

        with pytest.raises(TypeError, match="simulate"):
            project_fleet(scenario_fleet(scenario), finance)

    def test_simulate_and_the_error_target_are_keyword_only(self) -> None:
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=5)
        simulate, _ = _declining_two_home_simulate(curvature=0.02)
        fleet = scenario_fleet(scenario)

        with pytest.raises(TypeError):
            project_fleet(fleet, finance, simulate)
        with pytest.raises(TypeError):
            project_fleet(fleet, finance, 1.0, simulate=simulate)

    @pytest.mark.parametrize("project", _ENTRY_POINTS)
    def test_a_capped_projection_warns_its_callers_file_once(self, project: Callable[..., MultiYearCurve]) -> None:
        """An unreachable error target caps the bisection at MAX_NODES, and the one warning names this file."""
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=25)
        simulate, _ = _declining_two_home_simulate(curvature=0.35)

        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            project(scenario, finance, simulate=simulate, error_target_pct=1e-9)

        capped = [w for w in raised if issubclass(w.category, UserWarning) and "MAX_NODES" in str(w.message)]
        assert len(capped) == 1, [str(w.message) for w in raised]
        assert capped[0].filename == __file__

    def test_a_projection_is_frozen(self) -> None:
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=5)
        simulate, _ = _declining_two_home_simulate(curvature=0.02)
        projection = project_fleet(scenario_fleet(scenario), finance, simulate=simulate)

        with pytest.raises(dataclasses.FrozenInstanceError):
            projection.age0_summaries = ()


def _spare_battery_simulate() -> tuple[FleetSimulate, dict[int, FleetResults]]:
    """A simulate whose every battery holds 0.8 of its usable capacity all year, and each FleetResults it returned, by age.

    The batteries never discharge, so each home's operational spare capacity at
    events is (SOC - floor) / event hours, which falls with the battery's state
    of health.  Each answer pairs the asked homes with their results, as
    FleetRunner.simulate does.
    """
    answered: dict[int, FleetResults] = {}

    def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        results = []
        for home in fleet_config.homes:
            sim = make_sim_results()
            battery = home.battery_config
            assert battery is not None
            soc_kwh = 0.8 * battery.capacity_kwh * battery.resolved_soh
            results.append(dataclasses.replace(sim, battery_soc=pd.Series(soc_kwh, index=sim.battery_soc.index)))
        fleet_results = make_fleet_results_of(results, homes=fleet_config.homes)
        answered[int(fleet_config.homes[0].pv_config.system_age_years)] = fleet_results
        return fleet_results

    return simulate, answered


_EVENTS_PRICING = GridServicesEventsConfig()


def _projection_priced_at_events() -> tuple[FleetProjection, dict[int, FleetResults]]:
    """project_fleet of two 5 kWh battery homes over 25 years priced at events, and each FleetResults it simulated, by age."""
    scenario, finance = make_scenario_and_finance(
        n_homes=2, asset_life_years=25, battery_config=BatteryConfig(capacity_kwh=5.0)
    )
    finance = dataclasses.replace(
        finance, grid_services_model="capacity_at_events", grid_services_events=_EVENTS_PRICING
    )
    simulate, answered = _spare_battery_simulate()
    return project_fleet(scenario_fleet(scenario), finance, simulate=simulate), answered


class TestFleetProjectionGridServicesIncome:
    """FleetProjection.grid_services_income_gbp is the grid-services income the projection priced at each simulated age (B13)."""

    def test_it_holds_one_entry_per_simulated_age_ascending_from_the_seeds(self) -> None:
        projection, answered = _projection_priced_at_events()

        ages = [age for age, _ in projection.grid_services_income_gbp]

        assert ages == sorted(answered)
        assert {0, 12, 24} <= set(ages)

    def test_each_entry_is_the_pricing_of_that_ages_simulated_fleet(self) -> None:
        projection, answered = _projection_priced_at_events()

        for age, income in projection.grid_services_income_gbp:
            assert income == _EVENTS_PRICING.annual_income_gbp(answered[age]), age
        assert projection.grid_services_income_gbp[0] == (0, _EVENTS_PRICING.annual_income_gbp(answered[0]))

    def test_the_income_falls_with_the_batteries_state_of_health(self) -> None:
        projection, _ = _projection_priced_at_events()

        (first_age, first_income), (last_age, last_income) = (
            projection.grid_services_income_gbp[0],
            projection.grid_services_income_gbp[-1],
        )

        assert (first_age, last_age) == (0, 24)
        assert last_income < first_income

    @pytest.mark.parametrize(
        ("broken", "rule"),
        [
            pytest.param(lambda series: (), "must be non-empty", id="empty"),
            pytest.param(lambda series: (*series[:2], *series[1:]), "strictly ascending", id="repeated-age"),
            pytest.param(lambda series: (series[0], series[2], series[1], *series[3:]), "strictly ascending", id="unordered"),
            pytest.param(lambda series: series[1:], "first age must be 0", id="first-not-0"),
            pytest.param(lambda series: series[:-1], "last age must be 24", id="last-not-the-curves"),
            pytest.param(
                lambda series: tuple(entry for entry in series if entry[0] != 12), "every sampled age", id="missing-12"
            ),
            pytest.param(lambda series: _with_middle_income(series, -0.5), "finite and >= 0", id="negative"),
            pytest.param(lambda series: _with_middle_income(series, math.nan), "finite and >= 0", id="nan"),
            pytest.param(lambda series: _with_middle_income(series, math.inf), "finite and >= 0", id="infinite"),
        ],
    )
    def test_a_projection_refuses_a_series_its_curve_cannot_label(
        self, broken: Callable[[tuple[tuple[int, float], ...]], tuple[tuple[int, float], ...]], rule: str
    ) -> None:
        projection, _ = _projection_priced_at_events()
        assert 12 in projection.curve.sampled_ages
        series = broken(projection.grid_services_income_gbp)

        with pytest.raises(ValueError) as refused:
            dataclasses.replace(projection, grid_services_income_gbp=series)

        assert rule in str(refused.value)
        assert repr(series) in str(refused.value)


def _with_middle_income(series: tuple[tuple[int, float], ...], income: float) -> tuple[tuple[int, float], ...]:
    """*series* with its middle entry's income replaced by *income*."""
    middle = len(series) // 2
    return (*series[:middle], (series[middle][0], income), *series[middle + 1 :])
