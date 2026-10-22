# Capability manifest — Lane harness (review-all S24)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/lane-harness-one-collection-source.md`: every capability a leaf's signal asserts is bound to evidence. Its machine-readable twin is `docs/prds/lane-harness-one-collection-source.capability-manifest.yaml`.

**Code anchors** verified against main `962552956508` (2026-10-15). Main moves fast: anchors cite symbols, so re-locate lines at implementation time. Probes ran under pytest 9.0.3 and uv 0.11.6, in a fresh uv environment synced from this repo's uv.lock with the dev extra.

**Batch verdict: PASS, after one premise correction.** The synthesis's JUnit-XML collection source failed G3. The probe showed that a collect-only JUnit report holds no collected test. The PRD replaces it with an in-repo plugin (§3 decision 1, ruled by Leo), whose substrate is bound below. No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short` or `rejection-absent`. Out-of-batch producers: task 644 (in-progress, merging) for ε and ζ, and task 366 (pending) for θ.

## α — Collection report: one typed collection from an in-repo pytest plugin

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| JUnit XML cannot be the collection source (the premise behind the decision) | probe: `pytest --collect-only --junitxml` on a module with a plain, a parametrised and a class test, plus an importorskip module, wrote one testcase (the skipped module); the same under `-m` | FAIL for JUnit, so it is replaced |
| A plugin loaded by `-p <top-level module>` from a `PYTHONPATH` directory runs under `uv run … pytest` (the console script, not `python -m`) | probe: `PYTEST_ADDOPTS="--collect-only -p solar_challenge_collection_report --collection-report=…"`, with `PYTHONPATH` set to the plugin directory, gave exit 0 and the report written | PASS |
| It does not clash with a probed project's own `tests` package | probe: the same run on a synthetic project with `tests/__init__.py` and `tests/conftest.py` collected every test | PASS |
| `pytest_collection_finish` sees `session.items` after `-m` deselection | probe: with `-m 'not slow'`, the report listed 3 of 4 tests | PASS |
| `item.callspec.id` gives parametrise ids | probe: ids `3.12` and `3.13` reported; a plain test reported `null` | PASS |
| `pytest_collectreport` gives the skipped modules with their reasons (B4) | probe: `tests/test_skipmod.py` reported with "could not import 'nonexistent_mod_xyz'…" | PASS |
| The `::` filter, the rpartition, the ElementTree parsing and the `--verbosity=-1` mode exist to delete | grep: `_collect_only.collected_node_ids`, `test_interpreter_matrix_lane._interpreters_named_by`, `test_per_task_verify._modules_skipped_at_collection`, and `run_collect_only`'s `PYTEST_ADDOPTS` | PASS |
| B1 is a real RED: a `::` line that is not a test reads as one | grep: `collected_node_ids` returns `[line for line in listing.splitlines() if "::" in line]` | PASS (RED by construction) |

## β — One orchestrator command value and one process runner

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| Five hand compositions exist to collapse | grep: `_lane_collection.collect_lane_job`, `test_stale_uv_lock.test_each_lane_job_refuses_a_stale_lock_naming_uv_lock`, `test_per_task_verify._collect_with_test_command`, `test_stale_uv_lock.test_the_verify_refuses_a_stale_lock_naming_uv_lock` (`config[key]`), `_verify_suite.run_verify_suite` (`["test_command"]` + Popen) | PASS |
| B6 is a real RED: the collect runner kills only the shell on timeout | grep: `run_collect_only` → `subprocess.run(command, shell=True, …, timeout=300)`; `subprocess.run` kills only its direct child on timeout | PASS (RED by construction) |
| The process-group discipline exists to share | grep: `_verify_suite.run_verify_suite` (`start_new_session=True`, `_kill_process_group` → `os.killpg`); `test_verify_suite_helper.test_no_process_the_suite_started_outlives_a_hang` is the test pattern | PASS |
| dark-factory's lane command rules to fold in: cwd default '.', enabled default True, `sh -c`, `DF_VERIFY_ROLE=offline` | grep in dark-factory: `orchestrator/src/orchestrator/config.py::LaneCommand` (cwd, enabled); `offline_lane.py` env `{**os.environ, 'DF_VERIFY_ROLE': 'offline'}` | PASS |
| The lane runs in the orchestrator's whole environment, so a denylist probe environment is faithful (the weakened re-measure) | grep: same `offline_lane.py` env construction | PASS |
| The stale-lock tests keep their `uv lock` verdicts through the new value | producer: β rewrites them; their offline-cache fixture is unchanged | PASS (bound in-leaf) |

## γ — Lane-only stated once; the e2e mark comes from its directory

