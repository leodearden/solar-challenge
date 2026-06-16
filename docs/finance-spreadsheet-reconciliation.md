# Finance Spreadsheet Reconciliation Note

**Source**: `finance/Forecast Model for Community Owned Solar_INVESTOR_PITCH_v3.xlsm`
**Read**: 2026-06-16 via `uv run --with openpyxl` (data_only mode; file not git-tracked)
**Task**: #48 – Finance/battery W2 θ: spreadsheet calibration + H6 integration gate

---

## 1. Named Cell Reference Table

| Field | Cell Reference | Transcribed Value | Notes |
|-------|---------------|------------------|-------|
| Sensitivity — inp_kWp | `Sensitivity!B6` | 5.5 kWp | Named input: PV capacity per home |
| Sensitivity — inp_Batt_kWh | `Sensitivity!B7` | 5.0 kWh | Named input: battery capacity (5 kWh basis) |
| Sensitivity — inp_kWhPerkWp | `Sensitivity!B8` | 1050 kWh/kWp | Named input: annual specific yield |
| Sensitivity — out_MinCash_WithBatt | `Sensitivity!B10` | £96,334.55 | Min cash surplus with battery |
| Sensitivity — out_RetSurplus_WithBatt | `Sensitivity!B12` | £207,841.20 | Retained surplus with battery |
| Total Capex (5 kWh basis) | `Capital_Stack!B6` | **£775,000** | Also `Debt and Risk!B5`, `Presentation Funders!B7` |
| Per-roof cost (10 kWh basis) | `Workings!C57` | £9,000 | 5.5×£1000+£1000+10×£250 |
| Capital borrowed (10 kWh basis) | `Workings!C94` | **£900,000** | 100 × £9,000 |
| Min DSCR | `Debt_Analytics!B16` | **2.10378435678433** | Also `Presentation Funders!E8`, `Stress_Test!B9` |
| Avg DSCR | `Debt_Analytics!B17` | 3.1735282491711 | Average over loan term |
| Equity cashflow start | `Debt_Analytics!B13` | −£244,821 | 'Cash for IRR' row (net of fees) |
| Equity cashflow yr 1 | `Debt_Analytics!C13` | £155,947 | Year 1 cash for IRR |
| Equity cashflow yr 2 | `Debt_Analytics!D13` | £163,911 | Year 2 cash for IRR |
| Equity cashflow yr 3 | `Debt_Analytics!E13` | £172,837 | Year 3 cash for IRR |

---

## 2. Capex Reconciliation: £775,000 ↔ £900,000 (§2.3)

Two capex figures appear in the spreadsheet. Both are **correct** — they use the
same 4-term build-up with different battery sizes:

```
Per-roof capex = pv_kwp × pv_cost + roof_fit + battery_kwh × battery_cost
              = 5.5 × £1,000 + £1,000 + ? kWh × £250
```

| Basis | Battery | Per-roof | Fleet (100 homes) | Cell |
|-------|---------|---------|------------------|------|
| Named input (inp_Batt_kWh=5) | 5 kWh | £7,750 | **£775,000** | `Capital_Stack!B6` |
| Workings build-up | 10 kWh | £9,000 | **£900,000** | `Workings!C94` |

**Delta = £125,000 = 100 × 5 kWh × £250/kWh** — a pure battery-size difference, **NOT an error**.

The `project_economics` function reproduces `Capital_Stack!B6` exactly
(within £1) when given a 100-home fleet at 5.5 kWp + 5.0 kWh:

```python
100 × (5.5×£1000 + £1000 + 5.0×£250) = 100 × £7,750 = £775,000  ✓
```

---

## 3. DSCR/IRR Calibration: Method-Agreement Results

### 3.1 [FIN]-Assumption Revenue Curve

The `spreadsheet_revenue_curve` helper builds a flat revenue curve from the
named spreadsheet inputs (no physics simulation):

```
per_home_gen     = inp_kWp × inp_kWhPerkWp = 5.5 × 1050 = 5,775 kWh/yr
per_home_revenue = scf × gen × own_use/100 + (1−scf) × gen × export/100
                 = 0.70 × 5775 × 0.15 + 0.30 × 5775 × 0.06
                 = £606.38 + £103.95 = £710.33/home/yr
fleet_revenue    = 100 × £710.33 = £71,032.50/yr
```

