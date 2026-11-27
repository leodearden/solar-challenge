# SPDX-License-Identifier: AGPL-3.0-or-later
"""Withhold a page's animation frames, as a loaded host's headless browser can for seconds, to pin behaviour that must not wait for one."""

from playwright.sync_api import Page


def withhold_animation_frames(page: Page) -> None:
    """From the next page load on, the page's requestAnimationFrame never calls back, while its timers and microtasks still run."""
    page.add_init_script("window.requestAnimationFrame = () => 0;")
