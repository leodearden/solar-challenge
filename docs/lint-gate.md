# Lint: The Gate Is a Test, Not `lint_command`

**Task:** #246; #994 (§4); #1003 (§5); #302 (§6); #884 (§7)
**Rules:** [`pyproject.toml`](../pyproject.toml), table `[tool.ruff.lint]`
**Tests:** [`tests/unit/test_lint.py`](../tests/unit/test_lint.py); [`tests/unit/test_helper_type_check.py`](../tests/unit/test_helper_type_check.py)

---

## 1. What the Lint Is

The lint is ruff, from the `dev` extra, with the rules `pyproject.toml`'s `[tool.ruff.lint]`
selects. That table is the one home of the selection: the test, a developer's
`uv run --locked --extra dev ruff check src/solar_challenge tests` and an editor all read it.
The selection is named rather than left to ruff's defaults, because those change between
releases: ruff 0.16.10 enables hundreds of rules by default that 0.15.9 does not.

## 2. Where It Runs

`tests/unit/test_lint.py` lints `src/solar_challenge` and `tests`, and the verify's test
command runs it with the rest of the suite. `dark-factory-orchestrator.yaml` keeps
`lint_command: "true"`.

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

## 5. Decision (task 1003, 2026-10-20): E7 and E9 Join the Selection

The selection includes pycodestyle's E7, its statement rules; ruff's
[rule list](https://docs.astral.sh/ruff/rules/) says what each one flags. Most flag a
statement that does something other than it seems to, such as a bare `except`, which also
catches `KeyboardInterrupt` and `SystemExit`. While nothing checked for them, such
statements could build up unseen, as E402's findings did. Where `==` compares element by
element, as on a NumPy array or a pandas Series, the unsafe fixes for E711 and E712 change
what the code does: they rewrite `series == None` to `series is None` and `mask == False`
to `not mask`, neither of which compares element by element. Write such a comparison with
the library's own operations instead, such as `series.isna()` or `~mask`. A line that has
to break one of these rules carries `# noqa:` with the rule's code.

It includes E9 too. E9 makes the lint report a path it cannot read, such as a missing
path, a broken symlink or a module ruff may not open, as an E902 finding. Without it, ruff
only warns on stderr and reports no finding, so the lint would pass a module it never
read. Ruff reports a syntax error whatever the selection. E999, the old syntax-error
rule, was removed in ruff 0.8.0 and can no longer be selected, so E9 is E902 alone.

## 6. Decision (task 302, 2026-10-26): The Lint Covers `tests`

The test lints `tests` as well as the package, with the same selection, because
`pyproject.toml`'s `[tool.ruff.lint]` is the one home of the rules for both trees. While
nothing linted `tests`, findings built up there unseen. The chief one was F821: a helper
annotated with a type its module never imports, such as `-> "SimulationResults"`, carrying
`# type: ignore[name-defined]` to quiet mypy. Such an annotation tells the reader that a
name is bound where it is not, and `typing.get_type_hints` cannot resolve it. The pattern
came back after cleanups, because new tests copied it from their neighbours, until task 300
cleared the last of it. The verify's type check does not reach the test modules, so F821 is
the one check on their annotations.

With both trees clean, a lint that skipped one would also pass. So
`tests/unit/test_lint.py::test_the_lint_covers_the_package_and_its_tests` lints a scratch
project that carries this `pyproject.toml` and one finding in each tree, and expects both
findings.

## 7. Decision (task 884, 2026-10-30): The Helper Type Check Covers Every Helper Module

`tests/unit/test_helper_type_check.py::test_every_helper_module_outside_the_e2e_suite_passes_the_type_check`
runs mypy, with `pyproject.toml`'s `[tool.mypy]`, over every helper module: each module
directly in `tests` whose name starts with an underscore, and each module anywhere under a
directory of `tests` whose name does, such as `tests/_pytest_plugins`. The verify's
type-check command checks `src/solar_challenge` alone, and §3's reasons for a test over an
orchestrator command hold for this gate too.

Its two probes put a module of known verdict in every helper module's place: a function
without annotations, which only strict mode reports, and a `# type: ignore` that
suppresses no error, which only `warn_unused_ignores` reports. An override that relaxes
`tests.*`, or one helper module, then fails them, while the gate itself would still pass.

The test modules stay outside mypy, and F821 (§6) is the check on their annotations. So do
the modules of a test directory whose names start with an underscore, such as
`tests/unit/web_jobs/_fakes.py` and those of `tests/e2e`: they are not helper modules in this
sense. Task 1211 decides whether the check should reach them.
