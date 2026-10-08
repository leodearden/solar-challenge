# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write a saved home preset's row straight into a dashboard database's config_presets table.

The row skips the dashboard's own save and the names and configs it refuses, so a test can
give the database a saved home preset no save writes, such as one under a built-in home
preset's name.

Usage::

    from tests._config_preset_rows import insert_saved_home_preset

    preset_id = insert_saved_home_preset(app.config["DATABASE"], "Small Urban", json.dumps({"pv_kw": 9.5}))
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
