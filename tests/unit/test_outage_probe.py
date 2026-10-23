# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for scripts/outage_probe.py, run in-process against stand-ins on this machine for the services it asks."""

import json
import os
import re
import socket
import socketserver
import textwrap
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from types import ModuleType
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from solar_challenge.location import Location
from solar_challenge.weather import CLIMATE_YEARS
from tests._scripts import load_script

_THIS_MACHINE = "127.0.0.1"


def _origin_on(port: int) -> str:
    """The origin of a server on *port* of this machine."""
    return f"http://{_THIS_MACHINE}:{port}"


def _pvgis_api_url_at(origin: str) -> str:
    """The URL of a PVGIS API release served at *origin*, ending in a slash as PVGIS_API_URL does."""
    return f"{origin}/api/v5_3/"


@dataclass(frozen=True)
class _ReceivedRequest:
    """A request the stand-in received: its name, the last segment of its path, and its query as parse_qs reads it."""

    name: str
    query: dict[str, list[str]]


class _ServiceStandIn(socketserver.TCPServer):
    """An HTTP server on this machine that answers each GET with the status *statuses* sets for its name, 200 for any other, recording each request it receives."""

    def __init__(self, statuses: Mapping[str, int]) -> None:
        self.statuses = statuses
        self.received: list[_ReceivedRequest] = []
        super().__init__((_THIS_MACHINE, 0), _AnswersWithTheNamesStatus)


class _AnswersWithTheNamesStatus(BaseHTTPRequestHandler):
    server: _ServiceStandIn

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        name = PurePosixPath(url.path).name
        self.server.received.append(_ReceivedRequest(name, parse_qs(url.query)))
        body = b"stand-in"
        self.send_response(self.server.statuses.get(name, HTTPStatus.OK))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def _stand_in(statuses: Mapping[str, int]) -> Iterator[tuple[str, list[_ReceivedRequest]]]:
    """Serve a _ServiceStandIn answering with *statuses*, and yield its origin and the requests it receives."""
    with _ServiceStandIn(statuses) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield _origin_on(server.server_address[1]), server.received
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    """scripts/outage_probe.py."""
    return load_script("outage_probe")


def test_pvgis_serving_every_request_is_usable(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with _stand_in({}) as (origin, received):
        exit_status = probe.main(["pvgis", "--api-url", _pvgis_api_url_at(origin)])

    bristol = Location.bristol()
    point_and_years = {
        "lat": [str(bristol.latitude)],
        "lon": [str(bristol.longitude)],
        "startyear": [str(CLIMATE_YEARS[0])],
        "endyear": [str(CLIMATE_YEARS[-1])],
    }
    asked = [
        (request.name, {parameter: request.query.get(parameter) for parameter in point_and_years})
        for request in received
    ]
    assert (exit_status, capsys.readouterr().out) == (0, "")
    assert asked == [("tmy", point_and_years), ("seriescalc", point_and_years)]


@pytest.mark.parametrize(
    ("endpoint", "status"), [("tmy", 403), ("tmy", 429), ("tmy", 500), ("tmy", 503), ("seriescalc", 502)]
)
def test_an_endpoint_pvgis_refuses_or_fails_is_an_outage_named_on_one_line(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], endpoint: str, status: int
) -> None:
    with _stand_in({endpoint: status}) as (origin, _):
        exit_status = probe.main(["pvgis", "--api-url", _pvgis_api_url_at(origin)])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, f"PVGIS: {endpoint}: HTTP {status}\n")


