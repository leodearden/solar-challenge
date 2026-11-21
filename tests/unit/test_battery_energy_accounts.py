# SPDX-License-Identifier: AGPL-3.0-or-later
"""The battery's charge and discharge are energies at the home's bus; the charge loss is the battery's, pinned by the storage identity.

Battery.charge reports the energy it drew from the bus, before its charge_efficiency, as Battery.discharge reports the
energy it delivered to the bus, after its discharge_efficiency. So every flow of a step is a bus energy and the bus balance
closes with no loss term, while the battery's state of charge moves by the storage identity
Δsoc_kwh = charge_efficiency × battery_charge − battery_discharge / discharge_efficiency
(docs/prds/one-dispatch-engine.md §5.2, §9 rows 2-6).
"""

import math
from collections.abc import Callable
from datetime import datetime

import pandas as pd
import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.community import CommunityConfig, simulate_community, validate_community_balance
from solar_challenge.config import load_scenarios
from solar_challenge.dispatch import GridChargeConfig, TOUOptimizedStrategy
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou, validate_energy_balance
from solar_challenge.home import calculate_summary, simulate_home
from solar_challenge.tariff import TariffConfig
from tests._balanced_sim_results import make_balanced_fleet
from tests._repository_paths import SCENARIOS_DIR
from tests._synthetic_weather import sunless_weather, weather_for

_E7 = TariffConfig.economy_7()

_TEN_KWH = BatteryConfig(capacity_kwh=10.0, max_charge_kw=2.5, max_discharge_kw=2.5)
"""A 10 kWh battery with 2.5 kW charge and discharge limits and the default 0.975 efficiencies: SOC limits 1.0 and 9.0 kWh."""

Step = Callable[[Battery], EnergyFlowResult]
Day = Callable[[Battery], list[EnergyFlowResult]]


def _an_hour_of_excess_pv(battery: Battery) -> EnergyFlowResult:
    """One hour of 1 kW PV and no demand through simulate_timestep, self-consumption dispatch."""
    return simulate_timestep(1.0, 0.0, battery, timestep_minutes=60)


def _an_expensive_hour_of_excess_pv(battery: Battery) -> EnergyFlowResult:
    """One hour of 1 kW PV and no demand through simulate_timestep_tou at noon, an expensive Economy 7 hour."""
    return simulate_timestep_tou(1.0, 0.0, battery, pd.Timestamp("2024-01-15 12:00"), _E7, 60)


def _a_cheap_hour_dispatched_by_strategy(battery: Battery) -> EnergyFlowResult:
    """One hour from 02:00, a cheap Economy 7 hour, of no PV and no demand through simulate_timestep with TOU dispatch."""
    return simulate_timestep(
        0.0, 0.0, battery, 60, datetime(2024, 1, 15, 2, 0), TOUOptimizedStrategy([(17, 20)]), tariff=_E7
    )


def _a_cheap_hour_dispatched_inline(battery: Battery) -> EnergyFlowResult:
    """One hour from 02:00, a cheap Economy 7 hour, of no PV and no demand through simulate_timestep_tou."""
    return simulate_timestep_tou(0.0, 0.0, battery, pd.Timestamp("2024-01-15 02:00"), _E7, 60)


_MINUTES = pd.date_range("2024-06-21 00:00", periods=1440, freq="min")


def _hour(minute: pd.Timestamp) -> float:
    """The hour of the day minute starts at, as a fraction."""
    return minute.hour + minute.minute / 60


def _pv_kw(minute: pd.Timestamp) -> float:
    """The day's PV: 3·sin(π(h − 5)/16) kW from 05:00 to 21:00, and none outside."""
    h = _hour(minute)
    return 3 * math.sin(math.pi * (h - 5) / 16) if 5 <= h < 21 else 0.0


def _demand_kw(minute: pd.Timestamp) -> float:
    """The day's demand: 0.4 kW, plus 1.5 kW from 17:00 to 20:00."""
    h = _hour(minute)
    return 0.4 + (1.5 if 17 <= h < 20 else 0.0)


def _strategy_day(battery: Battery) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep, dispatched by TOU with peak hours 16:00 to 20:00 on Economy 7."""
    strategy = TOUOptimizedStrategy([(16, 20)])
    return [
        simulate_timestep(_pv_kw(minute), _demand_kw(minute), battery, 1.0, minute.to_pydatetime(), strategy, tariff=_E7)
        for minute in _MINUTES
    ]


def _inline_day(battery: Battery) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep_tou on Economy 7."""
    return [simulate_timestep_tou(_pv_kw(minute), _demand_kw(minute), battery, minute, _E7, 1.0) for minute in _MINUTES]


