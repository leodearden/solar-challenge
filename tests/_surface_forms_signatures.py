# SPDX-License-Identifier: AGPL-3.0-or-later
"""The signature inspect reads for a class or a routine, refused where inspect reads it differently by minor or cannot read it, and the module that spells each annotation it gives.

Both follow the chain and the constructor inspect follows. Of the helper, this module
imports only tests/_surface_forms_module_lookup.py, as
tests/unit/test_surface_forms_layers.py checks. docs/surface-forms-inspect-readings.md
says how each minor reads what this module refuses: a new refusal gets a rule test, then
an entry there.
"""

import abc
import dataclasses
import enum
import functools
import inspect
import types
import typing
import warnings
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping

from tests._surface_forms_module_lookup import (
    defining_module,
    is_get_delete_descriptor,
    is_routine,
    label_of,
)


class Unspelled(abc.ABC):
    """No module is known to spell the string annotations of a signature, so reading one is refused."""

    @abc.abstractmethod
    def refusal(self, source: str) -> TypeError:
        """The error for reading *source*, a string annotation in that signature."""


@dataclasses.dataclass(frozen=True)
class _RecordsNoModule(Unspelled):
    """*author*, the link given the signature (else the object whose signature is read), records no module of its own, as a functools.partial records none, and what it stands for spells no annotation."""

    author: object

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"{label_of(self.author)} carries a signature whose string annotation {source!r} "
            "no module is known to spell: it records no module of its own, and what it "
            "stands for spells no annotation: make the name private, annotate with the "
            "class, not a string, or carry the signature on a function defined with def"
        )


@dataclasses.dataclass(frozen=True)
class _MayBeCopied(Unspelled):
    """*author*, the function given the signature, wraps a link that carries a signature of its own, which *author*'s may be a copy of: its strings may be spelled where that one was given."""

    author: object

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"{label_of(self.author)} carries a signature whose string annotation {source!r} "
            "no module is known to spell: it wraps a callable that carries a signature of "
            "its own, so this one may be a copy of it, spelled where that one was given: "
            "make the name private, annotate with the class, not a string, or leave the "
            "signature to functools.wraps, which copies it"
        )


_ENUM_SIGNATURE_BY_MINOR = (
    "whose signature inspect reads from EnumType.__call__ on Python 3.11, from "
    "Enum.__signature__ on 3.12 and 3.13, and from EnumType.__signature__ on 3.14"
)


@dataclasses.dataclass(frozen=True)
class _EnumReadByMinor(Unspelled):
    """*enum_class*, an Enum, is what the signature is carried over, and inspect reads that Enum's own signature, which the carried one may copy, from a different place on each minor."""

    enum_class: type

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"A signature carried over {label_of(self.enum_class)}, an {label_of(enum.Enum)} "
            f"{_ENUM_SIGNATURE_BY_MINOR}, holds the string annotation {source!r}, which no "
            "module is known to spell, since the signature may be a copy of that Enum's: "
            "make the name private, or annotate with the class, not a string"
        )


ModuleOrUnspelled: typing.TypeAlias = types.ModuleType | Unspelled


def is_enum(obj: object) -> typing.TypeGuard[type[enum.Enum]]:
    """Whether *obj* is an Enum class, whose own signature inspect reads from a different place on each minor, as _ENUM_SIGNATURE_BY_MINOR says."""
    return inspect.isclass(obj) and issubclass(obj, enum.Enum)


def signature_of(obj: Callable[..., object]) -> inspect.Signature:
    """The signature inspect reads for *obj*, a class or a routine, once _refuse_chain_without_a_portable_form has passed the chain inspect follows from it.

    For a class at that chain's end, _refuse_constructor_without_a_portable_form lists
    the constructors it refuses. inspect's own FutureWarning on binding a
    functools.partial, which Python 3.13 alone emits, is ignored while inspect reads, as
    docs/surface-forms-inspect-readings.md §3.3 says.
    """
    _refuse_chain_without_a_portable_form(obj, obj)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"functools\.partial will be a method descriptor",
            category=FutureWarning,
            module=r"inspect\Z",
        )
        return inspect.signature(obj)


def _refuse_chain_without_a_portable_form(subject: object, link: object) -> None:
    """Raise the TypeError for *subject* that the first refusal below finds at the chain inspect follows from *link*: *subject* itself, or a __call__ inspect reads in its place."""
    _refuse_link_read_as_builtin(subject, link)
    end = _chain_end(link, stop=_has_non_none_signature)
    _refuse_wrapped_enum(subject, end)
    _refuse_wrapped_get_delete_descriptor(subject, end)
    _refuse_minor_dependent_signature(subject, end)
    if _carries_inspect_signature(end):
        return
    if inspect.isclass(end):
        _refuse_constructor_without_a_portable_form(end)
    else:
        _refuse_call_without_a_portable_form(subject, end)


def _refuse_call_without_a_portable_form(subject: object, obj: object) -> None:
    """Raise TypeError naming *subject* if inspect reads *obj*, in *subject*'s place, through the __call__ its type resolves, and so reads it differently by minor or cannot read it on any."""
    if _is_read_through_its_call(obj):
        _refuse_minor_dependent_call(subject, obj)
        _refuse_chain_without_a_portable_form(subject, _call_as_read(obj))


def _is_read_through_its_call(obj: object) -> bool:
    """Whether inspect reads *obj* through the __call__ its type resolves."""
    return (
        callable(obj)
        and not inspect.isclass(obj)
        and not is_routine(obj)
        and not _carries_inspect_signature(obj)
    )


def _call_as_read(obj: object) -> object:
    """The __call__ inspect reads for *obj*, an object its class makes callable: the one its type resolves, as inspect.getattr_static finds it, bound to *obj* as _bound_to binds it."""
    return _bound_to(inspect.getattr_static(type(obj), "__call__"), obj)


