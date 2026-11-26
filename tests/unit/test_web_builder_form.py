# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builder_form, called directly with form values."""

import math
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.config import parse_scenario, period_window
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import DistributionSpec, parse_fleet_distribution_config, write_distribution_spec
from solar_challenge.scenario_blocks import parse_seg_rate
from solar_challenge.web import builder_form
from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    FLEET_SIZE_DEFAULT,
    MAX_FLEET_HOMES,
    ComponentLimits,
)
from solar_challenge.web.fleet_config import FLEET_DISTRIBUTION_FORM_KEYS, read_form_fleet
from solar_challenge.web.fleet_scenario import parse_fleet_form
from tests._error_records import error_records
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
    "pv": {"capacity_kw": 4},
    "battery": {"capacity_kwh": 5},
}
"""A builder form builder_form_errors accepts: one home with a fixed PV and battery, and no load block, so the home runs LoadConfig's default consumption."""

_LIMIT_REASON = f"Number of homes must be between 1 and {MAX_FLEET_HOMES:,}."
"""The dashboard's own refusal of a number of homes outside its fleet limit."""


def _with_component(form: dict[str, object], component: ComponentLimits, spec: object) -> dict[str, object]:
    """*form* with *component*'s block holding *spec* as its field, as both fleet pages post it."""
    return {**form, component.key: {component.grammar_key: spec}}


def _with_pv(spec: object, form: dict[str, object] = _ACCEPTED_FORM) -> dict[str, object]:
    """*form* with its pv block holding *spec* as its capacity."""
    return _with_component(form, FLEET_COMPONENTS["pv"], spec)


def _pv_pool(values: list[object], counts: list[object]) -> dict[str, object]:
    """A shuffled pool of *values*, each given to its count of *counts* homes, as the grammar spells it."""
    return {"type": "shuffled_pool", "values": values, "counts": counts}


def _fleet_reader_refusal(form: dict[str, object]) -> str:
    """The str() of read_form_fleet's refusal of the fleet blocks *form* posts, its n_homes and each component block."""
    blocks = {key: form[key] for key in FLEET_DISTRIBUTION_FORM_KEYS if key in form}
    with pytest.raises(ConfigurationError) as refusal:
        read_form_fleet(blocks)
    return str(refusal.value)


def _written_fleet(form: dict[str, object]) -> Any:
    """The fleet_distribution block scenario_from_builder_form writes for *form*."""
    return scenario_from_builder_form(form)["fleet_distribution"]


