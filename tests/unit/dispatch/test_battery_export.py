# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/event-dispatch-and-battery-sizing.md §5.1, §5.8 invariants 1-3 and §9 B1-B3: battery export in the dispatch engine.

A decision's export_kw asks the battery for power beyond the home's shortfall. simulate_timestep serves the home
first from what the battery delivers and books the rest as grid export, and as battery_export, a part of both
battery_discharge and grid_export (B1, invariants 2 and 3). A run that asks for no export is byte-identical to the
engine before battery export existed (B3, invariant 1). B2, an export beyond its step's limit, is refused with the
other bounds, in tests/unit/dispatch/test_decision_bounds.py.
"""

import functools
import hashlib
import itertools
import math
import random
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchDecision,
    DispatchStrategy,
    GridChargeConfig,
    PeakShavingStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, validate_energy_balance
from solar_challenge.tariff import TariffConfig
from tests._fixed_decision_strategy import FixedDecisionStrategy
from tests._tou_on_the_tariff_s_clock import on_the_tariff_s_clock

_E7 = TariffConfig.economy_7()
_LONDON = ZoneInfo("Europe/London")

# Measured at the base f0b4cba5: on a minute at this generation and demand, a 10 kWh battery at 5.0 kWh under
# self-consumption delivers 0.020849925363509925 kWh against a shortfall of 0.020849925363509922 kWh, an ulp more,
# because (d - g) * h is not d * h - g * h.
_ULP_PAIR_GENERATION_KW = 1.9723046813928018
_ULP_PAIR_DEMAND_KW = 3.2233002032033973

# Task 1362's pair: two powers an ulp apart, whose energies over a minute are equal.
_POWER_KW = 3.9243814029178457
_AN_ULP_ABOVE_KW = math.nextafter(_POWER_KW, math.inf)

# Steps whose generation and demand are an ulp, or a rounding, apart, as (generation_kw, demand_kw).
_EDGE_STEPS = (
    (_ULP_PAIR_GENERATION_KW, _ULP_PAIR_DEMAND_KW),
    (_POWER_KW, _AN_ULP_ABOVE_KW),
    (_AN_ULP_ABOVE_KW, _POWER_KW),
    (0.1 + 0.2, 0.3),
)

_MINUTES_PER_DAY = 1440
_EDGE_MINUTES = range(30, _MINUTES_PER_DAY, 90)
_DAY_START = datetime(2024, 1, 15, tzinfo=_LONDON)


def _day_of_steps(seed: int) -> tuple[tuple[float, float], ...]:
    """A day of minutes' (generation_kw, demand_kw), each drawn from 0 to 3 kW by random.Random(seed), with _EDGE_STEPS spliced in turn into _EDGE_MINUTES."""
    rng = random.Random(seed)
    steps = [(rng.uniform(0.0, 3.0), rng.uniform(0.0, 3.0)) for _ in range(_MINUTES_PER_DAY)]
    for minute, edge in zip(_EDGE_MINUTES, itertools.cycle(_EDGE_STEPS)):
        steps[minute] = edge
    return tuple(steps)


_STEPS = _day_of_steps(seed=1702)


class _Dispatch(NamedTuple):
    """A strategy, the tariff its steps are priced at, and its battery's grid charging."""

    strategy: DispatchStrategy
    tariff: Optional[TariffConfig] = None
    grid_charging: Optional[GridChargeConfig] = None


_CHARGE_WINDOW_01_TO_05 = ChargeWindow(
    days="daily",
    start=time(1, 0),
    duration=timedelta(hours=4),
    target_soc_fraction=0.8,
    allow_discharge=False,
)
_DISCHARGE_WINDOW_17_TO_19 = ChargeWindow(
    days="daily",
    start=time(17, 0),
    duration=timedelta(hours=2),
    target_soc_fraction=0.3,
    allow_discharge=True,
)

BUILT_IN_DISPATCHES: dict[str, _Dispatch] = {
    "self_consumption": _Dispatch(SelfConsumptionStrategy()),
    "tou_optimized": _Dispatch(**on_the_tariff_s_clock(_E7), grid_charging=GridChargeConfig()),
    "peak_shaving": _Dispatch(PeakShavingStrategy(0.25), _E7, GridChargeConfig()),
    "scheduled_charge": _Dispatch(
        ScheduledChargeStrategy(
            TOUOptimizedStrategy([(16, 20)]), (_CHARGE_WINDOW_01_TO_05, _DISCHARGE_WINDOW_17_TO_19), _LONDON
        ),
        _E7,
        GridChargeConfig(),
    ),
}


