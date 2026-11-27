# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_scenario, called directly with fleet forms: the bodies fleet-simulator.js's buildPayload() posts."""

import dataclasses
import json
import re
from collections.abc import Callable
from typing import Any, Literal

import pytest
import yaml

pytest.importorskip("flask")

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import parse_scenario, read_fleet_scenario
from solar_challenge.dispatch import (
    STRATEGY_CONFIG_BY_TYPE,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    NormalDistribution,
    parse_fleet_distribution_config,
    write_distribution_spec,
)
from solar_challenge.home import simulate_home
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.number_fields import Interval
from solar_challenge.scenario_blocks import (
    parse_dispatch_strategy_config,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.scenario_writer import location_block
from solar_challenge.tariff import PRESET_RATES, TariffConfig
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    MAX_FLEET_HOMES,
    MAX_FLEET_SEED,
    MAX_WINDOW_DAYS,
    page_limits,
)
from solar_challenge.web.fleet_config import read_form_fleet
from solar_challenge.web.fleet_scenario import (
    FLEET_FORM_DISPATCH,
    FLEET_FORM_TARIFFS,
    ParsedFleetForm,
    fleet_form_dispatch_choices,
    fleet_form_from_scenario,
    parse_fleet_form,
    scenario_from_fleet_form,
)
from solar_challenge.web.form_choices import FormChoice, SettingInput
from solar_challenge.web.request_boundary import read_string, require_encodable_text
from solar_challenge.web.scenario_import import ImportedForm
from solar_challenge.web.simulation_params import parse_seg_tariff
from tests._fleet_form import form_fleet_blocks, valid_distribution_form
from tests._synthetic_weather import sunless_weather, weather_for
from tests._unusable_numbers import UNUSABLE_NUMBERS

_FLEET_FORM: dict[str, Any] = {
    "name": "Round Trip Fleet",
    "n_homes": 3,
    "seed": 7,
    "pv": {"capacity_kw": {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [1.0, 3.0]}},
    "battery": {"capacity_kwh": {"type": "shuffled_pool", "values": [0.0, 5.0], "counts": [1, 2]}},
    "load": {
        "annual_consumption_kwh": {"type": "normal", "mean": 3400.0, "std": 800.0, "min": 2000.0, "max": 6000.0}
    },
    "start": "2024-07-01",
    "end": "2024-07-10",
    "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
    "seg": {"preset": "Octopus"},
    "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5},
}


#: The scenario document _FLEET_FORM describes.
_FLEET_SCENARIO: dict[str, Any] = {
    "name": "Round Trip Fleet",
    "period": {"start_date": "2024-07-01", "end_date": "2024-07-10"},
    "location": location_block(Location.bristol()),
    "fleet_distribution": {
        "n_homes": 3,
        "seed": 7,
        "pv": {
            "capacity_kw": {
                "type": "weighted_discrete",
                "values": [3.0, 5.0],
                "weights": [1.0, 3.0],
            }
        },
        "battery": {
            "capacity_kwh": {"type": "shuffled_pool", "values": [0.0, 5.0], "counts": [1, 2]},
            "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5},
        },
        "load": {
            "annual_consumption_kwh": {
                "type": "normal",
                "mean": 3400.0,
                "std": 800.0,
                "min": 2000.0,
                "max": 6000.0,
            }
        },
    },
    "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
    "seg": {"preset": "Octopus"},
}


def _without(form: dict[str, Any], *keys: str) -> dict[str, Any]:
    """*form* without *keys*, as buildPayload leaves out a disabled block."""
    return {key: value for key, value in form.items() if key not in keys}


def _with_fleet_distribution(**blocks: Any) -> dict[str, Any]:
    """_FLEET_SCENARIO with *blocks* in place of those of its fleet_distribution block."""
    return {
        **_FLEET_SCENARIO,
        "fleet_distribution": {**_FLEET_SCENARIO["fleet_distribution"], **blocks},
    }


#: Each top-level key of a fleet form, with a value _FLEET_FORM does not give it.
_ANOTHER_VALUE_OF_EACH_FLEET_FORM_KEY: dict[str, Any] = {
    "name": "Another Fleet",
    "n_homes": 2,
    "seed": 8,
    "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
    "battery": {"capacity_kwh": {"type": "normal", "mean": 5.0, "std": 2.0, "min": 0.0, "max": 10.0}},
    "load": {"annual_consumption_kwh": {"type": "uniform", "min": 2000, "max": 5000}},
    "days": 7,
    "start": "2024-07-02",
    "end": "2024-07-09",
    "location": "london",
    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.28},
    "dispatch_strategy": {"strategy_type": "self_consumption"},
    "seg": {"rate_pence_per_kwh": 4.5},
}


#: _FLEET_FORM with its window set by days rather than by start and end: a form may send one or the other, not both.
_FLEET_FORM_BY_DAYS: dict[str, Any] = {**_without(_FLEET_FORM, "start", "end"), "days": 10}

#: _FLEET_FORM with a battery drawn from a distribution rather than its shuffled pool: a pool must hold one value per home, so only then can n_homes change alone.
_FLEET_FORM_WITHOUT_A_POOL: dict[str, Any] = {**_FLEET_FORM, "battery": _ANOTHER_VALUE_OF_EACH_FLEET_FORM_KEY["battery"]}

#: The form each key's change is made to, where _FLEET_FORM cannot take that change alone.
_FORM_TO_CHANGE_BY_KEY: dict[str, dict[str, Any]] = {"days": _FLEET_FORM_BY_DAYS, "n_homes": _FLEET_FORM_WITHOUT_A_POOL}

#: A value parse_fleet_form refuses for each key it reads after the fleet's distributions: the location, the tariff, dispatch strategy and SEG overlays, and the window.
_A_REFUSED_VALUE_OF_EACH_KEY_READ_AFTER_THE_DISTRIBUTIONS: dict[str, Any] = {
    "location": "atlantis",
    "tariff": {"type": "flat_rate"},
    "dispatch_strategy": {"strategy_type": "turbo"},
    "seg": {},
    "start": "not-a-date",
    "end": "not-a-date",
    "days": 2.5,
}


def _run(fleet: ParsedFleetForm) -> tuple[Any, ...]:
    """The run of the parsed *fleet*: the name, homes and dates the simulate endpoint submits."""
    return (fleet.name, fleet.homes, fleet.start_date, fleet.end_date)


