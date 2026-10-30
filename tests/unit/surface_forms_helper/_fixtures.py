# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixtures more than one rule module of this package uses.

Outer and Preset are defined at module level, where a qualified name carries no
'<locals>'; a rule module that imports them binds their names for its own forward
references to resolve. imported_module writes a module and imports it, for the rules
about the module a name is read in. UNREADABLE_ROUTINES holds a routine of each kind
whose signature inspect cannot read, each with its kind's name, for the refusal rules.
REFUSED_ROUTINE_AND_PARTIAL_MEMBERS adds a plain functools.partial to those: the members
that both branches of refuse_member_without_a_portable_form refuse.
GetterDeleter is a descriptor whose type defines __get__ and __delete__ but no __set__,
and CallableGetterDeleter a callable one, for the rules about how inspect reads such a
descriptor. Giver is a descriptor whose __get__ gives the object it was made with, for
the rules about what inspect binds a constructor or a __call__ to. GetterPartial is a functools.partial whose type takes __get__ from a class
other than functools.partial, and SettableGetterPartial one whose type also defines
__set__, for the rules about how inspect reads and binds such a partial.
PartialFirstGetterPartial is one whose type takes __get__ from GetMixin, a base after
functools.partial, whose own __get__ comes first from Python 3.13, for the rules about a
classmethod that wraps such a partial and about how inspect reads and binds such a
partial.
ChainedCall's __call__ is a classmethod of a staticmethod, for the rules about an object
inspect reads through a __call__ that Python 3.11 and 3.12 bind through the __get__ of
what it wraps. CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR makes, from a function, a method
descriptor, a classmethod or a property, each of which a classmethod that wraps it binds
through its __get__ on 3.11 and 3.12 and as a method from 3.13, for the rules about where
named_classes binds such a classmethod itself.
class_whose_init_is, class_whose_new_is and class_whose_metaclass_call_is build a class
whose __init__, whose __new__, or whose metaclass's __call__ is the argument, for the
rules about each constructor site.
object_whose_call_is builds an object whose class's __call__ is the argument, for the
rules about an object inspect reads through the __call__ its class resolves.
metaclass_whose_get_gives builds a metaclass whose __get__ gives the argument, for the
rules about a class held where inspect binds a constructor or a __call__, which it reads
unbound.
GIVEN_BY_A_METACLASS_GET holds what such a __get__ gives in those rules: an object that
is not callable, and None.
CALLS_BOUND_TO_AN_OBJECT_THAT_IS_NOT_CALLABLE holds a __call__ of each kind inspect binds
to an object that is not callable, each with a pattern naming that object's type, for the
rules about a routine or a class read through an object whose class resolves one.
"""

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
    """A functools.partial whose type takes __get__ from a base after functools.partial in its MRO."""


def _share(receiver: object, rate: int) -> None: ...


class ChainedCall:
    """A class whose __call__ is a classmethod of a staticmethod, which Python 3.11 and 3.12 bind through the staticmethod's __get__ and later minors as a method of the staticmethod."""

    __call__ = classmethod(staticmethod(_share))


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
