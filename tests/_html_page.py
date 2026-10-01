# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to a rendered HTML page: the ids its elements carry and the texts
it shows, in document order.

A text is one run of character data between two tags, outside script and style elements,
with character references decoded and whitespace collapsed. Blank runs are dropped, and an
attribute value is never a text.

Usage::

    from tests._html_page import element_ids, texts_after

    page = response.get_data(as_text=True)
    assert "chart-sankey" in element_ids(page)
    assert texts_after(page, "Total Demand", 2) == ["12.0", "kWh"]
"""

from html.parser import HTMLParser

_RAW_TEXT_ELEMENTS = frozenset({"script", "style"})


def element_ids(page: str) -> set[str]:
    """The ids the elements of *page* carry; an id inside script text does not count."""
    return _read(page).ids


def texts_after(page: str, label: str, count: int) -> list[str]:
    """The *count* texts that follow the one text of *page* equal to *label*.

    Raises ValueError, rather than guess, unless exactly one text equals *label*. A text
    that only contains *label*, or differs from it in case, is not equal to it.
    """
    texts = _read(page).texts
    positions = [index for index, text in enumerate(texts) if text == label]
    if len(positions) != 1:
        raise ValueError(
            f"Expected exactly one text equal to {label!r} on the page; found {len(positions)}"
        )
    start = positions[0] + 1
    return texts[start : start + count]


class _PageReader(HTMLParser):
    """Collects the element ids and the texts of one HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.texts: list[str] = []
        self._in_raw_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.ids.update(
            value for name, value in attrs if name == "id" and value is not None
        )
        if tag in _RAW_TEXT_ELEMENTS:
            self._in_raw_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _RAW_TEXT_ELEMENTS:
            self._in_raw_text = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text and not self._in_raw_text:
            self.texts.append(text)


def _read(page: str) -> _PageReader:
    reader = _PageReader()
    reader.feed(page)
    reader.close()
    return reader
