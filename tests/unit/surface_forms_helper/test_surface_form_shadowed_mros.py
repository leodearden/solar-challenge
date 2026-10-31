# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for a class whose metaclass gives a __mro__ other than the MRO the class records, as a metaclass that defines __mro__ as a property does, and for an object of such a class, one per test.

The classes and the function above the first test are defined at module level, where
their qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import contextlib
import functools
import sqlite3
from typing import Callable

import pytest

from tests._surface_forms import surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGiver,
    GetMixin,
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    metaclass_whose_mro_gives,
)


def _settle(receiver: object, rate: int) -> None: ...


class Rating:
    """A class whose __call__ is defined with def."""

    def __call__(self, rate: int) -> None: ...


class HiddenRating(Rating, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))):
    """A Rating whose __mro__ gives only the class itself, hiding Rating, which holds the __call__ the class resolves."""


class PartialCall:
    """A class whose __call__ is a functools.partial."""

    __call__ = functools.partial(_settle)


class MislistedRating(
    Rating, metaclass=metaclass_whose_mro_gives(lambda cls: (cls, PartialCall, object))
):
    """A Rating whose __mro__ lists PartialCall, which the MRO the class records does not hold, in place of Rating."""


class HiddenGetterPartial(
    functools.partial, GetMixin, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))
):
    """A functools.partial whose bases are functools.partial and then GetMixin, which defines __get__, but whose __mro__ gives only the class itself."""


class HiddenCallableGiver(CallableGiver, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))):
    """A CallableGiver whose __mro__ gives only the class itself, hiding Giver, which defines __get__."""


class Initialised:
    """A class whose __init__ is defined with def."""

    def __init__(self, rate: int) -> None: ...


class Made:
    """A class whose __new__ is defined with def."""

    def __new__(cls, share: str) -> "Made": ...


class Reordered(
    Initialised,
    Made,
    metaclass=metaclass_whose_mro_gives(lambda cls: (cls, Made, Initialised, object)),
):
    """A class of Initialised and then Made whose __mro__ lists Made first, though the MRO the class records lists Initialised first."""


class Hidden(Initialised, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))):
    """An Initialised whose __mro__ gives only the class itself, hiding Initialised and object."""


class CallingHidden(metaclass_whose_mro_gives(lambda cls: (cls,))):
    """A metaclass whose __call__ is defined with def and whose __mro__ gives, for each class of it, only that class."""

    def __call__(cls, rate: int) -> None: ...


class Called(Initialised, metaclass=CallingHidden):
    """An Initialised of CallingHidden, whose __call__ inspect reads before it reads __mro__."""


class Recorded(
    Initialised,
    metaclass=metaclass_whose_mro_gives(lambda cls: type.__dict__["__mro__"].__get__(cls)),
):
    """An Initialised whose __mro__ gives the very tuple that is the MRO the class records."""


@pytest.mark.parametrize(
    ("build", "form"),
    [
        pytest.param(
            lambda: functools.partial(HiddenRating()), "(rate: int) -> None", id="partial-of-it"
        ),
        pytest.param(lambda: class_whose_init_is(HiddenRating()), "(rate: int) -> None", id="init"),
        pytest.param(lambda: class_whose_new_is(HiddenRating()), "() -> None", id="new"),
        pytest.param(
            lambda: class_whose_metaclass_call_is(HiddenRating()),
            "(rate: int) -> None",
            id="metaclass-call",
        ),
        pytest.param(
            lambda: functools.partial(MislistedRating()),
            "(rate: int) -> None",
            id="partial-call-listed-only-by-mro",
        ),
    ],
)
def test_an_object_whose_types_metaclass_gives_a_mro_other_than_the_one_its_type_records_is_read_through_the_call_that_mro_resolves(
    build: Callable[[], object], form: str
) -> None:
    assert surface_form(build()) == form


def test_an_object_whose_types_mro_holds_a_base_defining_call_in_c_raises_the_type_error_naming_that_base_whatever_mro_its_metaclass_gives() -> None:
    class HiddenConnection(
        sqlite3.Connection, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))
    ):
        def __call__(self, rate: int) -> None: ...

    naming_that_base = (
        r"\bfunctools\.partial\(.*\.HiddenConnection\b.*\bsqlite3\.Connection\.__call__\b"
        r".*\bdefined in C\b"
    )
    with contextlib.closing(HiddenConnection(":memory:")) as connection:
        with pytest.raises(TypeError, match=naming_that_base):
            surface_form(functools.partial(connection))


@pytest.mark.parametrize(
    ("build", "refusal"),
    [
        pytest.param(
            lambda: HiddenGetterPartial(_settle),
            r"\.HiddenGetterPartial, a functools\.partial whose type takes __get__ from a class "
            r"other than functools\.partial and defines no __set__",
            id="partial",
        ),
        pytest.param(
            lambda: class_whose_init_is(classmethod(HiddenCallableGiver(_settle))),
            r"\.Built\.__init__, a classmethod that wraps a \S*\.HiddenCallableGiver, whose type "
            r"defines __get__",
            id="classmethod",
        ),
    ],
)
def test_a_partial_or_a_classmethod_wrapped_object_whose_type_takes_get_from_a_base_its_metaclass_mro_hides_raises_the_type_error_for_that_get(
    build: Callable[[], object], refusal: str
) -> None:
    with pytest.raises(TypeError, match=refusal):
        surface_form(build())


@pytest.mark.parametrize(
    ("cls", "name"),
    [
        pytest.param(Reordered, "Reordered", id="constructors-reordered"),
        pytest.param(Hidden, "Hidden", id="bases-hidden"),
    ],
)
def test_a_class_whose_metaclass_gives_a_mro_other_than_the_one_it_records_raises_a_type_error_naming_it_its_metaclass_and_that_mro(
    cls: type, name: str
) -> None:
    with pytest.raises(
        TypeError, match=rf"\.{name} has the metaclass \S*\.Shadowing, whose __mro__ gives "
    ):
        surface_form(cls)


@pytest.mark.parametrize(
    "cls",
    [
        pytest.param(Called, id="metaclass-call"),
        pytest.param(Recorded, id="mro-giving-the-one-the-class-records"),
    ],
)
def test_a_class_whose_metaclass_defines_mro_is_spelled_by_the_constructor_inspect_reads_where_it_chooses_none_by_a_mro_other_than_the_one_the_class_records(
    cls: type,
) -> None:
    assert surface_form(cls) == "(rate: int) -> None"
