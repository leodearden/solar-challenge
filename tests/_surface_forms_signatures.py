# SPDX-License-Identifier: AGPL-3.0-or-later
"""The signature inspect reads for a class or a routine, refused where inspect reads it differently by minor or cannot read it, and the module that spells each annotation it gives.

Both follow the chain and the constructor inspect follows. Of the helper, this module
imports only tests/_surface_forms_module_lookup.py, as
tests/unit/test_surface_forms_layers.py checks.
"""

import abc
import dataclasses
import enum
import functools
import inspect
import types
import typing
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
    """The signature inspect reads for *obj*, a class or a routine, once _refuse_chain_without_a_portable_form has passed the chain inspect follows from it."""
    _refuse_chain_without_a_portable_form(obj, obj)
    return inspect.signature(obj)


def _refuse_chain_without_a_portable_form(subject: object, link: object) -> None:
    """Raise the TypeError for *subject* that the first refusal below finds at the chain inspect follows from *link*: *subject* itself, or the __call__ _call_as_read gives for an object its class makes callable, at which a chain inspect follows from *subject* ends."""
    unreadable = _unreadable_link(link)
    if unreadable is not None:
        raise _unreadable_routine_error(label_of(subject), subject, unreadable)
    end = _chain_end(link, stop=_has_non_none_signature)
    _refuse_wrapped_enum(subject, end)
    _refuse_wrapped_get_delete_descriptor(subject, end)
    _refuse_minor_dependent_signature(subject, end)
    if _carries_inspect_signature(end):
        return
    if inspect.isclass(end):
        _refuse_constructor_without_a_portable_form(end)
    elif callable(end) and not is_routine(end):
        _refuse_minor_dependent_call(subject, end)
        _refuse_chain_without_a_portable_form(subject, _call_as_read(end))


def _call_as_read(obj: object) -> object:
    """The __call__ inspect reads for *obj*, an object its class makes callable: the one its type resolves, as inspect.getattr_static finds it, bound to *obj* as _bound_to binds it."""
    return _bound_to(inspect.getattr_static(type(obj), "__call__"), obj)


def _refuse_minor_dependent_call(subject: object, obj: object) -> None:
    """Raise TypeError naming *subject* if inspect reads *obj*, an object its class makes callable at which a chain inspect follows from *subject* ends, differently by minor: a class in its type's MRO defines __call__ in C, *obj* carries a __text_signature__, or the __call__ its type resolves is a functools.partial."""
    holders = list(namespace_holders(type(obj).__mro__, "__call__"))
    c_holder = next(
        (cls for cls in holders if isinstance(vars(cls)["__call__"], types.WrapperDescriptorType)),
        None,
    )
    if c_holder is not None:
        raise TypeError(
            f"{label_of(subject)} wraps {label_of(obj)}, a {label_of(type(obj))}, whose MRO holds "
            f"{label_of(c_holder)}.__call__, which is defined in C: from Python 3.13 inspect reads "
            "a __text_signature__ such a class may give its instances in place of the __call__ "
            "their type resolves, which it reads on 3.11 and 3.12: make the name private, wrap a "
            "function defined with def, or set a __signature__ that is an inspect.Signature on "
            "the routine or on what it wraps"
        )
    text_signature = getattr(obj, "__text_signature__", None)
    if text_signature:
        raise TypeError(
            f"{label_of(subject)} wraps {label_of(obj)}, a {label_of(type(obj))}, which carries the "
            f"__text_signature__ {text_signature!r}: inspect reads it in place of the __call__ "
            "its type resolves from Python 3.13, and reads that __call__ on 3.11 and 3.12: make "
            "the name private, or set a __signature__ that is an inspect.Signature on the "
            "routine or on what it wraps"
        )
    _refuse_partial_bound_as_method(
        subject, "is read through", holders[0], "__call__", vars(holders[0])["__call__"]
    )


