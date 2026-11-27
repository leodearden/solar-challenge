# SPDX-License-Identifier: AGPL-3.0-or-later
"""scenarios/bristol-phase1-victron.yaml: bristol-phase1-flex.yaml's fleet on Victron's battery and inverter-charger, enrolled in the drawn event windows."""

import dataclasses
import math

import pytest

from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.gridservices import EventParticipation, GridServicesEventsConfig
from tests._repository_paths import SCENARIOS_DIR


@pytest.fixture(scope="module")
def victron() -> ScenarioConfig:
    return load_scenario(SCENARIOS_DIR / "bristol-phase1-victron.yaml")


@pytest.fixture(scope="module")
def flex() -> ScenarioConfig:
    return load_scenario(SCENARIOS_DIR / "bristol-phase1-flex.yaml")


def _events_pricing(scenario: ScenarioConfig) -> GridServicesEventsConfig:
    assert scenario.finance is not None
    pricing = scenario.finance.grid_services_model
    assert isinstance(pricing, GridServicesEventsConfig)
    return pricing


def test_every_battery_is_a_victron_module_charging_below_its_discharge_power(victron: ScenarioConfig) -> None:
    one_way = math.sqrt(0.92) * 0.95
    for home in victron.homes:
        battery = home.battery_config
        assert battery is not None
        assert (battery.capacity_kwh, battery.max_discharge_kw, battery.max_charge_kw) == (5.12, 2.4, 1.8)
        assert battery.charge_efficiency == pytest.approx(one_way, abs=1e-3)
        assert battery.discharge_efficiency == pytest.approx(one_way, abs=1e-3)


def test_the_fleet_is_enrolled_behind_g98s_site_limit_and_otherwise_prices_as_the_flex_scenario(
    victron: ScenarioConfig, flex: ScenarioConfig
) -> None:
    pricing = _events_pricing(victron)
    assert pricing.participation is EventParticipation.DISPATCHED
    assert pricing.site_export_limit_kw == 3.68
    observed = dataclasses.replace(pricing, participation=EventParticipation.OBSERVED, site_export_limit_kw=None)
    assert victron.finance is not None
    assert dataclasses.replace(victron.finance, grid_services_model=observed) == flex.finance


def test_each_home_is_the_flex_scenarios_home_at_its_position_but_for_its_battery(
    victron: ScenarioConfig, flex: ScenarioConfig
) -> None:
    assert len(victron.homes) == len(flex.homes)
    for home, flex_home in zip(victron.homes, flex.homes, strict=True):
        assert home.pv_config == flex_home.pv_config
        assert home.load_config == flex_home.load_config
        assert home.tariff_config == flex_home.tariff_config
        assert home.battery_config is not None
        assert flex_home.battery_config is not None
        assert home.battery_config.dispatch_strategy == flex_home.battery_config.dispatch_strategy
        assert home.battery_config.grid_charging == flex_home.battery_config.grid_charging


def test_the_seg_rate_location_period_and_flex_band_are_the_flex_scenarios(
    victron: ScenarioConfig, flex: ScenarioConfig
) -> None:
    assert victron.seg_tariff_pence_per_kwh == flex.seg_tariff_pence_per_kwh
    assert victron.location == flex.location
    assert victron.period == flex.period
    assert victron.flex_band == flex.flex_band


def test_every_simulated_battery_home_discharges_in_the_drawn_windows_behind_the_site_limit(
    victron: ScenarioConfig,
) -> None:
    batteries = [home.battery_config for home in victron.simulated_homes() if home.battery_config is not None]
    assert len(batteries) == len(victron.homes)
    for battery in batteries:
        assert battery.event_discharge
        assert battery.site_export_limit_kw == 3.68
