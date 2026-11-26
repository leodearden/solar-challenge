# SPDX-License-Identifier: AGPL-3.0-or-later
"""The options the select elements of a rendered HTML page offer: the value each one submits and the text it shows.

tests/_html_page.py lists a page's option values (element_attributes) and its texts
(texts) apart, with nothing tying a value to its text; this reader pairs them, so a page
test can pin which label each value carries. An option's text is read as tests/_html_page.py
reads a text: character references decoded and whitespace collapsed.

Usage::

    from tests._html_select_options import option_texts, options_of_each

    page = response.get_data(as_text=True)
    assert option_texts(page, {"x-model": "formData.location"}) == {
        "bristol": "Bristol, UK (51.45°N, 2.58°W)",
        "custom": "Custom coordinates...",
    }
    assert options_of_each(page, {"x-model": "dist.type"})[0] == [("", "Fixed Value"), ("normal", "Normal")]
"""

from collections.abc import Mapping
from html.parser import HTMLParser

#: An option as read: its attributes, keyed by lower-case name, and its character data.
_Option = tuple[dict[str, str | None], list[str]]


def option_texts(page: str, select: Mapping[str, str]) -> dict[str, str]:
    """The text of each option of the one select element of *page* that carries every one of *select*'s attributes, each with exactly that value, keyed by the option's value, in document order.

    An option with no value attribute is keyed by its text, the value a browser submits
    for it. Raises ValueError, rather than guess which select is meant, unless exactly one
    select carries the attributes, whose names are read in lower case; and, rather than
    keep only one text, when two of its options carry the same value.
    """
    matching = options_of_each(page, select)
    if len(matching) != 1:
        raise ValueError(
            f"Expected exactly one select carrying {dict(select)!r}, its attribute names in"
            f" lower case; found {len(matching)}"
        )
    texts: dict[str, str] = {}
    for value, text in matching[0]:
        if value in texts:
            raise ValueError(
                f"Expected each option of the select to carry its own value; {value!r} is on"
                " more than one"
            )
        texts[value] = text
    return texts


def options_of_each(page: str, select: Mapping[str, str]) -> list[list[tuple[str, str]]]:
    """The options of each select element of *page* that carries every one of *select*'s attributes, each with exactly that value, in document order: each option as the value it submits and the text it shows, in document order.

    An option with no value attribute submits its text. The attribute names are read in
    lower case; a page with no such select reads [].
    """
    reader = _SelectReader()
    reader.feed(page)
    reader.close()
    return [
        [_value_and_text(attributes, data) for attributes, data in options]
        for carried, options in reader.selects
        if all(carried.get(name) == value for name, value in select.items())
    ]


def _value_and_text(attributes: Mapping[str, str | None], data: list[str]) -> tuple[str, str]:
    """The value an option carrying *attributes* submits and the text its character data *data* shows."""
    text = " ".join("".join(data).split())
    if "value" not in attributes:
        return text, text
    return attributes["value"] or "", text


class _SelectReader(HTMLParser):
    """Collects each select element of one HTML page, with its attributes and its options, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.selects: list[tuple[dict[str, str | None], list[_Option]]] = []
        self._open_select: list[_Option] | None = None
        self._open_option: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        carried: dict[str, str | None] = {}
        for name, value in attrs:
            carried.setdefault(name, value)
        if tag == "select":
            self._open_select = []
            self.selects.append((carried, self._open_select))
        elif tag == "option" and self._open_select is not None:
            self._open_option = []
            self._open_select.append((carried, self._open_option))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("option", "select"):
            self._open_option = None
        if tag == "select":
            self._open_select = None

    def handle_data(self, data: str) -> None:
        if self._open_option is not None:
            self._open_option.append(data)
