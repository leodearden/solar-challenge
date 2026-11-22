# SPDX-License-Identifier: AGPL-3.0-or-later
"""The per-type table of the distribution grammar, DISTRIBUTION_TYPES, and what derives from it.

Each type a distribution spec names in its ``type:`` key is one record: its title, the keys an
editor holds for it, the keys it holds none for, and its builder. The parser reads each type's
keys and builder, and the types an unknown one is refused naming, from the table.
"""

import json
from typing import Any

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    DISTRIBUTION_TYPES,
    DistributionSpec,
    DistributionType,
    NormalDistribution,
    ProportionalDistribution,
    ShuffledPoolDistribution,
    SpecParameter,
    SpecRows,
    SweepSpec,
    UniformDistribution,
    WeightedDiscreteDistribution,
    parse_fleet_distribution_config,
    write_distribution_spec,
)
from solar_challenge.scenario_blocks import FieldKind

_SPEC_PATH = "fleet_distribution.battery.capacity_kwh"

#: The key a spec is parsed at, by its component: a NUMBER field, and a CHOICE field of ASHP and GSHP.
_KEY_AT: dict[str, str] = {"battery": "capacity_kwh", "heat_pump": "heat_pump_type"}


def _parsed_spec(spec: object, *, at: str = "battery", n_homes: int = 4) -> DistributionSpec:
    """Parse *spec* as the *at* component's key _KEY_AT names, in a ``fleet_distribution:`` block of *n_homes* homes."""
    key = _KEY_AT[at]
    fleet = parse_fleet_distribution_config({"n_homes": n_homes, "pv": {"capacity_kw": 4.0}, at: {key: spec}})
    component = getattr(fleet, at)
    assert component is not None
    return component.draws[key]


#: A spec of each table type, by its name, giving every key the type recognises; a pool's counts total 4 homes.
_GIVEN_EVERY_KEY: dict[str, dict[str, Any]] = {
    "weighted_discrete": {"type": "weighted_discrete", "values": [5.0, 10.0], "weights": [1.0, 1.0]},
    "normal": {"type": "normal", "mean": 5.0, "std": 1.0, "min": 2.0, "max": 8.0},
    "uniform": {"type": "uniform", "min": 2.0, "max": 8.0},
    "fixed": {"type": "fixed", "value": 5.0},
    "shuffled_pool": {"type": "shuffled_pool", "values": [5.0, 10.0], "counts": [2, 2]},
    "proportional_to": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 1.5, "offset": 0.5},
}

_TABLE_TYPES = [
    pytest.param(distribution_type, id=distribution_type.name) for distribution_type in DISTRIBUTION_TYPES.values()
]


def _keys_an_editor_holds() -> list[Any]:
    """Each key an editor holds of each table type, its parameters' and its rows', with whether a spec must give it."""
    held = []
    for distribution_type in DISTRIBUTION_TYPES.values():
        keys = [(parameter.key, parameter.required) for parameter in distribution_type.parameters]
        if distribution_type.rows is not None:
            keys += [(key, True) for key in distribution_type.rows.keys]
        held += [
            pytest.param(distribution_type, key, required, id=f"{distribution_type.name}-without-{key}")
            for key, required in keys
        ]
    return held


#: A spec of each table type, by its name, with the component it is parsed at; a pool's counts total 4 homes.
_SAMPLE_BY_TYPE: dict[str, tuple[DistributionSpec, str]] = {
    "weighted_discrete": (WeightedDiscreteDistribution(values=(None, 5.0, 10.0), weights=(2.0, 1.0, 1.0)), "battery"),
    "normal": (NormalDistribution(mean=5.0, std=1.0, min=2.0), "battery"),
    "uniform": (UniformDistribution(min=2.0, max=8.0), "battery"),
    "fixed": (4.5, "battery"),
    "shuffled_pool": (ShuffledPoolDistribution(values=(None, 5.0, 10.0), counts=(1, 2, 1)), "battery"),
    "proportional_to": (
        ProportionalDistribution(
            source="pv.capacity_kw", multiplier=SweepSpec(min=0.5, max=2.0, steps=3, mode="linear")
        ),
        "battery",
    ),
}

_SPECS = [
    *(pytest.param(spec, at, id=name) for name, (spec, at) in _SAMPLE_BY_TYPE.items()),
    pytest.param(
        WeightedDiscreteDistribution(values=("ASHP", None), weights=(1.0, 3.0)), "heat_pump",
        id="weighted_discrete-of-choices",
    ),
    pytest.param(NormalDistribution(mean=5.0, std=1.0), "battery", id="normal-unclamped"),
    pytest.param(
        ShuffledPoolDistribution(values=("ASHP", "GSHP"), counts=(3, 1)), "heat_pump", id="shuffled_pool-of-choices"
    ),
    pytest.param(
        ProportionalDistribution(source="pv.capacity_kw", multiplier=1.5, offset=0.5), "battery",
        id="proportional_to-a-number",
    ),
    pytest.param(None, "battery", id="null"),
    pytest.param("GSHP", "heat_pump", id="a-choice"),
]


