# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_presets.fleet_preset_names_among: which of a directory's scenario files the fleet page's form loads."""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("flask")

from solar_challenge.web.builtin_scenarios import scenario_files_in
from solar_challenge.web.fleet_presets import fleet_preset_names_among

#: A fleet scenario the fleet form loads.
_FLEET_SCENARIO = """\
fleet_distribution:
  n_homes: 2
  seed: 1
  pv:
    capacity_kw: {type: uniform, min: 3.0, max: 6.0}
  load:
    annual_consumption_kwh: {type: uniform, min: 2500, max: 4500}
"""

#: A scenario of one home, which the fleet form refuses: it has no fleet_distribution block.
_HOME_SCENARIO = """\
home:
  pv:
    capacity_kw: 4.0
"""


def test_the_files_the_fleet_form_loads_are_named_in_their_order(tmp_path: Path) -> None:
    """The names are those of the files the fleet form loads, in the files' order; a scenario it refuses is left out."""
    (tmp_path / "b-fleet.yaml").write_text(_FLEET_SCENARIO)
    (tmp_path / "a-fleet.yml").write_text(_FLEET_SCENARIO)
    (tmp_path / "home.yaml").write_text(_HOME_SCENARIO)

    assert fleet_preset_names_among(scenario_files_in(tmp_path)) == ("a-fleet", "b-fleet")


def test_a_file_is_named_as_its_text_reads_now(tmp_path: Path) -> None:
    """A file edited from a scenario the fleet form refuses to one it loads is named once edited: each call reads the files afresh."""
    scenario = tmp_path / "fleet.yaml"
    scenario.write_text(_HOME_SCENARIO)
    files = scenario_files_in(tmp_path)
    assert fleet_preset_names_among(files) == ()

    scenario.write_text(_FLEET_SCENARIO)

    assert fleet_preset_names_among(files) == ("fleet",)


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

    with caplog.at_level(logging.WARNING, logger="solar_challenge.web.fleet_presets"):
        names = fleet_preset_names_among(files)

    assert names == ("fleet",)
    assert [record.levelno for record in caplog.records if str(spoilt) in record.getMessage()] == [
        logging.WARNING
    ]
