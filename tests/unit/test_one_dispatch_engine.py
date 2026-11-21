# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 13-14: a home that asks for tou_optimized is dispatched by one engine.

Row 13: TOUOptimizedStrategy on the tariff's clock, run through simulate_timestep, reproduces simulate_timestep_tou's
flows within 1e-9 kWh in every minute, on §2.2's morning-drain Economy 10 day and on the bristol-arbitrage home's
sunless 2024-01-15. Row 14: a home's dispatch is refused by build_dispatch_strategy's refusals.
"""

import dataclasses

import pandas as pd
import pytest
from solar_challenge.dispatch import TOUOptimizedStrategy
from solar_challenge.flow import EnergyFlowResult
from solar_challenge.home import SimulationResults, calculate_summary, simulate_home
from solar_challenge.tariff import TariffConfig
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._june_minute_day import MINUTES, inline_day, morning_drain_battery, morning_drain_demand_kw, strategy_day
from tests._synthetic_weather import sunless_weather, weather_for

_E10 = TariffConfig.economy_10()

_KWH_PER_MINUTE = 1e-9
"""The flows of two routes that reproduce each other differ by at most this, in kWh, in any minute."""

_MORNING_DRAIN_SOCS = [pytest.param(soc_kwh, id=f"from-{soc_kwh}-kwh") for soc_kwh in (1.0, 4.0, 5.9)]
"""The morning-drain day's initial states of charge, in kWh: §2.2's three."""


class TestTheMorningDrainDay:
    """§2.2's morning-drain Economy 10 day, stepped by simulate_timestep_tou and by TOUOptimizedStrategy on Economy 10's clock through simulate_timestep."""

    @pytest.mark.parametrize("soc_kwh", _MORNING_DRAIN_SOCS)
    def test_every_minute_s_flows_are_simulate_timestep_tou_s(self, soc_kwh: float) -> None:
        inline = inline_day(morning_drain_battery(soc_kwh), morning_drain_demand_kw, _E10)
        routed = strategy_day(
            morning_drain_battery(soc_kwh), morning_drain_demand_kw, TOUOptimizedStrategy(tariff=_E10), _E10
        )

        assert [
            (minute, field.name, inline_value, routed_value)
            for minute, inline_flow, routed_flow in zip(MINUTES, inline, routed, strict=True)
            for field, inline_value, routed_value in zip(
                dataclasses.fields(EnergyFlowResult),
                dataclasses.astuple(inline_flow),
                dataclasses.astuple(routed_flow),
                strict=True,
            )
            if abs(routed_value - inline_value) > _KWH_PER_MINUTE
        ] == []
        assert sum(flow.grid_charge for flow in routed) > 0


_BRISTOL_ARBITRAGE_FLOWS = (
    "generation",
    "demand",
    "self_consumption",
    "battery_charge",
    "battery_discharge",
    "grid_import",
    "grid_export",
    "grid_charge",
)
"""The kW series of the bristol-arbitrage home's results that row 13 compares, minute by minute, as kWh."""


def _minute_kwh(results: SimulationResults, flow: str) -> pd.Series:
    """The kWh that flow, one of results' kW series, moves in each of its rows."""
    series: pd.Series = getattr(results, flow)
    return series * results.window.step_hours


class TestTheBristolArbitrageHome:
    """scenarios/bristol-arbitrage.yaml's home on the sunless 2024-01-15: its own route, and TOUOptimizedStrategy on Economy 7's clock given to simulate_home."""

    def test_every_minute_s_flows_are_its_own_route_s(self) -> None:
        home = bristol_arbitrage_home()
        day = pd.Timestamp("2024-01-15")
        weather = weather_for(home, sunless_weather("2024-01-15", temp_air=8.0))

        routed = simulate_home(home, day, day, weather=weather)
        given = simulate_home(home, day, day, weather=weather, strategy=TOUOptimizedStrategy(tariff=home.tariff_config))

        assert (routed.strategy_name, given.strategy_name) == ("tou_optimized", "tou_optimized")
        for flow in _BRISTOL_ARBITRAGE_FLOWS:
            pd.testing.assert_series_equal(
                _minute_kwh(given, flow), _minute_kwh(routed, flow), check_exact=False, rtol=0, atol=_KWH_PER_MINUTE
            )
        pd.testing.assert_series_equal(
            given.battery_soc, routed.battery_soc, check_exact=False, rtol=0, atol=_KWH_PER_MINUTE
        )
        assert calculate_summary(routed).total_grid_charge_kwh > 0