def _refuse_minor_dependent_call(subject: object, obj: object) -> None:
    """Raise TypeError naming *subject* if *obj*, an object its class makes callable, which inspect reads in *subject*'s place, is read differently by minor: a class in its type's MRO defines __call__ in C, *obj* carries a __text_signature__, or the __call__ its type resolves is a functools.partial or a classmethod _refuse_classmethod_bound_by_minor refuses."""
    holders = list(namespace_holders(type(obj).__mro__, "__call__"))
    c_holder = next(
        (cls for cls in holders if isinstance(vars(cls)["__call__"], types.WrapperDescriptorType)),
        None,
    )
    if c_holder is not None:
        raise TypeError(
            f"{label_of(subject)} is read through {label_of(obj)}, a {label_of(type(obj))}, whose "
            f"MRO holds {label_of(c_holder)}.__call__, which is defined in C: from Python 3.13 "
            "inspect reads a __text_signature__ such a class may give its instances in place of "
            "the __call__ their type resolves, which it reads on 3.11 and 3.12: make the name "
            "private, put a function defined with def in that object's place, or set a "
            "__signature__ that is an inspect.Signature on that object or on what is read "
            "through it"
        )
    text_signature = getattr(obj, "__text_signature__", None)
    if text_signature:
        raise TypeError(
            f"{label_of(subject)} is read through {label_of(obj)}, a {label_of(type(obj))}, which "
            f"carries the __text_signature__ {text_signature!r}: inspect reads it in place of "
            "the __call__ its type resolves from Python 3.13, and reads that __call__ on 3.11 "
            "and 3.12: make the name private, or set a __signature__ that is an inspect.Signature "
            "on that object or on what is read through it"
        )
    holder = holders[0]
    held = vars(holder)["__call__"]
    _refuse_partial_bound_as_method(subject, "is read through", holder, "__call__", held)
    _refuse_classmethod_bound_by_minor(subject, "is read through", holder, "__call__", held)


def _chain_end(obj: object, stop: Callable[[object], bool] = lambda link: False) -> object:
    """The end of the chain inspect follows from *obj*, the callable whose own signature it reads: the last link _links_inspect_reads gives for *stop*."""
    *_, end = _links_inspect_reads(obj, stop)
    return end


def _links_inspect_reads(obj: object, stop: Callable[[object], bool]) -> Iterator[object]:
    """The links of the chain inspect follows from *obj* that it reads as the callables they are, in order: each functools.partial whose func it follows, then the chain's end, ending early at the first link *stop* holds of.

    A bound method, whose __func__ inspect follows, and a wrapper, whose __wrapped__ it
    follows as _unwrapped follows it, are passed through and never given: inspect reads
    neither.
    """
    if not callable(obj):
        yield obj
        return
    if isinstance(obj, types.MethodType):
        yield from _links_inspect_reads(obj.__func__, stop)
        return
    unwrapped = _unwrapped(obj, stop)
    if unwrapped is not obj:
        yield from _links_inspect_reads(unwrapped, stop)
        return
    yield obj
    if isinstance(obj, functools.partial) and not stop(obj):
        yield from _links_inspect_reads(obj.func, stop)


_ABSENT = object()


def _unwrapped(obj: object, stop: Callable[[object], bool]) -> object:
    """The object reached from *obj* through the callables each wrapper records as __wrapped__, stopping at the first link *stop* holds of or whose __signature__ is None: inspect stops following __wrapped__ at such a wrapper and reads it as the callable it is."""
    return inspect.unwrap(
        obj,  # type: ignore[arg-type]  # typeshed types unwrap's func as a callable; it follows __wrapped__ from any object
        stop=lambda link: getattr(link, "__signature__", _ABSENT) is None or stop(link),
    )


def _has_non_none_signature(obj: object) -> bool:
    """Whether *obj*'s __signature__ is anything but None, as _carries_inspect_signature or _minor_dependent_signature finds one: inspect reads it in *obj*'s place."""
    return _carries_inspect_signature(obj) or _minor_dependent_signature(obj) is not None


def _carries_inspect_signature(obj: object) -> bool:
    """Whether *obj*'s __signature__ is an inspect.Signature, the one value inspect.signature reads as given on every admitted minor, whatever *obj* is or wraps."""
    return isinstance(getattr(obj, "__signature__", None), inspect.Signature)


def _minor_dependent_signature(obj: object) -> object | None:
    """*obj*'s __signature__ if it is neither None, which inspect reads as the callable itself, nor an inspect.Signature, which it reads as given; None otherwise."""
    signature: object = getattr(obj, "__signature__", None)
    if signature is None or isinstance(signature, inspect.Signature):
        return None
    return signature


def _refuse_minor_dependent_signature(obj: object, end: object) -> None:
    """Raise TypeError naming *obj*, and the __signature__ *end* carries with its type, if _minor_dependent_signature gives one for *end*, the end of the chain inspect follows from *obj*; it names *end* too if its label differs from *obj*'s.

    A bound method and a functools.wraps wrapper take the label of the function they
    stand for, so one label names both.
    """
    signature = _minor_dependent_signature(end)
    if signature is not None:
        label = label_of(obj)
        end_label = label_of(end)
        subject = label if end_label == label else f"{label} is read through {end_label}, which"
        raise TypeError(f"{subject} {_minor_dependent_signature_clause(signature)}")


def _minor_dependent_signature_clause(signature: object) -> str:
    """What a message says of *signature*, a __signature__ _minor_dependent_signature gave: that it is carried, its repr and its type, why inspect's reading of it is refused, and what to do instead.

    It begins with its verb, so that a message begins with its subject.
    """
    return (
        f"carries the __signature__ {signature!r}, a {label_of(type(signature))}: Python 3.12 "
        "and 3.13 convert a string given as __signature__ and call a callable given there, "
        "and 3.11 and 3.14 refuse either: set __signature__ to an inspect.Signature, or "
        "make the name private"
    )


def _refuse_link_read_as_builtin(routine: object, link: object, label: str | None = None) -> None:
    """Raise TypeError for *routine* if inspect reads a link of the chain it follows from *link* as a builtin on some admitted minor, or cannot read one: the partial _partial_read_as_builtin_link finds, which inspect meets before the chain's end, as _partial_read_as_builtin_error says; else the link _unreadable_link finds, as _unreadable_routine_error says.

    *label* names *routine*, else label_of(routine), read only once a link is refused:
    a routine defined in C, such as str.join, records no __module__ for it to read.
    """
    partial = _partial_read_as_builtin_link(link)
    if partial is not None:
        raise _partial_read_as_builtin_error(label or label_of(routine), routine, partial)
    unreadable = _unreadable_link(link)
    if unreadable is not None:
        raise _unreadable_routine_error(label or label_of(routine), routine, unreadable)


def _unreadable_link(obj: object) -> object | None:
    """The link of the chain inspect follows from *obj* at which it fails to read a signature, if *obj* is a routine whose signature it cannot read; None otherwise.

    That link is *obj* itself if it is not callable, as no functools.partialmethod or
    functools.singledispatchmethod is, since inspect checks that before it follows any
    chain. Else it is the end of the chain, as _chain_end follows it, if
    _is_read_as_builtin finds it.
    """
    if not is_routine(obj):
        return None
    if not callable(obj):
        return obj
    end = _chain_end(obj, stop=_has_non_none_signature)
    return end if _is_read_as_builtin(end) else None


