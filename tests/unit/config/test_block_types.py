# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tariff: block and a distribution spec each name their type in a ``type:`` key.

An unknown type is refused, naming every supported type. Each type refuses a block lacking a key
it requires, and reads the numbers it takes as floats.
"""

from typing import Any

import pytest

from solar_challenge.config import ConfigurationError, parse_tariff_config

_FULL_PERIOD: dict[str, Any] = {"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": 0.25}


def _custom_block_whose_only_period_lacks(key: str) -> dict[str, Any]:
    """Return a custom tariff block holding one period that has every key but *key*."""
    period = {name: value for name, value in _FULL_PERIOD.items() if name != key}
    return {"type": "custom", "periods": [period]}


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


class TestTariffTypes:
    """Tests for the tariff types a tariff: block can name."""

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
