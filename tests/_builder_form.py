# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form, the body scenario-builder.js's getFormData() posts, as tests build it.

Usage::

    from tests._builder_form import accepted_builder_form, builder_page_starting_form

    def test_a_named_form_is_accepted() -> None:
        assert builder_form_errors(accepted_builder_form()) == []

    def test_the_builder_page_starts_at_a_form_it_accepts() -> None:
        assert builder_form_errors(builder_page_starting_form("Opened")) == []
"""

from typing import Any

from solar_challenge.web.fleet_components import FLEET_COMPONENTS, page_limits
from solar_challenge.web.request_boundary import WEB_DEFAULT_LOCATION
from tests._fleet_form import start_spec


def accepted_builder_form() -> dict[str, Any]:
    """A builder form builder_form_errors accepts: one named home with a fixed PV and battery and a period.

    It has no load block, so the home runs LoadConfig's default consumption.  Every call
    builds a new form, nested blocks included, so a test may change its own in place.
    """
    return {
        "name": "One home",
        "start_date": "2024-06-01",
        "end_date": "2024-06-07",
        "n_homes": 1,
        "pv": {"capacity_kw": 4},
        "battery": {"capacity_kwh": 5},
    }


def builder_page_starting_form(name: str) -> dict[str, Any]:
    """The builder form getFormData() posts when the page opens, named *name* as a user names it before Validate or Save.

    It holds page_limits()'s default window, fleet size, seed and flat_rate_start, the preset
    location the page starts at, and each component's editor at the type its card shows. Every
    call builds a new form, nested blocks included, so a test may change its own in place.
    """
    limits = page_limits()
    first_day, last_day = limits.default_window
    return {
        "name": name,
        "description": "",
        "start_date": first_day.isoformat(),
        "end_date": last_day.isoformat(),
        "location_preset": WEB_DEFAULT_LOCATION,
        "n_homes": limits.fleet_size_default,
        "seed": limits.seed_default,
        "import_rate": limits.flat_rate_start,
        "seg_rate_pence_per_kwh": "",
        **{
            component.key: {component.grammar_key: start_spec(component, component.start.shown)}
            for component in FLEET_COMPONENTS.values()
        },
    }
