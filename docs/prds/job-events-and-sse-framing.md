# PRD — Job events and SSE framing (S20)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream **S20**, wave 2, size M,
  risk medium, upstream stream S19. Findings record: `plans/review-all-solar_challenge-20261013.json`
  (`x_finding_run = review-all-solar_challenge-20261013`).
- **Status:** authored 2026-10-16, not yet filed. Decompose waits for the lead to hand over the ids
  this batch depends on (806, 814, 819 and 822, handed over) and to rule on §6's questions Q1–Q4.
- **Code anchors:** verified against main `1fa8f79` (2026-10-16). Main moves fast: this PRD cites
  symbols, not line numbers, and implementers should re-locate them at implementation time. The
  findings record's anchors are at `7dfea36`; since then tasks 641, 648, 684 and 701 changed
  `api.py`, `jobs.py`, `assistant.py`, `progress-tracker.js` and `parameter-sweep.js`, and added
  `static/js/job-progress-stream.js`. §2 re-measures every finding on `1fa8f79`.
- **Binding rulings:** **D21** (the server's failure event is renamed `failed` with `id` and `retry`
  fields; one SSE framing module serves `assistant.chat` and `api.get_job_progress`; the
  600-second stream limit ends with a named `timeout` event the browser treats as a reconnect) and
  **D29** (no name this stream touches is on the frozen surface, so nothing waits for S29). D33
  (deleting a run cancels its job) reaches this stream through S19 θ.
- **Upstream (S19, filed):** 805 α `Database`, 806 β `JobManager(storage)` and the `jobs` table
  retired, 814 ε run kinds and `/results/<run_id>`, 819 θ deletion cancels the job (terminal
  `'cancelled'`), 822 κ stored-run format version. The job state table and its transitions build
  on 806 and 819.
- **Owner seam (G4):** the SSE frame and the event payload types: one web module, `web/sse.py`.
  Readers: `assistant.js`, `job-progress-stream.js` (which `progress-tracker.js` and
  `parameter-sweep.js` call).
- **Approach:** **B + H**. A contract (§4) and a two-way boundary-test sketch (§10). The seam is a
  server-to-browser protocol written in two languages, and its history is a bug cluster: tasks
  533, 564, 638, 641, 648 and 649 each fixed one side of it.

---

## 1. Goal

After this stream, a dashboard user sees these behaviours:

1. **A long job is never shown as failed because its stream got old.** At 600 seconds the progress
   stream ends with a `timeout` event. The browser reopens it, and the tracker keeps following the
   job without showing "Simulation Failed" or "Reconnecting to server...". The reopened stream
   resumes from the last state the page saw. Today a 70-minute 100-home fleet is shown as failed
   at minute 10.
2. **A failed job, a dropped connection, a cancelled job and an unknown job each look different.**
   A failed job shows its message. A dropped connection shows "Reconnecting to server...", as
   since task 648. A job whose run was deleted shows "Cancelled". A job the server no longer
   tracks, for example after a restart, shows that, not a failure.
3. **Every page following a job sees the same states.** A second tab, a reload, or the sweep page
   and the results page following one job, all receive every state and the same final frame. No
   stream consumes what another needed.
4. **A job always ends.** A job dropped by a server shutdown, or one whose runner raised past its
   own error handling, reports `failed` with a message. It no longer stays `queued` or `running`
   until it ages out. A run whose results were saved is never later reported failed.
5. **The assistant's failure notice still shows.** The chat stream's failure event is `failed`, and
   the assistant page shows its message as before.

Structurally:
- `web/sse.py` is the one module that frames SSE and sets the event-stream response headers, and
  it declares each event's single payload type.
- `jobs.py` holds one job state table, and one writer refuses any transition the table does not
  allow.
- A job's run row follows the job: `RunStorage.save_*` no longer write a status.
- The browser has one reader of the job stream.

## 2. Background — re-measured at `1fa8f79`

- **Hand-written frames (fk-066e5cb461f7, re-measured):** 9 code sites. Five are in
  `assistant.py`: `_error_frame`, `_DONE_FRAME`, the delta frame, the tool frame and the cap-notice
  delta. Four are in `api.py`: `_job_event_frame`, the timeout literal, the "Job not found" literal
  and `:heartbeat`. The review counted 10; task 641 routed the late-subscriber frame through
  `_job_event_frame`. There are still 2 copies of the response headers (`assistant._event_stream`
  and `api.get_job_progress`'s `Response`) and 3 error payload shapes: `{message}`,
  `{status, message}` and `{error}`. Task 713, in the merge queue, gives `assistant.py` one local
  `_sse_frame(event, payload)` and typed reply events, so after 713 the assistant has one encoder
  and the api has another.
- **The progress stream (fk-7eb56fda0b1c, still present):**
  - `api._job_event_payload` sends 4, 5 and 2 keys for `progress`, `complete` and `error`.
  - The timeout and "Job not found" frames are `{error}`.
  - `JobEvent.type` restates `JobState.status`, and `api._FINAL_EVENT_TYPE_BY_STATUS` derives it a
    third time.
  - `progress-tracker.js::_onFailed` reads `data.message || data.error`, and `parameter-sweep.js`
    wraps each `JSON.parse` in an empty `catch`.
  - Since task 648, `job-progress-stream.js::onJobProgressStreamErrors` tells the server's `error`
    from the browser's native one by whether the event carries data. That works around the name
    collision; it does not remove it.
- **The drained queue (fk-4540d657bff6, still present):** `JobManager.get_events` copies and clears
  `_TrackedJob.events` (a `deque(maxlen=100)`). `get_job_progress` keeps the compensating terminal
  branch for a stream whose events another stream drained. Task 680 (pending, branch ready)
  renames the method `take_events`.
- **The lifecycle (fk-484952247bb6, still present):**
  - `_finish_job` stamps `finished_at` whatever the status.
  - `_report_state` overwrites the state unconditionally.
  - `save_home_run`/`save_fleet_run` write the run as `'completed'` inside `work_fn`, before the job
    reports completion.
  - Task 646 (in the merge queue) makes the done-callback fail a job whose runner raised. It
    deliberately leaves a job that shutdown dropped in its queued state.
  - After 806 lands, the `jobs` row is gone. Of the four facts the finding lists, three remain:
    `JobState.status`, `finished_at` and the `runs` row status.
- **The limit (fk-0097b5aaa45c, still present on main):** `max_duration = 600` ends the stream with
  `event: error` `{error: "SSE stream timed out after 10 minutes"}`. Task 564's branch (pending,
  unmerged) removes the limit instead and adds a briefing line that forbids re-adding one. That
  contradicts D21 (§6 Q1).
