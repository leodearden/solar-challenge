# Orchestrator Configuration: Why Each Setting Is Set

**Config:** [`dark-factory-orchestrator.yaml`](../dark-factory-orchestrator.yaml)

---

## 1. Purpose

`dark-factory-orchestrator.yaml` is configuration, so it carries values and at most a one-line
comment per block. This document holds the reason for each setting. The package defaults
live in dark-factory's `orchestrator/defaults.yaml`; the yaml overrides only what is
project-specific.

It holds no measured durations. A measurement goes stale with the host and the suite, and a
timeout is sized against a bound, not against one run. Where a setting depends on another,
the relation is stated here and the numbers are read from the yaml.

[`CLAUDE.md`](../CLAUDE.md)'s "Dark Factory" section says how to triage a red each offline-lane
job files and how to reproduce it; this document does not restate it.

## 2. Cost Ceiling (`orch_daily_cost_ceiling_usd`)

The package default is a pre-failover backstop. It trips during normal operation now that
per-account Max caps are the real spend governor: spend here is notional, imputed across
flat-rate Max subscription accounts, not metered API billing. Left at the default, the
scheduler pauses itself on architect-heavy days, a false positive. The value mirrors
dark-factory's own `config.yaml`, where it effectively disables the ceiling.

## 3. `fused_memory` and `escalation`

One fused-memory server serves every project, so only `project_id` is per-project and the
URL is shared. The escalation MCP server has a port of its own per project, and it must match
`.mcp.json`, so interactive sessions and the orchestrator share one escalation server.

## 4. Verify Commands (Test, Lint and Type Check)

The commands run inside a fresh git worktree, so they may use nothing that is not committed.
The project is editable-installed into a local, gitignored `venv/` that a worktree lacks, so
each command is a `uv run`, which resolves the pyproject dependencies into an ephemeral
per-worktree `.venv`.

- **`--locked`.** Every `uv run` here and in the offline-lane commands passes it, so uv refuses
  a `uv.lock` that `pyproject.toml` has outgrown, with an error naming the fix (`uv lock`),
  instead of silently re-locking in the worktree. That silent re-lock once let a commit that
  forgot `uv lock` pass verify and merge its stale lock. `tests/unit/test_stale_uv_lock.py`
  guards this.
- **`-m 'not slow'`.** Slow tests need a live service (PVGIS, PyPI, npm, the Anthropic API),
  which does not belong in a per-task verify loop. They run in the offline lane instead (§8),
  and `tests/unit/test_offline_lane_contracts.py` checks that each does, unless it lists the
  test as needing a service no lane job runs it against.
- **`--ignore=tests/e2e`.** The Playwright suite is likewise out of the per-task verify; the
  offline lane's `e2e` job runs it after every merge. The `--ignore` also keeps it out of
  collection on a task tree whose `collect_ignore` predates e2e, because dark-factory runs
  main's test command on each task's tree.
- **`--extra web`.** Every test module that needs the `web` extra calls `pytest.importorskip`,
  so without the extra those modules skip rather than fail, and the verify passes while
  silently losing their coverage. `tests/unit/test_per_task_verify.py` guards this. The
  type-check command takes the extra so `web/*` modules type-check against their real
  dependencies.
- **`lint_command: "true"`.** A no-op: the lint runs in the test suite. `docs/lint-gate.md`
  says why.

`CLAUDE.md`'s "Offline fast tests" and "Floors are the lock" bullets say what the suite
assumes of the environment.

## 5. The Verify Timeout (`verify_command_timeout_secs`)

The warm per-command timeout that task verifies and the main-tip sweep run under. It is
restart-tier: it takes effect at the next orchestrator restart.

A task verify that only times out is rerun `verify_timeout_retries` times (dark-factory's
default, not overridden here), so it fails after `verify_timeout_retries + 1` timeouts. A hung
task verify therefore costs that many times the timeout before it fails.

## 6. Cgroup Scope (`verify_use_cgroup_scope`)

Verify legs run in `df-verify-<project>-*.scope` systemd units, each weighted by its role
(merge, task, background) through dark-factory's `verify_cgroup_cpu_weight_*` settings; the
weights are read there, not copied here. Without the scope, this project's task verifies
share the service unit's CPU weight with its agents and out-weigh other projects' task legs.
The flag is restart-tier; the weights are hot-reloadable.

Source: dark-factory `plans/verify-rate-improvement-2026-10-09/MEMO.md`, item 14.

## 7. Merge-Verify Runners

`verify_runners`, `verify_host_policy`, `verify_drift_check_every_n_lands`,
`verify_cross_check_remote_green` and `verify_env_probes` are explained in
`docs/laptop-merge-verify.md`: why merge verifies run on `leo-laptop` first and here when the
laptop is busy, benched or unreachable, what lives on the laptop, what the env probes compare,
which keys take effect when, and how to roll back.

