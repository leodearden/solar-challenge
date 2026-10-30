# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's presets by name: the built-in home presets, and the saved presets of config_presets.

config_presets holds one saved preset per name, a home or a fleet preset, as the table's UNIQUE
name declares, so a save under a name a saved preset of the other type holds is refused. A
built-in home preset's name names that built-in preset only, so a home save under it is refused
too, and the home presets list each name once. Every read is of one type: the home presets hold
no saved fleet preset, and the saved fleet presets, which the scenario builder lists beside the
built-in scenario files, hold no home preset.
"""

import json
import logging
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal, get_args

from solar_challenge.web.database import Database, TableSchema, check_one_of, rebuild_table
from solar_challenge.web.stored_json import UndecodableJson, decoded_json

logger = logging.getLogger(__name__)

PresetType = Literal["home", "fleet"]  # the type of a saved preset, held by the config_presets table's type column
PRESET_TYPES: tuple[PresetType, ...] = get_args(PresetType)

PresetSource = Literal["builtin", "saved"]

CONFIG_PRESETS_TABLE = TableSchema(
    name="config_presets",
    columns=(
        ("id", "TEXT PRIMARY KEY"),
        ("name", "TEXT UNIQUE"),
        ("type", f"TEXT {check_one_of('type', PRESET_TYPES)}"),
        ("config_json", "TEXT"),
        ("created_at", "TEXT"),
    ),
)
"""The config_presets table this code reads and writes, which a new store creates: the saved presets, one per name, each of a PresetType."""

_CONFIG_PRESETS_TABLE_V1 = TableSchema(
    name="config_presets",
    columns=(
        ("id", "TEXT PRIMARY KEY"),
        ("name", "TEXT UNIQUE"),
        ("type", "TEXT CHECK(type IN ('home', 'fleet'))"),
        ("config_json", "TEXT"),
        ("created_at", "TEXT"),
    ),
)
"""The config_presets table at schema version 1, as tests/fixtures/databases/schema_v1.sql holds it, whatever CONFIG_PRESETS_TABLE states since."""


def migrate_config_presets_table_v1(conn: sqlite3.Connection) -> None:
    """Schema version 1's part for the config_presets table, run on *conn* inside its migration step's transaction: the table rebuilt to its schema at version 1."""
    rebuild_table(conn, _CONFIG_PRESETS_TABLE_V1)


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


class SavedPresetUnreadable(Exception):
    """A saved preset that cannot be read; the message names the preset and the fault.

    It is not a ValueError: no request causes it, so it is a server fault, never a refused request.
    """

    def __init__(self, name: str, fault: str) -> None:
        super().__init__(f"Saved preset {name!r} could not be read: {fault}")


def save_config_preset(
    database: Database, name: str, preset_type: PresetType, config: Mapping[str, Any]
) -> str:
    """Save *config* as the *preset_type* preset *name* in *database* and return the preset's id.

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
    with database.transaction() as conn:
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


def home_presets(database: Database) -> list[dict[str, Any]]:
    """The home presets, each name once: the built-in ones, then the ones saved in *database* by name.

    Each preset is its config with its name and its ``source``, a PresetSource; a saved one
    also has its ``created_at``. A saved home preset under a built-in preset's name is left
    out, so that name names the built-in preset, and so is one whose config is not a JSON
    object, with a logged warning naming it. When the database cannot be read, the fault is
    logged and the built-in presets are listed alone.
    """
    builtin = _builtin_home_presets()
    try:
        with database.transaction() as conn:
            rows = conn.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE type = 'home' ORDER BY name"
            ).fetchall()
    except sqlite3.Error:
        logger.warning("Failed to load saved presets", exc_info=True)
        return builtin
    saved = (_saved_home_preset(row) for row in rows if row["name"] not in _BUILTIN_HOME_PRESET_NAMES)
    return builtin + [preset for preset in saved if preset is not None]


