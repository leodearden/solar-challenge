# SPDX-License-Identifier: AGPL-3.0-or-later
"""Type-check contract tests for tests/_surface_forms.py.

The verify's type_check_command checks src/solar_challenge alone, so these tests are how
the verify type-checks the helper, with the settings pyproject.toml's [tool.mypy] gives it;
docs/lint-gate.md says why a gate is a test rather than an orchestrator command.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_HELPER = "tests/_surface_forms.py"
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


def _type_check_probe(project_root: Path, source: str, tmp_path: Path) -> list[_Error]:
    """Type-check *source* in place of the helper, under the helper's path and module name, tests._surface_forms.

    mypy's --shadow-file makes the settings the helper gets, per-module overrides
    included, apply to the probe. The helper's file is neither read nor written.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    return _type_check(project_root, "--shadow-file", _HELPER, str(probe), _HELPER)


def test_the_type_check_flags_an_untyped_function_in_the_helper(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a function without annotations in the helper.

    Only strict mode, which pyproject.toml's [tool.mypy] turns on, reports one. So
    this checks that the type check applies the project's settings to the helper
    and still reports an error there once the helper has none. Without it, an
    override that silences or relaxes tests.* would leave
    test_the_surface_forms_helper_passes_the_type_check passing on a check that
    reports nothing.
    """
    errors = _type_check_probe(project_root, "def probe(value):\n    return value\n", tmp_path)

    assert [(error.path, error.line, error.code) for error in errors] == [(_HELPER, 1, "no-untyped-def")], (
        "the type check must report the untyped function in the helper, and nothing else; it reported:\n"
        + "\n".join(map(str, errors))
    )


def test_the_type_check_flags_an_unused_type_ignore_in_the_helper(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a `# type: ignore` in the helper that suppresses no error.

    The helper reads attributes its target's typeshed does not declare under ignores
    scoped to one error code. Once the typeshed declares such an attribute, its ignore
    suppresses nothing, and warn_unused_ignores, which strict mode in pyproject.toml's
    [tool.mypy] turns on, is what reports it. The probe is such an ignore: an
    attr-defined one on the read of an attribute typeshed declares. Without this test,
    an override that turns warn_unused_ignores off would leave a stale ignore in the
    helper while test_the_surface_forms_helper_passes_the_type_check passes.
    """
    errors = _type_check_probe(project_root, "probe = int.__name__  # type: ignore[attr-defined]\n", tmp_path)

    assert [(error.path, error.line, error.code) for error in errors] == [(_HELPER, 1, "unused-ignore")], (
        "the type check must report the ignore that suppresses no error in the helper, and nothing else; "
        "it reported:\n" + "\n".join(map(str, errors))
    )


def test_the_surface_forms_helper_passes_the_type_check(project_root: Path) -> None:
    """The helper has no error under the project's type check, so the verify fails a commit that adds one."""
    errors = _type_check(project_root, _HELPER)

    assert not errors, (
        f"{_HELPER} has type errors; clear each without hiding a real one:\n" + "\n".join(map(str, errors))
    )
