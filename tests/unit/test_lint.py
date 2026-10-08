# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lint contract tests.

The lint is ruff, run with the rules pyproject.toml's [tool.ruff.lint] selects.
The verify runs the test suite, so these tests are how it lints the package;
dark-factory-orchestrator.yaml says why its lint_command does not.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PACKAGE = "src/solar_challenge"


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


def test_lint_flags_an_unused_import_in_a_package_module(project_root: Path) -> None:
    """The lint reports an unused import in a module of the package.

    Once the package is clean, test_the_package_passes_the_lint passes for a lint
    that flags nothing, so this checks the lint on a module of known verdict.
    --stdin-filename makes ruff lint it with the settings a real module at that
    path gets, per-file-ignores included; nothing is written.
    """
    probe = f"{_PACKAGE}/lint_probe.py"

    findings = _lint(project_root, "--stdin-filename", probe, "-", stdin="import json\n")

    assert [(finding.code, finding.path, finding.row) for finding in findings] == [("F401", probe, 1)], (
        "the lint must report the unused import in a package module, and nothing else; it reported:\n"
        + "\n".join(map(str, findings))
    )
