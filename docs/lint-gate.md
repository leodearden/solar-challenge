# Lint: The Gate Is a Test, Not `lint_command`

**Task:** #246; #994 (§4)
**Rules:** [`pyproject.toml`](../pyproject.toml), table `[tool.ruff.lint]`
**Test:** [`tests/unit/test_lint.py`](../tests/unit/test_lint.py)

---

## 1. What the Lint Is

The lint is ruff, from the `dev` extra, with the rules `pyproject.toml`'s `[tool.ruff.lint]`
selects. That table is the one home of the selection: the test, a developer's
`uv run --locked --extra dev ruff check src/solar_challenge` and an editor all read it. The
selection is named rather than left to ruff's defaults, because those change between
releases: ruff 0.16.10 enables hundreds of rules by default that 0.15.9 does not.

## 2. Where It Runs

`tests/unit/test_lint.py` lints `src/solar_challenge`, and the verify's `test_command` runs
it with the rest of the suite. `dark-factory-orchestrator.yaml` keeps `lint_command: "true"`.

## 3. Why Not `lint_command`

A test travels with the tree it is in; the orchestrator's `lint_command` does not.

- The orchestrator reads `lint_command` at start-up only, and runs that one command for
  every branch. A change to the test is in force from the first verify after it merges,
  since each verify first rebases its branch onto main.
- A branch whose verify-phase rebase fails is verified on its old base. If that base
  predates ruff in the `dev` extra, a `lint_command` that runs ruff fails the branch for a
  reason outside it. The old tree has no lint test either, so the lint fails nothing there.
- A test can carry probes of known verdict, which fail if ruff stops reporting findings or
  stops applying the selection. A bare command that reports nothing looks the same as a
  clean package.

## 4. Decision (task 994, 2026-10-20): E402 Joins the Selection

The selection includes pycodestyle's E402: a module-level import sits above the module's
other statements. A reader who meets an import further down has to stop and ask whether
its place is load-bearing, for instance whether it breaks an import cycle. While nothing
checked, such imports built up in the package unseen, until task 587 hoisted the last of
them. An import that has to follow a statement carries `# noqa: E402`, with a comment
saying why it comes there.

pycodestyle as a whole (`E`) cannot join: its line-length rule, E501, flags over a thousand
lines of the package.