- **Browser behaviour, probed 2026-10-16** with the locked Playwright's Chromium against a stub
  server (§7):
  - A stream the server ends normally fires a native `error` with no data, `readyState`
    CONNECTING.
  - The browser reopens it after the `retry` delay (300 ms set, 316 ms observed) and sends
    `Last-Event-ID`.
  - A frame without an `id` field leaves the last event id unchanged.

## 3. Sketch of approach

### 3.1 One SSE module (α, γ, δ)

`web/sse.py` holds everything the server says on an event stream:
- `sse_frame(event, payload, *, event_id=None, retry_ms=None)`, the only encoder;
- `HEARTBEAT`;
- `event_stream(frames)`, the only builder of a `text/event-stream` response;
- the event catalogue, in which each event is an `SseEvent[P]` binding its name to one payload type;
- `JobStreamPolicy` and `job_progress_frames`, the job stream itself.

`assistant.chat` and `api.get_job_progress` frame nothing themselves. The encoder emits one `data:`
line, because `json.dumps` escapes newlines inside strings (probed).

### 3.2 The event vocabulary (δ; D21)

| Stream | Event | Payload | `id` | `retry` | Browser does |
|---|---|---|---|---|---|
| job | `progress` | `JobState` (status `queued` or `running`) | snapshot version | policy | update |
| job | `completed` | `JobState` | version | policy | update, close |
| job | `failed` | `JobState` | version | policy | show the message, close |
| job | `cancelled` | `JobState` | version | policy | show "Cancelled", close |
| job | `timeout` | `StreamTimedOut(limit_seconds)` | none: the last id stands | policy | let the browser reopen quietly |
| job | `untracked` | `JobUntracked(job_id)` | none | policy | show "no longer tracked", close |
| chat | `delta` | `ChatDelta(text)` | none | none | append |
| chat | `tool` | `ChatToolCall(name)` | none | none | — |
| chat | `done` | `ChatDone()` | none | none | — |
| chat | `failed` | `ChatFailed(message)` | none | none | show the notice |

- The job stream's event is a function of the job's status: `JOB_STATE_EVENTS[status]`. Each
  terminal status names its own event, so `complete` becomes `completed`. `JobEvent` and its
  `type` field go.
- Every job-state frame carries the whole `JobState`, so every frame has the same keys.
- `id` and `retry` go on the job stream, the only stream the browser reopens. The chat is read with
  `fetch` and never reopened, so its frames carry neither.

### 3.3 Snapshots, not a queue (γ)

- `_TrackedJob` keeps a `JobSnapshot(version, state)`. The transition writer replaces it and bumps
  the version under the manager lock.
- `JobManager.job_snapshot(job_id)` reads it without changing anything. `get_events`, the `events`
  deque, `JobEvent` and `JobEventType` are deleted.
- Each stream keeps its own cursor, starting at the request's `Last-Event-ID` (absent → none).
- On each poll the stream sends the current state if its version is newer than the cursor. A stream
  ends with exactly one ending frame:
  - the terminal state's frame, always sent even when its version equals the cursor, so a reopened
    stream on a finished job never loops;
  - `timeout`;
  - or `untracked`.
- States between two polls collapse into the newest one, which is all the pages read.
- The late-subscriber branch and `_FINAL_EVENT_TYPE_BY_STATUS` are deleted.

### 3.4 One job state table, one writer (β)

```
queued  → running | failed | cancelled
running → running | completed | failed | cancelled      (running → running is a progress update)
completed, failed, cancelled → (none: terminal)
```

- `LEGAL_JOB_TRANSITIONS` states this table, and `TERMINAL_JOB_STATUSES` is derived from it.
- `check_job_transition(job_id, run_id, from_status, to_status)` raises `IllegalJobTransition`
  naming all four.
- The manager has **one** writer of job state, which calls `check_job_transition`. It stamps
  `finished_at` exactly when the new status is terminal. `_report_state`'s unconditional overwrite
  and `_finish_job`'s unconditional stamp go.

**Terminal at the executor boundary.** The future's done-callback makes the job terminal before it
stops counting it as unfinished. It decides in this order:
1. Already terminal: nothing to do.
2. The job's cancel flag is set: `cancelled`. `Future.cancel()` runs the callback before it returns,
   so `cancel_run` must set the flag before it cancels a queued job's future. θ (819) as filed
   cancels a queued future without setting the flag, so β changes `cancel_run` to set it first.
3. The future was cancelled by `shutdown(cancel_futures=True)`: `failed`, "Dropped: the server shut
   down before the job ran".
4. The future holds an exception: `failed` with its message, logged at ERROR with the traceback
   and naming the job and run.
5. The runner returned without reaching a terminal state: `failed`, logged as a defect.

This subsumes task 646's callback and reverses its choice to leave a dropped job queued. A dropped
job will never run, so `queued` would claim a liveness it does not have.

**Run status follows the job.**
- `RunStorage.save_home_run`/`save_fleet_run` lose their `status` parameter. They write the run's
  data, insert a new row as `'running'`, and leave an existing row's `status`, `completed_at` and
  `error_message` alone.
- Only the lifecycle methods write run status: `create_run` writes `'running'` (806), and the new
  `mark_run_completed(run_id)`, `mark_run_failed` (806, tightened here) and
  `fail_interrupted_runs` (806) move it on.
