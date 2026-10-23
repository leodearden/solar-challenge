# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tell the offline lane whether a live service serves the requests an offline-lane job's tests make of it.

Each offline-lane job whose tests need a live service declares this probe,
naming that service, as its outage_probe in dark-factory-orchestrator.yaml. The
probe asks the service what the job's tests ask it, and judges each answer by
whether the service served it, never by what it served:

- Exit 0, printing nothing to stdout, when the service serves every request.
- Otherwise print ONE stdout line, "<service>: <step>: <cause>", for the first
  request it does not serve, then exit os.EX_TEMPFAIL: 75, the outage status of
  dark-factory's LaneCommand.outage_probe. The causes are a fixed vocabulary, so
  the line is identical on every run of one outage: "HTTP <status>" for a 403, a
  429 or any 5xx; "no answer within <timeout> s"; or the name of the requests
  ConnectionError raised (ConnectionError, ProxyError, SSLError, ...). The URL
  and the detail go to stderr.
- Any other status is the service answering, so it is usable: whether its answer
  is right is the job's tests' question.
- Any other exception propagates, a traceback and exit 1, which the lane reads as
  a broken probe.

pvgis: the pvgis job's contract tests, tests/integration/test_pvgis.py, fetch
Bristol's TMY through PvgisTmy, which asks PVGIS_API_URL's tmy and seriescalc
endpoints for Location.bristol() over CLIMATE_YEARS. The probe asks both the
same, and its outage line is "PVGIS: <endpoint>: <cause>".

Usage, from the repository root:

    uv run --locked --extra dev python scripts/outage_probe.py <service> [options]

--help lists the services, and <service> --help the options of one.
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from types import MappingProxyType

import requests

from solar_challenge.location import Location
from solar_challenge.weather import PVGIS_API_URL, PVGIS_TMY_REQUEST

_REQUEST_TIMEOUT_S = 30.0
"""Seconds a request may take to connect, and again to answer. Twice this per request, for the at most two requests a service is asked, plus uv's start, the imports and the name lookups it does not bound, must fit the outage_probe_timeout_secs of every job in dark-factory-orchestrator.yaml that declares this probe."""

_PVGIS_ENDPOINTS = ("tmy", "seriescalc")
"""The PVGIS endpoints PvgisTmy reads, in the order it reads them."""

_BRISTOL = Location.bristol()

_PVGIS_QUERY: Mapping[str, float | str] = MappingProxyType(
    {
        "lat": _BRISTOL.latitude,
        "lon": _BRISTOL.longitude,
        **{name: str(PVGIS_TMY_REQUEST[name]) for name in ("outputformat", "startyear", "endyear")},
    }
)
"""What each PVGIS endpoint is asked for: the contract tests' point, and the arguments of their TMY request that get_pvgis_tmy sends PVGIS as query parameters of the same name."""


@dataclass(frozen=True)
class _Request:
    """A GET the probe sends a service: the step its outage line names, the URL, and the query sent with it."""

    step: str
    url: str
    query: Mapping[str, float | str] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class _Service:
    """A live service an offline-lane job's tests need: the name its outage line gives, and the requests it is sent, in order."""

    name: str
    requests: tuple[_Request, ...]


@dataclass(frozen=True)
class _Outage:
    """A request the service does not serve: the cause the outage line names, and the detail stderr gives."""

    cause: str
    detail: str


def _is_outage_status(status: int) -> bool:
    """Whether *status* is the service refusing a request or failing to serve it."""
    return status in (HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS) or status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _outage_at(request: _Request, timeout: float) -> _Outage | None:
    """The outage *request* meets, or None when the service serves it; no body is read."""
    try:
        with requests.get(request.url, params=request.query, timeout=timeout, stream=True) as response:
            status, reason = response.status_code, response.reason
    except requests.Timeout as error:
        return _Outage(f"no answer within {timeout:g} s", str(error))
    except requests.ConnectionError as error:
        return _Outage(type(error).__name__, str(error))
    return _Outage(f"HTTP {status}", reason) if _is_outage_status(status) else None


def _pvgis(options: argparse.Namespace) -> _Service:
    """PVGIS, asked each endpoint PvgisTmy reads of the API release options.api_url names."""
    return _Service(
        "PVGIS",
        tuple(_Request(endpoint, options.api_url + endpoint, _PVGIS_QUERY) for endpoint in _PVGIS_ENDPOINTS),
    )


def _parser() -> argparse.ArgumentParser:
    every_service = argparse.ArgumentParser(add_help=False)
    every_service.add_argument(
        "--timeout",
        type=float,
        default=_REQUEST_TIMEOUT_S,
        help="seconds a request may take to connect, and again to answer (default: %(default)g)",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    services = parser.add_subparsers(title="services", metavar="<service>", required=True)
    pvgis = services.add_parser(
        "pvgis", parents=[every_service], help="PVGIS, whose TMY the pvgis job's contract tests fetch"
    )
    pvgis.add_argument(
        "--api-url",
        default=PVGIS_API_URL,
        help="the PVGIS API release to ask, ending in a slash (default: %(default)s)",
    )
    pvgis.set_defaults(service_of=_pvgis)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    service: _Service = options.service_of(options)
    for request in service.requests:
        outage = _outage_at(request, options.timeout)
        if outage is not None:
            print(f"{service.name}: {request.step}: {outage.cause}")
            print(f"{request.url}: {outage.detail}", file=sys.stderr)
            return os.EX_TEMPFAIL
    return 0


if __name__ == "__main__":
    sys.exit(main())
