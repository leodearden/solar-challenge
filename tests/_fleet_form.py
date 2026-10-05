# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet form, the body fleet-simulator.js's buildPayload() posts, as tests build it.

Usage::

    from tests._fleet_form import FALSY_NON_NULL_VALUES, FLEET_FORM_BLOCKS, VALID_DISTRIBUTION_FORM

    @pytest.mark.parametrize(("value", "type_name"), FALSY_NON_NULL_VALUES)
    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    def test_a_falsy_block_is_refused(key: str, value: object, type_name: str) -> None:
        form = {**VALID_DISTRIBUTION_FORM, key: value}
"""

import pytest

#: A fleet form that form_to_fleet_distribution_config converts, with all three component blocks.
VALID_DISTRIBUTION_FORM: dict = {
    "n_homes": 2,
    "seed": 1,
    "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
    "battery": {"capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0}},
    "load": {"annual_consumption_kwh": 3500.0},
}

#: The fleet form's component blocks: the pv, battery and load distributions.
FLEET_FORM_COMPONENT_BLOCKS = ("pv", "battery", "load")

#: Every block of the fleet form: its component blocks and the tariff, dispatch_strategy and seg overlays.
FLEET_FORM_BLOCKS = (*FLEET_FORM_COMPONENT_BLOCKS, "tariff", "dispatch_strategy", "seg")

#: Each falsy JSON value other than null, with the type name a "must be a mapping" refusal names.
FALSY_NON_NULL_VALUES = (
    pytest.param("", "str", id="empty-string"),
    pytest.param(False, "bool", id="false"),
    pytest.param(0, "int", id="zero"),
    pytest.param([], "list", id="empty-array"),
)
