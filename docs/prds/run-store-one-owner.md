# PRD — Run store with one owner: connection, schema version, stored-run format, run type (S19)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S19**, wave 1, size L,
  risk high, no upstream streams. Findings record: `plans/review-all-solar_challenge-20261013.json`
  (`x_finding_run = review-all-solar_challenge-20261013`).
- **Status:** authored 2026-10-14, not yet filed. Decompose waits for the lead to hand over the ids
  of the out-of-batch tasks this batch depends on or supersedes (§6).
- **Code anchors:** verified against main `1251be0` (2026-10-14). Main moves fast: this PRD cites
  symbols, not line numbers, and implementers should re-locate them at implementation time. The
  findings record's anchors are at `7dfea36`; `git diff 7dfea36..1251be0` touches `api.py`,
  `assistant.py`, `jobs.py` and `shared.py` only cosmetically for this stream (re-read 2026-10-14).
- **Binding rulings:** **D19** (`init_db` writes `PRAGMA user_version`; on a mismatch the app
  refuses to start, naming both versions and the file; `solar-challenge web migrate` applies the
  ordered migrations explicitly) and **D20** (one `/results/<run_id>` route chooses the page from
  the record's run type; `/results/home/…` and `/results/fleet/…` redirect to it; the
  run-type-to-behaviour table lives on `storage.RunRecord`). Invariants **4, 6 and 7** (D27) are
  tests this stream owns.
- **Session rulings (2026-10-14, Leo):** the dead `'sweep'` run type and `sweep_id` are **dropped**
  (§5 D-S19-3). Deleting a run **wins and cancels its job** (§5 D-S19-6).
- **Owner seams (G4):** connection policy (`database.Database.connect`); the stored-run format
  version and the store's schema version (`stored_runs` / `schema`, readers every loader); the
  run-type → behaviour table (`storage.RunRecord.kind`, readers api, routes, templates, assistant).
- **Approach:** **B + H**. The PRD sets a contract (§4) and a two-way boundary-test sketch (§10)
  that the integration-gate leaf μ runs. This is the dashboard's persistence seam, which every web
  module and five later streams (S2, S10, S12, S25, S28 through S29's bump) depend on, and it moves user
  data on disk.

---

## 1. Goal

After this stream, a dashboard user can see these behaviours:

1. **A database written by an older dashboard is never silently half-upgraded.** `solar-challenge
   web start` on it exits non-zero with `…solar-challenge.db is at schema version 0; this
   solar-challenge needs 2. Run \`solar-challenge web migrate\``. `solar-challenge web migrate`
   brings the database and every stored run to the current versions. It prints what it changed,
   including any stored key it dropped and any run it could not migrate. The documented
   "delete the database file" policy goes.
2. **A stored run either loads exactly or is refused by name.** Results pages and exports never
   answer a 500 for a run that was saved before a field was added or that has been hand-edited. They
   answer a flash (pages) or a 409 (JSON) naming the run id, the document and the field.
3. **Run History shows every run correctly.** Fleet runs list their self-consumption ratio instead
   of `null`. Every row's link goes to `/results/<run_id>`, which renders the page for the run's
   type. The old `/results/home/<id>` and `/results/fleet/<id>` links redirect, so
   `/results/home/<fleet id>` is no longer a 500.
4. **Deleting a run deletes it, and stops its job.** The run vanishes from History at once. A queued
   job never runs. A running job stops at its next checkpoint and saves nothing, where today its
   final save brings the run back.
5. **A second dashboard on the same data directory refuses to start.** It names the process that
   holds the store, and it never fails the live server's in-flight runs.
6. **History's type filter offers Home and Fleet only.** The sweep page no longer shows a "Sweep ID"
   that identifies nothing, and the server refuses more than 50 sweep steps, as the page already does.

Structurally, `RunStorage` is the one module that issues SQL against `runs`. `JobManager` is built
with the app's `RunStorage` and writes through it. Nothing below `create_app` reads
`current_app.config['DATABASE'|'DATA_DIR']`. Every SQLite connection comes from one policy. A run's
default name, its summary decoding and its listing each have one implementation.

## 2. Background — what exists at `1251be0`

- `web/database.py` holds the `RunType`/`RunStatus`/`JobStatus`/`ChatRole`/`PresetType` Literals,
  `init_db` (`CREATE TABLE IF NOT EXISTS` for `runs`, `jobs`, `chat_messages`, `config_presets`, no
  version), `get_db(db_path)` (Row factory, `foreign_keys=ON`) and the chat-message store. Its
  docstring's migration policy is "delete the database file". `init_db`'s own connection sets WAL
  but not `foreign_keys`. **Re-measured (D28, fk-1070454e4c6e and fk-cca5fd81afda):**
  `user_version` has 0 hits in `src/`. There are 3 `sqlite3.connect` sites (`init_db`, `get_db`,
  `JobManager._run_job`) and 18 `get_db(` call sites in 7 files.
- `web/storage.py`: `RunRecord` (frozen, one field per `runs` column; `decoded_config()` and
  `decoded_summary()` return `Any` and `{}` on failure), `_run_row_upsert` (derived from
  `fields(RunRecord)`, keeping `_COLUMNS_A_RESAVE_KEEPS`), and `RunStorage(db_path, data_dir)` with
  `save_home_run`/`save_fleet_run`, `load_home_run`/`load_fleet_run`, `run_record`,
  `latest_run_named`, `update_run_labels`, `list_runs` (dicts; used only by `routes.index`) and
  `delete_run`. `_deserialize_dataclass` skips every key the class lacks and lets a dataclass
  constructor's `TypeError` escape. **Re-measured (fk-273b8b09c91a):** the skip and the silent
  default fill still hold. The loaders have 4 callers with 2 exception sets: `routes.home_results`,
  `routes.fleet_results` and `api.history_export_csv` catch only `FileNotFoundError`, and
  `api.history_export_yaml` catches a five-type tuple.
- `web/jobs.py`: `JobManager()` holds no store. `submit_home_job`/`submit_fleet_job` take
  `db_path`/`data_dir`, which nine methods thread through. The positional 12-column `INSERT INTO
  runs` lives in `_record_new_job`. A `jobs` table is written on every transition and per progress
  tick, and no production code reads it. `_run_job` opens its own connection before its `try`
  (task 646). Each runner builds a fresh `RunStorage`. `recover_stale_jobs(db_path)` fails every
  `running`/`queued` row unscoped.
- `web/app.py::create_app`: `init_db` → `RunStorage` → `JobManager()` → `recover_stale_jobs`. There
  is no lock (fk-e29393df0cd4), and the single-process rule is a docstring note. `cli/web.py::start`
  calls `create_app()` before `flask_app.run` binds the port.
- Readers that bypass `RunStorage`: `api.history_list_runs` (its own WHERE/ORDER/LIMIT, a
  `json.loads` of `summary_json`), `assistant.list_recent_runs` (its own SELECT),
  `routes._get_aggregate_stats` (a function-local `get_db` import, `status = 'completed'` literal,
  `json_extract('$.total_generation_kwh')`), `api.get_job_results` and `assistant.get_run_results`
  (raw `json.loads`). `api.scenarios_list_presets`/`scenarios_get_preset` query `config_presets`
  raw, and the get does not filter `type = 'fleet'`. There are 17 `current_app.config[...]` reads in
  `api.py` and `assistant.py`.
- The run type selects behaviour at 9 sites in 6 files with 3 different fallbacks (fk-81e62b2640a7).
  The `'sweep'` type is never written. **Re-measured (fk-2ff305a1dbb2):** the default-name literals
  sit on 12 lines in `web/*.py` (jobs 4, storage 2, routes 3, api 1, assistant 1,
  simulation_params 1), plus 6 in templates and JS.
- Core `home.simulate_home` takes no progress or cancel hook. A home job's checkpoints are
  therefore the runner's own phase boundaries, and a fleet job's are its per-home loop
  (`_run_fleet_simulation`).

## 3. Sketch of approach

### 3.1 The persistence stratum after S19 (bottom → top)

| Module | Owns | Imports (web) |
|---|---|---|
| `web/database.py` | `Database` (the connection policy), `TableSchema` + `rebuild_table` | none |
| `web/field_tree.py` | the field-tree codec: `field_tree`, `read_field_tree`, `without_unknown_keys`, `FieldTreeRefused`, `UnknownKey` | none |
| `web/stored_json.py` | `decoded_json`, the value of a store's JSON text, and `UndecodableJson`, its one refusal of text `json.loads` cannot decode: not JSON, or nested too deeply | none |
| `web/stored_runs.py` (new) | the stored-run **format**: `RunType`, its documents' field trees, read and written through `field_tree`, `StoredHomeRun`/`StoredFleetRun`, `RUN_KINDS`, `RUN_DOCUMENT_STEPS` + `RUN_FORMAT_VERSION`, `StoredRunUnreadable` | none after ι but `field_tree` and `stored_json`, below it (no SQL, no Flask); between ε and ι it imports `RunType` from `database`, where the runs DDL still lives |
| `web/storage.py` | the `runs` table: `RunStatus`, `RunRecord` (+ `.kind`), `RUNS_TABLE` derived from `RunRecord`, `RunStorage` (all `runs` SQL), `RunHeadline`/`run_headline`, `RunQuery`/`RunPage`/`RunTotals`, the runs-table migration functions | database, stored_runs |
| `web/presets.py` | the `config_presets` table, `PresetType`, home presets and saved fleet (scenario) presets | database, stored_json |
| `web/chat_messages.py` | the `chat_messages` table and its store: `ChatRole`, `CHAT_MESSAGES_TABLE` and its migration functions, `save_chat_message`/`get_chat_history` | database, stored_json |
| `web/schema.py` (new) | `SCHEMA_VERSION` (derived), the ordered `MIGRATIONS`, `open_database`, `migrate_store`, `SchemaVersionMismatch`, `MigrationReport` | database, stored_runs, storage, presets, chat_messages |
| `web/store_lock.py` (new) | `acquire_store_lock`, `StoreLock`, `StoreLocked` | none |
| `web/jobs.py` | `JobStatus`, `JobManager(storage, …)` (no SQL), cancellation | storage |
| `web/app.py` | the composition root: lock → `open_database` → `RunStorage` → `JobManager` → `fail_interrupted_runs` | all of the above |

Why `schema.py` exists: the `runs` DDL is derived from `RunRecord` (storage), and `storage` needs
`Database` (database). If the version assembly lived in `database.py`, it would import `storage`,
which imports `database`: an import cycle. Each table owner therefore states its own DDL and its
own migration functions, and `schema.py` states only the order, the version and the transaction.
This also keeps invariant 4 true as written: all `runs` SQL, migrations included, stays in
`storage.py`.

### 3.2 Connection policy (α)

`Database(path)` is a frozen value. `connect()` applies `row_factory=sqlite3.Row`, `foreign_keys=ON`
and `temp_store=MEMORY` (D-S19-13); `journal_mode=WAL` is a property of the file, which
`open_database` sets when it creates a store. `transaction()` is today's `get_db` (commit, rollback,
close). `create_app` builds one `Database` and stores it on `app.extensions` under `'database'`,
read through a typed `shared.get_database()`. `RunStorage(database, data_dir)`, the preset
functions and the chat functions take the `Database` in place of a path. `get_db` is deleted.

