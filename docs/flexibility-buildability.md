# Flexibility Buildability & Risk Note (W1 ε)

**Source:** Consulting model `2026-06-16-flexibility-value-buildability-model.md` §1.1/§1.3/§1.4/§2/§5; 2026-06-15 deployment-readiness survey §9
**Task:** #56 — W1 ε: flexibility buildability/risk note
**PRD:** [docs/prds/flexibility-value-finance-integration.md](prds/flexibility-value-finance-integration.md) §1/§6/§7/§10
**Value-model code:** [`src/solar_challenge/flex.py`](../src/solar_challenge/flex.py) (`FLEX_VALUE_BANDS`, `resolve_grid_services_band`)

---

## 1. Banded Value-Model Summary

The canonical Low/Central/High decomposition below is transcribed verbatim from
`src/solar_challenge/flex.py` `FLEX_VALUE_BANDS` — the code is the single source of
truth.  Numbers derive from consulting §1.1/§1.4 (time-shift + per-home grid-services)
and PRD §6 (per-kW grid-services rate).

| Band | Time-shift (£/home/yr) | Grid-services (£/home/yr) | Grid-services (£/kW/yr) | **Total (£/home/yr)** |
|------|------------------------|---------------------------|-------------------------|----------------------|
| Low | 100 | 4 | 1.5 | **120** |
| Central | 250 | 30 | 12 | **280** |
| High | 330 | 120 | 48 | **450** |

**Representative discharge power:** 2.5 kW (matches `BatteryConfig.max_discharge_kw` default; consulting §1.1 anchor figure).  Per-kW ↔ per-home cross-check: `rate × 2.5 ≈ per-home` (Low: 1.5 × 2.5 = 3.75 ≈ 4; Central/High: exact).

**Low-band note:** The Low total (£120) is not the arithmetic sum of its streams (100 + 4 = 104 ≠ 120).  Consulting §1.1 warns against simple column-maxima addition: arbitrage and self-consumption contend for the same battery capacity, so the documented headline figure is used directly.  Central (250 + 30 = 280) and High (330 + 120 = 450) sum exactly.

**Central is the Friday board headline case.** Low/High are selectable for sensitivity (PRD §6 decision 5).

---

## 2. Prerequisites

All four prerequisites below must be in place before the grid-services income stream
(the "grid-services topper") can be claimed.  Sources: consulting §1.3/§2/§5 + survey §9.

1. **P483-capable aggregator** — a licensed flexibility aggregator able to register and
   bid assets under P483 (Distribution Flexibility Service / Demand Flexibility Service
   framework).  Bristol Energy Cooperative does not operate this directly; a third-party
   aggregator contract is required.

2. **MID asset meters (EM530/EM540)** — metering compliant with the Measuring Instruments
   Directive (MID) fitted at each battery installation.  Eastron EM530 / EM540 are the
   referenced models (consulting §2).  Required for settlement-grade import/export
   metering under DSO/DNO flex contracts.

3. **NGED CMZ confirmation email** — written confirmation from National Grid Electricity
   Distribution (NGED) that the Bristol installations fall within a designated Constraint
   Management Zone (CMZ) eligible for local-flex payments.  This is a prerequisite for
   DNO flex revenue (consulting §1.4).

4. **G99/G100 compliance** — all inverters must hold G99 (≤16 A/phase) or G100
   (>16 A/phase) type-approval and the DNO connection agreement must be in force.
   Required for grid-connected export and for eligibility in any grid-services scheme.

---

## 3. Risk Rating

| Prerequisite | Risk level | Notes |
|---|---|---|
| P483-capable aggregator | Medium | Aggregator market exists; contract negotiation adds programme timeline risk |
| MID asset meters (EM530/EM540) | Low | Standard hardware; procurement lead-time only |
| NGED CMZ confirmation | Medium | Depends on NGED's CMZ mapping; confirmation can take 4–8 weeks |
| **G99/G100 compliance** | **HIGH** | Type-approval failures or late DNO connection agreements can block grid export entirely; the single highest-consequence dependency |

**The one HIGH risk is G99/G100 compliance.**  A failed type-approval or missing DNO
connection agreement prevents grid export and disqualifies the installation from any
grid-services scheme, collapsing the grid-services revenue stream to zero regardless
of aggregator, metering, or CMZ status.  Mitigation: verify inverter type-approval
certificates before procurement and submit DNO applications no later than four weeks
before installation.

---

## 4. Out of Scope

The following are **not** in scope for W1 (PRD §7):

- **Full OpenADR VEN / aggregator build** — buildability is *assessed* (this note), not
  built.  No OpenADR-VEN code, aggregator API integration, or dispatch automation is
  implemented in W1.
- **Per-home island / backup scenario** — consulting §3 estimates UK resilience value
  near £0 under current market rules; this is a capability spec for a later phase, not
  Phase-1 finance.
- **Self-registered VLP / Balancing-Mechanism grid-services** — below the ~1 MW
  practical floor at 100 homes (consulting §1.4); excluded from all three bands.
- **Round-trip-loss import-cost convention** — the pre-existing `flow.py`/`home.py`
  accounting convention is a candidate W2 follow-up, not a W1 blocker.
- **Surplus-side valuation / bill-surplus split** — how the time-shift value is divided
  between deeper householder savings and project surplus, and the self-consumption
  inflation fix in `project_multi_year`, are owned by the **W2 cost-recovery amendment**
  (`docs/prds/cost-recovery-householder-billing.md`).

---

## 5. Full Consulting Reference

The detailed buildability model, scenario-by-scenario breakdown, aggregator market
survey, and G99/G100 compliance checklist are in the external consulting document:

> `2026-06-16-flexibility-value-buildability-model.md`
> (at `/home/leo/mission-control/consulting/solar-challenge/`; not git-tracked)

The banded figures in §1 above are transcribed from §1.1/§1.4 of that document.
The prerequisites and risk rating in §2–§3 derive from §1.3/§2/§5 of that document
and the deployment-readiness survey §9 (2026-06-15).
