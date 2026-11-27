# Capability manifest — Surface version bump (review-all S29)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/surface-version-bump.md`. Each capability a leaf's signal asserts is bound to evidence. Machine-readable twin: `docs/prds/surface-version-bump.capability-manifest.yaml`.

**Code anchors** verified against main `beb1d9103ad8` (2026-10-18). The task store was read at 2026-10-18T09:14:46Z. The platform was read at `solar-challenge-platform` `d521265`. Cite symbols; re-locate lines at implementation time.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Producers outside the batch are upstream of the leaves that read them:

| Task | Stream and label | Status |
|---|---|---|
| 774 | S1 β (`ConfigurationError` subclasses `ValueError`) | pending |
| 926 | S23 ζ (drift labelled additive or breaking) | pending |
| 784, 790, 804, 826, 827, 843, 867, 892, 901, 905, 912, 939, 941, 950, 963 | held retirements of S10, S2, S9, S14, S15, S11, S28, S16, S12, S3, S27, S8 (two), S5, S6 | deferred, held for S29 |
| S25 ζ | held retirement of `SummaryStatistics.seg_revenue_gbp` | not yet filed |
| 224 | the pre-existing release task, re-scoped as β | pending (to be parked, §10 Q1) |

## α — Open the 0.6.0 release window; `ConfigurationError` in `__all__` (intermediate, unlocks the held leaves)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| R2 RED today: the window section is absent | `git grep '^### solar-challenge-v0\.6\.0' main -- docs/domain-library-consumption.md` exits 1 | PASS (RED observed) |
| The held leaves expect a section S29 opens | the descriptions of 790, 827, 905 and 912 say "in the release section S29 opens"; 826 and 843 hand their line to "S29's section" | PASS |
| R1 RED today: `ConfigurationError` is not in `__all__` | `git grep '"ConfigurationError"' main -- src/solar_challenge/__init__.py tests/unit/test_public_api_surface.py` exits 1; `errors.ConfigurationError` exists (task 773, done) | PASS (RED observed) |
| The form α freezes has the ruled base | `errors.ConfigurationError(Exception)` at `beb1d91`; producer 774 (S1 β, D2: subclasses `ValueError`) upstream of α | PASS (producer upstream) |
| A name added to the surface edits no count | producer 913 (S23 α), upstream of 926, which α depends on | PASS (producer upstream) |
| α's merge commit can serve as the inventory baseline | producer 926 (S23 ζ) labels each drift; α depends on it, so the tables at α's merge carry ζ's classifier | PASS (producer upstream) |

## β — Release solar-challenge 0.6.0 (leaf; task 224 re-scoped)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| R3 RED today: the version is 0.5.0 everywhere | `pyproject.toml` `version = "0.5.0"`; `__init__.py` `__version__ = "0.5.0"`; `uv.lock` project entry `version = "0.5.0"`; worked example `@solar-challenge-v0.5.0`; `cost-recovery-finance-model.md` `**Version**: 0.5.0` | PASS (RED observed) |
| The two version spellings in code are already tied | `tests/unit/test_package.py::test_pyproject_version_matches_dunder` | PASS |
| A version bump needs a re-lock, which works offline | `uv.lock` records the editable project's version; CLAUDE.md: uv resolution runs with `UV_OFFLINE=1`; no dependency changes | PASS |
| R4: there are lines to fold | 25 `**Unreleased on main**` paragraphs in the consumption guide (tasks 392 … 777), 7 in the finance-model header (219, 271, 281, 295, 307, 308, 656) | PASS (measured, not a bound) |
| R5: the inventory's classifier exists | producer 926 (S23 ζ) upstream; S23 contract F5 ("the lock's breaking entries … are its release inventory") | PASS (producer upstream) |
| Every held retirement lands before β | edges β → each held leaf (decompose §11 step 6); the store lists 15 retirement leaves plus 927 with `x_seam_wait.stream == S29` | PASS |
| The figures that move land before β | edges β → the 31 library-side leaves not upstream of a held leaf (PRD decision 3, recomputed at decompose) | PASS |
| R6: the doc test has two spellings to check | the worked-example line and the "← current release" tag line in "Tag / release convention" | PASS |
| R8: no transitional marker remains | `git grep -i -E 'S29\|surface bump' main -- src tests` is empty today; held leaves may add some (S15's `default_weather` docstring plan) | PASS (checked in-leaf; not a delivered check, since it is vacuous today) |
| The release notes have 224's scope notes | task 224 details: 219, 326, 285, Python floor 3.11 (195's note void) | PASS |
| The platform recipe has measured sites | `git grep` at platform `d521265` (PRD §2.3) | PASS (re-measured in-leaf) |

## γ — Human gate: cut and push the tag; file the platform re-pin

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A tag is cut on the release leaf's merge commit | `solar-challenge-v0.5.0` points at `03af26e`, "Merge task/110 into main" | PASS |
| The push-and-check steps exist | consumption guide "Tag / release convention": `git push origin <tag>`; `git ls-remote --tags origin <tag>` | PASS |
| The platform is a factory project that can take the re-pin task | `/home/leo/src/solar-challenge-platform/dark-factory-orchestrator.yaml` `project_id: "solar_challenge_platform"`; it pins `@solar-challenge-v0.5.0` | PASS |
| The tag cannot be cut by a leaf | the merge commit does not exist during the leaf; pushing a tag needs credentials the sandbox lacks | PASS (premise of the gate) |
