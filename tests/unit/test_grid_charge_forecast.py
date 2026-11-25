# SPDX-License-Identifier: AGPL-3.0-or-later
"""grid_charge_forecast turns a run's PV and demand into each cheap window's useful-charge ceiling, under each GridChargeForecast."""

import dataclasses
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import GRID_CHARGE_FORECASTS, GridChargeConfig, GridChargeForecast
from solar_challenge.grid_charge_forecast import grid_charge_ceilings_kwh, useful_charge_ceiling_kwh
from solar_challenge.tariff import TariffConfig

_BATTERY = dataclasses.replace(BatteryConfig.default_5kwh(), grid_charging=GridChargeConfig(0.9))
_E7 = TariffConfig.economy_7()
_MINUTES_PER_DAY = 24 * 60
_PV_SCALES = (1.0, 0.3, 0.8, 1.0, 0.1, 0.6, 1.0, 0.9, 0.2, 1.0, 0.5, 0.7, 1.0, 0.4, 0.8, 1.0, 0.6)
"""Each synthetic day's PV, as a fraction of a clear day's, so the days need different ceilings."""


def _trace(days: int, pv_scales: tuple[float, ...] = _PV_SCALES) -> tuple[pd.Series, pd.Series]:
    """Minute generation and demand in kW over *days* June days from local midnight in Europe/London.

    Each day's PV is a 06:00-18:00 sine of 3 kW peak times its scale; demand is 0.4 kW, 1.4 kW from 17:00 to 21:00.
    """
    index = pd.date_range("2024-06-01", periods=days * _MINUTES_PER_DAY, freq="min", tz="Europe/London")
    minute = np.arange(len(index)) % _MINUTES_PER_DAY
    day = np.arange(len(index)) // _MINUTES_PER_DAY
    daylight = np.clip(np.sin(np.pi * (minute - 360) / 720), 0.0, None) * ((minute >= 360) & (minute < 1080))
    generation = 3.0 * daylight * np.asarray(pv_scales)[day]
    demand = 0.4 + 1.0 * ((minute >= 1020) & (minute < 1260))
    return pd.Series(generation, index=index), pd.Series(demand, index=index)


def _windows(index: pd.DatetimeIndex, tariff: TariffConfig) -> list[tuple[int, int, int]]:
    """Each maximal run of rows tariff prices cheap: its first row, one past its last, and its horizon's end, the next run's first row or the run's end."""
    cheap = [tariff.is_cheap_at(timestamp) for timestamp in index]
    starts = [row for row in range(len(cheap)) if cheap[row] and (row == 0 or not cheap[row - 1])]
    ends = [row + 1 for row in range(len(cheap)) if cheap[row] and (row + 1 == len(cheap) or not cheap[row + 1])]
    return [(start, end, horizon) for start, end, horizon in zip(starts, ends, [*starts[1:], len(cheap)])]


def _own_horizon_ceiling(
    generation: pd.Series, demand: pd.Series, battery: BatteryConfig, start: int, horizon: int, cheap_end: int
) -> float:
    """The ceiling the step-5 horizon model gives the window whose cheap rows are [start, cheap_end), over [start, horizon)."""
    surplus = np.clip(generation.to_numpy() - demand.to_numpy(), 0.0, None)[start:horizon]
    shortfall = np.clip(demand.to_numpy() - generation.to_numpy(), 0.0, None)[start:horizon]
    after_the_window = np.arange(start, horizon) >= cheap_end
    step_hours = 1.0 / 60.0
    inflow = np.where(after_the_window, np.minimum(surplus, battery.max_charge_kw) * step_hours * battery.charge_efficiency, 0.0)
    outflow = np.where(
        after_the_window, np.minimum(shortfall, battery.max_discharge_kw) * step_hours / battery.discharge_efficiency, 0.0
    )
    envelope = battery.soc_envelope()
    return useful_charge_ceiling_kwh(inflow, outflow, floor_kwh=envelope.min_soc_kwh, top_kwh=envelope.max_soc_kwh)


def _window_values(ceilings: tuple[Optional[float], ...], start: int, end: int) -> set[Optional[float]]:
    """The distinct ceilings of a window's rows."""
    return set(ceilings[start:end])


