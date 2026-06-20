# PRD — `solar_challenge` domain-library extraction (P0)

- **Source:** `docs/analysis-and-context/2026-06-19-digital-layer-spec-and-implementation-plan.md`
  §2.1 (domain-library extraction), §3 (seam table), §5 (PRD roster — **P0**), decision **D2** (hybrid
  codebase: the ops platform *consumes* this repo's physics/finance/dispatch as a library, never
  re-implements it). Authored 2026-06-20.
- **Status:** active · authored 2026-06-20 · **P0 — the foundation gate** (serial; Wave 0). The
  `solar-challenge-platform` repo's foundational PRDs (P1+) are blocked on this seam.
- **Owner seam (G4):** **this PRD OWNS the `solar_challenge` public-API seam.** It owns (a) the **frozen
  top-level public surface** (`solar_challenge.__all__` + a lazy, typed re-export `__init__`), (b) the
  **buildable, `py.typed` wheel**, (c) the **documented dependency mechanism** an external repo uses to
  consume it (git+file pinned-to-tag), and (d) the **release/tag convention** that makes "freeze the API"
  literal. The single producer; P1+ are pure consumers.
- **Approach:** **B + H** (a written contract + two-way boundary tests). High-stakes: a frozen seam that
  ≥6 downstream PRDs import for the project's life, across a repo boundary, where the dependency
  mechanism is load-bearing for *orchestrator correctness* (see §8).
- **Consumes (do not re-touch — behaviour frozen):** every named domain module already implements the
  logic — `battery`, `flow`, `dispatch`, `finance`, `tariff`, `seg`, `gridservices`, `community`, `pv`,
  `weather`, `load`, `location` (verified in code 2026-06-20; §6). This PRD is **packaging + a stable
  public API only — NO behavioural change.** The existing simulator (CLI, web, full test suite) stays
  green and `uv run --extra dev --extra web mypy src/solar_challenge` stays clean throughout.
- **Produces (G1 consumers named):** the importable `solar_challenge` public API that
  **`solar-challenge-platform`** (PRDs **P1** skeleton/identity, **P3** device-sim → `battery`/`flow`,
  **P6** optimiser → `dispatch.decide_action`/`battery`, **P7** billing → `finance` bill engine)
  consumes; the **consumption recipe doc** that the platform's `pyproject.toml` follows; and an
  **external-consumer boundary test** + **cross-repo platform smoke** that prove the seam end-to-end.

---

## 1. Goal

Extract this simulator's pure domain logic into a standalone, **pip/uv-installable `solar_challenge`
package with a stable, documented, FROZEN public API**, so the new operational platform
(`solar-challenge-platform`) can `import solar_challenge` and call the physics / finance / dispatch
engines **as a library**, rather than re-implementing them. This is the **reuse dividend** of decision
D2 — the platform never re-derives battery physics, the energy-dispatch decision, or the cost-recovery
bill formula.

**User-observable outcome (G2):** in a **fresh git worktree of `solar-challenge-platform`**,
`uv run --extra dev python -c "import solar_challenge as s; s.householder_bill; s.BatteryConfig; …"`
resolves and **every symbol in `solar_challenge.__all__` is importable and callable**, the dependency
resolving from `pyproject.toml` + the committed `uv.lock` with **no committed venv** — while this
simulator's own suite (`uv run --extra dev --extra web pytest -m 'not slow and not e2e'`) and
`mypy src/solar_challenge` stay **green**. The freeze is machine-enforced: a surface-lock test fails if
the public set drifts without a deliberate, additive release.

## 2. Background — what exists, verified in code 2026-06-20 (do not rebuild)

- **Every named domain symbol already exists and imports cleanly under `uv run`** (§6 table). The work
  is *exposing* a curated surface, not writing physics/finance.