@functools.cache
def _flows_of_the_day(dispatch_id: str) -> tuple[EnergyFlowResult, ...]:
    """Each minute's flows of _STEPS from 2024-01-15 00:00 in London under BUILT_IN_DISPATCHES[dispatch_id], on one 10 kWh battery carried from minute to minute."""
    dispatch = BUILT_IN_DISPATCHES[dispatch_id]
    battery = Battery(BatteryConfig(capacity_kwh=10.0, grid_charging=dispatch.grid_charging))
    return tuple(
        simulate_timestep(
            generation_kw,
            demand_kw,
            battery,
            1.0,
            _DAY_START + timedelta(minutes=minute),
            dispatch.strategy,
            tariff=dispatch.tariff,
        )
        for minute, (generation_kw, demand_kw) in enumerate(_STEPS)
    )


# EnergyFlowResult's fields before battery export existed, named so that no later field enters the digest.
_PRE_EXPORT_FIELDS = (
    "generation",
    "demand",
    "self_consumption",
    "battery_charge",
    "battery_discharge",
    "grid_export",
    "grid_import",
    "battery_soc",
    "grid_charge",
)


def _digest(flows: Sequence[EnergyFlowResult]) -> str:
    """The sha256 of each step's _PRE_EXPORT_FIELDS, each written exactly by float.hex."""
    sha = hashlib.sha256()
    for flow in flows:
        sha.update((" ".join(float.hex(getattr(flow, name)) for name in _PRE_EXPORT_FIELDS) + "\n").encode())
    return sha.hexdigest()


# Recorded by running this test at the base f0b4cba5, before battery export existed.
_DIGESTS_BEFORE_BATTERY_EXPORT = {
    "self_consumption": "a5dafa22d81d1141e8805e8a2611d12818955180cd82a66c0cd36924f1550d05",
    "tou_optimized": "a7241dbd06f4ee75fe409818b81ccf7141f56e90a6332a90aa34b3455a128783",
    "peak_shaving": "b497f21cdbefd027baa89d70473fed1a18c77b38f02ede2829fb0a728116a8f1",
    "scheduled_charge": "3a0f9c0b3981695c77b84936bd460a2ccad34f151c9139ebeefada57411696dc",
}


class TestARunThatAsksForNoExportIsUnchanged:
    """B3, invariant 1: a built-in strategy asks for no export, so every step's flows are those of the engine before battery export, to the last bit."""

    @pytest.mark.parametrize("dispatch_id", list(BUILT_IN_DISPATCHES))
    def test_every_built_in_strategy_s_flows_are_byte_identical_to_the_engine_before_battery_export(
        self, dispatch_id: str
    ) -> None:
        assert _digest(_flows_of_the_day(dispatch_id)) == _DIGESTS_BEFORE_BATTERY_EXPORT[dispatch_id]

    @pytest.mark.parametrize("dispatch_id", list(BUILT_IN_DISPATCHES))
    def test_no_step_of_a_built_in_strategy_s_day_exports(self, dispatch_id: str) -> None:
        assert [flow.battery_export for flow in _flows_of_the_day(dispatch_id)] == [0.0] * _MINUTES_PER_DAY


def _ten_kwh_battery(soc_kwh: float) -> Battery:
    """A 10 kWh battery at *soc_kwh*, with the default 2.5 kW limits and 0.975 efficiencies."""
    return Battery(BatteryConfig(capacity_kwh=10.0), initial_soc_kwh=soc_kwh)


class _Export(NamedTuple):
    """An hour's step at a battery's SOC, generation and demand, the decision asked of it, and the flows it settles to, in kWh."""

    soc_kwh: float
    generation_kw: float
    demand_kw: float
    decision: DispatchDecision
    self_consumption: float
    battery_discharge: float
    battery_export: float
    grid_export: float
    grid_import: float


