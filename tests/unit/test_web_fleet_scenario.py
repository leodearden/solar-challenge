# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_scenario, called directly with fleet forms: the bodies fleet-simulator.js's buildPayload() posts."""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
import yaml

pytest.importorskip("flask")

from solar_challenge.config import parse_scenario
from solar_challenge.dispatch import SelfConsumptionStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import parse_fleet_distribution_config
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.scenario_blocks import (
    parse_dispatch_strategy_config,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.scenario_writer import location_block
from solar_challenge.tariff import PRESET_RATES
from solar_challenge.web.fleet_components import MAX_FLEET_HOMES, MAX_FLEET_SEED, MAX_WINDOW_DAYS
from solar_challenge.web.fleet_scenario import (
    FLEET_FORM_REFUSALS,
    ImportedFleetForm,
    ParsedFleetForm,
    fleet_form_from_scenario,
    parse_fleet_form,
    scenario_from_fleet_form,
)
from solar_challenge.web.request_boundary import require_encodable_text
from solar_challenge.web.simulation_params import parse_seg_tariff
from tests._fleet_form import valid_distribution_form
from tests._unusable_numbers import UNUSABLE_NUMBERS

_FLEET_FORM: dict[str, Any] = {
    "name": "Round Trip Fleet",
    "n_homes": 3,
    "seed": 7,
    "pv": {
        "capacity_kw": {
            "type": "weighted_discrete",
            "values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 3}],
        }
    },
    "battery": {
        "capacity_kwh": {
            "type": "shuffled_pool",
            "entries": [{"value": 0, "count": 1}, {"value": 5.0, "count": 2}],
        }
    },
    "load": {
        "annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800, "min": 2000, "max": 6000}
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
        with pytest.raises(ValueError) as exc_info:
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
        battery_pool = form["battery"]["capacity_kwh"]["entries"]
        homes_with_a_battery = sum(entry["count"] for entry in battery_pool if entry["value"] > 0)
        homes_without_a_battery = sum(entry["count"] for entry in battery_pool if entry["value"] == 0)

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
        with pytest.raises(FLEET_FORM_REFUSALS) as refusal:
            parse_fleet_form({**form, "dispatch_strategy": value})
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))


class TestParseFleetFormName:
    """The name parse_fleet_form reads: refused when it is text that does not encode as UTF-8, before the fleet is read."""

    def test_a_name_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        with pytest.raises(ValueError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ValueError) as refusal:
            parse_fleet_form({**_FLEET_FORM, "name": chr(0xD800)})
        assert str(refusal.value) == str(expected.value)

    def test_a_name_holding_a_lone_surrogate_is_refused_before_the_fleet_is_read(self) -> None:
        """A form whose pv distribution is refused too gets the name's refusal, so a refused name costs no home generation."""
        with pytest.raises(ValueError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ValueError) as refusal:
            parse_fleet_form({**_without(_FLEET_FORM, "pv"), "name": chr(0xD800)})
        assert str(refusal.value) == str(expected.value)


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
        with pytest.raises(FLEET_FORM_REFUSALS) as expected:
            parse_fleet_form({**form, key: value})
        with pytest.raises(FLEET_FORM_REFUSALS) as refusal:
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

    @pytest.mark.parametrize(
        ("key", "value", "read_block"),
        [
            pytest.param(
                "tariff", {"type": "flat_rate"}, lambda: parse_tariff_config({"type": "flat_rate"}), id="tariff"
            ),
            pytest.param("seg", {}, lambda: parse_seg_rate({}), id="seg"),
        ],
    )
    def test_a_refused_tariff_or_seg_is_refused_before_a_refused_fleet_distribution_as_parse_scenario_reads_them(
        self, key: str, value: Any, read_block: Callable[[], object]
    ) -> None:
        """The reader reads the tariff and SEG before the homes source, so a fleet grammar refusal is the later block's."""
        form = {**_FLEET_FORM, key: value, "battery": {"capacity_kwh": {"type": "uniform"}}}
        with pytest.raises(ConfigurationError) as expected:
            read_block()
        with pytest.raises(FLEET_FORM_REFUSALS) as refusal:
            parse_fleet_form(form)
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))

    @pytest.mark.parametrize(("key", "value", "read_block"), _A_REFUSED_TARIFF_OR_SEG_WITH_ITS_READERS_READING)
    def test_a_refused_tariff_or_seg_is_refused_before_the_dashboards_bound_on_the_fleet(
        self, key: str, value: Any, read_block: Callable[[], object]
    ) -> None:
        """The reader reads the tariff and SEG before the fleet, so a fleet the dashboard cannot run gets the earlier block's refusal."""
        form = {**_FLEET_FORM_WITHOUT_A_POOL, "n_homes": MAX_FLEET_HOMES + 1, key: value}
        with pytest.raises(ConfigurationError) as expected:
            read_block()
        with pytest.raises(FLEET_FORM_REFUSALS) as refusal:
            parse_fleet_form(form)
        assert (type(refusal.value), str(refusal.value)) == (type(expected.value), str(expected.value))

    def test_a_fleet_that_sweeps_is_refused_as_parse_scenario_refuses_its_document(self) -> None:
        """A sweep defines one fleet per point, which 'fleet sweep' runs, so the form's one fleet is refused naming the swept field."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_form({**_FLEET_FORM, "battery": {"capacity_kwh": _A_SWEPT_BATTERY_CAPACITY}})

        assert "fleet_distribution.battery.capacity_kwh: a sweep multiplier of 3 points" in str(refusal.value)
        assert "'fleet sweep'" in str(refusal.value)


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
                        "capacity_kw": {"type": "weighted_discrete", "values": [{"value": 0, "weight": 1}]}
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
        with pytest.raises((ValueError, ConfigurationError), match=reason):
            scenario_from_fleet_form(form)

    def test_a_name_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        """No YAML is written for a name the simulate endpoint refuses."""
        with pytest.raises(ValueError) as expected:
            require_encodable_text(chr(0xD800), "name")
        with pytest.raises(ValueError) as refusal:
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
        """The scenario a fleet form describes reads back as that form: its distributions as the editors' rows, its battery's dispatch as the form's dispatch strategy, and its period as start and end dates."""
        assert fleet_form_from_scenario(_FLEET_SCENARIO) == ImportedFleetForm(
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
                        "annual_consumption_kwh": {
                            "type": "shuffled_pool",
                            "entries": [{"value": 2900, "count": 2}, {"value": 4500, "count": 1}],
                        }
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
        ],
    )
    def test_an_exported_fleet_form_imports_back_to_the_same_scenario(
        self, form: dict[str, Any]
    ) -> None:
        """Every setting of a scenario the page exports is one the form holds, and the form read back describes that scenario."""
        document = scenario_from_fleet_form(form)

        imported = fleet_form_from_scenario(document)

        assert imported.not_loaded == ()
        assert scenario_from_fleet_form(imported.form) == document

    def test_a_scenario_file_loads_what_the_form_holds_and_names_the_rest(self) -> None:
        """A scenario file loads its name, fleet size, seed, distributions and SEG; the settings the form has no control for are named, in document order.

        A null battery capacity reads as 0 kWh: either way the home has no battery.
        """
        imported = fleet_form_from_scenario(yaml.safe_load(_BRISTOL_LIKE_SCENARIO_YAML))

        assert imported.form == {
            "name": "Bristol Phase 1",
            "n_homes": 100,
            "seed": 42,
            "pv": {
                "capacity_kw": {
                    "type": "shuffled_pool",
                    "entries": [
                        {"value": 3.0, "count": 20},
                        {"value": 4.0, "count": 40},
                        {"value": 5.0, "count": 30},
                        {"value": 6.0, "count": 10},
                    ],
                }
            },
            "battery": {
                "capacity_kwh": {
                    "type": "shuffled_pool",
                    "entries": [
                        {"value": 0.0, "count": 40},
                        {"value": 5.0, "count": 40},
                        {"value": 10.0, "count": 20},
                    ],
                }
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

    def test_a_location_other_than_bristol_is_not_loaded(self) -> None:
        """The fleet page has no location control and runs its fleet at Bristol, so a London scenario loads the rest and names its location."""
        london = {**_FLEET_SCENARIO, "location": location_block(LOCATION_PRESETS["london"])}

        assert fleet_form_from_scenario(london) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=("location",)
        )

    def test_a_period_of_midnight_timestamps_loads_as_its_days(self) -> None:
        """YAML reads `2024-07-01 00:00:00` as a timestamp; at midnight it is that day, which the page's date fields hold as an ISO date."""
        period = yaml.safe_load("start_date: 2024-07-01 00:00:00\nend_date: 2024-07-10 00:00:00\n")
        assert isinstance(period["start_date"], datetime), "premise: YAML reads a timestamp"

        assert fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period}) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=()
        )

    @pytest.mark.parametrize("key", ["start_date", "end_date"])
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("2024/07/01", id="slashes"),
            pytest.param("2024-02-30", id="no-such-day"),
            pytest.param("", id="empty-string"),
            pytest.param(20240701, id="number"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_period_date_that_is_not_an_iso_date_is_refused_naming_it(
        self, key: str, value: object
    ) -> None:
        """A period date that is neither a YAML date nor an ISO 8601 date string (YYYY-MM-DD) is refused with a ValueError naming it as period.<key> and the value as written; the other date is the round trip's."""
        period = {**_FLEET_SCENARIO["period"], key: value}
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period})
        assert str(exc_info.value) == f"period.{key} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}"

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
        """A period that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is refused with a ValueError naming the scenario's period.start_date and period.end_date as read."""
        with pytest.raises(ValueError) as exc_info:
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
        """A seed beyond MAX_FLEET_SEED is refused with a ValueError naming fleet_distribution.seed, the range and the value as written.

        The fleet page holds the seed as a JavaScript number, which reads 2**53 + 1 as 2**53, so
        loading it would run another fleet than the scenario's.
        """
        seed = MAX_FLEET_SEED + 2
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(seed=seed))
        assert str(exc_info.value) == (
            f"fleet_distribution.seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, "
            f"got {seed!r}"
        )

    def test_a_fleet_size_above_max_fleet_homes_is_refused_by_the_dashboards_bound_naming_it(self) -> None:
        """An n_homes the loaders accept but above the dashboard's fleet limit is refused with a ValueError naming fleet_distribution.n_homes, the range and the value as written.

        The battery's pool, sized to the scenario's 3 homes, becomes a fixed capacity, since the
        loaders' F6 would refuse it first.
        """
        n_homes = MAX_FLEET_HOMES + 1
        battery = {**_FLEET_SCENARIO["fleet_distribution"]["battery"], "capacity_kwh": 5.0}
        with pytest.raises(ValueError) as exc_info:
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

        assert imported == ImportedFleetForm(form=_FLEET_FORM, not_loaded=())
        assert type(imported.form["n_homes"]) is int
        assert type(imported.form["seed"]) is int

    def test_a_pools_counts_written_as_whole_floats_load_as_the_ints_they_equal(self) -> None:
        """A battery pool's counts of 1.0 and 2.0 load as the ints 1 and 2, the counts the loaders read them as."""
        battery = _FLEET_SCENARIO["fleet_distribution"]["battery"]
        pool = {**battery["capacity_kwh"], "counts": [1.0, 2.0]}

        imported = fleet_form_from_scenario(
            _with_fleet_distribution(battery={**battery, "capacity_kwh": pool})
        )

        assert imported == ImportedFleetForm(form=_FLEET_FORM, not_loaded=())
        entries = imported.form["battery"]["capacity_kwh"]["entries"]
        assert [type(entry["count"]) for entry in entries] == [int, int]

    def test_a_tariff_key_the_form_has_no_field_for_is_not_loaded(self) -> None:
        """An Economy 7 tariff loads its type and rates, and names the off-peak start the page has no field for."""
        tariff = {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1, "off_peak_start": "01:00"}

        assert fleet_form_from_scenario({**_FLEET_SCENARIO, "tariff": tariff}) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=("tariff.off_peak_start",)
        )

    @pytest.mark.parametrize(
        "dispatch_strategy",
        [
            pytest.param({"strategy_type": "tou_optimized"}, id="peak-hours-absent"),
            pytest.param({"strategy_type": "tou_optimized", "peak_hours": None}, id="peak-hours-null"),
        ],
    )
    def test_a_battery_dispatching_tou_optimized_on_its_tariffs_clock_is_not_loaded(
        self, dispatch_strategy: dict[str, Any]
    ) -> None:
        """The fleet page has no control for a tou_optimized on its tariff's clock, so the rest loads and the battery's dispatch_strategy is named."""
        battery = {**_FLEET_SCENARIO["fleet_distribution"]["battery"], "dispatch_strategy": dispatch_strategy}

        assert fleet_form_from_scenario(_with_fleet_distribution(battery=battery)) == ImportedFleetForm(
            form=_without(_FLEET_FORM, "dispatch_strategy"),
            not_loaded=("fleet_distribution.battery.dispatch_strategy",),
        )

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
        with pytest.raises(ValueError, match=re.escape(reason)):
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
        with pytest.raises(ValueError) as expected:
            require_encodable_text(name, "name")
        with pytest.raises(ValueError) as refusal:
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