def _is_read_as_builtin(obj: object) -> bool:
    """Whether inspect reads *obj* as a builtin on every admitted minor, as _GET_ONLY_DESCRIPTOR_ON_EVERY_MINOR says: a routine, as is_routine counts one, whose type defines __get__ in Python, carrying no signature for inspect to read in its place."""
    getter = inspect.getattr_static(type(obj), "__get__", None)
    return (
        is_routine(obj)
        and isinstance(getter, types.FunctionType)
        and not _has_non_none_signature(obj)
    )


def _is_read_as_builtin_before_3_13(obj: object) -> bool:
    """Whether inspect reads *obj* as a builtin on Python 3.11 and 3.12 alone, as _GET_DELETE_DESCRIPTOR_BY_MINOR says: a descriptor is_get_delete_descriptor finds, carrying no signature for inspect to read in its place."""
    return is_get_delete_descriptor(obj) and not _has_non_none_signature(obj)


def _partial_read_as_builtin_link(obj: object) -> object | None:
    """The first link inspect reads on the chain it follows from *obj*, of those _links_inspect_reads gives up to the first that carries a signature other than None, that _is_partial_read_as_builtin_before_3_13 finds; None if none does.

    For that stop, _unwrapped stops following __wrapped__ only where inspect does, at a
    link that carries a __signature__, so a partial that records __wrapped__ and carries
    none is read through what it wraps.
    """
    links = _links_inspect_reads(obj, _has_non_none_signature)
    return next(filter(_is_partial_read_as_builtin_before_3_13, links), None)


def _is_partial_read_as_builtin_before_3_13(obj: object) -> bool:
    """Whether inspect reads *obj* as a builtin on Python 3.11 and 3.12 alone, as _PARTIAL_WITH_ITS_OWN_GET_BY_MINOR says: a functools.partial _is_partial_with_its_own_get finds, whose type defines no __set__, carrying no signature for inspect to read in its place.

    It is asked of a link inspect reads as the callable it is, as _links_inspect_reads
    gives one, never of a wrapper whose __wrapped__ inspect follows instead.
    """
    return (
        _is_partial_with_its_own_get(obj)
        and not hasattr(type(obj), "__set__")
        and not _has_non_none_signature(obj)
    )


def _is_partial_with_its_own_get(obj: object) -> bool:
    """Whether *obj* is a functools.partial whose type's MRO, on either side of functools.partial, holds a class other than functools.partial that defines __get__."""
    return isinstance(obj, functools.partial) and any(
        holder is not functools.partial
        for holder in namespace_holders(type(obj).__mro__, "__get__")
    )


def _unreadable_routine_error(label: str, routine: object, link: object) -> TypeError:
    """The error for *routine*, which *label* names and whose signature inspect fails to read at *link*, the link _unreadable_link gives for it."""
    kind = label_of(type(routine))
    if link is routine:
        return TypeError(
            f"{label} is a {kind}, a routine whose signature inspect cannot read, so no "
            "form spells it: make the name private, or define it with def"
        )
    return TypeError(
        f"{label} is a {kind} that wraps {label_of(link)}, a {label_of(type(link))} whose "
        "signature inspect cannot read, so no form spells it: make the name private, or "
        "define what it wraps with def"
    )


def _partial_read_as_builtin_error(label: str, routine: object, partial: object) -> TypeError:
    """The error for *routine*, which *label* names, at whose link *partial*, the one _partial_read_as_builtin_link gives for it, inspect reads as _PARTIAL_WITH_ITS_OWN_GET_BY_MINOR says."""
    kind = label_of(type(partial))
    if partial is routine:
        return TypeError(
            f"{label} is a {kind}, {_PARTIAL_WITH_ITS_OWN_GET_BY_MINOR}: make the name private, "
            "define it with def, or set a __signature__ that is an inspect.Signature on it"
        )
    return TypeError(
        f"{label} wraps {label_of(partial)}, a {kind}, {_PARTIAL_WITH_ITS_OWN_GET_BY_MINOR}: "
        "make the name private, wrap a function defined with def, or set a __signature__ "
        "that is an inspect.Signature on the routine or on what it wraps"
    )


def _refuse_wrapped_enum(obj: object, end: object) -> None:
    """Raise TypeError naming *obj* and *end*, the end of the chain inspect follows from *obj*, if *end* is an Enum, whose signature inspect reads differently on each minor.

    An Enum is spelled by its members and never reaches here as *obj*; a routine that
    wraps one does.
    """
    if is_enum(end):
        raise TypeError(
            f"{label_of(obj)} wraps {label_of(end)}, an {label_of(enum.Enum)}, "
            f"{_ENUM_SIGNATURE_BY_MINOR}: make the name private, or wrap a function "
            "defined with def"
        )


_GET_ONLY_DESCRIPTOR_ON_EVERY_MINOR = (
    "whose type defines __get__ in Python but neither __set__ nor __delete__: inspect reads "
    "it as a method descriptor, by a text signature only a routine defined in C gives, on "
    "every admitted minor"
)

_GET_DELETE_DESCRIPTOR_BY_MINOR = (
    "whose type defines __get__ and __delete__ but no __set__: inspect reads it as a method "
    "descriptor, by a text signature only a routine defined in C gives, on Python 3.11 and "
    "3.12, and as a data descriptor, through its type's __call__, from 3.13"
)

_PARTIAL_WITH_ITS_OWN_GET_BY_MINOR = (
    "a functools.partial whose type takes __get__ from a class other than functools.partial "
    "and defines no __set__: inspect reads it as a method descriptor, by a text signature "
    "only a routine defined in C gives, on Python 3.11 and 3.12, where functools.partial "
    "defines no __get__, and as a functools.partial, through its func, from 3.13"
)

_NOT_CALLABLE_ON_ANY_MINOR = (
    "which is not callable: inspect reads no signature for what is not callable, on any "
    "admitted minor"
)


def _refuse_wrapped_get_delete_descriptor(obj: object, end: object) -> None:
    """Raise TypeError naming *obj*, *end* and *end*'s type if *end*, the end of the chain inspect follows from *obj*, is a descriptor _is_read_as_builtin_before_3_13 finds.

    Such a descriptor is no routine, so it never reaches here as *obj*; a routine that
    wraps one does.
    """
    if _is_read_as_builtin_before_3_13(end):
        raise TypeError(
            f"{label_of(obj)} wraps {label_of(end)}, a {label_of(type(end))}, "
            f"{_GET_DELETE_DESCRIPTOR_BY_MINOR}: make the name private, wrap a function "
            "defined with def, or set a __signature__ that is an inspect.Signature on the "
            "routine or on what it wraps"
        )


