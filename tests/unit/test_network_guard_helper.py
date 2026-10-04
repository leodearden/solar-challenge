# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_network_guard.py, which refuses every name lookup and connection off this machine."""

import http.client
import os
import socket
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests._network_guard import refusing_network

# TEST-NET-1 (RFC 5737) is never routed, and the guard refuses before any syscall, so no packet is sent.
_OFF_THIS_MACHINE = ("192.0.2.1", 9)


def _fetch_in_a_child_process(url: str) -> subprocess.CompletedProcess[str]:
    """Fetch *url* with urllib in a child Python process, with this process's environment; it prints the body, or exits non-zero."""
    program = f"import urllib.request; print(urllib.request.urlopen({url!r}, timeout=30).read().decode())"
    return subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=120)


def _send_to_the_proxy(method: str, request_target: str) -> int:
    """Send a *method* request for *request_target* to the proxy HTTP_PROXY names, as a client that honours it does, and return the answer's status."""
    proxy = urlsplit(os.environ["HTTP_PROXY"])
    connection = http.client.HTTPConnection(str(proxy.hostname), proxy.port, timeout=30)
    try:
        connection.request(method, request_target)
        return connection.getresponse().status
    finally:
        connection.close()


class _AnswersOk(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def loopback_server_port() -> Iterator[int]:
    """Serve HTTP on 127.0.0.1, answering every GET with 200 "ok", and yield its port."""
    with socketserver.TCPServer(("127.0.0.1", 0), _AnswersOk) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            thread.join()


class TestRefusingNetwork:
    def test_a_connection_to_a_host_off_this_machine_is_refused_and_recorded(self) -> None:
        with refusing_network() as refused, socket.socket() as sock:
            with pytest.raises(ConnectionRefusedError, match="192.0.2.1:9"):
                sock.connect(_OFF_THIS_MACHINE)
            with pytest.raises(ConnectionRefusedError, match="192.0.2.1:9"):
                sock.connect_ex(_OFF_THIS_MACHINE)

        assert refused == ["192.0.2.1:9", "192.0.2.1:9"]

    def test_a_name_lookup_of_a_host_off_this_machine_is_refused_and_recorded(self) -> None:
        with refusing_network() as refused:
            with pytest.raises(ConnectionRefusedError, match="example.invalid:443"):
                socket.getaddrinfo("example.invalid", 443)

        assert refused == ["example.invalid:443"]

    def test_a_connection_from_another_thread_is_refused_and_recorded(self) -> None:
        def connect_off_this_machine() -> None:
            with socket.socket() as sock, pytest.raises(ConnectionRefusedError):
                sock.connect(_OFF_THIS_MACHINE)

        with refusing_network() as refused:
            thread = threading.Thread(target=connect_off_this_machine)
            thread.start()
            thread.join()

        assert refused == ["192.0.2.1:9"]

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
    def test_a_connection_to_this_machine_goes_through(self, host: str) -> None:
        with socket.create_server(("127.0.0.1", 0)) as server:
            port = server.getsockname()[1]
            with refusing_network() as refused:
                socket.create_connection((host, port), timeout=5).close()

        assert refused == []

    def test_a_unix_domain_connection_goes_through(self, tmp_path: Path) -> None:
        path = str(tmp_path / "socket")
        with socket.socket(socket.AF_UNIX) as server, socket.socket(socket.AF_UNIX) as client:
            server.bind(path)
            server.listen()
            with refusing_network() as refused:
                client.connect(path)

        assert refused == []

    def test_leaving_restores_what_it_replaced(self) -> None:
        before = (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex)

        with refusing_network():
            pass

        assert (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex) == before

    @pytest.mark.parametrize(
        ("url", "destination"),
        [("https://example.invalid/", "example.invalid:443"), ("http://example.invalid/path", "example.invalid:80")],
    )
    def test_a_child_processs_request_to_a_host_off_this_machine_is_refused_and_recorded(
        self, url: str, destination: str
    ) -> None:
        with refusing_network() as refused:
            child = _fetch_in_a_child_process(url)

        assert child.returncode != 0, child.stdout
        assert refused == [destination], child.stderr

    def test_an_inherited_no_proxy_cannot_exempt_a_child_processs_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "example.invalid")

        with refusing_network() as refused:
            child = _fetch_in_a_child_process("https://example.invalid/")

        assert child.returncode != 0, child.stdout
        assert refused == ["example.invalid:443"], child.stderr

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
    def test_a_child_processs_request_to_this_machine_goes_through(self, host: str, loopback_server_port: int) -> None:
        with refusing_network() as refused:
            child = _fetch_in_a_child_process(f"http://{host}:{loopback_server_port}/")

        assert (child.returncode, child.stdout) == (0, "ok\n"), child.stderr
        assert refused == []

    def test_a_request_from_this_process_that_honours_the_proxy_variables_is_refused_and_recorded(self) -> None:
        """It goes through a fresh opener, as urlopen's process-wide one keeps the proxy variables of its first use."""
        with refusing_network() as refused:
            with pytest.raises(urllib.error.URLError):
                urllib.request.build_opener().open("https://example.invalid/", timeout=30)

        assert refused == ["example.invalid:443"]

    @pytest.mark.parametrize("method", ["PROPFIND", "TRACE"])
    def test_a_request_of_any_method_through_the_proxy_is_refused_and_recorded(self, method: str) -> None:
        with refusing_network() as refused:
            status = _send_to_the_proxy(method, "http://example.invalid/")

        assert (status, refused) == (HTTPStatus.FORBIDDEN, ["example.invalid:80"])

    @pytest.mark.parametrize(
        "request_target",
        ["/path", "http://example.invalid:no-port/", "ftp://example.invalid/"],
        ids=["origin-form", "port-not-a-number", "scheme-without-a-default-port"],
    )
    def test_a_request_through_the_proxy_whose_target_names_no_host_and_port_is_refused_and_recorded_as_sent(
        self, request_target: str
    ) -> None:
        with refusing_network() as refused:
            status = _send_to_the_proxy("GET", request_target)

        assert (status, refused) == (HTTPStatus.FORBIDDEN, [request_target])

    def test_leaving_restores_the_environment_it_replaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HTTP_PROXY", "http://the-callers-proxy.invalid:3128")
        monkeypatch.delenv("ALL_PROXY", raising=False)
        before = dict(os.environ)

        with refusing_network():
            pass

        assert dict(os.environ) == before
