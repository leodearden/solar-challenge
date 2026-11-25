# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet grammar reads its numbers: each distribution type, SweepSpec and FleetDistributionConfig reads its numbers through number_fields as it is built, and holds the Python float or int it reads."""

import dataclasses
import math
from typing import Any, Callable

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    ComponentDistribution,
    FleetDistributionConfig,
    NormalDistribution,
    ProportionalDistribution,
    ShuffledPoolDistribution,
    SweepSpec,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import as_finite_float, as_whole_number
from solar_challenge.pv import PVConfig
from tests._construction_refusals import construction_refusal, prefixed_construction_refusal

_WEIGHTED_DISCRETE = WeightedDiscreteDistribution(values=(30.0, 40.0), weights=(1.0, 2.0))
_NORMAL = NormalDistribution(mean=35.0, std=8.0, min=15.0, max=50.0)
_UNIFORM = UniformDistribution(min=20.0, max=45.0)
_SHUFFLED_POOL = ShuffledPoolDistribution(values=(30.0, 40.0), counts=(1, 1))
_PROPORTIONAL = ProportionalDistribution(source="pv.capacity_kw", multiplier=2.0, offset=1.0)
_SWEEP = SweepSpec(min=0.5, max=2.0, steps=3)
_FLEET = FleetDistributionConfig(n_homes=2, pv=ComponentDistribution({"capacity_kw": 4.0}), seed=1)

#: Values no number field reads as a number: not finite, a bool, or text float() cannot read.
_NO_FINITE_NUMBERS: tuple[object, ...] = (math.nan, math.inf, -math.inf, True, "x")

#: Values no whole-number field reads as a whole number: those no number field reads, and a fraction.
_NO_WHOLE_NUMBERS: tuple[object, ...] = (*_NO_FINITE_NUMBERS, 2.5)

_Reader = Callable[[Any, str], object]

#: Each type's number fields, by a valid instance of the type, with the reader each is read by and whether it lists its numbers.
_NUMBER_FIELDS: tuple[tuple[object, str, _Reader, bool], ...] = (
    (_WEIGHTED_DISCRETE, "weights", as_finite_float, True),
    (_NORMAL, "mean", as_finite_float, False),
    (_NORMAL, "std", as_finite_float, False),
    (_NORMAL, "min", as_finite_float, False),
    (_NORMAL, "max", as_finite_float, False),
    (_UNIFORM, "min", as_finite_float, False),
    (_UNIFORM, "max", as_finite_float, False),
    (_SHUFFLED_POOL, "counts", as_whole_number, True),
    (_PROPORTIONAL, "multiplier", as_finite_float, False),
    (_PROPORTIONAL, "offset", as_finite_float, False),
    (_SWEEP, "min", as_finite_float, False),
    (_SWEEP, "max", as_finite_float, False),
    (_SWEEP, "steps", as_whole_number, False),
    (_FLEET, "n_homes", as_whole_number, False),
    (_FLEET, "seed", as_whole_number, False),
)


def _bad_values_of(read: _Reader) -> tuple[object, ...]:
    """The values a field read by *read* refuses whatever its bounds."""
    return _NO_WHOLE_NUMBERS if read is as_whole_number else _NO_FINITE_NUMBERS


_ONE_BAD_NUMBER = [
    pytest.param(instance, field, read, listed, bad, id=f"{type(instance).__name__}.{field}-{bad!r}")
    for instance, field, read, listed in _NUMBER_FIELDS
    for bad in _bad_values_of(read)
]


def _with_one_bad_number(instance: Any, field: str, listed: bool, bad: object) -> object:
    """*instance* built again with *bad* as its *field*, or as that field's first number when the field lists its numbers."""
    value = (bad, *getattr(instance, field)[1:]) if listed else bad
    return dataclasses.replace(instance, **{field: value})


