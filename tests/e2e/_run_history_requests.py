# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold the Run History page's runs-list requests unanswered until the test answers them.

is_runs_list_request picks those requests out; hold_requests holds each request a page makes that such a predicate
matches, and HeldRequests.answer_each answers each request the page has made, however late Playwright hands it over.
tests/e2e/test_run_history_requests.py holds the contract.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route


def is_runs_list_request(url: str) -> bool:
    """Whether url asks for Run History's runs list, whatever its query."""
    return urlsplit(url).path == "/api/history/runs"


class HeldRequests:
    """The requests a page makes whose URL matches, each held unanswered until answer_each answers it.

    Playwright hands each one to this process some time after the page makes it, so iterating yields only those handed
    over so far, while answer_each also answers each one handed over later.
    """

    def __init__(self) -> None:
        self._handed_over: list[Route] = []
        self._answer: Callable[[Route], None] | None = None

    def receive(self, route: Route) -> None:
        """Hold route, the page.route handler's argument, or answer it at once if answer_each has been called."""
        self._handed_over.append(route)
        if self._answer is not None:
            self._answer(route)

    def answer_each(self, answer: Callable[[Route], None]) -> None:
        """Answer with answer each request held so far, and each one Playwright hands over from now on."""
        held_so_far = tuple(self._handed_over)
        self._answer = answer
        for route in held_so_far:
            answer(route)

    def __len__(self) -> int:
        return len(self._handed_over)

    def __iter__(self) -> Iterator[Route]:
        return iter(tuple(self._handed_over))


def hold_requests(page: Page, matches: Callable[[str], bool]) -> HeldRequests:
    """Hold, unanswered, each request page makes whose URL matches, until the returned HeldRequests answers it."""
    held = HeldRequests()
    page.route(matches, held.receive)
    return held
