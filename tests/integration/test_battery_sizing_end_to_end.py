# SPDX-License-Identifier: AGPL-3.0-or-later
"""The battery-sizing measurement end to end: PRD docs/prds/event-dispatch-and-battery-sizing.md §5.8's invariants on what it simulates.

It runs scripts/measure_battery_sizing.py's measure, the path docs/battery-sizing-with-events.md
was measured on, offline on synthetic weather. The fleet is small and the window a short winter
one. A recording simulate beneath the script keeps every fleet the script asks for, so the
invariants are checked on the series the sweep was priced from.
"""

import dataclasses
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.fleet import FleetConfig, FleetResults, FleetRunner, FleetSimulate
from solar_challenge.gridservices import (
    EventParticipation,
    GridServicesBand,
    GridServicesEventsConfig,
    enrolled_event_windows,
)
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.optimize import ConfigPoint, rank
from solar_challenge.weather import PvgisTmy, WeatherCache
from tests._scripts import load_script
from tests._synthetic_weather import synthetic_tmy

_SHORT_ASSET_LIFE_YEARS = 2
"""The asset life and loan term each projection runs over, so it simulates only two ages, as ε's Victron signal does."""

_SITE_EXPORT_LIMIT_KW = 1.0
"""Below both battery powers, 2.4 and 3.68 kW: the committed 3.68 kW never binds on them, so no check of it would have teeth."""

_TOLERANCE_KW = 1e-9


@dataclass(frozen=True)
class _Request:
    """One fleet the script asked to simulate, its window, and the results it was given."""

    fleet: FleetConfig
    start: pd.Timestamp
    end: pd.Timestamp
    results: FleetResults


@dataclass(frozen=True)
class _Measured:
    """measure's sweeps of scenario, each fleet it simulated, in order, and the warnings it raised."""

    scenario: ScenarioConfig
    sweeps: tuple[Any, ...]
    requests: tuple[_Request, ...]
    warnings: tuple[warnings.WarningMessage, ...]


@pytest.fixture(scope="module")
def sizing() -> ModuleType:
    """scripts/measure_battery_sizing.py."""
    return load_script("measure_battery_sizing")


def _scenario(sizing: ModuleType, first_day: date, last_day: date, homes: int) -> ScenarioConfig:
    """The Victron scenario's first homes from first_day to last_day, on a two-year life and a site limit that binds."""
    base = load_scenario(sizing.SCENARIO)
    assert base.finance is not None
    events = base.finance.grid_services_model
    assert isinstance(events, GridServicesEventsConfig)
    finance = dataclasses.replace(
        base.finance,
        asset_life_years=_SHORT_ASSET_LIFE_YEARS,
        loan_term_years=_SHORT_ASSET_LIFE_YEARS,
        grid_services_model=dataclasses.replace(events, site_export_limit_kw=_SITE_EXPORT_LIMIT_KW),
    )
    windowed = dataclasses.replace(base, finance=finance).with_window(first_day=first_day, last_day=last_day)
    return sizing.first_homes(windowed, homes)


