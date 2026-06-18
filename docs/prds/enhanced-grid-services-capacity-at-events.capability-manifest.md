# Capability manifest — enhanced-grid-services-capacity-at-events

Mechanizes G3 (substrate-exists/wired) + G6 (premise-valid) per task. Evidence verified on `main`
@ branch_base 63c617b3 (tasks 52–68 done). **No FAIL bindings** — every asserted capability is either
wired on `main` today or produced by a task **upstream** in this leaf's transitive dependency closure.

Verifier conventions: `grep:<file>:<line> wired` = referenced on the production entry path (not test-only);
`producer:task-<L> upstream` = delivered by an upstream task in the closure; `rejection:<X> fires` =
rejection mechanism exists and raises on X. Empty-value sentinel for field-population: `Undef`/`None`/default.

---

## α — gridservices.py foundation: EventWindow + GridServicesRateBands + FinanceConfig selector/config
*(intermediate — unlocks β, δ)*

| Capability asserted | Evidence | Verdict |
|---|---|---|
| `FinanceConfig` dataclass to extend with new fields | `grep:config.py:483-604 wired` (FinanceConfig + `__post_init__`) | PASS |
| `ConfigurationError` rejection fires on invalid input | `rejection:negative-rate fires` — existing pattern raises `ConfigurationError` in `__post_init__` (`grep:config.py:599-603`, the current `grid_services_income_per_kw_per_year_gbp < 0` guard) | PASS |
| `pd.DatetimeIndex` for `EventWindow.mask` (month/weekday/hour selection) | pandas stdlib; tz-aware 1-min index produced at `grep:load.py:496-499 wired` | PASS |
| `EventWindow` / `GridServicesEventsConfig` / `GridServicesRateBands` | **deliverable of α itself** (not a dependency) | n/a (produced here) |

## β — fleet spare-capacity physics: compute_fleet_spare_capacity_kw
*(intermediate — unlocks γ)*

| Capability asserted | Evidence | Verdict |
|---|---|---|
| `FleetResults.per_home_results: list[SimulationResults]` | `grep:fleet.py:141 wired` (production aggregation reads it) | PASS |
| `SimulationResults.battery_soc` populated (non-sentinel pd.Series) | `grep:home.py:62-124` declared + **populated** on production path `grep:home.py:350-412 wired` (real per-timestep Series, not `None`) | PASS (field-population) |
| `SimulationResults.battery_discharge` populated (net kW series) | `grep:home.py:62-124` + `grep:flow.py:267-268 wired` (producer writes real discharge) | PASS |
| `BatteryConfig.max_discharge_kw` | `grep:config.py:264 wired` | PASS |
| `BatteryConfig.min_soc_fraction` / `max_soc_fraction` → `min_soc_kwh` | `grep:battery.py:128-129 wired`; `available_discharge_capacity` pattern `grep:battery.py:330-332` | PASS |
| `EventWindow` type | `producer:task-α upstream` | PASS (DAG-direction) |
| SOC-under-arbitrage trajectory exists (TOU + grid-charging dispatch) | `producer:tasks-54,55,56 (W1) upstream`, status=done | PASS |

## γ — event-derived pricing: compute_grid_services_at_events
*(intermediate — unlocks δ)*

| Capability asserted | Evidence | Verdict |
|---|---|---|
| `compute_fleet_spare_capacity_kw` (avail_kW per window) | `producer:task-β upstream` | PASS |
| `GridServicesEventsConfig` + `GridServicesRateBands` (banded rates) | `producer:task-α upstream` | PASS |
| Pricing arithmetic premise (availability + utilisation × (1−agg)) | closed-form, no numeric floor asserted; `aggregator_share=1 ⇒ 0` and `zero-spare ⇒ 0` are identities | PASS |

## δ — supersede the W2 grid_services term in project_multi_year (B+H integration boundary)
*(intermediate — unlocks ε)*

| Capability asserted | Evidence | Verdict |
|---|---|---|
| `project_multi_year`/`_simulate_age` `grid_services` revenue term (the supersede point) | `grep:finance.py:1035,1139-1145 wired` (`grid_services = rate × Σ max_discharge_kw`, added into `fleet_revenue`) | PASS |
| `FleetResults` in scope at the revenue-assembly point | `grep:finance.py:1035 wired` (`project_multi_year` obtains FleetResults via `simulate`) | PASS |
| `compute_grid_services_at_events` | `producer:task-γ upstream` | PASS |
| I3 supersede-not-add; `"flat"` default bit-identical | negative assertion backed by the model-flag default (`"flat"`) added in α; bit-identity is a regression assertion against the existing path | PASS |
| I4 rate-independence ⇒ `solve_cost_recovery_rate` still converges | `rejection:own-use-rate-influences-dispatch fires=NO` — own-use rate absent from dispatch (`grep:dispatch.py`,`flow.py` use `tariff_rate`, not `own_use_rate`); affine solve already treats `grid_services` as rate-independent `grep:finance.py:1789-1802 wired` | PASS |

## ε — board scenario + finance/ranking report surface (LEAF / user-observable integration gate)

| Capability asserted | Evidence | Verdict |
|---|---|---|
| `generate_finance_report` flexibility block (where the new line renders) | `grep:output.py:851-869 wired` (renders flex_band block) | PASS |
| `solar-challenge finance run` CLI surface | `grep:cli/finance.py:57 wired` | PASS |
| Event-derived figure produced & wired into `project_multi_year` | `producer:task-δ upstream` (⇒ γ ⇒ β ⇒ α, all upstream in ε's closure) | PASS (DAG-direction) |
| `optimize configs` Table-1 ranking reflects the figure via `solve_cost_recovery_rate` | `grep:optimize.py:957,969 wired` (`_evaluate_config` → solve → `representative_outlay_gbp`) + `producer:task-68 (W3 E) upstream` | PASS |
| **End-to-end premise:** event-derived figure ≠ flat figure for the same fleet | branch-3 end-to-end capability; **qualitative inequality**, NOT an absolute numeric bound ⇒ no floor check; achievable because firm-spare-at-events is structurally ≠ nameplate `Σ max_discharge_kw` | PASS |

---

**Gate result:** all bindings PASS. Nothing re-scoped, re-homed, or relaxed. The single substrate risk
(discharge has no purpose-attribution, `flow.py:267-268`) is **designed around** (decision 2: spare read
from observable SOC-above-floor headroom), so it is not a FAIL binding.
