"""Tests for `solar-challenge web start`, run as a real server in a child process."""

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import pytest
pytest.importorskip("flask")

SERVER_WITH_BLOCKING_SIMULATIONS = """
import functools
import sys
import threading
from pathlib import Path

from flask import request_started

from solar_challenge.cli import app
from solar_challenge.web.jobs import JobManager

started_dir, port = Path(sys.argv[1]), sys.argv[2]
command_returned = threading.Event()


def blocking_simulation(config, start_date, end_date):
    (started_dir / str(config.pv_config.capacity_kw)).touch()
    command_returned.wait()
    raise RuntimeError("stub simulation")


@functools.cache
def blocking_jobs_of(dashboard):
    return JobManager(dashboard.extensions["storage"], max_workers=2, simulate_home=blocking_simulation)


def submit_to_blocking_jobs(dashboard, **extra):
    dashboard.extensions["job_manager"] = blocking_jobs_of(dashboard)


request_started.connect(submit_to_blocking_jobs)
try:
    app(["web", "start", "--port", port])
finally:
    command_returned.set()
"""

WEB_START = """
import sys

from solar_challenge.cli import app

app(["web", "start", *sys.argv[1:]])
"""

WEB_START_IMPORTING_SOURCE_FILE = """
import sys

import source_file

from solar_challenge.cli import app

app(["web", "start", *sys.argv[1:]])
"""

PRINTS_ON_STDOUT_AND_STDERR = """
import sys
import time

print("a line on stdout", flush=True)
print("a line on stderr", file=sys.stderr, flush=True)
time.sleep(600)
"""

_LOCALHOST = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_PATIENCE_SECS = 60

# Ends in \n, not $, which would also match a last line werkzeug is still writing, whose port may be cut short.
_WERKZEUG_STARTUP_LINE = re.compile(r"^ \* Running on http://127\.0\.0\.1:(\d+)\n", re.MULTILINE)


def _port_free_when_asked() -> int:
    """A port that was free when asked for; another process can take it before a server binds it, so it is only for a test that never connects to it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@dataclass(frozen=True)
class _ChildServer:
    """A server running in a child process, with the two files that its stdout and its stderr are written to."""

    process: subprocess.Popen[bytes]
    stdout_log: Path
    stderr_log: Path

    def stdout(self) -> str:
        """What the server has printed on its stdout so far."""
        return self.stdout_log.read_text(errors="replace")

    def stderr(self) -> str:
        """What the server has printed on its stderr so far."""
        return self.stderr_log.read_text(errors="replace")

    def logs(self) -> str:
        """Both logs in full, each headed by its file's name; a log that holds nothing reads as (empty)."""
        return "\n".join(
            f"the server's {log.name}:\n{text.rstrip() or '(empty)'}"
            for log, text in ((self.stdout_log, self.stdout()), (self.stderr_log, self.stderr()))
        )


@contextlib.contextmanager
def _server(tmp_path: Path, script: str, *args: str) -> Iterator[_ChildServer]:
    """Run script with args in a child process working in tmp_path, also its HOME, and yield it with its stdout in stdout.log and its stderr in stderr.log there; on exit kill its whole process group.

    The whole group: under --debug werkzeug's reloader serves from a second process, which
    a kill of the first alone would orphan, still holding the port and the store.

    An exception that leaves the block gets both logs as a note, added once the process is
    dead and the logs are complete, so the report of a red run says what the server printed.
    """
    stdout_log, stderr_log = tmp_path / "stdout.log", tmp_path / "stderr.log"
    with stdout_log.open("wb") as stdout, stderr_log.open("wb") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-c", script, *args],
            cwd=tmp_path,
            env={**os.environ, "HOME": str(tmp_path)},
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        server = _ChildServer(process, stdout_log, stderr_log)
        try:
            try:
                yield server
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        except BaseException as failure:
            failure.add_note(server.logs())
            raise


_Found = TypeVar("_Found")


def _wait_until(server: _ChildServer, condition: Callable[[], _Found | None], what: str) -> _Found:
    """Wait until condition returns something true, and return that; fail if the server has exited by then or _PATIENCE_SECS pass.

    Whether the server has exited is read before condition is, so a condition checked after an
    exit sees all that the server wrote: one that prints what the test waits for and exits at
    once is not reported as having exited before it.
    """
    deadline = time.monotonic() + _PATIENCE_SECS
    while True:
        exited = server.process.poll() is not None
        found = condition()
        if found:
            return found
        if exited:
            pytest.fail(f"the server exited with code {server.process.returncode} before {what}")
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting until {what}")
        time.sleep(0.05)


def _serving_port(server: _ChildServer) -> int:
    """The port that server listens on, which werkzeug names on its stderr once its socket listens: under --debug the reloader's watcher does so at once, and the serving process it starts serves on the same socket.

    The CLI's own status line names only the port it was asked for.
    """
    startup_line = _wait_until(
        server, lambda: _WERKZEUG_STARTUP_LINE.search(server.stderr()), "it reports the port it listens on"
    )
    return int(startup_line.group(1))


