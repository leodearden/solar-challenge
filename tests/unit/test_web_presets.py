# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.presets: the cause of the SavedPresetUnreadable saved_fleet_preset_named raises for a saved fleet preset whose config is not a JSON object, which is json.loads's refusal when there is one.

The error's message, and the 500 that GET /api/scenarios/presets/<name> answers with it, are
pinned in tests/unit/test_web_scenarios.py.
"""

from pathlib import Path

import pytest

from solar_challenge.web.database import Database
from solar_challenge.web.presets import SavedPresetUnreadable, saved_fleet_preset_named
from solar_challenge.web.schema import open_database
from tests._config_preset_rows import insert_saved_fleet_preset
from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE


@pytest.fixture
def database(tmp_path: Path) -> Database:
    """A new dashboard database, which open_database created."""
    return open_database(tmp_path / "presets.db")


@pytest.mark.parametrize(
    ("config_json", "refusal_of_json_loads"),
    [
        pytest.param("{not json", ValueError, id="not-json"),
        pytest.param(JSON_NESTED_TOO_DEEPLY_TO_DECODE, RecursionError, id="nested-too-deeply"),
    ],
)
def test_a_saved_fleet_preset_whose_config_json_loads_refuses_is_unreadable_caused_by_that_refusal(
    database: Database, config_json: str, refusal_of_json_loads: type[Exception]
) -> None:
    insert_saved_fleet_preset(database, "Broken", config_json)

    with pytest.raises(SavedPresetUnreadable) as unreadable:
        saved_fleet_preset_named(database, "Broken")

    assert isinstance(unreadable.value.__cause__, refusal_of_json_loads)


def test_a_saved_fleet_preset_whose_config_is_json_but_not_an_object_is_unreadable_with_no_cause(
    database: Database,
) -> None:
    insert_saved_fleet_preset(database, "Not an object", "[1]")

    with pytest.raises(SavedPresetUnreadable) as unreadable:
        saved_fleet_preset_named(database, "Not an object")

    assert unreadable.value.__cause__ is None
