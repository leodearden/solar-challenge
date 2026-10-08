# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tariff: block and a distribution spec each name their type in a ``type:`` key.

An unknown type is refused, naming every supported type. Each type refuses a block lacking a key
it requires, and reads the numbers it takes as floats.
"""

from typing import Any, Optional

import pytest

from solar_challenge.config import (
    ConfigurationError,
    DistributionSpec,
    ProportionalDistribution,
    parse_fleet_distribution_config,
    parse_tariff_config,
)

_FULL_PERIOD: dict[str, Any] = {"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": 0.25}


def _custom_block_whose_only_period_lacks(key: str) -> dict[str, Any]:
    """Return a custom tariff block holding one period that has every key but *key*."""
    period = {name: value for name, value in _FULL_PERIOD.items() if name != key}
    return {"type": "custom", "periods": [period]}


_TARIFF_BLOCKS_NAMING_NO_TYPE = [
    pytest.param({}, id="absent-type"),
    pytest.param({"type": None}, id="null-type"),
]

_UNKNOWN_TARIFF_TYPES = [
    pytest.param("economy_8", id="unknown-name"),
    pytest.param(7, id="integer"),
    pytest.param(["flat_rate"], id="list"),
    pytest.param({"name": "flat_rate"}, id="mapping"),
]

_TARIFF_BLOCKS_LACKING_A_REQUIRED_KEY = [
    pytest.param(
        {"type": "flat_rate"},
        "flat_rate tariff requires 'rate_per_kwh' field",
        id="flat_rate-absent-rate",
    ),
    pytest.param(
        {"type": "flat_rate", "rate_per_kwh": None},
        "flat_rate tariff requires 'rate_per_kwh' field",
        id="flat_rate-null-rate",
    ),
    pytest.param(
        {"type": "custom"},
        "custom tariff requires 'periods' field",
        id="custom-absent-periods",
    ),
    pytest.param(
        {"type": "custom", "periods": []},
        "custom tariff must have at least one period",
        id="custom-empty-periods",
    ),
    pytest.param(
        {"type": "custom", "periods": None},
        "custom tariff must have at least one period",
        id="custom-null-periods",
    ),
    *(
        pytest.param(
            _custom_block_whose_only_period_lacks(key),
            f"Tariff period requires '{key}' field",
            id=f"custom-period-lacks-{key}",
        )
        for key in _FULL_PERIOD
    ),
]

_INTEGER_RATE_TARIFF_BLOCKS = [
    pytest.param(
        {"type": "flat_rate", "rate_per_kwh": 1},
        [1.0],
        id="flat_rate",
    ),
    pytest.param(
        {"type": "economy_7", "off_peak_rate": 0, "peak_rate": 1},
        [0.0, 1.0],
        id="economy_7",
    ),
    pytest.param(
        {"type": "economy_10", "off_peak_rate": 0, "peak_rate": 1},
        [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        id="economy_10",
    ),
    pytest.param(
        {"type": "custom", "periods": [{**_FULL_PERIOD, "rate_per_kwh": 1}]},
        [1.0],
        id="custom",
    ),
]


_SPEC_PATH = "fleet_distribution.battery.capacity_kwh"


def _parsed_distribution_spec(spec: object) -> DistributionSpec:
    """Parse *spec* as the capacity of the battery in a one-home ``fleet_distribution:`` block."""
    fleet = parse_fleet_distribution_config(
        {"n_homes": 1, "pv": {"capacity_kw": 4.0}, "battery": {"capacity_kwh": spec}}
    )
    assert fleet.battery is not None
    return fleet.battery.capacity_kwh


def _spec_lacking(spec: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a copy of *spec* without *key*."""
    return {name: value for name, value in spec.items() if name != key}


_NON_MAPPING_DISTRIBUTION_SPECS = [
    pytest.param("5kWh", id="string"),
    pytest.param([5.0], id="list"),
]

_DISTRIBUTION_SPECS_NAMING_NO_TYPE = [
    pytest.param({"value": 5.0}, id="absent-type"),
    pytest.param({"type": None, "value": 5.0}, id="null-type"),
]

_UNKNOWN_DISTRIBUTION_TYPES = [
    pytest.param("lognormal", id="unknown-name"),
    pytest.param(3, id="integer"),
    pytest.param(["normal"], id="list"),
]

_SPECS_GIVING_ONLY_THEIR_REQUIRED_KEYS: list[tuple[dict[str, Any], str]] = [
    (
        {"type": "weighted_discrete", "values": [5.0], "weights": [1.0]},
        f"weighted_discrete distribution for '{_SPEC_PATH}' requires 'values' and 'weights'",
    ),
    (
        {"type": "normal", "mean": 5.0, "std": 1.0},
        f"normal distribution for '{_SPEC_PATH}' requires 'mean' and 'std'",
    ),
    (
        {"type": "uniform", "min": 5.0, "max": 6.0},
        f"uniform distribution for '{_SPEC_PATH}' requires 'min' and 'max'",
    ),
    (
        {"type": "fixed", "value": 5.0},
        f"fixed distribution for '{_SPEC_PATH}' requires 'value'",
    ),
    (
        {"type": "shuffled_pool", "values": [5.0], "counts": [1]},
        f"shuffled_pool distribution for '{_SPEC_PATH}' requires 'values' and 'counts'",
    ),
    (
        {"type": "proportional_to", "source": "pv.capacity_kw"},
        f"proportional_to distribution for '{_SPEC_PATH}' requires 'source'",
    ),
]

_DISTRIBUTION_SPECS_LACKING_A_REQUIRED_KEY = [
    pytest.param(_spec_lacking(spec, key), message, id=f"{spec['type']}-absent-{key}")
    for spec, message in _SPECS_GIVING_ONLY_THEIR_REQUIRED_KEYS
    for key in spec
    if key != "type"
]

