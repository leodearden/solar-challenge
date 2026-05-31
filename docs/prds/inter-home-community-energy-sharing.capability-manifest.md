# Capability manifest — Inter-home / community energy sharing (P5)

Mechanizes G3 (substrate exists + wired) + G6 (premise valid) per leaf. Each
asserted capability binds to evidence: `grep:file:line wired` (present
substrate), `producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` (numeric/limit claim with its basis). PRD:
`docs/prds/inter-home-community-energy-sharing.md`.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, `producer-downstream`, or `bound≤floor`. The one cross-PRD
substrate (canonical SEG/import pricing) is the single queued prereq **task #2**,
with a hard dependency edge wired (ε→#2). All intra-batch producers
(`CommunityConfig`/`CommunityResults`, `simulate_community` p2p + battery paths,
`validate_community_balance`, the config parser, the billing fn) are queued with
wired edges (β→α; γ→α; δ→α,β,γ; ε→β,δ,#2). **`fleet.py` is consumed read-only
through its public aggregate API — no fleet producer task, by design.**

## α — COMMUNITY-CORE (p2p netting + balance + result types) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `FleetResults.total_grid_export`/`total_grid_import` (aggregate kW Series) consumable read-only | grep:`fleet.py:174-181` wired (public API; fleet.py NOT modified) | ✅ |
| `flow.simulate_timestep(generation_kw, demand_kw, battery=None, …, strategy)` reusable for netting | grep:`flow.py:134-141` wired; PV-only `battery=None` path proven grep:`home.py:249-251`,`home.py:290-297` | ✅ |
| `dispatch.SelfConsumptionStrategy` reusable | grep:`home.py:12` wired (import) | ✅ |
| `flow.validate_energy_balance` reusable per community timestep | grep:`flow.py:336-390` wired | ✅ |
| `community.py`→{fleet,home,flow,dispatch,battery} has no import cycle | grep:`fleet.py:10-21` (no community/config import) wired | ✅ |
| Signal = synthetic 2-home `FleetResults` → `cg_exp`/`cg_imp` reduced by `min(E,D)`; balance holds; `p2p`+battery raises | unit test on `simulate_community` (p2p) + `validate_community_balance` (own task, synthetic FleetResults, no real sim) | ✅ |
| Premise: COMMUNITY-BALANCE closes (p2p) | floor: composition proof §3.1 (`(★)` per-home + `(◆)` reused flow); re-asserted every timestep | ✅ |

## β — COMMUNITY-BATTERY (community_battery / both) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `simulate_community` core + netting + result types | **producer:task-α** — dep β→α wired (serialises `community.py`) | ✅ |
| `battery.Battery`/`BatteryConfig` reusable as the community store (SOC/efficiency/limits) | grep:`battery.py:56-220`, `battery.py:10-26` wired | ✅ |
| Same reused `flow.simulate_timestep` accepts a non-None `Battery` (no new dispatch) | grep:`flow.py:134-141` wired | ✅ |
| Floor: community-battery charge/discharge ≤ configured `max_charge_kw`/`max_discharge_kw` | floor: reused `Battery.charge`/`discharge` caps grep:`battery.py:168`, `battery.py:199` (not re-implemented) | ✅ |
| Signal = net surplus charges (SOC↑ bounded), net deficit discharges (`cg_imp`↓ vs p2p); balance holds incl. `(cb_ch−cb_dis)`; `both`≡`community_battery` | unit test (decision/flow-level, synthetic FleetResults) (own task) | ✅ |
| Premise: COMMUNITY-BALANCE closes with battery term | floor: composition proof §3.1 incl. `(cb_ch−cb_dis)`; re-asserted every timestep | ✅ |

## γ — COMMUNITY-CONFIG (parser + scenario surface) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `CommunityConfig` type to construct | **producer:task-α** — dep γ→α wired | ✅ |
| `config.load_config(path)` reusable by `load_community_config` (no duplicate file IO) | grep:`config.py:1606` wired | ✅ |
| Nested `community_battery` parsed via the existing battery parser | grep:`config.py:584` (`_parse_*_config` pattern), `config.py:1701` (`load_fleet_config` precedent) wired | ✅ |
| `config.py`→`community.py` import is acyclic (community never imports config) | grep:`config.py:23-31` (imports fleet/battery/…, not community), design: `CommunityConfig` lives in `community.py` | ✅ |
| Signal = YAML `community:` round-trips; `p2p`+battery ⇒ `ConfigurationError`; no block ⇒ `None`; frozen+picklable | unit test on `_parse_community_config`/`load_community_config` (own task) | ✅ |

## δ — CLI-COMMUNITY-RUN (consumer + report + demo scenario) — LEAF (integration gate)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `simulate_community` (p2p + battery) callable | **producer:task-α,β** — deps δ→α, δ→β wired | ✅ |
| `load_community_config` callable | **producer:task-γ** — dep δ→γ wired | ✅ |
| `cli/fleet.py run` + `load_fleet_config` consumer entry exist | grep:`cli/fleet.py:50-101`, `config.py:1679` wired | ✅ |
| `simulate_home(weather_data=…)` injection for a fast no-PVGIS A/B | grep:`home.py:180`, `home.py:195` wired | ✅ |
| `output.generate_summary_report` precedent for `generate_community_report` | grep:`output.py:143` wired (additive new fn) | ✅ |
| Numeric: `community_grid_import < Σ per-home grid_import` | floor: `cg_imp = Σimp − S − cb_dis ≤ Σimp`, strict when `S=min(Σexp,Σimp)>0`; demo scenario forces simultaneous surplus/deficit (§12) | ✅ |
| Backward-compat: no `community:` block ⇒ output bit-identical | floor: `simulate_community` not invoked when `load_community_config` returns `None` (§4) | ✅ |
| `config validate` accepts `community:` keys | **producer:task-γ** — dep δ→γ wired | ✅ |

## ε — VNM-BILLING (savings slice) — LEAF (#2-dependent)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Community flows (`cg_imp`/`cg_exp`) produced | **producer:task-β** — dep ε→β wired | ✅ |
| Report/CLI surface to display savings | **producer:task-δ** — dep ε→δ wired | ✅ |
| Import priced via `TariffConfig.get_rate`; export via `seg.calculate_seg_revenue` (canonical, wired by #2 — NOT a third pricing path) | **producer:task-2 upstream** — dep ε→#2 wired; grep:`tariff.py` get_rate, `seg.py:40` (orphan until #2 wires it) | ✅ |
| Numeric: `community_net_cost < baseline_net_cost`, `community_savings_gbp ≥ 0` | floor: per shared kWh benefit `= T − G > 0` (UK import rate > SEG always); baseline & community priced at the **same** community tariff/SEG (§3.4, §12) | ✅ |
| No duplicated pricing: single `_price_grid_flows` applied to both legs | design: §3.4 one fn, two inputs; reuses #2's primitives | ✅ |
