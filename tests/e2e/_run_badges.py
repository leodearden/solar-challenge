# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read a run badge's classes two ways: as a dashboard macro draws it on the server, and as each badge a locator finds carries them in the browser."""

from playwright.sync_api import Locator

from tests._html_page import element_attributes


def server_drawn_classes(markup: object) -> set[str]:
    """The classes of the one span *markup*, a macro's rendering, draws."""
    (badge,) = element_attributes(str(markup), "span")
    return set((badge["class"] or "").split())


def classes_of_each(badges: Locator) -> list[set[str]]:
    """The classes each element *badges* finds carries now, in document order."""
    class_lists = badges.evaluate_all("els => els.map(el => [...el.classList])")
    return [set(class_list) for class_list in class_lists]
