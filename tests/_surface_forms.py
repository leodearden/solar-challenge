# SPDX-License-Identifier: AGPL-3.0-or-later
"""The surface form of a public name: the text that pins what its callers rely on.

A surface form reads the same on every Python minor that requires-python admits, which
inspect's own rendering does not. surface_form spells a name's form. member_forms spells
the forms of the public members a class's own body defines or declares. named_classes
gives the classes those forms name, and signature_closure the classes of a package that
some names' forms name, directly or through another such class. member_forms reads class
bodies, so undeclared_attributes and unset_attributes check the attributes a class
declares against those its own __init__ and __post_init__ set on self.

tests/unit/surface_forms_helper/ pins each function's rules, one rule per test; its
__init__.py says which module holds which.

Usage::

    from tests._surface_forms import member_forms, named_classes, surface_form, undeclared_attributes

    def scale(values: Optional[List[float]], factor: float = 1.0) -> "Series": ...

    class Meter:
        site: Path

        def __init__(self, site: Path) -> None:
            self.site = site
            self.label = site.name

        @property
        def reading(self) -> float: ...

    assert surface_form(scale) == "(values: list[float] | None, factor: float = 1.0) -> Series"
    assert surface_form({"peak": 0.3}) == "dict"
    assert member_forms(Meter) == {"site": "attribute Path", "reading": "property (self) -> float"}
    assert named_classes(Meter) == {Path, float}
    assert undeclared_attributes(Meter) == {"label"}
"""

import abc
import ast
import dataclasses
import enum
import functools
import inspect
import sys
import textwrap
import types
import typing
import weakref
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping


def surface_form(obj: object) -> str:
    """The surface form of *obj*.

    An Enum's is its members, as NAME=value in definition order. A constant's, that of
    anything neither a class nor a routine, is its type's qualified name; a
    functools.partial is a routine on every admitted minor, as inspect counts one from
    3.14, and any other descriptor whose type defines __get__ and __delete__ but no
    __set__ is no routine on any, as inspect counts none from 3.13. Any other class's
    or routine's is its signature, a class's being its constructor's without self and
    a partial's the one it leaves of the callable it wraps.
    A class's constructor is the __call__ its metaclass resolves if that is not defined
    in C, which inspect reads before any __new__ or __init__, else the __new__ or
    __init__ it reads. A dataclass's signature follows its kind: dataclass, then in
    brackets those of eq, order, unsafe_hash and frozen that are on, whether set on the
    class or on the base it inherits them from. An annotation in that signature which it
    has no rule for, such as a type alias, raises TypeError naming it and its type.

    A class whose constructor inspect reads differently by minor, or cannot read on any,
    raises TypeError naming it and the class holding that constructor, unless it carries
    a signature, which inspect reads in that constructor's place; so does a routine that
    wraps such a class, through a functools.partial, a bound method or a functools.wraps
    wrapper, unless the class or one of the routine's links carries one. A signature is
    an inspect.Signature as __signature__, which inspect reads as given. inspect reads a
    wrapper whose __signature__ is None, whether one of a routine's links or a class's
    constructor, as the callable it is, not as what it wraps, so no refusal here looks
    past it; a functools.partial whose __signature__ is None is still read through its
    func. Any other __signature__, such as a string or a callable, which Python 3.12 and
    3.13 convert or call and 3.11 and 3.14 refuse, raises TypeError naming it and what
    carries it. That applies on the routine or class itself, on the link of a routine's
    chain where inspect stops, and on the constructor inspect reads for a class, its
    metaclass __call__ included. A routine that wraps an Enum, whose signature inspect
    reads differently on each minor, raises TypeError naming it and that Enum, unless
    one of the routine's links carries a signature. A routine that wraps a descriptor
    whose type defines __get__ and __delete__ but no __set__, which inspect reads as a
    builtin before 3.13 and as a data descriptor from 3.13, raises TypeError naming it,
    that descriptor and its type, unless the descriptor or one of the routine's links
    carries a signature. inspect reads an object its class makes callable, at which a
    routine's chain ends, through the __call__ that class resolves, bound to the object,
    unless the object carries a signature; each refusal here applies to that __call__ as
    to the routine, naming the routine. The routine also raises TypeError naming it and
    the object if a class in the object's type's MRO defines __call__ in C, or if the
    object carries a __text_signature__, either of which inspect may read differently
    from Python 3.13; and naming that __call__ if it is a functools.partial, which
    Python 3.14 binds to the object as a method and earlier minors call without it.
    _refuse_constructor_without_a_portable_form lists the constructors it refuses.

    A routine whose signature inspect cannot read raises TypeError naming it and its
    kind: one that is not callable, as no functools.partialmethod or
    functools.singledispatchmethod is; a descriptor defined in Python whose
    __signature__ is None, or that lacks a __signature__ and records no __wrapped__,
    as functools.wraps records one, since inspect then reads it as itself; or a
    routine that inspect reads through such a descriptor, which the TypeError names
    too, with its kind.
    """
    if _is_enum(obj):
        return ", ".join(f"{member.name}={member.value!r}" for member in obj)
    if not _is_class_or_routine(obj):
        return type(obj).__qualname__
    signature = _signature(obj)
    text = str(
        signature.replace(
            parameters=[
                parameter.replace(annotation=_spelled(parameter.annotation))
                for parameter in signature.parameters.values()
            ],
            return_annotation=_spelled(signature.return_annotation),
        )
    )
    if inspect.isclass(obj) and dataclasses.is_dataclass(obj):
        return f"{_dataclass_kind(obj)} {text}"
    return text


def member_forms(cls: type) -> dict[str, str]:
    """The form of each public member of *cls*, by name.

    A member is a public name that *cls*'s own body defines, or declares as an instance
    attribute by annotating it alone or as a dataclass field, except those
    surface_form(cls) already pins: the dataclass fields, named tuple fields and
    init-only variables its constructor's signature takes, and an Enum's members.
    surface_form(cls) pins a named tuple field only while instances read it from the
    tuple: while no class in *cls*'s MRO, *cls* included, binds a value to its name
    before the class typing.NamedTuple or collections.namedtuple made. The attributes
    the body declares come first, in annotation order, then the other names it defines,
    in class-body order. A ClassVar annotation declares a class variable, not an
    instance attribute; a string annotation is read as named_classes reads one, so a
    name its module does not bind raises NameError, a module inspect reads no source for
    raises TypeError, and a module another of the same name has replaced in sys.modules
    raises LookupError. A public member that no member rule spells and that is a routine
    whose signature inspect cannot read, as surface_form describes one, raises TypeError
    naming *cls*, the member and its kind; any other that is a functools.partial, which
    Python 3.14 binds to the instance as a method and earlier minors call without it,
    raises TypeError naming *cls*, the member and that binding.
    """
    return {name: _member_form(member) for name, member in _public_members(cls).items()}


