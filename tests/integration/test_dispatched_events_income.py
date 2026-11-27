# SPDX-License-Identifier: AGPL-3.0-or-later
"""A dispatched fleet's events income, end to end: `finance run` prices the delivery metered from its own enrolled run.

docs/prds/event-dispatch-and-battery-sizing.md's signal, B11 and B12, on the real engine. The
scenario is two Economy 7 battery homes and a PV-only home over a sunless winter week, so every
kWh the fleet exports is battery export. `finance run` on its dispatched configuration renders the
metered rows. It refuses a fleet whose homes were not enrolled. The enrolled run's bills carry the
import its events caused. Each projection age is priced from its own aged, enrolled run.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.finance import (
    BillBreakdown,
    FinanceConfig,
    OwnUseBasis,
    basis_c_own_use_kwh,
    householder_bill,
    with_own_use_basis,
)
from solar_challenge.fleet import FleetConfig, FleetResults, FleetRunner, default_runner
from solar_challenge.gridservices import (
    EventWindow,
    GridServicesEventsConfig,
    compute_grid_services_at_events,
    drawn_event_days,
    enrolled_event_windows,
)
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.projection import project_fleet, scenario_fleet
from solar_challenge.weather import WeatherCache
from tests._calendar_dates import every_date
from tests._cli_fleet_simulator import answering, invoke_cli, invoke_finance_run
from tests._finance_builders import make_fleet_results_of, make_sim_results
from tests._markdown_tables import row_cells
from tests._synthetic_weather import sunless_tmy

_FIRST_DAY = date(2024, 1, 15)
_LAST_DAY = date(2024, 1, 19)
_EVENT_WINDOW = EventWindow(
    months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), events_per_year=35, event_hours=3.0
)
"""35 events over 2024's 87 eligible days: over the scenario's five weekdays, 35 × 5/87 draws 2."""
_EVENT_DAY_SEED = 5
_SEG_PENCE_PER_KWH = 15.0
_WINDOW_HEADING = "### This window's fleet, the same under every assumption"
_BATTERY_HOMES = ("battery-5", "battery-8")


def _battery_home(name: str, capacity_kwh: float) -> dict[str, Any]:
    """A battery home on Economy 7 that grid-charges overnight and holds its charge for a 16:00 to 20:00 peak."""
    return {
        "name": name,
        "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
        "battery": {
            "capacity_kwh": capacity_kwh,
            "max_charge_kw": 2.5,
            "max_discharge_kw": 2.5,
            "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 20]]},
            "grid_charging": {"target_soc_fraction": 0.9},
        },
        "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        "tariff": {"type": "economy_7"},
    }


def _document(participation: str, delivery_baseline: str) -> dict[str, Any]:
    """The scenario, its events priced at capacity at events under *participation* and *delivery_baseline*."""
    events = {
        "type": "capacity_at_events",
        "event_day_seed": _EVENT_DAY_SEED,
        "participation": participation,
        "delivery_baseline": delivery_baseline,
        "event_windows": [
            {
                "months": list(_EVENT_WINDOW.months),
                "weekdays": list(_EVENT_WINDOW.weekdays),
                "hours": list(_EVENT_WINDOW.hours),
                "events_per_year": _EVENT_WINDOW.events_per_year,
                "event_hours": _EVENT_WINDOW.event_hours,
            }
        ],
    }
    return {
        "name": f"Dispatched events income ({participation}, {delivery_baseline})",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
            "altitude": 11.0,
            "name": "Bristol, UK",
        },
        "period": {"start_date": _FIRST_DAY.isoformat(), "end_date": _LAST_DAY.isoformat()},
        "homes": [
            _battery_home("battery-5", 5.0),
            _battery_home("battery-8", 8.0),
            {
                "name": "pv-only",
                "pv": {"capacity_kw": 3.0, "azimuth": 180, "tilt": 35},
                "load": {"annual_consumption_kwh": 2800, "use_stochastic": False},
            },
        ],
        "seg": {"rate_pence_per_kwh": _SEG_PENCE_PER_KWH},
        "finance": {"standing_charge_pence_per_day": 60.0, "grid_services_model": events},
    }


def _scenario_file(
    tmp_path: Path, weather_cache: WeatherCache, participation: str, delivery_baseline: str = "operational"
) -> Path:
    """The scenario under *participation* and *delivery_baseline*, written under *tmp_path*, with its location's sunless TMY in *weather_cache*."""
    path = tmp_path / f"events-{participation}-{delivery_baseline}.yaml"
    path.write_text(yaml.safe_dump(_document(participation, delivery_baseline)), encoding="utf-8")
    weather_cache.put(sunless_tmy(temp_air=5.0), "tmy", load_scenario(path).get_location())
    return path


def _pricing(scenario: ScenarioConfig) -> GridServicesEventsConfig:
    """*scenario*'s events pricing."""
    assert scenario.finance is not None
    pricing = scenario.finance.grid_services_model
    assert isinstance(pricing, GridServicesEventsConfig)
    return pricing


