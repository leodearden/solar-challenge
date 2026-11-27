# SPDX-License-Identifier: AGPL-3.0-or-later
"""The numbers in a text, each as the text writes it, so a test pins how a value renders without pinning the wording around it.

A number with thousands separators is one number, and a decimal keeps its fraction:
"1,800" is one number, and neither "10.0" nor "1,200" reads as "10" or "1200".

Usage::

    from tests.unit.web_assistant._number_tokens import numbers_in

    assert f"{BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP:g}" in numbers_in(result["note"])
"""

import re

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def numbers_in(text: str) -> frozenset[str]:
    """Every number in *text*, each as *text* writes it."""
    return frozenset(_NUMBER.findall(text))