def _soc_change_by_the_identity_kwh(battery: Battery, flow: EnergyFlowResult) -> float:
    """The SOC change the storage identity gives for flow: battery's charge_efficiency times flow's battery_charge, less its battery_discharge divided by battery's discharge_efficiency."""
    return battery.charge_efficiency * flow.battery_charge - flow.battery_discharge / battery.discharge_efficiency


_DAY_SOC_KWH = 1.0
"""The SOC the day starts at: the battery's floor, so its cheap night grid-charges it to the 6.0 kWh target."""

_DAY_BATTERY = BatteryConfig(capacity_kwh=10.0, max_charge_kw=2.5, max_discharge_kw=2.5, grid_charging=GridChargeConfig(0.6))


class TestPvChargeLossIsNotExport:
    """§9 row 2: an hour of 1 kW excess PV into the battery at 2.0 kWh. It draws all of it and stores 0.975 kWh, so nothing is exported."""

    @pytest.mark.parametrize(
        "step",
        [
            pytest.param(_an_hour_of_excess_pv, id="simulate_timestep"),
            pytest.param(_an_expensive_hour_of_excess_pv, id="simulate_timestep_tou"),
        ],
    )
    def test_the_battery_draws_the_whole_excess_and_stores_its_charge_efficiency_share(self, step: Step) -> None:
        battery = Battery(_TEN_KWH, initial_soc_kwh=2.0)

        result = step(battery)

        assert result.battery_charge == pytest.approx(1.0)
        assert battery.soc_kwh - 2.0 == pytest.approx(0.975)
        assert result.grid_export == pytest.approx(0.0, abs=1e-12)


class TestGridChargingImportsWhatItDrew:
    """§9 row 3: a cheap Economy 7 hour with no PV and no demand. The battery at its floor grid-charges toward its 0.9 target at its 2.5 kW limit, importing 2.5 kWh and storing 2.4375 kWh of it."""

    @pytest.mark.parametrize(
        "step",
        [
            pytest.param(_a_cheap_hour_dispatched_by_strategy, id="simulate_timestep"),
            pytest.param(_a_cheap_hour_dispatched_inline, id="simulate_timestep_tou"),
        ],
    )
    def test_the_grid_import_is_the_energy_the_battery_drew(self, step: Step) -> None:
        config = BatteryConfig(
            capacity_kwh=10.0, max_charge_kw=2.5, max_discharge_kw=2.5, grid_charging=GridChargeConfig(0.9)
        )
        battery = Battery(config, initial_soc_kwh=config.soc_envelope().min_soc_kwh)
        soc_before_kwh = battery.soc_kwh

        result = step(battery)

        assert result.grid_import == pytest.approx(2.5)
        assert result.grid_charge == pytest.approx(2.5)
        assert result.battery_charge == pytest.approx(2.5)
        assert battery.soc_kwh - soc_before_kwh == pytest.approx(2.4375)


class TestStorageIdentity:
    """§9 row 4: over a June day on Economy 7 of PV charging, grid charging and discharge, the battery's SOC moves by its charge_efficiency times what it drew, less what it delivered divided by its discharge_efficiency.

    The battery is 10 kWh with 2.5 kW limits, grid-charging to 0.6 of it from 1.0 kWh; the day's PV is
    3·sin(π(h − 5)/16) kW from 05:00 to 21:00 and its demand 0.4 kW, plus 1.5 kW from 17:00 to 20:00.
    """

    @pytest.fixture(
        params=[pytest.param(_strategy_day, id="simulate_timestep"), pytest.param(_inline_day, id="simulate_timestep_tou")]
    )
    def day(self, request: pytest.FixtureRequest) -> Day:
        engine: Day = request.param
        return engine

    @pytest.fixture(
        params=[
            pytest.param(_DAY_BATTERY, id="default-efficiencies"),
            pytest.param(_DAY_BATTERY.with_round_trip(0.81), id="round-trip-0.81"),
        ]
    )
    def battery(self, request: pytest.FixtureRequest) -> Battery:
        return Battery(request.param, initial_soc_kwh=_DAY_SOC_KWH)

    def test_the_day_charges_from_pv_and_from_the_grid_discharges_and_fills_the_battery(
        self, day: Day, battery: Battery
    ) -> None:
        flows = day(battery)

        assert sum(flow.battery_charge - flow.grid_charge for flow in flows) > 0
        assert sum(flow.grid_charge for flow in flows) > 0
        assert sum(flow.battery_discharge for flow in flows) > 0
        assert any(flow.battery_soc == battery.max_soc_kwh for flow in flows)

    def test_over_the_day_the_soc_moves_by_what_the_battery_drew_and_delivered(self, day: Day, battery: Battery) -> None:
        flows = day(battery)

        drawn_kwh = sum(flow.battery_charge for flow in flows)
        delivered_kwh = sum(flow.battery_discharge for flow in flows)
        assert battery.soc_kwh - _DAY_SOC_KWH == pytest.approx(
            battery.charge_efficiency * drawn_kwh - delivered_kwh / battery.discharge_efficiency, abs=1e-9
        )

    def test_at_every_step_the_soc_moves_by_what_the_battery_drew_and_delivered(self, day: Day, battery: Battery) -> None:
        flows = day(battery)

        socs_before_kwh = [_DAY_SOC_KWH] + [flow.battery_soc for flow in flows[:-1]]
        off_by_kwh = [
            (minute, flow.battery_soc - soc_before_kwh - _soc_change_by_the_identity_kwh(battery, flow))
            for minute, flow, soc_before_kwh in zip(_MINUTES, flows, socs_before_kwh, strict=True)
        ]
        assert [(minute, off) for minute, off in off_by_kwh if abs(off) > 1e-12] == []

    def test_every_step_balances_at_the_bus_with_no_loss_term(self, day: Day, battery: Battery) -> None:
        flows = day(battery)

        assert all(validate_energy_balance(flow) for flow in flows)


