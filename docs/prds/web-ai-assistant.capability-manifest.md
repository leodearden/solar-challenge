# Capability manifest — Web AI Assistant (P1)

Mechanizes G3 (substrate exists + wired) + G6 (premise valid) per leaf. Each
asserted capability binds to evidence: `grep:file:line wired` (present
substrate), `producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` (numeric/limit/capability claim with its basis). PRD:
`docs/prds/web-ai-assistant.md`.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, `producer-downstream`, or `bound≤floor`. The one new library
(`anthropic`) is added by the batch's own first leaf (**①**) and every leaf that
imports it depends on it (②→①, transitively ③/④/⑤). All intra-batch producers
(blueprint, streaming chat endpoint, tool loop, tool handlers) are queued with
wired edges (②→①; ③→②; ④→③; ⑤→④ — a single linear chain serialising
`web/assistant.py`). The one cross-PRD consume (`web.api._parse_home_config`) is
present **today** (`api.py:47`) — no ordering edge required; ⑤'s boundary test
imports it and is the arbiter on rename. **`web/app.py` is consumed unchanged —
no app.py producer task, by design (the import simply resolves).**

## ① ASSISTANT-FOUNDATION (blueprint + page + dependency) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `app.py` registers an `assistant` blueprint in a swallowing `try/except` (resolving the import un-swallows it) | grep:`app.py:178-184` wired (app.py NOT modified) | ✅ |
| Flask `Blueprint` + page-route + `render_template(page=…)` precedent | grep:`routes.py:90-96`, `api.py:27` wired | ✅ |
| `nav_items` is an extensible Jinja list (add "AI Assistant" entry) | grep:`nav-sidebar.html:15-53` wired (unclaimed by P2) | ✅ |
| `anthropic` SDK present to import | **added here** — `pyproject.toml:46-50` `web` extra (verified absent: `ModuleNotFoundError`); no consumer before this leaf | ✅ |
| Signal = app starts w/o "Assistant blueprint not available"; `GET /assistant`→200; nav shows link | test asserts `assistant.bp` registered + `/assistant` renders (own task, no Anthropic call) | ✅ |
| Premise: import resolves regardless of `ANTHROPIC_API_KEY` | floor: `anthropic` is a declared `web`-extra dep ⇒ no `ImportError`; key checked at request time, not import (§4) | ✅ |

## ② ASSISTANT-CHAT-CORE (streaming chat endpoint + persistence) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `anthropic.Anthropic()` + `messages.stream` + `cache_control` system block | **producer:task-① upstream** — dep ②→① wired (anthropic added by ①); API capability per `claude-api` skill §2/streaming/prompt-caching | ✅ |
| SSE response pattern (`text/event-stream`, `event:/data:` frames, `stream_with_context`) reusable for chat | grep:`api.py:231-295` wired | ✅ |
| `chat_messages` table (session_id/role/content/created_at/metadata_json) + index | grep:`database.py:74-83`, `database.py:109-112` wired | ✅ |
| `get_db` context manager for the row writes/reads | grep:`database.py:118-150` wired | ✅ |
| Flask signed-cookie session for `session_id` (SECRET_KEY set) | grep:`app.py:77-83` wired | ✅ |
| Signal = `POST /chat` streams `delta` frames; user+assistant rows written; `GET /history` returns them; key-unset ⇒ `error` frame (no 500) | boundary test mocks `anthropic.Anthropic`; asserts cached system block in request + deltas in SSE body + row pair (own task, no real API) | ✅ |
| Premise: prompt-cache prefix is correct (tools+system cached, volatile content after) | floor: `cache_control:{ephemeral}` on last `system` block; render order tools→system→messages; verified via `usage.cache_read_input_tokens` (skill prompt-caching) | ✅ |

## ③ ASSISTANT-TOOLS-ADVISORY (tool loop + explain_metric + suggest_config) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Streaming chat loop to extend with tools | **producer:task-② upstream** — dep ③→② wired (serialises `web/assistant.py`) | ✅ |
| Manual tool-use loop (`stop_reason=="tool_use"` → `tool_result` w/ matching `tool_use_id` → re-stream) | API capability per `claude-api` skill tool-use §Manual Agentic Loop (manual loop required for per-token streaming w/ tools) | ✅ |
| `explain_metric` benchmark band is canonical (not hallucinated) | floor: in-module benchmark table owned by this leaf; handler returns the band, model only phrases it (§3) | ✅ |
| `suggest_config` sizing is rule-of-thumb w/ caveat (no engine call) | floor: simple heuristic in-handler + "run a simulation to confirm" caveat (§4 / §11.4); no numeric claim about engine output | ✅ |
| Tool list deterministically ordered (cache-safe) | floor: fixed-order `tools=[...]`; tools render at position 0, any reorder invalidates cache (skill prompt-caching) | ✅ |
| Signal = "explain self-consumption ratio" dispatches `explain_metric`; band reaches reply; `tool` frame emitted | boundary test: mock Anthropic emits a `tool_use` block; assert handler runs + band returned + frame (own task) | ✅ |

## ④ ASSISTANT-TOOLS-READ (get_run_results + list_recent_runs + run context) — LEAF

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Tool loop to add read tools into | **producer:task-③ upstream** — dep ④→③ wired (serialises `web/assistant.py`) | ✅ |
| Read-only `runs.summary_json` query pattern | grep:`api.py:298-339` wired (reuses `get_db`) | ✅ |
| Run-context injection path (chat body carries `run_id`) | grep:`api.py:319-339` (run lookup precedent) wired | ✅ |
| Signal = "summarise my last run" reads real `summary_json`; reply reports those numbers | floor: value supplied by the test's **seeded** `runs` row + read via present substrate — no number this task can't produce; boundary test (mock Anthropic, seeded row) asserts tool returns the row (own task) | ✅ |
| Backward-compat: read-only ⇒ no write to `runs` | floor: `SELECT`-only queries; no `INSERT`/`UPDATE` on `runs` (§3) | ✅ |

## ⑤ ASSISTANT-TOOLS-RUN (run_home_simulation + run_fleet_simulation) — LEAF (trigger)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Tool loop to add trigger tools into | **producer:task-④ upstream** — dep ⑤→④ wired (serialises `web/assistant.py`) | ✅ |
| `web.api._parse_home_config(dict)` → `(HomeConfig, …)` to build configs (read-only consume; P2-owned) | grep:`api.py:47-137` wired (present **today**; no ordering dep — current signature; ⑤ boundary test imports it, arbiter on rename) | ✅ |
| `JobManager.submit_home_job(...)` async → `(job_id, run_id)` | grep:`jobs.py:61-169` wired | ✅ |
| `JobManager.submit_fleet_job(configs, …)` explicit-list path (NOT P2's unbuilt distribution runner) | grep:`jobs.py:171-279`, consumer `api.py:203-212` wired; design: homogeneous N-home list (§4) — no dep on P2 `#19` | ✅ |
| Results URLs resolve to existing routes | grep:`routes.py:99` (`/results/home/<run_id>`), `routes.py:209` (`/results/fleet/<run_id>`) wired | ✅ |
| Capability: a chat-triggered sim runs and lands in `runs` | floor: produced by this leaf's wiring over present `_parse_home_config`+`JobManager`; `slow`-marked end-to-end test proves a real `run_id` lands — no numeric claim about sim **output** | ✅ |
| No re-pricing: assistant reports `summary_json`, adds no pricing path | design: §10 (pricing = task #2); `suggest_config` caveated; trigger tools only submit configs | ✅ |
