# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's is_additive_change, one per test."""

from dataclasses import dataclass

from tests._surface_forms import is_additive_change


def test_a_frozen_dataclass_that_gains_an_appended_defaulted_field_changes_additively() -> None:
    @dataclass(frozen=True)
    class Reading:
        a: int
        b: str = "x"
        c: float = 1.0

    assert is_additive_change("dataclass[eq, frozen] (a: int, b: str = 'x') -> None", Reading)


def test_a_defaulted_field_inserted_before_another_is_breaking() -> None:
    @dataclass(frozen=True)
    class Reading:
        a: int
        z: int = 0
        b: str = "x"

    assert not is_additive_change("dataclass[eq, frozen] (a: int, b: str = 'x') -> None", Reading)


def test_a_removed_parameter_is_breaking() -> None:
    def scale(a: int) -> int: ...

    assert not is_additive_change("(a: int, b: int = 1) -> int", scale)


def test_a_retyped_parameter_is_breaking() -> None:
    def scale(a: float) -> int: ...

    assert not is_additive_change("(a: int) -> int", scale)


def test_a_new_keyword_only_parameter_with_a_default_is_additive() -> None:
    def scale(a: int, *, b: int = 1) -> int: ...

    assert is_additive_change("(a: int) -> int", scale)


def test_a_gained_var_positional_or_var_keyword_parameter_is_additive() -> None:
    def gains_args(a: int, *args: int) -> int: ...

    def gains_kwargs(a: int, **kwargs: int) -> int: ...

    def gains_args_before_a_keyword_only_parameter(a: int, *args: int, k: int = 1) -> int: ...

    assert is_additive_change("(a: int) -> int", gains_args)
    assert is_additive_change("(a: int) -> int", gains_kwargs)
    assert is_additive_change(
        "(a: int, *, k: int = 1) -> int", gains_args_before_a_keyword_only_parameter
    )


def test_a_defaulted_positional_parameter_inserted_before_var_positional_is_breaking() -> None:
    def scale(a: int, b: int = 1, *args: int) -> int: ...

    assert not is_additive_change("(a: int, *args: int) -> int", scale)


def test_a_new_keyword_only_parameter_without_a_default_is_breaking() -> None:
    def scale(a: int, *, b: int) -> int: ...

    assert not is_additive_change("(a: int) -> int", scale)


def test_a_changed_return_annotation_is_breaking() -> None:
    def scale(a: int) -> str: ...

    assert not is_additive_change("(a: int) -> int", scale)


def test_a_dataclass_whose_kind_gains_a_qualifier_is_breaking() -> None:
    @dataclass(frozen=True, order=True)
    class Rank:
        level: int

    assert not is_additive_change("dataclass[eq, frozen] (level: int) -> None", Rank)
