# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for a functools.partial whose type takes __get__ from a class other than functools.partial, wherever inspect reads or binds it, one per test.

The classes and functions above the first test are defined at module level, where their
qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import functools
import inspect
import re
import types
from typing import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    GetMixin,
    GetterPartial,
    PartialFirstGetterPartial,
    SettableGetterPartial,
    class_whose_init_is,
    class_whose_metaclass_call_is,
)


def _settled(self: object, share: float, rate: int) -> None: ...


def _metered(self: object, share: float) -> None: ...


class DeletableGetterPartial(GetterPartial):
    """A GetterPartial whose type also defines __delete__, which inspect before Python 3.13 ignores in counting it a method descriptor."""

    def __delete__(self, instance: object) -> None: ...


class MixedInGetterPartial(GetMixin, functools.partial):
    """A functools.partial whose type takes __get__ from a base before functools.partial in its MRO."""


class GivingGetterPartial:
    """A descriptor, no functools.partial, whose __get__ gives a GetterPartial."""

    def __get__(self, instance: object, owner: type | None = None) -> GetterPartial:
        return GetterPartial(_settled, rate=1)


class GetterPartialNew:
    """A class whose __new__ is a GetterPartial."""

    __new__ = GetterPartial(_settled, rate=1)


class GivingGetterPartialInit:
    """A class whose __init__ is a GivingGetterPartial."""

    __init__ = GivingGetterPartial()


class GivingGetterPartialCall:
    """A class whose __call__ is a GivingGetterPartial."""

    __call__ = GivingGetterPartial()


def _with_a_signature_of_none(partial: GetterPartial) -> GetterPartial:
    partial.__signature__ = None
    return partial


def _with_a_text_signature(partial: GetterPartial) -> GetterPartial:
    partial.__text_signature__ = "(rate)"
    return partial


def _with_an_instance_attribute(partial: GetterPartial) -> GetterPartial:
    partial.note = "an attribute, so that a functools.partial of it keeps it as its func"
    return partial


def _with_metered_as_wrapped(partial: GetterPartial) -> GetterPartial:
    functools.update_wrapper(partial, _metered)
    return partial


class WrappingGetterPartialNew:
    """A class whose __new__ is a GetterPartial that records _metered as __wrapped__."""

    __new__ = _with_metered_as_wrapped(GetterPartial(_settled, rate=1))


def _partial_of_an_object_whose_call_is(partial: object) -> object:
    class CallingObject:
        __call__ = partial

    return functools.partial(CallingObject())


_NAMED_ITSELF = "^{partial} is a {kind}, "
_NAMED_AS_WHAT_IT_WRAPS = r"^.*\._metered is a {kind}, "
_NAMED_AS_A_LINK = " wraps {partial}, a {kind}, "


@pytest.mark.parametrize(
    ("build", "read_in", "naming"),
    [
        pytest.param(
            lambda: GetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="getter-partial",
        ),
        pytest.param(
            lambda: DeletableGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="deletable",
        ),
        pytest.param(
            lambda: MixedInGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="mixed-in",
        ),
        pytest.param(
            lambda: PartialFirstGetterPartial(_settled, rate=1),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="partial-first",
        ),
        pytest.param(
            lambda: _with_a_signature_of_none(GetterPartial(_settled, rate=1)),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="signature-of-none",
        ),
        pytest.param(
            lambda: _with_a_text_signature(GetterPartial(_settled, rate=1)),
            lambda subject: subject,
            _NAMED_ITSELF,
            id="text-signature",
        ),
        pytest.param(
            lambda: _with_a_signature_of_none(
                _with_metered_as_wrapped(GetterPartial(_settled, rate=1))
            ),
            lambda subject: subject,
            _NAMED_AS_WHAT_IT_WRAPS,
            id="wrapped-with-a-signature-of-none",
        ),
        pytest.param(
            lambda: functools.wraps(GetterPartial(_settled, rate=1))(lambda share: None),
            lambda subject: subject.__wrapped__,
            _NAMED_AS_A_LINK,
            id="functools-wraps",
        ),
        pytest.param(
            lambda: types.MethodType(GetterPartial(_settled, rate=1), object()),
            lambda subject: subject.__func__,
            _NAMED_AS_A_LINK,
            id="bound-method",
        ),
        pytest.param(
            lambda: functools.partial(_with_an_instance_attribute(GetterPartial(_settled, rate=1))),
            lambda subject: subject.func,
            _NAMED_AS_A_LINK,
            id="partial-of-it",
        ),
        pytest.param(
            lambda: GetterPartialNew,
            lambda subject: subject.__new__,
            r"\.GetterPartialNew is constructed through .*\.GetterPartialNew\.__new__, "
            "which inspect reads as {partial}, a {kind}, ",
            id="new",
        ),
        pytest.param(
            lambda: GivingGetterPartialInit,
            lambda subject: subject.__init__,
            r"\.GivingGetterPartialInit is constructed through .*\.GivingGetterPartialInit\.__init__, "
            "which inspect reads as {partial}, a {kind}, ",
            id="init-giving-it",
        ),
        pytest.param(
            lambda: functools.partial(GivingGetterPartialCall()),
            lambda subject: subject.func.__call__,
            _NAMED_AS_A_LINK,
            id="call-giving-it",
        ),
    ],
)
def test_a_partial_whose_type_takes_get_from_another_class_and_defines_no_set_raises_a_type_error_naming_it_and_its_type_wherever_inspect_reads_it(
    build: Callable[[], object], read_in: Callable[[object], object], naming: str
) -> None:
    subject = build()
    partial = read_in(subject)
    naming_it_and_its_type = naming.format(
        partial=re.escape(repr(partial)), kind=rf".*\.{type(partial).__qualname__}"
    ) + r"a functools\.partial whose type takes __get__ .*\b3\.11 and 3\.12\b.*\bfrom 3\.13\b"
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        surface_form(subject)
    with pytest.raises(TypeError, match=naming_it_and_its_type):
        named_classes(subject)


