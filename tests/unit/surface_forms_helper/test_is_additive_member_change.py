# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's is_additive_member_change, one per test."""

import abc

import pytest

from tests._surface_forms import is_additive_member_change


def test_a_property_made_settable_or_deletable_is_additive() -> None:
    class Meter:
        @property
        def settable(self) -> float: ...

        @settable.setter
        def settable(self, value: float) -> None: ...

        @property
        def deletable(self) -> float: ...

        @deletable.deleter
        def deletable(self) -> None: ...

        @property
        def both(self) -> float: ...

        @both.setter
        def both(self, value: float) -> None: ...

        @both.deleter
        def both(self) -> None: ...

    assert is_additive_member_change("property (self) -> float", Meter, "settable")
    assert is_additive_member_change("property (self) -> float", Meter, "deletable")
    assert is_additive_member_change("property (self) -> float", Meter, "both")


def test_a_property_that_loses_its_setter_is_breaking() -> None:
    class Meter:
        @property
        def reading(self) -> float: ...

    assert not is_additive_member_change("property[settable] (self) -> float", Meter, "reading")


def test_a_method_that_gains_a_keyword_only_parameter_with_a_default_is_additive() -> None:
    class Battery:
        def charge(self, power_kw: float, *, cap: float = 1.0) -> float: ...

    assert is_additive_member_change("(self, power_kw: float) -> float", Battery, "charge")


def test_a_classmethod_that_gains_a_trailing_defaulted_parameter_is_additive_and_one_retyped_is_breaking() -> None:
    class Meter:
        @classmethod
        def scaled(cls, n: int, factor: int = 1) -> int: ...

        @classmethod
        def retyped(cls, n: float) -> int: ...

    assert is_additive_member_change("classmethod (cls, n: int) -> int", Meter, "scaled")
    assert not is_additive_member_change("classmethod (cls, n: int) -> int", Meter, "retyped")


def test_an_annotated_attribute_retyped_is_breaking() -> None:
    class Meter:
        site: int

    assert not is_additive_member_change("attribute str", Meter, "site")


def test_a_method_made_abstract_is_breaking() -> None:
    class Meter(abc.ABC):
        @abc.abstractmethod
        def read(self) -> float: ...

    assert not is_additive_member_change("(self) -> float", Meter, "read")


def test_a_name_that_is_no_public_member_raises_key_error() -> None:
    class Base:
        def read(self) -> float: ...

    class Meter(Base):
        def _calibrate(self) -> None: ...

    with pytest.raises(KeyError):
        is_additive_member_change("(self) -> None", Meter, "_calibrate")
    with pytest.raises(KeyError):
        is_additive_member_change("(self) -> float", Meter, "read")
    with pytest.raises(KeyError):
        is_additive_member_change("(self) -> None", Meter, "absent")
