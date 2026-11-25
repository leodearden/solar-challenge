# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the loads a home's results carry by name.

Tests cover:
- TestLoads: SimulationResults.loads, the household's load, demand less the additional
  loads, then each additional load, summing to demand
- TestAdditionalLoadsAreRefusedUnlessTheyArePartsOfDemand: construction reads
  additional_loads' keys as load kinds, and refuses a household entry, a load off
  demand's rows, one holding no number or of a bool dtype, and additional loads that
  exceed demand in a row
- TestHeatPumpLoadIsAdditionalLoadsHeatPump: heat_pump_load and
  additional_loads[HEAT_PUMP] are one series, and two different ones are refused
- TestAdditionalLoadsInFramesAndAmounts: to_dataframe writes each additional load under
  its column, from_dataframe reads it back, and each has an energy amount
- TestAdditionalLoadsPickle: results keep their additional loads through pickle, as a
  fleet's worker returns them
"""

import datetime
import pickle

import pandas as pd
import pytest

from solar_challenge.demand import LoadKind
from solar_challenge.home import SeriesRefused, SimulationResults
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow

_WINDOW = SimulationWindow(datetime.date(2024, 3, 30), datetime.date(2024, 4, 1), ONE_MINUTE, "Europe/London")
_ROWS = _WINDOW.rows()
_DEMAND_KW = 3.0
_HEAT_PUMP_KW = 1.0
_EV_KW = 0.5


def _flat(kw: float, index: pd.DatetimeIndex = _ROWS) -> pd.Series:
    """*kw* on every row of *index*."""
    return pd.Series(kw, index=index)


def _results(**given: object) -> SimulationResults:
    """Results on the window's rows demanding _DEMAND_KW, all of it imported, with *given* in place of any of their arguments."""
    series = {
        "generation": _flat(0.0),
        "demand": _flat(_DEMAND_KW),
        "self_consumption": _flat(0.0),
        "battery_charge": _flat(0.0),
        "battery_discharge": _flat(0.0),
        "battery_soc": _flat(0.0),
        "grid_import": _flat(_DEMAND_KW),
        "grid_export": _flat(0.0),
        "import_cost": _flat(0.0),
        "export_revenue": _flat(0.0),
        "tariff_rate": _flat(0.0),
    }
    return SimulationResults(**(series | given))


def _results_with_a_heat_pump_and_an_ev() -> SimulationResults:
    """_results with a _HEAT_PUMP_KW heat pump and a _EV_KW EV among its demand."""
    return _results(additional_loads={LoadKind.HEAT_PUMP: _flat(_HEAT_PUMP_KW), LoadKind.EV: _flat(_EV_KW)})