def test_a_partial_whose_type_takes_get_from_another_class_but_defines_set_or_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it() -> None:
    signed = GetterPartial(_settled, rate=1)
    signed.__signature__ = inspect.Signature(
        [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float)]
    )

    assert (
        surface_form(SettableGetterPartial(_settled, rate=1))
        == "(self: object, share: float, *, rate: int = 1) -> None"
    )
    assert surface_form(signed) == "(share: float)"


def test_a_plain_partial_of_a_partial_whose_type_takes_get_from_another_class_and_that_holds_no_instance_dict_is_spelled_by_the_func_and_arguments_it_takes_as_its_own() -> None:
    plain = functools.partial(GetterPartial(_settled, rate=1))

    assert (plain.func, plain.args, plain.keywords) == (_settled, (), {"rate": 1})
    assert surface_form(plain) == "(self: object, share: float, *, rate: int = 1) -> None"


@pytest.mark.parametrize(
    ("build", "form"),
    [
        pytest.param(
            lambda: _with_metered_as_wrapped(GetterPartial(_settled, rate=1)),
            "(self: object, share: float) -> None",
            id="itself",
        ),
        pytest.param(
            lambda: functools.wraps(_with_metered_as_wrapped(GetterPartial(_settled, rate=1)))(
                lambda share: None
            ),
            "(self: object, share: float) -> None",
            id="functools-wraps",
        ),
        pytest.param(
            lambda: types.MethodType(
                _with_metered_as_wrapped(GetterPartial(_settled, rate=1)), object()
            ),
            "(share: float) -> None",
            id="bound-method",
        ),
        pytest.param(
            lambda: functools.partial(_with_metered_as_wrapped(GetterPartial(_settled, rate=1))),
            "(self: object, share: float) -> None",
            id="partial-of-it",
        ),
        pytest.param(lambda: WrappingGetterPartialNew, "(share: float) -> None", id="new"),
    ],
)
def test_a_partial_whose_type_takes_get_from_another_class_but_carries_wrapped_is_spelled_by_the_signature_of_what_it_wraps(
    build: Callable[[], object], form: str
) -> None:
    assert surface_form(build()) == form


@pytest.mark.parametrize("kind", [GetterPartial, SettableGetterPartial])
@pytest.mark.parametrize(
    ("build", "site"),
    [
        pytest.param(
            class_whose_init_is,
            r"\.Built\b.* is constructed through .*\.Built\.__init__, ",
            id="init",
        ),
        pytest.param(
            class_whose_metaclass_call_is,
            r"\.Called\b.* is constructed through .*\.Calling\.__call__, ",
            id="metaclass-call",
        ),
        pytest.param(
            _partial_of_an_object_whose_call_is,
            r" is read through .*\.CallingObject\.__call__, ",
            id="object-call",
        ),
    ],
)
def test_a_class_or_call_bound_through_a_partial_whose_type_takes_get_from_another_class_raises_a_type_error_naming_that_type_instead_of_the_binding_of_a_partial(
    build: Callable[[object], object], site: str, kind: type
) -> None:
    def settle(self: object, rate: int, scale: float = 1.0) -> None: ...

    naming_that_type = (
        rf"a .*\.{kind.__qualname__}, a functools\.partial whose type takes __get__ from a "
        r"class other than functools\.partial, a binding no rule"
    )
    with pytest.raises(TypeError, match=site + naming_that_type):
        surface_form(build(kind(settle, scale=2.0)))
