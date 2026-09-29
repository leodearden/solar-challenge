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

import solar_challenge.web.jobs
from solar_challenge.cli import app

started_dir, port = Path(sys.argv[1]), sys.argv[2]
command_returned = threading.Event()


def blocking_simulation(config, start_date, end_date):
    (started_dir / str(config.pv_config.capacity_kw)).touch()
    command_returned.wait()
    raise RuntimeError("stub simulation")


solar_challenge.web.jobs.simulate_home = blocking_simulation
try:
    app(["web", "start", "--port", port])
finally:
    command_returned.set()
"""

_LOCALHOST = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextlib.contextmanager
def _server_with_blocking_simulations(
    tmp_path: Path, started_dir: Path, port: int
) -> Iterator["subprocess.Popen[bytes]"]:
    log_path = tmp_path / "server.log"
    with log_path.open("wb") as log:
        server = subprocess.Popen(
            [sys.executable, "-c", SERVER_WITH_BLOCKING_SIMULATIONS, str(started_dir), str(port)],
            cwd=tmp_path,
            env={**os.environ, "HOME": str(tmp_path)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            yield server
        finally:
            server.kill()
            server.wait()
            print(log_path.read_text())


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

    with _server_with_blocking_simulations(tmp_path, started_dir, port) as server:
        _wait_until(server, lambda: _accepts_connections(port), "the server accepts connections")
        for pv_kw in (1.0, 2.0, 3.0):
            _submit_home_job(port, pv_kw)
        _wait_until(server, lambda: started() == ["1.0", "2.0"], "two jobs run and the third waits for a worker")

        server.send_signal(signal.SIGINT)
        server.wait(timeout=60)

    assert started() == ["1.0", "2.0"]
