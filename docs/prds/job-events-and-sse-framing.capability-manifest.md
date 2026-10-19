# Capability manifest — Job events and SSE framing (S20)

This manifest mechanises G3 (each substrate exists and is **wired**, not merely declared) and G6
(each premise is valid) for every leaf of `docs/prds/job-events-and-sse-framing.md`. Each
capability a signal asserts is bound to evidence, in one of these forms:
- `grep:<file> <symbol>` for substrate on main;
- `producer:<label or task> upstream` for a capability a prerequisite produces;
- `probe:` for a behaviour measured on 2026-10-16;
- `own-task` for what the leaf itself builds.

**Code anchors** were verified against main `1fa8f79` (2026-10-16). Citations are by symbol;
re-locate them at implementation time. The machine-readable twin is
`job-events-and-sse-framing.capability-manifest.yaml`.

**Batch verdict at authoring: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, `producer-downstream` or `producer-extent-short`:
- Every leaf's asserted capability is produced by the leaf itself, by an upstream label (DAG of
  PRD §11), or by an upstream S19 task the lead handed over (806, 814, 819, 822).
- The browser premises the design rests on were probed in Chromium (the locked Playwright's):
  - a normally ended stream reopens after `retry`;
  - `Last-Event-ID` is sent on the reopen;
  - a frame without `id` keeps the last id.
- The type premise was probed under `mypy --strict`: a mismatched payload is rejected.
- Every rejection signal is backed by a mechanism the same leaf builds (G6 branch 4):
  `IllegalJobTransition`, `RunStatusConflict`, and `sse_frame`'s payload check.

One extent finding was resolved at authoring. θ (819) as filed cancels a queued job's future
without setting its cancel flag. β's done-callback needs the flag set first to tell a delete from
a shutdown, because `Future.cancel` runs callbacks before it returns. **β owns that edit** to
`cancel_run`, so the binding is `own-task`, not `producer-extent-short` on 819.

**Delivered-check polarity** was checked on main `1fa8f79` with `git grep -E -c`:
- each `present` pattern has 0 matches today;
- each `absent` pattern has matches today: `["']event: ` 5 in `assistant.py`;
  `X-Accel-Buffering` 2; `status: RunStatus = "completed"` 2; `status="completed"` 2 in `jobs.py`;
  the `JobEvent`/`get_events` family 6; `_FINAL_EVENT_TYPE_BY_STATUS` 2; the api frame/heartbeat
  literals 4; `SSE stream timed out` 1; `data.message || data.error` 1; `new EventSource` 2 in the
  two pages; `JSON.parse` 2 in `parameter-sweep.js`.

`shared.delivered_check_polarity.lint_delivered_checks`, run at `main` with each leaf's declared
files, reports every leaf clean.

No absent-check is satisfied early by an upstream leaf:
- γ empties `api.py` of frames.
- δ's absent-checks target the page scripts and the timeout text, which γ moves into `sse.py`
  unchanged. δ's check names both files.
- δ's check leaves out "Job not found", because that text also answers
  `GET /api/jobs/<id>`'s 404 JSON, which stays.

Re-walk this manifest at decompose: main moves, and 564, 646, 680 and 713 may land first (PRD §6).

## α — One SSE module frames both streams — intermediate (unlocks γ, δ)

| Capability asserted | Evidence | Status |
|---|---|---|
| `sse_frame(event, payload, *, event_id, retry_ms)` with `SseEvent[P]` | own-task; probe 2026-10-16 (mypy --strict rejects a mismatched payload; bound `DataclassInstance` rejects a non-dataclass) | PASS |
| One `data:` line per frame | probe: `json.dumps` escapes `\n`; `tests/_sse.parse_sse_events` refuses two `data` lines, so B1 would catch a regression | PASS |
| `event_stream(frames)` serves both endpoints | own-task; today's two copies: `assistant._event_stream`, `api.get_job_progress`'s `Response` | PASS |
| Chat frames come from `sse.py` after 713 | producer: 713 upstream (`assistant._sse_frame`, typed reply events on its branch) | PASS |
| `assistant.js` shows the notice for `failed` | own-task; e2e test with a chat answer faked by `sse_frame(CHAT_FAILED, …)` | PASS |
| `tests/_sse.SseFrame` reads `id` and `retry` | own-task (extends the existing reader `tests/_sse.py`) | PASS |

## β — One job state table and writer; every job ends; run status follows the job — leaf (high)

| Capability asserted | Evidence | Status |
|---|---|---|
| `JobManager(storage)` and `RunStorage.create_run`/`mark_run_failed`/`fail_interrupted_runs` | producer: 806 upstream | PASS |
| `JobStatus` with terminal `'cancelled'`, per-job lock, cancel flag | producer: 819 upstream | PASS |
| `cancel_run` sets the flag before `Future.cancel()` | own-task (β edits θ's `cancel_run`); stdlib `Future.cancel` → `_invoke_callbacks` runs callbacks before returning | PASS |
| A shutdown-dropped job reaches the done-callback | stdlib `ThreadPoolExecutor.shutdown(cancel_futures=True)` → `work_item.future.cancel()` | PASS |
| `check_job_transition` refuses a move out of a terminal status (B6) | own-task; rejection authored by B6 with `("completed", "failed")` and each terminal status | PASS |
| `mark_run_failed` refuses a completed row (B7) | own-task (conditional update raising `RunStatusConflict`) | PASS |
| A failing completion write ends `failed`, never `completed` then `failed` (B5) | own-task; a `RunStorage` subclass injected at `JobManager(storage)` (806's constructor) | PASS |
| Seeding a completed or failed run in tests | producer: 425 upstream (through 806); β edits `tests/_web_runs.py` to mark status through the lifecycle methods | PASS |
| Run status readable through the product | grep: `api.history_get_run` → `RunStorage.run_record` (wired) | PASS |

## γ — Versioned snapshots replace the drained queue — leaf (unlocks δ)

| Capability asserted | Evidence | Status |
|---|---|---|
| Version bumped on every transition | producer: β upstream (the one writer) | PASS |
| `job_snapshot` reads without mutating; two streams see the same frames (B8) | own-task; non-destructive by construction (no queue left) | PASS |
| Resume from `Last-Event-ID` (B9) | own-task server side; probe: Chromium sends `Last-Event-ID` on reopen | PASS |
| The late-subscriber frame equals a live stream's last frame (B10) | own-task; both come from one `sse_frame` call on the same snapshot (identity) | PASS |
| Frames framed by `sse_frame` and served by `event_stream` | producer: α upstream | PASS |
| Data keys `== fields(JobState)` | identity: `asdict` of a flat frozen dataclass | PASS |
| Pages keep working on the pre-δ names | grep: `progress-tracker.js` and `parameter-sweep.js` read only `progress_pct`, `current_step`, `message`, `status` and `run_id`, all `JobState` fields | PASS |

## δ — The job stream's vocabulary, `timeout`, one browser reader — leaf, integration gate (high)

| Capability asserted | Evidence | Status |
|---|---|---|
| Chromium reopens after `timeout` and sends `Last-Event-ID` (B14) | probe 2026-10-16: native `error` (no data, readyState 0), reopen 316 ms after `retry: 300`, `Last-Event-ID: 5` | PASS |
| A frame without `id` keeps the browser's last id | same probe: `lastEventId` stayed `"5"` across the `timeout` frame | PASS |
| `cancelled` frames exist to send (B13) | producer: 819 (terminal `'cancelled'`) through β, upstream | PASS |
| Snapshot resume and non-draining streams | producer: γ upstream | PASS |
| e2e fakes built with the server's encoder | producer: α upstream (`sse_frame`); `tests/e2e/_job_requests.py` already centralises the fakes (`sse_event`) | PASS |
| The live server serves a held job's stream with a short policy | grep: `tests/e2e/conftest.py` builds `make_server(..., threaded=True)` and swaps `_e2e_app.extensions["job_manager"]`; δ swaps the policy the same way | PASS |
| The tracker's results link | producer: 814 upstream (the submit response's `results_url`) | PASS |
| Transport drops still show reconnecting and give up after 60 s | grep: `job-progress-stream.js::JOB_PROGRESS_RECONNECT_LIMIT_MS` and task 648's e2e tests in `test_progress_tracker.py`/`test_parameter_sweep.py` (wired; δ keeps them green) | PASS |
| B14's waits | numeric: about 2 s per timeout cycle at `retry_ms=1000` and `limit_seconds=1`; the leaf's waits allow 5 s for two cycles (PRD §14) | PASS |