def _chain_end(obj: object, stop: Callable[[object], bool] = lambda link: False) -> object:
    """The end of the chain inspect follows from *obj*, the callable whose own signature it reads: through a bound method's __func__, else the callables a wrapper records as __wrapped__, as _unwrapped follows them, else a functools.partial's func, ending early at the first object *stop* holds of."""
    if not callable(obj):
        return obj
    if isinstance(obj, types.MethodType):
        return _chain_end(obj.__func__, stop)
    unwrapped = _unwrapped(obj, stop)
    if unwrapped is not obj:
        return _chain_end(unwrapped, stop)
    if isinstance(obj, functools.partial) and not stop(obj):
        return _chain_end(obj.func, stop)
    return obj


_ABSENT = object()


def _unwrapped(obj: Callable[..., object], stop: Callable[[object], bool]) -> object:
    """The callable reached from *obj* through the callables each wrapper records as __wrapped__, stopping at the first link *stop* holds of or whose __signature__ is None: inspect stops following __wrapped__ at such a wrapper and reads it as the callable it is."""
    return inspect.unwrap(
        obj, stop=lambda link: getattr(link, "__signature__", _ABSENT) is None or stop(link)
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
_C_ROUTINE_KINDS = (
    *_C_CONSTRUCTOR_KINDS,
    types.MethodDescriptorType,
    types.ClassMethodDescriptorType,
    types.MethodWrapperType,
)


def _refuse_constructor_without_a_portable_form(cls: type) -> None:
    """Raise TypeError naming *cls* and the class holding its constructor if inspect reads that constructor differently by minor, or cannot read it on any.

    The constructors it refuses, in the order it checks them; a constructor wraps a
    callable defined in C here if _wrapped_c_callable gives one for it, carries a
    __signature__ inspect reads by minor if _refuse_constructor_signature finds one, and
    is read as a builtin if _refuse_constructor_read_as_builtin finds it so, bound as
    inspect binds it:

    - the __call__ _metaclass_call gives for *cls*, which inspect looks up before any
      __new__ or __init__, if it wraps a callable defined in C, is a
      functools.partial, carries such a __signature__ or is read as a builtin. inspect
      reads any other __call__ _metaclass_call gives in their place, so none of the
      constructors below is then checked;
    - the constructor inspect reads first of those the holder's own namespace holds, if
      it wraps a callable defined in C, as the __new__ warnings.deprecated writes for a
      class wraps object.__new__;
    - a functools.partial the holder's own namespace holds as __init__, unless that
      namespace also holds a __new__ not defined in C, which inspect reads first;
    - that first-read constructor, if it carries such a __signature__ or is read as a
      builtin;
    - the constructor of a holder other than object that _constructed_in_c counts as
      defined in C.
    """
    call = _metaclass_call(cls)
    if call is not None:
        _refuse_wrapper_of_c_callable(cls, type(cls), "__call__", call)
        _refuse_partial_bound_as_method(cls, "is constructed through", type(cls), "__call__", call)
        _refuse_constructor_signature(cls, type(cls), "__call__", call)
        _refuse_constructor_read_as_builtin(
            cls, type(cls), "__call__", _metaclass_call_as_read(cls)
        )
        return
    holder = _constructor_holder(cls)
    name, constructor = _first_read_constructor(holder)
    _refuse_wrapper_of_c_callable(cls, holder, name, constructor)
    if name == "__init__":
        _refuse_partial_bound_as_method(cls, "is constructed through", holder, name, constructor)
    _refuse_constructor_signature(cls, holder, name, constructor)
    _refuse_constructor_read_as_builtin(cls, holder, name, _constructor_as_read(cls, holder))
    if holder is not object and _constructed_in_c(holder):
        raise TypeError(
            f"{label_of(cls)} is constructed by {label_of(holder)}, which is defined in C (a "
            "builtin or extension type), so inspect reads its signature from a text "
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


def _first_read_constructor(holder: type) -> tuple[str, object]:
    """The name and value of the constructor inspect reads first of those *holder*'s own namespace holds: its __new__, as getattr gives it (a staticmethod unwrapped), unless that is defined in C beside an __init__; else its __init__."""
    namespace = vars(holder)
    if "__new__" in namespace:
        new = getattr(holder, "__new__")
        if not (isinstance(new, _C_CONSTRUCTOR_KINDS) and "__init__" in namespace):
            return "__new__", new
    return "__init__", namespace["__init__"]


def _refuse_wrapper_of_c_callable(
    cls: type, owner: type, name: str, constructor: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name* and the callable defined in C that *constructor*, the one *owner* holds as *name* that inspect reads first for *cls*, wraps, if _wrapped_c_callable gives one.

    inspect reads such a wrapper through that callable on some Python releases, and skips
    it as defined in C on others, reading the next constructor instead.
    """
    wrapped = _wrapped_c_callable(constructor)
    if wrapped is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which wraps "
            f"{wrapped.__qualname__}, defined in C: inspect reads such a wrapper through "
            "that callable on some Python releases and skips it as defined in C on "
            f"others: make the name private, or define {name} with def, wrapping no "
            "callable defined in C"
        )


def _wrapped_c_callable(
    constructor: object,
) -> types.BuiltinFunctionType | types.WrapperDescriptorType | None:
    """The callable defined in C that *constructor* wraps, if _unwrapped, stopped also at a link whose __signature__ is not None, ends at one; None if it ends elsewhere, or if *constructor* is itself defined in C or is not callable.

    It stops at any __signature__, as inspect's own lookup of a constructor does from
    Python 3.13, so it and _refuse_constructor_signature never both apply to one
    constructor.
    """
    if isinstance(constructor, _C_CONSTRUCTOR_KINDS) or not callable(constructor):
        return None
    wrapped = _unwrapped(constructor, _has_non_none_signature)
    return wrapped if isinstance(wrapped, _C_CONSTRUCTOR_KINDS) else None


_PARTIAL_BOUND_BY_MINOR = (
    "a functools.partial, which Python 3.14 binds to the instance as a method and earlier "
    "minors call without it"
)


def _refuse_partial_bound_as_method(
    subject: object,
    verb: typing.Literal["is constructed through", "is read through"],
    owner: type,
    name: str,
    method: object,
) -> None:
    """Raise TypeError saying *subject* *verb* *owner*'s *name*, and stating _PARTIAL_BOUND_BY_MINOR, if *method*, the one *owner* holds as *name* that inspect reads for *subject* and binds through its type's __get__, is a functools.partial."""
    if isinstance(method, functools.partial):
        raise TypeError(
            f"{label_of(subject)} {verb} {label_of(owner)}.{name}, "
            f"{_PARTIAL_BOUND_BY_MINOR}: define {name} with def"
        )


def _refuse_constructor_read_as_builtin(
    cls: type, owner: type, name: str, read: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name*, and the descriptor that ends the chain inspect follows from *read*, with its type, if inspect reads that descriptor as a builtin on some admitted minor, as _is_read_as_builtin or _is_read_as_builtin_before_3_13 finds; *read* is the constructor *owner* holds as *name* that inspect reads first for *cls*, bound as inspect binds it."""
    end = _chain_end(read, stop=_has_non_none_signature)
    if _is_read_as_builtin(end):
        reading = _GET_ONLY_DESCRIPTOR_ON_EVERY_MINOR
    elif _is_read_as_builtin_before_3_13(end):
        reading = _GET_DELETE_DESCRIPTOR_BY_MINOR
    else:
        return
    raise TypeError(
        f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which inspect reads "
        f"as {label_of(end)}, a {label_of(type(end))}, {reading}: make the name private, or "
        f"define {name} with def"
    )


def _refuse_constructor_signature(
    cls: type, owner: type, name: str, constructor: object
) -> None:
    """Raise TypeError naming *cls*, *owner*'s *name* and the __signature__ _minor_dependent_signature gives for the end of *constructor*'s chain, if it gives one; *constructor* is the one *owner* holds as *name* that inspect reads first for *cls*.

    The constructor is named as *owner*.*name*, not by its own label: a functools.wraps
    wrapper's label is that of the callable it wraps.
    """
    signature = _minor_dependent_signature(_chain_end(constructor, stop=_has_non_none_signature))
    if signature is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(owner)}.{name}, which "
            f"{_minor_dependent_signature_clause(signature)}"
        )


def spelling_modules(obj: object, names: Collection[str]) -> Mapping[str, ModuleOrUnspelled]:
    """The module whose source spells the annotation inspect.signature(*obj*) gives each of *names*, parameter names or "return", as _chain_spelling_modules finds it; _RecordsNoModule, naming *obj*, for each if it finds none."""
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

    An Enum's signature is spelled in no module known, as _EnumReadByMinor says, since
    inspect reads it from a different place on each minor. Any other class's constructor
    is the __call__ *cls*'s metaclass resolves, if _metaclass_call_as_read gives one,
    which inspect reads before any __new__ or __init__; else the one
    _constructor_as_read gives for the nearest class in *cls*'s MRO that holds one, which
    may be a base defined in another module. It is spelled where
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
    holder = _constructor_holder(cls)
    constructor = _constructor_as_read(cls, holder)
    end = _chain_end(constructor)
    if signature_holder is not None and isinstance(end, _C_CONSTRUCTOR_KINDS):
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


def _constructor_as_read(cls: type, holder: type) -> object:
    """The constructor inspect.signature reads for *cls* of those *holder*'s own namespace holds, as inspect reads it: a __new__ as getattr gives it, and any other __init__ bound to *cls*, as _bound_to binds it."""
    kind, constructor = _first_read_constructor(holder)
    if kind == "__new__" or isinstance(constructor, _C_CONSTRUCTOR_KINDS):
        return constructor
    return _bound_to(constructor, cls)


def _metaclass_call(cls: type) -> object | None:
    """The __call__ *cls*'s metaclass resolves, as inspect looks it up before any __new__ or __init__, through inspect.getattr_static; None if it is defined in C, as type.__call__ is, which inspect skips on every minor."""
    call = inspect.getattr_static(type(cls), "__call__")
    return None if isinstance(call, _C_CONSTRUCTOR_KINDS) else call


def _metaclass_call_as_read(cls: type) -> object | None:
    """The __call__ _metaclass_call gives for *cls*, as inspect reads it in place of any __new__ or __init__: bound to the metaclass, as _bound_to binds it; None if it gives none, or one that wraps a callable defined in C, as _wrapped_c_callable finds one, which only some minors read."""
    call = _metaclass_call(cls)
    if call is None or _wrapped_c_callable(call) is not None:
        return None
    return _bound_to(call, type(cls))


def _bound_to(descriptor: object, owner: object) -> object:
    """*descriptor* bound to *owner* through its type's __get__, as inspect binds a constructor, or a callable object's __call__, it reads; *descriptor* itself if its type defines no __get__ or it is a functools.partial."""
    get = getattr(type(descriptor), "__get__", None)
    if get is None or isinstance(descriptor, functools.partial):
        return descriptor
    bound: object = get(descriptor, owner, type(owner))
    return bound


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


def _constructor_holder(cls: type) -> type:
    """The class in *cls*'s MRO whose own namespace holds __init__ or __new__, the constructor inspect.signature(*cls*) reads."""
    return next(namespace_holders(cls.__mro__, "__init__", "__new__"))


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
    """Raise TypeError for *member*, a class member that *label* names, if no form of it holds on every admitted minor: the error _unreadable_routine_error gives if it is a routine whose signature inspect cannot read, as _unreadable_link finds one, else, if it is a functools.partial, one that states _PARTIAL_BOUND_BY_MINOR."""
    link = _unreadable_link(member)
    if link is not None:
        raise _unreadable_routine_error(label, member, link)
    if isinstance(member, functools.partial):
        raise TypeError(
            f"{label} is {_PARTIAL_BOUND_BY_MINOR}: make the name private, wrap it in "
            "staticmethod, or define it with def"
        )
