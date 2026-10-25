# SPDX-License-Identifier: AGPL-3.0-or-later
"""Type-check contract tests for the surface-forms helper's modules, tests/_surface_forms*.py.

The verify's type_check_command checks src/solar_challenge alone, so these tests are how
the verify type-checks each module of the helper, with the settings pyproject.toml's
[tool.mypy] gives it; docs/lint-gate.md says why a gate is a test rather than an
orchestrator command.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ERROR_LINE = re.compile(r"(?P<path>[^:]+):(?P<line>\d+): error: (?P<message>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?")


@dataclass(frozen=True)
class _Error:
    """One error in mypy's report: the path of its file as mypy was given it, its line, its error code if it has one, and mypy's message."""

    path: str
    line: int
    code: str | None
    message: str

    def __str__(self) -> str:
        code_suffix = f"  [{self.code}]" if self.code else ""
        return f"{self.path}:{self.line}: error: {self.message}{code_suffix}"


def _type_check(project_root: Path, *mypy_args: str) -> list[_Error]:
    """Run the project's type check, `mypy` with *mypy_args*, in *project_root*, and return its errors.

    The mypy is the dev extra's, in the environment running the suite. Run in
    *project_root*, it reads pyproject.toml's [tool.mypy]. It keeps no cache, so no
    run reads another's results, and none touches the worktree's .mypy_cache,
    which the verify's type leg writes at the same time.
    """
    result = subprocess.run(
        [sys.executable, "-m", "mypy", f"--cache-dir={os.devnull}", *mypy_args],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    matches = (_ERROR_LINE.fullmatch(line) for line in result.stdout.splitlines())
    errors = [
        _Error(path=match["path"], line=int(match["line"]), code=match["code"], message=match["message"])
        for match in matches
        if match
    ]
    assert result.returncode == (1 if errors else 0), (
        f"mypy exited {result.returncode} after {len(errors)} error lines were read from its report, "
        "but it exits 1 exactly when it reports an error and 0 when it reports none: "
        "mypy is missing, or cannot read or parse its input, or its report format changed and _ERROR_LINE "
        f"no longer reads it.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return errors


def _helper_modules(project_root: Path) -> list[str]:
    """The helper's modules, tests/_surface_forms*.py, as mypy is given them: sorted paths relative to *project_root*."""
    return sorted(
        path.relative_to(project_root).as_posix()
        for path in (project_root / "tests").glob("_surface_forms*.py")
    )


def _type_check_probe(project_root: Path, source: str, tmp_path: Path) -> list[_Error]:
    """Type-check *source* in place of each of the helper's modules, in one mypy run.

    mypy's --shadow-file reads the probe under each module's own path and module name,
    so each module's own settings, per-module overrides included, apply to the probe
    there. No module's file is read or written.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    modules = _helper_modules(project_root)
    shadows = [argument for module in modules for argument in ("--shadow-file", module, str(probe))]
    return _type_check(project_root, *shadows, *modules)


def test_the_type_check_flags_an_untyped_function_in_the_helper(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a function without annotations in each of the helper's modules, tests/_surface_forms*.py.

    Only strict mode, which pyproject.toml's [tool.mypy] turns on, reports one. So
    this checks that the type check applies the project's settings to each module
    and still reports an error there once the module has none. Without it, an
    override that silences or relaxes tests.*, or one module of the helper, would
    leave test_the_surface_forms_helper_passes_the_type_check passing on a check
    that reports nothing there.
    """
    errors = _type_check_probe(project_root, "def probe(value):\n    return value\n", tmp_path)

    expected = [(module, 1, "no-untyped-def") for module in _helper_modules(project_root)]
    assert sorted((error.path, error.line, error.code) for error in errors) == expected, (
        "the type check must report the untyped function in each of the helper's modules, and "
        "nothing else; it reported:\n" + "\n".join(map(str, errors))
    )


def test_the_type_check_flags_an_unused_type_ignore_in_the_helper(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a `# type: ignore` that suppresses no error in each of the helper's modules, tests/_surface_forms*.py.

    The helper reads attributes its target's typeshed does not declare under ignores
    scoped to one error code. Once the typeshed declares such an attribute, its ignore
    suppresses nothing, and warn_unused_ignores, which strict mode in pyproject.toml's
    [tool.mypy] turns on, is what reports it. The probe is such an ignore: an
    attr-defined one on the read of an attribute typeshed declares. Without this test,
    an override that turns warn_unused_ignores off, for tests.* or for one module of the
    helper, would leave a stale ignore there while
    test_the_surface_forms_helper_passes_the_type_check passes.
    """
    errors = _type_check_probe(project_root, "probe = int.__name__  # type: ignore[attr-defined]\n", tmp_path)

    expected = [(module, 1, "unused-ignore") for module in _helper_modules(project_root)]
    assert sorted((error.path, error.line, error.code) for error in errors) == expected, (
        "the type check must report the ignore that suppresses no error in each of the helper's "
        "modules, and nothing else; it reported:\n" + "\n".join(map(str, errors))
    )


def test_the_surface_forms_helper_passes_the_type_check(project_root: Path) -> None:
    """No module of the helper, tests/_surface_forms*.py, has an error under the project's type check, so the verify fails a commit that adds one."""
    errors = _type_check(project_root, *_helper_modules(project_root))

    assert not errors, (
        "the helper's modules have type errors; clear each without hiding a real one:\n"
        + "\n".join(map(str, errors))
    )
