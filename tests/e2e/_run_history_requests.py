# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold the Run History page's runs-list requests unanswered until the test answers them.

is_runs_list_request picks those requests out; hold_requests holds each request a page makes that such a predicate matches.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route


def is_runs_list_request(url: str) -> bool:
    """Whether url asks for Run History's runs list, whatever its query."""
    return urlsplit(url).path == "/api/history/runs"


def hold_requests(page: Page, matches: Callable[[str], bool]) -> Sequence[Route]:
    """Hold, unanswered, each request page makes whose URL matches; return the routes held, which grow as page makes them."""
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route(matches, hold)
    return held
