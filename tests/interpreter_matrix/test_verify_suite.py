# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-run the orchestrator verify suite on every admitted Python minor except the pin.

The orchestrator's offline lane runs this module after each merge to main. The
.python-version pin needs no case here: every per-task and merge verify already
runs on it. tests/conftest.py keeps this directory out of every default
collection, so it runs only when its path is passed explicitly. Its cases are
marked slow, the exemption from tests/conftest.py's offline guard, which refuses
a test's network access, its child processes' included: each case provisions
its interpreter's environment from PyPI whenever uv.lock changes.

Manual run::

    uv run --locked --extra dev pytest tests/interpreter_matrix [-k 3.13]

Inside a sandbox that cannot write uv's python directory, set
UV_PYTHON_INSTALL_DIR to a writable path.
"""

import contextlib
import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from tests._interpreters import off_pin_minor_versions
from tests._orchestrator_config import load_orchestrator_config
from tests._uv_env import isolated_uv_env

pytestmark = pytest.mark.slow

# Parametrization happens at collection time, before any fixture exists.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# About 15x the slowest measured suite run (491 s on 3.11). It exists only so a
# hang cannot stall the single-flight offline lane forever.
_SUITE_TIMEOUT_SECS = 7200

# Enough of the suite's output to carry pytest's short test summary.
_OUTPUT_TAIL_CHARS = 5000

# Printed by the interpreter uv ran the suite with, so a green run proves which Python it was.
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
    env = isolated_uv_env(_matrix_venv(major, minor))
    # "+gil" is load-bearing: a plain 3.14 request selects the free-threaded 3.14t on the factory host.
    env["UV_PYTHON"] = f"{major}.{minor}+gil"
    # The suite must never collect this matrix, even if tests/conftest.py stops ignoring it.
    env["PYTEST_ADDOPTS"] = "--ignore=tests/interpreter_matrix"
    return env


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL *proc*'s whole process group, unless *proc* has already been reaped.

    Until Popen reaps *proc*, its pid, which is also the group's id, cannot be reused.
    """
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def _run_verify_suite(env: dict[str, str], python: str) -> subprocess.CompletedProcess[str]:
    """Run the orchestrator's test_command verbatim in *env*, as the orchestrator runs it.

    The suite runs in a session of its own, which no signal sent to this process
    reaches. If the case ends before the suite does (a hang, an interrupt, an
    error), the whole process group is killed, so uv, pytest and its workers do
    not outlive the case.
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
        _kill_process_group(proc)
        output, _ = proc.communicate()
        pytest.fail(
            f"the verify suite on Python {python} hung for {_SUITE_TIMEOUT_SECS} s and was killed; "
            f"output tail:\n{output[-_OUTPUT_TAIL_CHARS:]}"
        )
    finally:
        _kill_process_group(proc)
    return subprocess.CompletedProcess(command, proc.returncode, output)


def _interpreter_identity(env: dict[str, str], python: str) -> dict[str, object]:
    """Return the Python version and GIL build of the interpreter `uv run` resolves in *env*.

    That is the resolution the suite ran under, so the probe reports the
    interpreter that ran it, whatever uv made of UV_PYTHON and UV_PROJECT_ENVIRONMENT.
    """
    probe = subprocess.run(
        # --no-sync: a plain `uv run` would re-sync the environment without the suite's extras.
        ["uv", "run", "--no-sync", "python", "-c", _IDENTITY_PROBE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if probe.returncode != 0:
        pytest.fail(
            f"the verify suite passed, but uv could not run the interpreter it resolves for "
            f"Python {python} (exit {probe.returncode}), so nothing shows which Python ran the "
            f"suite; uv said:\n{probe.stderr}"
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
    env = _suite_env(major, minor)

    result = _run_verify_suite(env, python)

    assert result.returncode == 0, (
        f"the verify suite failed on Python {python} (exit {result.returncode}); "
        f"output tail:\n{result.stdout[-_OUTPUT_TAIL_CHARS:]}"
    )
    identity = _interpreter_identity(env, python)
    assert identity == {"version": [major, minor], "gil_disabled": False}, (
        f"the verify suite passed, but the interpreter uv ran it with reports {identity}, not a "
        f"GIL build of Python {python}; uv did not honour UV_PYTHON, so the green run says "
        f"nothing about Python {python}"
    )
