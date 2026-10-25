-- The schema of a dashboard store at schema version 2: the statement creating each of its
-- tables and indexes, as a new store's sqlite_master holds it, the tables first. Version 2's
-- step changes no table, only the stored runs' documents, so its schema is version 1's. A
-- migration step N that changes a table's schema commits the schema of version N beside it as
-- schema_vN.sql (web/schema.py), and tests/unit/test_web_schema.py compares a new store's
-- schema with the one committed for schema.SCHEMA_VERSION.

CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role TEXT CHECK(role IN ('user', 'assistant')),
    content TEXT,
    created_at TEXT,
    metadata_json TEXT
);

CREATE TABLE config_presets (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    type TEXT CHECK(type IN ('home', 'fleet')),
    config_json TEXT,
    created_at TEXT
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT CHECK(type IN ('home', 'fleet')),
    config_json TEXT,
    summary_json TEXT,
    status TEXT DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed')),
    error_message TEXT,
    created_at TEXT,
    completed_at TEXT,
    duration_seconds REAL,
    n_homes INTEGER DEFAULT 1,
    notes TEXT
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);

CREATE INDEX idx_runs_created_at ON runs(created_at DESC);

CREATE INDEX idx_runs_type ON runs(type);