_C_CONSTRUCTOR_KINDS = (types.BuiltinFunctionType, types.WrapperDescriptorType)
_CCallableInspectSkips: typing.TypeAlias = (
    types.BuiltinFunctionType
    | types.WrapperDescriptorType
    | types.MethodWrapperType
    | types.ClassMethodDescriptorType
)
_C_ROUTINE_KINDS = (_CCallableInspectSkips, types.MethodDescriptorType)


def _refuse_constructor_without_a_portable_form(cls: type) -> None:
    """Raise TypeError naming *cls* if inspect reads its constructor differently by minor, or cannot read it on any.

    The constructors it refuses, in the order it checks them; a constructor wraps a
    callable defined in C here if _wrapped_c_callable gives one for it, and is not
    callable once bound, is read as an Enum, carries a __signature__ inspect reads by
    minor, or is read as a builtin or through an object its class makes callable, if
    _refuse_constructor_reading finds it so:

    - the __call__ _metaclass_call gives for *cls*, which inspect looks up before any
      __new__ or __init__, if it is a classmethod _refuse_classmethod_bound_by_minor
      refuses, checked before it is bound, or if it wraps a callable defined in C, is a
      functools.partial, is not callable once bound, is read as an Enum, carries such a
      __signature__, or is read as a builtin or through such an object. inspect reads
      any other __call__ _metaclass_call gives in their place, so none of the
      constructors below is then checked;
    - the __new__ and the __init__ *cls* resolves, both of which inspect binds before it
      chooses which to read, if either is a classmethod
      _refuse_classmethod_bound_by_minor refuses, checked before either is bound;
    - the constructor _first_read_constructor gives for *cls*, if it wraps a callable
      defined in C, as the __new__ warnings.deprecated writes for a class wraps
      object.__new__;
    - that first-read constructor, if it is an __init__ that is a functools.partial;
    - that first-read constructor, if it is not callable once bound, is read as an Enum,
      carries such a __signature__, or is read as a builtin or through such an object;
    - if inspect reads no constructor of *cls*, as _first_read_constructor then gives
      object's __init__: the constructor of the class _refuse_class_constructed_in_c
      finds, else the __new__ or __init__, one inspect skips, that
      _refuse_class_with_no_constructor_inspect_reads names.
    """
    call = _metaclass_call(cls)
    if call is not None:
        _refuse_classmethod_bound_by_minor(
            cls, "is constructed through", type(cls), "__call__", call
        )
        _refuse_wrapper_of_c_callable(cls, type(cls), "__call__", call)
        _refuse_partial_bound_as_method(cls, "is constructed through", type(cls), "__call__", call)
        _refuse_constructor_reading(cls, type(cls), "__call__", _metaclass_call_as_read(cls))
        return
    for name in ("__new__", "__init__"):
        owner = next(namespace_holders(cls.__mro__, name))
        _refuse_classmethod_bound_by_minor(
            cls, "is constructed through", owner, name, vars(owner)[name]
        )
    holder, name, constructor = _first_read_constructor(cls)
    _refuse_wrapper_of_c_callable(cls, holder, name, constructor)
    if name == "__init__":
        _refuse_partial_bound_as_method(cls, "is constructed through", holder, name, constructor)
    _refuse_constructor_reading(cls, holder, name, _constructor_as_read(cls, name, constructor))
    if isinstance(constructor, _CCallableInspectSkips):
        _refuse_class_constructed_in_c(cls)
        _refuse_class_with_no_constructor_inspect_reads(cls)


def _refuse_class_constructed_in_c(cls: type) -> None:
    """Raise TypeError naming *cls* and the first class in its MRO, object aside, that holds a __new__ or __init__ and that _constructed_in_c counts as defined in C, if one does; inspect reads no constructor of *cls*, so it reads the first text signature a class in that MRO gives."""
    constructing = next(
        (
            base
            for base in namespace_holders(cls.__mro__[:-1], "__new__", "__init__")
            if _constructed_in_c(base)
        ),
        None,
    )
    if constructing is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed by {label_of(constructing)}, which is defined in C "
            "(a builtin or extension type), so inspect reads its signature from a text "
            "signature, which a release of its package can add or rewrite, as CPython's "
            "minors do: make the name private, or give the class an __init__ or __new__ "
            "defined with def"
        )


def _constructed_in_c(holder: type) -> bool:
    """Whether the constructors *holder*'s own namespace holds are defined in C, as object's are and as a builtin or extension type's are: each __new__ and __init__ there is of a kind in _C_CONSTRUCTOR_KINDS."""
    namespace = vars(holder)
    return all(
        isinstance(namespace[name], _C_CONSTRUCTOR_KINDS)
        for name in ("__new__", "__init__")
        if name in namespace
    )


def _refuse_class_with_no_constructor_inspect_reads(cls: type) -> None:
    """Raise TypeError naming *cls*, of which inspect reads no constructor, and the first of the __new__ and __init__ it resolves that is not object's, by the class holding it: each as inspect's last check reads it, through getattr, but a _CCallableInspectSkips as held, since binding a classmethod_descriptor to *cls* raises.

    docs/surface-forms-inspect-readings.md §4.5 says how each minor reads such a class.
    """
    for name in ("__new__", "__init__"):
        holder = next(namespace_holders(cls.__mro__, name))
        held = vars(holder)[name]
        read = held if isinstance(held, _CCallableInspectSkips) else getattr(cls, name)
        if read is not vars(object)[name]:
            raise TypeError(
                f"{label_of(cls)} is constructed through {label_of(holder)}.{name}, which "
                "inspect skips, as it skips a constructor whose lookup or binding gives None "
                "or that is defined in C, and through no other constructor inspect reads, so "
                "inspect reads a text signature a class in its MRO gives, which a class "
                "docstring can give on some minors and not others, and raises ValueError "
                f"where none gives one: make the name private, or define {name} with def"
            )


def _first_read_constructor(cls: type) -> tuple[type, str, object]:
    """The class in *cls*'s MRO that holds the constructor inspect reads first for *cls*, with that constructor's name and value.

    Of __new__ and __init__, inspect reads a name only if _skipped_by_inspect does not
    find the one *cls* resolves skipped. The class is the first in the MRO that holds a
    name it reads. The constructor is that class's __new__ if inspect reads that name and
    the class holds it, as getattr gives it (a staticmethod unwrapped), or as
    _classmethod_as_read gives it if it is a classmethod; else its __init__. Where
    inspect reads neither name, the class is object and the constructor object's
    __init__, so the constructor is a _CCallableInspectSkips exactly when inspect reads
    no constructor of *cls*.
    """
    names = [
        name
        for name in ("__new__", "__init__")
        if not _skipped_by_inspect(cls, name, inspect.getattr_static(cls, name))
    ]
    holder = next(namespace_holders(cls.__mro__, *names), object)
    namespace = vars(holder)
    if "__new__" in names and "__new__" in namespace:
        held = namespace["__new__"]
        new = (
            _classmethod_as_read(held.__func__, holder)
            if isinstance(held, classmethod)
            else getattr(holder, "__new__")
        )
        return holder, "__new__", new
    return holder, "__init__", namespace["__init__"]


