# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the classes each run badge a locator finds carries in the browser, to compare with the classes tests._server_drawn_badges reads from the badge a macro draws on the server for the same value."""

from playwright.sync_api import Locator


def classes_of_each(badges: Locator) -> list[set[str]]:
    """The classes each element *badges* finds carries now, in document order."""
    class_lists = badges.evaluate_all("els => els.map(el => [...el.classList])")
    return [set(class_list) for class_list in class_lists]
