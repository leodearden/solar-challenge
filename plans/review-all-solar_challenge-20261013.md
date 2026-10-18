# review-all — solar_challenge — review-all-solar_challenge-20261013

## Method

```yaml
run_id: review-all-solar_challenge-20261013
as_of_sha: 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8
since: none
evidence:
  source_files: 59
  source_lines_by_area:
    simulation-core: 13703
    finance-economics: 5339
    web-dashboard: 7884
  test_files: 247
  corpora:
  - present-tree at as_of_sha
  - metrics snapshot (quality_metrics_snapshot.py via single-package shim)
  - git log fix-prefixed subjects (fix density)
  - review/briefing.yaml
  - fused-memory search
  - hotspot-survey-solar_challenge-20261013 findings (69)
  - review-solar_challenge-20261013 findings (110)
verification:
  confirmed: 38
  weakened: 25
  refuted: 1
  unverified: 0
  refutation_rate: 0.016
cost:
  seats:
    opus/high: 10
    sonnet/high: 11
    fable/high: 3
  agents_phases_3_4: 23
  subagent_tokens_phase_2: 5012450
  subagent_tokens_phases_3_4: 4254887
  subagent_tokens_total: 9267337
  wall_clock_phases_1_4: 16:27 elapsed (Phase 1 0:15; Phase 2 siblings 1:44 and 1:40 overlapping, 08:05-14:23; idle 14:23-19:41
    awaiting the lead; phases 3-4 workflow 4:24)
  wall_clock_total: see program doc
  phase_2:
    hotspot-survey-solar_challenge-20261013:
      agents: 22
      subagent_tokens: 2498161
      wall_clock: '1:44'
    review-solar_challenge-20261013:
      agents: 10
      subagent_tokens: 2514289
      wall_clock: '1:40'
  phases_3_4:
    agents: 23
    subagent_tokens: 4254887
    tool_uses: 962
    wall_clock: '4:24'
    workflow_run_id: wf_7866a6f5-923
inputs_consumed:
- hotspot-survey-solar_challenge-20261013
- review-solar_challenge-20261013
- legacy:review/reports/summary-20260630T110159Z.md
extra:
  findings_json: plans/review-all-solar_challenge-20261013.json
  worktree:
    path: /home/leo/src/solar-challenge/.worktrees/review-all-solar_challenge-20261013
    removed: true
    note: removed by an external sweep of .worktrees/ while phases 3-4 ran (no log found); every seat re-extracted as_of_sha
      with git archive into its scratch and read that identical tree, so anchors were still verified at as_of_sha
  yellow_flag_sample: null
  refutation_rate_prior_runs: []
  instruments:
  - instrument: hotspot-survey
    run_id: hotspot-survey-solar_challenge-20261013
    as_of_sha: 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8
    commits_since: 0
    verdict: re-run
    why: 'no prior baseline: run whole (--full) as this run''s Phase 2 at the pinned tree'
    open_findings: 69
  - instrument: review
    run_id: review-solar_challenge-20261013
    as_of_sha: 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8
    commits_since: 0
    verdict: re-run
    why: 'no committed contract-form report: run whole (--since none) as this run''s Phase 2 at the pinned tree'
    open_findings: 110
  - instrument: review (legacy)
    run_id: legacy:review/reports/summary-20260630T110159Z.md
    as_of_sha: null
    commits_since: null
    verdict: stale-not-run (superseded by the re-run)
    why: 'pre-contract: no as_of_sha; its unfiled findings became leads'
    open_findings: 0
  - instrument: census
    run_id: none
    as_of_sha: null
    commits_since: null
    verdict: stale-not-run
    why: no codebook (docs/legibility/confusion-codebook.yaml absent); the census is never run by review-all
    open_findings: 0
  - instrument: review-all
    run_id: none
    as_of_sha: null
    commits_since: null
    verdict: first run
    why: no previous record; since=none, no rotation
    open_findings: 0
  fable_seats:
    wanted:
    - synthesis
    - critic
    run:
    - synthesis
    - critic
  seats_lost: []
  severity_corrections:
    applied: 1
    disputed: 0
  trigger_chain: filed by the program; ids in the program doc FILED table
  launched_from: none
  metrics_snapshot:
    path: plans/quality-metrics/review-all-solar_challenge-20261013.json
    diffed_against: none
  key_implementation: shared/src/shared/finding_key.py
  area_rules: 'inferred from review/briefing.yaml purpose prose (no member lists): see gen_slices.py::area_of; briefing defect
    for /review-briefing'
  metrics_instrument_note: quality_metrics_snapshot.py run through a run-local member-list shim because the project declares
    no uv workspace (dark-factory task filed, source=review-all)
```

Keys minted by `shared/src/shared/finding_key.py`. Areas and the path-to-area rules are in `extra.area_rules`; the metrics instrument note in `extra.metrics_instrument_note`. Instruments consumed: hotspot-survey-solar_challenge-20261013, review-solar_challenge-20261013, legacy:review/reports/summary-20260630T110159Z.md.

**Read coverage** (one row per seat; every file read fully this run is a first-time read, there being no previous review-all record):

| seat | read fully | first time | indexed | partial (lines verbatim) | lines read / planned |
|---|---|---|---|---|---|
| simulation-core/physics | 17 | 17 | 0 | none | 7785 / 7555 |
| simulation-core/config-cli | 12 | 12 | 4 | src/solar_challenge/home.py (245), src/solar_challenge/fleet.py (95) | 6480 / 6148 |
| finance-economics | 8 | 8 | 3 | src/solar_challenge/config.py (266), src/solar_challenge/home.py (31), src/solar_challenge/output.py (79) | 5715 / 5339 |
| web-dashboard/server | 12 | 12 | 0 | none | 4670 / 4483 |
| web-dashboard/forms-charts | 11 | 11 | 16 | src/solar_challenge/web/api.py (294), src/solar_challenge/config.py (192), src/solar_challenge/web/static/js/fleet-simulator.js (76), src/solar_challenge/web/shared.py (33) | 4054 / 3401 |
| repo | 52 | 52 | 5 | none | 8200 / 7969 |
| cross:spot | 0 | 0 | 0 | none | None / None |
| cross:layering | 0 | 0 | 0 | none | None / None |
| cross:dimensions | 0 | 0 | 0 | none | None / None |
| cross:stateless | 0 | 0 | 0 | none | None / None |

## Metrics snapshot

Rendered from `plans/quality-metrics/review-all-solar_challenge-20261013.json` (quality_metrics_snapshot.py schema; complexipy cognitive complexity read as the pair max-per-function / module total). No previous snapshot: no delta column. Line counts are read-budget figures, never a ranking (docs/code-quality.md §Do not steer by).

Whole repo: 59 src files / 26926 lines, 247 test files; import graph 255 edges, 0 cycles, hidden cycles [['solar_challenge', 'solar_challenge.cli', 'solar_challenge.cli.main'], ['solar_challenge.config', 'solar_challenge.finance', 'solar_challenge.gridservices']], typing cycles [['solar_challenge', 'solar_challenge.cli', 'solar_challenge.cli.main'], ['solar_challenge.battery', 'solar_challenge.community', 'solar_challenge.config', 'solar_challenge.finance', 'solar_challenge.fleet', 'solar_challenge.flow', 'solar_challenge.gridservices', 'solar_challenge.home']], reach-back imports 1, deferred imports 43 of which 13 close a cycle.

| area | src files | lines (prose) | over soft / alarm | top cognitive max/total | top fan-in | reach-back | deferred (cycle-closing) | re-exports | private patch targets |
|---|---|---|---|---|---|---|---|---|---|
| finance-economics | 8 | 5339 (2204) | 0 / 1 | finance.py 78/216; optimize.py 29/34; optimize.py 26/100 | seg.py 13; tariff.py 7; gridservices.py 5 | 0 | 22 (12) | 1 | 0 |
| simulation-core | 29 | 13703 (3990) | 0 / 1 | config.py 45/346; ev.py 42/51; output.py 41/113 | home.py 19; config.py 18; location.py 15 | 1 | 10 (1) | 1 | 1 |
| web-dashboard | 22 | 7884 (2329) | 0 / 0 | assistant.py 47/78; fleet_config.py 34/99; api.py 22/125 | shared.py 7; database.py 7; storage.py 6 | 0 | 11 (0) | 1 | 0 |

## Instrument freshness

| instrument | run id | as_of_sha | commits since | verdict | open findings consumed |
|---|---|---|---|---|---|
| hotspot-survey | hotspot-survey-solar_challenge-20261013 | 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8 | 0 | re-run — no prior baseline: run whole (--full) as this run's Phase 2 at the pinned tree | 69 |
| review | review-solar_challenge-20261013 | 7dfea36e25040c0fa2bf4c9eb25a8ff444d15cc8 | 0 | re-run — no committed contract-form report: run whole (--since none) as this run's Phase 2 at the pinned tree | 110 |
| review (legacy) | legacy:review/reports/summary-20260630T110159Z.md | — | None | stale-not-run (superseded by the re-run) — pre-contract: no as_of_sha; its unfiled findings became leads | 0 |
| census | none | — | None | stale-not-run — no codebook (docs/legibility/confusion-codebook.yaml absent); the census is never run by review-all | 0 |
| review-all | none | — | None | first run — no previous record; since=none, no rotation | 0 |

## Area × heuristic view

Ranking rule (synthesis `method`): Payoff = cost removed x breadth x verdict weight. Cost removed is proxied by severity (high 3, medium 2, low 1; f7 revised to medium per the critic). Breadth is the finding's own measured reach (1 = one site, 2 = several sites in one module or area, 3 = cross-module or cross-area, read off the measurements). Verdict weight: confirmed 1, weakened 0.5; a prior re-emitted this run (p6, p50) takes this run's verdict; a prior an area seat re-checked as still_present keeps its instrument's verdict, since the seats recorded presence, not strength. Ties break by severity, then by heuristic co-tags. Nothing is ranked by line count, average complexity, coverage or test count; the h14 cells rank on the seats' partition measurements. Standing findings: none this run. Supersedes applied at the join: f6 replaces p10, f31 replaces p165 (p10, p165 removed from the matrix and from the PV and Surface-lock streams). Area member rule for the matrix (provisional, posed to the lead as a contradiction because review/briefing.yaml carries none): every src/solar_challenge/cli/ module maps to repo (the area the 14 CLI priors already carry, so it re-keys 5 new findings instead of 14 priors); seg.py and tariff.py map to finance-economics (the seat that read them). Under that rule f8 is superseded by p163 (f8's measurements carry forward under p163's key), f12 is folded into p161, p40 is superseded by p72, and p28, p41, p46 move cells; f10, f11, f43, f59 rank under repo. Verification counts corrected: 63 findings carry confirmed (38) or weakened (25); no finding or dropped entry carries a refutation, so refuted = 0 and refutation_rate = 0.0 until the pipeline names one. Critic fixes applied: p33/f51 exoneration rewritten against briefing 82-83 and 252; Dispatch stream gains the accept-and-ignore open choice and invariant 10 is conditional; charts.py, cli/utils, tests, finance.py and web-server exonerations narrowed to what was measured; Finite-quantities and Scenario-grammar streams reuse web/number_fields.py (moved down) instead of a new quantities.py; the charts stream extends chart_container; the lane stream reuses the JUnit-XML seam and the existing e2e modifyitems hook; dashboard limits live in fleet_components; the Finance partition's deletable list counts statements and names the removing stream.

| area | tag | ranked (best payoff first) |
|---|---|---|
| simulation-core | h10 | fk-a9c609ecb8ef h✓, fk-649851e5fc38 h✓, fk-0edf0069c6bb h✓, fk-2a53ae89932e m✓, fk-664e2030921e m✓, fk-f622bbaa9f2e m✓, fk-e2aaf2bfe651 m✓, fk-291910b552af m✓, fk-897e13f84164 m✓, fk-48447960eb2c m~, fk-f2e1ad46df4b m✓, fk-a2b33a420bcf m✓, fk-e79170280adf m✓, fk-a98db49f3fd7 l✓, fk-7dcdc5559d22 l✓, fk-e0e34ef46058 l✓ |
| simulation-core | h11 | fk-3be3240278ee h✓, fk-f126b1c9cbbe h✓, fk-148991ab9439 h✓, fk-35b8ddcf5565 m✓, fk-8b8f9d686b86 m✓, fk-2b16cc8bcf46 m✓, fk-d2b4045c6676 m✓, fk-dfeefbe95640 m✓, fk-bd03fe349ffd m~, fk-d6f16d95b126 l✓, fk-491014934d1e m✓, fk-ef13881623be l✓, fk-835a87838a52 l✓, fk-41767a1bc146 m✓, fk-94cab00e114e l~, fk-753ec8e6e149 l~, fk-f7b19fc4c8b5 l✓, fk-caad5305a3be l✓, fk-9df95e9e2b45 l~ |
| simulation-core | h9 | fk-4df47ebe6a96 m✓, fk-59fdc80fdded m✓, fk-b3dfd41a4d6a m~, fk-601c5b5f6415 m~, fk-8047de9b6789 m~, fk-66f886576b3f l✓, fk-616cc076b7cb l✓ |
| simulation-core | h12 | fk-94f4881bbe48 m✓, fk-04b52ee632c6 m✓, fk-7fa120a8bb98 l✓, fk-e4549a3a6b54 l~ |
| simulation-core | h3 | fk-0e58e2a7e007 h✓, fk-fc652220a4d3 m✓, fk-781d153ab978 m✓, fk-ac39320dcf1d m✓, fk-7ef1099d24e8 l✓, fk-4872e7ab367e m~, fk-7e76b4cf2cb2 m~, fk-083990041fdc l~ |
| simulation-core | h7 | fk-16df1a7ac416 h✓, fk-06035cd76226 m✓, fk-8529726bbd6b m✓, fk-615cbc883512 l✓, fk-44fdf5fb356b l✓, fk-188af6c13d71 l~ |
| simulation-core | kind:defect | fk-7440003fdd59 h✓, fk-1d920c89e872 h✓, fk-50a3985fae0f m✓, fk-740e9a804a4f m✓, fk-89777ec9faad m✓, fk-998f0cb69410 l✓, fk-756c0ef9e9d9 l✓ |
| simulation-core | h1 | fk-f5cd69400ce6 h✓, fk-99244625d7f2 l✓, fk-b97bf2325eda l✓ |
| simulation-core | h13 | fk-4435376bedb3 m✓, fk-370b3e49b67c m✓ |
| simulation-core | h4 | fk-1609d8c3d091 m✓, fk-72af0b90338d l~ |
| simulation-core | h6 | fk-2dc9d1cd2c06 m✓, fk-a80aa8f942eb m✓, fk-ae20e1833a19 l✓ |
| simulation-core | h8 | fk-c36d6fcbc2a8 m✓, fk-8995288451e6 l✓, fk-f2f8a5512feb l✓ |
| simulation-core | tests | fk-e58042aef503 m✓, fk-c78416de5500 l✓ |
| simulation-core | comments | fk-00cb82820af9 l✓, fk-dc5cf2ec9b84 l✓ |
| simulation-core | h14 | fk-62821dcde535 m✓ |
| finance-economics | h11 | fk-81d0840d19e2 h✓, fk-caeaf35c8151 h✓, fk-1cd332300623 m✓, fk-808be5588896 m✓, fk-0f24b7f66eb2 l✓, fk-3b0a239d0489 m✓, fk-9fa18977ec68 l✓, fk-50cf1dd5df58 l~ |
| finance-economics | h7 | fk-52fa98174363 h✓, fk-4ddab794283a m✓, fk-9cc706d3afdd m~, fk-2228ae61ef4e l~ |
| finance-economics | h10 | fk-aafe32daa988 m✓, fk-b69968a37b36 m✓, fk-872021ade9b6 m✓, fk-f4d53977c642 l~ |
| finance-economics | h3 | fk-d432a549b03f m✓, fk-4cc34de4e649 m~, fk-d63c41ca13f9 m~ |
| finance-economics | h9 | fk-4a9af7c31a4f m✓, fk-b0f648b0e6d0 m~, fk-3ca00f8edeb8 l✓ |
| finance-economics | h1 | fk-62dbe0f34b68 m✓, fk-3f4daea21220 m✓, fk-286fe17c28c9 m✓ |
| finance-economics | kind:defect | fk-758b2f309cab m✓, fk-2f88003e22c8 m✓ |
| finance-economics | tests | fk-c2c9277c1920 m✓, fk-72fdec5965a1 l✓, fk-97213a0e9ab2 l✓ |
| finance-economics | h13 | fk-da69830bb2d6 m✓, fk-0b791f2be2d6 l✓ |
| finance-economics | comments | fk-6cd8a932665c l✓, fk-5b34adae950b l~ |
| finance-economics | h4 | fk-c0e0ae3dcca8 h✓ |
| finance-economics | h14 | fk-5fdb04305288 m✓ |
| finance-economics | h6 | fk-41283f42a36a l~ |
| finance-economics | h2 | fk-0b4f5e04067c l✓ |
| web-dashboard | h11 | fk-a6d9f3e5a7e2 h✓, fk-9d7f66fdcfdd m✓, fk-42c0053b9a2b h✓, fk-93ee9a05751a m✓, fk-a391cf1f4edf m✓, fk-463e82417506 m✓, fk-bea05911eb70 m✓, fk-194e5b40da23 m✓, fk-366773b4083f m✓, fk-ff5b90768f66 m✓, fk-88374e6e3553 m✓, fk-f8b7b3ab709d l✓, fk-34a6679f1ef3 l✓, fk-7893b49b92c3 m✓, fk-40dff1473b94 m~, fk-8f26d000b68d m✓, fk-d303b6dbf669 m✓, fk-066e5cb461f7 l✓, fk-93d3bd7aa219 l✓, fk-ba29e186122f l✓, fk-2ff305a1dbb2 l~, fk-cca5fd81afda l~, fk-ad65ad5e4e48 l~ |
| web-dashboard | h10 | fk-a37ed16d59c5 h✓, fk-484952247bb6 h✓, fk-0593b530a371 m✓, fk-a0866b1bd680 h✓, fk-1df9dbc0d971 m✓, fk-6c98ee030531 m✓, fk-273b8b09c91a m~, fk-239274130a5a m~, fk-9dd1d9389dd2 m✓, fk-70edc755ede4 m✓, fk-1070454e4c6e m~, fk-e29393df0cd4 l✓, fk-5827f41eb082 l✓, fk-657669b23e71 l~ |
| web-dashboard | h12 | fk-7eb56fda0b1c h✓, fk-1d143fefefed m✓, fk-da0e3a4df6e7 m✓, fk-3239afd8ce6b m✓, fk-2e7ddcee2379 l~ |
| web-dashboard | h3 | fk-8107696f0b02 m✓, fk-81e62b2640a7 m✓, fk-29af8a4fe018 m✓, fk-006c3339e3b2 l✓ |
| web-dashboard | h7 | fk-60410de6dd0a h✓, fk-bfdae4525795 m✓, fk-8e109704aa24 m✓, fk-7bdd33abd0ff l✓ |
| web-dashboard | h9 | fk-df9d0fc1b2d3 m✓, fk-c14c02dc1b77 m✓, fk-4540d657bff6 m✓, fk-bd7f2abebeba l✓, fk-02500b87f3cb l✓ |
| web-dashboard | kind:defect | fk-8f4f4d63f917 m✓, fk-55f4e4ea396d m✓, fk-b867cc3e5653 h✓, fk-0097b5aaa45c m✓ |
| web-dashboard | h1 | fk-ce345e3b013d m✓, fk-acdc650baeb8 l✓, fk-2ac79d7a1989 l✓, fk-d8ad51b22de5 l✓ |
| web-dashboard | h4 | fk-ab16fff6f6c3 m✓ |
| web-dashboard | h13 | fk-cdcdf320a9e8 l✓ |
| web-dashboard | tests | fk-f6c905f91d32 l✓ |
| web-dashboard | h5 | fk-7aaa879bf0ac l✓ |
| web-dashboard | comments | fk-3cd0d3f3b512 l✓, fk-021a21b35427 l~ |
| web-dashboard | h6 | fk-c3625a25eed4 l✓ |
| repo | h11 | fk-2264bc150fa3 h✓, fk-416eb5643e7a h✓, fk-f99038047a27 m✓, fk-71b4ca35efe0 m✓, fk-f3a20a6d53e0 m✓, fk-f48c29a98a89 l✓, fk-1abd62632ae1 m~, fk-293a1282ace4 l✓, fk-6b7c45f8d766 l✓, fk-3667e4e32155 l✓ |
| repo | h10 | fk-879e8c13f581 h✓, fk-e5820c5e22ed h✓, fk-eec3806e584e m✓, fk-5de02e56b3af l✓, fk-dc5370224a78 l✓, fk-b0607cc5a685 l✓ |
| repo | h3 | fk-b7241e0ce122 h✓, fk-2106d1fbaed0 m✓ |
| repo | h12 | fk-d2881616c782 m✓, fk-dd434cb2d4b9 l✓ |
| repo | h9 | fk-ca5301a6f39f m✓, fk-8376e0ab00db l~ |
| repo | h5 | fk-789558b03270 m✓, fk-ac70915ba435 l✓ |
| repo | h7 | fk-cc292d7ce407 l~, fk-a0b751097301 l~ |
| repo | comments | fk-31fd9d5d4c68 l✓, fk-a9aad5f6d1b2 l✓, fk-b523bff3e51c l✓ |
| repo | h1 | fk-89afcb2b57f7 m✓ |
| repo | kind:defect | fk-e756dab8077e m✓ |
| repo | tests | fk-d89ee8df893c l✓ |
| repo | h4 | fk-f66948b9528c l✓ |
| repo | h13 | fk-19457544d6b6 l✓ |
| repo | h2 | fk-32d5e6707fb5 l✓ |

