# Lint: The Gate Is a Test, Not `lint_command`

**Task:** #246
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
