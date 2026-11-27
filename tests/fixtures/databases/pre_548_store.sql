-- The dashboard store as solar-challenge left it before task 548: the schema init_db created
-- then, copied verbatim from `git show 6e6865d^:src/solar_challenge/web/database.py`, and a
-- few rows. Its runs table admits 'sweep' runs and nameless runs, it keeps the retired jobs
-- table, whose run_id references runs, and it records no schema version (user_version 0).
-- tests/_dashboard_databases.py::write_pre_548_database writes it.

PRAGMA journal_mode=WAL;

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
        );

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
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT CHECK(role IN ('user', 'assistant')),
            content TEXT,
            created_at TEXT,
            metadata_json TEXT
        );

        CREATE TABLE IF NOT EXISTS config_presets (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            type TEXT CHECK(type IN ('home', 'fleet')),
            config_json TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_runs_created_at
        ON runs(created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_runs_type
        ON runs(type);

        CREATE INDEX IF NOT EXISTS idx_jobs_run_id
        ON jobs(run_id);

        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
        ON chat_messages(session_id);

INSERT INTO runs (id, name, type, config_json, summary_json, status, error_message, created_at, completed_at, duration_seconds, n_homes, notes)
VALUES
    ('legacy-named-home', 'South Roof', 'home',
     '{"name": "South Roof Home", "pv_config": {"capacity_kw": 4.0}, "load_config": {}}',
     NULL, 'completed', NULL, '2025-06-01T09:00:00+00:00', '2025-06-01T09:00:12+00:00', 12.0, 1, 'Checked'),
    ('legacy-nameless-home', NULL, 'home',
     '{"name": "North Roof", "pv_config": {"capacity_kw": 3.0}, "load_config": {}}',
     NULL, 'completed', NULL, '2025-06-02T09:00:00+00:00', '2025-06-02T09:00:10+00:00', 10.0, 1, NULL),
    ('legacy-blank-home', '  ', 'home',
     '{"pv_config": {"capacity_kw": 2.5}, "load_config": {}}',
     NULL, 'completed', NULL, '2025-06-03T09:00:00+00:00', '2025-06-03T09:00:09+00:00', 9.0, 1, NULL),
    ('legacy-nameless-fleet', NULL, 'fleet', NULL,
     NULL, 'failed', 'Simulation failed', '2025-06-04T09:00:00+00:00', '2025-06-04T09:01:00+00:00', NULL, 3, NULL);

INSERT INTO jobs (id, run_id, status, progress_pct, current_step, message, created_at, started_at, completed_at, error_traceback)
VALUES ('legacy-job', 'legacy-named-home', 'completed', 100, NULL, 'Done',
        '2025-06-01T09:00:00+00:00', '2025-06-01T09:00:01+00:00', '2025-06-01T09:00:12+00:00', NULL);

INSERT INTO chat_messages (session_id, role, content, created_at, metadata_json)
VALUES ('legacy-session', 'user', 'How much did South Roof generate?', '2025-06-01T09:05:00+00:00', NULL);

INSERT INTO config_presets (id, name, type, config_json, created_at)
VALUES ('legacy-preset', 'Legacy Preset', 'home', '{"pv_kw": 3.5, "battery_kwh": 0, "consumption_kwh": 3000}',
        '2025-06-01T08:00:00+00:00');