### 3.3 One writer of `runs`; the `jobs` table retired (β)

`RunStorage` gains the lifecycle writes JobManager makes today:
- `create_run(run_id, *, run_type, name, n_homes, created_at) -> RunRecord` (status `running`),
  bound by field name like the upsert;
- `mark_run_failed(run_id, message)`;
- `fail_interrupted_runs() -> int`.

A refused submit uses `delete_run` (no files exist yet).
`JobManager(storage, max_workers=2, *, simulate_home, new_id, clock)` writes only through it.
`submit_home_job(config, start, end, name=None)` and `submit_fleet_job(...)` lose `db_path`/`data_dir`.
`work_fn` loses its unused `conn`. The `jobs` table loses every write: the INSERT, the per-tick
progress UPDATE, the `started_at` UPDATE, the completed/failed UPDATEs and the DELETE. It leaves the
fresh-database DDL, and `JobStatus` moves into `jobs.py`. The in-memory JobManager stays
authoritative for live jobs, and the `runs` row is the durable outcome; the briefing already says
so. Existing databases drop the table in schema v1 (ι). `recover_stale_jobs` becomes
`storage.fail_interrupted_runs()`, called by `create_app`. `assistant.dispatch_tool` and its
trigger tools take the app's `RunStorage` and `JobManager`.

### 3.4 One listing, one typed summary, one headline (γ)

- `RunRecord.summary() -> SummaryStatistics | FleetSummary | None` decodes `summary_json` through
  `self.kind.summary_type` (None while the run has no summary).
- `RunRecord.home_configs() -> tuple[HomeConfig, ...] | None` decodes `config_json` the same way.
- `decoded_config`/`decoded_summary` and the three ad-hoc `json.loads` paths are deleted.
- `RunHeadline(generation_kwh, self_consumption_ratio)` comes from `run_headline(summary)`, which
  matches on the summary type with `assert_never`. It is the **one** place that maps
  `FleetSummary.fleet_self_consumption_ratio` to `self_consumption_ratio`.
- `RunStorage.page_runs(RunQuery) -> RunPage(records, total)` replaces `list_runs`,
  `api.history_list_runs`' SQL and `assistant.list_recent_runs`' SELECT. `RunQuery` is frozen and
  validates in `__post_init__`: a sort whitelist as a Literal, `1 ≤ per_page ≤ 100`, `page ≥ 1`.
- `RunStorage.totals() -> RunTotals(run_count, home_count, generation_kwh)` replaces
  `routes._get_aggregate_stats`. Counts come from SQL. Generation comes from `run_headline` over
  completed runs, in Python (no `json_extract`).
- The History JSON keeps its keys (`total_generation_kwh`, `self_consumption_ratio`) and adds
  `results_url`.
- `history.compare_page` passes `asdict(record.summary())` to the existing chart functions, so its
  behaviour is unchanged. The comparison charts' fleet handling is S21's (§8).

### 3.5 Run kinds and one results route (ε)

