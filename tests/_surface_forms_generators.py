# SPDX-License-Identifier: AGPL-3.0-or-later
"""The generators that write methods into the classes they process, the dataclass decorator and collections.namedtuple, each by the rules it documents: which classes it processed, the name it gives each method it writes there, after the class, and the parameters the dataclass decorator recorded for a class it processed.

Of the helper, this module imports only the modules below it in
tests/unit/test_surface_forms_layers.py's LAYERS, which checks that.
"""

import dataclasses
import types
from collections.abc import Callable

from tests._surface_forms_class_reads import namespace_holders, own_namespace, recorded_mro


@dataclasses.dataclass(frozen=True)
class MethodGenerator:
    """A generator that writes methods into each class it processes, by the rules it documents.

    *label* names the generator. *methods* holds the name of each function it writes into
    a class it processed and names after that class, as *named_after* gives the class's
    name, dotted with the function's own, once unwrapped from any decorator that records it
    as __wrapped__: never the dataclass decorator's __repr__, which wraps a function named
    after no class. *processed* finds each class it processed.
    """

    label: str
    methods: frozenset[str]
    named_after: Callable[[type], str]
    processed: Callable[[type], bool]

    def may_have_written(self, cls: type, name: str, function: object) -> bool:
        """Whether this generator may have written *function* into *cls* as its method *name*: one of its methods, a function named as it names that method after *cls*, in a class it processed.

        A function *cls*'s class statement defined under that name, which the generator
        leaves in place, may meet these conditions too.
        """
        return (
            name in self.methods
            and isinstance(function, types.FunctionType)
            and function.__qualname__ == f"{self.named_after(cls)}.{name}"
            and self.processed(cls)
        )


def _is_decorated_dataclass(cls: type) -> bool:
    """Whether the dataclass decorator processed *cls* itself; is_dataclass is true as well of an undecorated subclass of a dataclass, whose annotations the decorator never read."""
    return "__dataclass_fields__" in own_namespace(cls)


def dataclass_parameter(cls: type, name: str) -> bool:
    """Whether the dataclass decorator recorded its parameter *name* as on, in the __dataclass_params__ of the first class in *cls*'s MRO whose own namespace holds one: *cls*, if the decorator processed it, else the base it inherits the record from, as attribute lookup reads it."""
    holder = next(namespace_holders(recorded_mro(cls), "__dataclass_params__"))
    return bool(getattr(own_namespace(holder)["__dataclass_params__"], name))


DATACLASS_DECORATOR = MethodGenerator(
    label="the dataclass decorator",
    methods=frozenset(
        {
            "__init__",
            "__eq__",
            "__lt__",
            "__le__",
            "__gt__",
            "__ge__",
            "__hash__",
            "__setattr__",
            "__delattr__",
        }
    ),
    named_after=lambda cls: cls.__qualname__,
    processed=_is_decorated_dataclass,
)

NAMEDTUPLE = MethodGenerator(
    label="collections.namedtuple",
    methods=frozenset({"__new__", "_make", "_replace", "__repr__", "_asdict", "__getnewargs__"}),
    named_after=lambda cls: cls.__name__,
    processed=lambda cls: "_fields" in own_namespace(cls),
)

_GENERATORS = (DATACLASS_DECORATOR, NAMEDTUPLE)


def may_be_generated(cls: type, function: types.FunctionType) -> bool:
    """Whether the dataclass decorator or collections.namedtuple may have written *function* into *cls* as the method its own name names, as MethodGenerator.may_have_written finds."""
    return any(
        generator.may_have_written(cls, function.__name__, function) for generator in _GENERATORS
    )