- Each moves a row from `'running'` only. A row in another status raises `RunStatusConflict`
  naming the run, the status found and the status wanted.
- An absent row is a no-op for `mark_run_failed`, because a deleted run stays deleted. For
  `mark_run_completed` an absent row raises, because completing a deleted run breaks S19's C8.

The writer orders the durable write against the in-memory one:
- **Completion: row first, then memory.** A job is reported `completed` only after its run row
  reads `completed`. The save, `mark_run_completed` and the in-memory transition run under S19 θ's
  per-job lock. If `mark_run_completed` raises, the job goes to `failed` and its row is failed.
- **Failure: memory always, row best-effort.** A failure is always reported. A row write that fails
  is logged, naming the job and run, and the next start's `fail_interrupted_runs` is the backstop.
- **Cancellation writes no row**, because the row is already gone (θ).

The `completed → failed` reversal the finding describes cannot happen. The table refuses it in
memory, and `mark_run_failed` refuses it in the row.

### 3.5 The limit and the reconnect (δ; D21)

- `JobStreamPolicy` holds `limit_seconds=600`, `heartbeat_seconds=2`, `retry_ms`, `clock` and
  `sleep`. It is built at the composition root and read by the route, so tests drive it with a fake
  clock or a one-second real limit. No test patches `api.time`.
- At the limit, the stream sends `timeout` with `retry` and no `id`, and ends. The browser then
  fires its native `error` and reopens the stream after `retry` ms with `Last-Event-ID` (probed).
- `job-progress-stream.js` is the job stream's only reader: `followJobProgress(jobId, {onState,
  onEnd, onReconnecting, onLost})`.
  - It opens the `EventSource`, parses each frame once, and hands the full `JobState` to `onState`.
  - On a terminal state or `untracked` it closes the stream and calls `onEnd` with the ending.
  - A terminal frame whose state it cannot read ends in `onLost`, as a stream the browser gives up
    does, and its parse error is rethrown for the console.
  - On `timeout` it marks the next break as expected. That break shows no reconnecting indicator,
    but task 648's give-up timer is still armed, so a server gone during the reopen still ends in
    `onLost`.
  - A native `error` is only ever the transport.
- `progress-tracker.js` and `parameter-sweep.js` pass callbacks to the reader. They open no
  `EventSource` and parse no frame. `data.message || data.error` and the sweep's empty `catch`es
  around `JSON.parse` go.

### 3.6 Chat (α)

- After task 713, `assistant.py`'s `_sse_frame`, `_error_frame`, `_DONE_FRAME` and `_event_stream`
  move into `sse.py` as `sse_frame` with the chat catalogue and `event_stream`.
- The failure event is `failed` with `ChatFailed(message)`. `assistant.js` reads `failed`.
- `api.get_job_progress` builds its response through `event_stream` in α too, so the header policy
  has one copy from α on.

## 4. Contract (B + H)

Signatures are normative in shape. Names in *italics* are tactical; an implementer may rename them
if every reference moves too. The capitalised constants, `sse_frame`, `event_stream`,
`job_progress_frames`, `job_snapshot`, `check_job_transition`, `IllegalJobTransition`,
`mark_run_completed` and `RunStatusConflict` are named by the capability manifest's checks, so they
are normative.

```python
# web/sse.py — the server's event streams. Imports from web: jobs (JobState, JobStatus, JobSnapshot,
# TERMINAL_JOB_STATUSES). No other web module writes an SSE frame or a text/event-stream response.
P = TypeVar("P", bound="DataclassInstance")
@dataclass(frozen=True)
class SseEvent(Generic[P]):
    name: str                      # __post_init__ refuses "" and any whitespace or ':'
    payload_type: type[P]
def sse_frame(event: SseEvent[P], payload: P, *, event_id: int | None = None, retry_ms: int | None = None) -> str: ...
    # "event: {name}\n" ["id: {event_id}\n"] ["retry: {retry_ms}\n"] "data: {json.dumps(asdict(payload))}\n\n";
    # raises TypeError when payload is not an instance of event.payload_type (mypy rejects it first)
HEARTBEAT: str = ":heartbeat\n\n"
def event_stream(frames: Iterable[str]) -> Response: ...   # 200, text/event-stream, Cache-Control: no-cache, X-Accel-Buffering: no

@dataclass(frozen=True) class ChatDelta: text: str
@dataclass(frozen=True) class ChatToolCall: name: str
@dataclass(frozen=True) class ChatDone: pass
@dataclass(frozen=True) class ChatFailed: message: str
CHAT_DELTA: SseEvent[ChatDelta]; CHAT_TOOL: SseEvent[ChatToolCall]; CHAT_DONE: SseEvent[ChatDone]; CHAT_FAILED: SseEvent[ChatFailed]

@dataclass(frozen=True) class StreamTimedOut: limit_seconds: float
@dataclass(frozen=True) class JobUntracked: job_id: str
JOB_PROGRESS, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED: SseEvent[JobState]   # names: progress, completed, failed, cancelled
JOB_STREAM_TIMED_OUT: SseEvent[StreamTimedOut]                               # name: timeout
JOB_UNTRACKED: SseEvent[JobUntracked]                                       # name: untracked
JOB_STATE_EVENTS: Mapping[JobStatus, SseEvent[JobState]]                    # keys == get_args(JobStatus)
@dataclass(frozen=True)
class JobStreamPolicy:
    limit_seconds: float = 600.0
    heartbeat_seconds: float = 2.0
    retry_ms: int = 1000                                   # §13 Q1
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
def job_progress_frames(job_snapshot: Callable[[str], JobSnapshot | None], job_id: str, *,
                        last_event_id: int | None, policy: JobStreamPolicy) -> Iterator[str]: ...
    # polls job_snapshot(job_id); job_id is the id JOB_UNTRACKED's JobUntracked names

