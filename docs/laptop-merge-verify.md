# Merge and Task Verifies on leo-laptop

**Task:** #606, #1271
**Config:** [`dark-factory-orchestrator.yaml`](../dark-factory-orchestrator.yaml), the `verify_runners` block and its neighbours

---

Dark Factory's `SETUP.md` §12, "Optional: a remote merge-verify host", in `/home/leo/src/dark-factory`, describes the
generic mechanics: runners, the per-host yaml contract, gate checkouts and benching. Its subsection "Remote task
verifies on the same host" and `OPERATIONS.md` §"Remote task verifies" cover the task-verify side: the `verify_task_*`
keys, the dispatch record and rollback. This page covers only what is particular to this project. The measurements,
from versions and memory peaks to the pre-flight results, are in the commit messages of task 606 for merge verifies
and task 1271 for task verifies: `git log --grep='(606)'` and `git log --grep='(1271)'`.

## 1. What Runs Where

- Merge verifies go to leo-laptop first (`verify_host_policy: prefer_remote`). This workstation takes one when the
  laptop's slot is busy, benched or parked, and re-runs any verify the laptop could not answer, so the merge queue
  never stalls on the laptop.
- Every 10th land, the drift check runs the same merge on both hosts and compares their verdicts
  (`verify_drift_check_every_n_lands`). At the same cadence, `verify_env_probes` compares the declared tools on the
  two hosts.
- The per-land cross-check is off (`verify_cross_check_remote_green: false`). It is set explicitly because Dark
  Factory's default is true, which would re-run every laptop green on this host and so offload nothing.
- Every task verify may run on the laptop too (`verify_task_host_policy: remote_all`). The yaml declares no modules,
  so it has no module list to choose from, and no per-module `verify_env` or `scope_cargo`: Dark Factory cannot carry
  those to a remote host, and keeps every task verify of a project that has one local.
- A task verify queues on both hosts at once and runs on whichever grants it a turn first.
- `verify_admission_task_slots` bounds how many of this project's task verifies the laptop runs at once, and it is read
  on both sides. `dark-factory-orchestrator.yaml`'s value sizes the dispatcher's turns on the laptop, as it sizes this
  workstation's own task slots, and the host yaml's sizes the slot `orchestrator verify-task` takes there (§2).
  Neither file sets it, so Dark Factory's default applies to both.
- Task and merge verifies do not arbitrate, on the laptop as here: a task verify takes no merge slot, and the only
  priority between them is Dark Factory's `verify_cgroup_cpu_weight_*` settings, which favour merges.
- Both parity knobs are on for this project's first window of remote task verifies:
  - A laptop red re-runs here, and the local verdict is the one returned (`verify_task_remote_red_confirms_locally`).
  - Every 5th verify that returns a laptop verdict, green or red, also runs here, and the local verdict is
    authoritative (`verify_task_remote_cross_check_every_n`).
  - Each re-run records both verdicts in the task's dispatch record (§4).
  - They are on because the window is this project's first, and because §3 describes a red that only the laptop
    produces. Turning them off takes a ruling on this project's own window, as it did on Dark Factory's.
- The offline lane stays on this workstation.

Why: to take CPU load off the workstation (dark-factory `plans/verify-rate-improvement-2026-10-09/MEMO.md` §3 item 7).
Task verifies joined merge verifies once Dark Factory's own window of remote task verifies had passed, as Leo ruled on
2026-11-03 (dark-factory `plans/remote-task-leg-verify-prd.md`).

## 2. What Lives on the Laptop

- **The clone**, `/home/leo/src/solar-challenge`:
  - It is a real directory on the root filesystem. The verify-scope tag hashes the resolved project path, and uv
    hardlinks from `~/.cache/uv`, which needs one filesystem. A symlink to another disk breaks both.
  - Its only remote is `workstation`, with `receive.denyCurrentBranch=updateInstead`. The dispatcher's push keeps it
    current, so it must stay on `main` with no tracked edits.
  - Its `.venv` is only for reproducing a red by hand (§5). A dispatched verify runs in a fresh worktree.
- **The host yaml**, `~/.config/orchestrator/solar-challenge-laptop.yaml`, which `orchestrator verify-merge` and
  `orchestrator verify-task` both read:
  - It holds the keys the host reads, such as `project_root`, `git.remote` and §3's cache warm-up. Never restate the
    verify commands or `verify_env` there: the spec the workstation sends carries them, and the spec's copy wins.
  - Its `verify_admission_task_slots` is the laptop's half of §1's bound on task verifies. More of them run there at
    once only when both halves are raised. Raising only `dark-factory-orchestrator.yaml`'s value moves the wait into
    the laptop's slot, and widens this workstation's own task slots too (dark-factory
    `plans/remote-task-leg-verify-prd.md`, decision 14).
