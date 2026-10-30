# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for a class whose __new__, __init__ or metaclass __call__ inspect skips on every minor, as None or as defined in C, for what inspect reads in that constructor's place, and for the TypeError raised where it reads that differently by minor or cannot read it, one per test.

The classes above the first test are defined at module level, where their qualified
names carry no '<locals>' and a parametrize decorator can reach them.
"""

import decimal
import fractions
import functools
import re
import sys
import types
from typing import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    Giver,
    class_whose_metaclass_call_is,
    with_a_string_signature,
)


class Ledger(dict):
    """A class that inherits its constructor from dict, which CPython defines in C."""


class ReinitialisedLedger(dict):
    """A class over dict that holds object's own __init__, as a class defined in Python can."""

    __init__ = object.__init__


class Rated:
    """A class whose __init__ is defined with def, for a subclass to shadow."""

    def __init__(self, rate: int) -> None: ...


_INSPECT_SKIPS_AS_DEFINED_IN_C = (
    pytest.param("__new__", object.__new__, id="builtin-as-new"),
    pytest.param("__new__", staticmethod(object.__new__), id="staticmethod-of-a-builtin-as-new"),
    pytest.param("__new__", object().__init__, id="method-wrapper-as-new"),
    pytest.param(
        "__new__", staticmethod(object().__init__), id="staticmethod-of-a-method-wrapper-as-new"
    ),
    pytest.param(
        "__new__",
        staticmethod(dict.__dict__["fromkeys"]),
        id="staticmethod-of-a-classmethod-descriptor-as-new",
    ),
    pytest.param("__init__", object.__init__, id="slot-wrapper-as-init"),
    pytest.param("__init__", object().__init__, id="method-wrapper-as-init"),
    pytest.param("__init__", dict.__dict__["fromkeys"], id="classmethod-descriptor-as-init"),
)


