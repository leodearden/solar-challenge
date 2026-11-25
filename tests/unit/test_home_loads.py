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
- TestSummaryLoadEnergy: SummaryStatistics.load_energy_kwh, {} by default, held by load
  kind, each an energy of at least 0, an infinite one kept, agreeing with total_heat_pump_load_kwh, and
  load_share, each load's share of demand
- TestCalculateSummaryLoadEnergy: calculate_summary fills load_energy_kwh with each
  load's energy, summing to demand's, and the heat-pump fields from it
"""

import copy
import datetime
import math
import pickle

import pandas as pd
import pytest

from solar_challenge.demand import LoadKind
from solar_challenge.home import SeriesRefused, SimulationResults, SummaryStatistics, calculate_summary
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


_TOTAL_DEMAND_KWH = 10.0


def _summary(**given: object) -> SummaryStatistics:
    """A summary of _TOTAL_DEMAND_KWH of demand, all of it imported, with *given* in place of any of its arguments."""
    totals = {
        "total_generation_kwh": 0.0,
        "total_demand_kwh": _TOTAL_DEMAND_KWH,
        "total_self_consumption_kwh": 0.0,
        "total_grid_import_kwh": _TOTAL_DEMAND_KWH,
        "total_grid_export_kwh": 0.0,
        "total_battery_charge_kwh": 0.0,
        "total_battery_discharge_kwh": 0.0,
        "peak_generation_kw": 0.0,
        "peak_demand_kw": 1.0,
        "self_consumption_ratio": 0.0,
        "grid_dependency_ratio": 1.0,
        "export_ratio": 0.0,
        "window": _WINDOW,
        "total_import_cost_gbp": 0.0,
        "total_export_revenue_gbp": 0.0,
        "net_cost_gbp": 0.0,
    }
    return SummaryStatistics(**(totals | given))


class TestSummaryLoadEnergy:
    def test_a_summary_built_without_it_has_no_load_energy(self) -> None:
        assert _summary().load_energy_kwh == {}

    def test_it_is_held_by_load_kind_in_load_kind_order_without_item_assignment(self) -> None:
        energy = _summary(load_energy_kwh={"heat_pump": 2.0, "household": 6.0}).load_energy_kwh

        assert list(energy) == [LoadKind.HOUSEHOLD, LoadKind.HEAT_PUMP]
        assert all(type(kind) is LoadKind for kind in energy)
        with pytest.raises(TypeError):
            energy[LoadKind.EV] = 1.0

    def test_a_key_naming_no_load_kind_is_refused_naming_it(self) -> None:
        with pytest.raises(ValueError, match="boiler"):
            _summary(load_energy_kwh={"boiler": 1.0})

    @pytest.mark.parametrize("energy", [-0.1, math.nan])
    def test_an_energy_that_is_not_a_number_of_at_least_0_is_refused_naming_the_kind_and_value(
        self, energy: float
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            _summary(load_energy_kwh={"heat_pump": energy})

        assert "heat_pump" in str(refusal.value)
        assert str(energy) in str(refusal.value)

    def test_an_infinite_energy_is_kept_as_the_summary_s_other_infinite_totals_are(self) -> None:
        assert _summary(load_energy_kwh={"heat_pump": math.inf}).load_energy_kwh == {LoadKind.HEAT_PUMP: math.inf}

    def test_a_heat_pump_total_that_differs_from_its_load_energy_is_refused_naming_both(self) -> None:
        with pytest.raises(ValueError) as refusal:
            _summary(total_heat_pump_load_kwh=3.0, load_energy_kwh={LoadKind.HEAT_PUMP: 2.0})

        assert "3.0" in str(refusal.value)
        assert "2.0" in str(refusal.value)

    @pytest.mark.parametrize(
        ("total", "energy"),
        [(2.0, {LoadKind.HEAT_PUMP: 2.0}), (None, {LoadKind.HEAT_PUMP: 2.0}), (3.0, {})],
        ids=["equal", "total-unset", "energy-unset"],
    )
    def test_a_heat_pump_total_that_agrees_with_its_load_energy_or_either_unset_constructs(
        self, total: float | None, energy: dict[LoadKind, float]
    ) -> None:
        _summary(total_heat_pump_load_kwh=total, load_energy_kwh=energy)

    def test_a_load_s_share_is_its_energy_over_demand_s_and_0_for_a_load_it_lacks(self) -> None:
        summary = _summary(load_energy_kwh={LoadKind.HOUSEHOLD: 8.0, LoadKind.HEAT_PUMP: 2.0})

        assert summary.load_share(LoadKind.HEAT_PUMP) == pytest.approx(2.0 / _TOTAL_DEMAND_KWH)
        assert summary.load_share(LoadKind.EV) == 0.0

    def test_a_load_s_share_of_no_demand_is_0(self) -> None:
        summary = _summary(
            total_demand_kwh=0.0, total_grid_import_kwh=0.0, load_energy_kwh={LoadKind.HOUSEHOLD: 0.0}
        )

        assert summary.load_share(LoadKind.HOUSEHOLD) == 0.0

    def test_the_summary_pickles_deep_copies_and_hashes_as_an_equal_one(self) -> None:
        summary = _summary(load_energy_kwh={LoadKind.HOUSEHOLD: 8.0, LoadKind.HEAT_PUMP: 2.0})

        assert pickle.loads(pickle.dumps(summary)) == summary
        assert copy.deepcopy(summary) == summary
        assert hash(_summary(load_energy_kwh={"heat_pump": 2.0, "household": 8.0})) == hash(summary)


class TestCalculateSummaryLoadEnergy:
    def test_each_load_s_energy_is_its_kw_over_the_window_summing_to_demand_s(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        summary = calculate_summary(results)

        energy = summary.load_energy_kwh
        assert list(energy) == [LoadKind.HOUSEHOLD, LoadKind.HEAT_PUMP, LoadKind.EV]
        assert sum(energy.values()) == pytest.approx(summary.total_demand_kwh, rel=1e-9)
        for kind, load in results.loads.items():
            assert energy[kind] == results.window.energy_kwh(load)
            assert summary.load_share(kind) == pytest.approx(energy[kind] / summary.total_demand_kwh)

    def test_a_plain_home_s_load_energy_is_its_household_s_alone_which_is_demand_s(self) -> None:
        summary = calculate_summary(_results())

        assert summary.load_energy_kwh == {LoadKind.HOUSEHOLD: pytest.approx(summary.total_demand_kwh)}

    def test_the_heat_pump_fields_follow_its_load_energy(self) -> None:
        results = _results_with_a_heat_pump_and_an_ev()

        summary = calculate_summary(results)

        assert summary.total_heat_pump_load_kwh == summary.load_energy_kwh[LoadKind.HEAT_PUMP]
        assert summary.peak_heat_pump_load_kw == results.additional_loads[LoadKind.HEAT_PUMP].max()
        assert summary.heat_pump_load_ratio == summary.load_share(LoadKind.HEAT_PUMP)

    def test_a_home_without_a_heat_pump_has_no_heat_pump_fields(self) -> None:
        summary = calculate_summary(_results(additional_loads={LoadKind.EV: _flat(_EV_KW)}))

        assert (summary.total_heat_pump_load_kwh, summary.peak_heat_pump_load_kw, summary.heat_pump_load_ratio) == (
            None,
            None,
            None,
        )
