# Gap Register — my_solar_challenge

> **Purpose.** This is the shared coordination document for the PRD-authoring
> sessions spawned from the 2026-05-30 deep review. Each non-trivial gap below
> gets its own `/prd` session. Because several features touch the same files,
> this register **pre-assigns seam ownership** so sessions don't collide.
>
> **How to use it (read this first if you are a spawned `/prd` session):**
> 1. Find your PRD block below (you were told which one in your spawn prompt).
> 2. Before editing any file listed under **Cross-PRD seams**, confirm this
>    register names *you* as its owner. If it names another PRD, treat that
>    file's interface as fixed — consume it, don't redefine it. If ownership is
>    unclear, add a `SEAM QUESTION:` note here rather than guessing.
> 3. Author your PRD via the `/prd` skill (gates G1–G6). The existing thin task
>    (e.g. task #7) is your starting placeholder — your PRD supersedes it and
>    should decompose into properly-specified subtasks.
> 4. Update your PRD block's **Status** here (TODO → IN PROGRESS → PRD-DRAFTED →
>    QUEUED) and record the PRD file path + any subtask IDs you queued.
> 5. Edit only your own block + the seam table row(s) you own. Append, don't
>    rewrite others' entries.

Review ID: `20260530T090214Z` · Reports: `review/reports/{phase1,phase2,summary}-20260530T090214Z.{json,md}`

---

## A. Clear-cut fixes — already filed as tasks (NOT PRD work)

These are well-specified bug/hygiene tasks; the orchestrator can take them directly. Listed here only so PRD sessions know they're handled and can depend on them.

| Task | Title | Note for PRDs |
|------|-------|---------------|
| #2  | Fix TOU export revenue → price at SEG rate; wire SEGTariff/SEG_PRESETS; unify net_cost | **Pricing source of truth.** PRD-WEB-UI (tariff/SEG exposure) and PRD-GRIDCHARGE (arbitrage value) DEPEND on this landing. Do not re-fix pricing in a PRD. |
| #9  | Web financial chart must use configured tariff/SEG (not hardcoded 0.245/0.15) | depends on #2. Web financial display. |
| #10 | Fix orchestrator verify `test_command` (collection error: add `--extra web`, ignore e2e) | Verify infra. |
| #11 | Mark real-PVGIS/full-sim tests `slow`; register `integration` marker | Test infra. PRDs adding tests: mark real-PVGIS tests `slow`. |
| #12 | Make `mypy --strict` pass (60 errors) | Type gate. All PRDs: keep mypy strict green. |
| #13 | richardsonpy: simulate only requested window; make it a hard dependency | Load engine. PRD-COMMUNITY (fleet perf) benefits. |
| #14 | CLI `home run`/`quick` full-config parity via canonical parser + thread SEG | depends on #2. CLI config seam. |
| #15 | Test/toolchain hygiene: clean process exit + pin Python to declared range | Infra. |
| #1  | Declare AGPL-3.0 license uniformly (README says MIT) | Docs. |

---

## B. PRD roster — non-trivial gaps (one `/prd` session each)

Author sequentially in the order below (P1→P5) so seam ownership is claimed before dependents start.

