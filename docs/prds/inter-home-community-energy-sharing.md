# PRD — Inter-home / community energy sharing

- **Gap register item:** P5 (supersedes placeholder task #6)
- **Status:** active · authored 2026-05-31 (review `20260530T090214Z`)
- **Owner seam:** `fleet.py` simulation/aggregation (gap-register §C). **Decision: `fleet.py`'s public API is left UNCHANGED** — the sharing layer is a new sibling module `community.py` that *consumes* `FleetResults`. See §7/§D announcement.
- **Approach:** **B + H** (contract + two-way boundary tests). High stakes: extends the load-bearing energy-balance invariant to the community level and feeds the investor-viability case (community self-sufficiency + virtual-net-metering savings). See §8.
- **Consumes (do not re-touch / do not duplicate):**
  - `fleet.FleetResults` aggregate API (`total_grid_export`, `total_grid_import`, `per_home_results`) — the fleet layer owns aggregation; this PRD reads it, never re-sums.
  - `flow.simulate_timestep` + `dispatch.SelfConsumptionStrategy` + `battery.Battery` + `flow.validate_energy_balance` — reused verbatim for the community-battery dispatch and per-timestep balance. **No new dispatch or validation logic.**
  - `tariff.TariffConfig.get_rate` + `seg.calculate_seg_revenue`/`SEGTariff` — the pricing primitives **task #2** makes canonical; reused for the VNM billing slice (no third pricing path).

---

## 1. Goal

Model a Bristol-fleet **community** that shares energy instead of each home importing/exporting to the external grid independently. At every timestep, one home's surplus PV first offsets a neighbour's deficit (peer-to-peer virtual sharing), an optional **shared community battery** stores the remaining surplus to serve later deficit, and only the final residual touches the external grid. The community is then settled as a single **virtual-net-metering** entity, and the savings versus the same homes acting independently are reported.

**User-observable outcome:** running

```
solar-challenge fleet run scenarios/bristol-community.yaml --community-report report.md
```

on a heterogeneous community prints (and writes to `report.md`):

1. **Community grid import < Σ per-home grid import** and **community grid export < Σ per-home grid export** — sharing demonstrably reduces aggregate grid dependency (the headline energy signal, no pricing dependency).
2. **`community_net_cost_gbp` < baseline (sum-of-independent) net cost**, with a positive `community_savings_gbp` (the virtual-net-metering signal; depends on task #2's unified pricing).
3. The extended community energy-balance invariant **closes at every one of the ~1440 timesteps/day** (`validate_community_balance` passes).

With **no `community:` block** in the config, `fleet run` behaves exactly as today (community layer never invoked — bit-identical output).

## 2. Background

Today homes are simulated **independently**: `fleet.simulate_fleet` runs each `simulate_home` in a `ProcessPoolExecutor` and `FleetResults` merely *sums* the per-home series (`fleet.py:151-196`). There is no inter-home power exchange, no shared storage, and no community-level settlement. README §"Current Phase Scope" frames "more sophisticated power-sharing schemes … for future phases" (`README.md:19`); the briefing records this as an **UNINTENDED gap** (`review/briefing.yaml:106-108`) — real work, not a deliberate deferral. Review surfaced it as "Inter-home / community-battery sharing absent" (`review/reports/summary-20260530T090214Z.md:52`).

**Why a post-hoc aggregation layer (not a re-dispatch).** The seam contract (gap-register §C, P5) is *"consume per-home `SimulationResults`"*. Homes are therefore simulated exactly as today — preserving (a) the **per-home seed model** (`fleet_seed + index`, entirely inside `simulate_home`/fleet config generation, untouched) and (b) the **per-home energy-balance invariant** (already validated inside `simulate_home`). Community sharing operates on the already-balanced per-home `grid_import`/`grid_export` kW series on their common 1-minute index. A genuinely *co-optimised* dispatch (each home's battery aware of neighbours) would require re-running `simulate_home` with fleet-wide state — that contradicts the consume-`SimulationResults` contract and is explicitly **out of scope** (§10, future PRD).

**Physical note on sharing modes.** In a post-hoc aggregate, instantaneous netting is **conservation-inherent**: a community has one connection point, so simultaneous surplus and deficit physically net (you cannot suppress P2P matching while surplus and deficit coexist). Hence the two meaningful, non-degenerate behaviours — and the two `sharing_mode` values — are *netting only* (`p2p`) and *netting + a shared battery on the residual* (`community_battery`). A separate `both` value would be redundant (`community_battery` necessarily includes netting); **dropped per user decision**.

## 3. Sketch of approach — contract (load-bearing, H)

### 3.1 The community energy-balance contract — a composition theorem

The per-home invariant `validate_energy_balance` (`flow.py:336`) holds for every home (validated inside `simulate_home`). Summed over the `N` homes in `FleetResults` at timestep `t`:

```
Σgenᵢ + Σimpᵢ = Σdemᵢ + Σexpᵢ + Σ(bchᵢ − bdisᵢ)            … (★)  [per-home balances, summed]
```

The community layer redistributes only `Σexp`/`Σimp`; it never alters generation, demand, or per-home batteries. Define per timestep:

```
surplus      = Σexpᵢ                         # FleetResults.total_grid_export[t]
deficit      = Σimpᵢ                         # FleetResults.total_grid_import[t]
net_surplus  = max(0, surplus − deficit)     # instantaneous P2P netting (conservation)
net_deficit  = max(0, deficit − surplus)     # one of these is always 0
```

The community battery is then dispatched on `(generation = net_surplus, demand = net_deficit)` by **reusing `flow.simulate_timestep`** with a `SelfConsumptionStrategy` and a community `Battery` (or `battery=None` for `p2p` mode). That call returns an `EnergyFlowResult` whose own balance `flow.validate_energy_balance` already guarantees:

```
net_surplus + cg_imp = net_deficit + cg_exp + (cb_ch − cb_dis)     … (◆)  [reused flow invariant]
```

where `cg_imp`/`cg_exp` are the **community** grid import/export and `cb_ch`/`cb_dis` the community-battery charge/discharge. The community-level invariant is then **proven**, not re-implemented:

```
Σgen + cg_imp  =  Σdem + cg_exp + Σ(bchᵢ − bdisᵢ) + (cb_ch − cb_dis)     … (COMMUNITY BALANCE)
```

**Proof.** Substituting `surplus = Σexp`, `deficit = Σimp` into (◆) and cancelling the shared term:
`Σexp + cg_imp = Σimp + cg_exp + (cb_ch − cb_dis)` ⟹ `cg_imp − cg_exp = Σimp − Σexp + (cb_ch − cb_dis)`.
Then COMMUNITY-BALANCE LHS−RHS = `(Σgen − Σdem − Σ(bchᵢ−bdisᵢ)) + (cg_imp − cg_exp) − (cb_ch − cb_dis)`; by (★) the first bracket = `Σexp − Σimp`, and substituting the line above gives `(Σexp−Σimp) + (Σimp−Σexp) = 0`. ∎

So the community invariant **closes by composing two already-validated invariants** ((★) per-home + (◆) the reused flow timestep). With no community config (no sharing applied) it reduces to the plain sum of per-home balances — backward-compatible. This composition *is* the contract; every leaf binds to it. `validate_community_balance` asserts COMMUNITY-BALANCE directly as an independent cross-check (it does not re-derive dispatch — it sums `FleetResults` totals + the recorded community-battery deltas).

### 3.2 `simulate_community` — the thin core (single reused dispatch path)

```python
# community.py
def simulate_community(
    fleet_results: FleetResults,
    config: CommunityConfig,
    *, validate_balance: bool = True,
) -> CommunityResults:
    surplus = fleet_results.total_grid_export      # reuse fleet aggregate API — NO re-summing
    deficit = fleet_results.total_grid_import       # both are kW Series on the common index
    battery = Battery(config.community_battery) if config.community_battery else None
    strategy = SelfConsumptionStrategy()
    cg_imp, cg_exp, cb_ch, cb_dis, soc = [], [], [], [], []
    for t in surplus.index:
        ns = max(0.0, float(surplus[t]) - float(deficit[t]))    # net_surplus (kW)
        nd = max(0.0, float(deficit[t]) - float(surplus[t]))    # net_deficit (kW)
        r = simulate_timestep(generation_kw=ns, demand_kw=nd, battery=battery,
                              timestep_minutes=1.0, timestamp=t.to_pydatetime(), strategy=strategy)
        if validate_balance:
            validate_energy_balance(r)                          # reuse per-timestep flow validator
        # record (×60 → kW), mirroring home.simulate_home's conversion convention exactly
        ...
    return CommunityResults(...)  # series + a reference to fleet_results
```

- **Both modes via one path.** `p2p` ⟹ `battery=None` (self-consumption with no store: `cg_exp = net_surplus`, `cg_imp = net_deficit`). `community_battery` ⟹ a community `Battery`; netting still emerges from the self-consumption stage (conservation). The PV-only-home path already exercises `simulate_timestep(battery=None, …)` (`home.py:249-297`), so this is a proven reuse.
- **Units.** Per-home series are kW; the reused `simulate_timestep` takes power + `timestep_minutes` and returns kWh-per-step, converted back ×60 → kW — **identical** to `home.simulate_home`'s convention (`home.py:304-360`). No new units convention is introduced.
- **Encapsulation.** `community.py` reads `FleetResults` through its public aggregate properties only; `fleet.py` is not modified. The community battery is a plain `battery.BatteryConfig` → `Battery`, reusing all SOC/efficiency/limit logic.

### 3.3 Config surface

A new top-level `community:` block, parsed into a frozen `CommunityConfig` (in `community.py`, so `config.py` can import it without a cycle):

```yaml
community:
  sharing_mode: community_battery # "p2p" | "community_battery"
  community_battery:              # required for community_battery; forbidden for p2p
    capacity_kwh: 50.0
    max_charge_kw: 20.0
    max_discharge_kw: 20.0
  billing:                        # optional — enables the VNM £ slice (depends on #2)
    tariff: { ... }               # community import tariff (reuses TariffConfig YAML shape)
    seg_rate_pence_per_kwh: 4.1   # or  seg: { preset: Octopus }
```

`config._parse_community_config(data) -> Optional[CommunityConfig]` and `config.load_community_config(path)` (reusing the existing `load_config`, `config.py:1606`) read it. `fleet run` calls `load_community_config(config_path)` alongside the existing `load_fleet_config`; if a block is present it applies sharing. `FleetConfig` is **not** modified (community is parsed as a separate concern → fleet-layer encapsulation preserved; the file is small, the double-parse is negligible).

### 3.4 VNM billing (the financial slice — reuses #2's pricing)

A single internal `_price_grid_flows(import_kw: Series, export_kw: Series, tariff, seg) -> (import_cost, export_revenue)` reusing `TariffConfig.get_rate(ts)` (import) and `seg.calculate_seg_revenue` (export). It is applied **twice** with the same community tariff/SEG:

- **baseline** = price `(Σimp, Σexp)` (the sum-of-independent aggregate) → `baseline_net_cost`;
- **community** = price `(cg_imp, cg_exp)` (post-sharing residual) → `community_net_cost`;
- `community_savings_gbp = baseline_net_cost − community_net_cost ≥ 0`.

Pricing both legs at the **same** community tariff/SEG isolates the sharing benefit from per-home tariff heterogeneity. The slice depends on **#2** so it builds on #2's canonical, wired `seg.py` pricing rather than introducing a third inlined pricing path (review N-SEG-ORPHAN: `seg.py` is currently orphaned; #2 wires it in).

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Layer placement | New module `community.py`; **`fleet.py` public API unchanged** | Strongest answer to the P2 seam (P2 #19/#22 call `simulate_fleet` — zero churn). Higher layer (community) depends on lower (fleet); fleet has no knowledge of community. *(user-confirmed: new layer, no fleet-encapsulation violation)* |
| No duplicated logic | Reuse `FleetResults` aggregate API; reuse `flow.simulate_timestep`+`SelfConsumptionStrategy`+`Battery`+`validate_energy_balance`; reuse `TariffConfig`/`seg` pricing | Community-battery dispatch == single-home self-consumption on `(net_surplus, net_deficit)`; the balance is a composition theorem (§3.1), not new code. *(user directive: avoid logic duplication / layer violations)* |
| Sharing model | `sharing_mode ∈ {p2p, community_battery}`; netting always applied (conservation), community battery optional | `p2p` = netting only; `community_battery` = netting + shared battery. A separate `both` value is redundant (`community_battery` already implies netting) — **dropped per user decision**. *(user-confirmed)* |
| Financial scope | Energy signal (no deps) **+** VNM £-savings slice (depends on #2) | Gap explicitly names "virtual net metering". £ slice isolated behind #2 like P4's δ. *(user-confirmed: Energy + VNM £)* |
| Community battery dispatch | Self-consumption on the aggregate residual (charge surplus, discharge to deficit) | Mirrors per-home `SelfConsumptionStrategy`; reuses `flow`. TOU/arbitrage dispatch of the community battery is out of scope (§10). |
| VNM tariff | A single **homogeneous** community tariff + SEG in the `community.billing` block | Comparable baseline vs community settlement; isolates sharing benefit. Heterogeneous per-home VNM settlement is out of scope (§10). |
| Per-home benefit attribution | v1 reports **community aggregates**; per-home allocation deferred | Aggregates are allocation-independent; the headline signals need no allocation policy. Per-member benefit split is a governance/tactical follow-up (§10/§11). |
| Consumer surface | Auto-apply in `fleet run` when a `community:` block is present, `--community-report PATH` for the markdown | Minimal new surface; the config block is the trigger. Web exposure is a P2 follow-up, out of scope. *(user-confirmed)* |
| Config home | `CommunityConfig` in `community.py`; `_parse_community_config`/`load_community_config` in `config.py` | Avoids the `config ↔ community` import cycle (community must not import config); mirrors `BatteryConfig`-in-`battery.py` parsed by `config.py`. |
| Backward compatibility | No `community:` block ⟹ `simulate_community` never called ⟹ `fleet run` output bit-identical | Every existing fleet/CLI test stays green. |
| Reproducibility | Untouched — community layer is deterministic given per-home results; per-home seeding is inside `simulate_home`/fleet generation, not modified | Preserves the `fleet_seed + index` requirement by construction. |

## 5. Pre-conditions for activating

- **Task #2 must land** before the VNM-billing leaf (**ε**): ε reuses #2's canonical `seg.py`/`TariffConfig` pricing and depends on the export-at-SEG / unified-`net_cost` source of truth. The energy slices (**α/β/γ/δ**) do **not** depend on #2 — their signals are netting/balance/aggregate-grid correctness, not pricing.
- All engine substrate exists — see §6. No P3/P4 dependency (community sharing is orthogonal to PV degradation and per-home grid-charging; it consumes whatever per-home `SimulationResults` those produce).

## 6. Substrate verification (G3)

| Assumed capability | Evidence |
|---|---|
| `FleetResults.total_grid_export` / `total_grid_import` (aggregate kW Series) + `per_home_results` | `fleet.py:174-181`, `fleet.py:140`, `fleet.py:151-161` |
| Per-home `SimulationResults.grid_import`/`grid_export` are aligned 1-min kW Series | `home.py:80-81`, `home.py:352-361`; common index enforced (same tz/period) `fleet.py:42-46` |
| `flow.simulate_timestep(generation_kw, demand_kw, battery: Optional[Battery], timestep_minutes, timestamp, strategy)` | `flow.py:134-141` (battery optional; strategy defaults to self-consumption) |
| `dispatch.SelfConsumptionStrategy` | `home.py:12` import; `dispatch.py` |
| `battery.Battery` (charge/discharge/SOC/limits) + `BatteryConfig` reusable for the community store | `battery.py:56-220`, `battery.py:10-26` |
| `flow.validate_energy_balance(EnergyFlowResult)` + `EnergyFlowResult` fields | `flow.py:336-390`, `flow.py:117-131` |
| PV-only path already calls `simulate_timestep(battery=None, …)` (proves the `p2p` reuse) | `home.py:249-251`, `home.py:290-297` |
| `config.load_config(path)` (YAML/JSON → dict) reusable by `load_community_config` | `config.py:1606` |
| `cli/fleet.py` `run` command + `load_fleet_config` consumer entry | `cli/fleet.py:50-101`, `config.py:1679` |
| `TariffConfig.get_rate(ts)`; `seg.SEGTariff`/`calculate_seg_revenue`/`SEG_PRESETS` (billing primitives, #2 wires into production) | `tariff.py`, `seg.py:7/30/40` |
| No import cycle: `community.py`→{fleet, home, battery, flow, dispatch, tariff, seg} (none import community); `config.py`→community (community never imports config) | `fleet.py:10-21` (no config/community import); `config.py:23-31` |

**Novel substrate introduced (queued within this batch, not assumed):** `community.CommunityConfig`, `CommunityResults`, `CommunitySummary`, `simulate_community`, `validate_community_balance`, `_price_grid_flows` (billing), `config._parse_community_config`/`load_community_config`, `output.generate_community_report`, and the `cli/fleet.py run` community branch. Each is produced by a named task below and consumed by a named downstream task or the CLI surface — no orphan, no fiction. **G3 verdict: PASS.**

## 7. Cross-PRD relationship (G4)

| Other PRD / task | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **P2** (web UI parity) | **produces (for P2 to consume)** | P2 #19/#22 call `simulate_fleet` / build `FleetConfig`. **This PRD leaves `simulate_fleet`, `FleetResults`, `FleetConfig`, `simulate_fleet_iter` signatures UNCHANGED** (community is a separate `community.py` + a separate `community:` config block). | P5 owns `fleet.py` / `community.py`; **P2 needs no adaptation** | announced §D; no edge |
| **task #2** (SEG/import pricing) | **consumes** | VNM billing leaf ε reuses #2's canonical `seg.py`/`TariffConfig` pricing | #2 owns pricing; **P5 must not add a third pricing path** | dep ε→#2, wired at decompose |
| **P3** (PV degradation) | none | P3 adds `PVConfig` age fields consumed by per-home sim; community consumes the resulting `SimulationResults` transparently | — | no edge |
| **P4** (TOU grid-charging) | none | P4 is per-home dispatch (`flow`/`dispatch`/`BatteryConfig.grid_charging`); community sharing is post-hoc aggregation. Both touch `config.py` but in **disjoint functions** (P4 `_parse_battery_config`; P5 `_parse_community_config`/`load_community_config`). | — | no edge (file-lock note below) |
| **task #6** | superseded | — | this PRD | #6 → cancel at decompose |

`config.py` file-lock note: P3 (`#17`, `_parse_pv_config`/`PVDistributionConfig`), P4 (`#24`, `_parse_battery_config`), and P5 (`γ`, new `_parse_community_config`/`load_community_config`) edit **disjoint regions** of `config.py`. No logical conflict; the orchestrator's narrow file-lock serialises access. No reciprocal-ownership ambiguity: P5 owns the sharing layer end-to-end; #2 owns pricing.

## 8. G5 note — why B + H

High stakes on three axes: (1) it **extends the load-bearing invariant** to the community level — a naive sharing implementation silently breaks conservation (e.g. subtracting shared energy from export without adding it to a neighbour's met-demand); (2) the **VNM savings** number feeds the investor case; (3) cross-module blast radius ≥ 3 (`community.py`, `config.py`, `cli/fleet.py`, `output.py`, `scenarios/`) and a cross-PRD seam (P2 consumer, #2 dependency). → **B + H**:

- **Contract (B):** §3.1 composition theorem + the `simulate_community`/`CommunityConfig`/`CommunityResults` signatures (§3.2) + the explicit reuse bindings (§3, §6) are the written contract every leaf binds to.
- **Two-way boundary tests (H):**
  - *community ↔ invariant:* `validate_community_balance` holds at **every** timestep for all three modes (δ); and equals the composition of per-home + reused-flow validations.
  - *aggregation ↔ fleet:* the community netting uses `FleetResults.total_grid_export`/`total_grid_import` and never re-sums; a two-home synthetic `FleetResults` with home A exporting `E` while home B imports `D` at the same step yields `cg_exp`/`cg_imp` reduced by exactly `min(E,D)` (α).
  - *residual ↔ community battery:* net surplus charges the community `Battery` (SOC rises, capped at limits via the reused `Battery`), net deficit discharges; charge/discharge never exceed the configured power limits (β, by reuse).
  - *flows ↔ economics:* priced by #2's primitives, `community_net_cost < baseline_net_cost`, `community_savings_gbp ≥ 0` and equals the priced shared+stored energy (ε).
  - *backward-compat:* no `community:` block ⟹ `fleet run` output bit-identical to today (δ).

## 9. Decomposition plan

Five tasks. **`community.py`** is edited only by the serialised chain **α → β → ε** (no concurrent edits). **`config.py`** only by γ (disjoint from P3/P4 regions). **`cli/fleet.py`** + **`output.py`** + **`scenarios/`** only by δ. Per-task tests live in distinct modules (`tests/unit/test_community.py`, `tests/integration/test_community_fleet.py`) to avoid contention. δ is the **integration-gate leaf** (G2): α/β/γ are intermediates that unlock it.

### α — community core: P2P netting + balance + results types
- **Modules:** `community.py` (new) (+ `tests/unit/test_community.py`)
- **Work:** `CommunityConfig` (frozen: `sharing_mode: Literal["p2p","community_battery"]`; `community_battery: Optional[BatteryConfig]`; optional `billing`; `__post_init__`: battery required for `community_battery`, forbidden for `p2p`). `CommunityResults` (community `grid_import`/`grid_export`/`battery_charge`/`battery_discharge`/`battery_soc` kW Series + the source `FleetResults`). `simulate_community` **p2p path** (`battery=None`) reusing `flow.simulate_timestep`+`SelfConsumptionStrategy` on `(net_surplus, net_deficit)` derived from `FleetResults.total_grid_export/total_grid_import`. `validate_community_balance` asserting COMMUNITY-BALANCE (§3.1) from `FleetResults` totals + recorded community-battery deltas.
- **Classification:** intermediate — unlocks β, γ, δ.
- **Verification signal:** unit tests on a synthetic 2-home `FleetResults` (constructed series, no real sim) — home A exports `E`, home B imports `D` at the same step ⟹ `cg_exp` and `cg_imp` each reduced by `min(E,D)`; `validate_community_balance` holds at every step; `p2p` with `community_battery` set raises in `__post_init__`.

### β — community battery layer (community_battery mode)
- **Modules:** `community.py` (+ `tests/unit/test_community.py`)
- **Work:** extend `simulate_community` so `community_battery` mode instantiates a `Battery(config.community_battery)` and passes it into the **same** reused `simulate_timestep` call; record `cb_ch`/`cb_dis`/`soc`. No new dispatch logic.
- **Prereqs:** α (intra-batch, serialises `community.py`).
- **Verification signal:** unit test — with a community battery, a net-surplus step charges it (SOC rises, bounded by `max_charge_kw`/capacity via the reused `Battery`), a later net-deficit step discharges it to meet deficit (`cg_imp` falls vs the `p2p`-only result); `validate_community_balance` holds every step including the `(cb_ch − cb_dis)` term.

### γ — config parsing + scenario surface
- **Modules:** `config.py` (+ `tests/unit/test_config.py`)
- **Work:** `_parse_community_config(data) -> Optional[CommunityConfig]` (parses `sharing_mode`, nested `community_battery` via the existing battery parser, optional `billing.tariff`/`seg`) and `load_community_config(path)` (reusing `load_config`). Imports `CommunityConfig` from `community.py` (no cycle).
- **Prereqs:** α (needs the `CommunityConfig` type).
- **Classification:** intermediate — unlocks δ.
- **Verification signal:** unit tests — a YAML `community:` block round-trips into `CommunityConfig` (mode + battery + billing); a `p2p` block with a `community_battery` raises `ConfigurationError`; a file with no `community:` block ⟹ `load_community_config` returns `None`; `CommunityConfig` stays frozen + picklable.

### δ — CLI wiring + community report + demo scenario (integration-gate leaf, G1 consumer)
- **Modules:** `cli/fleet.py`, `output.py` (`generate_community_report`), `scenarios/bristol-community.yaml` (new), `tests/integration/test_community_fleet.py` (new)
- **Work:** `fleet run` calls `load_community_config(config)`; if present, after building `FleetResults` (existing path, unchanged), calls `simulate_community`, prints a community section (community grid import/export vs Σ per-home), and writes `generate_community_report` when `--community-report PATH` is given. Commit `scenarios/bristol-community.yaml`: a small heterogeneous fleet (PV-heavy low-load exporters + PV-light high-load importers) guaranteeing simultaneous surplus/deficit, with a `community:` block. Integration test uses **injected `weather_data`** (small synthetic frame, no PVGIS → fast/deterministic) for an A/B (community on vs off).
- **Prereqs:** α, β, γ.
- **User-observable signal (G6):** `solar-challenge fleet run scenarios/bristol-community.yaml` prints **community grid import < Σ per-home grid import** (and export likewise); `validate_community_balance` holds across the run; with the `community:` block removed, output is **bit-identical** to a plain `fleet run`. `solar-challenge config validate` accepts the `community:` keys.

### ε — virtual-net-metering billing slice (#2-dependent leaf)
- **Modules:** `community.py` (`_price_grid_flows` + savings on `CommunitySummary`), `cli/fleet.py`/`output.py` display (+ `tests/unit/test_community.py`, `tests/integration/test_community_fleet.py`)
- **Work:** `_price_grid_flows(import_kw, export_kw, tariff, seg)` reusing `TariffConfig.get_rate` + `seg.calculate_seg_revenue`; compute `baseline_net_cost` (priced `Σimp`/`Σexp`) and `community_net_cost` (priced `cg_imp`/`cg_exp`) at the same community tariff/SEG; `community_savings_gbp`. Surface in the report/table.
- **Prereqs:** β (community flows), δ (report/CLI surface), **#2** (canonical pricing — serialises after #2; no third pricing path).
- **User-observable signal (G6):** for `scenarios/bristol-community.yaml` with a `billing` block, `community_net_cost_gbp < baseline_net_cost_gbp` and `community_savings_gbp ≥ 0`, equal to the priced shared+stored energy; the report shows the savings line.

> **Note for decompose-time:** the orchestrator does not yet consume `user_observable_signal` / `consumer_ref` / substrate-confirmed metadata; recorded for a future tracking session. Task **#6 → cancel** (superseded by α/β/γ/δ/ε). Mark any real-PVGIS test `slow` per task #11 (δ/ε avoid PVGIS via injected/synthetic data).

## 10. Out of scope

- **Co-optimised dispatch** — per-home batteries aware of neighbours / a community optimiser re-running `simulate_home`. v1 is strictly post-hoc on per-home results (the consume-`SimulationResults` contract). Future PRD.
- **TOU / arbitrage dispatch of the community battery** — v1 uses self-consumption on the residual. (A community analogue of P4's grid-charging is a future PRD.)
- **Heterogeneous per-home VNM settlement** and **per-member benefit allocation** (equal/proportional split) — v1 prices a single community tariff/SEG and reports community aggregates.
- **Network/distribution losses** on shared energy — v1 P2P sharing is lossless; the community battery's round-trip loss is captured by the reused `Battery` exactly as per-home (the pre-existing no-loss-term convention in `validate_energy_balance` is preserved, not fixed).
- **Web exposure** of community sharing — a candidate P2 follow-up (P2 owns `web/`); not wired here.
- **Modifying `fleet.py` / `simulate_fleet` / `FleetResults`** — deliberately untouched (the P2 seam).

## 11. Open questions (tactical — deferred, not design-blocking)

1. **Community battery default size for the demo scenario.** δ must pick a `capacity_kwh`/power for `scenarios/bristol-community.yaml` that visibly stores midday surplus into the evening peak for the chosen fleet. Tune empirically in δ; the field is configurable either way.
2. **`p2p` netting granularity.** v1 nets at the fleet-aggregate level (`total_grid_export` vs `total_grid_import`) — correct for a single community connection point. A future multi-feeder / sub-community topology would net per-group; out of scope for v1, revisit if topology config appears.

> *(Resolved this session: the redundant `both` `sharing_mode` value was dropped — `community_battery` already implies netting. See §4.)*

## 12. G6 — premise validity of the asserted signals

- **δ energy premise — `community_grid_import < Σ per-home grid_import`:** *achievable and producible from this batch (α/β) alone, no #2.* `cg_imp = Σimp − S − cb_dis ≤ Σimp`, strict whenever the shared `S = min(Σexp,Σimp) > 0` or the battery discharges; the demo scenario is constructed so simultaneous surplus/deficit exists (heterogeneous exporters + importers) ⟹ `S > 0`. **Not a guess — it's the netting identity.**
- **δ invariant premise — community balance closes for all modes:** proven by composition in §3.1 ((★) per-home, validated in `simulate_home`, + (◆) the reused `flow.validate_energy_balance` on each community-battery timestep). The leaf re-asserts COMMUNITY-BALANCE every timestep. **Producible by α/β.**
- **β floor — community-battery charge/discharge ≤ configured limits:** guaranteed by the **reused** `Battery.charge/discharge` caps (`battery.py:168/199`), not re-implemented. **Producible by β.**
- **ε numeric premise — `community_savings_gbp ≥ 0`:** shared+stored energy that avoids import is valued at the import tariff `T` but would otherwise have earned only the SEG rate `G`; net benefit per shared kWh `= T − G > 0` (UK import rate always exceeds SEG). Battery round-trip loss only applies to energy the self-consumption dispatch chose to store (always beneficial when `T > G`). Pricing correctness is owed to **#2** (wired dep), reusing its primitives — **not** an independent/duplicated claim. **Not a guess.**
- **No false exactness / field-population:** `CommunityResults` series are populated with real values by `simulate_community` on the production path (α/β), not sentinels; `validate_community_balance` reads them. **G6 pass.**
