# PRD — Enhanced grid-services sim (capacity-at-events derived)

- **Status:** active · author pass (G1–G6 + META) completed 2026-06-18 · gate met (W1 + W2-amendment + W3 fully implemented & merged, tasks 52–68 done).
- **Type:** contract resolving an accreted seam — supersedes the flat per-kW grid-services revenue term shipped by W2.
- **Source:** the grid-services design fork (Leo, 2026-06-17). The Friday deliverable models grid-services
  income as a **flat per-kW-of-battery-power** rate (`grid_services_income_per_kw_per_year_gbp` × Σ
  `max_discharge_kw`, option B). This PRD is **option C** — the physically-grounded successor that derives
  grid-services income from the **simulated spare dispatchable capacity at event windows**.

## Goal

Replace the flat per-kW grid-services revenue term with a **capacity-at-events-derived** figure: from the
simulated per-home SOC + battery-discharge trajectories, compute the fleet's *firm spare dispatchable
capacity* at typical DFS/DNO flexibility-event windows — **net of what self-consumption and time-shift
arbitrage are already using the battery for** — and price it at a banded availability (£/kW-event) +
utilisation (£/MWh) market rate, net of aggregator share. Running
`solar-challenge finance run scenarios/bristol-phase1-flex.yaml` (with the model enabled) then shows a
grid-services line **derived from event-window spare capacity** — a different, per-config-honest number
from the flat rate — and `solar-challenge optimize configs …` ranks configs against that physically-grounded
figure. This completes the program's physics-grounding goal for the last value stream.

## Background

