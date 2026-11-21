# SPDX-License-Identifier: AGPL-3.0-or-later
"""finish_the_css_transitions (tests/e2e/_css_transitions.py) moves every CSS transition running in a page to its end value at once, and leaves the page's CSS animations running."""

from playwright.sync_api import Page

from tests.e2e._css_transitions import finish_the_css_transitions

_A_SLOW_BOX_AND_A_SPINNER = """<!DOCTYPE html>
<style>
    #box { width: 10px; height: 10px; transition: width 600s linear; }
    #spinner { width: 10px; height: 10px; animation: spin 1s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
</style>
<div id="box"></div>
<div id="spinner"></div>
"""

_WIDEN_THE_BOX = """() => {
    const box = document.getElementById('box');
    getComputedStyle(box).width;
    box.style.width = '500px';
}"""
"""Reads the box's computed width, so the width set next starts the box's 600 s transition, and sets it to 500px."""

_THE_BOX_WIDTH_AND_THE_RUNNING_ANIMATIONS = """() => ({
    width: getComputedStyle(document.getElementById('box')).width,
    animations: document.getAnimations().map(animation => animation.constructor.name).sort(),
})"""


def test_a_transition_the_last_change_started_reads_its_end_value_and_an_infinite_animation_keeps_running(page: Page) -> None:
    """The box's 600 s width transition, which the change just before the call starts, ends at 500px, and the spinner's infinite animation, whose finish() would throw, is still the one animation running."""
    page.set_content(_A_SLOW_BOX_AND_A_SPINNER)
    page.evaluate(_WIDEN_THE_BOX)

    finish_the_css_transitions(page)

    assert page.evaluate(_THE_BOX_WIDTH_AND_THE_RUNNING_ANIMATIONS) == {"width": "500px", "animations": ["CSSAnimation"]}
