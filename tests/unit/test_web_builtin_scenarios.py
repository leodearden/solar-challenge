# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builtin_scenarios: the scenario files a directory holds, each by its name, and those a page's importer loads."""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("flask")

from solar_challenge.errors import ConfigurationError
from solar_challenge.web.builder_form import builder_form_from_yaml
from solar_challenge.web.builtin_scenarios import (
    builtin_scenario_files,
    builtin_scenario_form,
    builtin_scenarios_loaded_by,
    scenario_files_in,
    scenario_files_loaded_by,
)
from solar_challenge.web.fleet_scenario import fleet_form_from_yaml
from tests._default_pv_pool_fleet import DEFAULT_PV_POOL_FLEET_YAML
from tests._error_records import error_records
from tests._repository_paths import SCENARIOS_DIR

_LOGGER = "solar_challenge.web.builtin_scenarios"

#: A fleet scenario both pages' forms load.
_FLEET_SCENARIO = """\
fleet_distribution:
  n_homes: 2
  seed: 1
  pv:
    capacity_kw: {type: uniform, min: 3.0, max: 6.0}
  load:
    annual_consumption_kwh: {type: uniform, min: 2500, max: 4500}
"""

#: _FLEET_SCENARIO on an Economy 7 tariff, which the fleet form holds and the builder's does not.
_ECONOMY_7_FLEET_SCENARIO = f"{_FLEET_SCENARIO}tariff:\n  type: economy_7\n"

#: A scenario of one home, which both pages' forms refuse: it has no fleet_distribution block.
_HOME_SCENARIO = """\
home:
  pv:
    capacity_kw: 4.0
"""


def test_scenario_files_are_named_by_their_stems_in_name_order(tmp_path: Path) -> None:
    """Each .yaml and .yml file is named by its stem, in name order: bristol before bristol-aged, whose file name sorts first."""
    for file_name in ("bristol-aged.yaml", "bristol.yaml", "arbitrage.yml"):
        (tmp_path / file_name).write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [
        ("arbitrage", tmp_path / "arbitrage.yml"),
        ("bristol", tmp_path / "bristol.yaml"),
        ("bristol-aged", tmp_path / "bristol-aged.yaml"),
    ]


def test_a_name_with_both_a_yaml_and_a_yml_file_means_its_yaml_file(tmp_path: Path) -> None:
    """A stem with a file of each suffix is one scenario, its .yaml file."""
    (tmp_path / "fleet.yml").write_text("")
    (tmp_path / "fleet.yaml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yaml")]


def test_a_name_with_only_a_yml_file_means_its_yml_file(tmp_path: Path) -> None:
    """A stem with a .yml file and no .yaml file is that .yml file."""
    (tmp_path / "fleet.yml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yml")]


def test_entries_that_are_not_yaml_files_are_not_scenario_files(tmp_path: Path) -> None:
    """A file of another suffix is not a scenario, nor is a directory named like one: its stem means the .yml file beside it."""
    (tmp_path / "notes.txt").write_text("")
    (tmp_path / "fleet.yaml").mkdir()
    (tmp_path / "fleet.yml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yml")]


def test_a_missing_directory_holds_no_scenario_files(tmp_path: Path) -> None:
    """A directory that does not exist, as scenarios/ in an installed package, holds none."""
    assert scenario_files_in(tmp_path / "scenarios") == {}


def test_the_files_the_importer_loads_are_named_in_their_order(tmp_path: Path) -> None:
    """The names are those of the files the importer loads, in the files' order; a scenario it refuses is left out."""
    (tmp_path / "b-fleet.yaml").write_text(_FLEET_SCENARIO)
    (tmp_path / "a-fleet.yml").write_text(_FLEET_SCENARIO)
    (tmp_path / "home.yaml").write_text(_HOME_SCENARIO)

    assert scenario_files_loaded_by(scenario_files_in(tmp_path), fleet_form_from_yaml) == ("a-fleet", "b-fleet")


@pytest.mark.parametrize(
    ("importer", "names"),
    [
        pytest.param(fleet_form_from_yaml, ("economy-7", "flat"), id="fleet-page"),
        pytest.param(builder_form_from_yaml, ("flat",), id="builder"),
    ],
)
def test_each_page_is_offered_the_files_its_own_importer_loads(
    tmp_path: Path, importer: Callable[[str], object], names: tuple[str, ...]
) -> None:
    """An Economy 7 fleet is loaded by the fleet page's importer and left out by the builder's, which holds only flat_rate."""
    (tmp_path / "economy-7.yaml").write_text(_ECONOMY_7_FLEET_SCENARIO)
    (tmp_path / "flat.yaml").write_text(_FLEET_SCENARIO)

    assert scenario_files_loaded_by(scenario_files_in(tmp_path), importer) == names


