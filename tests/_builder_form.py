# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form, the body scenario-builder.js's getFormData() posts, as tests build it.

Usage::

    from tests._builder_form import accepted_builder_form

    def test_a_named_form_is_accepted() -> None:
        assert builder_form_errors(accepted_builder_form()) == []
"""

from typing import Any


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