def _skipped_by_inspect(owner: type, name: str, held: object) -> bool:
    """Whether inspect skips *held*, the constructor *owner* resolves as *name*, as inspect.getattr_static finds it, on every admitted minor, reading that name of no class in the MRO.

    A classmethod, which inspect binds to a method even of None, is never skipped. A
    _CCallableInspectSkips is skipped as defined in C before inspect binds it. Else
    inspect skips what its lookup gives: a __new__ if getattr gives None or a
    _CCallableInspectSkips, as a staticmethod of one gives, and any other name if
    binding it to *owner*, as _bound_to binds it, gives None; inspect reads what that
    binding gives otherwise, a _CCallableInspectSkips included.
    """
    if isinstance(held, classmethod):
        return False
    if isinstance(held, _CCallableInspectSkips):
        return True
    if name == "__new__":
        new = getattr(owner, "__new__")
        return new is None or isinstance(new, _CCallableInspectSkips)
    return _bound_to(held, owner) is None


def _refuse_wrapper_of_c_callable(
    cls: type, owner: type, name: str, constructor: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name* and the callable defined in C that *constructor*, the one *owner* holds as *name* that inspect reads first for *cls*, wraps, if _wrapped_c_callable gives one.

    On some Python releases inspect follows __wrapped__ to that callable and skips the
    constructor as defined in C, reading the next constructor instead, and on others it
    reads the constructor as it binds it.
    """
    wrapped = _wrapped_c_callable(constructor)
    if wrapped is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which wraps "
            f"{wrapped.__qualname__}, defined in C: on some Python releases inspect follows "
            "__wrapped__ to that callable and skips the constructor as defined in C, and on "
            "others it reads the constructor as it binds it: make the name private, or "
            f"define {name} with def, wrapping no callable defined in C"
        )


def _wrapped_c_callable(constructor: object) -> _CCallableInspectSkips | None:
    """The _CCallableInspectSkips that *constructor* wraps, if _unwrapped, stopped also where _stops_constructor_lookup holds, ends at one; None if it ends elsewhere, or if *constructor* is itself one.

    docs/surface-forms-inspect-readings.md §4.5 says which minors take that walk from a
    constructor, and how each reads one at which it stops.
    """
    if isinstance(constructor, _CCallableInspectSkips):
        return None
    wrapped = _unwrapped(constructor, _stops_constructor_lookup)
    return wrapped if isinstance(wrapped, _CCallableInspectSkips) else None


def _stops_constructor_lookup(link: object) -> bool:
    """Whether Python 3.13, looking a class's constructor up before binding it, stops following __wrapped__ at *link*: *link* carries a __signature__, a None one being _unwrapped's own stop, or is a method descriptor as 3.13's inspect.ismethoddescriptor counts one, no class, method, function or functools.partial, whose type defines __get__ but neither __set__ nor __delete__.

    docs/surface-forms-inspect-readings.md §4.5 says where each minor's lookup stops.
    """
    return _has_non_none_signature(link) or (
        inspect.ismethoddescriptor(link)
        and not is_get_delete_descriptor(link)
        and not isinstance(link, functools.partial)
    )


_BindingVerb: typing.TypeAlias = typing.Literal["is constructed through", "is read through"]

_PARTIAL_BOUND_BY_MINOR = (
    "a functools.partial, which Python 3.14 binds to the instance as a method and earlier "
    "minors call without it"
)


def _refuse_partial_bound_as_method(
    subject: object,
    verb: _BindingVerb,
    owner: type,
    name: str,
    method: object,
) -> None:
    """Raise TypeError saying *subject* *verb* *owner*'s *name*, and stating the clause _partial_binding_clause gives for *method*, if *method*, the one *owner* holds as *name* that inspect reads for *subject* and binds through its type's __get__, is a functools.partial."""
    if isinstance(method, functools.partial):
        raise TypeError(
            f"{label_of(subject)} {verb} {label_of(owner)}.{name}, "
            f"{_partial_binding_clause(method)}: define {name} with def"
        )


def _partial_binding_clause(partial: functools.partial[object]) -> str:
    """What a message says of how *partial* binds: _PARTIAL_BOUND_BY_MINOR, unless _is_partial_with_its_own_get finds it; then that its type takes __get__ from a class other than functools.partial, a binding no rule here reads, which holds whatever its MRO, __set__ or signature."""
    if not _is_partial_with_its_own_get(partial):
        return _PARTIAL_BOUND_BY_MINOR
    return (
        f"a {label_of(type(partial))}, a functools.partial whose type takes __get__ from a "
        "class other than functools.partial, a binding no rule of this helper reads"
    )


_CLASSMETHOD_BOUND_BY_MINOR = (
    "Python 3.11 and 3.12 bind a classmethod through the __get__ of what it wraps, a "
    "binding no rule of this helper reads, and 3.13 and 3.14 bind it as a method of what "
    "it wraps"
)


def _refuse_classmethod_bound_by_minor(
    subject: object, verb: _BindingVerb, owner: type, name: str, held: object
) -> None:
    """Raise TypeError saying *subject* *verb* *owner*'s *name*, naming the type of what it wraps and stating _CLASSMETHOD_BOUND_BY_MINOR, if *held*, the one *owner* holds as *name* that inspect binds for *subject*, is a classmethod whose __func__ _is_bound_through_a_get_no_rule_reads finds."""
    if isinstance(held, classmethod) and _is_bound_through_a_get_no_rule_reads(held.__func__):
        raise TypeError(
            f"{label_of(subject)} {verb} {label_of(owner)}.{name}, a classmethod that wraps a "
            f"{label_of(type(held.__func__))}, whose type defines __get__: "
            f"{_CLASSMETHOD_BOUND_BY_MINOR}: make the name private, or define {name} with def"
        )


def _is_bound_through_a_get_no_rule_reads(wrapped: object) -> bool:
    """Whether Python 3.11 and 3.12 bind *wrapped*, held in a classmethod, through a __get__ no rule of this helper reads: one its type takes from a class other than types.FunctionType, functools.partial and types.MethodType.

    A function's __get__ binds it as a method, as 3.13 and 3.14 bind what any
    classmethod holds; functools.partial and types.MethodType define __get__ only from
    3.13, where a classmethod no longer binds what it holds through its __get__, so on
    3.11 and 3.12 neither hides the __get__ of a class after it in the MRO.
    """
    return any(
        holder not in (types.FunctionType, functools.partial, types.MethodType)
        for holder in namespace_holders(type(wrapped).__mro__, "__get__")
    )


def _refuse_constructor_reading(cls: type, owner: type, name: str, read: object) -> None:
    """Raise the TypeError for *cls* that the first refusal below finds for *read*, the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it: *read* is not callable, is read as an Enum, carries at the end of its chain a __signature__ inspect reads by minor, or is read as a builtin or through an object its class makes callable."""
    _refuse_constructor_bound_to_uncallable(cls, owner, name, read)
    end = _chain_end(read, stop=_has_non_none_signature)
    _refuse_constructor_read_as_enum(cls, owner, name, end)
    _refuse_constructor_signature(cls, owner, name, end)
    _refuse_constructor_read_as_builtin(cls, owner, name, read)
    _refuse_call_without_a_portable_form(cls, end)


def _refuse_constructor_bound_to_uncallable(
    cls: type, owner: type, name: str, read: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name*, and *read* with its type, if *read* is not callable; *read* is the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it.

    On every admitted minor, inspect checks that *read* is callable before it reads
    anything of it, its __signature__ included.
    """
    if not callable(read):
        raise _constructor_read_as_error(cls, owner, name, read, _NOT_CALLABLE_ON_ANY_MINOR)


def _constructor_read_as_error(
    cls: type, owner: type, name: str, link: object, reading: str
) -> TypeError:
    """The error naming *cls*, *owner*'s *name*, and *link* with its type and *reading*, the clause saying how inspect reads it; *link* is a link of the chain inspect follows from the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it."""
    return TypeError(
        f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which inspect reads "
        f"as {label_of(link)}, a {label_of(type(link))}, {reading}: make the name private, or "
        f"define {name} with def"
    )


def _refuse_constructor_read_as_enum(cls: type, owner: type, name: str, end: object) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name* and *end* if *end* is an Enum; *end* is the end of the chain inspect follows from the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it."""
    if is_enum(end):
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which inspect "
            f"reads as {label_of(end)}, an {label_of(enum.Enum)}, {_ENUM_SIGNATURE_BY_MINOR}: "
            f"make the name private, or define {name} with def, wrapping no Enum"
        )


def _refuse_constructor_read_as_builtin(
    cls: type, owner: type, name: str, read: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name*, and the link _constructor_link_read_as_builtin finds on the chain inspect follows from *read*, with that link's type and its reading, if it finds one; *read* is the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it."""
    found = _constructor_link_read_as_builtin(read)
    if found is None:
        return
    link, reading = found
    raise _constructor_read_as_error(cls, owner, name, link, reading)


def _constructor_link_read_as_builtin(read: object) -> tuple[object, str] | None:
    """The link of the chain inspect follows from *read*, a constructor as inspect reads it, that inspect reads as a builtin on some admitted minor, with that reading: the partial _partial_read_as_builtin_link finds, which inspect meets before the chain's end; else that end, if _is_read_as_builtin or _is_read_as_builtin_before_3_13 finds it; None if neither is found."""
    partial = _partial_read_as_builtin_link(read)
    if partial is not None:
        return partial, _PARTIAL_WITH_ITS_OWN_GET_BY_MINOR
    end = _chain_end(read, stop=_has_non_none_signature)
    if _is_read_as_builtin(end):
        return end, _GET_ONLY_DESCRIPTOR_ON_EVERY_MINOR
    if _is_read_as_builtin_before_3_13(end):
        return end, _GET_DELETE_DESCRIPTOR_BY_MINOR
    return None


def _refuse_constructor_signature(cls: type, owner: type, name: str, end: object) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name* and the __signature__ _minor_dependent_signature gives for *end*, if it gives one; *end* is the end of the chain inspect follows from the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it.

    The constructor is named as *owner*.*name*, not by the label of *end*: a
    functools.wraps wrapper's label is that of the callable it wraps, and *end* may be
    the function a classmethod holds or one a descriptor's __get__ gives.
    """
    signature = _minor_dependent_signature(end)
    if signature is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which "
            f"{_minor_dependent_signature_clause(signature)}"
        )


def spelling_modules(obj: object, names: Collection[str]) -> Mapping[str, ModuleOrUnspelled]:
    """The module whose source spells the annotation inspect.signature(*obj*) gives each of *names*, parameter names or "return", as _chain_spelling_modules finds it; _RecordsNoModule, naming *obj*, for each if it finds none.

    A class spells them where _constructor_spelling_modules says.
    """
    spelled = _chain_spelling_modules(obj, names)
    if spelled is None:
        return dict.fromkeys(names, _RecordsNoModule(obj))
    return spelled


def _chain_spelling_modules(
    obj: object, names: Collection[str]
) -> Mapping[str, ModuleOrUnspelled] | None:
    """The module that spells each of *names* in the signature inspect reads for *obj*, a class or a routine; None if nothing on its chain spells an annotation or carries a signature.

    That is where the end of the chain _chain_end follows from *obj* spells them, as
    _end_spelling_modules finds it, whatever signature a link carries, since a signature
    given to a wrapper of a callable that spells annotations is presumed derived from
    them. If that end spells no annotation, the strings were given to a link, and it is
    where _carried_signature_module finds the link given the signature of the first link
    that carries one.
    """
    spelled = _end_spelling_modules(_chain_end(obj), names)
    if spelled is not None:
        return spelled
    carrier = _signed_link(obj)
    if carrier is None:
        return None
    return dict.fromkeys(names, _carried_signature_module(carrier))


def _signed_link(obj: object) -> object | None:
    """The first link of the chain inspect follows from *obj*, as _chain_end follows it, whose __signature__ is an inspect.Signature; None if no link of it is."""
    link = _chain_end(obj, stop=_carries_inspect_signature)
    return link if _carries_inspect_signature(link) else None


def _end_spelling_modules(
    end: object, names: Collection[str]
) -> Mapping[str, ModuleOrUnspelled] | None:
    """The module that spells each of *names* where *end*, the end of a chain, spells it; None if *end* spells no annotation.

    A class spells them where _constructor_spelling_modules says. An object its class
    makes callable spells them as the __call__ _call_as_read gives for it does, from
    which inspect derives its signature; anything else that is no routine, such as a
    property a wrapper records as __wrapped__, spells none. A routine of a kind in
    _C_ROUTINE_KINDS spells none; any other, in the module whose globals the callable
    _annotations_author gives for it carries.
    """
    if inspect.isclass(end):
        return _constructor_spelling_modules(end, names)
    if not is_routine(end):
        return _chain_spelling_modules(_call_as_read(end), names) if callable(end) else None
    if isinstance(end, _C_ROUTINE_KINDS):
        return None
    return dict.fromkeys(names, defining_module(_annotations_author(end)))


def _carried_signature_module(carrier: object) -> ModuleOrUnspelled:
    """Where the link _signature_author gives for *carrier* is spelled, the module whose globals it carries if a def or lambda compiled it; _RecordsNoModule, naming that link, if it is neither; _MayBeCopied if that function wraps a link that carries a signature too, which its own may be a copy of."""
    author = _signature_author(carrier)
    if not isinstance(author, types.FunctionType):
        return _RecordsNoModule(author)
    if _signed_link(getattr(author, "__wrapped__", None)) is not None:
        return _MayBeCopied(author)
    return defining_module(author)


def _signature_author(carrier: object) -> object:
    """The link that was given the signature *carrier* carries: *carrier* itself, unless the callable it records as __wrapped__ holds that very signature, as functools.wraps copies it, and then that callable's author in turn; the author of a bound method's function if the walk ends at a bound method, which forwards the signature of the function it binds."""
    if not callable(carrier):
        return carrier
    author = inspect.unwrap(
        carrier, stop=lambda link: not _holds_signature_of(link, getattr(link, "__wrapped__"))
    )
    if isinstance(author, types.MethodType):
        return _signature_author(author.__func__)
    return author


def _holds_signature_of(wrapper: object, wrapped: object) -> bool:
    """Whether *wrapper* holds *wrapped*'s signature, as functools.wraps copies it along with __dict__, by reference: the same __signature__ object; never by equality, since two links given equal signatures each can be spelled in two modules."""
    return getattr(wrapper, "__signature__", None) is getattr(wrapped, "__signature__", _ABSENT)


def _annotations_author(routine: object) -> object:
    """The callable that spelled the annotations *routine* holds: *routine* itself, unless it holds those of the callable it records as __wrapped__, as functools.wraps copies them, and then that callable's author in turn."""
    if not callable(routine):
        return routine
    return inspect.unwrap(
        routine, stop=lambda link: not _holds_annotations_of(link, getattr(link, "__wrapped__"))
    )


def _holds_annotations_of(wrapper: object, wrapped: object) -> bool:
    """Whether *wrapper* holds *wrapped*'s annotations, as functools.wraps copies them, by reference: the same __annotate__ function, which Python 3.14 copies, else the same __annotations__ dict, which earlier minors copy; never by equality, since equal strings in two modules can name two classes."""
    annotate = getattr(wrapper, "__annotate__", None)
    if annotate is not None:
        return annotate is getattr(wrapped, "__annotate__", None)
    return getattr(wrapper, "__annotations__", None) is getattr(wrapped, "__annotations__", _ABSENT)


def _constructor_spelling_modules(
    cls: type, names: Collection[str]
) -> Mapping[str, ModuleOrUnspelled] | None:
    """The module whose source spells the annotation inspect.signature(*cls*) gives each of *names*, parameter names or "return": where the constructor inspect reads is spelled; None if _chain_spelling_modules finds none on that constructor's chain.

    An Enum's signature is spelled in no module known, as _EnumReadByMinor says. Any
    other class's constructor is the __call__ *cls*'s metaclass resolves, if
    _metaclass_call_as_read gives one, which inspect reads before any __new__ or
    __init__; else the one _first_read_constructor gives, as _constructor_as_read reads
    it, which a base defined in another module may hold. It is spelled where
    _chain_spelling_modules spells the end of its chain, so a function the class body
    assigns from another module, or that wraps one there as functools.wraps records one,
    is spelled in that other module. If the function whose annotations that end holds,
    as _annotations_author gives it, was compiled outside the class body and renamed
    into it, as the dataclass decorator generates an __init__ and collections.namedtuple
    a __new__, the constructor is spelled as _generated_constructor_modules spells it;
    if that function was renamed into another class and assigned here, TypeError names
    *cls* and the function. A constructor defined in C, or one that wraps a callable
    defined in C, spells no annotation, so the class's is that of the class
    _signature_holder gives if *cls* carries a signature, else where
    _chain_spelling_modules finds the link given the signature a link of that
    constructor's chain carries, if any does; _signature_holder checks every other class
    that carries a signature before the constructor is read.
    """
    if is_enum(cls):
        return dict.fromkeys(names, _EnumReadByMinor(cls))
    signature_holder = _signature_holder(cls) if _carries_inspect_signature(cls) else None
    call = _metaclass_call_as_read(cls)
    if call is not None:
        return _chain_spelling_modules(call, names)
    holder, name, held = _first_read_constructor(cls)
    constructor = _constructor_as_read(cls, name, held)
    end = _chain_end(constructor)
    if signature_holder is not None and isinstance(end, _CCallableInspectSkips):
        return dict.fromkeys(names, defining_module(signature_holder))
    author = _annotations_author(end)
    if _is_generated(author):
        _refuse_constructor_generated_for_another_class(cls, holder, author)
        return _generated_constructor_modules(holder, names)
    return _chain_spelling_modules(constructor, names)


def _refuse_constructor_generated_for_another_class(
    cls: type, holder: type, generated: types.FunctionType
) -> None:
    """Raise TypeError naming *cls* and *generated*, the function _is_generated finds as the _annotations_author of the end of the constructor *holder* holds, unless it was renamed into *holder*.

    The dataclass decorator renames a function into a class by the class's qualified
    name, collections.namedtuple by its name. A function renamed into another class and
    assigned in *holder*'s body keeps that class's name, and no module is known to spell
    the fields that class declares.
    """
    renamed_into_holder = (
        f"{holder.__qualname__}.{generated.__name__}",
        f"{holder.__name__}.{generated.__name__}",
    )
    if generated.__qualname__ not in renamed_into_holder:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(generated)}, a function generated "
            f"for another class and assigned in the body of {label_of(holder)}, so no module is "
            "known to spell the fields of the class it was generated for: make the name "
            f"private, or define {generated.__name__} with def"
        )