`stored_runs.RUN_KINDS: Mapping[RunType, RunKind]` is the run-type → behaviour table. A test
asserts its keys equal `get_args(RunType)`. `storage.RunRecord.kind` returns the record's entry,
which places the table "on `storage.RunRecord`" (D20). A `RunKind` names:
- `summary_type`;
- `read(run_dir, run_id) -> StoredRun` (the loader);
- `home_configs(config_document)`;
- `scenario_document(home_configs, name)` (the YAML export's scenario);
- (ζ) `default_name(home_configs)`.

A `RunKind` names no template: the page layer picks it (below).

`StoredHomeRun`/`StoredFleetRun` (frozen) carry the loaded objects. Each writes its run's files
(`write`) and answers the CSV export with `export_frame()`. The History YAML export reads none of
the run's files: it builds its scenario from `runs.config_json` through `run.kind.home_configs`
and `run.kind.scenario_document`, and never calls `load_run`, which reads every parquet time
series. `RunStorage.load_run(run_id)` reads the record and dispatches through `record.kind`.
`main.run_results` (`/results/<run_id>`) picks the template, the unnamed title and the page values,
and builds the charts, in one `match` on the `StoredRun` variant in `routes` with `assert_never`.
The page layer stays above storage, and mypy flags a new kind left unhandled.
`/results/home/<run_id>` and `/results/fleet/<run_id>` answer 301 to `/results/<run_id>`.

Every link uses the one route:
- `dashboard.html` through `url_for('main.run_results', ...)`;
- `runs.html` through the JSON row's `results_url`;
- the progress tracker through a server-provided URL (§13 Q4), its `result_type` parameter deleted;
- the assistant's trigger tools through `ToolContext.results_url`, the one route's path builder
  that `assistant._run_results_url_builder` makes in the request from the request's URL adapter,
  because `chat` streams its frames with no request context, where `url_for` cannot build the URL.

### 3.6 Default run name (ζ)

`RunKind.default_name` is the one home: home → `homes[0].name or "Web Simulation"`, fleet →
`"Fleet Simulation"`. These are today's stored values. JobManager applies it once, at
`create_run`. The save-time defaults, `api.simulate_fleet_api`'s `data.get("name", "Fleet
Simulation")`, `assistant.run_fleet_simulation`'s `or "Fleet Simulation"`,
`simulation_params.parse_home_config`'s `name or "Web Simulation"` and the client-side
`'Web Simulation'`/`'Fleet Simulation'` fallbacks are deleted. The fleet form's placeholder renders
the table's value. `PATCH /api/history/runs/<id>` refuses a null or blank `name` with a 400 naming
`name`.

### 3.7 Deletion wins and cancels the job (θ)

`JobManager.cancel_run(run_id) -> bool` gives a delete precedence over the job's final save:
- It finds the unfinished job of `run_id`. If the job is still queued, `Future.cancel()` drops it.
- Otherwise it sets the job's cancel flag under the job's own lock. Each `_TrackedJob` gets a
  `threading.Lock` of its own.
- The runner checks the flag at every `progress(...)` checkpoint and raises a private
  `_JobCancelled`.
- It takes the same per-job lock around the final check-and-save. Either the save completes before
  the cancel, and the delete then removes the saved run, or the flag is set first and the save never
  starts.

A cancelled job writes nothing to `runs`, and its row is already gone. It reports the new
**terminal** `JobStatus` `'cancelled'`, with message "Cancelled: its run was deleted". Its final SSE
event uses the failure event type until S20 gives it its own.

`api.history_delete_run` calls `job_manager.cancel_run(run_id)`, then `storage.delete_run(run_id)`
(row first, then directory). History's Delete stays available on running rows.

**Latency (stated, not hidden):** a home job stops only after its current `simulate_home` call
returns. That is up to one full simulation, about 40 s for a full-year home at the briefing's
measured rate. A fleet job stops after its current home. Interrupting inside `simulate_home` would
need a cancel hook on the frozen core surface and is out of scope (§11).

### 3.8 One process per store (λ)

`store_lock.acquire_store_lock(data_dir)` takes `fcntl.flock(LOCK_EX | LOCK_NB)` on
`<DATA_DIR>/dashboard.lock` and writes the holder's pid. On refusal it raises
`StoreLocked(path, holder_pid)`. `create_app` takes the lock **first**, before `open_database` and
recovery, and keeps it on `app.extensions['store_lock']`. `StoreLock.release()` is the seam a
shutdown handle calls (S16).

`cli/web.py start`: a second `web start` on the same store exits 1 naming the holder. Under
`--debug`, the process that holds the lock must be the one that serves, so the reloader's monitor
process does not build the app (e.g. `werkzeug.serving.run_simple` with the reloader, the app built
only when `is_running_from_reloader()`). `app.py`'s `__main__` block is deleted; the CLI is the one
entry.

### 3.9 Schema version and explicit migration (ι)

`schema.SCHEMA_VERSION` is derived as the highest step version. `open_database(path) -> Database`:
- a file with no tables is created at `SCHEMA_VERSION` from every owner's current DDL;
- a file at `SCHEMA_VERSION` is opened;
- anything else raises `SchemaVersionMismatch(path, found, expected)`. Its message names the path
  and both versions, and adds "Run `solar-challenge web migrate`" when `found < expected` or "This
  database was written by a newer solar-challenge" when `found > expected`. A legacy database is
  `found = 0` with tables.

`migrate_store(database_path, data_dir) -> MigrationReport` applies every pending step in order:
- the run-document part first (files, idempotent);
- then the database part and `PRAGMA user_version = step.version` in one transaction.

The `runs` DDL derives from `fields(RunRecord)`. Each field carries its column declaration in
`field(metadata=...)`, and the `CHECK`s come from the Literals as today.

**v1** (ι):
- `DROP TABLE IF EXISTS jobs`;
- rebuild `runs`, `config_presets` and `chat_messages` to their current DDL, so the 548/576
  `CHECK`s finally reach old databases;
- `runs.name` becomes `NOT NULL`, back-filled from `RunKind.default_name`;
- `'sweep'` is no longer admitted.

A row the new constraints refuse aborts the step and changes nothing, naming table, row id and
column. The rebuild renames the old table away, creates the current DDL under the final name,
copies, drops the old table and recreates the indexes. That leaves `sqlite_master` identical to a
fresh database's (probed, §14). `RunRecord.name: str`; the display fallbacks (`'Unnamed'`,
`'Home Simulation'`, `'Fleet Simulation'`, `'Unnamed Run'` ×3) go. The module docstring's "delete
the database file" policy is replaced by this one. `cli/web.py` gains `migrate`: lock →
`migrate_store` → print the report.

### 3.10 Stored-run format version and the strict reader (κ)

- Every save writes the run's documents and then, **last**, `format.json` (`{"format_version":
  RUN_FORMAT_VERSION}`), so a run directory without it is an incomplete or pre-versioning save.
- `RUN_FORMAT_VERSION` is derived as the version of the last `RUN_DOCUMENT_STEPS` entry.
- A loader refuses a marker that is missing or not `RUN_FORMAT_VERSION`.
- The reader refuses, as `StoredRunUnreadable(run_id, document, field, reason)`:
  - an unknown key;
  - a missing required (no-default) field;
  - a JSON value whose type cannot be the annotation (non-object for a dataclass, non-array for a
    sequence, bool or str for a number, …);
  - a dataclass whose `__post_init__` refuses the stored values.

  A missing *defaulted* field is still filled from its default, the documented compatibility.
- `RunRecord.summary()`/`home_configs()` use the same reader on the database's JSON and raise the
  same error, with `document = "runs.summary_json"`/`"runs.config_json"`.

**v2** (κ) is the first run-document step: "make today's lenient read explicit".
- For each run, it drops unknown keys from every document, files and database copies alike, and
  reports each dropped key whose value was not null.
- It validates the result with the strict reader, writes each changed file by temp file +
  `os.replace`, then writes the marker.
- A run whose documents fail validation (unloadable today too) is left untouched and reported, and
  migration continues. Afterwards that run's page names its field.

Every handler catches one type:
- the results route flashes the message and redirects;
- CSV/YAML export, `history_get_run` and `get_job_results` answer 409 `{"error", "run_id",
  "document", "field"}`;
- the History list shows the row with null headline fields and an `unreadable` reason;
- `totals()` skips the run with a logged warning naming it;
- the assistant's `get_run_results` returns `{"error": …}`.

### 3.11 Sweep (η)

- `RunType = Literal["home", "fleet"]`.
- The History filter's Sweep option, the `'sweep'` badge colour, `sweep_id` in
  `api.simulate_sweep`'s response, `parameter-sweep.js`'s `sweepId` and `sweep.html`'s "Sweep ID"
  line are deleted.
- `api._SWEEP_MAX_STEPS = 50` is refused above by the server with a 400 and rendered into
  `sweep.html`'s `max`.
- `?type=sweep` on the History API answers 400 naming the run types (via `RunQuery`, after γ).

### 3.12 Invariant 4 and the end-to-end gate (μ)

A test walks `src/solar_challenge/web/**/*.py` and asserts that `sqlite3.connect`, `FROM runs`,
`INSERT INTO runs`, `UPDATE runs` and `RunStorage(` match only in `database.py` (connect),
`storage.py` (runs SQL) and `app.py` (one construction). A `review/briefing.yaml` conventions line
points at it. μ also runs the §10 cross-module scenarios end to end.

## 4. Contract (B + H)

Signatures are normative in shape. Names in *italics* are tactical and may be renamed by the
implementer if every reference moves with them.

```python
# web/database.py — leaf; imports no solar_challenge.web module
@dataclass(frozen=True)
class Database:
    path: Path
    def connect(self) -> sqlite3.Connection: ...          # Row factory, foreign_keys=ON, temp_store=MEMORY — the only sqlite3.connect in src
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]: ...   # commit / rollback / close
@dataclass(frozen=True)
class TableSchema:
    name: str
    create: str                     # the CREATE TABLE statement (exact text a fresh database holds)
    indexes: tuple[str, ...]
def rebuild_table(conn: sqlite3.Connection, table: TableSchema, select: Mapping[str, str]) -> None: ...
    # rename-away, create current DDL, INSERT … SELECT <select[column] or column>, drop old, recreate indexes

# web/stored_runs.py — the format; no SQL, no Flask
RunType = Literal["home", "fleet"]
class StoredRunUnreadable(Exception):     # deliberately NOT a ValueError: S17's boundary translator turns
    run_id: str; document: str; field: str; reason: str      # ValueError/ConfigurationError into 400; this is a 409 / flash. Message names all four
@dataclass(frozen=True)
class StoredHomeRun:  run_id: str; config: HomeConfig; results: SimulationResults; summary: SummaryStatistics
@dataclass(frozen=True)
class StoredFleetRun: run_id: str; fleet_results: FleetResults; summary: FleetSummary; home_summaries: tuple[SummaryStatistics, ...]
StoredRun = StoredHomeRun | StoredFleetRun          # each: write(run_dir, ...) -> None; export_frame() -> pd.DataFrame
@dataclass(frozen=True)
class RunKind:
    summary_type: type[SummaryStatistics] | type[FleetSummary]
    read: Callable[[Path, str], StoredRun]
    home_configs: Callable[[Mapping[str, Any]], tuple[HomeConfig, ...]]
    scenario_document: Callable[[Sequence[HomeConfig], str], dict[str, Any]]
    default_name: Callable[[Sequence[HomeConfig]], str]          # ζ
