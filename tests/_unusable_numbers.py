# SPDX-License-Identifier: AGPL-3.0-or-later
"""Numbers a web number field refuses, as tests send them: one of each kind solar_challenge.web.number_fields.as_finite_float refuses.

The kinds are an integer too large for a float, infinity, NaN and a boolean, which float()
would read as 1.0 or 0.0. as_finite_float's own tests, in tests/unit/test_web_number_fields.py,
cover its full matrix, so a field read through it needs only one value of each kind. A field
that passes a boolean on as given, as a fleet form block's other settings do, takes
UNUSABLE_NON_BOOLEAN_NUMBERS.

Usage::

    from tests._unusable_numbers import UNUSABLE_NUMBERS

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    def test_a_fixed_capacity_that_is_not_finite_is_refused_naming_it(value: object) -> None:
        form = {**valid_distribution_form(), "pv": {"capacity_kw": value}}
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config(form)
        assert str(exc_info.value) == f"pv.capacity_kw must be a finite number, got {value!r}"
"""

import pytest

#: One value of each kind as_finite_float refuses, but a boolean.
UNUSABLE_NON_BOOLEAN_NUMBERS = (
    pytest.param(10**400, id="integer-too-large-for-a-float"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("nan"), id="nan"),
)

#: One value of each kind as_finite_float refuses, a boolean included.
UNUSABLE_NUMBERS = (*UNUSABLE_NON_BOOLEAN_NUMBERS, pytest.param(True, id="boolean"))
