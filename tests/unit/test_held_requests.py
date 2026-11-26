# SPDX-License-Identifier: AGPL-3.0-or-later
"""HeldRequests (tests/e2e/_run_history_requests.py) answers each route handed to it exactly once, whether Playwright hands it over before answer_each, while answer_each answers another, or after, and holds only the routes it has not answered.

HeldRequests only passes its routes to the answer, so these tests hand it sentinel objects and the verify runs them
without a browser.
"""

import pytest

from tests.e2e._run_history_requests import HeldRequests


def test_a_route_handed_over_before_answer_each_is_held_until_answer_each_answers_it_once() -> None:
    held = HeldRequests()
    route = object()
    held.receive(route)
    assert list(held) == [route]

    answered: list[object] = []
    held.answer_each(answered.append)

    assert answered == [route]
    assert list(held) == []


def test_a_route_handed_over_while_answer_each_answers_another_is_answered_once() -> None:
    """As Playwright's dispatcher can hand over a route while answering another blocks the test's greenlet."""
    held = HeldRequests()
    first, handed_over_meanwhile = object(), object()
    held.receive(first)
    answered: list[object] = []

    def answer(route: object) -> None:
        answered.append(route)
        if route is first:
            held.receive(handed_over_meanwhile)

    held.answer_each(answer)

    assert answered == [first, handed_over_meanwhile]
    assert list(held) == []


def test_a_route_handed_over_after_answer_each_is_answered_at_once_and_not_held() -> None:
    held = HeldRequests()
    answered: list[object] = []
    held.answer_each(answered.append)

    route = object()
    held.receive(route)

    assert answered == [route]
    assert list(held) == []


def test_answer_each_refuses_a_second_call_and_answers_nothing_again() -> None:
    held = HeldRequests()
    route = object()
    held.receive(route)
    answered: list[object] = []
    held.answer_each(answered.append)

    with pytest.raises(RuntimeError, match="answer_each has already been called on this HeldRequests"):
        held.answer_each(answered.append)

    assert answered == [route]
