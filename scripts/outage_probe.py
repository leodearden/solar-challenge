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

pypi: the interpreter-matrix and newest-releases jobs install what uv.lock pins
from PyPI, and newest-releases also resolves the newest releases from its
index. So the probe asks the index page, then one file, of the first package
uv.lock pins from a registry, its wheels before its sdist, and its outage line
is "PyPI: index: <cause>" or "PyPI: files: <cause>".

npm: the css-build job's npm ci installs, from the registry, the tarballs
package-lock.json resolves at http(s) URLs. So the probe asks for the first of
them, and its outage line is "npm registry: tarball: <cause>".

Neither the pypi nor the npm probe reads a body, so neither downloads a file.

Usage, from the repository root:

    uv run --locked --extra dev python scripts/outage_probe.py <service> [options]

--help lists the services, and <service> --help the options of one.
"""

import argparse
import json
import os
import sys
import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar
from urllib.parse import urlsplit

import requests

from solar_challenge.location import Location
from solar_challenge.weather import PVGIS_API_URL, PVGIS_TMY_REQUEST

_REPOSITORY = Path(__file__).resolve().parents[1]

_T = TypeVar("_T")

_REQUEST_TIMEOUT_S = 30.0
"""Seconds a request may take to connect, and again to answer. Twice this per request, for the at most two requests a service is asked, plus uv's start, the imports and the name lookups it does not bound, must fit the outage_probe_timeout_secs of every job in dark-factory-orchestrator.yaml that declares this probe."""

_PVGIS_ENDPOINTS = ("tmy", "seriescalc")
"""The PVGIS endpoints PvgisTmy reads, in the order it reads them."""


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


def _pvgis(api_url: str) -> _Service:
    """PVGIS, asked each endpoint PvgisTmy reads of the API release *api_url*.

    Each is asked for the contract tests' point, with the arguments of their TMY
    request that get_pvgis_tmy sends PVGIS as query parameters of the same name.
    """
    bristol = Location.bristol()
    query: Mapping[str, float | str] = MappingProxyType(
        {
            "lat": bristol.latitude,
            "lon": bristol.longitude,
            **{name: str(PVGIS_TMY_REQUEST[name]) for name in ("outputformat", "startyear", "endyear")},
        }
    )
    return _Service("PVGIS", tuple(_Request(endpoint, api_url + endpoint, query) for endpoint in _PVGIS_ENDPOINTS))


def _pypi(uv_lock: Path) -> _Service:
    """PyPI, asked the index page, then the first file, of the first package *uv_lock* pins from a registry."""
    packages = tomllib.loads(uv_lock.read_text(encoding="utf-8")).get("package", [])
    package = _first(
        (package for package in packages if "registry" in package["source"]), uv_lock, "package pinned from a registry"
    )
    pinned = _first(_files_pinned_for(package), uv_lock, f"file of {package['name']}")
    registry = package["source"]["registry"].rstrip("/")
    return _Service("PyPI", (_Request("index", f"{registry}/{package['name']}/"), _Request("files", pinned["url"])))


def _files_pinned_for(package: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """The files uv.lock pins for *package*, its wheels before its sdist."""
    yield from package.get("wheels", [])
    if "sdist" in package:
        yield package["sdist"]


def _npm(package_lock: Path) -> _Service:
    """The npm registry, asked for the first tarball *package_lock* resolves at an http(s) URL."""
    packages: Mapping[str, Any] = json.loads(package_lock.read_text(encoding="utf-8")).get("packages", {})
    resolved = (entry.get("resolved", "") for entry in packages.values())
    tarball = _first(
        (url for url in resolved if urlsplit(url).scheme in ("http", "https")),
        package_lock,
        "tarball resolved at an http(s) URL",
    )
    return _Service("npm registry", (_Request("tarball", tarball),))


def _first(items: Iterable[_T], lock: Path, what: str) -> _T:
    """The first of *items*, read from *lock*; with none, a ValueError saying *lock* names no *what*, so the lane reads a broken probe."""
    for item in items:
        return item
    raise ValueError(f"{lock} names no {what}, so the probe has nothing to ask")


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
    pvgis.set_defaults(service_of=lambda options: _pvgis(options.api_url))
    pypi = services.add_parser(
        "pypi",
        parents=[every_service],
        help="PyPI, from which the interpreter-matrix and newest-releases jobs install what uv.lock pins",
    )
    pypi.add_argument(
        "--uv-lock",
        type=Path,
        default=_REPOSITORY / "uv.lock",
        help="the uv.lock whose first package pinned from a registry is asked for (default: %(default)s)",
    )
    pypi.set_defaults(service_of=lambda options: _pypi(options.uv_lock))
    npm = services.add_parser(
        "npm",
        parents=[every_service],
        help="the npm registry, from which the css-build job's npm ci installs what package-lock.json resolves",
    )
    npm.add_argument(
        "--package-lock",
        type=Path,
        default=_REPOSITORY / "src" / "solar_challenge" / "web" / "package-lock.json",
        help="the package-lock.json whose first resolved tarball is asked for (default: %(default)s)",
    )
    npm.set_defaults(service_of=lambda options: _npm(options.package_lock))
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