- **The scope drop-ins**, in `~/.config/systemd/user/df-verify-solar-challenge-e0fb1248-.scope.d/`:
  - `memory-max.conf` applies the laptop memory policy of 2026-10-09, with `MemoryHigh` sized by dark-factory task
    5415's rule.
  - `cpu-quota.conf` is the 8-thread cap of dark-factory's 2026-09-11 ruling Q2. It is a CPU quota because the suite
    has no xdist: a quota is the one cap that also binds `fleet.py`'s process pools and BLAS threads.
  - Read the files for the values and how they were measured.
  - They cap task-verify scopes as well as merge-verify ones, because the tag is the project's, not the role's.
  - The tag is Dark Factory's slug plus a hash of the resolved `project_root`. The hash keeps these drop-ins off
    solar-challenge-platform's `df-verify-solar-challenge-platform-74bd33ed-*` scopes. Moving the clone changes the
    tag, and a drop-in under the wrong tag is silently ignored.
- **The Dark Factory gate checkouts**, under `/home/leo/src/dark-factory-gate`. The dispatcher builds them and shares
  them with dark-factory, reify and solar-challenge-platform.

To rebuild: clone, `uv sync --locked --extra dev --extra web`, the host yaml, the drop-ins, then
`systemctl --user daemon-reload`. Then prove the host as task 606 did: run the real gate on the laptop, and diff its
per-test outcomes against a workstation run of the same commit (`git log --grep='(606)'`).

## 3. Why the Laptop Warms uv's Cache Before Every Verify

Some tests run uv offline under `tests/conftest.py`'s network guard, so they read wheels and index pages only from the
host's uv cache: the lane collections of `tests/unit/test_offline_lane_contracts.py`, e2e included, and
`tests/unit/test_stale_uv_lock.py`. Agents and the offline lane keep this workstation's cache warm; nothing else warms
the laptop's. Without a warm-up, the next dependency change would turn laptop verifies red while they pass here.

So the host yaml's `verify_cold_preprovision_command` syncs every extra and refreshes the index before each verify on
the laptop, merge or task:

- The sync is `--locked`, so it never rewrites `uv.lock` and cannot hide a stale lock.
- It targets a scratch environment, which keeps the `e2e` extra out of the verify's own `.venv`.
- It runs with `--all-extras` in the verify's worktree, so it follows each commit's own lock.

It runs before task verifies too: a task verify's worktree on the laptop starts with a fresh `.task/`, which Dark
Factory reads as cold, and a cold verify runs the warm-up first.

It is laptop-only. `dark-factory-orchestrator.yaml` sets no `verify_cold_preprovision_command`, so the merge and task
specs both ship an empty one and Dark Factory keeps the laptop's own. If that file ever sets one, Dark Factory runs it
on the laptop instead, and the warm-up must move into it.

## 4. Checks

- The host answers: `SETUP.md` §12's two probes, under "Checking the host answers", against `leo-laptop`.
- The host yaml parses: `ssh leo-laptop orchestrator check-config --config
  ~/.config/orchestrator/solar-challenge-laptop.yaml` exits 0 with no unknown key.
- The clone is current: after a dispatch, `git ls-remote leo-laptop refs/heads/main` equals `git rev-parse main`, and
  `git status --porcelain` in the laptop clone is empty.
- The caps bind: while a verify runs, a live `df-verify-solar-challenge-e0fb1248-*.scope` under
  `/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/` shows the drop-ins' values in its
  `memory.high`, `memory.max`, `memory.swap.max` and `cpu.max`.
- The runner serves: `merge_verify` events whose `data.runner` is `laptop` appear in `data/orchestrator/runs.db`.
  Their `data.duration_ms` gives the hours per host.
- The runner serves task verifies: `workflow_verify` events whose `data.runner` is `laptop` appear in the same
  database. Each task verify the dispatcher considers also leaves a dispatch record beside its logs,
  `data/verify-logs/<task>/attempt-N.dispatch-<stamp>.json`. One that returned the laptop's verdict reads
  `decision: remote`, `runner: laptop` and `reason: remote`, and the laptop's streams sit beside it as
  `attempt-N.remote-laptop.*`. Any other `reason` reads `decision: local` and `runner: local`, because this
  workstation's verdict was returned. Dark Factory's `DispatchReason`, in its
  `orchestrator/src/orchestrator/task_verify_dispatch.py`, is the authority for these values:
  - `local_granted_first`: this workstation granted a turn first.
  - `not_eligible`: this verify could not go remote: a whole-workspace verify, one whose changed files could not be
    derived, or any verify once a module gains a per-module override (§1).
  - `no_host`: the orchestrator offered no remote host, as when it cannot resolve its own deployed commit.
  - `dirty_tree`, `runner_unavailable` and `infra_transient`: the laptop's turn came, but the verify ran here after
    all, because the task's worktree had uncommitted work, the laptop gave no verdict, or its verify failed in one of
    Dark Factory's infra-transient categories.
  - `dispatcher_error`: the dispatcher could not derive the verify's scope, or failed.
  - `cross_check` and `red_confirm`: a parity knob re-ran a laptop verdict here (§1). The record's `cross_check`
    holds both verdicts and whether they `agree`; its `red_confirmed_locally` holds this workstation's verdict on a
    laptop red.
