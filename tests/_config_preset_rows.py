# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rows of a dashboard database's config_presets table, written and read straight, past the dashboard's own saves.

insert_saved_home_preset writes a saved home preset no save writes, such as one under a
built-in home preset's name or one whose config is not JSON. saved_preset_names reads the
name of every saved preset, so a test can show what a save wrote.

Usage::

    from tests._config_preset_rows import insert_saved_home_preset, saved_preset_names

    preset_id = insert_saved_home_preset(app.config["DATABASE"], "Small Urban", json.dumps({"pv_kw": 9.5}))
    assert saved_preset_names(app.config["DATABASE"]) == ["Small Urban"]
"""

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def insert_saved_home_preset(db_path: str | Path, name: str, config_json: str) -> str:
    """Insert the saved home preset *name*, whose config is the text *config_json*, into the database at *db_path*. Returns its id."""
    preset_id = str(uuid.uuid4())
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, 'home', ?, ?)",
                (preset_id, name, config_json, datetime.now(timezone.utc).isoformat()),
            )
    return preset_id


def saved_preset_names(db_path: str | Path) -> list[str]:
    """The name of each saved preset, home and fleet alike, in the database at *db_path*, in name order."""
    with closing(sqlite3.connect(db_path)) as conn:
        return [name for (name,) in conn.execute("SELECT name FROM config_presets ORDER BY name")]
