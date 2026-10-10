# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet form, the body fleet-simulator.js's buildPayload() posts, as tests build it.

Usage::

    from tests._fleet_form import FLEET_FORM_BLOCKS, valid_distribution_form

    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    def test_a_null_block_is_read_as_absent(key: str) -> None:
        form = {**valid_distribution_form(), key: None}
"""

from typing import Any

#: The fleet form's component blocks: the pv, battery and load distributions.
FLEET_FORM_COMPONENT_BLOCKS = ("pv", "battery", "load")

#: Every block of the fleet form: its component blocks and the tariff, dispatch_strategy and seg overlays.
FLEET_FORM_BLOCKS = (*FLEET_FORM_COMPONENT_BLOCKS, "tariff", "dispatch_strategy", "seg")


def valid_distribution_form() -> dict[str, Any]:
    """A fleet form that form_to_fleet_distribution_config converts, with all three component blocks.

    Every call builds a new form, nested blocks included, so a test may change its own in place.
    """
    return {
        "n_homes": 2,
        "seed": 1,
        "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
        "battery": {"capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0}},
        "load": {"annual_consumption_kwh": 3500.0},
    }
