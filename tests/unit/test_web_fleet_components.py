# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of solar_challenge.web.fleet_components, what the dashboard's forms accept and start at, of the two fleet pages that render each component's card from it, and of the form pages that render their bounds and starting values from page_limits()."""

import dataclasses
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask, render_template_string
from flask.testing import FlaskClient

import solar_challenge.web
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    DISTRIBUTION_TYPES,
    DistributionSpec,
    NormalDistribution,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    editor_types,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
    write_distribution_spec,
)
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import Interval
from solar_challenge.scenario_blocks import BATTERY_BLOCK, LOAD_BLOCK, PV_BLOCK, ComponentBlock, FieldKind
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, SHORT_WINDOW_START
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    FULL_YEAR_DAYS_SENTINEL,
    MAX_DAYS,
    MAX_FLEET_HOMES,
    MAX_FLEET_SEED,
    FLEET_SIZE_DEFAULT,
    ComponentLimits,
    EditorStart,
    PageLimits,
    days_window,
    page_limits,
    read_fleet_seed,
    read_fleet_size,
    refuse_homes_outside_ranges,
)
from tests._css_classes import names_palette
from tests._html_labels import labelled_inputs
from tests._html_page import (
    counts_of,
    element_attributes,
    element_count,
    headings,
    script_text_by_id,
    texts_after,
)
from tests._html_select_options import options_of_each

#: The pages whose forms render their bounds and starting values from page_limits().
_FORM_PAGES = ("/simulate/home", "/simulate/fleet", "/scenarios/builder", "/scenarios/sweep")

#: The fleet_distribution: blocks of a fleet whose every home holds a value inside each component's range.
_HOMES_INSIDE_EVERY_RANGE: Mapping[str, Mapping[str, object]] = {
    "pv": {"capacity_kw": 4.0},
    "battery": {"capacity_kwh": 5.0},
    "load": {"annual_consumption_kwh": 3500},
}


def _editor_scopes(page: str) -> list[str | None]:
    """The x-data of each distribution editor of *page*, in page order."""
    return [
        attributes["x-data"]
        for attributes in element_attributes(page, "div")
        if (attributes.get("x-data") or "").startswith("distributionEditor(")
    ]


def _bounds_of_input(page: str, element_id: str) -> tuple[str | None, str | None]:
    """The (min, max) of the one input of *page* whose id is *element_id*."""
    (attributes,) = [
        attributes for attributes in element_attributes(page, "input") if attributes.get("id") == element_id
    ]
    return attributes.get("min"), attributes.get("max")


def _click_handlers(page: str, prefix: str) -> list[str | None]:
    """The @click of each button of *page* whose @click starts with *prefix*, in page order."""
    return [
        attributes.get("@click")
        for attributes in element_attributes(page, "button")
        if (attributes.get("@click") or "").startswith(prefix)
    ]


def _day_choice_captions(limits: PageLimits) -> list[str]:
    """The caption of each of *limits*' day choices: '1 year' for the full year, else '<days> days'."""
    return ["1 year" if days == limits.full_year_days else f"{days} days" for days in limits.day_choices]


def _fleet_homes(n_homes: int = 3, **blocks: object) -> list[HomeConfig]:
    """The homes of a fleet of *n_homes* whose fleet_distribution: blocks are *blocks* over _HOMES_INSIDE_EVERY_RANGE's, generated at Bristol as fleet_scenario generates a fleet form's homes."""
    fleet = parse_fleet_distribution_config(
        {"n_homes": n_homes, "seed": 42, **_HOMES_INSIDE_EVERY_RANGE, **blocks}
    )
    return generate_homes_from_distribution(fleet, Location.bristol())


def _block_holding(component: ComponentLimits, value: object) -> dict[str, dict[str, object]]:
    """The fleet_distribution: block of *component* holding *value* as its spec."""
    return {component.key: {component.grammar_key: value}}


