# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.demand, the loads a home's demand is composed of.

Tests cover:
- LoadKind: the three kinds in order, each with its column, energy column and label
- PerLoad: an immutable mapping of a value per load kind, in LoadKind order, that
  refuses a key naming no kind, pickles, deep-copies and hashes
- compose_demand: the household's load alone, or with a heat pump's and an EV's, each
  on the window's rows under its kind's column; a heat pump refuses a temperature
  that is not one year of hourly rows
- Demand: refuses loads without the household's, and a load off the window's rows,
  naming the first row that differs
"""

import copy
import datetime
import pickle

import pandas as pd
import pytest

from solar_challenge.demand import Demand, DemandInputs, LoadKind, PerLoad, compose_demand
from solar_challenge.ev import EVConfig, generate_ev_charging_profile
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, interpolate_to_minute_resolution, simulate_pv_output
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._synthetic_weather import synthetic_tmy

_WINDOW = SimulationWindow(datetime.date(2024, 3, 30), datetime.date(2024, 4, 1), ONE_MINUTE, "Europe/London")
_LOAD = LoadConfig(3400, use_stochastic=False)
_EV = EVConfig("7kW", 18, 7, 35, "none")


class TestLoadKind:
    def test_the_kinds_are_household_heat_pump_and_ev_in_that_order(self) -> None:
        assert list(LoadKind) == [LoadKind.HOUSEHOLD, LoadKind.HEAT_PUMP, LoadKind.EV]
        assert [kind.value for kind in LoadKind] == ["household", "heat_pump", "ev"]

    def test_each_kind_s_column_is_its_value_load_kw_and_its_energy_column_its_value_load_kwh(self) -> None:
        assert [kind.column for kind in LoadKind] == ["household_load_kw", "heat_pump_load_kw", "ev_load_kw"]
        assert [kind.energy_column for kind in LoadKind] == [
            "household_load_kwh",
            "heat_pump_load_kwh",
            "ev_load_kwh",
        ]

    def test_each_kind_s_label_is_how_a_report_names_it(self) -> None:
        assert [kind.label for kind in LoadKind] == ["Household", "Heat pump", "EV charging"]

    def test_a_kind_is_read_from_its_value(self) -> None:
        assert LoadKind("ev") is LoadKind.EV


class TestPerLoad:
    def test_it_holds_its_kinds_in_load_kind_order_whatever_the_order_given(self) -> None:
        by_kind = PerLoad({"ev": 2.0, "household": 1.0})

        assert list(by_kind) == [LoadKind.HOUSEHOLD, LoadKind.EV]
        assert all(type(kind) is LoadKind for kind in by_kind)
        assert by_kind == {LoadKind.HOUSEHOLD: 1.0, LoadKind.EV: 2.0}

    def test_a_key_naming_no_kind_is_refused_naming_it_and_the_kinds(self) -> None:
        with pytest.raises(ValueError) as refusal:
            PerLoad({"boiler": 1.0})

        message = str(refusal.value)
        assert "'boiler'" in message
        for kind in LoadKind:
            assert f"'{kind.value}'" in message

    def test_it_has_no_item_assignment(self) -> None:
        by_kind = PerLoad({LoadKind.HOUSEHOLD: 1.0})

        with pytest.raises(TypeError):
            by_kind[LoadKind.EV] = 1.0

    def test_changing_the_dict_it_was_built_from_does_not_change_it(self) -> None:
        source = {LoadKind.HOUSEHOLD: 1.0}
        by_kind = PerLoad(source)

        source[LoadKind.EV] = 2.0

        assert by_kind == {LoadKind.HOUSEHOLD: 1.0}

    def test_it_pickles_deep_copies_and_hashes_by_its_items(self) -> None:
        by_kind = PerLoad({LoadKind.HOUSEHOLD: 1.0, LoadKind.HEAT_PUMP: 0.5})

        assert pickle.loads(pickle.dumps(by_kind)) == by_kind
        assert copy.deepcopy(by_kind) == by_kind
        assert hash(PerLoad({"heat_pump": 0.5, "household": 1.0})) == hash(by_kind)

    def test_an_empty_one_equals_an_empty_dict(self) -> None:
        assert PerLoad({}) == {}


@pytest.fixture(scope="module")
def tmy_inputs() -> DemandInputs:
    """The window's inputs from a synthetic TMY year: its hourly air temperature, and a 4 kW Bristol PV's generation at one minute."""
    tmy = synthetic_tmy()
    minute_generation = interpolate_to_minute_resolution(
        simulate_pv_output(PVConfig(capacity_kw=4.0), Location.bristol(), tmy)
    )
    return DemandInputs(_WINDOW, tmy["temp_air"], minute_generation, None)


class TestComposeDemand:
    def test_a_home_with_no_heat_pump_and_no_ev_demands_its_household_s_load_alone(
        self, tmy_inputs: DemandInputs
    ) -> None:
        demand = compose_demand(_LOAD, None, None, tmy_inputs)

        assert list(demand.loads) == [LoadKind.HOUSEHOLD]
        pd.testing.assert_series_equal(
            demand.loads[LoadKind.HOUSEHOLD], generate_load_profile(_LOAD, _WINDOW), check_names=False
        )

    def test_a_heat_pump_s_and_an_ev_s_loads_join_the_household_s_on_the_window_s_rows(
        self, tmy_inputs: DemandInputs
    ) -> None:
        demand = compose_demand(_LOAD, HeatPumpConfig.default_ashp(), _EV, tmy_inputs)

        assert list(demand.loads) == [LoadKind.HOUSEHOLD, LoadKind.HEAT_PUMP, LoadKind.EV]
        for load in demand.loads.values():
            pd.testing.assert_index_equal(load.index, _WINDOW.rows())
        assert len(_WINDOW.rows()) == 4260

    def test_its_total_is_its_loads_summed(self, tmy_inputs: DemandInputs) -> None:
        demand = compose_demand(_LOAD, HeatPumpConfig.default_ashp(), _EV, tmy_inputs)

        loads = demand.loads
        pd.testing.assert_series_equal(
            demand.total_kw,
            loads[LoadKind.HOUSEHOLD] + loads[LoadKind.HEAT_PUMP] + loads[LoadKind.EV],
            check_names=False,
            rtol=1e-12,
        )

    def test_its_additional_loads_are_every_load_but_the_household_s(self, tmy_inputs: DemandInputs) -> None:
        demand = compose_demand(_LOAD, HeatPumpConfig.default_ashp(), _EV, tmy_inputs)

        assert list(demand.additional()) == [LoadKind.HEAT_PUMP, LoadKind.EV]

    def test_the_ev_s_load_is_its_charging_on_the_window(self, tmy_inputs: DemandInputs) -> None:
        demand = compose_demand(_LOAD, HeatPumpConfig.default_ashp(), _EV, tmy_inputs)

        pd.testing.assert_series_equal(
            demand.loads[LoadKind.EV], generate_ev_charging_profile(_EV, _WINDOW, tariff=None), check_names=False
        )

    def test_each_load_is_named_its_kind_s_column(self, tmy_inputs: DemandInputs) -> None:
        demand = compose_demand(_LOAD, HeatPumpConfig.default_ashp(), _EV, tmy_inputs)

        assert {kind: load.name for kind, load in demand.loads.items()} == {kind: kind.column for kind in LoadKind}

    def test_a_heat_pump_refuses_a_temperature_that_is_not_one_year_of_hourly_rows_naming_its_rows(
        self, tmy_inputs: DemandInputs
    ) -> None:
        one_day = DemandInputs(_WINDOW, synthetic_tmy()["temp_air"].iloc[:24], tmy_inputs.minute_generation_kw, None)

        with pytest.raises(ValueError) as refusal:
            compose_demand(_LOAD, HeatPumpConfig.default_ashp(), None, one_day)

        named = ("24 rows", "(8,760 to 8,784)", "not one year of hourly rows")
        assert [value for value in named if value not in str(refusal.value)] == []


def _household_on(index: pd.DatetimeIndex) -> pd.Series:
    """A 1 kW household load on *index*."""
    return pd.Series(1.0, index=index)


class TestDemand:
    def test_loads_without_the_household_s_are_refused_naming_it(self) -> None:
        with pytest.raises(ValueError, match="household"):
            Demand(_WINDOW, {LoadKind.EV: _household_on(_WINDOW.rows())})

    def test_a_load_a_minute_off_the_window_s_rows_is_refused_naming_its_kind_and_the_first_row_that_differs(
        self,
    ) -> None:
        rows = _WINDOW.rows()
        shifted = rows + pd.Timedelta(minutes=1)

        with pytest.raises(ValueError) as refusal:
            Demand(_WINDOW, {LoadKind.HOUSEHOLD: _household_on(shifted)})

        named = ("household", "row 0", str(shifted[0]), str(rows[0]))
        assert [value for value in named if value not in str(refusal.value)] == []

    def test_a_load_that_stops_short_of_the_window_s_rows_is_refused_naming_the_first_row_it_lacks(self) -> None:
        rows = _WINDOW.rows()
        first_lacking = len(rows) - 10

        with pytest.raises(ValueError) as refusal:
            Demand(_WINDOW, {LoadKind.HOUSEHOLD: _household_on(rows[:first_lacking])})

        named = ("household", f"row {first_lacking:,}", "no row", str(rows[first_lacking]))
        assert [value for value in named if value not in str(refusal.value)] == []