# web/jobs.py — after S19 β (806) and θ (819)
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]       # θ
LEGAL_JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]]                    # keys == get_args(JobStatus)
TERMINAL_JOB_STATUSES: frozenset[JobStatus]                                        # derived: no exits
class IllegalJobTransition(RuntimeError): job_id: str; run_id: str; from_status: JobStatus; to_status: JobStatus
def check_job_transition(job_id: str, run_id: str, from_status: JobStatus, to_status: JobStatus) -> None: ...
@dataclass(frozen=True)
class JobSnapshot: version: int; state: JobState                                   # γ
class JobManager:
    def job_state(self, job_id: str) -> JobState | None: ...                       # unchanged
    def job_snapshot(self, job_id: str) -> JobSnapshot | None: ...                 # γ; never mutates
    # deleted: get_events (or take_events), JobEvent, JobEventType, _TrackedJob.events

# web/storage.py — after S19
class RunStatusConflict(Exception): run_id: str; found: RunStatus | None; wanted: RunStatus
class RunStorage:
    def save_home_run(self, ...) -> None: ...      # no status parameter; new row 'running'; keeps status, completed_at, error_message
    def save_fleet_run(self, ...) -> None: ...     # likewise
    def mark_run_completed(self, run_id: str) -> None: ...         # running → completed, stamps completed_at
    def mark_run_failed(self, run_id: str, message: str) -> None: ...   # running → failed; absent row: no-op
