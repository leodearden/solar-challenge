# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-run the orchestrator verify suite on every admitted Python minor except the pin.

The orchestrator's offline lane runs this module after each merge to main. The
.python-version pin needs no case here: every per-task and merge verify already
runs on it. tests/conftest.py keeps this directory out of every default
collection, so it runs only when its path is passed explicitly.

Manual run::

    uv run --extra dev pytest tests/interpreter_matrix [-k 3.13]

Inside a sandbox that cannot write uv's python directory, set
UV_PYTHON_INSTALL_DIR to a writable path.
"""

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from tests._interpreters import off_pin_minor_versions
from tests._orchestrator_config import load_orchestrator_config

# Parametrization happens at collection time, before any fixture exists.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# About 15x the slowest measured suite run (491 s on 3.11). It exists only so a
# hang cannot stall the single-flight offline lane forever.
_SUITE_TIMEOUT_SECS = 7200

# Enough of the suite's output to carry pytest's short test summary.
_OUTPUT_TAIL_CHARS = 5000

# Run by the matrix environment's own interpreter, so a green suite proves which Python ran it.
_IDENTITY_PROBE = """
import json, sys, sysconfig
print(json.dumps({
    "version": list(sys.version_info[:2]),
    "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
}))
"""


_OFF_PIN_MINORS = sorted(off_pin_minor_versions(PROJECT_ROOT))


def _matrix_venv(major: int, minor: int) -> Path:
    """Return the project environment for Python *major*.*minor*, under the gitignored .cache/."""
    return PROJECT_ROOT / ".cache" / f"venv-py{major}{minor}"


def _suite_env(major: int, minor: int) -> dict[str, str]:
    """Return an environment in which the verify command runs on the GIL build of *major*.*minor*."""
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    # "+gil" is load-bearing: a plain 3.14 request selects the free-threaded 3.14t on the factory host.
    env["UV_PYTHON"] = f"{major}.{minor}+gil"
    env["UV_PROJECT_ENVIRONMENT"] = str(_matrix_venv(major, minor))
    # The suite must never collect this matrix, even if tests/conftest.py stops ignoring it.
    env["PYTEST_ADDOPTS"] = "--ignore=tests/interpreter_matrix"
    return env


def _run_verify_suite(env: dict[str, str], python: str) -> subprocess.CompletedProcess[str]:
    """Run the orchestrator's test_command verbatim in *env*, as the orchestrator runs it.

    On a hang the whole process group is killed, so uv, pytest and its workers
    do not outlive the case.
    """
    command = load_orchestrator_config(PROJECT_ROOT)["test_command"]
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=_SUITE_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        pytest.fail(
            f"the verify suite on Python {python} hung for {_SUITE_TIMEOUT_SECS} s and was killed; "
            f"output tail:\n{output[-_OUTPUT_TAIL_CHARS:]}"
        )
    return subprocess.CompletedProcess(command, proc.returncode, output)


def _interpreter_identity(venv: Path) -> dict[str, object]:
    """Return the Python version and GIL build that *venv*'s interpreter reports for itself."""
    probe = subprocess.run(
        [str(venv / "bin" / "python"), "-c", _IDENTITY_PROBE],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    identity: dict[str, object] = json.loads(probe.stdout)
    return identity


@pytest.mark.parametrize(
    "version",
    _OFF_PIN_MINORS,
    ids=[f"{major}.{minor}" for major, minor in _OFF_PIN_MINORS],
)
def test_verify_suite_passes_on_python(version: tuple[int, int]) -> None:
    """The orchestrator verify suite passes on the GIL build of this admitted minor."""
    major, minor = version
    python = f"{major}.{minor}"

    result = _run_verify_suite(_suite_env(major, minor), python)

    assert result.returncode == 0, (
        f"the verify suite failed on Python {python} (exit {result.returncode}); "
        f"output tail:\n{result.stdout[-_OUTPUT_TAIL_CHARS:]}"
    )
    identity = _interpreter_identity(_matrix_venv(major, minor))
    assert identity == {"version": [major, minor], "gil_disabled": False}, (
        f"the verify suite passed in {_matrix_venv(major, minor)}, but its interpreter reports "
        f"{identity}, not a GIL build of Python {python}; uv did not honour UV_PYTHON, so the "
        f"green run says nothing about Python {python}"
    )
