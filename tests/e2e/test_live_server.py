"""The e2e live server must answer other requests while a connection stays open.

A page's job-progress EventSource streams stay open while their jobs run. A server
that handles one connection at a time therefore makes every other request,
including the next test's page load, wait behind them.
"""

import socket
import urllib.request
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.e2e


def test_live_server_answers_while_another_connection_is_open(live_server: str) -> None:
    address = urlsplit(live_server)
    with socket.create_connection((address.hostname, address.port)):
        with urllib.request.urlopen(live_server + "/", timeout=10) as response:
            assert response.status == 200
