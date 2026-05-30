# Capability manifest — Web UI engine-capability parity (P2)

Mechanizes G3 (substrate exists) + G6 (premise valid) per leaf. Each asserted
capability binds to evidence: `grep:file:line wired` (present substrate),
`producer:task-N upstream` (queued prerequisite + wired dep), or
`floor:bound` (numeric claim with its basis). PRD: `docs/prds/web-ui-engine-capability-parity.md`.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, or `bound≤floor`. The two `producer-upstream` substrates
(PV-age fields, HomeConfig SEG rate) are queued prereqs (#16, #2) with hard
dependency edges wired (③→#16, ④→#2, ⑤→#2).

## ① WEB-HOME-PANELS (heat-pump + tariff + dispatch) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `HomeConfig.heat_pump_config` accepts `HeatPumpConfig` | grep:`home.py:44` + `heat_pump.py:99` wired | ✅ |
| `HeatPumpConfig(type, thermal_capacity_kw, annual_heat_demand_kwh)` validates | grep:`heat_pump.py:114-135` wired | ✅ |
| `config._parse_tariff_config(dict)` → `TariffConfig` (reusable) | grep:`config.py:653` wired | ✅ |
| `config._parse_dispatch_strategy_config(dict)` → `DispatchStrategyConfig`; `BatteryConfig.dispatch_strategy` consumed by engine | grep:`config.py:628`, `battery.py:26`, `home.py:253-266` wired | ✅ |
| Signal = sub-configs populated after parse (field-population) | boundary test on `_parse_home_config` (own task) | ✅ |

## ② WEB-FLEET-RUNNER (remove 501) — intermediate

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `config._parse_fleet_distribution_config(dict)` → `FleetDistributionConfig` | grep:`config.py:1056` wired | ✅ |
| `generate_homes_from_distribution(cfg, location)` → `list[HomeConfig]` | grep:`config.py:1163` wired | ✅ |
| `JobManager.submit_fleet_job(configs, …)` runs+aggregates a home list | grep:`jobs.py:171`, `jobs.py:523` wired | ✅ |
| `form_to_fleet_distribution_config(data)` emits the parser's dict shape | grep:`fleet_config.py:93` ↔ `config.py:1056` wired | ✅ |
| `resolve_location` (preset / `lat,lon`) | grep:`shared.py:26` wired | ✅ |
| Signal floor: endpoint returns 201 and `submit_fleet_job` receives N=3 | floor:N=3 (input-determined, not a model bound) | ✅ |

## ③ WEB-HOME-PVAGE — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `PVConfig(system_age_years=, degradation_rate_per_year=)` constructs | **producer:task-16 upstream** (not present today) — dep ③→#16 wired | ✅ (queued prereq) |
| P2's own claim: parsed value reaches `PVConfig` (field-population) | boundary test on `_parse_home_config` (own task, post-#16) | ✅ |
| Numeric: `system_age_years=20` ⇒ ≈10% lower generation | floor:0.90 = 1−20·0.005, **proven by #16/P3** (`test_pv.py` asserts 0.90); inherited via dep, NOT an independent P2 claim | ✅ |

## ④ WEB-HOME-SEG — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `HomeConfig` carries a SEG rate `simulate_home` prices export against | **producer:task-2 upstream** (not present today) — dep ④→#2 wired | ✅ (queued prereq; §7 seam) |
| `SEG_PRESETS` named-supplier rates readable | grep:`seg.py:30` wired (read-only) | ✅ |
| P2's own claim: SEG field == resolved rate after parse (field-population) | boundary test on `_parse_home_config` (own task) | ✅ |
| Summary `seg_revenue_gbp`/`net_cost` reflect SEG pricing | **producer:task-2** (the SEG math) — inherited via dep | ✅ |

## ⑤ WEB-FLEET-OVERLAY — leaf

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `dataclasses.replace` on frozen `HomeConfig`/`BatteryConfig` | grep:`home.py:25`, `battery.py:10` (frozen) wired | ✅ |
| Every generated home carries the fleet-wide `tariff_config` + `dispatch_strategy` | own task (replace over the list it controls) + ② runner | ✅ |
| SEG part of the overlay | **producer:task-2** via ④'s SEG-on-HomeConfig wiring — dep ⑤→#2 wired | ✅ |
