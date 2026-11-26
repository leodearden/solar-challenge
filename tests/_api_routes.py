# SPDX-License-Identifier: AGPL-3.0-or-later
"""The routes of the dashboard's api blueprint, read from its url_map, so a test parametrized over them covers a route added later without listing it.

Usage::

    from tests._api_routes import api_routes

    @pytest.mark.parametrize(
        ("method", "path"),
        [pytest.param(route.method, route.path, id=route.endpoint) for route in api_routes({"POST"})],
    )
    def test_every_post_route(client: FlaskClient, method: str, path: str) -> None:
        resp = client.open(path, method=method, json=[1])
"""

from collections.abc import Collection
from typing import NamedTuple

from flask import Flask

from solar_challenge.web.api import api_bp


class ApiRoute(NamedTuple):
    """One route of the api blueprint answering one method: its endpoint, e.g. api.simulate_home_api, that method, and a path that reaches it."""

    endpoint: str
    method: str
    path: str


def api_routes(methods: Collection[str]) -> tuple[ApiRoute, ...]:
    """Return every route of the api blueprint that answers one of *methods*, one entry per route and method.

    A path argument is filled with a value that names no record, e.g. no-such-run_id.
    """
    api_only = Flask(__name__, static_folder=None)
    api_only.register_blueprint(api_bp)
    urls = api_only.url_map.bind("localhost")
    return tuple(
        ApiRoute(
            rule.endpoint,
            method,
            urls.build(rule.endpoint, {name: f"no-such-{name}" for name in rule.arguments}, method=method),
        )
        for rule in api_only.url_map.iter_rules()
        for method in sorted(set(methods).intersection(rule.methods or ()))
    )