The flat model (`finance.py:1139–1143`) assumes every kW of nameplate `max_discharge_kw` is fully available
for grid services every event. In reality the battery's SOC and power at a winter 4–7pm event are **already
committed** to self-consumption and (under W1's TOU + grid-charging arbitrage) to time-shift; the *spare,
firm, dispatchable* capacity is smaller and **config-dependent** (a bigger battery / smaller PV leaves more
headroom). Deriving it from the simulated trajectory models the **three-way contention** (self-consumption
vs arbitrage vs grid-services) the consulting model flags but the flat rate ignores.

The substrate to do this now exists: W1 shipped the fleet TOU + grid-charging physics (so SOC trajectories
*under arbitrage* exist), W2 shipped the cost-recovery solve that consumes the `grid_services` term, and W3
shipped the config sweep that ranks per-config economics through that solve.

## Activation status

Gate **met**. All three upstream workstreams are fully implemented and merged:
- **W1** `docs/prds/flexibility-value-finance-integration.md` — tasks 52–56 done (fleet TOU+grid-charging,
  flex value-model `flex.py`, board scenario + time-shift).
- **W2-amendment** `docs/prds/cost-recovery-householder-billing.md` — tasks 57–63 done (`solve_cost_recovery_rate`,
  the `grid_services` term this supersedes, adversarial code↔doc gate CR7).
- **W3** `docs/prds/discrete-install-config-sweep.md` — tasks 64–68 done (`enumerate_configs`, `run_sweep`,
  `rank`, `sensitivity_panel`, `generate_config_ranking_report`, the `optimize` CLI).

## Sketch of approach (option C)

**Observable substrate (verified, G3).** `FleetResults.per_home_results[i]` (a `SimulationResults`,
`home.py:62–124`) exposes per-timestep 1-minute `pd.Series` on a tz-aware `DatetimeIndex`: `battery_soc`
(post-step kWh), `battery_discharge` (kW, **net/total**), plus `grid_import/export`, `self_consumption`,
`tariff_rate`. Battery bounds come from config: `max_discharge_kw` (`config.py:264`), `min_soc_fraction` /
`max_soc_fraction` (`battery.py:128–129`) → `min_soc_kwh = capacity·SOH·min_soc_fraction`.

**The substrate constraint that shapes the design.** `battery_discharge` is a single net series with **no
purpose-attribution** — the simulator does *not* split discharge into "for self-consumption" vs "for
arbitrage" (`flow.py:267–268`). So "net of contention" is **not** computed from a (non-existent)
purpose-split. Instead it is read off the **observable headroom**: the baseline SOC trajectory *already
embeds* self-consumption and arbitrage draw, so the energy that sits **above the SOC floor** during the
window — and the inverter power **not already in use** — is genuinely spare. This sidesteps the gap rather
than assuming around it.

**Firm spare capacity (per home, per event window `w = [t0,t1]`, `event_hours = t1−t0`):**

```
P_spare(home,w) = max_discharge_kw − max_{t∈w} battery_discharge(t)      # inverter headroom, firm over the window
E_spare(home,w) = min_{t∈w} ( battery_soc(t) − min_soc_kwh )             # smallest above-floor buffer in the window
avail_kW(home,w) = max( 0, min( P_spare(home,w), E_spare(home,w) / event_hours ) )
avail_kW(w)      = Σ_home avail_kW(home,w)
```

Using `max` discharge and `min` SOC over the window makes the result **firm** (sustainable for the whole
event without driving the *baseline* trajectory below floor or exceeding the inverter) — which is exactly
what an availability market pays for. A battery pinned at the floor, or already discharging at
`max_discharge_kw`, contributes 0.

**Pricing (exogenous, banded — Low/Central/High, mirroring `flex.py`):**

```
availability_income(w) = avail_kW(w) · availability_gbp_per_kw_per_event · events_per_year(w)
utilisation_income(w)  = avail_kW(w) · utilisation_factor · event_hours · (utilisation_gbp_per_mwh/1000) · events_per_year(w)
annual_income_gbp      = Σ_w (availability_income(w) + utilisation_income(w)) · (1 − aggregator_share)
```

**Seam.** This **supersedes** the W2 `grid_services` term: inside `project_multi_year`/`_simulate_age`
(`finance.py:1035,1139–1145`), when `finance.grid_services_model == "capacity_at_events"` the
`grid_services` component becomes `compute_grid_services_at_events(fleet_results, events_config).annual_income_gbp`
instead of `rate × Σ max_discharge_kw`. The flat path remains the default (`"flat"`), preserving
backward-compatibility; the board scenario opts in.

## Resolved design decisions

1. **Firm-minimum spare, not time-averaged.** `E_spare` uses the **window-minimum** above-floor buffer and
   `P_spare` the **window-maximum** own-discharge. Rationale: availability products require *firm*
   capacity for the whole event; an expected/time-integrated figure would over-state dispatchable kW and
   inflate revenue. The optimistic/expected variant is deferred to §Open questions.

2. **"Net of contention" via observable headroom, not purpose-attribution.** Forced by substrate
   (`battery_discharge` is unattributed, `flow.py:267–268`). The baseline trajectory already reflects
   self-consumption + arbitrage draw; spare = above-floor energy + unused inverter power. This is the
   load-bearing design choice and the reason the model is buildable today without re-architecting the
   dispatch to tag discharge by purpose.

3. **Availability + utilisation pricing (both), banded.** Matches the stub's `£/kW-availability (+£/MWh
   utilisation)` and the consulting model. `utilisation_factor` (expected dispatched fraction) and
   `aggregator_share` are exogenous params. Rates come from a banded `GridServicesRateBands`
   (low/central/high) co-located with the new model, sibling to `flex.py`'s `FLEX_VALUE_BANDS`.

4. **Model selector flag; flat retained as fallback.** New `FinanceConfig.grid_services_model:
   {"flat","capacity_at_events"}` (default `"flat"`). Resolves the stub's open "keep the flat field as a
   fallback?" — **yes**: `"flat"` stays the default so every existing scenario/test is bit-unchanged; the
   event model is opt-in. Makes the supersede *observable* (the two models yield different figures for the
   same fleet — ε's signal).

5. **Rate-independence preserved → W2's cost-recovery solve still holds.** The own-use rate
   `own_use_rate_pence_per_kwh` is a CBS *accounting transfer price*; it does **not** enter physical
   dispatch (`dispatch.py`/`flow.py` use `tariff_rate`, PV, load, SOC — never the own-use rate). Therefore
   the simulated SOC + discharge series, and hence `annual_income_gbp`, are **invariant** to the own-use
   rate, exactly as the flat term was. `solve_cost_recovery_rate`'s affine reconstruction
   (`finance.py:1789–1802`) — which holds `grid_services` constant across trial rates — remains valid
   unchanged. This invariant is a hard contract (see §Contract) and δ's consumer-side boundary test.

6. **New module `gridservices.py`.** Holds `EventWindow`, `GridServicesEventsConfig`, `GridServicesRateBands`,
   `compute_fleet_spare_capacity_kw`, `compute_grid_services_at_events`, `GridServicesAtEvents`. Rationale:
   the event model operates on `FleetResults` time series (unlike `flex.py`'s static bands) and keeps
   `finance.py` from bloating; mirrors how `flex.py` isolates the banded value model.

7. **Compute once from the representative simulation.** `project_multi_year` already obtains a `FleetResults`
   via `simulate`; `avail_kW(w)` is computed once from it and reused across asset-life years. Per-age SOH
   shrinkage of spare energy is a refinement (see §Open questions), not core — keeps δ tractable.

## Pre-conditions for activating

- W1 + W2-amendment + W3 fully implemented & merged — **met** (tasks 52–68 done).
- The PRD must be on `main` before the decomposed tasks dispatch — task α depends on the trigger task #51,
  which carries this commit; #51 is marked done (and its branch merged) before α becomes schedulable.

## Cross-PRD relationship (G4)

| Other PRD | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| `cost-recovery-householder-billing.md` (W2) | supersedes | the `grid_services` revenue term in `project_multi_year`/`_simulate_age` (`finance.py:1139–1145`) | **this PRD** (task δ holds the integration) | wired by δ under the model flag; flat path retained as default |
| `discrete-install-config-sweep.md` (W3) | consumes (transitively) | per-config `representative_outlay_gbp` via `solve_cost_recovery_rate` → `_evaluate_config` (`optimize.py:957,969`) | W3 (already done) | **no W3 change needed** — the event-derived figure flows through the existing solve automatically; ε asserts the ranking reflects it |
| `flexibility-value-finance-integration.md` (W1) | consumes | simulated SOC-under-arbitrage trajectories (`FleetResults.per_home_results[].battery_soc/battery_discharge`) | W1 (already done) | producer on main; β reads it |

No reciprocal-ownership ambiguity: this PRD unambiguously owns the new computation + the `project_multi_year`
wiring; W2/W3/W1 are upstream producers requiring no edits.

## Contract (B+H) — the superseding seam

**Why B+H.** High-stakes load-bearing seam (the `finance.py` fleet-revenue computation that feeds both the
W2 cost-recovery solve and the W3 ranking) + cross-PRD consumers ≥ 2 (W2, W3). The integration is specified
up front so δ lands as a first-class task rather than starving under the narrow-file-lock orchestrator.

**Producer signatures (`gridservices.py`):**

```python
@dataclass(frozen=True)
class EventWindow:
    months: tuple[int, ...]      # e.g. (11,12,1,2) winter
    weekdays: tuple[int, ...]    # 0=Mon … 6=Sun; e.g. (0,1,2,3,4)
    hours: tuple[int, ...]       # e.g. (16,17,18) for a 16:00–19:00 window
    events_per_year: int
    event_hours: float
    def mask(self, index: pd.DatetimeIndex) -> pd.Series: ...  # bool, True inside the window

