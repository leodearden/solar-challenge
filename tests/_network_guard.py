# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refuse every name lookup and connection off this machine, so a test that reaches the network is caught.

``refusing_network`` patches the stdlib socket calls every Python HTTP client goes
through, so it refuses a fetch from any thread. Loopback, unspecified and
Unix-domain destinations still go through.

Usage::

    from tests._network_guard import refusing_network

    with refusing_network() as refused:
        run_code_that_must_stay_on_this_machine()
    assert refused == []
"""

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

_NAMES_OF_THIS_MACHINE = frozenset({"", "localhost"})
_INTERNET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})


@contextmanager
def refusing_network() -> Iterator[list[str]]:
    """While open, refuse every name lookup and connection, from any thread, whose host is not this machine.

    Yields the refused destinations as "host:port", in order. Each refusal raises
    ConnectionRefusedError, an OSError, so an HTTP client reports a failed connection.
    """
    refused: list[str] = []
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def refusal(host: object, port: object) -> ConnectionRefusedError:
        destination = f"{host}:{port}"
        refused.append(destination)
        return ConnectionRefusedError(f"{destination} is off this machine, and this test runs offline")

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

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "getaddrinfo", getaddrinfo)
        patch.setattr(socket.socket, "connect", connect)
        patch.setattr(socket.socket, "connect_ex", connect_ex)
        yield refused


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