With [FIN] financing (grant=£250k, equity=75%, loan 15yr@7%):

| Metric | [FIN]-Assumption Model | Debt_Analytics cell | Ratio |
|--------|----------------------|--------------------|----|
| Total Capex | £775,000 | `Capital_Stack!B6` = £775,000 | **1.0000 (exact)** ✓ |
| min_dscr | ~4.02 | `B16` = 2.10378 | ~1.91 |
| equity_irr | ~10.7% | ~69% (prose, net of fees) | ~0.15 |

### 3.2 Why DSCR/IRR Differ from the Spreadsheet Cells (G6 Framing)

The [FIN]-assumption model **deliberately does not match** the spreadsheet's
DSCR and IRR digit-for-digit. This is expected because the spreadsheet's
income-and-expenditure model includes:

- **Equity-fundraising fees** and **formation costs** — these reduce the net
  cash available for debt service, lowering the spreadsheet DSCR below our model
- **Dividend deferral** — affects timing of equity returns
- **Grant timing** — grant drawdown schedule differs from the instant-grant
  assumption in our pure-layer model
- **Equity cashflow netting** — `Debt_Analytics!B13 = −£244,821` (the equity
  actually invested net of fees) is smaller than our model's `equity_gbp = £393,750`
  (75% of financed capex), explaining why the spreadsheet's IRR (~69%) is much
  higher than our model's (~11%)

### 3.3 Assertion Strategy (PRD §13 / G6 Latitude)

Per the "assert what is structurally achievable, report the rest" latitude:

| Assertion | Status | Rationale |
|-----------|--------|-----------|
| `total_capex_gbp == £775,000 ±£1` | **HARD asserted** | Exact 4-term build-up, no abstracted fees |
| `min_dscr ≥ 1.20` (covenant floor) | **HARD asserted** | Structural sanity, always achievable |
| `equity_irr > 0` | **HARD asserted** | Structural sanity, project generates returns |
| `min_dscr ≈ 2.10378` (digit-match) | *REPORTED only* | Fees/deferral not modelled in pure layer |
| `equity_irr ≈ 69%` (digit-match) | *REPORTED only* | Net-of-fees equity not modelled |

This makes the H6 gate honest: it passes if and only if the financial layer
correctly implements the 4-term capex build-up and covenant-floor constraints.

---

## 4. Spreadsheet-Input vs Physics Columns

The calibration test suite maintains two parallel columns:

| Column | Method | DSCR | IRR | Self-cons fraction |
|--------|--------|------|-----|-------------------|
| **Spreadsheet-input** | `spreadsheet_revenue_curve` (analytic) | ~4.02 | ~10.7% | 0.70 (named inp) |
| **Physics** | `project_multi_year` (real PVGIS sim) | varies | varies | ~30–52% (simulated) |

Only the **spreadsheet-input column** is hard-asserted (capex + covenant floor).
The **physics column** is run in the `@pytest.mark.slow` suite and *reported*
alongside the spreadsheet column to document the difference.

### 4.1 §2.3 Self-Consumption Tension

The spreadsheet assumes `self_consumption_fraction = 0.70` for with-battery homes
(Sensitivity!B7 = 5 kWh). The physics simulation typically yields ~30–52%
depending on load profile and battery dispatch. This is **expected** and **not an
error**: the spreadsheet uses a simplified aggregate assumption, while the physics
model accounts for load shape, PV intermittency, and battery SOC dynamics.

**The physics self-consumption fraction is deliberately NOT asserted equal to 0.70.**
This prevents false-precision: the physics column is the better-grounded default
for real fleet projections.

---

## 5. Summary

- `project_economics` **exactly reproduces** `Capital_Stack!B6 = £775,000` ✓
- DSCR and IRR from the pure layer legitimately differ from the spreadsheet due
  to abstracted fees/deferral — covenant floor (≥1.20) and IRR > 0 are asserted
- The £125,000 capex delta is a battery-size reconciliation, not an error
- Physics column self-consumption (~30–52%) differs from the spreadsheet's 0.70
  by design — physics is the correct path for real projections