class TestParseFleetForm:
    """parse_fleet_form's top-level keys: the fleet form's, each read for both the run and its scenario, and its refusal of any other."""

    def test_a_key_the_fleet_form_does_not_have_is_refused_naming_it(self) -> None:
        """heat_pump is a home config block the fleet has no overlay for, and tarif is a misspelt tariff.

        Both are refused by name rather than dropped from a fleet that would run without them.
        The error lists the fleet form's keys: exactly the keys of
        _ANOTHER_VALUE_OF_EACH_FLEET_FORM_KEY, each of which the run and its scenario read.
        """
        with pytest.raises(ConfigurationError) as exc_info:
            parse_fleet_form(
                {
                    **_FLEET_FORM,
                    "heat_pump": {"type": "ASHP"},
                    "tarif": {"type": "flat_rate", "rate_per_kwh": 0.3},
                }
            )
        assert str(exc_info.value) == (
            "Unrecognised fleet form keys: 'heat_pump', 'tarif'; "
            f"recognised keys: {', '.join(sorted(_ANOTHER_VALUE_OF_EACH_FLEET_FORM_KEY))}"
        )

    @pytest.mark.parametrize(
        ("form", "key", "value"),
        [
            pytest.param(_FORM_TO_CHANGE_BY_KEY.get(key, _FLEET_FORM), key, value, id=key)
            for key, value in _ANOTHER_VALUE_OF_EACH_FLEET_FORM_KEY.items()
        ],
    )
    def test_each_key_of_the_fleet_form_changes_both_the_run_and_its_scenario(
        self, form: dict[str, Any], key: str, value: Any
    ) -> None:
        """Changing any key a fleet *form* has changes what the simulate endpoint runs and the scenario the export writes, so neither accepts a key it then drops."""
        given = parse_fleet_form(form)
        changed = parse_fleet_form({**form, key: value})

        assert _run(changed) != _run(given)
        assert changed.scenario != given.scenario

    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="with-overlays"),
            pytest.param(_without(_FLEET_FORM, "tariff", "seg", "dispatch_strategy"), id="without-overlays"),
        ],
    )
    def test_every_home_holds_the_forms_tariff_and_seg_and_every_battery_its_dispatch_strategy(
        self, form: dict[str, Any]
    ) -> None:
        """The tariff and SEG reach every home and the dispatch strategy every battery, each as its reader reads the form's value.

        A form without a dispatch strategy leaves every battery BatteryConfig's self-consumption. A
        home the form's battery pool gives 0 kWh has no battery, and none is made to carry the strategy.
        """
        tariff = parse_tariff_config(form.get("tariff"))
        seg = parse_seg_tariff(form.get("seg"))
        form_dispatch = parse_dispatch_strategy_config(form.get("dispatch_strategy"))
        dispatch = SelfConsumptionStrategyConfig() if form_dispatch is None else form_dispatch
        battery_pool = form["battery"]["capacity_kwh"]
        pool = list(zip(battery_pool["values"], battery_pool["counts"], strict=True))
        homes_with_a_battery = sum(count for value, count in pool if value > 0)
        homes_without_a_battery = sum(count for value, count in pool if value == 0)

        homes = parse_fleet_form(form).homes

        assert [(home.tariff_config, home.seg_tariff) for home in homes] == [(tariff, seg)] * len(homes)
        assert [
            home.battery_config.dispatch_strategy for home in homes if home.battery_config is not None
        ] == [dispatch] * homes_with_a_battery
        assert sum(home.battery_config is None for home in homes) == homes_without_a_battery

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"strategy_type": "turbo"}, id="unknown-type"),
            pytest.param({"strategy_type": "peak_shaving"}, id="missing-setting"),
        ],
    )
    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="with-battery"),
            pytest.param(_without(_FLEET_FORM, "battery"), id="without-battery"),
        ],
    )
    def test_a_refused_dispatch_strategy_gets_its_readers_refusal_of_the_forms_value(
        self, form: dict[str, Any], value: dict[str, Any]
    ) -> None:
        """The refusal names the form's own dispatch_strategy key, never fleet_distribution.battery.dispatch_strategy, whether or not a battery carries it."""
        with pytest.raises(ConfigurationError) as expected:
            parse_dispatch_strategy_config(value)
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**form, "dispatch_strategy": value})
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))


class TestParseFleetFormName:
    """The name parse_fleet_form reads: refused when it is not a JSON string, or is text that does not encode as UTF-8, before the fleet is read; a blank name is no name."""

    def test_a_name_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_FLEET_FORM, "name": chr(0xD800)})
        assert str(refusal.value) == str(expected.value)

    def test_a_name_holding_a_lone_surrogate_is_refused_before_the_fleet_is_read(self) -> None:
        """A form whose pv distribution is refused too gets the name's refusal, so a refused name costs no home generation."""
        with pytest.raises(ConfigurationError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_without(_FLEET_FORM, "pv"), "name": chr(0xD800)})
        assert str(refusal.value) == str(expected.value)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"x": 1}, id="object"),
            pytest.param(5, id="integer"),
            pytest.param(True, id="boolean"),
        ],
    )
    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="a-fleet-it-reads"),
            pytest.param(_without(_FLEET_FORM, "pv"), id="before-the-fleet-is-read"),
        ],
    )
    def test_a_name_that_is_not_a_json_string_is_refused_as_read_string_refuses_it(
        self, form: dict[str, Any], value: object
    ) -> None:
        """A form whose pv distribution is refused too gets the name's refusal, so a refused name costs no home generation."""
        with pytest.raises(ConfigurationError) as expected:
            read_string(value, "name")
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**form, "name": value})
        assert str(refusal.value) == str(expected.value)

    def test_a_blank_name_is_no_name(self) -> None:
        """The run submitted takes its kind's default name, and the document names none."""
        parsed = parse_fleet_form({**_FLEET_FORM, "name": "   "})

        assert parsed.name is None
        assert "name" not in parsed.scenario


