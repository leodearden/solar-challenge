# SPDX-License-Identifier: AGPL-3.0-or-later
"""A read of a page's settled state finishes the CSS transitions running there, so it sees the values they end at without waiting for the frames that run them, which a loaded host can withhold.

tests/e2e/test_css_transitions.py holds the contract.
"""

from playwright.sync_api import Page

_FINISH_THE_CSS_TRANSITIONS = """() => document.getAnimations()
    .filter(animation => animation instanceof CSSTransition)
    .forEach(transition => transition.finish())"""


def finish_the_css_transitions(page: Page) -> None:
    """Finish every CSS transition running in page, including one the caller's last change has just started, since getAnimations() flushes pending style first, and leave its CSS animations, which may be infinite, running.

    A transition that a script starts in a later animation frame may not be running yet, and then it is not finished: Alpine's x-transition and x-collapse start theirs in the second animation frame after the change that shows or hides their element.
    """
    page.evaluate(_FINISH_THE_CSS_TRANSITIONS)
