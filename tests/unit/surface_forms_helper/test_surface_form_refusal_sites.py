# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule of tests/_surface_forms.py's surface_form for how its TypeError names the site of what it refuses: the class constructed through, or the class read through, what a class holds as a name.

The classes and functions above the test are defined at module level, where their
qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import enum
import functools
import types
from typing import Callable

import pytest

from tests._surface_forms import surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CallableGetter,
    Giver,
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    object_whose_call_is,
)


class Period(enum.Enum):
    PEAK = "peak"


def _settle(receiver: object, rate: int) -> None: ...


def _texted(receiver: object, rate: int) -> None: ...


_texted.__signature__ = "(receiver, rate)"


def _inheriting(cls: type) -> type:
    class Inheriting(cls):
        pass

    return Inheriting


@pytest.mark.parametrize(
    ("build", "site"),
    [
        pytest.param(
            lambda: class_whose_init_is(None),
            r"\.Inheriting is constructed through .*\.Built\.__init__, which inspect skips, ",
            id="init-that-inspect-skips",
        ),
        pytest.param(
            lambda: class_whose_init_is(functools.wraps(object.__init__)(lambda self: None)),
            r"\.Inheriting is constructed through .*\.Built\.__init__, which wraps object\.__init__, ",
            id="init-wrapping-a-callable-defined-in-c",
        ),
        pytest.param(
            lambda: class_whose_metaclass_call_is(functools.wraps(type.__call__)(lambda cls: None)),
            r"\.Inheriting is constructed through .*\.Calling\.__call__, which wraps type\.__call__, ",
            id="metaclass-call-wrapping-a-callable-defined-in-c",
        ),
        pytest.param(
            lambda: class_whose_init_is(functools.wraps(Period)(lambda self, value: None)),
            r"\.Inheriting is constructed through .*\.Built\.__init__, which inspect reads as "
            r".*\.Period, an enum\.Enum, ",
            id="init-read-as-an-enum",
        ),
        pytest.param(
            lambda: class_whose_new_is(_texted),
            r"\.Inheriting is constructed through .*\.Made\.__new__, which carries the __signature__ ",
            id="new-carrying-a-string-signature",
        ),
        pytest.param(
            lambda: class_whose_init_is(classmethod(Giver(_settle))),
            r"\.Inheriting is constructed through .*\.Built\.__init__, a classmethod that wraps a ",
            id="init-classmethod-bound-by-minor",
        ),
        pytest.param(
            lambda: class_whose_metaclass_call_is(classmethod(Giver(_settle))),
            r"\.Inheriting is constructed through .*\.Calling\.__call__, a classmethod that wraps a ",
            id="metaclass-call-classmethod-bound-by-minor",
        ),
        pytest.param(
            lambda: class_whose_metaclass_call_is(functools.partial(_settle)),
            r"\.Inheriting is constructed through .*\.Calling\.__call__, a functools\.partial, ",
            id="metaclass-call-partial",
        ),
        pytest.param(
            lambda: class_whose_init_is(functools.partial(_settle)),
            r"\.Inheriting is constructed through .*\.Built\.__init__, a functools\.partial, ",
            id="init-partial",
        ),
        pytest.param(
            lambda: class_whose_init_is(Giver(types.SimpleNamespace())),
            r"\.Inheriting is constructed through .*\.Built\.__init__, which inspect reads as "
            r"namespace\(\), a types\.SimpleNamespace, which is not callable",
            id="init-bound-to-an-object-that-is-not-callable",
        ),
        pytest.param(
            lambda: class_whose_init_is(Giver(CallableGetter())),
            r"\.Inheriting is constructed through .*\.Built\.__init__, which inspect reads as "
            r".*\.CallableGetter, whose type defines __get__ in Python",
            id="init-read-as-a-builtin",
        ),
        pytest.param(
            lambda: class_whose_init_is(object_whose_call_is(functools.partial(_settle))),
            r"\.Inheriting is read through .*\.Caller\.__call__, a functools\.partial, ",
            id="call-partial",
        ),
        pytest.param(
            lambda: class_whose_init_is(object_whose_call_is(classmethod(Giver(_settle)))),
            r"\.Inheriting is read through .*\.Caller\.__call__, a classmethod that wraps a ",
            id="call-classmethod-bound-by-minor",
        ),
        pytest.param(
            lambda: class_whose_init_is(object_whose_call_is(Giver(types.SimpleNamespace()))),
            r"\.Inheriting is read through .*\.Caller\.__call__, which inspect reads as "
            r"namespace\(\), a types\.SimpleNamespace, which is not callable",
            id="call-bound-to-an-object-that-is-not-callable",
        ),
    ],
)
def test_a_type_error_for_a_constructor_or_a_call_names_the_class_read_through_it_its_verb_and_the_class_holding_it_by_name_before_what_it_refuses(
    build: Callable[[], type], site: str
) -> None:
    with pytest.raises(TypeError, match=site):
        surface_form(_inheriting(build()))