def named_classes(obj: object) -> set[type]:
    """The classes the forms that pin *obj* name: surface_form(obj)'s and, for a class, member_forms(obj)'s.

    Only annotations name classes, never a default value. A generic names its origin and
    its arguments' classes, a bare alias its origin, a union its members' alone, an
    InitVar its type's alone, a type variable those of the constraints, bound and
    default it declares, a NewType its supertype's alone, and Literal's values,
    Annotated's metadata, a special form such as Self and a ParamSpec's args and kwargs
    none. None, given as None or as type(None), names no class either. A string
    annotation or a forward reference names the class its name is bound to in the module
    that spells it, read as a type checker reads it: its globals, with the imports of its
    top-level `if TYPE_CHECKING:` blocks bound over them. A name bound in neither raises
    NameError. A string read in a module inspect reads no source for, such as a built-in
    or extension module, which has no such block to read, raises TypeError naming it and
    that module. A routine is spelled in the module whose globals it carries, whatever
    module its __module__ names; a functools.partial, a bound method, or a routine that
    wraps another callable as functools.wraps records one, where that callable is,
    whatever __signature__ the wrapper carries, but a wrapper that is no partial and
    carries a __signature__ of None, where _annotations_author says its annotations were
    spelled; an object its class makes callable, where the __call__ that class resolves
    is once bound to the object, as inspect binds it, which may be a base's in another
    module; and a class in the one sys.modules holds under the name its __module__
    records. One whose module another of the same name has since replaced in sys.modules
    raises LookupError naming it and the module found there, and one whose module has
    since left sys.modules, LookupError naming it and that module's name. Where inspect
    reads no source for the module found, a class it does not bind under its qualified
    name, as _json binds _json.Scanner as make_scanner, is checked only by the functions
    its body compiled, which must carry that module's globals. A signature carried over
    a callable that spells no annotation, such as one defined in C or a class
    constructed by object or in C, is read where the def or lambda given it is defined.
    A string in one given to a link that records no module, as a functools.partial
    records none, or to a function that wraps a link carrying a signature of its own,
    which the new one may copy, raises TypeError naming the link and the string. A
    string in one carried over an Enum raises TypeError naming that Enum and the string:
    inspect reads an Enum's own signature, which the carried one may copy, from a
    different place on each minor. A signature that annotates nothing, as that of each
    routine CPython defines in C such as str.join, names no class, and no module is
    looked up for it. Met again inside its own evaluation in the same module, as each
    "JSON" is in JSON = Union[dict[str, "JSON"], list["JSON"], str, None], a string names
    no class there: that evaluation names them all.
    An annotation none of these rules reads, such as a type alias, raises TypeError
    naming it and its type; a class or routine whose signature surface_form refuses
    raises the TypeError surface_form raises for it, and a class with a member
    member_forms refuses, the TypeError member_forms raises for it.
    A class's signature, an Enum's aside, is spelled where its constructor is, the
    __call__ its metaclass resolves if inspect reads that, as
    _constructor_spelling_modules describes, whether or not the class carries a
    signature in the constructor's place; one its metaclass or a descriptor gives raises
    TypeError.
    What a type variable or a NewType carries is spelled in the module that declares it;
    inside its own declaration, as in TypeVar("T", bound="Node[T]"), it names no class.
    A type parameter, as in def f[T: "Node"](x: T), reports no module of its own: what
    it carries is spelled in the module that spells the signature holding it. That
    module binds no type parameter, so a string that names one, as "Node[T]" names T,
    raises NameError. A constant names its type, and an Enum's members name nothing.
    """
    if not inspect.isclass(obj):
        return _form_classes(obj)
    member_classes = (
        _member_form_classes(member, obj) for member in _public_members(obj).values()
    )
    return _form_classes(obj).union(*member_classes)


def signature_closure(roots: Iterable[object], package: str) -> set[type]:
    """The classes outside *roots* that a submodule of *package* defines and the forms pinning *roots* name, directly or through another such class.

    Each class found is followed through its own forms, as named_classes reads them, so
    the forms alone decide the set. A class among *roots* is left out by identity,
    whatever name it goes by, though its forms are followed as a root's.
    """
    pending = list(roots)
    root_classes = {root for root in pending if inspect.isclass(root)}
    found: set[type] = set()
    while pending:
        new = {
            cls
            for cls in named_classes(pending.pop())
            if cls.__module__.startswith(f"{package}.")
            and cls not in root_classes
            and cls not in found
        }
        found |= new
        pending.extend(new)
    return found


def undeclared_attributes(cls: type, *, reviewed: Collection[str] = ()) -> set[str]:
    """The public attributes *cls*'s own __init__ and __post_init__ set on self that no class body in its MRO defines or declares.

    An immutable type raises TypeError naming it before anything else is read, and a
    class with no class statement inspect can read, such as ast.AST or _json.Scanner,
    raises TypeError naming it when its source is read.

    A write to self whose attribute name the scan cannot read, such as
    setattr(self, name, value) or a reach into self.__dict__, raises TypeError naming
    *cls* and the write's text, unless *reviewed* holds that text; a text in *reviewed*
    that is no such write's raises ValueError. *reviewed* is a collection of such texts:
    one string given in its place raises TypeError.

    A string annotation in any of those class bodies is read as named_classes reads one,
    so a name its module does not bind raises NameError. Like those annotations, *cls*'s
    source is read from its own module only, so a module another of the same name has
    replaced in sys.modules raises LookupError, unless inspect reads no source for that
    one and *cls*'s body compiled no function to check it by.
    """
    _refuse_immutable_type(cls)
    declared = {name for base in cls.__mro__ for name in _own_members(base)}
    return _attributes_set_on_self(cls, reviewed) - declared


def unset_attributes(cls: type, *, reviewed: Collection[str] = ()) -> set[str]:
    """The attributes member_forms(cls) lists as declared that instances would lack: those *cls*'s own __init__ and __post_init__ never set on self, less each dataclass field with a default or a default factory, whose value the dataclass supplies.

    As in undeclared_attributes, an immutable type raises TypeError naming it before
    anything else is read, a class with no class statement inspect can read raises
    TypeError naming it when its source is read, a write to self whose attribute name the
    scan cannot read raises TypeError unless *reviewed* holds its text, a text in
    *reviewed* that is no such write's raises ValueError, and one string given as
    *reviewed* raises TypeError. A reviewed write sets none of the declared attributes,
    since its names are unknown.

    A string annotation in *cls*'s own body is read as named_classes reads one, so a name
    its module does not bind raises NameError. Like such an annotation, *cls*'s source is
    read from its own module only, so a module another of the same name has replaced in
    sys.modules raises LookupError, unless inspect reads no source for that one and
    *cls*'s body compiled no function to check it by.

    A known gap: a default factory counts as called by the generated __init__, so a field
    with one that a hand-written __init__ skips goes unreported, though instances lack it.
    """
    _refuse_immutable_type(cls)
    declared = member_forms(cls).keys() & _declared_attributes(cls).keys()
    return declared - _attributes_set_on_self(cls, reviewed) - _defaulted_fields(cls)


class _Spelling(str):
    """An annotation's spelling, which inspect prints unquoted, as it prints an annotation it does not know by its repr."""

    def __repr__(self) -> str:
        return str(self)


def _spelled(annotation: object) -> object:
    if annotation is inspect.Parameter.empty:
        return annotation
    return _Spelling(_parsed(annotation, frozenset()).text())


_TypeVariable: typing.TypeAlias = typing.TypeVar | typing.ParamSpec | typing.TypeVarTuple


@dataclasses.dataclass(frozen=True)
class _Evaluation:
    """A string evaluated in a module, held in *enclosing* while what it evaluates to is read, so that the same string met again there, in the same module, names no class."""

    source: str
    module: types.ModuleType


_Enclosing: typing.TypeAlias = frozenset[_TypeVariable | typing.NewType | _Evaluation]


class _Unspelled(abc.ABC):
    """No module is known to spell the string annotations of a signature, so reading one is refused."""

    @abc.abstractmethod
    def refusal(self, source: str) -> TypeError:
        """The error for reading *source*, a string annotation in that signature."""


@dataclasses.dataclass(frozen=True)
class _RecordsNoModule(_Unspelled):
    """*author*, the link given the signature (else the object whose signature is read), records no module of its own, as a functools.partial records none, and what it stands for spells no annotation."""

    author: object

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"{_label(self.author)} carries a signature whose string annotation {source!r} "
            "no module is known to spell: it records no module of its own, and what it "
            "stands for spells no annotation: make the name private, annotate with the "
            "class, not a string, or carry the signature on a function defined with def"
        )