EXPORTS = [
    pytest.param(
        _Export(5.0, 0.0, 1.0, DispatchDecision(0.0, 1.0, 0.0, 1.5), 1.0, 2.5, 1.5, 1.5, 0.0),
        id="the_home_s_shortfall_then_the_export",
    ),
    pytest.param(
        _Export(2.5, 0.0, 1.0, DispatchDecision(0.0, 1.0, 0.0, 1.5), 1.0, 1.4625, 0.4625, 0.4625, 0.0),
        id="less_delivered_than_asked-the_home_takes_its_shortfall_and_the_rest_is_exported",
    ),
    pytest.param(
        _Export(1.8, 0.0, 1.0, DispatchDecision(0.0, 1.0, 0.0, 1.5), 0.78, 0.78, 0.0, 0.0, 0.22),
        id="less_delivered_than_the_shortfall-nothing_is_exported",
    ),
    pytest.param(
        _Export(5.0, 0.0, 1.0, DispatchDecision(0.0, 0.5, 0.0, 1.0), 1.0, 1.5, 0.5, 0.5, 0.0),
        id="a_discharge_below_the_shortfall-the_delivery_serves_the_whole_shortfall_first",
    ),
    pytest.param(
        _Export(5.0, 2.0, 1.0, DispatchDecision(0.0, 0.0, 0.0, 1.0), 1.0, 1.0, 1.0, 2.0, 0.0),
        id="a_pv_excess-the_excess_and_the_battery_both_export",
    ),
]


# The flows each of EXPORTS names, in EnergyFlowResult's field order.
_SETTLED_FLOWS = ("self_consumption", "battery_discharge", "battery_export", "grid_export", "grid_import")


class TestAStepThatAsksForExportServesTheHomeFirst:
    """B1, invariants 2 and 3: an hour's step, so a power in kW is the same energy in kWh, whose decision asks for export.

    What the battery delivers serves the home's shortfall first, and only the rest is exported: battery_export is that
    rest, a part of both battery_discharge and grid_export, and self_consumption never includes it.
    """

    @staticmethod
    def _settled(export: _Export) -> EnergyFlowResult:
        """*export*'s step on a 10 kWh battery at its SOC, under a strategy that returns its decision."""
        return simulate_timestep(
            generation_kw=export.generation_kw,
            demand_kw=export.demand_kw,
            battery=_ten_kwh_battery(export.soc_kwh),
            timestep_minutes=60,
            strategy=FixedDecisionStrategy(export.decision),
        )

    @pytest.mark.parametrize("export", EXPORTS)
    def test_the_step_settles_the_home_s_shortfall_before_the_export(self, export: _Export) -> None:
        result = self._settled(export)
        settled = {flow: getattr(result, flow) for flow in _SETTLED_FLOWS}
        assert settled == pytest.approx({flow: getattr(export, flow) for flow in _SETTLED_FLOWS})

    @pytest.mark.parametrize("export", EXPORTS)
    def test_the_bus_identity_closes(self, export: _Export) -> None:
        assert validate_energy_balance(self._settled(export))

    @pytest.mark.parametrize("export", EXPORTS)
    def test_the_battery_s_export_is_a_part_of_its_discharge_and_of_the_grid_export(self, export: _Export) -> None:
        result = self._settled(export)
        assert result.battery_export <= result.battery_discharge
        assert result.battery_export <= result.grid_export

    @pytest.mark.parametrize("export", EXPORTS)
    def test_self_consumption_is_at_most_the_demand(self, export: _Export) -> None:
        result = self._settled(export)
        assert result.self_consumption <= result.demand


class TestAStepThatAsksForNoExportBooksNone:
    """B3's ulp gate: delivery beyond the shortfall is booked as export only when the decision asked for export, so the ulp a self-consumption minute can deliver beyond its shortfall is not."""

    def test_an_ulp_delivered_beyond_the_shortfall_is_not_exported(self) -> None:
        result = simulate_timestep(
            _ULP_PAIR_GENERATION_KW, _ULP_PAIR_DEMAND_KW, _ten_kwh_battery(5.0), 1.0, strategy=SelfConsumptionStrategy()
        )
        assert result.battery_discharge > result.demand - result.generation
        assert result.battery_export == 0.0
        assert result.grid_export == 0.0
