# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lint contract tests.

The lint is ruff, run with the rules pyproject.toml's [tool.ruff.lint] selects.
The verify runs the test suite, so these tests are how it lints the package;
docs/lint-gate.md says why the orchestrator's lint_command does not.
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PACKAGE = "src/solar_challenge"
_PROBE = f"{_PACKAGE}/lint_probe.py"
_TEST_PROBE = "tests/unit/test_lint_probe.py"
_LINTED_TREES = (_PACKAGE,)


@dataclass(frozen=True)
class _Finding:
    """One finding in ruff's report: its rule code, the project-relative POSIX path of its file, its row and ruff's message."""

    code: str
    path: str
    row: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.row}: {self.code} {self.message}"


def _lint(project_root: Path, *ruff_args: str, stdin: str | None = None) -> list[_Finding]:
    """Run the project's lint, `ruff check` with *ruff_args*, in *project_root*, and return its findings.

    The ruff is the dev extra's, in the environment running the suite.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format=json", *ruff_args],
        cwd=project_root,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode in (0, 1) and result.stdout, (
        f"ruff gave no report (exit {result.returncode}); its stderr:\n{result.stderr}"
    )
    root = project_root.resolve()
    return [
        _Finding(
            code=entry["code"],
            path=Path(entry["filename"]).resolve().relative_to(root).as_posix(),
            row=entry["location"]["row"],
            message=entry["message"],
        )
        for entry in json.loads(result.stdout)
    ]


def _lint_the_project(project_root: Path) -> list[_Finding]:
    """Lint every tree in _LINTED_TREES, the trees the verify holds to the project's lint, in *project_root*."""
    return _lint(project_root, *_LINTED_TREES)


def _lint_probe(project_root: Path, source: str, *ruff_args: str) -> list[_Finding]:
    """Lint *source* as the package module _PROBE, through ruff's stdin; no file is written.

    --stdin-filename makes ruff lint it with the settings a real module at that
    path gets, per-file-ignores included.
    """
    return _lint(project_root, *ruff_args, "--stdin-filename", _PROBE, "-", stdin=source)


def _located_codes(findings: list[_Finding]) -> list[tuple[str, str, int]]:
    """Each finding's rule code, path and row: the verdict a probe pins, without ruff's wording."""
    return [(finding.code, finding.path, finding.row) for finding in findings]


def test_lint_flags_an_unused_import_in_a_package_module(project_root: Path) -> None:
    """The lint reports an unused import in a module of the package.

    Once the package is clean, test_the_package_passes_the_lint passes for a lint
    that flags nothing, so this checks the lint on a module of known verdict.
    """
    findings = _lint_probe(project_root, "import json\n")

    assert _located_codes(findings) == [("F401", _PROBE, 1)], (
        "the lint must report the unused import in a package module, and nothing else; it reported:\n"
        + "\n".join(map(str, findings))
    )


def test_lint_flags_a_mid_file_import_in_a_package_module(project_root: Path) -> None:
    """The lint reports a module-level import below other code in a module of the package."""
    source = "PATTERN = 'x'\nimport re\n\nCOMPILED = re.compile(PATTERN)\n"

    findings = _lint_probe(project_root, source)

    assert _located_codes(findings) == [("E402", _PROBE, 2)], (
        "the lint must report the mid-file import in a package module, and nothing else; it reported:\n"
        + "\n".join(map(str, findings))
    )


def test_lint_flags_a_bare_except_in_a_package_module(project_root: Path) -> None:
    """The lint reports a bare except in a module of the package."""
    source = "try:\n    pass\nexcept:\n    pass\n"

    findings = _lint_probe(project_root, source)

    assert _located_codes(findings) == [("E722", _PROBE, 3)], (
        "the lint must report the bare except in a package module, and nothing else; it reported:\n"
        + "\n".join(map(str, findings))
    )


def test_lint_flags_a_package_path_it_cannot_read(project_root: Path) -> None:
    """The lint reports a path in the package that it cannot read as a finding, not only as a warning on stderr.

    No file exists at _PROBE, the path the other probes lint stdin as, so ruff
    cannot read it. A broken symlink, or a module ruff may not open, gets the
    same finding.
    """
    assert not (project_root / _PROBE).exists(), (
        f"the probe needs no file at {_PROBE}, the path it lints, so that ruff cannot read it; "
        "remove the file there"
    )

    findings = _lint(project_root, _PROBE)

    assert _located_codes(findings) == [("E902", _PROBE, 1)], (
        "the lint must report the package path it cannot read, and nothing else; it reported:\n"
        + "\n".join(map(str, findings))
    )


def test_lint_ignores_a_default_rule_pyproject_does_not_select(project_root: Path) -> None:
    """The lint applies pyproject.toml's rule selection, not ruff's default rules.

    The probe's `except Exception: pass` breaks S110 and BLE001, default rules
    pyproject.toml does not select. A control run with --isolated, which makes
    ruff ignore pyproject.toml, shows that ruff's defaults still flag the probe,
    so the probe tells the selection from the defaults.
    """
    source = "try:\n    pass\nexcept Exception:\n    pass\n"

    assert _lint_probe(project_root, source, "--isolated"), (
        "ruff's default rules no longer flag the probe, so it cannot tell them from pyproject.toml's "
        "selection; give it a line they flag and the selected rules pass"
    )

    findings = _lint_probe(project_root, source)

    assert not findings, (
        "the lint flagged the probe, which breaks only default rules pyproject.toml's [tool.ruff.lint] does "
        "not select; either ruff is not applying that selection, or it now selects them and the probe needs "
        "another rule:\n" + "\n".join(map(str, findings))
    )


def test_the_lint_covers_the_package_and_its_tests(project_root: Path, tmp_path: Path) -> None:
    """The lint reaches a module in each tree it holds to the rules: the package and its tests.

    The scratch project carries this project's pyproject.toml, a package module with
    an unused import, and a test module whose annotation names an unbound name, the
    pattern that built up in tests/ while nothing linted it. With both trees clean,
    test_the_package_and_its_tests_pass_the_lint also passes for a lint that skips
    one of them, so this checks that the lint reaches both.
    """
    shutil.copy(project_root / "pyproject.toml", tmp_path / "pyproject.toml")
    for module, source in (
        (_PROBE, "import json\n"),
        (_TEST_PROBE, 'def make_results() -> "SimulationResults":\n    raise NotImplementedError\n'),
    ):
        (tmp_path / module).parent.mkdir(parents=True)
        (tmp_path / module).write_text(source)

    findings = _lint_the_project(tmp_path)

    assert sorted(_located_codes(findings)) == [("F401", _PROBE, 1), ("F821", _TEST_PROBE, 1)], (
        "the lint must report the package module's unused import and the test module's undefined name, "
        "and nothing else; it reported:\n" + "\n".join(map(str, findings))
    )


def test_the_package_passes_the_lint(project_root: Path) -> None:
    """The package has no finding under the project's lint, so the verify fails a commit that adds one."""
    findings = _lint_the_project(project_root)

    assert not findings, (
        f"the package has lint findings; clear them (`uv run --locked --extra dev ruff check --fix {_PACKAGE}` "
        "applies the safe fixes):\n" + "\n".join(map(str, findings))
    )