_MULTIPLIER_MAPPINGS_THAT_ARE_NO_SWEEP = [
    pytest.param({"min": 0.5, "max": 2.0, "steps": 3}, id="untyped"),
    pytest.param({"type": "normal", "mean": 1.0, "std": 0.1}, id="other-type"),
]

_FIXED_SPEC_VALUES = [
    pytest.param(None, None, id="null"),
    pytest.param(5, 5.0, id="integer"),
]


class TestTariffTypes:
    """Tests for the tariff types a tariff: block can name."""

    @pytest.mark.parametrize("block", _TARIFF_BLOCKS_NAMING_NO_TYPE)
    def test_block_naming_no_type_is_refused(self, block: dict[str, Any]) -> None:
        """A block whose type is absent or null is refused for naming none."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_tariff_config(block)
        assert str(refusal.value) == "Tariff configuration requires 'type' field"

    @pytest.mark.parametrize("tariff_type", _UNKNOWN_TARIFF_TYPES)
    def test_unknown_type_is_refused_naming_every_supported_type(
        self, tariff_type: object
    ) -> None:
        """A type that is no supported name, whatever its kind, is refused as unknown."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_tariff_config({"type": tariff_type})
        assert str(refusal.value) == (
            f"Unknown tariff type '{tariff_type}'. "
            "Supported types: flat_rate, economy_7, economy_10, custom"
        )

    @pytest.mark.parametrize(("block", "message"), _TARIFF_BLOCKS_LACKING_A_REQUIRED_KEY)
    def test_block_lacking_a_required_key_is_refused_naming_the_key(
        self, block: dict[str, Any], message: str
    ) -> None:
        """A block lacking a key its type requires is refused, naming that key."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_tariff_config(block)
        assert str(refusal.value) == message

    @pytest.mark.parametrize(("block", "rates"), _INTEGER_RATE_TARIFF_BLOCKS)
    def test_integer_rates_are_read_as_floats(
        self, block: dict[str, Any], rates: list[float]
    ) -> None:
        """Every rate a block gives as an integer comes out of its periods as a float."""
        tariff = parse_tariff_config(block)
        assert tariff is not None
        assert [(type(period.rate_per_kwh), period.rate_per_kwh) for period in tariff.periods] == [
            (float, rate) for rate in rates
        ]


class TestDistributionSpecTypes:
    """Tests for the distribution-spec types a distribution parameter can name."""

    @pytest.mark.parametrize("spec", _NON_MAPPING_DISTRIBUTION_SPECS)
    def test_spec_that_is_no_number_null_or_mapping_is_refused(self, spec: object) -> None:
        """A spec that is not a number, null or a mapping is refused, naming its path."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_distribution_spec(spec)
        assert str(refusal.value) == (
            f"Invalid distribution spec for '{_SPEC_PATH}': expected number, null, or dict"
        )

    @pytest.mark.parametrize("spec", _DISTRIBUTION_SPECS_NAMING_NO_TYPE)
    def test_mapping_naming_no_type_is_refused(self, spec: dict[str, Any]) -> None:
        """A mapping whose type is absent or null is refused, naming the spec's path."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_distribution_spec(spec)
        assert str(refusal.value) == f"Distribution for '{_SPEC_PATH}' requires 'type' field"

    @pytest.mark.parametrize("spec_type", _UNKNOWN_DISTRIBUTION_TYPES)
    def test_unknown_type_is_refused_naming_every_supported_type(
        self, spec_type: object
    ) -> None:
        """A type that is no supported name, whatever its kind, is refused as unknown."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_distribution_spec({"type": spec_type})
        assert str(refusal.value) == (
            f"Unknown distribution type '{spec_type}' for '{_SPEC_PATH}'. Supported: "
            "weighted_discrete, normal, uniform, fixed, shuffled_pool, proportional_to"
        )

    @pytest.mark.parametrize(("spec", "message"), _DISTRIBUTION_SPECS_LACKING_A_REQUIRED_KEY)
    def test_spec_lacking_a_required_key_is_refused_naming_the_key(
        self, spec: dict[str, Any], message: str
    ) -> None:
        """A spec lacking a key its type requires is refused, naming the type, the path and the key."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_distribution_spec(spec)
        assert str(refusal.value) == message

    @pytest.mark.parametrize("multiplier", _MULTIPLIER_MAPPINGS_THAT_ARE_NO_SWEEP)
    def test_proportional_to_multiplier_mapping_that_is_no_sweep_is_refused(
        self, multiplier: dict[str, Any]
    ) -> None:
        """A proportional_to multiplier given as a mapping must be a sweep."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_distribution_spec(
                {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": multiplier}
            )
        assert str(refusal.value) == (
            f"proportional_to multiplier dict for '{_SPEC_PATH}' must have type='sweep'"
        )

    @pytest.mark.parametrize(("value", "expected"), _FIXED_SPEC_VALUES)
    def test_fixed_spec_is_its_value_as_a_float(
        self, value: Optional[int], expected: Optional[float]
    ) -> None:
        """A fixed spec is its value read as a float, or None for a null value."""
        parsed = _parsed_distribution_spec({"type": "fixed", "value": value})
        assert (type(parsed), parsed) == (type(expected), expected)

    def test_proportional_to_spec_naming_only_its_source_has_multiplier_one_and_offset_zero(
        self,
    ) -> None:
        """A proportional_to spec that gives no multiplier and no offset scales its source by 1.0, plus 0.0."""
        parsed = _parsed_distribution_spec({"type": "proportional_to", "source": "pv.capacity_kw"})
        assert parsed == ProportionalDistribution(
            source="pv.capacity_kw", multiplier=1.0, offset=0.0
        )
