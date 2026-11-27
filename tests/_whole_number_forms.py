# SPDX-License-Identifier: AGPL-3.0-or-later
"""A whole number in each form other than an int that a web integer field reads as that int.

solar_challenge.number_fields.as_whole_number refuses a fraction, a boolean and a value
that is not a finite number, and reads a whole number sent as a float, a numeric string or a
whole-float string as the int it equals. Its own tests, in tests/unit/test_number_fields.py,
cover its full matrix, so a field read through it needs only one value of each form.

whole_number_forms spells those forms for any whole number, such as one just beyond a field's
limit. WHOLE_NUMBER_FORMS are the forms of WHOLE_NUMBER, so a test sends the field in each
form and compares what it gets with what WHOLE_NUMBER gets.

Usage::

    from tests._whole_number_forms import WHOLE_NUMBER, WHOLE_NUMBER_FORMS, whole_number_forms

    @pytest.mark.parametrize("days", WHOLE_NUMBER_FORMS)
    def test_days_in_another_form_runs_the_window_of_its_int(days: object) -> None:
        assert parse_date_range({"days": days}) == parse_date_range({"days": WHOLE_NUMBER})

    @pytest.mark.parametrize("n_homes", whole_number_forms(LIMIT + 1))
"""

import pytest


def whole_number_forms(number: int) -> tuple[object, ...]:
    """*number* as a whole float, a numeric string and a whole-float string, each a pytest.param with its form's id."""
    return (
        pytest.param(float(number), id="whole-float"),
        pytest.param(str(number), id="numeric-string"),
        pytest.param(str(float(number)), id="whole-float-string"),
    )


#: The whole number each of WHOLE_NUMBER_FORMS equals.
WHOLE_NUMBER = 7

#: The forms of WHOLE_NUMBER.
WHOLE_NUMBER_FORMS = whole_number_forms(WHOLE_NUMBER)