- **The package already builds a wheel** (`uv build --wheel` succeeds; src-layout setuptools is wired,
  `pyproject.toml`). Two packaging gaps: **(a) the wheel ships no `py.typed`** (so a downstream
  `mypy --strict` cannot see the lib's inline types), and **(b) `__init__.py` exposes only the CLI**
  (`get_cli_app()`) — **zero domain symbols are re-exported**. Both are P0 deliverables.
- **The domain modules are import-clean and orchestration-decoupled** — `battery`, `flow`, `dispatch`,
  `finance`, `tariff`, `seg`, `gridservices`, `community` do **not** runtime-import `config`/`home`/
  `fleet`/`cli`/`web` (finance/battery/community use `TYPE_CHECKING`-only refs; `gridservices` lazy-
  imports `ConfigurationError` only inside `__post_init__`). **Two exceptions matter (below).**
- **Exception 1 — `FinanceConfig` lives in `config.py:485`,** not `finance.py`. `config.py` is the
  ~1500-line scenario/sweep parser, explicitly **not** a "pure domain" module, and importing it pulls
  `pvlib` transitively (~1 s). Per design decision (§4) `FinanceConfig` is **relocated into
  `finance.py`** with a back-compat re-export from `config.py`.
- **Exception 2 — the public functions' *signatures* reach into the orchestration layer.**
  `householder_bill(summary: SummaryStatistics, …)` takes `SummaryStatistics` (**home.py:127**);
  `solve_cost_recovery_rate(scenario: ScenarioConfig, …, simulate: Callable[[FleetConfig, …], FleetResults])`
  takes `ScenarioConfig` (**config.py:624**) and references `FleetConfig`/`FleetResults`
  (**fleet.py:26/133**). **Closure rule:** a function in the frozen surface ⇒ its parameter and return
  types must be in the frozen surface, or the function is not actually callable. So the surface
  **necessarily** includes these signature types even though they originate in modules the §2.1 framing
  excludes. The "pure 11 modules" boundary is therefore softer than it reads — this is honoured by
  *exposing the types as they are*, not by redesigning the functions to take plain data (that would be a
  behavioural change → out of scope; §11).
- **A name collision** — `dispatch.TariffPeriod` (an `Enum`) is **not** `tariff.TariffPeriod` (a frozen
  dataclass). A flat top-level namespace must disambiguate; resolved by aliasing the dispatch enum to
  `DispatchTariffPeriod` at the surface (the underlying `dispatch.TariffPeriod` symbol is **untouched** —
  alias only, no behavioural change).
- **`pv`/`weather` import `pvlib` at module load** (heavy, not network); `weather.get_tmy_data` does
  network I/O **at call time** only; `load` treats `richardsonpy` as an optional import. ⇒ an *eager*
  top-level re-export would drag `pvlib` into every `import solar_challenge`; the surface uses **lazy
  (PEP 562) loading** so `import solar_challenge` stays cheap (§3.2).

## 3. Sketch of approach

Four moving parts, all additive/packaging: **(3.1)** define the frozen surface; **(3.2)** a lazy, typed
re-export `__init__`; **(3.3)** packaging hardening (`py.typed`) + `FinanceConfig` relocation;
**(3.4)** the dependency mechanism + consumption doc + tag convention; **(3.5)** the two-way boundary
tests (in-repo external-install proof + cross-repo platform smoke).

### 3.1 The frozen public surface (the contract — B)

`solar_challenge.__all__`, grouped by origin module. This **is** the seam P1+ import; it is the
artifact a surface-lock test pins (§3.5). **Closure types** (§2, exception 2) are included so the
mandated functions are genuinely callable.

```python
__all__ = [
    # --- finance / bill engine (finance.py; FinanceConfig relocated here, §3.3) ---
    "householder_bill", "solve_cost_recovery_rate", "bill_distribution",
    "BillBreakdown", "BillDistribution", "CostRecoverySolution", "FinanceConfig",
    # --- signature-closure types required to CALL the bill engine (origin module noted) ---
    "SummaryStatistics",   # home.py   — arg to householder_bill
    "ScenarioConfig",      # config.py — arg to solve_cost_recovery_rate
    "FleetConfig", "FleetResults",  # fleet.py — in solve_cost_recovery_rate's `simulate` signature
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy", "DispatchDecision", "GridChargeContext", "compute_grid_charge_power_kw",
    "SelfConsumptionStrategy", "TOUOptimizedStrategy", "PeakShavingStrategy",
    "DispatchTariffPeriod",          # alias for dispatch.TariffPeriod (collision-renamed)
    # --- battery (battery.py) ---
    "Battery", "BatteryConfig", "compute_soh",
    # --- flow (flow.py) ---
    "EnergyFlowResult", "simulate_timestep", "simulate_timestep_tou", "validate_energy_balance",
    "calculate_self_consumption", "calculate_excess_pv", "calculate_shortfall",
    # --- tariff (tariff.py) ---
    "TariffConfig", "TariffPeriod", "calculate_bill", "FlatRateTariff",
    # --- seg (seg.py) ---
    "SEGTariff", "resolve_seg_tariff", "calculate_seg_revenue", "SEG_PRESETS",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand", "GridServicesRateBands", "resolve_grid_services_rate_band",
    "EventWindow", "GridServicesEventsConfig", "GridServicesAtEvents",
    "compute_fleet_spare_capacity_kw", "compute_grid_services_at_events",
    "GRID_SERVICES_RATE_BANDS", "DEFAULT_EVENT_WINDOWS",
    # --- community (community.py) ---
    "CommunityConfig", "CommunityBillingConfig", "CommunityResults",
    "simulate_community", "validate_community_balance",
    # --- pv (pv.py) ---
    "PVConfig", "simulate_pv_output", "create_model_chain", "create_pv_system",
    "apply_degradation", "calculate_degradation_factor", "interpolate_to_minute_resolution",
    # --- weather (weather.py) ---
    "get_tmy_data", "WeatherCache", "get_weather_cache", "set_weather_cache",
    # --- load (load.py) ---
    "LoadConfig", "OFGEM_TDCV_BY_OCCUPANTS", "ELEXON_PROFILE_CLASS_1", "SEASONAL_FACTORS",
    # --- location (location.py) — required by pv/weather call signatures ---
    "Location",
]
```

**Freeze policy (the contract semantics):** **adding** a name to `__all__` is an *additive,
backward-compatible* change shipped as a new tagged release; **removing or renaming** a name is a
**breaking** change requiring a major version bump + coordinated consumer update. Submodule imports
(`from solar_challenge.finance import …`) always work and are **not** governed by the freeze — `__all__`
is the *curated, supported* surface, not the only importable one.

### 3.2 Lazy, typed re-export `__init__` (PEP 562)

`__init__.py` exposes the surface **without** importing any submodule at package-import time:

```python
_SYMBOL_MODULE: dict[str, str] = { "householder_bill": "finance", "BatteryConfig": "battery", … }

def __getattr__(name: str):                 # PEP 562 — resolved on first attribute access
    mod = _SYMBOL_MODULE.get(name)
    if mod is None: raise AttributeError(f"module 'solar_challenge' has no attribute {name!r}")
    obj = getattr(importlib.import_module(f"solar_challenge.{mod}"), _SOURCE_NAME.get(name, name))
    globals()[name] = obj                   # cache
    return obj

def __dir__() -> list[str]: return sorted(__all__)

if TYPE_CHECKING:                           # static analysers see REAL types, runtime stays lazy
    from solar_challenge.finance import householder_bill, BillBreakdown, FinanceConfig, …
    from solar_challenge.dispatch import TariffPeriod as DispatchTariffPeriod
    from solar_challenge.tariff import TariffPeriod
    …
```

`_SOURCE_NAME` maps an exported alias to its underlying symbol (the one entry that needs it:
`DispatchTariffPeriod → dispatch.TariffPeriod`). The `TYPE_CHECKING` block is what keeps **consumers'**
`mypy --strict` precise (not `Any`) while `import solar_challenge` triggers **no** `pvlib` import — both
asserted in §9. Keeps the lazy `get_cli_app()` already present; the CLI stays out of `__all__`.

### 3.3 Packaging hardening + `FinanceConfig` relocation

- **`py.typed`:** add `src/solar_challenge/py.typed` (empty marker) and ship it via
  `[tool.setuptools.package-data] solar_challenge = ["py.typed"]`, so the built wheel marks the package
  typed and a downstream `mypy --strict` reads its inline annotations. (Today's wheel omits it — §2.)
- **`FinanceConfig` → `finance.py`** (design decision §4): move the class *definition* from
  `config.py:485` into `finance.py`; add `from solar_challenge.finance import FinanceConfig` in
  `config.py` so `config.FinanceConfig` and `_parse_finance_config` keep working unchanged. **Hazard:
  circular import** — `finance.py`'s `config` references are `TYPE_CHECKING`-only (no runtime cycle),
  and `config.py` runtime-importing `finance.py` is acyclic *iff* `finance.py` does not runtime-import
  `config.py`; the relocation task **asserts both import orders succeed** + full suite + mypy green
  (§9, §10·T2). Behaviour-preserving: same class object, relocated.
- **cli/ and web/ stay in the wheel** (the sim's own `[project.scripts]` entry point needs `cli`); they
  are simply **absent from `__all__`** — shipped, undocumented, unfrozen. Not the public surface.

### 3.4 Dependency mechanism — git+file pinned to a tag (consumer recipe + freeze-by-release)

**Decision (§4):** the platform depends on the lib via a **git+file URL pinned to a release tag**, with
a committed `uv.lock`:

```toml
# solar-challenge-platform/pyproject.toml
dependencies = ["solar-challenge @ git+file:///home/leo/src/my-solar-challenge@<release-tag>"]
```

**Why this and not an editable path source** (the rejected alternative): an editable absolute path
resolves the sim repo's **live main-checkout working tree**, shared by every platform worktree. A
merge to the sim's `main` then changes the bytes **underneath all in-flight platform worktrees at once**
— a green platform task can go red with no platform change, and two concurrent tasks can see *different*
lib code. That violates the orchestrator's correctness assumption (a task's inputs are stable for its
life) and is a flaky-verify generator. **git+file pinned insulates the platform:** each worktree builds
the lib wheel from the immutable pinned commit recorded in `uv.lock`; a sim `main` merge does **not**
change what the platform resolves. The platform adopts lib changes **deliberately** — bump the tag +
`uv lock` + commit — which lands as a *platform commit* through the platform's own verify/merge-queue,
so breakage is caught **before** it reaches other worktrees. **"Freeze the API" is literal: P0 cuts the
tag; the platform pins to it.**

Deliverable **`docs/domain-library-consumption.md`** documents, for the consumer: the exact
`dependencies` line; the `uv lock` workflow + how to bump the pin to a newer tag; the **tag/release
convention**; the frozen-surface listing (mirrors `__all__`); and the consumption **caveats** —
`import solar_challenge` is cheap but `pv`/`weather` pull `pvlib` on first access, and
`weather.get_tmy_data` does **network I/O** (consumers inject/mock it).

### 3.5 Two-way boundary proof (H) — and the platform wiring I execute at P0 close

- **In-repo, worktree-safe (orchestrator task T5):** an **external-consumer boundary test** builds the
  wheel and installs it into an **isolated, project-free environment**
  (`uv run --no-project --isolated --with <built-wheel> python …`, deps resolved from the uv cache),
  then imports **every** name in `solar_challenge.__all__` and asserts each is callable/constructible.
  This proves G2's "an external project can install + import + call every public symbol" **without** the
  platform repo, in this repo's own worktree.
- **Surface-lock / freeze test (orchestrator task T4):** asserts `solar_challenge.__all__` equals a
  committed frozen constant and that every name resolves to the expected kind (class / function /
  constant), and that `import solar_challenge` imports **no** `pvlib`. Drift fails CI → the freeze is
  enforced, not aspirational.
- **Cross-repo platform wiring (close-out step — *I* execute it, non-orchestrator; design decision §4,
  Q2):** because the frozen surface does not exist until P0 lands, the platform cannot pin to the API
  tag earlier. At P0 close I cut the release tag in this repo, then in `solar-challenge-platform` add
  the §3.4 pinned dependency, `uv lock`, commit, and add a **platform-side smoke test** importing the
  public API. This is an **in-scope deliverable of this P0 effort**, executed by me (a P0 task in *this*
  repo's worktrees cannot commit to the *platform* repo), **not** deferred to P1. It is the live
  cross-repo G1 proof.

## 4. Resolved design decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Dependency mechanism | **git+file pinned to a release tag** + committed `uv.lock` | Insulates platform worktrees from sim `main` merges (editable path would deploy breaking changes underneath in-flight worktrees — flaky verify); upgrades are explicit, reviewed platform commits; the tag *is* the API freeze. *(Leo, 2026-06-20 — confirmed after weighing the worktree-coupling hazard.)* |
| Public surface shape | **Curated, frozen top-level `__all__` with PEP-562 lazy loading** + a `TYPE_CHECKING` eager block for precise downstream types | An explicit `__all__` is the enforceable contract; lazy keeps `import solar_challenge` free of `pvlib`; typed block keeps consumer mypy precise. *(Leo, 2026-06-20.)* |
| `TariffPeriod` collision | Export `tariff.TariffPeriod` under its name; alias `dispatch.TariffPeriod` → **`DispatchTariffPeriod`** | Flat namespace must disambiguate; an alias touches no module internals (no behavioural change). |
| `FinanceConfig` location | **Relocate into `finance.py`** + back-compat re-export from `config.py` | Puts the bill-engine config in its domain module (clean seam); the public API no longer re-exports from the impure `config.py`. *(Leo, 2026-06-20 — chose seam-cleanliness over minimal-touch.)* |
| Signature-closure types | **Include** `SummaryStatistics`/`ScenarioConfig`/`FleetConfig`/`FleetResults` in the surface as-is | A frozen *callable* API must export its parameter/return types; redesigning the functions to take plain data is a behavioural change (out of scope, §11). |
| Consumer wiring ownership | **P0 self-proves in-repo (T5) AND I wire the platform at P0 close** (non-orchestrator) | Orchestrator tasks can't cross repos; the in-repo install test proves the signal, the close-out wiring proves it live cross-repo before P1. *(Leo, 2026-06-20.)* |
| Behavioural change | **None.** Packaging + re-export + alias + a behaviour-preserving relocation only | Hard constraint; the existing suite + `mypy` gate every task. |
| cli/ & web/ in the public API | **Excluded from `__all__`** (still shipped in the wheel) | §2.1 scope; the sim's own entry point still needs `cli` installed. |

## 5. Pre-conditions for activating

- **All domain modules present + import-clean** (§6 — verified 2026-06-20). No domain logic is written
  here.
- **`uv` available + both repos use `uv run` for verify** (sim `orchestrator.yaml`:
  `uv run --extra dev --extra web …`; platform `orchestrator.yaml`: `uv run --extra dev …`). Verified.
- **`solar-challenge-platform` repo exists, dark-factory-onboarded, `dependencies = []`** awaiting this
  seam (verified: `pyproject.toml` comment "becomes a dependency here once it is pip-installable").
- No new third-party runtime dependency is introduced.

## 6. Substrate verification (G3)

All verified in code 2026-06-20 (`uv run` import + `uv build --wheel` + grep).

| Assumed capability | Evidence |
|---|---|
| `householder_bill`, `solve_cost_recovery_rate`, `BillBreakdown`, `bill_distribution`, `BillDistribution`, `CostRecoverySolution` | `finance.py:393, 1720, 38, 636, 114, 191` — exist |
| `FinanceConfig` (frozen dataclass) — **relocation source** | `config.py:485` (→ moves to `finance.py`, §3.3) |
| Signature-closure types reachable: `SummaryStatistics` / `ScenarioConfig` / `FleetConfig` / `FleetResults` | `home.py:127` / `config.py:624` / `fleet.py:26` / `fleet.py:133` — exist |
| `DispatchStrategy.decide_action`, `GridChargeContext`, `DispatchDecision` + `SelfConsumption/TOUOptimized/PeakShaving` strategies, `compute_grid_charge_power_kw` | `dispatch.py:195, 61, 16, …` — exist |
| `TariffPeriod` collision (Enum vs dataclass) confirmed distinct | `dispatch.py` Enum ≠ `tariff.py` dataclass — verified `is` False under `uv run` |
| `Battery`, `BatteryConfig`, `compute_soh` (free function) | `battery.py:203, 82, 40` — exist |
| `flow` / `tariff` / `seg` / `gridservices` / `community` / `pv` / `weather` / `load` / `location` public symbols (§3.1 lists) | enumerated against source 2026-06-20 — all exist |
| Domain modules do **not** runtime-import `config`/`home`/`fleet`/`cli`/`web` (so lazy re-export is clean) | TYPE_CHECKING-only in finance/battery/community; `gridservices` lazy-imports `ConfigurationError` in `__post_init__` only |
| Package **builds a wheel** today | `uv build --wheel` succeeds (src-layout setuptools wired) |
| Wheel **lacks `py.typed`** (gap to fix) | wheel inspection 2026-06-20 — no `py.typed`; `__init__.py` exports only `get_cli_app` |
| `import solar_challenge.config` already pulls `pvlib` transitively (~1 s) — motivates lazy surface | timed under `uv run` 2026-06-20 |
| PEP-562 `__getattr__` / `__dir__` supported (Python ≥3.10) and `uv run --no-project --isolated --with <wheel>` supported (uv 0.11.6) | language/tool versions confirmed |
| Platform worktree dir `.worktrees/<branch>` ⇒ relative path dep breaks; absolute git+file resolves | platform `orchestrator.yaml` `git.worktree_dir: .worktrees` |

**Novel substrate introduced here (each consumed by a named task / the platform / the doc):** the
`__all__` frozen surface; the lazy/typed `__init__`; the `DispatchTariffPeriod` alias; `py.typed` +
package-data wiring; the relocated `FinanceConfig`; the surface-lock test; the external-install
boundary test; `docs/domain-library-consumption.md`; the release tag. **G3 verdict: PASS.**

## 7. Cross-PRD relationship (G4)

| Other PRD / repo | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| **`solar-challenge-platform` P1** (skeleton + identity) | **consumed-by** | first to add the git+file pinned dep + `uv.lock`; I wire it at P0 close (§3.5) | **this PRD owns** the producer + recipe; the platform owns *when* to bump the pin | blocked on P0 |
| **platform P3** (telemetry + device sim) | **consumed-by** | imports `battery`, `flow` (real-time physics for the Victron/Cerbo emulator) | this PRD owns the surface | downstream |
| **platform P6** (fleet optimiser) | **consumed-by** | imports `DispatchStrategy.decide_action`, `Battery`, `BatteryConfig`, `GridChargeContext` as the physics core | this PRD owns the surface | downstream |
| **platform P7** (billing engine) | **consumed-by** | imports the bill engine (`householder_bill`, `solve_cost_recovery_rate`, `BillBreakdown`, `FinanceConfig`, + closure types) on real billing cycles | this PRD owns the surface; P7 may later request thin plain-data entry points (a *future* PRD, §11) | downstream |
| `config.py` / `home.py` / `fleet.py` (this repo) | **co-tenant** | the surface re-exports their public types (`FinanceConfig` relocated; `ScenarioConfig`/`SummaryStatistics`/`FleetConfig`/`FleetResults` re-exported as-is) | this PRD owns only the *re-export*; the types' definitions are unchanged (except `FinanceConfig`'s file move) | additive |
| this repo's CLI/web/test suite | **must-stay-green** | packaging-only; no behavioural change | this PRD owns the no-regression guarantee | gated each task |

**No reciprocal-ownership fight.** P0 unilaterally owns the producer side (surface, wheel, recipe, tag).
The platform owns its own consumption and the cadence of pin bumps. The boundary test + the consumption
doc are themselves named consumers, so **G1 holds independent of P1+ landing.**

## 8. G5 note — why B + H

Stakes on three axes: (1) a **FROZEN seam ≥6 downstream PRDs import for the project's life** — getting
its shape or freeze-enforcement wrong is expensive to walk back; (2) it crosses a **repo boundary**, so
the contract must be legible to a separate orchestrator target; (3) the **dependency mechanism is
load-bearing for orchestrator correctness** — the wrong choice (editable path) silently breaks in-flight
platform worktrees (§3.4). ⇒ **B** (the §3.1 `__all__` + §3.4 recipe + the freeze policy are the written
contract every consumer binds to) **+ H** (two-way boundary tests: the **surface-lock freeze test**
T4 *and* the **external-install boundary test** T5 *and* the **cross-repo platform smoke** at P0 close —
each proves a different direction of the seam). Bare B (a contract with no executable boundary proof)
would let "the package imports" pass while a symbol is silently uncallable from an *external* install,
or while the surface drifts — exactly the fake-done/integration-starvation failure modes the gate
guards.

## 9. Boundary-test sketch (H)

| # | Scenario | Preconditions | Postconditions (asserted) |
|---|---|---|---|
| H1 | **Every public symbol callable from a fresh external install** (G2 leaf) | wheel built; isolated project-free env (`uv run --no-project --isolated --with <wheel>`) | `import solar_challenge`; for **every** name in `__all__`: `getattr` resolves and is callable/constructible (classes instantiate with valid minimal args or are types; functions are callable) |
| H2 | **Surface freeze enforced** | installed package | `solar_challenge.__all__ == FROZEN_SET` (committed constant); each name resolves to the expected kind; **fails if a name is added/removed without updating the frozen constant** |
| H3 | **`import solar_challenge` is `pvlib`-free** | clean interpreter | immediately after `import solar_challenge`, `"pvlib" not in sys.modules`; after touching `solar_challenge.PVConfig`, `"pvlib" in sys.modules` (lazy proven both ways) |
| H4 | **Collision resolved** | installed package | `solar_challenge.DispatchTariffPeriod is solar_challenge.dispatch.TariffPeriod`; `solar_challenge.TariffPeriod is solar_challenge.tariff.TariffPeriod`; the two are distinct |
| H5 | **`FinanceConfig` relocation is back-compat + acyclic** | both import orders | `from solar_challenge.finance import FinanceConfig` **and** `from solar_challenge.config import FinanceConfig` resolve to the **same** class object; `python -c "import solar_challenge.config"` and `… import solar_challenge.finance"` both succeed (no circular import); full sim suite + `mypy --strict` green |
| H6 | **`py.typed` shipped + downstream sees types** | built wheel; isolated install | wheel contains `solar_challenge/py.typed`; a downstream `reveal_type(solar_challenge.householder_bill)` under `mypy --strict` is the real signature, **not** `Any` |
| H7 | **No behavioural change** | the existing suite | `uv run --extra dev --extra web pytest -m 'not slow and not e2e' --ignore=tests/e2e` green; `uv run --extra dev --extra web mypy src/solar_challenge` clean — **throughout every task** |
| H8 | **Cross-repo live proof** (close-out, I execute) | platform repo wired to the tag + `uv lock` | in a **fresh `solar-challenge-platform` worktree**, `uv run --extra dev python -c "import solar_challenge as s; s.householder_bill; s.BatteryConfig; …"` resolves; platform smoke test green; platform `mypy --strict` resolves the typed dep |

## 10. Decomposition plan

Six orchestrator tasks (this repo) + one close-out wiring step I execute (platform repo). **File-lock
discipline:** `pyproject.toml` + new `py.typed` by **T1**; `finance.py`+`config.py` (the relocation) by
**T2**; `__init__.py` by **T3**; new test modules by **T4/T5** (distinct files); `docs/` by **T6** —
all disjoint regions. The only ordering is **T2 → T3 → {T4, T5, T6}** (the surface must exist before it
can be frozen/installed/documented); **T1** is independent.

#### T1 — `py.typed` + packaging hardening
- **Modules:** `pyproject.toml`, new `src/solar_challenge/py.typed` (+ a packaging assertion in `tests/`).
- **Work:** add the empty `py.typed` marker; wire `[tool.setuptools.package-data] solar_challenge = ["py.typed"]`; confirm the built wheel ships it.
- **Signal (G2/H6):** `uv build --wheel` produces a wheel containing `solar_challenge/py.typed`; an isolated install is treated as typed by `mypy --strict` (a `reveal_type` is not `Any`). Sim suite + mypy green.
- **Classification:** independent leaf.

#### T2 — relocate `FinanceConfig` into `finance.py` (back-compat, behaviour-preserving)
- **Modules:** `finance.py`, `config.py` (+ `tests/unit/test_finance.py`/`test_config.py` for the import-compat + no-cycle assertions).
- **Work:** move the `FinanceConfig` definition from `config.py:485` to `finance.py`; add `from solar_challenge.finance import FinanceConfig` re-export in `config.py`; keep `_parse_finance_config` working unchanged.
- **Signal (G2/H5):** both `solar_challenge.finance.FinanceConfig` and `solar_challenge.config.FinanceConfig` are the **same** class; importing `config` then `finance` and vice-versa both succeed (no circular import); **full sim suite + `mypy --strict` green** (the behaviour-preservation proof).
- **Prereqs:** none. Unlocks T3.

#### T3 — frozen public surface + lazy/typed `__init__`
- **Modules:** `src/solar_challenge/__init__.py`.
- **Work:** define `__all__` (§3.1); the PEP-562 `__getattr__`/`__dir__` lazy loader + `_SYMBOL_MODULE`/`_SOURCE_NAME` maps; the `DispatchTariffPeriod` alias; the `TYPE_CHECKING` eager block for precise downstream types; retain `get_cli_app()` (CLI stays out of `__all__`). Include the signature-closure types + `Location`.
- **Signal (G2/H3/H4):** `import solar_challenge; <every name in __all__>` resolves via lazy access; `"pvlib" not in sys.modules` immediately after `import solar_challenge`; collision aliases resolve as in H4; sim suite + mypy green.
- **Prereqs:** T2 (so `FinanceConfig` is imported from `finance`).

#### T4 — surface-lock (freeze) test
- **Modules:** `tests/unit/test_public_api_surface.py`.
- **Work:** assert `solar_challenge.__all__ == FROZEN_SET` (committed constant); each name resolves to its expected kind; `import solar_challenge` imports no `pvlib`. This **is** the freeze enforcement.
- **Signal (G2/H2/H3):** the test fails if the surface drifts without a deliberate update to the frozen constant; green on the authored surface.
- **Prereqs:** T3.

#### T5 — external-consumer boundary test (the G2 leaf)
- **Modules:** `tests/integration/test_external_install.py` (marked appropriately; resolves deps from the uv cache).
- **Work:** build the wheel; install into an **isolated, project-free** env (`uv run --no-project --isolated --with <built-wheel> …`); import **every** name in `__all__`; assert each callable/constructible.
- **Signal (G2/H1/H6):** an external (project-free) install imports + can call every public symbol; the wheel is typed. **This is the user-observable "an external project can install + import + call" proof, in-repo.**
- **Prereqs:** T1 (typed wheel), T3 (surface).

#### T6 — consumption recipe doc + tag/release convention
- **Modules:** `docs/domain-library-consumption.md`.
- **Work:** document the git+file pinned `dependencies` line; the `uv lock` + pin-bump workflow; the tag/release convention; the frozen-surface listing (mirrors `__all__`); the lazy-import + `weather` network caveats.
- **Signal (G2):** the doc gives a copy-pasteable recipe that resolves in a fresh platform worktree (verified live at the close-out step); its symbol list matches `__all__`.
- **Prereqs:** T3 (documents the authored surface).

#### Close-out (I execute — non-orchestrator, after T1–T6 land + tag cut)
- Cut the release tag in this repo; in `solar-challenge-platform` add the §3.4 pinned dependency, `uv lock`, commit, add a platform-side public-API smoke test.
- **Signal (H8):** a fresh platform worktree imports + calls the public API; platform smoke + `mypy --strict` green. The live cross-repo G1 proof.

> **Decompose-time notes:** the orchestrator does not yet consume `user_observable_signal` /
> `consumer_ref` / substrate-confirmed metadata — record for a future tracking session. **No
> behavioural change:** every task keeps the sim suite + `mypy --strict` green (H7) — re-run both in each
> task's verify. The close-out wiring is **not** an orchestrator task (cross-repo); file it as a
> human/me checklist item in the hand-back, gated on T1–T6 + the tag.

## 11. Out of scope

- **`cli/` and `web/` as public API** — shipped in the wheel, excluded from `__all__` (unfrozen,
  undocumented).
- **Any behavioural change to the domain modules** — no physics/finance/dispatch logic is altered; the
  only code moves are a behaviour-preserving `FinanceConfig` relocation, a re-export `__init__`, and a
  collision *alias*.
- **Thin plain-data entry points for the bill engine** — the public functions are frozen *as they are*
  (taking `SummaryStatistics`/`ScenarioConfig`); a P7-driven request for lighter, orchestration-free
  signatures is a **future** PRD (a behavioural addition), not P0.
- **Publishing to PyPI or any real index** — git+file local consumption only this phase.
- **The platform's own modules (P1+)** — P0 builds only the producer-side seam + the close-out wiring.
- **A versioned deprecation policy beyond the freeze + additive-only rule** — the initial freeze + tag
  convention is the contract; richer SemVer/deprecation tooling is later.
- **Splitting `pv`/`weather`/`load` into a separate forecasting extra** — they stay in the one package.

## 12. Open questions (tactical — deferred, not design-blocking)

1. **Exact `__all__` membership beyond the mandated minimum.** Whether to freeze the deeper billing
   types now (`project_multi_year`, `project_economics`, `MultiYearCurve`, `YearPoint`) or add them on
   first P7 demand. Additive/non-breaking either way; decide at T3 or when P7 lands.
2. **Tag/version scheme.** `solar-challenge-vX.Y.Z` vs an `api-vN` channel; whether to bump the
   `pyproject` `version` per API release. Pick at T6.
3. **Doc↔`__all__` drift guard.** Whether T4's freeze test also asserts `docs/…-consumption.md`
   enumerates exactly `__all__`, or the doc is generated from `__all__`. Tactical.
4. **Old-import deprecation.** Keep `config.FinanceConfig` a silent re-export (default, no behavioural
   change) vs add a `DeprecationWarning`. Default silent.
5. **Boundary-test isolation method.** `uv run --no-project --isolated --with <wheel>` vs explicit
   `uv venv` + `uv pip install`; pick the most offline-robust against the uv cache at T5.
6. **Release-tag automation at close-out.** Manual `git tag` vs a small script; mechanics only, the
   deliverable (a pinned platform dep that resolves in a fresh worktree) is fixed.

## 13. G6 — premise validity of the asserted signals

- **"Every documented public symbol is callable from an external install" (H1):** every symbol is
  verified to exist in source (§6); the boundary test installs the **built wheel** into a project-free
  env and imports each — backed by a real install mechanism, not synthetic stubs. **Producible by T5.**
- **"`import solar_challenge` does not drag `pvlib`" (H3):** achievable via PEP-562 lazy loading (a
  standard pattern; Python ≥3.10); asserted by a `sys.modules` probe both before and after touching a
  pv symbol. **Producible by T3.**
- **"Surface is frozen / drift fails CI" (H2):** backed by an active rejection mechanism — the
  surface-lock test compares `__all__` to a committed constant and fails closed on any change.
  **Rejection-mechanism-backed; producible by T4.**
- **"No behavioural change / suite stays green" (H7):** the relocation is a definition move with a
  back-compat re-export; the `__init__` only re-exports; the collision fix is an alias — all
  behaviour-preserving **by construction**, and the full suite + `mypy --strict` gate every task. No
  numeric/exactness claim is asserted. **Structurally preserved.**
- **"git+file pinned insulates platform worktrees from sim merges" (§3.4):** true by uv's lockfile
  semantics — a git dependency resolves to an immutable commit recorded in `uv.lock`, so a sim `main`
  merge cannot change what a pinned worktree builds. A mechanism claim backed by how uv resolves git
  deps, not a measurement. **Valid.**
- **"`FinanceConfig` relocation is acyclic" (H5):** `finance.py`'s `config` refs are `TYPE_CHECKING`-only
  (verified §2/§6), so `config.py` runtime-importing `finance.py` introduces no runtime cycle; asserted
  by both import orders succeeding. **Producible by T2.**

**G6 verdict: PASS.**

## 14. META gate

> If this PRD is decomposed and queued without further oversight, will the architecture be complete,
> coherent, cohesive, and good?

**Yes.** Every mechanism has a named consumer — the platform's P1/P3/P6/P7, plus the in-repo boundary
test and the consumption doc (G1). Every leaf names a user-observable signal (§10 — G2). Every assumed
substrate is verified present or produced in-batch (§6 — G3). The seam has a single unambiguous owner
(this PRD) with no reciprocal fight, and the one cross-repo action an orchestrator task **cannot** do
(committing to the platform repo) is explicitly assigned to a human/me close-out step rather than left
to rot as an orphan (§7 — G4). The high-stakes frozen seam uses B + H — a written contract plus a
*two-way* boundary proof (freeze test + external-install test + cross-repo smoke), because the
dependency mechanism is load-bearing for orchestrator correctness (§8 — G5). Every asserted premise is
validated, including the rejected-mechanism analysis that flips the dependency choice to git+file pinned
(§13 — G6). The design is coherent (one frozen surface, lazy + typed, one behaviour-preserving
relocation, one insulating dependency mechanism), it keeps the sim suite + `mypy` green throughout, and
it terminates in an executable freeze and a live cross-repo import. **No open design questions remain;**
§12 items are tactical/implementation-time.
