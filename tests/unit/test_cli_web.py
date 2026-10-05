"""Tests for `solar-challenge web start`, run as a real server in a child process."""

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
pytest.importorskip("flask")

SERVER_WITH_BLOCKING_SIMULATIONS = """
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


blocking_jobs = JobManager(max_workers=2, simulate_home=blocking_simulation)


def submit_to_blocking_jobs(dashboard, **extra):
    dashboard.extensions["job_manager"] = blocking_jobs


request_started.connect(submit_to_blocking_jobs)
try:
    app(["web", "start", "--port", port])
finally:
    command_returned.set()
"""

WEB_START = """
import sys

from solar_challenge.cli import app

app(["web", "start", "--port", sys.argv[1]])
"""

_LOCALHOST = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextlib.contextmanager
def _server(tmp_path: Path, script: str, *args: str) -> Iterator["subprocess.Popen[bytes]"]:
    """Run script with args in a child process working in tmp_path, also its HOME, that writes its stdout to stdout.log and its stderr to stderr.log there; kill it on exit."""
    stdout_log, stderr_log = tmp_path / "stdout.log", tmp_path / "stderr.log"
    with stdout_log.open("wb") as stdout, stderr_log.open("wb") as stderr:
        server = subprocess.Popen(
            [sys.executable, "-c", script, *args],
            cwd=tmp_path,
            env={**os.environ, "HOME": str(tmp_path)},
            stdout=stdout,
            stderr=stderr,
        )
        try:
            yield server
        finally:
            server.kill()
            server.wait()
            print(stdout_log.read_text())
            print(stderr_log.read_text(), file=sys.stderr)


def _wait_until(server: "subprocess.Popen[bytes]", condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + 60
    while not condition():
        if server.poll() is not None:
            pytest.fail(f"the server exited with code {server.returncode} before {what}")
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting until {what}")
        time.sleep(0.05)


def _accepts_connections(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _submit_home_job(port: int, pv_kw: float) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/simulate/home",
        data=json.dumps({"pv_kw": pv_kw, "days": 1}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with _LOCALHOST.open(request, timeout=30) as response:
        assert response.status == 201


def test_stopping_the_server_drops_the_jobs_still_queued(tmp_path: Path) -> None:
    """Ctrl+C drops the jobs still waiting for a worker, so they never run."""
    started_dir = tmp_path / "started"
    started_dir.mkdir()
    port = _free_port()

    def started() -> list[str]:
        return sorted(path.name for path in started_dir.iterdir())

    with _server(tmp_path, SERVER_WITH_BLOCKING_SIMULATIONS, str(started_dir), str(port)) as server:
        _wait_until(server, lambda: _accepts_connections(port), "the server accepts connections")
        for pv_kw in (1.0, 2.0, 3.0):
            _submit_home_job(port, pv_kw)
        _wait_until(server, lambda: started() == ["1.0", "2.0"], "two jobs run and the third waits for a worker")

        server.send_signal(signal.SIGINT)
        server.wait(timeout=60)

    assert started() == ["1.0", "2.0"]


def test_web_start_prints_its_ctrl_c_hint_after_its_status_line_on_stderr(tmp_path: Path) -> None:
    """The hint follows the status line naming the dashboard's address on stderr, and is not printed on stdout, which carries Flask's own banner."""
    port = _free_port()

    with _server(tmp_path, WEB_START, str(port)) as server:
        _wait_until(server, lambda: _accepts_connections(port), "the server accepts connections")

    status = (tmp_path / "stderr.log").read_text().splitlines()
    status_line = f"Starting web dashboard at http://127.0.0.1:{port}"
    assert status_line in status
    start = status.index(status_line)
    assert status[start + 1 : start + 2] == ["  Press Ctrl+C to stop the server."]
    assert "Press Ctrl+C to stop the server." not in (tmp_path / "stdout.log").read_text()