class TestParseFleetFormRefusalOrder:
    """Which refusal parse_fleet_form gives a form it refuses for more than one value: a value one of its readers refuses is refused before any home is generated."""

    @pytest.mark.parametrize(
        ("form", "key", "value"),
        [
            pytest.param(_FORM_TO_CHANGE_BY_KEY.get(key, _FLEET_FORM), key, value, id=key)
            for key, value in _A_REFUSED_VALUE_OF_EACH_KEY_READ_AFTER_THE_DISTRIBUTIONS.items()
        ],
    )
    def test_a_value_read_after_the_distributions_is_refused_before_any_home_is_generated(
        self, form: dict[str, Any], key: str, value: Any
    ) -> None:
        """A form whose pv capacity of 0 only the generation of its homes refuses gets the refusal its location, tariff, dispatch strategy, SEG or window gets on a fleet that generates, so such a refusal costs no home generation."""
        ungeneratable = {**form, "pv": {"capacity_kw": 0}}
        with pytest.raises(ConfigurationError, match="capacity_kw must be greater than 0"):
            parse_fleet_form(ungeneratable)
        with pytest.raises(ConfigurationError) as expected:
            parse_fleet_form({**form, key: value})
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**ungeneratable, key: value})
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))

    def test_a_fleet_above_the_dashboards_bound_is_refused_before_any_home_is_generated(self) -> None:
        """A fleet whose pv capacity of 0 only the generation of its homes refuses gets the dashboard's bound on its size, so a fleet the page cannot run costs no home generation."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_FLEET_FORM_WITHOUT_A_POOL, "n_homes": MAX_FLEET_HOMES + 1, "pv": {"capacity_kw": 0}})

        assert str(refusal.value) == f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}"


#: The refused tariff and SEG parse_fleet_form's scenario reader refuses before the fleet_distribution block, each with its block reader's reading of it.
_A_REFUSED_TARIFF_OR_SEG_WITH_ITS_READERS_READING = [
    pytest.param("tariff", {"type": "flat_rate"}, lambda: parse_tariff_config({"type": "flat_rate"}), id="tariff"),
    pytest.param("seg", {}, lambda: parse_seg_rate({}), id="seg"),
]

#: A battery capacity of a sweep multiplier of three points times each home's PV capacity.
_A_SWEPT_BATTERY_CAPACITY: dict[str, Any] = {
    "type": "proportional_to",
    "source": "pv.capacity_kw",
    "multiplier": {"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3},
}


class TestParseFleetFormReadsItsDocumentThroughParseScenario:
    """parse_fleet_form's run is its scenario document as config.parse_scenario reads it, so the simulate endpoint and the export are one reading."""

    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="with-overlays"),
            pytest.param(_without(_FLEET_FORM, "tariff", "seg", "dispatch_strategy"), id="without-overlays"),
            pytest.param(_FLEET_FORM_BY_DAYS, id="by-days"),
            pytest.param({**_FLEET_FORM, "location": "london"}, id="london"),
        ],
    )
    def test_the_run_is_the_scenario_document_as_parse_scenario_reads_it(self, form: dict[str, Any]) -> None:
        fleet = parse_fleet_form(form)

        scenario = parse_scenario(fleet.scenario)

        assert scenario.simulated_homes() == fleet.homes
        assert scenario.simulation_bounds() == (fleet.start_date, fleet.end_date)

    @pytest.mark.parametrize(("key", "value", "read_block"), _A_REFUSED_TARIFF_OR_SEG_WITH_ITS_READERS_READING)
    def test_a_refused_fleet_block_is_refused_before_a_refused_tariff_or_seg_naming_the_forms_field(
        self, key: str, value: Any, read_block: Callable[[], object]
    ) -> None:
        """The form's fleet blocks are read at the form's own paths before read_fleet_scenario reads the tariff and SEG, so the refusal is the grammar's of the battery block, naming battery.capacity_kwh."""
        form = {**_FLEET_FORM, key: value, "battery": {"capacity_kwh": {"type": "uniform"}}}
        with pytest.raises(ConfigurationError):
            read_block()
        blocks = form_fleet_blocks(form)
        with pytest.raises(ConfigurationError) as expected:
            parse_fleet_distribution_config(blocks, block_path="")
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form(form)
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))
        assert str(refusal.value).startswith("battery.capacity_kwh")

    @pytest.mark.parametrize(("key", "value", "read_block"), _A_REFUSED_TARIFF_OR_SEG_WITH_ITS_READERS_READING)
    def test_the_dashboards_bound_on_the_fleet_is_refused_before_a_refused_tariff_or_seg(
        self, key: str, value: Any, read_block: Callable[[], object]
    ) -> None:
        """read_form_fleet holds the fleet to the dashboard's bounds before read_fleet_scenario reads the tariff and SEG."""
        form = {**_FLEET_FORM_WITHOUT_A_POOL, "n_homes": MAX_FLEET_HOMES + 1, key: value}
        with pytest.raises(ConfigurationError):
            read_block()
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form(form)
        assert str(refusal.value) == f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}"

    def test_a_refused_fleet_block_names_the_field_the_form_posts_not_its_scenario_path(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_FLEET_FORM, "pv": {"capacity_kw": {"type": "normal"}}})
        assert str(refusal.value).startswith("pv.capacity_kw")
        assert "fleet_distribution." not in str(refusal.value)

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(None, id="a-cleared-fixed-value"),
            pytest.param({"type": "shuffled_pool", "values": [4.0, None], "counts": [2, 1]}, id="a-blank-pool-value"),
        ],
    )
    def test_a_pv_capacity_a_home_would_draw_null_is_refused_as_read_form_fleet_refuses_it_naming_the_forms_field(
        self, spec: object
    ) -> None:
        """A cleared PV input posts null, refused at pv.capacity_kw before any home is generated, not as a home's null draw under fleet_distribution."""
        form = {**_FLEET_FORM, "pv": {"capacity_kw": spec}}
        blocks = form_fleet_blocks(form)
        with pytest.raises(ConfigurationError) as expected:
            read_form_fleet(blocks)
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form(form)
        assert str(refusal.value) == str(expected.value)
        assert str(refusal.value).startswith("pv.capacity_kw: required")

    def test_a_fleet_that_sweeps_is_refused_as_parse_scenario_refuses_its_document(self) -> None:
        """A sweep defines one fleet per point, which 'fleet sweep' runs, so the form's one fleet is refused with parse_scenario's refusal of the document the form describes, naming the swept field."""
        battery = _FLEET_SCENARIO["fleet_distribution"]["battery"]
        document = _with_fleet_distribution(battery={**battery, "capacity_kwh": _A_SWEPT_BATTERY_CAPACITY})
        with pytest.raises(ConfigurationError) as expected:
            parse_scenario(document)
        assert "fleet_distribution.battery.capacity_kwh" in str(expected.value), (
            "premise: parse_scenario refuses the sweep naming its field"
        )

        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_FLEET_FORM, "battery": {"capacity_kwh": _A_SWEPT_BATTERY_CAPACITY}})

        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))


#: Each component's fixed value no home may hold (P3), with the refusal parse_fleet_form gives a fleet form fixing it.
_FIXED_VALUES_OUTSIDE_THEIR_RANGES = [
    pytest.param(
        "pv",
        {"capacity_kw": 50},
        "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 1",
        id="pv",
    ),
    pytest.param(
        "battery",
        {"capacity_kwh": 500},
        "battery.capacity_kwh must be between 0 and 100 for every home, got 500.0 for home 1",
        id="battery",
    ),
    pytest.param(
        "load",
        {"annual_consumption_kwh": 100000},
        "load.annual_consumption_kwh must be between 500 and 20000 for every home, got 100000.0 for home 1",
        id="load",
    ),
]

#: A PV distribution every home draws above the pv component's range (P15).
_PV_DRAWN_ABOVE_ITS_RANGE = {"capacity_kw": {"type": "normal", "mean": 50, "std": 1}}

#: The refusal of a home drawing PV above its range, the value drawn left open.
_PV_DRAWN_ABOVE_ITS_RANGE_REFUSAL = re.compile(
    r"pv\.capacity_kw must be between 0\.5 and 20 for every home, got \d+\.\d+ for home \d+"
)


