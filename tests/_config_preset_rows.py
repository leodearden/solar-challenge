# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct access to the rows of a dashboard Database's config_presets table.

insert_saved_home_preset and insert_saved_fleet_preset write a saved home or fleet preset no
save writes, such as a home preset under a built-in home preset's name, or a preset whose config
is not JSON or is NULL. saved_preset_names reads the name of every saved preset, so a test can
show what a save wrote.

Usage::

    from tests._config_preset_rows import insert_saved_home_preset, saved_preset_names
    from tests._web_app import database_of

    preset_id = insert_saved_home_preset(database_of(app), "Small Urban", json.dumps({"pv_kw": 9.5}))
    assert saved_preset_names(database_of(app)) == ["Small Urban"]
"""

import uuid
from datetime import datetime, timezone

from solar_challenge.web.database import Database, PresetType


def insert_saved_home_preset(database: Database, name: str, config_json: str | None) -> str:
    """Insert the saved home preset *name*, whose config is the text *config_json*, NULL for None, into *database*. Returns its id."""
    return _insert_saved_preset(database, name, "home", config_json)


def insert_saved_fleet_preset(database: Database, name: str, config_json: str | None) -> str:
    """Insert the saved fleet preset *name*, whose config is the text *config_json*, NULL for None, into *database*. Returns its id."""
    return _insert_saved_preset(database, name, "fleet", config_json)


def _insert_saved_preset(database: Database, name: str, preset_type: PresetType, config_json: str | None) -> str:
    """Insert the saved *preset_type* preset *name*, whose config is the text *config_json*, NULL for None, into *database*. Returns its id."""
    preset_id = str(uuid.uuid4())
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (preset_id, name, preset_type, config_json, datetime.now(timezone.utc).isoformat()),
        )
    return preset_id


def saved_preset_names(database: Database) -> list[str]:
    """The name of each saved preset, home and fleet alike, in *database*, in name order."""
    with database.transaction() as conn:
        return [row["name"] for row in conn.execute("SELECT name FROM config_presets ORDER BY name")]