@dataclasses.dataclass(frozen=True)
class _MayBeCopied(_Unspelled):
    """*author*, the function given the signature, wraps a link that carries a signature of its own, which *author*'s may be a copy of: its strings may be spelled where that one was given."""

    author: object

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"{_label(self.author)} carries a signature whose string annotation {source!r} "
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
class _EnumReadByMinor(_Unspelled):
    """*enum_class*, an Enum, is what the signature is carried over, and inspect reads that Enum's own signature, which the carried one may copy, from a different place on each minor."""

    enum_class: type

    def refusal(self, source: str) -> TypeError:
        return TypeError(
            f"A signature carried over {_label(self.enum_class)}, an {_label(enum.Enum)} "
            f"{_ENUM_SIGNATURE_BY_MINOR}, holds the string annotation {source!r}, which no "
            "module is known to spell, since the signature may be a copy of that Enum's: "
            "make the name private, or annotate with the class, not a string"
        )


_ModuleOrUnspelled: typing.TypeAlias = types.ModuleType | _Unspelled


class _Construct(abc.ABC):
    """An annotation parsed as the construct it is, the annotations inside it parsed in turn: the one grammar both its spelling and the classes it names are read by."""

    @abc.abstractmethod
    def text(self) -> str:
        """The spelling, alike on every admitted minor."""

    @abc.abstractmethod
    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        """The classes it names, a name in it resolved in *module*; a string raises TypeError where *module* is _Unspelled, as no module is known to spell it."""


@dataclasses.dataclass(frozen=True)
class _Unevaluated(_Construct):
    """A string annotation or a forward reference: spelled as written, naming the classes of the annotation it evaluates to, read inside the declarations and evaluations that enclose it where it is written; inside its own evaluation in the same module it names no class."""

    source: str
    enclosing: _Enclosing

    def text(self) -> str:
        return self.source

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        if isinstance(module, _Unspelled):
            raise module.refusal(self.source)
        evaluation = _Evaluation(self.source, module)
        if evaluation in self.enclosing:
            return set()
        evaluated = _evaluated(self.source, module)
        return _parsed(evaluated, self.enclosing | {evaluation}).classes(module)


@dataclasses.dataclass(frozen=True)
class _Leaf(_Construct):
    """A part read whole, an annotation or a value inside one: spelled as given, naming the classes it carries."""

    spelling: str
    named: frozenset[type] = frozenset()

    def text(self) -> str:
        return self.spelling

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return set(self.named)


@dataclasses.dataclass(frozen=True)
class _Union(_Construct):
    """A union: spelled by its members with bars, naming its members' classes alone."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return " | ".join(member.text() for member in self.members)

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Subscripted(_Construct):
    """An origin and its arguments: spelled origin[arguments], origin[()] with none, naming the classes of both."""

    origin: _Construct
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        inside = _texts_of(self.arguments) if self.arguments else "()"
        return f"{self.origin.text()}[{inside}]"

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return self.origin.classes(module) | _classes_of(self.arguments, module)


@dataclasses.dataclass(frozen=True)
class _ParameterTypes(_Construct):
    """A Callable's list of parameter types: spelled in brackets, naming its members' classes."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return f"[{_texts_of(self.members)}]"

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Declared(_Construct):
    """A type variable or a NewType: spelled by its name, then in parentheses the annotations its declaration passes, if any; naming their classes alone, a name in them resolved in the module that declares it, or, where none is known, in the module that spells the signature holding it."""

    name: str
    module: types.ModuleType | None
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        if not self.arguments:
            return self.name
        return f"{self.name}({_texts_of(self.arguments)})"

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return _classes_of(self.arguments, module if self.module is None else self.module)


@dataclasses.dataclass(frozen=True)
class _Keyword(_Construct):
    """An annotation a declaration passes by keyword: spelled keyword=annotation, naming its classes."""

    keyword: str
    annotation: _Construct

    def text(self) -> str:
        return f"{self.keyword}={self.annotation.text()}"

    def classes(self, module: _ModuleOrUnspelled) -> set[type]:
        return self.annotation.classes(module)


def _texts_of(constructs: Iterable[_Construct]) -> str:
    return ", ".join(construct.text() for construct in constructs)


def _classes_of(constructs: Iterable[_Construct], module: _ModuleOrUnspelled) -> set[type]:
    return set().union(*(construct.classes(module) for construct in constructs))


_CLASSLESS_NAME_KINDS: tuple[type, ...] = (
    typing.ParamSpecArgs,
    typing.ParamSpecKwargs,
    typing._SpecialForm,
)


def _parsed(annotation: object, enclosing: _Enclosing) -> _Construct:
    """The construct *annotation* is, read inside the declarations of the type variables and NewTypes and the evaluations of the strings in *enclosing*; raises TypeError naming it and its type if no construct reads it."""
    if isinstance(annotation, str):
        return _Unevaluated(annotation, enclosing)
    if isinstance(annotation, typing.ForwardRef):
        return _Unevaluated(annotation.__forward_arg__, enclosing)
    if annotation is None or annotation is type(None):
        return _Leaf("None")
    if annotation is Ellipsis:
        return _Leaf("...")
    if isinstance(annotation, list):
        return _ParameterTypes(_each_parsed(annotation, enclosing))
    if isinstance(annotation, dataclasses.InitVar):
        return _Subscripted(_Leaf("InitVar"), (_parsed(annotation.type, enclosing),))
    if _is_bare_alias(annotation):
        return _parsed(typing.get_origin(annotation), enclosing)
    if isinstance(annotation, _TypeVariable):
        return _parsed_type_variable(annotation, enclosing)
    if isinstance(annotation, typing.NewType):
        return _parsed_new_type(annotation, enclosing)
    if isinstance(annotation, _CLASSLESS_NAME_KINDS):
        return _Leaf(repr(annotation))
    if typing.get_origin(annotation) is not None:
        return _parsed_subscription(annotation, enclosing)
    if inspect.isclass(annotation):
        return _Leaf(annotation.__qualname__, frozenset({annotation}))
    kind = f"{type(annotation).__module__}.{type(annotation).__qualname__}"
    raise TypeError(
        f"No construct reads the annotation {annotation!r}, of type {kind}: give it a "
        "_Construct that spells it and names its classes, or, if it is a name and no "
        "class, add its type to _CLASSLESS_NAME_KINDS"
    )


def _is_bare_alias(annotation: object) -> bool:
    """Bare List: a class as origin, and no __args__ at all.

    Not tuple[()], whose __args__ is (), nor P.args, whose origin is no class.
    """
    has_class_origin = inspect.isclass(typing.get_origin(annotation))
    return has_class_origin and not hasattr(annotation, "__args__")


def _parsed_type_variable(variable: _TypeVariable, enclosing: _Enclosing) -> _Declared:
    """*variable* as its declaration passes it: its repr, then its constraints, then its bound and its default by keyword, each only if declared and each read inside that declaration; its repr alone if that declaration encloses it."""
    module = _declaring_module(variable)
    if variable in enclosing:
        return _Declared(repr(variable), module, ())
    inside = enclosing | {variable}
    arguments = list(_each_parsed(getattr(variable, "__constraints__", ()), inside))
    bound = getattr(variable, "__bound__", None)
    if bound is not None and bound is not type(None):
        arguments.append(_Keyword("bound", _parsed(bound, inside)))
    if getattr(variable, "has_default", lambda: False)():
        default = variable.__default__  # type: ignore[union-attr]  # typeshed declares __default__ only from 3.13
        arguments.append(_Keyword("default", _parsed(default, inside)))
    return _Declared(repr(variable), module, tuple(arguments))