*Amended 2026-10-22, task 875: the row below citing `NEVER_IN_A_DEFAULT_COLLECTION` is authoring-time evidence, kept as history. That flag no longer exists; the default-collection contract is derived from each row's suite path (see the PRD's header amendment).*

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| A mark added in a subdirectory conftest's `pytest_collection_modifyitems` is seen by `-m` and by `get_closest_marker` | probe: a hook-added `e2e` mark selected by `-m e2e` and deselected by `-m 'not e2e'`; tests/conftest.py's exemption reads `item.get_closest_marker` at run time | PASS |
| The existing hook walks every item under tests/e2e | grep: `tests/e2e/conftest.py::pytest_collection_modifyitems` adds `flaky` when `item.path.is_relative_to(Path(__file__).parent)` | PASS |
| An explicit path overrides `collect_ignore` (the lane job still collects tests/e2e) | *(historical, task 875 — see the γ amendment)* grep: the css-build and newest-releases rows list both `COLLECTS_ONLY_ITS_SUITE` and `NEVER_IN_A_DEFAULT_COLLECTION` and pass on main | PASS |
| B7 is a real RED: a collection with addopts cleared reaches tests/e2e | grep: `collect_ignore` lacks `e2e`; `default_collection_node_ids_under` clears addopts; fix 3d7474f recorded the playwright ImportError | PASS (RED by construction) |
| 23 pytestmarks exist to delete | grep: `pytestmark = pytest.mark.e2e` in 23 tests/e2e/test_*.py | PASS |
| The pytester copy pattern for the e2e conftest exists (B9) | grep: `tests/unit/test_e2e_network_change_reruns.py` runs copies of tests/e2e/conftest.py; that conftest imports nothing from playwright | PASS |
| `--ignore=tests/e2e` stays in test_command (decision 4) | grep: present in `dark-factory-orchestrator.yaml` test_command | PASS (kept) |

## δ — Mark vocabulary

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| `strict_markers = true` makes an unregistered mark a collection error (rejection mechanism) | rejection-check: pytest 9.0.3 with `strict_markers = true` and `@pytest.mark.slwo` gave `ERROR … 'slwo' not found in markers configuration option`, exit 2 | PASS (rejection observed) |
| The ini option exists on every pytest the dev range admits | producer: ε raises the pytest floor to 9.0.3, the release probed, and ε is upstream of δ | PASS |
| Every mark in use is registered or built in, so strict mode breaks nothing | grep: marks in tests/ are parametrize, slow, usefixtures, e2e, integration, build, skipif, filterwarnings and flaky (rerunfailures registers flaky) | PASS |
| `integration` has no consumer | grep: no `-m` expression naming it in the yaml, CLAUDE.md, pyproject or tests; applied in 14 modules, 5 of them not slow | PASS |
| The offline guard alone fails a non-slow test that reaches the network | grep: `tests/conftest.py::pytest_runtest_protocol` and `pytest_runtest_teardown` | PASS |

## ε — D23: every dependency floor is the locked release

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| uv.lock pins each of the 20 direct requirements at one version | probe: tomllib over uv.lock gives one version per core, dev, web and e2e distribution; no direct dependency is forked | PASS |
| 19 of 20 floors sit below the lock (the RED) | probe: only pytest-rerunfailures 16.7 equals its lock | PASS |
| Raising floors to the lock leaves every locked version unchanged | the current resolution satisfies floor == lock; resolution markers fork only by Python ≥ 3.14 and platform, and no direct dependency is forked | PASS |
| `[build-system].requires` is not in uv.lock (decision 8) | probe: no setuptools or wheel package in uv.lock | PASS |
| `--deselect <function node id>` deselects every parametrisation | probe: `--deselect=tests/test_a.py::test_two` deselected `test_two[3.12]` and `test_two[3.13]` | PASS |
| newest-releases runs the verify on an upgraded lock with the original pyproject (why the deselect is needed) | grep: `test_verify_suite_on_newest_releases` → `uv lock --upgrade`, then `run_verify_suite` | PASS |
| test_dev_extra.py exists to delete | producer: task 644 (out of batch, merging); ε depends on 644 | PASS |
| A lowered floor fails the test naming the requirement and the lock (rejection) | bound in-leaf: ε's scratch-copy RED | PASS (bound in-leaf) |

## ζ — The lint and the helper type check cover tests/

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| 59 F findings in 23 files, plus 4 invalid noqa directives (the RED) | ran: `ruff check --no-cache tests --output-format json` (0.16.10) → F821 44, F401 11, F841 3, F541 1; warnings at test_flex.py `# noqa: no assignment …` ×4 | PASS |
| 29 name-defined ignores in 12 files | ran: `grep -rn 'type: ignore\[name-defined\]' tests` | PASS |
| 2 helper type errors among the 32 unchecked helpers | ran: `mypy --cache-dir=/dev/null` over tests/_*.py minus `_surface_forms.py` → `_css_classes.py` (misc), `_job_manager_double.py` (no-any-return) | PASS |
| The type-check test to generalise | producer: task 644 edits `tests/unit/test_surface_forms_type_check.py`; ζ depends on 644 | PASS |

## η — The orchestrator config's rationale moves to docs

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| 85 of 134 yaml lines are comments carrying measured durations | ran: `grep -c '^\s*#'` → 85; `214 s`, `~20 s`, `17-38 s`, `17-19 min` present | PASS |
| ≤ 15 comment lines is achievable | basis: a two-line header plus one line for each of 8 blocks makes 10 | PASS |
| The yaml still parses to the same mapping | grep: `tests/unit/test_orchestrator_config.py::test_canonical_orchestrator_config_loads`; comment-only edits | PASS |
| The docs/lint-gate.md precedent | grep: `lint_command`'s comment points at docs/lint-gate.md | PASS |

## θ — Retire the e2e mark after task 366

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| After 366, nothing consumes the e2e mark | producer: 366 drops `e2e` from `_MARKS_OF_TESTS_ALLOWED_ONLINE` (its description, WORK step 2); test_command never collects tests/e2e (`--ignore=tests/e2e`, plus γ's collect_ignore) | PASS (366 upstream) |
| The hook keeps `flaky` | grep: `tests/e2e/conftest.py::pytest_collection_modifyitems` | PASS |
