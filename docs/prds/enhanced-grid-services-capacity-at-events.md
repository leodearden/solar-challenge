# PRD STUB — Enhanced grid-services sim (capacity-at-events derived)

> **⚠ STUB — not gated.** This is a seed for a future full `/prd` author pass (G1–G6 + META) +
> decomposition. It is **blocked on the full implementation of W1, W2-amendment, and W3** and is
> triggered by the fused-memory **"design & decompose: enhanced grid-services (capacity-at-events)"**
> task once those land. Do **not** decompose this file as-is.

- **Status:** stub · seeded 2026-06-17 · **blocked-on:** W1 + W2-amendment + W3 full implementation.
- **Source:** the grid-services design fork (Leo, 2026-06-17). The Friday deliverable models grid-services
  income as a **per-kW-of-battery-power** flat rate (`grid_services_income_per_kw_per_year_gbp`, option B).
  This PRD is **option C** — the fullest treatment, deferred until the per-kW model is shipped and the
  W1–W3 chain is in place to build on.

## Goal (to be refined in the full pass)

Replace the **flat per-kW** grid-services parameter with a **capacity-at-events-derived** model: compute
the fleet's *actually available dispatchable capacity* at typical DFS/DNO flexibility-event windows —
**net of what self-consumption and time-shift arbitrage are already using that battery for** — then price
it at a banded £/kW-event (availability) + £/MWh (utilisation) market rate. This models the **three-way
contention** for the battery (self-consumption vs arbitrage vs grid-services) that the consulting model
flags but the flat per-kW rate ignores.

## Why this is the fuller model (vs the shipped per-kW rate)

The per-kW rate (`Σ max_discharge_kw × £/kW`) assumes every kW of nameplate battery power is fully
available for grid services. In reality the battery's SOC and power are **already committed** to
self-consumption and arbitrage at event times; the *spare, firm, dispatchable* capacity at (say) a winter
4–7pm DFS window is smaller and **config-dependent**. Deriving it from the simulated SOC trajectory makes
the grid-services income physically grounded and per-config-honest, completing the program's
physics-grounding goal for the last value stream.

## Sketch of approach (option C — to be designed)

- **Event-window model:** define typical DFS/DNO event windows (e.g. winter weekday evening peaks; a
  banded count of events/yr) — exogenous market parameters.
- **Available-capacity physics:** for each event window `w`, from the simulated per-home SOC + power:
  `avail_kW(w) = Σ_home min(max_discharge_kw, usable_SOC(w) / event_hours)`, **net of** the discharge the
  battery is already doing for self-consumption / arbitrage in that window. Captures the three-way
  contention.
- **Pricing (exogenous, banded):** `income = Σ_w avail_kW(w) × £/kW_availability(w) × utilisation_factor
  × (1 − aggregator_share)` (or an availability + utilisation split), CMZ-gated.
- **Seam:** this **supersedes** the W2 cost-recovery `grid_services` term (currently
  `Σ max_discharge_kw × grid_services_income_per_kw_per_year_gbp`) with the event-derived figure; W2 owns
  the consuming math, this PRD owns the capacity-at-events computation.

## Consumers (G1 — to confirm in the full pass)

- **W2 cost-recovery** (`cost-recovery-householder-billing.md`) — its `grid_services` revenue term.
- **W3 install-config sweep** — per-config ranking now reflects event-window-available capacity.
- **Leo + ResNet board** — a physics-grounded grid-services line replacing the banded assumption.

## Pre-conditions (hard — why this is blocked)

- **W1 fully implemented** — fleet TOU + grid-charging physics + the flex value-model (so SOC trajectories
  under arbitrage exist to measure spare capacity against).
- **W2-amendment fully implemented** — the cost-recovery solve + the `grid_services` term this replaces.
- **W3 fully implemented** — the config sweep that consumes the per-config grid-services figure.

## Substrate notes (to verify in the full G3 pass)

- `home.battery_config.max_discharge_kw` (exists, config.py:264), simulated per-timestep SOC (exists).
- **Novel:** event-window definitions; the spare-capacity-at-window computation net of other battery use;
  an availability/utilisation £ rate schedule; CMZ gating.

## Out of scope (provisional)

- Real OpenADR VEN / aggregator dispatch integration (assessed in W1's buildability note, not built).
- Actual half-hourly settlement / MID-meter data ingestion.

## Open (for the full pass)

- Availability-only vs availability+utilisation pricing; event-schedule banding; how to net grid-services
  against arbitrage without double-committing the same kWh; whether to keep the flat per-kW field as a
  fallback/override.