def _declaring_module(variable: _TypeVariable) -> types.ModuleType | None:
    """The module *variable*'s __module__ names, looked up unchecked, as a type variable records nothing else to check it by; None if that name is typing, which a type parameter (`def f[T]`) reports in place of the module of the routine or class that declares it."""
    return None if variable.__module__ == "typing" else _defining_module(variable)


def _parsed_new_type(new_type: typing.NewType, enclosing: _Enclosing) -> _Declared:
    """*new_type* by its qualified name, as a class is spelled, then its supertype, read inside its declaration; its name alone if that declaration encloses it."""
    qualified_name = new_type.__qualname__  # type: ignore[attr-defined]  # typeshed's NewType omits the __qualname__ its __init__ sets
    module = _defining_module(new_type)
    if new_type in enclosing:
        return _Declared(qualified_name, module, ())
    supertype = _parsed(new_type.__supertype__, enclosing | {new_type})
    return _Declared(qualified_name, module, (supertype,))


def _parsed_subscription(annotation: object, enclosing: _Enclosing) -> _Construct:
    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return _Union(_each_parsed(arguments, enclosing))
    if origin is typing.Literal:
        return _Subscripted(_Leaf("Literal"), _value_leaves(arguments))
    if origin is typing.Annotated:
        annotated, *metadata = arguments
        return _Subscripted(
            _Leaf("Annotated"), (_parsed(annotated, enclosing), *_value_leaves(metadata))
        )
    return _Subscripted(_parsed(origin, enclosing), _each_parsed(arguments, enclosing))


def _each_parsed(
    annotations: Iterable[object], enclosing: _Enclosing
) -> tuple[_Construct, ...]:
    return tuple(_parsed(annotation, enclosing) for annotation in annotations)


def _value_leaves(values: Iterable[object]) -> tuple[_Leaf, ...]:
    """The values inside an annotation, a Literal's values and an Annotated's metadata: each spelled by its repr, naming no class."""
    return tuple(_Leaf(repr(value)) for value in values)


def _form_classes(obj: object) -> set[type]:
    """The classes surface_form(obj) names: none for an Enum, a constant's type, else those its signature's annotations name, each read in the module that spells it; none, and no module looked up, for a signature that annotates nothing."""
    if _is_enum(obj):
        return set()
    if not _is_class_or_routine(obj):
        return {type(obj)}
    annotations = _signature_annotations(_signature(obj))
    if not annotations:
        return set()
    modules = _spelling_modules(obj, annotations)
    return set().union(
        *(
            _parsed(annotation, frozenset()).classes(modules[name])
            for name, annotation in annotations.items()
        )
    )


def _is_enum(obj: object) -> typing.TypeGuard[type[enum.Enum]]:
    """Whether *obj* is an Enum class: surface_form spells it by its members, and inspect reads its own signature from a different place on each minor."""
    return inspect.isclass(obj) and issubclass(obj, enum.Enum)


def _is_class_or_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a class or a routine, the objects surface_form spells, an Enum aside, by their signature rather than by their type."""
    return inspect.isclass(obj) or _is_routine(obj)


def _is_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a routine as inspect.isroutine reads one from Python 3.14, on every admitted minor: before 3.14 inspect counts no functools.partial as one, and before 3.13 it counts each descriptor _is_get_delete_descriptor finds."""
    return isinstance(obj, functools.partial) or (
        inspect.isroutine(obj) and not _is_get_delete_descriptor(obj)
    )


def _is_get_delete_descriptor(obj: object) -> bool:
    """Whether *obj*'s type defines __get__ and __delete__ but no __set__: a data descriptor, as inspect.isdatadescriptor reads one on every admitted minor, that inspect before Python 3.13 also counts as a method descriptor."""
    kind = type(obj)
    return (
        inspect.isdatadescriptor(obj) and hasattr(kind, "__get__") and not hasattr(kind, "__set__")
    )


def _signature(obj: Callable[..., object]) -> inspect.Signature:
    """The signature inspect reads for *obj*, a class or a routine, once _refuse_chain_without_a_portable_form has passed the chain inspect follows from it."""
    _refuse_chain_without_a_portable_form(obj, obj)
    return inspect.signature(obj)


def _refuse_chain_without_a_portable_form(subject: object, link: object) -> None:
    """Raise the TypeError for *subject* that the first refusal below finds at the chain inspect follows from *link*: *subject* itself, or the __call__ _call_as_read gives for an object its class makes callable, at which a chain inspect follows from *subject* ends."""
    unreadable = _unreadable_link(link)
    if unreadable is not None:
        raise _unreadable_routine_error(_label(subject), subject, unreadable)
    end = _chain_end(link, stop=_has_non_none_signature)
    _refuse_wrapped_enum(subject, end)
    _refuse_wrapped_get_delete_descriptor(subject, end)
    _refuse_minor_dependent_signature(subject, end)
    if _carries_inspect_signature(end):
        return
    if inspect.isclass(end):
        _refuse_constructor_without_a_portable_form(end)
    elif callable(end) and not _is_routine(end):
        _refuse_minor_dependent_call(subject, end)
        _refuse_chain_without_a_portable_form(subject, _call_as_read(end))


def _call_as_read(obj: object) -> object:
    """The __call__ inspect reads for *obj*, an object its class makes callable: the one its type resolves, as inspect.getattr_static finds it, bound to *obj* as _bound_to binds it."""
    return _bound_to(inspect.getattr_static(type(obj), "__call__"), obj)