@dataclass(frozen=True)
class GridServicesEventsConfig:
    band: str = "central"                       # low|central|high
    event_windows: tuple[EventWindow, ...] = ...
    aggregator_share: float = ...               # in [0,1)
    utilisation_factor: float = ...             # in [0,1]
    availability_gbp_per_kw_per_event: float | None = None   # None => use band
    utilisation_gbp_per_mwh: float | None = None             # None => use band

@dataclass(frozen=True)
class GridServicesAtEvents:
    annual_income_gbp: float
    per_window_avail_kw: tuple[float, ...]      # avail_kW(w) per window (breakdown for the report)
    per_window_income_gbp: tuple[float, ...]

def compute_fleet_spare_capacity_kw(
    fleet_results: "FleetResults", windows: tuple[EventWindow, ...]
) -> tuple[float, ...]: ...                      # avail_kW(w) per window, firm-minimum, net of own use, >= 0

def compute_grid_services_at_events(
    fleet_results: "FleetResults", cfg: GridServicesEventsConfig
) -> GridServicesAtEvents: ...
```

**Invariants (hard):**
- **I1 — non-negativity.** `annual_income_gbp >= 0`; every `per_window_avail_kw >= 0`.
- **I2 — firmness.** `avail_kW(home,w) <= max_discharge_kw − max_{t∈w} battery_discharge(t)` and
  `<= (min_{t∈w}(soc−min_soc_kwh))/event_hours`. A floor-pinned or fully-loaded battery ⇒ 0.
- **I3 — supersede, not add.** When `grid_services_model == "capacity_at_events"`, the
  `project_multi_year` `grid_services` component **equals** `annual_income_gbp` and the flat `rate × Σ
  max_discharge_kw` term is **not** also added. When `"flat"` (default), the `YearPoint` stream is
  **bit-identical** to pre-PRD output.
- **I4 — rate-independence.** `annual_income_gbp` is invariant to `own_use_rate_pence_per_kwh`; ⇒
  `solve_cost_recovery_rate` converges unchanged and its affine reconstruction stays valid.

## Boundary-test sketch (B+H) — δ's observable signal

| # | Side | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|---|
| B1 | producer | known synthetic `FleetResults` | 2 homes, hand-set `battery_soc`/`battery_discharge` series + configs; one window | `compute_fleet_spare_capacity_kw` == hand-computed firm `Σ min(P_spare,E_spare/h)`; floor-pinned home ⇒ 0 |
| B2 | producer | pricing | known `avail_kW(w)`, central band | `annual_income_gbp` == `Σ_w (avail·avail_rate·N + avail·util_f·h·util_rate/1000·N)·(1−agg)`; `aggregator_share=1` ⇒ 0 |
| B3 | consumer | supersede takes effect | board scenario, `grid_services_model="capacity_at_events"` | `project_multi_year` `grid_services` component == event-derived figure ≠ flat `rate × Σ max_discharge_kw` |
| B4 | consumer | backward-compat | same scenario, model omitted/`"flat"` | `YearPoint` stream bit-identical to pre-PRD |
| B5 | consumer | solve still holds | `solve_cost_recovery_rate` on the capacity-at-events scenario | converges; `grid_services` constant across trial own-use rates (I4) |

## Decomposition plan

Linear vertical slice culminating in the user-observable integration gate (ε). Greek labels; real IDs
assigned at decompose time. Out-of-batch deps wired to the W1/W2/W3 leaf tasks task #51 gates on.

- **α — `gridservices.py` foundation: `EventWindow` + `GridServicesRateBands` + `FinanceConfig` selector/config.**
  Modules: `src/solar_challenge/gridservices.py` (new), `config.py` (FinanceConfig: `grid_services_model` +
  `grid_services_events`), `tests/unit/test_gridservices.py` (new), `tests/unit/test_config.py`.
  *Intermediate (unlocks β, δ).* Signal: `EventWindow.mask(index)` selects exactly the winter-weekday-16:00–19:00
  timesteps of a known `DatetimeIndex`; a `FinanceConfig` with `grid_services_model="capacity_at_events"` +
  a `GridServicesEventsConfig` round-trips and **rejects** invalid input (negative rate, `aggregator_share`
  outside [0,1), empty `event_windows`) with `ConfigurationError`; default `"flat"` leaves config unchanged.
  Prereq: #51 (PRD on main).

- **β — fleet spare-capacity physics (`compute_fleet_spare_capacity_kw`).**
  Modules: `gridservices.py`, `tests/unit/test_gridservices.py`.
  *Intermediate (unlocks γ).* Signal: unit test with a synthetic `FleetResults` (hand-built per-home
  `battery_soc`/`battery_discharge` series + configs) — returns per window `Σ_home max(0, min(max_discharge_kw
  − max-window-discharge, (min-window-soc − min_soc_kwh)/event_hours))`, matching a hand-computed multi-home
  figure (non-tautological); floor-pinned ⇒ 0; already-at-`max_discharge_kw` ⇒ 0 (I1, I2).
  Prereq: α; out-of-batch: **54, 55, 56** (W1 — the TOU+grid-charging arbitrage physics that shapes the SOC
  trajectory spare is measured against).

- **γ — event-derived pricing → annual income (`compute_grid_services_at_events`).**
  Modules: `gridservices.py`, `tests/unit/test_gridservices.py`.
  *Intermediate (unlocks δ).* Signal: unit test — `annual_income_gbp` == the banded availability+utilisation
  formula × `(1−aggregator_share)` for a known band; `GridServicesAtEvents` breakdown exposes per-window
  `avail_kW` + £; zero spare ⇒ £0; `aggregator_share=1` ⇒ £0 (B2).
  Prereq: β.

- **δ — supersede the W2 `grid_services` term in `project_multi_year` under the model flag (B+H integration boundary).**
  Modules: `src/solar_challenge/finance.py` (`_simulate_age`/`project_multi_year`),
  `tests/integration/test_grid_services_events.py` (new).
  *Intermediate (unlocks ε).* Signal: the boundary tests B3–B5 — event-derived `grid_services` ≠ flat for the
  same fleet under the flag; bit-identical under `"flat"`; `solve_cost_recovery_rate` converges with
  `grid_services` invariant across trial own-use rates (I3, I4).
  Prereq: γ; out-of-batch: **63** (W2 CR7 — the cost-recovery solve + the term being superseded).

- **ε — board scenario + finance/ranking report surface (user-observable leaf / integration gate).**
  Modules: `scenarios/bristol-phase1-flex.yaml` (add `grid_services_model: capacity_at_events` + event
  schedule + band), `src/solar_challenge/output.py` (`generate_finance_report` flex block: a
  `Grid services (capacity-at-events)` line with the event-derived £ + per-window `avail_kW`),
  `tests/integration/test_grid_services_events.py`.
  *Leaf (user-observable).* Signal: `solar-challenge finance run scenarios/bristol-phase1-flex.yaml` emits a
  grid-services figure **derived from event-window spare capacity** (visible in the finance report's
  flexibility block), and for the same fleet that figure **differs** from the flat-model figure (proving the
  supersede end-to-end); `solar-challenge optimize configs …` Table-1 cost-recovery ranking reflects the
  event-derived figure via `solve_cost_recovery_rate`.
  Prereq: δ; out-of-batch: **68** (W3 E — `generate_config_ranking_report` + `optimize` CLI consumer).

## Out of scope

- Real OpenADR VEN / aggregator dispatch integration (assessed in W1's buildability note, not built).
- Half-hourly settlement / MID-meter data ingestion.
- Re-architecting the dispatch to tag discharge by economic purpose (the design deliberately avoids needing
  this — decision 2).
- Co-optimising dispatch *for* grid services (the model measures spare capacity of the existing dispatch; it
  does not change dispatch to chase grid-services revenue).

## Open questions (tactical — deferred, not design-blocking)

1. **Per-age SOH degradation of spare capacity.** Spare energy shrinks as SOH falls over the 25-year life.
   **Suggested resolution:** compute `avail_kW(w)` from the representative (year-1) simulation and reuse it;
   optionally scale `E_spare` by per-age SOH. Decide during δ.
2. **Default banded rate values.** `availability_gbp_per_kw_per_event` / `utilisation_gbp_per_mwh` per band.
   **Suggested resolution:** seed central from the consulting model so the event-derived central figure lands
   in a defensible neighbourhood of (but need not equal) the flat £12/kW/yr; calibration is a tuning task.
   Decide during α/γ.
3. **Firm-minimum vs expected/time-integrated spare.** Decision 1 picks firm-minimum. If the board wants an
   expected-value variant, add it as a second pricing mode later. Decide post-ε if raised.
4. **Default event-window schedule.** Winter weekday 16:00–19:00 is the assumed DFS-style window; exact
   `months`/`hours`/`events_per_year` are tunable. **Suggested resolution:** a single winter-evening window,
   ~12 events/yr, 3 h. Decide during α.

## Note for the decompose / orchestrator hand-off

The orchestrator does **not** currently read the `user_observable_signal` / `consumer_ref` /
substrate-confirmed metadata fields filed with each task — that metadata is substrate for a future
tracking-infra session. Dependencies are wired as real `add_dependency` edges (the scheduler reads those).
