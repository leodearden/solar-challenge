# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for scripts/pvgis_outage_probe.py, run in-process against a PVGIS stand-in on this machine."""

import os
import socket
import socketserver
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from types import ModuleType
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from solar_challenge.location import Location
from solar_challenge.weather import CLIMATE_YEARS
from tests._scripts import load_script

_THIS_MACHINE = "127.0.0.1"


def _api_url_on(port: int) -> str:
    """The URL of a PVGIS API release served on *port* of this machine, ending in a slash as PVGIS_API_URL does."""
    return f"http://{_THIS_MACHINE}:{port}/api/v5_3/"


@dataclass(frozen=True)
class _ReceivedRequest:
    """A request the stand-in received: its endpoint, the last segment of its path, and its query as parse_qs reads it."""

    endpoint: str
    query: dict[str, list[str]]


class _PvgisStandIn(socketserver.TCPServer):
    """An HTTP server on this machine that answers each GET with the status *statuses* sets for its endpoint, 200 for any other, recording each request it receives."""

    def __init__(self, statuses: Mapping[str, int]) -> None:
        self.statuses = statuses
        self.received: list[_ReceivedRequest] = []
        super().__init__((_THIS_MACHINE, 0), _AnswersWithTheEndpointsStatus)


class _AnswersWithTheEndpointsStatus(BaseHTTPRequestHandler):
    server: _PvgisStandIn

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        endpoint = url.path.rsplit("/", 1)[-1]
        self.server.received.append(_ReceivedRequest(endpoint, parse_qs(url.query)))
        body = b"stand-in"
        self.send_response(self.server.statuses.get(endpoint, HTTPStatus.OK))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def _pvgis_stand_in(statuses: Mapping[str, int]) -> Iterator[tuple[str, list[_ReceivedRequest]]]:
    """Serve a _PvgisStandIn answering with *statuses*, and yield its API URL and the requests it receives."""
    with _PvgisStandIn(statuses) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield _api_url_on(server.server_address[1]), server.received
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    """scripts/pvgis_outage_probe.py."""
    return load_script("pvgis_outage_probe")


def test_pvgis_serving_every_request_is_usable(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with _pvgis_stand_in({}) as (api_url, received):
        exit_status = probe.main(["--api-url", api_url])

    bristol = Location.bristol()
    point_and_years = {
        "lat": [str(bristol.latitude)],
        "lon": [str(bristol.longitude)],
        "startyear": [str(CLIMATE_YEARS[0])],
        "endyear": [str(CLIMATE_YEARS[-1])],
    }
    asked = [(request.endpoint, {name: request.query.get(name) for name in point_and_years}) for request in received]
    assert (exit_status, capsys.readouterr().out) == (0, "")
    assert asked == [("tmy", point_and_years), ("seriescalc", point_and_years)]


@pytest.mark.parametrize(
    ("endpoint", "status"), [("tmy", 403), ("tmy", 429), ("tmy", 500), ("tmy", 503), ("seriescalc", 502)]
)
def test_an_endpoint_pvgis_refuses_or_fails_is_an_outage_named_on_one_line(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], endpoint: str, status: int
) -> None:
    with _pvgis_stand_in({endpoint: status}) as (api_url, _):
        exit_status = probe.main(["--api-url", api_url])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, f"PVGIS: {endpoint}: HTTP {status}\n")


@pytest.mark.parametrize("status", [400, 404])
def test_an_answer_pvgis_gave_to_a_request_it_judged_is_no_outage(
    probe: ModuleType, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    """So the red goes to the confirm, and the contract tests say what changed."""
    with _pvgis_stand_in({"tmy": status}) as (api_url, _):
        exit_status = probe.main(["--api-url", api_url])

    assert (exit_status, capsys.readouterr().out) == (0, "")


def test_a_connection_this_machine_refuses_is_an_outage(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    """The port is bound but never listened on, so the kernel refuses each connection, and no other socket can take it."""
    with socket.socket() as never_listens:
        never_listens.bind((_THIS_MACHINE, 0))
        exit_status = probe.main(["--api-url", _api_url_on(never_listens.getsockname()[1])])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, "PVGIS: tmy: ConnectionError\n")


def test_no_answer_within_the_timeout_is_an_outage(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with socket.create_server((_THIS_MACHINE, 0)) as never_accepts:
        exit_status = probe.main(["--api-url", _api_url_on(never_accepts.getsockname()[1]), "--timeout", "0.2"])

    assert (exit_status, capsys.readouterr().out) == (os.EX_TEMPFAIL, "PVGIS: tmy: no answer within 0.2 s\n")


def test_a_request_the_probe_cannot_send_raises_instead_of_reporting_an_outage(probe: ModuleType) -> None:
    """So the lane reads a broken probe and keeps filing the red: a defect of the probe's cannot pose as an outage."""
    with pytest.raises(requests.exceptions.MissingSchema):
        probe.main(["--api-url", "re.jrc.ec.europa.eu/api/v5_3/"])