def _refuse_minor_dependent_call(subject: object, obj: object) -> None:
    """Raise TypeError naming *subject* if inspect reads *obj*, an object its class makes callable at which a chain inspect follows from *subject* ends, differently by minor: a class in its type's MRO defines __call__ in C, *obj* carries a __text_signature__, or the __call__ its type resolves is a functools.partial."""
    holders = list(_namespace_holders(type(obj).__mro__, "__call__"))
    c_holder = next(
        (cls for cls in holders if isinstance(vars(cls)["__call__"], types.WrapperDescriptorType)),
        None,
    )
    if c_holder is not None:
        raise TypeError(
            f"{_label(subject)} wraps {_label(obj)}, a {_label(type(obj))}, whose MRO holds "
            f"{_label(c_holder)}.__call__, which is defined in C: from Python 3.13 inspect reads "
            "a __text_signature__ such a class may give its instances in place of the __call__ "
            "their type resolves, which it reads on 3.11 and 3.12: make the name private, wrap a "
            "function defined with def, or set a __signature__ that is an inspect.Signature on "
            "the routine or on what it wraps"
        )
    text_signature = getattr(obj, "__text_signature__", None)
    if text_signature:
        raise TypeError(
            f"{_label(subject)} wraps {_label(obj)}, a {_label(type(obj))}, which carries the "
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
        label = _label(obj)
        end_label = _label(end)
        subject = label if end_label == label else f"{label} is read through {end_label}, which"
        raise TypeError(f"{subject} {_minor_dependent_signature_clause(signature)}")


def _minor_dependent_signature_clause(signature: object) -> str:
    """What a message says of *signature*, a __signature__ _minor_dependent_signature gave: that it is carried, its repr and its type, why inspect's reading of it is refused, and what to do instead.

    It begins with its verb, so that a message begins with its subject.
    """
    return (
        f"carries the __signature__ {signature!r}, a {_label(type(signature))}: Python 3.12 "
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
    if not _is_routine(obj):
        return None
    if not callable(obj):
        return obj
    end = _chain_end(obj, stop=_has_non_none_signature)
    return end if _is_read_as_builtin(end) else None


def _is_read_as_builtin(obj: object) -> bool:
    """Whether inspect reads *obj* as a builtin on every admitted minor, as _GET_ONLY_DESCRIPTOR_ON_EVERY_MINOR says: a routine, as _is_routine counts one, whose type defines __get__ in Python, carrying no signature for inspect to read in its place."""
    getter = inspect.getattr_static(type(obj), "__get__", None)
    return (
        _is_routine(obj)
        and isinstance(getter, types.FunctionType)
        and not _has_non_none_signature(obj)
    )


def _is_read_as_builtin_before_3_13(obj: object) -> bool:
    """Whether inspect reads *obj* as a builtin on Python 3.11 and 3.12 alone, as _GET_DELETE_DESCRIPTOR_BY_MINOR says: a descriptor _is_get_delete_descriptor finds, carrying no signature for inspect to read in its place."""
    return _is_get_delete_descriptor(obj) and not _has_non_none_signature(obj)


def _unreadable_routine_error(label: str, routine: object, link: object) -> TypeError:
    """The error for *routine*, which *label* names and whose signature inspect fails to read at *link*, the link _unreadable_link gives for it."""
    kind = _label(type(routine))
    if link is routine:
        return TypeError(
            f"{label} is a {kind}, a routine whose signature inspect cannot read, so no "
            "form spells it: make the name private, or define it with def"
        )
    return TypeError(
        f"{label} is a {kind} that wraps {_label(link)}, a {_label(type(link))} whose "
        "signature inspect cannot read, so no form spells it: make the name private, or "
        "define what it wraps with def"
    )


def _refuse_wrapped_enum(obj: object, end: object) -> None:
    """Raise TypeError naming *obj* and *end*, the end of the chain inspect follows from *obj*, if *end* is an Enum, whose signature inspect reads differently on each minor.

    An Enum is spelled by its members and never reaches here as *obj*; a routine that
    wraps one does.
    """
    if _is_enum(end):
        raise TypeError(
            f"{_label(obj)} wraps {_label(end)}, an {_label(enum.Enum)}, "
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
            f"{_label(obj)} wraps {_label(end)}, a {_label(type(end))}, "
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
            f"{_label(cls)} is constructed by {_label(holder)}, which is defined in C (a "
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
            f"{_label(cls)} is constructed through {_label(owner)}.{name}, which wraps "
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
            f"{_label(subject)} {verb} {_label(owner)}.{name}, "
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
        f"{_label(cls)} is constructed through {_label(owner)}.{name}, which inspect reads "
        f"as {_label(end)}, a {_label(type(end))}, {reading}: make the name private, or "
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
            f"{_label(cls)} is constructed through {_label(owner)}.{name}, which "
            f"{_minor_dependent_signature_clause(signature)}"
        )


def _signature_annotations(signature: inspect.Signature) -> dict[str, object]:
    """The annotations *signature* gives, by parameter name or "return"; a parameter or return without one has no entry."""
    annotations = {
        name: parameter.annotation
        for name, parameter in signature.parameters.items()
        if parameter.annotation is not inspect.Parameter.empty
    }
    if signature.return_annotation is not inspect.Signature.empty:
        annotations["return"] = signature.return_annotation
    return annotations


def _spelling_modules(obj: object, names: Collection[str]) -> Mapping[str, _ModuleOrUnspelled]:
    """The module whose source spells the annotation inspect.signature(*obj*) gives each of *names*, parameter names or "return", as _chain_spelling_modules finds it; _RecordsNoModule, naming *obj*, for each if it finds none."""
    spelled = _chain_spelling_modules(obj, names)
    if spelled is None:
        return dict.fromkeys(names, _RecordsNoModule(obj))
    return spelled


def _chain_spelling_modules(
    obj: object, names: Collection[str]
) -> Mapping[str, _ModuleOrUnspelled] | None:
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
) -> Mapping[str, _ModuleOrUnspelled] | None:
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
    if not _is_routine(end):
        return _chain_spelling_modules(_call_as_read(end), names) if callable(end) else None
    if isinstance(end, _C_ROUTINE_KINDS):
        return None
    return dict.fromkeys(names, _defining_module(_annotations_author(end)))


def _carried_signature_module(carrier: object) -> _ModuleOrUnspelled:
    """Where the link _signature_author gives for *carrier* is spelled, the module whose globals it carries if a def or lambda compiled it; _RecordsNoModule, naming that link, if it is neither; _MayBeCopied if that function wraps a link that carries a signature too, which its own may be a copy of."""
    author = _signature_author(carrier)
    if not isinstance(author, types.FunctionType):
        return _RecordsNoModule(author)
    if _signed_link(getattr(author, "__wrapped__", None)) is not None:
        return _MayBeCopied(author)
    return _defining_module(author)


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
) -> Mapping[str, _ModuleOrUnspelled] | None:
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
    if _is_enum(cls):
        return dict.fromkeys(names, _EnumReadByMinor(cls))
    signature_holder = _signature_holder(cls) if _carries_inspect_signature(cls) else None
    call = _metaclass_call_as_read(cls)
    if call is not None:
        return _chain_spelling_modules(call, names)
    holder = _constructor_holder(cls)
    constructor = _constructor_as_read(cls, holder)
    end = _chain_end(constructor)
    if signature_holder is not None and isinstance(end, _C_CONSTRUCTOR_KINDS):
        return dict.fromkeys(names, _defining_module(signature_holder))
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
            f"{_label(cls)} is constructed through {_label(generated)}, a function generated "
            f"for another class and assigned in the body of {_label(holder)}, so no module is "
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
    decorated = tuple(base for base in holder.__mro__ if _is_decorated_dataclass(base))
    return {
        name: _defining_module(
            next((base for base in decorated if name in inspect.get_annotations(base)), holder)
        )
        for name in names
    }


def _constructor_holder(cls: type) -> type:
    """The class in *cls*'s MRO whose own namespace holds __init__ or __new__, the constructor inspect.signature(*cls*) reads."""
    return next(_namespace_holders(cls.__mro__, "__init__", "__new__"))


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
            f"{_label(cls)} carries a signature its metaclass {_label(type(cls))} provides "
            "or may provide, through an attribute, a data descriptor or a __getattribute__ "
            "or __getattr__ it defines, so no module is known to spell it: make the name "
            "private, or give the class a metaclass that provides no __signature__"
        )
    holder = next(_namespace_holders(cls.__mro__, "__signature__"))
    held = vars(holder)["__signature__"]
    if not isinstance(held, inspect.Signature):
        raise TypeError(
            f"{_label(cls)} carries the signature a {_label(type(held))} descriptor gives "
            f"as {_label(holder)}.__signature__, so no module is known to spell it: make "
            "the name private, or set __signature__ to an inspect.Signature"
        )
    return holder


def _metaclass_may_provide_signature(cls: type) -> bool:
    """Whether *cls*'s metaclass provides the __signature__ type.__getattribute__ gives inspect for *cls*, or may: a class in the metaclass's MRO other than type and object defines __getattribute__; the first one there that holds a __signature__ holds a data descriptor, which outranks *cls*'s own; or no class in *cls*'s MRO holds one, so a metaclass attribute, descriptor or __getattr__ provides it."""
    metaclass_mro = inspect.getmro(type(cls))
    metaclass_holder = next(_namespace_holders(metaclass_mro, "__signature__"), None)
    getattribute_holders = _namespace_holders(
        (meta for meta in metaclass_mro if meta not in (type, object)), "__getattribute__"
    )
    return (
        next(getattribute_holders, None) is not None
        or (
            metaclass_holder is not None
            and inspect.isdatadescriptor(vars(metaclass_holder)["__signature__"])
        )
        or next(_namespace_holders(cls.__mro__, "__signature__"), None) is None
    )


def _namespace_holders(classes: Iterable[type], *names: str) -> Iterator[type]:
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


