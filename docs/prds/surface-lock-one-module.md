# PRD — Surface lock: one contract module, one reading per annotation, classified drift

- **Program:** review-all-solar_challenge-20261013, stream **S23** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 1, no upstream stream deps, size M, risk low, mode agent.
- **Finding keys:** fk-293a1282ace4, fk-9df95e9e2b45 (weakened; re-measured in §2), fk-879e8c13f581 (high), fk-ca5301a6f39f, fk-d2881616c782, fk-dc5370224a78, fk-b0607cc5a685 (closed by task 700, §6), fk-ac70915ba435.
- **Binding rulings:**
  - D4: one coordinated surface bump, S29's. No shim survives.
  - D26: S23 is accepted as the synthesis wrote it.
  - D28: the weakened key is re-measured before decomposition.
  - D29: additive frozen-table edits land in-leaf with their row and an "Unreleased on main" line. Renames and retirements are held leaves that S29 releases.
  - The escalation ruling on task 700 (esc-700-3, Leo, option C): fail closed on a computed setattr or `__dict__` write, keep a reviewed acknowledgement set, and walk only `__init__`/`__post_init__`, "so S23 does not redo it".
- **Two premise corrections to the stream row** (§3 decisions 2 and 3):
  - `__init__`'s three tables cannot all derive from one mapping. A probe showed that a computed `__all__` breaks `from solar_challenge import *` for a mypy-strict consumer.
  - The row's "surface_form gains the frozen/eq/order dimension" has already landed, as task 567.
- **Seam-row correction** (§4.1): FROZEN_SURFACE, FROZEN_CLOSURE and FROZEN_MEMBERS live in `tests/unit/test_public_api_surface.py`, not in `tests/_surface_forms.py`, and they stay there. The helper owns how forms are spelled and classified.
- **Status:** authored 2026-10-17 by an author-only /prd seat (agent mode). Not committed.
- **Approach:** B, with a contract (§4) and a boundary-test sketch (§5) for the seam the program gives this stream, FROZEN_SURFACE as the one home of the surface, which every other stream edits in-leaf.
- **Code anchors** verified against main `c06d12b115ed` (2026-10-17). Main moves fast: anchors cite symbols, so re-locate lines at implementation time. Since the review's pin `7dfea36e`, these have landed:
  - task 567: a dataclass's form begins with its kind, `dataclass[eq, frozen] (...)`;
  - task 719: test_init_lazy_surface.py stopped asserting `69`, its private-map test was retired, and the stale `_external_probe.py` pointer was deleted;
  - task 670: the helper's rule tests moved to `tests/unit/surface_forms_helper/`;
  - task 689: unused ignores in tests were deleted.

  `src/solar_challenge/__init__.py` is unchanged since the pin. Task 700 is in review on `task/700`.

## 1. Goal

The surface lock is the test machinery that freezes `solar_challenge.__all__` and what each name's callers rely on. Every stream of this program edits it in-leaf, and S29 uses it to cut the one release. It becomes one contract organised by behaviour, with one reading of each annotation and a lock failure that says what kind of change it saw.

What a user (an agent editing the surface, the S29 release author, a platform consumer) observes:

1. **One module states the surface contract**, in sections by behaviour:
   - the package imports without pvlib and loads a submodule on first touch;
   - every exported name resolves to its typed import;
   - the runtime tables agree at import;
   - the frozen forms;
   - the drift report.

   `tests/unit/test_init_lazy_surface.py` is gone. No test body exists twice. No docstring names T3, T4, H2–H4 or a bare "PRD §".
