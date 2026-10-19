# PRD — Lane harness: one typed collection source, one lane-only mechanism, gates over tests/

- **Program:** review-all-solar_challenge-20261013, stream **S24** (`plans/review-all-program-solar_challenge-20261014.md`). Wave 1, no upstream stream deps, size M, risk low.
- **Finding keys:** fk-1abd62632ae1 (weakened; re-measured in §2), fk-dd434cb2d4b9, fk-eec3806e584e, fk-f48c29a98a89, fk-a0b751097301 (weakened; re-measured in §2), fk-e5820c5e22ed (high), fk-5de02e56b3af, fk-3667e4e32155, fk-a9aad5f6d1b2.
- **Binding rulings:**
  - D23: every floor in pyproject.toml is raised to the locked version, and the capability-claim tests are deleted. The floor is the lock and is re-raised on every re-lock. No oldest-floor lane job.
  - D28: the weakened findings are re-measured before decomposition.
  - D29: does not touch S24, which changes no frozen public name.
  - The synthesis ruling that the e2e mark is added in the existing `pytest_collection_modifyitems` hook of tests/e2e/conftest.py.
- **Premise correction to a synthesis ruling** (§3 decision 1): the synthesis made the `--junitxml` report "the one typed collection source". A collect-only JUnit report holds no collected test, so it cannot be. Leo ruled in this session to replace it with an in-repo collection-report plugin. That plugin also takes over the skipped-module question JUnit answers today, so the repo keeps exactly one typed collection source.
- **Status:** authored 2026-10-15 by an author-only /prd session; not yet committed.
- **Approach:** B, with a contract (§4) and a boundary-test sketch (§5) for the two seams the program gives this stream: the collection report and the lane-only suite list.
- **Code anchors** verified against main `962552956508` (2026-10-15). Main moves fast: anchors cite symbols, so re-locate lines at implementation time. Since the review's pin `7dfea36e`, only `tests/unit/test_marker_registration.py` has changed among this stream's files: five unit classes moved from its networked list to its offline list.

## 1. Goal

The test harness that pins how the orchestrator runs this repo's verify and offline lane becomes one mechanism per fact:

- one typed source for "what did this command collect";
- one value per orchestrator command;
- one home for "this suite runs only in the lane";
- one network guard, with no hand-kept lists beside it;
- floors that are the lock;
- static gates that cover tests/ as well as src/.

What a user (an agent or a human maintaining the repo) observes:

