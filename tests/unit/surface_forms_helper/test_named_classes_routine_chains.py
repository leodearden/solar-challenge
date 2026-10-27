# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the callable that spells a routine's annotations when it wraps or binds another callable or carries a signature over one, and the errors raised when none is known, one per test.

_typed is defined at module level, where its lambda carries this module's globals.
"""

import datetime
import decimal
import enum
import fractions
import functools
import inspect
import operator
import pathlib
import types
from typing import TYPE_CHECKING, Callable

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import (
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    imported_module,
)

if TYPE_CHECKING:
    from decimal import Decimal  # noqa: F401


def _typed(function: Callable[..., object], *receivers: str, annotation: object = "Decimal") -> Callable[..., object]:
    """A wrapper of *function*, as functools.wraps records one, given a signature here: *receivers*, then share annotated with *annotation*, by default the string "Decimal", which this module binds only for type checking."""
    wrapper = functools.wraps(function)(lambda *args: function(*args))
    wrapper.__signature__ = inspect.Signature(
        [
            *(inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD) for name in receivers),
            inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation),
        ]
    )
    return wrapper


_RELAYING_SOURCE = (
    "import inspect\n"
    "from fractions import Fraction as Decimal\n"
    "from functools import wraps\n"
    "\n"
    "def relay(function):\n"
    "    return wraps(function)(lambda *args: function(*args))\n"
    "\n"
    "def resign(function, dropping=0):\n"
    "    signature = inspect.signature(function)\n"
    "    resigned = relay(function)\n"
    "    parameters = list(signature.parameters.values())[dropping:]\n"
    "    resigned.__signature__ = signature.replace(parameters=parameters)\n"
    "    return resigned\n"
)


class Band(enum.Enum):
    """An Enum with a member."""

    PEAK = "peak"


class MemberlessBand(enum.Enum):
    """An Enum with no member."""


class BandFlags(enum.IntFlag):
    """An Enum of flags."""

    PEAK = 1


_ENUM_KINDS = (Band, MemberlessBand, BandFlags)


def _typed_partial(function: Callable[..., object], annotation: object) -> Callable[..., object]:
    """A functools.partial of *function* given the signature _typed gives a wrapper of it, share annotated with *annotation*."""
    partial = functools.partial(function)
    partial.__signature__ = _typed(function, annotation=annotation).__signature__
    return partial


def _signed_links_over(enum_class: type[enum.Enum], annotation: object) -> dict[str, Callable[..., object]]:
    """One link of each shape that carries over *enum_class* a signature annotating share with *annotation*, by the shape's name: a functools.partial, a wrapper as functools.wraps records one, a bound method of one, a functools.partial of a callable object whose __call__ is one, and a class whose __init__, whose __new__, or whose metaclass's __call__ is one."""

    class Caller:
        __call__ = _typed(enum_class, "receiver", annotation=annotation)

    return {
        "partial": _typed_partial(enum_class, annotation),
        "functools-wraps-wrapper": _typed(enum_class, annotation=annotation),
        "bound-method": types.MethodType(_typed(enum_class, "receiver", annotation=annotation), object()),
        "callable-object": functools.partial(Caller()),
        "init": class_whose_init_is(_typed(enum_class, "receiver", annotation=annotation)),
        "new": class_whose_new_is(_typed(enum_class, "receiver", annotation=annotation)),
        "metaclass-call": class_whose_metaclass_call_is(_typed(enum_class, "receiver", annotation=annotation)),
    }


_LINK_SHAPES = tuple(_signed_links_over(Band, int))


def test_a_partial_names_the_classes_the_callable_it_wraps_names_each_read_where_that_callable_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    halving = imported_module(
        tmp_path,
        monkeypatch,
        "halving",
        "from fractions import Fraction\n"
        "from functools import partial\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, ratio: 'Fraction') -> None: ...\n"
        "\n"
        "def settle(share: 'Fraction', rate: int) -> None: ...\n"
        "\n"
        "half = partial(settle, rate=1)\n",
    )

    class Submeter(halving.Meter):
        pass

    assert named_classes(halving.half) == {fractions.Fraction, int}
    assert named_classes(functools.partial(Submeter)) == {fractions.Fraction}


def test_a_routine_that_wraps_another_callable_names_the_classes_that_callable_names_each_read_where_that_callable_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "from functools import partial, wraps\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n"
        "\n"
        "half = partial(settle, rate=1)\n"
        "\n"
        "def logged(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "    return wrapper\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "\n"
        "from metering import Meter, half, logged\n"
        "\n"
        "class Submeter(Meter):\n"
        "    pass\n"
        "\n"
        "submeter = logged(Submeter)\n"
        "halved = logged(half)\n"
        "\n"
        "@logged\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    assert named_classes(submetering.submeter) == {fractions.Fraction}
    assert named_classes(submetering.halved) == {fractions.Fraction, int}
    assert named_classes(submetering.audit) == {decimal.Decimal}


def test_a_partial_that_wraps_another_callable_as_functools_wraps_records_one_names_the_classes_that_callable_names_read_where_that_callable_is_spelled_not_where_its_func_is(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    billing = imported_module(
        tmp_path,
        monkeypatch,
        "billing",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    reconciling = imported_module(
        tmp_path,
        monkeypatch,
        "reconciling",
        "from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    audited = functools.update_wrapper(functools.partial(billing.settle, rate=1), reconciling.audit)

    assert named_classes(audited) == {decimal.Decimal}


def test_a_partial_that_wraps_another_callable_as_functools_wraps_records_one_but_carries_a_signature_of_none_names_the_classes_its_func_names_read_where_its_func_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    billing = imported_module(
        tmp_path,
        monkeypatch,
        "billing",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    reconciling = imported_module(
        tmp_path,
        monkeypatch,
        "reconciling",
        "from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    audited = functools.update_wrapper(functools.partial(billing.settle, rate=1), reconciling.audit)
    audited.__signature__ = None

    assert named_classes(audited) == {fractions.Fraction, int}


def test_a_routine_that_wraps_another_callable_names_the_classes_that_callable_names_read_where_that_callable_is_spelled_though_the_routine_carries_a_signature(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    imported_module(
        tmp_path,
        monkeypatch,
        "decorating",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "def without_rate(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "\n"
        "    signature = inspect.signature(function)\n"
        "    parameters = list(signature.parameters.values())[:1]\n"
        "    wrapper.__signature__ = signature.replace(parameters=parameters)\n"
        "    return wrapper\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decorating import without_rate\n"
        "from metering import settle\n"
        "\n"
        "settled = without_rate(settle)\n",
    )

    assert named_classes(submetering.settled) == {fractions.Fraction}


def test_a_routine_that_wraps_another_callable_but_carries_a_signature_of_none_names_the_classes_the_annotations_it_holds_name_read_where_they_are_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "from datetime import date as Share\n"
        "\n"
        "from metering import settle\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n"
        "\n"
        "audit.__wrapped__ = settle\n"
        "audit.__signature__ = None\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "from auditing import audit\n"
        "\n"
        "@wraps(audit)\n"
        "def reaudit(share: 'Share', extra: 'Share') -> 'Share': ...\n"
        "\n"
        "reaudit.__signature__ = None\n",
    )

    assert named_classes(auditing.audit) == {datetime.date}
    assert named_classes(submetering.reaudit) == {datetime.date}


@pytest.mark.parametrize(
    "routine",
    [
        pytest.param(_typed(len), id="builtin-function"),
        pytest.param(_typed(str.join), id="method-descriptor"),
        pytest.param(_typed(vars(dict)["fromkeys"]), id="classmethod-descriptor"),
        pytest.param(_typed((1).__add__), id="method-wrapper"),
        pytest.param(_typed(operator.itemgetter(1)), id="object-of-a-class-defined-in-c"),
        pytest.param(types.MethodType(_typed(len, "receiver"), object()), id="bound-method"),
    ],
)
def test_a_signature_a_link_carries_over_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    routine: Callable[..., object],
) -> None:
    assert named_classes(routine) == {decimal.Decimal}


def test_a_signature_a_link_carries_over_the_call_a_metaclass_resolves_that_wraps_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled() -> None:
    class Counting(type):
        __call__ = _typed(type.__call__, "receiver")

    class Counted(metaclass=Counting):
        pass

    assert named_classes(Counted) == {decimal.Decimal}


def test_a_signature_a_link_carries_over_the_call_of_a_callable_object_that_wraps_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled() -> None:
    class Caller:
        __call__ = _typed(len, "receiver")

    assert named_classes(functools.partial(Caller())) == {decimal.Decimal}


def test_a_signature_a_link_carries_over_an_object_that_is_neither_callable_nor_a_routine_names_the_classes_it_names_read_where_the_link_given_it_is_spelled() -> None:
    assert named_classes(_typed(property(len))) == {decimal.Decimal}


@pytest.mark.parametrize(
    "wrapped",
    [
        pytest.param(_typed(len), id="function"),
        pytest.param(types.MethodType(_typed(len, "receiver"), object()), id="bound-method"),
    ],
)
def test_a_signature_functools_wraps_copies_from_a_link_that_carries_one_over_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    wrapped: Callable[..., object], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relaying = imported_module(tmp_path, monkeypatch, "relaying", _RELAYING_SOURCE)

    assert named_classes(relaying.relay(wrapped)) == {decimal.Decimal}


@pytest.mark.parametrize(
    ("wrapped", "dropping"),
    [
        pytest.param(_typed(len, "receiver"), 0, id="equal-copy"),
        pytest.param(_typed(len, "receiver"), 1, id="parameters-dropped"),
        pytest.param(functools.partial(_typed(len, "receiver"), 1), 0, id="copy-of-a-partials"),
    ],
)
def test_a_signature_given_to_a_function_that_wraps_a_link_carrying_a_signature_of_its_own_over_a_routine_defined_in_c_raises_type_error_for_a_string_annotation_naming_the_string_and_that_it_may_be_a_copy(
    wrapped: Callable[..., object],
    dropping: int,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relaying = imported_module(tmp_path, monkeypatch, "relaying", _RELAYING_SOURCE)

    with pytest.raises(TypeError, match=r"annotation 'Decimal' no module is known to spell:.*\bmay be a copy\b"):
        named_classes(relaying.resign(wrapped, dropping))


def test_a_partial_that_carries_a_signature_over_a_routine_defined_in_c_records_no_module_so_a_string_annotation_there_raises_type_error_naming_it_and_the_string() -> None:
    rating = functools.partial(len)
    rating.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    counting = functools.partial(len)
    counting.__signature__ = inspect.Signature(
        [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Decimal")]
    )
    relayed = functools.wraps(counting)(lambda *args: counting(*args))

    assert named_classes(rating) == {int}
    naming_the_partial_and_the_string = (
        r"\bfunctools\.partial\(<built-in function len>\).*'Decimal'.*\brecords no module of its own\b"
    )
    with pytest.raises(TypeError, match=naming_the_partial_and_the_string):
        named_classes(counting)
    with pytest.raises(TypeError, match=naming_the_partial_and_the_string):
        named_classes(relayed)


def test_a_signature_a_link_carries_over_a_constructor_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialising = imported_module(
        tmp_path,
        monkeypatch,
        "initialising",
        "from fractions import Fraction as Decimal\n"
        "\n"
        "class Initialised:\n"
        "    pass\n",
    )
    initialising.Initialised.__init__ = _typed(object.__init__, "receiver")

    class Plain:
        pass

    assert named_classes(_typed(zip)) == {decimal.Decimal}
    assert named_classes(_typed(Plain)) == {decimal.Decimal}
    assert named_classes(initialising.Initialised) == {decimal.Decimal}


@pytest.mark.parametrize("shape", _LINK_SHAPES)
@pytest.mark.parametrize("enum_class", _ENUM_KINDS)
def test_a_signature_a_link_carries_over_an_enum_names_the_classes_it_is_annotated_with(
    enum_class: type[enum.Enum], shape: str
) -> None:
    link = _signed_links_over(enum_class, int)[shape]

    assert named_classes(link) == {int}


@pytest.mark.parametrize("shape", _LINK_SHAPES)
@pytest.mark.parametrize("enum_class", _ENUM_KINDS)
def test_a_string_annotation_in_a_signature_a_link_carries_over_an_enum_raises_type_error_naming_that_enum_and_the_string(
    enum_class: type[enum.Enum], shape: str
) -> None:
    link = _signed_links_over(enum_class, "Decimal")[shape]

    with pytest.raises(TypeError, match=rf"\.{enum_class.__name__}\b.*\benum\.Enum\b.*'Decimal'"):
        named_classes(link)


def test_a_routine_that_wraps_a_callable_object_names_the_classes_its_call_method_names_read_where_that_method_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "calling",
        "from fractions import Fraction as Share\n"
        "from functools import wraps\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, share: 'Share') -> None: ...\n"
        "\n"
        "def settle(self, share: 'Share') -> None: ...\n"
        "\n"
        "def logged(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "    return wrapper\n",
    )
    recalling = imported_module(
        tmp_path,
        monkeypatch,
        "recalling",
        "from decimal import Decimal as Share\n"
        "from functools import partial\n"
        "\n"
        "from calling import Caller, logged, settle\n"
        "\n"
        "class Subcaller(Caller):\n"
        "    pass\n"
        "\n"
        "class Settler:\n"
        "    __call__ = settle\n"
        "\n"
        "called = logged(Subcaller())\n"
        "settled = logged(Settler())\n"
        "halved = partial(Subcaller())\n",
    )

    assert named_classes(recalling.called) == {fractions.Fraction}
    assert named_classes(recalling.settled) == {fractions.Fraction}
    assert named_classes(recalling.halved) == {fractions.Fraction}


def test_a_method_bound_to_a_callable_object_names_the_classes_its_call_method_names_read_where_that_method_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "calling",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, owner, share: 'Share') -> None: ...\n",
    )
    recalling = imported_module(
        tmp_path,
        monkeypatch,
        "recalling",
        "from decimal import Decimal as Share\n"
        "\n"
        "from calling import Caller\n"
        "\n"
        "class Subcaller(Caller):\n"
        "    pass\n",
    )

    classes = named_classes(types.MethodType(recalling.Subcaller(), object()))

    assert classes == {fractions.Fraction}


def test_a_routine_that_wraps_a_callable_object_whose_class_resolves_a_descriptor_as_call_names_the_classes_the_callable_that_descriptor_gives_the_object_names_read_where_that_callable_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "binding",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Rebinding:\n"
        "    def __init__(self, rebound):\n"
        "        self.rebound = rebound\n"
        "\n"
        "    def __get__(self, instance, owner):\n"
        "        return self if instance is None else self.rebound\n"
        "\n"
        "    def __call__(self, share: 'Share') -> None: ...\n",
    )
    rebinding = imported_module(
        tmp_path,
        monkeypatch,
        "rebinding",
        "from decimal import Decimal as Share\n"
        "\n"
        "from binding import Rebinding\n"
        "\n"
        "def rebound(share: 'Share') -> None: ...\n"
        "\n"
        "class Caller:\n"
        "    __call__ = Rebinding(rebound)\n",
    )

    assert named_classes(functools.partial(rebinding.Caller())) == {decimal.Decimal}
