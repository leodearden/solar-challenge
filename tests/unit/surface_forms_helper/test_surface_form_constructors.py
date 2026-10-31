# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for the constructor inspect reads for a class, or the signature the class carries in its place, and the TypeError raised where inspect reads that constructor differently by minor or cannot read it, one per test.

A constructor every minor skips, and what inspect reads in its place, have their rules
in test_surface_form_skipped_constructors.py. A constructor that wraps a callable
defined in C, recording it as __wrapped__ or giving it where inspect binds the
constructor, has its rules in test_surface_form_c_wrapping_constructors.py.

The classes and functions above the first test are defined at module level, where their
qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import enum
import fractions
import functools
import inspect
import operator
import re
import types
import warnings
from typing import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE,
    GIVEN_BY_A_METACLASS_GET,
    CallableGetter,
    CallableGiver,
    ChainedCall,
    DefCall,
    DeletingGiver,
    Giver,
    NoneSignedCallableGetter,
    PartialFirstGetterPartial,
    SettableGetterPartial,
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    metaclass_whose_get_gives,
    object_whose_call_is,
    recording_object_init,
    with_a_string_signature,
)


class DeletableCallableGetter(CallableGetter):
    """A CallableGetter whose type also defines __delete__, so that inspect counts it a method descriptor before Python 3.13 alone."""

    def __delete__(self, instance: object) -> None: ...


def _charge(self: object, share: fractions.Fraction, rate: int) -> None: ...


def _settle(receiver: object, rate: int) -> None: ...


class PartialCall:
    """A class whose __call__ is a functools.partial, which Python 3.14 alone binds to its instances as a method."""

    __call__ = functools.partial(_charge, rate=1)


class NestedCall:
    """A class whose __call__ is a PartialCall, which inspect reads in turn through the partial PartialCall resolves."""

    __call__ = PartialCall()


def _with_a_text_signature(call: DefCall) -> DefCall:
    call.__text_signature__ = "(rate)"
    return call


class Period(enum.Enum):
    """An Enum with a member, whose signature inspect reads from a different place on each minor."""

    PEAK = "peak"