class TestChargeCappedAtTheCeiling:
    """§9 row 5: 0.01 kWh below its ceiling, the battery stores only that 0.01 kWh of a minute's 2 kW, so it draws only 0.01 kWh divided by its charge_efficiency."""

    @staticmethod
    def _battery_just_below_its_ceiling() -> Battery:
        return Battery(_TEN_KWH, initial_soc_kwh=_TEN_KWH.soc_envelope().max_soc_kwh - 0.01)

    def test_the_step_exports_the_excess_the_battery_did_not_draw(self) -> None:
        battery = self._battery_just_below_its_ceiling()

        result = simulate_timestep(2.0, 0.0, battery, timestep_minutes=1)

        assert battery.soc_kwh == battery.max_soc_kwh
        assert result.battery_charge == pytest.approx(0.01 / 0.975, abs=1e-12)
        assert result.grid_export == pytest.approx(2.0 / 60 - 0.01 / 0.975, abs=1e-12)

    def test_a_capped_charge_returns_what_it_could_store_divided_by_its_charge_efficiency(self) -> None:
        battery = self._battery_just_below_its_ceiling()

        drawn_kwh = battery.charge(2.0, 1)

        assert drawn_kwh == pytest.approx(0.01 / battery.charge_efficiency, abs=1e-12)
        assert battery.soc_kwh == battery.max_soc_kwh

    def test_an_uncapped_charge_returns_the_whole_energy_it_was_offered(self) -> None:
        battery = Battery(_TEN_KWH, initial_soc_kwh=2.0)

        drawn_kwh = battery.charge(1.0, 60)

        assert drawn_kwh == pytest.approx(1.0)
        assert battery.soc_kwh - 2.0 == pytest.approx(0.975)


class TestBusBalancesStillClose:
    """§9 row 6: the bus balances a home run and a community battery are checked against need no loss term."""

    def test_the_arbitrage_home_balances_every_minute_and_summarises_its_grid_charge(self) -> None:
        home = load_scenarios(SCENARIOS_DIR / "bristol-arbitrage.yaml")[0].home
        assert home is not None
        day = pd.Timestamp("2024-01-15")

        results = simulate_home(
            home, day, day, validate_balance=True, weather=weather_for(home, sunless_weather("2024-01-15", temp_air=8.0))
        )

        assert calculate_summary(results).total_grid_charge_kwh > 0

    def test_a_lossy_community_battery_balances_the_community(self) -> None:
        minutes = pd.date_range("2024-06-21 12:00", periods=2, freq="min", tz="Europe/London")
        fleet = make_balanced_fleet(minutes, [([10.0, 0.0], [0.0, 0.0]), ([0.0, 0.0], [2.0, 10.0])])
        lossy = BatteryConfig(capacity_kwh=10.0, max_charge_kw=30.0, max_discharge_kw=30.0)

        community = simulate_community(fleet, CommunityConfig(sharing_mode="community_battery", community_battery=lossy))

        assert community.battery_charge.iloc[0] > 0
        assert community.battery_discharge.iloc[1] > 0
        assert validate_community_balance(fleet, community) is True
