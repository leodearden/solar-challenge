# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixtures more than one rule module of this package uses; each one's name, or its own docstring, says what it is.

Outer and Preset are defined at module level, where a qualified name carries no
'<locals>'; a rule module that imports them binds their names for its own forward
references to resolve.
"""

import fractions
import functools
import importlib.util
import inspect
import pathlib
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass

import pytest


class Outer:
    class Inner:
        pass


@dataclass(frozen=True)
class Preset:
    rate: float


class Getter:
    """A descriptor that defines only __get__, as a classproperty does, and records the function it wraps as __wrapped__."""

    def __init__(self, function: Callable[..., object]) -> None:
        self.function = function
        self.__wrapped__ = function

    def __get__(self, instance: object, owner: type) -> object:
        return self.function(owner)


class CallableGetter:
    """A callable descriptor whose __get__ gives itself, with no __set__ and no __wrapped__."""

    def __get__(self, instance: object, owner: type) -> "CallableGetter":
        return self

    def __call__(self, rate: int) -> str: ...


class NoneSignedCallableGetter(CallableGetter):
    """A CallableGetter that records the function it wraps as __wrapped__ but carries a __signature__ of None, at which inspect stops unwrapping and reads it as itself."""

    __signature__ = None

    def __init__(self, function: Callable[..., object]) -> None:
        self.__wrapped__ = function


class GetterDeleter:
    """A descriptor whose type defines __get__ and __delete__ but no __set__."""

    def __get__(self, instance: object, owner: type) -> int:
        return 1

    def __delete__(self, instance: object) -> None: ...


class CallableGetterDeleter(GetterDeleter):
    """A callable GetterDeleter."""

    def __call__(self, rate: int) -> str: ...


class Giver:
    """A descriptor whose __get__ gives the object it was made with."""

    def __init__(self, given: object) -> None:
        self.given = given

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self.given


class CallableGiver(Giver):
    """A callable Giver, whose type defines __get__ and __call__ but neither __set__ nor __delete__."""

    def __call__(self, rate: int) -> None: ...


class DeletingGiver(Giver):
    """A Giver whose type also defines __delete__ but no __call__."""

    def __delete__(self, instance: object) -> None: ...


class GetterPartial(functools.partial):
    """A functools.partial whose own __get__ binds it to an instance as a method, as a function's binds."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self if instance is None else types.MethodType(self, instance)


class SettableGetterPartial(GetterPartial):
    """A GetterPartial whose type also defines __set__, so that no minor reads it as a method descriptor."""

    def __set__(self, instance: object, value: object) -> None: ...


class GetMixin:
    """A class that defines __get__, for a functools.partial subclass to take it from."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self


class PartialFirstGetterPartial(functools.partial, GetMixin):
    """A functools.partial whose type takes __get__ from GetMixin, a base after functools.partial in its MRO, on Python 3.11 and 3.12, and from functools.partial's own __get__, which comes first, from 3.13."""


def _share(receiver: object, rate: int) -> None: ...


class ChainedCall:
    """A class whose __call__ is a classmethod of a staticmethod, which Python 3.11 and 3.12 bind through the staticmethod's __get__ and later minors as a method of the staticmethod."""

    __call__ = classmethod(staticmethod(_share))


class DefCall:
    """A class whose __call__ is defined with def."""

    def __call__(self, share: fractions.Fraction, rate: int) -> None: ...


CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR = (
    pytest.param(lambda build: str.join, id="method-descriptor"),
    pytest.param(classmethod, id="classmethod"),
    pytest.param(property, id="property"),
)


def class_whose_init_is(constructor: object) -> type:
    class Built:
        __init__ = constructor

    return Built


def class_whose_new_is(constructor: object) -> type:
    class Made:
        __new__ = constructor

    return Made


def class_whose_metaclass_call_is(constructor: object) -> type:
    class Calling(type):
        __call__ = constructor

    class Called(metaclass=Calling):
        pass

    return Called


def object_whose_call_is(call: object) -> object:
    class Caller:
        __call__ = call

    return Caller()


