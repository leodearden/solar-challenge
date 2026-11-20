# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for the module a string annotation or a forward reference is evaluated in, and the errors raised where no module is known to spell it, where the module found is not the one that defined what spells it, or where that module binds nothing to a name it holds, each the one named_classes raises for it, one per test."""

import functools
import inspect
import pathlib

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    MAKE_DATACLASS_MADE_SOURCE,
    NEW_CLASS_MADE_SOURCE,
    imported_module,
    made_not_bound_in,
    make_dataclass_records,
)


def test_a_string_annotation_naming_what_its_module_does_not_bind_raises_name_error() -> None:
    def f(a: "Unbound") -> None: ...  # noqa: F821

    with pytest.raises(NameError, match="Unbound"):
        surface_form(f)


def test_a_dataclass_types_new_class_makes_raises_the_lookup_error_named_classes_raises_for_it_naming_it_and_the_module_types(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spellednewclassing = imported_module(
        tmp_path, monkeypatch, "spellednewclassing", NEW_CLASS_MADE_SOURCE
    )

    with pytest.raises(LookupError, match=made_not_bound_in("types")):
        surface_form(spellednewclassing.Made)


def test_a_dataclass_dataclasses_make_dataclass_makes_raises_the_lookup_error_naming_the_module_types_on_python_3_11_and_from_python_3_12_is_spelled_by_its_kind_then_its_constructor_signature_with_its_string_annotation_evaluated(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spelledmaking = imported_module(
        tmp_path, monkeypatch, "spelledmaking", MAKE_DATACLASS_MADE_SOURCE
    )

    if make_dataclass_records("spelledmaking") == "types":
        with pytest.raises(LookupError, match=made_not_bound_in("types")):
            surface_form(spelledmaking.Made)
    else:
        assert surface_form(spelledmaking.Made) == "dataclass[eq] (spare: Decimal) -> None"


def test_a_string_annotation_in_a_signature_a_partial_carries_over_a_routine_defined_in_c_raises_the_type_error_named_classes_raises_for_it_naming_the_partial_and_the_string() -> None:
    counting = functools.partial(len)
    counting.__signature__ = inspect.Signature(
        [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Decimal")]
    )

    with pytest.raises(TypeError) as named:
        named_classes(counting)
    with pytest.raises(
        TypeError,
        match=r"\bfunctools\.partial\(<built-in function len>\).*'Decimal'.*\brecords no module of its own\b",
    ) as spelled:
        surface_form(counting)
    assert str(spelled.value) == str(named.value)