RUN_KINDS: Mapping[RunType, RunKind]                              # keys == get_args(RunType)
@dataclass(frozen=True)
class RunDocumentStep:
    version: int; description: str
    apply: Callable[[RunType, StoredRunDocuments], StepResult]  # pure; apply(apply(d)) == apply(d)
RUN_DOCUMENT_STEPS: tuple[RunDocumentStep, ...]                   # ascending versions
RUN_FORMAT_VERSION: int = RUN_DOCUMENT_STEPS[-1].version

# web/storage.py — the runs table
RunStatus = Literal["running", "completed", "failed"]
@dataclass(frozen=True)
class RunRecord:                                   # one field per runs column; column decl in field metadata
    ...
    @property
    def kind(self) -> RunKind: ...                 # RUN_KINDS[self.type]
    def summary(self) -> SummaryStatistics | FleetSummary | None: ...      # raises StoredRunUnreadable
    def home_configs(self) -> tuple[HomeConfig, ...] | None: ...          # raises StoredRunUnreadable
RUNS_TABLE: TableSchema                            # derived from fields(RunRecord)
@dataclass(frozen=True)
class RunHeadline: generation_kwh: float; self_consumption_ratio: float
def run_headline(summary: SummaryStatistics | FleetSummary) -> RunHeadline: ...
@dataclass(frozen=True)
class RunQuery: run_type: RunType | None = None; text: str | None = None; created_from: date | None = None
                created_to: date | None = None; sort: RunSort = "created_at"; descending: bool = True
                page: int = 1; per_page: int = 20           # __post_init__ refuses page < 1, per_page ∉ [1, 100]
@dataclass(frozen=True)
class RunPage: records: tuple[RunRecord, ...]; total: int
@dataclass(frozen=True)
class RunTotals: run_count: int; home_count: int; generation_kwh: float
class RunStorage:
    def __init__(self, database: Database, data_dir: Path) -> None: ...
    def create_run(self, run_id: str, *, run_type: RunType, name: str, n_homes: int, created_at: str) -> RunRecord: ...
    def save_home_run(...) -> None: ...            # files, then format.json, then the row (upsert keeps id, created_at, name, notes)
    def save_fleet_run(...) -> None: ...
    def mark_run_failed(self, run_id: str, message: str) -> None: ...
    def fail_interrupted_runs(self) -> int: ...
    def delete_run(self, run_id: str) -> None: ...   # row first, then directory
    def run_record(self, run_id: str) -> RunRecord | None: ...
    def latest_run_named(self, name: str) -> RunRecord | None: ...
    def update_run_labels(...) -> RunRecord | None: ...   # refuses a null or blank name
    def page_runs(self, query: RunQuery) -> RunPage: ...
    def totals(self) -> RunTotals: ...
    def load_run(self, run_id: str) -> StoredRun: ...     # FileNotFoundError (absent) | StoredRunUnreadable
def migrate_runs_table_v1(conn: sqlite3.Connection) -> None: ...   # the runs SQL of schema v1 stays here

# web/schema.py
SCHEMA_VERSION: int                                  # derived: max step version; versions contiguous from 1
class SchemaVersionMismatch(Exception): path: Path; found: int; expected: int
def open_database(path: Path) -> Database: ...       # create fresh at SCHEMA_VERSION | open | raise SchemaVersionMismatch
def migrate_store(database_path: Path, data_dir: Path) -> MigrationReport: ...

# web/store_lock.py
class StoreLocked(Exception): path: Path; holder_pid: int | None
def acquire_store_lock(data_dir: Path) -> StoreLock: ...   # StoreLock.release()

# web/jobs.py
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
class JobManager:
    def __init__(self, storage: RunStorage, max_workers: int = 2, *, simulate_home=..., new_id=..., clock=...) -> None: ...
    def submit_home_job(self, config, start_date, end_date, name: str | None = None) -> tuple[str, str]: ...
    def submit_fleet_job(self, configs, start_date, end_date, name: str | None = None) -> tuple[str, str]: ...
    def cancel_run(self, run_id: str) -> bool: ...
