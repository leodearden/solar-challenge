# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for the signature inspect reads for a routine, at the end of the chain it follows from one, and the TypeError raised where inspect reads that chain differently by minor or cannot read it, one per test.

The classes and the function above the first test are defined at module level, where a
parametrize decorator can reach them.
"""

import contextlib
import decimal
import enum
import fractions
import functools
import inspect
import operator
import re
import sqlite3
import types
import warnings
from typing import Callable, Optional

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE,
    GIVEN_BY_A_METACLASS_GET,
    UNREADABLE_ROUTINES,
    CallableGetter,
    CallableGetterDeleter,
    ChainedCall,
    GetterDeleter,
    PartialFirstGetterPartial,
    metaclass_whose_get_gives,
    object_whose_call_is,
)


class Tariff(enum.Enum):
    """An Enum that EnumCall's __call__ wraps."""

    PEAK = "peak"


class StringSignedCall:
    """A class whose __call__ carries a string as __signature__."""

    def __call__(self, rate: int) -> None: ...

    __call__.__signature__ = "(self, rate)"


class EnumCall:
    """A class whose __call__ wraps Tariff, as functools.wraps records one."""

    @functools.wraps(Tariff)
    def __call__(self, value: object) -> object: ...


class GetterCall:
    """A class whose __call__ is a CallableGetter, whose signature inspect cannot read."""

    __call__ = CallableGetter()


class CallableWrapper:
    """A callable object, whose type defines no __get__, that records the object it is made with as __wrapped__, as functools.wraps records what it wraps."""

    def __init__(self, wrapped: object) -> None:
        self.__wrapped__ = wrapped

    def __call__(self, rate: int) -> str: ...


class ClassmethodWrapperCall:
    """A class whose __call__ is a classmethod of a CallableWrapper of a CallableGetter, which every minor binds as a method of that wrapper and reads through to the CallableGetter."""

    __call__ = classmethod(CallableWrapper(CallableGetter()))


_REFUSING_A_CALLABLE_GETTER = (
    r" is a functools\.partial that wraps <.*\.CallableGetter object\b"
    r".*\bsurface_forms_helper\._fixtures\.CallableGetter\b"
)


class TextedCall:
    """A class whose instances carry a __text_signature__ beside the __call__ it defines."""

    __text_signature__ = "(rate)"

    def __call__(self, rate: int) -> None: ...


class UnsignedTextedCall(TextedCall):
    """A TextedCall whose instances also carry a __signature__ of None."""

    __signature__ = None


def _share(receiver: object, rate: int) -> None: ...


class PartialFirstCall:
    """A class whose __call__ is a classmethod of a PartialFirstGetterPartial, which Python 3.11 and 3.12 bind through GetMixin's __get__ and later minors as a method of the partial."""

    __call__ = classmethod(PartialFirstGetterPartial(_share))


def test_a_partial_is_spelled_by_the_signature_it_leaves_of_the_callable_it_wraps() -> None:
    def settle(share: fractions.Fraction, rate: int, *, fee: Optional[float] = None) -> None: ...

    assert (
        surface_form(functools.partial(settle, rate=1))
        == "(share: Fraction, *, rate: int = 1, fee: float | None = None) -> None"
    )
    assert (
        surface_form(functools.partial(settle, fractions.Fraction(1, 2)))
        == "(rate: int, *, fee: float | None = None) -> None"
    )


