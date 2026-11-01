# SPDX-License-Identifier: AGPL-3.0-or-later
"""A class's own namespace and own annotations, refused where its metaclass shadows __dict__ or its metaclass's MRO holds a __getattribute__ other than type's and object's, and the MRO a class records, each read as attribute lookup or inspect reads it, whatever its metaclass gives.

The helper's other modules read classes through own_namespace, own_annotations,
recorded_mro and overriding_getattribute_holder. Of the helper, this module imports only
the modules below it in tests/unit/test_surface_forms_layers.py's LAYERS, which checks
that.
"""

import inspect
import types
from collections.abc import Mapping

from tests._surface_forms_labels import label_of


def own_namespace(cls: type) -> Mapping[str, object]:
    """The namespace *cls* holds itself, which attribute lookup reads: what type's own __dict__ descriptor gives for *cls*, whatever __dict__ its metaclass gives.

    A class whose metaclass shadows __dict__ raises TypeError naming it, its metaclass, the
    class in that metaclass's MRO that holds the __dict__ in place of type's, and that
    __dict__'s type. By inspect's own rule, a metaclass shadows __dict__ if a class in the
    MRO it records holds, in its own namespace, a __dict__ other than the descriptor CPython
    made for that very class, as a metaclass that defines __dict__ as a property does. Each
    such namespace is read as the class holds it, since inspect never asks whether the
    metaclass's own metaclass shadows __dict__. A class whose metaclass shadows no __dict__,
    but whose metaclass's MRO holds a __getattribute__ that overriding_getattribute_holder
    finds, which may give another __dict__, raises TypeError naming it, its metaclass and the
    class holding that __getattribute__. docs/surface-forms-inspect-readings.md §4.8 says how
    each minor reads such classes.
    """
    _refuse_dict_other_than_held(cls)
    return _held_namespace(cls)


def own_annotations(cls: type) -> Mapping[str, object]:
    """The annotations *cls*'s own body wrote, as inspect.get_annotations reads them: never a base's, and each string left a string; the TypeError own_namespace raises for each class it refuses, since before Python 3.14 inspect.get_annotations reads such a class's annotations from the __dict__ its metaclass gives."""
    _refuse_dict_other_than_held(cls)
    return inspect.get_annotations(cls)


def overriding_getattribute_holder(metaclass: type) -> type | None:
    """The first class in the MRO *metaclass* records, type and object aside, whose own namespace, read unchecked as attribute lookup reads it, holds __getattribute__; None if none does. Attribute lookup on a class of *metaclass* may then call that __getattribute__ for every name, __dict__ and __signature__ among them."""
    return next(
        (
            holder
            for holder in recorded_mro(metaclass)
            if holder not in (type, object) and "__getattribute__" in _held_namespace(holder)
        ),
        None,
    )


def _refuse_dict_other_than_held(cls: type) -> None:
    """Raise the TypeError own_namespace raises for *cls* if its metaclass shadows __dict__, or else if overriding_getattribute_holder finds a __getattribute__ in its metaclass's MRO."""
    _refuse_shadowed_dict(cls)
    holder = overriding_getattribute_holder(type(cls))
    if holder is not None:
        raise _dict_intercepted_error(cls, holder)


def _refuse_shadowed_dict(cls: type) -> None:
    """Raise the TypeError own_namespace raises for *cls* if its metaclass shadows __dict__."""
    for holder in recorded_mro(type(cls)):
        namespace = _held_namespace(holder)
        if "__dict__" in namespace and not _is_own_dict_descriptor(holder, namespace["__dict__"]):
            raise _dict_shadowed_error(cls, holder, namespace["__dict__"])


def _held_namespace(cls: type) -> Mapping[str, object]:
    """The namespace *cls* holds itself, as type's own __dict__ descriptor gives it, read unchecked."""
    namespace: Mapping[str, object] = type.__dict__["__dict__"].__get__(cls)
    return namespace


def _is_own_dict_descriptor(holder: type, held: object) -> bool:
    """Whether *held*, which *holder*'s own namespace holds as __dict__, is the descriptor CPython makes for *holder* as it creates the class, through which its instances read their own __dict__: a getset descriptor called __dict__ whose __objclass__ is *holder*."""
    return (
        type(held) is types.GetSetDescriptorType
        and held.__name__ == "__dict__"
        and held.__objclass__ is holder
    )


_DICT_READINGS_BY_MINOR = (
    "inspect also reads its annotations by that __dict__ before Python 3.14, and finds its "
    "source by it from 3.13"
)


def _dict_shadowed_error(cls: type, holder: type, held: object) -> TypeError:
    """The error for *cls*, whose metaclass's MRO holds *holder*, whose own namespace holds *held* as __dict__ in place of the descriptor CPython made for it."""
    return TypeError(
        f"{label_of(cls)} has the metaclass {label_of(type(cls))}, whose MRO holds "
        f"{label_of(holder)}.__dict__, a {label_of(type(held))}, in place of the __dict__ "
        "type gives each class: inspect.getattr_static skips a class whose metaclass so "
        "shadows __dict__, attribute lookup reads the namespace the class holds, and inspect "
        "chooses which of its __new__ and __init__ it reads by what that __dict__ gives; "
        f"{_DICT_READINGS_BY_MINOR}; these are readings no rule of this helper reads: make "
        "the name private, or leave __dict__ to type"
    )


def _dict_intercepted_error(cls: type, holder: type) -> TypeError:
    """The error for *cls*, whose metaclass's MRO holds *holder*, whose own namespace holds a __getattribute__ in place of type's."""
    return TypeError(
        f"{label_of(cls)} has the metaclass {label_of(type(cls))}, whose MRO holds "
        f"{label_of(holder)}.__getattribute__, in place of the __getattribute__ type gives "
        "each class: inspect.getattr_static, and inspect's choice of which of the class's "
        "__new__ and __init__ it reads, read its __dict__ through that __getattribute__, "
        "which may give another namespace than the one the class holds; "
        f"{_DICT_READINGS_BY_MINOR}; these are readings no rule of this helper reads: make "
        "the name private, or leave __getattribute__ to type"
    )


def recorded_mro(cls: type) -> tuple[type, ...]:
    """The MRO *cls* records, which attribute lookup and inspect.getattr_static walk: what type's own __mro__ descriptor gives for *cls*, whatever __mro__ its metaclass gives."""
    mro: tuple[type, ...] = type.__dict__["__mro__"].__get__(cls)
    return mro