## 8. `git` and the Offline Lane

`main_branch`, `branch_prefix`, `remote` and `worktree_dir` are the branch layout.

After every merge to main the offline lane runs each `offline_lane_commands` job in order, off
the merge path at idle priority. It never gates a merge. A confirmed red files a fix task
naming the failing node-ids, unless the job's `outage_probe` reports an outage, which is
escalated instead. Each job whose suite needs a live service declares `scripts/outage_probe.py`,
naming that service, as its `outage_probe`; the script defines what counts as an outage.
`outage_probe_timeout_secs` is pinned beside each probe, not left to dark-factory's default,
because the probe's request timeout is sized to fit it. Each probe runs as
`uv run --locked --extra dev`, since the script needs requests from the dev extra and
`solar_challenge` for the PVGIS request, so it starts only once uv has synced the job's
environment. If PyPI is out of reach while `uv.lock` pins a file this host's uv cache lacks,
the job's own sync fails, and so does the probe's: the lane reads a broken probe, so the red
goes to its confirm and is filed, with a broken-probe escalation beside it.

- **`interpreter-matrix`.** The verify suite on each Python minor `requires-python` admits,
  except the `.python-version` pin. Its probe asks PyPI, whose files a case's locked sync
  downloads whenever `uv.lock` changes.
- **`e2e`.** The non-slow Playwright suite. `LaneCommand` has no timeout field and the lane is
  single-flight, so without the `timeout` prefix a hung browser run would stall every later
  lane run. The prefix is sized as a generous multiple of the run, not at the run. Its suite
  needs no live service, so it declares no probe.
- **`pvgis`.** The PVGIS contract tests, `tests/integration/test_pvgis.py`. They check PVGIS's
  live TMY, so a change in PVGIS or pvlib is seen and an outage is never a silent green. Its
  probe asks PVGIS. The `timeout` prefix caps a hung request.
- **`css-build`.** Rebuilds `static/dist/style.css` in a scratch copy from the committed sources
  and `package-lock.json` (`tests/css_build`), and goes red when the committed file differs,
  for example after an unrebuilt `tailwind.config.js` edit, or when the Tailwind license texts
  beside it are not the locked tailwindcss package's. It also rebuilds `static/dist/favicon.svg`,
  which `build-favicon.js` draws in the theme's primary-500, and goes red when the committed
  favicon differs, for example after an accent edit in `static/src/theme-tokens.json` committed
  without `npm run build:favicon`. It needs npm and
  `registry.npmjs.org`, which its probe asks. The `timeout` prefix caps a hung run.
- **`newest-releases`.** Re-runs the verify suite in a scratch copy whose `uv.lock` is upgraded
  to the newest releases `pyproject.toml`'s ranges admit (`tests/newest_releases`), the
  releases a consumer that re-locks installs, so an upstream release that breaks this code
  files a fix task. It needs PyPI, which its probe asks. Like `interpreter-matrix` it has no
  `timeout` prefix: its suite timeout bounds a hang.

The legacy numeric and infra seams (`offline_lane_legacy_numeric_enabled`,
`offline_lane_infra_enabled`) are off because this repo has neither script they run.
`tests/unit/test_offline_lane_contracts.py::test_offline_lane_starts_and_skips_the_seams_this_repo_lacks`
keeps them off and names both.

`offline_lane_enabled` and `persistent_offline_deep_worktree` take effect at orchestrator
restart (the fleet redeploy applies them); `offline_lane_commands` is hot-reloadable.

## 9. Sandbox

`sandbox` turns on the Landlock OS filesystem sandbox: kernel-enforced, whole-filesystem
read-only except each task's own writable scope. The backend is pinned to `landlock`, the
proven fleet backend; `bwrap` is effectively dead fleet-wide. The rollout is dark-factory's
`os-sandbox-worktree-containment` PRD, fleet-remainder wave, gated on the reify wave.
`sandbox.*` is not in the config hot-reload allowlist, so an edit is inert until the next
orchestrator restart, which the scheduled fleet redeploy performs; no separate deploy task is
needed.

## 10. Enforcement Flags

- **`convert_to_blocked_enforce`.** Enforces strand conversion (task 3539) fleet-wide, by
  Leo's ruling of 2026-10-18 on `esc-3546-1` (task 3546, the mu gate). Restart-only.
- **`workflow_exit_contract_enforce`.** Enforces the `run()`-exit contract (task 3542)
  fleet-wide, by Leo's ruling E of 2026-10-20 (dark-factory task 7255), after a clean soak
  following task 3113's deploy. Restart-only, so it goes live at the next fleet restart.
