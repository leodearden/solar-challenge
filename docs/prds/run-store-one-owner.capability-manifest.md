# Capability manifest — Run store with one owner (S19)

This manifest mechanises G3 (each substrate exists and is **wired**, not merely declared) and G6
(each premise is valid) for every leaf of `docs/prds/run-store-one-owner.md`. Each capability a
signal asserts is bound to evidence, in one of these forms:
- `grep:<file> <symbol>` for substrate on main;
- `producer:<label> upstream` for a capability an in-batch prerequisite produces;
- `probe:` for a behaviour measured on 2026-10-14;
- `own-task` for what the leaf itself builds.

**Code anchors** were verified against main `1251be0` (2026-10-14). Citations are by symbol;
re-locate them at implementation time. The machine-readable twin is
`run-store-one-owner.capability-manifest.yaml`.

**Batch verdict at authoring: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, `producer-downstream` or `producer-extent-short`:
- Every leaf's asserted capability is produced by the leaf itself or by an upstream label, in the
  DAG of PRD §11.
- The one capability the design could have assumed falsely, a cancel hook inside core
  `simulate_home`, is **not assumed**: cancellation is checkpoint-granular (PRD §3.7).
- The three premises this design rests on were probed at authoring: `user_version` rolls back with
  its transaction, a rename-away rebuild gives an identical `sqlite_master`, and `flock` conflicts
  within one process.
- Every rejection signal is backed by a mechanism the same leaf builds (G6 branch 4).

Re-walk this manifest at decompose: main moves, and β/κ depend on task 425 landing.

**Delivered-check polarity.** The sidecar validates against `CapabilityManifestDoc`. Run with each
leaf's declared files, `shared.delivered_check_polarity.lint_delivered_checks` reports every check
clean except one warning: μ's `current_app.config[` absent-check, whose matches its upstream leaves
α/β/γ/δ remove. μ has no in-batch dependent, so the warning cannot wedge anything.

ζ's absent-check is deliberately scoped to the write path (`storage.py`, `jobs.py`). The templates'
`'Unnamed Run'` display fallbacks are ι's to delete after its `NOT NULL` back-fill, and ι depends on
ζ, so a template-wide scope would deadlock the pair.

## α — `Database`: one connection policy — intermediate (unlocks β, γ, δ, η, ι)

| Capability asserted | Evidence | Status |
|---|---|---|
| Three connection setups exist today (`init_db`, `get_db`, `JobManager._run_job`) | grep:`web/database.py` `init_db`, `get_db`; grep:`web/jobs.py` `_run_job` `sqlite3.connect` | ✅ |
| `Database.connect()` applies WAL, Row, `foreign_keys` | own-task (stdlib `sqlite3`) | ✅ |
| Presets/chat endpoints keep answering | grep:`web/api.py` `list_presets` → `presets.home_presets`; grep:`web/assistant.py` `chat_history` → `database.get_chat_history` (both wired today; α changes only their argument) | ✅ |

## β — JobManager writes through the app's RunStorage; `jobs` retired — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Submit → `running` → `completed` visible in `GET /api/history/runs/<id>` | grep:`web/api.py` `history_get_run` → `RunStorage.run_record` (wired); own-task `create_run`; save's upsert writes `completed` (grep:`web/storage.py` `_saved_run_row`) | ✅ |
| Failure writes `failed` + message | grep:`web/jobs.py` `_record_failed_run_row` (moves to `RunStorage.mark_run_failed`, own-task) | ✅ |
| Restart marks interrupted runs failed | grep:`web/jobs.py` `recover_stale_jobs` (moves to `fail_interrupted_runs`, own-task); `create_app` call site wired | ✅ |
| Rebuilding an app on one store in a test | producer:λ is **downstream**, so β's restart test must not need a lock: until λ lands no lock exists, and λ adds the release seam and updates the test | ✅ (ordering noted) |
| No reader of the `jobs` table is lost | grep `FROM jobs` over `src/` → only `jobs.py` writes; `JobManager.job_state` docstring "never reads the jobs table" | ✅ |

## η — Drop `'sweep'` and `sweep_id`; server step ceiling — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Type filter options rendered by `templates/history/runs.html` | grep:`runs.html` `<option value="sweep">` (to delete) | ✅ |
| `simulate_sweep` validates `steps` before submitting | grep:`web/api.py` `simulate_sweep` `Steps must be at least 2` (ceiling added beside it) | ✅ |
| No writer stores `'sweep'` today | grep `run_type="sweep"` / `'sweep'` writers over `src/` → none (verdict note, fk-2ac79d7a1989) | ✅ |
| A fresh DB's CHECK refuses `'sweep'` | grep:`web/database.py` `_check_one_of("type", RUN_TYPES)` derives the CHECK from the Literal | ✅ |
| Rejection: `steps: 51` → 400 | own-task (the refusal it adds); the test authors the input and observes the 400 | ✅ |

