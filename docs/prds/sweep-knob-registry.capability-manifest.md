# Capability manifest — Sweep knob registry (review-all S26)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/sweep-knob-registry.md`. Machine-readable twin: `docs/prds/sweep-knob-registry.capability-manifest.yaml`.

**Code anchors** verified against main `dfcbde8` (2026-10-17). Main moves fast — cite-by-symbol; re-locate lines at implementation time.

**Batch verdict: PASS, conditional on the S6 leaves.** No binding resolves to a FAIL value. Producers outside the batch are upstream of the leaves that read them:

- S5 γ;
- S6 (labels from the lead): `homes()`, the SEG policy, the fleet-document reader and `cli/optimize`;
- 919 and 921 (S7 δ, ε);
- 868 and 870 (S4 ζ, η);
- 930 (S8 ζ);
- 885 (S16 γ);
- 802 and 803 (S9 β, γ);
- 807 (S19 η);
- 835 (S21 η);
- 938 (S17 ζ);
- 739;
- 440.

S6 is unfiled, so the decompose re-checks its leaves' extent (`homes()`, the form-preserving write, D10 at resolve time) before filing β, γ and η.

| Leaf | Capability asserted by the signal | Evidence binding | Status |
|---|---|---|---|
| α | `SweepSpec` admits non-finite points today | probe: `SweepSpec(1e-300, 1e300, 3)` gives `[1e-300, inf, inf]`; `validate config` on the overflow file says "got inf kWh" | PASS (RED) |
| α | finite min and max are read through the number leaf | producer 868 (S4 ζ), upstream | PASS |
| β | a `dataclasses.replace` knob reproduces today's web points | probe: equal at nine points across `pv_kw`, `battery_kwh`, `consumption_kwh`; no swept field derives a stored value (`object.__setattr__` grep: only the battery efficiency split, from `efficiency`) | PASS |
| β | the finance knobs derive from `FinanceConfig` | `dataclasses.fields(FinanceConfig)`: 15 real-number fields plus the grid-services field; `typing.get_type_hints` fails on the forward reference (probed), so the leaf reads the annotations | PASS |
| β | `--sensitivity <canonical name>` is refused today | `_SENSITIVITY_ALIAS_MAP` holds aliases only (read) | PASS (RED) |
| β | home-level knobs map over `ScenarioConfig.homes()` | producer: S6 `homes()` leaf, upstream (unfiled; lead question 3) | PASS (conditional) |
| γ | the default path issues 8 sweeps, 6 distinct | read at `dfcbde8`: `configs` → `run_sweep`; the panel → baseline, 3 floors (short-circuit keyed on the `None` override), 3 grid values | PASS (RED) |
| γ | equality reuse is sound | probe: `ScenarioConfig` of 100 homes `==` a field-by-field copy | PASS |
| γ | one projection per config under the counter | producer 930 (S8 ζ), upstream | PASS |
| δ | unknown mode runs linear; a battery to 200 kWh is accepted; `steps: 10**6` submits 10**6 jobs | probe through `build_test_app` with a recording job manager | PASS (RED) |
| δ | the bounds exist as data | `FLEET_COMPONENTS[pv/battery/load].fixed_range` = (0.5, 20), (0, 100), (500, 20000) | PASS |
| δ | the step bound | producer 807 (S19 η), upstream | PASS |
| ε | the page restates options and arithmetic | read: `parameterOptions` and `previewValues` in `parameter-sweep.js`; `sweep.html` `max="50"` | PASS (RED) |
| ζ | misplaced sweeps are refused late and namelessly | probe: `validate config` gives the internal message; `parse_sweep_fleet_configs` gives "No sweep specification found…" | PASS (RED) |
| ζ | the placement edit is generic over `draws` | producer 919 (S7 δ), upstream; F7 joins 921's checks | PASS |
| ζ | `validate config` already validates sweep documents per point | read: `cli/validate._fleet_homes` routes through `parse_sweep_fleet_configs` | PASS |
| η | the mode split exists | producer 739, in progress (`task/739`: `_param_sweep`, `_yaml_sweep`; complexipy `sweep` 8) | PASS |
| η | the knob path reads the fleet document as a scenario | producer: S6 fleet-document reader leaf, upstream (unfiled) | PASS (conditional) |
| θ | all four entry points are wired | γ, δ, ε, η upstream | PASS |
