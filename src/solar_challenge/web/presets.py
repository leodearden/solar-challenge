# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saving to config_presets, which holds one saved preset per name, a home or a fleet preset.

Home and fleet presets share that one namespace, as the table's UNIQUE name declares, so a
save under a name a preset of the other type holds is refused.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from solar_challenge.web.database import get_db

PresetType = Literal["home", "fleet"]


class PresetNameTaken(ValueError):
    """A save under a name a saved preset of the other type holds; the message names the name and that type."""

    def __init__(self, name: str, holder_type: str) -> None:
        super().__init__(f"A saved {holder_type} preset is already named {name!r}")


def save_config_preset(
    db_path: str | Path, name: str, preset_type: PresetType, config: Mapping[str, Any]
) -> str:
    """Save *config* as the *preset_type* preset *name* and return the preset's id.

    A preset of that type already named *name* keeps its id and takes *config*. The lookup
    of *name* and the write share one write transaction, so saves of one name take effect
    one after the other.

    Raises:
        PresetNameTaken: Writing nothing, when a saved preset of the other type holds *name*.
    """
    config_json = json.dumps(config)
    saved_at = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        holder = conn.execute("SELECT id, type FROM config_presets WHERE name = ?", (name,)).fetchone()
        if holder is None:
            preset_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (preset_id, name, preset_type, config_json, saved_at),
            )
            return preset_id
        if holder["type"] != preset_type:
            raise PresetNameTaken(name, holder["type"])
        conn.execute(
            "UPDATE config_presets SET config_json = ?, created_at = ? WHERE id = ?",
            (config_json, saved_at, holder["id"]),
        )
        return str(holder["id"])
