# SPDX-License-Identifier: AGPL-3.0-or-later
"""Withhold or delay a page's animation frames, as a loaded host's headless browser can for seconds: withheld, to pin behaviour that must not wait for a frame; delayed, to pin a read that must wait for what the next frame shows."""

from playwright.sync_api import Page


def withhold_animation_frames(page: Page) -> None:
    """From the next page load on, the page's requestAnimationFrame never calls back, while its timers and microtasks still run."""
    page.add_init_script("window.requestAnimationFrame = () => 0;")


def delay_animation_frames(page: Page, delay_ms: int) -> None:
    """From the next page load on, each requestAnimationFrame callback runs *delay_ms* after it is asked for, as a loaded host's headless browser renders its next frame late, while timers and microtasks run on time."""
    page.add_init_script(
        f"window.requestAnimationFrame = callback => setTimeout(() => callback(performance.now()), {delay_ms});"
        " window.cancelAnimationFrame = id => clearTimeout(id);"
    )