def test_a_scenario_the_importer_refuses_is_left_out_and_a_debug_record_names_the_file_and_the_refusal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    home = tmp_path / "home.yaml"
    home.write_text(_HOME_SCENARIO)
    with pytest.raises(ConfigurationError) as refusal:
        fleet_form_from_yaml(_HOME_SCENARIO)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert scenario_files_loaded_by(scenario_files_in(tmp_path), fleet_form_from_yaml) == ()

    [record] = [record for record in caplog.records if record.name == _LOGGER]
    assert record.levelno == logging.DEBUG
    assert str(home) in record.getMessage()
    assert str(refusal.value) in record.getMessage()
    assert "is not offered as a preset" in record.getMessage()


def test_a_file_is_named_as_its_text_reads_now(tmp_path: Path) -> None:
    """A file edited from a scenario the importer refuses to one it loads is named once edited: each call reads the files afresh."""
    scenario = tmp_path / "fleet.yaml"
    scenario.write_text(_HOME_SCENARIO)
    files = scenario_files_in(tmp_path)
    assert scenario_files_loaded_by(files, fleet_form_from_yaml) == ()

    scenario.write_text(_FLEET_SCENARIO)

    assert scenario_files_loaded_by(files, fleet_form_from_yaml) == ("fleet",)


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(Path.unlink, id="removed-after-listing"),
        pytest.param(lambda path: path.write_bytes("# Café\n".encode("latin-1")), id="not-utf-8"),
    ],
)
def test_a_file_that_cannot_be_read_as_utf8_text_is_left_out_and_a_warning_names_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, spoil: Callable[[Path], object]
) -> None:
    """A file gone by the time it is read, or not UTF-8, is left out while the others are named, and a warning names it."""
    (tmp_path / "fleet.yaml").write_text(_FLEET_SCENARIO)
    spoilt = tmp_path / "spoilt.yaml"
    spoilt.write_text(_FLEET_SCENARIO)
    files = scenario_files_in(tmp_path)
    spoil(spoilt)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        names = scenario_files_loaded_by(files, fleet_form_from_yaml)

    assert names == ("fleet",)
    assert [record.levelno for record in caplog.records if str(spoilt) in record.getMessage()] == [
        logging.WARNING
    ]


def test_a_value_error_from_the_importer_that_is_not_a_configuration_error_leaves_the_file_out_logged_as_a_probable_defect(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def importer_failing(yaml_text: str) -> object:
        raise ValueError("probe")

    (tmp_path / "fleet.yaml").write_text(_FLEET_SCENARIO)

    assert scenario_files_loaded_by(scenario_files_in(tmp_path), importer_failing) == ()
    [record] = error_records(caplog)
    assert "ValueError" in record.getMessage()


def test_a_type_error_from_the_importer_is_not_a_refusal_and_propagates(tmp_path: Path) -> None:
    def importer_failing(yaml_text: str) -> object:
        raise TypeError("probe")

    (tmp_path / "fleet.yaml").write_text(_FLEET_SCENARIO)

    with pytest.raises(TypeError, match="probe"):
        scenario_files_loaded_by(scenario_files_in(tmp_path), importer_failing)


def test_a_scenario_file_holding_the_fleet_pages_default_pv_pool_with_200_homes_is_not_offered_and_logs_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Row R4: the pool holds 100 values for 200 homes, a refusal, not a defect."""
    (tmp_path / "default-pool.yaml").write_text(DEFAULT_PV_POOL_FLEET_YAML)

    assert scenario_files_loaded_by(scenario_files_in(tmp_path), fleet_form_from_yaml) == ()
    assert error_records(caplog) == []


def test_the_builtin_scenarios_an_importer_loads_are_those_of_the_builtin_files_it_loads() -> None:
    assert builtin_scenarios_loaded_by(builder_form_from_yaml) == scenario_files_loaded_by(
        builtin_scenario_files(), builder_form_from_yaml
    )


def test_no_form_is_read_for_a_name_no_builtin_file_holds() -> None:
    assert builtin_scenario_form("no-such-scenario", fleet_form_from_yaml) is None


def test_a_builtin_scenarios_form_is_the_importers_reading_of_its_files_text() -> None:
    def text_itself(yaml_text: str) -> str:
        return yaml_text

    assert builtin_scenario_form("bristol-phase1", text_itself) == (SCENARIOS_DIR / "bristol-phase1.yaml").read_text(
        encoding="utf-8"
    )