def _constructor_as_read(cls: type, name: str, constructor: object) -> object:
    """*constructor*, the one _first_read_constructor gives for *cls* as *name*, as inspect reads it: a __new__ as given, and any other __init__ bound to *cls*, as _bound_to binds it."""
    if name == "__new__" or isinstance(constructor, _CCallableInspectSkips):
        return constructor
    return _bound_to(constructor, cls)


def _metaclass_call(cls: type) -> object | None:
    """The __call__ *cls*'s metaclass resolves, as inspect looks it up before any __new__ or __init__, through inspect.getattr_static; None if _skipped_by_inspect finds it skipped on every minor, as type.__call__, defined in C, is."""
    call: object = inspect.getattr_static(type(cls), "__call__")
    if _skipped_by_inspect(type(cls), "__call__", call):
        return None
    return call


def _metaclass_call_as_read(cls: type) -> object | None:
    """The __call__ _metaclass_call gives for *cls*, as inspect reads it in place of any __new__ or __init__: bound to the metaclass, as _bound_to binds it; None if it gives none, or one that wraps a callable defined in C, as _wrapped_c_callable finds one, which only some minors read."""
    call = _metaclass_call(cls)
    if call is None or _wrapped_c_callable(call) is not None:
        return None
    return _bound_to(call, type(cls))