### P1 — AI Assistant (subsumes task #3)  ·  Status: **TODO**
- **Gap:** entirely absent. `web/app.py:178-181` imports `solar_challenge.web.assistant` (always ImportError, swallowed → "Assistant blueprint not available"); `web/database.py:73-78` creates an unused `chat_messages` table. The design doc (`docs/web-ui-design.md`) specs a full assistant (model id, tool use, chat UI) — none exists.
- **Owns (new):** `src/solar_challenge/web/assistant.py` (new blueprint), chat UI templates, Anthropic dependency in `pyproject.toml`, `chat_messages` writes in `web/database.py`.
- **Consumes (don't modify):** `web/app.py` blueprint-registration pattern (the try/except is already there — just make the import resolve).
- **Design notes:** greenfield; decide tool-use surface (can it trigger sims? read results?). Use latest Claude model per the API skill. Reconcile with `docs/web-ui-design.md` (note: doc is NOT authoritative — see review).
- **PRD file:** _(record path here)_ · **Subtasks queued:** _(ids)_

### P2 — Web UI engine-capability parity (subsumes tasks #4 + #5)  ·  Status: **QUEUED**
- **Gap (task #5):** single-home web form lacks heat-pump, tariff, and dispatch-strategy panels the engine supports (`web/templates/simulate/home.html`; `web/api.py:_parse_home_config`). **Gap (task #4):** `POST /api/simulate/fleet-from-distribution` returns HTTP 501 (`web/api.py:503-525`); the explicit-home-list path works.
- **Owns:** `web/templates/simulate/*`, `web/api.py` (`_parse_home_config` + `simulate_fleet_from_distribution`), `web/fleet_config.py` (`form_to_fleet_distribution_config`).
- **Consumes (don't modify):** engine config schema in `config.py` (HomeConfig fields already exist — *except* `system_age`, owned by P3); the corrected pricing from **#2/#9** (surface SEG/tariff inputs but rely on #2 for the math); `fleet.simulate_fleet` (call it for the distribution runner — owned by P5 only if community logic changes it).
- **Seam:** shares `web/api.py` with nobody else among PRDs (P1 only adds a new blueprint). Owns all home/fleet form parsing.
- **Decided (user-confirmed):** SEG exposure **included** (depends on #2's HomeConfig SEG surface — see §D note below); dispatch surface = the richer `BatteryConfig.dispatch_strategy` (`DispatchStrategyConfig`); fleet path = a **fleet-wide tariff/dispatch/SEG overlay** applied via `dataclasses.replace` in P2's runner (no `config.py` sampler change — per-home distribution of those fields stays out of scope). Approach **B + H** (form↔engine boundary tests per leaf).
- **PRD file:** `docs/prds/web-ui-engine-capability-parity.md` (committed `cd5545e`) · manifest `docs/prds/web-ui-engine-capability-parity.capability-manifest.md` (`4eed04f`) · **Subtasks queued:** **#18** (① home panels: heat-pump+tariff+dispatch) → **#19** (② fleet-from-distribution runner, removes the 501) → **#20** (③ home PV-age inputs; depends on **#16**) → **#21** (④ home SEG selector; depends on **#2**) → **#22** (⑤ fleet-wide tariff/dispatch/SEG overlay; depends on **#2**). Linear chain serialises shared `web/api.py` edits. Placeholder **tasks #4 + #5 cancelled** (superseded).

### P3 — PV degradation in live simulation (subsumes task #7)  ·  Status: **QUEUED**
- **Gap:** `pv.py:370-438` (`calculate_degradation_factor`, `apply_degradation`) implemented + tested but never called from `home.simulate_home` / `pv.simulate_pv_output`. No system-age parameter on any config. Long-run yield is un-degraded.
- **Owns:** the new PV-age fields — **landed on `PVConfig` (`pv.py`), NOT HomeConfig** (degradation is a PV-array property; `simulate_pv_output` already takes `PVConfig` → zero signature churn). Wires `apply_degradation` into `pv.simulate_pv_output`. See announced field contract in §D.
- **Seam (IMPORTANT):** P3 is the **sole owner of the PV-age schema additions** for this batch. P2 (web form) and #14 (CLI) expose these fields once P3 announces them — **see §D below for the final field contract**. Until then, P2/#14 do not add these fields.
- **Decided:** field location/name/type/units resolved → see §D. Approach: bare **B** + the §D announcement as the cross-PRD contract (a web/CLI two-way boundary test belongs to P2/#14, whose files P3 must not touch).
- **PRD file:** `docs/prds/pv-degradation-live-sim.md` (committed `f79cc61`) · **Subtasks queued:** **#16** (α — engine wiring, `pv.py`) → **#17** (β — config threading + `fleet run` signal, `config.py`/`scenarios/`; depends on #16). Placeholder **task #7 cancelled** (superseded).

### P4 — TOU grid-charging / battery arbitrage (subsumes task #8)  ·  Status: **TODO**
- **Gap:** `flow.py:245` — charging the battery from the grid during cheap TOU periods is a comment-only "future enhancement"; the TOU path only charges from excess PV. Limits arbitrage realism.
- **Owns:** `flow.simulate_timestep_tou`, dispatch logic in `dispatch.py` (rate-aware path). Must preserve the energy-balance invariant (`validate_energy_balance`).
- **Consumes (don't modify):** SEG/import pricing from **#2** (arbitrage economics depend on correct TOU pricing — do not re-touch home.py financial accounting). Beware the two unrelated `TariffPeriod` symbols (enum in dispatch vs dataclass in tariff) — see briefing key_decision.
- **PRD file:** _(record path)_ · **Subtasks queued:** _(ids)_

### P5 — Inter-home / community energy sharing (subsumes task #6)  ·  Status: **TODO**
- **Gap:** homes are simulated independently; no inter-home power-sharing / community battery / virtual net metering. README frames it as a "future phase" but the user treats it as real work.
- **Owns:** a new sharing/aggregation layer; `fleet.py` aggregation (`FleetResults`, `simulate_fleet`). Largest/most-design-heavy — expect multiple subtasks.
- **Consumes (don't modify):** per-home `simulate_home` outputs (consume `SimulationResults`); `fleet.simulate_fleet_iter` parallelism model. If P2's fleet-from-distribution runner needs the sharing path, P5 announces the interface here.
- **Seam:** P5 owns `fleet.py` simulation/aggregation changes. P2 only *calls* `simulate_fleet`; if P5 changes its signature, record it here for P2.
- **PRD file:** _(record path)_ · **Subtasks queued:** _(ids)_

---

## C. Cross-PRD seam ownership

| Seam / file | Owner | Consumers (must not redefine) |
|-------------|-------|-------------------------------|
| **`pv.py` `PVConfig` schema** (new `system_age_years`, `degradation_rate_per_year`) — *not* HomeConfig | **P3** | P2 (web form) — wired by **#20** (depends on #16); #14 (CLI) — wire once P3 announces field (see §D; announced ✅) |
| `web/api.py` form parsing (`_parse_home_config`, fleet-from-distribution) | **P2** | — · queued as **#18/#19/#20/#21/#22** (PRD `docs/prds/web-ui-engine-capability-parity.md`) |
| `web/fleet_config.py` | **P2** | — · runner **#19** + overlay **#22** |
| `web/app.py` blueprint registration | shared pattern; **P1** adds assistant bp | P2 (existing bps unchanged) |
| `web/database.py` `chat_messages` | **P1** | — |
| `flow.py` / `dispatch.py` TOU dispatch | **P4** | — |
| `home.py` financial accounting / `seg.py` pricing | **task #2** (not a PRD) | P2, P4 depend on it; do NOT re-fix |
| `fleet.py` simulation/aggregation | **P5** | P2 (calls `simulate_fleet`) |
| test markers (`slow`/`integration`), mypy strict | **tasks #11/#12** | all PRDs: mark new real-PVGIS tests `slow`; keep mypy green |

## D. Notes / open seam questions
- _(spawned sessions append here)_

### 📢 P2 → task #2 seam requirement — SEG must land on `HomeConfig`

P2 (PRD `docs/prds/web-ui-engine-capability-parity.md`, SEG subtasks **#21** + **#22**) surfaces a SEG export-rate / named-supplier selector in the web form and needs the chosen rate to reach `simulate_home` so it affects `net_cost`. **For this to work without P2 touching `jobs.py` (which P2 does not own), task #2 must expose the SEG rate on `HomeConfig`** (the only config object `simulate_home` receives; `home.py` is already in #2's `FILES_TO_MODIFY`). The web path then inherits SEG pricing for free: `web/api.py` sets the field → `submit_home_job` → `simulate_home` prices the `export_revenue` series at the SEG rate → `calculate_summary` sums it → `net_cost`. **No `jobs.py` change required iff SEG lives on `HomeConfig`.**

- **Why this matters:** SEG today threads *only* via `ScenarioConfig.seg_tariff_pence_per_kwh` → `calculate_summary(seg=...)` on the CLI/output/fleet paths (`output.py:159`, `fleet.py:372`). The web's `jobs.py:_run_home_simulation` calls `calculate_summary(results)` with **no** SEG arg (`jobs.py:505`/`565`), so SEG is currently unreachable from the browser regardless of the form.
- **If #2 lands SEG NOT on `HomeConfig`** (e.g. only as a `calculate_summary` param), the web path needs a `jobs.py` change that **no PRD currently owns** — that becomes an integration gap. In that case #21's implementer should raise a `SEAM QUESTION` here before proceeding, and a `jobs.py` owner must be assigned.
- **Field name:** P2 binds to whatever #2 names it (the #21→#2 dependency guarantees #2 lands first); the boundary test on `_parse_home_config` is the arbiter.

### 📢 P3 field announcement — PV-age schema (for P2 web form + #14 CLI to expose)

P3 (PRD `docs/prds/pv-degradation-live-sim.md`, tasks #16/#17) adds **two fields to `solar_challenge.pv.PVConfig`** (frozen dataclass, `pv.py:17`). The register originally said "HomeConfig"; the field lives on **`PVConfig`** instead — `HomeConfig` is in `home.py`, and degradation is a PV-array property that `simulate_pv_output` applies directly. **Final contract — do not redefine; consume as-is:**

| Field | Type | Default | Units / meaning | Validation (PVConfig.`__post_init__`) |
|-------|------|---------|-----------------|----------------------------------------|
| `system_age_years` | `float` | `0.0` | Age of the PV array in years (fractional OK). `0.0` = brand-new → no degradation. | `>= 0`, else `ValueError` |
| `degradation_rate_per_year` | `float` | `0.005` | Fractional capacity loss per year (`0.005` = 0.5%/yr). | `0 <= rate <= 1`, else `ValueError` |

- **Semantics:** generation is multiplied by `max(0, 1 - system_age_years * degradation_rate_per_year)` inside `simulate_pv_output` (linear model; existing `pv.apply_degradation`).
- **YAML surface (under the `pv:` block):** `pv.system_age_years`, `pv.degradation_rate_per_year`. Both also available as distribution params on `PVDistributionConfig` for fleets (added by #17).
- **How P2/#14 expose it:** add the two fields to the `pv` sub-form / PV parsing alongside `capacity_kw`/`azimuth`/`tilt`. The canonical `_parse_pv_config` (config.py) reads them after #17 lands, so #14's canonical-parser fix picks them up for free; P2 surfaces them in the web home form. Backward-compatible — omitting them = age 0, no behaviour change.
- **Wired (P3) vs your job:** P3 wires the engine + canonical parser + fleet sampler and proves it via `fleet run`. P2 owns the web-form widgets; #14 owns the CLI `home run` exposure (P3 deliberately does **not** route its signal through the under-exposing `cli/home.py` path).