class TestEachFleetTypeReadsItsNumbers:
    """Each distribution type, SweepSpec and FleetDistributionConfig reads its numbers as it is built, refusing one its reader refuses in the reader's words, and holds what it reads."""

    @pytest.mark.parametrize(("instance", "field", "read", "listed", "bad"), _ONE_BAD_NUMBER)
    def test_a_number_its_reader_refuses_is_refused_in_the_readers_words(
        self, instance: object, field: str, read: _Reader, listed: bool, bad: object
    ) -> None:
        """A field given a value that is not a finite number, or not a whole one where a count is meant, is refused naming the field, and its index in a list, and the value."""
        name = f"{field}[0]" if listed else field

        with pytest.raises(ConfigurationError) as refusal:
            _with_one_bad_number(instance, field, listed, bad)

        assert str(refusal.value) == construction_refusal(lambda: read(bad, name))

    @pytest.mark.parametrize(
        ("build", "message"),
        [
            pytest.param(
                lambda: dataclasses.replace(_NORMAL, std=-1.0), "std must be at least 0, got -1.0", id="std"
            ),
            pytest.param(
                lambda: dataclasses.replace(_WEIGHTED_DISCRETE, weights=(1.0, -1.0)),
                "weights[1] must be at least 0, got -1.0",
                id="weights",
            ),
            pytest.param(
                lambda: dataclasses.replace(_SHUFFLED_POOL, counts=(1, -1)),
                "counts[1] must be at least 0, got -1",
                id="counts",
            ),
            pytest.param(
                lambda: dataclasses.replace(_SWEEP, steps=1), "steps must be at least 2, got 1", id="steps"
            ),
            pytest.param(
                lambda: dataclasses.replace(_FLEET, n_homes=0), "n_homes must be at least 1, got 0", id="n_homes"
            ),
        ],
    )
    def test_a_number_outside_its_fields_bounds_is_refused_naming_the_bounds(
        self, build: Callable[[], object], message: str
    ) -> None:
        """A number below its field's least value is refused naming the field, the bound and the value."""
        with pytest.raises(ConfigurationError) as refusal:
            build()

        assert str(refusal.value) == message

    def test_a_normal_holds_its_mean_and_std_as_floats_and_its_omitted_bounds_as_none(self) -> None:
        normal = NormalDistribution(mean=4, std=1)

        assert [(type(normal.mean), normal.mean), (type(normal.std), normal.std)] == [(float, 4.0), (float, 1.0)]
        assert (normal.min, normal.max) == (None, None)

    def test_a_shuffled_pool_holds_its_values_as_given_and_its_counts_as_ints(self) -> None:
        """Its values are outcomes, which the home's type reads, so the tuple holds them as given, never read as numbers."""
        pool = ShuffledPoolDistribution(values=[1, "a"], counts=[2.0, 1])

        assert (type(pool.values), [(type(value), value) for value in pool.values]) == (tuple, [(int, 1), (str, "a")])
        assert (type(pool.counts), [(type(count), count) for count in pool.counts]) == (tuple, [(int, 2), (int, 1)])

    def test_a_weighted_discrete_holds_its_values_as_given_and_its_weights_as_floats(self) -> None:
        distribution = WeightedDiscreteDistribution(values=["ASHP", None], weights=[1, 3])

        assert (type(distribution.values), distribution.values) == (tuple, ("ASHP", None))
        assert (
            type(distribution.weights),
            [(type(weight), weight) for weight in distribution.weights],
        ) == (tuple, [(float, 1.0), (float, 3.0)])

    def test_a_proportional_to_keeps_a_sweep_multiplier(self) -> None:
        proportional = ProportionalDistribution(source="pv.capacity_kw", multiplier=_SWEEP)

        assert proportional.multiplier is _SWEEP

    def test_a_proportional_to_holds_its_multiplier_and_offset_as_floats(self) -> None:
        proportional = ProportionalDistribution(source="pv.capacity_kw", multiplier=2, offset=1)

        assert [(type(proportional.multiplier), proportional.multiplier), (type(proportional.offset), proportional.offset)] == [
            (float, 2.0),
            (float, 1.0),
        ]

    def test_a_sweep_holds_its_steps_as_an_int(self) -> None:
        steps = SweepSpec(min=1, max=4, steps=4.0).steps

        assert (type(steps), steps) == (int, 4)

    def test_a_fleet_holds_its_n_homes_and_seed_as_ints(self) -> None:
        fleet = dataclasses.replace(_FLEET, n_homes=3.0, seed=7.0)

        assert [(type(fleet.n_homes), fleet.n_homes), (type(fleet.seed), fleet.seed)] == [(int, 3), (int, 7)]

    def test_a_fleet_with_no_seed_holds_none(self) -> None:
        assert dataclasses.replace(_FLEET, seed=None).seed is None

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda values: WeightedDiscreteDistribution(values=values, weights=(1.0, 1.0)), id="weighted_discrete"),
            pytest.param(lambda values: ShuffledPoolDistribution(values=values, counts=(1, 1)), id="shuffled_pool"),
        ],
    )
    @pytest.mark.parametrize(
        "values",
        [
            pytest.param("ab", id="text"),
            pytest.param(b"ab", id="bytes"),
            pytest.param({"a": 1.0, "b": 2.0}, id="mapping"),
            pytest.param({1.0, 2.0}, id="set"),
            pytest.param(5, id="not-iterable"),
        ],
    )
    def test_values_that_are_no_list_are_refused(self, build: Callable[[object], object], values: object) -> None:
        """A weighted_discrete's or shuffled_pool's values are a list: text, bytes, a mapping, a set, whose order is arbitrary, and a value that is not iterable are refused naming values and the value."""
        with pytest.raises(ConfigurationError) as refusal:
            build(values)

        assert str(refusal.value) == f"values must be a list, got {values!r}"


