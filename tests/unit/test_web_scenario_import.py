# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.scenario_import, the import rules the fleet page and the scenario builder share."""

import dataclasses
from datetime import date, datetime
from typing import Any

import pytest
import yaml

pytest.importorskip("flask")

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    NormalDistribution,
    parse_fleet_distribution_config,
    write_distribution_spec,
)
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.scenario_import import (
    ImportedForm,
    not_loaded,
    read_blocks,
    read_component,
    read_period,
    read_seg,
    read_typed_block,
    required,
    scenario_yaml_document,
)
from solar_challenge.web.simulation_params import read_iso_date

_PAGES = [pytest.param("fleet page", id="fleet-page"), pytest.param("builder", id="builder")]


def _pv_read(fleet: dict[str, Any]) -> tuple[Any, ...]:
    """read_component's reading of the pv block of the fleet_distribution block *fleet*, as the grammar reads it."""
    parsed = parse_fleet_distribution_config(fleet)
    return read_component(fleet, "fleet_distribution", FLEET_COMPONENTS["pv"], parsed.pv)


class TestImportedForm:
    """ImportedForm, a scenario read as a page's form."""

    def test_an_imported_form_is_frozen(self) -> None:
        imported = ImportedForm(form={"n_homes": 1}, not_loaded=())

        with pytest.raises(dataclasses.FrozenInstanceError):
            imported.not_loaded = ("finance",)