2. **Adding a public name edits no number.** No count literal of the surface is left in tests, and none in the briefing's convention text.
3. **`import solar_challenge` refuses tables that disagree, wherever they disagree.** A duplicate in `__all__`, a name with no origin module, or an alias entry for a name outside `__all__` raises RuntimeError naming it. Today only the first of the runtime pairs is checked.
4. **Removing a key from `SEG_PRESETS`, or a value from a pinned Enum, fails the lock**, naming the constant. Today the constant is pinned by its type name alone (`"SEG_PRESETS": "dict"`), so both pass silently. An Enum alias shows in its form. A public class nested in a pinned class is refused, not pinned as `()`.
5. **A source-style edit changes no frozen row.** Adding or removing `from __future__ import annotations`, quoting an annotation, or writing `Optional[X]` for `X | None` leaves every form unchanged. A form spells the evaluated annotation.
6. **The helper models only the typing constructs the library uses**:
   - classes;
   - unions;
   - subscripted generics, Literal among them, and Callable's parameter lists;
   - None and Ellipsis;
   - bare aliases;
   - typing's special forms.

   Any other construct raises TypeError naming it (task 602's fail-closed rule). The InitVar, TypeVar/ParamSpec/TypeVarTuple, NewType, Annotated and ParamSpec-args rules go, and so do their two typeshed-gap ignores and about 27 rule tests.
7. **The lock's failure labels each drifted entry `additive` or `breaking` and names what to edit.** An additive entry gets an "Unreleased on main" line in docs/domain-library-consumption.md's "Tag / release convention" section, in the same commit. A breaking entry lands only with a version bump. Under D29 that makes the in-leaf/held split executable for every stream. On S29's branch, the breaking list is exactly the release inventory.
8. **A generated dataclass `__init__` is recognised by the documented rule.** The `co_qualname` artefact goes. With task 785, the helper's cache of `TYPE_CHECKING` imports is keyed by module, so no fixture has to pick unique module names.

## 2. Background (measured at c06d12b115ed)

- **Two modules.**
  - tests/unit/test_public_api_surface.py has 676 lines and 11 tests: the three tables, the lock and member guards, EXPECTED_KIND, the laziness pair and the collision test.
  - tests/unit/test_init_lazy_surface.py has 169 lines and 8 tests.
  - Duplicated between them:
    - `test_import_is_pvlib_free` (same body; only one copy has a timeout);
    - `test_touching_pv_imports_pvlib` and `test_touching_pvconfig_imports_pvlib`;
    - `test_tariffperiod_collision_resolved`;
    - the `get_cli_app` exclusion (in `test_all_has_no_duplicates_and_no_cli_names` and `test_all_equals_frozen_set`).
  - `test_every_name_resolves_to_expected_kind` re-checks that every name resolves, which `test_every_name_resolves_to_its_type_checking_import` (task 719) already checks more strongly.
  - The test_public_api_surface.py docstring and banners name T3/T4, H2/H3/H4 and "PRD §3.1/§3.5/§10".
- **Count literals.** test_public_api_surface.py asserts `len(__all__) == len(FROZEN_SET) == 69` in `test_all_equals_frozen_set`. It restates 69 in its module docstring, in the H2 banner and in that test's docstring and message. review/briefing.yaml's convention says "(currently 69 names)". Its line-427 "69 public names" is a dated attestation comment, so it is provenance and stays.
- **`__init__.py` tables.**
  - `__all__` is a literal list of 69 names.
  - `_SYMBOL_MODULE` maps name to module.
  - `_SOURCE_NAME` maps the one alias, `DispatchTariffPeriod → TariffPeriod`.
  - The `if TYPE_CHECKING:` block holds 69 explicit `as` re-exports, plus `Typer`.

  The import-time `RuntimeError` compares `set(_SYMBOL_MODULE)` with `set(__all__)` only.

  The tests cover:
  - TYPE_CHECKING names against `__all__` plus `Typer`;
  - each name's runtime object against its TYPE_CHECKING import's object, by identity (task 719);
  - `__all__` against FROZEN_SURFACE.

  Nothing checks `_SOURCE_NAME`'s keys or duplicates at import. A banner says "Frozen public surface — PRD §3.1" (also listed by task 765).
- **Constants.** FROZEN_SURFACE pins `SEG_PRESETS`, `OFGEM_TDCV_BY_OCCUPANTS` and `SEASONAL_FACTORS` as `"dict"`, `ELEXON_PROFILE_CLASS_1` as `"list"`, and `DEFAULT_EVENT_WINDOWS` as `"tuple"`. `GRID_SERVICES_RATE_BANDS` is `"GridServicesRateBands"`, a dataclass instance whose class form is pinned.

  `surface_form` spells an Enum by iterating it, which skips aliases. A class member that is a class is spelled by its constructor signature, and its own members go unpinned.

  Probed over all 42 pinned classes: no nested public class, no `__slots__`, no Enum alias. Nothing is wrong today, but each would pass silently.
- **Annotation readings** (fk-d2881616c782). `_Unevaluated.text()` returns the string as written, while `.classes()` evaluates it.
  - In finance.py and community.py, which both use future annotations, rows read `finance: 'FinanceConfig'`, `Optional[BatteryConfig]` and `pd.Series`. pv.py and load.py rows read `X | None` and `Series`.
  - A regex over the tables (quoted identifiers, `Optional[`, `Union[`, `pd.`) finds **11 rows** that would respell: FROZEN_SURFACE's 6 finance and 5 community names. No FROZEN_CLOSURE or FROZEN_MEMBERS row would change. The heat-pump row's hit was `Literal['ASHP', …]`, whose quotes are value reprs and stay.
  - Every pinned string annotation is already evaluated today, because `signature_closure` runs `named_classes` over every exported name and member. So evaluating for spelling too raises no new NameError on the real surface.
- **Unused constructs** (fk-ca5301a6f39f). grep over src finds no InitVar, NewType, TypeVar, ParamSpec, TypeVarTuple or self-referential alias. `Annotated` appears only in cli/, which is not frozen.

  The PRDs of the other streams plan none of these on the frozen surface. S2's `DispatchStrategyConfig: TypeAlias = A | B | C` is a plain union, and S20's `TypeVar` is in web/, which is not frozen.

  The helper still carries `_parsed_type_variable`, `_parsed_new_type`, `_Declared`, `_Keyword`, `_declaring_module`, the InitVar branch with `_init_only_variables`, the Annotated branch, ParamSpecArgs/Kwargs in `_CLASSLESS_NAME_KINDS`, and the `_Evaluation` recursion cut.

  Two ignores serve them: `__default__ # type: ignore[union-attr]` and `__qualname__ # type: ignore[attr-defined]`. A third, on `__dataclass_params__`, is task 567's and stays.

  A regex over the 98 rule tests in tests/unit/surface_forms_helper/ (InitVar, NewType, TypeVar, ParamSpec, Unpack, Annotated, JSON, type parameters) matches **27**: test_named_classes 15, test_surface_form 9, and test_member_forms, test_signature_closure and test_undeclared_attributes 1 each. One of them (`test_literal_values_and_annotated_metadata_name_no_class`) keeps its Literal half.
- **Drift message** (fk-dc5370224a78). `_drift_message` prints frozen and current forms and asks for an "Unreleased on main" line. No test checks the line. Drift is not classified: grep finds `additive`/`breaking` in neither the module nor the helper.
- **Generated `__init__`** (fk-ac70915ba435). `_holds_generated_init` decides by `init.__code__.co_qualname != init.__qualname__`, a CPython compilation artefact. The dataclasses documentation states the rule directly: "init: If true (the default), a `__init__()` method will be generated. If the class already defines `__init__()`, this parameter is ignored."

  `_type_checking_imports` is `functools.cache`d on the module name. Task 785 (pending) re-keys it.
- **Task 700** (in review, branch `task/700`, 4 commits). It replaces `_attributes_set_on_self`'s whole-class `ast.walk` with `_initialisers(cls)`, which reads the ClassDef's own `__init__`/`__post_init__` statements through their receiver. It also adds `reviewed=` and `REVIEWED_COMPUTED_NAME_WRITES` (FinanceConfig, home.SimulationResults). That is the stream row's "walks only `__init__`/`__post_init__`" and all of fk-b0607cc5a685.

**Weakened finding re-measured (D28):**

| Key | Measurement | Finding | c06d12b115ed |
|---|---|---|---|
| fk-9df95e9e2b45 | name restated in `__all__`, `_SYMBOL_MODULE`, TYPE_CHECKING, FROZEN_SURFACE (+ `_SOURCE_NAME` for the alias) | yes | yes, unchanged |
| fk-9df95e9e2b45 | literal 69 in tests | 2 asserts + prose in 2 files | **1 assert** (test_public_api_surface.py) + 3 prose; task 719 removed the lazy file's |
| fk-9df95e9e2b45 | the lazy-loader test reads private `_SYMBOL_MODULE`/`_SOURCE_NAME` | yes | **no**: task 719 retired it; resolution is now checked against the TYPE_CHECKING import |
| fk-9df95e9e2b45 | runtime sync check covers the first pair only | yes | yes: `_SOURCE_NAME` keys and `__all__` duplicates are unchecked at import |
| fk-9df95e9e2b45 | the tables can all derive from one mapping | proposed | **no** for `__all__` and TYPE_CHECKING: probe in §3 decision 2 |

The finding holds, and is smaller than the review measured it: one count literal is left and two runtime pairs are unchecked.

## 3. Resolved design decisions

1. **The merged module is the existing `tests/unit/test_public_api_surface.py`. The tables stay in it, in their present shapes.**
   - 33 open tasks list that file, nearly all of them for row edits under D29. Moving the tables into a new module, even one beside the helper as the seam row's wording suggests, would turn every in-flight row edit into a modify/delete conflict.
   - The lazy module's tests move in and test_init_lazy_surface.py is deleted. Only tasks 515, 808 and 827 list it, and none of them edits its tests.
   - The module keeps its name, which consumers' docs already cite.
2. **`__all__` and the TYPE_CHECKING block stay literal; only the runtime tables are checked against them, over every pair** (premise correction).
   - **Probe:** a package whose `__all__ = list(_ORIGIN)` imports fine at runtime, but mypy 2.1.0 `--strict` on a consumer's `from pkg import *` reports `Name "f" is not defined` for every name. With the literal list it passes.
   - Static readers do not execute the package, so the four declarations cannot collapse into one. What can be made whole is the check that the declarations agree.
   - At import, a RuntimeError names each offender, whatever `-O` is in force:
     - `__all__` has no duplicate;
     - `set(_SYMBOL_MODULE) == set(__all__)`;
     - every `_SOURCE_NAME` key is in `__all__`.
   - In the tests: TYPE_CHECKING names equal `__all__` plus `Typer`, each runtime object is its TYPE_CHECKING import's (task 719's identity test), and `__all__` equals FROZEN_SURFACE's keys.
   - `_SYMBOL_MODULE` and `_SOURCE_NAME` keep their names and shapes, because D4's derived ruling and S3's, S8's, S14's and S15's PRDs name `_SYMBOL_MODULE`. Folding the alias into tuple values would restate 69 source names, or mix value types, to remove one row.