class TestParseFleetFormBoundsEveryHome:
    """parse_fleet_form refuses a fleet whose homes hold a PV, battery or load value outside its component's value_range, fixed or drawn (L2)."""

    @pytest.mark.parametrize(("key", "block", "message"), _FIXED_VALUES_OUTSIDE_THEIR_RANGES)
    def test_a_fixed_value_outside_its_components_range_is_refused_naming_its_path_the_home_the_range_and_the_value(
        self, key: str, block: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            parse_fleet_form({**valid_distribution_form(), key: block})
        assert str(exc_info.value) == message

    def test_a_drawn_value_outside_its_components_range_is_refused_naming_its_path_and_the_home(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            parse_fleet_form({**valid_distribution_form(), "pv": _PV_DRAWN_ABOVE_ITS_RANGE})
        assert _PV_DRAWN_ABOVE_ITS_RANGE_REFUSAL.fullmatch(str(exc_info.value)), str(exc_info.value)

    def test_scenario_from_fleet_form_refuses_the_same_form(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            scenario_from_fleet_form({**valid_distribution_form(), "pv": {"capacity_kw": 50}})
        assert str(exc_info.value) == (
            "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 1"
        )


class TestScenarioFromFleetForm:
    """The fleet scenario document scenario_from_fleet_form builds from a fleet form, and its refusals."""

    def test_a_fleet_form_is_the_scenario_document_it_describes(self) -> None:
        """Its distributions are written in fleet_distribution.py's grammar with the dispatch under the battery; its dates, location, tariff and SEG are their blocks.

        The blocks come in the order the scenario builder writes them.
        """
        assert list(scenario_from_fleet_form(_FLEET_FORM).items()) == list(_FLEET_SCENARIO.items())

    def test_a_fleet_form_without_overlays_writes_no_tariff_seg_or_battery_dispatch(self) -> None:
        """A form with no tariff, SEG or dispatch writes null tariff: and seg: blocks and a battery block of its capacity alone; its days give the period."""
        form = {
            **_without(_FLEET_FORM, "start", "end", "tariff", "seg", "dispatch_strategy"),
            "days": 7,
        }

        document = scenario_from_fleet_form(form)

        assert document["period"] == {"start_date": "2024-06-01", "end_date": "2024-06-07"}
        assert (document["tariff"], document["seg"]) == (None, None)
        assert document["fleet_distribution"]["battery"].keys() == {"capacity_kwh"}

    def test_a_dispatch_strategy_sent_without_a_battery_is_not_written(self) -> None:
        """The simulate endpoint's overlay gives that dispatch to no home, so the document is the one the form without it describes."""
        without_battery = _without(_FLEET_FORM, "battery")

        document = scenario_from_fleet_form(without_battery)

        assert "battery" not in document["fleet_distribution"]
        assert document == scenario_from_fleet_form(_without(without_battery, "dispatch_strategy"))

    @pytest.mark.parametrize(
        ("form", "reason"),
        [
            pytest.param({**_FLEET_FORM, "tariff": {"type": "flat_rate"}}, "rate_per_kwh", id="tariff"),
            pytest.param({**_FLEET_FORM, "seg": {}}, "seg", id="seg"),
            pytest.param(
                {**_without(_FLEET_FORM, "battery"), "dispatch_strategy": {"strategy_type": "turbo"}},
                "turbo",
                id="dispatch-without-battery",
            ),
            pytest.param(
                {**_FLEET_FORM, "start": "not-a-date", "end": "2024-07-10"}, "not-a-date", id="start-date"
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {
                        "capacity_kw": {"type": "weighted_discrete", "values": [0], "weights": [1]}
                    },
                },
                "capacity_kw must be greater than 0",
                id="pv-capacity-zero",
            ),
        ],
    )
    def test_a_fleet_form_the_loaders_would_refuse_is_refused(
        self, form: dict[str, Any], reason: str
    ) -> None:
        """A block the loaders or the simulate endpoint refuse is refused with their reason, so no YAML is written for it.

        A dispatch is checked even without a battery to carry it, as the simulate endpoint checks it.
        A fleet whose homes cannot be generated is refused too: load_fleet_config generates them.
        """
        with pytest.raises(ConfigurationError, match=reason):
            scenario_from_fleet_form(form)

    def test_a_name_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        """No YAML is written for a name the simulate endpoint refuses."""
        with pytest.raises(ConfigurationError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ConfigurationError) as refusal:
            scenario_from_fleet_form({**_FLEET_FORM, "name": chr(0xD800)})
        assert str(refusal.value) == str(expected.value)


_BRISTOL_LIKE_SCENARIO_YAML = """\
name: Bristol Phase 1
location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
  altitude: 11.0
  name: Bristol, UK
seg:
  rate_pence_per_kwh: 4.1
fleet_distribution:
  n_homes: 100
  seed: 42
  random_order: bristol_legacy
  pv:
    capacity_kw:
      type: shuffled_pool
      values: [3.0, 4.0, 5.0, 6.0]
      counts: [20, 40, 30, 10]
    azimuth: 180
    tilt: 35
  battery:
    capacity_kwh:
      type: shuffled_pool
      values: [null, 5.0, 10.0]
      counts: [40, 40, 20]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
finance:
  standing_charge_pence_per_day: 60.0
"""


class TestFleetFormFromScenario:
    """The fleet form fleet_form_from_scenario reads from a fleet scenario, the settings it names as not loaded, and its refusals."""

    def test_a_fleet_scenario_is_the_fleet_form_it_describes(self) -> None:
        """The scenario a fleet form describes reads back as that form: its distributions as the grammar's own specs, its battery's dispatch as the form's dispatch strategy, and its period as start and end dates."""
        assert fleet_form_from_scenario(_FLEET_SCENARIO) == ImportedForm(
            form=_FLEET_FORM, not_loaded=()
        )

    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="every-overlay"),
            pytest.param(
                _without(_FLEET_FORM, "battery", "tariff", "seg", "dispatch_strategy"),
                id="no-battery-or-overlay",
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
                    "battery": {
                        "capacity_kwh": {"type": "normal", "mean": 5.0, "std": 2.0, "min": 0.0, "max": 10.0}
                    },
                    "load": {
                        "annual_consumption_kwh": {"type": "shuffled_pool", "values": [2900, 4500], "counts": [2, 1]}
                    },
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.28},
                    "seg": {"rate_pence_per_kwh": 4.5},
                    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 21]]},
                },
                id="uniform-normal-and-pool-editors",
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {"capacity_kw": 5.5},
                    "battery": {"capacity_kwh": 5.0},
                    "load": {"annual_consumption_kwh": 3400.0},
                },
                id="fixed-values",
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "normal",
                            "mean": 3400.0,
                            "std": 800.0,
                            "min": None,
                            "max": None,
                        }
                    },
                },
                id="normal-without-clamps",
            ),
        ],
    )
    def test_an_exported_fleet_form_imports_back_to_the_same_scenario(
        self, form: dict[str, Any]
    ) -> None:
        """Every setting of a scenario the page exports is one the form holds, and the form read back describes the scenario read_fleet_scenario reads from the export: a null clamp is written, and read as absent."""
        document = scenario_from_fleet_form(form)

        imported = fleet_form_from_scenario(document)

        assert imported.not_loaded == ()
        assert read_fleet_scenario(scenario_from_fleet_form(imported.form)) == read_fleet_scenario(document)

    def test_a_scenario_file_loads_what_the_form_holds_and_names_the_rest(self) -> None:
        """A scenario file loads its name, fleet size, seed, distributions and SEG; the settings the form has no control for are named, in document order.

        Each distribution loads as the grammar's spec, and the battery pool's null value as
        null, a home without a battery.
        """
        imported = fleet_form_from_scenario(yaml.safe_load(_BRISTOL_LIKE_SCENARIO_YAML))

        assert imported.form == {
            "name": "Bristol Phase 1",
            "n_homes": 100,
            "seed": 42,
            "pv": {
                "capacity_kw": {"type": "shuffled_pool", "values": [3.0, 4.0, 5.0, 6.0], "counts": [20, 40, 30, 10]}
            },
            "battery": {
                "capacity_kwh": {"type": "shuffled_pool", "values": [None, 5.0, 10.0], "counts": [40, 40, 20]}
            },
            "load": {
                "annual_consumption_kwh": {
                    "type": "normal",
                    "mean": 3400.0,
                    "std": 800.0,
                    "min": 2000.0,
                    "max": 6000.0,
                }
            },
            "seg": {"rate_pence_per_kwh": 4.1},
        }
        assert imported.not_loaded == (
            "fleet_distribution.random_order",
            "fleet_distribution.pv.azimuth",
            "fleet_distribution.pv.tilt",
            "finance",
        )

    @pytest.mark.parametrize(
        "capacity_kwh",
        [
            pytest.param(None, id="null"),
            pytest.param({"type": "fixed", "value": None}, id="fixed-null"),
        ],
    )
    def test_a_null_battery_capacity_loads_as_null(self, capacity_kwh: object) -> None:
        """A battery capacity of null, written as the capacity or as a fixed distribution's value, loads as null, the editor's blank Fixed Value, as a null among a pool's values does: the form runs no battery, as the scenario does."""
        battery = _FLEET_SCENARIO["fleet_distribution"]["battery"]
        document = _with_fleet_distribution(battery={**battery, "capacity_kwh": capacity_kwh})

        imported = fleet_form_from_scenario(document)

        assert imported == ImportedForm(
            form={**_FLEET_FORM, "battery": {"capacity_kwh": None}}, not_loaded=()
        )
        homes_the_form_runs = parse_fleet_form(imported.form).homes
        assert homes_the_form_runs == read_fleet_scenario(document).scenario().simulated_homes()
        assert all(home.battery_config is None for home in homes_the_form_runs)

    def test_a_location_other_than_bristol_is_not_loaded(self) -> None:
        """The fleet page has no location control and runs its fleet at Bristol, so a London scenario loads the rest and names its location."""
        london = {**_FLEET_SCENARIO, "location": location_block(LOCATION_PRESETS["london"])}

        assert fleet_form_from_scenario(london) == ImportedForm(
            form=_FLEET_FORM, not_loaded=("location",)
        )

    @pytest.mark.parametrize(
        ("period", "message"),
        [
            pytest.param(
                {"start_date": "2024-06-10", "end_date": "2024-06-01"},
                "period.end_date must not be before period.start_date, "
                "got period.start_date '2024-06-10' and period.end_date '2024-06-01'",
                id="end-before-start",
            ),
            pytest.param(
                yaml.safe_load("start_date: 2024-06-10\nend_date: 2024-06-01\n"),
                "period.end_date must not be before period.start_date, "
                "got period.start_date '2024-06-10' and period.end_date '2024-06-01'",
                id="yaml-dates-end-before-start",
            ),
            pytest.param(
                {"start_date": "2024-01-01", "end_date": "2025-12-31"},
                f"period.start_date to period.end_date must span at most {MAX_WINDOW_DAYS} days, "
                "got period.start_date '2024-01-01' and period.end_date '2025-12-31', 731 days",
                id="longer-than-the-page-runs",
            ),
        ],
    )
    def test_a_period_the_page_cannot_run_is_refused_naming_start_date_and_end_date(
        self, period: dict[str, Any], message: str
    ) -> None:
        """A period that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is refused with a ConfigurationError naming the scenario's period.start_date and period.end_date as read."""
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period})
        assert str(exc_info.value) == message

    def test_a_fractional_fleet_size_is_refused_with_the_loaders_refusal_naming_n_homes(self) -> None:
        """An n_homes of 2.5 is refused by the loaders' own reader, naming n_homes under fleet_distribution: the page reads no fleet size ahead of the loaders."""
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(n_homes=2.5))
        assert str(exc_info.value) == "fleet_distribution: n_homes must be a whole number, got 2.5"

    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    @pytest.mark.parametrize(
        "value",
        [
            *UNUSABLE_NUMBERS,
            pytest.param("x", id="non-numeric-string"),
            pytest.param(2.5, id="fraction"),
        ],
    )
    def test_a_fleet_size_or_seed_that_is_not_a_whole_number_is_refused_with_the_loaders_refusal(
        self, key: str, value: object
    ) -> None:
        """An n_homes or seed that is not a whole number, a boolean or a fraction included, is refused with the loaders' own refusal, naming it under fleet_distribution and the value as written.

        Loading a fractional one would run a different fleet: the page runs a whole number of
        homes, and a seed of 2.5 samples another fleet than a seed of 2, since
        random.Random(2.5) is not random.Random(2), while the page has no seed field to show it.
        """
        document = _with_fleet_distribution(**{key: value})
        with pytest.raises(ConfigurationError) as loader_refusal:
            parse_fleet_distribution_config(document["fleet_distribution"])
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario(document)
        assert str(exc_info.value) == str(loader_refusal.value)
        assert str(exc_info.value).startswith(f"fleet_distribution: {key} ")

    def test_a_seed_the_fleet_page_cannot_hold_exactly_is_refused_naming_it(self) -> None:
        """A seed beyond MAX_FLEET_SEED is refused with a ConfigurationError naming fleet_distribution.seed, the range and the value as written.

        The fleet page holds the seed as a JavaScript number, which reads 2**53 + 1 as 2**53, so
        loading it would run another fleet than the scenario's.
        """
        seed = MAX_FLEET_SEED + 2
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(seed=seed))
        assert str(exc_info.value) == (
            f"fleet_distribution.seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, "
            f"got {seed!r}"
        )

    def test_a_fleet_size_above_max_fleet_homes_is_refused_by_the_dashboards_bound_naming_it(self) -> None:
        """An n_homes the loaders accept but above the dashboard's fleet limit is refused with a ConfigurationError naming fleet_distribution.n_homes, the range and the value as written.

        The battery's pool, sized to the scenario's 3 homes, becomes a fixed capacity, since the
        loaders' F6 would refuse it first.
        """
        n_homes = MAX_FLEET_HOMES + 1
        battery = {**_FLEET_SCENARIO["fleet_distribution"]["battery"], "capacity_kwh": 5.0}
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(n_homes=n_homes, battery=battery))
        assert str(exc_info.value) == (
            f"fleet_distribution.n_homes must be between 1 and {MAX_FLEET_HOMES}, got {n_homes!r}"
        )

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "fleet_distribution": _without(_FLEET_SCENARIO["fleet_distribution"], "n_homes"),
                },
                id="absent",
            ),
            pytest.param(_with_fleet_distribution(n_homes=None), id="null"),
            pytest.param(_with_fleet_distribution(n_homes=0), id="no-homes"),
        ],
    )
    def test_a_fleet_without_a_size_the_loaders_accept_is_refused_with_their_refusal(
        self, document: dict[str, Any]
    ) -> None:
        """A fleet_distribution that leaves n_homes out, sets it null or sets it to no homes is refused with the loaders' own refusal, which names n_homes."""
        with pytest.raises(ConfigurationError) as loader_refusal:
            parse_fleet_distribution_config(document["fleet_distribution"])
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_form_from_scenario(document)
        assert str(exc_info.value) == str(loader_refusal.value)
        assert "n_homes" in str(exc_info.value)

    def test_a_fleet_size_and_seed_written_as_whole_floats_load_as_the_ints_they_equal(self) -> None:
        """An n_homes of 3.0 and a seed of 7.0 load as the ints 3 and 7, the fleet they run: random.Random(7.0) draws as random.Random(7) does."""
        imported = fleet_form_from_scenario(_with_fleet_distribution(n_homes=3.0, seed=7.0))

        assert imported == ImportedForm(form=_FLEET_FORM, not_loaded=())
        assert type(imported.form["n_homes"]) is int
        assert type(imported.form["seed"]) is int

    def test_a_pools_counts_written_as_whole_floats_load_as_the_ints_they_equal(self) -> None:
        """A battery pool's counts of 1.0 and 2.0 load as the ints 1 and 2, the counts the grammar reads them as."""
        battery = _FLEET_SCENARIO["fleet_distribution"]["battery"]
        pool = {**battery["capacity_kwh"], "counts": [1.0, 2.0]}

        imported = fleet_form_from_scenario(
            _with_fleet_distribution(battery={**battery, "capacity_kwh": pool})
        )

        assert imported == ImportedForm(form=_FLEET_FORM, not_loaded=())
        counts = imported.form["battery"]["capacity_kwh"]["counts"]
        assert [type(count) for count in counts] == [int, int]

    def test_a_fixed_spec_loads_as_its_number(self) -> None:
        """A pv.capacity_kw written as a fixed spec loads as the number the editor's Fixed Value holds, as the grammar reads it."""
        imported = fleet_form_from_scenario(_with_fleet_distribution(pv={"capacity_kw": {"type": "fixed", "value": 4}}))

        assert imported == ImportedForm(form={**_FLEET_FORM, "pv": {"capacity_kw": 4.0}}, not_loaded=())

    def test_a_normal_without_clamps_loads_with_null_clamps_and_its_form_runs_the_scenarios_fleet(self) -> None:
        """A normal that sets no min or max loads as the grammar's NormalDistribution written back, its clamps null, and the form loaded runs the fleet the scenario describes."""
        document = _with_fleet_distribution(load={"annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800}})

        imported = fleet_form_from_scenario(document)

        assert imported.form["load"] == {"annual_consumption_kwh": write_distribution_spec(NormalDistribution(3400, 800))}
        assert imported.form["load"]["annual_consumption_kwh"]["min"] is None
        assert imported.form["load"]["annual_consumption_kwh"]["max"] is None
        assert parse_fleet_form(imported.form).homes == read_fleet_scenario(document).scenario().simulated_homes()

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(
                {"type": "weighted_discrete", "values": [2900, 4500], "weights": [1, 3]}, id="weighted-discrete"
            ),
            pytest.param({"type": "normal", "mean": 3400, "std": 800, "min": 2000, "max": 6000}, id="normal"),
            pytest.param({"type": "uniform", "min": 2000, "max": 5000}, id="uniform"),
            pytest.param({"type": "shuffled_pool", "values": [2900, 4500], "counts": [2.0, 1.0]}, id="shuffled-pool"),
        ],
    )
    def test_each_type_the_editor_offers_loads_as_the_grammars_reading_written_back(self, spec: dict[str, Any]) -> None:
        """A load distribution of each type the editor offers loads as write_distribution_spec of the spec the grammar read: values beside their weights or counts lists, each number as the grammar holds it."""
        document = _with_fleet_distribution(load={"annual_consumption_kwh": spec})
        read = read_fleet_scenario(document).fleet.load.draws["annual_consumption_kwh"]

        imported = fleet_form_from_scenario(document)

        assert imported.form["load"] == {"annual_consumption_kwh": write_distribution_spec(read)}
        assert imported.not_loaded == ()

    def test_a_distribution_the_editor_does_not_offer_is_refused_naming_its_path_its_type_and_the_editors_types(
        self,
    ) -> None:
        """A load drawn proportional_to the home's PV is one the grammar reads but the editor cannot hold, so the import refuses it, naming its path, its type and the types the load's editor offers: loading anything else would run another fleet."""
        document = _with_fleet_distribution(
            load={"annual_consumption_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 800}}
        )
        read_fleet_scenario(document)
        offered = ", ".join(each.name for each in FLEET_COMPONENTS["load"].editor_types)

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(document)

        message = str(refusal.value)
        assert "fleet_distribution.load.annual_consumption_kwh" in message
        assert "'proportional_to'" in message
        assert offered in message

    def test_a_tariff_key_the_form_has_no_field_for_is_not_loaded(self) -> None:
        """An Economy 7 tariff loads its type and rates, and names the off-peak start the page has no field for."""
        tariff = {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1, "off_peak_start": "01:00"}

        assert fleet_form_from_scenario({**_FLEET_SCENARIO, "tariff": tariff}) == ImportedForm(
            form=_FLEET_FORM, not_loaded=("tariff.off_peak_start",)
        )

    @pytest.mark.parametrize(
        "dispatch_strategy",
        [
            pytest.param({"strategy_type": "tou_optimized"}, id="peak-hours-absent"),
            pytest.param({"strategy_type": "tou_optimized", "peak_hours": None}, id="peak-hours-null"),
        ],
    )
    def test_a_battery_dispatching_tou_optimized_on_its_tariffs_clock_loads_with_the_clock_chosen_and_runs(
        self, dispatch_strategy: dict[str, Any]
    ) -> None:
        """The fleet page holds the tariff's clock as a null peak_hours, so the strategy loads with it, every battery home dispatches on its Economy 7 tariff's clock, and a home runs.

        It replaces a test that named such a strategy not loaded: that pinned the control the
        page lacked, which it now has.
        """
        battery = {**_FLEET_SCENARIO["fleet_distribution"]["battery"], "dispatch_strategy": dispatch_strategy}

        imported = fleet_form_from_scenario(_with_fleet_distribution(battery=battery))

        assert imported == ImportedForm(
            form={**_FLEET_FORM, "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": None}},
            not_loaded=(),
        )
        parsed = parse_fleet_form(imported.form)
        battery_homes = [home for home in parsed.homes if home.battery_config is not None]
        assert battery_homes
        assert all(home.battery_config.dispatch_strategy == TOUOptimizedStrategyConfig() for home in battery_homes)
        home = battery_homes[0]
        day = parsed.start_date
        results = simulate_home(home, day, day, weather=weather_for(home, sunless_weather(day, temp_air=5.0)))
        assert len(results.tariff_rate) > 0

    def test_an_economy_tariff_that_sets_no_rate_loads_its_preset_rates(self) -> None:
        """An Economy 10 tariff that sets no rate loads the rates the loaders charge it, its PRESET_RATES row."""
        imported = fleet_form_from_scenario({**_FLEET_SCENARIO, "tariff": {"type": "economy_10"}})

        assert imported.form["tariff"] == {
            "type": "economy_10",
            "peak_rate": PRESET_RATES["economy_10"].peak_rate,
            "off_peak_rate": PRESET_RATES["economy_10"].off_peak_rate,
        }
        assert imported.not_loaded == ()

    def test_an_economy_tariff_that_sets_one_rate_loads_it_and_the_preset_rate_for_the_other(
        self,
    ) -> None:
        """An Economy 7 tariff that sets only its off-peak rate loads that rate, and its PRESET_RATES row's peak rate."""
        imported = fleet_form_from_scenario(
            {**_FLEET_SCENARIO, "tariff": {"type": "economy_7", "off_peak_rate": 0.1}}
        )

        assert imported.form["tariff"] == {
            "type": "economy_7",
            "peak_rate": PRESET_RATES["economy_7"].peak_rate,
            "off_peak_rate": 0.1,
        }
        assert imported.not_loaded == ()

    @pytest.mark.parametrize(
        ("document", "reason"),
        [
            pytest.param([_FLEET_SCENARIO], "mapping", id="list-document"),
            pytest.param(
                {"name": "One Home", "home": {"pv": {"capacity_kw": 4.0}}},
                "fleet_distribution",
                id="home-scenario",
            ),
            pytest.param(
                {**_FLEET_SCENARIO, "fleet_distribution": [_FLEET_SCENARIO["fleet_distribution"]]},
                "fleet_distribution must be a mapping, got list",
                id="list-fleet-distribution",
            ),
            pytest.param(
                {**_FLEET_SCENARIO, "fleet_distribution": None},
                "fleet_distribution must be a mapping, got NoneType",
                id="null-fleet-distribution",
            ),
            pytest.param(
                _with_fleet_distribution(
                    battery={
                        "capacity_kwh": {
                            "type": "proportional_to",
                            "source": "pv.capacity_kw",
                            "multiplier": 2.0,
                        }
                    }
                ),
                "fleet_distribution.battery.capacity_kwh",
                id="proportional-battery-capacity",
            ),
            pytest.param(
                _with_fleet_distribution(
                    pv={"capacity_kw": {"type": "shuffled_pool", "values": [None, 4.0], "counts": [1, 2]}}
                ),
                "fleet_distribution.pv.capacity_kw",
                id="null-in-a-pv-pool",
            ),
            pytest.param(
                _with_fleet_distribution(
                    battery={
                        **_FLEET_SCENARIO["fleet_distribution"]["battery"],
                        "capacity_kwh": {
                            "type": "shuffled_pool",
                            "values": [0.0, 5.0],
                            "counts": [1, 2.5],
                        },
                    }
                ),
                "fleet_distribution.battery.capacity_kwh: counts[1] must be a whole number, got 2.5",
                id="fractional-count-in-a-battery-pool",
            ),
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "tariff": {
                        "type": "custom",
                        "periods": [{"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": 0.25}],
                    },
                },
                "tariff.type",
                id="custom-tariff",
            ),
            pytest.param(
                _with_fleet_distribution(
                    battery={
                        **_FLEET_SCENARIO["fleet_distribution"]["battery"],
                        "dispatch_strategy": {
                            "strategy_type": "tou_optimized",
                            "peak_hours": [[8, 10], [16, 19]],
                        },
                    }
                ),
                "fleet_distribution.battery.dispatch_strategy.peak_hours",
                id="two-peak-windows",
            ),
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "period": yaml.safe_load(
                        "start_date: 2024-07-01 12:30:00\nend_date: 2024-07-10\n"
                    ),
                },
                "period.start_date",
                id="a-timestamp-with-a-time-of-day",
            ),
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "period": yaml.safe_load(
                        "start_date: 2024-07-01\nend_date: 2024-07-10T00:00:00Z\n"
                    ),
                },
                "period.end_date",
                id="a-timestamp-with-a-time-zone",
            ),
        ],
    )
    def test_a_scenario_the_form_cannot_hold_is_refused(self, document: object, reason: str) -> None:
        """A scenario whose fleet, period, tariff or dispatch the form cannot hold exactly is refused, naming the setting: loading it anyway would run a different fleet."""
        with pytest.raises(ConfigurationError, match=re.escape(reason)):
            fleet_form_from_scenario(document)

    def test_a_scenario_key_no_scenario_reads_is_refused_naming_it(self) -> None:
        """A misspelt finance: block is refused as parse_scenario refuses it, rather than named not loaded."""
        document = {**_FLEET_SCENARIO, "finanse": {"standing_charge_pence_per_day": 60.0}}
        with pytest.raises(ConfigurationError) as expected:
            parse_scenario(document)

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(document)

        assert str(refusal.value) == str(expected.value)
        assert "'finanse'" in str(refusal.value)

    def test_a_name_that_is_not_a_string_is_refused_as_parse_scenario_refuses_it(self) -> None:
        """The reader's refusal runs before the form's own reads of the scenario, so the name the form never holds is refused with its message."""
        document = {**_FLEET_SCENARIO, "name": 5}
        with pytest.raises(ConfigurationError) as expected:
            parse_scenario(document)
        assert str(expected.value) == "name: must be a string, got 5", "premise: the reader refuses the name"

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(document)

        assert str(refusal.value) == str(expected.value)

    def test_a_scenario_the_loaders_refuse_is_refused_with_their_message(self) -> None:
        """The loaders' refusal of a scenario is the import's refusal."""
        document = _with_fleet_distribution(
            pv={"capacity_kw": {"type": "weighted_discrete", "values": [3.0, 5.0]}}
        )

        with pytest.raises(
            ConfigurationError,
            match=re.escape(
                "fleet_distribution.pv.capacity_kw: requires 'weights'"
            ),
        ):
            fleet_form_from_scenario(document)

    def test_a_name_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        """YAML's \\u escape can write a lone surrogate into a scenario's name, and the page could not run that scenario's form, so the scenario is not loaded."""
        name = yaml.safe_load(r'"\ud800"')
        assert name == chr(0xD800), "premise: YAML reads the escape as a lone surrogate"
        with pytest.raises(ConfigurationError) as expected:
            require_encodable_text(name, "name")
        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario({**_FLEET_SCENARIO, "name": name})
        assert str(refusal.value) == str(expected.value)

    @pytest.mark.parametrize(
        "counts",
        [
            pytest.param([MAX_FLEET_HOMES + 1], id="a-pool-count-above-the-fleet-limit"),
            pytest.param([MAX_FLEET_HOMES, 1], id="pool-counts-totalling-more-than-the-fleet-limit"),
        ],
    )
    def test_a_pool_larger_than_the_fleet_limit_is_refused_by_the_loaders_naming_it(
        self, counts: list[int]
    ) -> None:
        """A shuffled pool holding more values than a dashboard fleet has homes is refused by the loaders, naming the pool and its total: a pool must total n_homes, which the import first bounds to MAX_FLEET_HOMES."""
        document = _with_fleet_distribution(
            pv={
                "capacity_kw": {
                    "type": "shuffled_pool",
                    "values": [4.0, 5.0][: len(counts)],
                    "counts": counts,
                }
            }
        )

        with pytest.raises(
            ConfigurationError,
            match=re.escape(
                "fleet_distribution: pv.capacity_kw: shuffled_pool counts must total n_homes (3), "
                f"got {MAX_FLEET_HOMES + 1}"
            ),
        ):
            fleet_form_from_scenario(document)

    def test_a_refused_tariff_is_refused_before_the_dashboards_bound_as_parse_scenario_reads_them(self) -> None:
        """The import reads the scenario's tariff before its fleet, as parse_scenario does, so a fleet above the dashboard's bound gets the tariff's refusal."""
        battery = {**_FLEET_SCENARIO["fleet_distribution"]["battery"], "capacity_kwh": 5.0}
        document = {
            **_with_fleet_distribution(n_homes=MAX_FLEET_HOMES + 1, battery=battery),
            "tariff": {"type": "flat_rate"},
        }
        with pytest.raises(ConfigurationError) as expected:
            parse_tariff_config({"type": "flat_rate"})

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(document)

        assert str(refusal.value) == str(expected.value)

    def test_a_setting_the_form_cannot_hold_is_refused_before_any_home_is_generated(self) -> None:
        """A scenario whose 0 kW PV only the generation of its homes refuses gets the form's refusal of its custom tariff, so the import generates no home before the form reads the scenario."""
        ungeneratable = _with_fleet_distribution(pv={"capacity_kw": 0})
        with pytest.raises(ConfigurationError) as generation_refusal:
            parse_scenario(ungeneratable)
        assert str(generation_refusal.value) == (
            "fleet_distribution.pv: home 1: capacity_kw must be greater than 0, got 0.0"
        ), "premise: only generation refuses the scenario's PV"
        custom_tariff = {
            "type": "custom",
            "periods": [{"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": 0.25}],
        }

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario({**ungeneratable, "tariff": custom_tariff})

        assert str(refusal.value) == (
            "tariff.type must be one the fleet page holds (flat_rate, economy_7, economy_10), got 'custom'"
        )

    def test_a_battery_whose_dispatch_reaches_its_tariffs_cheap_period_is_refused_as_parse_scenario_refuses_it(
        self,
    ) -> None:
        """A tou_optimized peak window reaching into Economy 7's off-peak is refused only by generating a home, which the import leaves to the form it loads."""
        battery = {
            **_FLEET_SCENARIO["fleet_distribution"]["battery"],
            "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[7, 9]]},
        }
        document = _with_fleet_distribution(battery=battery)
        with pytest.raises(ConfigurationError) as expected:
            parse_scenario(document)

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(document)

        assert str(refusal.value) == str(expected.value)

    def test_a_null_a_home_draws_from_a_pv_pool_is_refused_at_its_scenario_path_as_the_form_refuses_it_at_its_own(
        self,
    ) -> None:
        """A pool's null is held as written, but every home has PV, so a null a home draws is refused before any form is loaded or home generated, naming fleet_distribution.pv.capacity_kw, as parse_fleet_form refuses it naming pv.capacity_kw."""
        pool = {"type": "shuffled_pool", "values": [None, 4.0], "counts": [1, 2]}
        with pytest.raises(ConfigurationError) as form_refusal:
            parse_fleet_form({**_FLEET_FORM, "pv": {"capacity_kw": pool}})

        with pytest.raises(ConfigurationError) as refusal:
            fleet_form_from_scenario(_with_fleet_distribution(pv={"capacity_kw": pool}))

        assert str(form_refusal.value).startswith("pv.capacity_kw: required")
        assert str(refusal.value) == f"fleet_distribution.{form_refusal.value}"

    @pytest.mark.parametrize(
        ("blocks", "form", "not_loaded"),
        [
            pytest.param(
                {"pv": {**_FLEET_SCENARIO["fleet_distribution"]["pv"], "azimuth": 400}},
                _FLEET_FORM,
                ("fleet_distribution.pv.azimuth",),
                id="pv-azimuth-outside-0-to-360",
            ),
            pytest.param(
                {
                    "battery": {
                        "capacity_kwh": _FLEET_SCENARIO["fleet_distribution"]["battery"]["capacity_kwh"],
                        "grid_charging": {"target_soc_fraction": 0.8},
                    }
                },
                _without(_FLEET_FORM, "dispatch_strategy"),
                ("fleet_distribution.battery.grid_charging",),
                id="grid-charging-under-self-consumption",
            ),
        ],
    )
    def test_a_setting_only_generation_refuses_loads_the_rest_and_is_named_when_the_form_does_not_hold_it(
        self, blocks: dict[str, Any], form: dict[str, Any], not_loaded: tuple[str, ...]
    ) -> None:
        """The import generates only the form it loads, so a setting the form does not hold is never generated: a scenario that parse_scenario, fleet run and validate config refuse only while generating its homes, for such a setting, loads the rest and names the setting, which the page does not run."""
        document = _with_fleet_distribution(**blocks)
        with pytest.raises(ConfigurationError):
            parse_scenario(document)
        read_fleet_scenario(document)

        assert fleet_form_from_scenario(document) == ImportedForm(form=form, not_loaded=not_loaded)