## High findings

### simulation-core

_re-observed_

#### fk-a9c609ecb8ef (home-battery-dispatch.1) — `src/solar_challenge/flow.py::simulate_timestep`

tags h10, h11, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** There is no shared definition of a valid physical quantity. Each class spells its own comparison, in three incompatible polarities. (a) NaN-permissive: `if x < 0` / `if x <= 0`. dispatch.py has 21 such guards: DispatchDecision.__post_init__ x3, the same five-check input block copied into each of the three decide_action methods x15, compute_grid_charge_power_kw, PeakShavingStrategy.__init__. heat_pump.py::HeatPumpConf…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-f126b1c9cbbe (home-battery-dispatch.2) — `src/solar_challenge/battery.py::Battery`

tags h11, h9, h10, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** The battery has five capacity concepts and no single value owns them. (1) BatteryConfig.capacity_kwh is nominal. (2) BatteryConfig.nominal_usable_capacity_kwh uses the config's SOC fractions, not a Battery's overridden ones. (3) SOH is resolved only inside Battery.__init__: the override wins, otherwise compute_soh with throughput fixed at 0.0. finance.py::_aged_homes runs compute_soh separately and injects the result…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-0edf0069c6bb (pv-weather.1) — `src/solar_challenge/pv.py::_module_parameters`

tags h10, h3, h12, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** PVConfig.module_efficiency is validated in __post_init__ but is read nowhere in pv.py; the only module-building function that accepts an efficiency, create_simple_module_params, is not fed from PVConfig. _module_parameters applies temperature_coefficient only through the sentinel test `config.temperature_coefficient != -0.004`, and writes it to gamma_pdc on a CEC catalogue module, where pvlib's single-diode model rea…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-7440003fdd59 (R5) — `src/solar_challenge/flow.py::simulate_timestep`

tags kind:defect, h10, kind:critical-path, kind:cross-module, kind:deep-read, comments · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Battery charge losses vanish from the energy accounts on both charge paths, and the per-timestep balance validator cannot see it. Battery.charge returns the energy STORED after charge_efficiency (battery.py:430-463), and both simulate_timestep (flow.py:276-283, 303-304) and simulate_timestep_tou (flow.py:383-399, 425-426) then set grid_export = excess - pv_charge_stored and grid_import = shortfall - discharge + grid_…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

#### fk-1d920c89e872 (R6) — `src/solar_challenge/load.py::generate_load_profile`

tags kind:defect, h13, kind:critical-path, kind:deep-read, tests · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Both load paths lay each simulated day's 1,440 one-minute values positionally onto a tz-aware Europe/London minute index and trim or pad the surplus at the END of the window (load.py:345-362 for the default richardsonpy path, 492-519 for Elexon), so every day after a clock change inside the window is displaced by an hour against the local wall clock until the next change. Measured on the pinned tree: April 4 2024's E…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

#### fk-f5cd69400ce6 (R7) — `src/solar_challenge/pv.py::PVConfig`

tags h1, h11, kind:deep-read, kind:critical-path · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** PVConfig.module_efficiency ("Panel efficiency as fraction") and PVConfig.temperature_coefficient ("Power temp coefficient per degC") have no effect on simulated output on the default path. module_efficiency is read nowhere in pv.py; temperature_coefficient is written only as gamma_pdc onto the CEC module dict, and only when it differs from the literal sentinel -0.004 that duplicates the field default (pv.py:485-486),…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

#### fk-649851e5fc38 (scenario-config.1) — `src/solar_challenge/config.py::_number`

tags h10, h11, h12, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** config.py has 51 numeric coercion sites, and no one reader enforces the rule 'a finite number, never a bool, a whole number where a count is meant, refused with the key path'. The block readers use three different styles. (a) Raw splat into the domain dataclass: _parse_pv_config, _parse_battery_config, _parse_load_config, _parse_grid_charge_config, and parse_home_block's scalar keys. The component __post_init__ check…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-148991ab9439 (scenario-config.2) — `src/solar_challenge/config.py::_modify_battery_config`

tags h11, h3, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** PVConfig's defaults (azimuth 180.0, tilt 35.0, module_efficiency 0.20, inverter_efficiency 0.96, degradation_rate_per_year 0.005) are written four times: in pv.py::PVConfig, in config.py::PVDistributionConfig's field defaults, in config.py::_parse_pv_distribution_config's data.get(..., 180.0) calls, and in config.py::generate_homes_from_distribution's `pv_azimuth if pv_azimuth is not None else 180.0` fallbacks. EV de…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-2264bc150fa3 (scenario-config.3) — `src/solar_challenge/cli/utils.py::load_config_with_overrides`

tags h11, h12, h7, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Which document a config file is (a scenario list, one scenario, a bare scenario, a wrapped or flat home file, fleet homes, a fleet distribution, a YAML sweep) is decided by testing for top-level keys. Each of these makes that decision on its own, with its own order and fallback: config.py::load_scenarios ('scenarios', then 'scenario', else the whole document), config.py::load_home_config ('home', else a flat file), c…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-0e58e2a7e007 (R3) — `src/solar_challenge/config.py::generate_homes_from_distribution`

tags h3, h2, h4, kind:deep-read, kind:critical-path · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Heuristic 3, carefully factored orthogonal dimensions of variability: the spec-type x field axis of fleet generation has no single mechanism, and the gaps produce silently wrong fleets. Parsing is table-driven and accepts every spec type for every field (_DISTRIBUTION_SPEC_TYPES, config.py:1213-1238, via _parse_distribution_spec; heat_pump_type accepts any dict spec at 1408-1412), but which spec types a field can act…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

#### fk-3be3240278ee (R4) — `src/solar_challenge/config.py::parse_fleet_config`

tags h11, kind:critical-path, h10, kind:cross-module, h1, kind:deep-read · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** The library loader has no owner for which of a scenario's top-level blocks reach its homes. Each consumer re-decides, with different coverage and different conflict policies. In config.py, _read_fleet_distribution_file (config.py:2346-2367) gives fleet_distribution homes location: and tariff: but not seg:. The homes: branch of parse_fleet_config (config.py:2387-2395) gives location: only, so a top-level tariff: in a…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

### finance-economics

_re-observed_

#### fk-b7241e0ce122 (finance-economics.1) — `src/solar_challenge/cli/finance.py::run`

tags h3, h1, h2 · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** `finance run` has three independent axes: --assumptions (physics/spreadsheet/both), --flex-band, and FinanceConfig.grid_services_model. Each one reaches a different subset of the computations rendered into one board report. --assumptions is applied only to the two bill_distribution calls. project_multi_year, solve_cost_recovery_rate and compute_grid_services_at_events all read the unmodified scenario `finance`. Two c…

**Next change.** Plausible next change: report the cost-recovery solve or the economics under both assumption sets, or add a fourth mode such as a calibrated override. The agent must know four things beyond this file. generate_finance_report's first positional is named bill_physics and fixes the heading. The project…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-all-solar_challenge-20261013.

#### fk-52fa98174363 (finance-projection.1) — `src/solar_challenge/finance.py::_physics_import_cost_gbp`

tags h7, h11, h12, h10, tests, kind:cross-system-patching · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** home.py::simulate_home encodes 'no tariff' as a priced cost of 0.0 for every timestep (`import_costs = [0.0 ...]` when tariff_config is None) and 'no SEG' as export revenue of 0.0. home.py::SummaryStatistics then carries only the totals total_import_cost_gbp and total_export_revenue_gbp. It does not carry whether they were priced, or at what rate. Finance has to rebuild that lost fact from the totals. (1) finance.py:…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-caeaf35c8151 (finance-projection.2) — `src/solar_challenge/finance.py::project_multi_year`

tags h11, h10, h1, tests, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** One home's annual flows (own-use, import and its cost, export and its SEG) are put together twice. householder_bill annualises, applies the retail fallback, switches physics/override through _billed_energy, re-prices import and calls bill. project_multi_year._simulate_age annualises again, calls _billed_energy with `_cbs_own_use_kwh(s) * phys.scale`, sums physics export and import, and calls _seg_export_income_gbp, w…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-81d0840d19e2 (finance-projection.3) — `src/solar_challenge/finance.py::_reconcile_seg_homes`