1. **A lane contract test reads collections as data.** A uv or pytest line that happens to contain `::` no longer reads as a test, and parametrise ids are no longer cut out of node-id text. Today `collected_node_ids` keeps every stdout line containing `::`, and `_interpreters_named_by` does `rpartition("[")`.
2. **A probe cannot drop part of how the orchestrator runs a command.** The command string, its directory, its enabled flag and its role all come from one value built from dark-factory-orchestrator.yaml. One runner starts every probe in its own session and kills the whole process group on timeout. Today five sites compose these by hand, and the collect runner kills only the shell.
3. **`pytest -o addopts=` from the repo root never reaches tests/e2e.** dark-factory's serial and confirm reruns append `-o addopts=`, so this is what they see. "Lane-only" has one home, `tests/conftest.py::collect_ignore`. A contract test covers every lane directory, e2e included, which it did not before.
4. **No e2e module hand-writes its mark.** The e2e conftest's hook marks every test under tests/e2e.
5. **pyproject.toml's floors are uv.lock's versions, and the verify keeps them so.** Re-lock past a floor without raising it, and the verify fails, naming the requirement, its table, the locked version and the fix. The capability-claim tables in test_e2e_extra.py, test_build_system.py and test_dev_extra.py (task 644's file) go.
6. **One mark vocabulary, enforced by pytest.** `integration`, a mark with no consumer, is retired. pytest refuses an unregistered mark at collection, so a misspelt `@pytest.mark.slwo` errors instead of silently not exempting. The hand-kept network lists go, and the offline guard is the one network mechanism.
7. **`ruff check` and the helper type check cover tests/.** Today 59 F findings in 23 test files, 29 cargo `# type: ignore[name-defined]` and 2 helper type errors go uncaught.
8. **dark-factory-orchestrator.yaml is configuration.** Its rationale lives in a doc it names, and stale measured durations are deleted.

## 2. Background (measured at 962552956508)

- **Collection reading.**
  - tests/_collect_only.py::run_collect_only runs a command verbatim with `PYTEST_ADDOPTS="--collect-only --verbosity=-1 …"`. tests/unit/test_collect_only.py pins that an ini `-v` cancels `-q`.
  - `collected_node_ids(listing)` keeps every stdout line containing `::`.
  - tests/_lane_collection.py::_lies_under partitions node ids on `::`.
  - tests/unit/test_interpreter_matrix_lane.py::_interpreters_named_by does `node_id.rpartition("[")[2].removesuffix("]")`.
  - tests/unit/test_per_task_verify.py::_modules_skipped_at_collection parses a `--junitxml` report with ElementTree.
  - tests/unit/test_marker_registration.py regex-parses `<Class (\w+)>` out of collect output.
- **JUnit premise, probed.** Under pytest 9.0.3, `pytest --collect-only --junitxml=out.xml` on a module with a plain, a parametrised and a class test, plus a module that importorskips, writes one testcase: the skipped module. The same holds under `-m`. A collect-only JUnit report lists only collection reports that skipped or failed. It lists no collected item, so it cannot carry node ids or parametrise ids.
- **Command composition** (fk-1abd62632ae1). Five sites each build "how the orchestrator runs this command" by hand:
  - `_lane_collection.collect_lane_job` composes sole_offline_lane_job, lane_job_directory and run_collect_only;
  - `test_stale_uv_lock.test_each_lane_job_refuses_a_stale_lock_naming_uv_lock` repeats that trio;
  - `test_per_task_verify._collect_with_test_command` reads `["test_command"]`;
  - `test_stale_uv_lock.test_the_verify_refuses_a_stale_lock_naming_uv_lock` indexes `config[key]`;
  - `_verify_suite.run_verify_suite` reads `["test_command"]` and runs it through its own Popen.

  The runners differ. `run_verify_suite` starts a new session and `killpg`s on timeout. `run_collect_only` uses `subprocess.run(shell=True, timeout=300)`, which kills only the direct child.
- **Lane-only.**
  - `tests/conftest.py::collect_ignore = ["interpreter_matrix", "css_build", "newest_releases"]`.
  - tests/e2e is kept out by pyproject addopts `--ignore=tests/e2e`, by test_command's `--ignore=tests/e2e` and by `-m '… not e2e'`.
  - The `e2e` row of `LANE_JOBS` (tests/unit/test_offline_lane_contracts.py) checks only `COLLECTS_ONLY_ITS_SUITE`.
  - `interpreter_matrix/test_verify_suite._suite_env` and the newest-releases test each set `PYTEST_ADDOPTS=--ignore=<own suite>`.
- **e2e mark.**
  - All 23 tests/e2e/test_*.py modules carry `pytestmark = pytest.mark.e2e`.
  - `tests/e2e/conftest.py::pytest_collection_modifyitems` already walks every item under its directory, to add the `flaky` rerun marker.
  - `tests/conftest.py::_MARKS_OF_TESTS_ALLOWED_ONLINE = ("slow", "e2e")` exempts e2e from the offline guard.

  Probed: a mark added by a subdirectory conftest's modifyitems hook is seen by `-m`, and by `get_closest_marker` at run time.
- **Floors** (fk-e5820c5e22ed). uv.lock pins each of the 20 direct requirements at exactly one version: 8 core, 6 dev, 4 web and 2 e2e. 19 of the 20 floors sit below their locked version; only pytest-rerunfailures 16.7 already matches. The examples run from pandas>=2.0.0 against 3.0.3 to playwright>=1.51.0 against 1.61.0. `[build-system].requires` (setuptools>=77.0.0, wheel) is not in uv.lock. The capability-claim tables are test_e2e_extra.py (4 rows) and test_build_system.py (3 rows). Task 644, which is merging, adds test_dev_extra.py (mypy rows) and `mypy>=1.11.0`.
- **The newest-releases interaction.** tests/newest_releases runs the verify unchanged in a copy whose uv.lock went through `uv lock --upgrade`, with pyproject.toml untouched. A verify test asserting floor == lock is therefore false by construction in that copy.
- **Marks** (fk-3667e4e32155).
  - `integration` is registered as "may hit real PVGIS". It is applied in 14 integration modules, 5 of them not slow, and nothing selects or deselects on it.
  - test_marker_registration.py keeps INTEGRATION_FILES (8 of 25 modules), NETWORKED_UNIT_CLASSES (1 class) and PURE_UNIT_CLASSES (8 classes).
  - Marks in use across tests/: parametrize, slow, usefixtures, e2e, integration, build, skipif, filterwarnings and flaky. All of them are registered or built in.
  - Probed on pytest 9.0.3: the ini option `strict_markers = true` makes an unregistered mark a collection error, and it survives `-o addopts=`.
- **Static gates** (fk-5de02e56b3af).
  - `ruff check tests` (ruff 0.16.10, select F) reports 59 findings in 23 files: F821 44 (pd 14, FleetConfig 8, BillDistribution 6, Callable 6, …), F401 11, F841 3 and F541 1. It also warns about 4 invalid `# noqa` directives in test_flex.py.
  - `grep -rn 'type: ignore\[name-defined\]' tests` finds 29 comments in 12 files.
  - 33 tests/_*.py helpers exist; only `_surface_forms.py` is type-checked (test_surface_forms_type_check.py). mypy strict over the other 32 reports 2 errors: `_css_classes.py` (list-comprehension type) and `_job_manager_double.py` (returns Any).
  - test_lint lints `src/solar_challenge` only.
- **Orchestrator yaml** (fk-a9aad5f6d1b2). 85 of its 134 lines are comments, carrying measured durations (214 s, ~20 s, 17-38 s, 17-19 min), memo and PRD history, and intent that CLAUDE.md restates. CLAUDE.md has `uv run --locked` 11 times.

**Weakened findings re-measured (D28):**

| Key | Measurement | Finding | 962552956508 |
|---|---|---|---|
| fk-1abd62632ae1 | hand compositions of "how the orchestrator runs a command" | 5 | 5 (the five sites listed above) |
| fk-1abd62632ae1 | collect runner kills the process group on timeout | no | no: `subprocess.run(shell=True, timeout=300)` |
| fk-1abd62632ae1 | probe environment leaks ambient UV_* settings the lane would not have | claimed | **weakened further.** dark-factory's offline lane runs each command in `{**os.environ, 'DF_VERIFY_ROLE': 'offline'}` (orchestrator/src/orchestrator/offline_lane.py), i.e. the orchestrator's whole environment. A denylist of the *caller's* venv and lock-mode switches is therefore the faithful model; an allowlist would diverge from the lane. The one real gap is that `DF_VERIFY_ROLE` is unset. |
| fk-a0b751097301 | lane_job_directory / lane_job_enabled re-implement LaneCommand.cwd ('.') / enabled (True) with asserts | yes | yes; dark-factory's LaneCommand still has those defaults |
| fk-a0b751097301 | an upstream validation entry point exists | no | no: orchestrator/cli.py has no validate-config command |
| fk-a0b751097301 | yaml must pin both seam flags false | yes | infra now defaults False upstream and legacy_numeric True; test_offline_lane_starts_and_skips_the_seams_this_repo_lacks pins both against default drift, which is still worth keeping |

Both conclusions hold for the in-repo half. The upstream half of fk-a0b751097301 (a dark-factory `validate-config`, default-off seams) is out of this repo's reach (§9).

## 3. Resolved design decisions

1. **The typed collection source is an in-repo pytest plugin, not JUnit XML** (ruled by Leo in this session). The JUnit premise is false (§2). A plugin module is loaded with `-p` from a directory that holds only plugins and is prepended to `PYTHONPATH` by the probe. It writes a JSON collection report to the path its `--collection-report` option names.

   It loads by `-p` rather than through tests/conftest.py's `pytest_plugins` because test_collect_only.py and test_lane_collection_helper.py probe synthetic projects that have no copy of the plugin. It has a top-level module name, not `tests.…`, because a synthetic project's own `tests` package would clash with it in `sys.modules`.

   I prototyped this through `uv run --locked --extra dev pytest`, the console script, against a synthetic project with its own `tests` package. It reported node ids, test files, parametrise ids and skipped modules with reasons, and honoured `-m`.

   test_per_task_verify's JUnit parsing moves onto the same report, so the repo has one typed collection source.
2. **Mark selection stays pytest's own.** `suite_node_ids_matching` keeps passing `-m` to pytest. The report does not carry marks, because re-implementing mark-expression matching over reported marks would be an ad-hoc parser.
3. **One `OrchestratorCommand` value and one process runner** (fk-1abd62632ae1, fk-a0b751097301).
   - tests/_orchestrator_config.py builds the value from the yaml. `verify_command(root, slot)` covers `lint_command`, `type_check_command` and `test_command`. `lane_command(root, name)` asserts the job is the sole one of its name and absorbs `lane_job_directory`'s and `lane_job_enabled`'s rules and asserts. The dark-factory LaneCommand citation then lives in one docstring.
   - One runner starts each command with `sh -c` in the value's directory, in its own session, and kills the process group on timeout. Collect mode only adds `PYTEST_ADDOPTS` and the report option.
   - The probe environment stays a denylist of the caller's venv and uv lock-mode switches, matching how the lane really runs (§2), and adds `DF_VERIFY_ROLE` from the command's role.
4. **"Lane-only" means a directory in `tests/conftest.py::collect_ignore`, now including `e2e`.**
   - The rows read it behaviourally: every `LANE_JOBS` row whose suite is a directory directly under tests/ lists `NEVER_IN_A_DEFAULT_COLLECTION`, and a structural test keeps it so.
   - pyproject addopts' `--ignore=tests/e2e` and the interpreter matrix's `PYTEST_ADDOPTS` ignore are deleted as restatements.
   - The newest-releases `PYTEST_ADDOPTS` stays, but only to carry the floor-test deselect (decision 7).
   - **test_command stays byte-identical.** dark-factory reads it from main's yaml but runs it on each task's tree. A branch cut before γ has no `e2e` in its collect_ignore, and without `--ignore=tests/e2e` its verify would try to import playwright.
   - pvgis stays lane-only through `slow`, the mark for "needs a live service".
5. **The e2e mark comes from the directory** (binding ruling). `tests/e2e/conftest.py::pytest_collection_modifyitems` adds `pytest.mark.e2e` next to `flaky`, and the 23 pytestmarks go.
6. **The network axis stays with task 366** (ruled by Leo in this session). 366 (pending) seeds the live server's weather and drops `e2e` from `_MARKS_OF_TESTS_ALLOWED_ONLINE`, and 387 then un-slows two lifecycle tests. S24 does not duplicate it.

   Once 366 lands, the e2e mark has no consumer left. Lane membership is the directory and network permission is `slow`, and test_command never collects tests/e2e. So leaf θ retires the mark after 366, the way δ retires `integration`.
7. **D23 is enforced by a verify test, and newest-releases deselects it** (ruled by Leo in this session).
   - `test_every_declared_floor_is_the_locked_release` asserts each requirement in `[project].dependencies` and every extra has a `>=` floor equal to the lowest version uv.lock pins for that distribution. Today exactly one version is pinned for each. The failure names the table, the requirement, the locked version and the fix: `name>=<locked>`, then `uv lock`.
   - The floor rule is a property of the committed pyproject/uv.lock pair, which the newest-releases copy breaks on purpose. So that lane runs the verify with `--deselect` on the test's node id and says why. `--deselect` prefix-matches every parametrisation (probed).
   - If the test is renamed, the deselect stops matching. The test then runs in the upgraded copy and the lane goes red, so the coupling cannot fail silently.
8. **`[build-system].requires` is outside D23's referent.** uv.lock does not lock build requirements. `setuptools>=77.0.0` stays as declared, and test_build_system.py goes with the other capability-claim tests. The floor test's docstring says build requirements are out and why (open question 1 asks the lead to confirm).
9. **One mark vocabulary** (ruled by Leo in this session).
   - `integration` is retired from its 14 modules and from pyproject's marker table.
   - pyproject's `[tool.pytest.ini_options]` gains `strict_markers = true`.
   - test_marker_registration.py is deleted whole. That takes its two hand-kept lists, its regex over collect output and its registration greps; the offline guard is the one network mechanism.
   - δ depends on ε, so the pytest floor (9.0.3) guarantees the ini option exists on every pytest the dev range admits.
10. **Static gates.** test_lint lints `src/solar_challenge` and `tests`. The helper type check covers every helper module: each `tests/_*.py` and each module under a `tests/_*/` directory, which takes in decision 1's plugin. The 59 findings, 4 invalid noqa directives, 29 name-defined ignores and 2 helper errors are cleared. Test modules (test_*.py) stay outside mypy, as today; ruff's F821 covers their string annotations.
11. **The yaml's rationale moves to `docs/orchestrator-config.md`, following the precedent of docs/lint-gate.md.**
    - The yaml keeps a header pointer and at most a one-line comment per block.
    - Measured durations are deleted, not moved.
    - What CLAUDE.md already says is not restated; the doc points at CLAUDE.md's bullets instead.
    - CLAUDE.md gains one pointer to the doc. Restructuring CLAUDE.md's lane bullets is out of scope (§9).

## 4. Contract — the two seams S24 owns

### 4.1 Collection report (owner: tests/_collect_only.py with the plugin)

```python
# tests/_collect_only.py  (names tactical; shape binding)
@dataclass(frozen=True)
class CollectedTest:
    node_id: str                  # pytest's nodeid, rootdir-relative
    path: PurePosixPath           # the test file, rootdir-relative
    parametrize_id: str | None    # item.callspec.id; None when not parametrised

@dataclass(frozen=True)
class Collection:
    command: str
    returncode: int
    output: str                                   # stdout + stderr, for describe/"names the fix" checks
    tests: tuple[CollectedTest, ...] | None       # None: pytest wrote no report (it never reached collection's end)
    skipped_modules: tuple[tuple[str, str], ...]  # (module node id, reason) for each module skipped at collection

    def node_ids(self) -> tuple[str, ...]: ...    # asserts tests is not None, naming command and outcome
    def node_ids_outside(self, path: str) -> tuple[str, ...]: ...  # by CollectedTest.path, never by splitting node ids

def collect(command: OrchestratorCommand | ShellCommand, *pytest_args: str, env: Mapping[str, str] | None = None,
            timeout_secs: float = ...) -> Collection: ...
```

Invariants:

- **C1.** `tests` is in collection order, after `-m`, `-k` and `--deselect` deselection; it is `session.items` at `pytest_collection_finish`.
- **C2.** `tests is None` and `tests == ()` are distinct states. The first means pytest never reached the end of collection (uv refused, the shell failed, an import crashed the session), and every reader that needs node ids fails naming the command and its output. A caller never sees it as an empty suite (no-silent-fail-soft).
- **C3.** No reader splits, partitions or regex-parses a node id or collect stdout. `path` and `parametrize_id` are read as fields.
- **C4.** The plugin imports only pytest and the standard library, so it loads in any environment a probed command builds, including uv environments that hold only the dev extra. It is inert unless `--collection-report` is given.
- **C5.** `skipped_modules` comes from `pytest_collectreport` reports whose outcome is skipped and whose collector is a module. Its reason is the skip message, e.g. importorskip's "could not import 'flask'…".

### 4.2 Lane-only suite list (owner: tests/conftest.py::collect_ignore)

- **L1.** `collect_ignore` lists every lane-only directory directly under tests/: `e2e`, `interpreter_matrix`, `css_build` and `newest_releases`. An explicit path argument still collects the directory, as each lane job's command does.
- **L2.** Every `LANE_JOBS` row whose `suite` is a directory directly under tests/ lists `NEVER_IN_A_DEFAULT_COLLECTION`. A structural test over `LANE_JOBS` fails naming a row that does not. The behavioural test (a collection of tests/ with addopts cleared reaches none of the suite) is the reader that keeps L1 honest.
- **L3.** No lane suite restates its own exclusion (`PYTEST_ADDOPTS=--ignore=<suite>`). test_command's `--ignore=tests/e2e` is the one deliberate exception, for config/tree skew (§3 decision 4).

### 4.3 Orchestrator command (owner: tests/_orchestrator_config.py; it is not a program seam, but β's value)

```python
@dataclass(frozen=True)
class OrchestratorCommand:
    label: str          # "test_command", "lane job 'e2e'": what failure messages name
    command: str        # the yaml string, verbatim
    directory: Path     # project root, or the lane job's cwd under it (asserted to be a directory)
    role: str           # DF_VERIFY_ROLE the orchestrator sets: "task" for a verify slot, "offline" for a lane job

def verify_command(project_root: Path, slot: Literal["lint_command", "type_check_command", "test_command"]) -> OrchestratorCommand
def lane_command(project_root: Path, name: str) -> OrchestratorCommand  # sole job of the name, enabled flag a YAML bool and true
def lane_commands(project_root: Path) -> tuple[OrchestratorCommand, ...]  # every job, in config order
```

## 5. Boundary-test sketch

| # | Faces | Scenario | Preconditions | Postconditions |
|---|---|---|---|---|
| B1 | producer | A collection whose output carries a `::` line that is not a test | Synthetic project whose conftest prints `warning: a::b` at collection, with two tests | `Collection.node_ids()` is exactly the two tests' ids. **RED today:** `collected_node_ids` also returns the warning line |
| B2 | producer | Parametrise ids come from the item | Synthetic module parametrised with ids `3.12` and `3.13`, plus one plain test | `parametrize_id`s are `"3.12"`, `"3.13"` and `None`; no string surgery anywhere in tests/ |
| B3 | producer | No report is not an empty suite | A command that fails before pytest starts (`false`), and one that collects nothing (`-k nomatch`) | The first has `tests is None` and `node_ids()` fails naming the command; the second has `tests == ()` |
| B4 | consumer | test_per_task_verify answers its skip question from the report | Synthetic module that importorskips a missing package | `skipped_modules` holds that module with importorskip's reason; tests/unit/test_per_task_verify.py contains no ElementTree |
| B5 | consumer | The interpreter-matrix lane contract reads parametrise ids | Real yaml and real tests/interpreter_matrix | `test_interpreter_matrix_job_collects_one_case_per_off_pin_admitted_minor` passes on `CollectedTest.parametrize_id` |
| B6 | producer | A hung collect probe leaves no process behind | A command that starts a child and sleeps past a short timeout | After the timeout, no process of the probe's group is alive (the pattern of `test_no_process_the_suite_started_outlives_a_hang`). **RED today:** `subprocess.run` kills only the shell |
| B7 | consumer | The lane-only list covers e2e | Real tree | `test_a_default_collection_never_reaches_the_suite[e2e]` passes. **RED before γ:** with addopts cleared, collecting tests/ reaches tests/e2e and fails importing playwright in the verify environment (the failure fix 3d7474f recorded) |
| B8 | consumer | A new lane directory without the contract is caught | LANE_JOBS gains a directory row lacking `NEVER_IN_A_DEFAULT_COLLECTION`, in a scratch edit | The structural test fails, naming the row |
| B9 | producer | The e2e mark comes from the directory | pytester, under copies of the root and e2e conftests, with a module under the e2e copy that has no pytestmark | The module's test carries `e2e` (`get_closest_marker`) and runs outside the offline window (until 366) |

## 6. Existing tasks this PRD meets

| Task | Status | Relation |
|---|---|---|
| 644 | in-progress (merging) | Adds tests/unit/test_dev_extra.py and `mypy>=1.11.0`, and pins warn_unused_ignores in test_surface_forms_type_check.py. ε deletes test_dev_extra.py under D23 and ζ generalises the type-check test, so ε and ζ depend on 644 |
| 655 | pending | The mypy-floor capability rows. Superseded by ε under D23: cancel with `x_superseded_by` ε at decompose, after contract §8 step 1 |
| 657 | pending | One home for the copied floor-test bodies. Superseded by ε: the bodies are deleted, not merged. Cancel with `x_superseded_by` ε |
| 366 | pending (deps 250) | Owns the network half of fk-eec3806e584e (§3 decision 6). At decompose, stamp its metadata `x_finding_key` with fk-eec3806e584e and `x_finding_run`; θ depends on it |
| 387 | pending (deps 366) | Unchanged |

## 7. Cross-PRD relationship

| Other PRD / stream | Direction | Seam mechanism | Owner | Status |
|---|---|---|---|---|
| every stream | consumes | ζ: tests/ is under ruff F and the helper type check. A leaf landing after ζ keeps its test code F-clean and its helpers typed | S24 ζ | queued |
| every stream | consumes | ε: a leaf that adds or re-locks a dependency declares its floor at the version `uv lock` picks, in the same change | S24 ε | queued |
| every stream | consumes | δ: a new pytest mark is registered in pyproject's marker table, or collection fails | S24 δ | queued |
| every stream that adds e2e tests (S18, S21, S17, …) | consumes | γ: a new tests/e2e module carries no `pytestmark = pytest.mark.e2e`; the directory supplies it | S24 γ | queued |
| S23 Surface lock | shares a file family | S23 owns tests/_surface_forms.py's content (its two type-ignores); ζ owns the helper type gate that generalises test_surface_forms_type_check.py. The two only merge as text | S23 (content) / S24 (gate) | queued |
| S15 Weather as explicit input / task 366 | cross-reference only | 366 plans to seed the e2e live server through `set_weather_cache`, which S15 ε retires at S29. 366 should seed through S15's provider once S15 β lands. S24 owns neither | lead | to apply |

No S24 change touches a frozen public name, so S29 is not involved (D29).

## 8. Decomposition plan

Leaves are labelled α–θ; real ids come at decompose. Priority follows each leaf's highest finding severity.

**α — Collection report: one typed collection from an in-repo pytest plugin** (intermediate → β, γ; carries its own signal)

- **Keys:** fk-dd434cb2d4b9 (low).
- **Modules:**
  - the plugin module, in its own directory (suggested: tests/_pytest_plugins/solar_challenge_collection_report.py);
  - tests/_collect_only.py, tests/_lane_collection.py;
  - tests/unit/test_collect_only.py, tests/unit/test_lane_collection_helper.py, tests/unit/test_interpreter_matrix_lane.py, tests/unit/test_per_task_verify.py, tests/unit/test_offline_lane_contracts.py (call sites).
- **Work:**
  - Write the plugin (C4, C5) and `Collection` and `CollectedTest` (§4.1). The probe prepends the plugin directory to `PYTHONPATH`.
  - Delete `collected_node_ids`, `_lies_under`, `_interpreters_named_by`'s rpartition, the `--verbosity=-1` mode and its pin in test_collect_only.py, and `_modules_skipped_at_collection`'s ElementTree parsing.
  - Move every caller onto fields.
- **Signal:** B1 (RED today), B2, B3, B4 and B5. In the per-task verify, test_offline_lane_contracts, test_interpreter_matrix_lane and test_per_task_verify run against the real yaml and pass, reading the report. `grep` over tests/ finds no `"::" in line`, no `rpartition("[")` and no `xml.etree`.
- **Consumer:** the lane and verify contract tests run in every per-task verify; β; γ.
- **Prereqs:** none.

**β — One orchestrator command value and one process runner** (intermediate → γ; carries its own signal)

- **Keys:** fk-1abd62632ae1 (medium, weakened, re-measured §2), fk-a0b751097301 (low, weakened, re-measured §2).
- **Modules:**
  - helpers: tests/_orchestrator_config.py, tests/_collect_only.py, tests/_verify_suite.py, tests/_uv_env.py, tests/_lane_collection.py;
  - helper tests: tests/unit/test_orchestrator_config_helper.py, tests/unit/test_verify_suite_helper.py, tests/unit/test_collect_only.py, tests/unit/test_uv_env_helper.py;
  - call sites: tests/unit/test_stale_uv_lock.py, tests/unit/test_per_task_verify.py, tests/unit/test_offline_lane_contracts.py, tests/interpreter_matrix/test_verify_suite.py, tests/newest_releases/test_verify_suite_on_newest_releases.py.
- **Work:**
  - Build `OrchestratorCommand`, `verify_command`, `lane_command` and `lane_commands` (§4.3). `lane_job_directory` and `lane_job_enabled` fold into `lane_command`, with their asserts and one LaneCommand citation.
  - Write one runner (own session, killpg on timeout, injectable timeout) behind both `collect` and `run_verify_suite`.
  - The probe environment adds `DF_VERIFY_ROLE`.
  - Rewrite the five sites as one-line calls.
- **Signal:** B6 (RED today). `grep` finds no `lane_job_directory`, no `lane_job_enabled`, and no `["test_command"]` or `config[key]` outside tests/_orchestrator_config.py. Exactly one `subprocess.Popen` starts orchestrator commands. A helper test shows a lane command's probe environment carries `DF_VERIFY_ROLE=offline` and a verify slot's carries `task`. test_stale_uv_lock's verify and lane cases still fail naming `uv lock` on a stale lock.
- **Consumer:** test_stale_uv_lock, test_per_task_verify, test_offline_lane_contracts (every verify), and the interpreter-matrix and newest-releases lane jobs (`run_verify_suite`).
- **Prereqs:** α (both rewrite tests/_collect_only.py).

**γ — Lane-only stated once: e2e joins collect_ignore; the e2e mark comes from its directory** (leaf)

- **Keys:** fk-f48c29a98a89 (low), fk-eec3806e584e (medium; the mark half, §3 decision 6).
- **Modules:**
  - tests/conftest.py (`collect_ignore`), tests/e2e/conftest.py (the hook) and the 23 tests/e2e/test_*.py modules (delete `pytestmark`);
  - pyproject.toml (addopts drops `--ignore=tests/e2e`) and tests/interpreter_matrix/test_verify_suite.py (`_suite_env` drops `PYTEST_ADDOPTS`);
  - tests/unit/test_offline_lane_contracts.py (the e2e row lists `NEVER_IN_A_DEFAULT_COLLECTION`; the L2 structural test);
  - one pytester test for the hook (suggested: beside tests/unit/test_e2e_network_change_reruns.py, which already runs copies of the e2e conftest).
- **Work:** §3 decisions 4 and 5, and §4.2. test_command is not edited.
- **Signal:** B7 (RED before), B8 and B9. `grep` finds no `pytestmark = pytest.mark.e2e` under tests/e2e, no `--ignore=tests/e2e` in pyproject.toml and no `PYTEST_ADDOPTS` in tests/interpreter_matrix. The lane's e2e job still collects only tests/e2e (`test_the_job_collects_its_suite_and_nothing_else[e2e]` passes).
- **Consumer:** plain `pytest`, dark-factory's serial and confirm reruns (`-o addopts=`), and tests/conftest.py's offline exemption (until 366).
- **Prereqs:** β (serialises the shared lane helpers and call sites).

**δ — Mark vocabulary: retire `integration`, refuse unregistered marks, delete the hand-kept network lists** (leaf)

- **Keys:** fk-3667e4e32155 (low).
- **Modules:**
  - tests/unit/test_marker_registration.py (deleted);
  - pyproject.toml (the marker table drops `integration`, and `strict_markers = true` is added);
  - the 14 tests/integration modules that apply `pytest.mark.integration` (where a `pytestmark` list carries `slow` too, keep `slow`);
  - test_flex_timeshift.py's "Marked integration (NOT slow)" docstring;
  - one rejection test (suggested: a pytester session under a copy of pyproject.toml, the precedent tests/unit/test_pytest_deprecations_are_errors.py follows).
- **Signal:**
  - Rejection check: a module carrying an unregistered mark fails collection, naming the mark (probed on 9.0.3).
  - `pytest --markers` lists no `integration`, and `grep` finds no `mark.integration` in tests/.
  - The verify stays green with the lists gone; the classes they named stay under the offline guard.
- **Consumer:** every collection (strict markers); the offline guard as the one network mechanism.
- **Prereqs:** ε (the pytest floor 9.0.3 guarantees the `strict_markers` ini option on every admitted pytest).

**ε — D23: every dependency floor is the locked release; the capability-claim tests go** (leaf, **high**)

- **Keys:** fk-e5820c5e22ed (high).
- **Modules:**
  - pyproject.toml and uv.lock;
  - tests/unit/test_dependency_floors.py (new);
  - tests/unit/test_e2e_extra.py, tests/unit/test_build_system.py and tests/unit/test_dev_extra.py (all deleted);
  - tests/_pyproject.py (a lock reader beside `declared_floor`, if the test needs one) and tests/unit/test_pyproject_helper.py;
  - tests/newest_releases/test_verify_suite_on_newest_releases.py: its `PYTEST_ADDOPTS` becomes the floor-test `--deselect`, and the `--ignore` restatement goes;
  - CLAUDE.md: a Key Patterns bullet saying "floors are the lock", and the newest-releases bullet saying a re-lock raises the floors it moves.
- **Work:**
  - Raise all 20 floors to uv.lock's versions, then `uv lock`.
  - Write the floor test (§3 decision 7, with build requirements excluded per decision 8).
  - Delete the three capability-claim files.
- **Signal:**
  - In the verify, `test_every_declared_floor_is_the_locked_release` passes over 20 parametrisations. **RED today:** 19 of 20 below the lock.
  - Rejection check: lowering one floor in a scratch copy fails the test, naming the requirement, its table and the locked version.
  - `git diff uv.lock` changes only solar-challenge's own requires-dist specifiers, with no package version moved.
  - The newest-releases module deselects the floor test by node id and states why.
  - The three capability-claim files are absent.
- **Consumer:** the per-task verify; consumers who re-lock (they get at least what this repo tests); CLAUDE.md readers.
- **Prereqs:** task 644 (out of batch; it creates test_dev_extra.py and raises the mypy floor).

**ζ — The lint and the helper type check cover tests/** (leaf)

- **Keys:** fk-5de02e56b3af (low).
- **Modules:**
  - tests/unit/test_lint.py (lint paths become `src/solar_challenge` and `tests`);
  - tests/unit/test_surface_forms_type_check.py, generalised to every helper module (§3 decision 10; it may be renamed, e.g. test_helper_type_check.py);
  - the 23 files with F findings and the 12 with name-defined ignores (real imports, under `TYPE_CHECKING` where import cost matters);
  - test_flex.py's 4 noqa directives;
  - tests/_css_classes.py and tests/_job_manager_double.py;
  - docs/lint-gate.md (the gate covers tests/).
- **Signal:**
  - `test_the_package_passes_the_lint` (or its successor) lints tests/ and passes. **RED today:** 59 findings in 23 files.
  - The helper type check passes over all 33+ helpers. **RED today:** 2 errors.
  - `grep -rn 'type: ignore\[name-defined\]' tests` finds 0.
  - `ruff check tests` prints no invalid-noqa warning.
- **Consumer:** the per-task verify, which every later leaf of every stream passes through.
- **Prereqs:** task 644 (it edits test_surface_forms_type_check.py).

**η — The orchestrator config's rationale moves to docs; measured durations go** (leaf)

- **Keys:** fk-a9aad5f6d1b2 (low).
- **Modules:** dark-factory-orchestrator.yaml (comments only, no key or value changes), docs/orchestrator-config.md (new) and CLAUDE.md (one pointer).
- **Signal:**
  - `grep -c '^\s*#' dark-factory-orchestrator.yaml` reports at most 15. It is 85 today. The bound allows a two-line header pointer plus one line for each of the eight blocks (cost ceiling, fused_memory, escalation, verify commands, cgroup scope, git, offline-lane jobs, sandbox), which makes 10, with margin.
  - The header names docs/orchestrator-config.md, which exists and holds each setting's reason with no measured duration (`grep -E '[0-9]+ s\b|[0-9]+-[0-9]+ min'` finds nothing).
  - `test_canonical_orchestrator_config_loads` and every lane contract still pass, so the yaml parses to the same mapping.
- **Consumer:** agents reading the yaml or the doc; fix-task readers.
- **Prereqs:** γ, ε (they change the lane facts the prose describes).

**θ — Retire the e2e mark once task 366 takes e2e off the offline exemption** (leaf)

- **Keys:** fk-eec3806e584e (medium; closes the axis split after 366).
- **Modules:**
  - tests/e2e/conftest.py (the hook keeps only `flaky`);
  - pyproject.toml's marker table;
  - dark-factory-orchestrator.yaml's test_command, whose `-m` becomes `'not slow'` while `--ignore=tests/e2e` stays;
  - CLAUDE.md and tests/conftest.py docstrings that still say "slow or e2e";
  - any pytester source that applies `e2e`.
- **Signal:** `pytest --markers` lists no `e2e`, and `grep` finds no `mark.e2e` or `"e2e"` mark use in tests/ or the yaml. The verify, the e2e lane job's collection contract and the offline guard tests pass. B9's pytester test is rewritten to show tests under tests/e2e run inside the offline window.
- **Consumer:** every reader of the mark vocabulary. Lane membership is then the directory, network permission is `slow`, and browser dependency is the directory with the e2e extra.
- **Prereqs:** γ; task 366 (out of batch, pending).
- **Note for the lead:** this could instead be folded into 366's acceptance, if the lead prefers to keep the batch to what can start now.

**Batch DAG:** α → β → γ; 644 → ε → δ; 644 → ζ; {γ, ε} → η; {γ, 366} → θ. ε is the batch's only high leaf, so it becomes a dependency of the trigger-chain gate 772.

**G7 (advisory; solar_challenge has no docs/legibility/design-invariants.md).** I walked the batch against dark-factory's trigger shapes:

- no-silent-fail-soft: C2 keeps "no report" apart from an empty collection, and a renamed floor test fails the newest-releases lane loudly.
- exceptions-owned-or-ratified: the one deselect is owned by ε and ratified in §3 decision 7; test_command's `--ignore` is ratified in decision 4.
- guards-exercise-behaviour: every new guard runs pytest or reads the live pyproject/lock pair, and δ deletes the regex-over-text guard.
- one-fact-one-home: floor == lock is two copies of one version, by D23's choice, with the floor test as the reconciler.
- no-lockstep-duplication: β removes five compositions.

No hits are unresolved.

## 9. Out of scope

- **dark-factory upstream** (fk-a0b751097301's other half):
  - an `orchestrator validate-config` entry point that resolves each job's command, cwd, enabled flag and env;
  - a default-off legacy-numeric seam.

  These belong to dark-factory, not this repo. They are a follow-up candidate for the lead to file there. When one exists, `lane_command` can shell out to it and drop its asserts.
- **A checked timeout relation** (fk-a9aad5f6d1b2's proposal): `timeout_secs` per LANE_JOBS row, with internal timeouts summing below the job's. η deletes the measured numbers, and the relation stays prose in docs/orchestrator-config.md. This is a candidate follow-up.
- **The network axis of the e2e suite**: task 366 (§3 decision 6).
- **Restructuring CLAUDE.md's lane bullets**, so that they stop restating each lane command. η adds only a pointer.
- **Floors for `[build-system].requires`** (§3 decision 8, open question 1).
- **Type-checking test modules** (test_*.py). Only helpers come under mypy.

## 10. Open questions (tactical)

1. **setuptools under D23.** uv.lock does not lock build requirements, so D23's "the locked version" has no referent for `setuptools>=77.0.0`. **Suggested resolution:** keep the declared floor and delete test_build_system.py with the other capability-claim tests. The floor test's docstring says build requirements are out of the lock. The lead confirms this reading of D23 or rules a different floor.
2. **The plugin's directory and module name.** It must load by a top-level module name, not `tests.…` (§3 decision 1). **Suggested:** tests/_pytest_plugins/solar_challenge_collection_report.py. Decide in α.
3. **A fork in uv.lock.** If a future re-lock pins a direct dependency at two versions for different Python markers, the floor is the lower one. The floor test reads the lowest version, which decision 7 already says. Decide the message wording in ε.
4. **The successor names for test_lint's package test and the helper type-check module.** Decide in ζ.
5. **docs/orchestrator-config.md versus the finding's docs/offline-lane.md.** The yaml's prose covers more than the lane (cost ceiling, cgroup scope, sandbox, verify commands), hence the broader name. Decide in η.

## Gate record

- **G1:** every mechanism names its consumer in §8: the collection report, OrchestratorCommand and the runner, collect_ignore e2e, the central mark, the floor test, strict_markers, the widened gates and the doc. Each consumer is a test that runs in every per-task verify or lane job, or a reader-facing artifact.
- **G2:** every leaf names its signal; α and β also carry their own signals, beyond the downstream leaves they unlock.
- **G3:** every substrate was probed or found on main. That covers the plugin hooks and `-p` loading through `uv run`, `--deselect` prefix-matching, `strict_markers` on 9.0.3, `-m` seeing marks a conftest adds, dark-factory's lane environment, and the uv.lock pins. The JUnit premise **failed** G3 and was replaced (§3 decision 1).
- **G4:** §7. S24 owns both of its program seams. The cross-reference lines are returned to the lead.
- **G5:** B with a contract and boundary tests for the owned seams. There are about 9 mechanisms, but all of them sit in the test harness and a single owner holds them.
- **G6:**
  - Numeric bounds have bases: 19 of 20 floors, 59 findings, 2 helper errors, 85 comment lines and η's ≤ 15.
  - The rejection premises (strict_markers, the floor test, C2) were observed or are bound in-leaf.
  - No signal depends on a downstream leaf. δ's needs ε's floor and θ's needs 366, and both are wired as prerequisites.
- **G7:** advisory walk (§8); no hits are unresolved.
- **META:** decompose-and-queue yields one collection reader, one command value and runner, one lane-only list, one network mechanism and floors equal to the lock, with no design question left open. Yes.
