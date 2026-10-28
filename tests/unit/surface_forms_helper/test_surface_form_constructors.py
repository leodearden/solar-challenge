# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for the constructor inspect reads for a class, or the signature the class carries in its place, and the TypeError raised where inspect reads that constructor differently by minor or cannot read it, one per test.

The classes and functions above the first test are defined at module level, where their
qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import decimal
import enum
import fractions
import functools
import inspect
import operator
import re
import sys
import types
import warnings
from typing import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGetter,
    NoneSignedCallableGetter,
    SettableGetterPartial,
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
)


class Ledger(dict):
    """A class that inherits its constructor from dict, which CPython defines in C."""


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


class DefCall:
    """A class whose __call__ is defined with def."""

    def __call__(self, share: fractions.Fraction, rate: int) -> None: ...


def _with_a_text_signature(call: DefCall) -> DefCall:
    call.__text_signature__ = "(rate)"
    return call


def _with_a_string_signature(function: Callable[..., object]) -> Callable[..., object]:
    function.__signature__ = "(receiver, rate)"
    return function


class Period(enum.Enum):
    """An Enum with a member, whose signature inspect reads from a different place on each minor."""

    PEAK = "peak"


class Giver:
    """A descriptor whose __get__ gives the callable it was made with."""

    def __init__(self, given: Callable[..., object]) -> None:
        self.given = given

    def __get__(self, instance: object, owner: type | None = None) -> Callable[..., object]:
        return self.given


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


@pytest.mark.parametrize(
    "new",
    [
        pytest.param(object.__new__, id="builtin"),
        pytest.param(staticmethod(object.__new__), id="staticmethod"),
    ],
)
def test_a_class_whose_init_is_a_partial_beside_a_new_defined_in_c_raises_the_type_error_naming_the_partial(
    new: object,
) -> None:
    def build(self: object, rate: int, scale: float = 1.0) -> None: ...

    class Assigned:
        __new__ = new
        __init__ = functools.partial(build, scale=2.0)

    with pytest.raises(
        TypeError, match=r"\.Assigned\b.*\.Assigned\.__init__\b.*\bfunctools\.partial\b"
    ):
        surface_form(Assigned)


@pytest.mark.parametrize(
    ("cls", "naming_it_and_its_constructor"),
    [
        pytest.param(
            functools.partial,
            r"\bfunctools\.partial\b.*\bfunctools\.partial\b",
            id="functools.partial",
        ),
        pytest.param(int, r"\bbuiltins\.int\b.*\bbuiltins\.int\b", id="int"),
        pytest.param(list, r"\bbuiltins\.list\b.*\bbuiltins\.list\b", id="list"),
        pytest.param(
            decimal.Decimal,
            r"\bdecimal\.Decimal\b.*\bdecimal\.Decimal\b",
            id="decimal.Decimal",
        ),
        pytest.param(
            types.ModuleType,
            r"\bbuiltins\.module\b.*\bbuiltins\.module\b",
            id="types.ModuleType",
        ),
        pytest.param(
            types.FunctionType,
            r"\bbuiltins\.function\b.*\bbuiltins\.function\b",
            id="types.FunctionType",
        ),
        pytest.param(
            Ledger,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_constructors\.Ledger\b.*\bbuiltins\.dict\b",
            id="Ledger",
        ),
    ],
)
def test_a_class_constructed_by_a_class_defined_in_c_raises_a_type_error_naming_it_and_that_class(
    cls: type, naming_it_and_its_constructor: str
) -> None:
    with pytest.raises(TypeError, match=naming_it_and_its_constructor):
        surface_form(cls)
    with pytest.raises(TypeError, match=naming_it_and_its_constructor):
        named_classes(cls)


def test_a_class_that_object_constructs_is_spelled_with_no_parameters() -> None:
    class Plain:
        pass

    assert surface_form(object) == "()"
    assert surface_form(Plain) == "()"


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