class TestScenarioYamlDocument:
    """scenario_yaml_document reads YAML text as the document it holds, and refuses text that is not YAML."""

    def test_text_that_does_not_parse_as_yaml_is_refused_naming_the_parsers_error(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            scenario_yaml_document("name: [unclosed")
        assert str(refusal.value).startswith("Invalid YAML: ")

    def test_yaml_text_is_the_document_it_holds(self) -> None:
        assert scenario_yaml_document("name: Fleet\nfleet_distribution:\n  n_homes: 2\n") == {
            "name": "Fleet",
            "fleet_distribution": {"n_homes": 2},
        }


class TestReadPeriod:
    """read_period reads a scenario's period as its two days, by the rules both pages' date fields share."""

    @pytest.mark.parametrize("page", _PAGES)
    def test_no_period_reads_as_none(self, page: str) -> None:
        assert read_period(None, page) is None

    def test_a_period_of_iso_dates_reads_as_its_days(self) -> None:
        assert read_period({"start_date": "2024-07-01", "end_date": "2024-07-10"}, "builder") == (
            date(2024, 7, 1),
            date(2024, 7, 10),
        )

    def test_a_period_of_midnight_timestamps_reads_as_its_days(self) -> None:
        """YAML reads `2024-07-01 00:00:00` as a timestamp; at midnight it is that day, which the pages' date fields hold as an ISO date."""
        period = yaml.safe_load("start_date: 2024-07-01 00:00:00\nend_date: 2024-07-10 00:00:00\n")
        assert isinstance(period["start_date"], datetime), "premise: YAML reads a timestamp"

        assert read_period(period, "fleet page") == (date(2024, 7, 1), date(2024, 7, 10))

    def test_a_reversed_or_long_window_reads_as_its_days(self) -> None:
        """The two days are read alone: bounding the window is the page's own rule, not the shared reader's."""
        assert read_period({"start_date": "2025-12-31", "end_date": "2024-01-01"}, "builder") == (
            date(2025, 12, 31),
            date(2024, 1, 1),
        )

    @pytest.mark.parametrize("page", _PAGES)
    @pytest.mark.parametrize(
        ("period_yaml", "path"),
        [
            pytest.param("start_date: 2024-07-01 12:30:00\nend_date: 2024-07-10\n", "period.start_date", id="time-of-day"),
            pytest.param("start_date: 2024-07-01\nend_date: 2024-07-10T00:00:00Z\n", "period.end_date", id="time-zone"),
        ],
    )
    def test_a_timestamp_the_date_fields_cannot_hold_is_refused_naming_it_and_the_page(
        self, page: str, period_yaml: str, path: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_period(yaml.safe_load(period_yaml), page)

        message = str(refusal.value)
        assert message.startswith(f"{path} must be a day, got ")
        assert message.endswith(f": the {page}'s date fields hold no time of day or time zone")

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
    def test_a_period_date_that_is_not_an_iso_date_is_refused_as_read_iso_date_refuses_it_naming_it(
        self, key: str, value: object
    ) -> None:
        """A period date that is neither a YAML date nor an ISO 8601 date string is refused as read_iso_date refuses it at period.<key>; the other date is a valid one."""
        path = f"period.{key}"
        with pytest.raises(ConfigurationError) as iso_refusal:
            read_iso_date(value, path)
        period = {"start_date": "2024-07-01", "end_date": "2024-07-10", key: value}

        with pytest.raises(ConfigurationError) as refusal:
            read_period(period, "builder")

        assert str(refusal.value) == str(iso_refusal.value)
        assert path in str(refusal.value)

    def test_a_period_that_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_period(["2024-07-01", "2024-07-10"], "builder")
        assert str(refusal.value) == "period must be a mapping, got list"


class TestReadBlocks:
    """read_blocks and not_loaded: a block as a page's form holds it, naming each setting of it the form does not hold."""

    def test_each_key_not_read_and_each_unheld_setting_of_a_read_key_is_named_in_the_blocks_order(self) -> None:
        block = {"a": 1, "b": {"x": 1, "y": 2}, "c": 3}
        reads = {"b": ({"b_x": 1}, ("top.b.y",))}

        assert read_blocks(block, "top", reads) == ({"b_x": 1}, ("top.a", "top.b.y", "top.c"))

    def test_the_forms_settings_are_those_of_every_read(self) -> None:
        block = {"a": 1, "b": 2}
        reads = {"a": ({"first": 1}, ()), "b": ({"second": 2, "third": 3}, ())}

        assert read_blocks(block, "", reads) == ({"first": 1, "second": 2, "third": 3}, ())

    def test_a_top_level_key_is_named_by_itself(self) -> None:
        assert not_loaded({"finance": {}, "name": "Fleet"}, "", {"name": ()}) == ("finance",)

    def test_a_held_keys_own_unheld_settings_are_named_in_its_place(self) -> None:
        held = {"battery": ("fleet_distribution.battery.dispatch_strategy",)}

        assert not_loaded({"n_homes": 2, "battery": {}}, "fleet_distribution", held) == (
            "fleet_distribution.n_homes",
            "fleet_distribution.battery.dispatch_strategy",
        )


class TestReadComponent:
    """read_component loads a component block's field as its editor loads the grammar's reading of it (E3)."""

    def test_a_fixed_spec_loads_as_its_number(self) -> None:
        fleet = {"n_homes": 2, "pv": {"capacity_kw": {"type": "fixed", "value": 4}}}

        assert _pv_read(fleet) == ({"pv": {"capacity_kw": 4.0}}, ())

    def test_a_normal_without_clamps_loads_with_null_clamps(self) -> None:
        fleet = {"n_homes": 2, "pv": {"capacity_kw": {"type": "normal", "mean": 4, "std": 1}}}

        form, unheld = _pv_read(fleet)

        assert form == {"pv": {"capacity_kw": write_distribution_spec(NormalDistribution(4, 1))}}
        assert form["pv"]["capacity_kw"]["min"] is None
        assert form["pv"]["capacity_kw"]["max"] is None
        assert unheld == ()

    def test_a_distribution_the_editor_does_not_offer_is_refused_naming_its_path_and_the_editors_types(self) -> None:
        fleet = {
            "n_homes": 2,
            "pv": {"capacity_kw": 4},
            "battery": {"capacity_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 2}},
        }
        parsed = parse_fleet_distribution_config(fleet)
        limits = FLEET_COMPONENTS["battery"]
        with pytest.raises(ConfigurationError) as editor_refusal:
            limits.editor_spec(parsed.battery.draws["capacity_kwh"], "fleet_distribution.battery.capacity_kwh")

        with pytest.raises(ConfigurationError) as refusal:
            read_component(fleet, "fleet_distribution", limits, parsed.battery)

        assert str(refusal.value) == str(editor_refusal.value)
        assert "fleet_distribution.battery.capacity_kwh" in str(refusal.value)
        assert ", ".join(each.name for each in limits.editor_types) in str(refusal.value)

    def test_a_setting_of_the_block_other_than_its_field_is_named(self) -> None:
        fleet = {"n_homes": 2, "pv": {"capacity_kw": 4, "azimuth": 180}}

        assert _pv_read(fleet) == ({"pv": {"capacity_kw": 4.0}}, ("fleet_distribution.pv.azimuth",))


class TestReadSeg:
    """read_seg reads a scenario's SEG as the page's form holds it, given the SEG keys the page holds."""

    def test_a_held_key_loads_as_given(self) -> None:
        seg = {"rate_pence_per_kwh": 4.1}

        assert read_seg(seg, frozenset({"rate_pence_per_kwh"}), "builder") == ({"seg": {"rate_pence_per_kwh": 4.1}}, ())

    def test_no_seg_loads_none(self) -> None:
        assert read_seg(None, frozenset({"rate_pence_per_kwh"}), "builder") == ({}, ())

    @pytest.mark.parametrize("page", _PAGES)
    def test_a_preset_the_page_does_not_hold_is_refused_naming_it_and_the_page(self, page: str) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_seg({"preset": "Octopus"}, frozenset({"rate_pence_per_kwh"}), page)

        message = str(refusal.value)
        assert "seg.preset" in message
        assert f"the {page}" in message
        assert "'Octopus'" in message


class TestReadTypedBlock:
    """read_typed_block reads a block whose type names its settings, as the page's settings table holds it."""

    _SETTINGS = {"flat_rate": {"rate_per_kwh": required("builder")}}

    def test_a_held_type_loads_its_held_settings_and_names_the_rest(self) -> None:
        tariff = {"type": "flat_rate", "rate_per_kwh": 0.3, "name": "Flat"}

        assert read_typed_block(tariff, "tariff", "type", self._SETTINGS, "builder") == (
            {"type": "flat_rate", "rate_per_kwh": 0.3},
            ("tariff.name",),
        )

    @pytest.mark.parametrize("page", _PAGES)
    def test_a_type_the_page_does_not_hold_is_refused_naming_its_type_key_the_page_and_the_types_it_holds(
        self, page: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_typed_block({"type": "economy_7"}, "tariff", "type", self._SETTINGS, page)

        assert str(refusal.value) == f"tariff.type must be one the {page} holds (flat_rate), got 'economy_7'"

    @pytest.mark.parametrize("page", _PAGES)
    def test_a_required_setting_left_out_is_refused_naming_it_and_the_page(self, page: str) -> None:
        settings = {"flat_rate": {"rate_per_kwh": required(page)}}

        with pytest.raises(ConfigurationError) as refusal:
            read_typed_block({"type": "flat_rate"}, "tariff", "type", settings, page)

        assert str(refusal.value) == f"tariff.rate_per_kwh must be set: the {page} always sets it"