def test_a_class_whose_init_is_a_partial_raises_a_type_error_naming_it_and_the_class_holding_the_partial() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    class Rebuilt(Built):
        pass

    naming_built_and_its_init = r"\.Built\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    with pytest.raises(TypeError, match=naming_built_and_its_init):
        surface_form(Built)
    with pytest.raises(TypeError, match=naming_built_and_its_init):
        named_classes(Built)
    with pytest.raises(
        TypeError, match=r"\.Rebuilt\b.*\.Built\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(Rebuilt)


def test_a_class_whose_new_is_a_partial_is_spelled_by_the_signature_the_partial_leaves_less_cls() -> None:
    def make(cls: type, rate: int, scale: float = 1.0) -> object: ...

    class Made:
        __new__ = functools.partial(make, scale=2.0)

    assert surface_form(Made) == "(rate: int, *, scale: float = 2.0) -> object"


def test_a_class_whose_init_is_a_partial_beside_a_new_defined_with_def_is_spelled_by_that_new_without_a_warning() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Both:
        def __new__(cls, rate: int) -> object: ...

        __init__ = functools.partial(build, scale=2.0)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(Both) == "(rate: int) -> object"
        assert named_classes(Both) == {int, object}


def test_a_class_whose_inherited_init_is_a_partial_beside_its_own_new_defined_with_def_is_spelled_by_that_new_without_a_warning() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Built:
        __init__ = functools.partial(build, scale=2.0)

    class Remade(Built):
        def __new__(cls, rate: int) -> object: ...

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(Remade) == "(rate: int) -> object"


def test_a_class_that_carries_a_signature_is_spelled_by_that_signature_whatever_its_constructor() -> None:
    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Rated(dict):
        __signature__ = signature

    class Rerated(Rated):
        pass

    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

    class Counted(metaclass=Counting):
        __signature__ = signature

    assert surface_form(Rated) == "(rate: int)"
    assert named_classes(Rated) == {int}
    assert surface_form(Rerated) == "(rate: int)"
    assert surface_form(Counted) == "(rate: int)"
    assert surface_form(functools.partial(Rated)) == "(rate: int)"


def test_a_constructor_that_wraps_one_defined_with_def_is_spelled_by_the_one_it_wraps() -> None:
    class Based:
        def __new__(cls, rate: int) -> "Based":
            return object.__new__(cls)

    class Rebased(Based):
        @functools.wraps(Based.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Rebased":
            return Based.__new__(cls, *args, **kwargs)

    assert surface_form(Rebased) == "(rate: int) -> Based"


def test_a_class_whose_metaclass_call_is_a_partial_raises_a_type_error_naming_it_and_that_call() -> None:
    def settle(cls: type, rate: int, scale: float = 1.0) -> None: ...

    class Partial(type):
        __call__ = functools.partial(settle, scale=2.0)

    class Made(metaclass=Partial):
        pass

    naming_made_and_its_call = r"\.Made\b.*\.Partial\.__call__\b.*\bfunctools\.partial\b"
    with pytest.raises(TypeError, match=naming_made_and_its_call):
        surface_form(Made)
    with pytest.raises(TypeError, match=naming_made_and_its_call):
        named_classes(Made)


def test_a_class_whose_constructor_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_it_that_constructor_and_that_value() -> None:
    class Initialised:
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = "(self, rate)"

    class Priced:
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = lambda: "(self, rate)"

    class Created:
        def __new__(cls, rate: int) -> "Created":
            return object.__new__(cls)

        __new__.__signature__ = "(cls, rate)"

    class Recreated(Created):
        pass

    class Texted:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Texted":
            return object.__new__(cls)

        __new__.__signature__ = "(cls, rate)"

        def __init__(self, rate: int) -> None: ...

    class Counting(type):
        def __call__(cls, rate: int) -> object: ...

        __call__.__signature__ = "(cls, rate)"

    class Counted(metaclass=Counting):
        pass

    class Wrapping(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

        __call__.__signature__ = "(cls, rate)"

    class Wrapped(metaclass=Wrapping):
        pass

    naming_initialised_its_init_and_the_text = (
        r"\.Initialised\b.*\.Initialised\.__init__\b.*'\(self, rate\)'"
        r".*\bbuiltins\.str\b.*\binspect\.Signature\b"
    )
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        surface_form(Initialised)
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        named_classes(Initialised)
    with pytest.raises(TypeError, match=naming_initialised_its_init_and_the_text):
        surface_form(functools.partial(Initialised))
    with pytest.raises(
        TypeError, match=r"\.Priced\b.*\.Priced\.__init__\b.*\bbuiltins\.function\b"
    ):
        surface_form(Priced)
    with pytest.raises(
        TypeError, match=r"\.Created\b.*\.Created\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Created)
    with pytest.raises(
        TypeError, match=r"\.Recreated\b.*\.Created\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Recreated)
    with pytest.raises(
        TypeError, match=r"\.Texted\b.*\.Texted\.__new__\b.*'\(cls, rate\)'"
    ):
        surface_form(Texted)
    with pytest.raises(
        TypeError, match=r"\.Counted\b.*\.Counting\.__call__\b.*'\(cls, rate\)'"
    ):
        surface_form(Counted)
    with pytest.raises(
        TypeError, match=r"\.Wrapped\b.*\.Wrapping\.__call__\b.*'\(cls, rate\)'"
    ):
        surface_form(Wrapped)


@pytest.mark.parametrize(
    ("signature", "carried"),
    [
        pytest.param("(receiver, rate)", r"'\(receiver, rate\)', a builtins\.str\b", id="string"),
        pytest.param(lambda: "(receiver, rate)", r", a builtins\.function\b", id="callable"),
    ],
)
@pytest.mark.parametrize(
    "hold",
    [
        pytest.param(classmethod, id="classmethod"),
        pytest.param(Giver, id="descriptor"),
        pytest.param(
            lambda build: recording_object_init(CallableGiver(build)),
            id="descriptor-recording-a-callable-defined-in-c",
        ),
    ],
)
@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_new_is, "Made.__new__", id="new"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_classmethod_or_descriptor_constructor_gives_a_function_carrying_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_it_that_constructor_and_that_value(
    construct: Callable[[object], type],
    constructor: str,
    hold: Callable[[Callable[..., object]], object],
    signature: object,
    carried: str,
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    build.__signature__ = signature
    cls = construct(hold(build))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*{carried}"
            r".*\binspect\.Signature\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("hold", "form", "classes"),
    [
        pytest.param(classmethod, "(rate: int) -> None", {int}, id="classmethod"),
        pytest.param(
            staticmethod,
            "(receiver: float, rate: int) -> None",
            {float, int},
            id="staticmethod",
        ),
        pytest.param(
            Giver, "(receiver: float, rate: int) -> None", {float, int}, id="descriptor"
        ),
    ],
)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_whose_classmethod_staticmethod_or_descriptor_constructor_itself_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_is_spelled_by_what_inspect_binds_it_to(
    construct: Callable[[object], type],
    hold: Callable[[Callable[..., object]], object],
    form: str,
    classes: set[type],
) -> None:
    def build(receiver: float, rate: int) -> None: ...

    held = hold(build)
    held.__signature__ = "(rate)"
    cls = construct(held)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert surface_form(subject) == form
        assert named_classes(subject) == classes
        assert surface_form(functools.partial(subject)) == form


@pytest.mark.parametrize(
    ("hold", "form", "classes"),
    [
        pytest.param(classmethod, "() -> None", set(), id="classmethod"),
        pytest.param(staticmethod, "(rate: int) -> None", {int}, id="staticmethod"),
        pytest.param(Giver, "(rate: int) -> None", {int}, id="descriptor"),
    ],
)
def test_a_class_whose_classmethod_staticmethod_or_descriptor_new_itself_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_is_spelled_by_what_getattr_binds_it_to_less_its_first_parameter(
    hold: Callable[[Callable[..., object]], object], form: str, classes: set[type]
) -> None:
    def build(receiver: float, rate: int) -> None: ...

    held = hold(build)
    held.__signature__ = "(rate)"
    cls = class_whose_new_is(held)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert surface_form(subject) == form
        assert named_classes(subject) == classes
        assert surface_form(functools.partial(subject)) == form


@pytest.mark.parametrize(
    ("wrap", "kind"),
    [
        pytest.param(Giver, r"\.Giver\b", id="descriptor"),
        pytest.param(
            lambda build: Giver(with_a_string_signature(build)),
            r"\.Giver\b",
            id="descriptor-giving-a-string-signature",
        ),
        pytest.param(staticmethod, r"\bbuiltins\.staticmethod\b", id="staticmethod"),
        pytest.param(classmethod, r"\bbuiltins\.classmethod\b", id="classmethod"),
        pytest.param(
            lambda build: object.__init__, r"\bbuiltins\.wrapper_descriptor\b", id="slot-wrapper"
        ),
        pytest.param(
            lambda build: str.join, r"\bbuiltins\.method_descriptor\b", id="method-descriptor"
        ),
        pytest.param(
            SettableGetterPartial, r"\.SettableGetterPartial\b", id="partial-with-its-own-get"
        ),
        pytest.param(
            PartialFirstGetterPartial,
            r"\.PartialFirstGetterPartial\b",
            id="partial-taking-get-from-a-later-base",
        ),
        pytest.param(functools.cache, r"\bfunctools\._lru_cache_wrapper\b", id="lru-cache"),
    ],
)
@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_new_is, "Made.__new__", id="new"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_classmethod_constructor_wraps_an_object_whose_type_defines_get_raises_a_type_error_naming_it_that_constructor_and_that_type(
    construct: Callable[[object], type],
    constructor: str,
    wrap: Callable[[Callable[..., object]], object],
    kind: str,
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    cls = construct(classmethod(wrap(build)))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}, a classmethod\b"
            rf".*{kind}.*\b3\.11\b.*\b3\.13\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


def test_a_class_beside_whose_constructor_inspect_binds_a_classmethod_that_wraps_an_object_whose_type_defines_get_raises_a_type_error_naming_that_classmethod() -> None:
    def build(receiver: object, rate: int) -> None: ...

    class Joined:
        __init__ = classmethod(str.join)

    class Made(Joined):
        def __new__(cls, rate: int) -> object: ...

    class Static:
        __new__ = classmethod(staticmethod(build))

    class Built(Static):
        def __init__(self, rate: int) -> None: ...

    class Both:
        def __new__(cls, rate: int) -> object: ...

        __init__ = classmethod(staticmethod(build))

    for cls, constructor, kind in (
        (Made, "Joined.__init__", r"\bbuiltins\.method_descriptor\b"),
        (Built, "Static.__new__", r"\bbuiltins\.staticmethod\b"),
        (Both, "Both.__init__", r"\bbuiltins\.staticmethod\b"),
    ):
        naming_that_classmethod = (
            rf"\.{cls.__name__}\b.*\.{re.escape(constructor)}, a classmethod\b.*{kind}"
        )
        with pytest.raises(TypeError, match=naming_that_classmethod):
            surface_form(cls)
        with pytest.raises(TypeError, match=naming_that_classmethod):
            named_classes(cls)


@pytest.mark.parametrize(
    ("wrapped", "form", "classes"),
    [
        pytest.param(_settle, "(rate: int) -> None", {int}, id="function"),
        pytest.param(functools.partial(_settle), "(rate: int) -> None", {int}, id="partial"),
        pytest.param(types.MethodType(_settle, object()), "() -> None", set(), id="bound-method"),
    ],
)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_whose_classmethod_constructor_wraps_a_function_a_partial_or_a_bound_method_is_spelled_by_what_inspect_binds_it_to(
    construct: Callable[[object], type], wrapped: object, form: str, classes: set[type]
) -> None:
    cls = construct(classmethod(wrapped))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(cls) == form
        assert surface_form(functools.partial(cls)) == form
        assert named_classes(cls) == classes


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: functools.wraps(Period)(lambda receiver, value: None), id="wrapper"),
        pytest.param(
            lambda: functools.wraps(functools.partial(Period))(lambda receiver, value: None),
            id="wrapper-of-a-partial",
        ),
        pytest.param(lambda: Period, id="the-enum"),
        pytest.param(
            lambda: classmethod(functools.wraps(Period)(lambda receiver, value: None)),
            id="classmethod",
        ),
        pytest.param(lambda: Giver(functools.wraps(Period)(lambda value: None)), id="descriptor"),
    ],
)
@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_new_is, "Made.__new__", id="new"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_inspect_reads_as_an_enum_raises_a_type_error_naming_it_that_constructor_and_that_enum(
    construct: Callable[[object], type], constructor: str, build: Callable[[], object]
) -> None:
    cls = construct(build())

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*\.Period\b.*\benum\.Enum\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("construct", "constructor", "refusal"),
    [
        pytest.param(class_whose_new_is, "Made.__new__", r"\.Period\b.*\benum\.Enum\b", id="new"),
        pytest.param(
            class_whose_init_is,
            "Built.__init__",
            r"\bfunctools\.partial\b.*\b3\.14\b",
            id="init",
        ),
        pytest.param(
            class_whose_metaclass_call_is,
            "Calling.__call__",
            r"\bfunctools\.partial\b.*\b3\.14\b",
            id="metaclass-call",
        ),
    ],
)
def test_a_class_whose_constructor_is_a_partial_of_an_enum_raises_the_type_error_naming_that_enum_as_new_and_the_one_for_its_binding_as_init_or_metaclass_call(
    construct: Callable[[object], type], constructor: str, refusal: str
) -> None:
    cls = construct(functools.partial(Period))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*{refusal}"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("signature", "form"),
    [
        pytest.param(
            inspect.Signature(
                [
                    inspect.Parameter("receiver", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                    inspect.Parameter(
                        "rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int
                    ),
                ]
            ),
            "(rate: int)",
            id="signature",
        ),
        pytest.param(None, "(rate: int) -> None", id="signature-of-none"),
    ],
)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_new_is, id="new"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_wraps_an_enum_but_carries_a_signature_or_a_signature_of_none_is_spelled_by_what_inspect_reads(
    construct: Callable[[object], type], signature: inspect.Signature | None, form: str
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    build.__wrapped__ = Period
    build.__signature__ = signature
    cls = construct(build)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert surface_form(subject) == form
        assert named_classes(subject) == {int}
        assert surface_form(functools.partial(subject)) == form


def test_a_class_whose_metaclass_resolves_a_call_defined_in_python_is_spelled_by_that_call_whatever_its_constructor() -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Charging(type):
        def __call__(cls, rate: int) -> None: ...

    class Keyed(dict, metaclass=Charging):
        pass

    class Built(metaclass=Charging):
        __init__ = functools.partial(build, scale=2.0)

    class Created(metaclass=Charging):
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Created":
            return object.__new__(cls)

    assert surface_form(Keyed) == "(rate: int) -> None"
    assert named_classes(Keyed) == {int}
    assert surface_form(Built) == "(rate: int) -> None"
    assert surface_form(Created) == "(rate: int) -> None"


@pytest.mark.parametrize(
    ("descriptor", "reading"),
    [
        pytest.param(CallableGetter(), r"\bevery admitted minor\b", id="get-only"),
        pytest.param(
            NoneSignedCallableGetter(lambda rate: None),
            r"\bevery admitted minor\b",
            id="get-only-signature-of-none",
        ),
        pytest.param(DeletableCallableGetter(), r"\b__delete__\b.*\b3\.13\b", id="get-delete"),
    ],
)
def test_a_class_constructed_through_a_descriptor_inspect_reads_as_a_builtin_raises_a_type_error_naming_it_that_constructor_and_the_descriptor_type(
    descriptor: object, reading: str
) -> None:
    class Built:
        __init__ = descriptor

    class Rebuilt(Built):
        pass

    class Made:
        __new__ = descriptor

    class Calling(type):
        __call__ = descriptor

    class Called(metaclass=Calling):
        pass

    class Wrapped:
        @functools.wraps(descriptor)
        def __init__(self, rate: int) -> None: ...

    kind = rf"\.{type(descriptor).__qualname__}\b"
    for cls, constructor in (
        (Built, "Built.__init__"),
        (Rebuilt, "Built.__init__"),
        (Made, "Made.__new__"),
        (Called, "Calling.__call__"),
        (Wrapped, "Wrapped.__init__"),
    ):
        naming_it = rf"\.{cls.__name__}\b.*\.{re.escape(constructor)}\b.*{kind}.*{reading}"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(cls)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(cls)
    with pytest.raises(TypeError, match=rf"\.Built\b.*\.Built\.__init__\b.*{kind}"):
        surface_form(functools.partial(Built))


@pytest.mark.parametrize(
    ("hold", "kind"),
    [
        pytest.param(lambda build: Giver(Giver(build)), r"\.Giver\b", id="get-only-descriptor"),
        pytest.param(
            lambda build: CallableGiver(Giver(build)),
            r"\.Giver\b",
            id="callable-descriptor-giving-one",
        ),
        pytest.param(
            lambda build: Giver(DeletingGiver(build)),
            r"\.DeletingGiver\b",
            id="get-delete-descriptor",
        ),
        pytest.param(
            lambda build: Giver(types.SimpleNamespace(__signature__="(receiver, rate)")),
            r"\btypes\.SimpleNamespace\b",
            id="object-carrying-a-string-signature",
        ),
        pytest.param(
            lambda build: types.SimpleNamespace(),
            r"\btypes\.SimpleNamespace\b",
            id="object-defining-no-get",
        ),
        pytest.param(
            lambda build: staticmethod(types.SimpleNamespace()),
            r"\btypes\.SimpleNamespace\b",
            id="staticmethod",
        ),
        pytest.param(
            lambda build: classmethod(types.SimpleNamespace()),
            r"\btypes\.SimpleNamespace\b",
            id="classmethod",
        ),
        pytest.param(
            lambda build: classmethod(None),
            r"\bbuiltins\.NoneType\b",
            id="classmethod-of-none",
        ),
    ],
)
@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_new_is, "Made.__new__", id="new"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_inspect_binds_to_an_object_that_is_not_callable_raises_a_type_error_naming_it_that_constructor_and_that_object_type(
    construct: Callable[[object], type],
    constructor: str,
    hold: Callable[[Callable[..., object]], object],
    kind: str,
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    cls = construct(hold(build))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*{kind}.*\bnot callable\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_new_is, "Made.__new__", id="new"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_wraps_a_descriptor_whose_type_defines_get_but_neither_set_nor_delete_and_that_is_not_callable_raises_a_type_error_naming_it_that_constructor_and_the_descriptor_type(
    construct: Callable[[object], type], constructor: str
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    cls = construct(functools.wraps(Giver(build))(lambda receiver, rate: None))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*\.Giver\b"
            r".*\bmethod descriptor\b.*\bevery admitted minor\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize("given", GIVEN_BY_A_METACLASS_GET)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_whose_init_or_metaclass_call_is_a_class_whose_metaclass_defines_get_is_spelled_by_that_class_which_inspect_binds_to_nothing(
    construct: Callable[[object], type], given: object
) -> None:
    class Held(metaclass=metaclass_whose_get_gives(given)):
        def __init__(self, rate: int) -> None: ...

    assert surface_form(construct(Held)) == "(rate: int) -> None"


@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_new_is, id="new"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_inspect_reads_as_a_refused_class_raises_the_type_error_naming_that_class(
    construct: Callable[[object], type],
) -> None:
    def build(self: object, rate: int) -> None: ...

    class Ledger(dict):
        pass

    class PartialInit:
        __init__ = functools.partial(build)

    naming_ledger = r"\.Ledger is constructed by builtins\.dict\b.*\bdefined in C\b"
    for held, naming_it in (
        (Ledger, naming_ledger),
        (functools.wraps(Ledger)(lambda *args: None), naming_ledger),
        (
            PartialInit,
            r"\.PartialInit is constructed through .*\.PartialInit\.__init__, "
            r"a functools\.partial\b.*\b3\.14\b",
        ),
    ):
        cls = construct(held)

        class Inheriting(cls):
            pass

        for subject in (cls, Inheriting):
            with pytest.raises(TypeError, match=naming_it):
                surface_form(subject)
            with pytest.raises(TypeError, match=naming_it):
                named_classes(subject)
            with pytest.raises(TypeError, match=naming_it):
                surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("construct", "form_by_that_class"),
    [
        pytest.param(class_whose_init_is, "(rate: int)", id="init"),
        pytest.param(class_whose_new_is, "()", id="new"),
        pytest.param(class_whose_metaclass_call_is, "(rate: int)", id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_inspect_reads_as_a_refused_class_is_spelled_by_a_signature_carried_by_it_by_that_class_or_by_a_link_between_them(
    construct: Callable[[object], type], form_by_that_class: str
) -> None:
    receiver = inspect.Parameter("receiver", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    rate = inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)

    class Ledger(dict):
        pass

    class SignedLedger(dict):
        __signature__ = inspect.Signature([rate])

    signed_link = functools.wraps(Ledger)(lambda *args: None)
    signed_link.__signature__ = inspect.Signature([receiver, rate])

    class SignedHolder(construct(Ledger)):
        __signature__ = inspect.Signature([rate])

    assert surface_form(construct(SignedLedger)) == form_by_that_class
    assert surface_form(construct(signed_link)) == "(rate: int)"
    assert surface_form(SignedHolder) == "(rate: int)"


def test_a_class_constructed_through_a_descriptor_that_carries_a_signature_or_whose_get_gives_a_function_is_spelled_by_what_inspect_reads() -> None:
    def build(rate: int) -> str: ...

    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Giving:
        def __get__(self, instance: object, owner: type) -> Callable[..., object]:
            return build

    class Signed(CallableGetter):
        __signature__ = signature

    class SignedDeletable(DeletableCallableGetter):
        __signature__ = signature

    class Given:
        __init__ = Giving()

    class Rated:
        __init__ = Signed()

    class Rerated:
        __init__ = SignedDeletable()

    class Calling(type):
        __call__ = Giving()

    class Called(metaclass=Calling):
        pass

    class SignedCalling(type):
        __call__ = Signed()

    class SignedCalled(metaclass=SignedCalling):
        pass

    assert surface_form(Given) == "(rate: int) -> str"
    assert surface_form(Rated) == "(rate: int)"
    assert surface_form(Rerated) == "(rate: int)"
    assert surface_form(Called) == "(rate: int) -> str"
    assert surface_form(SignedCalled) == "(rate: int)"


def test_a_class_constructed_through_an_object_whose_class_resolves_a_partial_as_call_raises_a_type_error_naming_it_and_that_call_without_binding_the_partial() -> None:
    class Built:
        __init__ = PartialCall()

    class Rebuilt(Built):
        pass

    class Made:
        __new__ = PartialCall()

    class Calling(type):
        __call__ = PartialCall()

    class Called(metaclass=Calling):
        pass

    class Wrapped:
        __init__ = functools.wraps(PartialCall())(lambda self, share: None)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for cls in (Built, Rebuilt, Made, Called, Wrapped):
            naming_it_and_that_call = (
                rf"\.{cls.__name__}\b.*\.PartialCall\.__call__\b.*\bfunctools\.partial\b.*\b3\.14\b"
            )
            with pytest.raises(TypeError, match=naming_it_and_that_call):
                surface_form(cls)
            with pytest.raises(TypeError, match=naming_it_and_that_call):
                named_classes(cls)
        with pytest.raises(TypeError, match=r"\.Built\b.*\.PartialCall\.__call__\b"):
            surface_form(functools.partial(Built))


@pytest.mark.parametrize(("call", "kind"), CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_new_is, id="new"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_constructed_through_an_object_whose_class_resolves_a_call_inspect_binds_to_an_object_that_is_not_callable_raises_a_type_error_naming_it_that_call_and_that_object_type(
    construct: Callable[[object], type], call: object, kind: str
) -> None:
    cls = construct(object_whose_call_is(call))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__} is read through .*\.Caller\.__call__\b.*{kind}.*\bnot callable\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("build", "read_through"),
    [
        pytest.param(
            lambda: operator.itemgetter(1),
            r"operator\.itemgetter\(1\), .*\boperator\.itemgetter\.__call__\b.*\bdefined in C\b",
            id="call-defined-in-c",
        ),
        pytest.param(
            lambda: _with_a_text_signature(DefCall()),
            r"<.*\.DefCall object\b.*\b__text_signature__ '\(rate\)'",
            id="text-signature",
        ),
        pytest.param(
            NestedCall,
            r".*\.PartialCall\.__call__\b.*\bfunctools\.partial\b",
            id="call-read-through-an-object",
        ),
        pytest.param(
            ChainedCall,
            r".*\.ChainedCall\.__call__, a classmethod\b.*\bbuiltins\.staticmethod\b",
            id="call-a-classmethod-binds-by-minor",
        ),
    ],
)
@pytest.mark.parametrize(
    "construct",
    [
        pytest.param(class_whose_init_is, id="init"),
        pytest.param(class_whose_new_is, id="new"),
        pytest.param(class_whose_metaclass_call_is, id="metaclass-call"),
    ],
)
def test_a_class_constructed_through_an_object_its_class_makes_callable_raises_the_type_error_a_routine_whose_chain_ends_at_that_object_raises_naming_the_class(
    construct: Callable[[object], type], build: Callable[[], object], read_through: str
) -> None:
    cls = construct(build())

    refusing_its_call = rf"\.{cls.__name__} is read through {read_through}"
    with pytest.raises(TypeError, match=refusing_its_call):
        surface_form(cls)
    with pytest.raises(TypeError, match=refusing_its_call):
        named_classes(cls)


def test_a_class_constructed_through_an_object_its_class_makes_callable_is_spelled_by_the_call_its_class_resolves_bound_to_it_or_by_the_signature_that_object_carries() -> None:
    class StaticCall:
        __call__ = staticmethod(functools.partial(_charge, rate=1))

    class SignedCall:
        __signature__ = inspect.Signature(
            [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float)]
        )
        __text_signature__ = "(rate)"
        __call__ = functools.partial(_charge, rate=1)

    class Built:
        __init__ = DefCall()

    class Made:
        __new__ = DefCall()

    class Calling(type):
        __call__ = DefCall()

    class Called(metaclass=Calling):
        pass

    class Static:
        __init__ = StaticCall()

    class Signed:
        __init__ = SignedCall()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert surface_form(Built) == "(share: Fraction, rate: int) -> None"
        assert surface_form(Made) == "(rate: int) -> None"
        assert surface_form(Called) == "(share: Fraction, rate: int) -> None"
        assert surface_form(Static) == "(self: object, share: Fraction, *, rate: int = 1) -> None"
        assert surface_form(Signed) == "(share: float)"