@dataclasses.dataclass(frozen=True)
class _TurboStrategyConfig:
    """A dispatch strategy the fleet form has no title for."""

    strategy_type: Literal["turbo"] = dataclasses.field(default="turbo", init=False)


@dataclasses.dataclass(frozen=True)
class _BoostStrategyConfig:
    """A dispatch strategy setting, boost_kw, the fleet form has no setting for, under a strategy it titles."""

    boost_kw: float
    strategy_type: Literal["peak_shaving"] = dataclasses.field(default="peak_shaving", init=False)


def _dispatch_choice(strategy_type: str) -> FormChoice:
    (choice,) = (each for each in FLEET_FORM_DISPATCH if each.type == strategy_type)
    return choice


_PEAK_HOURS_PATH = "fleet_distribution.battery.dispatch_strategy.peak_hours"


class TestFleetFormVocabulary:
    """FLEET_FORM_TARIFFS and FLEET_FORM_DISPATCH: the tariff and dispatch choices the fleet form offers, each starting at a block the grammar reads (V1, V2)."""

    def test_the_dispatch_choices_are_the_dispatch_strategies_in_their_order(self) -> None:
        assert [choice.type for choice in FLEET_FORM_DISPATCH] == list(STRATEGY_CONFIG_BY_TYPE)

    def test_each_dispatch_choices_settings_are_its_strategys_fields_in_their_order(self) -> None:
        for choice in FLEET_FORM_DISPATCH:
            config = STRATEGY_CONFIG_BY_TYPE[choice.type]
            assert [setting.key for setting in choice.settings] == [
                each.name for each in dataclasses.fields(config) if each.init
            ]

    def test_a_strategy_the_form_has_no_title_for_is_refused_naming_it_and_the_titles_table(self) -> None:
        with pytest.raises(KeyError, match=r"_DISPATCH_TITLES has no entry for the dispatch strategy 'turbo'"):
            fleet_form_dispatch_choices({**STRATEGY_CONFIG_BY_TYPE, "turbo": _TurboStrategyConfig})

    def test_a_strategy_setting_the_form_has_no_setting_for_is_refused_naming_it_its_strategy_and_the_settings_table(
        self,
    ) -> None:
        with pytest.raises(
            KeyError,
            match=r"_DISPATCH_SETTINGS has no entry for the field 'boost_kw' of the dispatch strategy 'peak_shaving'",
        ):
            fleet_form_dispatch_choices({**STRATEGY_CONFIG_BY_TYPE, "peak_shaving": _BoostStrategyConfig})

    def test_the_first_dispatch_choice_is_the_strategy_a_battery_that_names_none_runs(self) -> None:
        assert STRATEGY_CONFIG_BY_TYPE[FLEET_FORM_DISPATCH[0].type]() == BatteryConfig(capacity_kwh=5.0).dispatch_strategy

    def test_each_dispatch_choice_starts_at_a_block_the_grammar_reads_as_its_strategy(self) -> None:
        for choice in FLEET_FORM_DISPATCH:
            strategy = parse_dispatch_strategy_config(choice.starting_block("strategy_type"))
            assert isinstance(strategy, STRATEGY_CONFIG_BY_TYPE[choice.type])

    def test_tou_optimized_holds_its_peak_hours_as_the_clock_or_one_window_starting_at_16_to_19(self) -> None:
        (setting,) = _dispatch_choice("tou_optimized").settings

        assert setting.key == "peak_hours"
        assert setting.input is SettingInput.CLOCK_OR_WINDOW
        assert setting.start == ((16, 19),)
        assert setting.within == Interval(0, 24)
        assert setting.step == 1

    def test_the_tariff_choices_are_flat_rate_and_the_economy_presets(self) -> None:
        assert [choice.type for choice in FLEET_FORM_TARIFFS] == ["flat_rate", "economy_7", "economy_10"]

    def test_each_tariff_choice_starts_at_a_block_the_grammar_reads_as_its_tariff(self) -> None:
        expected = {
            "flat_rate": TariffConfig.flat_rate(page_limits().flat_rate_start),
            "economy_7": TariffConfig.economy_7(),
            "economy_10": TariffConfig.economy_10(),
        }

        assert {choice.type: parse_tariff_config(choice.starting_block("type")) for choice in FLEET_FORM_TARIFFS} == (
            expected
        )

    def test_each_economy_choice_starts_at_its_preset_rates(self) -> None:
        for choice in FLEET_FORM_TARIFFS:
            if choice.type in PRESET_RATES:
                assert {setting.key: setting.start for setting in choice.settings} == dataclasses.asdict(
                    PRESET_RATES[choice.type]
                )

    @pytest.mark.parametrize(
        ("peak_hours", "read"),
        [
            pytest.param(None, None, id="the-tariffs-clock"),
            pytest.param([[16, 21]], [[16, 21]], id="one-window"),
        ],
    )
    def test_peak_hours_reads_the_clock_or_one_window(self, peak_hours: Any, read: Any) -> None:
        (setting,) = _dispatch_choice("tou_optimized").settings

        assert setting.read(peak_hours, _PEAK_HOURS_PATH) == read

    @pytest.mark.parametrize(
        "peak_hours",
        [
            pytest.param([[8, 10], [16, 19]], id="two-windows"),
            pytest.param([], id="no-window"),
        ],
    )
    def test_peak_hours_holding_other_than_one_window_is_refused_naming_its_path(self, peak_hours: Any) -> None:
        (setting,) = _dispatch_choice("tou_optimized").settings

        with pytest.raises(ConfigurationError, match=re.escape(_PEAK_HOURS_PATH)):
            setting.read(peak_hours, _PEAK_HOURS_PATH)

    def test_tou_optimizeds_json_is_its_type_and_its_peak_hours_input_and_start(self) -> None:
        assert _dispatch_choice("tou_optimized").as_json() == {
            "type": "tou_optimized",
            "settings": [{"key": "peak_hours", "input": "clock_or_window", "start": [[16, 19]]}],
        }

    @pytest.mark.parametrize(
        "choice",
        [pytest.param(choice, id=choice.type) for choice in (*FLEET_FORM_TARIFFS, *FLEET_FORM_DISPATCH)],
    )
    def test_each_choices_json_round_trips_through_json(self, choice: FormChoice) -> None:
        assert json.loads(json.dumps(choice.as_json(), allow_nan=False)) == choice.as_json()