class TestFleetComponents:
    """The fleet components FLEET_COMPONENTS defines, and the invariants each one keeps."""

    def test_the_components_are_pv_battery_and_load_each_listed_under_its_own_key(self) -> None:
        """The keys are the builder form's field prefixes and the fleet_distribution blocks, and their order is both pages' card order."""
        assert list(FLEET_COMPONENTS) == ["pv", "battery", "load"]
        assert all(component.key == key for key, component in FLEET_COMPONENTS.items())

    def test_each_component_bounds_a_homes_value_by_its_value_range(self) -> None:
        assert all(isinstance(component, ComponentLimits) for component in FLEET_COMPONENTS.values())
        assert {key: component.value_range for key, component in FLEET_COMPONENTS.items()} == {
            "pv": Interval(0.5, 20),
            "battery": Interval(0, 100),
            "load": Interval(500, 20000),
        }

    @pytest.mark.parametrize("beyond", ["below", "above"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_start_whose_fixed_value_lies_beyond_the_value_range_is_refused_naming_the_component_the_range_and_the_value(
        self, component: ComponentLimits, beyond: str
    ) -> None:
        value_range = component.value_range
        value = (
            math.nextafter(value_range.low, -math.inf)
            if beyond == "below"
            else math.nextafter(value_range.high, math.inf)
        )
        with pytest.raises(ValueError) as exc_info:
            replace(component, start=replace(component.start, fixed=value))
        assert str(exc_info.value) == (
            f"start.fixed of fleet component {component.key!r} must lie within its value_range, "
            f"{value_range}, got {value!r}"
        )

    @pytest.mark.parametrize(
        ("component", "block"),
        [
            pytest.param(FLEET_COMPONENTS["pv"], PV_BLOCK, id="pv"),
            pytest.param(FLEET_COMPONENTS["battery"], BATTERY_BLOCK, id="battery"),
            pytest.param(FLEET_COMPONENTS["load"], LOAD_BLOCK, id="load"),
        ],
    )
    def test_each_components_editor_types_are_those_its_fields_kind_draws_and_its_scalar_form_is_the_tables(
        self, component: ComponentLimits, block: ComponentBlock[Any]
    ) -> None:
        (scalar_form,) = [each for each in DISTRIBUTION_TYPES.values() if each.is_scalar_form]
        assert component.block is block
        assert component.field_kind is component.block.fleet[component.grammar_key].kind
        assert component.editor_types == editor_types(component.field_kind)
        assert component.scalar_form is scalar_form

    @pytest.mark.parametrize(
        ("key", "shown", "fixed", "specs"),
        [
            pytest.param(
                "pv",
                "shuffled_pool",
                4.0,
                (
                    WeightedDiscreteDistribution((3.0, 4.0, 5.0, 6.0), (20, 40, 30, 10)),
                    NormalDistribution(4.0, 1.0, 2.0, 8.0),
                    UniformDistribution(2.0, 8.0),
                    ShuffledPoolDistribution((3.0, 4.0, 5.0, 6.0), (20, 40, 30, 10)),
                ),
                id="pv",
            ),
            pytest.param(
                "battery",
                "shuffled_pool",
                5.0,
                (
                    WeightedDiscreteDistribution((0.0, 5.0, 10.0), (40, 40, 20)),
                    NormalDistribution(5.0, 2.0, 0.0, 15.0),
                    UniformDistribution(0.0, 15.0),
                    ShuffledPoolDistribution((0.0, 5.0, 10.0), (40, 40, 20)),
                ),
                id="battery",
            ),
            pytest.param(
                "load",
                "normal",
                3500,
                (
                    WeightedDiscreteDistribution((2900, 3500, 4500), (30, 40, 30)),
                    NormalDistribution(3400, 800, 2000, 6000),
                    UniformDistribution(2000, 6000),
                    ShuffledPoolDistribution((2900, 3500, 4500), (30, 40, 30)),
                ),
                id="load",
            ),
        ],
    )
    def test_each_components_start_is_the_fleet_pages_distribution_as_the_editor_holds_it(
        self, key: str, shown: str, fixed: float, specs: tuple[DistributionSpec, ...]
    ) -> None:
        """Its editor_state() shows *shown*, holds *fixed* at Fixed Value, and holds each editor type's spec as written, without its type, in editor_types order."""
        component = FLEET_COMPONENTS[key]
        written = [write_distribution_spec(spec) for spec in specs]
        assert all(isinstance(each, dict) for each in written)
        state = component.start.editor_state()
        assert state == {
            "type": shown,
            "fixed": fixed,
            "specs": {
                each["type"]: {name: value for name, value in each.items() if name != "type"}
                for each in written
                if isinstance(each, dict)
            },
        }
        assert list(state["specs"]) == [each.name for each in component.editor_types]

    def test_editor_state_is_the_distribution_editors_dist(self) -> None:
        """The shape templates/components/distribution-editor.html documents, which each component's start writes into #page-limits: the type shown, the fixed value, and each type's spec as written, a null clamp as null."""
        start = EditorStart(
            shown="",
            fixed=4.0,
            specs=(
                WeightedDiscreteDistribution((3.0, 5.0), (20, 80)),
                NormalDistribution(4.0, 1.0),
                UniformDistribution(2.0, 8.0),
                ShuffledPoolDistribution((3.0, None), (60, 40)),
            ),
        )
        component = replace(FLEET_COMPONENTS["pv"], start=start)
        assert component.start.editor_state() == {
            "type": "",
            "fixed": 4.0,
            "specs": {
                "weighted_discrete": {"values": [3.0, 5.0], "weights": [20.0, 80.0]},
                "normal": {"mean": 4.0, "std": 1.0, "min": None, "max": None},
                "uniform": {"min": 2.0, "max": 8.0},
                "shuffled_pool": {"values": [3.0, None], "counts": [60, 40]},
            },
        }

    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_start_whose_shuffled_pool_does_not_total_the_default_fleet_size_is_refused_naming_the_component_and_the_counts(
        self, component: ComponentLimits
    ) -> None:
        specs = tuple(
            ShuffledPoolDistribution((1.0, 2.0), (FLEET_SIZE_DEFAULT, 1))
            if isinstance(spec, ShuffledPoolDistribution)
            else spec
            for spec in component.start.specs
        )
        with pytest.raises(ValueError) as exc_info:
            replace(component, start=replace(component.start, specs=specs))
        assert str(exc_info.value) == (
            f"start.specs of fleet component {component.key!r} must hold shuffled pools whose counts "
            f"total FLEET_SIZE_DEFAULT, {FLEET_SIZE_DEFAULT}, got {(FLEET_SIZE_DEFAULT, 1)!r}"
        )
        assert FLEET_SIZE_DEFAULT == 100

    @pytest.mark.parametrize(
        "edit",
        [
            pytest.param(lambda specs: specs[:-1], id="missing-a-type"),
            pytest.param(lambda specs: (*specs[:-1], UniformDistribution(1.0, 2.0)), id="another-type"),
            pytest.param(lambda specs: (specs[1], specs[0], *specs[2:]), id="out-of-order"),
        ],
    )
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_start_not_holding_one_spec_of_each_editor_type_in_order_is_refused_naming_the_component_and_the_specs(
        self,
        component: ComponentLimits,
        edit: Callable[[tuple[DistributionSpec, ...]], tuple[DistributionSpec, ...]],
    ) -> None:
        specs = edit(component.start.specs)
        names = ", ".join(each.name for each in component.editor_types)
        with pytest.raises(ValueError) as exc_info:
            replace(component, start=replace(component.start, specs=specs))
        assert str(exc_info.value) == (
            f"start.specs of fleet component {component.key!r} must be one spec of each of its "
            f"editor types, in order ({names}), got {specs!r}"
        )

    @pytest.mark.parametrize("shown", ["fixed", "proportional_to", "bogus"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_start_showing_a_type_that_is_no_editor_type_is_refused_naming_the_component_and_the_type(
        self, component: ComponentLimits, shown: str
    ) -> None:
        names = ", ".join(each.name for each in component.editor_types)
        with pytest.raises(ValueError) as exc_info:
            replace(component, start=replace(component.start, shown=shown))
        assert str(exc_info.value) == (
            f"start.shown of fleet component {component.key!r} must be '' or one of its editor "
            f"types ({names}), got {shown!r}"
        )

    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_grammar_key_outside_its_blocks_fleet_rows_is_refused_naming_the_component_and_the_key(
        self, component: ComponentLimits
    ) -> None:
        rows = ", ".join(component.block.fleet)
        with pytest.raises(ValueError) as exc_info:
            replace(component, grammar_key="bogus_key")
        assert str(exc_info.value) == (
            f"grammar_key of fleet component {component.key!r} must be one of its block's fleet "
            f"rows ({rows}), got 'bogus_key'"
        )


class TestPageLimits:
    """page_limits(), the one PageLimits value every dashboard form's bounds and starting values render from (L3)."""

    def test_page_limits_is_one_value_that_compares_equal_on_every_call(self) -> None:
        assert isinstance(page_limits(), PageLimits)
        assert page_limits() == page_limits()

    @pytest.mark.parametrize("name", [field.name for field in dataclasses.fields(PageLimits)])
    def test_no_field_of_page_limits_can_be_assigned(self, name: str) -> None:
        limits = page_limits()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(limits, name, getattr(limits, name))

    def test_as_json_round_trips_through_json(self) -> None:
        """Strict JSON, with no NaN or Infinity, which a page script's JSON.parse would refuse."""
        assert json.loads(json.dumps(page_limits().as_json(), allow_nan=False)) == page_limits().as_json()

    def test_a_fleet_holds_1_to_max_fleet_homes_homes_starting_at_100_and_the_slider_is_a_10_to_500_convenience(
        self,
    ) -> None:
        limits = page_limits()
        assert MAX_FLEET_HOMES == 10_000
        assert limits.fleet_size == Interval(1, MAX_FLEET_HOMES)
        assert limits.fleet_size_default == 100
        assert limits.fleet_size_slider == (10, 500, 10)

    def test_a_fleets_seed_is_a_whole_number_up_to_max_fleet_seed_either_way_starting_at_42(self) -> None:
        limits = page_limits()
        assert limits.seed == Interval(-MAX_FLEET_SEED, MAX_FLEET_SEED)
        assert limits.seed_default == 42

    def test_a_window_runs_1_to_max_days_days_whose_largest_is_the_full_year(self) -> None:
        limits = page_limits()
        assert MAX_DAYS == FULL_YEAR_DAYS_SENTINEL == 365
        assert limits.window_days == Interval(1, MAX_DAYS)
        assert limits.full_year_days == FULL_YEAR_DAYS_SENTINEL

    def test_the_windows_are_timebases(self) -> None:
        limits = page_limits()
        assert limits.default_window == (DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)
        assert limits.short_window_start == SHORT_WINDOW_START

    def test_the_day_choices_start_at_30_days_and_the_custom_range_at_their_window(self) -> None:
        limits = page_limits()
        assert limits.day_choices == (7, 14, 30, 90, FULL_YEAR_DAYS_SENTINEL)
        assert limits.default_days == 30
        assert limits.custom_range_default == days_window(limits.default_days)

    def test_the_period_presets_are_the_builders_buttons_in_order(self) -> None:
        limits = page_limits()
        assert list(limits.period_presets.items()) == [
            ("Full Year", limits.default_window),
            ("Summer", (date(2024, 6, 1), date(2024, 8, 31))),
            ("Winter", (date(2024, 12, 1), date(2025, 2, 28))),
            ("1 Month", days_window(30)),
            ("1 Week", days_window(7)),
        ]

    def test_the_components_are_fleet_components(self) -> None:
        components = page_limits().components
        assert list(components) == list(FLEET_COMPONENTS)
        assert all(components[key] is component for key, component in FLEET_COMPONENTS.items())

    def test_as_json_writes_dates_as_iso_text_intervals_as_their_bounds_and_tuples_and_ordered_mappings_as_lists(
        self,
    ) -> None:
        """The period presets and the components are lists in their order, which the page's JSON, whose objects tojson writes with sorted keys, would not keep as objects."""
        limits = page_limits()

        def window(days: tuple[date, date]) -> list[str]:
            return [day.isoformat() for day in days]

        assert limits.as_json() == {
            "fleet_size": {"low": 1, "high": MAX_FLEET_HOMES},
            "fleet_size_default": 100,
            "fleet_size_slider": [10, 500, 10],
            "seed": {"low": -MAX_FLEET_SEED, "high": MAX_FLEET_SEED},
            "seed_default": 42,
            "window_days": {"low": 1, "high": MAX_DAYS},
            "full_year_days": FULL_YEAR_DAYS_SENTINEL,
            "default_window": window((DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)),
            "short_window_start": SHORT_WINDOW_START.isoformat(),
            "day_choices": [7, 14, 30, 90, FULL_YEAR_DAYS_SENTINEL],
            "default_days": 30,
            "custom_range_default": window(days_window(30)),
            "period_presets": [
                {"title": title, "window": window(period)} for title, period in limits.period_presets.items()
            ],
            "components": [
                {
                    "key": component.key,
                    "grammar_key": component.grammar_key,
                    "subject": component.subject,
                    "unit": component.unit,
                    "step": component.step,
                    "value_range": {
                        "low": component.value_range.low,
                        "high": component.value_range.high,
                    },
                    "new_row_value": component.new_row_value,
                    "start": component.start.editor_state(),
                    "editor_types": [
                        {
                            "name": each.name,
                            "title": each.title,
                            "parameters": [
                                {"key": parameter.key, "title": parameter.title, "required": parameter.required}
                                for parameter in each.parameters
                            ],
                            "rows": (
                                None
                                if each.rows is None
                                else {"keys": list(each.rows.keys), "paired_title": each.rows.paired_title}
                            ),
                        }
                        for each in component.editor_types
                    ],
                    "scalar_form": {
                        "name": component.scalar_form.name,
                        "title": component.scalar_form.title,
                        "key": component.scalar_form.spec_keys[0],
                    },
                }
                for component in FLEET_COMPONENTS.values()
            ],
        }

    def test_days_window_runs_the_full_year_for_the_sentinel_and_any_other_days_from_short_window_start(
        self,
    ) -> None:
        assert days_window(FULL_YEAR_DAYS_SENTINEL) == (DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)
        assert days_window(7) == (SHORT_WINDOW_START, SHORT_WINDOW_START + timedelta(days=6))

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            pytest.param(
                {"fleet_size_default": 0},
                "fleet_size_default must be between 1 and 10000, got 0",
                id="fleet-size-default",
            ),
            pytest.param(
                {"seed_default": MAX_FLEET_SEED + 1},
                f"seed_default must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, "
                f"got {MAX_FLEET_SEED + 1}",
                id="seed-default",
            ),
            pytest.param(
                {"fleet_size_slider": (10, 20000, 10)},
                "fleet_size_slider must start and end within fleet_size, between 1 and 10000, "
                "got (10, 20000, 10)",
                id="fleet-size-slider",
            ),
            pytest.param(
                {"day_choices": (7, 30, 400)},
                "day_choices must each be between 1 and 365, got (7, 30, 400)",
                id="day-choices",
            ),
            pytest.param(
                {"default_days": 31},
                "default_days must be one of day_choices (7, 14, 30, 90, 365), got 31",
                id="default-days",
            ),
        ],
    )
    def test_a_default_or_choice_its_own_bound_does_not_admit_is_refused_naming_the_field_and_the_value(
        self, changes: Mapping[str, object], message: str
    ) -> None:
        with pytest.raises(ValueError) as exc_info:
            replace(page_limits(), **changes)
        assert str(exc_info.value) == message


class TestReadFleetSizeAndSeed:
    """read_fleet_size and read_fleet_seed read a dashboard fleet's number of homes and seed within page_limits()'s bounds."""

    @pytest.mark.parametrize("n_homes", [1, MAX_FLEET_HOMES])
    def test_a_fleet_size_from_1_to_max_fleet_homes_is_read_as_the_int_sent(self, n_homes: int) -> None:
        assert read_fleet_size(n_homes, "n_homes") == n_homes

    @pytest.mark.parametrize("n_homes", [0, MAX_FLEET_HOMES + 1])
    def test_a_fleet_size_outside_1_to_max_fleet_homes_is_refused_naming_the_field_the_range_and_the_value(
        self, n_homes: int
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            read_fleet_size(n_homes, "fleet.n_homes")
        assert str(exc_info.value) == (
            f"fleet.n_homes must be between 1 and {MAX_FLEET_HOMES}, got {n_homes!r}"
        )

    @pytest.mark.parametrize("seed", [-MAX_FLEET_SEED, 0, MAX_FLEET_SEED])
    def test_a_seed_up_to_max_fleet_seed_either_way_is_read_as_the_int_sent(self, seed: int) -> None:
        assert read_fleet_seed(seed, "seed") == seed

    @pytest.mark.parametrize("seed", [-MAX_FLEET_SEED - 1, MAX_FLEET_SEED + 1])
    def test_a_seed_beyond_max_fleet_seed_is_refused_naming_the_field_the_range_and_the_value(
        self, seed: int
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            read_fleet_seed(seed, "fleet.seed")
        assert str(exc_info.value) == (
            f"fleet.seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, got {seed!r}"
        )


class TestRefuseHomesOutsideRanges:
    """refuse_homes_outside_ranges bounds every home's PV, battery and load value by its component's value_range, fixed or drawn."""

    def test_homes_inside_every_range_pass(self) -> None:
        refuse_homes_outside_ranges(_fleet_homes())

    @pytest.mark.parametrize("end", ["low", "high"])
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_a_value_at_either_end_of_its_range_passes(self, component: ComponentLimits, end: str) -> None:
        value = getattr(component.value_range, end)
        refuse_homes_outside_ranges(_fleet_homes(**_block_holding(component, value)))

    @pytest.mark.parametrize(
        ("key", "value", "message"),
        [
            pytest.param(
                "pv",
                50,
                "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 1",
                id="pv",
            ),
            pytest.param(
                "battery",
                500,
                "battery.capacity_kwh must be between 0 and 100 for every home, got 500.0 for home 1",
                id="battery",
            ),
            pytest.param(
                "load",
                100000,
                "load.annual_consumption_kwh must be between 500 and 20000 for every home, "
                "got 100000.0 for home 1",
                id="load",
            ),
        ],
    )
    def test_a_fixed_value_outside_its_range_is_refused_naming_the_components_path_the_range_the_value_and_the_home(
        self, key: str, value: float, message: str
    ) -> None:
        homes = _fleet_homes(**_block_holding(FLEET_COMPONENTS[key], value))
        with pytest.raises(ConfigurationError) as exc_info:
            refuse_homes_outside_ranges(homes)
        assert str(exc_info.value) == message

    def test_a_drawn_value_outside_its_range_is_refused_naming_the_home_that_draws_it(self) -> None:
        homes = _fleet_homes(pv={"capacity_kw": {"type": "normal", "mean": 50, "std": 1}})
        with pytest.raises(ConfigurationError) as exc_info:
            refuse_homes_outside_ranges(homes)
        assert str(exc_info.value) == (
            f"pv.capacity_kw must be between 0.5 and 20 for every home, "
            f"got {homes[0].pv_config.capacity_kw!r} for home 1"
        )

    def test_the_first_home_outside_a_range_is_named_by_its_number(self) -> None:
        homes = [*_fleet_homes(2), *_fleet_homes(1, pv={"capacity_kw": 50}), *_fleet_homes(1)]
        with pytest.raises(ConfigurationError) as exc_info:
            refuse_homes_outside_ranges(homes)
        assert str(exc_info.value) == (
            "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 3"
        )

    @pytest.mark.parametrize(
        ("blocks", "named"),
        [
            pytest.param(
                {"pv": {"capacity_kw": 50}, "load": {"annual_consumption_kwh": 100000}},
                "pv.capacity_kw",
                id="pv-before-load",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 500}, "load": {"annual_consumption_kwh": 100000}},
                "battery.capacity_kwh",
                id="battery-before-load",
            ),
        ],
    )
    def test_a_homes_components_are_checked_in_fleet_components_order(
        self, blocks: Mapping[str, object], named: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            refuse_homes_outside_ranges(_fleet_homes(**blocks))
        assert str(exc_info.value).startswith(f"{named} must be ")

    def test_a_home_without_a_battery_or_with_an_unscaled_load_is_not_checked_for_that_component(
        self,
    ) -> None:
        fleet = parse_fleet_distribution_config(
            {"n_homes": 3, "seed": 42, "pv": {"capacity_kw": 4.0}, "load": {}}
        )
        homes = generate_homes_from_distribution(fleet, Location.bristol())
        assert all(home.battery_config is None for home in homes)
        assert all(home.load_config.annual_consumption_kwh is None for home in homes)
        refuse_homes_outside_ranges(homes)

    def test_value_of_reads_each_components_value_of_a_home(self) -> None:
        """The home's PV capacity_kw, battery capacity_kwh and load annual_consumption_kwh, _HOMES_INSIDE_EVERY_RANGE's fixed values."""
        (home,) = _fleet_homes(1)
        assert {key: component.value_of(home) for key, component in FLEET_COMPONENTS.items()} == {
            "pv": 4.0,
            "battery": 5.0,
            "load": 3500.0,
        }

    def test_value_of_reads_none_for_a_component_a_home_lacks_or_leaves_unset(self) -> None:
        (home,) = _fleet_homes(1, battery={"capacity_kwh": 0}, load={})
        assert FLEET_COMPONENTS["battery"].value_of(home) is None
        assert FLEET_COMPONENTS["load"].value_of(home) is None


@pytest.mark.parametrize(
    ("path", "dists", "captioned_with_subject"),
    [
        pytest.param("/scenarios/builder", ("dists.pv", "dists.battery", "dists.load"), False, id="builder"),
        pytest.param("/simulate/fleet", ("pvDist", "batteryDist", "loadDist"), True, id="fleet"),
    ],
)
class TestPagesRenderEachComponentFromTheTable:
    """Each fleet page renders one distribution editor per component, in FLEET_COMPONENTS order, as the table defines it.

    *dists* are the page's Alpine expressions of its cards' distributions, in card order. The
    fleet page starts each caption with the component's subject, which the builder's
    fieldset groups name instead.
    """

    def test_each_editor_edits_its_cards_distribution_and_starts_an_added_row_at_its_components_new_row_value(
        self, client: FlaskClient, path: str, dists: tuple[str, ...], captioned_with_subject: bool
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert _editor_scopes(page) == [
            f"distributionEditor(() => {dist}, {component.new_row_value})"
            for component, dist in zip(FLEET_COMPONENTS.values(), dists, strict=True)
        ]

    def test_each_distribution_type_offers_the_scalar_forms_title_then_each_editor_type_in_order(
        self, client: FlaskClient, path: str, dists: tuple[str, ...], captioned_with_subject: bool
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert options_of_each(page, {"x-model": "dist.type"}) == [
            [("", component.scalar_form.title), *((each.name, each.title) for each in component.editor_types)]
            for component in FLEET_COMPONENTS.values()
        ]

    def test_each_fixed_value_is_captioned_by_the_scalar_forms_title_and_bounded_and_stepped_as_its_component(
        self, client: FlaskClient, path: str, dists: tuple[str, ...], captioned_with_subject: bool
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert [
            (caption, attributes.get("step"), attributes.get("min"), attributes.get("max"))
            for caption, attributes in labelled_inputs(page)
            if attributes.get("x-model.number") == "dist.fixed"
        ] == [
            (
                _caption(component, component.scalar_form.title, captioned_with_subject),
                str(component.step),
                str(component.value_range.low),
                str(component.value_range.high),
            )
            for component in FLEET_COMPONENTS.values()
        ]

    def test_each_editor_types_inputs_are_captioned_by_the_table_and_bound_to_its_spec_in_the_editor(
        self, client: FlaskClient, path: str, dists: tuple[str, ...], captioned_with_subject: bool
    ) -> None:
        """A parameter is unbounded (the server refuses a negative Std Dev, naming it); a row's paired column is at least 0, and a count steps by 1."""
        page = client.get(path).get_data(as_text=True)
        assert [
            (
                caption,
                attributes.get("x-model.number"),
                attributes.get("step"),
                attributes.get("min"),
                attributes.get("max"),
            )
            for caption, attributes in labelled_inputs(page)
            if (attributes.get("x-model.number") or "").startswith("dist.specs.")
        ] == [
            spec_input
            for component in FLEET_COMPONENTS.values()
            for spec_input in _spec_inputs(component, captioned_with_subject)
        ]


def _caption(component: ComponentLimits, title: str, captioned_with_subject: bool) -> str:
    """The caption a fleet page gives *component*'s input titled *title*: its subject, then the title, on the fleet page."""
    return f"{component.subject} {title}" if captioned_with_subject else title


def _spec_inputs(
    component: ComponentLimits, captioned_with_subject: bool
) -> list[tuple[str, str, str, str | None, None]]:
    """The (caption, binding, step, min, max) of each input of *component*'s editor that edits one of its editor types' specs, in editor_types order: each parameter, then a row's value and paired inputs."""
    inputs: list[tuple[str, str, str, str | None, None]] = []
    for each in component.editor_types:
        spec = f"dist.specs.{each.name}"
        for parameter in each.parameters:
            inputs.append((
                _caption(component, parameter.title, captioned_with_subject),
                f"{spec}.{parameter.key}",
                str(component.step),
                None,
                None,
            ))
        if each.rows is not None:
            values_key, paired_key = each.rows.keys
            paired_step = "1" if each.rows.paired_kind is FieldKind.COUNT else "any"
            inputs.append((
                _caption(component, "Value", captioned_with_subject),
                f"{spec}.{values_key}[idx]",
                str(component.step),
                None,
                None,
            ))
            inputs.append((
                _caption(component, each.rows.paired_title, captioned_with_subject),
                f"{spec}.{paired_key}[idx]",
                paired_step,
                "0",
                None,
            ))
    return inputs


#: The editor's template and the scripts that build or read a component's spec, under the web package.
_EDITOR_SOURCES = (
    "templates/components/distribution-editor.html",
    "static/js/distribution-editor.js",
    "static/js/fleet-simulator.js",
    "static/js/scenario-builder.js",
)


@pytest.mark.parametrize("source", _EDITOR_SOURCES)
def test_no_editor_source_names_a_distribution_type_the_editor_holds(source: str) -> None:
    """The editor renders every type from the table and the scripts read them from #page-limits, so none spells a type's name (E4)."""
    text = (Path(solar_challenge.web.__file__).parent / source).read_text(encoding="utf-8")
    assert [
        f"{quote}{name}{quote}"
        for name, each in DISTRIBUTION_TYPES.items()
        if each.editable
        for quote in ("'", '"', "`")
        if f"{quote}{name}{quote}" in text
    ] == []


class TestPagesHeadEachCardFromTheTable:
    """Each fleet page heads each component's card with the words FLEET_COMPONENTS gives it."""

    def test_the_builder_heads_each_card_with_its_components_heading(self, client: FlaskClient) -> None:
        page = client.get("/scenarios/builder").get_data(as_text=True)
        card_headings = tuple(component.heading for component in FLEET_COMPONENTS.values())
        assert counts_of(headings(page), card_headings) == dict.fromkeys(card_headings, 1)

    def test_the_fleet_page_heads_each_card_with_its_components_subject(self, client: FlaskClient) -> None:
        page = client.get("/simulate/fleet").get_data(as_text=True)
        subjects = tuple(component.subject for component in FLEET_COMPONENTS.values())
        assert counts_of(headings(page), subjects) == dict.fromkeys(subjects, 1)


class TestTheFleetPageColoursEachCardByItsComponent:
    """The fleet page draws each component's card in the role palette the token file's
    tailwind.component group names under that component's key."""

    @pytest.mark.parametrize("key", list(FLEET_COMPONENTS))
    def test_the_fleet_page_draws_each_components_card_in_its_role_palette(
        self, client: FlaskClient, key: str
    ) -> None:
        """The card's header band and its dot are the page's only divs naming component-<key>."""
        page = client.get("/simulate/fleet").get_data(as_text=True)

        role_classes = {
            css_class
            for div in element_attributes(page, "div")
            for css_class in (div.get("class") or "").split()
            if names_palette(css_class, f"component-{key}")
        }

        assert role_classes == {
            f"bg-component-{key}-50",
            f"dark:bg-component-{key}-900/20",
            f"bg-component-{key}-500",
        }


class TestPagesRenderPageLimits:
    """Every form page renders its bounds and starting values from page_limits(), through one channel (L1).

    A context processor gives every template page_limits, and base.html writes its as_json()
    once into each page as the #page-limits element, which the pages' scripts read.
    """

    @pytest.mark.parametrize("path", _FORM_PAGES)
    def test_each_form_page_writes_page_limits_once_into_its_page_limits_element(
        self, client: FlaskClient, path: str
    ) -> None:
        page = client.get(path).get_data(as_text=True)
        assert element_count(page, "script", {"type": "application/json", "id": "page-limits"}) == 1
        assert json.loads(script_text_by_id(page, "page-limits")) == page_limits().as_json()

    def test_every_template_is_given_page_limits(self, app: Flask) -> None:
        with app.test_request_context():
            rendered = render_template_string("{{ page_limits.fleet_size.high }}")
        assert rendered == str(page_limits().fleet_size.high)

    def test_the_fleet_pages_number_of_homes_admits_the_fleet_size(self, client: FlaskClient) -> None:
        page = client.get("/simulate/fleet").get_data(as_text=True)
        fleet_size = page_limits().fleet_size
        assert _bounds_of_input(page, "n_homes") == (str(fleet_size.low), str(fleet_size.high))

    def test_the_fleet_pages_size_slider_and_its_captions_are_the_fleet_size_slider(
        self, client: FlaskClient
    ) -> None:
        page = client.get("/simulate/fleet").get_data(as_text=True)
        low, high, step = page_limits().fleet_size_slider
        (slider,) = [
            attributes
            for attributes in element_attributes(page, "input")
            if attributes.get("id") == "n_homes_range"
        ]
        assert (slider.get("min"), slider.get("max"), slider.get("step")) == (str(low), str(high), str(step))
        assert texts_after(page, "Number of Homes", 2) == [str(low), str(high)]

    @pytest.mark.parametrize(
        ("path", "days_variable"),
        [
            pytest.param("/simulate/home", "formData.period_days", id="home"),
            pytest.param("/simulate/fleet", "periodDays", id="fleet"),
        ],
    )
    def test_the_period_buttons_offer_each_day_choice_the_full_year_captioned_1_year(
        self, client: FlaskClient, path: str, days_variable: str
    ) -> None:
        """One button per day choice, in order, each choosing its days; the buttons follow the Custom range option."""
        page = client.get(path).get_data(as_text=True)
        limits = page_limits()
        assert texts_after(page, "Custom range", len(limits.day_choices)) == _day_choice_captions(limits)
        assert _click_handlers(page, f"{days_variable} = ") == [
            f"{days_variable} = {days}" for days in limits.day_choices
        ]

    def test_the_builders_number_of_homes_admits_the_fleet_size(self, client: FlaskClient) -> None:
        page = client.get("/scenarios/builder").get_data(as_text=True)
        fleet_size = page_limits().fleet_size
        assert _bounds_of_input(page, "builder_n_homes") == (str(fleet_size.low), str(fleet_size.high))

    def test_the_builders_period_buttons_are_the_period_presets_each_setting_the_period_its_title_names(
        self, client: FlaskClient
    ) -> None:
        """The buttons follow the Period section's title, in period_presets order."""
        page = client.get("/scenarios/builder").get_data(as_text=True)
        titles = list(page_limits().period_presets)
        assert texts_after(page, "Period", len(titles)) == titles
        assert _click_handlers(page, "setPeriod(") == [f"setPeriod({json.dumps(title)})" for title in titles]

    def test_the_sweeps_days_admit_the_window_days(self, client: FlaskClient) -> None:
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        window_days = page_limits().window_days
        assert _bounds_of_input(page, "sweep_base_days") == (str(window_days.low), str(window_days.high))

    def test_the_home_pages_pv_capacity_slider_spans_the_pv_components_value_range(
        self, client: FlaskClient
    ) -> None:
        page = client.get("/simulate/home").get_data(as_text=True)
        value_range = page_limits().components["pv"].value_range
        assert _bounds_of_input(page, "pv_kw") == (str(value_range.low), str(value_range.high))