def _builtin_home_presets() -> list[dict[str, Any]]:
    """The built-in home presets, each with the ``source`` 'builtin'."""
    return [{**preset, "source": "builtin"} for preset in _BUILTIN_HOME_PRESETS]


def _saved_home_preset(row: sqlite3.Row) -> dict[str, Any] | None:
    """The preset a saved home preset's row holds; None, with a logged warning naming it, when its config cannot be read."""
    try:
        config = _saved_preset_config(row)
    except SavedPresetUnreadable as unreadable:
        logger.warning("%s, so it is not listed", unreadable)
        return None
    return {**config, "name": row["name"], "created_at": row["created_at"], "source": "saved"}


def _saved_preset_row(database: Database, name: str, preset_type: PresetType) -> sqlite3.Row | None:
    """The config_presets row of the saved *preset_type* preset *name*, or None when there is none.

    Raises:
        SavedPresetUnreadable: When *database* cannot be read.
    """
    try:
        with database.transaction() as conn:
            row: sqlite3.Row | None = conn.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE name = ? AND type = ?",
                (name, preset_type),
            ).fetchone()
    except sqlite3.Error as exc:
        raise SavedPresetUnreadable(name, str(exc)) from exc
    return row


def _saved_preset_config(row: sqlite3.Row) -> dict[str, Any]:
    """The config a saved preset's row holds, a JSON object; a config stored as NULL or empty text reads as {}.

    Raises:
        SavedPresetUnreadable: When decoded_json refuses the config, as not JSON or nested too
            deeply to decode, or when the config is JSON but not an object.
    """
    try:
        config = decoded_json(row["config_json"]) if row["config_json"] else {}
    except UndecodableJson as undecodable:
        raise SavedPresetUnreadable(row["name"], f"its config {undecodable.reason}") from undecodable.refusal
    if not isinstance(config, dict):
        raise SavedPresetUnreadable(row["name"], "its config is not a JSON object")
    return config


def home_preset_named(database: Database, name: str) -> dict[str, Any] | None:
    """The home preset named *name*, as home_presets lists it when *database* can be read, or None when there is none.

    A built-in preset's name is answered without reading *database*.

    Raises:
        SavedPresetUnreadable: When *name* is not a built-in preset's and *database* cannot be read.
    """
    if name in _BUILTIN_HOME_PRESET_NAMES:
        return next(preset for preset in _builtin_home_presets() if preset["name"] == name)
    row = _saved_preset_row(database, name, "home")
    return None if row is None else _saved_home_preset(row)


def saved_fleet_presets(database: Database) -> list[dict[str, Any]]:
    """The saved fleet presets by name, each its name, its ``source`` and its ``created_at``.

    When the database cannot be read, the fault is logged and none are listed.
    """
    try:
        with database.transaction() as conn:
            rows = conn.execute(
                "SELECT name, created_at FROM config_presets WHERE type = 'fleet' ORDER BY name"
            ).fetchall()
    except sqlite3.Error:
        logger.warning("Failed to load saved fleet presets", exc_info=True)
        return []
    return [_listed_saved_fleet_preset(row) for row in rows]


def saved_fleet_preset_named(database: Database, name: str) -> dict[str, Any] | None:
    """The saved fleet preset *name*, as saved_fleet_presets lists it, with its ``config``.

    None when no saved fleet preset is named *name*. A config stored as NULL or empty text
    reads as {}.

    Raises:
        SavedPresetUnreadable: When the database cannot be read, or the preset's config is not
            JSON, is nested too deeply to decode, or is JSON but not an object.
    """
    row = _saved_preset_row(database, name, "fleet")
    return None if row is None else {**_listed_saved_fleet_preset(row), "config": _saved_preset_config(row)}


def _listed_saved_fleet_preset(row: sqlite3.Row) -> dict[str, Any]:
    """The entry saved_fleet_presets lists for a saved fleet preset's row."""
    return {"name": row["name"], "source": "saved", "created_at": row["created_at"]}
