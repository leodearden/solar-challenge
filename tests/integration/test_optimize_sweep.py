# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for run_sweep + ConfigResult/RankedSweep (W3, task B/#65).

All tests are offline/fast — no PVGIS/network is touched.  An injected synthetic
simulate (constant or pv-varying FleetResults) stands in for the real fleet
simulator.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import (
    CostRecoverySolution,
    FinanceConfig,
    bill_distribution,
)
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.home import RunPricing, SimulationResults, calculate_summary
from solar_challenge.optimize import (
    ConfigPoint,
    ConfigResult,
    RankedSweep,
    enumerate_configs,
    pareto_baseline,
    run_sweep,
)
from solar_challenge.projection import (
    fewest_simulated_ages,
    project_economics,
    project_multi_year,
    scenario_fleet,
    solve_cost_recovery_rate,
)
from solar_challenge.pv import wired_dc_capacity_kw
from solar_challenge.scenario_knobs import KNOBS
from solar_challenge.seg import SEGTariff
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._factories import make_config_result, make_cost_recovery_solution
from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_scenario, make_sim_results
from tests._fleet_simulate_stand_in import answering_with
from tests._recording_simulate import recording
from tests._install_capex import fleet_wired_dc_kw, roof_battery_inverter_capex_gbp
from tests._projection_fleet_names import PROJECTION_AGES_OVER_25_YEARS


# ---------------------------------------------------------------------------
# Offline scaffolding: the finance builders, this module's pinned scenario and
# fleet results over tests/_finance_builders.py
# ---------------------------------------------------------------------------


def _make_fleet_results(n_homes: int = 5, seg_rate_pence_per_kwh: float | None = None) -> FleetResults:
    """*n_homes* default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year.

    Each home's export earns SEG income at *seg_rate_pence_per_kwh*, and no tariff prices its import.
    """
    return make_fleet_results(
        n_homes=n_homes,
        self_kwh=2000.0,
        export_kwh=800.0,
        import_kwh=1200.0,
        pricing=RunPricing(None, seg_rate_pence_per_kwh),
    )


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    asset_life_years: int = 25,
) -> FinanceConfig:
    return FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life_years,
        loan_term_years=min(asset_life_years, 15),
        own_use_rate_pence_per_kwh=own_use_rate_pence_per_kwh,
        retained_cash_floor_per_home_per_year_gbp=retained_cash_floor,
        retail_baseline_rate_pence_per_kwh=retail_baseline_rate,
        pv_cost_per_kwp_gbp=pv_cost_per_kwp_gbp,
        grant_gbp=grant_gbp,
        vat_rate=0.05,
    )


def _make_scenario(n_homes: int = 5, finance: FinanceConfig | None = None) -> ScenarioConfig:
    """make_scenario's *n_homes* default homes carrying *finance*, pinned to a 5 p/kWh scenario SEG rate."""
    return make_scenario(n_homes=n_homes, seg_tariff_pence_per_kwh=5.0, finance=finance)


def _interior_finance(n_homes: int = 5) -> FinanceConfig:
    """Finance params that produce an interior 'floor' solve."""
    return _make_finance(
        pv_cost_per_kwp_gbp=2000.0,
        grant_gbp=0.0,
        own_use_rate_pence_per_kwh=15.0,
        retained_cash_floor=100.0,
        retail_baseline_rate=30.0,
    )


# ---------------------------------------------------------------------------
# step-01/02 — TestConfigResult: frozen dataclass construction
# ---------------------------------------------------------------------------


