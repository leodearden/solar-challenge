# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_network_guard.py, which refuses every name lookup and connection off this machine."""

import socket
import threading
from pathlib import Path

import pytest

from tests._network_guard import refusing_network

# TEST-NET-1 (RFC 5737) is never routed, and the guard refuses before any syscall, so no packet is sent.
_OFF_THIS_MACHINE = ("192.0.2.1", 9)


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