```

**Invariants (each enforced at the place named):**

| # | Invariant | Enforced by |
|---|---|---|
| C1 | Only `Database.connect` opens SQLite; only `storage.py` issues `runs` SQL; only `app.py` builds a `RunStorage` | invariant 4 test (μ) |
| C2 | The database's `user_version` equals `SCHEMA_VERSION` whenever the app runs; a mismatch refuses start naming path and both versions | `open_database` (ι); invariant 7 test |
| C3 | `PRAGMA table_info(runs)` names equal `[f.name for f in fields(RunRecord)]`, fresh and migrated; a migrated database's `sqlite_master` equals a fresh one's | DDL derivation + invariant 7 test (ι) |
| C4 | Every stored run's documents carry `RUN_FORMAT_VERSION`; a loader refuses anything else with `StoredRunUnreadable` naming run id, document and field | stored_runs reader (κ); invariant 6 test |
| C5 | Every `RunDocumentStep` is idempotent and every migration step version is contiguous from 1 | generic tests over `RUN_DOCUMENT_STEPS` and `MIGRATIONS` (ι, κ) |
| C6 | `RUN_KINDS` covers exactly `RunType`; no module outside `stored_runs`/`storage`/`routes`' one `match` compares a run type to select behaviour | exhaustiveness test + `assert_never` (ε) |
| C7 | A run's name is decided once, at `create_run`, by `RunKind.default_name` when none is given; it is never NULL or blank | `create_run`, `update_run_labels`, `NOT NULL` (ζ, ι) |
| C8 | After a delete, no job writes the run back: a cancelled job saves nothing | per-job lock around check-and-save (θ) |
| C9 | Recovery (`fail_interrupted_runs`) runs only while this process holds the store lock | `create_app` order (λ) |
| C10 | A stored-dataclass shape change (rename, retirement, new required field) ships with a `RunDocumentStep` and a schema step | the contract for S2, S10, S12, S25 and S28 via S29 (§8); C5's tests run each new step |

## 5. Resolved design decisions

- **D-S19-1 Module strata (§3.1).** The table owners each state their DDL and migrations, and
  `schema.py` states order, version and transaction. The alternative, all DDL in `database.py`,
  needs an import cycle once the `runs` DDL derives from `RunRecord`. **Consequence:**
  invariant 7's checkable form names `schema.SCHEMA_VERSION`, not `database.SCHEMA_VERSION` (an
  amendment returned to the lead).
- **D-S19-2 One store version.** `PRAGMA user_version` counts every step, whether it touches the
  database, run files or both. `RUN_FORMAT_VERSION` is derived, the version of the last
  run-document step. This gives one startup check and one migrate command (D19). A format bump
  without a schema bump is impossible by construction, so no stored run can become unreadable
  without the app refusing to start first.
- **D-S19-3 Sweep (ruled by Leo, 2026-10-14).** Drop `'sweep'` and `sweep_id`. A run's type is its
  data shape, and how it was launched is a separate dimension (heuristic 3) with no consumer today.
- **D-S19-4 The `jobs` table is retired.** It has no reader. In-memory JobManager state is
  authoritative for live jobs and the `runs` row is the durable outcome, as the briefing already
  states. The table had no reader for `error_traceback`.
- **D-S19-5 Legacy stored runs.** Schema v2 makes today's lenient read explicit once, reporting
  every non-null key it drops. No run that loads today becomes unreadable after `web migrate`. From
  v2 on, unknown keys and missing required fields are refused, and a missing *defaulted* field is
  still filled (the remedy's scope).
- **D-S19-6 Delete (ruled by Leo, 2026-10-14).** Deletion wins and cancels the run's job, at the
  runner's checkpoints (§3.7). A new terminal `JobStatus` `'cancelled'` keeps a cancelled job from
  reading as failed. Mid-simulation interruption is out of scope.
- **D-S19-7 One `Database` value, not ambient config.** Every table owner takes the app's
  `Database`. The remedy's "`database.connect(db_path)`" is `Database(path).connect()`.
- **D-S19-8 The cross-type summary headline is S19's.** `run_headline` in `storage` is the one place
  the web maps fleet names to listing names. S21's comparison consumes it (and may widen
  `RunHeadline`). If S25 needs the mapping in core, S25 re-homes it and `run_headline` delegates;
  there is still one home (§8).
- **D-S19-9 Unreadable-run answers.** Pages flash and redirect, as "Run not found" does today. JSON
  answers 409 with structured fields (heuristic 12). The dashboard totals skip the run with a logged
  warning, and the History list makes it visible (G7 note, §15).
- **D-S19-10 Lock.** Use POSIX `flock`, which conflicts across file descriptions even within one
  process (probed, §14), so a second `create_app` in the same process is refused too. That is what
  makes the lock testable without subprocesses.
- **D-S19-11 Old results URLs answer 301** to `/results/<run_id>`, so existing bookmarks and the
  e2e suite's literal hrefs keep resolving. The e2e tests that assert hrefs are updated in ε.
- **D-S19-12 Durability: `synchronous` stays FULL (ruled by Leo, 2026-10-19, esc-859-3 option C).**
  A write through today's per-operation connection costs 5 syncs, about 7 ms, against 2-5 ms with
  a held connection (measured at `ede1d99`); `synchronous=NORMAL` alone gains nothing measurable.
  Nothing board-facing reads the store, so the gain does not justify giving up durability or
  adding app-lifetime connection state. α's `Database` keeps today's policy. Task 859 is cancelled.
- **D-S19-13 Temporary storage: `connect()` applies `temp_store=MEMORY` (task 1199).** Otherwise
  SQLite writes a temporary B-tree that outgrows its page cache (2,000 KiB by default), such as the
  run list's whole-row sort, to the first of `SQLITE_TMPDIR`, `TMPDIR`, `/var/tmp`, `/usr/tmp` and
  `/tmp` that `access()` admits. Where that directory refuses new files, as `/var/tmp` does in a
  sandboxed agent session (Landlock leaves `access()` unrestricted), the statement fails with
  "unable to open database file". The cost is memory in place of a temp file, bounded by the rows
  a statement holds: about +84 MiB for the last name-sorted page of 1,000 runs of 77 KB (measured
  2026-10-29, SQLite 3.45.1).

## 6. Pre-conditions and the tasks this stream subsumes

There are no upstream streams. The following **pre-existing tasks** overlap; the lead decides
before this batch is filed:

| Task | Status | Overlap | Proposed disposition |
|---|---|---|---|
| 468 | pending, **architect-routed 2026-10-13** | runs SQL into RunStorage; its plan builds **one RunStorage per job** from paths, which contradicts this stream | **cancel as superseded by β + γ before it dispatches** (urgent) |
| 547 | pending | `dispatch_tool` takes the app's RunStorage | cancel, superseded by β + γ |
| 355 | pending | one storage-level error for undecodable runs (`UndecodableRun`) | cancel, superseded by κ (`StoredRunUnreadable`) |
| 614 | pending (→355) | decode refuses JSON-type mismatches | cancel, superseded by κ (the strict reader includes it) |
| 646 | pending, has a branch | `_run_job`'s pre-`try` connect | β deletes that connection; if 646 merges first, β rebases over it. The executor-boundary half stays S20's (fk-484952247bb6) |
| 425 | **in-progress** | `tests/_web_runs.py` seeding helpers | β and κ depend on it (wire at decompose if still unmerged) |
| 647 | pending | partition of `tests/unit/test_web_jobs.py` | land before β (β depends on it) or cancel; β rewrites the jobs-table helpers it would move |
| 439, 438 | pending | production save-from-results function; e2e seeding onto helpers | independent; no dependency, rebase as needed |

The two mechanical tickets for this stream's keys (`tkt_0RVRX9E9QVNJQBDZSVFDFE046G` for
fk-cca5fd81afda, `tkt_0RVRX9E3MJH2BHG8KJ01E7ETVJ` for fk-2ac79d7a1989) **failed on a server
restart** and created no task (`list_tickets`, 2026-10-14). Both keys are filed by this batch, α/ι
and η.

## 7. Substrate verification (G3)

| Assumed capability | Evidence (main `1251be0` / stdlib / locked deps) | Status |
|---|---|---|
| `PRAGMA user_version`, transactional (rolled back with its transaction) | probe 2026-10-14, SQLite 3.45.1: `BEGIN; PRAGMA user_version=5; ROLLBACK` → 0 | ✅ |
| Rename-away rebuild leaves `sqlite_master` identical to a fresh database | probe 2026-10-14 (§14) | ✅ |
| `fcntl.flock` conflicts across two fds in one process | probe 2026-10-14: second `LOCK_EX\|LOCK_NB` raised `BlockingIOError` | ✅ |
| `werkzeug.serving.is_running_from_reloader`, `run_simple(use_reloader=True)` | werkzeug 3.1.8 (`uv.lock`); `serving.py` defines both. The reloader parent binds the socket and the child re-uses its fd | ✅ |
| `Future.cancel()` drops a queued job | stdlib `concurrent.futures`; `JobManager._schedule` holds the future | ✅ (β/θ keep the future on `_TrackedJob`) |
| `typing.assert_never` | Python ≥ 3.11 (`requires-python >=3.11`) | ✅ |
| `url_for` inside the chat stream | `assistant.chat` returns `stream_with_context(generate())` | ✅ |
| `RunRecord`-derived upsert pattern | `storage._run_row_upsert` (task 577) | ✅ wired |
| Results-page chart builders | `routes.home_results`/`fleet_results` call `charts.*` | ✅ wired (ε moves the calls) |
| A cancel hook inside core `simulate_home` | **absent** (no progress/cancel parameter) | ❌ not assumed; cancellation is checkpoint-granular (§3.7) |

No novel syntax or service is assumed. Every new mechanism is produced by a leaf in this batch.

## 8. Cross-PRD relationship (G4)

| Other stream | Direction | Seam mechanism | Owner | Status / ask |
|---|---|---|---|---|
| S2 Dispatch config | S2 consumes | Moving `DispatchStrategyConfig`/`GridChargeConfig` changes the stored `config.json` tree, and `HomeConfig.dispatch_strategy` retires at S29. Each needs a `RunDocumentStep` + schema step (C10). S2's deletion of `_field_types`' config-namespace merge applies wherever the reader lives after κ (`stored_runs`, and `web/field_tree.py` since task 1141) | S19 owns the mechanism; S2 owns its step | S2's stored-shape leaf **depends on κ** (ask the lead to add the edge) |
| S12 Load composition | S12 consumes | Heat-pump summary fields → named-load mapping; SimulationResults parquet columns change. S12 adds a schema step and **extends `RunDocumentStep` with a frame transform** (first consumer of frames) | S19 mechanism; S12 step + frame hook | already S12 → S19 in the program |
| S25 Board reports | S25 consumes | Retires `SummaryStatistics.seg_revenue_gbp` (stored): a `RunDocumentStep`. Its "five shared energy totals" helper: if it lands in core, `run_headline` delegates to it (D-S19-8) | S19 headline; S25 may re-home the mapping | ask: S25 → κ dependency |
| S28 Battery facts | S28 consumes | Retiring `BatteryConfig.efficiency` changes stored configs: a `RunDocumentStep` | S19 mechanism | ask: S28's held S29 leaf → κ |
| S10 Window and cadence | S10 consumes | S10 β adds `SummaryStatistics.window` (defaulted None: no step needed, old runs read None) and `date`/`timedelta` codec branches (they land in `web/field_tree.py`, in its writer and its leaf reader, where task 1141 moved the codec out of `stored_runs.py`). S10's held η makes `window` **required** and `simulation_days` a property. Under C10 that needs a `RunDocumentStep`: drop `simulation_days`, derive `window` from the run's stored index. η extends the step input with a read-only stored-index accessor (S12 later adds frame transforms). **Conflict:** S10's PRD instead lets every pre-η run become unreadable by name. That contradicts C10 and D-S19-5 and would blank every user's History results; returned to the lead | S19 mechanism; S10 η its step | ask: S10 η → κ, plus the step |
| S11 Tariff | S11 consumes | A stored run whose tariff no longer passes `TariffConfig.__post_init__` is refused by κ's reader as `StoredRunUnreadable` (the web only stores tiling presets, so none is expected) | S19 refusal | consistent with S11's PRD |
| S1 Errors leaf | shares | `StoredRunUnreadable` stays in `stored_runs` (S1 D2 lists it as a web-local type). κ wraps a domain `__post_init__` refusal (ConfigurationError, a ValueError after S1) into it | S1 base class; S19 the wrapper | consistent with S1's PRD; 355's stale premise is superseded by κ |
| S29 Surface bump | S29 consumes | Every retired or renamed field of a stored dataclass (`HomeConfig` tree, `SummaryStatistics`, `FleetSummary`) ships with its step in the bump (C10) | S29 | cross-reference line |
| S16 Fleet execution | S16 consumes | `create_app` collaborator injection keeps: lock first (λ), `JobManager(storage, …)` (β), recovery after the lock, and the reloader parent building no app. Its shutdown handle calls `StoreLock.release()`. FleetRunner's progress sink keeps per-home calls and lets `_JobCancelled` propagate (θ) | S16 owns the handle; S19 owns lock and constructor | S16 is wave 2; build on β/λ/θ |
| S20 Job events | S20 consumes | `JobStatus` lives in `jobs.py` with `'cancelled'` terminal (θ); `JobManager(storage)`; the `jobs` table is gone. S20's transition table includes `cancelled`. If S20 moves the `'completed'` write out of the save, it adds `RunStorage.mark_run_completed` | S20 owns transitions and events | already S20 → S19 |
| S17 Request boundary | S17 consumes | `shared.get_database()` joins `get_storage`/`get_job_manager` as service accessors that S17 moves beside app/jobs. ζ deletes `simulation_params`' `"Web Simulation"` default | S17 moves accessors | file-level overlap only |
| S21 Charts | S21 consumes | Comparison input is built from `RunRecord.summary()` and `RunHeadline` (widened by S21 if needed), with no second decoder or fleet mapping. Results-page panels plug into ε's per-variant `match` in `routes` | S19 decode + headline; S21 charts | S21 wave 1: its comparison leaf → γ |
| S22 Assistant | S22 consumes | `dispatch_tool` takes `storage`/`job_manager` (β, γ); S22's handler table keeps that injection | S22 | file overlap in `assistant.py` |
| S26 Sweep registry / S18 PageLimits | consume | `api._SWEEP_MAX_STEPS` (η): S26 keeps it; S18's `PageLimits` absorbs it | S18 eventually | cross-reference |

There is no reciprocal "the other owns it" pair: every row names one owner.

## 9. G5 — why B + H

All four triggers fire:
- blast radius: about 12 web modules, 2 CLI modules, templates and JS;
- mechanism count: 12 tasks, about 20 mechanisms;
- load-bearing seam: persistence of user data on disk;
- cross-PRD consumers: S2, S10, S12, S16, S20, S21, S25, S28, S29.

The contract (§4) lets each later stream add a migration step or plug into the run-kind table
without rediscovering the rules. The boundary tests (§10) face both the producer side (store,
schema, lock) and the consumer side (pages, exports, CLI, jobs).

## 10. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) | Side | Leaf |
|---|---|---|---|---|---|
| B1 | Fresh store | empty `DATA_DIR` | `user_version == SCHEMA_VERSION`; `table_info(runs)` names `== fields(RunRecord)` | producer | ι |
| B2 | Legacy store refuses start | fixture DB with pre-548 DDL, a `jobs` table and a NULL-name run | `create_app` raises `SchemaVersionMismatch` whose message has the path, `0` and `SCHEMA_VERSION`; `solar-challenge web start` exits 1 with it | consumer (CLI) | ι |
| B3 | Legacy store migrates | B2's fixture | `web migrate` exits 0 and reports the versions; afterwards `sqlite_master` equals a fresh database's, `jobs` is absent, the NULL name is the kind's default, and `create_app` starts | both | ι |
| B4 | Newer store | `user_version = SCHEMA_VERSION + 1` | start and migrate both refuse, naming "newer" and both versions; the file is unchanged | producer | ι |
| B5 | Legacy run directory | B3 done; a committed pre-469 run dir (no `format.json`) | before migrate: `GET /results/<id>` flashes a message naming the id and `format_version`, never a 500. After `web migrate`: 200, and `total_grid_charge_kwh == 0.0` | both | κ |
| B6 | Corrupt current run | a current run whose `summary.json` lacks `total_generation_kwh` / has an unknown key / has `"battery_config": "big"` | results page flashes; CSV, YAML, `history/runs/<id>` and `jobs/<id>/results` answer 409 with `run_id`, `document`, `field`; the History row has `unreadable` | consumer | κ |
| B7 | Fleet in History | a completed fleet run | the History JSON row's `self_consumption_ratio == FleetSummary.fleet_self_consumption_ratio`, `results_url == "/results/<id>"`; dashboard energy includes its generation | consumer | γ |
| B8 | Wrong-type URL | a fleet run | `GET /results/home/<id>` → 301 → `/results/<id>` → 200 fleet page; `/results/fleet/<home id>` → home page | consumer | ε |
| B9 | Delete a running run | blocking fake simulation, job inside `simulate_home` | `DELETE` → 200 and the run is 404 at once; after release: no run dir, job status `cancelled`, `runs` row absent | both | θ |
| B10 | Delete a queued run | `max_workers=1`, a job queued behind a blocked one | queued job's simulate is never called; status `cancelled` | producer | θ |
| B11 | Delete mid-fleet | 3-home fleet, block in home 1 | after release, homes 2 and 3 are never simulated; nothing is saved | producer | θ |
| B12 | Second process | app A holds `DATA_DIR`, run R `running` | `create_app` B raises `StoreLocked` naming A's pid; R is still `running` | producer | λ |
| B13 | Debug reloader | — | `solar-challenge web start --debug --port <free>` (HOME at a temp dir) serves `GET /` 200 | consumer (CLI) | λ |
| B14 | Owner grep | — | invariant 4: matches only in `database.py`, `storage.py`, `app.py` | producer | μ |
| B15 | Step hygiene | — | every `RunDocumentStep` is idempotent on its fixture; versions contiguous; `RUN_KINDS` keys `== get_args(RunType)` | producer | ι/κ/ε |
| B16 | End to end | legacy fixture store (DB + run dirs) | refuse → migrate → start → History lists every run with headlines → each `results_url` renders → CSV/YAML export → delete → gone | both | μ |

Every test drives public seams: HTTP routes, the CLI through `CliRunner` or a subprocess,
`RunStorage`'s and `schema`'s public functions, and committed fixtures. No test reaches a private
name.

## 11. Decomposition plan

Every leaf carries `metadata.x_finding_key` (list), `x_finding_run =
"review-all-solar_challenge-20261013"`, `source = "review-all"`, `priority` = the highest severity
among its keys, and file-level `metadata.files`. Every leaf runs the verify suite and `mypy --strict`.
A leaf that edits a template or JS updates the e2e tests asserting its hrefs or labels, runs
`pytest tests/e2e -m 'not slow'` for the touched files locally, and rebuilds `static/dist/style.css`
if a class token changed (CLAUDE.md).

#### α — `Database`: one connection policy for every SQLite connection
- **Keys:** fk-cca5fd81afda, fk-bfdae4525795 · **priority:** medium
- **Modules:** `web/database.py`, `web/storage.py` (constructor), `web/presets.py`, `web/app.py`,
  `web/shared.py` (`get_database`), `web/api.py` and `web/assistant.py` (presets/chat call sites),
  `web/jobs.py` (its connection via `Database`), tests.
- **Work:** §3.2. Delete `get_db`. Route presets and chat through `get_database()`, which removes
  their 6 config reads (api presets ×3, assistant chat ×3).
- **Signal (intermediate → β, γ, δ, ι):** a connection from `Database(path).connect()` reports
  `PRAGMA foreign_keys = 1` and `journal_mode = wal`, and so does the app's
  `get_database().connect()` on a test app. Saved presets and chat history answer through
  `/api/presets` and `/assistant/history` as before, with no `current_app.config` read in the
  presets or chat paths. `sqlite3.connect` appears only in `database.py`.
- **Prereqs:** none.

#### β — JobManager writes through the app's RunStorage; the `jobs` table is retired
- **Keys:** fk-bfdae4525795, fk-df9d0fc1b2d3, fk-9d7f66fdcfdd, fk-c14c02dc1b77 · **priority:** medium
- **Modules:** `web/jobs.py`, `web/storage.py`, `web/app.py`, `web/api.py` (4 submit sites),
  `web/assistant.py` (trigger tools, `dispatch_tool`'s job manager), `web/database.py` (jobs DDL out
  of the fresh schema, `JobStatus` → jobs.py), tests (`test_web_jobs.py`, `web_api`,
  `web_assistant`).
- **Work:** §3.3.
- **Signal (leaf):**
  - `POST /api/simulate/home` on a test app answers 201, and `GET /api/history/runs/<run_id>` shows
    `running`, then `completed`, with the submit's name.
  - A failing fake shows `failed` with the job's message.
  - A run left `running`, then the app rebuilt on the same store, shows `failed` "Interrupted by
    server restart". λ, which lands later, adds the lock release this test then needs.
  - A fresh database has no `jobs` table.
  - `JobManager.submit_*` has no path parameters, and `jobs.py` contains no SQL.
- **Prereqs:** α. Out of batch: 425 (in-progress), 647 (if it is to land).

#### η — Drop the `'sweep'` run type and `sweep_id`; refuse more than 50 sweep steps on the server
- **Keys:** fk-2ac79d7a1989, fk-9d7f66fdcfdd · **priority:** low
- **Modules:** `web/database.py` (`RunType`), `web/api.py::simulate_sweep`, `templates/history/runs.html`,
  `templates/components/macros.html`, `templates/scenarios/sweep.html`, `static/js/parameter-sweep.js`,
  tests including e2e `test_parameter_sweep.py`.
- **Work:** §3.11, except the `?type=sweep` 400, which lands with γ's `RunQuery`.
- **Signal (leaf):**
  - The History page's type filter offers exactly All/Home/Fleet.
  - `POST /api/simulate/sweep` answers without `sweep_id`, and with `steps: 51` it answers 400 naming
    the ceiling.
  - `sweep.html` renders `max="50"` from the constant.
  - A fresh database's `runs` CHECK refuses `'sweep'`.
- **Prereqs:** α (both edit `database.py`).

#### ε — Run kinds on `RunRecord` and one `/results/<run_id>` route
- **Keys:** fk-81e62b2640a7 · **priority:** medium
- **Modules:** `web/stored_runs.py` (new: `RunKind`, `RUN_KINDS`, `StoredHomeRun`/`StoredFleetRun`,
  the loaders moved from storage; it imports `RunType` from `database` until ι moves it),
  `web/storage.py`
  (`RunRecord.kind`, `load_run`), `web/routes.py`, `web/api.py` (CSV/YAML exports),
  `web/assistant.py` (`results_url` ×2), `templates/dashboard.html`, `templates/history/runs.html`,
  `templates/simulate/partials/progress-tracker.html` (+ its callers), e2e tests asserting
  `/results/home|fleet/` hrefs.
- **Work:** §3.5. The History JSON rows gain `results_url`.
- **Signal (leaf):** B8.
  - Dashboard, History rows (both layouts) and the progress tracker link to `/results/<id>`.
  - The assistant's trigger tools return `results_url == "/results/<id>"`.
  - CSV and YAML exports choose their layout from the record's kind, so no site compares a type
    string.
  - `RUN_KINDS` covers `RunType` exactly (B15).
- **Prereqs:** η.

#### γ — One run list, one typed summary, one headline
- **Keys:** fk-a37ed16d59c5 (**high**), fk-34a6679f1ef3, fk-df9d0fc1b2d3, fk-9d7f66fdcfdd,
  fk-bfdae4525795 · **priority:** high
- **Modules:** `web/storage.py`, `web/api.py` (`history_list_runs`, `history_get_run`,
  `get_job_results`), `web/assistant.py` (`list_recent_runs`, `get_run_results`, `dispatch_tool`
  takes `storage`), `web/routes.py` (`index`, `_get_aggregate_stats` → `totals`), `web/history.py`
  (`compare_page` input), tests.
- **Work:** §3.4. This removes the History list's config read.
- **Signal (leaf):** B7.
  - `GET /api/history/runs?type=fleet` lists a fleet run with a non-null `self_consumption_ratio`
    equal to its `fleet_self_consumption_ratio` (the 653 class).
  - The assistant's `list_recent_runs` reports the same value.
  - `?type=sweep` answers 400 naming the run types.
  - The dashboard's energy total sums home and fleet generation.
  - `api.py`, `assistant.py` and `routes.py` hold no `runs` SQL, and `decoded_summary` is gone.
- **Prereqs:** β, ε. **Added as a dependency of the trigger-chain gate** once it exists (high).

#### δ — Saved scenario presets owned by `presets.py`
- **Keys:** fk-df9d0fc1b2d3, fk-bfdae4525795 · **priority:** medium
- **Modules:** `web/presets.py`, `web/api.py` (`scenarios_list_presets`, `scenarios_get_preset`), tests.
- **Work:** The `config_presets` reads in `api.py` move into `presets.py` functions taking the
  `Database`. The get filters `type = 'fleet'`. A database error is logged and answered 500, not
  404 "not found". This removes the last 2 config reads.
- **Signal (leaf):**
  - `GET /api/scenarios/presets/<name>` of a saved **home** preset answers 404 (today 200).
  - A forced database error answers 500 with a logged record naming the preset.
  - `api.py` contains no `config_presets` SQL, and `current_app.config[` appears in no web module
    but `app.py`.
- **Prereqs:** α.

#### ζ — A run's default name has one home
- **Keys:** fk-2ff305a1dbb2 · **priority:** low
- **Modules:** `web/stored_runs.py` (`RunKind.default_name`), `web/jobs.py`, `web/storage.py`,
  `web/api.py`, `web/assistant.py`, `web/simulation_params.py`, `web/routes.py` (fleet form
  placeholder), `templates/simulate/home.html`, `templates/simulate/fleet.html`,
  `static/js/fleet-simulator.js`, tests.
- **Work:** §3.6.
- **Signal (leaf):**
  - `POST /api/simulate/fleet` without `name` lists as "Fleet Simulation".
  - A home without a name lists as "Web Simulation", and with `config.name` as that name.
  - `PATCH .../runs/<id>` with `{"name": ""}` or `null` answers 400 naming `name`.
  - The default-name literals exist only in `RUN_KINDS`, apart from the NULL-name display fallbacks
    that ι removes once it back-fills names and makes the column `NOT NULL`.
- **Prereqs:** ε, β.

#### θ — Deleting a run cancels its job; deletion wins
- **Keys:** fk-8f4f4d63f917 · **priority:** medium
- **Modules:** `web/jobs.py`, `web/api.py` (`history_delete_run`, the final-event map for
  `cancelled`), `static/js/progress-tracker.js` (shows "Cancelled"), tests.
- **Work:** §3.7.
- **Signal (leaf):** B9, B10, B11 through `POST /api/simulate/*` and `DELETE /api/history/runs/<id>`.
  `GET /api/jobs/<job_id>` reports `cancelled`, and the progress page shows "Cancelled: its run was
  deleted".
- **Prereqs:** β.

#### λ — One process per store: the `DATA_DIR` lock before recovery
- **Keys:** fk-e29393df0cd4 · **priority:** low
- **Modules:** `web/store_lock.py` (new), `web/app.py` (order; `__main__` deleted),
  `cli/web.py::start` (`--debug` path), `tests/_web_app.py` (release seam for tests that rebuild an
  app on one dir), tests, `review/briefing.yaml` (web-dashboard key decision: single process is
  enforced by the lock).
- **Work:** §3.8.
- **Signal (leaf):** B12, B13.
  - A second `solar-challenge web start` on the same store exits 1 naming the lock path and the
    holder pid, and the first server's in-flight run stays `running`.
- **Prereqs:** β.

#### ι — Schema version, ordered migrations, `solar-challenge web migrate`
- **Keys:** fk-1070454e4c6e, fk-cca5fd81afda · **priority:** medium
- **Modules:** `web/schema.py` (new), `web/database.py` (`TableSchema`, `rebuild_table`, chat DDL;
  docstring policy; the runs, presets DDL and their Literals leave it), `web/storage.py`
  (`RUNS_TABLE` from `RunRecord`, `migrate_runs_table_v1`, `RunStatus` here, `name: str`),
  `web/stored_runs.py` (`RunType` moves here), `web/presets.py` (DDL, `PresetType` + v1),
  `web/app.py`, `cli/web.py` (`migrate`;
  `start` reports the mismatch), templates/routes (display fallbacks), `tests/fixtures/databases/`
  (pre-548 fixture), tests, `review/briefing.yaml` (invariant 7 line; "what working means" start
  line amended).
- **Work:** §3.9, schema v1.
- **Signal (leaf):** B1–B4 through `solar-challenge web start` and `web migrate` (`CliRunner` with
  `HOME` at a temp dir). **Invariant 7 test** as checkable (§14 G6), plus its briefing line.
- **Prereqs:** α, β, γ, δ, η, ζ, λ.

#### κ — Stored-run format version, strict reader, `StoredRunUnreadable`
- **Keys:** fk-273b8b09c91a, fk-a37ed16d59c5 · **priority:** high (shares the high key's decoders)
- **Modules:** `web/stored_runs.py`, `web/storage.py`, `web/schema.py` (v2), `web/routes.py`,
  `web/api.py`, `web/history.py`, `web/assistant.py` (handlers), `tests/fixtures/stored_runs/`
  (frozen pre-469 home run dir and a legacy fleet run dir), tests, `review/briefing.yaml`
  (invariant 6 line).
- **Work:** §3.10, schema v2.
- **Signal (leaf):** B5, B6.
  - `web migrate` prints dropped non-null keys and unmigratable runs by id and field.
  - **Invariant 6 test** as checkable (§14), plus its briefing line.
- **Prereqs:** ι, ε, γ. Out of batch: 425. **Added to the trigger-chain gate** (high).

#### μ — Integration gate: invariant 4 and the end-to-end store scenario
- **Keys:** fk-df9d0fc1b2d3, fk-bfdae4525795 · **priority:** medium
- **Modules:** a new test module for invariant 4, a new integration test for B16,
  `tests/fixtures/` (re-uses ι's and κ's fixtures), `review/briefing.yaml` (invariant 4 line).
- **Signal (leaf; the C-as-integration-gate):** B14 and B16 pass on main. That is the user path
  "upgrade an old dashboard and keep every run" end to end, through the CLI and HTTP.
- **Prereqs:** every other leaf.

**DAG:** α → {β, δ, η}; η → ε; {β, ε} → γ; {β, ε} → ζ; β → {θ, λ};
{α, β, γ, δ, η, ζ, λ} → ι; {ι, ε, γ} → κ; all → μ.

**Out-of-batch edges** (wired at decompose): β → 425, κ → 425 (if unmerged), β → 647 (if it is
kept). Asked of the lead: S2/S10 η/S25/S28 stored-shape leaves → κ, and S21's comparison leaf → γ.

## 12. Out of scope

- Interrupting a running `simulate_home` mid-call: this needs a cancel hook on core's frozen
  surface (D4/S29).
- Typed comparison charts and their fleet axes (S21: fk-3239afd8ce6b, fk-8e109704aa24), job state
  transitions and SSE event names (S20), `create_app` collaborator injection and its shutdown handle
  (S16), and moving `get_storage`/`get_job_manager`/`get_database` beside app/jobs (S17).
- Recording sweep provenance (ruled out, D-S19-3).
- Removing the duplicated summary copy (`runs.summary_json` vs `summary.json`). It stays. Each
  `RunDocumentStep` transforms both through one function, so they cannot drift (G7 note, §15).
- A Windows file lock: the dashboard's supported platform is POSIX (§13 Q3).
- Parquet frame migrations: added by S12, the first stream to change stored columns (§8).

## 13. Open questions (tactical, decided at implementation)

1. **Store location option.** Default: no `--data-dir` option; `web migrate` and `web start` read
   the one default location function that `create_app` uses, and tests point `HOME` at a temp dir.
   Decide in ι.
2. **Marker file name** (`format.json`) and the exact JSON key. Decide in κ.
3. **Non-POSIX platforms.** Default: `acquire_store_lock` raises a clear error naming the platform
   where `fcntl` is absent. Decide in λ.
4. **Progress-tracker URL source.** Default: the submit responses' `results_url` (`url_for`); an
   alternative is a URL in the final SSE payload (S20). Decide in ε.
5. **Totals performance.** Python aggregation over completed runs' summaries is O(runs).
   Measure on 1,000 runs in γ, and record it. If it is over about 200 ms, keep the counts in SQL and
   cache the per-run headline. That is a tactical detail, as long as `run_headline` stays the only
   decoder.
6. **Redirect code** (301 vs 308). Default 301 (GET-only routes).

## 14. G6 — premise validity of the asserted signals

- **Exactness:** "a migrated database's `sqlite_master` equals a fresh one's" holds only for the
  rename-away rebuild (create the current DDL under the final name). A rename-into-place rebuild
  stores `CREATE TABLE "runs"` with quotes and fails the comparison. The configuration is named in
  §3.9 and was probed (`sqlite_master equal: True`).
- **Invariant 7 checkable form, as this stream will implement it:** after `open_database` on a fresh
  file, `PRAGMA user_version == schema.SCHEMA_VERSION`, and `table_info(runs)` names
  `== [f.name for f in fields(RunRecord)]`. On a file at a lower version, `open_database` raises
  `SchemaVersionMismatch` naming both versions and the path, and `migrate_store` brings it to
  `SCHEMA_VERSION` (D19 makes the "or" a refusal plus an explicit migrate). Fixture: a pre-548 DDL
  database and a fresh one. **Amendment returned:** the program text's `database.SCHEMA_VERSION`
  reads `schema.SCHEMA_VERSION`.
- **Invariant 6 checkable form:**
  - a fixture run directory saved without a version raises `StoredRunUnreadable` naming the run id
    and `format_version`;
  - a current run whose `summary.json` lacks `total_generation_kwh` raises it naming that field;
  - a current-format fixture loads;
  - a current run whose `summary.json` carries an unknown key raises it naming the key.

  **Amendment returned:** the program text's third clause, "`_deserialize_dataclass` with an
  unknown key raises the same type", is asserted through the public loader, because a test calling
  the private deserializer reaches an internal (Leo's tests stance), and the private function has no
  run id to name.
- **Invariant 4:** holds as written. The runs-table migration SQL lives in `storage.py`, and
  `schema.py` holds none of the patterns.
- **Rejection signals (branch 4):** every refusal named in §11 is produced by a mechanism built in
  the same leaf, and each signal authors the refused input and observes the named error:
  `SchemaVersionMismatch`, `StoredRunUnreadable`, `StoreLocked`, the 400s for `steps: 51`, a blank
  name and `?type=sweep`, and the 409s. B12's in-process refusal relies on `flock` conflicting
  within a process, probed ✅. With `lockf`/`fcntl` record locks it would not conflict, so the
  contract names `flock`.
- **Numeric:** "about 40 s" for a full-year home (θ latency) is not asserted by any test. It is a
  documented expectation from the briefing's measured 3.5 s per 30 days, and θ's signals use
  blocking fakes. B11's "homes 2 and 3 never simulated" needs the per-home checkpoint, which
  `_run_fleet_simulation`'s loop calls before each home ✅.
- **End-to-end (branch 3):**
  - B7 needs `run_headline` (γ) and `results_url` (ε); γ depends on ε ✅.
  - B5 needs schema v1 (ι), the format marker and v2 (κ), and the kind loader (ε); κ depends on all
    three ✅.
  - B16 needs every leaf; μ depends on all ✅.
  - ζ's "names are never NULL" is asserted only for new runs and PATCH. The NOT NULL column and
    back-fill are ι's, and ι depends on ζ ✅.

## 15. G7 — advisory walk

This repo has no `docs/legibility/design-invariants.md`, so the walk uses dark-factory's trigger
shapes and is advisory:

- **no-silent-fail-soft:** `totals()` skipping an unreadable run. It is logged by name, and the run
  is visible in History with its reason. Recorded as a **G7 waiver** on γ/κ: the dashboard's
  headline total is a display figure, and failing the index page for one damaged run is worse.
- **corroborate-before-acting:** recovery fails `running` rows only while holding the store lock
  (C9). That resolves fk-e29393df0cd4.
- **holds-owned-and-bounded:** the lock records its holder pid and is bounded by process lifetime
  (`flock` is released on exit or crash).
- **status-matches-liveness:** an interrupted run becomes `failed` at the next start. A cancelled
  job reports `cancelled`, and its run row is gone.
- **one-fact-one-home:** the run's summary is held in `runs.summary_json` and `summary.json` (out
  of scope, §12). Each migration step transforms both through one function. The run-kind table, the
  default name, the connection policy and the summary decoding each get one home here.
- **contracts-machine-checked:** C1–C9 are each enforced by a test or a type (§4). C10 is enforced
  for each step by C5's generic tests.
- **exceptions-owned-or-ratified:** invariant 4's allow-list (3 files) is ratified by D27.

## 16. META

**If this PRD is decomposed and queued without further oversight, will what gets built be
complete, coherent, cohesive and good?** Yes, conditional on the lead's §6 dispositions. If task
468 dispatches first, its per-job-RunStorage design lands and β must undo it.

- Every finding key has a leaf.
- Every mechanism has a named consumer: a page, endpoint or CLI command in this batch, or a later
  stream in §8.
- The two rulings and the two session rulings are embodied.
- The module layout is decided.
- The migration and format contracts give S2, S10, S12, S25 and S28 a concrete recipe; S10's conflicting plan for its held η is returned to the lead.
- The remaining questions (§13) are local.
