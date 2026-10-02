# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to a rendered HTML page: the document type it declares, its
elements and the ids they carry, and the texts it shows, in document order.

A text is one run of character data between two tags, outside script and style elements,
with character references decoded and whitespace collapsed. Blank runs are dropped, and an
attribute value is never a text. Tag and attribute names are read in lower case, as HTML
reads them in any case; attribute values and texts keep their case. An element that
repeats an attribute carries only its first value, as HTML reads it.

Usage::

    from tests._html_page import doctype, element_count, element_ids, texts, texts_after

    page = response.get_data(as_text=True)
    assert doctype(page) == "html"
    assert element_count(page, "input", {"x-model": "name"}) == 1
    assert "chart-sankey" in element_ids(page)
    assert texts(page).count("YAML Preview") == 1
    assert texts_after(page, "Total Demand", 2) == ["12.0", "kWh"]
"""

from collections import Counter
from collections.abc import Mapping
from html.parser import HTMLParser

_RAW_TEXT_ELEMENTS = frozenset({"script", "style"})


def doctype(page: str) -> str | None:
    """The document type *page* declares, in lower case, or None when it declares none.

    <!DOCTYPE html> and <!doctype HTML> both declare 'html'. A legacy declaration keeps
    its identifiers, so it is not 'html'. Raises ValueError, rather than pick one, when
    the page declares more than one.
    """
    declared = _read(page).doctypes
    if len(declared) > 1:
        raise ValueError(
            f"Expected at most one doctype declaration on the page; found {len(declared)}: {declared}"
        )
    return declared[0] if declared else None


def element_count(
    page: str, tag: str, attributes: Mapping[str, str] | None = None
) -> int:
    """How many *tag* elements of *page* carry every one of *attributes*, each with exactly that value.

    Raises ValueError, rather than count none, when *tag* or an attribute name is not in
    lower case: the page's names are read in lower case, so no element could match. An
    element inside script text does not count.
    """
    required = attributes or {}
    not_in_lower_case = [name for name in (tag, *required) if name != name.lower()]
    if not_in_lower_case:
        raise ValueError(
            "Expected tag and attribute names in lower case, as the page is read;"
            f" got {', '.join(map(repr, not_in_lower_case))}"
        )
    return sum(
        1
        for name, carried in _read(page).elements
        if name == tag
        and all(carried.get(key) == value for key, value in required.items())
    )


def element_ids(page: str) -> set[str]:
    """The ids the elements of *page* carry; an id inside script text does not count.

    Raises ValueError, rather than count it once, when more than one element carries an
    id: document.getElementById finds only the first of them.
    """
    carried_ids = (carried.get("id") for _, carried in _read(page).elements)
    elements_per_id = Counter(
        element_id for element_id in carried_ids if element_id is not None
    )
    repeated = [
        f"{element_id!r} is on {count} elements"
        for element_id, count in elements_per_id.items()
        if count > 1
    ]
    if repeated:
        raise ValueError(
            f"Expected each id on only one element of the page; {', '.join(repeated)}"
        )
    return set(elements_per_id)


def texts(page: str) -> list[str]:
    """The texts of *page*, in document order; a text that occurs more than once is listed each time."""
    return _read(page).texts


def texts_after(page: str, label: str, count: int) -> list[str]:
    """The *count* texts that follow the one text of *page* equal to *label*.

    Raises ValueError, rather than guess, unless exactly one text equals *label*. A text
    that only contains *label*, or differs from it in case, is not equal to it.
    """
    page_texts = texts(page)
    positions = [index for index, text in enumerate(page_texts) if text == label]
    if len(positions) != 1:
        raise ValueError(
            f"Expected exactly one text equal to {label!r} on the page; found {len(positions)}"
        )
    start = positions[0] + 1
    return page_texts[start : start + count]


class _PageReader(HTMLParser):
    """Collects the doctypes, the elements with their attributes, and the texts of one HTML page, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctypes: list[str] = []
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.texts: list[str] = []
        self._in_raw_text = False

    def handle_decl(self, decl: str) -> None:
        self.doctypes.append(" ".join(decl.split()[1:]).lower())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        carried: dict[str, str | None] = {}
        for name, value in attrs:
            carried.setdefault(name, value)
        self.elements.append((tag, carried))
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
