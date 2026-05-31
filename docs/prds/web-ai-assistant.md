# PRD — Web AI Assistant

- **Gap register item:** P1 (supersedes placeholder task #3 *Implement AI assistant feature*). This is the **last** PRD in the 2026-05-30 review chain.
- **Status:** active · authored 2026-05-31 (review `20260530T090214Z`)
- **Owner seam:** sole owner of the **new** `src/solar_challenge/web/assistant.py` blueprint, the chat UI templates (`web/templates/assistant/*`), the `anthropic` dependency in `pyproject.toml` (`web` extra), the **writes** to the existing `chat_messages` table in `web/database.py`, and the new "AI Assistant" entry in `web/templates/partials/nav-sidebar.html` (+ its icon in `components/icons.html`). No other PRD touches these.
- **Consumes (don't modify):** `web/app.py` blueprint-registration `try/except` (already present at `app.py:178-184` — P1 just makes the import resolve); `JobManager` (`web/jobs.py`); `web/api.py:_parse_home_config` (P2-owned — read-only consume); `web/database.py:get_db`; `web/shared.py:resolve_location`.
- **Approach:** **B + H** (vertical slices + two-way boundary tests on the chat↔Anthropic and tool↔engine seams, with the Anthropic client mocked). See §8.

---

## 1. Goal

The web dashboard ships a fully-wired *placeholder* for an AI assistant that has never been built: `web/app.py:178-184` imports `solar_challenge.web.assistant` inside a `try/except ImportError` that always fails silently ("Assistant blueprint not available"), and `web/database.py:74-83` creates a `chat_messages` table that is never written. The design doc (`docs/web-ui-design.md` §8) specs a full conversational assistant — model id, six tools, streaming chat UI, per-session history — none of which exists. (The design doc is **not authoritative**: it names a retired model `claude-sonnet-4-5-20250514`, an HTMX stack that was removed, and Tailwind CDN play-mode that was replaced by compiled CSS. This PRD reconciles to the implementation, not the doc.)

**User-observable outcome:** from any page a user opens an **AI Assistant** chat, asks a question in natural language, and gets a **streamed** answer that is grounded in the simulator's actual capabilities. The assistant can (a) **explain** metrics and suggest sizing, (b) **read** the user's past runs and report their real numbers, and (c) **trigger** new home/fleet simulations that actually run and land in history with a clickable results link. Conversation history persists per browser session and reloads on revisit.

## 2. Background

- **The blueprint slot already exists, defensively.** `web/app.py:_register_blueprints` (`app.py:138-184`) registers five blueprints, each in its own `try/except ImportError`. The fifth (`app.py:178-184`) targets `solar_challenge.web.assistant`'s `bp` at `url_prefix="/assistant"` and currently always logs *"Assistant blueprint not available"*. **P1 makes the import resolve** — it does not touch `app.py` (the briefing's `key_decisions` notes a typo in any blueprint silently 404s; making the import succeed is the whole fix).
- **The persistence table exists, unused.** `web/database.py:74-83` creates `chat_messages(id, session_id, role CHECK(role IN ('user','assistant')), content, created_at, metadata_json)` with an index on `session_id` (`database.py:109-112`). No code writes or reads it. **P1 owns those reads/writes.** `web/database.py:get_db` (`database.py:118-150`) is the connection context manager (auto-commit/rollback) reused verbatim.
- **Streaming over SSE is an established pattern here.** `web/api.py:get_job_progress` (`api.py:231-295`) returns `Response(stream_with_context(gen), mimetype="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})` and yields `event: <type>\ndata: <json>\n\n` frames. P1's chat endpoint reuses this exact SSE shape. The briefing's `web-dashboard.key_decisions` mandates **single-worker** deployment (in-memory `JobManager`); SSE chat fits that model (one request, one generator).
- **Background jobs are submitted, never run inline.** `JobManager.submit_home_job(config, start, end, db_path, data_dir, name)` (`jobs.py:61-169`) and `submit_fleet_job(configs, …)` (`jobs.py:171-279`) create `runs`+`jobs` rows and dispatch to a `ThreadPoolExecutor`, returning `(job_id, run_id)` immediately. A full-year stochastic home sim is >20s (review headline), so the assistant must **submit-and-link**, never block the chat turn on `simulate_home`.
- **Home-config parsing is owned by P2 but already works for the basic fields.** `web/api.py:_parse_home_config(dict) -> (HomeConfig, start, end, name)` (`api.py:47-137`) builds `PVConfig`/`BatteryConfig`/`LoadConfig`/`HomeConfig` from a flat JSON dict (pv/battery/load/location/days), with validation. It exists and works today; P2 (#18) extends it additively. P1's `run_home_simulation` tool **consumes it read-only** to avoid duplicating config construction/validation.
- **Reading a run's summary is an established read-only pattern.** `web/api.py:get_job_results` (`api.py:298-339`) reads `runs.summary_json` via `get_db`. P1's `get_run_results` tool reuses the same read-only query.
- **Flask sessions are available.** `web/app.py:78` configures a persisted `SECRET_KEY` (`SESSION_COOKIE_HTTPONLY`/`SAMESITE` set), so a signed-cookie `session_id` is available to scope `chat_messages` per browser without auth.
- **The Anthropic SDK is absent.** `import anthropic` → `ModuleNotFoundError` (verified); there are zero `ANTHROPIC*` references in `src/`. **P1 adds `anthropic` to the `web` extra** (`pyproject.toml:46-50`) and is the sole consumer. The SDK client `anthropic.Anthropic()` resolves `ANTHROPIC_API_KEY` from the environment.
- **Model + API guidance (per the `claude-api` skill, 2026-05).** Default `claude-opus-4-8` (1M context), configurable to `claude-sonnet-4-6`. Adaptive thinking only (`thinking={"type":"adaptive"}`); `budget_tokens`/`temperature`/`top_p` **400** on these models — do not send them. Depth via `output_config={"effort": ...}`. Prompt caching is a prefix match: a `cache_control:{"type":"ephemeral"}` breakpoint on the last `system` block caches `tools`+`system` together (render order `tools`→`system`→`messages`); keep the tool list deterministically ordered and put per-request content (the user message, current-run context) **after** the cached prefix. Min cacheable prefix on Opus 4.8 is 4096 tokens. For per-token streaming **with** tool use, use the **manual agentic loop** (the SDK tool-runner returns complete messages, not deltas): `client.messages.stream(...)` per API call → stream `text_stream`, then `stream.get_final_message()`; on `stop_reason=="tool_use"` execute the tool, append a `tool_result` with the matching `tool_use_id`, and loop until `end_turn`.

Review context: `review/reports/summary-20260530T090214Z.md` ("AI assistant entirely absent … the blueprint import is swallowed and the `chat_messages` table is never written").

## 3. Sketch of approach

A new self-contained `web/assistant.py` Flask blueprint (`bp`, `url_prefix="/assistant"`) plus chat-UI templates, built in five vertical slices on one file (serialised — §9):

**Foundation.** Add `anthropic` to the `web` extra; create `assistant.py` with `bp` + a `GET /assistant` page route rendering a chat shell; add the nav entry. The import now resolves — the swallowed-`ImportError` warning is gone and the blueprint registers via the **unchanged** `app.py` pattern.

**Chat core.** `POST /assistant/chat` returns `text/event-stream`: it pulls the user message (+ optional `run_id` context) from the JSON body, derives a `session_id` from the Flask session cookie, loads prior turns from `chat_messages`, and runs the Anthropic request with a cached simulator-docs system prompt, streaming `delta` SSE frames. User and assistant turns are written to `chat_messages`; `GET /assistant/history` returns them. If `ANTHROPIC_API_KEY` is unset, the page shows a configure-notice and `/chat` emits a clean `error` frame (no 500).

**Tools (three tiers, one loop).** The chat endpoint runs the manual tool-use loop. Tier 1 advisory: `explain_metric`, `suggest_config` (grounded handlers — canonical UK benchmark bands / rule-of-thumb sizing, so numbers aren't hallucinated). Tier 2 read: `get_run_results`, `list_recent_runs` (read-only `runs` queries via `get_db`). Tier 3 trigger: `run_home_simulation`, `run_fleet_simulation` (build configs via the consumed `_parse_home_config`, submit via `JobManager`, return a `run_id` + results URL). Each tool call streams a `tool` SSE frame so the UI shows progress.

Every slice carries a **two-way boundary test** with the Anthropic client mocked (no real API calls in CI), proving the wiring actually moves data across the seam (§8).

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| **Tool-use surface** | **Full**: advisory (`explain_metric`, `suggest_config`) + read (`get_run_results`, `list_recent_runs`) + trigger (`run_home_simulation`, `run_fleet_simulation`). | User-confirmed. Highest value; matches the design-doc intent. Side-effects are gated by B+H boundary tests proving a tool call reaches `JobManager` and a run lands in history. |
| **Response delivery** | **SSE streaming** (`text/event-stream`), consumed client-side via **`fetch()` streaming body** (not `EventSource` — the chat POSTs a message, and `EventSource` is GET-only; the app already uses plain `fetch()`). Hybrid with tools: stream text, pause to run a tool, resume. | User-confirmed; matches the existing SSE infra (`api.py:231-295`) and the single-worker model. |
| **Sim execution mode** | Trigger tools **submit-and-link** (async via `JobManager`), returning `{run_id, results_url}`; never block the chat turn on `simulate_home`. | A sim is >20s; the whole app is background-job based. Blocking the SSE turn would stall the chat and the single worker. |
| **Model + params** | Default `claude-opus-4-8`; configurable via env `SOLAR_ASSISTANT_MODEL` (e.g. `claude-sonnet-4-6`). `thinking={"type":"adaptive"}`, `output_config={"effort":"low"}` (chat responsiveness; configurable). No `temperature`/`budget_tokens` (would 400). | User specified both ids; opus-default-configurable is the skill's convention. Adaptive thinking is the only supported mode on these models. |
| **Prompt caching** | System prompt = simulator-capability docs + UK benchmark bands + tool guidance, as a single `system` text block with `cache_control:{"type":"ephemeral"}`. Tools listed in a fixed order. Per-request content (user message, run context) after the prefix. | Prefix-match caching; caches `tools`+`system` once and serves ~0.1× on every subsequent turn. Verified via `usage.cache_read_input_tokens`. |
| **Persistence / identity** | A `session_id` (uuid) stored in the signed Flask session cookie scopes `chat_messages`. Each turn writes a row; `metadata_json` holds tool calls / run links on assistant rows. No user accounts. | The `chat_messages` schema already has `session_id`; `SECRET_KEY` is configured (`app.py:78`). Matches the zero-infra, local-desktop posture. |
| **API-key-absent behavior** | Import still resolves (`anthropic` is a declared `web`-extra dep, so no `ImportError`); `GET /assistant` renders a "set `ANTHROPIC_API_KEY`" notice; `POST /assistant/chat` emits an `error` SSE frame. | Decouples "blueprint registers" (the gap-register fix) from "API key present". The blueprint must register so the swallowed-import warning is gone regardless of key state. |
| **Fleet trigger scope** | `run_fleet_simulation` builds a **homogeneous** N-home list via `_parse_home_config` and calls `submit_fleet_job` (the **explicit-list** fleet path, which works today). | Avoids reimplementing P2's distribution machinery (`#19`'s 501 fix) — no duplication, no seam collision. Heterogeneous distribution fleets stay P2's (§10). |
| **Scenario tool** | `load_scenario` (design-doc tool #3) is **out of scope** (§10); the assistant can describe scenarios from its system-prompt knowledge. | Lower value; would couple to the scenarios surface. Candidate follow-up. |
| **Backward compatibility** | All new; touches no existing route. Existing web tests stay green; the new blueprint is additive. | Greenfield. |

## 5. Pre-conditions for activating

- **Foundation (① ) / chat core (②) / advisory (③) / read (④):** none — all substrate present today (§6), and the one missing library (`anthropic`) is added by ① itself.
- **Trigger (⑤):** consumes `web/api.py:_parse_home_config`, which **exists today** (`api.py:47`) and works for the basic fields — **no ordering dependency on P2**. P2's `#18` additions are additive/backward-compatible; ⑤ binds to the current signature and inherits any extension for free.
- **Runtime (not a code pre-condition):** `ANTHROPIC_API_KEY` in the environment to actually talk to Claude; absent it, the assistant degrades gracefully (§4).

## 6. Substrate verification (G3)

| Assumed capability | Evidence | Verdict |
|---|---|---|
| `app.py` already registers an `assistant` blueprint in a swallowing `try/except` (just make import resolve) | `app.py:178-184`, `app.py:138-150` | present |
| `chat_messages` table with `session_id`/`role`/`content`/`created_at`/`metadata_json` (+ index) | `database.py:74-83`, `database.py:109-112` | present |
| `get_db` context manager (auto-commit/rollback) for reads+writes | `database.py:118-150` | present |
| SSE streaming response pattern (`text/event-stream`, `event:/data:` frames, `stream_with_context`) | `api.py:231-295` | present |
| Read-only `runs.summary_json` query pattern | `api.py:298-339` | present |
| `JobManager.submit_home_job(...)` → `(job_id, run_id)`, async | `jobs.py:61-169` | present |
| `JobManager.submit_fleet_job(configs, …)` (explicit-list path) | `jobs.py:171-279`; consumer at `api.py:203-212` | present |
| `web/api.py:_parse_home_config(dict)` → `(HomeConfig, start, end, name)` (read-only consume; P2-owned) | `api.py:47-137` | present (current signature) |
| `resolve_location(preset)` for fleet/home location | `shared.py:26-39` | present |
| Page-route + template-render precedent (`render_template`, `page=` var) | `routes.py:90-96` | present |
| Flask signed-cookie session (SECRET_KEY configured) for `session_id` | `app.py:77-83` | present |
| Nav is an extensible Jinja `nav_items` list (unclaimed by other PRDs) | `nav-sidebar.html:15-53` | present |
| **`anthropic` Python SDK** (`Anthropic()`, `messages.stream`, tool use, `cache_control`) | **NOT installed** — `ModuleNotFoundError` (verified); added by **① to the `web` extra** (`pyproject.toml:46-50`) | **added by ①** |
| Model ids `claude-opus-4-8` / `claude-sonnet-4-6`; adaptive thinking; `cache_control` ephemeral | `claude-api` skill (2026-05), §2 model table + prompt-caching/tool-use docs | present (API capability) |

**G3 verdict: pass.** Every same-batch substrate is verified present at a cited line. The only missing capability — the `anthropic` SDK — is added by the batch's own first leaf (①) before any leaf that imports it depends on it (②→①). The one cross-PRD consume (`_parse_home_config`) exists today; ⑤'s boundary test is the arbiter if P2 ever renames it. No substrate fiction.

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **P2** (web engine-capability parity) | **consumes** (read-only) | ⑤'s trigger tools call `web.api._parse_home_config(dict)` to build a `HomeConfig`, then `JobManager.submit_home_job`. P1 **does not modify** `web/api.py`. | P2 owns `_parse_home_config`; P1 owns the assistant tool that calls it | P2 queued (#18). **No ordering dep** — the function exists today and P2's additions are additive. ⑤'s boundary test catches a rename. |
| `web/app.py` blueprint registration | consumes (unchanged) | The existing `try/except` at `app.py:178-184` resolves once `assistant.py:bp` imports cleanly | shared pattern; **P1 adds the assistant bp** by making the import succeed | P1 does not edit `app.py` (gap-register §C row) |
| `web/database.py` `chat_messages` | **owns (writes/reads)** | P1 writes user+assistant rows and reads history; reuses `get_db` | **P1** (gap-register §C) | — |
| `JobManager` (`web/jobs.py`) | consumes | ⑤ submits via `submit_home_job`/`submit_fleet_job`; shared in-memory infra (single-worker) | engine/web infra (not PRD-owned) | unchanged |
| **task #2** (pricing source of truth) | sibling (read-only) | `get_run_results` reports whatever financials the engine already computed into `summary_json`; the assistant **does not re-price** anything and `suggest_config` caveats its rule-of-thumb estimates | #2 owns pricing | independent; P1 adds **no** pricing path (do not re-fix pricing) |
| `web/templates/partials/nav-sidebar.html` + `components/icons.html` | **owns (adds entry)** | Adds an "AI Assistant" `nav_items` row + an icon branch; unclaimed by P2 (P2 owns `web/templates/simulate/*` only) | **P1** | no overlap with P2 |
| P3/P4/P5 | none | P1 is a self-contained web blueprint; no engine-schema or fleet/community seam | — | disjoint |
| task #3 | superseded | — | this PRD | cancel at decompose; replaced by ①–⑤ |

**The one real coordination point** is P1's read-only consume of `_parse_home_config`. There is **no reciprocal-ownership ambiguity**: P2 owns the function outright and P1 only *calls* it; P1 owns every assistant file outright and P2 never touches them. Because the function already exists and works for the fields ⑤ needs, P1 declares **no hard dependency** on P2 — it binds to the current signature, and ⑤'s boundary test (which imports `_parse_home_config`) is the arbiter if P2 renames it. P1 deliberately does **not** reuse P2's still-unbuilt fleet-from-distribution runner (`#19`); ⑤ uses the working explicit-list fleet path instead (§4), so there is no dependency on unlanded P2 work.

## 8. G5 note — why B + H

P1 is a **high-stakes integration PRD** and the *exact* "fake-done leaf" hazard the gates exist to catch: a chat endpoint that returns canned text, or a tool that is *declared* in the `tools=[...]` array but whose handler is never wired to `JobManager`/the DB, would sail past a naive unit test while the user-visible feature does nothing. It also crosses an external boundary (the Anthropic API) that must **not** be hit in CI. **Decision: B + H.**

- **Contracts (B):** (a) the **SSE event contract** — `delta` (text token), `tool` (`{name}` invoked), `done` (`{run_id?, results_url?}`), `error` (`{message}`); (b) each **tool's input JSON schema**; (c) the `chat_messages` row shape.
- **Two-way boundary tests (H), Anthropic mocked:** each slice asserts data actually crosses the seam — the chat request carries a `cache_control`-marked system block and streamed deltas reach the SSE body (②); `explain_metric` is dispatched and its grounded benchmark text reaches the reply (③); `get_run_results` returns a *seeded* DB row's real numbers (④); `run_home_simulation` causes `JobManager.submit_home_job` to receive a populated `HomeConfig` **and** a `slow`-marked integration test runs a tiny sim end-to-end so a real `run_id` lands in `runs` (⑤). These tests live under `tests/` against P1-owned `web/assistant.py`, so there is no seam violation. They are the anti-fake-done mechanism for every leaf signal. Real-Anthropic calls are confined to an optional `slow`/skip-without-key smoke test (per task #11's marker convention).

## 9. Decomposition plan

Five subtasks. **All five edit `web/assistant.py`** (and its templates/tests), so they are chained into a single linear dependency to serialise edits deterministically under the orchestrator's narrow-file-lock model (no cross-PRD contention — P1 owns the file outright). Order builds bottom-up: foundation → streaming chat → advisory tools → read tools → trigger tools, so each leaf's signal is demonstrable on a working base.

Each leaf names a **user-observable signal** and a **boundary test** (G2/§8). Metadata fields `user_observable_signal`, `consumer_ref`, `substrate_confirmed` are recorded per task (not yet read by the orchestrator — see note).

### ① ASSISTANT-FOUNDATION — blueprint + page + dependency (import resolves)
- **Modules:** `pyproject.toml` (`web` extra: add `anthropic`), new `web/assistant.py` (`bp` + `GET /assistant` page route), new `web/templates/assistant/chat.html` (chat shell, extends `base.html`), `web/templates/partials/nav-sidebar.html` (+ icon in `components/icons.html`) (+ `tests/`).
- **Work:** create the blueprint with a page route rendering an (initially static) chat UI; add the "AI Assistant" nav entry; add `anthropic` to the `web` optional-deps. The `app.py:178-184` import now resolves (no app.py edit).
- **Deps:** none (substrate present; this leaf adds the `anthropic` dep). **Classification:** intermediate (front of the assistant.py chain). **`substrate_confirmed`:** anthropic-added-here.
- **Signal:** the web app starts with **no** "Assistant blueprint not available" log line; `GET /assistant` returns **200** and renders the chat UI; the sidebar shows an "AI Assistant" link; a test asserts `assistant.bp` is registered on the app and `/assistant` renders.
- **Consumer:** end-user (chat page) + `app.py` registration (consumes the resolved import).

### ② ASSISTANT-CHAT-CORE — streaming chat endpoint + persistence
- **Modules:** `web/assistant.py` (`POST /assistant/chat` SSE, `GET /assistant/history`, Anthropic client, cached system prompt), `web/templates/assistant/chat.html` (+ `web/static/js/assistant.js` for the `fetch()` stream reader), `web/database.py` (chat_messages read/write helpers) (+ `tests/`).
- **Work:** derive `session_id` from the Flask session; load history; call Anthropic with `model=SOLAR_ASSISTANT_MODEL|claude-opus-4-8`, `thinking=adaptive`, a `cache_control`-marked simulator-docs system prompt; stream `delta` frames; write user+assistant rows to `chat_messages`. Graceful `error` frame + configure-notice when `ANTHROPIC_API_KEY` is unset.
- **Deps:** [①] (serialise `web/assistant.py`). **Classification:** intermediate.
- **Signal:** `POST /assistant/chat {"message":"hi"}` returns `text/event-stream` whose `delta` frames reconstruct the (mocked) reply; a user+assistant **`chat_messages` row pair is written**; `GET /assistant/history` returns them in order; a boundary test (mock `anthropic.Anthropic`) asserts the request carries a `cache_control:{"type":"ephemeral"}` system block and that streamed deltas reach the SSE body; with the key unset, the page shows the notice and `/chat` emits an `error` frame (no 500).
- **Consumer:** end-user (chat UI) + `GET /assistant/history` (consumes the writes).

### ③ ASSISTANT-TOOLS-ADVISORY — tool-use loop + explain_metric + suggest_config
- **Modules:** `web/assistant.py` (manual tool-use loop; `explain_metric`, `suggest_config` definitions + grounded handlers) (+ `tests/`).
- **Work:** add the `stop_reason=="tool_use"` loop (append `tool_result` with matching `tool_use_id`, re-stream); `explain_metric(metric)` returns a canonical definition + UK benchmark band from an in-module table; `suggest_config(annual_consumption_kwh, goal)` returns a rule-of-thumb PV/battery sizing with a caveat. Tools listed in a **fixed order** (cache-safe). Stream a `tool` SSE frame per call.
- **Deps:** [②]. **Classification:** intermediate.
- **Signal:** "explain my self-consumption ratio" **dispatches `explain_metric`** and the grounded benchmark text appears in the reply; a boundary test (mock Anthropic emitting a `tool_use` block) asserts the handler runs, the canonical band is returned, and a `tool` frame is emitted; the tool list order is asserted stable.
- **Consumer:** end-user; grounds numbers in canonical bands (no hallucinated benchmarks).

### ④ ASSISTANT-TOOLS-READ — get_run_results + list_recent_runs + run context
- **Modules:** `web/assistant.py` (`get_run_results`, `list_recent_runs` read-only `runs` queries via `get_db`; optional `run_id` context injection on `POST /assistant/chat`) (+ `tests/`).
- **Work:** `get_run_results(run_id_or_name)` reads `runs.summary_json` (read-only, like `api.py:298-339`); `list_recent_runs(limit)` reads recent `runs` rows; when the chat body includes a `run_id`, inject that run's summary into the turn (the "ask about these results" path).
- **Deps:** [③] (serialise `web/assistant.py`). **Classification:** leaf.
- **Signal:** "summarise my last run" → `get_run_results` reads the **real** `summary_json` and the reply reports those numbers; a boundary test (mock Anthropic, **seeded** `runs` row) asserts the tool returns the seeded row's fields; posting `{"message":"…","run_id":"<seeded>"}` injects that summary into the request.
- **Consumer:** end-user; consumes the existing `runs` table read-only.

### ⑤ ASSISTANT-TOOLS-RUN — run_home_simulation + run_fleet_simulation
- **Modules:** `web/assistant.py` (`run_home_simulation`, `run_fleet_simulation` definitions + handlers that call `web.api._parse_home_config` and `JobManager.submit_home_job`/`submit_fleet_job`) (+ `tests/`).
- **Work:** `run_home_simulation({pv_kw, battery_kwh, consumption_kwh, occupants, location, days})` → `_parse_home_config(dict)` → `submit_home_job(...)` → return `{run_id, results_url=/results/home/<run_id>}`; `run_fleet_simulation({n_homes, pv_kw, battery_kwh, location, days})` → build N homes via `_parse_home_config` → `submit_fleet_job(...)` → `{run_id, results_url=/results/fleet/<run_id>}`. Stream the returned link in the reply.
- **Deps:** [④] + consume **P2 `_parse_home_config`** (exists today; **no ordering dep**). **Classification:** leaf.
- **Signal:** "run a 4 kW home with a 5 kWh battery for 7 days" → a boundary test (mock Anthropic emitting the `tool_use`) asserts `JobManager.submit_home_job` **receives a populated `HomeConfig`** (pv 4 kW, battery 5 kWh) and the reply contains `/results/home/<run_id>`; a **`slow`-marked** integration test runs a tiny home sim end-to-end and the run lands in `runs` with a fetchable `run_id`.
- **Consumer:** end-user; consumes P2's `_parse_home_config` (read-only) + `JobManager`.

> **Note for decompose-time:** the orchestrator does not yet consume the `user_observable_signal` / `consumer_ref` / `substrate_confirmed` metadata; recorded for a future tracking session. Task **#3** is cancelled (superseded by ①–⑤). A capability manifest is committed beside this PRD (`web-ai-assistant.capability-manifest.md`).

## 10. Out of scope

- **Re-pricing / SEG math** — the assistant only *reports* `summary_json` financials and *caveats* `suggest_config` estimates; it adds **no** pricing path → **task #2**.
- **Heterogeneous distribution fleets from chat** — `run_fleet_simulation` builds a homogeneous N-home list; per-component distribution sampling is P2's (`#19`/`#22`) fleet machinery.
- **A `load_scenario` tool / scenario-file reads** — design-doc tool #3; candidate follow-up (the assistant can describe scenarios from system-prompt knowledge).
- **Sweep triggering / scenario building / run editing from chat** — not in the chosen surface.
- **Real-time progress of a triggered sim inside the chat** — the assistant returns a results link; live progress remains the existing job-SSE page.
- **Multi-user accounts / auth** — `session_id` is a per-browser signed cookie; no login.
- **Any edit to `web/app.py`, `web/api.py`, or `web/jobs.py`** — consumed read-only; owned by the existing code / P2.
- **Replacing the SDK tool-runner's manual loop with the beta tool-runner** — the manual loop is required for per-token streaming with tools (§2).

## 11. Open questions (tactical — deferred, not design-blocking)

1. **`anthropic` minimum version pin.** Pin to a recent release supporting `messages.stream` + `cache_control` (≥ the version current at ① implementation time). Tactical; the boundary tests mock the client so CI is version-agnostic.
2. **`effort` / thinking default for chat latency.** Start `effort="low"` with adaptive thinking; tune during ② if replies feel shallow. Env-overridable.
3. **System-prompt token budget vs the 4096-token cache floor.** The simulator-docs system prompt must exceed 4096 tokens on Opus 4.8 to cache; if the curated docs fall short, either accept no-cache (correct, just not cheaper) or pad with the benchmark tables. Decide during ②; the cache-hit assertion is informational, not a hard gate.
4. **`suggest_config` heuristic.** Ship a simple rule-of-thumb (e.g. PV kWp ≈ consumption/950; battery ≈ daily shortfall) with an explicit "indicative — run a simulation to confirm" caveat; refine later.
5. **History retention / pruning.** `chat_messages` grows unbounded; a retention sweep is a later hygiene task, not design-blocking.

## 12. G6 — premise validity of leaf signals

- **① foundation:** asserts only that the blueprint registers and `/assistant` renders (and the warning is gone) — directly observable wiring, no number/capability claim. Substrate (`anthropic`) is added by this leaf itself. **Pass.**
- **② chat core:** asserts the endpoint streams deltas and writes a `chat_messages` row pair — produced entirely by this leaf's own wiring over present substrate (SSE pattern, `get_db`, the SDK from ①). The cache assertion is a config-shape check on a mocked request, not a runtime number. **Pass.**
- **③ advisory:** asserts `explain_metric` is dispatched and returns a *canonical* band from an in-module table this leaf owns — no external number claimed; fully producible from its own handler. **Pass.**
- **④ read:** asserts `get_run_results` returns a **seeded** row's fields — the value is supplied by the test's own fixture and read via the present `runs`/`get_db` substrate; no claim about a number this task can't produce. **Pass.**
- **⑤ trigger:** asserts `JobManager.submit_home_job` receives a populated `HomeConfig` and a real `run_id` lands — produced by this leaf's wiring over present `_parse_home_config` (current signature) + `JobManager`. The only "capability" claim (a sim runs and lands) is producible from its own dependency set; no numeric/exactness claim about sim *output*. **Pass.**

No signal asserts a number, exactness, or capability its own task (plus its declared prerequisites) cannot produce. **G6 pass.**
