# PRD — Surface version bump: one release window, one release commit, one re-pin

- **Program:** review-all-solar_challenge-20261013, stream **S29** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 4, upstream every stream that changes a frozen name, size S, risk medium, mode agent.
- **Finding keys:** none. Every leaf carries `x_finding_key: []` and `x_lead_ruling: "D4"`.
- **Binding rulings:**
  - D4: one coordinated surface bump for the whole program, with one consumer-recipe update. No re-export shim or dual field survives the program. The platform consumer re-pins once.
  - D29: additive frozen-table edits land in-leaf with their row and an "Unreleased on main" line. Renames and retirements are held leaves that S29 releases.
  - D31: `simulation_days` leaves `householder_bill` and `bill_distribution` at the bump (it rides in 784).
  - L3: `ConfigurationError` joins `__all__` in S29's release.
  - L13: `get_tmy_data` is retired at the bump, in 827.
  - L27: 892 (`solve_cost_recovery_rate`'s `simulate=None` retired; `FleetRunner` exported) is held for S29.
  - L30: 912 (`CommunityConfig.sharing_mode` derived) is held for S29.
  - L32: 927 (S23 η, the released snapshot) is held on S29's release commit.
  - L37: ruled `tariff_config` would go with `ScenarioConfig.output` in 950 unless S6 claimed it. S6 did not claim it (§Cross-reference S6 line), so 950 retires it.
  - L41: the S23 lock may label the `ScenarioConfig` freeze breaking. If it does, S29's inventory names it.
- **Status:** authored 2026-10-18 by an author-only /prd seat (agent mode). Not committed.
- **Approach:** B + H. The work is three small leaves. The stakes are a release that a consumer pins and an ordering across 16 held leaves of 15 streams, so §4 is a contract and §5 a boundary-test sketch.
- **Code anchors** verified against main `beb1d9103ad8` (2026-10-18). The task store was read at 2026-10-18T09:14:46Z. Main moves fast: cite symbols and re-read at implementation time.

## 1. Goal

The program ends in one release, `solar-challenge-v0.6.0`. Every rename and retirement the program makes lands inside one release window. One release commit bumps the version and folds every "Unreleased on main" line into one release section. The platform consumer re-pins once, following one recipe.

What a user observes. The users are a platform developer re-pinning, an agent landing a held leaf, and the next agent changing the surface.

1. **A held leaf has a section to write into.** Each held leaf's task says it adds its line "in the release section S29 opens". After α, `docs/domain-library-consumption.md` has that section. It is headed `### solar-challenge-v0.6.0`, and it says the window is open. Today it does not exist.
2. **`from solar_challenge import ConfigurationError` works** and type-checks under mypy --strict (L3). Today the name is importable only from `solar_challenge.errors`.
3. **One commit is the release.** After β, these all say 0.6.0: `pyproject.toml`, `solar_challenge.__version__`, `uv.lock`'s own entry, the consumption guide's worked example and its "current release" tag line, and the finance-model doc's Version header. Neither doc carries an "Unreleased on main" line. Each such line, 25 in the consumption guide and 7 in the finance-model header at `beb1d91`, is now an entry of the 0.6.0 notes, grouped as breaking, results that move, or additive. Each breaking entry names what a consumer writes instead.
4. **The release names every break.** β's inventory runs S23 ζ's lock over the tables as they stood at the window's opening. Every entry the lock labels `breaking` is named in the release section, with no extra and none missing.
5. **The platform re-pins once.** After γ, `git ls-remote --tags origin solar-challenge-v0.6.0` prints the tag, on β's merge commit. A re-pin task is filed in `solar_challenge_platform`, and it lists the platform sites the recipe changes.
6. **The next surface edit has an executable obligation.** 927 (S23 η) lands on β's release commit and snapshots the released tables, so the next edit to a frozen row fails until it names its Unreleased line. S29 only orders 927. S23 owns it.

## 2. Background (measured at `beb1d91`, store at 2026-10-18T09:14:46Z)

### 2.1 The release machinery today

- `pyproject.toml` has `version = "0.5.0"`, and so does `src/solar_challenge/__init__.py`'s `__version__`. `tests/unit/test_package.py::test_pyproject_version_matches_dunder` keeps the two equal. `uv.lock` records the project's own `version = "0.5.0"`, so a bump without a re-lock fails every `uv run --locked`.
- The tags are `solar-challenge-v0.2.0` to `v0.5.0`. `v0.5.0` is on `03af26e`, the merge commit of task 110, whose own commit bumped the version. The tag is cut on the merge, after the leaf.
- `docs/domain-library-consumption.md`:
  - It has a "Pinned dependency recipe" with a worked example at `@solar-challenge-v0.5.0`, and an "Upgrade workflow".
  - Its "Tag / release convention" section holds the tag list, the push-and-`ls-remote` rule, the v0.5.0 note and the "Changes merged since the last tag" rule. Then come 25 `**Unreleased on main**` paragraphs, tasks 392 to 777.
  - Its "Frozen public surface" section still names `tests/unit/test_init_lazy_surface.py`, which S23 α deletes.
- `docs/cost-recovery-finance-model.md` has a `**Version**: 0.5.0` header and 7 `**Unreleased on main**` lines (tasks 219, 271, 281, 295, 307, 308, 656).
- `tests/unit/test_consumption_doc.py` checks only that the guide exists and is non-empty.
- `git grep -i -E 'S29|surface bump' main -- src tests` finds nothing today. Held leaves may add such pointers, for example S15's `default_weather` docstring ("Until the S29 bump"). β removes any that remain.

### 2.2 The held leaves (the store, read-only)

There are 16 tasks with `metadata.x_seam_wait.stream == "S29"`, all `deferred`:

| Task | Stream / label | Retires or renames | Deps in store |
|---|---|---|---|
| 784 | S10 η | `SummaryStatistics.window` required, `simulation_days` derived, `annual_self_consumption_kwh` → `window_self_consumption_kwh`, `simulation_days` parameter dropped (D31), timestep defaults dropped, `per_minute_amounts` → `per_step_amounts` | 778, 779, 782, 783, 822 |
| 790 | S2 ε | home- and fleet-level `dispatch_strategy` key and `HomeConfig.dispatch_strategy`; `BatteryConfig.dispatch_strategy` defaults to `SelfConsumptionStrategyConfig()` | 787, 822, 839, 904 |
| 804 | S9 ε | `FinanceConfig`'s two grid-services fields and the `str` model selector; `grid_services_model_of` | 802, 803 |
| 826 | S14 η | `apply_degradation` | 284, 810 |
| 827 | S15 ε | `set_weather_cache`, `get_weather_cache`, `get_tmy_data`, `_weather_cache` | 809, 813, 815 |
| 843 | S11 ε | `TariffConfig.mean_period_rate` | 838 |
| 867 | S28 γ | `BatteryConfig.efficiency` | 863, 822 |
| 892 | S16 ζ | `solve_cost_recovery_rate`'s `simulate=None`; `FleetRunner` and four protocols join `__all__` | 885 |
| 901 | S12 ζ | `SimulationResults.heat_pump_load` and three heat-pump summary fields; `load_energy_kwh` required; `EVConfig` enum annotations | 895, 897, 899, 822 |
| 905 | S3 ζ | `simulate_timestep_tou` | 904 |
| 912 | S27 γ | `CommunityConfig(sharing_mode=…)` and the YAML key | 910 |
| 927 | S23 η | (not a retirement) the released snapshot and the executable Unreleased check; `x_seam_wait` is "the release commit…" | 926 |
| 939 | S8 ι | `_SYMBOL_MODULE["solve_cost_recovery_rate"]` → `projection`; finance's wrapper | 892, 928, 930 |
| 941 | S8 κ | `BillDistribution.per_home_net_bill_gbp` → `per_home_total_outlay_gbp` | 784, 917 |
| 950 | S5 ζ | `ScenarioConfig.output`, `config.OutputConfig`, `ScenarioConfig.tariff_config` | 949 |
| 963 | S6 ι | `ScenarioConfig.period` becomes a `SimulationWindow`; `config.SimulationPeriod` | 956 |

There is one more, not yet filed: **S25 ζ** retires `SummaryStatistics.seg_revenue_gbp`. Its id comes at the S25 decompose (cross-reference line "S29 (from S25)"). That makes 15 retirement leaves on file across 14 streams, plus 927, plus S25 ζ to come.

No held leaf carries `metadata.delivered_checks`. Two edges between held leaves already exist: 941 → 784 and 939 → 892. Each held leaf's task already tells it to:

- edit the frozen tables in `tests/unit/test_public_api_surface.py` in its own commit, because the lock fails otherwise;
- add its line "in the release section S29 opens" (790, 827, 905, 912 say so in those words; 826 and 843 hand their line to "S29's section").

### 2.3 What the platform consumer touches

`solar-challenge-platform` is at `d521265`, pinned at `solar-challenge-v0.5.0`, project `solar_challenge_platform`. `git grep` over its `src` and `tests` finds:

| Name the release changes | Sites |
|---|---|
| `simulation_days` (`SummaryStatistics(…)` and `householder_bill(…)`) | 13 in 3 files |
| `annual_self_consumption_kwh=` | 4 in 3 files |
| `seg_revenue_gbp` | 3 in 2 files |
| `total_heat_pump_load_kwh` and the other two heat-pump summary fields | 3 + 9 in 2 files |
| `SummaryStatistics(` | 4 in 3 files |
| `householder_bill(` | 6 in 3 files |
| `BillDistribution.per_home_net_bill_gbp` | 1 in 1 file |
| `SimulationPeriod` | 2 in 1 file (its seam test) |
| `from solar_challenge.config import GridChargeConfig` (S2 α moves it to `dispatch`; the config binding stays at runtime but not for mypy) | 2 files |
| `solve_cost_recovery_rate(…, simulate=simulate)` (`billing/cbs.py::recommend_rate`, whose `simulate` defaults to `None`) | 3 sites in 3 files |

These have 0 sites: `set_weather_cache`, `get_tmy_data(`, `simulate_timestep_tou`, `apply_degradation`, `mean_period_rate`, `efficiency=` (the platform passes the per-direction pair), `dispatch_strategy`, `sharing_mode`, the two grid-services fields, `OutputConfig`, `per_minute_amounts`, `FleetRunner`.

So the re-pin is a real code change in the platform, not a pin edit alone.

### 2.4 Task 224: a release task already on file

Task 224 is `pending`, `low`, with no claimant and no branch. It is titled "Decide whether to cut a solar-challenge release with task 219's CBS grid-charge correction so solar-challenge-platform can re-pin". It has no dependencies, so the scheduler may dispatch it at any time.

- Its details carry four release-scope notes:
  - task 219's CBS correction;
  - task 326's `TOUOptimizedStrategy(off_peak_hours=…)` break, which argues for a minor bump;
  - task 285's TMY scaling, which moves every weather-driven figure;
  - the Python floor's rise to 3.11 (esc-review-20260930T042942-5, option B).
- Its 195 note is void, per the recon relay note in the same details.
- Its `files` are β's files.

If it runs before the window closes, it cuts a release with the program half landed, which D4 forbids. §10 Q1 asks the lead to park it now.

## 3. Resolved design decisions

1. **Release model: the window opens with α, the held leaves land inside it, and β closes it.** The program doc says "released in the bump window". The held leaves' tasks say they write into "the release section S29 opens". 927 waits on "the release commit that bumps the version and writes the one release section". The lead's addendum asks for both edge directions at once (held leaves on the bump, and the bump on every held leaf), which would be a cycle. Splitting the opening from the closing satisfies every one of these texts:
   - each held leaf **depends on α**, which opens the window;
   - **β depends on every held leaf** and is the release commit;
   - **927 depends on β**.

   α is also the inventory's baseline (decision 4). Without α, the first held leaf to land would have to create the section, and fifteen agents would follow an ad-hoc rule.
2. **Version 0.6.0** (§10 Q2). Pre-1.0 semver allows a break in a minor. The v0.5.0 note set the precedent of a minor that breaks constructors, and 224's notes already argue for 0.6.0. The tag list keeps `v1.0.0` as "first stable / breaking-change boundary (future)".
3. **β waits for the library side of the whole program, not only the held leaves** (§10 Q3). "One re-pin" means more than adapting to breaks. The platform calls `solve_cost_recovery_rate` and the billing functions, so it needs the figures that move too: S3 γ settlement, S11 γ presets, S14's NOCT yield, S28 β cycle fade, S8 θ capex, S9 α′. If those landed after the tag, the platform would re-pin a second time to get correct figures.
   - So β depends on every open program leaf whose `metadata.files` names a library module, meaning `src/solar_challenge/*.py` outside `web/` and `cli/`.
   - At the store read there are 90 such leaves besides the held ones (open tasks with `x_finding_run` of this run, not 944). 58 of them are already upstream of a held leaf. 32 are not. Leaving out 759, which the S18 decompose cancels, these 31 need an edge: 707, 718, 781, 789, 812, 818, 823, 825, 833, 841, 861, 862, 864, 865, 866, 868, 871, 900, 902, 907, 908, 931, 933, 934, 935, 936, 937, 940, 948, 957, 961.
   - The decompose session recomputes the list at its own time (§11).
   - Web-only and CLI-only leaves are not edges, because they do not change what the platform imports.
4. **The inventory is the S23 lock run against the tables at the window's opening** (S23 F5, cross-reference "S29 (from S23)"). On β's branch:
   - copy `tests/unit/test_public_api_surface.py` as it stood at α's merge commit to a scratch module;
   - run it against β's base;
   - the entries ζ labels `breaking` are the in-window breaks;
   - the `**Unreleased on main**` paragraphs give the changes from before the window (task 326, S2 α's `GridChargeConfig` move, refusals the 0.5.0 tag accepted).

   The scratch module is deleted before commit. 927 makes the same comparison permanent from β onward, so β adds no test of its own for it.
5. **Folding, not rewriting.**
   - β moves each Unreleased paragraph under `### solar-challenge-v0.6.0`, into one of three groups: breaking, results that move, additive. It keeps the paragraph's text and task id, without the "Unreleased on main" prefix.
   - The finance-model header's lines come in under results that move. Its Version line becomes 0.6.0 and points at the release section.
   - The held leaves' lines, already in the section, go into the breaking group.
   - Each breaking entry ends with its consumer action.
   - "Changes merged since the last tag" stays as the rule for later changes. After β, no "Unreleased on main" paragraph is left in either doc.
6. **The tag convention gains the window rule.** One paragraph in "Tag / release convention" says:
   - a rename or retirement lands only inside an open release window, with its line in that window's section;
   - the window closes with the release commit that bumps the version;
   - the tag is cut on that commit's merge, pushed, and checked with `ls-remote` (as today).

   927 adds the snapshot step to the same section. S29 does not write it.
7. **`ConfigurationError` joins `__all__` in α** (L3). It is additive, so it could land at any time. Putting it in α gives the window-opening leaf a signal a consumer can run.
   - α depends on 774 (S1 β, pending), so the form α freezes has `ValueError` as its base.
   - Its `_SYMBOL_MODULE` origin is `errors`.
   - Its line goes in the release section's additive group.
8. **The tag and the platform re-pin are a human gate, γ** (§10 Q4).
   - A leaf cannot tag its own merge commit, and pushing a tag needs the GitHub credentials the sandbox lacks. task 110's tag was cut after its merge in the same way.
   - The re-pin is in another project's tree, `solar_challenge_platform`.
   - γ cuts and pushes the tag, checks it, and files one task in the platform project. That task carries β's consumer recipe and §2.3's site list, re-measured, and depends on nothing in this project.
9. **Task 224 is re-scoped in place as β** (§10 Q1), as 705 became S25 α (L39) and 751 became S22 β (L29). It is the same work. Its details already carry the four release-scope notes β must fold, and it has no claimant and no branch.
10. **Priorities.**
    - α, β and γ are filed `medium`, like the held leaves. A `low` α would gate 16 medium leaves behind the scheduler's lowest tier.
    - Each carries `x_lead_ruling: "D4"`.
    - β also joins the trigger-chain gate 772 (§10 Q5). It is the program's last library leaf, so the next review-all run would otherwise measure a half-released surface.

## 4. Contract

### 4.1 The release window (owner S29; readers: every held leaf, 927, the platform)

- **W1.** After α, `docs/domain-library-consumption.md`'s "Tag / release convention" section has one subsection headed exactly `### solar-challenge-v0.6.0`. Its first line says the window is open and names α's task. A held leaf adds its paragraph under that heading in the existing form, `**Unreleased on main** (task N): …`, ending with its consumer action.
- **W2.** No held leaf edits `version`, `__version__`, `uv.lock`'s project entry, the tag list or the worked example. Those are β's.
- **W3.** A non-held leaf keeps today's convention: its additive or behavioural line goes beside the other Unreleased paragraphs, not under the window heading. β folds both kinds.
- **W4.** The window is closed by β's merge commit. After it, the heading's status line says "released", there is no Unreleased paragraph in either doc, and the version is 0.6.0. The next surface change starts a new Unreleased paragraph, under 927's snapshot rule.
- **W5.** The inventory (decision 4): every path that S23 ζ's lock labels `breaking` between α's merge commit and β's base is named in the section's breaking group, and every name the breaking group lists is such a path or comes from a pre-window Unreleased paragraph.

### 4.2 Release section shape (after β; wording tactical)

```
### solar-challenge-v0.6.0

Released by task <β> (the review-all-solar_challenge-20261013 program). Python floor: 3.11.

**Breaking** — each entry: what changed (task N); what a consumer writes instead.
**Results that move** — each entry: which figure moves and by how much where measured (task N).
**Additive** — each entry (task N).

#### Consumer recipe for 0.6.0
1. Change the pin to solar-challenge-v0.6.0 (the Pinned dependency recipe) and run uv lock.
2. Apply the breaking group's replacements (a table: old spelling -> new spelling).
3. Re-baseline figures listed under "Results that move".
Platform (solar-challenge-platform at <sha>): the sites that change, by file.
```

### 4.3 Invariants

- **I1.** At most one release window is open at a time. It opens in α and closes in β.
- **I2.** `pyproject.toml`'s version, `__version__`, `uv.lock`'s project version, the worked-example tag and the tag list's "current release" line all name one version. β adds a test that the two doc spellings equal `solar-challenge-v{__version__}`. `test_package.py` already ties the first two.
- **I3.** No src or test file names S29, the surface bump or a transitional form "until the bump" after β (D4: nothing transitional survives).

## 5. Boundary-test sketch

| # | Faces | Scenario | Preconditions | Postconditions | Leaf |
|---|---|---|---|---|---|
| R1 | consumer (library) | The error type is public | α landed | `from solar_challenge import ConfigurationError` works; mypy --strict on a star-import consumer sees the name; `issubclass(ConfigurationError, ValueError)`; `FROZEN_SURFACE` has its row. **RED today:** ImportError from `solar_challenge` | α |
| R2 | producer (held leaf) | A held leaf finds its section | α landed | `### solar-challenge-v0.6.0` exists once, with an open-window line. **RED today:** absent | α |
| R3 | consumer (platform) | The version is one fact | β landed | `pyproject.toml`, `__version__`, `uv.lock` say 0.6.0; `uv run --locked` passes; the new doc test passes. **RED today:** 0.5.0 | β |
| R4 | consumer (doc reader) | Nothing is left unreleased | β landed | `grep -c '^\*\*Unreleased on main\*\*'` is 0 in both docs; every task id that had a line appears in the 0.6.0 section | β |
| R5 | producer (S29) | The inventory is complete | β's branch, scratch module from α's merge commit | each lock entry labelled `breaking` is named in the breaking group, and the reverse holds; the scratch module is gone before commit | β |
| R6 | both | The doc test catches a stale tag | scratch edit of `__version__` to 0.6.1 | the doc test fails, naming the worked-example tag and the tag line | β |
| R7 | consumer (platform) | The tag resolves | γ done | `git ls-remote --tags origin solar-challenge-v0.6.0` prints β's merge commit; a platform task exists with the recipe and site list | γ |
| R8 | producer (held leaves) | Nothing transitional survives | β landed | `git grep -i -E 'S29|surface bump' -- src tests` finds nothing | β |

## 6. Existing tasks this PRD meets

| Task | Status | Relation |
|---|---|---|
| 224 | pending, no deps, no claimant | **Re-scoped in place as β** (decision 9). The lead parks it `deferred` now (§10 Q1). Its four release-scope notes become β's fold inputs. Its 195 note stays void |
| 784, 790, 804, 826, 827, 843, 867, 892, 901, 905, 912, 939, 941, 950, 963 | deferred, held | Each gains `→ α`. β gains `→` each. Each is released by commit_planning, with `x_seam_wait` moved to `x_seam_released` (the 894 precedent) |
| S25 ζ | not yet filed | The same as the row above, once its id exists |
| 927 | deferred, held, deps 926 | Gains `→ β`, and is released with the others. S23 owns its content |
| 926 | pending (S23 ζ) | α depends on it, so the classification exists before the window opens (F4, F5) |
| 774 | pending (S1 β) | α depends on it (decision 7) |
| 772 | deferred (trigger chain) | Gains `→ β` (§10 Q5) |

## 7. Cross-PRD relationship

| Other PRD / stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| S23 `surface-lock-one-module.md` | consumes | F4/F5: ζ's labels drive the inventory; η (927) lands on β | S23 (lock), S29 (window, release commit) | ζ pending; η held |
| S2, S3, S5, S6, S8, S9, S10, S11, S12, S14, S15, S16, S25, S27, S28 | consume | W1–W3: each held leaf lands after α and writes under the window heading | each stream (its line), S29 (section) | held |
| S1 | produces for | `ConfigurationError` (774's base class) joins `__all__` in α | S1 (type), S29 (export) | 774 pending |
| S19 `run-store-one-owner.md` | produces for | C10: each retired stored field ships its `RunDocumentStep` in its held leaf (784, 790, 867, 901 depend on 822; S25 ζ likewise) | S19 | wired |
| S4, S7, S13, S17, S18, S20, S21, S22, S24, S26 | none held | their in-leaf Unreleased lines are folded by β; S4, S7, S13, S17 and S22 library leaves are β edges (decision 3) | — | — |
| `solar_challenge_platform` | consumes | one re-pin task filed by γ | platform | after γ |

## 8. Decomposition plan

Labels are this PRD's. Every leaf carries `x_finding_key: []`, `x_lead_ruling: "D4"`, `x_finding_run = review-all-solar_challenge-20261013`, `source = review-all` and `prd_path`. Each leaf is filed under `planning_mode=True`.

**α — Open the 0.6.0 release window; `ConfigurationError` in `__all__`** (intermediate; unlocks the held leaves; priority medium)

- **Files:**
  - `docs/domain-library-consumption.md` (the window heading and its open line under "Tag / release convention"; decision 6's convention paragraph; the "Frozen public surface" paragraph re-read against S23 α);
  - `src/solar_challenge/__init__.py` (`__all__`, `_SYMBOL_MODULE["ConfigurationError"] = "errors"`, the TYPE_CHECKING import);
  - `tests/unit/test_public_api_surface.py` (the `FROZEN_SURFACE` row, pasted from the lock's `current`).
- **Work:**
  - decisions 1, 6 and 7;
  - one paragraph under the heading for `ConfigurationError`, in the additive group.
- **Signal:** R1 and R2 (both RED today). The lock passes. mypy --strict on `src/solar_challenge` passes.
- **Consumer:** every held leaf (W1); library consumers that catch the error; β's inventory (α's merge commit is the baseline).
- **Prereqs:** 926 (S23 ζ), 774 (S1 β).

**β — Release solar-challenge 0.6.0: version, folded notes, consumer recipe** (leaf; priority medium; task 224 re-scoped in place)

- **Files:**
  - `pyproject.toml` and `src/solar_challenge/__init__.py` (version);
  - `uv.lock` (`UV_OFFLINE=1 uv lock`; no dependency moves);
  - `docs/domain-library-consumption.md` (the section, recipe, tag list, worked example and Upgrade workflow example);
  - `docs/cost-recovery-finance-model.md` (the Version header; its Unreleased lines folded);
  - `tests/unit/test_consumption_doc.py` (I2's test);
  - `review/briefing.yaml` (only if a convention line names 0.5.0 as current; dated attestation comments stay).
- **Work:**
  - decisions 4 and 5, and the I3 sweep;
  - fold 224's four notes: 219, 326, 285, and the Python floor 3.11 (the platform pins `>=3.11,<3.13`, so the ranges nest);
  - re-measure §2.3's platform sites at the platform's main of the day and write them under "Platform";
  - name the tariff_config retirement with 950 and the `SimulationWindow` period with 963 (S6 cross-reference lines).
- **Signal:**
  - R3, R4, R5, R6 and R8;
  - the verify passes on `uv run --locked`;
  - the release section's breaking group has one entry per held leaf (16, with S25 ζ) plus the pre-window breaks, each with its consumer action.
- **Consumer:** the platform's re-pin (γ's task); 927, which snapshots the tables at this commit; the next surface edit.
- **Prereqs:** α; 926; every held leaf other than 927; S25 ζ; the library-side program leaves of decision 3.

**γ — Human gate: cut and push `solar-challenge-v0.6.0`; file the platform re-pin** (human gate, `task_kind: deterministic`; priority medium)

- **Work:**
  - on main, `git tag solar-challenge-v0.6.0 <β's merge commit>`;
  - `git push origin solar-challenge-v0.6.0`;
  - `git ls-remote --tags origin solar-challenge-v0.6.0` must print it;
  - file one task in `solar_challenge_platform` (project_root `/home/leo/src/solar-challenge-platform`): re-pin to `solar-challenge-v0.6.0` per the consumption guide's 0.6.0 recipe, with the site list β wrote and the guide's Upgrade workflow (pin, `uv lock`, one reviewed commit).
- **Signal:** R7.
- **Consumer:** the platform (D4's one re-pin).
- **Prereqs:** β.

**Edges outside the batch:**

- each held leaf → α;
- β → each held leaf (other than 927);
- 927 → β;
- 772 → β.

**DAG:** {926, 774} → α → {held leaves} → β → {γ, 927}; {library-side leaves} → β.

**G7 (advisory; solar_challenge has no design-invariants registry).**

- one-fact-one-home: the version gets one test across its five spellings (I2), and the release has one section.
- holds-owned-and-bounded: every held leaf has an owner (S29) and a window bounded by α and β.
- no-silent-fail-soft: the inventory fails closed on a `breaking` entry the section does not name (R5).

No hits are unresolved.

## 9. Out of scope

- **What each held leaf changes.** Each stream owns its retirement and its line. S29 orders and folds them.
- **927's snapshot, `UNRELEASED` table and doc step.** S23 owns them, and S29 adds only the edge.
- **The platform's code changes.** They belong to its project's task, which γ files.
- **Releasing 1.0.0.** That is a stability promise this program does not make (§10 Q2).
- **Rendering the 0.5.0 tree with today's helper** to audit the inventory against the tag. The S23 PRD set it out of scope too. The pre-window changes rely on their Unreleased paragraphs.
- **Changing the lock's `breaking` trailer** to name the window. The held leaves' tasks already say S29 bumps, and editing one message three times (α, β, 927) would be churn.

## 10. Open questions

1. **Task 224 (urgent).** It is `pending` with no dependency, so it can be dispatched now and cut a half-program release. **Default:** the lead sets 224 `deferred` now. At decompose it is re-scoped in place as β (decision 9). The alternative is to cancel it with `x_superseded_by` β and copy its notes into β.
2. **Version.** **Default:** 0.6.0 (decision 2). The alternative is 1.0.0.
3. **What β waits for.** **Default:** the held leaves plus every open library-side program leaf (decision 3; 31 extra edges at the store read). The alternative is the held leaves only, accepting a second re-pin for the figures that move.
4. **Tag and re-pin as a human gate γ.** **Default:** yes (decision 8). The alternative is that the decompose session files the platform task now with `external_deps` on γ, deferred until the tag exists.
5. **β joins gate 772 at medium priority.** **Default:** yes, recorded as `x_lead_ruling: "D4"`, an exception to "high/critical join the gate" like L37's. The alternative is no edge, so the next run may review a mid-window tree.
6. **Contradictions found** (reported, not resolved here):
   - (a) Cross-reference "S29 (from S7, S8, S4)" says "no S4 lines (S4 exports no checker)". "S29 (from S4, S21, S24, S28)" says the release section includes "S4 (public checker names)". The addendum says "S4 lands in-leaf, no S4 line". **Default:** S29 writes no S4 entry of its own, and β folds S4's in-leaf Unreleased paragraphs (S4 PRD: every tightening leaf writes one).
   - (b) The brief's goal says "fifteen filed leaves across twelve streams". The store has 15 retirement leaves across 14 streams (S8 has two), plus 927 (S23), which is 16 across 15. S25 ζ will make 17 across 16.
   - (c) S14's PRD spells 826's `x_seam_wait.contract` as "one coordinated frozen-surface bump (D4)". The store has "the surface bump release window". **Default:** the store's value holds. No action.
   - (d) The addendum asks for held leaves to depend on the bump leaf and for the bump leaf to depend on them. Decision 1 resolves this with α and β.
   - (e) 950's title still says "unless S6 claims it". S6 did not claim it, so 950 retires `tariff_config`. **Default:** the lead amends 950's title at release.

## 11. Decompose-time actions (in order)

1. Run contract §8 step 1: S29 has no keys, so this is a search for twins. 224 is the only one found (`search_tasks` "release version bump re-pin"; titles grep). Re-read 224's status and claimant.
2. File α (`submit_task`, `planning_mode=True`). File γ the same way (`task_kind: deterministic`).
3. Re-scope 224 as β with `update_task`: title, description, details (keep its notes), and metadata (`x_finding_key: []`, `x_finding_run`, `source: review-all`, `x_lead_ruling: "D4"`, `prd_path`, `files`). Leave it `deferred`.
4. `add_dependency`: α → 926; α → 774.
5. `add_dependency`: each of 784, 790, 804, 826, 827, 843, 867, 892, 901, 905, 912, 939, 941, 950, 963 and S25 ζ → α.
6. `add_dependency`: β (224) → α; β → 926; β → each of the 16 ids in step 5.
7. `add_dependency`: β → each library-side leaf of decision 3, recomputed from the store.
8. `add_dependency`: 927 → β; γ → β; 772 → β (if §10 Q5 holds).
9. `update_task` on each held leaf and 927: replace `x_seam_wait` with `x_seam_released = {stream, contract, released_by: "S29 decompose commit_planning <date>, depends on α"}`.
10. `commit_planning` with α, β (224) and γ. Then `commit_planning` with the 17 held ids (16 plus 927).

## Gate record

- **G1:**
  - α's consumers are the held leaves (W1) and library code catching the error;
  - β's are the platform re-pin, 927 and the next surface edit;
  - γ's is the platform project.
- **G2:**
  - α's R1 and R2 are RED today;
  - β's R3 is RED today, and R4 to R6 and R8 run in the per-task verify or as a grep;
  - γ's R7 is a human check by design: the tag cannot be cut by a leaf.
- **G3:**
  - These were measured on main `beb1d91`: version spellings (pyproject, `__init__`, `uv.lock`, the worked example, the model doc); 25 + 7 Unreleased paragraphs; the tag on the merge commit (`03af26e`); `test_pyproject_version_matches_dunder`; `ConfigurationError` absent from `__init__.py`.
  - The held leaves come from the store, and the platform sites from `d521265`.
  - The inventory's classifier is 926's (upstream of α and β).
- **G4:** §7. S29 owns FROZEN_SURFACE after S23 only for the release moment. The tables stay in S23's module, and S23 owns their rules.
- **G5:** B + H. There is a contract for the window and the release section, and a boundary-test table.
- **G6:**
  - Every count states what it counted and where.
  - No signal depends on a leaf downstream of it.
  - The one RED-by-construction premise (the section is absent today) is checked.
- **META:** five questions remain for the lead (§10). Under their defaults, the decomposed batch is coherent and needs no further oversight. Q1 is time-sensitive.
