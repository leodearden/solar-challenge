# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tell the offline lane whether PVGIS serves the requests the pvgis job's contract tests make.

The contract tests, tests/integration/test_pvgis.py, fetch Bristol's TMY through
PvgisTmy, which asks PVGIS_API_URL's tmy and seriescalc endpoints for
Location.bristol() over CLIMATE_YEARS. This probe asks both the same, and judges
each answer by whether PVGIS served it, never by what it served:

- Exit 0, printing nothing to stdout, when PVGIS serves both.
- Otherwise print ONE stdout line, "PVGIS: <endpoint>: <cause>", for the first
  endpoint it does not serve, then exit os.EX_TEMPFAIL: 75, the outage status of
  dark-factory's LaneCommand.outage_probe. The causes are a fixed vocabulary, so
  the line is identical on every run of one outage: "HTTP <status>" for a 403, a
  429 or any 5xx; "no answer within <timeout> s"; or the name of the requests
  ConnectionError raised (ConnectionError, ProxyError, SSLError, ...). The URL
  and the detail go to stderr.
- Any other status is PVGIS answering, so it is usable: whether its answer is
  right is the contract tests' question.
- Any other exception propagates, a traceback and exit 1, which the lane reads as
  a broken probe.

Usage, from the repository root:

    uv run --locked --extra dev python scripts/pvgis_outage_probe.py [--api-url URL] [--timeout SECONDS]
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from types import MappingProxyType

import requests

from solar_challenge.location import Location
from solar_challenge.weather import PVGIS_API_URL, PVGIS_TMY_REQUEST

_ENDPOINTS = ("tmy", "seriescalc")
"""The PVGIS endpoints PvgisTmy reads, in the order it reads them."""

_BRISTOL = Location.bristol()

_QUERY: Mapping[str, float | str] = MappingProxyType(
    {
        "lat": _BRISTOL.latitude,
        "lon": _BRISTOL.longitude,
        **{name: str(PVGIS_TMY_REQUEST[name]) for name in ("outputformat", "startyear", "endyear")},
    }
)
"""What each endpoint is asked for: the contract tests' point, and the arguments of their TMY request that get_pvgis_tmy sends PVGIS as query parameters of the same name."""

_REQUEST_TIMEOUT_S = 30.0
"""Seconds a request may take to connect, and again to answer: both requests fit dark-factory's default outage_probe_timeout_secs of 180."""


@dataclass(frozen=True)
class _Outage:
    """An endpoint PVGIS does not serve: the cause the outage line names, and the detail stderr gives."""

    cause: str
    detail: str


def _is_outage_status(status: int) -> bool:
    """Whether *status* is PVGIS refusing a request or failing to serve it."""
    return status in (HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS) or status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _outage_at(url: str, timeout: float) -> _Outage | None:
    """The outage a GET of *url* with _QUERY meets, or None when PVGIS serves it; no body is read."""
    try:
        with requests.get(url, params=_QUERY, timeout=timeout, stream=True) as response:
            status, reason = response.status_code, response.reason
    except requests.Timeout as error:
        return _Outage(f"no answer within {timeout:g} s", str(error))
    except requests.ConnectionError as error:
        return _Outage(type(error).__name__, str(error))
    return _Outage(f"HTTP {status}", reason) if _is_outage_status(status) else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--api-url",
        default=PVGIS_API_URL,
        help="the PVGIS API release to ask, ending in a slash (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_REQUEST_TIMEOUT_S,
        help="seconds a request may take to connect, and again to answer (default: %(default)g)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    for endpoint in _ENDPOINTS:
        url = options.api_url + endpoint
        outage = _outage_at(url, options.timeout)
        if outage is not None:
            print(f"PVGIS: {endpoint}: {outage.cause}")
            print(f"{url}: {outage.detail}", file=sys.stderr)
            return os.EX_TEMPFAIL
    return 0


if __name__ == "__main__":
    sys.exit(main())