class TestUsefulChargeCeiling:
    """useful_charge_ceiling_kwh is the highest start-of-horizon SOC whose extra charge the horizon's PV will not strand."""

    def test_a_horizon_that_never_fills_gives_the_top_less_its_highest_net_level(self) -> None:
        assert useful_charge_ceiling_kwh([0.0, 1.0, 0.0], [0.5, 0.0, 0.0], floor_kwh=0.5, top_kwh=4.5) == pytest.approx(4.0)

    def test_a_horizon_that_drains_to_the_floor_before_pv_fills_it_gives_the_start_that_empties_first(self) -> None:
        """From 3.5 kWh a 3 kWh shortfall empties the battery to its 0.5 kWh floor before 5 kWh of PV fills it; more would strand PV."""
        assert useful_charge_ceiling_kwh([0.0, 5.0], [3.0, 0.0], floor_kwh=0.5, top_kwh=4.5) == pytest.approx(3.5)

    @pytest.mark.parametrize(
        ("inflow", "outflow", "ceiling"),
        [
            pytest.param([0.0], [10.0], 4.5, id="a-shortfall-beyond-the-envelope-is-the-top"),
            pytest.param([10.0], [0.0], 0.5, id="pv-beyond-the-envelope-is-the-floor"),
        ],
    )
    def test_the_ceiling_is_clipped_to_the_envelope(self, inflow: list[float], outflow: list[float], ceiling: float) -> None:
        assert useful_charge_ceiling_kwh(inflow, outflow, floor_kwh=0.5, top_kwh=4.5) == pytest.approx(ceiling)

    @pytest.mark.parametrize(
        ("inflow", "outflow", "floor", "top", "names"),
        [
            pytest.param([1.0, 0.0], [0.0], 0.5, 4.5, ("inflow_kwh", "outflow_kwh"), id="unequal-lengths"),
            pytest.param([1.0, -0.1], [0.0, 0.0], 0.5, 4.5, ("inflow_kwh",), id="negative-inflow"),
            pytest.param([1.0, 0.0], [0.0, -2.0], 0.5, 4.5, ("outflow_kwh",), id="negative-outflow"),
            pytest.param([1.0], [0.0], 4.6, 4.5, ("floor_kwh", "top_kwh"), id="floor-above-top"),
        ],
    )
    def test_flows_or_bounds_it_cannot_read_are_refused_naming_them(
        self, inflow: list[float], outflow: list[float], floor: float, top: float, names: tuple[str, ...]
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            useful_charge_ceiling_kwh(inflow, outflow, floor_kwh=floor, top_kwh=top)

        assert all(name in str(refusal.value) for name in names)


class TestGridChargeCeilings:
    """grid_charge_ceilings_kwh gives each row of a run the ceiling its cheap window's fill is capped at, None where there is none."""

    _DAYS = 16

    def test_pv_blind_has_no_ceiling(self) -> None:
        generation, demand = _trace(self._DAYS)

        assert grid_charge_ceilings_kwh("pv_blind", generation, demand, _BATTERY, _E7) == (None,) * len(generation)

    @pytest.mark.parametrize("forecast", GRID_CHARGE_FORECASTS)
    def test_a_row_outside_every_cheap_window_has_no_ceiling(self, forecast: str) -> None:
        generation, demand = _trace(self._DAYS)

        ceilings = grid_charge_ceilings_kwh(forecast, generation, demand, _BATTERY, _E7)  # type: ignore[arg-type]

        assert len(ceilings) == len(generation)
        assert all(ceilings[row] is None for row in range(len(ceilings)) if not _E7.is_cheap_at(generation.index[row]))

    def test_perfect_foresight_gives_each_window_its_own_horizons_ceiling(self) -> None:
        generation, demand = _trace(self._DAYS)

        ceilings = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, _BATTERY, _E7)

        windows = _windows(generation.index, _E7)
        assert len(windows) == self._DAYS
        for start, end, horizon in windows:
            (held,) = _window_values(ceilings, start, end)
            assert held == pytest.approx(_own_horizon_ceiling(generation, demand, _BATTERY, start, horizon, end))

    def test_the_days_need_different_ceilings(self) -> None:
        """The control for the trailing tests: a run whose windows all needed one ceiling could not tell a quantile from a copy."""
        generation, demand = _trace(self._DAYS)

        ceilings = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, _BATTERY, _E7)

        assert len({ceilings[start] for start, _, _ in _windows(generation.index, _E7)}) > 3

    def test_trailing_14_days_waits_for_14_windows_then_fills_to_their_75th_percentile(self) -> None:
        generation, demand = _trace(self._DAYS)

        trailing = grid_charge_ceilings_kwh("trailing_14_days", generation, demand, _BATTERY, _E7)
        foresight = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, _BATTERY, _E7)

        windows = _windows(generation.index, _E7)
        for start, end, _ in windows[:14]:
            assert _window_values(trailing, start, end) == {None}
        for number, (start, end, _) in enumerate(windows[14:], start=14):
            analogues = [foresight[earlier] for earlier, _, _ in windows[number - 14 : number]]
            (held,) = _window_values(trailing, start, end)
            assert held == pytest.approx(float(np.quantile(analogues, 0.75)))

    @pytest.mark.parametrize("window_number", [14, 15])
    def test_a_trailing_ceiling_cannot_see_its_own_window_or_after_it(self, window_number: int) -> None:
        """Zero PV and doubled demand from the window's first row on move its perfect_foresight ceiling, the control, and not its trailing one."""
        generation, demand = _trace(self._DAYS)
        start, end, _ = _windows(generation.index, _E7)[window_number]
        dark_generation, heavy_demand = generation.copy(), demand.copy()
        dark_generation.iloc[start:] = 0.0
        heavy_demand.iloc[start:] *= 2.0

        def ceiling(forecast: str, pv: pd.Series, load: pd.Series) -> Optional[float]:
            return grid_charge_ceilings_kwh(forecast, pv, load, _BATTERY, _E7)[start]  # type: ignore[arg-type]

        assert ceiling("trailing_14_days", dark_generation, heavy_demand) == ceiling("trailing_14_days", generation, demand)
        assert ceiling("perfect_foresight", dark_generation, heavy_demand) != ceiling("perfect_foresight", generation, demand)

    def test_each_window_of_a_two_window_day_draws_its_analogues_from_the_same_window(self) -> None:
        tariff = TariffConfig.economy_10()
        generation, demand = _trace(self._DAYS)

        trailing = grid_charge_ceilings_kwh("trailing_14_days", generation, demand, _BATTERY, tariff)
        foresight = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, _BATTERY, tariff)

        windows = _windows(generation.index, tariff)
        clocks = [generation.index[start].strftime("%H:%M") for start, _, _ in windows]
        assert len(set(clocks)) > 1
        forecast_windows = 0
        for number, (start, end, _) in enumerate(windows):
            same_clock = [foresight[windows[earlier][0]] for earlier in range(number) if clocks[earlier] == clocks[number]]
            (held,) = _window_values(trailing, start, end)
            if len(same_clock) < 14:
                assert held is None
            else:
                forecast_windows += 1
                assert held == pytest.approx(float(np.quantile(same_clock[-14:], 0.75)))
        assert forecast_windows >= len(set(clocks))

    def test_a_window_spanning_midnight_draws_its_analogues_only_from_windows_opening_at_its_clock(self) -> None:
        """Off-peak 23:30 to 06:30: the run opens inside a cheap window, whose 00:00 clock never recurs, so that window has no ceiling and is no 23:30 window's analogue."""
        tariff = TariffConfig.economy_7(off_peak_start="23:30", off_peak_end="06:30")
        generation, demand = _trace(self._DAYS)

        trailing = grid_charge_ceilings_kwh("trailing_14_days", generation, demand, _BATTERY, tariff)
        foresight = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, _BATTERY, tariff)

        opening, *late_evening = _windows(generation.index, tariff)
        assert opening[0] == 0
        assert {generation.index[start].strftime("%H:%M") for start, _, _ in late_evening} == {"23:30"}
        assert len(late_evening) == self._DAYS
        assert _window_values(trailing, opening[0], opening[1]) == {None}
        for start, end, _ in late_evening[:14]:
            assert _window_values(trailing, start, end) == {None}
        for number, (start, end, _) in enumerate(late_evening[14:], start=14):
            analogues = [foresight[earlier] for earlier, _, _ in late_evening[number - 14 : number]]
            (held,) = _window_values(trailing, start, end)
            assert held == pytest.approx(float(np.quantile(analogues, 0.75)))

    def test_a_window_the_run_opens_inside_is_no_later_windows_analogue(self) -> None:
        """Zero PV over the opening 00:00 window's horizon, the first day up to 23:30, moves its perfect_foresight ceiling, the control, and no trailing one."""
        tariff = TariffConfig.economy_7(off_peak_start="23:30", off_peak_end="06:30")
        generation, demand = _trace(self._DAYS)
        opening, first_late_evening, *_ = _windows(generation.index, tariff)
        dark_first_day = generation.copy()
        dark_first_day.iloc[: first_late_evening[0]] = 0.0

        def ceilings(forecast: GridChargeForecast, pv: pd.Series) -> tuple[Optional[float], ...]:
            return grid_charge_ceilings_kwh(forecast, pv, demand, _BATTERY, tariff)

        assert opening[2] == first_late_evening[0]
        assert ceilings("perfect_foresight", dark_first_day)[0] != pytest.approx(ceilings("perfect_foresight", generation)[0])
        assert ceilings("trailing_14_days", dark_first_day) == ceilings("trailing_14_days", generation)

    def test_a_derated_battery_is_sized_within_its_derated_envelope(self) -> None:
        """On a sunless day nothing strands the fill, so the ceiling is the top of the SoH-derated envelope, 0.9 x 5 x 0.8 = 3.6 kWh."""
        worn = dataclasses.replace(_BATTERY, soh=0.8)
        generation, demand = _trace(2, pv_scales=(0.0, 0.0))

        ceilings = grid_charge_ceilings_kwh("perfect_foresight", generation, demand, worn, _E7)

        held = [ceiling for ceiling in ceilings if ceiling is not None]
        assert worn.soc_envelope().max_soc_kwh == pytest.approx(3.6)
        assert held and held == pytest.approx([3.6] * len(held))

    @pytest.mark.parametrize(
        "mismatch",
        [
            pytest.param(lambda demand: demand.iloc[:-1], id="shorter"),
            pytest.param(lambda demand: demand.set_axis(demand.index + pd.Timedelta(minutes=1)), id="shifted-index"),
        ],
    )
    def test_generation_and_demand_on_different_rows_are_refused(self, mismatch: object) -> None:
        generation, demand = _trace(1)

        with pytest.raises(ValueError, match="generation_kw and demand_kw"):
            grid_charge_ceilings_kwh("trailing_14_days", generation, mismatch(demand), _BATTERY, _E7)  # type: ignore[operator]