def _member_form_classes(member: object, cls: type) -> set[type]:
    """The classes the form of *member*, one of *cls*'s, names."""
    if isinstance(member, _AnnotatedAttribute):
        return _parsed(member.annotation, frozenset()).classes(_defining_module(cls))
    function = _spelled_function(member)
    return _form_classes(member if function is None else function)


def _defining_module(obj: object) -> types.ModuleType:
    """The module that defined *obj*, as sys.modules holds it: the one place this helper looks a module up by name, through _module_named, checked for a routine and for a class; a functools.partial's is that of the callable it wraps, and anything else records only its module's name, so that module is looked up unchecked."""
    if isinstance(obj, functools.partial):
        return _defining_module(obj.func)
    if _is_routine(obj):
        return _routine_module(obj)
    if inspect.isclass(obj):
        return _class_module(obj)
    return _module_named(obj.__module__, obj)


def _module_named(name: str, obj: object) -> types.ModuleType:
    """The module sys.modules holds under *name*, the name of the module that defined *obj*; LookupError naming both if sys.modules holds none there, as once that module has left it."""
    module = sys.modules.get(name)
    if module is None:
        raise LookupError(
            f"{_label(obj)} is defined in the module named {name!r}, but sys.modules holds "
            "no module under that name: read each module's objects while sys.modules holds it"
        )
    return module


def _label(obj: object) -> str:
    """The name this helper's errors give *obj*: its module's name and its qualified name, dotted; its repr if it records no qualified name, as a type variable does not."""
    qualified_name = getattr(obj, "__qualname__", None)
    return repr(obj) if qualified_name is None else f"{obj.__module__}.{qualified_name}"


def _routine_module(routine: Callable[..., object]) -> types.ModuleType:
    """The module whose globals *routine* carries, whatever module its __module__ names: the one sys.modules holds under the name that module was imported as, its spec's, or its __name__ if it has no spec.

    If sys.modules holds another module under that name, as once another module of the
    same name has replaced it there, LookupError names *routine* and both modules. A
    routine that carries no globals, as a descriptor object that carries a signature
    carries none, records nothing to check its module by, so the one its __module__
    names is looked up unchecked.
    """
    namespace = getattr(routine, "__globals__", None)
    if namespace is None:
        return _module_named(routine.__module__, routine)
    spec = namespace.get("__spec__")
    name = namespace.get("__name__") if spec is None else spec.name
    module = _module_named(name, routine)
    if vars(module) is not namespace:
        raise _defined_elsewhere(_label(routine), namespace, module, name)
    return module


_PY_TPFLAGS_IMMUTABLETYPE = 1 << 8


def _is_immutable_type(cls: type) -> bool:
    """Whether *cls*'s flags mark it an immutable type, which only C code defines.

    Python marks no class a class statement or type() creates, and CPython marks every
    static type and many heap types it defines in C, though not all, such as ast.AST.
    """
    return bool(cls.__flags__ & _PY_TPFLAGS_IMMUTABLETYPE)


def _class_module(cls: type) -> types.ModuleType:
    """The module sys.modules holds under the name *cls*'s __module__ records, where typing and inspect read a class's annotations and source, checked to be the module that defined *cls*.

    A class defined outside any function must be bound there under its qualified name,
    and one defined inside a function must find there the globals the first function its
    body compiled carries. A module inspect reads no source for, such as a built-in or
    extension module, holds no class statement to misread, and _evaluated refuses a
    string read there, so a class such a module does not bind under its qualified name,
    as _json binds _json.Scanner as make_scanner, is checked as one defined inside a
    function is. Otherwise, as once another module of the same name has replaced its own
    in sys.modules, LookupError names *cls* and the module found. An immutable type
    carries no source or annotation to misread, and a class so checked whose body
    compiled no function carries nothing to check it by, so their module is looked up
    unchecked.
    """
    module = _module_named(cls.__module__, cls)
    if _is_immutable_type(cls):
        return module
    if "<locals>" in cls.__qualname__:
        return _checked_by_body_function(cls, module)
    bound = _bound_under(cls.__qualname__, module)
    if bound is cls:
        return module
    if not _has_source(module):
        return _checked_by_body_function(cls, module)
    raise LookupError(
        f"{_label(cls)} is not bound under {cls.__qualname__!r} in "
        f"the module at {getattr(module, '__file__', None)}, which sys.modules holds under "
        f"the name {cls.__module__!r}: that module binds "
        f"{'nothing' if bound is None else 'another object'} there. Read each module's "
        "objects before importing another module of that name, or bind the class under "
        "its qualified name"
    )


def _checked_by_body_function(cls: type, module: types.ModuleType) -> types.ModuleType:
    """*module*, checked to hold as its globals those the first function *cls*'s body compiled carries: LookupError naming *cls* and both modules if it does not; unchecked if that body compiled none."""
    function = _function_compiled_in_body(cls)
    if function is not None and function.__globals__ is not vars(module):
        raise _defined_elsewhere(_label(cls), function.__globals__, module, cls.__module__)
    return module


def _defined_elsewhere(
    label: str, namespace: dict[str, object], module: types.ModuleType, name: str
) -> LookupError:
    """The error for *label*, defined in the module whose globals are *namespace*, once sys.modules holds *module* in its place under *name*."""
    return LookupError(
        f"{label} is defined in the module at {namespace.get('__file__')}, but sys.modules "
        f"holds the module at {getattr(module, '__file__', None)} under the name {name!r}: "
        "read each module's objects before importing another module of that name"
    )


def _function_compiled_in_body(cls: type) -> types.FunctionType | None:
    """The first function *cls*'s own body compiled, read through _spelled_function and unwrapped from any decorator that records it as __wrapped__: one whose code's qualified name is *cls*'s dotted with the code's name; None if the body compiled none, as an annotation-only body compiles none before Python 3.14, which compiles its __annotate__ unless the module imports annotations from __future__, and as the dataclass decorator and EnumType compile the functions they add elsewhere."""
    functions = (_spelled_function(member) or member for member in vars(cls).values())
    unwrapped = (
        inspect.unwrap(function) for function in functions if isinstance(function, types.FunctionType)
    )
    return next(
        (
            function
            for function in unwrapped
            if isinstance(function, types.FunctionType)
            and function.__code__.co_qualname == f"{cls.__qualname__}.{function.__code__.co_name}"
        ),
        None,
    )


def _bound_under(qualified_name: str, module: types.ModuleType) -> object:
    """What *module* binds under the dotted *qualified_name*, one attribute at a time; None if it binds nothing there."""
    bound: object = module
    for name in qualified_name.split("."):
        bound = getattr(bound, name, None)
    return bound


def _evaluated(annotation: str, module: types.ModuleType) -> object:
    """*annotation* evaluated in a copy of *module*'s globals, with the imports of its top-level `if TYPE_CHECKING:` blocks run over them; TypeError naming both if inspect reads no source for *module*, which then has no such block to read."""
    if not _has_source(module):
        raise TypeError(
            f"The string annotation {annotation!r} is read in the module {module.__name__!r}, "
            "for which inspect reads no source, as for a built-in or extension module, so no "
            "`if TYPE_CHECKING:` import there can be read: make the name private, or annotate "
            "with the class, not a string"
        )
    namespace = dict(vars(module))
    exec(_type_checking_imports(module), namespace)
    return eval(annotation, namespace)


_Argument = typing.TypeVar("_Argument")
_Result = typing.TypeVar("_Result")


def _cached_while_alive(function: Callable[[_Argument], _Result]) -> Callable[[_Argument], _Result]:
    """*function*, its result for each argument computed once and kept only while that argument lives, so the cache keeps no argument alive."""
    results: weakref.WeakKeyDictionary[_Argument, _Result] = weakref.WeakKeyDictionary()

    @functools.wraps(function)
    def cached(argument: _Argument) -> _Result:
        if argument not in results:
            results[argument] = function(argument)
        return results[argument]

    return cached