@pytest.mark.parametrize("status", [400, 404])
def test_an_answer_pvgis_gave_to_a_request_it_judged_is_no_outage(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    """So the red goes to the confirm, and the contract tests say what changed."""
    with _stand_in({"tmy": status}) as (origin, _):
        exit_status = probe.main(["pvgis", "--api-url", _pvgis_api_url_at(origin)])

    assert (exit_status, capsys.readouterr().out) == (0, "")


def test_a_connection_this_machine_refuses_is_an_outage(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    """The port is bound but never listened on, so the kernel refuses each connection, and no other socket can take it."""
    with socket.socket() as never_listens:
        never_listens.bind((_THIS_MACHINE, 0))
        api_url = _pvgis_api_url_at(_origin_on(never_listens.getsockname()[1]))
        exit_status = probe.main(["pvgis", "--api-url", api_url])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, "PVGIS: tmy: ConnectionError\n")


def test_no_answer_within_the_timeout_is_an_outage(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with socket.create_server((_THIS_MACHINE, 0)) as never_accepts:
        api_url = _pvgis_api_url_at(_origin_on(never_accepts.getsockname()[1]))
        exit_status = probe.main(["pvgis", "--api-url", api_url, "--timeout", "0.2"])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, "PVGIS: tmy: no answer within 0.2 s\n")


def test_a_request_the_probe_cannot_send_raises_instead_of_reporting_an_outage(probe: ModuleType) -> None:
    """So the lane reads a broken probe and keeps filing the red: a defect of the probe's cannot pose as an outage."""
    with pytest.raises(requests.exceptions.MissingSchema):
        probe.main(["pvgis", "--api-url", "re.jrc.ec.europa.eu/api/v5_3/"])


_EDITABLE_PROJECT = """
[[package]]
name = "demo-project"
version = "0.1.0"
source = { editable = "." }
"""
"""uv.lock's table for the project's own package, which uv installs from the working tree, not from a registry."""

_NPM_ROOT = ("", {"devDependencies": {"demo": "^1.0.0"}})
"""package-lock.json's entry for the project itself, which nothing resolves."""


def _demo_package_pinned_from(origin: str) -> str:
    """uv.lock's table for demo-package 1.0, pinned from the registry <origin>/simple, its sdist listed before its wheel as uv lists them."""
    return textwrap.dedent(
        f"""
        [[package]]
        name = "demo-package"
        version = "1.0"
        source = {{ registry = "{origin}/simple" }}
        sdist = {{ url = "{origin}/packages/demo_package-1.0.tar.gz" }}
        wheels = [
            {{ url = "{origin}/packages/demo_package-1.0-py3-none-any.whl" }},
        ]
        """
    )


def _uv_lock(*packages: str) -> str:
    """The text of a uv.lock holding the [[package]] tables *packages*, in order."""
    return 'version = 1\nrevision = 3\nrequires-python = ">=3.11"\n' + "".join(packages)


def _demo_resolved_at(origin: str) -> tuple[str, dict[str, str]]:
    """package-lock.json's entry for demo 1.0.0, resolved at the registry *origin*."""
    return "node_modules/demo", {"version": "1.0.0", "resolved": f"{origin}/demo/-/demo-1.0.0.tgz"}


def _package_lock(*packages: tuple[str, object]) -> str:
    """The text of a lockfileVersion 3 package-lock.json whose packages are the (path, entry) pairs *packages*, in order."""
    return json.dumps({"name": "web", "lockfileVersion": 3, "requires": True, "packages": dict(packages)}, indent=2)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_pypi_serving_the_index_page_and_a_file_of_the_first_registry_package_is_usable(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """It asks nothing for the project's own package, which no registry serves."""
    with _stand_in({}) as (origin, received):
        lock = _write(tmp_path / "uv.lock", _uv_lock(_EDITABLE_PROJECT, _demo_package_pinned_from(origin)))
        exit_status = probe.main(["pypi", "--uv-lock", str(lock)])

    assert (exit_status, capsys.readouterr().out) == (0, "")
    assert [request.name for request in received] == ["demo-package", "demo_package-1.0-py3-none-any.whl"]


@pytest.mark.parametrize(
    ("step", "requested"), [("index", "demo-package"), ("files", "demo_package-1.0-py3-none-any.whl")]
)
def test_a_pypi_step_that_fails_is_an_outage_named_on_one_line(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path, step: str, requested: str
) -> None:
    with _stand_in({requested: 503}) as (origin, _):
        lock = _write(tmp_path / "uv.lock", _uv_lock(_EDITABLE_PROJECT, _demo_package_pinned_from(origin)))
        exit_status = probe.main(["pypi", "--uv-lock", str(lock)])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, f"PyPI: {step}: HTTP 503\n")


def test_the_npm_registry_serving_the_first_resolved_tarball_is_usable(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with _stand_in({}) as (origin, received):
        lock = _write(tmp_path / "package-lock.json", _package_lock(_NPM_ROOT, _demo_resolved_at(origin)))
        exit_status = probe.main(["npm", "--package-lock", str(lock)])

    assert (exit_status, capsys.readouterr().out) == (0, "")
    assert [request.name for request in received] == ["demo-1.0.0.tgz"]


def test_a_tarball_the_npm_registry_fails_to_serve_is_an_outage_named_on_one_line(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with _stand_in({"demo-1.0.0.tgz": 503}) as (origin, _):
        lock = _write(tmp_path / "package-lock.json", _package_lock(_NPM_ROOT, _demo_resolved_at(origin)))
        exit_status = probe.main(["npm", "--package-lock", str(lock)])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, "npm registry: tarball: HTTP 503\n")


@pytest.mark.parametrize(
    ("service", "option", "lock_name", "lock_text"),
    [
        pytest.param("pypi", "--uv-lock", "uv.lock", _uv_lock(_EDITABLE_PROJECT), id="pypi"),
        pytest.param("npm", "--package-lock", "package-lock.json", _package_lock(_NPM_ROOT), id="npm"),
    ],
)
def test_a_lock_naming_nothing_to_ask_raises_naming_the_lock(
    probe: ModuleType, tmp_path: Path, service: str, option: str, lock_name: str, lock_text: str
) -> None:
    """So the lane reads a broken probe, never a check of nothing passing as usable."""
    lock = _write(tmp_path / lock_name, lock_text)

    with pytest.raises(ValueError, match=re.escape(str(lock))):
        probe.main([service, option, str(lock)])
