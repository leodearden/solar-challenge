# PRD — Web UI engine-capability parity

- **Gap register item:** P2 (supersedes placeholder tasks #4 *fleet-from-distribution 501* + #5 *missing home-form panels*)
- **Status:** active · authored 2026-05-30 (review `20260530T090214Z`)
- **Owner seam:** sole owner of **all** web home/fleet form parsing — `web/api.py` (`_parse_home_config`, `simulate_fleet_from_distribution`), `web/fleet_config.py`, `web/templates/simulate/*`. No other PRD touches these files (P1 only adds a new blueprint).
- **Approach:** **B + H** (vertical slices + two-way boundary tests on the form↔engine seam). See §8.

---

## 1. Goal

The energy engine supports heat pumps, tariffs, battery dispatch strategies, and (via P3) PV-array ageing — but the **web UI cannot reach most of it**. Two concrete gaps:

- **Home form is under-powered (was task #5):** the single-home form (`web/templates/simulate/home.html`, parsed by `web/api.py:_parse_home_config`) only collects PV / battery / load / location / period. It silently drops the engine's heat-pump, tariff, dispatch-strategy, and PV-age capabilities — a user cannot model them from the browser even though `HomeConfig` carries the fields.
- **Fleet-from-distribution is a stub (was task #4):** `POST /api/simulate/fleet-from-distribution` parses the form then returns **HTTP 501** (`web/api.py:503-525`). The explicit-home-list fleet path works; the distribution path is dead.

**User-observable outcome:** from the browser a user can (a) configure a single home with a heat pump, an import tariff, a battery dispatch strategy, a SEG export rate, and a PV-array age, run it, and see those choices reflected in the summary; and (b) launch a distribution-based fleet (e.g. "100 homes, PV ~ Normal(4,1) kW") that actually runs and lands in history — optionally with a fleet-wide tariff/dispatch/SEG applied to every home.

## 2. Background

- **Home parsing is hand-rolled, not canonical.** `web/api.py:_parse_home_config` (api.py:47-137) builds `PVConfig`/`BatteryConfig`/`LoadConfig`/`HomeConfig` directly from the JSON body — it does **not** call `config._parse_home_config`. So new fields must be added to the web parser explicitly; they are not inherited from the canonical YAML parser.
- **The engine surfaces already exist on the config objects:**
  - `HomeConfig.heat_pump_config: Optional[HeatPumpConfig]` (`home.py:44`). `HeatPumpConfig(heat_pump_type: 'ASHP'|'GSHP', thermal_capacity_kw, annual_heat_demand_kwh)` (`heat_pump.py:99`, validated in `__post_init__`: type ∈ {ASHP,GSHP}, 0 < thermal ≤ 50, demand > 0). No singular YAML heat-pump parser exists (only the distribution one) → the web parser constructs `HeatPumpConfig` directly.
  - `HomeConfig.tariff_config: Optional[TariffConfig]` (`home.py:48`). Built by `config._parse_tariff_config(data)` (config.py:653) from `{type: flat_rate|economy_7|economy_10|custom, ...}` — **reusable as-is** (module-level, consume-only).
  - Battery dispatch: `BatteryConfig.dispatch_strategy: Optional[DispatchStrategyConfig]` (`battery.py:26`). `DispatchStrategyConfig(strategy_type ∈ {self_consumption, tou_optimized, peak_shaving}, peak_hours, import_limit_kw)` (config.py:313, validated in `__post_init__`). Built by `config._parse_dispatch_strategy_config(data)` (config.py:628) — **reusable**. `home._create_dispatch_strategy` maps it to the dispatch.py Strategy classes; it takes precedence over the simpler `HomeConfig.dispatch_strategy` string (`home.py:253-266`).
- **PV-age fields are owned by P3 (announced, not yet landed).** Per gap-register §D, P3 adds `system_age_years: float = 0.0` and `degradation_rate_per_year: float = 0.005` to **`PVConfig`** (not HomeConfig). The web parser builds `PVConfig(...)` directly, so it can set these once **task #16** lands the fields. Backward-compatible (omitting = age 0).
- **SEG is owned by task #2.** SEG today threads **only** via `ScenarioConfig.seg_tariff_pence_per_kwh` → `calculate_summary(seg=...)` on the CLI/output/fleet paths (`output.py:159`, `fleet.py:372`). **`HomeConfig` has no SEG field**, and the web's `jobs.py:_run_home_simulation` calls `calculate_summary(results)` with **no** SEG arg (`jobs.py:505`, `565`). Task #2 fixes export pricing *inside* `simulate_home`'s per-timestep `export_revenue` series (`home.py:310-314`) and unifies `net_cost`; it owns `home.py` (where `HomeConfig` lives). See §7 for the required SEG seam.
- **Fleet runner substrate is complete.** `config._parse_fleet_distribution_config(dict)` (config.py:1056) → `FleetDistributionConfig`; `config.generate_homes_from_distribution(cfg, location)` (config.py:1163) → `list[HomeConfig]`; `JobManager.submit_fleet_job(configs, start, end, ...)` (jobs.py:171) already runs a list of homes and aggregates `FleetResults`. The existing `form_to_fleet_distribution_config(data)` (fleet_config.py:93) already produces the dict shape `_parse_fleet_distribution_config` expects. **Nothing new in the engine is required to remove the 501** — only wiring.
- **The fleet sampler hardcodes per-home `tariff_config=None` / `dispatch_strategy="greedy"`** (config.py:1349-1350) and surfaces no SEG/PV-age. `generate_homes_from_distribution` is in `config.py` — **not P2-owned** — so per-home distribution of those fields is out of scope (§10). A fleet-*wide* overlay applied in the P2-owned runner via `dataclasses.replace` is in scope (§4).

Review context: `review/reports/summary-20260530T090214Z.md` ("Web fleet-from-distribution returns 501"; "Web home form lacks heat-pump / tariff / dispatch panels").

## 3. Sketch of approach

Two vertical slices, each proven by a form→engine boundary test:

**Slice A — single-home form parity.** Add form panels + extend `_parse_home_config` so a POST body carrying heat-pump / tariff / dispatch / SEG / PV-age fields produces a `HomeConfig` with the corresponding sub-configs populated. Reuse the canonical `config._parse_tariff_config` and `config._parse_dispatch_strategy_config` (consume-only) rather than re-implementing tariff/dispatch parsing; construct `HeatPumpConfig`/`PVConfig` directly (no canonical singular parser exists / web builds `PVConfig` directly).

**Slice B — fleet-from-distribution runner.** Replace the 501 with: `form_to_fleet_distribution_config(data)` → `config._parse_fleet_distribution_config` → `generate_homes_from_distribution(cfg, resolve_location(...))` → `submit_fleet_job(configs, start, end, ...)`, returning `201 {job_id, run_id}`. Then add a fleet-wide tariff/dispatch/SEG overlay that `dataclasses.replace`s the generated homes — keeping all engine-config mutation inside P2-owned files.

Cross-task ordering is handled by dependencies (§9): PV-age waits on #16, SEG waits on #2; the no-dependency deliverables (panels, 501-removal) front-load.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| SEG exposure | **Include**, with the SEG-wiring subtask depending on **#2** | Register mandates "surface SEG/tariff inputs but rely on #2 for the math". Making a web SEG input affect `net_cost` *requires* #2's engine surface — P2 does not own `jobs.py`/`home.py`, so it cannot route SEG itself. (User-confirmed.) |
| Dispatch surface | Expose the **richer `BatteryConfig.dispatch_strategy`** (`DispatchStrategyConfig`: self_consumption / tou_optimized / peak_shaving + peak_hours / import_limit_kw) | Maximises engine-capability parity (the PRD's purpose). It takes precedence over the simple `HomeConfig.dispatch_strategy` string in `home.py`. Only meaningful with a battery → surfaced inside the battery panel. (User-confirmed.) |
| Fleet parity | **Fleet-wide tariff/dispatch/SEG overlay** applied via `dataclasses.replace` in the P2-owned runner | Gives the distribution fleet the same financial/dispatch capability as single-home **without** modifying the `config.py` sampler (not P2-owned). Per-home *distribution* of these fields stays out of scope. (User-confirmed.) |
| Home parser strategy | Keep the hand-rolled `web/api.py:_parse_home_config`; **reuse** `config._parse_tariff_config` + `config._parse_dispatch_strategy_config`; construct `HeatPumpConfig`/`PVConfig` directly | Reusing the canonical tariff/dispatch parsers avoids drift on the complex types; a full switch to `config._parse_home_config` is a larger refactor and out of scope. |
| PV-age field source | Set `system_age_years` / `degradation_rate_per_year` directly on the `PVConfig(...)` the web parser builds | The web parser builds `PVConfig` directly; once #16 adds the fields, no further plumbing is needed. Depends on **#16** (not #17 — the web path does not use `config._parse_pv_config`). |
| Fleet location | Default Bristol via `resolve_location(data.get("location","bristol"))` | The fleet form sends no location today; Bristol is the project default. Adding a fleet location selector is optional polish (§11). |
| Backward compatibility | All new fields optional; omitting them reproduces today's behaviour | Existing presets, the explicit-home fleet path, and current web tests stay green. |

## 5. Pre-conditions for activating

- **Slice A panels (heat-pump, tariff, dispatch) + Slice B runner:** none — all substrate present today (§6).
- **PV-age exposure:** **task #16** must land the two `PVConfig` fields first.
- **SEG exposure (single-home + fleet overlay):** **task #2** must land a SEG rate on `HomeConfig` (§7 seam). Both are queued; the dependents declare the dependency.

## 6. Substrate verification (G3)

| Assumed capability | Evidence | Verdict |
|---|---|---|
| `HomeConfig.heat_pump_config` accepts `HeatPumpConfig` | `home.py:44`; `heat_pump.py:99` | present |
| `HeatPumpConfig(type, thermal_capacity_kw, annual_heat_demand_kwh)` validates | `heat_pump.py:114-135` | present |
| `HomeConfig.tariff_config` + reusable `config._parse_tariff_config` | `home.py:48`; `config.py:653` | present |
| `BatteryConfig.dispatch_strategy` + reusable `config._parse_dispatch_strategy_config` + `DispatchStrategyConfig` validation | `battery.py:26`; `config.py:628`, `config.py:313-363` | present |
| Engine consumes `BatteryConfig.dispatch_strategy` (Strategy pattern) | `home.py:145-160`, `home.py:253-266`; `dispatch.py:89/180/347` | present |
| `config._parse_fleet_distribution_config` (dict→`FleetDistributionConfig`) | `config.py:1056` | present |
| `generate_homes_from_distribution(cfg, location)` → `list[HomeConfig]` | `config.py:1163-1354` | present |
| `JobManager.submit_fleet_job(configs, …)` runs+aggregates a home list | `jobs.py:171-279`, `jobs.py:523-590` | present |
| `form_to_fleet_distribution_config(data)` already emits the parser's dict shape | `fleet_config.py:93-135` ↔ `config.py:1056-1072` | present |
| `resolve_location` (preset or `lat,lon`) | `shared.py:26-40` | present |
| `HomeConfig`/`BatteryConfig` are frozen → `dataclasses.replace` for overlay | `home.py:25`, `battery.py:10` | present |
| **PV-age fields on `PVConfig`** (`system_age_years`, `degradation_rate_per_year`) | **NOT present yet** — delivered by **task #16** | **queued prereq** |
| **SEG rate on `HomeConfig`** (so `simulate_home` prices export at SEG, no `jobs.py` change) | **NOT present yet** — required from **task #2** (see §7) | **queued prereq** |

**G3 verdict: pass.** All same-batch substrate verified present; the two missing capabilities (PV-age fields, HomeConfig SEG rate) are explicit queued prerequisites (#16, #2) and the consuming subtasks declare hard dependencies on them. No substrate fiction.

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **task #2** (pricing source of truth) | **consumes** | Web SEG selector → `HomeConfig` SEG rate → `simulate_home` prices `export_revenue` at SEG → `calculate_summary` sums series → `net_cost`. **No `jobs.py` change** *iff* #2 lands SEG on `HomeConfig`. | #2 owns the SEG math + the `HomeConfig` SEG field; **P2 owns the web widget + setting the field** | #2 pending; P2 SEG subtasks depend on #2. **Seam requirement recorded in gap-register §D.** |
| **task #16** (P3 α — PV-age engine wiring) | consumes | `PVConfig.system_age_years` / `degradation_rate_per_year` set by the web PV parser | #16 owns the `PVConfig` schema + degrading `simulate_pv_output`; P2 owns the form widgets | #16 pending; P2 PV-age subtask depends on #16. Contract = gap-register §D. |
| P3 (PV degradation) | consumes | (same fields, via #16) | as above | announced §D ✅ |
| task #9 (web financial chart tariff/SEG) | sibling | both depend on #2's pricing; #9 fixes `web/charts.py` hardcoded rates (not P2-owned) | #9 owns `web/charts.py` | independent; no file overlap with P2 |
| `config.py` `generate_homes_from_distribution` / sampler | consumes (read-only) | P2 *calls* it; fleet-wide overlay applied in P2 files via `dataclasses.replace` (no `config.py` edit) | engine / P3 (#17 for PV-age sampler) | P2 does not modify it |
| tasks #4, #5 | superseded | — | this PRD | cancel at decompose; replaced by the 5 subtasks |

**SEG seam — the one real coordination risk.** P2 asserts it can set a SEG rate on `HomeConfig`. That field does not exist yet; #2 must add it (the natural design: `home.py` is #2's file, `HomeConfig` lives there, and `simulate_home` reads `config.tariff_config` at `home.py:310` — a parallel `config.seg_*` is the obvious place). If #2 instead lands SEG only on `calculate_summary`'s param, the web path would need a `jobs.py` change that **no PRD owns** — an integration gap. **Mitigation:** (a) recorded as an explicit seam requirement in gap-register §D for #2's implementer; (b) P2's SEG subtasks depend on #2 so it lands first and the surface is known; (c) the SEG subtask binds to whatever field #2 lands and its boundary test is the arbiter. No reciprocal-ownership ambiguity otherwise: P2 owns every web form/parse file outright.

## 8. G5 note — why B + H

P2 is a **high-stakes integration PRD**: it crosses the web↔engine boundary, depends on two unlanded tasks (#2, #16), and its whole point is that a UI input must *actually reach and change* the simulation (the exact "fake-done leaf" hazard — a form field that's collected but silently dropped). Bare B (just ship the panels) is insufficient because a panel can look done while the parsed value never lands on the config. **Decision: B + H** — each slice carries a **two-way boundary test** asserting the form payload round-trips to a populated engine config (and, where an engine dep is involved, that the simulated output changes). These tests live in `tests/` against `web/api.py`, which P2 owns, so there is no seam violation (contrast P3 §8, which could not author them). They are the anti-fake-done mechanism for every leaf signal.

## 9. Decomposition plan

Five subtasks. **All five touch `web/api.py`**, so they are chained into a single linear dependency to serialise edits deterministically under the orchestrator's narrow-file-lock model (no cross-PRD contention — P2 owns the file outright). Order front-loads the two no-engine-dependency deliverables (panels, 501-removal); the engine-dependent ones (PV-age→#16, SEG→#2) follow.

Each leaf names a **user-observable signal** and a **boundary test** (G2/§8). Metadata fields `user_observable_signal`, `consumer_ref`, `substrate_confirmed` are recorded per task (not yet read by the orchestrator — see note).

### ① WEB-HOME-PANELS — heat-pump + tariff + battery-dispatch panels & parsing
- **Modules:** `web/templates/simulate/home.html`, new partials `heat-pump-config.html` / `tariff-config.html` (+ dispatch UI in `battery-config.html`), `web/api.py:_parse_home_config` (+ `tests/`).
- **Work:** add Heat Pump + Tariff tabs and a dispatch-strategy section in the battery tab. Extend `_parse_home_config` to build `HeatPumpConfig` (direct), `TariffConfig` (via `config._parse_tariff_config`), and `BatteryConfig.dispatch_strategy` (via `config._parse_dispatch_strategy_config`, only when a battery is enabled). All optional/back-compatible.
- **Deps:** none (substrate present). **Classification:** intermediate (front of the api.py chain).
- **Signal:** `POST /api/simulate/home` with `heat_pump`, `tariff`, and battery `dispatch_strategy` fields yields a `HomeConfig` whose `heat_pump_config`, `tariff_config`, and `battery_config.dispatch_strategy` are populated; boundary test on `_parse_home_config` asserts all three; the rendered home form shows Heat Pump + Tariff tabs and a dispatch selector.

### ② WEB-FLEET-RUNNER — remove the 501, run the distribution fleet
- **Modules:** `web/api.py:simulate_fleet_from_distribution` (+ a `_parse_date_range` helper factored from `_parse_home_config`), `web/fleet_config.py` (+ `tests/`).
- **Work:** replace the 501 with `form_to_fleet_distribution_config(data)` → `config._parse_fleet_distribution_config` → `generate_homes_from_distribution(cfg, resolve_location(data.get("location","bristol")))` → `submit_fleet_job(configs, start, end, db, data_dir, name)`; return `201 {job_id, run_id}`. Parse `days`|`start`/`end` like the home path.
- **Deps:** [①] (serialise `web/api.py`). **Classification:** intermediate.
- **Signal:** `POST /api/simulate/fleet-from-distribution` with a 3-home distribution returns **201** with `job_id`+`run_id` (not 501); a boundary test (mocking `JobManager.submit_fleet_job`) asserts it receives exactly 3 `HomeConfig`s sampled from the distribution; a `slow`-marked integration test runs a tiny fleet end-to-end and a fleet run lands in history with `n_homes==3`.
- **Consumer:** end-user (fleet page) + ⑤ (overlay extends this runner).

### ③ WEB-HOME-PVAGE — PV-array age inputs in the home form
- **Modules:** `web/templates/simulate/partials/pv-config.html`, `web/api.py:_parse_home_config` (`PVConfig` construction) (+ `tests/`).
- **Work:** add `system_age_years` + `degradation_rate_per_year` inputs to the PV panel; pass them into the `PVConfig(...)` the parser builds.
- **Deps:** [②, **#16**]. **Classification:** leaf.
- **Signal:** `POST /api/simulate/home` with `system_age_years=20` produces `PVConfig(system_age_years=20.0)`; boundary test asserts the field is set; with #16 landed, a `system_age_years=20` run reports ≈10% lower generation than an age-0 run (the engine-effect proof). PV panel shows both inputs.
- **Consumer:** end-user; consumes the `PVConfig` schema from **#16** (gap-register §D contract).

### ④ WEB-HOME-SEG — SEG export-rate selector in the home form
- **Modules:** `web/templates/simulate/partials/tariff-config.html` (SEG sub-section), `web/api.py:_parse_home_config` (set the `HomeConfig` SEG field) (+ `tests/`).
- **Work:** add a SEG export-rate input + `SEG_PRESETS` named-supplier dropdown (read-only from `seg.py`); resolve the selection to a pence/kWh rate and set it on the `HomeConfig` SEG field landed by #2.
- **Deps:** [③, **#2**]. **Classification:** leaf.
- **Signal:** `POST /api/simulate/home` with a SEG rate/preset produces a `HomeConfig` whose SEG field == the resolved rate (boundary test); with #2 landed, the run summary's `seg_revenue_gbp`/`net_cost` reflect the SEG rate (not the import rate). Tariff panel shows a SEG sub-section with preset names.
- **Consumer:** end-user; consumes #2's SEG surface (§7 seam).

### ⑤ WEB-FLEET-OVERLAY — fleet-wide tariff / dispatch / SEG
- **Modules:** `web/templates/simulate/fleet.html` (+ `static/js/fleet-simulator.js`), `web/api.py:simulate_fleet_from_distribution` + `web/fleet_config.py` (overlay) (+ `tests/`).
- **Work:** add a fleet-wide Tariff / Dispatch / SEG section to the fleet form; in the runner, after `generate_homes_from_distribution`, `dataclasses.replace` each home with the chosen `tariff_config`, `battery_config.dispatch_strategy` (where a battery exists), and SEG rate.
- **Deps:** [④, **#2**] (reuses ④'s SEG-on-HomeConfig wiring + ②'s runner). **Classification:** leaf.
- **Signal:** `POST /api/simulate/fleet-from-distribution` with a fleet-wide tariff + dispatch returns 201 and a boundary test asserts **every** generated `HomeConfig` carries that `TariffConfig` and `BatteryConfig.dispatch_strategy`; fleet form shows the new section.

> **Note for decompose-time:** the orchestrator does not yet consume the `user_observable_signal` / `consumer_ref` / `substrate_confirmed` metadata; recorded for a future tracking session. Tasks #4 and #5 are cancelled (superseded by ①–⑤). No separate manifest file is written — the G3/G6 capability→evidence bindings live in §6/§12 (matching the P3 PRD precedent).

## 10. Out of scope

- **Per-home distribution** of tariff / dispatch / SEG / PV-age across a fleet → requires editing the `config.py` sampler (`generate_homes_from_distribution`), which is **not P2-owned**. (Fleet-*wide* overlay is in scope; PV-age fleet sampler is #17's.)
- The **pricing/SEG math** itself (export-at-SEG, `net_cost` unification, `SEG_PRESETS` engine wiring) → **task #2**. P2 only surfaces inputs.
- The **web financial chart** hardcoded rates (`web/charts.py:449-450`) → **task #9**.
- **CLI** home-form parity (`cli/home.py` hand-builder) → **task #14**.
- Switching the web home parser to the canonical `config._parse_home_config` (larger refactor; the hand-rolled parser is retained and extended).
- A full **`ScenarioConfig`** round-trip / scenario-file save of the new home fields (the home form posts a flat JSON body, not a scenario).

## 11. Open questions (tactical — deferred, not design-blocking)

1. **Exact `HomeConfig` SEG field name from #2.** ④/⑤ bind to whatever #2 lands (field name/type). The dependency guarantees #2 is done first; the boundary test is the arbiter. If #2 lands SEG *not* on `HomeConfig`, raise a `SEAM QUESTION` in gap-register §D before implementing ④ (see §7 mitigation).
2. **Dispatch panel placement.** Battery-dispatch lives on `BatteryConfig`, so it is only meaningful with a battery — render it inside the battery tab gated on `battery_enabled`, or as its own tab disabled without a battery. Decide during ①.
3. **`peak_hours` editor UX** for `tou_optimized` (repeatable start/end rows) vs a simple preset (e.g. 16:00–19:00). Ship a minimal repeatable-rows editor; refine later.
4. **Fleet location selector.** The fleet form sends no location (defaults Bristol). Adding a preset/custom selector mirroring the home form is optional polish; decide during ② or ⑤.

## 12. G6 — premise validity of leaf signals

- **① panels:** signal asserts only field-population (sub-configs present after parse) — directly verifiable, no numeric/capability claim. **Pass.**
- **② runner:** asserts the endpoint returns 201 and `submit_fleet_job` receives N=3 homes — produced entirely by this task's own wiring over present substrate (§6). No number claimed beyond the input N. **Pass.**
- **③ PV-age:** asserts field-population now, and (post-#16) ≈10% lower generation at age 20. The 10% bound is **#16/P3's** proven property (`factor = 1 − 20·0.005 = 0.90`, `test_pv.py` asserts 0.90), inherited via the dependency — not an independent P2 claim; P2 only proves its input reaches `PVConfig`. **Pass** (premise owed-and-supplied by the declared prereq #16).
- **④ SEG:** asserts the SEG field is set to the resolved rate (field-population, verifiable), and (post-#2) that the summary reflects SEG pricing — the SEG math is **#2's** proven property, inherited via the dependency. P2's own claim is only the field round-trip. **Pass** (premise owed-and-supplied by #2).
- **⑤ overlay:** asserts *every* home carries the fleet-wide tariff/dispatch — a `dataclasses.replace` over the list this task controls; fully producible from its own dependency set (②'s runner + ④'s SEG wiring + #2). **Pass.**

No signal asserts a number or capability its own task (plus its declared prerequisites) cannot produce. **G6 pass.**