def _finance(scenario: ScenarioConfig) -> FinanceConfig:
    """*scenario*'s finance."""
    assert scenario.finance is not None
    return scenario.finance


def _engine() -> FleetRunner:
    """The default runner, running its homes in turn in this process."""
    return dataclasses.replace(default_runner(), parallel=False)


def _simulated(scenario: ScenarioConfig) -> FleetResults:
    """*scenario*'s homes, enrolled as its participation enrols them, simulated over its period by the engine."""
    fleet = scenario_fleet(scenario)
    return _engine().simulate(FleetConfig(homes=fleet.homes, name=scenario.name), fleet.start, fleet.end)


def _drawn_days() -> tuple[date, ...]:
    """The scenario's drawn event days."""
    return drawn_event_days(_EVENT_WINDOW, every_date(_FIRST_DAY, _LAST_DAY), _EVENT_DAY_SEED, position=0)


def _at(day: date, hour: int) -> pd.Timestamp:
    """*day*'s *hour* o'clock in Bristol."""
    return pd.Timestamp(day.isoformat(), tz="Europe/London") + pd.Timedelta(hours=hour)


def _results_named(fleet_results: FleetResults, name: str) -> SimulationResults:
    """The results of *fleet_results*' home named *name*."""
    (results,) = [
        sim for sim, home in zip(fleet_results.per_home_results, fleet_results.home_configs) if home.name == name
    ]
    return results


def _physics_bill(results: SimulationResults, finance: FinanceConfig) -> BillBreakdown:
    """*results*' householder bill on the physics basis."""
    summary = calculate_summary(results)
    return householder_bill(summary, basis_c_own_use_kwh(summary), with_own_use_basis(finance, OwnUseBasis.SIMULATED))


def test_the_scenario_draws_some_but_not_all_of_its_days() -> None:
    assert 0 < len(_drawn_days()) < len(every_date(_FIRST_DAY, _LAST_DAY))