def _recording(weather_dir: Path) -> tuple[FleetSimulate, list[_Request]]:
    """A FleetRunner's simulate in turn on the weather cache in weather_dir, and the list it appends each request to."""
    runner = FleetRunner(weather=PvgisTmy(WeatherCache(weather_dir)), home_simulator=simulate_home, parallel=False)
    requests: list[_Request] = []

    def simulate(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        results = runner.simulate(fleet, start, end)
        requests.append(_Request(fleet, start, end, results))
        return results

    return simulate, requests


def _measured(
    sizing: ModuleType, tmp_path_factory: pytest.TempPathFactory, first_day: date, last_day: date, homes: int
) -> _Measured:
    """measure's sweeps of the scenario over first_day to last_day on synthetic weather, with what it simulated and warned."""
    scenario = _scenario(sizing, first_day, last_day, homes)
    weather_dir = tmp_path_factory.mktemp("weather-cache")
    WeatherCache(weather_dir).put(synthetic_tmy(), "tmy", scenario.get_location())
    simulate, requests = _recording(weather_dir)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sweeps = sizing.measure(scenario, simulate=simulate)
    return _Measured(scenario, tuple(sweeps), tuple(requests), tuple(caught))


@pytest.fixture(scope="module")
def weekdays(sizing: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> _Measured:
    """Two homes over Monday and Tuesday 2024-01-15/16, two eligible weekdays: the draw takes one, and the other baselines it.

    It takes about 20 s, and every pytest-xdist worker that runs one of its tests builds it
    again, so its checks share two tests: one of the sweeps, one of the fleets simulated.
    """
    return _measured(sizing, tmp_path_factory, date(2024, 1, 15), date(2024, 1, 16), homes=2)


@pytest.fixture(scope="module")
def weekend(sizing: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> _Measured:
    """One home over Saturday and Sunday 2024-01-13/14: no day is eligible, so the dispatched scenario enrols no window."""
    return _measured(sizing, tmp_path_factory, date(2024, 1, 13), date(2024, 1, 14), homes=1)


def _batteries(fleet: FleetConfig) -> list[Any]:
    """Each battery of fleet's homes, in order."""
    return [home.battery_config for home in fleet.homes if home.battery_config is not None]


def _is_dispatched(request: _Request) -> bool:
    """Whether request's homes are enrolled: the dispatched scenario sets each battery the site's export limit, which an observed fleet's homes do not carry."""
    limits = {battery.site_export_limit_kw for battery in _batteries(request.fleet)}
    assert len(limits) == 1, limits
    return limits == {_SITE_EXPORT_LIMIT_KW}


def _battery_of(request: _Request) -> tuple[float, float]:
    """The installed battery's nameplate kWh and its power in kW, which every home of request shares."""
    installed = {(battery.capacity_kwh, battery.max_discharge_kw) for battery in _batteries(request.fleet)}
    assert len(installed) == 1, installed
    return installed.pop()


def _group(request: _Request) -> tuple[bool, tuple[float, float]]:
    """request's participation and configuration: whether it is dispatched, and its battery."""
    return _is_dispatched(request), _battery_of(request)


def _home_runs(requests: Sequence[_Request]) -> list[tuple[HomeConfig, SimulationResults]]:
    """Each home of each request with its results."""
    return [
        (home, results)
        for request in requests
        for home, results in zip(request.results.home_configs, request.results.per_home_results, strict=True)
    ]


def _battery_export(results: SimulationResults) -> pd.Series:
    """results' battery export in kW, 0 in every row when the run exported none."""
    if results.battery_export is None:
        return pd.Series(0.0, index=results.grid_export.index)
    return results.battery_export


def _in_a_window(home: HomeConfig, index: pd.DatetimeIndex) -> np.ndarray:
    """Whether each row of index falls in one of home's battery's event windows, on the row's own clock."""
    battery = home.battery_config
    windows = () if battery is None else battery.event_discharge
    inside = np.zeros(len(index), dtype=bool)
    for window in windows:
        inside |= np.isin(index.date, window.days) & np.isin(index.hour, window.hours)
    return inside


def _events(scenario: ScenarioConfig) -> GridServicesEventsConfig:
    """scenario's events configuration."""
    assert scenario.finance is not None
    events = scenario.finance.grid_services_model
    assert isinstance(events, GridServicesEventsConfig)
    return events


def _reference_point(sizing: ModuleType) -> ConfigPoint:
    """The smallest battery at its power, the point every sweep compares against."""
    kwh, kw = sizing.BATTERIES[0]
    return ConfigPoint(pv_kwp=sizing.PV_KWP, battery_kwh=kwh, inverter_kw=sizing.INVERTER_KW, battery_kw=kw)


def _age_of(request: _Request) -> float:
    """The projection age request's homes were simulated at: their PV's age in years, which every home of request shares."""
    ages = {home.pv_config.system_age_years for home in request.fleet.homes}
    assert len(ages) == 1, ages
    return ages.pop()


def _check_each_band_ranks_the_four_configurations_enrolled_and_not(sizing: ModuleType, measured: _Measured) -> None:
    expected_points = {
        ConfigPoint(pv_kwp=sizing.PV_KWP, battery_kwh=kwh, inverter_kw=sizing.INVERTER_KW, battery_kw=kw)
        for kwh, kw in sizing.BATTERIES
    }

    assert [(sweep.band, sweep.participation) for sweep in measured.sweeps] == [
        (band, participation)
        for band in GridServicesBand
        for participation in (EventParticipation.DISPATCHED, EventParticipation.OBSERVED)
    ]
    for sweep in measured.sweeps:
        results = [row.result for row in sweep.rows]
        assert len(results) == 4 and {result.config for result in results} == expected_points, sweep.band
        feasible = [result for result in results if result.feasible]
        assert [result.config for result in results[: len(feasible)]] == [result.config for result in rank(feasible)]
        assert not any(result.feasible for result in results[len(feasible) :])


def _check_the_marginal_columns_are_differences_against_the_reference_row(sizing: ModuleType, measured: _Measured) -> None:
    reference_point = _reference_point(sizing)

    for sweep in measured.sweeps:
        (own_reference,) = [row.result for row in sweep.rows if row.result.config == reference_point]
        for row in sweep.rows:
            result, reference = row.result, row.reference
            assert reference is own_reference, (sweep.band, sweep.participation)
            assert row.extra_capex_per_home_gbp == result.capex_per_home_gbp - reference.capex_per_home_gbp
            assert row.outlay_change_gbp == result.representative_outlay_gbp - reference.representative_outlay_gbp
            assert row.pays_for_itself == (
                result.feasible and result.representative_outlay_gbp <= reference.representative_outlay_gbp
            )
        (reference_row,) = [row for row in sweep.rows if row.result is own_reference]
        assert (reference_row.extra_capex_per_home_gbp, reference_row.outlay_change_gbp) == (0.0, 0.0)


def _check_each_configuration_is_simulated_once_per_participation_whatever_the_band(
    sizing: ModuleType, measured: _Measured
) -> None:
    """The three bands are priced from the same runs, each age of a configuration simulated once, one configuration at a time, dispatched first.

    Each age is counted by its homes' PV age, not compared as a whole fleet, so a band that
    reached the homes it simulates would show as an age simulated once per band.
    """
    requests = measured.requests
    for index, request in enumerate(requests):
        for later in requests[index + 1 :]:
            assert (request.fleet, request.start, request.end) != (later.fleet, later.start, later.end), request.fleet.name

    groups = [_group(request) for request in requests]
    in_turn = [group for index, group in enumerate(groups) if index == 0 or groups[index - 1] != group]
    assert in_turn == [(dispatched, battery) for dispatched in (True, False) for battery in sizing.BATTERIES]

    ages: dict[tuple[bool, tuple[float, float]], list[float]] = {}
    for group, request in zip(groups, requests, strict=True):
        ages.setdefault(group, []).append(_age_of(request))
    for group, simulated in ages.items():
        assert len(simulated) == len(set(simulated)), (group, simulated)
    for battery in sizing.BATTERIES:
        assert sorted(ages[True, battery]) == sorted(ages[False, battery]), battery


def _check_the_bus_identity_closes_on_every_step(measured: _Measured) -> None:
    for home, results in _home_runs(measured.requests):
        np.testing.assert_allclose(
            (results.generation + results.grid_import).to_numpy(),
            (results.demand + results.grid_export + results.battery_charge - results.battery_discharge).to_numpy(),
            rtol=0,
            atol=_TOLERANCE_KW,
            err_msg=home.name,
        )


def _check_battery_export_is_part_of_discharge_and_of_export_and_only_inside_the_drawn_windows(
    measured: _Measured,
) -> None:
    exported_days: set[date] = set()
    for request in measured.requests:
        for home, results in _home_runs([request]):
            battery_export = _battery_export(results)
            assert (battery_export <= results.battery_discharge + _TOLERANCE_KW).all(), home.name
            assert (battery_export <= results.grid_export + _TOLERANCE_KW).all(), home.name
            exporting = (battery_export > 0).to_numpy()
            assert not (exporting & ~_in_a_window(home, results.grid_export.index)).any(), home.name
            if not _is_dispatched(request):
                assert not exporting.any(), home.name
            exported_days |= set(results.grid_export.index[exporting].date)

    enrolled = enrolled_event_windows(_events(measured.scenario), measured.scenario.window())
    drawn_days = {day for window in enrolled for day in window.days}
    assert drawn_days
    assert exported_days == drawn_days


def _check_a_home_exports_at_most_the_site_limit_while_its_battery_exports(measured: _Measured) -> None:
    exports_while_the_battery_exports = pd.concat(
        [results.grid_export[_battery_export(results) > 0] for _, results in _home_runs(measured.requests)]
    )

    assert not exports_while_the_battery_exports.empty
    assert (exports_while_the_battery_exports <= _SITE_EXPORT_LIMIT_KW + _TOLERANCE_KW).all()
    assert exports_while_the_battery_exports.max() == pytest.approx(_SITE_EXPORT_LIMIT_KW)


def _check_pricing_and_simulation_agree_on_the_event_days(measured: _Measured) -> None:
    """Pricing refuses a fleet whose batteries carry other days than the draw (gridservices' check), so every sweep priced means they agree."""
    enrolled = enrolled_event_windows(_events(measured.scenario), measured.scenario.window())
    assert enrolled

    for request in measured.requests:
        expected = enrolled if _is_dispatched(request) else ()
        for battery in _batteries(request.fleet):
            assert battery.event_discharge == expected, request.fleet.name


def test_each_band_ranks_its_sweeps_and_compares_every_row_with_its_own_reference(
    sizing: ModuleType, weekdays: _Measured
) -> None:
    _check_each_band_ranks_the_four_configurations_enrolled_and_not(sizing, weekdays)
    _check_the_marginal_columns_are_differences_against_the_reference_row(sizing, weekdays)


def test_every_fleet_simulated_holds_the_prds_invariants(sizing: ModuleType, weekdays: _Measured) -> None:
    _check_each_configuration_is_simulated_once_per_participation_whatever_the_band(sizing, weekdays)
    _check_the_bus_identity_closes_on_every_step(weekdays)
    _check_battery_export_is_part_of_discharge_and_of_export_and_only_inside_the_drawn_windows(weekdays)
    _check_a_home_exports_at_most_the_site_limit_while_its_battery_exports(weekdays)
    _check_pricing_and_simulation_agree_on_the_event_days(weekdays)


def _un_enrolled(fleet: FleetConfig) -> tuple[HomeConfig, ...]:
    """fleet's homes with no event window and no site export limit on any battery, as an observed fleet holds them."""
    return tuple(
        home
        if home.battery_config is None
        else dataclasses.replace(
            home,
            battery_config=dataclasses.replace(home.battery_config, event_discharge=(), site_export_limit_kw=None),
        )
        for home in fleet.homes
    )


def _figures(row: Any) -> tuple[object, ...]:
    """Every figure the report prints for row; ConfigResult itself is not compared, since its equity_irr may be NaN."""
    result = row.result
    return (
        result.config,
        result.capex_per_home_gbp,
        result.solved_own_use_rate_pence_per_kwh,
        result.representative_outlay_gbp,
        result.grid_services_income_per_home_gbp,
        row.extra_capex_per_home_gbp,
        row.outlay_change_gbp,
        row.pays_for_itself,
    )


def test_a_configuration_with_no_event_windows_equals_the_un_enrolled_run(weekend: _Measured) -> None:
    dispatched = [request for request in weekend.requests if _is_dispatched(request)]
    observed = [request for request in weekend.requests if not _is_dispatched(request)]
    assert dispatched and len(dispatched) == len(observed)

    for request in dispatched:
        assert all(battery.event_discharge == () for battery in _batteries(request.fleet)), request.fleet.name
        (twin,) = [
            other
            for other in observed
            if (other.fleet.homes, other.fleet.name, other.start, other.end)
            == (_un_enrolled(request.fleet), request.fleet.name, request.start, request.end)
        ]
        for results, twin_results in zip(request.results.per_home_results, twin.results.per_home_results, strict=True):
            pd.testing.assert_frame_equal(results.to_dataframe(), twin_results.to_dataframe(), check_exact=True)

    by_band = {(sweep.band, sweep.participation): sweep for sweep in weekend.sweeps}
    for band in GridServicesBand:
        enrolled = by_band[band, EventParticipation.DISPATCHED]
        un_enrolled = by_band[band, EventParticipation.OBSERVED]
        assert [_figures(row) for row in enrolled.rows] == [_figures(row) for row in un_enrolled.rows], band
    assert any("contributes £0" in str(caught.message) for caught in weekend.warnings)