class TestTheTable:
    """The table holds each type the grammar names, with the data an editor renders for it."""

    def test_the_table_holds_the_grammars_six_types_in_order_each_under_its_name(self) -> None:
        assert list(DISTRIBUTION_TYPES) == [
            "weighted_discrete", "normal", "uniform", "fixed", "shuffled_pool", "proportional_to"
        ]
        assert [distribution_type.name for distribution_type in DISTRIBUTION_TYPES.values()] == list(
            DISTRIBUTION_TYPES
        )

    @pytest.mark.parametrize(
        ("name", "title", "parameters", "rows", "unheld_keys"),
        [
            pytest.param(
                "weighted_discrete", "Weighted Discrete", (), SpecRows("weights", "Weight", FieldKind.NUMBER), (),
                id="weighted_discrete",
            ),
            pytest.param(
                "normal",
                "Normal (Gaussian)",
                (
                    SpecParameter("mean", "Mean"),
                    SpecParameter("std", "Std Dev"),
                    SpecParameter("min", "Min (clamp)", required=False),
                    SpecParameter("max", "Max (clamp)", required=False),
                ),
                None,
                (),
                id="normal",
            ),
            pytest.param(
                "uniform", "Uniform", (SpecParameter("min", "Min"), SpecParameter("max", "Max")), None, (),
                id="uniform",
            ),
            pytest.param("fixed", "Fixed Value", (SpecParameter("value", "Value"),), None, (), id="fixed"),
            pytest.param(
                "shuffled_pool", "Shuffled Pool", (), SpecRows("counts", "Count", FieldKind.COUNT), (),
                id="shuffled_pool",
            ),
            pytest.param(
                "proportional_to", "Proportional To", (), None, ("source", "multiplier", "offset"),
                id="proportional_to",
            ),
        ],
    )
    def test_each_type_states_its_title_parameters_rows_and_unheld_keys(
        self,
        name: str,
        title: str,
        parameters: tuple[SpecParameter, ...],
        rows: SpecRows | None,
        unheld_keys: tuple[str, ...],
    ) -> None:
        distribution_type = DISTRIBUTION_TYPES[name]

        assert (
            distribution_type.title,
            distribution_type.parameters,
            distribution_type.rows,
            distribution_type.unheld_keys,
        ) == (title, parameters, rows, unheld_keys)

    @pytest.mark.parametrize(
        ("name", "recognised_keys"),
        [
            pytest.param("weighted_discrete", {"type", "values", "weights"}, id="weighted_discrete"),
            pytest.param("normal", {"type", "mean", "std", "min", "max"}, id="normal"),
            pytest.param("uniform", {"type", "min", "max"}, id="uniform"),
            pytest.param("fixed", {"type", "value"}, id="fixed"),
            pytest.param("shuffled_pool", {"type", "values", "counts"}, id="shuffled_pool"),
            pytest.param("proportional_to", {"type", "source", "multiplier", "offset"}, id="proportional_to"),
        ],
    )
    def test_each_types_recognised_keys_are_type_and_its_parameters_rows_and_unheld_keys(
        self, name: str, recognised_keys: set[str]
    ) -> None:
        assert DISTRIBUTION_TYPES[name].recognised_keys == frozenset(recognised_keys)

    def test_only_a_type_with_unheld_keys_is_editable(self) -> None:
        assert [
            distribution_type.name for distribution_type in DISTRIBUTION_TYPES.values() if not distribution_type.editable
        ] == ["proportional_to"]

    def test_only_fixed_is_the_scalar_form(self) -> None:
        assert [
            distribution_type.name
            for distribution_type in DISTRIBUTION_TYPES.values()
            if distribution_type.is_scalar_form
        ] == ["fixed"]

    def test_a_type_whose_keys_are_not_its_specs_fields_in_order_is_refused_naming_them(self) -> None:
        """A dataclass type's keys are its spec's fields in order, and the scalar form's are one key, else the record is refused naming the type and its keys."""
        with pytest.raises(ConfigurationError) as dataclass_refusal:
            DistributionType(
                "normal", "Normal", NormalDistribution, lambda data, path: None,
                parameters=(SpecParameter("mean", "Mean"),),
            )
        with pytest.raises(ConfigurationError) as scalar_refusal:
            DistributionType(
                "fixed", "Fixed Value", float, lambda data, path: None,
                parameters=(SpecParameter("a", "A"), SpecParameter("b", "B")),
            )

        assert "'normal'" in str(dataclass_refusal.value)
        assert repr(("mean",)) in str(dataclass_refusal.value)
        assert repr(("mean", "std", "min", "max")) in str(dataclass_refusal.value)
        assert "'fixed'" in str(scalar_refusal.value)
        assert repr(("a", "b")) in str(scalar_refusal.value)