class TestLoads:
    def test_the_loads_are_the_household_s_then_each_additional_load_in_load_kind_order(self) -> None:
        assert list(_results_with_a_heat_pump_and_an_ev().loads) == [
            LoadKind.HOUSEHOLD,
            LoadKind.HEAT_PUMP,
            LoadKind.EV,
        ]

    def test_the_household_s_load_is_demand_less_the_additional_loads(self) -> None:
        loads = _results_with_a_heat_pump_and_an_ev().loads

        pd.testing.assert_series_equal(
            loads[LoadKind.HOUSEHOLD], _flat(_DEMAND_KW - _HEAT_PUMP_KW - _EV_KW), check_names=False
        )

    def test_the_loads_sum_to_demand(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        pd.testing.assert_series_equal(
            sum(results.loads.values()), results.demand, check_names=False, rtol=0.0, atol=1e-9
        )

    def test_each_load_is_named_its_kind_s_column(self) -> None:
        loads = _results_with_a_heat_pump_and_an_ev().loads

        assert {kind: load.name for kind, load in loads.items()} == {kind: kind.column for kind in LoadKind}

    def test_results_with_no_additional_loads_have_the_household_s_load_alone_which_is_demand(self) -> None:
        results = _results()

        assert list(results.loads) == [LoadKind.HOUSEHOLD]
        pd.testing.assert_series_equal(results.loads[LoadKind.HOUSEHOLD], results.demand, check_names=False)


class TestAdditionalLoadsAreRefusedUnlessTheyArePartsOfDemand:
    def test_a_load_kind_s_value_is_read_as_its_kind(self) -> None:
        results = _results(additional_loads={"ev": _flat(_EV_KW)})

        assert list(results.additional_loads) == [LoadKind.EV]
        assert type(next(iter(results.additional_loads))) is LoadKind

    def test_the_household_s_load_is_refused_as_an_additional_load(self) -> None:
        with pytest.raises(SeriesRefused) as refusal:
            _results(additional_loads={LoadKind.HOUSEHOLD: _flat(1.0)})

        assert refusal.value.column == "household_load_kw"
        assert "household" in str(refusal.value)

    def test_a_load_off_demand_s_rows_is_refused_naming_its_column(self) -> None:
        with pytest.raises(SeriesRefused) as refusal:
            _results(additional_loads={LoadKind.EV: _flat(_EV_KW, _ROWS + pd.Timedelta(minutes=1))})

        assert refusal.value.column == "ev_load_kw"

    def test_additional_loads_above_demand_in_one_row_are_refused_naming_the_household_and_the_row(self) -> None:
        ev = _flat(_EV_KW)
        ev[pd.Timestamp("2024-03-31 02:00", tz="Europe/London")] = _DEMAND_KW + 0.5

        with pytest.raises(SeriesRefused) as refusal:
            _results(additional_loads={LoadKind.EV: ev})

        assert refusal.value.column == "household_load_kw"
        assert "2024-03-31 02:00:00+01:00" in str(refusal.value)

    def test_an_additional_load_holding_no_number_in_a_row_is_refused_naming_its_column(self) -> None:
        ev = _flat(_EV_KW)
        ev.iloc[7] = float("nan")

        with pytest.raises(SeriesRefused) as refusal:
            _results(additional_loads={LoadKind.EV: ev})

        assert refusal.value.column == "ev_load_kw"

    def test_an_additional_load_of_a_bool_dtype_is_refused_naming_its_column(self) -> None:
        with pytest.raises(SeriesRefused) as refusal:
            _results(additional_loads={LoadKind.EV: pd.Series(True, index=_ROWS)})

        assert refusal.value.column == "ev_load_kw"


class TestHeatPumpLoadIsAdditionalLoadsHeatPump:
    def test_a_heat_pump_load_alone_is_the_additional_heat_pump_load(self) -> None:
        heat_pump = _flat(_HEAT_PUMP_KW)

        results = _results(heat_pump_load=heat_pump)

        pd.testing.assert_series_equal(results.additional_loads[LoadKind.HEAT_PUMP], heat_pump, check_names=False)

    def test_an_additional_heat_pump_load_alone_is_the_heat_pump_load(self) -> None:
        heat_pump = _flat(_HEAT_PUMP_KW)

        results = _results(additional_loads={LoadKind.HEAT_PUMP: heat_pump})

        assert results.heat_pump_load is not None
        pd.testing.assert_series_equal(results.heat_pump_load, heat_pump, check_names=False)

    def test_a_heat_pump_load_that_differs_from_the_additional_heat_pump_load_is_refused(self) -> None:
        with pytest.raises(SeriesRefused) as refusal:
            _results(
                heat_pump_load=_flat(_HEAT_PUMP_KW),
                additional_loads={LoadKind.HEAT_PUMP: _flat(_HEAT_PUMP_KW / 2)},
            )

        assert refusal.value.column == "heat_pump_load_kw"


class TestAdditionalLoadsInFramesAndAmounts:
    def test_to_dataframe_writes_each_additional_load_once_under_its_column_and_no_household_load(self) -> None:
        columns = list(_results_with_a_heat_pump_and_an_ev().to_dataframe().columns)

        assert columns.count("heat_pump_load_kw") == 1
        assert columns.count("ev_load_kw") == 1
        assert "household_load_kw" not in columns

    def test_from_dataframe_reads_back_every_load(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        read_back = SimulationResults.from_dataframe(results.to_dataframe(), strategy_name=results.strategy_name)

        assert list(read_back.loads) == list(results.loads)
        for kind, load in results.loads.items():
            pd.testing.assert_series_equal(read_back.loads[kind], load, check_freq=False)

    def test_each_additional_load_has_an_energy_amount(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        assert {"heat_pump_load_kwh", "ev_load_kwh"} <= set(results.per_step_amounts().columns)
        assert {"heat_pump_load_kwh", "ev_load_kwh"} <= set(results.total_amounts())


class TestAdditionalLoadsPickle:
    def test_results_keep_their_additional_loads_through_pickle(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        unpickled = pickle.loads(pickle.dumps(results))

        assert list(unpickled.additional_loads) == [LoadKind.HEAT_PUMP, LoadKind.EV]
        for kind, load in results.additional_loads.items():
            pd.testing.assert_series_equal(unpickled.additional_loads[kind], load)