- Drift outcomes, in the same database:
  - `verdict_parity_ok` when the hosts agree.
  - A verdict split is an L1 of category `verify_drift_divergence`, and it quarantines the laptop. Clear that with
    `mcp__escalation__clear_verify_host_quarantine` once parity is restored.
  - `drift_check_deferred` when the check could not get both hosts.
  - `verify_env_parity_ok` or `verify_env_divergence`. A divergence files one deduped L1 and never quarantines. Every
    probe printed the same on both hosts when the runner was enabled, so a divergence means a tool has changed on one
    host since, or that the laptop clone lags a pin change (next bullet).
- The interpreter probes, `uv-python` and `uv-run-python`, follow the pin, so the yaml names no Python version. They
  read `.python-version` from each host's checkout at `project_root` and report the interpreter a fresh verify would
  get. `--system` and `--isolated` keep the checkout's own `.venv` out of the answer, and `--no-python-downloads` stops
  a probe from installing an interpreter. Each merge verify sent to the laptop first pushes `main` to the clone, but
  the drift check runs its env probes before its own dispatch. So the first drift check after a `.python-version`
  change can see the two hosts on different interpreters: that divergence is the clone's lag, not a skew.
- tzdata is deliberately not an env probe: it updates on the two hosts at different times, and the suite uses only
  zones whose rules have long been stable. When a red involves time zones, compare `dpkg-query -W tzdata` on both
  hosts by hand. The versions when the runner was enabled are in the 606 commits.

## 5. Reading and Reproducing a Laptop Red

The `merge_verify` event's `data.runner` names the host that ran a verify. A red with runner `laptop` that does not
reproduce on this workstation may come from the laptop's environment. In the verdict, a leg that passed has an empty
`lint_output` or `type_output`: Dark Factory keeps a leg's output only when the leg fails.

A task verify's laptop red does not reach the task while red-confirm is on (§1): it re-runs here, and the verdict the
task sees is this workstation's. A verdict the two hosts split on, whichever was red, is a parity split. The task's
dispatch record shows it as a `red_confirmed_locally` whose `local_passed` is true, or a `cross_check` whose `agree` is
false (§4). Reproduce it on the laptop as for a merge red, below.

To reproduce the whole gate on the laptop, as task 606's pre-flight did:

1. Push the commit to a namespaced ref: `git push leo-laptop <sha>:refs/merge-verify/<label>`.
2. Build the spec on this workstation with Dark Factory's own builder, `build_merge_verify_spec(cfg,
   list(cfg.module_configs_or_empty.values()), None)`, where `cfg` is `load_config` of this repo's
   `dark-factory-orchestrator.yaml`. Copy `spec_to_json` of it to a file on the laptop.
3. On the laptop, run `orchestrator verify-merge --sha <sha> --spec "$(cat <spec file>)" --config
   ~/.config/orchestrator/solar-challenge-laptop.yaml`. It prints the verdict as JSON on stdout and logs on stderr.
4. Delete the ref: `git push leo-laptop :refs/merge-verify/<label>`.

To run one node-id, push the commit as in step 1, then on the laptop run
`git -C /home/leo/src/solar-challenge worktree add --detach /tmp/<dir> <sha>`, then
`uv run --locked --extra dev --extra web pytest <node-id>` in that directory, then `git worktree remove` it. Never move
the clone's own HEAD. A non-login `ssh leo-laptop '<command>'` does not put `~/.local/bin`, where uv lives, on PATH
(`SETUP.md`'s "Non-login-ssh PATH trap").

## 6. Rollback, Tiers and the Parity Rule

- Stop sending merge verifies to the laptop now: set `verify_host_policy: prefer_local`, commit, then call
  `mcp__escalation__reload_config`. The key is green tier, so the change takes effect at the next dispatch.
- Stop sending task verifies to the laptop now: set `verify_task_host_policy: local`, commit, then call
  `mcp__escalation__reload_config`. The `verify_task_*` keys are green tier too: the next task verify runs here, and
  one already running on the laptop finishes there. To stop both at once, make both edits before the one reload.
- Remove the runner: set `enabled: false` on the `laptop` entry, or drop the block, then restart the orchestrator.
  `verify_runners`, `verify_drift_check_every_n_lands` and `verify_env_probes` are restart-tier; Dark Factory's
  `OPERATIONS.md` §6, "Config reload vs restart", is the authority.
- None of these touches the laptop's files.

Parity rule: a local red with a laptop green, or the reverse, that reproduces on the same commit means `prefer_local`
the same day, then escalate. Do not wait for the next drift check. For a task verify, whose split shows in its
dispatch record (§5), it means `verify_task_host_policy: local` the same day, then escalate.