@_cached_while_alive
def _type_checking_imports(module: types.ModuleType) -> types.CodeType:
    """The Import and ImportFrom statements of *module*'s top-level `if TYPE_CHECKING:` blocks, compiled, so running them binds each name as Python binds it."""
    imports: list[ast.stmt] = []
    for node in ast.parse(inspect.getsource(module)).body:
        match node:
            case ast.If(
                test=ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"),
                body=body,
            ):
                imports += [
                    statement
                    for statement in body
                    if isinstance(statement, (ast.Import, ast.ImportFrom))
                ]
    return compile(ast.Module(body=imports, type_ignores=[]), module.__name__, "exec")


@_cached_while_alive
def _has_source(module: types.ModuleType) -> bool:
    """Whether inspect reads a source for *module*: not for a built-in or extension module, nor for one with no file, as a module types.ModuleType makes has none."""
    try:
        inspect.getsource(module)
    except (OSError, TypeError):
        return False
    return True


def _pinned_by_class_form(cls: type) -> set[str]:
    """The names member_forms leaves to surface_form(cls): an Enum's members, each dataclass field its constructor takes, or each named tuple field it takes that instances read from the tuple."""
    if _is_enum(cls):
        return set(cls.__members__)
    if dataclasses.is_dataclass(cls):
        return _dataclass_fields(cls).keys() & _constructor_parameters(cls)
    if _is_named_tuple(cls):
        return _fields_read_from_the_tuple(cls) & _constructor_parameters(cls)
    return set()


def _dataclass_fields(cls: type) -> dict[str, dataclasses.Field[object]]:
    """*cls*'s dataclass fields by name, inherited ones included; none if *cls* is no dataclass."""
    if not dataclasses.is_dataclass(cls):
        return {}
    return {field.name: field for field in dataclasses.fields(cls)}


def _is_named_tuple(cls: type) -> typing.TypeGuard[type[typing.NamedTuple]]:
    """Whether *cls* is a named tuple, as dataclasses.asdict recognises one: a tuple whose class records its fields' names as _fields, as each class typing.NamedTuple or collections.namedtuple makes does, and each subclass of one."""
    return issubclass(cls, tuple) and hasattr(cls, "_fields")


def _fields_read_from_the_tuple(cls: type[typing.NamedTuple]) -> set[str]:
    """The names of the named tuple *cls*'s fields that its instances read from the tuple: each that no class in *cls*'s MRO binds before the class typing.NamedTuple or collections.namedtuple made, which binds each field's descriptor beside _fields; a value bound earlier hides the field."""
    return {
        name
        for name in cls._fields
        if "_fields" in vars(next(_namespace_holders(cls.__mro__, name, "_fields")))
    }


def _constructor_parameters(cls: type) -> set[str]:
    """The names of the parameters of *cls*'s constructor that surface_form(cls) spells, self excluded."""
    return set(_signature(cls).parameters)


def _defaulted_fields(cls: type) -> set[str]:
    """The names of *cls*'s dataclass fields with a default, which instances read from the class, or a default factory, which the generated __init__ calls."""
    return {
        name
        for name, field in _dataclass_fields(cls).items()
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    }


def _is_decorated_dataclass(cls: type) -> bool:
    """Whether the dataclass decorator processed *cls* itself; is_dataclass is true as well of an undecorated subclass of a dataclass, whose annotations the decorator never read."""
    return "__dataclass_fields__" in vars(cls)


def _init_only_variables(cls: type) -> set[str]:
    """The names of the dataclass init-only variables *cls*'s own body declares: those it annotates, other than as a ClassVar, that its constructor takes but that are no dataclass fields."""
    if not _is_decorated_dataclass(cls):
        return set()
    annotated = {
        name
        for name, annotation in inspect.get_annotations(cls).items()
        if not _is_class_var(annotation, cls)
    }
    return (annotated & _constructor_parameters(cls)) - _dataclass_fields(cls).keys()


@dataclasses.dataclass(frozen=True)
class _AnnotatedAttribute:
    """The annotation of a name a class body declares as an instance attribute, by annotating it alone or as a dataclass field."""

    annotation: object


def _public_members(cls: type) -> dict[str, object]:
    """The members member_forms(cls) spells, by name: the public names *cls*'s own body defines or declares, less those surface_form(cls) pins.

    A member that _spelled_function has no rule for raises the TypeError
    _refuse_member_without_a_portable_form raises for it, if any, naming *cls* and the
    member.
    """
    pinned = _pinned_by_class_form(cls)
    members = {
        name: member
        for name, member in _own_members(cls).items()
        if not name.startswith("_") and name not in pinned
    }
    for name, member in members.items():
        if _spelled_function(member) is None:
            _refuse_member_without_a_portable_form(f"{_label(cls)}.{name}", member)
    return members


def _refuse_member_without_a_portable_form(label: str, member: object) -> None:
    """Raise TypeError for *member*, which *label* names and no member rule spells, if no form of it holds on every admitted minor: the error _unreadable_routine_error gives if it is a routine whose signature inspect cannot read, as _unreadable_link finds one, else, if it is a functools.partial, one that states _PARTIAL_BOUND_BY_MINOR."""
    link = _unreadable_link(member)
    if link is not None:
        raise _unreadable_routine_error(label, member, link)
    if isinstance(member, functools.partial):
        raise TypeError(
            f"{label} is {_PARTIAL_BOUND_BY_MINOR}: make the name private, wrap it in "
            "staticmethod, or define it with def"
        )


def _own_members(cls: type) -> dict[str, object]:
    """Each attribute *cls*'s own body declares, as an _AnnotatedAttribute, then each other name it defines, as its value; a dataclass init-only variable declares a constructor parameter, so it is neither, even with a default."""
    declared = {
        name: _AnnotatedAttribute(annotation)
        for name, annotation in _declared_attributes(cls).items()
    }
    defined = {name: value for name, value in vars(cls).items() if name not in declared}
    init_only = _init_only_variables(cls)
    return {
        name: member
        for name, member in (declared | defined).items()
        if name not in init_only
    }


def _declared_attributes(cls: type) -> dict[str, object]:
    """The annotation of each attribute *cls*'s own body declares, by name: each name it annotates, other than as a ClassVar, and gives no class value; a dataclass field's default is the field's, not a class value.

    inspect.get_annotations reads the body's own annotations, never a base's, and leaves
    a string annotation a string.
    """
    class_values = vars(cls).keys() - _dataclass_fields(cls).keys()
    return {
        name: annotation
        for name, annotation in inspect.get_annotations(cls).items()
        if name not in class_values and not _is_class_var(annotation, cls)
    }


def _is_class_var(annotation: object, cls: type) -> bool:
    """Whether *annotation*, which *cls*'s own body declares, is ClassVar, bare or subscripted, which declares a class variable, not an instance attribute; a string annotation is evaluated as named_classes evaluates one, in *cls*'s module."""
    if isinstance(annotation, str):
        return _is_class_var(_evaluated(annotation, _defining_module(cls)), cls)
    return annotation is typing.ClassVar or typing.get_origin(annotation) is typing.ClassVar


def _member_form(member: object) -> str:
    form = _form_by_kind(member)
    if getattr(member, "__isabstractmethod__", False):
        return f"abstract {form}"
    return form


def _form_by_kind(member: object) -> str:
    if isinstance(member, _AnnotatedAttribute):
        return f"attribute {_parsed(member.annotation, frozenset()).text()}"
    function = _spelled_function(member)
    if function is None:
        return surface_form(member)
    if isinstance(member, property):
        return f"{_property_kind(member)} {surface_form(function)}"
    return f"{type(member).__name__} {surface_form(function)}"


