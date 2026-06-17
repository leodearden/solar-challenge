# PRD — Flexibility value → finance integration (W1)

- **Source:** 2026-06-15 deployment-readiness survey §5/§8 (workstream **W1**) + §9 capability-scope refinement. Consulting model: `/home/leo/mission-control/consulting/solar-challenge/2026-06-16-flexibility-value-buildability-model.md`. Brief: `/home/leo/.claude/spawn-briefs/solar-w1-flexibility-value.md`.
- **Status:** active · authored 2026-06-17 · **board-gated** (ResNet board meeting Friday 2026-06-19).
- **Owner seam:** a **new `flex.py` value-model module** (the banded Low/Central/High decomposition + grid-services parameter resolver) + **fleet-wide TOU-tariff threading** in `config.py` (`generate_homes_from_distribution`) + a board scenario in `scenarios/` + a buildability/risk note in `docs/`. W1 **delivers values into** a W2-owned `FinanceConfig` grid-services field — it does **not** add that field.
- **Approach:** **B + H** (contract + two-way boundary tests). High stakes: board-facing numbers, a load-bearing finance seam shared with W2, and ≥2 cross-PRD consumers (W2 valuation, W3 ranking). See §8/§9.

---

## 1. Goal — what ships, and what a user observes

The simulator's finance layer (W2) and install-config ranking (W3) currently ignore the **single largest value stream** for a battery fleet: flexibility value (~£280/battery-home/yr central ≈ **10× the project's £27/home surplus** — consulting model §0). This PRD makes that value **flow into the economics** so the cost-recovery solve and the householder bill reflect it.

The flexibility value has two physically-distinct parts, and this PRD treats them differently (the **resolved design fork**, §6):

| Part | Central | Nature | How it reaches finance |
|---|---|---|---|
| **Time-shift** (TOU/wholesale arbitrage, smart export, improved self-consumption) | ~£250 | **Endogenous physics** — the simulator already models it | Fleet runs on a TOU tariff + grid-charging → cheaper graded `import_cost` → lower `net_annual_bill` (today, correctly) |
| **Grid-services topper** (DFS + DNO local flex via a P483 aggregator, net of share) | ~£30 | **Exogenous parameter** — DFS/DNO income is not per-home physics | A new W2-owned `FinanceConfig` field that W1 fills (Low/Central/High) |

**User-observable surfaces when this lands:**
- A user runs `solar-challenge finance` on the new **board scenario** (fleet on Economy-7 + grid-charging) and sees a battery home's **net annual bill is lower** than the same home with arbitrage off, by a per-battery-home **time-shift saving that lands in the £100–330 research band** — reported alongside the banded grid-services figure.
- Setting the **grid-services band** (Low/Central/High) on the scenario's finance config **moves the project surplus** (W2's consuming math) by `n_battery_homes × band£`; the default leaves existing economics and the θ calibration **bit-identical**.
- W3's ranking (min householder bill) now **orders configs by per-config arbitrage benefit** — a 10 kWh battery out-arbitrages a 5 kWh one — because the time-shift lands in the bill it ranks on.
- A committed **buildability/risk note** in `docs/` records the prerequisites (P483 aggregator, MID asset meters, NGED CMZ confirmation, G99/G100) and the one HIGH risk, traceable from the value model.

---

## 2. Background