def test_a_partial_of_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    with pytest.raises(
        TypeError, match=r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(functools.partial(Built, 1))
    with pytest.raises(TypeError, match=r"\bbuiltins\.dict\b.*\bbuiltins\.dict\b"):
        surface_form(functools.partial(dict, rate=1.0))
    with pytest.raises(
        TypeError, match=r"\bfunctools\.partial\b.*\bfunctools\.partial\b"
    ):
        named_classes(functools.partial(functools.partial, print))


def test_a_routine_that_wraps_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    class Zipper:
        @functools.wraps(zip)
        def zipped(self, *iterables: object) -> object: ...

    zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    building = functools.wraps(Built)(lambda rate: Built(rate))
    unsigned = functools.partial(zip, [1])
    unsigned.__signature__ = None
    wrapping = functools.partial(build, 1)
    wrapping.__wrapped__ = zip

    naming_zip = r"\bbuiltins\.zip\b.*\bbuiltins\.zip\b"
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        named_classes(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(functools.partial(zipping, [1]))
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(Zipper().zipped)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(unsigned)
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(wrapping)
    with pytest.raises(
        TypeError, match=r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(building)


def test_a_routine_that_wraps_an_enum_raises_a_type_error_naming_it_and_that_enum() -> None:
    class Period(enum.Enum):
        PEAK = "peak"

    naming_the_partial_and_period = r"\bfunctools\.partial\(.*\.Period\b.*\benum\.Enum\b"
    with pytest.raises(TypeError, match=naming_the_partial_and_period):
        surface_form(functools.partial(Period))
    with pytest.raises(TypeError, match=naming_the_partial_and_period):
        named_classes(functools.partial(Period))
    with pytest.raises(TypeError, match=r"\.Period\b.*\.Period\b.*\benum\.Enum\b"):
        surface_form(functools.wraps(Period)(lambda value: Period(value)))


def test_a_routine_that_wraps_a_class_but_carries_a_signature_is_spelled_by_that_signature() -> None:
    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    zipping.__signature__ = signature
    zipped = functools.partial(zip, [1])
    zipped.__signature__ = signature

    assert surface_form(zipping) == "(rate: int)"
    assert named_classes(zipping) == {int}
    assert surface_form(zipped) == "(rate: int)"
    assert named_classes(zipped) == {int}


def test_a_routine_that_carries_a_signature_of_none_is_spelled_by_its_own_signature_whatever_it_wraps() -> None:
    def settle(self: object, rate: int) -> None: ...

    def zipping(share: decimal.Decimal) -> None: ...

    zipping.__wrapped__ = zip
    zipping.__signature__ = None

    @functools.wraps(functools.partialmethod(settle, rate=1))
    def halved(self: object) -> None: ...

    halved.__signature__ = None

    assert surface_form(zipping) == "(share: Decimal) -> None"
    assert named_classes(zipping) == {decimal.Decimal}
    assert surface_form(halved) == "(self: object) -> None"


def test_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_what_carries_it_and_that_value() -> None:
    def pay(rate: int) -> None: ...

    def settle(rate: int) -> None: ...

    settle.__signature__ = "(rate)"
    paying = functools.wraps(pay)(lambda rate: pay(rate))
    paying.__signature__ = "(rate)"
    paid = functools.partial(pay)
    paid.__signature__ = "(rate)"
    texted = functools.partial(zip, [1])
    texted.__signature__ = "(rate)"
    texted_zipping = functools.wraps(zip)(lambda *iterables: zip(*iterables))
    texted_zipping.__signature__ = "(rate)"

    class Texted:
        __signature__ = "(rate)"

        def __init__(self, rate: int) -> None: ...

    class Keyed(dict):
        __signature__ = "(rate)"

    class Called(dict):
        @classmethod
        def __signature__(cls) -> inspect.Signature:
            return inspect.Signature(
                [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
            )

    class Meter:
        def read(self, rate: int) -> None: ...

        read.__signature__ = "(self, rate)"

    getter = CallableGetter()
    getter.__signature__ = "(rate)"

    carrying_text = r"'\(rate\)'.*\bbuiltins\.str\b.*\binspect\.Signature\b"
    naming_settle_and_its_text = rf"\.settle\b.*{carrying_text}"
    with pytest.raises(TypeError, match=naming_settle_and_its_text):
        surface_form(settle)
    with pytest.raises(TypeError, match=naming_settle_and_its_text):
        named_classes(settle)
    with pytest.raises(TypeError, match=rf"\.pay\b.*{carrying_text}"):
        surface_form(paying)
    with pytest.raises(TypeError, match=rf"\bfunctools\.partial\(.*\bpay\b.*{carrying_text}"):
        surface_form(paid)
    with pytest.raises(TypeError, match=rf"\bfunctools\.partial\(.*\bzip\b.*{carrying_text}"):
        surface_form(texted)
    with pytest.raises(TypeError, match=rf"\bbuiltins\.zip\b.*{carrying_text}"):
        surface_form(texted_zipping)
    naming_texted_and_its_text = rf"\.Texted\b.*{carrying_text}"
    with pytest.raises(TypeError, match=naming_texted_and_its_text):
        surface_form(Texted)
    with pytest.raises(TypeError, match=naming_texted_and_its_text):
        named_classes(Texted)
    with pytest.raises(
        TypeError, match=rf"\bfunctools\.partial\(.*\.Texted\b.*{carrying_text}"
    ):
        surface_form(functools.partial(Texted))
    with pytest.raises(TypeError, match=rf"\.Keyed\b.*{carrying_text}"):
        surface_form(Keyed)
    with pytest.raises(
        TypeError, match=r"\.Called\b.*\bbuiltins\.method\b.*\binspect\.Signature\b"
    ):
        surface_form(Called)
    with pytest.raises(
        TypeError, match=r"\.Meter\.read\b.*'\(self, rate\)'.*\bbuiltins\.str\b"
    ):
        surface_form(Meter().read)
    with pytest.raises(TypeError, match=rf"\bCallableGetter\b.*{carrying_text}"):
        surface_form(getter)


@pytest.mark.parametrize(("routine", "kind"), UNREADABLE_ROUTINES)
def test_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_it_and_its_kind(
    routine: object, kind: str
) -> None:
    naming_it_and_its_kind = rf"{re.escape(repr(routine))}.*\b{re.escape(kind)}\b"
    with pytest.raises(TypeError, match=naming_it_and_its_kind):
        surface_form(routine)
    with pytest.raises(TypeError, match=naming_it_and_its_kind):
        named_classes(routine)


def test_a_routine_that_wraps_a_routine_whose_signature_inspect_cannot_read_raises_a_type_error_naming_both_and_their_kinds() -> None:
    def settle(self: object, rate: int) -> None: ...

    half = functools.partialmethod(settle, rate=1)

    @functools.wraps(half)
    def halved(self: object) -> None: ...

    naming_both_and_their_kinds = (
        rf"\.halved\b.*\bbuiltins\.function\b.*{re.escape(repr(half))}"
        r".*\bfunctools\.partialmethod\b"
    )
    with pytest.raises(TypeError, match=naming_both_and_their_kinds):
        surface_form(halved)
    with pytest.raises(TypeError, match=naming_both_and_their_kinds):
        named_classes(halved)


def test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_raises_a_type_error_naming_it_that_descriptor_and_its_type() -> None:
    called = CallableGetterDeleter()
    uncalled = GetterDeleter()
    partial = functools.partial(called)

    @functools.wraps(called)
    def calling(rate: int) -> str: ...

    @functools.wraps(uncalled)
    def reading(rate: int) -> str: ...

    naming_the_partial_and_called = (
        rf"{re.escape(repr(partial))}.*{re.escape(repr(called))}"
        r".*\.CallableGetterDeleter\b.*\b__delete__\b"
    )
    naming_calling_and_called = (
        rf"\.calling\b.*{re.escape(repr(called))}.*\.CallableGetterDeleter\b.*\b__delete__\b"
    )
    naming_reading_and_uncalled = (
        rf"\.reading\b.*{re.escape(repr(uncalled))}.*\.GetterDeleter\b.*\b__delete__\b"
    )
    for routine, naming_it in (
        (partial, naming_the_partial_and_called),
        (calling, naming_calling_and_called),
        (reading, naming_reading_and_uncalled),
    ):
        with pytest.raises(TypeError, match=naming_it):
            surface_form(routine)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(routine)


def test_a_routine_that_wraps_a_descriptor_whose_type_defines_set_or_no_get_or_that_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it() -> None:
    class Settable(CallableGetterDeleter):
        def __set__(self, instance: object, value: object) -> None: ...

    class Getless:
        def __delete__(self, instance: object) -> None: ...

        def __call__(self, rate: int) -> str: ...

    signed = CallableGetterDeleter()
    signed.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    assert surface_form(functools.partial(Settable())) == "(rate: int) -> str"
    assert surface_form(functools.partial(Getless())) == "(rate: int) -> str"
    assert surface_form(functools.partial(signed)) == "(rate: int)"


@pytest.mark.parametrize(
    "shape", ["partial", "functools-wraps-wrapper", "bound-method", "partial-of-a-signed-wrapper"]
)
def test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_is_spelled_by_the_signature_one_of_its_links_carries(
    shape: str,
) -> None:
    rate = inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)
    receiver = inspect.Parameter("receiver", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    called = CallableGetterDeleter()

    def signed(link: Callable[..., object], *receivers: inspect.Parameter) -> Callable[..., object]:
        link.__signature__ = inspect.Signature([*receivers, rate])
        return link

    def wrapper() -> Callable[..., object]:
        return functools.wraps(called)(lambda *args: called(*args))

    routine_builders = {
        "partial": lambda: signed(functools.partial(called)),
        "functools-wraps-wrapper": lambda: signed(wrapper()),
        "bound-method": lambda: types.MethodType(signed(wrapper(), receiver), object()),
        "partial-of-a-signed-wrapper": lambda: functools.partial(signed(wrapper())),
    }
    routine = routine_builders[shape]()

    assert surface_form(routine) == "(rate: int)"
    assert named_classes(routine) == {int}


@pytest.mark.parametrize(
    ("called", "refusing_its_call"),
    [
        pytest.param(
            StringSignedCall(),
            r" is read through .*\.StringSignedCall\.__call__\b.*'\(self, rate\)'.*\bbuiltins\.str\b",
            id="string-signature",
        ),
        pytest.param(EnumCall(), r" wraps .*\.Tariff\b.*\benum\.Enum\b", id="enum"),
        pytest.param(GetterCall(), _REFUSING_A_CALLABLE_GETTER, id="callable-getter"),
        pytest.param(
            ClassmethodWrapperCall(),
            _REFUSING_A_CALLABLE_GETTER,
            id="classmethod-of-a-wrapper-of-a-callable-getter",
        ),
    ],
)
def test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_raises_the_type_error_the_call_it_is_read_through_raises_naming_the_routine(
    called: object, refusing_its_call: str
) -> None:
    routine = functools.partial(called)
    naming_the_routine = re.escape(repr(routine)) + refusing_its_call
    with pytest.raises(TypeError, match=naming_the_routine):
        surface_form(routine)
    with pytest.raises(TypeError, match=naming_the_routine):
        named_classes(routine)


def test_a_routine_whose_chain_ends_at_an_object_whose_call_wraps_a_refused_class_raises_the_type_error_naming_that_class() -> None:
    class ZipCall:
        @functools.wraps(zip)
        def __call__(self, *iterables: object) -> object: ...

    zipping = functools.partial(ZipCall())

    naming_zip = r"\bbuiltins\.zip\b.*\bbuiltins\.zip\b"
    with pytest.raises(TypeError, match=naming_zip):
        surface_form(zipping)
    with pytest.raises(TypeError, match=naming_zip):
        named_classes(zipping)


def test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_a_partial_as_call_raises_a_type_error_naming_it_and_that_call_without_binding_the_partial() -> None:
    def settle(rate: int) -> None: ...

    class PartialCall:
        __call__ = functools.partial(settle)

    class SignedPartialCall:
        __call__ = functools.partial(settle)
        __call__.__signature__ = inspect.Signature(
            [
                inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
            ]
        )

    class NestedCall:
        __call__ = PartialCall()

    called = functools.partial(PartialCall())
    calling = functools.wraps(PartialCall())(lambda rate: None)
    nested = functools.partial(NestedCall())

    naming_the_partial_and_that_call = r"\bfunctools\.partial\(.*\.PartialCall\.__call__\b.*\bfunctools\.partial\b.*\b3\.14\b"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(TypeError, match=naming_the_partial_and_that_call):
            surface_form(called)
        with pytest.raises(TypeError, match=naming_the_partial_and_that_call):
            named_classes(called)
        with pytest.raises(TypeError, match=r"\.<lambda> is read through .*\.PartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(calling)
        with pytest.raises(TypeError, match=r"\bfunctools\.partial\(.*\.SignedPartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(functools.partial(SignedPartialCall()))
        with pytest.raises(TypeError, match=rf"{re.escape(repr(nested))} is read through .*\.PartialCall\.__call__\b.*\bfunctools\.partial\b"):
            surface_form(nested)


@pytest.mark.parametrize(
    ("call_class", "kind"),
    [
        pytest.param(ChainedCall, r"\bbuiltins\.staticmethod\b", id="staticmethod"),
        pytest.param(
            PartialFirstCall,
            r"\.PartialFirstGetterPartial\b",
            id="partial-taking-get-from-a-later-base",
        ),
    ],
)
def test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_as_call_a_classmethod_that_wraps_an_object_whose_type_defines_get_raises_a_type_error_naming_it_that_call_and_that_type(
    call_class: type, kind: str
) -> None:
    called = functools.partial(call_class())

    refusing_that_call = (
        rf" is read through .*\.{call_class.__name__}\.__call__, a classmethod\b"
        rf".*{kind}.*\b3\.11\b.*\b3\.13\b"
    )
    with pytest.raises(TypeError, match=re.escape(repr(called)) + refusing_that_call):
        surface_form(called)
    with pytest.raises(TypeError, match=re.escape(repr(called)) + refusing_that_call):
        named_classes(called)
    with pytest.raises(TypeError, match=r"\.<lambda>" + refusing_that_call):
        surface_form(functools.wraps(call_class())(lambda rate: None))


@pytest.mark.parametrize(("call", "kind"), CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE)
def test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_a_call_inspect_binds_to_an_object_that_is_not_callable_raises_a_type_error_naming_it_that_call_and_that_object_type(
    call: object, kind: str
) -> None:
    called = object_whose_call_is(call)
    routine = functools.partial(called)

    refusing_that_call = rf" is read through .*\.Caller\.__call__\b.*{kind}.*\bnot callable\b"
    with pytest.raises(TypeError, match=re.escape(repr(routine)) + refusing_that_call):
        surface_form(routine)
    with pytest.raises(TypeError, match=re.escape(repr(routine)) + refusing_that_call):
        named_classes(routine)
    with pytest.raises(TypeError, match=r"\.<lambda>" + refusing_that_call):
        surface_form(functools.wraps(called)(lambda rate: None))


def test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_is_spelled_by_the_call_its_class_resolves_bound_to_it_or_by_the_signature_that_object_carries() -> None:
    def settle(rate: int) -> None: ...

    def charge(owner: object, rate: int) -> None: ...

    class StaticCall:
        __call__ = staticmethod(functools.partial(settle))

    class ClassCall:
        __call__ = classmethod(charge)

    class HalvedCall:
        __call__ = functools.partialmethod(charge, rate=1)

    class SignedCall:
        __signature__ = inspect.Signature([inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float)])
        __text_signature__ = "(rate)"
        __call__ = functools.partial(settle)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(functools.partial(StaticCall())) == "(rate: int) -> None"
        assert surface_form(functools.partial(ClassCall())) == "(rate: int) -> None"
        assert surface_form(functools.partial(HalvedCall())) == "(*, rate: int = 1) -> None"
        assert surface_form(functools.partial(SignedCall())) == "(share: float)"
        assert named_classes(functools.partial(SignedCall())) == {float}


@pytest.mark.parametrize("given", GIVEN_BY_A_METACLASS_GET)
def test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_as_call_a_class_whose_metaclass_defines_get_is_spelled_by_that_class_which_inspect_binds_to_nothing(
    given: object,
) -> None:
    class Held(metaclass=metaclass_whose_get_gives(given)):
        def __init__(self, rate: int) -> None: ...

    assert surface_form(functools.partial(object_whose_call_is(Held))) == "(rate: int) -> None"


def test_a_routine_whose_chain_ends_at_an_object_a_class_defined_in_c_makes_callable_raises_a_type_error_naming_it_that_object_and_that_class() -> None:
    getting = functools.partial(operator.itemgetter(1))

    naming_it_that_object_and_that_class = (
        r"\bfunctools\.partial\(operator\.itemgetter\(1\)\).*\boperator\.itemgetter\.__call__\b"
        r".*\bdefined in C\b"
    )
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_class):
        surface_form(getting)
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_class):
        named_classes(getting)


def test_a_routine_whose_chain_ends_at_an_object_whose_class_overrides_a_call_a_base_defines_in_c_raises_a_type_error_naming_it_that_object_and_that_base() -> None:
    class Connected(sqlite3.Connection):
        def __call__(self, rate: int) -> None: ...

    naming_it_that_object_and_that_base = (
        r"\bfunctools\.partial\(.*\.Connected\b.*\bsqlite3\.Connection\.__call__\b.*\bdefined in C\b"
    )
    with contextlib.closing(Connected(":memory:")) as connection:
        with pytest.raises(TypeError, match=naming_it_that_object_and_that_base):
            surface_form(functools.partial(connection))
        with pytest.raises(TypeError, match=naming_it_that_object_and_that_base):
            named_classes(functools.partial(connection))


@pytest.mark.parametrize(
    "called",
    [
        pytest.param(TextedCall(), id="text-signature"),
        pytest.param(UnsignedTextedCall(), id="beside-a-signature-of-none"),
    ],
)
def test_a_routine_whose_chain_ends_at_an_object_that_carries_a_text_signature_raises_a_type_error_naming_it_that_object_and_that_text(
    called: object,
) -> None:
    naming_it_that_object_and_that_text = (
        rf"\bfunctools\.partial\(.*{re.escape(repr(called))}.*\b__text_signature__ '\(rate\)'"
    )
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_text):
        surface_form(functools.partial(called))
    with pytest.raises(TypeError, match=naming_it_that_object_and_that_text):
        named_classes(functools.partial(called))


def test_a_functools_partial_subclass_whose_type_defines_delete_is_still_a_routine_spelled_by_the_signature_it_leaves() -> None:
    class Deleting(functools.partial):
        def __delete__(self, instance: object) -> None: ...

    def settle(rate: int, share: float) -> str: ...

    assert surface_form(Deleting(settle, 1)) == "(share: float) -> str"
