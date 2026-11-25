# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.demand, the loads a home's demand is composed of.

Tests cover:
- LoadKind: the three kinds in order, each with its column, energy column and label
- PerLoad: an immutable mapping of a value per load kind, in LoadKind order, that
  refuses a key naming no kind, pickles, deep-copies and hashes
"""

import copy
import pickle

import pytest

from solar_challenge.demand import LoadKind, PerLoad


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
