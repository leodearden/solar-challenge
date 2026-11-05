# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the causes chained under the errors it raises, one per test."""

import sys
import types

import pytest

from tests._surface_forms import named_classes


def test_a_class_whose_module_inspect_reads_no_source_for_raises_a_type_error_from_an_error_naming_that_module_which_is_raised_from_the_error_inspect_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsourced = types.ModuleType("unsourced")
    monkeypatch.setitem(sys.modules, "unsourced", unsourced)
    exec(
        "from typing import NamedTuple\n\nReading = NamedTuple('Point', [('share', int)])\n",
        vars(unsourced),
    )

    with pytest.raises(
        TypeError, match=r"unsourced\.Point\b.*\bno class statement inspect can read\b"
    ) as raised:
        named_classes(unsourced.Reading)

    naming_the_module = raised.value.__cause__
    assert str(naming_the_module) == f"inspect reads no source for {unsourced!r}"
    assert isinstance(naming_the_module.__cause__, (OSError, TypeError))