def _bound_to(descriptor: object, owner: object) -> object:
    """*descriptor* bound to *owner* through its type's __get__, as inspect binds a constructor, or a callable object's __call__, it reads, but a classmethod as _classmethod_as_read gives it for *owner*'s type; *descriptor* itself if its type defines no __get__ or it is a functools.partial."""
    if isinstance(descriptor, classmethod):
        return _classmethod_as_read(descriptor.__func__, type(owner))
    get = getattr(type(descriptor), "__get__", None)
    if get is None or isinstance(descriptor, functools.partial):
        return descriptor
    bound: object = get(descriptor, owner, type(owner))
    return bound


def _classmethod_as_read(function: object, owner: type) -> object:
    """What inspect reads for a classmethod that holds *function*, bound to *owner* as Python 3.13 and 3.14 bind one, whatever it holds: a method of *function*, or *function* itself if it is not callable.

    types.MethodType will not make a method of what is not callable, though
    classmethod.__get__ makes one, and inspect reads such a method through to
    *function*, as _links_inspect_reads does.

    3.11 and 3.12 bind it alike unless _refuse_classmethod_bound_by_minor refuses the
    classmethod, as it does wherever inspect itself binds one.
    """
    if not callable(function):
        return function
    return types.MethodType(function, owner)


def _generated_constructor_modules(
    holder: type, names: Iterable[str]
) -> dict[str, types.ModuleType]:
    """The module spelling each of *names* in a constructor compiled outside *holder*'s body and renamed into it: that of the nearest class in *holder*'s MRO that the dataclass decorator processed and whose own body annotates the name, or *holder*'s if none does."""
    decorated = tuple(base for base in holder.__mro__ if is_decorated_dataclass(base))
    return {
        name: defining_module(
            next((base for base in decorated if name in inspect.get_annotations(base)), holder)
        )
        for name in names
    }


