# SPDX-License-Identifier: AGPL-3.0-or-later
"""The inputs a rendered HTML page captions by wrapping them in a label element: each one's caption and attributes.

tests/_html_page.py lists a page's input attributes (element_attributes) and its texts
(texts) apart, with nothing tying an input to its caption; this reader pairs them, so a page
test can pin which caption names each input. A caption is all the character data inside the
label, its child elements' included (an sr-only span's too, which an accessible name
reads), with character references decoded and whitespace collapsed.

Usage::

    from tests._html_labels import labelled_inputs

    page = response.get_data(as_text=True)
    assert ("PV Capacity Mean", "dist.specs.normal.mean") in [
        (caption, attributes.get("x-model.number")) for caption, attributes in labelled_inputs(page)
    ]
"""

from collections.abc import Mapping
from html.parser import HTMLParser


def labelled_inputs(page: str) -> list[tuple[str, Mapping[str, str | None]]]:
    """Each input element of *page* inside a label element, in document order: the label's caption and the input's attributes, keyed by lower-case name.

    An input outside every label is left out. A valueless attribute reads None.
    """
    reader = _LabelReader()
    reader.feed(page)
    reader.close()
    return [
        (" ".join("".join(caption).split()), attributes)
        for caption, inputs in reader.labels
        for attributes in inputs
    ]


class _LabelReader(HTMLParser):
    """Collects each label element of one HTML page, with its character data and the inputs inside it, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: list[tuple[list[str], list[dict[str, str | None]]]] = []
        self._open_label: tuple[list[str], list[dict[str, str | None]]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "label":
            self._open_label = ([], [])
            self.labels.append(self._open_label)
        elif tag == "input" and self._open_label is not None:
            carried: dict[str, str | None] = {}
            for name, value in attrs:
                carried.setdefault(name, value)
            self._open_label[1].append(carried)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self._open_label = None

    def handle_data(self, data: str) -> None:
        if self._open_label is not None:
            self._open_label[0].append(data)
