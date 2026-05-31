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

### P4 — TOU grid-charging / battery arbitrage (subsumes task #8)  ·  Status: **QUEUED**
- **Gap:** `flow.py:245` — charging the battery from the grid during cheap TOU periods is a comment-only "future enhancement"; the TOU path only charges from excess PV. Limits arbitrage realism.
- **Owns:** `flow.simulate_timestep_tou` + `flow.simulate_timestep`, the rate-aware grid-charge controller in `dispatch.py` (`compute_grid_charge_power_kw` + `GridChargeContext` + `DispatchDecision.grid_charge_kw`), and the **new `GridChargeConfig` schema on `BatteryConfig`** (battery.py) + its `config.py` parser. Must preserve the energy-balance invariant (`validate_energy_balance`) — done via source-split charge accounting (PRD §3.1).
- **Consumes (don't modify):** SEG/import pricing from **#2** (arbitrage economics depend on correct TOU pricing — do not re-touch home.py financial accounting). The two unrelated `TariffPeriod` symbols are avoided structurally: the dispatch.py controller is float-only and imports neither.
- **Decided (user-confirmed):** config = nested `GridChargeConfig` on `BatteryConfig` (rides `battery.config` into the function path, zero new args); trigger = round-trip **spread test** + **target SOC**; **both** dispatch paths covered; Strategy path uses **explicit per-strategy** `DispatchDecision.grid_charge_kw` with per-strategy serialized tasks (TOUOptimized, PeakShaving) chained on `dispatch.py` for collision safety. Approach **B + H** (split-accounting contract + two-way balance/economics boundary tests).
- **PRD file:** `docs/prds/tou-grid-charging-battery-arbitrage.md` (committed `d11f963`) · manifest `docs/prds/tou-grid-charging-battery-arbitrage.capability-manifest.md` (`d11f963`) · **Subtasks queued:** **#23** (α — dispatch core: controller + `DispatchDecision.grid_charge_kw`) → **#25** (α2 — TOUOptimized grid-charge; dep #23) → **#26** (α3 — PeakShaving grid-charge; dep #25, serialises dispatch.py) ; **#24** (β — `GridChargeConfig`/`BatteryConfig` schema + parser) ; **#27** (γ — flow split-accounting both call sites; dep #23+#24) ; **#28** (ε — home.py strategy-path tariff threading; dep #27+**#2**) ; **#29** (δ — arbitrage economics + demo scenario; dep #27+**#2**). Placeholder **task #8 cancelled** (superseded).

### P5 — Inter-home / community energy sharing (subsumes task #6)  ·  Status: **QUEUED**
- **Gap:** homes are simulated independently; no inter-home power-sharing / community battery / virtual net metering. README frames it as a "future phase" but the user treats it as real work.
- **Owns (new):** a new sharing/aggregation layer `src/solar_challenge/community.py` (`CommunityConfig`, `CommunityResults`, `simulate_community`, `validate_community_balance`, VNM billing). **Decision: `fleet.py`'s public API is left UNCHANGED** — the layer *consumes* `FleetResults` through its existing aggregate properties (no fleet-encapsulation violation, no logic duplication — per user directive). Also owns new `config.py` functions (`_parse_community_config`, `load_community_config`), the `cli/fleet.py run` community branch, and `output.generate_community_report`.
- **Consumes (don't modify / don't duplicate):** per-home `simulate_home` outputs (`SimulationResults`); `fleet.FleetResults` aggregate API (`total_grid_export`/`total_grid_import`); `flow.simulate_timestep` + `dispatch.SelfConsumptionStrategy` + `battery.Battery` + `flow.validate_energy_balance` (reused verbatim for community-battery dispatch + per-timestep balance); `tariff.TariffConfig`/`seg.py` pricing primitives from **#2** (VNM billing leaf only).
- **Seam:** P5 owns the sharing layer end-to-end. **`simulate_fleet` / `FleetResults` / `FleetConfig` / `simulate_fleet_iter` signatures are UNCHANGED — P2 #19/#22 need NO adaptation** (see §D announcement). Energy-balance invariant extended to the community level as a *composition theorem* (proven in PRD §3.1); per-home seed model untouched (community layer is deterministic post-hoc).
- **PRD file:** `docs/prds/inter-home-community-energy-sharing.md` (committed `5803492`) · manifest `docs/prds/inter-home-community-energy-sharing.capability-manifest.md` (`5803492`) · **Subtasks queued:** **#30** (α — community.py core: P2P netting + `validate_community_balance` + result types) → **#31** (β — community battery layer; dep #30, serialises community.py) ; **#32** (γ — `config.py` parser + `load_community_config`; dep #30) ; **#33** (δ — `fleet run` community branch + `generate_community_report` + demo scenario; **integration-gate leaf**, dep #30+#31+#32) ; **#34** (ε — VNM £ billing slice; dep #31+#33+**#2**). Placeholder **task #6 cancelled** (superseded). Approach **B + H** (composition-theorem contract + two-way balance/economics boundary tests).

---

## C. Cross-PRD seam ownership

| Seam / file | Owner | Consumers (must not redefine) |
|-------------|-------|-------------------------------|
| **`pv.py` `PVConfig` schema** (new `system_age_years`, `degradation_rate_per_year`) — *not* HomeConfig | **P3** | P2 (web form) — wired by **#20** (depends on #16); #14 (CLI) — wire once P3 announces field (see §D; announced ✅) |
| `web/api.py` form parsing (`_parse_home_config`, fleet-from-distribution) | **P2** | — · queued as **#18/#19/#20/#21/#22** (PRD `docs/prds/web-ui-engine-capability-parity.md`) |
| `web/fleet_config.py` | **P2** | — · runner **#19** + overlay **#22** |
| `web/app.py` blueprint registration | shared pattern; **P1** adds assistant bp | P2 (existing bps unchanged) |
| `web/database.py` `chat_messages` | **P1** | — |
| `flow.py` / `dispatch.py` TOU dispatch | **P4** | — · queued **#23**(α dispatch core)→**#25**(α2 TOU)→**#26**(α3 PeakShaving), **#24**(β config), **#27**(γ flow), **#28**(ε home wiring), **#29**(δ economics) · PRD `docs/prds/tou-grid-charging-battery-arbitrage.md` |
| `battery.py` `BatteryConfig` schema (new `grid_charging: GridChargeConfig`) + `config.py` `_parse_battery_config` | **P4** (queued **#24**) | P2 consumes existing `BatteryConfig.dispatch_strategy` only — new optional `grid_charging` field is additive, no conflict |
| `home.py` financial accounting / `seg.py` pricing | **task #2** (not a PRD) | P2, P4 depend on it; do NOT re-fix |
| `fleet.py` simulation/aggregation | **P5** (owns; **left UNCHANGED** — see §D) | P2 (calls `simulate_fleet` — no adaptation needed) |
| **`community.py`** (new sharing/aggregation layer) | **P5** (queued **#30**→**#31**, **#33**, **#34**) | — · PRD `docs/prds/inter-home-community-energy-sharing.md` |
| `config.py` `_parse_community_config` / `load_community_config` (new fns) | **P5** (queued **#32**) | — · **disjoint** from P3 `#17` (`_parse_pv_config`) + P4 `#24` (`_parse_battery_config`) regions; file-lock serialises |
| `cli/fleet.py` `run` community branch + `output.generate_community_report` | **P5** (queued **#33**) | — · P5-only among PRDs (P2 owns `web/`; #14 owns `cli/home.py`) |
| test markers (`slow`/`integration`), mypy strict | **tasks #11/#12** | all PRDs: mark new real-PVGIS tests `slow`; keep mypy green |

## D. Notes / open seam questions
- _(spawned sessions append here)_

### 📢 P4 announcement — `GridChargeConfig` on `BatteryConfig` (additive; web/CLI may later expose)

P4 (PRD `docs/prds/tou-grid-charging-battery-arbitrage.md`, task **#24**) adds an optional nested config object to `solar_challenge.battery.BatteryConfig` (frozen dataclass). **Additive and backward-compatible — `None` = disabled = today's behaviour. Consume as-is; do not redefine:**

| Field (on `BatteryConfig`) | Type | Default | Meaning |
|---|---|---|---|
| `grid_charging` | `Optional[GridChargeConfig]` | `None` | Presence enables TOU grid-charging; `None` disables. |

`GridChargeConfig` (frozen, in `config.py` beside `DispatchStrategyConfig`): `target_soc_fraction: float = 0.9` (fill ceiling as a fraction of capacity; `0 < x <= 1`).

- **YAML surface (under the `battery:` block):** `battery.grid_charging.target_soc_fraction`. Parsed by `_parse_battery_config` (#24).
- **Effect:** only on the rate-aware TOU paths (function `simulate_timestep_tou` and the Strategy-pattern path with a tariff). Inert without a tariff; the round-trip spread gate makes it a no-op on flat tariffs.
- **For P2/#14 (NOT required by P4):** a future web/CLI toggle for `battery.grid_charging` is a candidate follow-up, **out of scope for P4** — P4 ships the engine + YAML surface only.

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

### 📢 P5 announcement — `fleet.py` public API UNCHANGED; community sharing is a new `community.py` layer (P2 needs NO adaptation)

P5 (PRD `docs/prds/inter-home-community-energy-sharing.md`, tasks **#30–#34**) implements inter-home / community energy sharing as a **post-hoc aggregation layer that consumes `FleetResults`** — it does **not** modify `fleet.py`. **For P2 (#19 fleet-from-distribution runner, #22 fleet overlay): the seam you call is unchanged — consume as-is, no adaptation required:**

| Symbol (in `fleet.py`) | Change | Note |
|---|---|---|
| `simulate_fleet(config, start, end, validate_balance=True, parallel=True, max_workers=None) -> FleetResults` | **NONE** | Same signature, same return type. |
| `FleetResults` (`per_home_results`, `home_configs`, `total_grid_*`, …) | **NONE** | Community layer reads its public aggregate properties read-only. |
| `FleetConfig` | **NONE** | Community config is a **separate** `community:` YAML block parsed by `config.load_community_config` (#32) — **not** a `FleetConfig` field. P2's `FleetConfig(homes=...)` is unaffected. |
| `simulate_fleet_iter` | **NONE** | Parallelism model untouched. |

- **Where community sharing lives:** new module `src/solar_challenge/community.py` — `simulate_community(fleet_results: FleetResults, config: CommunityConfig) -> CommunityResults`. The CLI (`fleet run`, #33) calls `simulate_community` *after* `simulate_fleet` when a `community:` block is present. Higher layer (community) depends on lower (fleet); fleet has no knowledge of community.
- **Energy-balance invariant:** extended to the community level as a **composition theorem** over the per-home balances + the reused `flow.validate_energy_balance` (PRD §3.1) — `validate_community_balance`. No change to `flow.validate_energy_balance` itself.
- **`config.py` file-lock (for P3/P4 awareness):** P5 #32 adds only **new** functions (`_parse_community_config`, `load_community_config`) — disjoint from P3 #17 (`_parse_pv_config`/`PVDistributionConfig`) and P4 #24 (`_parse_battery_config`). No logical conflict; the orchestrator's narrow file-lock serialises concurrent `config.py` edits.
- **For P2/web (NOT required by P5):** a future web surface for community sharing is a candidate **P2 follow-up**, out of scope for P5 (engine + CLI + YAML only).
- **VNM billing → task #2:** the P5 billing leaf (#34) reuses #2's canonical `seg.py`/`TariffConfig` pricing (dep #34→#2 wired) — it does **not** add a third pricing path; do not re-fix pricing in P5.
