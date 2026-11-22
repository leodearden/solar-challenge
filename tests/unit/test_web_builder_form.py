# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builder_form, called directly with form values."""

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.config import load_fleet_config
from solar_challenge.scenario_writer import scenario_yaml
from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, FleetComponent
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES, form_to_fleet_distribution_config
from solar_challenge.web.request_boundary import NotAJsonObject
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


def _loader_refusal(form: dict[str, object], directory: Path) -> str:
    """The str() of load_fleet_config's refusal of the scenario the builder writes for *form*, read from the YAML text the builder previews, as builder_form_errors reads it."""
    path = directory / "scenario.yaml"
    path.write_text(scenario_yaml(scenario_from_builder_form(form)), encoding="utf-8")
    with pytest.raises(ValueError) as refusal:
        load_fleet_config(path)
    return str(refusal.value)


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
        ("distribution_holding", "written_at"),
        [
            pytest.param(
                lambda value: {"pv_distribution_type": "normal", "pv_mean": value, "pv_std": 1},
                ("pv", "capacity_kw", "mean"),
                id="parameter",
            ),
            pytest.param(
                lambda value: {
                    "load_distribution_type": "weighted_discrete",
                    "load_wd_values": [{"value": value, "weight": 1}],
                },
                ("load", "annual_consumption_kwh", "values", 0),
                id="row-value",
            ),
            pytest.param(
                lambda value: {
                    "battery_distribution_type": "weighted_discrete",
                    "battery_wd_values": [{"value": 5, "weight": value}],
                },
                ("battery", "capacity_kwh", "weights", 0),
                id="row-weight",
            ),
            pytest.param(
                lambda value: {
                    "pv_distribution_type": "shuffled_pool",
                    "pv_sp_entries": [{"value": 4, "count": value}],
                },
                ("pv", "capacity_kw", "counts", 0),
                id="row-count",
            ),
        ],
    )
    def test_a_distribution_number_is_written_as_sent_and_its_refusal_is_the_loaders(
        self,
        distribution_holding: Callable[[object], dict[str, object]],
        written_at: tuple[str | int, ...],
        value: object,
        tmp_path: Path,
    ) -> None:
        """A distribution's parameter, or a row's value, weight or count, holding a number too large for a float, an infinity, NaN or a boolean is written into the scenario as sent, and builder_form_errors reports load_fleet_config's refusal of it: the builder reads no distribution number."""
        form = {**_ACCEPTED_FORM, **distribution_holding(value)}
        written: Any = scenario_from_builder_form(form)["fleet_distribution"]
        for step in written_at:
            written = written[step]
        assert written is value
        assert builder_form_errors(form) == [_loader_refusal(form, tmp_path)]

    def test_a_normal_mean_that_is_not_finite_is_refused_by_the_loaders_naming_mean(
        self, tmp_path: Path
    ) -> None:
        """An infinite pv_mean reaches the scenario as sent, and the form's one reason is load_fleet_config's refusal naming the normal's mean under its YAML path."""
        form = {**_ACCEPTED_FORM, "pv_distribution_type": "normal", "pv_mean": math.inf, "pv_std": 1}
        refusal = _loader_refusal(form, tmp_path)
        assert builder_form_errors(form) == [refusal]
        assert "fleet_distribution.pv.capacity_kw" in refusal
        assert "mean" in refusal

    def test_a_distribution_type_the_editor_does_not_offer_is_written_as_sent_and_its_refusal_is_the_loaders(
        self, tmp_path: Path
    ) -> None:
        """A type the distribution editor does not offer is written into the scenario as sent, and builder_form_errors reports load_fleet_config's refusal of the spec, naming its YAML path."""
        form = {**_ACCEPTED_FORM, "battery_distribution_type": "fixed"}
        assert scenario_from_builder_form(form)["fleet_distribution"]["battery"] == {
            "capacity_kwh": {"type": "fixed"}
        }
        refusal = _loader_refusal(form, tmp_path)
        assert builder_form_errors(form) == [refusal]
        assert "fleet_distribution.battery.capacity_kwh" in refusal

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
        ],
    )
    def test_a_malformed_distribution_is_refused_with_the_fleet_forms_refusal_naming_the_builders_field(
        self, changes: dict[str, object], message: str
    ) -> None:
        """Each refusal of a distribution's shape is the fleet form's refusal of the same distribution, under the builder's field names: both forms' distributions are translated by one translator."""
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **changes})
        assert str(exc_info.value) == message

    def test_a_number_of_homes_with_a_fractional_part_is_refused_naming_it(self) -> None:
        """The number of homes with a fractional part is refused, not truncated."""
        with pytest.raises(ValueError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, "n_homes": 2.5})
        assert str(exc_info.value) == "n_homes must be a whole number, got 2.5"

    @pytest.mark.parametrize("value", WHOLE_NUMBER_FORMS)
    def test_a_number_of_homes_that_is_a_whole_number_in_another_form_is_the_int_it_equals(
        self, value: object
    ) -> None:
        """The number of homes sent as a whole float or a numeric string is the int it equals in the fleet block, not a float or a string."""
        block = scenario_from_builder_form({**_ACCEPTED_FORM, "n_homes": value})["fleet_distribution"]

        assert (type(block["n_homes"]), block["n_homes"]) == (int, WHOLE_NUMBER)

    @pytest.mark.parametrize("count", WHOLE_NUMBER_FORMS)
    def test_a_shuffled_pool_row_count_that_is_a_whole_number_in_another_form_is_written_as_sent_and_loads_as_the_int_it_equals(
        self, count: object
    ) -> None:
        """A shuffled pool row's count sent as a whole float or a numeric string is written into the pool's counts as sent, and the loaders read it as the int it equals: a pool of 2 and that count fills a fleet of 2 + WHOLE_NUMBER homes."""
        form = {
            **_form_with_pv_pool([{"value": 3, "count": 2}, {"value": 4, "count": count}]),
            "n_homes": 2 + WHOLE_NUMBER,
        }
        counts = scenario_from_builder_form(form)["fleet_distribution"]["pv"]["capacity_kw"]["counts"]

        assert counts[1] is count
        assert builder_form_errors(form) == []

    @pytest.mark.parametrize(
        "count",
        [
            pytest.param(-1, id="negative"),
            pytest.param(2.5, id="fraction"),
            pytest.param(MAX_FLEET_HOMES + 1, id="one-above-the-fleet-limit"),
            pytest.param(10**12, id="the-count-of-finding-fk-9dd1d9389dd2"),
            pytest.param(1e300, id="huge-float"),
            pytest.param(MAX_FLEET_HOMES - 1, id="counts-totalling-one-above-the-fleet-limit"),
        ],
    )
    def test_a_shuffled_pool_row_count_the_loaders_refuse_is_written_as_sent_and_their_refusal_is_the_forms_one_reason(
        self, count: object, tmp_path: Path
    ) -> None:
        """A shuffled pool row's count is written into the scenario as sent; ShuffledPoolDistribution refuses one below 0 or with a fractional part, and the fleet's F6 refuses counts that do not total its homes, before any value of the pool is built: n_homes, at most MAX_FLEET_HOMES, bounds every pool."""
        form = _form_with_pv_pool([{"value": 3, "count": 2}, {"value": 4, "count": count}])
        counts = scenario_from_builder_form(form)["fleet_distribution"]["pv"]["capacity_kw"]["counts"]

        assert counts[1] is count
        refusal = _loader_refusal(form, tmp_path)
        assert builder_form_errors(form) == [refusal]
        assert "pv.capacity_kw" in refusal

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
        "rows",
        [
            pytest.param(
                [{"value": 4, "count": MAX_FLEET_HOMES + 1}], id="a-count-one-above-the-fleet-limit"
            ),
            pytest.param(
                [{"value": 4, "count": MAX_FLEET_HOMES}, {"value": 5, "count": 1}],
                id="counts-totalling-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_a_shuffled_pool_too_large_for_a_dashboard_fleet_is_refused_by_the_loaders_or_by_the_number_of_homes(
        self, rows: list[dict[str, object]], tmp_path: Path
    ) -> None:
        """A pool of one value more than the fleet limit is refused by load_fleet_config, whose F6 holds a pool to the fleet's homes before any value of it is built; for a fleet above the limit the dashboard's number of homes is the one reason, and the loaders do not run.

        The pool sent is one value over the limit, never a count such as finding
        fk-9dd1d9389dd2's 10**12, so a regressed bound builds a pool of 10,001 values
        rather than exhausting the host's memory.
        """
        at_limit = [{"value": 4, "count": MAX_FLEET_HOMES}]
        assert builder_form_errors({**_form_with_pv_pool(at_limit), "n_homes": MAX_FLEET_HOMES}) == [], (
            "premise: a pool of the fleet limit's values is accepted for a fleet of that many homes"
        )
        form = _form_with_pv_pool(rows)
        assert builder_form_errors(form) == [_loader_refusal(form, tmp_path)]
        assert builder_form_errors({**form, "n_homes": MAX_FLEET_HOMES + 1}) == [
            f"Number of homes must be between 1 and {MAX_FLEET_HOMES:,}."
        ]


class TestBothFormsWriteADistributionAlike:
    """The scenario builder's flat fields and the fleet page's nested body write one editor distribution as the same fleet_distribution.py grammar spec."""

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
