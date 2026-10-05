# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builder_form, called directly with form values."""

from collections.abc import Callable

import pytest

pytest.importorskip("flask")

from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.shared import NotAJsonObject

_FORMS_THAT_ARE_NOT_JSON_OBJECTS = [
    pytest.param([1], "list", id="array"),
    pytest.param(None, "NoneType", id="null"),
]

_ACCEPTED_FORM: dict[str, object] = {
    "name": "One home",
    "start_date": "2024-06-01",
    "end_date": "2024-06-07",
    "n_homes": 1,
    "pv_capacity_kw": 4,
    "battery_capacity_kwh": 5,
}
"""A builder form builder_form_errors accepts. It needs its battery: without one the builder writes battery: {}, which load_fleet_config refuses."""

# One value of each kind number_fields.as_finite_float refuses; its full matrix is tested there.
_UNUSABLE_NUMBERS = [
    pytest.param(10**400, id="integer-too-large-for-a-float"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(True, id="boolean"),
]


class TestScenarioFromBuilderForm:
    """The fleet scenario document scenario_from_builder_form builds from a builder form, and its refusals."""

    @pytest.mark.parametrize(("form", "type_name"), _FORMS_THAT_ARE_NOT_JSON_OBJECTS)
    def test_a_form_that_is_not_a_json_object_is_refused_naming_its_type(
        self, form: object, type_name: str
    ) -> None:
        """The web's shared NotAJsonObject refuses it as the "Builder form".

        Over HTTP this refusal is unreachable, because request_json_object refuses the
        body first, so this direct call is its only guard.
        """
        with pytest.raises(NotAJsonObject) as exc_info:
            scenario_from_builder_form(form)
        assert str(exc_info.value) == f"Builder form must be a JSON object, got {type_name}"

    @pytest.mark.parametrize("value", _UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("arm", "field"),
        [
            pytest.param({}, "battery_capacity_kwh", id="fixed-value"),
            pytest.param({}, "import_rate", id="rate"),
            pytest.param({}, "n_homes", id="number-of-homes"),
            pytest.param({"location_preset": "custom"}, "latitude", id="custom-coordinate"),
            pytest.param(
                {"pv_distribution_type": "normal", "pv_mean": 4},
                "pv_std",
                id="distribution-parameter",
            ),
        ],
    )
    def test_a_number_field_that_is_not_a_finite_number_is_refused_naming_it(
        self, arm: dict[str, object], field: str, value: object
    ) -> None:
        """A number field holding a number too large for a float, an infinity, NaN or a boolean is refused naming the field.

        *arm* is the rest of the form that makes the builder read *field*.
        """
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **arm, field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("value", _UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("rows_holding", "field"),
        [
            pytest.param(
                lambda value: {
                    "load_distribution_type": "weighted_discrete",
                    "load_wd_values": [{"value": value, "weight": 1}],
                },
                "load_wd_values[0].value",
                id="row-value",
            ),
            pytest.param(
                lambda value: {
                    "battery_distribution_type": "weighted_discrete",
                    "battery_wd_values": [{"value": 5, "weight": value}],
                },
                "battery_wd_values[0].weight",
                id="row-weight",
            ),
            pytest.param(
                lambda value: {
                    "pv_distribution_type": "shuffled_pool",
                    "pv_sp_entries": [{"value": 4, "count": value}],
                },
                "pv_sp_entries[0].count",
                id="row-count",
            ),
        ],
    )
    def test_a_distribution_row_number_that_is_not_a_finite_number_is_refused_naming_its_row(
        self,
        rows_holding: Callable[[object], dict[str, object]],
        field: str,
        value: object,
    ) -> None:
        """A row's value, weight or count holding a number too large for a float, an infinity, NaN or a boolean is refused naming the row's field."""
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **rows_holding(value)})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        ("changes", "field"),
        [
            pytest.param({"n_homes": 2.5}, "n_homes", id="number-of-homes"),
            pytest.param(
                {
                    "pv_distribution_type": "shuffled_pool",
                    "pv_sp_entries": [{"value": 4, "count": 2.5}],
                },
                "pv_sp_entries[0].count",
                id="row-count",
            ),
        ],
    )
    def test_a_count_with_a_fractional_part_is_refused_naming_it(
        self, changes: dict[str, object], field: str
    ) -> None:
        """The number of homes, or a shuffled pool row's count, with a fractional part is refused, not truncated."""
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **changes})
        assert str(exc_info.value) == f"{field} must be a whole number, got 2.5"


class TestBuilderFormErrors:
    """Every reason builder_form_errors gives for refusing a builder form."""

    @pytest.mark.parametrize(("form", "type_name"), _FORMS_THAT_ARE_NOT_JSON_OBJECTS)
    def test_a_form_that_is_not_a_json_object_has_that_refusal_as_its_one_reason(
        self, form: object, type_name: str
    ) -> None:
        """The shared rule refuses it before the dashboard's limits read any field of it.

        Over HTTP this is unreachable, because request_json_object refuses the body
        first, so this direct call is its only guard.
        """
        assert builder_form_errors(form) == [
            f"Builder form must be a JSON object, got {type_name}"
        ]

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            pytest.param(
                {"import_rate": "nan"},
                "import_rate must be a finite number, got 'nan'",
                id="import-rate",
            ),
            pytest.param(
                {"pv_capacity_kw": "nan"},
                "pv_capacity_kw must be a finite number, got 'nan'",
                id="pv-capacity",
            ),
            pytest.param(
                {"n_homes": "inf"}, "n_homes must be a finite number, got 'inf'", id="n-homes"
            ),
        ],
    )
    def test_a_number_field_that_is_not_a_finite_number_is_the_forms_one_reason(
        self, changes: dict[str, object], reason: str
    ) -> None:
        """The refusal naming the field is the form's one reason.

        The dashboard limits also read pv_capacity_kw and n_homes, but leave a value their
        reader refuses to scenario_from_builder_form, so it is reported once.
        """
        assert builder_form_errors(_ACCEPTED_FORM) == [], "premise: the unchanged form is accepted"
        assert builder_form_errors({**_ACCEPTED_FORM, **changes}) == [reason]
