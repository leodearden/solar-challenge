# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests cover:
- TestAStrategyWithNoClock: a TOUOptimizedStrategy given neither peak_hours nor a tariff is
  refused, naming tou_optimized, peak_hours and the missing tariff (§9 row 8).
- TestPeakHoursThatReachACheapMinute: peak_hours given with a tariff are refused when a window
  reaches one of the tariff's cheap minutes, in one refusal naming each such window, the clock
  ranges it reaches and the tariff; a window's shape is refused first (§5.3, §9 row 7).
- TestPeakHoursThatNarrowTheExpensiveMinutes: a window wholly inside the tariff's expensive
  minutes, or given with no tariff, builds, and the battery discharges in its hours only
  (§5.3, §9 row 7).
- TestTheTariffClock: without peak_hours the strategy discharges in the tariff's expensive
  minutes and holds the battery in its cheap ones (§5.3).
- TestTheStrategyAndTheGridChargeContextAgree: a strategy built with the step's tariff never
  discharges in a minute whose grid-charge context is cheap (§5.3, §9 row 10).

The section and row numbers are those of docs/prds/tariff-coverage-classifier-presets.md.
Every tariff, strategy and battery is built inside a test, never at import, so a refusal
fails its own tests and not the module's collection.
"""

from collections.abc import Callable
from datetime import datetime, time

import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import GridChargeConfig, TOUOptimizedStrategy
from solar_challenge.errors import ConfigurationError
from solar_challenge.flow import EnergyFlowResult, simulate_timestep
from solar_challenge.tariff import TariffConfig
from tests._minutes_of_a_winter_day import MINUTES_OF_A_WINTER_DAY

# Each builds its tariff when called: Economy 7 is cheap 00:30-07:30, Economy 10 00:00-05:00,
# 13:00-16:00 and 20:00-22:00, and the flat rate never.
_ECONOMY_7: Callable[[], TariffConfig] = TariffConfig.economy_7
_ECONOMY_10: Callable[[], TariffConfig] = TariffConfig.economy_10


def _flat_rate() -> TariffConfig:
    return TariffConfig.flat_rate(0.25)


def _discharge_kw(strategy: TOUOptimizedStrategy, at: time) -> float:
    """The power strategy discharges at *at* on 2024-01-10, for a 1 kW demand with no PV, its 5 kWh battery half full."""
    return strategy.decide_action(
        timestamp=datetime.combine(datetime(2024, 1, 10), at),
        generation_kw=0.0,
        demand_kw=1.0,
        battery_soc_kwh=2.5,
        battery_capacity_kwh=5.0,
    ).discharge_kw


class TestAStrategyWithNoClock:
    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda: TOUOptimizedStrategy(), id="no-argument"),
            pytest.param(lambda: TOUOptimizedStrategy(None), id="peak_hours-None"),
        ],
    )
    def test_it_is_refused_naming_the_tariffs_clock_and_the_missing_tariff(
        self, build: Callable[[], TOUOptimizedStrategy]
    ) -> None:
        with pytest.raises(ConfigurationError) as refused:
            build()

        for name in ("'tou_optimized'", "peak_hours", "tariff's clock", "no tariff"):
            assert name in str(refused.value), (name, str(refused.value))


class TestPeakHoursThatReachACheapMinute:
    @pytest.mark.parametrize(
        ("peak_hours", "build_tariff", "named"),
        [
            pytest.param(
                [(7, 9)], _ECONOMY_7, ["peak_hours[0] (7, 9)", "07:00-07:30"], id="economy_7-morning"
            ),
            pytest.param(
                [(16, 21)], _ECONOMY_10, ["peak_hours[0] (16, 21)", "20:00-21:00"], id="economy_10-evening"
            ),
            pytest.param(
                [(12, 21)],
                _ECONOMY_10,
                ["peak_hours[0] (12, 21)", "13:00-16:00, 20:00-21:00"],
                id="economy_10-two-cheap-runs-in-one-window",
            ),
            pytest.param(
                [(16, 19), (21, 23)],
                _ECONOMY_10,
                ["peak_hours[1] (21, 23)", "21:00-22:00"],
                id="economy_10-the-second-window",
            ),
            pytest.param(
                [(4, 6), (21, 23)],
                _ECONOMY_10,
                ["peak_hours[0] (4, 6)", "04:00-05:00", "peak_hours[1] (21, 23)", "21:00-22:00"],
                id="economy_10-both-windows",
            ),
        ],
    )
    def test_it_is_refused_naming_each_such_window_its_cheap_minutes_and_the_tariff(
        self,
        peak_hours: list[tuple[int, int]],
        build_tariff: Callable[[], TariffConfig],
        named: list[str],
    ) -> None:
        tariff = build_tariff()

        with pytest.raises(ConfigurationError) as refused:
            TOUOptimizedStrategy(peak_hours, tariff=tariff)

        for name in [*named, tariff.name]:
            assert name in str(refused.value), (name, str(refused.value))

    def test_a_window_inside_the_expensive_minutes_beside_it_is_not_named(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            TOUOptimizedStrategy([(16, 19), (21, 23)], tariff=TariffConfig.economy_10())

        assert "peak_hours[0]" not in str(refused.value)
        assert "(16, 19)" not in str(refused.value)

    def test_the_refusal_says_why_a_peak_hour_cannot_be_cheap_and_how_to_fix_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            TOUOptimizedStrategy([(7, 9)], tariff=TariffConfig.economy_7())

        for name in ("discharges", "cheap period", "remove peak_hours", "narrow"):
            assert name in str(refused.value), (name, str(refused.value))

    @pytest.mark.parametrize(
        "peak_hours",
        [
            pytest.param([(20, 16)], id="a-window-that-ends-before-it-starts"),
            pytest.param([(7, 9), (20, 16)], id="a-cheap-window-then-one-that-ends-before-it-starts"),
        ],
    )
    def test_a_window_of_the_wrong_shape_is_refused_first_as_without_a_tariff(
        self, peak_hours: list[tuple[int, int]]
    ) -> None:
        with pytest.raises(ConfigurationError) as unchecked:
            TOUOptimizedStrategy(peak_hours)
        with pytest.raises(ConfigurationError) as checked:
            TOUOptimizedStrategy(peak_hours, tariff=TariffConfig.economy_7())

        assert str(checked.value) == str(unchecked.value)


class TestPeakHoursThatNarrowTheExpensiveMinutes:
    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda: TOUOptimizedStrategy([(16, 19)], tariff=_ECONOMY_7()), id="economy_7"),
            pytest.param(lambda: TOUOptimizedStrategy([(16, 19)], tariff=_ECONOMY_10()), id="economy_10"),
            pytest.param(lambda: TOUOptimizedStrategy([(16, 19)], tariff=_flat_rate()), id="flat_rate"),
            pytest.param(lambda: TOUOptimizedStrategy([(16, 19)]), id="no-tariff"),
        ],
    )
    def test_an_evening_window_builds_and_the_battery_discharges_in_its_hours_only(
        self, build: Callable[[], TOUOptimizedStrategy]
    ) -> None:
        strategy = build()

        assert (_discharge_kw(strategy, time(17)), _discharge_kw(strategy, time(12))) == (1.0, 0.0)


class TestTheTariffClock:
    @pytest.mark.parametrize(
        ("build_tariff", "at", "discharge_kw"),
        [
            pytest.param(_ECONOMY_7, time(18), 1.0, id="economy_7-18:00-expensive"),
            pytest.param(_ECONOMY_7, time(0, 15), 1.0, id="economy_7-00:15-expensive"),
            pytest.param(_ECONOMY_7, time(3), 0.0, id="economy_7-03:00-cheap"),
            pytest.param(_ECONOMY_7, time(7, 15), 0.0, id="economy_7-07:15-cheap"),
            pytest.param(_ECONOMY_10, time(14), 0.0, id="economy_10-14:00-cheap"),
            pytest.param(_ECONOMY_10, time(21), 0.0, id="economy_10-21:00-cheap"),
            pytest.param(_ECONOMY_10, time(17), 1.0, id="economy_10-17:00-expensive"),
            pytest.param(_flat_rate, time(3), 1.0, id="flat_rate-03:00-expensive"),
        ],
    )
    def test_it_discharges_in_the_expensive_minutes_and_holds_the_battery_in_the_cheap_ones(
        self, build_tariff: Callable[[], TariffConfig], at: time, discharge_kw: float
    ) -> None:
        strategy = TOUOptimizedStrategy(tariff=build_tariff())

        assert _discharge_kw(strategy, at) == discharge_kw


def _winter_day_of_flows(strategy: TOUOptimizedStrategy, tariff: TariffConfig) -> list[EnergyFlowResult]:
    """The flows of each minute of 2024-01-10 in turn, a 1 kW demand with no PV, met by a 5 kWh battery that grid-charges to 0.9, stepped by strategy at tariff."""
    battery = Battery(BatteryConfig(capacity_kwh=5.0, grid_charging=GridChargeConfig(0.9)))
    return [
        simulate_timestep(
            generation_kw=0.0,
            demand_kw=1.0,
            battery=battery,
            timestamp=minute.to_pydatetime(),
            strategy=strategy,
            tariff=tariff,
        )
        for minute in MINUTES_OF_A_WINTER_DAY
    ]


class TestTheStrategyAndTheGridChargeContextAgree:
    @pytest.mark.parametrize(
        "peak_hours",
        [pytest.param([(16, 19)], id="an-evening-window"), pytest.param(None, id="the-tariff-clock")],
    )
    def test_built_with_the_steps_tariff_it_never_discharges_in_a_cheap_minute(
        self, peak_hours: list[tuple[int, int]] | None
    ) -> None:
        tariff = TariffConfig.economy_10()
        strategy = TOUOptimizedStrategy(peak_hours, tariff=tariff)

        flows = dict(zip(MINUTES_OF_A_WINTER_DAY, _winter_day_of_flows(strategy, tariff), strict=True))
        cheap = [minute for minute in flows if tariff.is_cheap_at(minute)]

        assert [minute for minute in cheap if flows[minute].battery_discharge > 0] == []
        assert any(flows[minute].battery_discharge > 0 for minute in flows if 16 <= minute.hour < 19)
        assert any(flows[minute].grid_charge > 0 for minute in cheap)
