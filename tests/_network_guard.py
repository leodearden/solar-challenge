# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refuse every name lookup and connection off this machine, so a test that reaches the network is caught.

``refusing_network`` patches the stdlib socket calls every Python HTTP client goes
through, so it refuses a fetch from any thread. Loopback, unspecified and
Unix-domain destinations still go through.

A child process is reached through the standard proxy variables, which uv, curl,
and Python's requests and urllib honour. While ``refusing_network`` is open, they
name a proxy of its own on this machine, which forwards nothing: it records each
request's destination as "host:port", like the socket refusals, and refuses it.
NO_PROXY names only this machine, so a child's loopback traffic stays direct.

One limit: a client that reads the proxy variables once, when it is built, keeps
the proxy of the ``refusing_network`` it was built under. Once that has closed,
its requests are refused without being named. urllib's process-wide urlopen
opener and an httpx client are such clients.

Usage::

    from tests._network_guard import refusing_network

    with refusing_network() as refused:
        run_code_that_must_stay_on_this_machine()
    assert refused == []
"""

import ipaddress
import socket
import socketserver
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlsplit

import pytest

_NAMES_OF_THIS_MACHINE = frozenset({"", "localhost"})
_INTERNET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})
_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_NO_PROXY_VARIABLES = ("NO_PROXY", "no_proxy")
_HOSTS_A_CHILD_REACHES_DIRECTLY = "localhost,127.0.0.1,::1"
_PROXY_HOST = "127.0.0.1"
_DEFAULT_PORTS = {"http": 80, "https": 443}


@contextmanager
def refusing_network() -> Iterator[list[str]]:
    """While open, refuse every name lookup and connection, from any thread, whose host is not this machine, and every HTTP(S) request a child process sends through the standard proxy variables.

    Yields the refused destinations as "host:port", in order. A refused lookup or
    connection raises ConnectionRefusedError, an OSError, so an HTTP client reports
    a failed connection; a request through the proxy is answered 403 Forbidden.
    """
    refused: list[str] = []
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def refusal(host: object, port: object) -> ConnectionRefusedError:
        destination = f"{host}:{port}"
        refused.append(destination)
        return ConnectionRefusedError(_reason_for_refusing(destination))

    def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_this_machine(host):
            raise refusal(host, port)
        return real_getaddrinfo(host, port, *args, **kwargs)

    def connect(sock: socket.socket, address: Any) -> None:
        if _leaves_this_machine(sock, address):
            raise refusal(address[0], address[1])
        real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if _leaves_this_machine(sock, address):
            raise refusal(address[0], address[1])
        return real_connect_ex(sock, address)

    with _refusing_proxy(refused.append) as proxy, pytest.MonkeyPatch.context() as patch:
        _send_child_processes_through(proxy, patch)
        patch.setattr(socket, "getaddrinfo", getaddrinfo)
        patch.setattr(socket.socket, "connect", connect)
        patch.setattr(socket.socket, "connect_ex", connect_ex)
        yield refused


def _send_child_processes_through(proxy: str, patch: pytest.MonkeyPatch) -> None:
    """Point the proxy variables a child process inherits at *proxy*, for every host but this machine, whatever they named before."""
    for name in _PROXY_VARIABLES:
        patch.setenv(name, proxy)
    for name in _NO_PROXY_VARIABLES:
        patch.setenv(name, _HOSTS_A_CHILD_REACHES_DIRECTLY)


@contextmanager
def _refusing_proxy(record: Callable[[str], None]) -> Iterator[str]:
    """Serve a _RefusingProxy that records with *record* until the block ends, and yield its URL.

    It loops on handle_request rather than serve_forever, whose shutdown() waits out a poll interval.
    """
    server = _RefusingProxy(record)
    port = server.server_address[1]
    stopping = threading.Event()

    def serve_until_stopping() -> None:
        while not stopping.is_set():
            server.handle_request()

    thread = threading.Thread(target=serve_until_stopping, daemon=True)
    thread.start()
    try:
        yield f"http://{_PROXY_HOST}:{port}"
    finally:
        stopping.set()
        socket.create_connection((_PROXY_HOST, port)).close()
        thread.join()
        server.server_close()


class _RefusingProxy(socketserver.ThreadingTCPServer):
    """An HTTP proxy on this machine that records every request's destination and refuses it.

    Not an http.server.HTTPServer, whose bind looks up this machine's name.
    Its handlers run in daemon threads, so a client that never sends keeps no one waiting.
    """

    daemon_threads = True

    def __init__(self, record: Callable[[str], None]) -> None:
        self.record = record
        super().__init__((_PROXY_HOST, 0), _RefusingHandler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Stay silent when a client hangs up before its refusal is written."""
        if not isinstance(sys.exception(), ConnectionError):
            super().handle_error(request, client_address)


class _RefusingHandler(BaseHTTPRequestHandler):
    server: _RefusingProxy

    def _refuse(self) -> None:
        destination = self.path if self.command == "CONNECT" else _destination_of(self.path)
        self.server.record(destination)
        self.send_error(HTTPStatus.FORBIDDEN, _reason_for_refusing(destination))

    do_CONNECT = do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _destination_of(request_target: str) -> str:
    """Return the "host:port" an absolute-form request target names, or the target itself if it names none."""
    try:
        url = urlsplit(request_target)
        port = url.port or _DEFAULT_PORTS.get(url.scheme)
    except ValueError:
        return request_target
    if url.hostname is None or port is None:
        return request_target
    return f"{url.hostname}:{port}"


def _reason_for_refusing(destination: str) -> str:
    return f"{destination} is off this machine, and this test runs offline"


def _leaves_this_machine(sock: socket.socket, address: Any) -> bool:
    return sock.family in _INTERNET_FAMILIES and not _is_this_machine(address[0])


def _is_this_machine(host: object) -> bool:
    if host is None:
        return True
    name = host.decode() if isinstance(host, bytes) else str(host)
    if name.lower() in _NAMES_OF_THIS_MACHINE:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified
