# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_html_labels.py, the reader of the caption of each input a page's label element wraps.

Each test pins one reading rule, so an edit that weakens the reader fails here instead of
letting a page test that uses it pass vacuously.
"""

from tests._html_labels import labelled_inputs


def test_each_wrapped_input_is_read_with_its_labels_caption_in_document_order() -> None:
    page = (
        '<label><span>Mean</span><input x-model.number="mean"></label>'
        '<label><span>Std Dev</span><input x-model.number="std" min="0"></label>'
    )

    assert labelled_inputs(page) == [
        ("Mean", {"x-model.number": "mean"}),
        ("Std Dev", {"x-model.number": "std", "min": "0"}),
    ]


def test_a_caption_reads_every_child_elements_text_decoded_and_with_whitespace_collapsed() -> None:
    page = '<label>\n  <span class="sr-only">PV &amp; Battery </span>\n  Value <span></span><input id="v"></label>'

    assert labelled_inputs(page) == [("PV & Battery Value", {"id": "v"})]


def test_an_input_outside_every_label_is_left_out() -> None:
    page = '<input id="outside"><label>Inside<input id="inside"></label><input id="after">'

    assert labelled_inputs(page) == [("Inside", {"id": "inside"})]
