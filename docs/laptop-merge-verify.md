# Merge Verifies on leo-laptop

**Task:** #606
**Config:** [`dark-factory-orchestrator.yaml`](../dark-factory-orchestrator.yaml), the `verify_runners` block and its neighbours

---

Dark Factory's `SETUP.md` §12, "Optional: a remote merge-verify host", in `/home/leo/src/dark-factory`, describes the
generic mechanics: runners, the per-host yaml contract, gate checkouts and benching. This page covers only what is
particular to this project. The measurements, from versions and memory peaks to the pre-flight result, are in task
606's commit messages: `git log --grep='(606)'`.

## 1. What Runs Where

- Merge verifies go to leo-laptop first (`verify_host_policy: prefer_remote`). This workstation takes one when the
  laptop's slot is busy, benched or parked, and re-runs any verify the laptop could not answer, so the merge queue
  never stalls on the laptop.
- Every 10th land, the drift check runs the same merge on both hosts and compares their verdicts
  (`verify_drift_check_every_n_lands`). At the same cadence, `verify_env_probes` compares the declared tools on the
  two hosts.
- The per-land cross-check is off (`verify_cross_check_remote_green: false`). It is set explicitly because Dark
  Factory's default is true, which would re-run every laptop green on this host and so offload nothing.
- Task verifies and the offline lane stay on this workstation.

Why: to take CPU load off the workstation (dark-factory `plans/verify-rate-improvement-2026-10-09/MEMO.md` §3 item 7).

## 2. What Lives on the Laptop

- **The clone**, `/home/leo/src/solar-challenge`:
  - It is a real directory on the root filesystem. The verify-scope tag hashes the resolved project path, and uv
    hardlinks from `~/.cache/uv`, which needs one filesystem. A symlink to another disk breaks both.
  - Its only remote is `workstation`, with `receive.denyCurrentBranch=updateInstead`. The dispatcher's push keeps it
    current, so it must stay on `main` with no tracked edits.
  - Its `.venv` is only for reproducing a red by hand (§5). A dispatched verify runs in a fresh worktree.
- **The host yaml**, `~/.config/orchestrator/solar-challenge-laptop.yaml`, holds the keys the host reads, such as
  `project_root`, `git.remote` and §3's cache warm-up. Never restate the verify commands or `verify_env` there: the
  spec the workstation sends carries them, and the spec's copy wins.
- **The scope drop-ins**, in `~/.config/systemd/user/df-verify-solar-challenge-e0fb1248-.scope.d/`:
  - `memory-max.conf` applies the laptop memory policy of 2026-10-09, with `MemoryHigh` sized by dark-factory task
    5415's rule.
  - `cpu-quota.conf` is the 8-thread cap of dark-factory's 2026-09-11 ruling Q2. It is a CPU quota because the suite
    has no xdist: a quota is the one cap that also binds `fleet.py`'s process pools and BLAS threads.
  - Read the files for the values and how they were measured.
  - The tag is Dark Factory's slug plus a hash of the resolved `project_root`. The hash keeps these drop-ins off
    solar-challenge-platform's `df-verify-solar-challenge-platform-74bd33ed-*` scopes. Moving the clone changes the
    tag, and a drop-in under the wrong tag is silently ignored.
- **The Dark Factory gate checkouts**, under `/home/leo/src/dark-factory-gate`. The dispatcher builds them and shares
  them with dark-factory, reify and solar-challenge-platform.

To rebuild: clone, `uv sync --locked --extra dev --extra web`, the host yaml, the drop-ins, then
`systemctl --user daemon-reload`. Then prove the host as task 606 did: run the real gate on the laptop, and diff its
per-test outcomes against a workstation run of the same commit (`git log --grep='(606)'`).

## 3. Why the Laptop Warms uv's Cache Before Every Merge Verify

Some tests run uv offline under `tests/conftest.py`'s network guard, so they read wheels and index pages only from the
host's uv cache: the lane collections of `tests/unit/test_offline_lane_contracts.py`, e2e included, and
`tests/unit/test_stale_uv_lock.py`. Agents and the offline lane keep this workstation's cache warm; nothing else warms
the laptop's. Without a warm-up, the next dependency change would turn laptop merge verifies red while they pass here.

So the host yaml's `verify_cold_preprovision_command` syncs every extra and refreshes the index before each merge
verify:

- The sync is `--locked`, so it never rewrites `uv.lock` and cannot hide a stale lock.
- It targets a scratch environment, which keeps the `e2e` extra out of the verify's own `.venv`.
- It runs with `--all-extras` in the verify's worktree, so it follows each commit's own lock.

It is laptop-only. `dark-factory-orchestrator.yaml` sets no `verify_cold_preprovision_command`, so the spec ships an
empty one and Dark Factory keeps the laptop's own. If that file ever sets one, Dark Factory runs it on the laptop
instead, and the warm-up must move into it.

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

- Stop using the laptop now: set `verify_host_policy: prefer_local`, commit, then call
  `mcp__escalation__reload_config`. The key is green tier, so the change takes effect at the next dispatch.
- Remove the runner: set `enabled: false` on the `laptop` entry, or drop the block, then restart the orchestrator.
  `verify_runners`, `verify_drift_check_every_n_lands` and `verify_env_probes` are restart-tier; Dark Factory's
  `OPERATIONS.md` §6, "Config reload vs restart", is the authority.
- Neither touches the laptop's files.

Parity rule: a local red with a laptop green, or the reverse, that reproduces on the same commit means `prefer_local`
the same day, then escalate. Do not wait for the next drift check.
