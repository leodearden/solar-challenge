# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct writes of the rows of a dashboard Database's chat_messages table that no save writes.

save_chat_message stores a message's metadata as the JSON of a dict, or NULL. insert_chat_message
stores the metadata text it is given, so a test can hold a message whose metadata is not JSON, is
nested too deeply to decode, or is JSON but not an object.

Usage::

    from tests._chat_message_rows import insert_chat_message
    from tests._web_app import database_of

    message_id = insert_chat_message(database_of(app), "session-1", "assistant", "Hi there!", "{not json")
"""

from datetime import datetime, timezone

from solar_challenge.web.chat_messages import ChatRole
from solar_challenge.web.database import Database


def insert_chat_message(
    database: Database, session_id: str, role: ChatRole, content: str, metadata_json: str | None
) -> int:
    """Insert the *role* message *content* of the session *session_id*, whose metadata is the text *metadata_json*, NULL for None, into *database*. Returns its id."""
    with database.transaction() as conn:
        message_id = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, datetime.now(timezone.utc).isoformat(), metadata_json),
        ).lastrowid
    assert message_id is not None, "sqlite3 reported no rowid for the chat_messages row it inserted"
    return message_id
