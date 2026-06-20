# Capability manifest — `solar_challenge` domain-library extraction (P0)

Mechanizes G3 (substrate exists, **wired** not merely declared) + G6 (premise
valid) per task. Each asserted capability binds to evidence: `grep:file:line
wired` (present substrate on `main`), `producer:task-TN upstream` (queued
prerequisite + wired dep), or a mechanism/identity note. PRD:
`docs/prds/domain-library-extraction.md`. Verified against `main` at decompose
2026-06-20 (`uv run` import probes + `uv build --wheel` + grep).

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`,
`producer-absent`, `producer-downstream`, or `producer-extent-short`. Every
named domain symbol the surface re-exports exists on `main` and is grep-bound
below; the wheel builds today; the two real gaps (no `py.typed`; `__init__`
exports only the CLI) are each produced by a named in-batch task with wired
edges (T3→T2; T4/T5/T6→T3; T5→T1). No numeric/exactness premise is asserted
(packaging, not computation), so G6 branches 1–2 do not fire; branch 3
(end-to-end capability) is the load-bearing one and every required capability is
**upstream** of the leaf that asserts it (DAG-direction verified). The one
cross-repo capability an orchestrator task cannot produce (committing to the
platform repo) is **excluded from the batch** and assigned to a human close-out
step (PRD §3.5/§10) — it is not asserted by any filed task's signal, so no leaf
inherits a false premise. The behaviour-preservation guarantee (sim suite +
`mypy --strict` green) gates every task.

## T1 — `py.typed` + packaging hardening — intermediate (unlocks T5)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Package builds a wheel via setuptools src-layout | grep:`pyproject.toml:1-3,56-57` (`build-system` + `packages.find where=["src"]`); `uv build --wheel` **succeeded** 2026-06-20 | ✅ |
| `[tool.setuptools.package-data]` ships a data file in the wheel | own-task deliverable (add `py.typed` + package-data stanza); standard setuptools mechanism | ✅ |
| Today's wheel omits `py.typed` (the gap) | wheel inspection 2026-06-20 — no `py.typed` in `solar_challenge-0.1.0-py3-none-any.whl` | ✅ |
| Signal = built wheel **contains** `solar_challenge/py.typed`; an isolated install is treated as **typed** by `mypy --strict` (a `reveal_type` ≠ `Any`) | own-task: build + unzip assertion + isolated-install mypy probe — observable through the build artifact + a downstream type-check | ✅ |

## T2 — relocate `FinanceConfig` into `finance.py` (back-compat) — intermediate (unlocks T3)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `FinanceConfig` frozen dataclass (relocation source) | grep:`config.py:485` wired | ✅ |
| `finance.py` does **not** runtime-import `config.py` (so the reverse re-export is acyclic) | grep:`finance.py:27-30` — `config`/`fleet`/`home` refs are all under `if TYPE_CHECKING:` (string annotations), no runtime import | ✅ |
| `_parse_finance_config` constructs `FinanceConfig` (must keep working post-move) | grep:`config.py` `_parse_finance_config` (the W2 parser) wired; back-compat re-export `from solar_challenge.finance import FinanceConfig` keeps the symbol resolvable from `config` | ✅ |
| No circular import at module load (the relocation premise) | **structural**: `finance.py` TYPE_CHECKING-only config refs ⇒ `config.py` runtime-importing `finance.py` introduces no runtime cycle; asserted by both import orders succeeding (H5) | ✅ |
| Signal = `solar_challenge.finance.FinanceConfig is solar_challenge.config.FinanceConfig`; both import orders succeed; **full sim suite + `mypy --strict` green** | own-task unit test + the orchestrator verify suite (the behaviour-preservation proof) | ✅ |

## T3 — frozen public surface + lazy/typed `__init__` — intermediate (unlocks T4, T5, T6)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Every re-exported domain symbol exists on `main` | grep: finance `finance.py:38,114,191,393,636,1720`; battery `battery.py:40,82,203`; dispatch `dispatch.py:16,61,114,195,329`(+ `SelfConsumption/TOUOptimized/PeakShaving` strategies); flow `flow.py` (`EnergyFlowResult`, `simulate_timestep`, `simulate_timestep_tou`, `validate_energy_balance`, `calculate_self_consumption/excess_pv/shortfall`); tariff `tariff.py:15,100`(+`calculate_bill`,`FlatRateTariff`); seg `seg.py:7,31,41,68`; gridservices `gridservices.py:60,107,197,308,472`(+ resolvers/computers/constants); community `community.py:38,61,105,213,391`; pv `pv.py:18`(+ sim/builders/degradation/interp); weather `weather.py:19,170,178,184`; load `load.py:33,43,110,124`; location `location.py:9` — all wired | ✅ |
| `FinanceConfig` re-exported from `finance` (not `config`) | **producer:task-T2 upstream** — dep T3→T2 wired | ✅ |
| Signature-closure types reachable for a callable API | grep:`home.py:127` (`SummaryStatistics`), `config.py:624` (`ScenarioConfig`), `fleet.py:26` (`FleetConfig`), `fleet.py:133` (`FleetResults`) wired | ✅ |
| `TariffPeriod` collision is real ⇒ alias needed | grep:`dispatch.py:329` (Enum) ≠ `tariff.py:15` (frozen dataclass); confirmed distinct objects under `uv run` 2026-06-20 — alias `dispatch.TariffPeriod`→`DispatchTariffPeriod` (no module internal touched) | ✅ |
| PEP-562 `__getattr__`/`__dir__` lazy loading supported | Python `>=3.10,<3.13` (grep:`pyproject.toml:10`) — PEP 562 available | ✅ |
| Signal = `import solar_challenge`; every `__all__` name resolves via lazy access; `"pvlib" not in sys.modules` right after import; alias identities hold (H3/H4); sim suite + mypy green | own-task unit test — observable through the package's public import path | ✅ |

## T4 — surface-lock (freeze) test — leaf · prereq T3

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `solar_challenge.__all__` is the frozen surface to pin | **producer:task-T3 upstream** — dep T4→T3 wired | ✅ |
| Lazy `__getattr__` resolves every name to the expected kind | **producer:task-T3 upstream** | ✅ |
| `import solar_challenge` is `pvlib`-free (lazy proven) | **producer:task-T3** (mechanism); T4 observes via a `sys.modules` probe before/after touching a pv symbol (H3) | ✅ |
| Rejection mechanism: surface drift **fails** the test | own-task: assert `__all__ == FROZEN_SET` (committed constant) + per-name kind check — an **active** rejection that fires on any add/remove (G6 branch-4 backed) | ✅ |
| Signal = test fails on surface drift without a deliberate frozen-constant update; green on the authored surface (H2) | own-task CI test against the **real** public surface (not synthetic input) | ✅ |

## T5 — external-consumer boundary test (the G2 leaf) — leaf · prereqs T1, T3

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The package builds + installs as a wheel into an isolated, project-free env | grep:`pyproject.toml` build-system; `uv build --wheel` succeeded 2026-06-20; `uv run --no-project --isolated --with <wheel>` supported (uv 0.11.6) | ✅ |
| The typed wheel (so the external install is type-complete) | **producer:task-T1 upstream** — dep T5→T1 wired | ✅ |
| The frozen surface (every name to import + call) | **producer:task-T3 upstream** — dep T5→T3 wired | ✅ |
| Each `__all__` symbol exists + is callable/constructible | every symbol grep-bound under T3 above; `FinanceConfig` via **producer:task-T2** (transitive through T3); closure types grep:`home.py:127`,`config.py:624`,`fleet.py:26/133` wired | ✅ |
| End-to-end (G6 branch 3): all required capabilities are **upstream** of T5 | DAG: T5 depends_on T1, T3 (and transitively T2 via T3) — **no producer-downstream** | ✅ |
| Signal = a project-free wheel install imports + calls **every** public symbol (H1); the wheel is typed (H6) | own-task integration test — the user-observable "an external project can install + import + call" proof, in-repo | ✅ |

> **Scope note (T5):** asserts importability/callability from an *isolated wheel
> install in this repo* — **not** resolution from the platform repo (that is the
> non-orchestrator close-out step H8, gated on the release tag). T5's signal
> claims nothing its own dependency set cannot produce.

## T6 — consumption recipe doc + consistency check — leaf · prereq T3

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `solar_challenge.__all__` to enumerate + assert against | **producer:task-T3 upstream** — dep T6→T3 wired | ✅ |
| The git+file pinned dependency **recipe** (a documented string + workflow) | design decision (PRD §3.4/§4); a documented recipe, not a runtime capability T6 invokes — its live resolution is the close-out step (H8), **out of T6's asserted scope** | ✅ |
| Rejection mechanism: doc↔`__all__` drift **fails** | own-task: a check asserting the doc's frozen-surface listing == `solar_challenge.__all__` and the doc contains the exact `git+file` dependency line (active rejection on drift) | ✅ |
| Signal = `docs/domain-library-consumption.md` exists with the exact recipe + tag convention; its surface listing matches `__all__` (CI-checked) | own-task doc + consistency assertion — observable via CI, **not docs-only** | ✅ |

> **Decompose note:** the **platform-repo wiring + cross-repo smoke (H8)** is a
> human/me **close-out step**, NOT a filed orchestrator task — a P0 task in this
> repo's worktrees cannot commit to `solar-challenge-platform`. It is gated on
> T1–T6 landing + the release tag, and surfaced in the decompose hand-back as a
> checklist item (PRD §3.5/§10). The orchestrator does not yet consume
> `user_observable_signal` / `consumer_ref` / the substrate-confirmed flag —
> recorded for a future tracking session.