def metaclass_whose_get_gives(given: object) -> type:
    class Getting(type):
        def __get__(cls, instance: object, owner: type | None = None) -> object:
            return given

    return Getting


def metaclass_whose_mro_gives(mro: Callable[[type], tuple[type, ...]]) -> type:
    """A metaclass whose __mro__ gives, for each class of it, what *mro* gives for that class, in place of the MRO the class records."""

    class Shadowing(type):
        @property
        def __mro__(cls) -> tuple[type, ...]:
            return mro(cls)

    return Shadowing


def with_a_string_signature(function: Callable[..., object]) -> Callable[..., object]:
    """*function*, carrying the string '(receiver, rate)' as its __signature__."""
    function.__signature__ = "(receiver, rate)"
    return function


def recording_object_init(wrapper: object) -> object:
    """*wrapper*, recording object.__init__ as its __wrapped__."""
    wrapper.__wrapped__ = object.__init__
    return wrapper


GIVEN_BY_A_METACLASS_GET = (
    pytest.param(1, id="get-giving-an-object-that-is-not-callable"),
    pytest.param(None, id="get-giving-none"),
)


def _settle(self: object, rate: int) -> None: ...


_NONE_TYPE = r"\bbuiltins\.NoneType\b"
_SIMPLE_NAMESPACE = r"\btypes\.SimpleNamespace\b"

CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE = (
    pytest.param(None, _NONE_TYPE, id="none"),
    pytest.param(staticmethod(None), _NONE_TYPE, id="staticmethod-of-none"),
    pytest.param(classmethod(None), _NONE_TYPE, id="classmethod-of-none"),
    pytest.param(Giver(None), _NONE_TYPE, id="descriptor-giving-none"),
    pytest.param(types.SimpleNamespace(), _SIMPLE_NAMESPACE, id="object-defining-no-get"),
    pytest.param(staticmethod(types.SimpleNamespace()), _SIMPLE_NAMESPACE, id="staticmethod"),
    pytest.param(classmethod(types.SimpleNamespace()), _SIMPLE_NAMESPACE, id="classmethod"),
    pytest.param(
        Giver(Giver(_settle)), r"\.Giver\b", id="descriptor-giving-a-get-only-descriptor"
    ),
    pytest.param(
        Giver(GetterDeleter()),
        r"\.GetterDeleter\b",
        id="descriptor-giving-a-get-delete-descriptor",
    ),
    pytest.param(
        Giver(types.SimpleNamespace(__signature__="(rate)")),
        _SIMPLE_NAMESPACE,
        id="descriptor-giving-an-object-carrying-a-string-signature",
    ),
    pytest.param(
        Giver(types.SimpleNamespace(__signature__=inspect.Signature())),
        _SIMPLE_NAMESPACE,
        id="descriptor-giving-an-object-carrying-a-signature",
    ),
)

UNREADABLE_ROUTINES = (
    pytest.param(
        functools.partialmethod(_settle, rate=1), "functools.partialmethod", id="partialmethod"
    ),
    pytest.param(
        functools.singledispatchmethod(_settle),
        "functools.singledispatchmethod",
        id="singledispatchmethod",
    ),
    pytest.param(Getter(_settle), "tests.unit.surface_forms_helper._fixtures.Getter", id="getter"),
    pytest.param(
        CallableGetter(),
        "tests.unit.surface_forms_helper._fixtures.CallableGetter",
        id="callable-getter",
    ),
    pytest.param(
        NoneSignedCallableGetter(_settle),
        "tests.unit.surface_forms_helper._fixtures.NoneSignedCallableGetter",
        id="none-signed-callable-getter",
    ),
)

REFUSED_ROUTINE_AND_PARTIAL_MEMBERS = (
    *UNREADABLE_ROUTINES,
    pytest.param(functools.partial(round, ndigits=1), "functools.partial", id="partial"),
)


def imported_module(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str, source: str
) -> types.ModuleType:
    """The module *name*, written from *source* under *tmp_path* and imported, left in sys.modules until *monkeypatch* is undone or a later call imports another module of that name."""
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module
