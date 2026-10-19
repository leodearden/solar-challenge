# Capability manifest — Surface lock (review-all S23)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/surface-lock-one-module.md`. Every capability a leaf's signal asserts is bound to evidence. Its machine-readable twin is `docs/prds/surface-lock-one-module.capability-manifest.yaml`.

**Code anchors** verified against main `c06d12b115ed` (2026-10-17). Main moves fast: anchors cite symbols, so re-locate lines at implementation time. Probes ran in this repo's locked dev environment, with mypy 2.1.0 from the repo venv.

**Batch verdict: PASS, after one premise correction.**

- The stream row's "`__init__`'s three tables derive from one mapping" **failed** G3. A computed `__all__` breaks a mypy-strict consumer's star import. The PRD keeps `__all__` and the TYPE_CHECKING block literal and checks every pair instead (§3 decision 2).
- No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`.
- Out-of-batch producers: task 700 (in review) for α and δ, and task 785 (pending) for δ.
- η is held for S29.

## α — One surface-contract module by behaviour; no count literal; the import-time check covers every runtime pair

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The duplicated tests exist to merge | grep: `test_import_is_pvlib_free` in both modules; `test_touching_pv_imports_pvlib` / `test_touching_pvconfig_imports_pvlib`; `test_tariffperiod_collision_resolved` in both; `get_cli_app` exclusion in `test_all_has_no_duplicates_and_no_cli_names` and `test_all_equals_frozen_set` | PASS |
| B1 is a real RED: adding a name fails on a count | grep: `test_all_equals_frozen_set` asserts `len(solar_challenge.__all__) == len(FROZEN_SET) == 69` | PASS (RED by construction) |
| `__all__` must stay literal (the premise correction) | probe: a scratch package with `__all__ = list(_ORIGIN)`; `mypy --strict` on `from pkg import *` reports `Name "f" is not defined [name-defined]` for each name; with a literal list, `Success` | FAIL for derivation, so it is replaced |
| B2/B3 are real REDs: the import-time check covers only `_SYMBOL_MODULE` against `__all__` | grep: `__init__.py`'s `if set(_SYMBOL_MODULE) != set(__all__): raise RuntimeError`; no check reads `_SOURCE_NAME` or duplicates | PASS (RED by construction) |
| The check can be driven without loading a submodule | grep: `__init__.py` imports only `importlib` and `typing` at runtime, and the check runs before `__getattr__` is defined, so a temp copy of `__init__.py` alone exercises it | PASS |
| The resolution identity test that replaces the private-table test exists | grep: `test_init_lazy_surface.test_every_name_resolves_to_its_type_checking_import` (task 719) | PASS |
| The prose to delete exists | grep: `T4 contract file`, `Relationship to T3`, `Bounded overlap`, `PRD §3.1` in test_public_api_surface.py; `# Frozen public surface — PRD §3.1` in `__init__.py`; `(currently 69 names)` in review/briefing.yaml | PASS |
| The stale `_external_probe.py` pointer (the row's deletable) | grep: absent since task 719 (f6641d8) | PASS (already gone) |
| Task 700's edits to the same module land first | producer: task 700, in review, adds `REVIEWED_COMPUTED_NAME_WRITES` and `test_reviewed_computed_name_writes_name_only_pinned_classes`; α depends on it | PASS (upstream) |

## β — Constants by their value's structure; Enum aliases shown; nested public classes refused

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| B8 is a real RED: constants are pinned by type name | grep: FROZEN_SURFACE `"SEG_PRESETS": "dict"`, `"OFGEM_TDCV_BY_OCCUPANTS": "dict"`, `"SEASONAL_FACTORS": "dict"`, `"ELEXON_PROFILE_CLASS_1": "list"`, `"DEFAULT_EVENT_WINDOWS": "tuple"`; `surface_form` returns `type(obj).__qualname__` for a non-class, non-routine | PASS (RED by construction) |
| The constants are mappings and sequences whose keys and items have forms | probe: SEG_PRESETS dict of str → SEGTariff; OFGEM and SEASONAL dicts of int → float; ELEXON a list of 48 floats; DEFAULT_EVENT_WINDOWS a tuple of one EventWindow | PASS |
| `Enum.__members__` includes aliases; iteration does not (B9) | probe: `Enum('E', [('A',1),('B',1),('C',2)])` gives `__members__` A, B, C and iteration A, C | PASS |
| No pinned class has a nested public class, `__slots__` or an Enum alias today (no table churn beyond the 5 rows) | probe: over the 42 classes of `_pinned_classes()`, none | PASS |
| The closure does not grow | grep: SEGTariff and EventWindow are in `__all__`, so `signature_closure` leaves them out as roots | PASS |
| An Unreleased line is due (the contract widens) | grep: precedent lines for task 505 and task 567 in docs/domain-library-consumption.md | PASS |

## γ — The helper models only the typing constructs the surface uses

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| No frozen annotation uses a construct to drop | grep: src has no `InitVar`, `NewType`, `TypeVar`, `ParamSpec`, `TypeVarTuple` or self-referential alias; `Annotated` only in cli/ (unfrozen) | PASS |
| No other stream's PRD plans one on the frozen surface | grep docs/prds: S2's `DispatchStrategyConfig: TypeAlias` is a plain union; S16's are `Callable` aliases; S20's `TypeVar` is in web/ | PASS |
| The fail-closed TypeError exists (B5's mechanism) | grep: `_parsed`'s final `raise TypeError(f"No construct reads the annotation …")` (task 602) | PASS |
| The two ignores serve dropped rules | grep: `variable.__default__  # type: ignore[union-attr]` in `_parsed_type_variable`; `new_type.__qualname__  # type: ignore[attr-defined]` in `_parsed_new_type` | PASS |
| About 27 rule tests to delete | ran: a regex over the 98 tests of tests/unit/surface_forms_helper/ matches 27 (named_classes 15, surface_form 9, member_forms 1, signature_closure 1, undeclared_attributes 1) | PASS (measurement, not a bound) |
| The helper type gate stays green with warn_unused_ignores | producer: task 644 (in progress) pins it in test_surface_forms_type_check.py | PASS |

## δ — A generated `__init__` read from the documented rule

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The documented rule exists | docs: Python's dataclasses reference, `init`: "If the class already defines `__init__()`, this parameter is ignored." | PASS |
| `__dataclass_params__.init` is recorded on every admitted minor | grep: `_dataclass_kind` already reads `__dataclass_params__` (task 567); `init` is in 3.11's record (task 668's measurement lists init, repr, eq, order, unsafe_hash, frozen) | PASS |
| One class-body parse to share | producer: task 700's `_initialisers(cls)` parses `inspect.getsource(cls)` to its single ClassDef (branch task/700) | PASS (upstream) |
| B12 is a real RED: the current rule reads a compiler artefact | grep: `_holds_generated_init` returns `init.__code__.co_qualname != init.__qualname__`; `CodeType.replace(co_qualname=…)` exists from 3.11 | PASS (RED by construction) |
| The cache half | producer: task 785 (pending) keys `_type_checking_imports` by module and drops `_fixtures.imported_module`'s unique-name guard; δ depends on it | PASS (upstream) |

## ε — One reading per annotation

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| B6 is a real RED: text is the source as written | grep: `_Unevaluated.text()` returns `self.source`; FROZEN_SURFACE rows hold `'FinanceConfig'`, `Optional[…]` and `pd.Series` for finance.py and community.py (both use future annotations) | PASS (RED by construction) |
| Every pinned string annotation already evaluates (no new NameError) | grep: `_closure_classes` runs `signature_closure` (so `named_classes`) over every exported object, and `_member_form_classes` over every member, both evaluating each string through `_evaluated` | PASS |
| Each annotation has a spelling module to evaluate in | grep: `_spelling_modules(obj, names)` and `_member_form_classes` (`cls.__module__`) | PASS |
| 11 rows respell | ran: a regex for quoted identifiers, `Optional[`, `Union[`, `pd.` over the tables: FROZEN_SURFACE 11 (finance 6, community 5), FROZEN_CLOSURE 0 (the heat-pump hit was Literal value reprs), FROZEN_MEMBERS 0 | PASS (measurement; the lock prints the exact set) |
| A recursive string can be detected at parse (B7) | grep: today's `_Evaluation(source, module)` membership test in `_Unevaluated.classes`; ε keeps the detection and raises instead | PASS |

## ζ — The lock labels each drift additive or breaking and names the doc line

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Re-rendering with parts dropped reproduces a frozen row exactly | probe: for `@dataclass(frozen=True) class New(a: int, b: str = "x", c: float = 1.0, d: int \| None = None)`, rendering `inspect.signature(New)` without c and d through the helper's `_spelled` and `_dataclass_kind` equals `surface_form(Old)` for `Old(a, b="x")`: `dataclass[eq, frozen] (a: int, b: str = 'x') -> None` | PASS |
| Drift is not classified today (B10, B11 RED) | grep: neither `additive` nor `breaking` appears in tests/unit/test_public_api_surface.py or tests/_surface_forms.py | PASS (RED by construction) |
| The doc section the trailer names exists | grep: `## Tag / release convention` and its "**Unreleased on main**" lines in docs/domain-library-consumption.md | PASS |
| Table-level added/removed paths are known to the lock | grep: `_drifted` returns current-only paths and frozen-only paths (`absent=`) | PASS |

## η — The released snapshot and the executable Unreleased-line obligation (held for S29)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A release commit that bumps the version and writes the one release section | producer: S29 (wave 4, program closing step); η carries `x_seam_wait = {stream: S29, contract: "the release commit"}` | PASS (held; upstream by construction) |
| Unreleased lines name their tasks in a fixed lead | grep: every "**Unreleased on main** (task N)" / "(tasks N, M, K)" line in docs/domain-library-consumption.md | PASS |
| ζ's path-level diff to reuse | producer: ζ (upstream in batch) | PASS |
