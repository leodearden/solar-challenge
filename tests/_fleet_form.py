# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet form, the body fleet-simulator.js's buildPayload() posts, as tests build it, and what a dashboard form's fleet blocks read as.

Usage::

    from tests._fleet_form import FLEET_FORM_BLOCKS, fleet_page_starting_form, start_wire, valid_distribution_form

    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    def test_a_null_block_is_read_as_absent(key: str) -> None:
        form = {**valid_distribution_form(), key: None}

    def test_the_fleet_page_posts_its_pv_fixed_value(client: FlaskClient) -> None:
        pv = FLEET_COMPONENTS["pv"]
        form = {**fleet_page_starting_form(), "pv": {pv.grammar_key: start_wire(pv, SCALAR_FORM)}}
"""

from collections.abc import Mapping
from typing import Any

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import DistributionType, write_distribution_spec
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits, page_limits
from solar_challenge.web.fleet_config import FLEET_DISTRIBUTION_FORM_KEYS, read_form_fleet

#: The fleet form's component blocks: the pv, battery and load distributions.
FLEET_FORM_COMPONENT_BLOCKS = ("pv", "battery", "load")

#: Every block of the fleet form: its component blocks and the tariff, dispatch_strategy and seg overlays.
FLEET_FORM_BLOCKS = (*FLEET_FORM_COMPONENT_BLOCKS, "tariff", "dispatch_strategy", "seg")


def valid_distribution_form() -> dict[str, Any]:
    """A fleet form that parse_fleet_form reads, with all three component blocks, each field a grammar spec.

    Every call builds a new form, nested blocks included, so a test may change its own in place.
    """
    return {
        "n_homes": 2,
        "seed": 1,
        "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
        "battery": {"capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0}},
        "load": {"annual_consumption_kwh": 3500.0},
    }


def form_fleet_blocks(form: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet blocks a dashboard *form* posts, its FLEET_DISTRIBUTION_FORM_KEYS fields, as sent."""
    return {key: form[key] for key in FLEET_DISTRIBUTION_FORM_KEYS if key in form}


def fleet_reader_refusal(form: Mapping[str, Any]) -> str:
    """The str() of read_form_fleet's refusal of the fleet blocks a dashboard *form* posts; the calling test fails if it reads them."""
    with pytest.raises(ConfigurationError) as refusal:
        read_form_fleet(form_fleet_blocks(form))
    return str(refusal.value)


def start_spec(component: ComponentLimits, name: str) -> Any:
    """*component*'s start spec of the editor type named *name*, written as the grammar reads it."""
    (written,) = [
        written
        for written in (write_distribution_spec(spec) for spec in component.start.specs)
        if isinstance(written, dict) and written["type"] == name
    ]
    return written


def start_wire(component: ComponentLimits, editor_type: DistributionType) -> Any:
    """What *component*'s distribution editor posts for its field with *editor_type* chosen: its start's Fixed Value for the scalar form, else start_spec."""
    if editor_type.is_scalar_form:
        return component.start.fixed
    return start_spec(component, editor_type.name)


def fleet_page_starting_form() -> dict[str, Any]:
    """The fleet form the fleet page starts at: page_limits()'s fleet size, seed and days, and each component's editor at the type its card shows."""
    limits = page_limits()
    return {
        "n_homes": limits.fleet_size_default,
        "seed": limits.seed_default,
        "days": limits.default_days,
        **{
            component.key: {component.grammar_key: start_spec(component, component.start.shown)}
            for component in FLEET_COMPONENTS.values()
        },
    }
