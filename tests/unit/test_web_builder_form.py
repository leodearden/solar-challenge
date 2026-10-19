# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builder_form, called directly with form values."""

import math
from collections.abc import Callable

import pytest

pytest.importorskip("flask")

from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, FleetComponent
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES, form_to_fleet_distribution_config
from solar_challenge.web.shared import NotAJsonObject
from tests._fleet_form import valid_distribution_form
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests._whole_number_forms import WHOLE_NUMBER, WHOLE_NUMBER_FORMS, whole_number_forms

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


def _form_with_pv_pool(rows: list[dict[str, object]]) -> dict[str, object]:
    """_ACCEPTED_FORM with its PV a shuffled pool of *rows*, the pv_sp_entries the builder reads."""
    return {**_ACCEPTED_FORM, "pv_distribution_type": "shuffled_pool", "pv_sp_entries": rows}


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

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
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

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
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
        ("changes", "message"),
        [
            pytest.param(
                {"pv_distribution_type": "weighted_discrete", "pv_wd_values": "ab"},
                "pv_wd_values must be a list, got str",
                id="rows-that-are-not-a-list",
            ),
            pytest.param(
                {"pv_distribution_type": "shuffled_pool", "pv_sp_entries": [3]},
                "pv_sp_entries[0] must be a mapping, got int",
                id="row-that-is-not-a-mapping",
            ),
            pytest.param(
                {"load_distribution_type": "weighted_discrete", "load_wd_values": [{"value": 2900}]},
                "load_wd_values[0] must be a mapping with 'value' and 'weight', "
                "got {'value': 2900}",
                id="row-without-its-weight",
            ),
            pytest.param(
                {"battery_distribution_type": "fixed"},
                "battery_distribution_type must be one of normal, uniform, weighted_discrete, "
                "shuffled_pool, got 'fixed'",
                id="type-the-editor-does-not-offer",
            ),
        ],
    )
    def test_a_malformed_distribution_is_refused_with_the_fleet_forms_refusal_naming_the_builders_field(
        self, changes: dict[str, object], message: str
    ) -> None:
        """Each refusal is the fleet form's refusal of the same distribution, under the builder's field names: both forms' distributions are read by one reader."""
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **changes})
        assert str(exc_info.value) == message

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

    @pytest.mark.parametrize("value", WHOLE_NUMBER_FORMS)
    def test_a_number_of_homes_that_is_a_whole_number_in_another_form_is_the_int_it_equals(
        self, value: object
    ) -> None:
        """The number of homes sent as a whole float or a numeric string is the int it equals in the fleet block, not a float or a string."""
        block = scenario_from_builder_form({**_ACCEPTED_FORM, "n_homes": value})["fleet_distribution"]

        assert (type(block["n_homes"]), block["n_homes"]) == (int, WHOLE_NUMBER)

    @pytest.mark.parametrize("count", WHOLE_NUMBER_FORMS)
    def test_a_shuffled_pool_row_count_that_is_a_whole_number_in_another_form_is_the_int_it_equals(
        self, count: object
    ) -> None:
        """A shuffled pool row's count sent as a whole float or a numeric string is the int it equals in the pool's counts, not a float or a string."""
        form = {
            **_ACCEPTED_FORM,
            "pv_distribution_type": "shuffled_pool",
            "pv_sp_entries": [{"value": 3, "count": 2}, {"value": 4, "count": count}],
        }
        pv_block = scenario_from_builder_form(form)["fleet_distribution"]["pv"]

        counts = pv_block["capacity_kw"]["counts"]
        assert [(type(read), read) for read in counts] == [(int, 2), (int, WHOLE_NUMBER)]

    @pytest.mark.parametrize(
        "count",
        [
            pytest.param(-1, id="negative"),
            pytest.param(MAX_FLEET_HOMES + 1, id="one-above-the-fleet-limit"),
            pytest.param(10**12, id="the-count-of-finding-fk-9dd1d9389dd2"),
            pytest.param(1e300, id="huge-float"),
        ],
    )
    def test_a_shuffled_pool_row_count_outside_0_to_the_fleet_limit_is_refused_naming_it(
        self, count: object
    ) -> None:
        """A shuffled pool row's count outside 0 to the dashboard's fleet limit is refused, naming the row's count, the range and the value as sent: 1e300 reads 'got 1e+300', not its 301-digit int."""
        rows = [{"value": 3, "count": 2}, {"value": 4, "count": count}]
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form(_form_with_pv_pool(rows))
        assert str(exc_info.value) == (
            f"pv_sp_entries[1].count must be between 0 and {MAX_FLEET_HOMES}, got {count!r}"
        )

    def test_a_shuffled_pool_whose_counts_total_more_than_the_fleet_limit_is_refused_naming_its_rows_and_the_total(
        self,
    ) -> None:
        """Counts each within the dashboard's fleet limit are refused when together they hold values for more homes than a dashboard fleet has."""
        rows = [{"value": 3, "count": 2}, {"value": 4, "count": MAX_FLEET_HOMES - 1}]
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form(_form_with_pv_pool(rows))
        assert str(exc_info.value) == (
            f"pv_sp_entries counts must total at most {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}"
        )

    def test_shuffled_pool_counts_from_0_to_a_total_of_the_fleet_limit_are_read_as_given(
        self,
    ) -> None:
        """A row may give its value to no home, or to as many homes as a dashboard fleet holds; the pool may total exactly that many values."""
        rows = [{"value": 3, "count": 0}, {"value": 4, "count": MAX_FLEET_HOMES}]
        pv_block = scenario_from_builder_form(_form_with_pv_pool(rows))["fleet_distribution"]["pv"]

        assert pv_block["capacity_kw"]["counts"] == [0, MAX_FLEET_HOMES]


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

    @pytest.mark.parametrize("beyond", ["below", "above"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_fixed_value_beyond_its_components_fixed_range_is_refused_naming_the_range_and_the_value(
        self, component: FleetComponent, beyond: str
    ) -> None:
        """The range's refusal is one of the form's reasons: a scenario reader may refuse the value as well."""
        low, high = component.fixed_range
        value = math.nextafter(low, -math.inf) if beyond == "below" else math.nextafter(high, math.inf)
        assert builder_form_errors(_ACCEPTED_FORM) == [], "premise: the unchanged form is accepted"
        errors = builder_form_errors({**_ACCEPTED_FORM, component.fixed_field: value})
        assert f"{component.heading} must be between {low:g} and {high:g}, got {value!r}." in errors, errors

    @pytest.mark.parametrize("end", ["low", "high"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_fixed_value_at_either_end_of_its_components_fixed_range_is_accepted(
        self, component: FleetComponent, end: str
    ) -> None:
        value = component.fixed_range[0] if end == "low" else component.fixed_range[1]
        assert builder_form_errors({**_ACCEPTED_FORM, component.fixed_field: value}) == []

    @pytest.mark.parametrize("value", WHOLE_NUMBER_FORMS)
    def test_a_number_of_homes_that_is_a_whole_number_in_another_form_is_accepted(
        self, value: object
    ) -> None:
        """The dashboard's limit on the number of homes reads a whole float or a numeric string as the number it equals, as the scenario does, so a form sending one within the limit has no reason to be refused."""
        assert builder_form_errors({**_ACCEPTED_FORM, "n_homes": value}) == []

    @pytest.mark.parametrize("value", whole_number_forms(MAX_FLEET_HOMES + 1))
    def test_a_number_of_homes_above_the_limit_that_is_a_whole_number_in_another_form_is_refused_naming_the_limit(
        self, value: object
    ) -> None:
        """The dashboard's limit on the number of homes reads a whole float or a numeric string as the number it equals, as the scenario does, so one home above the limit sent in any of those forms has the limit's refusal as its one reason."""
        assert builder_form_errors({**_ACCEPTED_FORM, "n_homes": value}) == [
            f"Number of homes must be between 1 and {MAX_FLEET_HOMES:,}."
        ]

    @pytest.mark.parametrize(
        ("rows", "reason"),
        [
            pytest.param(
                [{"value": 4, "count": MAX_FLEET_HOMES + 1}],
                f"pv_sp_entries[0].count must be between 0 and {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="a-count-one-above-the-fleet-limit",
            ),
            pytest.param(
                [{"value": 4, "count": MAX_FLEET_HOMES}, {"value": 5, "count": 1}],
                f"pv_sp_entries counts must total at most {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="counts-totalling-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_a_shuffled_pool_too_large_for_a_dashboard_fleet_is_the_forms_one_reason(
        self, rows: list[dict[str, object]], reason: str
    ) -> None:
        """The refusal comes from the form's conversion, before load_fleet_config would build every value of the pool.

        The pool sent is one value over the limit, never a count such as finding
        fk-9dd1d9389dd2's 10**12, so a regressed bound builds a pool of 10,001 values
        rather than exhausting the host's memory.
        """
        at_limit = [{"value": 4, "count": MAX_FLEET_HOMES}]
        assert builder_form_errors({**_form_with_pv_pool(at_limit), "n_homes": MAX_FLEET_HOMES}) == [], (
            "premise: a pool of the fleet limit's values is accepted for a fleet of that many homes"
        )
        assert builder_form_errors(_form_with_pv_pool(rows)) == [reason]


class TestBothFormsWriteADistributionAlike:
    """The scenario builder's flat fields and the fleet page's nested body write one editor distribution as the same config.py grammar spec."""

    @pytest.mark.parametrize(
        ("fleet_spec", "builder_fields"),
        [
            pytest.param(
                {"type": "normal", "mean": 4.0, "std": 1.0, "min": 2.0, "max": 8.0},
                {
                    "pv_distribution_type": "normal",
                    "pv_mean": 4.0,
                    "pv_std": 1.0,
                    "pv_min": 2.0,
                    "pv_max": 8.0,
                },
                id="normal",
            ),
            pytest.param(
                {"type": "normal", "mean": 4.0},
                {"pv_distribution_type": "normal", "pv_mean": 4.0},
                id="normal-with-only-a-mean",
            ),
            pytest.param(
                {"type": "uniform", "min": 2.0, "max": 8.0},
                {
                    "pv_distribution_type": "uniform",
                    "pv_mean": 5.0,
                    "pv_std": 1.0,
                    "pv_min": 2.0,
                    "pv_max": 8.0,
                },
                id="uniform-beside-the-normals-parameters",
            ),
            pytest.param(
                {"type": "uniform", "max": 8.0},
                {"pv_distribution_type": "uniform", "pv_max": 8.0},
                id="uniform-with-only-a-max",
            ),
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2}, {"value": 5.0, "weight": 1}],
                },
                {
                    "pv_distribution_type": "weighted_discrete",
                    "pv_wd_values": [{"value": 3.0, "weight": 2}, {"value": 5.0, "weight": 1}],
                },
                id="weighted-discrete",
            ),
            pytest.param(
                {"type": "weighted_discrete"},
                {"pv_distribution_type": "weighted_discrete"},
                id="weighted-discrete-without-rows",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": 1}],
                },
                {
                    "pv_distribution_type": "shuffled_pool",
                    "pv_sp_entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": 1}],
                },
                id="shuffled-pool",
            ),
        ],
    )
    def test_the_builder_writes_each_editor_distribution_as_the_fleet_form_does(
        self, fleet_spec: dict[str, object], builder_fields: dict[str, object]
    ) -> None:
        """Each editor distribution, complete or not, becomes the same grammar spec from the builder's pv_* fields as from the fleet form's pv.capacity_kw: neither form invents a parameter the other leaves out."""
        builder_scenario = scenario_from_builder_form({**_ACCEPTED_FORM, **builder_fields})
        fleet_config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": fleet_spec}}
        )

        assert (
            builder_scenario["fleet_distribution"]["pv"]["capacity_kw"]
            == fleet_config["pv"]["capacity_kw"]
        )