class TestTheParserReadsTheTable:
    """The parser reads each type's recognised keys and builder, and the types an unknown one is refused naming, from the table."""

    def test_an_unknown_type_is_refused_naming_the_tables_types(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_spec({"type": "lognormal"})

        assert str(refusal.value) == (
            f"Unknown distribution type 'lognormal' for '{_SPEC_PATH}'. Supported: {', '.join(DISTRIBUTION_TYPES)}"
        )

    @pytest.mark.parametrize("distribution_type", _TABLE_TYPES)
    def test_a_key_outside_a_types_recognised_keys_is_refused_listing_them(
        self, distribution_type: DistributionType
    ) -> None:
        """A spec giving every key its type recognises parses as its type's spec, and the same spec with one more key is refused."""
        given = _GIVEN_EVERY_KEY[distribution_type.name]
        assert set(given) == distribution_type.recognised_keys

        with pytest.raises(ConfigurationError) as refusal:
            _parsed_spec({**given, "bogus": 1})

        assert "'bogus'" in str(refusal.value)
        assert str(refusal.value).endswith(f"recognised keys: {', '.join(sorted(distribution_type.recognised_keys))}")
        assert isinstance(_parsed_spec(given), distribution_type.spec_type)

    @pytest.mark.parametrize(("distribution_type", "key", "required"), _keys_an_editor_holds())
    def test_a_spec_lacking_a_required_parameter_or_row_is_refused_and_one_lacking_an_optional_parameter_is_built(
        self, distribution_type: DistributionType, key: str, required: bool
    ) -> None:
        """The record's required flags are its builder's own: a spec lacking a required key is refused naming the key."""
        spec = {name: value for name, value in _GIVEN_EVERY_KEY[distribution_type.name].items() if name != key}

        if required:
            with pytest.raises(ConfigurationError, match=f"'{key}'"):
                _parsed_spec(spec)
        else:
            assert isinstance(_parsed_spec(spec), distribution_type.spec_type)


class TestTheWriterIsTheParsersInverse:
    """A spec is written as the mapping, or the scalar, that the grammar reads back as it (T1)."""

    @pytest.mark.parametrize(("spec", "at"), _SPECS)
    def test_a_spec_written_by_write_distribution_spec_parses_back_as_itself(
        self, spec: DistributionSpec, at: str
    ) -> None:
        assert _parsed_spec(write_distribution_spec(spec), at=at) == spec

    @pytest.mark.parametrize("scalar", [pytest.param(4.5, id="a-number"), pytest.param(None, id="null"), "GSHP"])
    def test_the_scalar_forms_are_written_as_they_are(self, scalar: DistributionSpec) -> None:
        written = write_distribution_spec(scalar)

        assert (type(written), written) == (type(scalar), scalar)

    @pytest.mark.parametrize("distribution_type", _TABLE_TYPES)
    def test_each_types_write_parses_back_as_the_spec_it_wrote(self, distribution_type: DistributionType) -> None:
        spec, at = _SAMPLE_BY_TYPE[distribution_type.name]

        assert _parsed_spec(distribution_type.write(spec), at=at) == spec

    def test_the_fixed_type_writes_null_as_a_value_that_parses_back_as_null(self) -> None:
        assert _parsed_spec(DISTRIBUTION_TYPES["fixed"].write(None)) is None

    @pytest.mark.parametrize("distribution_type", _TABLE_TYPES)
    def test_a_written_spec_gives_its_type_and_every_recognised_key_as_plain_data(
        self, distribution_type: DistributionType
    ) -> None:
        """A written spec holds lists, never tuples, and a sweep as its mapping: data a JSON body or a YAML file carries."""
        spec, _ = _SAMPLE_BY_TYPE[distribution_type.name]

        written = distribution_type.write(spec)

        assert written["type"] == distribution_type.name
        assert set(written) == distribution_type.recognised_keys
        assert json.loads(json.dumps(written)) == written

    def test_a_value_that_is_no_spec_is_refused_naming_it(self) -> None:
        not_a_spec: Any = SweepSpec(min=0.5, max=2.0, steps=3)

        with pytest.raises(ConfigurationError) as refusal:
            write_distribution_spec(not_a_spec)

        assert repr(not_a_spec) in str(refusal.value)
        assert [name for name in DISTRIBUTION_TYPES if name not in str(refusal.value)] == []
