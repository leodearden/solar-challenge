# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to a rendered HTML page: the document type it declares, its
elements with the attributes and ids they carry, the texts it shows and its headings, in
document order, and how many times each of some given texts occurs among them.

A text is one run of character data between two tags, outside script and style elements,
with character references decoded and whitespace collapsed. Blank runs are dropped, and an
attribute value is never a text. Tag and attribute names are read in lower case, as HTML
reads them in any case; attribute values and texts keep their case. An element that
repeats an attribute carries only its first value, as HTML reads it.

Usage::

    from tests._html_page import counts_of, doctype, element_attributes, element_count, element_ids, headings, texts, texts_after

    page = response.get_data(as_text=True)
    assert doctype(page) == "html"
    assert element_count(page, "input", {"x-model": "name"}) == 1
    assert element_attributes(page, "script")[0]["src"] == "/static/app.js"
    assert "chart-sankey" in element_ids(page)
    assert headings(page).count("PV Capacity") == 1
    assert texts(page).count("YAML Preview") == 1
    assert texts_after(page, "Total Demand", 2) == ["12.0", "kWh"]
    subjects = ("PV Capacity", "Battery Capacity")
    assert counts_of(headings(page), subjects) == dict.fromkeys(subjects, 1)
"""

from collections import Counter
from collections.abc import Mapping
from html.parser import HTMLParser

_RAW_TEXT_ELEMENTS = frozenset({"script", "style"})
_HEADING_ELEMENTS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


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
    _refuse_names_not_in_lower_case(tag, *required)
    return sum(
        1
        for name, carried in _read(page).elements
        if name == tag
        and all(carried.get(key) == value for key, value in required.items())
    )


def element_attributes(page: str, tag: str) -> list[Mapping[str, str | None]]:
    """The attributes of each *tag* element of *page*, in document order, keyed by lower-case name.

    A valueless attribute, such as defer, reads None. Raises ValueError, rather than list
    none, when *tag* is not in lower case. An element inside script text does not count.
    """
    _refuse_names_not_in_lower_case(tag)
    return [carried for name, carried in _read(page).elements if name == tag]


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


def headings(page: str) -> list[str]:
    """The text of each heading of *page*, h1 to h6, in document order.

    A heading's text is all the character data inside it, its child elements' included,
    with character references decoded and whitespace collapsed; a heading with none reads
    as ''. A heading inside script text does not count. Raises ValueError, rather than
    guess where it ends, when a heading is not closed by its end tag before the next
    heading starts or the page ends.
    """
    reader = _read(page)
    if reader.headings_left_open:
        raise ValueError(
            "Expected each heading closed by its end tag before the next heading or the"
            f" end of the page; {reader.headings_left_open} left open"
        )
    return reader.headings


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


def counts_of(items: list[str], keys: tuple[str, ...]) -> dict[str, int]:
    """How many times each of *keys* occurs in *items*, such as texts(page) or headings(page); a key no item equals counts 0.

    An item counts only when it equals the key, as texts_after matches its label. Raises
    ValueError, rather than return counts that equal an empty expectation whatever the
    items, when *keys* is empty.
    """
    if not keys:
        raise ValueError("Expected at least one key to count; got none")
    return {key: items.count(key) for key in keys}


def _refuse_names_not_in_lower_case(*names: str) -> None:
    not_in_lower_case = [name for name in names if name != name.lower()]
    if not_in_lower_case:
        raise ValueError(
            "Expected tag and attribute names in lower case, as the page is read;"
            f" got {', '.join(map(repr, not_in_lower_case))}"
        )


class _PageReader(HTMLParser):
    """Collects the doctypes, the elements with their attributes, the texts and the headings of one HTML page, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctypes: list[str] = []
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.texts: list[str] = []
        self.headings: list[str] = []
        self.headings_left_open = 0
        self._in_raw_text = False
        self._open_heading: list[str] | None = None

    def handle_decl(self, decl: str) -> None:
        self.doctypes.append(" ".join(decl.split()[1:]).lower())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        carried: dict[str, str | None] = {}
        for name, value in attrs:
            carried.setdefault(name, value)
        self.elements.append((tag, carried))
        if tag in _RAW_TEXT_ELEMENTS:
            self._in_raw_text = True
        if tag in _HEADING_ELEMENTS:
            if self._open_heading is not None:
                self.headings_left_open += 1
            self._open_heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _RAW_TEXT_ELEMENTS:
            self._in_raw_text = False
        if tag in _HEADING_ELEMENTS and self._open_heading is not None:
            self.headings.append(" ".join("".join(self._open_heading).split()))
            self._open_heading = None

    def handle_data(self, data: str) -> None:
        if self._in_raw_text:
            return
        if self._open_heading is not None:
            self._open_heading.append(data)
        text = " ".join(data.split())
        if text:
            self.texts.append(text)

    def close(self) -> None:
        super().close()
        if self._open_heading is not None:
            self.headings_left_open += 1
            self._open_heading = None


def _read(page: str) -> _PageReader:
    reader = _PageReader()
    reader.feed(page)
    reader.close()
    return reader
