# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's is_additive_change, one per test."""

import enum
from dataclasses import dataclass

from tests._surface_forms import is_additive_change


def test_a_frozen_dataclass_that_gains_an_appended_defaulted_field_changes_additively() -> None:
    @dataclass(frozen=True)
    class Reading:
        a: int
        b: str = "x"
        c: float = 1.0

    assert is_additive_change("dataclass[eq, frozen, match_args] (a: int, b: str = 'x') -> None", Reading)


def test_a_defaulted_field_inserted_before_another_is_breaking() -> None:
    @dataclass(frozen=True)
    class Reading:
        a: int
        z: int = 0
        b: str = "x"

    assert not is_additive_change("dataclass[eq, frozen, match_args] (a: int, b: str = 'x') -> None", Reading)


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

    assert not is_additive_change("dataclass[eq, frozen, match_args] (level: int) -> None", Rank)


def test_a_mapping_constant_that_gains_a_key_is_additive() -> None:
    assert is_additive_change("dict {'a': float}", {"a": 1.0, "b": 2.0})
    assert is_additive_change("dict {'a': float, 'b': float}", {"a": 1.0, "m": 0.5, "b": 2.0})


def test_a_mapping_constant_that_loses_a_key_is_breaking() -> None:
    assert not is_additive_change("dict {'a': float, 'b': float}", {"a": 1.0})


def test_a_mapping_constant_whose_value_is_retyped_is_breaking() -> None:
    assert not is_additive_change("dict {'a': float}", {"a": 1})


def test_a_list_constant_that_gains_an_item_is_breaking() -> None:
    assert not is_additive_change("list [float]", [1.0, 2.0])


def test_an_enum_that_gains_a_member_is_additive() -> None:
    class Band(enum.Enum):
        LOW = 1
        MID = 2
        HIGH = 3

    assert is_additive_change("LOW=1, HIGH=3", Band)


def test_an_enum_whose_member_changes_its_value_is_breaking() -> None:
    class Band(enum.Enum):
        LOW = 1
        HIGH = 4

    assert not is_additive_change("LOW=1, HIGH=3", Band)


def test_an_enum_of_64_members_is_classified_at_once_where_trying_every_subset_of_them_never_would_finish() -> None:
    members = [(f"M{value:02d}", value) for value in range(64)]
    wide = enum.Enum("Wide", members)
    renumbered = enum.Enum("Renumbered", [(name, -1 if name == "M31" else value) for name, value in members])

    assert is_additive_change(", ".join(f"{name}={value}" for name, value in members if name != "M31"), wide)
    assert not is_additive_change(", ".join(f"{name}={value}" for name, value in members), renumbered)