3. **Task 567 already delivers the row's "frozen/eq/order dimension"; tasks 668 and 669 stay as filed.**
   - 668 decides `match_args`/`slots`/`weakref_slot` and a class's own `__slots__`/`__match_args__`, with its 3.11 constraint.
   - 669 is a briefing-policy decision about the nine mutable pinned dataclasses, not a lock gap.
   - S23 does not redo either. At decompose, 668 gains fk-879e8c13f581 and an edge on ζ, so that its new qualifiers arrive with their additive/breaking rule (§6).
4. **A constant is pinned by its value's structure, not its scalars** (fk-879e8c13f581).
   - A mapping spells its type and then its entries in iteration order, each as `key_repr: value_form`, so a dropped or renamed key shows.
   - A list or tuple spells its type and then its items' forms, so its length shows.
   - Anything else spells its type's qualified name, as today. That covers scalars and dataclass instances, whose class form is pinned.
   - A preset's numbers are data. A changed rate is "what a public name returns", which the doc already lists as its own kind of Unreleased line. The lock pins what a consumer indexes: keys, positions and types.
   - An Enum spells `__members__`, aliases included. A public class in a pinned class's body raises TypeError naming it.
   - The named classes of a constant are the types its form spells. That changes no closure today, because SEGTariff and EventWindow are exported.
   - β adds an "Unreleased on main" line, as tasks 505 and 567 did when the contract widened.