- **The value model already exists** (consulting doc, 2026-06-16): Low £120 / Central £280 / High £450 per battery-home/yr, decomposed as time-shift (~£100/£250/£330) + grid-services net (~£4/£30/£120). Cross-checks against *The Sun Pays* (£1,009/home/yr NOI, flex 36%). Recommends the **Central** case for Friday; flex is the soft, assumption-sensitive line.
- **The arbitrage physics is already built and merged** (PRD `tou-grid-charging-battery-arbitrage.md`, tasks #23–#29 `done`): `compute_grid_charge_power_kw` (spread gate), `TOUOptimizedStrategy`/`PeakShavingStrategy` grid-charging, `flow.simulate_timestep`/`simulate_timestep_tou` execute it, and `scenarios/bristol-arbitrage.yaml` proves `net_cost(grid_charge ON) < net_cost(OFF)`. `home.py:322` prices grid import **per-timestep at the TOU rate**, so cheap-rate charging genuinely lowers `total_import_cost_gbp`.
- **The W2 financial layer has landed** (`finance.py`: `householder_bill`, `project_multi_year`, `project_economics`, `spreadsheet_revenue_curve`; θ calibration task #48 `done`). `FinanceConfig` lives at `config.py:478` and has **no flex field yet** — the **W2 cost-recovery amendment** (concurrent session) adds it.
- **The gap this PRD fills:** fleet-distribution homes are hardcoded `tariff_config=None` (`config.py:~1579`), so the canonical fleet **sees zero arbitrage value today**; and there is no grid-services income channel into the economics at all.

---

## 3. Sketch of approach

**Time-shift = physics, surfaced at fleet scale.** Thread a fleet-wide TOU tariff + grid-charging onto distribution-generated homes (the only substrate gap), then ship a board scenario where the arbitrage saving appears in the householder bill. The mechanism is already wired end-to-end at the single-home/timestep level; W1 lifts it to the fleet and the board surface.

**Grid-services = a banded parameter W1 fills into W2's field.** W1 owns a `flex.py` value-model that holds the canonical Low/Central/High decomposition and resolves a band → grid-services £/battery-home/yr. W2's amendment owns the `FinanceConfig` field and the math that consumes it.

**Valuation/split stays with W2.** How the time-shift value is split between deeper householder savings and project surplus (the own-use-rate cost-recovery solve), and the correction of the self-consumption-inflation in `project_multi_year`'s `fleet_revenue` (§9), are **W2's consuming-math** — coordinated, not in W1's scope. W1 surfaces the physics and supplies the parameter values.

---

## 4. Why this shape (the resolved design fork)

The brief flagged "one parameter vs physics + parameter" as a real fork. Resolved with Leo (2026-06-17):

1. **Flex architecture → physics drives the time-shift** (not a flat parameter). The arbitrage physics already exists and is the more honest, per-config-varying basis; W3 needs per-config arbitrage to rank install configs correctly (a bigger battery has more arbitrage headroom). Only the exogenous grid-services topper is a parameter.
2. **W1/W2 boundary → W1 = physics method; W2 = valuation.** The time-shift reaches the **householder bill** correctly **today** (`import_cost → net_annual_bill`), and since **W3 ranks on min householder bill**, A3's per-config arbitrage goal is met through the already-correct path. The **project-surplus** path computes `fleet_revenue = self_consumption_saving + seg_export` only, so it captures arbitrage only via an **overstated** self-consumption inflation (grid-charged discharge valued at full retail) — correcting that is **W2-owned** `finance.py` accounting (the consuming math the brief assigns to W2), not W1's lift for Friday.

---

## 5. Pre-conditions for activating

- **Landed (verified):** the arbitrage dispatch path (`dispatch.py`/`flow.py`, tasks #23–#29), TOU tariffs (`tariff.py`), per-timestep TOU import pricing (`home.py`), and the W2 base financial layer (`finance.py`; `householder_bill`, `project_multi_year`, `project_economics`).
- **Blocked-on-consumer (out-of-batch dependency):** task **δ** (grid-services parameter → economics) depends on the **W2 cost-recovery amendment** adding the `FinanceConfig` grid-services field + wiring it into the economics. As of authoring the amendment is **not yet on disk** (no flex/grid-services field in `config.py`). δ is queued behind it; the field name is the agreed seam (§8).
- **Calibration guard (META):** β threads a fleet tariff **only when the scenario specifies one**; the θ calibration scenario (`bristol-fin-calibration.yaml`, no `tariff:` block) and all existing finance YAMLs are unchanged. The δ grid-services field defaults `0.0`. θ/#48 stays green.

---

## 6. Resolved design decisions

1. **Time-shift is physics; grid-services is a parameter.** No `FinanceConfig` field for time-shift. The W2-owned field holds **grid-services income only** (~£30 central), **not** the full £280 — communicated to the W2 session via fused-memory.
2. **Grid-services bands (net of aggregator share), £/battery-home/yr:** Low **4** / Central **30** / High **120** (consulting §1.1/§1.4). Modelled as base (~£15–25 gross DFS + partial local flex) + upside (~£40–50 gross with a confirmed active Bristol CMZ) **via a partnered aggregator — not self-VLP** (not viable at 100 homes). Never assert above the High case; DNO local flex is **£0 outside an active NGED constraint zone**.
3. **Time-shift expected band (for validating the physics, not a parameter):** Low ~**100** / Central ~**250** / High ~**330**. The board scenario's per-battery-home arbitrage saving is asserted to fall **within** this band — a band-membership sanity check, **never** a point estimate (§9, G6).
4. **Canonical board tariff = Economy-7** (off-peak 0.09 / peak 0.25 £/kWh, 00:30–07:30), matching `bristol-arbitrage.yaml`. The tariff choice is now load-bearing (it sets the spread that bounds the time-shift), so it is pinned here for reproducibility.
5. **Central is the headline case for Friday.** The board scenario defaults to Central; Low/High are selectable for sensitivity.
6. **Buildability is assessed, not built.** ε is a documentation deliverable referencing the consulting doc; no OpenADR VEN / aggregator integration is built here.

---

## 7. Out of scope for this PRD

- **Surplus-side valuation + bill/surplus split + the self-consumption-inflation fix** in `project_multi_year`'s `fleet_revenue` — **W2** (the cost-recovery amendment's consuming math). §9 documents the issue for the W2 session.
- **Per-home island / backup scenario** (consulting §3) — UK pays ~£0; resilience/mission value, separately costed. A capability spec, not Phase-1 finance.
- **Full OpenADR VEN / aggregator build** — buildability is *assessed* (ε), not built.
- **Self-registered VLP / Balancing-Mechanism** grid-services — below the ~1 MW practical floor at 100 homes (consulting §1.4); excluded from the band.
- **The round-trip-loss import-cost convention** (§9 known limitation) — pre-existing `flow.py`/`home.py` accounting; a candidate W2 follow-up, not a W1 blocker.

---

## 8. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **W2** `docs/prds/financial-layer-battery-fidelity.md` (+ its **cost-recovery amendment**, concurrent) | W1 **produces → W2 consumes** | New `FinanceConfig` **grid-services** field — proposed `grid_services_income_per_battery_home_gbp: float = 0.0` (additive, default 0.0, θ-safe); W1 fills Low 4 / Central 30 / High 120 | **W2 owns** the field + the consuming economics/bill math + the surplus-side valuation/split + the self-consumption-inflation fix. **W1 fills** the values + supplies the physics method (fleet TOU+grid-charging) + buildability | **field not yet on disk**; seam recorded in fused-memory; δ queued behind the W2 amendment |
| **W2** `finance.py` `householder_bill` / `home.py` import pricing | W1 **consumes (read-only)** | Time-shift reaches `import_cost → net_annual_bill` via the already-landed TOU import pricing | W2 owns the functions; W1 only enables the fleet to exercise them (β/γ) | landed; no W2 change required for the time-shift→bill path |
| **W3** `docs/prds/discrete-install-config-sweep.md` | W1 **produces → W3 consumes** | W3 ranks on **min householder bill**, which now reflects per-config arbitrage (via the board scenario's TOU+grid-charging) | **W3 consumes passively**; W3 must run on the TOU+grid-charging fleet scenario to capture per-config time-shift (a **W3 coordination item** when W3 resumes) | W3 authored 2026-06-16, queue-gated on W2; **add W1 board scenario to W3's pre-conditions** |
| Consulting model `2026-06-16-flexibility-value-buildability-model.md` | W1 **references** | Provenance for the bands + the buildability assessment (ε) | the consulting doc (read-only reference) | landed |

**Reciprocal-ownership resolution.** The brief's mirror (W2 brief states "W2 owns the field, W1 fills") is honoured: W1 adds **no** `FinanceConfig` field and edits **no** `finance.py` valuation math. The only `config.py` change W1 makes is the **fleet-tariff threading** (β), disjoint from `_parse_finance_config`.

---

## 9. Contract + boundary-test sketch (B + H)

### 9.1 Contract — the three seams

**Seam 1 — fleet-tariff threading (β, W1-owned).**
```
generate_homes_from_distribution(dist_config, location, *, fleet_tariff=None, fleet_grid_charging=None) -> list[HomeConfig]
```
- When `fleet_tariff` (a `TariffConfig`) is provided, every generated home inherits it as `tariff_config`; when `fleet_grid_charging` is provided, every battery home inherits the grid-charging spec. The scenario parser passes the scenario-level `tariff:` + `battery.grid_charging:` through.
- **Invariant (calibration-safe):** when neither is provided, behaviour is **bit-identical** to today (`tariff_config=None`). θ/#48 and every existing fleet YAML are unchanged.

**Seam 2 — grid-services parameter (δ ↔ W2).**
- W2 adds `FinanceConfig.grid_services_income_per_battery_home_gbp: float = 0.0` (final name W2's call; W1 references the agreed name). W1's `flex.resolve_grid_services_band(band: "low"|"central"|"high") -> float` returns 4/30/120.
- **Invariant:** default `0.0` → economics bit-identical to non-flex runs. Additive: the field enters project revenue (or the own-use-rate solve) as `n_battery_homes × field` — **W2's math**.

**Seam 3 — time-shift physics → bill (γ, read-only on W2).**
- With the board scenario (TOU + grid-charging), `householder_bill(...).import_cost_gbp` (hence `net_annual_bill_gbp`) is **lower** than the arbitrage-off baseline. No W2 code change.
- **Invariant:** with grid-charging off / no tariff, results are bit-identical to non-flex runs.

### 9.2 Boundary tests (both sides of each seam)

| Scenario | Preconditions | Postcondition (asserted) | Faces |
|---|---|---|---|
| Fleet inherits TOU tariff | scenario sets `tariff: economy_7` + `battery.grid_charging` | every generated home has `tariff_config != None` + grid-charging; a fleet run's `total_import_cost_gbp` reflects TOU rates | producer (β) |
| Fleet tariff absent ⇒ unchanged | scenario with **no** `tariff:` | generated homes `tariff_config is None`; fleet run bit-identical to pre-β | producer (β) — **θ guard** |
| Time-shift in the bill | board scenario, arbitrage ON vs OFF (grid_charging toggled) | battery home `net_annual_bill_gbp(ON) < (OFF)`; per-battery-home delta ∈ **[£100, £330]** (annualised) | producer (γ) / consumer (W3 bill) |
| Grid-services moves surplus | board scenario, grid-services band ∈ {low,central,high} | project surplus rises by ≈ `n_battery × {4,30,120}`; band selectable, moves the number | consumer (δ↔W2) — **blocked on W2 amendment** |
| Grid-services default ⇒ θ-safe | field unset / `0.0` | economics + θ calibration bit-identical | consumer (δ↔W2) |
| Battery vs no-battery flex increment | one battery home, one no-battery home | they differ by the flex increment (time-shift in bill + grid-services on battery home only) | integration (γ+δ) |

### 9.3 Known limitation (documented, not fixed here)

`project_multi_year` computes `fleet_revenue = Σ(self_consumption_saving + seg_export)`; because `flow.py:276` counts **battery discharge of grid-charged energy as self-consumption**, valued at full retail, the **project-surplus** view of the time-shift is **overstated**. Separately, `home.py` prices `grid_import` (which includes post-charge-efficiency stored energy) rather than the larger grid-side draw, making the **bill-level** time-shift ~8% **optimistic**. Both are **W2 consuming-math** concerns; the board scenario reports the time-shift via the **bill** path (where it is correct in sign and order) and asserts only **band membership**, so neither blocks W1. Flagged to the W2 session via fused-memory.

---

## 10. Decomposition plan

Greek labels are intra-batch; task IDs assigned at decompose. **B+H phasing:** α/β are foundation; γ/δ are the vertical-slice integration gates; ε is the companion assessment.

- **α — `flex.py` value-model module** · *modules:* `src/solar_challenge/flex.py` (new), `tests/unit/test_flex.py` · *intermediate (unlocks γ, δ, ε).*
  - Frozen dataclass(es) holding the canonical Low/Central/High decomposition (time-shift band + grid-services band + totals + provenance refs) and `resolve_grid_services_band(band) -> float`.
  - **Signal:** unit test — `resolve_grid_services_band("central") == 30.0`; the three bands expose the documented time-shift + grid-services components; totals match the consulting §1.1 table (within the doc's banding).
  - **Unlocks:** γ (time-shift expected band), δ (grid-services value), ε (decomposition for the note).

- **β — fleet-wide TOU-tariff threading** · *modules:* `src/solar_challenge/config.py` (`generate_homes_from_distribution` + scenario parse), `tests/unit/test_config.py` · *intermediate (unlocks γ).*
  - Thread scenario-level `tariff:` + `battery.grid_charging:` onto distribution homes (Seam 1). Guard: absent ⇒ `tariff_config=None`, bit-identical.
  - **Signal:** unit test — a `fleet_distribution` scenario with `tariff: economy_7` yields homes with `tariff_config != None` + grid-charging; a scenario without `tariff:` yields `tariff_config is None` (regression-pinned against θ).

- **γ — board scenario + annual time-shift figure (integration gate)** · *modules:* `scenarios/bristol-phase1-flex.yaml` (new), `tests/integration/test_flex_timeshift.py` (new), `output.py` (report line) · *leaf · prereqs: α, β.*
  - Fleet board scenario: Economy-7 + grid-charging batteries, ~annual period (or annualised). The finance report shows the per-battery-home time-shift saving alongside the grid-services band.
  - **Signal:** integration test — battery home `net_annual_bill_gbp(arbitrage ON) < (OFF)`; the annualised per-battery-home time-shift delta ∈ **[£100, £330]**; `validate_energy_balance` holds across the run.
  - **G6:** asserts an **inequality** (mechanism proven by #29) + **band membership**, never a point value.

- **δ — grid-services parameter → economics (seam gate)** · *modules:* `scenarios/bristol-phase1-flex.yaml` (finance block), `tests/integration/test_flex_grid_services.py` (new) · *leaf · prereqs: α, **W2 cost-recovery amendment (out-of-batch)**.*
  - Set the resolved grid-services band on the board scenario's `finance` config (W2's field). 
  - **Signal:** integration test — selecting band ∈ {low,central,high} moves the project surplus by ≈ `n_battery × {4,30,120}`; default/unset leaves economics + θ bit-identical; a battery home and a no-battery home differ by the flex increment.
  - **Blocked-on-consumer** until the W2 amendment lands the field; the field name is the agreed seam (§8).

- **ε — buildability/risk note** · *modules:* `docs/flexibility-buildability.md` (new) · *leaf · prereqs: α.*
  - Short note: the banded value model summary; prerequisites (**P483-capable aggregator**, **MID asset meters** EM530/EM540, **NGED CMZ confirmation** email, **G99/G100** compliance — the one HIGH risk); reference to the full consulting doc; the out-of-scope items (§7).
  - **Signal:** doc committed at the path, lists the 4 prerequisites + the HIGH risk rating, and is linked from this PRD and `flex.py`'s module docstring.

**Decomposition note:** queue α/β/ε immediately; γ depends on α+β; **δ must not be queued until the W2 cost-recovery amendment's grid-services field is `done`/merged** (mirror of the W2/W3 inverter-capex precedent, task #49).

---

## 11. Capability manifest (draft — committed at decompose)

Per-leaf G3+G6 bindings; any FAIL blocks queueing.

- **γ (time-shift integration):**
  - `compute_grid_charge_power_kw` / `simulate_timestep_tou` grid-charge path → **PASS** `grep:src/solar_challenge/flow.py` wired into the fleet run via β; proven by task #29 (`net_cost ON<OFF`).
  - per-timestep TOU import pricing → **PASS** `grep:src/solar_challenge/home.py:322` (`r.grid_import * rate`).
  - numeric band `[£100,£330]` → **PASS (band, not floor):** Economy-7 spread 0.16 £/kWh × ~usable battery × annual cycles brackets the band; signal asserts **membership + inequality**, not a point estimate. No analytical-floor violation (not an accuracy bound).
- **β (fleet-tariff threading):**
  - `generate_homes_from_distribution` tariff seam → **PASS** producer-in-batch (β itself); calibration-safe invariant pinned by a θ regression test.
- **δ (grid-services parameter):**
  - `FinanceConfig.grid_services_income_per_battery_home_gbp` → **FAIL until W2 amendment lands** (`producer-absent` today). Resolution (G3-b): queue **upstream** of δ as the W2 cost-recovery amendment task; wire the dep; do not queue δ before it merges.
  - grid-services values 4/30/120 → **PASS** within consulting §1.1/§1.4 bounds; never above the High case.
- **α (value-model):** pure constants + resolver, no novel substrate → **G3 N/A**; values bounded by the consulting doc.
- **ε (buildability note):** documentation deliverable; prerequisites cite the consulting §1.3/§2/§5 + survey §9 → **PASS** (assessed, not built).

---

## 12. Open questions (tactical — deferred)

1. **Final `FinanceConfig` field name.** Proposed `grid_services_income_per_battery_home_gbp`; W2 owns the final name. **Resolution:** reconcile against the W2 amendment when it hits disk (re-checked this session; see hand-off). Decide during δ.
2. **Board scenario period / runtime.** Full PVGIS year is slow; the time-shift figure may use a representative window + `householder_bill` annualisation (the < 360-day path exists). **Suggested:** deterministic short window + annualisation for the test; full-year for the board artifact. Decide during γ.
3. **Band-selection surface.** `flex.resolve_grid_services_band` + a scenario `finance` value is the minimum; a `--flex-band` CLI option is a nice-to-have. **Suggested:** scenario-level for Friday; CLI later. Decide during δ.
4. **Round-trip / self-consumption-inflation correction.** A W2 follow-up (§9). **Suggested:** file against W2 after Friday; W1 reports band-membership only. Decide with the W2 session.
