# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a pytest command verbatim in collect-only mode, for the orchestrator contract tests.

Usage::

    from tests._collect_only import collected_node_ids, requires_uv, run_collect_only

    result = run_collect_only(command, project_root)
    node_ids = collected_node_ids(result.stdout)
"""

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

requires_uv = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is not installed; the orchestrator command under test runs through it"
)


def run_collect_only(
    command: str, cwd: Path, *pytest_args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run *command* verbatim in *cwd*, in *env* (default: this process's environment).

    The pytest the command invokes only collects, with *pytest_args* added to its
    arguments. The mode travels in PYTEST_ADDOPTS, so the command's own args and
    the project's ini addopts stay in force. It is --verbosity=-1 rather than -q
    because an ini -v cancels -q (tests/unit/test_collect_only.py pins this), so
    stdout lists one node id per line.
    """
    collect_env = dict(os.environ if env is None else env)
    collect_env["PYTEST_ADDOPTS"] = shlex.join(["--collect-only", "--verbosity=-1", *pytest_args])
    return subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        env=collect_env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def collected_node_ids(listing: str) -> list[str]:
    """Return the node ids, in order, in a run_collect_only stdout *listing*."""
    return [line for line in listing.splitlines() if "::" in line]