_TILT_PATH = "fleet_distribution.pv.tilt"
_BATTERY_CAPACITY_PATH = "fleet_distribution.battery.capacity_kwh"
_PV = {"capacity_kw": 4.0}


def _fleet_with_tilt(tilt: dict[str, Any]) -> dict[str, Any]:
    """A fleet_distribution: block of 2 homes with 4 kW of PV whose pv.tilt is *tilt*."""
    return {"n_homes": 2, "pv": {**_PV, "tilt": tilt}}


def _fleet_with_battery_proportional_to_pv(**spec: object) -> dict[str, Any]:
    """A fleet_distribution: block of 2 homes whose battery.capacity_kwh is proportional_to pv.capacity_kw, with *spec*'s multiplier or offset."""
    return {
        "n_homes": 2,
        "pv": _PV,
        "battery": {"capacity_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", **spec}},
    }


class TestAFleetBlockRefusesANumberItsTypeRefusesNamingItsPath:
    """A number a fleet_distribution: block gives a type is passed as written, and the type's refusal of it is named after the path of the spec or block that gave it."""

    @pytest.mark.parametrize(
        ("block", "path", "build"),
        [
            pytest.param(
                _fleet_with_tilt({"type": "normal", "mean": "abc", "std": 1}),
                _TILT_PATH,
                lambda: NormalDistribution(mean="abc", std=1),
                id="normal-mean-text",
            ),
            pytest.param(
                _fleet_with_tilt({"type": "uniform", "min": 10, "max": math.nan}),
                _TILT_PATH,
                lambda: UniformDistribution(min=10, max=math.nan),
                id="uniform-max-nan",
            ),
            pytest.param(
                _fleet_with_tilt({"type": "weighted_discrete", "values": [30], "weights": [True]}),
                _TILT_PATH,
                lambda: WeightedDiscreteDistribution(values=[30], weights=[True]),
                id="weighted_discrete-weight-bool",
            ),
            pytest.param(
                _fleet_with_tilt({"type": "shuffled_pool", "values": [30, 40], "counts": [1.5, 0.5]}),
                _TILT_PATH,
                lambda: ShuffledPoolDistribution(values=[30, 40], counts=[1.5, 0.5]),
                id="shuffled_pool-fractional-counts",
            ),
            pytest.param(
                _fleet_with_battery_proportional_to_pv(offset=True),
                _BATTERY_CAPACITY_PATH,
                lambda: ProportionalDistribution(source="pv.capacity_kw", offset=True),
                id="proportional_to-offset-bool",
            ),
            pytest.param(
                _fleet_with_battery_proportional_to_pv(multiplier=True),
                _BATTERY_CAPACITY_PATH,
                lambda: ProportionalDistribution(source="pv.capacity_kw", multiplier=True),
                id="proportional_to-multiplier-bool",
            ),
            pytest.param(
                _fleet_with_battery_proportional_to_pv(
                    multiplier={"type": "sweep", "min": 0.5, "max": 2.0, "steps": 2.5}
                ),
                f"{_BATTERY_CAPACITY_PATH}.multiplier",
                lambda: SweepSpec(min=0.5, max=2.0, steps=2.5),
                id="sweep-fractional-steps",
            ),
            pytest.param(
                {"n_homes": 2.7, "pv": _PV},
                "fleet_distribution",
                lambda: FleetDistributionConfig(n_homes=2.7, pv=ComponentDistribution(_PV)),
                id="fractional-n_homes",
            ),
            pytest.param(
                {"n_homes": 2, "seed": True, "pv": _PV},
                "fleet_distribution",
                lambda: FleetDistributionConfig(n_homes=2, pv=ComponentDistribution(_PV), seed=True),
                id="bool-seed",
            ),
        ],
    )
    def test_the_refusal_is_the_types_after_the_path(
        self, block: dict[str, Any], path: str, build: Callable[[], object]
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config(block)

        assert str(refusal.value) == prefixed_construction_refusal(path, build)

    def test_a_fractional_n_homes_is_refused_naming_the_block_and_the_value(self) -> None:
        """C1: a fleet of 2.7 homes is refused, where it ran 2."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config({"n_homes": 2.7, "pv": _PV})

        assert str(refusal.value) == "fleet_distribution: n_homes must be a whole number, got 2.7"


#: Values a fleet block gives every home that are not numbers: a bool, not finite, text, even text float() reads, or a list.
_NO_NUMBERS_EVERY_HOME_IS_GIVEN = [
    pytest.param(True, id="True"),
    pytest.param(False, id="False"),
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="-inf"),
    pytest.param("4", id="numeric-text"),
    pytest.param("5kWh", id="text"),
    pytest.param([5.0], id="list"),
]


class TestAValueEveryHomeIsGivenIsReadAtParse:
    """A number a fleet block gives every home, as a scalar or a fixed spec's value, is read when the block is parsed, naming the parameter's path, whichever way the block writes it."""

    @pytest.mark.parametrize("bad", _NO_NUMBERS_EVERY_HOME_IS_GIVEN)
    def test_a_scalar_that_is_no_number_is_refused_naming_its_path(self, bad: object) -> None:
        """C4 is the True case, which gave every home 1.0 kW."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config({"n_homes": 1, "pv": {"capacity_kw": bad}})

        assert str(refusal.value) == f"fleet_distribution.pv.capacity_kw must be a finite number, got {bad!r}"

    @pytest.mark.parametrize("bad", _NO_NUMBERS_EVERY_HOME_IS_GIVEN)
    def test_a_fixed_value_that_is_no_number_is_refused_naming_its_parameters_path(self, bad: object) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config({"n_homes": 1, "pv": {**_PV, "tilt": {"type": "fixed", "value": bad}}})

        assert str(refusal.value) == f"fleet_distribution.pv.tilt must be a finite number, got {bad!r}"


class TestACodeBuiltBareNumberIsReadByTheHomesType:
    """A ComponentDistribution built in code may give every home a bare value; the sampler hands it on as given, and the home's type reads it, naming the component and the home."""

    @pytest.mark.parametrize(
        ("components", "label", "build"),
        [
            pytest.param(
                {"pv": ComponentDistribution({"capacity_kw": True})},
                "fleet_distribution.pv: home 1",
                lambda: PVConfig(capacity_kw=True),
                id="pv.capacity_kw",
            ),
            pytest.param(
                {"pv": ComponentDistribution({"capacity_kw": 4.0, "tilt": True})},
                "fleet_distribution.pv: home 1",
                lambda: PVConfig(capacity_kw=4.0, tilt=True),
                id="pv.tilt",
            ),
            pytest.param(
                {"pv": ComponentDistribution(_PV), "load": ComponentDistribution({"annual_consumption_kwh": True})},
                "fleet_distribution.load: home 1",
                lambda: LoadConfig(annual_consumption_kwh=True),
                id="load.annual_consumption_kwh",
            ),
        ],
    )
    def test_a_bool_is_refused_by_the_homes_type_not_read_as_one(
        self, components: dict[str, ComponentDistribution], label: str, build: Callable[[], object]
    ) -> None:
        """A True was read as 1.0 before any type saw it: a 1.0 kW home."""
        fleet = FleetDistributionConfig(n_homes=1, seed=1, **components)

        with pytest.raises(ConfigurationError) as refusal:
            generate_homes_from_distribution(fleet, Location.bristol())

        assert str(refusal.value) == prefixed_construction_refusal(label, build)
