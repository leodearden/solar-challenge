# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixtures more than one rule module of this package uses.

Outer and Preset are defined at module level, where a qualified name carries no
'<locals>'; a rule module that imports them binds their names for its own forward
references to resolve. imported_module writes a module and imports it, for the rules
about the module a name is read in. UNREADABLE_ROUTINES holds a routine of each kind
whose signature inspect cannot read, each with its kind's name, for the refusal rules.
"""

import functools
import importlib.util
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


def _settle(self: object, rate: int) -> None: ...


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
