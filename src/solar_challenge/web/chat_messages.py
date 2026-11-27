# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner of the chat_messages table, in which the assistant's conversations persist, each message under its browser session.

CHAT_MESSAGES_TABLE is the table a new store creates, and migrate_chat_messages_table_v1 is
schema version 1's part for it, which that version's step in web/schema.py runs.
save_chat_message stores one message, and get_chat_history reads a session's messages back in
the order they were saved.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal, get_args

from solar_challenge.web.database import Database, TableSchema, check_one_of, rebuild_table
from solar_challenge.web.stored_json import JsonObjectRefused, decoded_json_object

logger = logging.getLogger(__name__)

_UNREADABLE_METADATA_WARNING = "Chat message %d's metadata %s, so the message is read without it"

ChatRole = Literal["user", "assistant"]  # who wrote a chat message, held by the chat_messages table's role column
CHAT_ROLES: tuple[ChatRole, ...] = get_args(ChatRole)

CHAT_MESSAGES_TABLE = TableSchema(
    name="chat_messages",
    columns=(
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("session_id", "TEXT"),
        ("role", f"TEXT {check_one_of('role', CHAT_ROLES)}"),
        ("content", "TEXT"),
        ("created_at", "TEXT"),
        ("metadata_json", "TEXT"),
    ),
    indexes=("CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id)",),
)
"""The chat_messages table this code reads and writes, which a new store creates: the assistant's conversations, each message under its browser session."""

_CHAT_MESSAGES_TABLE_V1 = TableSchema(
    name="chat_messages",
    columns=(
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("session_id", "TEXT"),
        ("role", "TEXT CHECK(role IN ('user', 'assistant'))"),
        ("content", "TEXT"),
        ("created_at", "TEXT"),
        ("metadata_json", "TEXT"),
    ),
    indexes=("CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id)",),
)
"""The chat_messages table at schema version 1, as tests/fixtures/databases/schema_v1.sql holds it, whatever CHAT_MESSAGES_TABLE states since."""


def migrate_chat_messages_table_v1(conn: sqlite3.Connection) -> None:
    """Schema version 1's part for the chat_messages table, run on *conn* inside its migration step's transaction: the table rebuilt to its schema at version 1."""
    rebuild_table(conn, _CHAT_MESSAGES_TABLE_V1)


def save_chat_message(
    database: Database,
    session_id: str,
    role: ChatRole,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert a chat message row and return the new row id.

    Args:
        database: The Database holding the chat_messages table.
        session_id: Browser-session identifier scoping the conversation.
        role: Who wrote the message, one of CHAT_ROLES.
        content: Message text.
        metadata: Optional dict serialised as JSON (e.g. usage/cache stats).

    Returns:
        The auto-incremented integer id of the newly inserted row.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    metadata_json: str | None = json.dumps(metadata) if metadata is not None else None
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, created_at, metadata_json),
        )
        return int(cursor.lastrowid or 0)


def get_chat_history(
    database: Database,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return all chat messages for a session in insertion order.

    A message whose metadata is not JSON, is nested too deeply to decode, or is JSON but not an
    object is read with metadata ``None``, and a logged warning names its id and the fault.

    Args:
        database: The Database holding the chat_messages table.
        session_id: Browser-session identifier to filter by.

    Returns:
        List of dicts with keys: ``role``, ``content``, ``created_at``,
        ``metadata`` (dict or ``None``).
    """
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, role, content, created_at, metadata_json
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "metadata": _message_metadata(row["id"], row["metadata_json"]),
            }
        )
    return result


def _message_metadata(message_id: int, metadata_json: str | None) -> dict[str, Any] | None:
    """The metadata of the chat message *message_id*, stored as *metadata_json*: the JSON object that text holds, or None for NULL or, with a logged warning, for text that cannot be read as a JSON object."""
    if metadata_json is None:
        return None
    try:
        return decoded_json_object(metadata_json)
    except JsonObjectRefused as unreadable:
        logger.warning(_UNREADABLE_METADATA_WARNING, message_id, unreadable.reason)
        return None