tags h11, h12, h7, comments, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Two fields on config.py::ScenarioConfig hold unresolved pricing overlays: seg_tariff_pence_per_kwh and tariff_config. Neither is applied to HomeConfig at parse time. The SEG rate is applied separately in each of these places: cli/finance.py::run (parse_seg_rate, then `SEGTariff(name="", ...)` and replace on every home), cli/optimize.py::configs (the same block written again), cli/home.py::home_config_for_run (a third…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-c0e0ae3dcca8 (R1) — `src/solar_challenge/finance.py::project_multi_year`

tags h4, h2, h5, h3, kind:deep-read, kind:critical-path · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Heuristic 4, small function scopes, and heuristic 2, simple control flows: project_multi_year (finance.py:1471-1788, 318 lines) produces every board-facing 25-year number, and it does seven jobs in one scope: home resolution and SEG reconciliation, time axes, a model guard, an 86-line nested closure _simulate_age (1556-1641) that runs a fleet sim and computes own-use, SEG, grid services, PV and battery SOH, the seed…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

### web-dashboard

_re-observed_

#### fk-7eb56fda0b1c (web-jobs-runs.1) — `src/solar_challenge/web/api.py::get_job_progress`

tags h12, h10, h11, kind:stringly-typed · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** There is one producer and two consumers of the progress stream, and no shared definition of what the stream says. In api.py::_job_event_payload each event type gets a different subset of JobState, in a different key order: progress has 4 keys, complete has 5 and error has 2. api.py::get_job_progress also writes three frames by hand, outside that builder: the 10-minute timeout and 'Job not found' frames as {"error": .…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-484952247bb6 (web-jobs-runs.2) — `src/solar_challenge/web/jobs.py::JobManager._finish_job`

tags h10, h11, h7, kind:state-machine-gap · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** A job's progress through queued→running→completed|failed is recorded as four separate facts with no legal-transition table: JobState.status, _TrackedJob.finished_at, the jobs-row status and the runs-row status. JobManager._report_state overwrites the state with whatever it is handed. Only _run_job's try/except makes a job terminal, and the executor boundary does not: JobManager._finish_job, the done-callback that run…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-a37ed16d59c5 (web-jobs-runs.3) — `src/solar_challenge/web/storage.py::RunRecord.decoded_summary`

tags h10, h12, h11, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** save_home_run writes summary_json from SummaryStatistics and save_fleet_run writes it from FleetSummary, and the two key sets differ. For example, FleetSummary has fleet_self_consumption_ratio and no self_consumption_ratio, grid_dependency_ratio or total_battery_charge_kwh. Yet RunRecord.decoded_summary returns Any, and the run's `type` never selects a schema on the way out. At least six readers read home keys by str…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-b867cc3e5653 (R8) — `src/solar_challenge/web/assistant.py::chat`

tags kind:defect, h10, kind:critical-path, kind:deep-read · severity **high** · verdict confirmed · class mechanical · re-observed · disposition filed:701

**Statement.** chat() breaks the chat_messages invariant it exists to keep (one assistant row with real content after every user row) on two paths. (1) An API error before the first streamed token (rate limit after retries, 529 overload, a bad key or SOLAR_ASSISTANT_MODEL, a network fault) lands in the except at assistant.py:1012-1022, which saves an assistant row whose content is the empty accumulated text. The next request replay…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

#### fk-60410de6dd0a (web-form-parsing.1) — `src/solar_challenge/web/fleet_config.py::_build_distribution_dict`

tags h7, h10, h11, h12, kind:cross-system-patching · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** config.py's distribution grammar reads numbers with bare float()/int(). config.py::_build_normal_spec calls float(data['mean']), _build_weighted_discrete_spec calls float(w), and _build_shuffled_pool_spec calls int(c), which truncates 2.5 and raises OverflowError on inf. parse_fleet_distribution_config truncates n_homes with int() and takes seed unchecked. NormalDistribution, UniformDistribution and ShuffledPoolDistr…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-a6d9f3e5a7e2 (web-form-parsing.2) — `src/solar_challenge/web/fleet_config.py::_build_distribution_dict`

tags h11, h3, h9, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Both fleet pages edit a component through one editor state, fleet_components.py::EditorDistribution.editor_state and distribution-editor.js, but each page serialises it into its own wire grammar. fleet-simulator.js _buildDistPayload posts a nested body: {pv: {capacity_kw: {type, mean, ..., values: [{value, weight}], entries: [{value, count}]}}}. scenario-builder.js componentFormData flattens the same state to pv_dist…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-42c0053b9a2b (web-templates-theme.1) — `src/solar_challenge/web/templates/results/home.html`

tags h11, h12, h9, kind:duplication · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Each chart on a results page is described in four unrelated places. (1) routes.py::home_results builds a dict keyed by chart name, whose values are JSON strings. A builder returns '{}' (sankey_diagram, sweep_parameter_chart), None (monthly_summary, seasonal_comparison, heat_pump_analysis) or JSON, so 'nothing to draw' is a three-state string convention (heuristic 12). (2) results/home.html and fleet.html guard each c…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-a0866b1bd680 (R9) — `src/solar_challenge/web/fleet_scenario.py::parse_fleet_form`

tags h10, kind:defect, kind:critical-path, kind:cross-module · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Heuristic 10, clear invariants uniformly enforced. A shuffled_pool distribution must hold one value per home (ShuffledPoolDistribution's docstring, config.py:128, 'must sum to n_homes'; the editor's hint, distribution-editor.html:108, 'Counts should sum to the fleet size'), but no reader enforces it: ShuffledPoolDistribution.__post_init__ checks lengths, negatives and an all-zero total only; the fleet form's _pool_co…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

### repo

_re-observed_

#### fk-879e8c13f581 (surface-lock.1) — `tests/_surface_forms.py::surface_form`

tags h10, h9, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** surface_form returns a string built from inspect.signature (or the Enum member list, or the constant's type name), and member_forms adds body names. Anything outside that lens is unpinned. I ran the helper on fixture classes (Python 3.14). A frozen dataclass and the same dataclass with frozen=False, order=True produce an identical surface_form ('(a: int, b: str = 'x') -> None') and an identical empty member_forms. Th…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-e5820c5e22ed (build-lanes.1) — `tests/unit/test_e2e_extra.py::test_e2e_extra_floor_excludes_releases_lacking`

tags h10, h11, kind:missing-invariant · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** The invariant 'every release a declared floor admits works with this code' is checked nowhere, and the lock hides it. uv.lock pins every direct dependency far above its floor: pandas>=2.0.0 against 3.0.3, mypy>=1.0.0 against 2.1.0, pytest>=7.0.0 against 9.0.3, typer>=0.12.1 against 0.26.3, playwright>=1.51.0 against 1.61.0, scipy>=1.7.2 against 1.17.1. The lanes probe the locked set (verify, interpreter matrix) and t…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run hotspot-survey-solar_challenge-20261013.

#### fk-416eb5643e7a (R2) — `src/solar_challenge/cli/home.py::home_config_for_run`

tags h11, h6, kind:cross-module, kind:deep-read · severity **high** · verdict confirmed · class structural · re-observed · disposition open

**Statement.** Heuristic 11, SPOT: `home run` reads a home file through a second reader, cli/utils.py::load_config_with_overrides (utils.py:144-203) plus `config_dict.get("home", {})` (home.py:50-52). The canonical home-file loader, config.load_home_config (config.py:2302-2325), is what `validate config` uses, and the two disagree. (1) Flat home files: config.load_home_config accepts a file whose top level is the home block. A flat…

Measurements, proposal and the skeptic's note: in the findings JSON and in the source run review-solar_challenge-20261013.

### cross-area

_new_

#### fk-16df1a7ac416 (stateless.1) — `src/solar_challenge/load.py::_try_richardsonpy_profile`

tags h7, h5, tests, kind:latent-bug · severity **high** · verdict confirmed · class structural · new · disposition open

**Statement.** Per-home seeding (CLAUDE.md: 'Reproducible simulations via per-home seeding') is carried through process-global state, not the call. _try_richardsonpy_profile does `np.random.seed(config.seed); random.seed(config.seed)` and then lets richardsonpy draw from the global numpy and random generators. config.generate_homes_from_distribution, by contrast, samples through an explicit random.Random(config.seed).

A profile's output therefore depends on whatever ran before it in the same process:
- **Unseeded after seeded:** an unseeded LoadConfig simulated after a seeded one is a deterministic copy (probe: two unseeded runs after seed 5 are identical).
- **External seeding:** an unseeded run after an external np.random.seed(123) is reproducible, so a caller's unrelated seeding silently fixes it.
- **Concurrent threads:** the web JobManager runs simulations on a ThreadPoolExecutor(max_workers=2) (jobs.py:207), and web fleets are seeded (default seed 42, home i gets 42+i, config.py:1751-1754). Two concurrent seeded profiles (seeds 42 and 43) differed from their serial runs in 10 of 10.

A web fleet run started while another job runs is stored as seeded yet is not reproducible, and nothing reports it. The same leak crosses homes within a ProcessPoolExecutor worker in fleet.simulate_fleet_iter. The stochastic engine also has no seam: tests reach it by patching richardsonpy's module attribute (test_load.py:404, 431, 514) and load's private _simulate_stochastic_day (test_load.py:547).

**Measurements.**
- concurrent seeded profiles differing from their serial run: 10 of 10 (5 trials x 2 seeds) — rule: Probe at 7dfea36: generate_load_profile(LoadConfig(3400, 3 occupants, use_stochastic=True, seed=s)) for 2024-06-01..07 with s=42 and 43, run serially as reference, then 5 times concurrently on ThreadPoolExecutor(2); compared with Series.equals.
- order dependence of unseeded profiles: unseeded after seed 5: identical across repeats; unseeded after external np.random.seed(123)/random.seed(123): identical; two fresh unseeded: differ — rule: Same probe harness, 2024-06-01..02 window, one process.
- RNG plumbing styles in src: 2: explicit random.Random (config.py:1643, web/fleet_config.py:150) vs global np.random/random seeding (load.py:272-274) — rule: grep for random.seed, np.random.seed, random.Random, default_rng over src/solar_challenge.
- test reach-ins into the stochastic engine: 4 monkeypatch sites (3 on richardsonpy.classes.appliance.run_application_simulation, 1 on load._simulate_stochastic_day) — rule: AST scan of tests for setattr calls whose target is a solar_challenge or richardsonpy module object.

**Next change.** An agent adding parallelism (e.g. raising JobManager max_workers, or running web fleet jobs through simulate_fleet) or a new stochastic generator will assume the seed travels with LoadConfig, as the config sampler's does. They must know richardsonpy reads only the globals. Today nothing catches a wrong version: no test runs two seeded simulations concurrently or checks an unseeded home after a seeded one.

**Proposal.** Give load.py one owner of the global-RNG hand-off: a module-private lock plus a context that saves the np.random/random state, seeds it from the LoadConfig's seed (or fresh SeedSequence entropy when the seed is None), runs the richardsonpy window, and restores the state. Every stochastic draw goes through it. Make the per-day simulator an injectable parameter of generate_load_profile so tests stop patching richardsonpy and load privates. Add a test that runs two seeded profiles on two threads and compares them with the serial ones.

**Skeptic.** load.py:255-290 (_try_richardsonpy_profile), config.py:1643/1751-1754, web/fleet_config.py:150/220, web/jobs.py:207, tests/unit/test_load.py monkeypatch sites; ran a probe of generate_load_profile against a git-archive export of 7dfea36 (the review worktree path does not exist; commit exists). — Probe reproduced all three behaviours; global np.random/random seeding confirmed in source. Web fleet default seed 42 and home seed = seed+i confirmed.


## All findings

One line per finding that is not high: key · anchor · severity · verdict · class · disposition (statements, measurements and skeptic notes are in the findings JSON; re-observed findings keep their full text in the source run's report).

### simulation-core

*simulation-core/physics*: The review worktree named in the brief did not exist, so the pinned commit 7dfea36 was extracted with git archive into the seat scratchpad and read there. All 17 READ FULLY files were read in full (7,555 lines). The extra lines in lines_read are the seams followed out of the slice: briefing conventions, config._parse_battery_config, scenario_writer._battery_block, tariff.economy_7/10 and the test_measurement_scripts filter. Probes ran against the repo's .venv, which has pvlib 0.15.1, the version uv.lock pins.

Layering is clean. The import graph shows no cycles and no reach-backs in the slice. timebase and location sit at the bottom, then battery, dispatch and flow, then home, then fleet and…

*simulation-core/config-cli*: The pinned worktree was gone, so I read 7dfea36 from a git archive extracted into the seat scratchpad. I read all 12 READ FULLY files (6148 lines) and ran probes against that tree with the project's .venv.

Two well-built mechanisms exist. Since task 238, every nested reader refuses unknown keys through _refuse_unrecognised_keys and _BlockType tables. The CLI's stdout/stderr discipline in cli/utils is clean. No test imports a private name from any slice module, and no slice module is patched by dotted path.

The cost of the next change sits in config.py. It is 2815 lines with a prose share of 0.256, and it holds eight separable concerns (h14 measurement below). Five unenforced policies run t…

_new_
- fk-35b8ddcf5565 · `src/solar_challenge/battery.py::BatteryConfig` · medium · ✓ confirmed · structural · open — BatteryConfig holds two facts (charge and discharge efficiency) in three fields: efficiency, charge_efficiency…
- fk-48447960eb2c · `src/solar_challenge/pv.py::_get_cec_module` · medium · ~ weakened · mechanical · filed:756 — Every default PV simulation uses one CEC module, and nothing names it. It is found by substring search over pv…
- fk-7ef1099d24e8 · `src/solar_challenge/timebase.py` · low · ✓ confirmed · structural · open — The simulation's cadence is one axis handled three ways. (1) timebase.HOURS_PER_MINUTE is documented both as a…
- fk-b97bf2325eda · `src/solar_challenge/load.py::calculate_annual_consumption` · low · ✓ confirmed · mechanical · filed:757 — calculate_annual_consumption does not compute an annual figure. Its docstring opens 'Despite the name (kept fo…
- fk-d6f16d95b126 · `src/solar_challenge/heat_pump.py::calculate_cop` · low · ✓ confirmed · structural · open — The heat-pump type vocabulary is written out in five places and the per-type COP curve in a sixth: (1) the Hea…
- fk-6a52ed98b18e · `src/solar_challenge/cli/utils.py::create_summary_table` · medium · ✓ confirmed · structural · open — create_summary_table takes `summary: Any` and picks its rows by testing for attribute names (hasattr and getat…
- fk-ac39320dcf1d · `src/solar_challenge/config.py::detect_sweep_spec` · medium · ✓ confirmed · structural · open — Where a YAML-defined sweep may sit is decided in one hard-coded place, while the grammar accepts it in 19.

-…

_re-observed_
- fk-bd03fe349ffd · `src/solar_challenge/ev.py::generate_ev_charging_profile` · medium · ~ weakened · structural · open
- fk-616cc076b7cb · `src/solar_challenge/pv.py::create_model_chain` · low · ✓ confirmed · structural · open
- fk-94f4881bbe48 · `src/solar_challenge/config.py::_VALID_DISPATCH_STRATEGIES` · medium · ✓ confirmed · structural · open
- fk-f3a20a6d53e0 · `src/solar_challenge/cli/fleet.py::run` · medium · ✓ confirmed · structural · open
- fk-4df47ebe6a96 · `src/solar_challenge/flow.py::simulate_timestep_tou` · medium · ✓ confirmed · structural · open
- fk-04b52ee632c6 · `src/solar_challenge/home.py::HomeConfig` · medium · ✓ confirmed · structural · open
- fk-2a53ae89932e · `src/solar_challenge/battery.py::Battery.charge` · medium · ✓ confirmed · structural · open
- fk-1609d8c3d091 · `src/solar_challenge/home.py::simulate_home` · medium · ✓ confirmed · structural · open
- fk-72af0b90338d · `src/solar_challenge/load.py::_try_richardsonpy_profile` · low · ~ weakened · structural · open
- fk-3ccbba41d836 · `src/solar_challenge/pv.py::simulate_pv_output` · medium · ✓ confirmed · structural · open
- fk-8b8f9d686b86 · `src/solar_challenge/pv.py::wired_dc_capacity_kw` · medium · ✓ confirmed · structural · open
- fk-06035cd76226 · `src/solar_challenge/weather.py::get_weather_cache` · medium · ✓ confirmed · structural · open
- fk-e4549a3a6b54 · `src/solar_challenge/weather.py::WeatherCache` · low · ~ weakened · structural · open
- fk-a98db49f3fd7 · `src/solar_challenge/pv.py::_module_rating_w` · low · ✓ confirmed · mechanical · filed:699
- fk-7dcdc5559d22 · `src/solar_challenge/location.py::Location.__post_init__` · low · ✓ confirmed · mechanical · filed:382
- fk-370b3e49b67c · `src/solar_challenge/battery.py::BatteryConfig` · medium · ✓ confirmed · structural · open
- fk-50a3985fae0f · `src/solar_challenge/battery.py::compute_soh` · medium · ✓ confirmed · structural · open
- fk-664e2030921e · `src/solar_challenge/community.py::simulate_community` · medium · ✓ confirmed · mechanical · filed:706
- fk-f622bbaa9f2e · `src/solar_challenge/dispatch.py::DispatchDecision` · medium · ✓ confirmed · structural · open
- fk-740e9a804a4f · `src/solar_challenge/ev.py::generate_ev_charging_profile` · medium · ✓ confirmed · mechanical · filed:708
- fk-e58042aef503 · `src/solar_challenge/fleet.py::simulate_fleet` · medium · ✓ confirmed · mechanical · filed:709
- fk-491014934d1e · `src/solar_challenge/flow.py::simulate_timestep_tou` · medium · ✓ confirmed · mechanical · filed:270
- fk-a80aa8f942eb · `src/solar_challenge/home.py::simulate_home` · medium · ✓ confirmed · mechanical · filed:710
- fk-89777ec9faad · `src/solar_challenge/load.py::_get_daily_profile_kwh` · medium · ✓ confirmed · mechanical · filed:711
- fk-2f88003e22c8 · `src/solar_challenge/tariff.py::TariffConfig` · medium · ✓ confirmed · structural · open
- fk-dc5cf2ec9b84 · `src/solar_challenge/community.py::simulate_community` · low · ✓ confirmed · mechanical · filed:743
- fk-00cb82820af9 · `src/solar_challenge/dispatch.py::TOUOptimizedStrategy.decide_action` · low · ✓ confirmed · mechanical · filed:744
- fk-99244625d7f2 · `src/solar_challenge/dispatch.py::compute_grid_charge_power_kw` · low · ✓ confirmed · structural · open
- fk-7fa120a8bb98 · `src/solar_challenge/ev.py::EVConfig` · low · ✓ confirmed · mechanical · filed:745
- fk-e0e34ef46058 · `src/solar_challenge/fleet.py::FleetConfig.create_uniform` · low · ✓ confirmed · mechanical · filed:746
- fk-8995288451e6 · `src/solar_challenge/fleet.py::FleetResults` · low · ✓ confirmed · structural · open
- fk-f7b19fc4c8b5 · `src/solar_challenge/fleet.py::simulate_multi_sweep_iter` · low · ✓ confirmed · mechanical · filed:747
- fk-f2f8a5512feb · `src/solar_challenge/home.py::SummaryStatistics` · low · ✓ confirmed · structural · open
- fk-ef13881623be · `src/solar_challenge/home.py::calculate_summary` · low · ✓ confirmed · structural · open
- fk-c78416de5500 · `src/solar_challenge/load.py::_try_richardsonpy_profile` · low · ✓ confirmed · structural · open
- fk-998f0cb69410 · `src/solar_challenge/pv.py::simulate_pv_output` · low · ✓ confirmed · mechanical · filed:284
- fk-606a9211b34d · `src/solar_challenge/seg.py::SEGTariff` · low · ✓ confirmed · structural · open
- fk-97213a0e9ab2 · `src/solar_challenge/tariff.py::TariffPeriod` · low · ✓ confirmed · mechanical · filed:748
- fk-756c0ef9e9d9 · `src/solar_challenge/validation.py::_check_annual_yield` · low · ✓ confirmed · mechanical · filed:749
- fk-835a87838a52 · `src/solar_challenge/validation.py::validate_self_consumption_pv_only` · low · ✓ confirmed · structural · open
- fk-2b16cc8bcf46 · `src/solar_challenge/scenario_writer.py::_pv_block` · medium · ✓ confirmed · structural · open
- fk-e2aaf2bfe651 · `src/solar_challenge/config.py::parse_home_block` · medium · ✓ confirmed · structural · open
- fk-4435376bedb3 · `src/solar_challenge/config.py::ConfigurationError` · medium · ✓ confirmed · structural · open
- fk-2dc9d1cd2c06 · `src/solar_challenge/config.py` · medium · ✓ confirmed · structural · open
- fk-d2b4045c6676 · `src/solar_challenge/config.py::_modify_pv_config` · medium · ✓ confirmed · structural · open
- fk-9df95e9e2b45 · `src/solar_challenge/__init__.py::_SYMBOL_MODULE` · low · ~ weakened · structural · open
- fk-62821dcde535 · `src/solar_challenge/config.py` · medium · ✓ confirmed · structural · open
- fk-291910b552af · `src/solar_challenge/config.py::ConfigurationError` · medium · ✓ confirmed · structural · open
- fk-c36d6fcbc2a8 · `src/solar_challenge/config.py::DispatchStrategyConfig` · medium · ✓ confirmed · structural · open
- fk-897e13f84164 · `src/solar_challenge/config.py::ScenarioConfig` · medium · ✓ confirmed · structural · open
- fk-f2e1ad46df4b · `src/solar_challenge/config.py::_DistributionSampler` · medium · ✓ confirmed · mechanical · filed:297
- fk-a2b33a420bcf · `src/solar_challenge/config.py::generate_homes_from_distribution` · medium · ✓ confirmed · mechanical · filed:675
- fk-dfeefbe95640 · `src/solar_challenge/config.py::generate_homes_from_distribution` · medium · ✓ confirmed · structural · open
- fk-e79170280adf · `src/solar_challenge/config.py::substitute_config_variables` · medium · ✓ confirmed · mechanical · filed:707
- fk-41767a1bc146 · `src/solar_challenge/output.py::calculate_seasonal_metrics` · medium · ✓ confirmed · mechanical · filed:712
- fk-caad5305a3be · `src/solar_challenge/config.py::run_parameter_sweep` · low · ✓ confirmed · mechanical · filed:237
- fk-ae20e1833a19 · `src/solar_challenge/output.py` · low · ✓ confirmed · structural · open

### finance-economics

*finance-economics*: The slice is two strata: domain modules (finance.py 2376 lines, optimize.py, gridservices.py, tariff.py, flex.py, seg.py) and two Typer front-ends (cli/finance.py, cli/optimize.py). The leaf value modules are small and frozen: seg, flex, tariff and the gridservices dataclasses. The bill arithmetic has one honest core, finance.bill(), and BillBreakdown enforces its CBS identity at construction. The next-change cost sits in three places. (1) finance.py still holds five jobs: config, billing, projection, economics and the solve. Its two ledger assemblies, householder_bill and _simulate_age, are tied only by shared private helpers. The 25 prior findings here are all still present at 7dfea36, and…

_new_
- fk-286fe17c28c9 · `src/solar_challenge/finance.py::householder_bill` · medium · ✓ confirmed · structural · open — householder_bill's public parameter `annual_self_consumption_kwh` is not annual. The function multiplies it by…
- fk-872021ade9b6 · `src/solar_challenge/tariff.py::TariffConfig` · medium · ✓ confirmed · structural · open — TariffConfig's defining invariant, that its periods tile the 24-hour day exactly once, is not checked at const…
- fk-f4d53977c642 · `src/solar_challenge/gridservices.py::GridServicesAtEvents` · low · ~ weakened · mechanical · open — GridServicesAtEvents' docstring declares `sum(per_window_income_gbp) == annual_income_gbp` a 'design invariant…

_re-observed_
- fk-be5b13274bcb · `src/solar_challenge/cli/optimize.py::configs` · medium · ~ weakened · structural · open
- fk-3ca00f8edeb8 · `src/solar_challenge/optimize.py::sensitivity_panel` · low · ✓ confirmed · structural · open
- fk-4a9af7c31a4f · `src/solar_challenge/finance.py::solve_cost_recovery_rate` · medium · ✓ confirmed · structural · open
- fk-aafe32daa988 · `src/solar_challenge/finance.py::FinanceConfig` · medium · ✓ confirmed · structural · open
- fk-b69968a37b36 · `src/solar_challenge/seg.py::SEGTariff` · medium · ✓ confirmed · structural · open
- fk-41283f42a36a · `src/solar_challenge/finance.py` · low · ~ weakened · structural · open
- fk-5fdb04305288 · `src/solar_challenge/finance.py` · medium · ✓ confirmed · structural · open
- fk-c2c9277c1920 · `src/solar_challenge/finance.py` · medium · ✓ confirmed · structural · open
- fk-3f4daea21220 · `src/solar_challenge/finance.py::BillDistribution` · medium · ✓ confirmed · structural · open
- fk-808be5588896 · `src/solar_challenge/finance.py::CostRecoverySolution` · medium · ✓ confirmed · structural · open
- fk-d432a549b03f · `src/solar_challenge/finance.py::FinanceConfig` · medium · ✓ confirmed · structural · open
- fk-62dbe0f34b68 · `src/solar_challenge/finance.py::YearPoint` · medium · ✓ confirmed · mechanical · filed:702
- fk-758b2f309cab · `src/solar_challenge/finance.py::project_multi_year` · medium · ✓ confirmed · structural · open
- fk-da69830bb2d6 · `src/solar_challenge/gridservices.py::EventWindow` · medium · ✓ confirmed · structural · open
- fk-3b0a239d0489 · `src/solar_challenge/optimize.py::_evaluate_config` · medium · ✓ confirmed · structural · open
- fk-6cd8a932665c · `src/solar_challenge/finance.py` · low · ✓ confirmed · mechanical · filed:581
- fk-0b791f2be2d6 · `src/solar_challenge/finance.py::_resolve_homes` · low · ✓ confirmed · mechanical · filed:485
- fk-50cf1dd5df58 · `src/solar_challenge/finance.py::_seg_export_income_gbp` · low · ~ weakened · mechanical · filed:715
- fk-9fa18977ec68 · `src/solar_challenge/finance.py::bill` · low · ✓ confirmed · mechanical · filed:716
- fk-5b34adae950b · `src/solar_challenge/finance.py::solve_cost_recovery_rate` · low · ~ weakened · structural · open
- fk-0f24b7f66eb2 · `src/solar_challenge/gridservices.py::GRID_SERVICES_RATE_BANDS` · low · ✓ confirmed · structural · open
- fk-72fdec5965a1 · `src/solar_challenge/optimize.py` · low · ✓ confirmed · mechanical · filed:717
- fk-0b4f5e04067c · `src/solar_challenge/optimize.py::sensitivity_panel` · low · ✓ confirmed · mechanical · filed:718

### web-dashboard

*web-dashboard/server*: The review worktree named in the brief no longer exists. I read the pinned commit 7dfea36 through `git archive` into the seat scratchpad and read all 11 READ FULLY files in rank order (4,482 lines). I also read presets.py (114 lines) and short excerpts of home.py and tests to anchor claims.

The server slice is a flat set of Flask blueprints (api, routes, history, assistant) over three persistence modules (database, storage, jobs). shared.py is the app-extension accessor. Strata are partial. RunRecord, RUN_LABELS and the Literal vocabularies (RunType, RunStatus, JobStatus) are recent, careful single homes for facts. The docstrings state contracts precisely, and no test patches a private name…

*web-dashboard/forms-charts*: The tree's worktree had been removed; every read and probe ran on `git archive 7dfea36` extracted to the seat scratchpad, with the main repo's .venv and PYTHONPATH pointed at that tree. All 11 READ FULLY files (3,401 lines) were read in full. The slice has no import-graph symptoms: zero reach-backs, deferred imports, cycles or re-exports among its modules, and no test patches its private names. The test_web_scenarios lead is the test's own `_DEFAULT_FORM` class constant, not module internals.

The leaf modules are healthy and coherent:
- number_fields.py: one reader family with informative refusals.
- fleet_components.py: a real SPOT for component metadata, enforced in `__post_init__`.
- cha…

_new_
- fk-273b8b09c91a · `src/solar_challenge/web/storage.py::_deserialize_dataclass` · medium · ~ weakened · structural · open — A stored run's config.json and summary.json are rebuilt into the current HomeConfig, SummaryStatistics and Fle…
- fk-81e62b2640a7 · `src/solar_challenge/web/database.py::RunType` · medium · ✓ confirmed · structural · open — RunType ('home', 'fleet', 'sweep') selects a run's loader, results page, CSV export and YAML export. No single…
- fk-1070454e4c6e · `src/solar_challenge/web/database.py::init_db` · medium · ~ weakened · structural · open — The database schema is created only by CREATE TABLE IF NOT EXISTS (database.py:171-225). No schema version is…
- fk-e29393df0cd4 · `src/solar_challenge/web/jobs.py::recover_stale_jobs` · low · ✓ confirmed · structural · open — The dashboard needs one process per database (create_app's docstring note, app.py:69-74), but the only stateme…
- fk-066e5cb461f7 · `src/solar_challenge/web/assistant.py::_event_stream` · low · ✓ confirmed · structural · open — The server has two Server-Sent Events producers, assistant.chat and api.get_job_progress. Neither shares an en…
- fk-2ff305a1dbb2 · `src/solar_challenge/web/jobs.py::JobManager._run_home_simulation` · low · ~ weakened · structural · open — The default name of a run is spelled at 11 sites in 6 files: 'Web Simulation', 'Fleet Simulation', 'Unnamed Ru…
- fk-29af8a4fe018 · `src/solar_challenge/web/simulation_params.py::_HOME_CONFIG_DEFAULTS` · medium · ✓ confirmed · structural · open — Heuristic 3, orthogonal dimensions of variability. Whether a field counts as 'not sent' is one axis, and each…
- fk-ad65ad5e4e48 · `src/solar_challenge/web/fleet_scenario.py::_refuse_what_the_loaders_refuse` · low · ~ weakened · structural · open — Heuristic 11, SPOT. 'Would load_fleet_config accept this scenario document' is emulated twice in the slice, an…

_re-observed_
- fk-6c98ee030531 · `src/solar_challenge/web/fleet_scenario.py::FLEET_FORM_REFUSALS` · medium · ✓ confirmed · structural · open
- fk-1d143fefefed · `src/solar_challenge/web/fleet_scenario.py::_fleet_form_location` · medium · ✓ confirmed · structural · open
- fk-006c3339e3b2 · `src/solar_challenge/web/fleet_scenario.py::_FORM_TARIFF_SETTINGS` · low · ✓ confirmed · structural · open
- fk-bea05911eb70 · `src/solar_challenge/web/api.py::simulate_sweep` · medium · ✓ confirmed · structural · open
- fk-c14c02dc1b77 · `src/solar_challenge/web/jobs.py::JobManager._run_job` · medium · ✓ confirmed · structural · open
- fk-9d7f66fdcfdd · `src/solar_challenge/web/jobs.py::JobManager._record_new_job` · medium · ✓ confirmed · structural · open
- fk-4540d657bff6 · `src/solar_challenge/web/jobs.py::JobManager.get_events` · medium · ✓ confirmed · structural · open
- fk-239274130a5a · `src/solar_challenge/web/api.py::simulate_fleet_api` · medium · ~ weakened · structural · open
- fk-acdc650baeb8 · `src/solar_challenge/web/shared.py::resolve_location` · low · ✓ confirmed · mechanical · filed:698
- fk-0097b5aaa45c · `src/solar_challenge/web/api.py::get_job_progress` · medium · ✓ confirmed · mechanical · filed:564
- fk-8f4f4d63f917 · `src/solar_challenge/web/api.py::history_delete_run` · medium · ✓ confirmed · structural · open
- fk-da0e3a4df6e7 · `src/solar_challenge/web/api.py::simulate_fleet_api` · medium · ✓ confirmed · structural · open
- fk-194e5b40da23 · `src/solar_challenge/web/assistant.py::METRIC_TABLE` · medium · ✓ confirmed · structural · open
- fk-ab16fff6f6c3 · `src/solar_challenge/web/assistant.py::chat` · medium · ✓ confirmed · mechanical · filed:713
- fk-0593b530a371 · `src/solar_challenge/web/shared.py::resolve_location` · medium · ✓ confirmed · structural · open
- fk-df9d0fc1b2d3 · `src/solar_challenge/web/storage.py::RunStorage` · medium · ✓ confirmed · structural · open
- fk-34a6679f1ef3 · `src/solar_challenge/web/api.py::history_list_runs` · low · ✓ confirmed · structural · open
- fk-cdcdf320a9e8 · `src/solar_challenge/web/api.py::preview_distribution` · low · ✓ confirmed · mechanical · filed:153
- fk-2ac79d7a1989 · `src/solar_challenge/web/api.py::simulate_sweep` · low · ✓ confirmed · mechanical · filed:750
- fk-f6c905f91d32 · `src/solar_challenge/web/app.py::create_app` · low · ✓ confirmed · structural · open
- fk-93d3bd7aa219 · `src/solar_challenge/web/assistant.py::dispatch_tool` · low · ✓ confirmed · mechanical · filed:751
- fk-7aaa879bf0ac · `src/solar_challenge/web/jobs.py::shutdown_all_managers` · low · ✓ confirmed · structural · open
- fk-9dd1d9389dd2 · `src/solar_challenge/web/builder_form.py::_distribution_spec` · medium · ✓ confirmed · mechanical · filed:697
- fk-7893b49b92c3 · `src/solar_challenge/web/fleet_config.py::_draw_samples` · medium · ✓ confirmed · structural · open
- fk-366773b4083f · `src/solar_challenge/web/static/js/fleet-simulator.js` · medium · ✓ confirmed · structural · open
- fk-40dff1473b94 · `src/solar_challenge/web/static/js/scenario-builder.js` · medium · ~ weakened · structural · open
- fk-021a21b35427 · `src/solar_challenge/web/fleet_config.py` · low · ~ weakened · structural · open
- fk-93ee9a05751a · `src/solar_challenge/web/charts.py::COLOUR_PALETTE` · medium · ✓ confirmed · structural · open
- fk-8e109704aa24 · `src/solar_challenge/web/charts.py::sankey_diagram` · medium · ✓ confirmed · structural · open
- fk-3239afd8ce6b · `src/solar_challenge/web/charts.py::comparison_radar` · medium · ✓ confirmed · structural · open
- fk-8f26d000b68d · `src/solar_challenge/web/templates/history/compare.html` · medium · ✓ confirmed · mechanical · filed:674
- fk-ff5b90768f66 · `src/solar_challenge/web/templates/components/macros.html` · medium · ✓ confirmed · structural · open
- fk-2e7ddcee2379 · `tests/_css_classes.py` · low · ~ weakened · structural · open
- fk-657669b23e71 · `src/solar_challenge/web/static/dist/style.css` · low · ~ weakened · structural · open
- fk-ce345e3b013d · `src/solar_challenge/web/charts.py::financial_breakdown` · medium · ✓ confirmed · mechanical · filed:714
- fk-55f4e4ea396d · `src/solar_challenge/web/charts.py::sweep_parameter_chart` · medium · ✓ confirmed · structural · open
- fk-1df9dbc0d971 · `src/solar_challenge/web/fleet_components.py::FleetComponent` · medium · ✓ confirmed · structural · open
- fk-8107696f0b02 · `src/solar_challenge/web/fleet_config.py::_build_distribution_dict` · medium · ✓ confirmed · structural · open
- fk-a391cf1f4edf · `src/solar_challenge/web/fleet_config.py::apply_fleet_overlay` · medium · ✓ confirmed · structural · open
- fk-88374e6e3553 · `src/solar_challenge/web/fleet_config.py::sample_distribution` · medium · ✓ confirmed · structural · open
- fk-70edc755ede4 · `src/solar_challenge/web/simulation_params.py::_parse_heat_pump_block` · medium · ✓ confirmed · mechanical · filed:245
- fk-d303b6dbf669 · `src/solar_challenge/web/static/js/scenario-builder.js::loadPreset` · medium · ✓ confirmed · structural · open
- fk-02500b87f3cb · `src/solar_challenge/web/charts.py::overlaid_power_flows` · low · ✓ confirmed · mechanical · filed:752
- fk-f8b7b3ab709d · `src/solar_challenge/web/fleet_config.py::MAX_FLEET_HOMES` · low · ✓ confirmed · mechanical · filed:376
- fk-3cd0d3f3b512 · `src/solar_challenge/web/fleet_config.py::_parse_component_distribution` · low · ✓ confirmed · mechanical · filed:753
- fk-c3625a25eed4 · `src/solar_challenge/web/fleet_config.py::form_to_fleet_distribution_config` · low · ✓ confirmed · structural · open
- fk-d8ad51b22de5 · `src/solar_challenge/web/fleet_scenario.py::_read_battery` · low · ✓ confirmed · mechanical · filed:754
- fk-ba29e186122f · `src/solar_challenge/web/simulation_params.py::_HOME_CONFIG_DEFAULTS` · low · ✓ confirmed · mechanical · filed:755
- fk-5827f41eb082 · `src/solar_challenge/web/simulation_params.py::parse_home_config` · low · ✓ confirmed · mechanical · filed:517

### repo

*repo*: The review worktree at .worktrees/review-all-solar_challenge-20261013 no longer existed. I exported 7dfea36 with `git archive` into the seat scratchpad and read that tree.

The repo slice is the project's test infrastructure: 32 tests/_*.py helper modules (3,479 lines), 17 tests/unit/test_*_helper.py files that pin them (4,284 lines), and the lane and verify contract tests that tie dark-factory-orchestrator.yaml, pyproject.toml and uv.lock together.

Most of it is healthy and reads well in isolation. Each helper has a one-sentence purpose, a usage block and typed returns. Each helper test drives the public function against a real throwaway project with no mocks: _lane_collection, _collect_on…

_new_
- fk-789558b03270 · `slug:tracked-claude-symlink` · medium · ✓ confirmed · mechanical · filed:758 — The tree tracks `.claude` as a symlink (git mode 120000, blob 6ddfab8) whose target is `../../../../.claude`.…
- fk-5de02e56b3af · `tests/unit/test_lint.py::test_the_package_passes_the_lint` · low · ✓ confirmed · structural · open — Heuristic 10, uniformly enforced: the verify's static gates cover src/solar_challenge and one test helper.
- t…
- fk-3667e4e32155 · `tests/unit/test_marker_registration.py::TestNetworkedUnitClassesExcludedButPureKept` · low · ✓ confirmed · structural · open — test_marker_registration.py guards network access by hand-kept lists, which the offline guard has since made a…

_re-observed_
- fk-293a1282ace4 · `tests/unit/test_init_lazy_surface.py` · low · ✓ confirmed · structural · open
- fk-ca5301a6f39f · `tests/_surface_forms.py::_parsed` · medium · ✓ confirmed · structural · open
- fk-d2881616c782 · `tests/_surface_forms.py::_Unevaluated` · medium · ✓ confirmed · structural · open
- fk-dc5370224a78 · `tests/unit/test_public_api_surface.py::_drift_message` · low · ✓ confirmed · structural · open
- fk-b0607cc5a685 · `tests/_surface_forms.py::_attributes_set_on_self` · low · ✓ confirmed · mechanical · filed:700
- fk-ac70915ba435 · `tests/_surface_forms.py::_type_checking_imports` · low · ✓ confirmed · structural · open
- fk-1abd62632ae1 · `tests/_lane_collection.py::collect_lane_job` · medium · ~ weakened · structural · open
- fk-eec3806e584e · `tests/conftest.py::pytest_runtest_protocol` · medium · ✓ confirmed · structural · open
- fk-f48c29a98a89 · `tests/conftest.py::collect_ignore` · low · ✓ confirmed · structural · open
- fk-a0b751097301 · `tests/_orchestrator_config.py::lane_job_directory` · low · ~ weakened · structural · open
- fk-a9aad5f6d1b2 · `dark-factory-orchestrator.yaml` · low · ✓ confirmed · structural · open
- fk-dd434cb2d4b9 · `tests/_collect_only.py::collected_node_ids` · low · ✓ confirmed · structural · open
- fk-89afcb2b57f7 · `src/solar_challenge/cli/finance.py::run` · medium · ✓ confirmed · mechanical · filed:703
- fk-f99038047a27 · `src/solar_challenge/cli/finance.py::run` · medium · ✓ confirmed · structural · open
- fk-71b4ca35efe0 · `src/solar_challenge/cli/optimize.py::_SENSITIVITY_ALIAS_MAP` · medium · ✓ confirmed · mechanical · filed:704
- fk-2106d1fbaed0 · `src/solar_challenge/cli/utils.py::create_summary_table` · medium · ✓ confirmed · mechanical · filed:705
- fk-e756dab8077e · `src/solar_challenge/cli/utils.py::load_config_with_overrides` · medium · ✓ confirmed · mechanical · filed:681
- fk-78587492a799 · `src/solar_challenge/__init__.py::_SYMBOL_MODULE` · low · ~ weakened · mechanical · filed:719
- fk-f66948b9528c · `src/solar_challenge/cli/finance.py::run` · low · ✓ confirmed · mechanical · filed:738
- fk-19457544d6b6 · `src/solar_challenge/cli/fleet.py::_print_community_section` · low · ✓ confirmed · mechanical · filed:722
- fk-32d5e6707fb5 · `src/solar_challenge/cli/fleet.py::sweep` · low · ✓ confirmed · mechanical · filed:739
- fk-6b7c45f8d766 · `src/solar_challenge/cli/home.py::quick` · low · ✓ confirmed · mechanical · filed:731
- fk-d89ee8df893c · `src/solar_challenge/cli/home.py::run` · low · ✓ confirmed · mechanical · filed:740
- fk-b523bff3e51c · `src/solar_challenge/cli/optimize.py::configs` · low · ✓ confirmed · mechanical · filed:741
- fk-31fd9d5d4c68 · `src/solar_challenge/cli/utils.py::CliFleetSimulator` · low · ✓ confirmed · mechanical · filed:742

### cross-area

_new_
- fk-1cd332300623 · `src/solar_challenge/finance.py::bill_distribution` · medium · ✓ confirmed · structural · open — The length of the simulated window has a carrier, SummaryStatistics.simulation_days, which home.calculate_summ…
- fk-463e82417506 · `src/solar_challenge/web/routes.py::simulate_home_page` · medium · ✓ confirmed · structural · open — What 'Economy 7' and 'Economy 10' cost has two disagreeing homes.

**Library:** TariffConfig.economy_7 default…
- fk-94cab00e114e · `src/solar_challenge/config.py::SimulationPeriod` · low · ~ weakened · mechanical · filed:759 — The default simulation window has no home in the library.

- **Library:** config.SimulationPeriod declares no…
- fk-753ec8e6e149 · `src/solar_challenge/weather.py::_fetch_mean_annual_ghi_kwh_per_m2` · low · ~ weakened · mechanical · open — Two PVGIS request policies live in weather.py, and only one of them has a single home.

- **TMY request:** a f…
- fk-cca5fd81afda · `src/solar_challenge/web/database.py::get_db` · low · ~ weakened · mechanical · filed:760 — How the dashboard opens a SQLite connection is written three times:
- database.init_db (database.py:63-65) set…
- fk-b3dfd41a4d6a · `src/solar_challenge/config.py::DispatchStrategyConfig` · medium · ~ weakened · structural · open — Two domain value types, DispatchStrategyConfig (config.py:356) and GridChargeConfig (config.py:254), are defin…
- fk-601c5b5f6415 · `src/solar_challenge/config.py::ConfigurationError` · medium · ~ weakened · mechanical · filed:177 — ConfigurationError is the exception that domain value objects raise when a domain invariant fails, but it is d…
- fk-b0f648b0e6d0 · `src/solar_challenge/finance.py::project_multi_year` · medium · ~ weakened · structural · open — finance.py, at 2,376 lines and over the 2,000-line alarm, holds two strata, and the layering cost appears as f…
- fk-8047de9b6789 · `src/solar_challenge/config.py::ScenarioConfig` · medium · ~ weakened · structural · open — ScenarioConfig encodes 'the homes of a scenario' as an either/or of `home` and `homes`, and 'the SEG rate' as…
- fk-66f886576b3f · `src/solar_challenge/location.py::Location` · low · ✓ confirmed · structural · open — The two front ends each define their own location-string grammar, because no stratum below them owns one. loca…
- fk-bd7f2abebeba · `src/solar_challenge/web/shared.py` · low · ✓ confirmed · structural · open — web/shared.py ('Shared helpers') mixes two strata.
- **Request-reading values:** NotAJsonObject, require_json_…
- fk-8376e0ab00db · `src/solar_challenge/cli/main.py` · low · ~ weakened · mechanical · open — The package root and the CLI import each other. cli/main.py:8 does `from solar_challenge import __version__`,…
- fk-fc652220a4d3 · `src/solar_challenge/home.py::_create_dispatch_strategy` · medium · ✓ confirmed · structural · open — Grid charging (battery top-up from the grid in cheap periods) is one axis. It is switched on only by a three-w…
- fk-4872e7ab367e · `src/solar_challenge/dispatch.py::TOUOptimizedStrategy` · medium · ~ weakened · structural · open — 'When is it peak or cheap' is one axis, defined by four independent mechanisms. (1) flow._is_cheap_period clas…
- fk-781d153ab978 · `src/solar_challenge/load.py::generate_load_profile` · medium · ✓ confirmed · structural · open — The two optional extra loads, heat pump and EV, are added to demand by two different mechanisms at two layers.…
- fk-7e76b4cf2cb2 · `src/solar_challenge/fleet.py::simulate_fleet` · medium · ~ weakened · structural · open — How a fleet is executed (parallelism, worker cap, balance validation, which home simulator, progress) is one a…
- fk-4cc34de4e649 · `src/solar_challenge/optimize.py::_build_axis_configs` · medium · ~ weakened · structural · open — 'Vary one named setting of a scenario across runs' is one axis. It has five mechanisms, each with its own stri…
- fk-d63c41ca13f9 · `src/solar_challenge/finance.py::_annualisation_scale` · medium · ~ weakened · structural · open — How a simulated window's length changes a figure is one axis, and each consumer decides it with its own rule a…
- fk-083990041fdc · `src/solar_challenge/community.py::CommunityConfig` · low · ~ weakened · structural · open — Whether a community has a shared battery is one fact encoded twice: the mode string sharing_mode ('p2p' | 'com…
- fk-8529726bbd6b · `src/solar_challenge/flow.py::_build_grid_charge_context` · medium · ✓ confirmed · structural · open — flow.py reaches through the Battery into its config: 11 reads of battery.config.* (capacity_kwh, max_charge_kw…
- fk-4ddab794283a · `src/solar_challenge/finance.py::project_multi_year` · medium · ✓ confirmed · structural · open — project_multi_year computes the capacity-at-events grid-services figure through a closure memo. The memo (_eve…
- fk-bfdae4525795 · `src/solar_challenge/web/jobs.py::JobManager` · medium · ✓ confirmed · structural · open — The run database has no single owner. Every interaction that writes it re-derives the store from ambient Flask…
- fk-9cc706d3afdd · `src/solar_challenge/finance.py` · medium · ~ weakened · structural · open — finance.py (2,376 lines, past the 2,000-line alarm) has a private layer that other modules use as an interface…
- fk-7bdd33abd0ff · `src/solar_challenge/web/app.py::create_app` · low · ✓ confirmed · structural · open — create_app builds JobManager() with the real simulate_home and keeps it only in app.extensions['job_manager']…
- fk-615cbc883512 · `src/solar_challenge/battery.py::BatteryConfig` · low · ✓ confirmed · structural · open — BatteryConfig's annotations name DispatchStrategyConfig and GridChargeConfig, which battery.py imports only un…
- fk-44fdf5fb356b · `src/solar_challenge/weather.py::get_tmy_data` · low · ✓ confirmed · structural · open — get_tmy_data reads its cache from a module global (_weather_cache) that anyone can replace through the public…
- fk-cc292d7ce407 · `src/solar_challenge/cli/utils.py::set_status_quiet` · low · ~ weakened · structural · open — --quiet travels by mutating a module-global Rich Console. cli/main.py's callback calls set_status_quiet(quiet)…
- fk-188af6c13d71 · `src/solar_challenge/config.py::ScenarioConfig` · low · ~ weakened · mechanical · filed:485 — ScenarioConfig holds 'the homes this scenario simulates' as two fields: `home` and `homes`, exactly one set (_…
- fk-2228ae61ef4e · `src/solar_challenge/optimize.py::_pareto_baseline` · low · ~ weakened · mechanical · filed:717 — optimize.py keeps three private one-line shims whose only callers are tests: _split_infeasible, _rank_feasible…

_re-observed_
- fk-59fdc80fdded · `src/solar_challenge/config.py::run_parameter_sweep` · medium · ✓ confirmed · structural · open


## Heuristic-14 measurements

| seat | file | prose share | prose home ok | partition size | stays whole |
|---|---|---|---|---|---|
| simulation-core/config-cli | `src/solar_challenge/config.py` | 0.256 | True | 8 | False |
| finance-economics | `src/solar_challenge/finance.py` | 0.453 | False | 5 | False |

## Candidate streams (for deliberation)

Nothing here is a decision.

### Errors leaf: one exception vocabulary below config

keys: fk-601c5b5f6415, fk-4435376bedb3, fk-da69830bb2d6, fk-291910b552af

remedy: New leaf module solar_challenge/errors.py importing no solar_challenge module; it defines ConfigurationError (base class decided here, see open choice) and config.py, finance.py and gridservices.py import it at top level. The invariant 'a domain invariant failure raises the one error type the CLI and web boundaries cat…

deletable: The 11 function-local ConfigurationError imports (finance.py:119, :1540; gridservices.py:237-266 x8, :345), about 20 lines of cycle-break prose in gridservices.py and finance.py, a…

size S · risk low · mode spawn · seam candidates: ConfigurationError (owner: errors.py; consumers config, finance, gridservices, web readers, cli/utils.handle_errors)

- open choice: Does ConfigurationError subclass ValueError?
  - Subclass ValueError — trade-off: Every web route's except ValueError and cli handle_errors already catch it; the three rewraps and FL… — long term: One refusal type at both boundaries; the next reader an agent adds needs no tuple. Risk: a ValueErro…
  - Keep it a plain Exception and add one boundary translator — trade-off: No semantic widening; the web and CLI each gain one translator that maps ConfigurationError to a ref… — long term: Two translators to keep in step; each new boundary (an API client, a notebook) repeats the mapping.

### Dispatch configuration below config

keys: fk-b3dfd41a4d6a, fk-615cbc883512, fk-370b3e49b67c, fk-c36d6fcbc2a8, fk-94f4881bbe48, fk-04b52ee632c6, fk-fc652220a4d3, fk-8529726bbd6b, fk-99244625d7f2, fk-f126b1c9cbbe

remedy: dispatch.py owns the dispatch-configuration types: a frozen DispatchStrategyConfig and GridChargeConfig, a closed strategy vocabulary (StrEnum or tagged union of strategy configs) with one validator, and the strategy factory moved from home._create_dispatch_strategy. The factory takes the battery's grid_charging and th…

deletable: battery.py's TYPE_CHECKING import of config types; web/storage._field_types' namespace merge of solar_challenge.config and its docstring; web/fleet_config.py's TYPE_CHECKING import…

size L · risk medium · mode spawn · seam candidates: DispatchStrategyConfig / GridChargeConfig (owner: dispatch.py; readers battery, flow, home, config, scenario_writer, web/storage, web/fleet_config), HomeConfig.dispatch_strategy and BatteryConfig fields are on the frozen public surface: version-bump route per the briefing

- open choice: What happens when BatteryConfig.grid_charging is set under a dispatcher that ignores it (briefing key_decisions lines 261-262: SelfConsumptionStrategy deliberately accepts-but-ignores the grid-charge context)?
  - Refuse the combination at construction with a ConfigurationError naming grid_charging and the strategy — trade-off: Reverses the briefing decision and tightens the frozen surface; existing scenarios with the combinat… — long term: The silent 0 kWh f44 measured cannot recur and the four conjunction re-tests collapse into the facto…
  - Keep accept-and-ignore but warn once, naming the keys — trade-off: Honours the briefing; the result still simulates as 0 kWh grid charge but the run says why. — long term: A warning is a weaker gate than a refusal (INV-11); tests must assert the warning for the combinatio…
  - Keep as is and record the decision beside BatteryConfig.grid_charging with a pointer to the briefing — trade-off: No behaviour change; the next agent reads the rule where the field is. — long term: The four re-tests stay; each new strategy must re-learn the conjunction.
- open choice: Does the strategy vocabulary stay a string on HomeConfig or become a tagged union?
  - StrEnum with one validator, 'greedy' mapped to self_consumption — trade-off: Smallest surface change; still two fields (home-level and battery-level) to reconcile. — long term: Precedence between the two fields remains a rule an agent must find.
  - One tagged union of strategy configs on BatteryConfig; HomeConfig.dispatch_strategy retired — trade-off: Frozen-surface bump; scenario_writer and both web forms change together. — long term: One field, one home, one precedence; adding a strategy is one variant plus one factory branch.

### One dispatch engine: shared settle tail and bounded decisions

keys: fk-4df47ebe6a96, fk-491014934d1e, fk-7440003fdd59, fk-2a53ae89932e, fk-f622bbaa9f2e

remedy: flow.py keeps one settle function for both paths (sum, self-consumption cap, split-source flows, EnergyFlowResult) and one grid-charge gate; DispatchDecision.__post_init__ bounds charge_kw + grid_charge_kw against the battery's charge limit and discharge against the shortfall, so Battery.charge's per-call clamp is a se…

deletable: flow.py:412-438 (verbatim copy of 290-316) and the preamble copy 356-376; the identical 15-line grid-charge gate in TOUOptimizedStrategy and PeakShavingStrategy; the two NOTE comme…

size M · risk medium · mode spawn · seam candidates: Energy settlement rule (one function in flow.py read by both simulate_timestep variants and by validate_energy_balance)

- open choice: Do both dispatch paths stay (briefing: 'Two dispatch paths coexist') with a shared settle tail, or does simulate_timestep_tou become a TOU strategy object?
  - Keep both entry points, share the settle tail and the gate — trade-off: Honours the briefing's coexistence decision; two entry points remain on the frozen surface. — long term: Every grid-charge or settlement change is made once, but strategy selection still has two mechanisms…
  - Retire simulate_timestep_tou in favour of a TOU strategy through simulate_timestep — trade-off: Frozen-surface bump; one dispatch mechanism for the axis. — long term: N strategies cost N classes; the inline path cannot drift again.

### Finite quantities: one checker in every domain __post_init__

keys: fk-a9c609ecb8ef, fk-b69968a37b36, fk-7dcdc5559d22, fk-649851e5fc38, fk-60410de6dd0a, fk-e79170280adf, fk-5827f41eb082, fk-239274130a5a, fk-a2b33a420bcf

remedy: web/number_fields.py moves down to the package leaf beside whole_numbers.py unchanged in behaviour (as_finite_float, as_finite_float_within, as_whole_number, as_whole_number_within refuse bool, NaN, inf and fractions naming the field). Every domain __post_init__ that today writes 'x < 0' or 'not 0 < x < inf' calls it w…

deletable: config._parse_seg_rate_scalar's private isfinite rule; fleet_config._build_distribution_dict's rebuild and _spec_number's invented defaults; fleet_scenario._read_fleet_size_and_see…

size L · risk medium · mode spawn · seam candidates: number_fields (owner: package leaf; readers config, web readers, domain configs), Refusal type raised by the checker (depends on the Errors stream's base-class choice)

- open choice: Which error does the shared checker raise from a domain __post_init__?
  - ValueError everywhere, ConfigurationError only from config's readers wrapping with the key path — trade-off: Matches today's 178 ValueError raise sites; config adds the path on the way up. — long term: Two error types stay, joined by the Errors stream's base-class decision.
  - ConfigurationError (from the errors leaf) everywhere — trade-off: One type, but domain modules depend on the errors leaf and the frozen surface's documented exception… — long term: One catch at each boundary; a version bump now.

### Scenario grammar: config.py partition and the parameter-sweep deletion

keys: fk-62821dcde535, fk-2dc9d1cd2c06, fk-59fdc80fdded, fk-caad5305a3be, fk-e2aaf2bfe651, fk-897e13f84164

remedy: Partition config.py along the config-cli seat's measured layering: errors leaf (from the Errors stream) and the moved number_fields <- scenario_blocks.py (block readers, _refuse_unrecognised_keys, _BlockType, every reader raising with its block_path) <- fleet_distribution.py (distribution types, sampler, generate_homes…

deletable: 266 lines of parameter-sweep runner and its test file; config.py's imports of home and fleet; the cli/config.py templates' dead output:/period: keys; every reader-local error messa…

size L · risk low · mode agent · seam candidates: scenario_blocks.py as the home of battery.py's TYPE_CHECKING types until the Dispatch stream moves them (order the two streams: Dispatch first)


### Fleet-document scenario overlays: one reader for the blocks that reach the homes

keys: fk-3be3240278ee, fk-2264bc150fa3, fk-416eb5643e7a, fk-e756dab8077e, fk-f99038047a27, fk-a391cf1f4edf, fk-ad65ad5e4e48, fk-81d0840d19e2, fk-8047de9b6789, fk-188af6c13d71, fk-0b791f2be2d6

remedy: config gains one function that parses a fleet document's scenario-level blocks (location, tariff, seg, finance, flex_band, period, name) into a typed scenario with the same unknown-key refusal as _parse_scenario, applying them to the generated homes under one stated policy. ScenarioConfig becomes a deep value: homes()…

deletable: cli/utils.load_config_with_overrides' hand-written home/pv/load/location blocks and the whole-block battery replace; the two hand-built ScenarioConfigs in cli/finance.py:228 and cl…

size L · risk medium · mode spawn · seam candidates: Fleet-document overlay reader (owner: config; consumers cli/finance, cli/optimize, cli/home, cli/fleet, web/fleet_scenario, web/builder_form), ScenarioConfig.homes()/with_seg() (owner: config; consumers finance, optimize, cli/validate)

- open choice: Which SEG-to-home policy is the one policy?
  - Fill-and-refuse (finance's: fill homes lacking a seg_tariff, refuse a contradicting one) — trade-off: Catches a scenario that disagrees with its homes; the CLI and optimize overwrite paths become refusa… — long term: One policy with a loud failure; contract decision for finance-economics recorded once.
  - Overwrite (cli/finance's and optimize's) — trade-off: Never refuses; the scenario-level rate silently wins over a per-home one. — long term: A per-home SEG an agent sets is ignored without a signal (INV-11).
- open choice: Does `finance run` honour the file's period block (as optimize does) or keep the --start/--end-only policy?
  - Flag > file period > default, for every command — trade-off: finance run's windows change for files with a period block. — long term: One period policy for one file across commands.
  - Flags only, everywhere; the file's period block is refused for fleet documents — trade-off: optimize's current behaviour changes; the grammar shrinks. — long term: A scenario file cannot carry its own window; the board's reproducibility depends on the command line…

### Component defaults: one home per component, distributions derive from it

keys: fk-148991ab9439, fk-d2b4045c6676, fk-dfeefbe95640, fk-0e58e2a7e007, fk-f2e1ad46df4b, fk-2b16cc8bcf46, fk-d6f16d95b126

remedy: Each component's defaults live on its domain config (PVConfig, BatteryConfig, LoadConfig, HeatPumpConfig, EVConfig) and the distribution layer builds homes with dataclasses.replace over a default instance, so no field list is restated; heat-pump types become one per-type record (COP intercept, slope, min, max) that the…

deletable: The restated PV defaults in PVDistributionConfig, _parse_pv_distribution_config and generate_homes_from_distribution's None fallbacks; the 8.0/8000.0 heat-pump defaults in three pl…

size M · risk low · mode agent · seam candidates: Component block key tables shared by config's parsers and scenario_writer (one owner, read by both)


### Finance partition: a scenario-economics stratum above bill arithmetic

keys: fk-5fdb04305288, fk-41283f42a36a, fk-6cd8a932665c, fk-b0f648b0e6d0, fk-9cc706d3afdd, fk-c2c9277c1920, fk-c0e0ae3dcca8, fk-4a9af7c31a4f, fk-3b0a239d0489, fk-52fa98174363, fk-caeaf35c8151, fk-50cf1dd5df58, fk-9fa18977ec68, fk-3f4daea21220, fk-62dbe0f34b68, fk-808be5588896, fk-5b34adae950b

remedy: Step one is p84's prose rehoming (CR/W/Greek codenames, 'Suggestion 3/4' headings, stale cli pointers, the non-linear 'exactly affine' claim) with a re-measure after it. Then, resting on f39's heuristic-13 symptoms (7 cycle-free function-local import statements, optimize's private _resolve_homes import, p75's partition…

deletable: 7 function-local import statements in finance.py (1422, 1517, 1561-1563, 2276, 2350-2351) after the Errors stream removes lines 119 and 1540 and the Grid-services stream removes li…

size L · risk medium · mode spawn · seam candidates: Billing-energy records (owner: finance.py; readers projection module, tests), solar_challenge.__init__._SYMBOL_MODULE maps solve_cost_recovery_rate to 'finance' (frozen surface): re-export from finance or version bump

- open choice: How does the frozen surface keep solve_cost_recovery_rate importable from solar_challenge?
  - finance.py re-exports it from the new module — trade-off: No surface change; one upward import in finance.py, which heuristic 13 counts as stitching. — long term: A permanent re-export shim the next reviewer flags.
  - _SYMBOL_MODULE points at the new module under a surface version bump — trade-off: Contract change for platform consumers; FROZEN_SURFACE and release note move together. — long term: Clean layering; one bump.

### Grid-services figure as an explicit input and a closed model selector

keys: fk-4ddab794283a, fk-758b2f309cab, fk-aafe32daa988, fk-d432a549b03f, fk-0f24b7f66eb2, fk-71b4ca35efe0

remedy: FinanceConfig.grid_services_model becomes a closed type (none | flat band | capacity_at_events(config)) validated once at construction, so the four selector checks and the admitted 'capacity_at_events with events None' go. project_multi_year takes the age-0 fleet results (or a precomputed GridServicesAtEvents) as an in…

deletable: _event_gs_memo and finance.py:1606; the string branch and assert in _simulate_age; cli/finance's silent None and cli/optimize's flat-field override; _SENSITIVITY_ALIAS_MAP's (1.5,…

size M · risk medium · mode spawn · seam candidates: Grid-services rate bands (owner: gridservices.py; readers flex, finance, cli/optimize), FinanceConfig.grid_services_model is on the frozen surface

- open choice: Does the per-event income vary with battery SOH per age (fixing the age-0 memo defect p81) in the same change?
  - Yes: compute per age from each age's aged homes — trade-off: Board figures change (lower later-year income); more simulations per projection. — long term: The model says what it means; the compute-once tests become per-age tests.
  - No: age-0 figure as an explicit input, documented as the modelling choice — trade-off: Figures unchanged; the simplification is stated where the input is taken. — long term: The next SOH change must revisit this input; recorded in docs, not a closure.

### Window length and cadence as typed values in timebase

keys: fk-1cd332300623, fk-d63c41ca13f9, fk-286fe17c28c9, fk-756c0ef9e9d9, fk-7ef1099d24e8

remedy: timebase.py owns SimulationWindow: covered days derived from the tz-aware minute index (not timedelta.days), the one-minute cadence, one kW-to-kWh integration helper that reads it, and annualisation_scale() with the one threshold. SummaryStatistics.simulation_days derives from it; bill_distribution and householder_bill…

deletable: 13 inline '.sum() * HOURS_PER_MINUTE' integrations; four '.days + 1' recomputations (validation.py:87, 299; charts.py:370, 526); validation's own 365/duration rule and _check_annua…

size M · risk medium · mode spawn · seam candidates: SimulationWindow (owner: timebase.py; readers home, finance, validation, output, charts, cli)

- open choice: One annualisation rule for every consumer, or keep validation's always-scale?
  - finance's rule (x365/d below 360 days, else x1) everywhere — trade-off: validation's consumption check on a 400-day run stops scaling down; the board report and validation… — long term: One rule, one threshold; a leap-year or multi-year run is one edit.
  - Each consumer keeps its rule but takes the day count from SimulationWindow — trade-off: Figures unchanged; only the day-count source is unified. — long term: Two rules an agent must still find; f49's divergence persists.
- open choice: Is the one-minute cadence an invariant or a parameter?
  - Invariant: declare it in timebase, drop the 10 timestep parameters that only pretend to vary it — trade-off: Simpler engine; half-hourly smart-meter input needs resampling at the boundary. — long term: No per-site cadence bugs; coarser sweeps are impossible without resampling.
  - Parameter owned by the run (index-derived), threaded to every integration site — trade-off: Every generator and consumer must read it; larger change. — long term: Variable cadence works end to end; each new site must read the window.

### Tariff: coverage invariant, one cheap-period classifier, named preset defaults

keys: fk-872021ade9b6, fk-2f88003e22c8, fk-97213a0e9ab2, fk-bd03fe349ffd, fk-463e82417506, fk-4872e7ab367e

remedy: TariffConfig.__post_init__ checks that sorted periods tile the 24-hour day exactly once, raising with the gap or overlap times named, and TariffPeriod requires a finite rate; TariffConfig exposes the cheap-period classifier (flow._is_cheap_period moves onto it, with mean_period_rate duration-weighted or replaced) and n…

deletable: flow._is_cheap_period's private authority and its mean_period_rate comparison; ev.py's two copies of the 00:30-07:30 window and the 10:00-16:00 literal; the 0.35/0.13 pairs in home…

size M · risk medium · mode spawn · seam candidates: Cheap-period classifier (owner: tariff.py; readers flow, dispatch, ev), Tariff preset defaults (owner: tariff.py; readers config.parse_tariff_config, web routes/forms, fleet_scenario._FORM_TARIFF_SETTINGS)

- open choice: Does TOUOptimizedStrategy classify from the tariff, with peak_hours an override refused when it contradicts the tariff, or does peak_hours stay an independent schedule?
  - Tariff is the authority; peak_hours only as a checked override — trade-off: tou_optimized homes whose YAML peak_hours disagree with their tariff (Economy 7: 840 minutes) start… — long term: One definition of peak; seasonal or Agile-style tariffs the briefing anticipates need one edit.
  - peak_hours stays an independent schedule, documented as a behavioural (not price) window — trade-off: No scenario changes; the two clocks remain and the EV windows still need their own input. — long term: Every tariff change edits YAML peak_hours and EV windows too (f45's cost).

### Load composition: additional loads one mechanism, calendar-aligned days

keys: fk-781d153ab978, fk-1d920c89e872, fk-740e9a804a4f, fk-7fa120a8bb98, fk-89777ec9faad, fk-72af0b90338d, fk-1609d8c3d091

remedy: home.simulate_home composes a sequence of named load contributions (household, heat pump, EV) from each configured component and SimulationResults carries a mapping of named load series; summary, output, charts and templates iterate it instead of branching per kind. load, ev and heat_pump generators produce series alig…

deletable: load.py:447's function-local ev import and base_load.add(fill_value=0.0); 18 heat-pump presence branches across 7 files and the three Optional summary fields; ev.py's five 1440 lit…

size L · risk medium · mode spawn · seam candidates: Named load series on SimulationResults (owner: home.py; readers output, charts, templates, scenario_writer, web/storage), Day iterator over the tz-aware index (owner: timebase.py, shared with the Window stream)

- open choice: Do the heat-pump summary fields stay as named Optional fields (frozen surface) or become entries of the named-load mapping?
  - Keep the three Optional fields, add the mapping beside them — trade-off: No surface change; two representations of one fact for a release. — long term: A SPOT violation until the next bump retires the fields.
  - Replace them with the mapping under a surface bump — trade-off: Stored web runs saved with the old summary need the stored-run version from the Run store stream. — long term: One mechanism for the next load kind.

### RNG hand-off: the seed travels with the call

keys: fk-16df1a7ac416, fk-e0e34ef46058, fk-c78416de5500

remedy: load.py owns the global-RNG hand-off: a module-private lock and a context that saves np.random and random state, seeds both from LoadConfig.seed (fresh SeedSequence entropy when None), runs the richardsonpy window and restores the state, so profiles are identical serially and concurrently (briefing line 252). FleetConf…

deletable: The shared LoadConfig in create_uniform and the unseeded LoadConfigs in create_heterogeneous; tests/unit/test_load.py:547's monkeypatch of _simulate_stochastic_day; the order depen…

size S · risk low · mode agent · seam candidates: Global RNG state (owner: load.py's hand-off context; the briefing mandates seeding both numpy and random)


### PV model: one home for module choice, run policy and ageing

keys: fk-48447960eb2c, fk-616cc076b7cb, fk-0edf0069c6bb, fk-8b8f9d686b86, fk-a98db49f3fd7, fk-f5cd69400ce6, fk-998f0cb69410, fk-835a87838a52

remedy: pv.py names the default CEC module row as a constant and requires it the way _require_cec_library_row requires inverter rows, deleting the substring search and both fallbacks; exposes one public run-the-chain function that applies the scipy warning policy and ageing (degradation on DC before the inverter, or documented…

deletable: _get_cec_module's two fallbacks and the wrong CS6K-400MS comment; three verbatim copies of the _chandrupatla filter (pv.py, two scripts) and the broader test filter; the gamma_pdc…

size M · risk medium · mode spawn · seam candidates: Default PV module identity (owner: pv.py constant; restated in 6 docs/tests sites that should point at it), PVConfig fields on the frozen surface

- open choice: Do module_efficiency and temperature_coefficient become live model inputs or leave PVConfig?
  - Live: derive module parameters from them when set, STC-consistent — trade-off: Yields change for scenarios that set them; the CEC row becomes a template. — long term: Fields say what they do; one more axis in the model to test.
  - Remove them under a surface bump — trade-off: Scenario files and the web form that set them must drop the keys. — long term: No lying names (heuristic 1); smaller surface.

### Weather as an explicit input

keys: fk-44fdf5fb356b, fk-06035cd76226, fk-e4549a3a6b54

remedy: simulate_home takes weather_data (or a weather provider) as a required input; cli/home, the web JobManager and any sweep runner prefetch per location as fleet.simulate_fleet_iter already does; WeatherCache.get reads what put writes (tz sidecar, metadata) with one os.replace; the module-global cache and set_weather_cach…

deletable: weather._weather_cache and get/set_weather_cache (after the surface bump); simulate_home's weather_data-is-None fallback; fleet._tmy_by_location's compensation; the three conftest…

size M · risk medium · mode spawn · seam candidates: Weather cache value (owner: composition roots cli/web/tests; readers simulate_home via argument), set_weather_cache is on the frozen public surface

- open choice: Required weather_data argument, or a provider object with a get(location) method?
  - Required DataFrame argument — trade-off: Simplest; every caller must prefetch and hold the frame. — long term: Callers duplicate the prefetch loop unless the Fleet execution stream's runner owns it.
  - Provider object (cache-backed) passed down — trade-off: One prefetch policy in the provider; processes need a picklable provider. — long term: A second parallel path cannot miss the cache (task-460 class defect).

### Fleet execution policy as one value

keys: fk-7e76b4cf2cb2, fk-f3a20a6d53e0, fk-31fd9d5d4c68, fk-d89ee8df893c, fk-cc292d7ce407, fk-e58042aef503, fk-f7b19fc4c8b5, fk-7bdd33abd0ff, fk-f6c905f91d32, fk-7aaa879bf0ac

remedy: One frozen FleetRunner (parallel, max_workers, validate_balance, progress sink, home simulator) with simulate(FleetConfig, start, end), built once at each boundary: the CLI (CliFleetSimulator wraps it and gains a per-home progress callback so fleet run and fleet sweep use it), the web (create_app takes the JobManager o…

deletable: cli/fleet.py run's 16-line copy of simulate_fleet's assembly; the simulate kwarg threaded through 6 finance/optimize functions; the (validate_balance, parallel, max_workers) tuple…

size L · risk medium · mode spawn · seam candidates: FleetRunner (owner: fleet.py; built by cli/utils, web/app, tests/_cli_fleet_simulator), cli/utils module docstring's rule 'every fleet command reads its simulator from ctx' becomes true or is narrowed

- open choice: Does the runner own weather prefetch (joining the Weather stream) or receive weather per call?
  - Runner owns prefetch per location — trade-off: One prefetch policy; the runner depends on weather. — long term: A new parallel path cannot miss the cache.
  - Weather passed per call — trade-off: Runner stays weather-agnostic; each boundary prefetches. — long term: Three prefetch loops to keep in step.

### Web request boundary: one refusal, one presence rule, one location grammar

keys: fk-6c98ee030531, fk-1d143fefefed, fk-29af8a4fe018, fk-66f886576b3f, fk-bd7f2abebeba, fk-0593b530a371, fk-acdc650baeb8, fk-da0e3a4df6e7, fk-a0866b1bd680, fk-ba29e186122f, fk-70edc755ede4

remedy: A request-reading module below the Flask services (shared.py split: readers and NotAJsonObject here, get_storage/get_job_manager beside app/jobs) applies one presence rule (null and '' are absent, defaults separated from nullability) to every body before reading, and one boundary translator maps the one refusal type (f…

deletable: FLEET_FORM_REFUSALS and the three ConfigurationError rewraps; six distinct except-tuples collapse to one; resolve_location's silent Bristol fallback and LOCATION_PRESETS in shared.…

size M · risk medium · mode spawn · seam candidates: Location grammar and presets (owner: location.py; readers cli/utils, web readers, templates), Refusal type (owner: errors.py), Presence rule (owner: the request-reading module; readers simulation_params, fleet_scenario, builder_form)

- open choice: Does the web keep its silent Bristol fallback for an unknown location?
  - Refuse an unknown preset or bad coordinates with a 400 naming the value — trade-off: The assistant's free-text location tool and any bookmarked bad value start failing visibly. — long term: A mistyped preset can no longer pass every test; one grammar with the CLI.
  - Keep the fallback but return the resolved location in the response — trade-off: No breaking change; the user sees Bristol was used. — long term: INV-11 fail-soft remains, now visible.

### Dashboard limits and distribution editing from one table

keys: fk-1df9dbc0d971, fk-f8b7b3ab709d, fk-366773b4083f, fk-a6d9f3e5a7e2, fk-8107696f0b02, fk-7893b49b92c3, fk-88374e6e3553, fk-40dff1473b94, fk-d303b6dbf669, fk-9dd1d9389dd2, fk-006c3339e3b2, fk-021a21b35427, fk-3cd0d3f3b512, fk-c3625a25eed4

remedy: fleet_components.page_limits() returns a frozen PageLimits (MAX_FLEET_HOMES moves in beside each FleetComponent's fixed_range/step/default, seed and days bounds) that routes render into fleet.html, builder.html and the scripts, so no limit is a template or JS literal; the distribution editor's per-type behaviour (field…

deletable: fleet-simulator.js's 1000/15.0/6000 literals and fleet.html's max=500, builder.html's 10000; _build_distribution_dict and its lossy rebuild, _draw_samples' per-type chain and _spec…

size L · risk medium · mode spawn · seam candidates: PageLimits (owner: fleet_components.py; readers routes, templates, static/js, builder_form, simulation_params), Per-type distribution table (owner: config's grammar / fleet_distribution module; readers web editor and preview)

- open choice: Does the editor's per-type table live in config's grammar module or in web/fleet_components?
  - config (fleet_distribution.py after the partition) owns it; the web imports it — trade-off: The grammar and the editor cannot drift; the web depends on config's module layout. — long term: Adding a distribution type is one record; the web renders it.
  - fleet_components owns a web-facing table checked against config's by a test — trade-off: Web stays decoupled; two tables with a guard. — long term: A guard test to keep green instead of one home.

### Run store with one owner: connection, schema version, stored-run format, run type

keys: fk-bfdae4525795, fk-df9d0fc1b2d3, fk-9d7f66fdcfdd, fk-34a6679f1ef3, fk-a37ed16d59c5, fk-273b8b09c91a, fk-1070454e4c6e, fk-cca5fd81afda, fk-c14c02dc1b77, fk-e29393df0cd4, fk-2ff305a1dbb2, fk-8f4f4d63f917, fk-2ac79d7a1989, fk-81e62b2640a7

remedy: RunStorage is the one owner of the runs table and the stored-run format: database.connect(db_path) applies the connection policy (WAL, row_factory, foreign_keys) for init_db, get_db and the job connection; init_db writes PRAGMA user_version and applies ordered migrations or refuses naming both versions and the file, wi…

deletable: 17 current_app.config reads of DATABASE/DATA_DIR and 3 of 4 RunStorage constructions; raw runs SQL in jobs.py, api.history_list_runs, assistant.list_recent_runs and routes._get_agg…

size L · risk high · mode spawn · seam candidates: Connection policy (owner: database.connect), Stored-run format version and runs schema version (owner: storage/database; readers every loader), Run type -> behaviour table (owner: storage.RunRecord; readers api, routes, templates, assistant)

- open choice: Migrations in place, or refuse to start on a version mismatch with a documented one-shot migration command?
  - Ordered in-place migrations on startup — trade-off: User databases upgrade silently; each schema change ships a migration. — long term: Every column add is a migration an agent must write and test against a frozen fixture database.
  - Refuse on mismatch; `solar-challenge web migrate` applies them explicitly — trade-off: Visible step for the user; no silent change to their data. — long term: Same migration code, run on request; start-up stays simple.
- open choice: One /results/<run_id> route choosing the page from record.type, or keep /results/home and /results/fleet with results_url(record) helpers?
  - One route — trade-off: Bookmarked URLs change (redirects needed). — long term: A new run kind adds a loader and a template, no new route or JS branch.
  - Keep both routes, derive every link from results_url(record) — trade-off: No URL change; two routes remain. — long term: A new run kind adds a route; links cannot be wrong.

### Job events and SSE framing

keys: fk-7eb56fda0b1c, fk-4540d657bff6, fk-484952247bb6, fk-0097b5aaa45c, fk-066e5cb461f7

remedy: jobs.py holds one job state table (JobStatus transitions) and _finish_job/_report_state refuse a transition the table does not allow, stamping finished_at only on terminal states; each event type has one typed payload and one web module frames SSE (sse_frame(event, payload), event_stream(frames)) used by both assistant…

deletable: 10 hand-written frame sites and the two header copies; api.get_job_progress's compensating terminal branch; progress-tracker.js's `data.message || data.error`; the three error payl…

size M · risk medium · mode spawn · seam candidates: SSE frame and event payload types (owner: one web module; readers assistant.js, progress-tracker.js, parameter-sweep.js)

- open choice: Does the server rename its 'error' event to avoid EventSource's native error event?
  - Rename to 'failed' with id/retry fields — trade-off: Both browser consumers change in the same release. — long term: Reconnects resume; no collision.
  - Keep 'error', unify its payload — trade-off: Smallest change; the collision stays documented. — long term: Each new consumer must learn the two meanings of 'error'.

### Results chart panels, theme tokens and chart facts

keys: fk-42c0053b9a2b, fk-93ee9a05751a, fk-8e109704aa24, fk-3239afd8ce6b, fk-8f26d000b68d, fk-ff5b90768f66, fk-2e7ddcee2379, fk-657669b23e71, fk-ce345e3b013d, fk-55f4e4ea396d, fk-02500b87f3cb

remedy: charts.py returns a ChartPanel value (figure JSON or a named absence reason) rendered through the existing chart_container macro (macros.html:78, already live on compare.html:118 and :129; p122's measurement corrected to 'unused on results/home.html and results/fleet.html'), extended to take the panel; chart inputs are…

deletable: 12 "!= '{}'" guards and the '{}'/None returns; the two direct Plotly.newPlot calls; 32 copies of the card class triple via the card macro; the Chart.js dead path in parameter-sweep…

size M · risk low · mode spawn · seam candidates: Theme tokens (owner: one table; readers tailwind.config.js, chart-renderer.js, charts.py _AMBER), ChartPanel rendered by chart_container (owner: macros.html)

- open choice: Where does the theme token table live so both Tailwind's build and Python's charts read it?
  - A JSON file under static/src read by tailwind.config.js and loaded by charts.py — trade-off: One file, two languages reading it; the css-build lane job checks the Tailwind side. — long term: A colour change is one edit and one rebuild.
  - Python constants emitted into a generated tokens.js at build — trade-off: A build step the npm script runs; Python is the source. — long term: Generated file to commit beside style.css, same discipline as the stylesheet.

### Assistant facts from the engine

keys: fk-194e5b40da23, fk-93d3bd7aa219, fk-ab16fff6f6c3

remedy: assistant.py derives its TDCV figures, benchmark bands and yield figure from load.OFGEM_TDCV_BY_OCCUPANTS and validation's band constants (one import, not three copies); TOOLS carries each tool's handler so dispatch_tool is a lookup; chat() is split into the stream loop, the tool round-trip and the persistence step, wi…

deletable: The three TDCV versions and the literal bands in the system prompt and metric tables; the six-name string if-chain in dispatch_tool; two of three save_chat_message sites.

size S · risk low · mode agent · seam candidates: Benchmark constants (owner: load.py and validation.py; reader assistant.py)


### Surface lock

keys: fk-293a1282ace4, fk-9df95e9e2b45, fk-879e8c13f581, fk-ca5301a6f39f, fk-d2881616c782, fk-dc5370224a78, fk-b0607cc5a685, fk-ac70915ba435

remedy: One surface-contract test module organised by behaviour (laziness, pvlib-free import, frozen forms, drift message) replaces test_init_lazy_surface.py and test_public_api_surface.py; the exported-name count derives from FROZEN_SURFACE rather than a literal; __init__'s three tables derive from one name-to-module mapping…

deletable: Three duplicated test bodies and the two literal 69 asserts plus four prose mentions; the T3/T4/H-number ownership prose; _external_probe.py's stale line pointer; the two type-igno…

size M · risk low · mode agent · seam candidates: FROZEN_SURFACE as the one home of the surface (owner: tests/_surface_forms.py; readers the merged test module, release notes)


### Lane harness: one typed collection source, one lane-only mechanism, gates over tests/

keys: fk-1abd62632ae1, fk-dd434cb2d4b9, fk-eec3806e584e, fk-f48c29a98a89, fk-a0b751097301, fk-e5820c5e22ed, fk-5de02e56b3af, fk-3667e4e32155, fk-a9aad5f6d1b2

remedy: tests/_collect_only.py obtains node ids and interpreter names from pytest's --junitxml report (the seam test_per_task_verify.py:84 already uses) instead of parsing '::' stdout; tests/e2e/conftest.py's existing pytest_collection_modifyitems hook adds pytest.mark.e2e to every test under its directory so conftest's offlin…

deletable: collected_node_ids' '::' filter and _interpreters_named_by's rpartition; test_marker_registration's regex over collect output and its INTEGRATION_FILES/NETWORKED_UNIT_CLASSES/PURE_…

size M · risk low · mode spawn · seam candidates: Lane-only suite list (owner: tests/conftest.py collect_ignore; readers lane rows, interpreter_matrix, newest_releases), Collection report (owner: tests/_collect_only via JUnit XML)

- open choice: How are the declared dependency floors checked (p152)?
  - An oldest-floor lane job that resolves at the floors and runs the verify — trade-off: A 15-20 minute post-merge job like newest-releases; floors become tested facts. — long term: A floor claim cannot drift silently; lane cost grows.
  - Raise each floor to the locked version and delete the capability-claim tests — trade-off: Consumers lose range; no new job. — long term: The floor is the lock; re-raised on every re-lock.

### Board reports: one typed row source and one assumption mode per report

keys: fk-2106d1fbaed0, fk-b7241e0ce122, fk-89afcb2b57f7, fk-f66948b9528c, fk-b523bff3e51c, fk-ae20e1833a19, fk-41767a1bc146, fk-ef13881623be

remedy: cli/finance.run resolves each --assumptions mode to its own FinanceConfig once and drives bill, projection, solve and events per mode from that value; generate_finance_report takes labelled sections keyed by mode instead of a positional bill_physics; events income renders with the economics it changes. Summary tables a…

deletable: create_summary_table's 8 hasattr/getattr probes and Any parameter; the 'Physics Assumptions' heading on spreadsheet figures; the if/elif binding chain and inline IRR/DSCR/payback f…

size M · risk medium · mode spawn · seam candidates: Report sections keyed by assumption mode (owner: output.generate_finance_report; reader cli/finance), Typed summary rows (owner: home.SummaryStatistics / fleet.FleetSummary; reader cli/utils)

- open choice: Under `--assumptions both`, does the board report show the solve and economics under both modes or physics only, labelled?
  - Both modes for every computation — trade-off: Report doubles in length; four more fleet-free computations per run. — long term: The spreadsheet comparison is complete; no mixed-mode section.
  - Physics only for solve/economics, labelled as such; bills under both — trade-off: Today's shape with honest labels. — long term: A fourth mode still needs a label rule; mixed-mode report remains.

### Sweep knob registry

keys: fk-4cc34de4e649, fk-ac39320dcf1d, fk-bea05911eb70, fk-32d5e6707fb5, fk-3ca00f8edeb8, fk-0b4f5e04067c

remedy: One registry below the entry points maps a typed knob identifier to a pure ScenarioConfig -> ScenarioConfig transform, with value generation always through SweepSpec (one default mode); the YAML sweep's placement is data the registry knows, so a sweep multiplier on an unsupported field is refused at parse time naming t…

deletable: detect_sweep_spec/_replace_sweep_with_value's battery.capacity_kwh special case and the sampler's late refusal as a user message; _SWEEP_PARAMETER_HOME_KEYS; cli/optimize's alias m…

size L · risk medium · mode spawn · seam candidates: Knob registry (owner: the fleet_distribution/config stratum; readers web/api, cli/fleet, cli/optimize, optimize)

- open choice: Does the registry operate on ScenarioConfig only, or also on a single HomeConfig?
  - ScenarioConfig only, with homes() from the overlay stream — trade-off: Single-home web sweeps wrap the home in a scenario. — long term: One transform signature; every knob is scenario-shaped.
  - Two signatures (home and scenario) per knob — trade-off: Direct for the web's home sweep; two implementations per knob. — long term: Twice the registry to keep in step.

### Community: dispatch from the factory, mode derived from the battery

keys: fk-664e2030921e, fk-083990041fdc, fk-dc5cf2ec9b84, fk-8995288451e6

remedy: CommunityConfig takes a dispatch strategy config and the community battery runs through the dispatch factory from the Dispatch stream with the tariff; sharing_mode becomes a property derived from community_battery (or each mode a frozen variant carrying its own fields); CommunityResults and FleetResults/FleetConfig are…

deletable: The hard-coded SelfConsumptionStrategy() and tariff-less simulate_timestep call; the three consistency ifs in CommunityConfig.__post_init__; community.py:366-368's post-constructio…

size S · risk low · mode agent · seam candidates: Dispatch factory (owner: dispatch.py, from the Dispatch stream; this stream follows it)


### Battery facts: one representation each for efficiency and throughput

keys: fk-35b8ddcf5565, fk-50a3985fae0f

remedy: BatteryConfig holds two efficiency facts in two fields; round-trip efficiency is a classmethod constructor (or __post_init__ refuses a set efficiency that contradicts per-direction values, naming both) and _parse_battery_config refuses a block setting both forms; compute_soh's throughput definition (discharged energy v…

deletable: The retained efficiency field and its 12-line override docstring with the replace() caveat; the efc = throughput / (2 * usable) ambiguity and finance.py's contradicting docstring.

size S · risk medium · mode spawn · seam candidates: BatteryConfig fields on the frozen surface (version-bump route)

- open choice: Refuse contradicting efficiency inputs, or retire the efficiency field for a constructor?
  - Keep three fields, refuse contradictions in __post_init__ — trade-off: No surface change; dataclasses.replace of a per-direction value still silently loses under a retaine… — long term: optimize/web replace patterns remain a trap.
  - Two fields plus BatteryConfig.with_round_trip(efficiency) under a surface bump — trade-off: Scenario key 'efficiency' maps to the constructor in the parser; surface bump. — long term: Each fact has one representation; replace works.


## Invariant candidates

- **Every numeric field of a frozen domain config is finite and not a bool, and a violation names the field and value.** (h10 clear invariants uniformly enforced; maps to INV-2 structured-facts-at-failure and INV-11 no-silent-fail-soft rather than a new INV) — checkable form: For every dataclass in solar_challenge whose fields include float or int, constructing with NaN, inf, -inf and True in each numeric field raises, and the message contains the field name and the repr of the value; no cons… — fixture: Parametrize over (dataclass, field) pairs discovered by walking dataclasses.fields of PVConfig, BatteryConfig, LoadConfig, HeatPumpConfig, EVConfig, Location, S…
- **A TariffConfig's periods tile the 24-hour day exactly once.** (h10 redundantly enforced (today only at use via get_rate); INV-11) — checkable form: TariffConfig((TariffPeriod('07:00','23:00',0.3),)) raises naming the gap 23:00-07:00; TariffConfig with 00:00-12:00 and 06:00-00:00 raises naming the overlap 06:00-12:00; every preset constructs; get_rate over 1440 minut… — fixture: The two probed tariffs from f14 plus the three presets; a 1-minute sweep over 2024-01-10 Europe/London.
- **A stochastic load profile depends only on its LoadConfig, not on process order or concurrency.** (h7 stateless interactions; the briefing's convention at lines 82-83 and 252 (no existing INV encodes it; propose as a project invariant enforced by this test)) — checkable form: generate_load_profile(LoadConfig(seed=s)) run serially equals the same call run on two threads concurrently for s in {42, 43}; an unseeded profile generated after a seeded one differs from a second fresh unseeded profile… — fixture: f51's probe harness: 2024-06-01..07 window, ThreadPoolExecutor(2), five trials, Series.equals; plus a fleet of three homes asserting seeds.
- **The runs table and stored-run files are written and read only through RunStorage.** (h7 and INV-9 one-fact-one-home) — checkable form: grep over src/solar_challenge/web for 'sqlite3.connect', 'FROM runs', 'INSERT INTO runs', 'UPDATE runs' and 'RunStorage(' finds matches only in storage.py and database.py (connect) and app.py (one construction). — fixture: A test that walks the web package's .py files with a regex and asserts the allowed set of files; runs under the per-task verify.
- **No solar_challenge module imports another solar_challenge module inside a function.** (h13 files make internal sense in isolation; INV-5 no-lockstep-duplication of the cycle-break idiom) — checkable form: An AST scan of src/solar_challenge finds zero Import/ImportFrom nodes nested in a FunctionDef whose module starts with solar_challenge, except an allow-list that is empty after the Errors, Finance, Grid-services and Load… — fixture: Reuse the import_graph.json producer's deferred-edge logic as a test; the allow-list is a frozenset in the test that shrinks per stream.
- **A stored run names the format version that wrote it, and a loader refuses a run it cannot rebuild, naming the run id and the field.** (h10 informatively enforced; INV-13 readers-prove-their-producer) — checkable form: Loading a fixture run directory saved without a version, or with a summary.json missing total_generation_kwh, raises StoredRunUnreadable whose message contains the run id and the field name; loading a current-format fixt… — fixture: A frozen pre-task-469 run directory committed under tests/fixtures/stored_runs/ plus a current one generated by save_home_run in the test.
- **The database schema version matches the code and the runs DDL matches RunRecord.** (h10 and INV-1 contracts-machine-checked) — checkable form: After init_db on a fresh file, PRAGMA user_version equals database.SCHEMA_VERSION and the column names of PRAGMA table_info(runs) equal [f.name for f in fields(RunRecord)]; init_db on a file whose user_version is lower e… — fixture: A temp database created with the pre-548 DDL (f19's probe) and one created fresh.
- **The day count a bill is computed over is the summaries' own.** (h11 SPOT; INV-9) — checkable form: bill_distribution(summaries, finance, days) raises naming both values when days != summaries[0].simulation_days; cli finance run over 2024-03-31..04-01 bills over 2 days (the index's count), not 1. — fixture: f32's probe summaries with simulation_days 2 and a call with days 1; a CliRunner invocation over the DST-crossing window with a fake simulator.
- **A grid-charge target is a fraction of the battery's effective capacity.** (h7 (flow reads the Battery's answer, not its config); h1 for GridChargeConfig's documented basis) — checkable form: After 180 one-minute cheap-period steps of simulate_timestep_tou on Battery(BatteryConfig(10 kWh, soh=0.7, grid_charging=GridChargeConfig(0.5))) with Economy 7, the end SOC fraction of effective capacity equals 0.5 withi… — fixture: f52's probe verbatim, parametrized over soh in {1.0, 0.7}.
- **A BatteryConfig.grid_charging set under a dispatcher that cannot honour it is refused (or warned) by name. CONDITIONAL on the Dispatch stream's first open choice; if the briefing's accept-and-ignore is kept, the invarian…** (h3 one owner for the axis; INV-11 no-silent-fail-soft) — checkable form: For each of the three ignored combinations f44 measured (default greedy, battery self_consumption, home tou_optimized without tariff), constructing or simulating raises ConfigurationError naming 'grid_charging' and the s… — fixture: probes/grid_charge.py from the cross-dimensions seat: PV 4 kW, deterministic 3400 kWh load, 5 kWh battery with GridChargeConfig(0.9), 2024-06-15 synthetic June…
- **Dashboard form defaults for tariff rates and the simulation window are the engine's.** (h11 SPOT; INV-9) — checkable form: Rendering simulate/home.html and simulate/fleet.html and parsing their x-data yields economy_7 and economy_10 peak/off-peak rates equal to TariffConfig's preset table, and start/end defaults equal to the library's defaul… — fixture: Flask test client GET of both pages, a small regex over the x-data block, compared with tariff.PRESET_DEFAULTS and timebase/config window constants; a grep test…

## Contradictions

- between fk-fc652220a4d3, fk-664e2030921e: f44 measures a configured grid_charging silently ignored under self-consumption dispatch as a defect and proposes refusing the combination; review/briefing.yaml key_decisions (lines 261-262) record SelfConsumptionStrategy's accept-and-ignore as intentional ('s… → Not resolved here: the Dispatch stream carries it as an open choice (refuse / warn once / keep and record), and invariant candidate 10 is conditional on it. f44 keeps its rank as a cost-of-change find…
- between fk-649851e5fc38, fk-60410de6dd0a, fk-6c98ee030531: The config-cli seat and the forms seat each proposed a new finite-number checker (a config quantities module; scenario_blocks readers finite_number/whole_number_field/boolean_field), while web/number_fields.py already provides as_finite_float, as_finite_float_… → Resolved: number_fields.py moves down to the package leaf as the one checker; the quantities.py and finite_number designs are dropped; the Finite quantities and Scenario grammar streams say 'number_fi…
- between fk-42c0053b9a2b, fk-ff5b90768f66: The charts stream's first draft rendered ChartPanel through a new Jinja partial, but templates/components/macros.html:78 already defines chart_container(id, title, height), live at compare.html:118 and :129; p122's '0 chart_container uses each' holds only for… → Resolved: extend chart_container to take the panel; p122's measurement corrected to 'unused on the two results pages; used twice in compare.html'.
- between fk-dd434cb2d4b9, fk-1abd62632ae1, fk-eec3806e584e: The lane stream's first draft added a '-p tests._collection_report' plugin for a typed collection and a central e2e mark in tests/e2e/conftest.py, while tests/unit/test_per_task_verify.py:84 already obtains a structured collection with --junitxml parsed by Ele… → Resolved: the JUnit-XML report is the one typed collection source for collected_node_ids and _interpreters_named_by; the e2e mark is pytest.mark.e2e added in the existing hook.
- between fk-366773b4083f, fk-f8b7b3ab709d, fk-1df9dbc0d971: The web boundary stream's first draft introduced a form_limits.page_limits() value while its own seam list named fleet_components.py as the dashboard-limits home; FleetComponent already carries fixed_range/step/default enforced in __post_init__. → Resolved: fleet_components.page_limits() (frozen PageLimits, MAX_FLEET_HOMES moves in) is the one home; no form_limits module.
- between fk-6c98ee030531, fk-291910b552af, fk-601c5b5f6415: f23 proposes making ConfigurationError a ValueError so web routes catch one type; p57 records that cli/utils.handle_errors catches ConfigurationError, FileNotFoundError, ValueError and WeatherDataError but not TypeError, and that ConfigurationError is not a Va… → Posed as the Errors stream's open choice: subclass ValueError (one refusal type at both boundaries, risk of a bug's ValueError answered as a 400) or keep a plain Exception with one boundary translator…
- between fk-4872e7ab367e, fk-bd03fe349ffd: f45 proposes TOUOptimizedStrategy classify peak from the tariff and refuse a contradicting peak_hours; the briefing anticipates Flux/Agile-style tariffs and records two intentional TariffPeriod symbols, and today's tou_optimized scenarios carry YAML peak_hours… → Open choice in the Tariff stream: tariff as the authority with peak_hours a checked override, or peak_hours as an independent behavioural window. The Dispatch stream references this choice rather than…
- between fk-6a52ed98b18e, fk-2106d1fbaed0, fk-be5b13274bcb, fk-f99038047a27, fk-606a9211b34d, fk-b69968a37b36, fk-f3a20a6d53e0, fk-b7241e0ce122, fk-8376e0ab00db, fk-cc292d7ce407, fk-2264bc150fa3: review/briefing.yaml's subprojects carry purpose and scenarios but no member-path rule, so files under src/solar_challenge/cli/ are keyed under three areas (f10, f43, f59, p46 simulation-core; f11, f12 finance-economics; p159-p172 repo), seg.py under two (p40… → Provisionally applied for this synthesis: every cli/ module maps to repo and seg.py/tariff.py to finance-economics, so p163 supersedes f8, p161 absorbs f12, p72 supersedes p40, p28/p41/p46 move cells.…
- between fk-616cc076b7cb, fk-3ccbba41d836, fk-293a1282ace4, fk-78587492a799: f6 declares it supersedes p10 and f31 declares it supersedes p165; the previous synthesis ranked both members of each pair. → Resolved: p10 and p165 are removed from the matrix and from the PV and Surface-lock streams; the supersedes are recorded on f6 and f31.
- between fk-4df47ebe6a96, fk-491014934d1e: p3 and p25 propose one dispatch mechanism (the strategy objects) with simulate_timestep_tou retired or reduced to a shared settle tail; the briefing's key_decision records 'Two dispatch paths coexist ... BOTH now support grid-charging' as the state the project… → Open choice in the Dispatch engine stream: keep both entry points with one shared settle function and gate, or retire simulate_timestep_tou under a surface bump. Either way the byte-identical tail is…
- between fk-7ef1099d24e8, fk-d63c41ca13f9: f3 offers two opposite remedies (make cadence a run-owned value threaded everywhere, or declare one minute invariant and delete the 10 timestep parameters); f49 wants the window typed in the same module. One stream cannot do both of f3's options. → Open choice in the Window stream; the recommendation leans to declaring one-minute cadence invariant with boundary resampling, since every generator and consumer already assumes it and only flow/dispa…
- between fk-44fdf5fb356b, fk-06035cd76226: f58 proposes retiring set_weather_cache from the frozen surface while tests/conftest.py (3 sites), two scripts and the briefing's contract still rely on it; p12 reports the same global but its remedy stops at passing weather down. → Resolved as a sequence: pass weather explicitly first (p12), then retire the global setter at the next contract revision via the briefing's version-bump route (f58).
- between fk-16df1a7ac416, fk-e0e34ef46058: The digest's verification block reports refuted 1 / refutation_rate 0.016, but every emitted finding carries confirmed or weakened and dropped is empty; nothing in the inputs names a refuted finding. (Listed here because the only verdict-shaped dispute in the… → Corrected in method to refuted 0 / 0.0; the pipeline should either surface the refuted finding in dropped or fix its count.

## Exonerations

Simulation slice layering (physics seat, import graph): timebase and location at the bottom, then battery, dispatch and flow, then home, then fleet and community, with no cycles and no reach-backs inside the slice; the only typing cycle is battery.py:12's TYPE_CHECKING import of config types (f37) and the only hidden runtime cycle is config -> finance -> gridservices -> config (f38, p49, p82). The frozen dataclasses with __post_init__ checks make configs cheap to construct correctly; what they lack is the finite check (Finite quantities stream). What the physics seat dropped after reading the briefing, and this synthesis records as contract rather than findings: the Battery SOC and efficiency setters and constructor overrides with no src caller (the platform assigns min_soc_fraction), and the fact that load seeds both numpy and random (briefing lines 82-83 mandate seeding both). That exoneration does not reach p33 or f51: briefing 82-83 ('per-home seed = fleet_seed + index') and 252 ('the same seed reproduces ... regardless of parallel execution order') are the conventions p33 (one shared or unseeded LoadConfig per home) and f51 (10 of 10 concurrent seeded profiles differ from their serial run; an unseeded home after a seeded one is a deterministic copy) violate, so both stay ranked (simulation-core/h10 and h7) and in the RNG stream. Config readers: since task 238 every nested reader refuses unknown keys through _refuse_unrecognised_keys and _BlockType tables (p48's remaining cost is messages without block_path, not missing refusal). The strategy-comparison cluster the leads named is gone (bbf1030, task 87): no finding. Tests of the config-cli and web-forms slices: no test imports a private name from a config-cli or web-forms module; the dotted-path claim is not made, because tests/unit/test_cli.py:1161 patches cli.home.simulate_home (p170) and patches or restores status_console 8 times (f59), both ranked and in the Fleet execution stream's deletable list. cli/utils: the stdout/stderr discipline is clean and there is no h2 finding against cli/utils; the CLI's one h2 finding is p168 at cli/fleet.py::sweep. Web forms-charts slice: zero reach-backs, deferred imports, cycles or re-exports among its 11 modules and no test patches its private names; number_fields.py is one reader family with informative refusals (promoted to the package leaf by the Finite quantities stream); fleet_components.py is a real SPOT enforced in __post_init__ (its one open cost is p133'…

## Critic

verdict: revise · synthesis revised: True · Checked against the pinned tree 7dfea36 (the review worktree is gone; read via git show). Verified true: config.py rewraps ValueError into ConfigurationError at exactly the seven sites the Errors stream names (1859, 1867, 1873, 1942, 1971, 2017, 2788, plus two YAML/JSON load wraps at 2218/2242 that are not rewraps of domain errors); config.DispatchStrategyConfig and config.GridChargeConfig are in FROZEN_CLOSURE (test_public_api_surface.py:255-256); the test_cli.py:1161 dotted-path patch exists; web/number_fields.py has the finite/whole readers; macros.html has chart_container; tests/e2e/conftest.py already has a collection_modifyitems hook; test_per_task_verify.py reads a --junitxml collection. The matrix is complete (all 61 f-ids, p6, p50 and all 172 priors appear exactly once except the duplicates named above) and every new-finding score I could compute (severity x breadth x verdict) is consistent with the listed order. Not checkable from the digest: prior findings carry no severity or verdict there, so the placement of every p-id relative to f-ids (e.g. p12 above f52 in simulation-core/h7, p79 between f11 and f48) is unverifiable; skeptic notes are absent, so why 25 findings were weakened cannot be checked against the streams. Smaller items not filed as errors: p6 is a canonical of two streams (cheap-period and minute index); f7 and p4 describe one cost under two keys (both top of simulation-core/h12 and both in the Dispatch stream), the fourth such pair the contradictions section did not catch; f43 (weakened) is in the matrix but in no stream, only in invariant candidate 8; observation.re_observed lists nine canonicals that are also under 'new' and one tagless canonical ('repo|...cli/optimize.py::_sensitivity_alias_map'); the exoneration cites p87 as confirming bill() has no duplicated arithmetic, but p87 is an open h11 finding against bill's docstring, the support comes from the finance seat's area_health. The errors that force revise: the f44/Dispatch remedy reverses a briefing key decision without an open choice; five duplicate keys inflate four matrix cells and three streams; three streams recreate mechanisms the tree has; the p33 exoneration contradicts the matrix and the RNG stream.

- evidence-contradicts-conclusion at exonerations (p33, f51): The exoneration says 'p33's seeding of the global RNGs ... are briefing-mandated contract, not findings'. p33 is fleet.py::fleetconfig.create_uniform|h10 (one LoadConfig shared across homes; create_heterogeneous builds unseeded LoadConfigs). review/briefing.ya… → fix: Rewrite the exoneration to name what was dropped (Battery SOC/efficiency setters and constructor overrides; the fact of seeding both RNGs, which the briefing re…
- evidence-contradicts-conclusion at stream 'Dispatch configuration below config' (f44, p21); invariant candidate 10: The remedy 'refuses a BatteryConfig.grid_charging under a dispatcher that ignores it' and the invariant candidate make that refusal an INV-11 invariant. review/briefing.yaml key_decisions at the pin state: 'SelfConsumptionStrategy deliberately accepts-but-igno… → fix: Add an open_choice to the Dispatch stream: (a) refuse the ignored combination at construction (reverses the briefing decision; frozen-surface contract tightenin…
- evidence-contradicts-conclusion at exonerations (charts.py): 'charts.py is exonerated as a module ... p124's reconstruction of flows is the one cost.' The matrix holds five further open charts.py canonicals: p123 (colour_palette|h11), p125 (comparison_radar|h12), p131 (financial_breakdown|h1, a trace titled the opposite… → fix: Restrict the exoneration to what was measured: control flow (per-function cognitive max 5) and the _EnergyFlow/_SankeyNode enums as a SPOT. Name the six open ch…
- one-term-of-sum at exonerations (charts.py 'cognitive max 5'): charts.py is exonerated 'as a module' from the per-function maximum alone; no module total or decision-point count is recorded in the digest for charts.py, so the conclusion reads one term of the pair. → fix: Either add the module total from the metrics snapshot or narrow the sentence to 'no h2 finding per function'.
- evidence-contradicts-conclusion at exonerations (cli/utils 'cognitive 11-12 (p168 measured, no h2 finding)'): p168 is repo|src/solar_challenge/cli/fleet.py::sweep|h2, an h2 finding against the CLI that the matrix ranks under repo/h2; its prior_verdict records no cognitive figure for cli/utils, and no seat measured cli/utils at 11-12. The exoneration both misattributes… → fix: Drop the cognitive figure or cite the instrument that measured it; say 'no h2 finding against cli/utils; the CLI's h2 finding is p168 at cli/fleet.py::sweep'.
- evidence-contradicts-conclusion at exonerations ('no test in the config-cli or web-forms slices imports a private name or patches by dotted path'): p170 (repo, still_present) records tests/unit/test_cli.py:1161 monkeypatch.setattr(_cli_home_module, 'simulate_home', ...), verified at the pin ('Patch simulate_home in the CLI module (local binding)'); cli/home.py is a READ FULLY file of the config-cli seat.… → fix: Narrow the exoneration to 'no test imports a private name from a config-cli or web-forms module' and drop the dotted-path claim, pointing at p170 and f59.
- evidence-contradicts-conclusion at exonerations (finance.py 'stays near 1,840 lines after rehoming its prose'; 'neither file is large because of comments'): The finance seat measured 883 docstring + 194 comment-only lines of 2,376 (prose share 0.453, prose_home_ok false). 2,376 x 0.547 = 1,300 non-prose lines, under the 1,500 soft ceiling; no recorded rule yields 1,840. With 45% prose the claim that finance.py is… → fix: Replace the figure with the measured one (about 1,300 non-prose lines) and rest the Finance partition stream on f39's heuristic-13 symptoms (7 cycle-free functi…
- area-unmapped at f8 / p163; matrix simulation-core/h3 and repo/h3; stream 'Board reports': f8 (simulation-core) and p163 (repo) share the anchor src/solar_challenge/cli/utils.py::create_summary_table|h3. Both are ranked (f8 4th in simulation-core/h3, p163 sole entry of repo/h3) and both are canonicals of the Board reports stream, so the synthesis's… → fix: Keep one key under the one area the member rule gives cli/utils.py; record supersedes on the other; remove it from the losing matrix cell and from the stream's…
- area-unmapped at cli/ findings: f10, f43, f59 (simulation-core); f11, f12 (finance-economics); p159-p172 (repo): Files under src/solar_challenge/cli/ carry three areas across instruments: cli/fleet.py is simulation-core (f10) and repo (p167, p168); cli/finance.py is finance-economics (f11) and repo (p160, p161, p166); cli/utils.py is simulation-core (f59) and repo (p163,… → fix: Write a member rule into review/briefing.yaml (either every cli/ module to one area, or cli/<cmd>.py to the area of the domain it drives), re-key f10/f11/f12/f4…
- area-unmapped at seg.py (p40 simulation-core, p72 finance-economics); tariff.py (f14 finance-economics; p28, p41 simulation-core): seg.py::segtariff|h10 is minted under two areas and both keys are ranked (simulation-core/h10 and finance-economics/h10) and both listed as canonicals of the Finite quantities stream. tariff.py's new finding f14 is finance-economics (the finance seat read tari… → fix: Map seg.py and tariff.py to one area (finance-economics, where the seat that read them sits), re-key p28/p40/p41, record supersedes on p40 (p72 wins) and remove…
- evidence-contradicts-conclusion at matrix simulation-core/h9 (f6, p10) and repo/h11 + repo/tests (f31, p165); streams 'PV model' and 'Surface lock': f6 declares supersedes_canonical pv.py::simulate_pv_output|h9 (p10) and f31 declares supersedes_canonical __init__.py::_symbol_module|tests (p165). Both the superseding and the superseded ids are ranked in the matrix and both are listed as canonicals of their… → fix: Apply the supersedes: drop p10 and p165 from the matrix and from the PV and Surface-lock stream canonical lists, recording supersedes on the losing keys.
- duplicate-mechanism at streams 'Finite quantities: one checker in every domain __post_init__' and 'Scenario grammar': The remedies write a new quantities.py (require_finite_in, require_positive_finite, require_fraction) and new scenario_blocks readers (finite_number, whole_number_field, boolean_field) that refuse bool, NaN, inf and fractions naming the field. At the pin src/s… → fix: Move web/number_fields.py down to the package leaf (beside whole_numbers.py) as the one checker; the domain __post_init__ calls and the scenario readers wrap it…
- duplicate-mechanism at stream 'Results chart panels, theme tokens and chart facts' (p122): The remedy renders ChartPanel through 'one Jinja partial'. templates/components/macros.html:78 already defines chart_container(id, title, height) and history/compare.html:118 and :129 render through it. p122's verdict '0 chart_container uses each' is true of t… → fix: Have the stream extend chart_container (or render ChartPanel through it) rather than add a second partial; correct p122's measurement to 'unused on results/home…
- duplicate-mechanism at stream 'Lane harness' (p158, p153): The remedy adds '-p tests._collection_report plugin dumps a typed Collection so no test parses :: text'. tests/unit/test_per_task_verify.py:35-89 already obtains a structured collection with pytest's --junitxml and parses it with ElementTree, the seam the repo… → fix: Make the JUnit-XML report the one typed collection source for collected_node_ids and _interpreters_named_by instead of a new plugin; phrase the e2e-mark remedy…
- duplicate-mechanism at stream 'Web request boundary' (p119, p140, p133): The remedy introduces 'a form_limits.page_limits() frozen value (MAX_FLEET_HOMES, seed, days, each FleetComponent's fixed_range/step/default ...)' while the same stream's seam_candidates and the exonerations name fleet_components.py as 'the dashboard-limits ho… → fix: One home: fleet_components.page_limits() (or a frozen PageLimits built there); delete the form_limits module from the remedy.
- evidence-contradicts-conclusion at digest verification counts (refuted 1, dropped []): verification reports confirmed 38 + weakened 25 = 63, which is every emitted finding (f1-f61, p6, p50); 'refuted: 1' and refutation_rate 0.016 name a 64th verdict that appears on no finding and in no dropped entry, so the synthesis consumed a refutation it nev… → fix: Name the refuted finding and its disposition in dropped, or correct refuted to 0 and the rate to 0.0.
- inconsistent-rule at stream 'Finance partition' deletable vs f39 measurement: The stream deletes 'the eight function-local imports in finance.py'; f39 measured '7 statements, 8 names' that close no cycle, and the digest records three further cycle-closing statements (finance.py:119, :1540 via f38/p82; :1606 via f53) that the Errors and… → fix: State the figure as statements (7 remaining after the Errors and Grid-services streams remove 119, 1540 and 1606) and name the removing stream for each.
- do-not-steer-leak at exonerations (web server slice 'healthy by size'): 'The web server slice is healthy by size: no file reaches the alarm (assistant.py 1,034, api.py 1,020)' reads line counts as health. Under the definition being under the alarm means only that heuristic 14 does not fire; the same slice carries 23 open priors an… → fix: Say 'no file reaches the h14 alarm' and leave health to the findings.
- severity-unsupported at f7: f7's next_change is: six sites to edit in step, mypy flags none, a misspelt or wrong-level value simulates as self-consumption and is caught only by a test asserting strategy_name. That is the same scenario shape and detection gap as f44 (silent 0 kWh grid cha… → fix: Set f7 to medium; it stays first in simulation-core/h12. If the lead holds high, the record needs the distinguishing consequence stated in next_change.

Severity corrections: 1 applied, 0 flagged (critic_disputes_severity).
- fk-94f4881bbe48: high → medium — f7's next_change is: six sites to edit in step, mypy flags none, a misspelt or wrong-level value simulates as self-consumption and is caught only by a test asserting strategy_name. That is the same scenario shape and detection gap as f44 (silent 0 kWh grid charge; medium) and f1 (silent flat sweep; medium); the extra cost f7 names is breadth across sites, which the method scores separately. Nothing in the scenario (board-facing figure already wrong and shipping, data loss, concurrency) lifts it above those two. — accepted=True applied=True

## Dropped and degraded

none
- seats lost: none
- pinned worktree: removed by an external sweep of .worktrees/ while phases 3-4 ran (no log found); every seat re-extracted as_of_sha with git archive into its scratch and read that identical tree, so anchors were still verified at as_of_sha
- calibration sample: not run (the area skeptics refuted one finding, so the zero-refutation trigger did not fire); the Phase 2 siblings recorded 0 refutations across 179 findings and ran no sample
- area rule divergence: review-solar_challenge-20261013 mapped tariff.py and seg.py to simulation-core and src/solar_challenge/cli/** plus the package __init__ to repo, while this run and the hotspot survey map them to finance-economics and simulation-core; keys at those anchors differ between instruments (critic area-unmapped items). Fix: member lists in review/briefing.yaml and a /review-all overlay, which the repo cannot hold until its dangling .claude symlink is replaced
- markdown size: rendered above the ~60 KB target because 233 findings and 28 streams are carried; the one-line and compact forms are already in use
- unchecked priors: 0
- synthesis ids unresolved: none
- instruments not re-run: ['legacy:review/reports/summary-20260630T110159Z.md', 'none']
- refuted this run: 1 — fk-ec3fe72ce844 `src/solar_challenge/cli/main.py::version_callback`: grep for 0.5.0 and __version__ over pyproject.toml, src and tests in the 7dfea36 tree. Read tests/unit/test_package.py in full. Checked __init__.py's lazy get_c
- fable seats wanted and not run: none

## Mechanical filings

| key | sources | step | ticket or task | disposition |
|---|---|---|---|---|
| fk-9dd1d9389dd2 | hotspot-survey-solar_challenge-20261013 | none | 697 | filed:697 |
| fk-acdc650baeb8 | hotspot-survey-solar_challenge-20261013 | none | 698 | filed:698 |
| fk-a98db49f3fd7 | hotspot-survey-solar_challenge-20261013 | none | 699 | filed:699 |
| fk-7dcdc5559d22 | hotspot-survey-solar_challenge-20261013 | none | 382 | filed:382 |
| fk-8f26d000b68d | hotspot-survey-solar_challenge-20261013 | 2 | 674 | filed:674 |
| fk-b0607cc5a685 | hotspot-survey-solar_challenge-20261013 | none | 700 | filed:700 |
| fk-b867cc3e5653 | review-solar_challenge-20261013 | none | 701 | filed:701 |
| fk-62dbe0f34b68 | review-solar_challenge-20261013 | none | 702 | filed:702 |
| fk-89afcb2b57f7 | review-solar_challenge-20261013 | none | 703 | filed:703 |
| fk-71b4ca35efe0 | review-solar_challenge-20261013 | none | 704 | filed:704 |
| fk-2106d1fbaed0 | review-solar_challenge-20261013 | none | 705 | filed:705 |
| fk-e756dab8077e | review-solar_challenge-20261013 | 2 | 681 | filed:681 |
| fk-664e2030921e | review-solar_challenge-20261013 | none | 706 | filed:706 |
| fk-f2e1ad46df4b | review-solar_challenge-20261013 | 2 | 297 | filed:297 |
| fk-a2b33a420bcf | review-solar_challenge-20261013 | 2 | 675 | filed:675 |
| fk-e79170280adf | review-solar_challenge-20261013 | none | 707 | filed:707 |
| fk-740e9a804a4f | review-solar_challenge-20261013 | none | 708 | filed:708 |
| fk-e58042aef503 | review-solar_challenge-20261013 | none | 709 | filed:709 |
| fk-491014934d1e | review-solar_challenge-20261013 | 2 | 270 | filed:270 |
| fk-a80aa8f942eb | review-solar_challenge-20261013 | none | 710 | filed:710 |
| fk-89777ec9faad | review-solar_challenge-20261013 | none | 711 | filed:711 |
| fk-41767a1bc146 | review-solar_challenge-20261013 | none | 712 | filed:712 |
| fk-0097b5aaa45c | review-solar_challenge-20261013 | 2 | 564 | filed:564 |
| fk-ab16fff6f6c3 | review-solar_challenge-20261013 | none | 713 | filed:713 |
| fk-ce345e3b013d | review-solar_challenge-20261013 | none | 714 | filed:714 |
| fk-70edc755ede4 | review-solar_challenge-20261013 | 2 | 245 | filed:245 |
| fk-6cd8a932665c | review-solar_challenge-20261013 | 2 | 581 | filed:581 |
| fk-0b791f2be2d6 | review-solar_challenge-20261013 | 2 | 485 | filed:485 |
| fk-50cf1dd5df58 | review-solar_challenge-20261013 | none | 715 | filed:715 |
| fk-9fa18977ec68 | review-solar_challenge-20261013 | none | 716 | filed:716 |
| fk-72fdec5965a1 | review-solar_challenge-20261013 | none | 717 | filed:717 |
| fk-0b4f5e04067c | review-solar_challenge-20261013 | none | 718 | filed:718 |
| fk-78587492a799 | review-solar_challenge-20261013 | none | 719 | filed:719 |
| fk-f66948b9528c | review-solar_challenge-20261013 | none | 738 | filed:738 |
| fk-19457544d6b6 | review-solar_challenge-20261013 | none | 722 | filed:722 |
| fk-32d5e6707fb5 | review-solar_challenge-20261013 | none | 739 | filed:739 |
| fk-6b7c45f8d766 | review-solar_challenge-20261013 | none | 731 | filed:731 |
| fk-d89ee8df893c | review-solar_challenge-20261013 | none | 740 | filed:740 |
| fk-b523bff3e51c | review-solar_challenge-20261013 | none | 741 | filed:741 |
| fk-31fd9d5d4c68 | review-solar_challenge-20261013 | none | 742 | filed:742 |
| fk-dc5cf2ec9b84 | review-solar_challenge-20261013 | none | 743 | filed:743 |
| fk-caad5305a3be | review-solar_challenge-20261013 | 2 | 237 | filed:237 |
| fk-00cb82820af9 | review-solar_challenge-20261013 | none | 744 | filed:744 |
| fk-7fa120a8bb98 | review-solar_challenge-20261013 | none | 745 | filed:745 |
| fk-e0e34ef46058 | review-solar_challenge-20261013 | none | 746 | filed:746 |
| fk-f7b19fc4c8b5 | review-solar_challenge-20261013 | none | 747 | filed:747 |
| fk-998f0cb69410 | review-solar_challenge-20261013 | 2 | 284 | filed:284 |
| fk-97213a0e9ab2 | review-solar_challenge-20261013 | none | 748 | filed:748 |
| fk-756c0ef9e9d9 | review-solar_challenge-20261013 | none | 749 | filed:749 |
| fk-cdcdf320a9e8 | review-solar_challenge-20261013 | none | 153 | filed:153 |
| fk-2ac79d7a1989 | review-solar_challenge-20261013 | none | 750 | filed:750 |
| fk-93d3bd7aa219 | review-solar_challenge-20261013 | none | 751 | filed:751 |
| fk-02500b87f3cb | review-solar_challenge-20261013 | none | 752 | filed:752 |
| fk-f8b7b3ab709d | review-solar_challenge-20261013 | 2 | 376 | filed:376 |
| fk-3cd0d3f3b512 | review-solar_challenge-20261013 | none | 753 | filed:753 |
| fk-d8ad51b22de5 | review-solar_challenge-20261013 | none | 754 | filed:754 |
| fk-ba29e186122f | review-solar_challenge-20261013 | none | 755 | filed:755 |
| fk-5827f41eb082 | review-solar_challenge-20261013 | none | 517 | filed:517 |
| fk-48447960eb2c | review-all-solar_challenge-20261013 | none | 756 | filed:756 |
| fk-b97bf2325eda | review-all-solar_challenge-20261013 | none | 757 | filed:757 |
| fk-f4d53977c642 | review-all-solar_challenge-20261013 | lead-weakened | None | open |
| fk-789558b03270 | review-all-solar_challenge-20261013 | none | 758 | filed:758 |
| fk-94cab00e114e | review-all-solar_challenge-20261013 | none | 759 | filed:759 |
| fk-753ec8e6e149 | review-all-solar_challenge-20261013 | lead-weakened | None | open |
| fk-cca5fd81afda | review-all-solar_challenge-20261013 | none | 760 | filed:760 |
| fk-601c5b5f6415 | review-all-solar_challenge-20261013 | none | 177 | filed:177 |
| fk-8376e0ab00db | review-all-solar_challenge-20261013 | lead-weakened | None | open |
| fk-188af6c13d71 | review-all-solar_challenge-20261013 | 2 | 485 | filed:485 |
| fk-2228ae61ef4e | review-all-solar_challenge-20261013 | none | 717 | filed:717 |
| (164 structural findings) | review-all, review, hotspot-survey | structural, contract §6 | — | open → deliberation (keys in the findings JSON and in the stream list above) |

## Next

Deliberation per references/deliberation.md, anchored on this report; program doc expected at `plans/review-all-program-solar_challenge-20261013.md`; the contract §11 trigger chain is filed as the program's last act and its ids land in the program doc's FILED section.