class TestScenarioFromBuilderForm:
    """The fleet scenario document scenario_from_builder_form builds from a builder form, and its refusals."""

    @pytest.mark.parametrize(("form", "type_name"), _FORMS_THAT_ARE_NOT_JSON_OBJECTS)
    def test_a_form_that_is_not_a_json_object_is_refused_naming_its_type(
        self, form: object, type_name: str
    ) -> None:
        """require_json_object refuses it as the "Builder form", with a ConfigurationError.

        Over HTTP this refusal is unreachable, because request_json_object refuses the
        body first, so this direct call is its only guard.
        """
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_builder_form(form)
        assert str(exc_info.value) == f"Builder form must be a JSON object, got {type_name}"

    @pytest.mark.parametrize(
        "key",
        [
            "pv_distribution_type",
            "pv_capacity_kw",
            "pv_mean",
            "pv_sp_entries",
            "battery_capacity_kwh",
            "battery_wd_values",
            "annual_consumption_kwh",
            "load_distribution_type",
        ],
    )
    def test_a_flat_distribution_field_the_builder_once_sent_is_refused_as_an_unrecognised_key_naming_it(
        self, key: str
    ) -> None:
        """The builder posts each component as its block; a flat field is a key it does not read, never a second spelling of a block."""
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, key: 4})
        assert str(exc_info.value).startswith(f"Unrecognised builder form keys: {key!r}; ")

    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_component_block_is_written_into_the_fleet_distribution_as_sent(
        self, component: ComponentLimits
    ) -> None:
        """Each block the form sends is the fleet_distribution's block for its component, every key and value as sent, none it does not send invented."""
        block = {component.grammar_key: {"type": "normal", "mean": "x", "std": None}, "seed_offset": [1]}
        written = _written_fleet({**_ACCEPTED_FORM, component.key: block})

        assert written[component.key] == block

    def test_a_component_the_form_leaves_out_has_no_block(self) -> None:
        """The fleet_distribution holds the blocks the form sends and its number of homes, and no block for a component it leaves out or sends as null."""
        form = {**_ACCEPTED_FORM, "load": None}

        assert _written_fleet(form) == {"n_homes": 1, "pv": {"capacity_kw": 4}, "battery": {"capacity_kwh": 5}}

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("arm", "field"),
        [
            pytest.param({}, "import_rate", id="rate"),
            pytest.param({}, "n_homes", id="number-of-homes"),
            pytest.param({"location_preset": "custom"}, "latitude", id="custom-coordinate"),
        ],
    )
    def test_a_number_field_that_is_not_a_finite_number_is_refused_naming_it(
        self, arm: dict[str, object], field: str, value: object
    ) -> None:
        """A flat number field holding a number too large for a float, an infinity, NaN or a boolean is refused naming the field.

        *arm* is the rest of the form that makes the builder read *field*.
        """
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, **arm, field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("component", "spec_holding", "written_at"),
        [
            pytest.param("battery", lambda value: value, (), id="fixed-value"),
            pytest.param(
                "pv", lambda value: {"type": "normal", "mean": value, "std": 1}, ("mean",), id="parameter"
            ),
            pytest.param(
                "battery",
                lambda value: {"type": "weighted_discrete", "values": [5], "weights": [value]},
                ("weights", 0),
                id="weight",
            ),
            pytest.param("pv", lambda value: _pv_pool([4], [value]), ("counts", 0), id="count"),
        ],
    )
    def test_a_spec_number_is_written_as_sent_and_the_forms_one_reason_is_the_fleet_readers_refusal_naming_the_forms_field(
        self,
        component: str,
        spec_holding: Callable[[object], object],
        written_at: tuple[str | int, ...],
        value: object,
    ) -> None:
        """A fixed value, a parameter, a weight or a count holding a number too large for a float, an infinity, NaN or a boolean is written into the scenario as sent, and builder_form_errors reports read_form_fleet's refusal of it, naming the field at the form's own path: the builder reads no spec number."""
        limits = FLEET_COMPONENTS[component]
        form = _with_component(_ACCEPTED_FORM, limits, spec_holding(value))
        written: Any = _written_fleet(form)[component][limits.grammar_key]
        for step in written_at:
            written = written[step]
        refusal = _fleet_reader_refusal(form)

        assert written is value
        assert builder_form_errors(form) == [refusal]
        assert refusal.removeprefix("the top level: ").startswith(f"{component}.{limits.grammar_key}")

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    def test_a_pool_value_is_written_as_sent_and_the_forms_one_reason_is_the_readers_refusal_of_the_home_it_draws(
        self, value: object
    ) -> None:
        """A weighted value is held unread by the grammar, so read_form_fleet accepts it, and the form's one reason is parse_scenario's refusal of the home that draws it, as a scenario file's."""
        form = _with_component(
            _ACCEPTED_FORM,
            FLEET_COMPONENTS["load"],
            {"type": "weighted_discrete", "values": [value], "weights": [1]},
        )
        document = scenario_from_builder_form(form)
        with pytest.raises(ConfigurationError) as reader_refusal:
            parse_scenario(document)

        assert document["fleet_distribution"]["load"]["annual_consumption_kwh"]["values"][0] is value
        assert builder_form_errors(form) == [str(reader_refusal.value)]

    @pytest.mark.parametrize(
        ("form", "named"),
        [
            pytest.param(_with_pv({"type": "normal"}), ("pv.capacity_kw", "'mean'", "'std'"), id="E2-normal-without-its-parameters"),
            pytest.param(
                _with_pv({"type": "normal", "mean": 4, "std": 1, "min": 8, "max": 2}),
                ("pv.capacity_kw", "min", "max"),
                id="E6-inverted-clamps",
            ),
            pytest.param(
                _with_pv(_pv_pool([4], [10**12]), {**_ACCEPTED_FORM, "n_homes": 10}),
                ("pv.capacity_kw", "n_homes (10)", str(10**12)),
                id="E7-counts-far-above-the-fleets-homes",
            ),
            pytest.param(
                _with_pv({"type": "normal", "mean": math.inf, "std": 1}),
                ("pv.capacity_kw", "mean"),
                id="normal-mean-not-finite",
            ),
            pytest.param(
                {**_ACCEPTED_FORM, "battery": {"capacity_kwh": {"type": "fixed"}}},
                ("battery.capacity_kwh",),
                id="a-type-the-editor-does-not-offer",
            ),
            pytest.param(
                _with_pv({"type": "weighted_discrete", "values": "ab", "weights": [1]}),
                ("pv.capacity_kw", "values"),
                id="values-that-are-not-a-list",
            ),
            pytest.param(
                _with_pv({"type": "weighted_discrete", "values": [3]}),
                ("pv.capacity_kw", "'weights'"),
                id="values-without-their-weights",
            ),
            pytest.param({**_ACCEPTED_FORM, "pv": "4"}, ("pv",), id="a-block-that-is-not-a-mapping"),
            pytest.param(_with_pv(None), ("pv.capacity_kw", "required"), id="a-cleared-pv-capacity"),
            pytest.param({**_ACCEPTED_FORM, "battery": {"capacity_kwh": -1}}, ("battery.capacity_kwh",), id="a-negative-battery"),
        ],
    )
    def test_a_spec_the_grammar_refuses_is_written_as_sent_and_the_forms_one_fleet_reason_is_read_form_fleets_naming_the_forms_field(
        self, form: dict[str, object], named: tuple[str, ...]
    ) -> None:
        """The builder writes each block as sent and reads it with the fleet page's reader, so a refusal names the field the page posted, never its fleet_distribution path."""
        refusal = _fleet_reader_refusal(form)

        assert {key: _written_fleet(form)[key] for key in ("pv", "battery")} == {
            key: form[key] for key in ("pv", "battery")
        }
        assert builder_form_errors(form) == [refusal]
        assert "fleet_distribution" not in refusal
        assert all(name in refusal for name in named), (refusal, named)

    def test_a_fleet_refusal_follows_the_dashboards_own_reasons(self) -> None:
        """A form without a name and with a refused fleet has the dashboard's reason, then read_form_fleet's."""
        form = {key: value for key, value in _with_pv({"type": "normal"}).items() if key != "name"}

        assert builder_form_errors(form) == ["Scenario name is required.", _fleet_reader_refusal(form)]

    def test_a_number_of_homes_with_a_fractional_part_is_refused_naming_it(self) -> None:
        """The number of homes with a fractional part is refused, not truncated."""
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, "n_homes": 2.5})
        assert str(exc_info.value) == "n_homes must be a whole number, got 2.5"

    def test_a_location_preset_that_is_neither_custom_nor_a_preset_is_refused_naming_it(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_builder_form({**_ACCEPTED_FORM, "location_preset": "atlantis"})
        assert str(exc_info.value).startswith("location_preset must be 'custom' or one of ")
        assert str(exc_info.value).endswith("got 'atlantis'")

    @pytest.mark.parametrize("value", WHOLE_NUMBER_FORMS)
    def test_a_number_of_homes_that_is_a_whole_number_in_another_form_is_the_int_it_equals(
        self, value: object
    ) -> None:
        """The number of homes sent as a whole float or a numeric string is the int it equals in the fleet block, not a float or a string."""
        block = _written_fleet({**_ACCEPTED_FORM, "n_homes": value})

        assert (type(block["n_homes"]), block["n_homes"]) == (int, WHOLE_NUMBER)

    @pytest.mark.parametrize("count", WHOLE_NUMBER_FORMS)
    def test_a_shuffled_pool_count_that_is_a_whole_number_in_another_form_is_written_as_sent_and_loads_as_the_int_it_equals(
        self, count: object
    ) -> None:
        """A shuffled pool's count sent as a whole float or a numeric string is written into the pool's counts as sent, and the fleet's readers read it as the int it equals: a pool of 2 and that count fills a fleet of 2 + WHOLE_NUMBER homes."""
        form = _with_pv(_pv_pool([3, 4], [2, count]), {**_ACCEPTED_FORM, "n_homes": 2 + WHOLE_NUMBER})
        counts = _written_fleet(form)["pv"]["capacity_kw"]["counts"]

        assert counts[1] is count
        assert builder_form_errors(form) == []

    @pytest.mark.parametrize(
        "count",
        [
            pytest.param(-1, id="negative"),
            pytest.param(2.5, id="fraction"),
            pytest.param(0, id="counts-totalling-one-above-the-forms-homes"),
            pytest.param(MAX_FLEET_HOMES + 1, id="one-above-the-fleet-limit"),
            pytest.param(float(MAX_FLEET_HOMES + 1), id="a-whole-float-one-above-the-fleet-limit"),
            pytest.param(MAX_FLEET_HOMES - 1, id="counts-totalling-one-above-the-fleet-limit"),
        ],
    )
    def test_a_shuffled_pool_count_the_grammar_refuses_is_written_as_sent_and_its_refusal_is_the_forms_one_reason(
        self, count: object
    ) -> None:
        """A shuffled pool's count is written into the scenario as sent; ShuffledPoolDistribution refuses one below 0 or with a fractional part, and the fleet's F6 refuses counts that do not total its homes, before any value of the pool is built: n_homes, at most MAX_FLEET_HOMES, bounds every pool."""
        form = _with_pv(_pv_pool([3, 4], [2, count]))
        counts = _written_fleet(form)["pv"]["capacity_kw"]["counts"]
        refusal = _fleet_reader_refusal(form)

        assert counts[1] is count
        assert builder_form_errors(form) == [refusal]
        assert "pv.capacity_kw" in refusal

    def test_shuffled_pool_counts_from_0_to_a_total_of_the_fleet_limit_are_written_as_given(
        self,
    ) -> None:
        """A row may give its value to no home, or to as many homes as a dashboard fleet holds; the pool may total exactly that many values."""
        pool = _written_fleet(_with_pv(_pv_pool([3, 4], [0, MAX_FLEET_HOMES])))["pv"]["capacity_kw"]

        assert pool["counts"] == [0, MAX_FLEET_HOMES]


def _start_specs() -> list[Any]:
    """Each component with each spec its editor starts at, one per editor type, as pytest params."""
    return [
        pytest.param(component, spec, id=f"{component.key}-{each.name}")
        for component in FLEET_COMPONENTS.values()
        for spec, each in zip(component.start.specs, component.editor_types, strict=True)
    ]


class TestBothFleetPagesPostOneSpec:
    """E1: the fleet page and the builder post a component's spec in one shape, read as one fleet."""

    @pytest.mark.parametrize(("component", "spec"), _start_specs())
    def test_a_spec_written_and_posted_by_either_page_reads_as_the_same_draws(
        self, component: ComponentLimits, spec: DistributionSpec
    ) -> None:
        """The start's spec written by write_distribution_spec, posted as the fleet form's block and as the builder form's, is the same spec in each page's scenario document."""
        homes = {"n_homes": FLEET_SIZE_DEFAULT}
        fleet_form = _with_component({**valid_distribution_form(), **homes}, component, write_distribution_spec(spec))
        builder = _with_component({**_ACCEPTED_FORM, **homes}, component, write_distribution_spec(spec))

        fleet_page_draws = getattr(
            parse_fleet_distribution_config(parse_fleet_form(fleet_form).scenario["fleet_distribution"]),
            component.key,
        ).draws
        builder_draws = getattr(
            parse_fleet_distribution_config(scenario_from_builder_form(builder)["fleet_distribution"]),
            component.key,
        ).draws

        assert fleet_page_draws == builder_draws
        assert builder_draws[component.grammar_key] == spec
        assert builder_form_errors(builder) == []


class TestBuilderFormErrors:
    """Every reason builder_form_errors gives for refusing a builder form."""

    @pytest.mark.parametrize(("form", "type_name"), _FORMS_THAT_ARE_NOT_JSON_OBJECTS)
    def test_a_form_that_is_not_a_json_object_has_that_refusal_as_its_one_reason(
        self, form: object, type_name: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The shared rule refuses it before the dashboard's limits read any field of it, and logs nothing: it is a refusal, not a defect.

        Over HTTP this is unreachable, because request_json_object refuses the body
        first, so this direct call is its only guard.
        """
        assert builder_form_errors(form) == [
            f"Builder form must be a JSON object, got {type_name}"
        ]
        assert error_records(caplog) == []

    def test_a_value_error_from_the_reader_that_is_not_a_configuration_error_is_the_one_reason_logged_once_as_a_probable_defect(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The reader is not asked again for the fleet beside it, which would meet the defect, and log it, a second time."""
        reads: list[object] = []

        def parse_scenario_failing(document: Any) -> Any:
            reads.append(document)
            raise ValueError("probe")

        monkeypatch.setattr(builder_form, "parse_scenario", parse_scenario_failing)

        assert builder_form_errors(_ACCEPTED_FORM) == ["probe"]
        assert len(reads) == 1
        [record] = error_records(caplog)
        assert "ValueError" in record.getMessage()

    def test_a_value_error_that_is_not_a_configuration_error_from_the_fleet_read_beside_a_refusal_is_the_one_reason_logged_once(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The reader refuses the document, then fails reading its fleet with the period: and seg: blocks left null."""
        reads: list[object] = []

        def parse_scenario_refusing_then_failing(document: Any) -> Any:
            reads.append(document)
            if len(reads) == 1:
                raise ConfigurationError("refusal")
            raise ValueError("probe")

        monkeypatch.setattr(builder_form, "parse_scenario", parse_scenario_refusing_then_failing)

        assert builder_form_errors(_ACCEPTED_FORM) == ["probe"]
        [record] = error_records(caplog)
        assert "ValueError" in record.getMessage()

    def test_a_value_error_from_the_fleet_reader_that_is_not_a_configuration_error_is_the_one_fleet_reason_logged_once_as_a_probable_defect(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It follows the dashboard's own reasons, as a refusal of the fleet does, and the scenario reader is not asked."""
        scenario_reads: list[object] = []

        def read_form_fleet_failing(blocks: Any) -> Any:
            raise ValueError("probe")

        def parse_scenario_counting(document: Any) -> Any:
            scenario_reads.append(document)
            return parse_scenario(document)

        monkeypatch.setattr(builder_form, "read_form_fleet", read_form_fleet_failing)
        monkeypatch.setattr(builder_form, "parse_scenario", parse_scenario_counting)
        form = {key: value for key, value in _ACCEPTED_FORM.items() if key != "name"}

        assert builder_form_errors(form) == ["Scenario name is required.", "probe"]
        assert scenario_reads == []
        [record] = error_records(caplog)
        assert "ValueError" in record.getMessage()

    def test_a_type_error_from_the_fleet_reader_is_not_a_reason_and_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def read_form_fleet_failing(blocks: Any) -> Any:
            raise TypeError("probe")

        monkeypatch.setattr(builder_form, "read_form_fleet", read_form_fleet_failing)

        with pytest.raises(TypeError, match="probe"):
            builder_form_errors(_ACCEPTED_FORM)

    def test_a_battery_block_setting_a_dispatch_strategy_is_the_one_fleet_reason_naming_the_one_strategy_rule(
        self,
    ) -> None:
        """The builder has no dispatch setting, so every battery takes the default; the refusal is read_form_fleet's, worded for both forms."""
        form = {**_ACCEPTED_FORM, "battery": {"capacity_kwh": 5, "dispatch_strategy": "tou_optimized"}}

        assert builder_form_errors(form) == [
            "battery.dispatch_strategy must be absent or null: a dashboard form gives every "
            "battery one dispatch strategy, its own or the default, got 'tou_optimized'"
        ]

    def test_a_type_error_from_the_reader_is_not_a_reason_and_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def parse_scenario_failing(document: Any) -> Any:
            raise TypeError("probe")

        monkeypatch.setattr(builder_form, "parse_scenario", parse_scenario_failing)

        with pytest.raises(TypeError, match="probe"):
            builder_form_errors(_ACCEPTED_FORM)

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            pytest.param(
                {"import_rate": "nan"},
                "import_rate must be a finite number, got 'nan'",
                id="import-rate",
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

        The dashboard limits also read n_homes, but leave a value their reader refuses to
        scenario_from_builder_form, so it is reported once.
        """
        assert builder_form_errors(_ACCEPTED_FORM) == [], "premise: the unchanged form is accepted"
        assert builder_form_errors({**_ACCEPTED_FORM, **changes}) == [reason]

    @pytest.mark.parametrize("beyond", ["below", "above"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_fixed_value_beyond_its_components_value_range_is_refused_naming_the_range_and_the_value(
        self, component: ComponentLimits, beyond: str
    ) -> None:
        """The one reason is the homes check's, for home 1, whose value is the float the loader holds.

        A battery below 0 never becomes a home: the grammar's presence rule refuses a
        negative capacity first, naming the field at the form's path.
        """
        value_range = component.value_range
        value = (
            math.nextafter(value_range.low, -math.inf)
            if beyond == "below"
            else math.nextafter(value_range.high, math.inf)
        )
        form = _with_component(_ACCEPTED_FORM, component, value)
        reason = (
            _fleet_reader_refusal(form)
            if component.key == "battery" and beyond == "below"
            else f"{component.key}.{component.grammar_key} must be {value_range} for every home, "
            f"got {value!r} for home 1"
        )
        assert builder_form_errors(_ACCEPTED_FORM) == [], "premise: the unchanged form is accepted"
        assert builder_form_errors(form) == [reason]

    def test_a_drawn_value_beyond_its_components_value_range_is_refused_naming_the_home(self) -> None:
        """P15: a normal around 50 kW draws PV no home may hold, refused as a fixed 50 kW is."""
        errors = builder_form_errors(_with_pv({"type": "normal", "mean": 50, "std": 1}))
        assert len(errors) == 1, errors
        assert re.fullmatch(
            r"pv\.capacity_kw must be between 0\.5 and 20 for every home, got \d+\.\d+ for home 1",
            errors[0],
        ), errors

    @pytest.mark.parametrize("end", ["low", "high"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_fixed_value_at_either_end_of_its_components_value_range_is_accepted(
        self, component: ComponentLimits, end: str
    ) -> None:
        value = getattr(component.value_range, end)
        assert builder_form_errors(_with_component(_ACCEPTED_FORM, component, value)) == []

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
        assert builder_form_errors({**_ACCEPTED_FORM, "n_homes": value}) == [_LIMIT_REASON]

    @pytest.mark.parametrize(
        "n_homes",
        [pytest.param(0, id="below"), pytest.param(MAX_FLEET_HOMES + 1, id="above")],
    )
    @pytest.mark.parametrize(
        "pv",
        [
            pytest.param(4, id="a-fleet-the-grammar-accepts"),
            pytest.param({"type": "normal"}, id="a-spec-the-grammar-refuses"),
            pytest.param(_pv_pool([4], [10**12]), id="E7-counts-far-above-the-fleets-homes"),
        ],
    )
    def test_a_number_of_homes_outside_the_limit_is_the_one_reason_with_no_fleet_reason_beside_it(
        self, n_homes: int, pv: object
    ) -> None:
        """The dashboard's limit is the fleet's one reason: neither read_form_fleet nor the scenario reader is asked, so no second refusal of n_homes, and no refusal of the pool it would hold, is listed."""
        assert builder_form_errors(_with_pv(pv, {**_ACCEPTED_FORM, "n_homes": n_homes})) == [_LIMIT_REASON]

    def test_a_shuffled_pool_of_the_fleet_limits_values_is_accepted_for_a_fleet_of_that_many_homes(self) -> None:
        """The largest pool a dashboard fleet holds is one value per home of the largest fleet."""
        form = _with_pv(_pv_pool([4], [MAX_FLEET_HOMES]), {**_ACCEPTED_FORM, "n_homes": MAX_FLEET_HOMES})

        assert builder_form_errors(form) == []

    def test_a_period_day_that_is_not_a_day_is_refused_as_a_scenario_files_is(self) -> None:
        """'2024' is no day, though pd.Timestamp reads it as 2024-01-01."""
        assert (
            "period.start_date: '2024' is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp"
            in builder_form_errors({**_ACCEPTED_FORM, "start_date": "2024"})
        )

    def test_a_period_whose_two_days_are_not_days_is_refused_once_naming_its_start_day(self) -> None:
        """The period's one reason is the reader's first refusal of it, not one reason per day."""
        assert builder_form_errors({**_ACCEPTED_FORM, "start_date": "2024", "end_date": "2024-02-30"}) == [
            "period.start_date: '2024' is not a day: give a date, a 'YYYY-MM-DD' string or a Timestamp"
        ]

    def test_a_period_whose_last_day_precedes_its_first_is_refused_as_a_scenario_files_is(self) -> None:
        with pytest.raises(ConfigurationError) as scenario_file_refusal:
            period_window("2024-08-31", "2024-06-01", timezone="Europe/London")

        errors = builder_form_errors({**_ACCEPTED_FORM, "start_date": "2024-08-31", "end_date": "2024-06-01"})

        assert [error for error in errors if error.startswith("period.")] == [str(scenario_file_refusal.value)]

    def test_a_cleared_period_day_is_listed_once(self) -> None:
        """The one reason is parse_scenario's refusal of the period, as a scenario file's is refused."""
        with pytest.raises(ConfigurationError) as scenario_file_refusal:
            parse_scenario({"period": {"start_date": "2024-06-01"}, "home": {}})
        assert str(scenario_file_refusal.value) == "period: requires 'end_date'"

        assert builder_form_errors({**_ACCEPTED_FORM, "end_date": ""}) == [str(scenario_file_refusal.value)]

    @pytest.mark.parametrize(
        ("changes", "refused_block"),
        [
            pytest.param(
                {"start_date": "2024-08-31", "end_date": "2024-06-01"},
                lambda: period_window("2024-08-31", "2024-06-01", timezone="Europe/London"),
                id="reversed-period",
            ),
            pytest.param(
                {"seg_rate_pence_per_kwh": -1},
                lambda: parse_seg_rate({"rate_pence_per_kwh": -1.0}),
                id="negative-seg-rate",
            ),
        ],
    )
    def test_a_refused_period_or_seg_rate_does_not_hide_a_fleet_reason(
        self, changes: dict[str, object], refused_block: Callable[[], object]
    ) -> None:
        with pytest.raises(ConfigurationError) as block_refusal:
            refused_block()
        component = FLEET_COMPONENTS["pv"]
        pv_reason = (
            f"{component.key}.{component.grammar_key} must be {component.value_range} "
            f"for every home, got {400.0!r} for home 1"
        )
        assert builder_form_errors(_with_pv(400)) == [pv_reason], "premise: the PV alone is refused for home 1"

        errors = builder_form_errors({**_with_pv(400), **changes})

        assert errors == [pv_reason, str(block_refusal.value)]

    def test_a_refused_period_is_the_one_reason_beside_a_refused_seg_rate(self) -> None:
        """The reader reads the period before the SEG rate, and its first refusal of the two is the one listed."""
        with pytest.raises(ConfigurationError) as period_refusal:
            period_window("2024-08-31", "2024-06-01", timezone="Europe/London")

        errors = builder_form_errors(
            {**_ACCEPTED_FORM, "start_date": "2024-08-31", "end_date": "2024-06-01", "seg_rate_pence_per_kwh": -1}
        )

        assert errors == [str(period_refusal.value)]

    @pytest.mark.parametrize(
        "changes",
        [
            pytest.param({"location_preset": "custom", "latitude": 95, "longitude": 0}, id="location"),
            pytest.param({"import_rate": -1}, id="tariff"),
            pytest.param({"battery": {"capacity_kwh": -1}}, id="fleet-distribution"),
        ],
    )
    def test_a_refused_location_tariff_or_fleet_distribution_is_the_one_reason_beside_a_refused_period(
        self, changes: dict[str, object]
    ) -> None:
        refused_period = {"start_date": "2024-08-31", "end_date": "2024-06-01"}
        alone = builder_form_errors({**_ACCEPTED_FORM, **changes})
        assert len(alone) == 1, "premise: the block alone is refused with one reason"
        assert alone != builder_form_errors({**_ACCEPTED_FORM, **refused_period}), (
            "premise: the period alone is refused with another reason"
        )

        assert builder_form_errors({**_ACCEPTED_FORM, **changes, **refused_period}) == alone

    def test_a_refused_seg_rate_is_listed_once(self) -> None:
        with pytest.raises(ConfigurationError) as seg_refusal:
            parse_seg_rate({"rate_pence_per_kwh": -1.0})

        assert builder_form_errors({**_ACCEPTED_FORM, "seg_rate_pence_per_kwh": -1}) == [str(seg_refusal.value)]

    def test_validation_needs_no_temp_directory(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The document is judged in memory: with the temp directory missing, so that any temp file fails, the reader's refusal is still the answer."""
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "absent"))
        with pytest.raises(ConfigurationError) as seg_refusal:
            parse_seg_rate({"rate_pence_per_kwh": -1.0})

        assert builder_form_errors({**_ACCEPTED_FORM, "seg_rate_pence_per_kwh": -1}) == [str(seg_refusal.value)]

