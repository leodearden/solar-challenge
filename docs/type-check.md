# Type Check: Third-Party Packages mypy Reads as Untyped

**Task:** #1043
**Settings:** [`pyproject.toml`](../pyproject.toml), the `ignore_missing_imports` table of `[[tool.mypy.overrides]]`
**Gate:** [`dark-factory-orchestrator.yaml`](../dark-factory-orchestrator.yaml) (`type_check_command`); [`tests/unit/test_helper_type_check.py`](../tests/unit/test_helper_type_check.py)

---

## 1. What the Override Does

- The verify's type leg, `type_check_command`, runs mypy strict over `src/solar_challenge`,
  and `tests/unit/test_helper_type_check.py` runs mypy with the same settings over the test
  helper modules.
- mypy finds no types for a package that ships no `py.typed` and has no stub package
  installed, and reports each import of it as `import-untyped`. A package listed in the
  override is read instead with every name as `Any`, so its imports need no per-line
  `# type: ignore[import-untyped]`.
- Under strict, `warn_unused_ignores` reports such an ignore once it suppresses nothing.
- The override changes nothing for a package that ships its own types, as numpy and flask
  do: mypy reads their annotations whether they are listed or not.

## 2. Decision (task 1043, 2026-11-06): scipy Joins the Override, Not scipy-stubs

- scipy ships no `py.typed`.
- scipy-stubs 1.18.x requires Python >=3.12, and its stubs use PEP 695 `type` statements,
  which mypy at `[tool.mypy]`'s `python_version = "3.11"` refuses with a blocking syntax
  error. The project admits Python 3.11, so an unbounded scipy-stubs in the `dev` extra
  forks `uv.lock` by Python version.
- scipy-stubs 1.17.1.5 requires `optype[numpy]<0.18`, which requires
  `numpy-typing-compat<20251207`; the newest release below that bound, 20251206.2.4,
  requires `numpy<2.5`, and the first release to admit numpy 2.5, 20260602.2.5, is above
  the bound. That caps numpy at 2.4 across the whole lock, and holds `uv lock --upgrade`
  (the newest-releases lane) back from numpy 2.5.
- Revisit when `requires-python`'s floor and `python_version` reach 3.12, and scipy-stubs'
  optype chain admits the locked numpy.
