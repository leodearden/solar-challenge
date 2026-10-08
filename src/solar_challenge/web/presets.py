# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's presets by name: the built-in home presets, and the saved presets of config_presets.

config_presets holds one saved preset per name, a home or a fleet preset, as the table's UNIQUE
name declares, so a save under a name a saved preset of the other type holds is refused. A
built-in home preset's name names that built-in preset only, so a home save under it is refused
too, and the home presets list each name once.
"""

import json
import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from solar_challenge.web.database import get_db

logger = logging.getLogger(__name__)

PresetType = Literal["home", "fleet"]
PresetSource = Literal["builtin", "saved"]

_BUILTIN_HOME_PRESETS: tuple[Mapping[str, Any], ...] = (
    {"name": "Small Urban", "pv_kw": 3.0, "battery_kwh": 0, "consumption_kwh": 2900},
    {"name": "Medium Suburban", "pv_kw": 4.0, "battery_kwh": 5.0, "consumption_kwh": 3500},
    {"name": "Large with Battery", "pv_kw": 6.0, "battery_kwh": 10.0, "consumption_kwh": 4500},
)
_BUILTIN_HOME_PRESET_NAMES: frozenset[str] = frozenset(preset["name"] for preset in _BUILTIN_HOME_PRESETS)


class PresetNameTaken(ValueError):
    """A save under a name another preset holds; the message names the name and the holding preset's source and type."""

    def __init__(self, name: str, holder_source: PresetSource, holder_type: PresetType) -> None:
        super().__init__(
            f"A {'built-in' if holder_source == 'builtin' else 'saved'} {holder_type} preset is already named {name!r}"
        )


def save_config_preset(
    db_path: str | Path, name: str, preset_type: PresetType, config: Mapping[str, Any]
) -> str:
    """Save *config* as the *preset_type* preset *name* and return the preset's id.

    A preset of that type already named *name* keeps its id and takes *config*. The lookup
    of *name* and the write share one write transaction, so saves of one name take effect
    one after the other.

    Raises:
        PresetNameTaken: Writing nothing, when a saved preset of the other type holds *name*,
            or when a home save is named like a built-in home preset.
    """
    if preset_type == "home" and name in _BUILTIN_HOME_PRESET_NAMES:
        raise PresetNameTaken(name, "builtin", "home")
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
            raise PresetNameTaken(name, "saved", holder["type"])
        conn.execute(
            "UPDATE config_presets SET config_json = ?, created_at = ? WHERE id = ?",
            (config_json, saved_at, holder["id"]),
        )
        return str(holder["id"])


def home_presets(db_path: str | Path) -> list[dict[str, Any]]:
    """The home presets, each name once: the built-in ones, then the saved ones by name.

    Each preset is its config with its name and its ``source``, a PresetSource; a saved one
    also has its ``created_at``. A saved home preset under a built-in preset's name is left
    out, so that name names the built-in preset. When the saved presets cannot be read, the
    fault is logged and the built-in presets are listed alone.
    """
    builtin = [{**preset, "source": "builtin"} for preset in _BUILTIN_HOME_PRESETS]
    try:
        with get_db(db_path) as conn:
            rows = conn.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE type = 'home' ORDER BY name"
            ).fetchall()
        saved = [
            {
                **(json.loads(row["config_json"]) if row["config_json"] else {}),
                "name": row["name"],
                "created_at": row["created_at"],
                "source": "saved",
            }
            for row in rows
            if row["name"] not in _BUILTIN_HOME_PRESET_NAMES
        ]
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load saved presets", exc_info=True)
        return builtin
    return builtin + saved


def home_preset_named(db_path: str | Path, name: str) -> dict[str, Any] | None:
    """The preset home_presets lists under *name*, or None when it lists none."""
    return next((preset for preset in home_presets(db_path) if preset["name"] == name), None)
