"""SQLite database module for Solar Challenge web dashboard persistence.

Provides schema initialization and connection management for storing
simulation runs, background jobs, chat messages, and configuration presets.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def init_db(db_path: str | Path) -> None:
    """Initialize the SQLite database with the required schema.

    Creates tables for runs, jobs, chat_messages, and config_presets.
    Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.

    Args:
        db_path: Path to the SQLite database file. Parent directory
            will be created if it doesn't exist.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row  # Enable dict-like row access

    cursor = conn.cursor()

    # Runs table - stores metadata for home/fleet/sweep simulations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT CHECK(type IN ('home', 'fleet', 'sweep')),
            config_json TEXT,
            summary_json TEXT,
            status TEXT DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed')),
            error_message TEXT,
            created_at TEXT,
            completed_at TEXT,
            duration_seconds REAL,
            n_homes INTEGER DEFAULT 1,
            notes TEXT
        )
    """)

    # Jobs table - tracks background processing jobs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'completed', 'failed')),
            progress_pct REAL DEFAULT 0,
            current_step TEXT,
            message TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            error_traceback TEXT
        )
    """)

    # Chat messages table - stores AI assistant conversation history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT CHECK(role IN ('user', 'assistant')),
            content TEXT,
            created_at TEXT,
            metadata_json TEXT
        )
    """)

    # Config presets table - stores saved configuration templates
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config_presets (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            type TEXT CHECK(type IN ('home', 'fleet')),
            config_json TEXT,
            created_at TEXT
        )
    """)

    # Create indexes for common queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_created_at
        ON runs(created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_type
        ON runs(type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_run_id
        ON jobs(run_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
        ON chat_messages(session_id)
    """)

    conn.commit()
    conn.close()


@contextmanager
def get_db(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection as a context manager.

    Provides a connection with row_factory set to sqlite3.Row for
    dict-like access. Automatically commits on success and closes
    the connection when the context exits.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        sqlite3.Connection: Database connection with Row factory enabled.

    Example:
        with get_db("/path/to/db.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs")
            rows = cursor.fetchall()
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