@pytest.mark.parametrize(
    "new",
    [
        pytest.param(object.__new__, id="builtin"),
        pytest.param(staticmethod(object.__new__), id="staticmethod"),
        pytest.param(object().__init__, id="method-wrapper"),
        pytest.param(staticmethod(object().__init__), id="staticmethod-of-a-method-wrapper"),
        pytest.param(
            staticmethod(dict.__dict__["fromkeys"]),
            id="staticmethod-of-a-classmethod-descriptor",
        ),
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
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_skipped_constructors\.Ledger\b.*\bbuiltins\.dict\b",
            id="Ledger",
        ),
        pytest.param(
            ReinitialisedLedger,
            r"\btests\.unit\.surface_forms_helper\.test_surface_form_skipped_constructors\.ReinitialisedLedger\b.*\bbuiltins\.dict\b",
            id="ReinitialisedLedger",
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

    class RenewedByAStaticmethod:
        __new__ = staticmethod(object.__new__)

    class RenewedByABuiltin:
        __new__ = object.__new__

    class ReinitialisedByASlotWrapper:
        __init__ = object.__init__

    assert surface_form(object) == "()"
    assert surface_form(Plain) == "()"
    assert surface_form(RenewedByAStaticmethod) == "()"
    assert surface_form(RenewedByABuiltin) == "()"
    assert surface_form(ReinitialisedByASlotWrapper) == "()"


@pytest.mark.parametrize(
    "held",
    [
        pytest.param(None, id="none"),
        pytest.param(Giver(None), id="descriptor-giving-none"),
        pytest.param(staticmethod(None), id="staticmethod-of-none"),
    ],
)
def test_a_class_whose_new_or_metaclass_call_inspect_binds_to_none_is_spelled_by_the_init_inspect_reads_in_its_place(
    held: object,
) -> None:
    class Initialised:
        __new__ = held

        def __init__(self, rate: int) -> None: ...

    class Reinitialised(class_whose_metaclass_call_is(held)):
        def __init__(self, rate: int) -> None: ...

    for cls in (Initialised, Reinitialised):
        assert surface_form(cls) == "(rate: int) -> None"
        assert named_classes(cls) == {int}


@pytest.mark.parametrize(
    ("hold", "refused"),
    [
        pytest.param(functools.partial, r"\bfunctools\.partial\b", id="partial"),
        pytest.param(
            with_a_string_signature,
            r"'\(receiver, rate\)', a builtins\.str\b",
            id="string-signature",
        ),
        pytest.param(
            functools.wraps(object.__init__),
            r"\bobject\.__init__\b",
            id="wrapper-of-a-callable-defined-in-c",
        ),
    ],
)
@pytest.mark.parametrize(
    "held",
    [
        pytest.param(None, id="none"),
        pytest.param(Giver(None), id="descriptor-giving-none"),
        pytest.param(staticmethod(None), id="staticmethod-of-none"),
    ],
)
def test_a_class_whose_new_or_metaclass_call_inspect_binds_to_none_raises_the_type_error_naming_the_init_inspect_reads_in_its_place(
    held: object, hold: Callable[[Callable[..., object]], object], refused: str
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    init = hold(build)

    class Initialised:
        __new__ = held
        __init__ = init

    class Reinitialised(class_whose_metaclass_call_is(held)):
        __init__ = init

    for cls in (Initialised, Reinitialised):

        class Inheriting(cls):
            pass

        for subject in (cls, Inheriting):
            naming_it = rf"\.{subject.__name__}\b.*\.{cls.__name__}\.__init__\b.*{refused}"
            with pytest.raises(TypeError, match=naming_it):
                surface_form(subject)
            with pytest.raises(TypeError, match=naming_it):
                named_classes(subject)
            with pytest.raises(TypeError, match=naming_it):
                surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("hold", "refused"),
    [
        pytest.param(
            with_a_string_signature,
            r"'\(receiver, rate\)', a builtins\.str\b",
            id="string-signature",
        ),
        pytest.param(
            functools.wraps(object.__new__),
            r"\bobject\.__new__\b",
            id="wrapper-of-a-callable-defined-in-c",
        ),
    ],
)
@pytest.mark.parametrize(
    "held",
    [
        pytest.param(None, id="none"),
        pytest.param(Giver(None), id="descriptor-giving-none"),
        pytest.param(staticmethod(None), id="staticmethod-of-none"),
    ],
)
def test_a_class_whose_init_inspect_binds_to_none_raises_the_type_error_naming_the_new_inspect_reads_in_its_place(
    held: object, hold: Callable[[Callable[..., object]], object], refused: str
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    class Created:
        __new__ = hold(build)

    class Reinitialised(Created):
        __init__ = held

    naming_it = rf"\.Reinitialised\b.*\.Created\.__new__\b.*{refused}"
    with pytest.raises(TypeError, match=naming_it):
        surface_form(Reinitialised)
    with pytest.raises(TypeError, match=naming_it):
        named_classes(Reinitialised)
    with pytest.raises(TypeError, match=naming_it):
        surface_form(functools.partial(Reinitialised))


@pytest.mark.parametrize(
    ("base", "naming_base"),
    [
        pytest.param(int, r"\bbuiltins\.int\b", id="int"),
        pytest.param(frozenset, r"\bbuiltins\.frozenset\b", id="frozenset"),
        pytest.param(property, r"\bbuiltins\.property\b", id="property"),
    ],
)
@pytest.mark.parametrize(
    "name",
    [pytest.param("__new__", id="new"), pytest.param("__init__", id="init")],
)
@pytest.mark.parametrize(
    "held",
    [
        pytest.param(None, id="none"),
        pytest.param(Giver(None), id="descriptor-giving-none"),
        pytest.param(staticmethod(None), id="staticmethod-of-none"),
    ],
)
def test_a_class_whose_only_constructor_inspect_binds_to_none_over_a_class_defined_in_c_raises_the_type_error_naming_that_class(
    held: object, name: str, base: type, naming_base: str
) -> None:
    skipping = type("Skipping", (base,), {name: held})

    class Inheriting(skipping):
        pass

    for subject in (skipping, Inheriting):
        naming_it = rf"\.{subject.__name__}\b.*{naming_base}.*\bdefined in C\b.*\btext signature\b"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    "held",
    [
        pytest.param(object().__init__, id="method-wrapper"),
        pytest.param(dict.__dict__["fromkeys"], id="classmethod-descriptor"),
    ],
)
def test_a_class_whose_metaclass_call_new_or_init_is_a_method_wrapper_or_a_classmethod_descriptor_is_spelled_by_the_constructor_inspect_reads_in_its_place(
    held: object,
) -> None:
    class Reinitialised(class_whose_metaclass_call_is(held)):
        def __init__(self, share: "fractions.Fraction") -> None: ...

    class Made:
        def __new__(cls, share: "fractions.Fraction") -> object: ...

        __init__ = held

    class Initialised:
        __new__ = staticmethod(held)

        def __init__(self, share: "fractions.Fraction") -> None: ...

    for cls, form, classes in (
        (Reinitialised, "(share: fractions.Fraction) -> None", {fractions.Fraction}),
        (Made, "(share: fractions.Fraction) -> object", {fractions.Fraction, object}),
        (Initialised, "(share: fractions.Fraction) -> None", {fractions.Fraction}),
    ):
        assert surface_form(cls) == form
        assert named_classes(cls) == classes


@pytest.mark.parametrize(
    "held",
    [
        pytest.param(object().__init__, id="method-wrapper"),
        pytest.param(dict.__dict__["fromkeys"], id="classmethod-descriptor"),
    ],
)
def test_a_class_whose_metaclass_call_is_a_method_wrapper_or_a_classmethod_descriptor_raises_the_type_error_naming_the_init_inspect_reads_in_its_place(
    held: object,
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    class Reinitialised(class_whose_metaclass_call_is(held)):
        __init__ = functools.partial(build)

    class Inheriting(Reinitialised):
        pass

    for subject in (Reinitialised, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.Reinitialised\.__init__\b.*\bfunctools\.partial\b"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("base", "naming_base"),
    [
        pytest.param(int, r"\bbuiltins\.int\b", id="int"),
        pytest.param(frozenset, r"\bbuiltins\.frozenset\b", id="frozenset"),
        pytest.param(property, r"\bbuiltins\.property\b", id="property"),
    ],
)
@pytest.mark.parametrize(
    ("held", "name"),
    [
        pytest.param(object().__init__, "__new__", id="method-wrapper-as-new"),
        pytest.param(object().__init__, "__init__", id="method-wrapper-as-init"),
        pytest.param(dict.__dict__["fromkeys"], "__init__", id="classmethod-descriptor-as-init"),
        pytest.param(
            staticmethod(dict.__dict__["fromkeys"]),
            "__new__",
            id="staticmethod-of-a-classmethod-descriptor-as-new",
        ),
    ],
)
def test_a_class_whose_only_constructor_is_a_method_wrapper_or_a_classmethod_descriptor_over_a_class_defined_in_c_raises_the_type_error_naming_that_class(
    held: object, name: str, base: type, naming_base: str
) -> None:
    skipping = type("Skipping", (base,), {name: held})

    class Inheriting(skipping):
        pass

    for subject in (skipping, Inheriting):
        naming_it = rf"\.{subject.__name__}\b.*{naming_base}.*\bdefined in C\b.*\btext signature\b"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(("name", "held"), _INSPECT_SKIPS_AS_DEFINED_IN_C)
def test_a_class_whose_new_or_init_inspect_skips_as_defined_in_c_is_spelled_by_the_constructor_inspect_reads_in_its_place_which_a_base_holds(
    name: str, held: object
) -> None:
    class Initialised:
        def __init__(self, share: "fractions.Fraction") -> None: ...

    class Created:
        def __new__(cls, share: "fractions.Fraction") -> object: ...

    base, form, classes = {
        "__new__": (Initialised, "(share: fractions.Fraction) -> None", {fractions.Fraction}),
        "__init__": (
            Created,
            "(share: fractions.Fraction) -> object",
            {fractions.Fraction, object},
        ),
    }[name]
    skipping = type("Skipping", (base,), {name: held})

    assert surface_form(skipping) == form
    assert named_classes(skipping) == classes


@pytest.mark.parametrize(("name", "held"), _INSPECT_SKIPS_AS_DEFINED_IN_C)
def test_a_class_whose_new_or_init_inspect_skips_as_defined_in_c_raises_the_type_error_naming_the_constructor_inspect_reads_in_its_place_which_a_base_holds(
    name: str, held: object
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    def make(receiver: object, rate: int) -> None: ...

    class Built:
        __init__ = functools.partial(build)

    class Created:
        __new__ = with_a_string_signature(make)

    base, refused = {
        "__new__": (Built, r"\.Built\.__init__\b.*\bfunctools\.partial\b"),
        "__init__": (Created, r"\.Created\.__new__\b.*'\(receiver, rate\)', a builtins\.str\b"),
    }[name]
    skipping = type("Skipping", (base,), {name: held})

    class Inheriting(skipping):
        pass

    for subject in (skipping, Inheriting):
        naming_it = rf"\.{subject.__name__}\b.*{refused}"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


@pytest.mark.parametrize(
    ("bases", "namespace", "skipped"),
    [
        pytest.param((), {"__init__": None}, "Skipping.__init__", id="init-none"),
        pytest.param(
            (), {"__init__": Giver(None)}, "Skipping.__init__", id="init-descriptor-giving-none"
        ),
        pytest.param(
            (),
            {"__init__": staticmethod(None)},
            "Skipping.__init__",
            id="init-staticmethod-of-none",
        ),
        pytest.param((), {"__new__": None}, "Skipping.__new__", id="new-none"),
        pytest.param(
            (), {"__new__": Giver(None)}, "Skipping.__new__", id="new-descriptor-giving-none"
        ),
        pytest.param(
            (), {"__new__": staticmethod(None)}, "Skipping.__new__", id="new-staticmethod-of-none"
        ),
        pytest.param(
            (), {"__new__": None, "__init__": None}, "Skipping.__new__", id="new-and-init-none"
        ),
        pytest.param(
            (),
            {"__new__": staticmethod(object.__new__), "__init__": None},
            "Skipping.__init__",
            id="init-none-beside-object-new",
        ),
        pytest.param(
            (),
            {"__new__": None, "__init__": object.__init__},
            "Skipping.__new__",
            id="new-none-beside-object-init",
        ),
        pytest.param(
            (Rated,),
            {"__init__": None},
            "Skipping.__init__",
            id="init-none-over-a-base-init-defined-with-def",
        ),
        pytest.param(
            (Rated,),
            {"__new__": object.__new__, "__init__": None},
            "Skipping.__init__",
            id="init-none-beside-a-builtin-new-over-a-base-init-defined-with-def",
        ),
        pytest.param(
            (class_whose_metaclass_call_is(Giver(None)),),
            {"__init__": None},
            "Skipping.__init__",
            id="init-none-under-a-metaclass-call-giving-none",
        ),
        pytest.param(
            (), {"__init__": object().__init__}, "Skipping.__init__", id="init-method-wrapper"
        ),
        pytest.param(
            (),
            {"__init__": dict.__dict__["fromkeys"]},
            "Skipping.__init__",
            id="init-classmethod-descriptor",
        ),
        pytest.param(
            (), {"__new__": object().__init__}, "Skipping.__new__", id="new-method-wrapper"
        ),
        pytest.param(
            (),
            {"__new__": staticmethod(object().__init__)},
            "Skipping.__new__",
            id="new-staticmethod-of-a-method-wrapper",
        ),
        pytest.param(
            (),
            {"__new__": staticmethod(dict.__dict__["fromkeys"])},
            "Skipping.__new__",
            id="new-staticmethod-of-a-classmethod-descriptor",
        ),
    ],
)
def test_a_class_of_which_inspect_reads_no_constructor_raises_a_type_error_naming_it_and_the_constructor_inspect_skips(
    bases: tuple[type, ...], namespace: dict[str, object], skipped: str
) -> None:
    skipping = type("Skipping", bases, namespace)

    class Inheriting(skipping):
        pass

    for subject in (skipping, Inheriting):
        naming_it = (
            rf"\.{subject.__name__}\b.*\.{re.escape(skipped)}\b.*\binspect skips\b"
            r".*\bValueError\b.*\bTypeError\b.*\bclassmethod_descriptor __init__"
        )
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


def test_a_class_that_object_constructs_under_a_docstring_in_text_signature_form_raises_a_type_error_naming_it_the_class_holding_that_docstring_and_its_text_signature() -> None:
    class Plain:
        """Plain(rate)
        --

        A class object constructs, whose docstring is in text-signature form once dedented."""

    class RenewedByAStaticmethod:
        """RenewedByAStaticmethod(rate)
        --

        A class object constructs, whose docstring is in text-signature form once dedented."""

        __new__ = staticmethod(object.__new__)

    class RenewedByABuiltin:
        """RenewedByABuiltin(rate)
        --

        A class object constructs, whose docstring is in text-signature form once dedented."""

        __new__ = object.__new__

    class ReinitialisedByASlotWrapper:
        """ReinitialisedByASlotWrapper(rate)
        --

        A class object constructs, whose docstring is in text-signature form once dedented."""

        __init__ = object.__init__

    for cls in (Plain, RenewedByAStaticmethod, RenewedByABuiltin, ReinitialisedByASlotWrapper):

        class Inheriting(cls):
            pass

        for subject in (cls, Inheriting):
            naming_it = rf"\.{subject.__name__}\b.*\bdocstring of .*\.{cls.__name__}\b.*'\(rate\)'"
            with pytest.raises(TypeError, match=naming_it):
                surface_form(subject)
            with pytest.raises(TypeError, match=naming_it):
                named_classes(subject)
            with pytest.raises(TypeError, match=naming_it):
                surface_form(functools.partial(subject))


def test_a_class_that_object_constructs_raises_a_type_error_naming_the_first_class_in_its_mro_whose_docstring_is_in_text_signature_form_once_dedented_as_python_3_13_compiles_it_however_it_is_indented() -> None:
    class Flush:
        """Flush(rate)
--

A docstring set flush-left, in text-signature form on every minor."""

    class Bare:
        """Bare(rate)
        --

        """

    class Redocumented(Flush):
        """Redocumented(share)
        --

        A docstring in text-signature form once dedented, over a base's set flush-left."""

    class Tabbed:
        """Tabbed(rate)\n\t--\n\n\tA docstring whose lines after the first a tab indents."""

    class Undented:
        """Undented(rate)
        --

        A docstring whose closing line holds only spaces, fewer than the lines before it.
    """

    class Assigned:
        __doc__ = """Assigned(rate)
        --

        A docstring the class body assigns to __doc__, which no compiler dedents."""

    Typed = type("Typed", (), {"__doc__": "Typed(rate)\n    --\n\n    A docstring type() gives."})

    for subject, naming_it in (
        (Flush, r"\.Flush\b.*\bdocstring of .*\.Flush\b.*'\(rate\)'"),
        (Bare, r"\.Bare\b.*\bdocstring of .*\.Bare\b.*'\(rate\)'"),
        (Redocumented, r"\.Redocumented\b.*\bdocstring of .*\.Redocumented\b.*'\(share\)'"),
        (Tabbed, r"\.Tabbed\b.*\bdocstring of .*\.Tabbed\b.*'\(rate\)'"),
        (Undented, r"\.Undented\b.*\bdocstring of .*\.Undented\b.*'\(rate\)'"),
        (Assigned, r"\.Assigned\b.*\bdocstring of .*\.Assigned\b.*'\(rate\)'"),
        (Typed, r"\.Typed\b.*\bdocstring of .*\.Typed\b.*'\(rate\)'"),
    ):
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)


def test_a_class_that_object_constructs_under_a_docstring_not_in_text_signature_form_once_dedented_as_python_3_13_compiles_it_is_spelled_with_no_parameters() -> None:
    class Opened:
        """
        Opened(rate)
        --

        A docstring whose signature follows a blank first line, which no minor reads as one."""

    class Misnamed:
        """Ledger(rate)
        --

        A docstring in text-signature form for another class's name."""

    for cls in (Opened, Misnamed):
        assert surface_form(cls) == "()"
        assert named_classes(cls) == set()


def test_a_class_that_object_constructs_created_under_a_docstring_in_text_signature_form_set_flush_left_raises_a_type_error_naming_the_text_signature_it_keeps_whatever_its_doc_later_holds() -> None:
    class Reassigned:
        """Reassigned(rate)
--

A docstring set flush-left, in text-signature form on every minor, until reassigned."""

    Reassigned.__doc__ = "A docstring that gives no text signature."

    class Inheriting(Reassigned):
        pass

    for subject in (Reassigned, Inheriting):
        naming_it = rf"\.{subject.__name__}\b.*\.Reassigned's __text_signature__ gives, '\(rate\)'"
        with pytest.raises(TypeError, match=naming_it):
            surface_form(subject)
        with pytest.raises(TypeError, match=naming_it):
            named_classes(subject)
        with pytest.raises(TypeError, match=naming_it):
            surface_form(functools.partial(subject))


def test_a_class_that_object_constructs_created_under_a_docstring_in_text_signature_form_that_a_class_body_indents_raises_that_type_error_from_python_3_13_and_is_spelled_with_no_parameters_on_3_11_and_3_12_once_its_doc_is_reassigned() -> None:
    class Indented:
        """Indented(rate)
        --

        A docstring in text-signature form once dedented, until reassigned."""

    Indented.__doc__ = "A docstring that gives no text signature."

    class Inheriting(Indented):
        pass

    for subject in (Indented, Inheriting):
        if sys.version_info < (3, 13):
            assert surface_form(subject) == "()"
            assert named_classes(subject) == set()
        else:
            naming_it = rf"\.{subject.__name__}\b.*\.Indented's __text_signature__ gives, '\(rate\)'"
            with pytest.raises(TypeError, match=naming_it):
                surface_form(subject)
            with pytest.raises(TypeError, match=naming_it):
                named_classes(subject)
