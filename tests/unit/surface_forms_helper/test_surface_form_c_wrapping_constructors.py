# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for a class whose __new__, __init__ or metaclass __call__ wraps a callable defined in C, recording it as __wrapped__, as functools.wraps(object.__new__) does, or giving it where inspect binds the constructor, as staticmethod(object.__init__) does, and for the TypeError raised where inspect reads that constructor differently by minor, one per test.

The classes above the first test are defined at module level, where their qualified
names carry no '<locals>' and a parametrize decorator can reach them.
"""

import fractions
import functools
import re
import sys
import types
import warnings
from typing import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGiver,
    DefCall,
    DeletingGiver,
    Giver,
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    recording_object_init,
)


class DeletingCallableGiver(CallableGiver):
    """A CallableGiver whose type also defines __delete__."""

    def __delete__(self, instance: object) -> None: ...


class SettingCallableGiver(CallableGiver):
    """A CallableGiver whose type also defines __set__."""

    def __set__(self, instance: object, value: object) -> None: ...


class SettingGiver(Giver):
    """A Giver whose type also defines __set__ but no __call__."""

    def __set__(self, instance: object, value: object) -> None: ...


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


@pytest.mark.parametrize(
    ("hold", "form", "classes"),
    [
        pytest.param(
            lambda build: recording_object_init(CallableGiver(build)),
            "(receiver: float, rate: int) -> None",
            {float, int},
            id="descriptor",
        ),
        pytest.param(
            lambda build: staticmethod(functools.wraps(object.__init__)(build)),
            "(self, /, *args, **kwargs)",
            set(),
            id="staticmethod",
        ),
        pytest.param(
            lambda build: functools.wraps(recording_object_init(CallableGiver(build)))(
                lambda self, rate: None
            ),
            "(*args, **kwargs)",
            set(),
            id="wrapper-of-such-a-descriptor",
        ),
        pytest.param(
            lambda build: recording_object_init(Giver(build)),
            "(receiver: float, rate: int) -> None",
            {float, int},
            id="non-callable-descriptor",
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
def test_a_class_whose_constructor_is_or_wraps_a_descriptor_whose_type_defines_get_but_neither_set_nor_delete_is_spelled_by_what_inspect_binds_it_to_whatever_the_descriptor_records_as_wrapped(
    construct: Callable[[object], type],
    hold: Callable[[Callable[..., object]], object],
    form: str,
    classes: set[type],
) -> None:
    def build(receiver: float, rate: int) -> None: ...

    cls = construct(hold(build))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert surface_form(subject) == form
        assert named_classes(subject) == classes
        assert surface_form(functools.partial(subject)) == form


@pytest.mark.parametrize(
    ("callable_defined_in_c", "form"),
    [
        pytest.param(object().__init__, "(*args, **kwargs)", id="method-wrapper"),
        pytest.param(
            dict.__dict__["fromkeys"],
            "(type, iterable, value=None, /)",
            id="classmethod-descriptor",
        ),
        pytest.param(object.__new__, "(*args, **kwargs)", id="builtin"),
        pytest.param(object.__init__, "(self, /, *args, **kwargs)", id="slot-wrapper"),
    ],
)
@pytest.mark.parametrize(
    "hold",
    [pytest.param(staticmethod, id="staticmethod"), pytest.param(Giver, id="descriptor")],
)
def test_a_class_whose_metaclass_call_or_init_inspect_binds_to_a_callable_defined_in_c_is_spelled_by_that_callable_text_signature(
    hold: Callable[[object], object], callable_defined_in_c: object, form: str
) -> None:
    constructor = hold(callable_defined_in_c)

    class Reinitialised(class_whose_metaclass_call_is(constructor)):
        def __init__(self, share: "fractions.Fraction") -> None: ...

    class Created:
        def __new__(cls, share: "fractions.Fraction") -> object: ...

    class Built(Created):
        __init__ = constructor

    for cls in (Reinitialised, Built):

        class Inheriting(cls):
            pass

        for subject in (cls, Inheriting):
            assert surface_form(subject) == form
            assert named_classes(subject) == set()
            assert surface_form(functools.partial(subject)) == form


@pytest.mark.parametrize(
    "giver",
    [
        pytest.param(CallableGiver, id="get-only-descriptor"),
        pytest.param(Giver, id="non-callable-get-only-descriptor"),
        pytest.param(DeletingCallableGiver, id="get-delete-descriptor"),
        pytest.param(DeletingGiver, id="non-callable-get-delete-descriptor"),
        pytest.param(SettingCallableGiver, id="get-set-descriptor"),
        pytest.param(SettingGiver, id="non-callable-get-set-descriptor"),
    ],
)
def test_a_class_whose_new_is_a_descriptor_that_records_a_callable_defined_in_c_as_wrapped_is_spelled_by_what_getattr_binds_it_to_less_its_first_parameter_whatever_its_type_defines_besides_get(
    giver: type[Giver],
) -> None:
    def build(receiver: float, rate: int) -> None: ...

    held = giver(build)
    held.__wrapped__ = object.__new__
    cls = class_whose_new_is(held)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert surface_form(subject) == "(rate: int) -> None"
        assert named_classes(subject) == {int}
        assert surface_form(functools.partial(subject)) == "(rate: int) -> None"


@pytest.mark.parametrize(
    "hold",
    [
        pytest.param(
            lambda build: recording_object_init(DeletingCallableGiver(build)),
            id="get-delete-descriptor",
        ),
        pytest.param(
            lambda build: recording_object_init(SettingCallableGiver(build)),
            id="get-set-descriptor",
        ),
        pytest.param(lambda build: recording_object_init(DefCall()), id="object-defining-no-get"),
        pytest.param(
            lambda build: functools.update_wrapper(functools.partial(build), object.__init__),
            id="partial",
        ),
        pytest.param(
            lambda build: recording_object_init(DeletingGiver(build)),
            id="non-callable-get-delete-descriptor",
        ),
        pytest.param(
            lambda build: recording_object_init(SettingGiver(build)),
            id="non-callable-get-set-descriptor",
        ),
        pytest.param(
            lambda build: recording_object_init(types.SimpleNamespace()),
            id="non-callable-object-defining-no-get",
        ),
    ],
)
@pytest.mark.parametrize(
    ("construct", "constructor"),
    [
        pytest.param(class_whose_init_is, "Built.__init__", id="init"),
        pytest.param(class_whose_metaclass_call_is, "Calling.__call__", id="metaclass-call"),
    ],
)
def test_a_class_whose_constructor_is_a_descriptor_whose_type_defines_set_or_delete_a_partial_or_an_object_defining_no_get_that_records_a_callable_defined_in_c_as_wrapped_raises_a_type_error_naming_it_that_constructor_and_that_callable(
    construct: Callable[[object], type],
    constructor: str,
    hold: Callable[[Callable[..., object]], object],
) -> None:
    def build(receiver: float, rate: int) -> None: ...

    cls = construct(hold(build))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*"
            r"\bobject\.__init__, defined in C\b"
            r".*\bskips the constructor as defined in C\b.*\breads the constructor as it binds it\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("wrapped", "qualified_name"),
    [
        pytest.param(object().__init__, "object.__init__", id="method-wrapper"),
        pytest.param(dict.__dict__["fromkeys"], "dict.fromkeys", id="classmethod-descriptor"),
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
def test_a_class_whose_constructor_wraps_a_method_wrapper_or_a_classmethod_descriptor_raises_a_type_error_naming_it_that_constructor_and_that_callable(
    construct: Callable[[object], type],
    constructor: str,
    wrapped: object,
    qualified_name: str,
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    cls = construct(functools.wraps(wrapped)(build))

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(constructor)}\b.*"
            rf"\b{re.escape(qualified_name)}, defined in C\b"
            r".*\bskips the constructor as defined in C\b.*\breads the constructor as it binds it\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


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
