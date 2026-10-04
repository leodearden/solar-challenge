# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's form as a fleet scenario: the scenario document a fleet form describes.

A fleet form is the body fleet-simulator.js's buildPayload() posts; this module is the
fleet page's counterpart of builder_form.py.
"""

from collections.abc import Mapping
from typing import Any

import pandas as pd

from solar_challenge.config import (
    generate_homes_from_distribution,
    parse_dispatch_strategy_config,
    parse_fleet_distribution_config,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_config import form_to_fleet_distribution_config
from solar_challenge.web.shared import resolve_location
from solar_challenge.web.simulation_params import parse_date_range

_NAMELESS_FLEET_NAME = "Fleet Distribution Simulation"


def fleet_form_name(form: Mapping[str, Any]) -> Any:
    """The name of the fleet *form* describes: its 'name' as given, or the name a nameless fleet runs as."""
    return form.get("name", _NAMELESS_FLEET_NAME)


def fleet_form_location(form: Mapping[str, Any]) -> Location:
    """The location of the fleet *form* describes: its 'location' as resolve_location reads it, 'bristol' when absent."""
    return resolve_location(form.get("location", "bristol"))


def scenario_from_fleet_form(form: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet scenario document the fleet *form* describes, which load_fleet_config reads back as its fleet.

    The form's distributions are the fleet_distribution: block in config.py's grammar,
    with the form's dispatch strategy in their battery block, where load_fleet_config
    gives it to every battery, as the simulate endpoint's overlay does.  A form without a
    battery gives it to none.  The tariff: and seg: blocks are the form's as given, null
    when it sends none.

    Each value is first checked, as given, by the reader the simulate endpoint and the
    loaders read it with, in the simulate endpoint's order, so a form is refused exactly
    where, and with the message, its simulation is.  The fleet's homes are generated, as
    both do, so a fleet they cannot generate is refused too.

    Raises:
        ValueError, TypeError: from the form's distribution conversion or date range, or
            for a date that does not parse, naming it.
        ConfigurationError: for a block the loaders refuse, or homes they cannot generate.
    """
    distribution = form_to_fleet_distribution_config(dict(form))
    location = fleet_form_location(form)
    generate_homes_from_distribution(parse_fleet_distribution_config(distribution), location)
    parse_tariff_config(form.get("tariff"))
    dispatch_strategy = form.get("dispatch_strategy")
    parse_dispatch_strategy_config(dispatch_strategy)
    parse_seg_rate(form.get("seg"))
    start, end = parse_date_range(form)
    for date in (start, end):
        pd.Timestamp(date, tz=location.timezone)
    if dispatch_strategy is not None and "battery" in distribution:
        distribution["battery"]["dispatch_strategy"] = dispatch_strategy
    return {
        "name": fleet_form_name(form),
        "period": {"start_date": start, "end_date": end},
        "location": location_block(location),
        "fleet_distribution": distribution,
        "tariff": form.get("tariff"),
        "seg": form.get("seg"),
    }
