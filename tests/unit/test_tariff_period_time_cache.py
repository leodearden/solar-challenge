"""TariffPeriod parses its HH:MM strings once, and that cache stays invisible.

Two contracts are pinned here:

* ``get_start_time`` and ``get_end_time`` return the same parsed
  ``datetime.time`` object on every call. A re-parse would hand back an equal
  but different object, because ``datetime.time`` objects are not interned.
* The parsed times are a derived cache, not part of a period's identity. They
  must stay out of ``dataclasses.fields()``: field-driven serialisers
  (``field_tree`` in ``web/field_tree.py``, ``dataclasses.asdict``) cannot
  encode a ``datetime.time`` and would break their round-trip.
"""

import copy
import dataclasses
import json
import pickle
from collections.abc import Callable
from datetime import time

import pandas as pd
import pytest

from solar_challenge.tariff import TariffConfig, TariffPeriod

OFF_PEAK_START = time(0, 30)
OFF_PEAK_END = time(7, 30)


def _off_peak_period() -> TariffPeriod:
    return TariffPeriod("00:30", "07:30", 0.09, "Off-peak")


def _pickle_round_trip(period: TariffPeriod) -> TariffPeriod:
    clone: TariffPeriod = pickle.loads(pickle.dumps(period))
    return clone


class TestTimesAreParsedOnce:
    """The accessors parse each HH:MM string once and return that same object."""

    def test_accessors_return_the_same_parsed_time_object_every_call(self) -> None:
        period = _off_peak_period()

        assert period.get_start_time() is period.get_start_time()
        assert period.get_end_time() is period.get_end_time()

    def test_replace_parses_the_replacement_times(self) -> None:
        original = _off_peak_period()

        moved = dataclasses.replace(original, start_time="10:00", end_time="12:15")

        assert (moved.get_start_time(), moved.get_end_time()) == (
            time(10, 0),
            time(12, 15),
        )
        assert (original.get_start_time(), original.get_end_time()) == (
            OFF_PEAK_START,
            OFF_PEAK_END,
        )

    @pytest.mark.parametrize(
        "clone",
        [copy.copy, copy.deepcopy, _pickle_round_trip],
        ids=["copy", "deepcopy", "pickle"],
    )
    def test_clones_keep_working_parsed_times(
        self, clone: Callable[[TariffPeriod], TariffPeriod]
    ) -> None:
        cloned = clone(_off_peak_period())

        assert (cloned.get_start_time(), cloned.get_end_time()) == (
            OFF_PEAK_START,
            OFF_PEAK_END,
        )
        assert cloned.matches_time(pd.Timestamp("2024-01-15 03:00")) is True
        assert cloned.matches_time(pd.Timestamp("2024-01-15 12:00")) is False


class TestParsedTimesStayOutOfDataclassFields:
    """The cache must not leak into fields(), asdict, equality or repr."""

    def test_fields_are_exactly_the_constructor_arguments(self) -> None:
        assert [f.name for f in dataclasses.fields(TariffPeriod)] == [
            "start_time",
            "end_time",
            "rate_per_kwh",
            "name",
        ]

    def test_asdict_round_trips_through_json(self) -> None:
        period = _off_peak_period()

        restored = TariffPeriod(**json.loads(json.dumps(dataclasses.asdict(period))))

        assert restored == period

    def test_a_whole_tariff_serialises_to_json(self) -> None:
        json.dumps(dataclasses.asdict(TariffConfig.economy_7()))

    def test_equality_hash_and_repr_use_the_declared_fields_only(self) -> None:
        first, second = _off_peak_period(), _off_peak_period()

        assert first == second
        assert hash(first) == hash(second)
        assert repr(first) == (
            "TariffPeriod(start_time='00:30', end_time='07:30', "
            "rate_per_kwh=0.09, name='Off-peak')"
        )