def _signature_holder(cls: type) -> type:
    """The class in *cls*'s MRO whose own namespace holds, as an inspect.Signature, the __signature__ *cls* carries.

    No module is known to spell a signature that comes from anywhere else. So TypeError
    names *cls* and its metaclass where _metaclass_may_provide_signature(*cls*); and
    where the first class in *cls*'s MRO that holds a __signature__ holds a descriptor
    that gives one, not an inspect.Signature, TypeError names *cls*, that class and the
    descriptor's type.
    """
    if _metaclass_may_provide_signature(cls):
        raise TypeError(
            f"{label_of(cls)} carries a signature its metaclass {label_of(type(cls))} provides "
            "or may provide, through an attribute, a data descriptor or a __getattribute__ "
            "or __getattr__ it defines, so no module is known to spell it: make the name "
            "private, or give the class a metaclass that provides no __signature__"
        )
    holder = next(namespace_holders(cls.__mro__, "__signature__"))
    held = vars(holder)["__signature__"]
    if not isinstance(held, inspect.Signature):
        raise TypeError(
            f"{label_of(cls)} carries the signature a {label_of(type(held))} descriptor gives "
            f"as {label_of(holder)}.__signature__, so no module is known to spell it: make "
            "the name private, or set __signature__ to an inspect.Signature"
        )
    return holder


def _metaclass_may_provide_signature(cls: type) -> bool:
    """Whether *cls*'s metaclass provides the __signature__ type.__getattribute__ gives inspect for *cls*, or may: a class in the metaclass's MRO other than type and object defines __getattribute__; the first one there that holds a __signature__ holds a data descriptor, which outranks *cls*'s own; or no class in *cls*'s MRO holds one, so a metaclass attribute, descriptor or __getattr__ provides it."""
    metaclass_mro = inspect.getmro(type(cls))
    metaclass_holder = next(namespace_holders(metaclass_mro, "__signature__"), None)
    getattribute_holders = namespace_holders(
        (meta for meta in metaclass_mro if meta not in (type, object)), "__getattribute__"
    )
    return (
        next(getattribute_holders, None) is not None
        or (
            metaclass_holder is not None
            and inspect.isdatadescriptor(vars(metaclass_holder)["__signature__"])
        )
        or next(namespace_holders(cls.__mro__, "__signature__"), None) is None
    )


def namespace_holders(classes: Iterable[type], *names: str) -> Iterator[type]:
    """The classes among *classes*, in their order, whose own namespace holds one of *names*."""
    return (cls for cls in classes if any(name in vars(cls) for name in names))


def _is_generated(routine: object) -> typing.TypeGuard[types.FunctionType]:
    """Whether *routine* is a function compiled outside a class body and renamed into a class, as the dataclass decorator generates __init__ and collections.namedtuple __new__.

    The code of such a function keeps another qualified name than the function; one the
    body defines, or one assigned from elsewhere, keeps its own. A function that records
    __wrapped__ is none, though its code keeps another name: functools.wraps renamed it
    after what it wraps, not into a class.
    """
    return (
        isinstance(routine, types.FunctionType)
        and not hasattr(routine, "__wrapped__")
        and routine.__code__.co_qualname != routine.__qualname__
    )


def is_decorated_dataclass(cls: type) -> bool:
    """Whether the dataclass decorator processed *cls* itself; is_dataclass is true as well of an undecorated subclass of a dataclass, whose annotations the decorator never read."""
    return "__dataclass_fields__" in vars(cls)


def refuse_member_without_a_portable_form(label: str, member: object) -> None:
    """Raise TypeError for *member*, a class member that *label* names, if no form of it holds on every admitted minor, checking as a routine's chain is checked, then how it binds: the error _refuse_link_read_as_builtin raises if inspect reads a link of *member*'s chain as a builtin on some admitted minor, or cannot read one; else, if *member* is a functools.partial, one that states the clause _partial_binding_clause gives for it."""
    _refuse_link_read_as_builtin(member, member, label)
    if isinstance(member, functools.partial):
        raise TypeError(
            f"{label} is {_partial_binding_clause(member)}: make the name private, wrap it in "
            "staticmethod, or define it with def"
        )