def test_finance_run_on_a_dispatched_scenario_prices_the_delivery_metered_from_its_enrolled_run(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    path = _scenario_file(tmp_path, weather_cache, "dispatched")
    engine = _engine()
    priced: list[FleetResults] = []

    def simulate(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        results = engine.simulate(fleet, start, end)
        priced.append(results)
        return results

    result = invoke_cli(["finance", "run", str(path)], answering(simulate))

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert (
        "Model: **capacity at events, central band, operational delivery baseline, dispatched participation**" in lines
    ), result.output
    breakdown = compute_grid_services_at_events(priced[0], _pricing(load_scenario(path)))
    assert row_cells(result.output, _WINDOW_HEADING, "Annual fleet income") == [f"£{breakdown.annual_income_gbp:,.0f}"]
    for label, figure in (
        ("Per-event metered delivery", breakdown.per_window_avail_kw),
        ("Delivery on 50% of event days", breakdown.per_window_avail_p50_kw),
        ("Delivery on 90% of event days", breakdown.per_window_avail_p90_kw),
    ):
        assert row_cells(result.output, _WINDOW_HEADING, label) == [f"{figure[0]:.1f} kW"], label
    (export_kwh,) = breakdown.per_window_battery_export_kwh_per_event
    assert export_kwh > 0
    assert row_cells(result.output, _WINDOW_HEADING, "Battery export per event") == [f"{export_kwh:.1f} kWh"]
    assert "Physics bills include the import the events caused" in result.output


def test_finance_run_refuses_a_dispatched_scenario_whose_fleet_was_not_enrolled(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    path = _scenario_file(tmp_path, weather_cache, "dispatched")
    stored_homes = load_scenario(path).homes
    assert any(home.battery_config is not None for home in stored_homes)
    un_enrolled = make_fleet_results_of(
        [make_sim_results(days=5, first_day=_FIRST_DAY) for _ in stored_homes], homes=stored_homes
    )

    result = invoke_finance_run([str(path)], un_enrolled)

    assert result.exit_code == 1, result.output
    assert "Configuration error:" in result.output
    assert "dispatched" in result.output


@pytest.fixture
def enrolled_and_observed(
    tmp_path: Path, weather_cache: WeatherCache
) -> tuple[ScenarioConfig, FleetResults, FleetResults]:
    """The dispatched scenario, and its enrolled and its observed twin's fleet each simulated by the engine."""
    dispatched = load_scenario(_scenario_file(tmp_path, weather_cache, "dispatched"))
    observed = load_scenario(_scenario_file(tmp_path, weather_cache, "observed"))
    return dispatched, _simulated(dispatched), _simulated(observed)


class TestTheEnrolledRunsBillsHoldTheImportItsEventsCaused:
    """B11: the enrolled fleet imports more after each event than its observed twin, and its bills show it."""

    def test_after_each_drawn_days_window_the_enrolled_fleet_imports_at_a_higher_cost_until_the_next_days_window(
        self, enrolled_and_observed: tuple[ScenarioConfig, FleetResults, FleetResults]
    ) -> None:
        _, enrolled, observed = enrolled_and_observed
        window_end, window_start = max(_EVENT_WINDOW.hours) + 1, min(_EVENT_WINDOW.hours)
        for day in _drawn_days():
            next_window = _at(day + timedelta(days=1), window_start)
            after_the_event = slice(_at(day, window_end), next_window - pd.Timedelta(minutes=1))
            enrolled_cost = sum(sim.import_cost.loc[after_the_event].sum() for sim in enrolled.per_home_results)
            observed_cost = sum(sim.import_cost.loc[after_the_event].sum() for sim in observed.per_home_results)
            assert enrolled_cost > observed_cost, (day, enrolled_cost, observed_cost)

    def test_before_the_first_drawn_days_window_both_runs_import_at_the_same_cost(
        self, enrolled_and_observed: tuple[ScenarioConfig, FleetResults, FleetResults]
    ) -> None:
        _, enrolled, observed = enrolled_and_observed
        first_event = _at(min(_drawn_days()), min(_EVENT_WINDOW.hours))
        for enrolled_sim, observed_sim in zip(enrolled.per_home_results, observed.per_home_results, strict=True):
            before = enrolled_sim.import_cost.index < first_event
            pd.testing.assert_series_equal(enrolled_sim.import_cost[before], observed_sim.import_cost[before])

    @pytest.mark.parametrize("name", _BATTERY_HOMES)
    def test_each_battery_homes_bill_carries_its_extra_import_cost_annualised(
        self, enrolled_and_observed: tuple[ScenarioConfig, FleetResults, FleetResults], name: str
    ) -> None:
        scenario, enrolled, observed = enrolled_and_observed
        enrolled_sim, observed_sim = _results_named(enrolled, name), _results_named(observed, name)
        extra_window_cost = enrolled_sim.import_cost.sum() - observed_sim.import_cost.sum()

        extra_bill = (
            _physics_bill(enrolled_sim, _finance(scenario)).import_cost_gbp
            - _physics_bill(observed_sim, _finance(scenario)).import_cost_gbp
        )

        assert extra_bill > 0
        assert extra_bill == pytest.approx(extra_window_cost * scenario.window().annualisation_scale, rel=1e-9)

    def test_the_pv_only_homes_bill_is_the_same_in_both_runs(
        self, enrolled_and_observed: tuple[ScenarioConfig, FleetResults, FleetResults]
    ) -> None:
        scenario, enrolled, observed = enrolled_and_observed

        assert _physics_bill(_results_named(enrolled, "pv-only"), _finance(scenario)) == _physics_bill(
            _results_named(observed, "pv-only"), _finance(scenario)
        )

    def test_the_enrolled_runs_event_export_earns_the_seg_rate(
        self, enrolled_and_observed: tuple[ScenarioConfig, FleetResults, FleetResults]
    ) -> None:
        _, enrolled, _ = enrolled_and_observed
        for name in _BATTERY_HOMES:
            sim = _results_named(enrolled, name)
            index = pd.DatetimeIndex(sim.grid_export.index)
            in_the_windows = pd.Index(index.date).isin(_drawn_days()) & index.hour.isin(_EVENT_WINDOW.hours)
            export_kwh = sim.grid_export[in_the_windows] * sim.window.step_hours
            assert export_kwh.sum() > 0, name

            pd.testing.assert_series_equal(
                sim.export_revenue[in_the_windows], export_kwh * _SEG_PENCE_PER_KWH / 100, check_names=False
            )


def test_each_projection_age_is_priced_from_its_own_aged_enrolled_run(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """B12: every age the projection simulates is enrolled, and is priced from its own run."""
    scenario = load_scenario(_scenario_file(tmp_path, weather_cache, "dispatched", "capacity"))
    pricing = _pricing(scenario)
    engine = _engine()
    asked: list[FleetConfig] = []
    by_name: dict[str, FleetResults] = {}

    def simulate(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        asked.append(fleet)
        by_name[fleet.name] = engine.simulate(fleet, start, end)
        return by_name[fleet.name]

    projection = project_fleet(scenario_fleet(scenario), _finance(scenario), simulate=simulate)

    windows = enrolled_event_windows(pricing, scenario.period)
    assert windows
    for fleet in asked:
        for home in fleet.homes:
            if home.battery_config is not None:
                assert home.battery_config.event_discharge == windows, (fleet.name, home.name)
    for age, income in projection.grid_services_income_gbp:
        assert income == pricing.annual_income_gbp(by_name[f"proj-age-{age}"]), age
    (_, first), (_, last) = projection.grid_services_income_gbp[0], projection.grid_services_income_gbp[-1]
    assert first != last