class TestConfigResult:
    """ConfigResult frozen dataclass construction and validation."""

    def test_all_fields_read_back(self) -> None:
        """The stored fields read back, and the five solved fields read through the solution."""
        config = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        solution = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0,
            feasible=True,
            binding="floor",
            representative_outlay_gbp=400.0,
            net_surplus_per_home_per_year_gbp=100.0,
        )
        cr = ConfigResult(
            config=config,
            solution=solution,
            total_capex_gbp=10000.0,
            min_dscr=1.5,
            equity_irr=0.08,
            payback_years=12.0,
            baseline_own_use_rate_pence_per_kwh=15.0,
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=80.0,
        )

        assert cr.config is config
        assert cr.solution is solution
        assert cr.representative_outlay_gbp == solution.representative_outlay_gbp
        assert cr.solved_own_use_rate_pence_per_kwh == solution.own_use_rate_pence_per_kwh
        assert cr.surplus_at_solved_gbp == solution.net_surplus_per_home_per_year_gbp
        assert cr.feasible is solution.feasible
        assert cr.binding == solution.binding
        assert cr.total_capex_gbp == pytest.approx(10000.0)
        assert cr.min_dscr == pytest.approx(1.5)
        assert cr.equity_irr == pytest.approx(0.08)
        assert cr.payback_years == pytest.approx(12.0)
        assert cr.baseline_own_use_rate_pence_per_kwh == pytest.approx(15.0)
        assert cr.baseline_outlay_gbp == pytest.approx(450.0)
        assert cr.baseline_surplus_per_home_gbp == pytest.approx(80.0)

    def test_an_infeasible_solution_is_read_through(self) -> None:
        """Over an infeasible solution, feasible and binding are the solution's own."""
        cr = ConfigResult(
            config=ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6),
            solution=make_cost_recovery_solution(feasible=False, binding="infeasible_above_retail"),
            total_capex_gbp=10000.0,
            min_dscr=1.5,
            equity_irr=0.08,
            payback_years=12.0,
            baseline_own_use_rate_pence_per_kwh=15.0,
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=80.0,
        )
        assert cr.feasible is cr.solution.feasible is False
        assert cr.binding == "infeasible_above_retail"

    def test_payback_years_none_allowed(self) -> None:
        """payback_years=None is a valid sentinel (never pays back within asset life)."""
        cr = make_config_result(payback_years=None)
        assert cr.payback_years is None

    def test_min_dscr_inf_allowed(self) -> None:
        """min_dscr=inf is allowed (debt-free project)."""
        cr = make_config_result(min_dscr=float("inf"))
        assert math.isinf(cr.min_dscr)

    def test_equity_irr_nan_allowed(self) -> None:
        """equity_irr=nan is allowed (undefined IRR for zero-equity project)."""
        cr = make_config_result(equity_irr=float("nan"))
        assert math.isnan(cr.equity_irr)

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning a stored field raises dataclasses.FrozenInstanceError."""
        cr = make_config_result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cr.total_capex_gbp = 1.0  # type: ignore[misc]

    def test_config_point_accessible(self) -> None:
        """config.pv_kwp / battery_kwh / inverter_kw match the constructed values."""
        cr = make_config_result(pv_kwp=5.0, battery_kwh=10.0, inverter_kw=4.6)
        assert cr.config.pv_kwp == pytest.approx(5.0)
        assert cr.config.battery_kwh == pytest.approx(10.0)
        assert cr.config.inverter_kw == pytest.approx(4.6)

    def test_solution_field_accessible(self) -> None:
        """solution.own_use_rate_pence_per_kwh is readable through the ConfigResult."""
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=18.5, feasible=True, binding="floor", representative_outlay_gbp=400.0
        )

        cr = ConfigResult(
            config=ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6),
            solution=sol,
            total_capex_gbp=10000.0,
            min_dscr=1.5,
            equity_irr=0.08,
            payback_years=12.0,
            baseline_own_use_rate_pence_per_kwh=15.0,
            baseline_outlay_gbp=450.0,
            baseline_surplus_per_home_gbp=80.0,
        )
        assert cr.solution.own_use_rate_pence_per_kwh == pytest.approx(18.5)


# ---------------------------------------------------------------------------
# step-03/04 — TestRankedSweep: frozen dataclass construction
# ---------------------------------------------------------------------------


class TestRankedSweep:
    """RankedSweep frozen dataclass construction and validation."""

    def _make_one_feasible(self) -> ConfigResult:
        return make_config_result(
            pv_kwp=4.0,
            representative_outlay_gbp=400.0,
            surplus_at_solved_gbp=100.0,
        )

    def test_fields_read_back(self) -> None:
        """All fields read back after construction."""
        cr = self._make_one_feasible()
        infeasible_pt = ConfigPoint(pv_kwp=8.0, battery_kwh=10.0, inverter_kw=5.0)
        pareto_pt = cr.config

        rs = RankedSweep(
            results=(cr,),
            infeasible=(infeasible_pt,),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(pareto_pt,),
        )

        assert rs.results == (cr,)
        assert rs.infeasible == (infeasible_pt,)
        assert rs.retained_cash_floor_gbp == pytest.approx(100.0)
        assert rs.cheapest_feasible is cr.config
        assert rs.pareto_baseline == (pareto_pt,)

    def test_the_own_use_override_reads_back_and_defaults_to_none(self) -> None:
        """self_consumption_override reads back as built, and is None (simulated own-use) when not given."""
        cr = self._make_one_feasible()

        def built(**override: float) -> RankedSweep:
            return RankedSweep(
                results=(cr,),
                infeasible=(),
                retained_cash_floor_gbp=100.0,
                cheapest_feasible=cr.config,
                pareto_baseline=(),
                **override,
            )

        assert built(self_consumption_override=0.6).self_consumption_override == pytest.approx(0.6)
        assert built().self_consumption_override is None

    def test_cheapest_feasible_equals_results_0_config(self) -> None:
        """When results non-empty, cheapest_feasible must equal results[0].config."""
        cr = self._make_one_feasible()
        rs = RankedSweep(
            results=(cr,),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(),
        )
        assert rs.cheapest_feasible is rs.results[0].config

    def test_cheapest_feasible_none_when_results_empty(self) -> None:
        """When results is empty, cheapest_feasible must be None."""
        rs = RankedSweep(
            results=(),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=None,
            pareto_baseline=(),
        )
        assert rs.cheapest_feasible is None

    def test_cheapest_feasible_mismatch_raises_value_error(self) -> None:
        """cheapest_feasible != results[0].config raises ValueError."""
        cr = self._make_one_feasible()
        wrong = ConfigPoint(pv_kwp=99.0, battery_kwh=0.0, inverter_kw=99.0)
        with pytest.raises(ValueError):
            RankedSweep(
                results=(cr,),
                infeasible=(),
                retained_cash_floor_gbp=100.0,
                cheapest_feasible=wrong,
                pareto_baseline=(),
            )

    def test_frozen_raises_on_assignment(self) -> None:
        """Assigning any field raises dataclasses.FrozenInstanceError."""
        cr = self._make_one_feasible()
        rs = RankedSweep(
            results=(cr,),
            infeasible=(),
            retained_cash_floor_gbp=100.0,
            cheapest_feasible=cr.config,
            pareto_baseline=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rs.retained_cash_floor_gbp = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# step-05/06 — W-H1 seam: single config, run_sweep vs direct W2 primitives
# ---------------------------------------------------------------------------


class TestRunSweepSingleConfig:
    """W-H1 seam: single config numbers equal direct W2 primitive calls."""

    def _setup(self) -> tuple:  # type: ignore[type-arg]
        """Return (scenario, finance, fake_fr, simulate, configs)."""
        n_homes = 5
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = answering_with(fr)

        configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )
        return scenario, finance, fr, simulate, configs

    def test_solve_fields_match_direct_w2(self) -> None:
        """representative_outlay / solved_rate / surplus / feasible / binding == sol.*"""
        scenario, finance, fr, simulate, configs = self._setup()

        ranked = run_sweep(configs, simulate=simulate)
        assert len(ranked.results) == 1

        cr = ranked.results[0]

        # Direct W2 call for comparison: use configs[0][1] (the scenario after
        # enumerate_configs applied the install — homes may have been modified, e.g.
        # battery fabricated from battery_kwh=6.0 on homes that had no battery).
        # The finance block is preserved from the base scenario by enumerate_configs.
        sweep_scenario = configs[0][1]
        sol = solve_cost_recovery_rate(sweep_scenario, finance, simulate=simulate)

        assert cr.representative_outlay_gbp == pytest.approx(sol.representative_outlay_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(
            sol.own_use_rate_pence_per_kwh
        )
        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.feasible == sol.feasible
        assert cr.binding == sol.binding

    def test_solution_field_is_cost_recovery_solution(self) -> None:
        """result.solution is a CostRecoverySolution."""
        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert isinstance(ranked.results[0].solution, CostRecoverySolution)

    def test_baseline_econ_fields_match_direct_w2(self) -> None:
        """total_capex / min_dscr / equity_irr / payback_years match project_economics."""
        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        # Use configs[0][1] — the same scenario run_sweep uses (homes may differ
        # after the install knobs apply, e.g. battery fabricated).
        sweep_scenario = configs[0][1]
        curve = project_multi_year(sweep_scenario, finance, simulate=simulate)
        econ = project_economics(curve, scenario_fleet(sweep_scenario), finance)

        assert cr.baseline_surplus_per_home_gbp == pytest.approx(
            econ.net_surplus_per_home_per_year_gbp
        )
        assert cr.total_capex_gbp == pytest.approx(econ.total_capex_gbp)
        assert cr.min_dscr == pytest.approx(econ.min_dscr)
        # equity_irr and payback_years may be nan/None; check type equality
        if econ.payback_years is None:
            assert cr.payback_years is None
        else:
            assert cr.payback_years == pytest.approx(econ.payback_years)
        if math.isnan(econ.equity_irr):
            assert math.isnan(cr.equity_irr)
        else:
            assert cr.equity_irr == pytest.approx(econ.equity_irr)

    def test_a_3_kwp_configs_pv_capex_is_the_pv_dc_its_homes_wire(self) -> None:
        """A 3 kWp config's capex prices the 2.803 kWp its homes wire, not their 3 kWp nameplate."""
        finance = _interior_finance()
        configs = enumerate_configs(
            _make_scenario(n_homes=5, finance=finance), pv_kwp=[3.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        homes = configs[0][1].homes
        assert wired_dc_capacity_kw(homes[0].pv_config) == pytest.approx(2.803, abs=5e-4)

        ranked = run_sweep(configs, simulate=answering_with(_make_fleet_results(n_homes=5)))

        assert len(ranked.results) == 1, (
            f"the config must solve feasibly, as only ranked.results holds a ConfigResult; "
            f"infeasible: {ranked.infeasible!r}"
        )
        assert ranked.results[0].total_capex_gbp == pytest.approx(
            fleet_wired_dc_kw(homes) * finance.pv_cost_per_kwp_gbp + roof_battery_inverter_capex_gbp(homes, finance)
        )

    def test_baseline_outlay_matches_age0_bill_distribution(self) -> None:
        """baseline_outlay_gbp equals bill_distribution(...).representative.total_outlay_gbp
        from the age-0 simulation at the configured own-use rate."""
        scenario, finance, fr, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        # The fake simulate answers every fleet, whatever its age, with fr's
        # per-home results, so the age-0 baseline simulation bills fr's results.
        summaries = [calculate_summary(r) for r in fr.per_home_results]
        dist = bill_distribution(summaries, finance)
        expected_outlay = dist.representative.total_outlay_gbp

        assert cr.baseline_outlay_gbp == pytest.approx(expected_outlay)

    def test_the_projections_age0_fleet_is_simulated_over_the_scenario_bounds(self) -> None:
        """The calendar year 2024, a period other than make_period()'s 2021, reaches every fleet run_sweep simulates,
        the projection's age-0 fleet the baseline outlay bills included, as the swept scenario's simulation_bounds()."""
        finance = _interior_finance()
        scenario = dataclasses.replace(
            _make_scenario(finance=finance),
            period=SimulationWindow(date(2024, 1, 1), date(2024, 12, 31), ONE_MINUTE, "Europe/London"),
        )
        configs = enumerate_configs(scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6])
        asked: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
        answer = answering_with(_make_fleet_results())

        def recording_simulate(fc: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            asked.append((fc.name, start, end))
            return answer(fc, start, end)

        run_sweep(configs, simulate=recording_simulate)

        swept_scenario = configs[0][1]
        assert "proj-age-0" in [name for name, _, _ in asked]
        assert [(start, end) for _, start, end in asked] == [swept_scenario.simulation_bounds()] * len(asked)

    def test_cheapest_feasible_matches_config_point(self) -> None:
        """With one config, cheapest_feasible == that config's ConfigPoint."""
        _, _, _, simulate, configs = self._setup()
        ranked = run_sweep(configs, simulate=simulate)
        assert ranked.cheapest_feasible is ranked.results[0].config

    def test_every_fleet_it_simulates_exports_at_the_scenario_seg_rate(self) -> None:
        """The scenario's 5 p/kWh reaches each home of every fleet run_sweep simulates, the age-0
        fleet the baseline outlay bills included, though no home carries a tariff of its own."""
        _, _, fr, _, configs = self._setup()
        tariffs_simulated: list[SEGTariff | None] = []
        answer = answering_with(fr)

        def recording_simulate(fc: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            tariffs_simulated.extend(home.seg_tariff for home in fc.homes)
            return answer(fc, start, end)

        run_sweep(configs, simulate=recording_simulate)

        assert set(tariffs_simulated) == {SEGTariff(name="", rate_pence_per_kwh=5.0)}


# ---------------------------------------------------------------------------
# B10-B12 — one projection per config serves its solve, economics and baseline
# ---------------------------------------------------------------------------


def _results_at_battery_soh(soh: float, *, seg_rate_pence_per_kwh: float | None) -> SimulationResults:
    """A home's year with a battery at *soh*: it self-consumes 2,000 × *soh* kWh, exporting and importing the rest of 2,000 instead.

    It generates 2,800 kWh and demands 3,200 at every SOH, and its export earns SEG income at *seg_rate_pence_per_kwh*.
    """
    lost_kwh = 2000.0 * (1.0 - soh)
    return make_sim_results(
        self_kwh=2000.0 - lost_kwh,
        export_kwh=800.0 + lost_kwh,
        import_kwh=1200.0 + lost_kwh,
        pricing=RunPricing(None, seg_rate_pence_per_kwh),
    )


def _answering_by_battery_soh(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
    """A simulate answering each home with _results_at_battery_soh of its battery's resolved SOH (1.0 without one), at its own SEG rate."""
    return make_fleet_results_of(
        [
            _results_at_battery_soh(
                1.0 if home.battery_config is None else home.battery_config.resolved_soh,
                seg_rate_pence_per_kwh=None if home.seg_tariff is None else home.seg_tariff.rate_pence_per_kwh,
            )
            for home in fleet_config.homes
        ],
        homes=fleet_config.homes,
    )


def _six_year_battery_configs() -> list[tuple[ConfigPoint, ScenarioConfig]]:
    """One config of two homes whose 5 kWh batteries are 6 years old, at a 4.1 p/kWh scenario SEG rate and _interior_finance()."""
    scenario = make_scenario(
        n_homes=2,
        seg_tariff_pence_per_kwh=4.1,
        battery_config=BatteryConfig(capacity_kwh=5.0, system_age_years=6.0),
        finance=_interior_finance(),
    )
    return enumerate_configs(scenario, pv_kwp=[4.0], battery_kwh=[5.0], inverter_kw=[3.6])


class TestOneProjectionPerConfig:
    """Each config's one projection at the configured rate gives its rank fields, its baseline pair and its economics."""

    def test_a_config_asks_its_simulator_for_one_projection(self) -> None:
        """B10: at a 25-year life, the projection's seeds and first pass's midpoints, and nothing else."""
        finance = _interior_finance()
        configs = enumerate_configs(
            _make_scenario(finance=finance), pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        asked: list[str] = []
        answer = answering_with(_make_fleet_results())

        def recording_simulate(fc: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            asked.append(fc.name)
            return answer(fc, start, end)

        run_sweep(configs, simulate=recording_simulate)

        assert tuple(asked) == PROJECTION_AGES_OVER_25_YEARS
        assert len(asked) == fewest_simulated_ages(finance.asset_life_years)

    def test_an_aged_battery_configs_age_0_fleets_are_new_installs_at_the_scenario_seg_rate(self) -> None:
        """B11: a 6-year battery's age-0 fleets, the ones the baseline outlay bills, hold new batteries exporting at the scenario SEG rate."""
        configs = _six_year_battery_configs()
        asked: list[FleetConfig] = []
        answer = answering_with(_make_fleet_results(n_homes=2, seg_rate_pence_per_kwh=4.1))

        def recording_simulate(fc: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            asked.append(fc)
            return answer(fc, start, end)

        run_sweep(configs, simulate=recording_simulate)

        age0_fleets = [fc for fc in asked if all(home.pv_config.system_age_years == 0.0 for home in fc.homes)]
        assert age0_fleets
        for fleet_config in age0_fleets:
            assert [home.battery_config.soh for home in fleet_config.homes if home.battery_config] == [1.0, 1.0]
            assert {home.seg_tariff for home in fleet_config.homes} == {SEGTariff(name="", rate_pence_per_kwh=4.1)}

    def test_an_aged_battery_configs_baseline_outlay_bills_a_new_install(self) -> None:
        """B11: billed on what a stand-in answers by each home's battery SOH, the outlay is a new install's, not the 6-year battery's."""
        configs = _six_year_battery_configs()
        swept = configs[0][1]
        assert swept.finance is not None
        assert all(home.battery_config and home.battery_config.resolved_soh < 1.0 for home in swept.homes), (
            "premise: the swept homes' batteries are aged, so a fleet of them answers otherwise than a new install"
        )

        ranked = run_sweep(configs, simulate=_answering_by_battery_soh)

        assert ranked.results, f"the config must solve feasibly; infeasible: {ranked.infeasible!r}"
        new_install = _results_at_battery_soh(1.0, seg_rate_pence_per_kwh=4.1)
        expected = bill_distribution([calculate_summary(new_install)] * 2, swept.finance)
        assert ranked.results[0].baseline_outlay_gbp == pytest.approx(expected.representative.total_outlay_gbp)

    def test_the_baseline_pair_names_the_configured_own_use_rate(self) -> None:
        """B12: the rate the baseline outlay and surplus are priced at is the scenario's configured rate."""
        finance = dataclasses.replace(_interior_finance(), own_use_rate_pence_per_kwh=12.0)
        configs = enumerate_configs(
            _make_scenario(finance=finance), pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )

        ranked = run_sweep(configs, simulate=answering_with(_make_fleet_results()))

        assert ranked.results[0].baseline_own_use_rate_pence_per_kwh == 12.0


# ---------------------------------------------------------------------------
# step-07/08 — multi-config rank + feasibility + cheapest
# ---------------------------------------------------------------------------


class TestRunSweepMultiConfig:
    """Multi-config ranking: sorted by outlay, feasible/infeasible split, cheapest."""

    def _make_pv_varying_simulate(self) -> Callable[[FleetConfig, pd.Timestamp, pd.Timestamp], FleetResults]:
        """Return a simulate that scales self_kwh/export with fc.homes[0].pv_config.capacity_kw.

        Its results are paired with the homes of the fleet it is asked to simulate.
        """

        def simulate(fc: FleetConfig, s: pd.Timestamp, e: pd.Timestamp) -> FleetResults:
            cap = fc.homes[0].pv_config.capacity_kw
            # Larger PV → more self-consumption and export → lower cost-recovery rate
            # → lower outlay (but we want variance for ordering tests)
            self_kwh = 1500.0 * (cap / 4.0)
            export_kwh = 600.0 * (cap / 4.0)
            return make_fleet_results(
                homes=fc.homes,
                self_kwh=self_kwh,
                export_kwh=export_kwh,
                import_kwh=1200.0,
            )

        return simulate

    def _make_infeasible_finance(self) -> FinanceConfig:
        """Finance params that produce infeasible_above_retail at _interior_finance's floor: a PV capex no rate up to retail recovers."""
        return _make_finance(
            pv_cost_per_kwp_gbp=20000.0,
            grant_gbp=0.0,
            own_use_rate_pence_per_kwh=15.0,
            retained_cash_floor=_interior_finance().retained_cash_floor_per_home_per_year_gbp,
            retail_baseline_rate=30.0,
        )

    def test_results_sorted_ascending_by_outlay(self) -> None:
        """results is sorted ascending by representative_outlay_gbp."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario,
            pv_kwp=[3.0, 5.0],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )
        ranked = run_sweep(configs, simulate=simulate)

        outlays = [r.representative_outlay_gbp for r in ranked.results]
        assert outlays == sorted(outlays), "results must be sorted ascending by outlay"

    def test_all_results_feasible(self) -> None:
        """Every ConfigResult in results has feasible=True and binding!='infeasible_above_retail'."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        for r in ranked.results:
            assert r.feasible is True
            assert r.binding != "infeasible_above_retail"

    def test_cheapest_feasible_is_results_0_config(self) -> None:
        """cheapest_feasible == results[0].config when results non-empty."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        simulate = self._make_pv_varying_simulate()

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        assert ranked.cheapest_feasible is ranked.results[0].config

    def test_infeasible_config_in_infeasible_not_results(self) -> None:
        """Infeasible configs appear in ranked.infeasible (not results); count adds up."""
        n_homes = 3
        # Feasible finance for most configs
        feasible_finance = _interior_finance(n_homes)
        # Infeasible finance for one
        infeasible_finance = self._make_infeasible_finance()

        # Build two scenarios: one feasible, one infeasible
        feasible_scenario = _make_scenario(n_homes=n_homes, finance=feasible_finance)
        infeasible_scenario = _make_scenario(n_homes=n_homes, finance=infeasible_finance)

        feasible_configs = enumerate_configs(
            feasible_scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        infeasible_pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        infeasible_configs = [(infeasible_pt, infeasible_scenario)]

        # Combine: 1 feasible + 1 infeasible
        all_configs = feasible_configs + infeasible_configs
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = answering_with(fr)

        ranked = run_sweep(all_configs, simulate=simulate)

        assert len(ranked.results) + len(ranked.infeasible) == len(all_configs)
        assert all(r.feasible for r in ranked.results)
        # The infeasible config's point should appear in ranked.infeasible
        assert len(ranked.infeasible) >= 1


    def test_reported_pareto_front_matches_pareto_baseline_of_results(self) -> None:
        """ranked.pareto_baseline equals pareto_baseline() over all evaluated configs
        (results + infeasible)."""
        n_homes = 3
        finance = _interior_finance(n_homes)
        scenario = _make_scenario(n_homes=n_homes, finance=finance)
        fr = _make_fleet_results(n_homes=n_homes)
        simulate = answering_with(fr)

        configs = enumerate_configs(
            scenario, pv_kwp=[3.0, 5.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        ranked = run_sweep(configs, simulate=simulate)

        # pareto_baseline over all results (all feasible here) should match
        expected_pareto = pareto_baseline(list(ranked.results))
        assert set(ranked.pareto_baseline) == set(expected_pareto)


# ---------------------------------------------------------------------------
# The retained-cash floor has one setter: the scenario's finance field, set
# through its knob before enumerate_configs
# ---------------------------------------------------------------------------


class TestRetainedCashFloor:
    """run_sweep solves at the floor its configs' finance sets, which the floor knob sets on the base scenario."""

    def _setup(self, floor: float) -> tuple[FleetSimulate, list[tuple[ConfigPoint, ScenarioConfig]]]:
        """(simulate, configs): one config enumerated from the interior scenario with the floor knob applied at *floor*."""
        n_homes = 5
        scenario = KNOBS["retained_cash_floor_per_home_per_year_gbp"].apply(
            _make_scenario(n_homes=n_homes, finance=_interior_finance(n_homes)), floor
        )
        simulate = answering_with(_make_fleet_results(n_homes=n_homes))
        configs = enumerate_configs(scenario, pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6])
        return simulate, configs

    def test_the_sweep_echoes_its_configs_common_floor(self) -> None:
        simulate, configs = self._setup(120.0)
        ranked = run_sweep(configs, simulate=simulate)
        assert ranked.retained_cash_floor_gbp == pytest.approx(120.0)

    def test_a_floor_set_through_its_knob_reaches_the_solve(self) -> None:
        """The surplus and solved rate equal solve_cost_recovery_rate's on the knob-applied scenario and its finance."""
        simulate, configs = self._setup(120.0)
        ranked = run_sweep(configs, simulate=simulate)
        cr = ranked.results[0]

        sweep_scenario = configs[0][1]
        finance = sweep_scenario.finance
        assert finance is not None
        assert finance.retained_cash_floor_per_home_per_year_gbp == pytest.approx(120.0)
        sol = solve_cost_recovery_rate(sweep_scenario, finance, simulate=simulate)

        assert cr.surplus_at_solved_gbp == pytest.approx(sol.net_surplus_per_home_per_year_gbp)
        assert cr.solved_own_use_rate_pence_per_kwh == pytest.approx(sol.own_use_rate_pence_per_kwh)

    def test_the_floor_leaves_the_baseline_outlay_unchanged(self) -> None:
        """baseline_outlay_gbp is the same at two floors (the own-use rate stays the configured one)."""
        simulate, configs_low = self._setup(100.0)
        _, configs_high = self._setup(130.0)

        ranked_low = run_sweep(configs_low, simulate=simulate)
        ranked_high = run_sweep(configs_high, simulate=simulate)

        assert ranked_low.results[0].baseline_outlay_gbp == pytest.approx(
            ranked_high.results[0].baseline_outlay_gbp
        )

    def test_run_sweep_takes_no_floor_override(self) -> None:
        """The scenario's finance is the floor's one setter: run_sweep refuses a floor keyword at the call."""
        simulate, configs = self._setup(120.0)
        with pytest.raises(TypeError, match="retained_cash_floor_gbp"):
            run_sweep(configs, retained_cash_floor_gbp=60.0, simulate=simulate)


class TestOwnUseAssumption:
    """run_sweep records the own-use assumption, the self_consumption_override, its configs' finance shares."""

    def _ranked(self, finance: FinanceConfig) -> RankedSweep:
        """run_sweep of one config enumerated from the interior scenario carrying *finance*."""
        n_homes = 5
        configs = enumerate_configs(
            _make_scenario(n_homes=n_homes, finance=finance), pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6]
        )
        return run_sweep(configs, simulate=answering_with(_make_fleet_results(n_homes=n_homes)))

    def test_configs_on_simulated_own_use_record_no_override(self) -> None:
        assert self._ranked(_interior_finance()).self_consumption_override is None

    def test_configs_on_an_override_record_it(self) -> None:
        finance = dataclasses.replace(_interior_finance(), self_consumption_override=0.6)
        assert self._ranked(finance).self_consumption_override == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# step-15/16 — guards: TypeError for no simulator, ValueError for empty configs and None finance
# ---------------------------------------------------------------------------


class TestRunSweepGuards:
    """Guards: TypeError for a call passing no simulator, ValueError for empty configs and None finance."""

    def test_raises_value_error_on_empty_configs(self) -> None:
        """run_sweep raises ValueError when configs list is empty."""
        with pytest.raises(ValueError, match="(?i)empty|no config"):
            run_sweep([], simulate=answering_with(_make_fleet_results()))

    def test_raises_value_error_when_finance_is_none(self) -> None:
        """run_sweep raises ValueError when any scenario.finance is None."""
        n_homes = 3
        # Scenario with no finance block
        scenario_no_finance = _make_scenario(n_homes=n_homes, finance=None)
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        configs = [(pt, scenario_no_finance)]

        fr = _make_fleet_results(n_homes=n_homes)
        simulate = answering_with(fr)

        with pytest.raises(ValueError, match="(?i)finance"):
            run_sweep(configs, simulate=simulate)

    def test_a_call_without_simulate_raises_type_error_naming_simulate(self) -> None:
        """run_sweep runs only the simulator its caller passes: a call passing none is refused by name."""
        n_homes = 3
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        configs = [(pt, _make_scenario(n_homes=n_homes, finance=_interior_finance(n_homes=n_homes)))]

        with pytest.raises(TypeError, match="simulate"):
            run_sweep(configs)

    def test_configs_at_two_floors_are_refused_naming_both_before_any_simulation(self) -> None:
        """run_sweep solves every config at one retained-cash floor: configs at two are refused, naming both, unsimulated."""
        n_homes = 3
        configs = enumerate_configs(
            _make_scenario(n_homes=n_homes, finance=_make_finance(retained_cash_floor=15.0)),
            pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6],
        ) + enumerate_configs(
            _make_scenario(n_homes=n_homes, finance=_make_finance(retained_cash_floor=27.0)),
            pv_kwp=[5.0], battery_kwh=[6.0], inverter_kw=[3.6],
        )
        asked: list[FleetConfig] = []

        with pytest.raises(ValueError, match=r"15\.0.*27\.0"):
            run_sweep(configs, simulate=recording(asked, answering_with(_make_fleet_results(n_homes=n_homes))))
        assert asked == []

    def test_configs_on_two_own_use_assumptions_are_refused_naming_both_before_any_simulation(self) -> None:
        """run_sweep solves every config on one own-use assumption: configs on two are refused, naming both, unsimulated."""
        n_homes = 3
        configs = enumerate_configs(
            _make_scenario(n_homes=n_homes, finance=_make_finance()),
            pv_kwp=[4.0], battery_kwh=[6.0], inverter_kw=[3.6],
        ) + enumerate_configs(
            _make_scenario(n_homes=n_homes, finance=dataclasses.replace(_make_finance(), self_consumption_override=0.6)),
            pv_kwp=[5.0], battery_kwh=[6.0], inverter_kw=[3.6],
        )
        asked: list[FleetConfig] = []

        with pytest.raises(ValueError, match=r"None.*0\.6"):
            run_sweep(configs, simulate=recording(asked, answering_with(_make_fleet_results(n_homes=n_homes))))
        assert asked == []


# ---------------------------------------------------------------------------
# Amendment tests — coverage gaps surfaced by code review
# ---------------------------------------------------------------------------


class TestRunSweepRateClampedZero:
    """run_sweep ranks a config whose cost-recovery rate clamps at zero as feasible."""

    def test_rate_clamped_zero_config_lands_in_results(self) -> None:
        """A config whose cost-recovery solve clamps the rate at 0 is feasible, so
        run_sweep ranks it in results and reports nothing infeasible.

        The grant covers the capex and each home's SEG income beats its share of
        opex plus the retained-cash floor, so the surplus clears the floor at 0 p/kWh.
        """
        finance = _make_finance(
            pv_cost_per_kwp_gbp=200.0,
            grant_gbp=50000.0,
            retained_cash_floor=10.0,
            retail_baseline_rate=30.0,
        )
        scenario = _make_scenario(n_homes=5, finance=finance)
        fr = _make_fleet_results(n_homes=5, seg_rate_pence_per_kwh=25.0)  # £200 a home on 800 kWh
        configs = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
        )

        ranked = run_sweep(configs, simulate=answering_with(fr))

        assert [r.binding for r in ranked.results] == ["rate_clamped_zero"]
        assert ranked.results[0].solved_own_use_rate_pence_per_kwh == pytest.approx(0.0)
        assert ranked.infeasible == ()
        assert ranked.cheapest_feasible is ranked.results[0].config