def _submit_home_job(port: int, pv_kw: float) -> str:
    """Submit a home job of pv_kw to the server on port, and return its run's id."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/simulate/home",
        data=json.dumps({"pv_kw": pv_kw, "days": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with _LOCALHOST.open(request, timeout=_PATIENCE_SECS) as response:
        assert response.status == 201
        run_id: str = json.load(response)["run_id"]
        return run_id


def _run_status(port: int, run_id: str) -> str:
    """The status of run run_id, as the server on port reports it."""
    with _LOCALHOST.open(f"http://127.0.0.1:{port}/api/history/runs/{run_id}", timeout=_PATIENCE_SECS) as response:
        status: str = json.load(response)["status"]
        return status


def _dashboard_status(port: int) -> int:
    """The status with which the server on port answers GET /."""
    with _LOCALHOST.open(f"http://127.0.0.1:{port}/", timeout=_PATIENCE_SECS) as response:
        status: int = response.status
        return status


def _store_lock_file(home: Path) -> Path:
    """The lock file of the dashboard store of a server whose HOME is home."""
    return home / ".solar-challenge" / "dashboard.lock"


def _store_holder_pid(home: Path) -> int | None:
    """The pid that the lock file of the dashboard store under home records, or None while it records none."""
    try:
        return int(_store_lock_file(home).read_text())
    except (OSError, ValueError):
        return None


def test_a_check_that_fails_while_a_server_runs_reports_what_the_server_printed_on_stdout_and_stderr(
    tmp_path: Path,
) -> None:
    """The failure's own text carries both logs, so a red verify keeps what the server said."""
    with pytest.raises(pytest.fail.Exception) as failed:
        with _server(tmp_path, PRINTS_ON_STDOUT_AND_STDERR) as server:
            _wait_until(
                server,
                lambda: "a line on stderr" in server.stderr(),
                "the server has printed on both streams",
            )
            pytest.fail("a check failed")

    assert "a line on stdout" in failed.exconly()
    assert "a line on stderr" in failed.exconly()


def test_stopping_the_server_drops_the_jobs_still_queued(tmp_path: Path) -> None:
    """Ctrl+C drops the jobs still waiting for a worker, so they never run."""
    started_dir = tmp_path / "started"
    started_dir.mkdir()

    def started() -> list[str]:
        return sorted(path.name for path in started_dir.iterdir())

    with _server(tmp_path, SERVER_WITH_BLOCKING_SIMULATIONS, str(started_dir), "0") as server:
        port = _serving_port(server)
        for pv_kw in (1.0, 2.0, 3.0):
            _submit_home_job(port, pv_kw)
        _wait_until(server, lambda: started() == ["1.0", "2.0"], "two jobs run and the third waits for a worker")

        server.process.send_signal(signal.SIGINT)
        server.process.wait(timeout=_PATIENCE_SECS)
        assert started() == ["1.0", "2.0"]


def test_web_start_prints_its_ctrl_c_hint_after_its_status_line_on_stderr(tmp_path: Path) -> None:
    """The hint follows the status line naming the dashboard's address on stderr, and is not printed on stdout, which carries Flask's own banner."""
    port = _port_free_when_asked()

    with _server(tmp_path, WEB_START, "--port", str(port)) as server:
        _wait_until(server, lambda: "Press Ctrl+C to stop the server." in server.stderr(), "it prints its Ctrl+C hint")

    status = server.stderr().splitlines()
    status_line = f"Starting web dashboard at http://127.0.0.1:{port}"
    assert status_line in status
    start = status.index(status_line)
    assert status[start + 1 : start + 2] == ["  Press Ctrl+C to stop the server."]
    assert "Press Ctrl+C to stop the server." not in server.stdout()


def test_a_second_web_start_on_the_store_exits_1_naming_the_lock_file_and_its_holder_and_the_first_servers_run_stays_running(
    tmp_path: Path,
) -> None:
    """COLUMNS keeps Rich from folding the long lock path at 80 columns on the second server's stderr, which is not a terminal."""
    started_dir = tmp_path / "started"
    started_dir.mkdir()
    lock_path = str(_store_lock_file(tmp_path))

    with _server(tmp_path, SERVER_WITH_BLOCKING_SIMULATIONS, str(started_dir), "0") as server:
        port = _serving_port(server)
        run_id = _submit_home_job(port, 1.0)
        _wait_until(server, lambda: (started_dir / "1.0").exists(), "its job's simulation starts")

        second = subprocess.run(
            [sys.executable, "-c", WEB_START, "--port", "0"],
            cwd=tmp_path,
            env={**os.environ, "HOME": str(tmp_path), "COLUMNS": "1000"},
            capture_output=True,
            text=True,
            timeout=_PATIENCE_SECS,
        )

        assert second.returncode == 1, second.stderr
        assert lock_path in second.stderr
        assert re.search(rf"(?<!\d){server.process.pid}(?!\d)", second.stderr.replace(lock_path, "")), second.stderr
        assert "Traceback" not in second.stderr
        assert _run_status(port, run_id) == "running"


def test_web_start_debug_serves_the_dashboard(tmp_path: Path) -> None:
    """B13: werkzeug's reloader binds the port at once, and the process it serves from accepts the queued request once it serves."""
    with _server(tmp_path, WEB_START, "--debug", "--port", "0") as server:
        port = _serving_port(server)

        assert _dashboard_status(port) == 200


def test_web_start_debug_serves_again_after_a_source_file_changes_from_a_restarted_process_that_retakes_the_store(
    tmp_path: Path,
) -> None:
    """The reloader restarts the serving process when a module it imported changes, and the restarted process can take the store only once the one before it has exited.

    source_file.py starts dated to the epoch, so its change is newer than the time the reloader recorded at any clock resolution.
    """
    source_file = tmp_path / "source_file.py"
    source_file.write_text("")
    os.utime(source_file, (0, 0))

    with _server(tmp_path, WEB_START_IMPORTING_SOURCE_FILE, "--debug", "--port", "0") as server:
        port = _serving_port(server)
        assert _dashboard_status(port) == 200
        first_holder = _store_holder_pid(tmp_path)
        assert first_holder not in (None, server.process.pid)

        source_file.write_text("CHANGED = True\n")
        _wait_until(
            server,
            lambda: _store_holder_pid(tmp_path) not in (None, first_holder),
            "a restarted serving process takes the store",
        )
        assert _dashboard_status(port) == 200
