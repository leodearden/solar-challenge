# SPDX-License-Identifier: AGPL-3.0-or-later
"""Type-check contract tests for the test helper modules.

A helper module is a module of tests/ whose name starts with an underscore, or any module
under a directory of tests/ whose name does, wherever either sits, save those
_ILL_TYPED_ON_PURPOSE names. The verify's type_check_command checks src/solar_challenge
alone, so these tests are how the verify type-checks each helper module, with the settings
pyproject.toml's [tool.mypy] gives it. tests/e2e's modules import the e2e extra, which the
verify's own environment lacks, so their check reads the packages of the environment the
offline lane's e2e job runs in. The test modules stay outside the check, and the lint's
F821 is the check on their annotations. docs/lint-gate.md §7 and §8 record which modules
the check covers and where, and its §3 says why a gate is a test rather than an
orchestrator command.
"""

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tests._collect_only import requires_uv
from tests._command_runner import ShellCommand, describe_outcome, run_command
from tests._orchestrator_config import lane_command
from tests._uv_env import SharedUvEnvironments, uv_run_options

pytest.importorskip(
    "jinja2",
    reason="the helper modules' type check needs jinja2, from the web extra: tests/_css_classes.py imports it, "
    "and mypy reports a missing import as an error",
)

_E2E_SUITE = PurePosixPath("tests/e2e")
"""The suite of the offline lane's e2e job. Its modules import the e2e extra, which only that job's environment installs."""

_ILL_TYPED_ON_PURPOSE = frozenset({"tests/unit/surface_forms_helper/_fixtures.py"})
"""The modules the rule selects that the type check leaves out: each builds objects that are ill-typed on purpose,
as inputs its tests hand to inspect, which only a `# type: ignore` or a construct that hides them from mypy would let
pass. tests/unit/surface_forms_helper/_fixtures.py builds them for the rule tests of tests/_surface_forms.py."""

_ERROR_LINE =re.compile(r"(?P<path>[^:]+):(?P<line>\d+): error: (?P<message>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?")


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
    """The helper modules, as mypy is given them: sorted paths relative to *project_root*."""
    tests = project_root / "tests"
    selected = {
        path.relative_to(project_root).as_posix()
        for path in tests.rglob("*.py")
        if any(part.startswith("_") for part in path.relative_to(tests).parts)
    }
    stale = sorted(_ILL_TYPED_ON_PURPOSE - selected)
    assert not stale, (
        f"_ILL_TYPED_ON_PURPOSE leaves out {stale}, which the rule selects no module at: "
        "drop each path, or name the module at its new one"
    )
    return sorted(selected - _ILL_TYPED_ON_PURPOSE)


def _in_the_e2e_suite(module: str) -> bool:
    """Whether helper *module*, a path as _helper_modules gives it, lies in the e2e job's suite."""
    return PurePosixPath(module).is_relative_to(_E2E_SUITE)


def _e2e_job_interpreter(project_root: Path, environments: SharedUvEnvironments) -> str:
    """The Python of the environment the offline lane's e2e job runs its suite in, synced as the job's command syncs it.

    environments shares that environment with every probe that runs the job's command, so a session syncs it once.
    """
    command = lane_command(project_root, "e2e").command
    print_interpreter = shlex.join(
        ["uv", "run", *uv_run_options(command), "python", "-c", "import sys; print(sys.executable)"]
    )
    outcome = run_command(
        ShellCommand(print_interpreter, project_root), environments.for_command(command), timeout_secs=300
    )
    assert outcome.returncode == 0, (
        f"{print_interpreter!r} could not sync the e2e job's environment and name its Python; if uv could not "
        f"download a wheel its cache lacks, run that command once with network access\n{describe_outcome(outcome)}"
    )
    return outcome.stdout.strip()


def _type_check_probe(project_root: Path, source: str, tmp_path: Path) -> list[_Error]:
    """Type-check *source* in place of each helper module, in one mypy run.

    mypy's --shadow-file reads the probe under each module's own path and module name,
    so each module's own settings, per-module overrides included, apply to the probe
    there. No module's file is read or written.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    modules = _helper_modules(project_root)
    shadows = [argument for module in modules for argument in ("--shadow-file", module, str(probe))]
    return _type_check(project_root, *shadows, *modules)


def test_the_type_check_flags_an_untyped_function_in_each_helper_module(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a function without annotations, the probe each helper module gets in its place.

    Only strict mode, which pyproject.toml's [tool.mypy] turns on, reports one. So
    this checks that the type check applies the project's settings to each helper
    module and still reports an error there once the module has none. Without it,
    an override that silences or relaxes tests.*, or one helper module, would leave
    the gate tests passing on a check that reports nothing there.
    """
    errors = _type_check_probe(project_root, "def probe(value):\n    return value\n", tmp_path)

    expected = [(module, 1, "no-untyped-def") for module in _helper_modules(project_root)]
    assert sorted((error.path, error.line, error.code) for error in errors) == expected, (
        "the type check must report the untyped function in each helper module, and "
        "nothing else; it reported:\n" + "\n".join(map(str, errors))
    )


def test_the_type_check_flags_an_unused_type_ignore_in_each_helper_module(project_root: Path, tmp_path: Path) -> None:
    """The type check reports a `# type: ignore` that suppresses no error, the probe each helper module gets in its place.

    A helper module that reads an attribute its target's typeshed does not declare
    does so under an ignore scoped to one error code. Once the typeshed declares the
    attribute, the ignore suppresses nothing, and warn_unused_ignores, which strict
    mode in pyproject.toml's [tool.mypy] turns on, is what reports it. The probe is
    such an ignore: an attr-defined one on the read of an attribute typeshed
    declares. Without this test, an override that turns warn_unused_ignores off, for
    tests.* or for one helper module, would leave a stale ignore there while the gate
    tests pass.
    """
    errors = _type_check_probe(project_root, "probe = int.__name__  # type: ignore[attr-defined]\n", tmp_path)

    expected = [(module, 1, "unused-ignore") for module in _helper_modules(project_root)]
    assert sorted((error.path, error.line, error.code) for error in errors) == expected, (
        "the type check must report the ignore that suppresses no error in each helper "
        "module, and nothing else; it reported:\n" + "\n".join(map(str, errors))
    )


def test_every_helper_module_outside_the_e2e_suite_passes_the_type_check(project_root: Path) -> None:
    """No helper module outside tests/e2e has an error under the project's type check, so the verify fails a commit that adds one."""
    modules = [module for module in _helper_modules(project_root) if not _in_the_e2e_suite(module)]
    errors = _type_check(project_root, *modules)

    assert not errors, (
        "the helper modules have type errors; clear each without hiding a real one:\n"
        + "\n".join(map(str, errors))
    )


@requires_uv
def test_every_helper_module_of_the_e2e_suite_passes_the_type_check(
    project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    """No helper module of tests/e2e has an error under the project's type check, with the e2e job's packages.

    Those modules import the e2e extra, which the verify's own environment lacks, so mypy reads the packages of the
    environment the offline lane's e2e job runs its suite in, and the verify fails a commit that adds an error there.
    """
    interpreter = _e2e_job_interpreter(project_root, shared_uv_probe_environments)
    modules = [module for module in _helper_modules(project_root) if _in_the_e2e_suite(module)]
    errors = _type_check(project_root, f"--python-executable={interpreter}", *modules)

    assert not errors, (
        "the helper modules of tests/e2e have type errors; clear each without hiding a real one:\n"
        + "\n".join(map(str, errors))
    )