```

`SseEvent` forbids all whitespace in an event name. The test reader `tests/_sse.parse_sse_events`
refuses only leading or trailing whitespace and keeps an inner space as written; its docstring
gives the reason. The difference is deliberate, so do not align the two.

**Invariants (each enforced at the place named):**

| # | Invariant | Enforced by |
|---|---|---|
| J1 | Job status moves only along `LEGAL_JOB_TRANSITIONS`, through one writer; terminal statuses are final; an illegal move raises `IllegalJobTransition` naming job, run, from and to | `check_job_transition` in the writer (β); table test |
| J2 | Every job the executor is done with is terminal before it stops counting as unfinished; `finished_at` is stamped by, and only by, a transition into a terminal status | done-callback order (β) |
| J3 | A job reports `completed` only after its run row reads `completed`; a failure is always reported in memory | writer order (β) |
| J4 | Only RunStorage's lifecycle methods write run status, each from `'running'` only | `save_*` signatures; conditional updates raising `RunStatusConflict` (β) |
| J5 | A job's snapshot version strictly increases with each transition; reading a snapshot changes nothing | the writer; `job_snapshot` (γ) |
| J6 | Every job-state frame is `JOB_STATE_EVENTS[status]` with data keys `== fields(JobState)`, `id` = version, `retry` = the policy's | `job_progress_frames` (γ, δ); frame-keys test |
| J7 | A job stream sends the current state on open unless `Last-Event-ID` equals its version, and ends with exactly one ending frame: terminal state (always sent), `timeout` or `untracked` | `job_progress_frames` (γ, δ) |
| J8 | Each event name has one payload type per stream; no web module but `sse.py` writes a frame or an event-stream response | `SseEvent[P]` + mypy + `sse_frame`'s check (α); manifest greps |
| J9 | `job-progress-stream.js` is the only code that opens a job `EventSource` and parses its frames; a native `error` means the transport only; the break after `timeout` reopens without the indicator | δ; e2e (B14–B16) |

## 5. Resolved design decisions

- **D-S20-1 Event names (reading of D21).** Each terminal job status names its own event:
  `completed`, `failed`, `cancelled`. `complete` becomes `completed`, so one mapping
  (`JOB_STATE_EVENTS`) holds the whole rule and no second spelling exists. The chat's `error`
  becomes `failed` too. That gives the server one name for "this stream's work failed", and the
  browser no `error` that could be mistaken for its own.
- **D-S20-2 `id` and `retry` (D21).**
  - Every job-state frame carries `id` = the snapshot version, and every job-stream frame carries
    `retry`.
  - The `timeout` and `untracked` frames carry no `id`, so the browser's last id stands and a
    reopened stream resumes from it (probed).
  - Chat frames carry neither, because a `fetch` reader never reopens.
- **D-S20-3 Full-state payloads.** Every job-state frame carries the full `JobState`, which is the
  finding's proposal. `JobEvent.type` is deleted, because it restated the status.
- **D-S20-4 Snapshots replace the queue** (fk-4540d657bff6's proposal). States between polls
  collapse into the newest one, which is what the pages read. Waking streams on change instead of
  polling every 2 s is out of scope (§12).
- **D-S20-5 The limit (D21).** The limit stays at 600 s per response and ends with `timeout`. The
  browser reopens natively, and the reader hides the indicator for that one break. Task 564's
  branch takes the other route, no limit; D21 decided against it, and §6 Q1 returns 564 to the
  lead.
- **D-S20-6 `untracked`.** It is its own event. The reader closes the stream, because the server
  would answer the same again, and both pages show "no longer tracked" as a state distinct from
  failed (heuristic 12).
- **D-S20-7 One table, one writer, terminal at the boundary** (§3.4). `check_job_transition` is a
  public function. The table is then exercised directly with real inputs, and no test reaches the
  manager's private writer.
- **D-S20-8 Run status follows the job** (§3.4). It closes the stream row's deletable "the save
  upsert writing 'completed' before the record". S19 §8 assigned `mark_run_completed` to this
  stream. Test seeding goes through `tests/_web_runs.py`'s helpers (task 425), which mark the
  seeded status through the lifecycle methods.
- **D-S20-9 Module boundaries.** `sse.py` owns framing, the response policy, the catalogue and the
  job-stream generator, the seam the program names. Each stream has one browser reader. The
  JavaScript event-name literals live once in each reader, and the server's catalogue holds the
  names on the Python side. The e2e fakes are built with `sse_frame` from that catalogue, so a
  reader that listens for a name the server never sends fails a behavioural test. A text grep
  across the two languages would only compare strings (G7 `guards-exercise-behaviour`).
- **D-S20-10 The policy is a value at the composition root**, read by the route through a typed
  accessor. It replaces the literal `600` and the `time.time()`/`time.sleep` calls.

## 6. Pre-conditions and the tasks this stream subsumes

**Upstream (the lead handed these ids):** 806 and 819 (β builds on `JobManager(storage)`, the
retired `jobs` table, `JobStatus` in `jobs.py`, the cancel flag and per-job lock, and terminal
`'cancelled'`); 822 (β edits `save_*` after κ's format-version change to them); 814 (δ rewrites the
tracker after ε moved its results link). 805 is upstream of all of them.

**Pre-existing tasks; the lead decides before this batch is filed:**

| Task | Status | Overlap | Proposed disposition |
|---|---|---|---|
| 564 | pending, branch reviewed, not in the merge queue | holds fk-0097b5aaa45c; its branch **removes** the limit and adds a briefing line forbidding one, which contradicts D21 | **cancel as superseded by δ before it is re-dispatched** (Q1). Its keyword-injected `sleep` and its ten-minute test carry over into δ's policy and test |
| 680 | pending, branch ready, not queued | renames `get_events` to `take_events` | cancel as superseded by γ, which deletes the method (Q2). If it lands first, γ deletes `take_events` |
| 646 | in the merge queue | the done-callback fails a job whose runner raised | let it land; β rewrites the callback into the table and reverses its "dropped job stays queued" choice (Q3). No edge |
| 713 | in the merge queue (S22's key fk-ab16fff6f6c3) | splits `chat()`, adds `assistant._sse_frame` | α depends on it |
| 425 | in the merge queue | `tests/_web_runs.py` seeding helpers | β edits the helpers; 806 already depends on 425, so it is upstream through 806 |

**Questions returned to the lead:**
- **Q1 (urgent).** Cancel 564 with `x_superseded_by` δ before it is re-dispatched, and move
  fk-0097b5aaa45c to δ. 564's branch records a measurement worth Leo's eye: werkzeug closes a gone
  client's stream at the next heartbeat write, about 2 s after the client closes its socket, so the
  limit frees no server resource. D21 binds this PRD as ruled. If Leo revisits D21's timeout
  clause in light of 564's measurement, δ loses `timeout` and `JobStreamPolicy.limit_seconds`, and
  the rest of the design stands.
- **Q2.** Cancel 680 with `x_superseded_by` γ, or let it land and have γ delete `take_events`.
- **Q3.** Let 646 land; β subsumes it. No edge.
- **Q4.** Confirm the reading of D21 in D-S20-1 and D-S20-2:
  - the chat's failure event is also `failed`;
  - `id` and `retry` go on the job stream only;
  - `complete` becomes `completed`.

## 7. Substrate verification (G3)

| Assumed capability | Evidence | Status |
|---|---|---|
| EventSource reopens a normally ended 200 stream after `retry` ms | probe 2026-10-16, locked Playwright Chromium, stub server: native `error` (no data, readyState 0), reopen 316 ms after `retry: 300` | ✅ |
| `Last-Event-ID` sent on reopen; a frame without `id` keeps the last id | same probe: `timeout` frame with no `id` → `lastEventId` stayed `"5"`; reopen sent `Last-Event-ID: 5` | ✅ |
| `SseEvent[P]` makes mypy reject a wrong payload type | probe 2026-10-16, mypy --strict: `sse_frame(CHAT_DELTA, JobState(...))` → "Cannot infer value of type parameter"; the method form → `arg-type`; a non-dataclass `P` → `type-var` | ✅ |
| `json.dumps` emits one line for any payload | probe: a message with `\n` encodes as `\\n` in one `data:` line | ✅ |
| `shutdown(cancel_futures=True)` runs a cancelled future's done-callbacks | stdlib `concurrent.futures.thread`: `work_item.future.cancel()` → `Future._invoke_callbacks` | ✅ |
| `Future.cancelled()` / `Future.exception()` in the done-callback | stdlib; task 646's branch reads both | ✅ |
| `JobManager(storage)`, `mark_run_failed`, `create_run`, `fail_interrupted_runs` | **producer: 806** (upstream) | ✅ queued |
| cancel flag, per-job lock around check-and-save, terminal `'cancelled'` | **producer: 819** (upstream). θ as filed cancels a queued future without setting the flag; β sets the flag before `Future.cancel()` in `cancel_run`, which is how the callback tells a delete from a shutdown (`Future.cancel` runs callbacks before returning: stdlib `Future.cancel` → `_invoke_callbacks`) | ✅ queued; β's own edit |
| `tests/_web_runs.store_home_run`/`store_fleet_run` | task 425 branch (queued for merge; upstream through 806) | ✅ queued |
| Flask `request.headers.get("Last-Event-ID")` | Flask/werkzeug `Headers` | ✅ |
| e2e live server serves concurrent streams | `tests/e2e/conftest.py::live_server` uses `make_server(..., threaded=True)` | ✅ wired |
| e2e can swap app collaborators | `tests/e2e/conftest.py` swaps `_e2e_app.extensions["job_manager"]` | ✅ wired (δ swaps the policy the same way) |

No novel syntax or service is assumed.

## 8. Cross-PRD relationship (G4)

| Other stream | Direction | Seam mechanism | Owner | Status / ask |
|---|---|---|---|---|
| S19 Run store (`run-store-one-owner.md`) | S20 consumes and extends | `JobManager(storage)`, `JobStatus` with `'cancelled'`, the cancel flag and per-job lock (806, 819). S20 adds `mark_run_completed` and `RunStatusConflict`, makes `mark_run_failed` conditional, and removes `save_*`'s `status`. All the SQL stays in `storage.py`, so invariant 4 holds as written | S19 the store; S20 the transitions (S19 §8 row) | edges β→806, 819, 822; δ→814. β changes θ's `cancel_run` to set the cancel flag before `Future.cancel()` (line returned, informational) |
| S22 Assistant facts / task 713 | shares `assistant.py` | after 713, `chat()`'s frames come from `sse.py`; 713's typed reply events map one-to-one onto the chat catalogue | S20 the frames; S22 the turn structure | α→713 |
| S16 Fleet execution policy | S16 consumes | JobManager's fleet runner reports progress through the job's progress callback, i.e. through S20's writer, and S16's `FleetRunner` sink never writes job state itself. `JobStreamPolicy` is one more collaborator `create_app` builds; S16's injection form carries it if S16 lands first | S16 the runner and `create_app` injection; S20 the writer and the policy | cross-reference line |
| S17 Request boundary | S17 moves | the policy accessor sits beside `get_job_manager` and moves with it | S17 | file overlap in `shared.py` |
| S21 Charts (`chart-panels-and-theme-tokens.md`) | S21 η consumes | η reads a finished point's `run_id` from the completed event. After δ that is `JobState.run_id`, handed to `parameter-sweep.js` by the reader's `onEnd` | S20 the event; S21 the chart post | S21's table already lists this file overlap; cross-reference line: `complete` → `completed` |
| S18 / S26 | share | `parameter-sweep.js` and `sweep.html` | — | file overlap only |
| S29 Surface bump | none | no `solar_challenge.web` name is on the frozen surface (checked: `tests/_surface_forms.py`, `__init__._SYMBOL_MODULE`) | — | no held leaf (D29) |

There is no reciprocal "the other owns it" pair: every row names one owner.

## 9. G5 — why B + H

- **Mechanism count:** about 14 (the catalogue, the encoder, the response policy, the policy value,
  the job stream generator, snapshots, the transition table, the writer, the executor boundary,
  `mark_run_completed`, conditional run-status writes, the browser reader, and two page
  consumers).
- **Load-bearing seam:** a cross-language protocol. Six earlier tasks each fixed one side of it,
  and only an e2e run catches a half edit (fk-066e5cb461f7's `next_change`).
- **Blast radius:** about 6 Python modules, 4 scripts and a template in one package, and both
  directions of the HTTP boundary.

The contract (§4) states the protocol once. The boundary tests (§10) face the producer (frames,
transitions, run rows) and the consumers (the two pages and the assistant page, in a real browser).

## 10. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) | Side | Leaf |
|---|---|---|---|---|---|
| B1 | Frame round trip | each catalogue event with a sample payload | `tests/_sse.parse_sse_events` (extended with `id` and `retry`) returns the name, the payload as a dict, the id and the retry `sse_frame` was given | both | α |
| B2 | Chat failure | no `ANTHROPIC_API_KEY` | `POST /assistant/chat` answers one frame, `failed` `{message}`; e2e: the assistant page, its chat answer faked with `sse_frame(CHAT_FAILED, …)`, shows the notice | both | α |
| B3 | One header policy | — | both endpoints answer `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` | producer | α |
| B4 | Shutdown drops a queued job | `max_workers=1`, job A blocked, job B queued | after `shutdown()`, B reports `failed` naming the shutdown; B's run reads `failed` in `GET /api/history/runs/<id>`; after release every job is terminal | producer | β |
| B5 | Completion cannot be recorded | storage whose `mark_run_completed` raises | `GET /api/jobs/<id>` reports `failed` with that error, and the run reads `failed`. It never reads `completed` then `failed` | both | β |
| B6 | Failure after a terminal state | `check_job_transition(j, r, "completed", "failed")`, and for each terminal status | raises `IllegalJobTransition` naming j, r, both statuses; `LEGAL_JOB_TRANSITIONS` keys `== get_args(JobStatus)` and terminal sets are empty | producer | β |
| B7 | A run row moves only from running | `mark_run_failed` on a completed run | raises `RunStatusConflict` naming the run, `completed` and `failed`; the row still reads `completed` | producer | β |
| B8 | Two subscribers | two streams on one running job | each receives every state the job reports after it opened, with the same ids, and ends with the same terminal frame; data keys `== fields(JobState)` | both | γ |
| B9 | Resume | a running job at version n | a stream opened with `Last-Event-ID: n` sends no state frame until version n+1; one opened with n-1 sends version n first | producer | γ |
| B10 | Late subscriber | a finished job | a new stream gets the terminal frame byte for byte as a live stream ended with, and nothing else | producer | γ |
| B11 | Timeout | policy with a fake clock past `limit_seconds`, job running | the stream's last frame is `timeout` `{limit_seconds}` with `retry` and no `id`; `GET /api/jobs/<id>` still reports `running` | producer | δ |
| B12 | Untracked | an id no manager tracks | one frame, `untracked` `{job_id}`, and the response ends | producer | δ |
| B13 | Failed and cancelled | a failing fake; a run deleted while its job runs (θ) | `failed` and `cancelled` frames carry the full `JobState` with `id` and `retry` | producer | δ |
| B14 | Timeout in the browser | e2e live server, policy `limit_seconds=1`, held job | the tracker follows the job through at least two timeouts, never shows "Simulation Failed", shows no "Reconnecting to server..." once each reopen lands, and shows the results link once the job is released | both | δ |
| B15 | Endings in the browser | e2e fakes built with `sse_frame` | `failed` shows the job's message; `cancelled` shows "Cancelled"; `untracked` shows its own text; a final state the page cannot read shows the run lost, not running; a dropped connection still shows reconnecting, then the outcome (task 648's tests stay green) | consumer | δ |
| B16 | Sweep | e2e, two points; point 1's stream times out once, point 2 fails | row 1 keeps `running` through the timeout and fetches its results on `completed`; row 2 shows `failed`; the page then draws its chart | consumer | δ |

The tests go through public seams only: HTTP routes, `JobManager`'s public methods,
`check_job_transition`, `RunStorage`, `sse.py`'s public functions and a real browser. The storage
fakes of B5 subclass `RunStorage` at the `JobManager(storage)` constructor seam. No test reaches a
private name.

## 11. Decomposition plan

Every leaf carries `metadata.x_finding_key` (list), `x_finding_run =
"review-all-solar_challenge-20261013"`, `source = "review-all"`, `priority` = the highest severity
among its keys, and file-level `metadata.files`. Every leaf runs the verify suite and `mypy
--strict`. A leaf that edits a template or script:
- updates the e2e tests that assert its behaviour;
- runs `pytest tests/e2e -m 'not slow'` for the touched files locally;
- rebuilds `static/dist/style.css` if a class token changed (CLAUDE.md).

#### α — One SSE module frames both streams; the chat's failure event is `failed`
- **Keys:** fk-066e5cb461f7 · **priority:** low
- **Modules:**
  - `web/sse.py` (new: `SseEvent`, `sse_frame`, `HEARTBEAT`, `event_stream`, the chat catalogue);
  - `web/assistant.py` (chat frames and response through `sse.py`; `_sse_frame`, `_error_frame`,
    `_DONE_FRAME` and `_event_stream` deleted);
  - `web/api.py` (`get_job_progress`'s response through `event_stream`);
  - `static/js/assistant.js` (reads `failed`);
  - `tests/_sse.py` (`SseFrame` gains `id` and `retry`), `tests/unit/test_sse_helper.py`, a new
    `tests/unit/test_web_sse.py`, `tests/unit/web_assistant/test_chat.py` and
    `tests/unit/web_api/test_jobs.py` (header tests);
  - a new e2e test for the assistant page's failure notice.
- **Signal (leaf):** B1, B2, B3. `assistant.py` contains no frame literal and no event-stream
  `Response`, and `X-Accel-Buffering` appears only in `sse.py`.
- **Prereqs:** out of batch: 713.

#### β — One job state table and writer; every job ends; run status follows the job
- **Keys:** fk-484952247bb6 (**high**) · **priority:** high
- **Modules:**
  - `web/jobs.py` (`LEGAL_JOB_TRANSITIONS`, `TERMINAL_JOB_STATUSES`, `check_job_transition`,
    `IllegalJobTransition`, the one writer, the done-callback order of §3.4, `finished_at` at the
    terminal transition, the runner's completion under θ's lock, and `cancel_run` setting the
    cancel flag before it cancels a queued future);
  - `web/storage.py` (`mark_run_completed`, `RunStatusConflict`, conditional `mark_run_failed`,
    `save_*` without `status`);
  - `tests/_web_runs.py` (seeded status through the lifecycle methods), `tests/unit/web_jobs/*`,
    `tests/unit/test_web_database.py` and `tests/unit/test_web_storage_roundtrip.py` (status
    seeding);
  - `review/briefing.yaml` (a web-dashboard key decision: one job state table; the run row follows
    the job).
- **Signal (leaf):** B4–B7 through `JobManager`'s public methods, `POST /api/simulate/home`,
  `GET /api/jobs/<id>` and `GET /api/history/runs/<id>`. After `wait_until_idle`, every job in
  every B4/B5 scenario is terminal. θ's B10 (a queued job whose run is deleted) still reports
  `cancelled`, not B4's `failed`.
- **Prereqs:** out of batch: 806, 819, 822. **Added as a dependency of the trigger-chain gate
  (772)** (high).

#### γ — Versioned job snapshots replace the drained queue; every stream sees every state
- **Keys:** fk-4540d657bff6 · **priority:** medium
- **Modules:**
  - `web/jobs.py` (`JobSnapshot`, `job_snapshot`, the version bumped by β's writer; `events`,
    `get_events`/`take_events`, `JobEvent` and `JobEventType` deleted);
  - `web/sse.py` (`job_progress_frames` reading snapshots and `last_event_id`; J6, J7; the
    pre-δ names `progress`/`complete`/`error`, with `cancelled` → `error` as θ left it; the
    10-minute and "Job not found" frames move here from `api.py` unchanged, and δ types them);
  - `web/api.py` (the route reads `Last-Event-ID` and returns `event_stream(job_progress_frames(…))`,
    and frames nothing; `_job_event_payload`, `_job_event_frame` and `_FINAL_EVENT_TYPE_BY_STATUS`
    deleted);
  - `tests/unit/web_jobs/test_job_endpoints.py`, `tests/unit/web_api/test_jobs.py` and
    `tests/unit/web_api/conftest.py`;
  - `review/briefing.yaml` (the "in-memory progress queues" key decision now reads "versioned job
    snapshots").
- **Signal (leaf):** B8, B9, B10 through `GET /api/jobs/<id>/progress`, and `api.py` contains no
  frame literal. The pages are unchanged: every frame now carries a superset of the keys they read
  (checked by the e2e suite locally).
- **Prereqs:** α, β. Out of batch: 680 (if kept).

#### δ — The job stream's vocabulary, the limit as `timeout`, and one browser reader (integration gate)
- **Keys:** fk-7eb56fda0b1c (**high**), fk-0097b5aaa45c, fk-066e5cb461f7 · **priority:** high
- **Modules:**
  - `web/sse.py` (the job catalogue, `JOB_STATE_EVENTS`, `StreamTimedOut`, `JobUntracked`,
    `JobStreamPolicy`; the limit and untracked frames);
  - `web/app.py` and `web/shared.py` (the policy at the composition root and its accessor);
  - `static/js/job-progress-stream.js` (`followJobProgress`), `static/js/progress-tracker.js` and
    `static/js/parameter-sweep.js` (callbacks only);
  - `templates/simulate/partials/progress-tracker.html` (the cancelled and untracked states);
  - `static/dist/style.css` if a class token changes;
  - `tests/e2e/_job_requests.py` (`sse_event` replaced by frames from `sse_frame`),
    `tests/e2e/conftest.py` (the policy fixture), `tests/e2e/test_progress_tracker.py`,
    `tests/e2e/test_parameter_sweep.py`, `tests/e2e/test_fleet_interactions.py`,
    `tests/unit/web_jobs/test_job_endpoints.py` and `tests/unit/web_api/test_jobs.py`;
  - `review/briefing.yaml` (a key decision: D21's limit and quiet reopen; it replaces task 564's
    line if that landed).
- **Signal (leaf; the C-as-integration-gate):** B11–B16, and every row of §10 green on main
  together.
  - The `{error}` payloads ("Job not found", "SSE stream timed out after 10 minutes") are gone.
  - Only `job-progress-stream.js` opens a job `EventSource`.
  - `data.message || data.error` and the sweep's `JSON.parse` calls are gone.
- **Prereqs:** α, γ (β through γ). Out of batch: 814; 819 through β. **Added as a dependency of the
  trigger-chain gate (772)** (high).

**DAG:** α → γ; β → γ; γ → δ. Out of batch: α → 713; β → 806, 819, 822; δ → 814.

## 12. Out of scope

- Waking streams when a job's version changes instead of polling every 2 s. The latency is
  unchanged from today, and the pages read only the newest state.
- Interrupting a running `simulate_home` (S19 §12; frozen core surface).
- How `create_app` injects collaborators (S16) and where the accessors live (S17); δ adds one
  collaborator in whatever form is current.
- A results URL in the completed payload. S19 ε (814) decided the tracker's link comes from the
  submit response (S19 §13 Q4), and the payload stays exactly `JobState`.
- `GET /api/jobs/<id>`'s 404 body (JSON, not SSE) and the sweep's result-fetch `catch`, which
  handles an aborted fetch, not a frame.

## 13. Open questions (tactical, decided at implementation)

1. **`retry_ms` default.** Default 1000 ms: well under task 648's 60-second give-up limit, and
   quick enough that a timeout reopen is invisible. Decide in δ.
2. **Copy for `untracked` and `cancelled`.** Default: "The server no longer tracks this job. Its
   run is in Run History." and θ's "Cancelled: its run was deleted". Decide in δ.
3. **A malformed `Last-Event-ID`.** Default: treated as absent, so the current state is sent.
   Decide in γ.
4. **`job_state` beside `job_snapshot`.** Default: keep both. `job_state` serves
   `GET /api/jobs/<id>` and the results endpoint; it returns `job_snapshot(...).state`. Decide in
   γ.
5. **The shutdown-drop message.** Default: "Dropped: the server shut down before the job ran".
   Decide in β.
6. **The policy's injection form** if S16 has landed. Decide in δ.

## 14. G6 — premise validity of the asserted signals

- **Numbers:**
  - 600 s is D21's.
  - `retry_ms` is asserted only as equal to the policy's value.
  - B14's one-second limit runs on real time. The reopen latency it relies on was probed at
    `retry` + 16 ms. With `retry_ms=1000` each timeout cycle takes about 2 s, so B14's waits must
    allow about 5 s for two cycles, and the leaf sets its `expect` timeouts accordingly.
- **Exactness:** "data keys `== fields(JobState)`" holds by identity, because the payload is
  `asdict(state)` of a flat frozen dataclass. B10's "byte for byte" holds because both frames come
  from one `sse_frame` call on the same snapshot.
- **Rejection (branch 4):** every refusal a signal names is produced by a mechanism built in the
  same leaf, and each signal authors the refused input:
  - `IllegalJobTransition` from `check_job_transition` (B6);
  - `RunStatusConflict` from `mark_run_failed` on a completed row (B7);
  - `sse_frame`'s `TypeError` on a mismatched payload, and mypy's rejection (probed, §7).

  B6 drives the table through its public function. Through `JobManager`, an illegal move is
  reachable only by a defect: after a completed transition the runner has nothing left to do.
- **End to end (branch 3):**
  - B5 needs `JobManager(storage)` (806, upstream) and `mark_run_completed` (β itself).
  - B13's `cancelled` needs θ (819, upstream of β, which is upstream of δ).
  - B14 and B16 need α's encoder for the fakes, γ's resume and δ's reader; δ depends on α and γ.
  - B4's "the run reads failed" needs `mark_run_failed` (806) and β's callback.
- **Field population:** every `JobState` field is set by `create_run`'s queued state and by each
  transition (strings and floats, no sentinel). The version is set by β's writer, which γ makes
  count.

## 15. G7 — advisory walk

This repo has no `docs/legibility/design-invariants.md`, so the walk uses dark-factory's trigger
shapes and is advisory:

- **status-matches-liveness:** every job the executor is done with is terminal (J2). A dropped job
  is `failed`, not `queued`. A stream's age is a stream fact (`timeout`), never a job fact.
- **no-silent-fail-soft:** a failure's row write is best-effort. It is logged at ERROR, naming the
  job and run, and the next start's `fail_interrupted_runs` repairs the row. The in-memory job is
  `failed` regardless. Recorded as a **G7 waiver on β**: refusing to report a failure because its
  row could not be written would hide the failure itself.
- **one-fact-one-home:**
  - The event type is derived from the status (`JobEvent.type` deleted).
  - Run status has one writer path.
  - The event names live once per language. The JavaScript literals are mirrored behaviourally by
    e2e fakes built from the server's catalogue (D-S20-9). That is a ratified cross-language
    duplication with a behavioural guard.
- **contracts-machine-checked:** `SseEvent[P]` under mypy, the frame-keys test, the transition
  table's exhaustiveness test and the manifest's greps.
- **holds-owned-and-bounded:** a stream is bounded by `limit_seconds`, and the browser's reopen
  loop by task 648's 60-second give-up timer.
- **readers-prove-their-producer:** the browser reader is tested against frames the producer's
  encoder built, and against the live server in B14.
- **corroborate-before-acting:** the pages no longer infer "failed" from a transport event. They act
  on the server's named outcome.

## 16. META

**If this PRD is decomposed and queued without further oversight, will what gets built be
complete, coherent, cohesive and good?** Yes, conditional on the lead's §6 dispositions. If task 564
merges first, δ re-adds the limit against 564's briefing line. That is allowed by D21, but the lead
should cancel 564 rather than let the two land in turn.

- Every finding key has a leaf.
- D21's three clauses are each embodied: the `failed` event with `id` and `retry` (δ), one framing
  module (α, completed by δ), and the named `timeout` the browser treats as a reopen (δ).
- Every mechanism has a named consumer: a page, an endpoint, or the S16, S19 or S21 seams in §8.
- The module layout and the vocabulary are decided.
- The browser premises the design rests on were probed in Chromium.
- The remaining questions (§13) are local.