def _spelled_function(member: object) -> object | None:
    """The function whose signature the form of *member* spells after its kind: a classmethod's or staticmethod's, a property's getter or a cached_property's; None for any other member."""
    match member:
        case classmethod() | staticmethod():
            return member.__func__
        case property():
            return member.fget
        case functools.cached_property():
            return member.func
        case _:
            return None


def _property_kind(member: property) -> str:
    abilities = [
        ability
        for ability, accessor in (("settable", member.fset), ("deletable", member.fdel))
        if accessor is not None
    ]
    return _qualified_kind("property", abilities)


_DATACLASS_KIND_PARAMETERS: tuple[str, ...] = ("eq", "order", "unsafe_hash", "frozen")


def _dataclass_kind(cls: type) -> str:
    """The kind of the dataclass *cls*: dataclass, qualified by those of _DATACLASS_KIND_PARAMETERS the decorator recorded as on, for *cls* or for the base *cls* inherits the record from."""
    parameters = cls.__dataclass_params__  # type: ignore[attr-defined]  # typeshed declares no __dataclass_params__
    return _qualified_kind(
        "dataclass", [name for name in _DATACLASS_KIND_PARAMETERS if getattr(parameters, name)]
    )


def _qualified_kind(kind: str, qualifiers: list[str]) -> str:
    """*kind*, then *qualifiers* in brackets if there are any, as in property[settable, deletable]."""
    return f"{kind}[{', '.join(qualifiers)}]" if qualifiers else kind


def _refuse_immutable_type(cls: type) -> None:
    """Raise TypeError naming *cls* if it is an immutable type."""
    if _is_immutable_type(cls):
        raise TypeError(
            f"{_label(cls)} is an immutable type, so no class statement holds an __init__ "
            "or __post_init__ to read: pass a class that a class statement defines"
        )


def _attributes_set_on_self(cls: type, reviewed: Collection[str]) -> set[str]:
    """The public attributes that the __init__ and __post_init__ *cls*'s own body defines set on their receiver, each one's first parameter.

    Each is read whole, a closure in it included. An attribute is set by any assignment
    to it on the receiver, or by setattr(receiver, "name", value),
    <expr>.__setattr__(receiver, "name", value), receiver.__setattr__("name", value) or
    super().__setattr__("name", value), whose name is a string constant.

    A write names no attribute the scan can read if it is one of those calls with any
    other name, such as a variable, an f-string or a starred argument, or a reach into
    the receiver's __dict__, as receiver.__dict__ in any context or as vars(receiver).
    Such a write raises TypeError naming *cls* and the write's source, as ast.unparse
    spells it, unless *reviewed* holds that source. Then a text in *reviewed* that is no
    such write's source raises ValueError.
    """
    writes = [
        write
        for initialiser in _initialisers(cls)
        for write in _writes_to_receiver(initialiser)
    ]
    _refuse_unreviewed(cls, {write.source for write in writes if write.name is None}, reviewed)
    names = {write.name for write in writes if write.name is not None}
    return {name for name in names if not name.startswith("_")}


def _refuse_unreviewed(cls: type, unnamed: set[str], reviewed: Collection[str]) -> None:
    """Raise TypeError if *reviewed* is one string, not a collection of write texts; then TypeError naming each source in *unnamed*, *cls*'s writes to self that name no attribute, that *reviewed* lacks; then ValueError naming each text in *reviewed* that *unnamed* lacks."""
    if isinstance(reviewed, str):
        raise TypeError(
            f"reviewed must be a collection of write texts, not one string: {reviewed!r}"
        )
    unreviewed = unnamed - set(reviewed)
    if unreviewed:
        raise TypeError(
            f"{cls.__qualname__} sets attributes on self under names the scan cannot "
            f"read:{_listed(unreviewed)}\nGive each name as a string constant, as in "
            'object.__setattr__(self, "name", value); or, once a reviewer has checked that '
            "every name such a write sets is declared, pass the write's text in reviewed."
        )
    stale = set(reviewed) - unnamed
    if stale:
        raise ValueError(
            f"{cls.__qualname__} makes none of these reviewed writes to self:"
            f"{_listed(stale)}\nDrop each from reviewed."
        )


def _listed(texts: set[str]) -> str:
    """*texts* in sorted order, each on a line of its own, indented."""
    return "".join(f"\n  {text}" for text in sorted(texts))


_INITIALISERS: tuple[str, ...] = ("__init__", "__post_init__")


def _initialisers(cls: type) -> list[ast.FunctionDef]:
    """The __init__ and __post_init__ statements of *cls*'s own body, never another method nor anything a class nested in it defines."""
    match ast.parse(_class_source(cls)).body:
        case [ast.ClassDef(body=body)]:
            return [
                statement
                for statement in body
                if isinstance(statement, ast.FunctionDef) and statement.name in _INITIALISERS
            ]
    raise TypeError(f"inspect.getsource({cls.__qualname__}) is not a single class statement")


def _class_source(cls: type) -> str:
    """*cls*'s source, dedented, read only once _defining_module has looked *cls*'s module up, since inspect.getsource finds a class's file through sys.modules by the name its __module__ records; TypeError naming *cls* if inspect can read no class statement for it."""
    _defining_module(cls)
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError) as unread:
        raise TypeError(
            f"{_label(cls)} has no class statement inspect can read, so the scan has no "
            "__init__ or __post_init__ to read: pass a class that a class statement in a "
            "source file defines"
        ) from unread
    return textwrap.dedent(source)


@dataclasses.dataclass(frozen=True)
class _SelfWrite:
    """A write an initialiser makes to its receiver: the attribute it sets, None if its source names none the scan can read, and its source as ast.unparse spells it."""

    name: str | None
    source: str


def _writes_to_receiver(function: ast.FunctionDef) -> Iterator[_SelfWrite]:
    """Each write *function* makes to its receiver, its first positional parameter, anywhere in it; none if it takes no positional parameter."""
    positional = [*function.args.posonlyargs, *function.args.args]
    if not positional:
        return
    receiver = positional[0].arg
    for node in ast.walk(function):
        write = _write_to(receiver, node)
        if write is not None:
            yield write


def _write_to(receiver: str, node: ast.AST) -> _SelfWrite | None:
    """The write *node* makes to *receiver*, if it is one in a spelling _attributes_set_on_self reads."""
    match node:
        case ast.Attribute(value=ast.Name(id=owner), attr="__dict__") if owner == receiver:
            return _SelfWrite(None, ast.unparse(node))
        case ast.Call(func=ast.Name(id="vars"), args=[ast.Name(id=owner)]) if owner == receiver:
            return _SelfWrite(None, ast.unparse(node))
        case ast.Attribute(value=ast.Name(id=owner), attr=name, ctx=ast.Store()) if owner == receiver:
            return _SelfWrite(name, ast.unparse(node))
        case ast.Call(
            func=ast.Name(id="setattr") | ast.Attribute(attr="__setattr__"),
            args=[ast.Name(id=owner), named, *_],
        ) if owner == receiver:
            return _SelfWrite(_constant_name(named), ast.unparse(node))
        case ast.Call(
            func=ast.Attribute(value=ast.Name(id=owner), attr="__setattr__"),
            args=[named, *_],
        ) if owner == receiver:
            return _SelfWrite(_constant_name(named), ast.unparse(node))
        case ast.Call(
            func=ast.Attribute(value=ast.Call(func=ast.Name(id="super")), attr="__setattr__"),
            args=[named, *_],
        ):
            return _SelfWrite(_constant_name(named), ast.unparse(node))
    return None


def _constant_name(named: ast.expr) -> str | None:
    """The name *named* gives, if it is a string constant; None for any other expression, whose value the source does not show."""
    match named:
        case ast.Constant(value=str() as name):
            return name
    return None