def test_a_class_whose_new_or_init_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_constructor_and_that_callable() -> None:
    class Created:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Created":
            return object.__new__(cls)

        def __init__(self, rate: int) -> None: ...

    class Recreated(Created):
        pass

    class Initialised:
        @functools.wraps(object.__init__)
        def __init__(self, rate: int) -> None: ...

    class Keyed(dict):
        @functools.wraps(dict.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Keyed":
            return dict.__new__(cls)

        def __init__(self, rate: int) -> None: ...

    naming_created_and_its_new = r"\.Created\b.*\.Created\.__new__\b.*\bobject\.__new__\b"
    with pytest.raises(TypeError, match=naming_created_and_its_new):
        surface_form(Created)
    with pytest.raises(TypeError, match=naming_created_and_its_new):
        named_classes(Created)
    with pytest.raises(
        TypeError, match=r"\.Recreated\b.*\.Created\.__new__\b.*\bobject\.__new__\b"
    ):
        surface_form(Recreated)
    with pytest.raises(
        TypeError,
        match=r"\.Initialised\b.*\.Initialised\.__init__\b.*\bobject\.__init__\b",
    ):
        surface_form(Initialised)
    with pytest.raises(
        TypeError, match=r"\.Keyed\b.*\.Keyed\.__new__\b.*\bdict\.__new__\b"
    ):
        surface_form(Keyed)


@pytest.mark.skipif(
    sys.version_info < (3, 13), reason="warnings.deprecated is new in Python 3.13"
)
def test_a_class_decorated_with_warnings_deprecated_raises_the_type_error_naming_the_new_it_writes() -> None:
    @warnings.deprecated("use Meter")
    class Gauge:
        def __init__(self, rate: int) -> None: ...

    with pytest.raises(
        TypeError, match=r"\.Gauge\b.*\.Gauge\.__new__\b.*\bobject\.__new__\b"
    ):
        surface_form(Gauge)


def test_a_constructor_that_wraps_one_defined_with_def_is_spelled_by_the_one_it_wraps() -> None:
    class Based:
        def __new__(cls, rate: int) -> "Based":
            return object.__new__(cls)

    class Rebased(Based):
        @functools.wraps(Based.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Rebased":
            return Based.__new__(cls, *args, **kwargs)

    assert surface_form(Rebased) == "(rate: int) -> Based"


def test_a_wrapper_of_a_callable_defined_in_c_that_inspect_reads_after_another_constructor_leaves_the_class_spelled_by_that_constructor() -> None:
    class Paired:
        def __new__(cls, rate: int) -> "Paired":
            return object.__new__(cls)

        @functools.wraps(object.__init__)
        def __init__(self, *args: object, **kwargs: object) -> None: ...

    class Wrapping:
        @functools.wraps(object.__new__)
        def __new__(cls, *args: object, **kwargs: object) -> "Wrapping":
            return object.__new__(cls)

    class Overriding(Wrapping):
        def __init__(self, rate: int) -> None: ...

    assert surface_form(Paired) == "(rate: int) -> Paired"
    assert surface_form(Overriding) == "(rate: int) -> None"


def test_a_class_whose_metaclass_call_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_call_and_that_callable() -> None:
    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, *args: object, **kwargs: object) -> object:
            return super().__call__(*args, **kwargs)

    class Counted(metaclass=Counting):
        def __init__(self, rate: int) -> None: ...

    naming_counted_and_its_call = r"\.Counted\b.*\.Counting\.__call__\b.*\btype\.__call__\b"
    with pytest.raises(TypeError, match=naming_counted_and_its_call):
        surface_form(Counted)
    with pytest.raises(TypeError, match=naming_counted_and_its_call):
        named_classes(Counted)


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
    [pytest.param(classmethod, id="classmethod"), pytest.param(Giver, id="descriptor")],
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
            lambda build: Giver(_with_a_string_signature(build)),
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


def test_a_class_whose_constructor_wraps_a_callable_defined_in_c_but_carries_a_signature_of_none_is_spelled_by_that_constructor() -> None:
    class Created:
        @functools.wraps(object.__new__)
        def __new__(cls, rate: int) -> object:
            return object.__new__(cls)

        __new__.__signature__ = None

    class Initialised:
        @functools.wraps(object.__init__)
        def __init__(self, rate: int) -> None: ...

        __init__.__signature__ = None

    class Counting(type):
        @functools.wraps(type.__call__)
        def __call__(cls, rate: int) -> object: ...

        __call__.__signature__ = None

    class Counted(metaclass=Counting):
        pass

    assert surface_form(Created) == "(rate: int) -> object"
    assert surface_form(Initialised) == "(rate: int) -> None"
    assert surface_form(Counted) == "(rate: int) -> object"


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