## ε — Run kinds on `RunRecord`; one `/results/<run_id>` route — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Home and fleet loaders exist | grep:`web/storage.py` `load_home_run`, `load_fleet_run` (move into `RUN_KINDS[...].read`) | ✅ |
| Page builders exist | grep:`web/routes.py` `home_results`, `fleet_results` chart calls (move under one route's `match`) | ✅ |
| Exports pick their layout | grep:`web/api.py` `history_export_csv` (`to_dataframe` / `to_aggregate_dataframe`), `history_export_yaml` (`home_scenario` / `fleet_scenario`) | ✅ |
| `url_for` in the assistant's tool path | grep:`web/assistant.py` `stream_with_context(generate())` | ✅ |
| `/results/home/<fleet id>` is a 500 today | probe (finding fk-81e62b2640a7): `stored_home_config` on a fleet config → `TypeError` | ✅ (motivates B8) |
| 301 redirect | Flask `redirect(..., code=301)` | ✅ |

## γ — One run list, one typed summary, one headline — leaf (high)

| Capability asserted | Evidence | Status |
|---|---|---|
| `RunRecord.summary()` typed by kind | producer:ε upstream (`RUN_KINDS[t].summary_type`) | ✅ |
| Fleet summary has `fleet_self_consumption_ratio` | grep:`fleet.py` `class FleetSummary` field `fleet_self_consumption_ratio`, populated by `calculate_fleet_summary` (non-sentinel on the production path) | ✅ |
| History list endpoint and params | grep:`web/api.py` `history_list_runs` (page, per_page, sort, order, type, q, date_from, date_to) | ✅ |
| Dashboard totals | grep:`web/routes.py` `_get_aggregate_stats` → `index` | ✅ |
| `?type=sweep` → 400 | own-task (`RunQuery` refusal) on producer:η's two-value `RunType` | ✅ |
| `dispatch_tool` takes the storage | producer:β upstream (trigger tools already lost their paths) | ✅ |

## δ — Saved scenario presets owned by `presets.py` — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Today's get answers a home preset | grep:`web/api.py` `scenarios_get_preset` (no `type = 'fleet'` filter; verdict note, fk-df9d0fc1b2d3) | ✅ |
| DB error answered 404 today | grep:`web/api.py` `scenarios_list_presets`/`scenarios_get_preset` `except` → 404 | ✅ |
| `Database` handle reachable | producer:α upstream (`get_database()`) | ✅ |

## ζ — A run's default name has one home — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Default-name literal sites | re-measured 2026-10-14: 12 lines in `web/*.py` + 6 in templates/JS (PRD §2) | ✅ |
| `RunKind.default_name` slot | producer:ε upstream | ✅ |
| Name decided at `create_run` | producer:β upstream | ✅ |
| Rejection: blank/null `name` PATCH → 400 | own-task, in `update_run_labels` + `history_patch_run` | ✅ |

## θ — Deleting a run cancels its job; deletion wins — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| Queued-job drop | stdlib `Future.cancel()`; grep:`web/jobs.py` `_schedule` creates the future (θ keeps it on `_TrackedJob`) | ✅ |
| Checkpoints exist | grep:`web/jobs.py` `_run_home_simulation` `progress(20.0…)`, `progress(80.0…)`, `progress(90.0…)`; `_run_fleet_simulation` per-home `progress(pct, …)` | ✅ |
| A cancel inside `simulate_home` | **not asserted** (grep:`home.py` `simulate_home` has no hook) | n/a |
| Final-event mapping for a new terminal status | grep:`web/api.py` `_FINAL_EVENT_TYPE_BY_STATUS` | ✅ |
| Deterministic blocking fakes | grep:`tests/unit/test_web_jobs.py` `_BlockingSimulation` | ✅ |

## λ — One process per store — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| In-process refusal (B12) | probe 2026-10-14: `flock` second fd → `BlockingIOError` | ✅ |
| Reloader parent can skip building the app | werkzeug 3.1.8 `run_simple` binds in the parent and re-uses the fd in the child; `is_running_from_reloader` | ✅ |
| The live server's run stays `running` | ordering: lock before `fail_interrupted_runs` (producer:β upstream) | ✅ |
| Subprocess `web start` offline | `tests/conftest.py` offline guard allows localhost | ✅ |

## ι — Schema version, migrations, `web migrate` — leaf

| Capability asserted | Evidence | Status |
|---|---|---|
| `user_version` transactional | probe 2026-10-14 (rollback → 0) | ✅ |
| Migrated `sqlite_master` == fresh | probe 2026-10-14, rename-away rebuild (`True`) | ✅ (configuration-dependent: rename-into-place fails; PRD §14) |
| Pre-548 DDL accepted bogus rows | probe (finding fk-1070454e4c6e) | ✅ (fixture motivation) |
| Names back-filled from kind default | producer:ζ upstream | ✅ |
| `migrate` takes the lock | producer:λ upstream | ✅ |
| Typer subcommand group | grep:`cli/web.py` `app = typer.Typer`; `start` registered | ✅ |
| Rejection: mismatch refuses start | own-task `SchemaVersionMismatch`; `cli/utils.handle_errors` maps it to exit 1 | ✅ |

## κ — Stored-run format version, strict reader — leaf (high)

| Capability asserted | Evidence | Status |
|---|---|---|
| Skip-unknown and default-fill today | grep:`web/storage.py` `_deserialize_dataclass` "Field not in dataclass definition, skip" | ✅ |
| `total_grid_charge_kwh` default `0.0` | grep:`home.py` `SummaryStatistics.total_grid_charge_kwh: float = 0.0` | ✅ |
| Type-mismatch pass-through today | task 614 probe: `"battery_config": "big"` loads as str | ✅ |
| Schema step machinery | producer:ι upstream | ✅ |
| Kind loaders, typed summary | producer:ε, γ upstream | ✅ |
| Rejections (missing marker, unknown key, missing required, wrong type) | own-task; each test authors the bad document and observes `StoredRunUnreadable` naming the field | ✅ |

## μ — Integration gate — leaf (C-as-integration-gate)

| Capability asserted | Evidence | Status |
|---|---|---|
| Invariant 4 allow-list achievable | runs SQL only in storage (β, γ, ι, κ upstream); `sqlite3.connect` only in database (α); `RunStorage(` only in app (β, γ) | ✅ |
| B16 end to end | every other label upstream | ✅ |