5. **Shrink `_parsed` to the vocabulary in use, and fail closed on the rest** (fk-ca5301a6f39f).
   - "Handling each typing form explicitly" means one rule per construct the frozen surface uses (§1 item 6), with task 602's TypeError for anything else. The two ignores go with the rules they serve.
   - One parametrised rule test pins the TypeError for each dropped family (InitVar, TypeVar, NewType, Annotated, ParamSpec.args). A removed rule comes back from git history, driven by a real signature, when src first uses the construct.
6. **One reading per annotation: evaluate at parse time** (fk-d2881616c782).
   - `_parsed(annotation, module)` evaluates a string or ForwardRef in the module that spells it, with that module's top-level TYPE_CHECKING imports bound over its globals as today, and parses the result. So the construct tree holds no unevaluated string.
   - `text()` and `classes()` read the same tree, and `_Unevaluated` is deleted. `surface_form` and `named_classes` share one walk that pairs each annotation with its spelling module (`_spelling_modules`).
   - A string met again inside its own evaluation raises TypeError naming it, as no rule spells a recursive alias. That replaces the `_Evaluation` cut and its two tests.
   - The 11 rows are regenerated in the same commit. That is spelling only, no API change, so no Unreleased line.
7. **The lock classifies drift by re-rendering, never by parsing the frozen text** (fk-dc5370224a78).
   - A changed entry is `additive` when the current object's form, less some of its additive parts, renders exactly the frozen row. The rendering uses the helper's own renderer (probe in the manifest: dropping trailing defaulted fields from `inspect.signature(New)` renders `Old`'s row byte for byte).
   - These are the additive parts, defined in one table in the helper:
     - a parameter with a default that is keyword-only;
     - a positional parameter with a default, dropped only together with every positional parameter after it;
     - `*args` or `**kwargs`;
     - a property's `settable` or `deletable` qualifier;
     - an entry of a mapping constant;
     - an Enum member.
   - At table level, an added path is additive and a removed path is breaking. Anything else is breaking, because what is not proven additive fails closed.
   - The message labels each entry. Its trailer says that an additive change needs an "**Unreleased on main** (task N): …" line in the "Tag / release convention" section of docs/domain-library-consumption.md in the same commit, and that a breaking one lands only with a version bump under that section.
8. **A generated `__init__` is read from the documented rule** (fk-ac70915ba435, second half). `_holds_generated_init(cls)` is true when all of these hold:
   - the decorator processed `cls`;
   - `cls.__dataclass_params__.init` is on;
   - `__new__` is not in `vars(cls)`;
   - the class's own ClassDef neither defines nor assigns `__init__`.

   The ClassDef is read once, through the same parse task 700's `_initialisers` reads, refactored into one class-body reader. The cache half is task 785's.
9. **The executable Unreleased-line obligation waits for S29's release** (fk-dc5370224a78, first half; held leaf η, open question 1).
   - Today the obligation can only be checked through a hand-kept path-to-task table, and populating that table means archaeology over everything changed since 0.5.0, in a spelling the 0.5.0 tables do not share. It would also add a second edit to every in-flight leaf of the program.
   - After S29's bump, the released tables are the current tables. So a snapshot taken at that commit starts the path-to-task table empty, and each later surface edit adds one row beside its Unreleased line.

## 4. Contract — the seam S23 owns

### 4.1 FROZEN_SURFACE as the one home of the surface (owner: tests/unit/test_public_api_surface.py; forms by tests/_surface_forms.py)

- **F1.** These keep their shapes and module, one row per line, during the program and after:
  - `FROZEN_SURFACE: dict[str, str]` (name → form);
  - `FROZEN_CLOSURE: dict[str, str]` (`module.Qualname` → form);
  - `FROZEN_MEMBERS: dict[str, dict[str, str]]` (class path → member → form).

  An in-leaf edit by any stream is a row edit there, plus the `__all__`, `_SYMBOL_MODULE` and TYPE_CHECKING rows in `__init__.py`, plus its Unreleased line.
- **F2.** No count of the surface is written anywhere a name edit would have to touch. Name equality is set equality with FROZEN_SURFACE's keys, and duplicates are the import-time check's.
- **F3.** A row is exactly what the lock printed as `current` for that path. After ε, it is the evaluated spelling: an `Optional[X]` or quoted row pasted from an older branch fails at the merge verify and prints its current form.
- **F4.** After ζ, every failure line carries `additive` or `breaking`. Under D29, a leaf whose own edit prints `breaking` is a held leaf for S29.
- **F5.** S29 reads the merged module and the classification. On S29's branch, the lock's breaking entries against main are its release inventory, and the release section names each one.

### 4.2 Helper interface after S23 (tests/_surface_forms.py; names tactical, shape binding)

```python
def surface_form(obj: object) -> str: ...                 # unchanged signature; §3 decisions 4, 6 change spellings
def member_forms(cls: type) -> dict[str, str]: ...        # unchanged; a nested public class raises TypeError
def named_classes(obj: object) -> set[type]: ...          # unchanged; a constant names the types its form spells
def signature_closure(roots: Iterable[object], package: str) -> set[type]: ...
def undeclared_attributes(cls: type, *, reviewed: Collection[str] = ()) -> set[str]: ...  # task 700
def unset_attributes(cls: type, *, reviewed: Collection[str] = ()) -> set[str]: ...       # task 700

def is_additive_change(frozen: str, obj: object) -> bool:
    """Whether surface_form(obj), less some of its additive parts, spells *frozen* exactly."""
def is_additive_member_change(frozen: str, cls: type, name: str) -> bool:
    """The same for member_forms(cls)[name]."""
```

Invariants:

- **H1.** Every annotation the forms read is evaluated once, in its spelling module. `text()` and `classes()` read one tree.
- **H2.** A construct with no rule raises TypeError naming it and its type. So does a recursive string, and so does a nested public class.
- **H3.** The additive-parts table is the only place classification rules live. Classification renders the current object and compares strings, and never splits or parses a frozen row.
- **H4.** Anything not proven additive is breaking.

## 5. Boundary-test sketch

| # | Faces | Scenario | Preconditions | Postconditions |
|---|---|---|---|---|
| B1 | consumer (every stream) | A name is added with no number edited | Scratch edit adding one name to `__all__`, `_SYMBOL_MODULE`, TYPE_CHECKING and FROZEN_SURFACE | The merged module passes. **RED today:** `test_all_equals_frozen_set` fails on `== 69` |
| B2 | producer (`__init__`) | A stale alias entry refuses import | A temp copy of `__init__.py` whose `_SOURCE_NAME` names a name outside `__all__`, imported in a subprocess | RuntimeError naming that name. **RED today:** it imports |
| B3 | producer (`__init__`) | A duplicate in `__all__` refuses import | The same, with a name listed twice | RuntimeError naming it. **RED today:** it imports, and only a test notices |
| B4 | consumer | Laziness is stated once | Real tree | One definition each of the pvlib-free and the touch-loads-pvlib tests in tests/; test_init_lazy_surface.py absent; both pass |
| B5 | producer (helper) | A dropped construct fails closed | Fixture signatures annotated with InitVar[int], a TypeVar, a NewType, Annotated[int, 1], P.args | Each `surface_form` raises TypeError naming the annotation and its type. **RED today:** each is spelled |
| B6 | producer (helper) | Source style changes no form | Two fixture modules, one with `from __future__ import annotations`, each `def f(a: Optional[A], b: A \| None, c: "Optional[A]")` | Both forms are `(a: A \| None, b: A \| None, c: A \| None)`. **RED today:** the future-import module spells `Optional[A]` and `'Optional[A]'` |
| B7 | producer (helper) | A recursive alias fails closed | `JSON = Union[dict[str, "JSON"], list["JSON"], str, None]` in a fixture signature | TypeError naming `"JSON"` |
| B8 | consumer (platform) | A dropped preset key fails the lock | monkeypatch a copy of SEG_PRESETS minus one key into the lock's view (or a fixture dict) | The form differs, naming the key; `"SEG_PRESETS": "dict"` is gone from the table. **RED today:** the same `"dict"` |
| B9 | producer (helper) | Enum aliases show; nested classes refuse | Fixture `class E(Enum): A = 1; B = 1; C = 2`; a pinned-class fixture with a public nested class | `surface_form(E) == "A=1, B=1, C=2"`; `member_forms` raises TypeError naming the nested class. **RED today:** `"A=1, C=2"` and `"()"` |
| B10 | both | Drift is classified | Fixture pairs (frozen row, current object): appended defaulted field; defaulted field inserted before another; removed parameter; retyped parameter; new keyword-only defaulted parameter; property made settable; constant gains a key; constant loses a key | additive, breaking, breaking, breaking, additive, additive, additive, breaking. At table level, a new name is additive and a removed member breaking |
| B11 | consumer (every stream) | The lock's message names the kind and the doc | A scratch edit to one pinned signature | The failure lists the path with frozen, current and its label, and its trailer names the "Tag / release convention" section of docs/domain-library-consumption.md |
| B12 | producer (helper) | The generated-`__init__` rule survives a compiler change | A decorated fixture dataclass whose generated `__init__.__code__` is replaced by `.replace(co_qualname=<its __qualname__>)`, with an inherited field annotated in another module | Its inherited field is still spelled in the declaring module. **RED today:** `_holds_generated_init` says not generated, so a NameError |

## 6. Existing tasks this PRD meets

| Task | Status | Relation |
|---|---|---|
| 700 | in-progress (review), deps 670 | **Built on, not superseded.** It delivers fk-b0607cc5a685 whole and the row's "walk only `__init__`/`__post_init__`", under Leo's esc-700-3 ruling. α depends on 700, because both edit test_public_api_surface.py. δ refactors 700's `_initialisers` into the one class-body reader |
| 785 | pending, deps 670 | **Built on, not superseded.** It delivers the cache half of fk-ac70915ba435: keyed by module, and `_fixtures.py`'s unique-name guard removed. At decompose, add fk-ac70915ba435 and `x_finding_run` to its metadata. δ carries the key and closes it, and depends on 785 |
| 567 | done | Delivered the row's frozen/eq/order dimension (§3 decision 3) |
| 719, 670, 689 | done | 719 removed one `69` and the external-probe pointer; 670 split the rule tests; 689 removed unused ignores |
| 668 | pending, deps 567 | Stays. At decompose, add fk-879e8c13f581 to its metadata and the edge 668 → ζ, so its new qualifiers come with an additive/breaking rule |
| 669 | pending | Stays (briefing policy). Unaffected |
| 644 | in-progress | Pins warn_unused_ignores for the helper's ignores. It is independent of which ignores exist; γ removing two is compatible |
| 765 | pending | Lists `__init__.py`'s "PRD §3.1" banner, which α rewrites. Whichever lands second drops that item |
| 808, 515, 827 | pending / pending / deferred | List test_init_lazy_surface.py, which α deletes. 808 already says "unless S23 has derived it" for the count |

## 7. Cross-PRD relationship

| Other PRD / stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| every stream that edits a frozen row (S2, S3, S8–S12, S14–S16, S27, S28, …) | consumes | F1–F4: rows in test_public_api_surface.py; no count after α; evaluated spelling after ε; classified drift after ζ | S23 | queued |
| S29 Surface bump (D4) | consumes | F5: the merged module (α) and classification (ζ); η is held on S29's release commit | S23 (module, ζ) / S29 (release, snapshot moment) | queued / held |
| S24 Lane harness | shares a file family | S24 ζ owns the helper type gate and ruff over tests/; S23 owns `_surface_forms.py`'s content | S23 (content) / S24 (gate) | queued |
| S15 / task 808 | consumes | 808 adds three names in-leaf. After α it edits no count | S15 | queued |
| task 700, task 785 | produces for S23 | `_initialisers` class-body parse; module-keyed TYPE_CHECKING cache | 700 / 785 | in review / pending |

## 8. Decomposition plan

Leaves are labelled α–η; real ids come at decompose. Priority follows each leaf's finding severity. Only α touches src (`src/solar_challenge/__init__.py`, comments and the import-time check); no leaf changes a public name.

**α — One surface-contract module by behaviour; no count literal; the import-time check covers every runtime pair** (leaf)

- **Keys:** fk-293a1282ace4 (low), fk-9df95e9e2b45 (low, weakened, re-measured §2).
- **Modules:**
  - tests/unit/test_public_api_surface.py (merged, sections by behaviour);
  - tests/unit/test_init_lazy_surface.py (deleted);
  - src/solar_challenge/__init__.py: the import-time check over `__all__` duplicates, `_SYMBOL_MODULE` and `_SOURCE_NAME`, and banners without "PRD §3.1", "T2" or an invariant comment that restates the check;
  - tests/unit/test_consumption_doc.py and docs/domain-library-consumption.md (references to the deleted file);
  - review/briefing.yaml (drop "(currently 69 names)"; the protected-gates list names the merged module).
- **Work:**
  - Move the lazy tests in, one copy each.
  - Drop EXPECTED_KIND's duplicate resolution loop, keeping only the kind check.
  - Add the B2/B3 subprocess rejection test.
  - Delete the T3/T4/H-number/"PRD §" prose.
- **Signal:**
  - B1 (RED today) and B2/B3 (RED today): a stale alias or a duplicate name refuses import with RuntimeError naming it.
  - B4.
  - `grep` finds no `== 69`, no `T3`/`T4`/`Bounded overlap` and no `PRD §` in the module.
  - The verify passes with test_init_lazy_surface.py absent.
- **Consumer:** every in-leaf surface edit (B1); `import solar_challenge` for every consumer; S29.
- **Prereqs:** task 700 (out of batch).

**β — Constants by their value's structure; Enum aliases shown; nested public classes refused** (leaf, **high**)

- **Keys:** fk-879e8c13f581 (high).
- **Modules:** tests/_surface_forms.py; tests/unit/surface_forms_helper/test_surface_form.py, test_member_forms.py, test_named_classes.py; tests/unit/test_public_api_surface.py (the 5 container-constant rows); docs/domain-library-consumption.md (one "Unreleased on main" line: the contract now covers each constant's keys and length); review/briefing.yaml's convention (constants are pinned by structure).
- **Work:** §3 decision 4.
- **Signal:**
  - B8 (RED today): `grep` finds no `"SEG_PRESETS": "dict"` and no `"ELEXON_PROFILE_CLASS_1": "list"`.
  - B9 (RED today).
  - The lock passes with the regenerated rows.
- **Consumer:** platform code that indexes SEG_PRESETS, OFGEM_TDCV_BY_OCCUPANTS, SEASONAL_FACTORS, ELEXON_PROFILE_CLASS_1 and DEFAULT_EVENT_WINDOWS; the lock on every verify.
- **Prereqs:** α.

**γ — The helper models only the typing constructs the surface uses** (leaf)

- **Keys:** fk-ca5301a6f39f (medium).
- **Modules:** tests/_surface_forms.py; tests/unit/surface_forms_helper/test_named_classes.py, test_surface_form.py, test_member_forms.py, test_signature_closure.py, test_undeclared_attributes.py.
- **Work:** §3 decision 5. Delete `_parsed_type_variable`, `_parsed_new_type`, `_declaring_module`, `_Declared`, `_Keyword`, the InitVar branch and `_init_only_variables`, the Annotated branch, ParamSpecArgs/Kwargs, and the about 27 rule tests (§2's regex). Add one parametrised fail-closed test (B5).
- **Signal:**
  - B5 (RED for the raising direction today).
  - `grep` finds no `type: ignore[union-attr]` and no `def _parsed_new_type` in the helper.
  - The helper type check (test_surface_forms_type_check.py, with task 644's warn_unused_ignores) passes.
  - The lock passes unchanged: no row moves.
- **Consumer:** the lock (no row changes, by construction: no pinned annotation uses a dropped construct); the next agent who meets a new construct gets a TypeError naming it.
- **Prereqs:** β.

**δ — A generated `__init__` read from the documented rule** (leaf)

- **Keys:** fk-ac70915ba435 (low; the cache half is task 785).
- **Modules:** tests/_surface_forms.py (one class-body reader shared with `_initialisers`); tests/unit/surface_forms_helper/test_named_classes.py (B12).
- **Work:** §3 decision 8.
- **Signal:**
  - B12 (RED today).
  - `grep` finds no `co_qualname` in the helper.
  - The lock and the interpreter-matrix lane, which runs the verify on every admitted minor, pass.
- **Consumer:** the lock's closure and member spelling for inherited dataclass fields, on every admitted minor.
- **Prereqs:** γ; task 785 (out of batch).

**ε — One reading per annotation: strings evaluated where they are parsed** (leaf)

- **Keys:** fk-d2881616c782 (medium).
- **Modules:** tests/_surface_forms.py; tests/unit/surface_forms_helper/test_surface_form.py, test_named_classes.py (the `_Evaluation` tests become B7); tests/unit/test_public_api_surface.py (the 11 rows regenerated in the same commit).
- **Work:** §3 decision 6. No Unreleased line: the change is spelling only.
- **Signal:**
  - B6 (RED today) and B7.
  - `grep` finds no `class _Unevaluated` in the helper, and no `Optional[` and no `: 'FinanceConfig'` in the module's tables.
  - The lock passes.
- **Consumer:** every stream's in-leaf row edits (F3), which stop churning on source style; S24's lint sweeps over src.
- **Prereqs:** δ.

**ζ — The lock labels each drift additive or breaking and names the doc line** (leaf)

- **Keys:** fk-dc5370224a78 (low; the classification half; the obligation half is η).
- **Modules:** tests/_surface_forms.py (`is_additive_change`, `is_additive_member_change` and the additive-parts table); tests/unit/surface_forms_helper/test_drift.py (new: the B10 fixtures); tests/unit/test_public_api_surface.py (`_drift_message`, `_drifted`); review/briefing.yaml's convention (each failure is labelled).
- **Work:** §3 decision 7.
- **Signal:**
  - B10.
  - B11: a scratch edit appending a defaulted parameter to `calculate_degradation_factor` prints it labelled `additive`, and one removing a parameter prints `breaking`, each with the trailer naming the section.
- **Consumer:** every stream deciding in-leaf vs held under D29 (F4); S29's release inventory (F5); task 668 (its qualifiers' rule).
- **Prereqs:** ε.

**η — The released snapshot and the executable Unreleased-line obligation** (leaf; **held** for S29)

- **Keys:** fk-dc5370224a78 (low; the obligation half).
- **Modules:** tests/unit/test_public_api_surface.py (or a data module beside it); docs/domain-library-consumption.md (the release convention gains the snapshot step).
- **Work:**
  - At S29's release commit, copy the three tables as released into `RELEASED_SURFACE` / `RELEASED_CLOSURE` / `RELEASED_MEMBERS`.
  - Add `UNRELEASED: dict[str, int]` (path → task id), initially empty.
  - Add a test that the keys of `UNRELEASED` equal the paths whose current row differs from the released one, and that each id appears in an "**Unreleased on main** (task N" line of the doc.
  - The release step replaces the snapshot and empties the table.
- **Signal:** a scratch edit to one row fails until `UNRELEASED` names it with a task id whose Unreleased line exists. On S29's release commit, the snapshot equals the tables.
- **Consumer:** every surface edit after S29; platform consumers reading the release notes.
- **Prereqs:** ζ; S29's release leaf (`metadata.x_seam_wait = {stream: "S29", contract: "the release commit that bumps the version and writes the one release section"}`), excluded from the batch's commit_planning.
- **Note for the lead:** open question 1.

**Batch DAG:** 700 → α → β → γ → δ → ε → ζ → η(held, + S29); 785 → δ. The order serialises one helper file and keeps β, the batch's only high leaf, early. β becomes a dependency of the trigger-chain gate 772.

**G7 (advisory; solar_challenge has no docs/legibility/design-invariants.md).** I walked the batch against dark-factory's trigger shapes:

- no-silent-fail-soft: γ, ε and β raise TypeError on what they cannot model, and ζ labels anything unproven `breaking`.
- one-fact-one-home: the count derives; the tables keep one home; η's snapshot records a different fact (as released), reconciled by its test.
- guards-exercise-behaviour: α's rejection runs a real import, ζ's fixtures run the classifier, and B8 runs the lock.
- exceptions-owned-or-ratified: task 700's reviewed writes are ratified by esc-700-3.
- no-lockstep-duplication: α deletes three duplicated test pairs.

No hits are unresolved.

## 9. Out of scope

- **A per-name structured record** (fk-879e8c13f581's NameContract proposal). The row chose forms that stay strings, plus classification by re-rendering (§3 decision 7). The structure ζ needs lives inside the helper, and tables stay pasteable strings that in-flight leaves can edit.
- **`match_args`, `slots`, `weakref_slot`, own `__slots__`/`__match_args__`:** task 668. **The briefing's frozen-dataclass rule:** task 669.
- **Moving the tables out of the test module.** Not during the program (§3 decision 1). After S29, if the module's size calls for it, a data module beside it is a candidate.
- **Rendering the 0.5.0 tree with today's helper** to audit S29's inventory against the tag. ζ on S29's branch already lists main's breaking drift. A tag-level audit would need the old tree importable in the verify environment.

## 10. Open questions

1. **η: file it now as a held leaf, or leave fk-dc5370224a78 half-open?** The row names only the classification and the doc line (ζ). The finding's executable obligation needs a released snapshot, which S29's release commit creates (§3 decision 9). **Suggested:** file η held on S29, so that the key closes when η lands.
2. **The seam row's owner file.** The program's seam row names `tests/_surface_forms.py`. The tables live in, and stay in, `tests/unit/test_public_api_surface.py` (§3 decision 1). **Suggested:** the lead amends the row to "owner: tests/unit/test_public_api_surface.py (tables) with tests/_surface_forms.py (forms, classification)".
3. **Tactical, decided in-leaf:**
   - α: the merged module's section order, and whether the B2/B3 subprocess copies only `__init__.py` into a temp package (the check runs before any submodule import);
   - β: whether a long uniform sequence (ELEXON's 48 floats) is spelled item by item or as a counted run;
   - ζ: the name of the new rule-test module.

## Gate record

- **G1:** every mechanism names its consumer in §8:
  - the merged module, for every stream's edits and S29;
  - the import-time check, for every `import solar_challenge`;
  - constant structure, for platform indexing;
  - the shrink, for the next new construct;
  - one reading, for in-leaf edits;
  - classification, for D29 and S29;
  - the generated-`__init__` rule, for the lock on every minor;
  - the snapshot, for post-S29 edits.
- **G2:** every leaf names a signal that runs in the per-task verify. Each RED-today row in §5 binds a real gap.
- **G3:**
  - A derived `__all__` **failed** (mypy-strict star import, probed) and was replaced by decision 2.
  - The rest was found on main or in documentation:
    - `inspect.Signature.replace` rendering subsets, prototyped against a real form;
    - the dataclasses documentation's `init` rule;
    - Enum `__members__` including aliases;
    - task 700's `_initialisers`, on its branch, in review;
    - task 785, pending, upstream of δ.
- **G4:** §7. S23 owns its seam. The seam-row file correction and the cross-reference lines are returned to the lead.
- **G5:** B, with a contract and boundary tests for the one owned seam. There are about 8 mechanisms, all in the test harness plus one import-time check, under a single owner.
- **G6:**
  - Counts (11 rows, about 27 tests, 69 names, 42 classes) are measurements by stated rules, not acceptance bounds. Signals assert absences and named failures.
  - Each rejection premise is bound in-leaf with a RED fixture (B2, B3, B5, B7, B9, B12).
  - No signal depends on a downstream leaf. δ's depends on 785, wired upstream.
- **META:** one design-level choice remains, η's filing (open question 1). The decomposed result is coherent either way, because ζ stands alone.
