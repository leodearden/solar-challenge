# SPDX-License-Identifier: AGPL-3.0-or-later
"""The surface form of a public name: the text that pins what its callers rely on.

A surface form reads the same on every Python minor that requires-python admits, which
inspect's own rendering does not. surface_form spells a name's form. member_forms spells
the forms of the public members a class's own body defines or declares. named_classes
gives the classes those forms name, and signature_closure the classes of a package that
some names' forms name, directly or through another such class. member_forms reads class
bodies, so undeclared_attributes and unset_attributes check the attributes a class
declares against those its own __init__ and __post_init__ set on self.

tests/unit/surface_forms_helper/test_<function>.py pins each function's rules, one rule
per test.

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
from collections.abc import Callable, Collection, Iterable, Iterator


def surface_form(obj: object) -> str:
    """The surface form of *obj*.

    An Enum's is its members, as NAME=value in definition order. A constant's, that of
    anything neither a class nor a routine, is its type's qualified name; a
    functools.partial is a routine on every admitted minor, as inspect counts one from
    3.14. Any other class's or routine's is its signature, a class's being its
    constructor's without self and a partial's the one it leaves of the callable it wraps.
    A dataclass's signature follows its kind: dataclass, then in brackets those of eq,
    order, unsafe_hash and frozen that are on, whether set on the class or on the base it
    inherits them from. An annotation in that signature which it has no rule for, such as
    a type alias, raises TypeError naming it and its type.

    A class whose constructor inspect reads differently by minor raises TypeError naming
    it and the class in its MRO holding that constructor, unless it carries a signature,
    which inspect reads in that constructor's place; so does a routine that wraps such a
    class, through a functools.partial, a bound method or a functools.wraps wrapper,
    unless the class or one of the routine's links carries one. A signature is an
    inspect.Signature as __signature__, which inspect reads as given. Any other
    __signature__ counts as none for these refusals, since Python 3.12 and 3.13 convert a
    string or call a callable given there and 3.11 and 3.14 refuse either.
    _refuse_minor_dependent_constructor lists the constructors it refuses.

    A routine whose signature inspect cannot read raises TypeError naming it and its
    kind: one that is not callable, as no functools.partialmethod or
    functools.singledispatchmethod is; a descriptor defined in Python that neither
    wraps a callable, as functools.wraps records one, nor carries a signature; or a
    routine that wraps such a descriptor, which the TypeError names too, with its kind.
    """
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
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
    surface_form(cls) already pins: the dataclass fields and init-only variables its
    constructor's signature takes, and an Enum's members. The attributes the body
    declares come first, in annotation order, then the other names it defines, in
    class-body order. A ClassVar annotation declares a class variable, not an instance
    attribute; a string annotation is read as named_classes reads one, so a name its
    module does not bind raises NameError, and a module another of the same name has
    replaced in sys.modules raises LookupError. A public member that no member rule
    spells and that is a routine whose signature inspect cannot read, as surface_form
    describes one, raises TypeError naming *cls*, the member and its kind.
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
    NameError. A routine is spelled in the module whose globals it carries, whatever
    module its __module__ names; a functools.partial, a bound method, or a routine that
    wraps another callable as functools.wraps records one, where that callable is,
    whatever __signature__ the wrapper carries; an object its class makes callable,
    where the __call__ that class resolves is, which may be a base's in another module;
    and a class in the one sys.modules holds under the name its __module__ records. One
    whose module another of the same name has since replaced in sys.modules raises
    LookupError naming it and the module found there, and one whose module has since
    left sys.modules, LookupError naming it and that module's name. A signature that
    annotates nothing, as that of each routine CPython defines in C such as str.join,
    names no class, and no module is looked up for it. Met again
    inside its own evaluation in the same module, as each
    "JSON" is in JSON = Union[dict[str, "JSON"], list["JSON"], str, None], a string names
    no class there: that evaluation names them all.
    An annotation none of these rules reads, such as a type alias, raises TypeError
    naming it and its type; a class whose constructor surface_form refuses, a routine
    surface_form reads as such a class, or a routine whose signature inspect cannot read
    raises the TypeError surface_form raises for it, and a class with a member
    member_forms refuses, the TypeError member_forms raises for it.
    A class's constructor is spelled in the module of the class in its MRO whose own body
    defines __init__ or __new__, which may be a base defined in another module; a
    parameter of an __init__ the dataclass decorator generated, in the module of the
    nearest class in that MRO the decorator processed whose own body annotates it, so an
    inherited field in the base that declares it, however a mixin annotates it. A
    signature a class carries in its constructor's place is spelled where that
    constructor is, or where the class holding the signature is if object or a class
    defined in C holds the constructor; one its metaclass or a descriptor gives raises
    TypeError. What a type variable or a NewType carries is spelled in the module that
    declares it; inside its own declaration, as in
    TypeVar("T", bound="Node[T]"), it names no class. A type parameter, as in
    def f[T: "Node"](x: T), reports no module of its own: what it carries is spelled in
    the module that spells the signature holding it. That module binds no type
    parameter, so a string that names one, as "Node[T]" names T, raises NameError. A
    constant names its type, and an Enum's members name nothing.
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
    class with no class statement inspect can read, such as ast.AST, raises TypeError
    naming it when its source is read.

    A write to self whose attribute name the scan cannot read, such as
    setattr(self, name, value) or a reach into self.__dict__, raises TypeError naming
    *cls* and the write's text, unless *reviewed* holds that text; a text in *reviewed*
    that is no such write's raises ValueError. *reviewed* is a collection of such texts:
    one string given in its place raises TypeError.

    A string annotation in any of those class bodies is read as named_classes reads one,
    so a name its module does not bind raises NameError. Like those annotations, *cls*'s
    source is read from its own module only, so a module another of the same name has
    replaced in sys.modules raises LookupError.
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
    sys.modules raises LookupError.

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


class _Construct(abc.ABC):
    """An annotation parsed as the construct it is, the annotations inside it parsed in turn: the one grammar both its spelling and the classes it names are read by."""

    @abc.abstractmethod
    def text(self) -> str:
        """The spelling, alike on every admitted minor."""

    @abc.abstractmethod
    def classes(self, module: types.ModuleType) -> set[type]:
        """The classes it names, a name in it resolved in *module*."""


@dataclasses.dataclass(frozen=True)
class _Unevaluated(_Construct):
    """A string annotation or a forward reference: spelled as written, naming the classes of the annotation it evaluates to, read inside the declarations and evaluations that enclose it where it is written; inside its own evaluation in the same module it names no class."""

    source: str
    enclosing: _Enclosing

    def text(self) -> str:
        return self.source

    def classes(self, module: types.ModuleType) -> set[type]:
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

    def classes(self, module: types.ModuleType) -> set[type]:
        return set(self.named)


@dataclasses.dataclass(frozen=True)
class _Union(_Construct):
    """A union: spelled by its members with bars, naming its members' classes alone."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return " | ".join(member.text() for member in self.members)

    def classes(self, module: types.ModuleType) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Subscripted(_Construct):
    """An origin and its arguments: spelled origin[arguments], origin[()] with none, naming the classes of both."""

    origin: _Construct
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        inside = _texts_of(self.arguments) if self.arguments else "()"
        return f"{self.origin.text()}[{inside}]"

    def classes(self, module: types.ModuleType) -> set[type]:
        return self.origin.classes(module) | _classes_of(self.arguments, module)


@dataclasses.dataclass(frozen=True)
class _ParameterTypes(_Construct):
    """A Callable's list of parameter types: spelled in brackets, naming its members' classes."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return f"[{_texts_of(self.members)}]"

    def classes(self, module: types.ModuleType) -> set[type]:
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

    def classes(self, module: types.ModuleType) -> set[type]:
        return _classes_of(self.arguments, module if self.module is None else self.module)


@dataclasses.dataclass(frozen=True)
class _Keyword(_Construct):
    """An annotation a declaration passes by keyword: spelled keyword=annotation, naming its classes."""

    keyword: str
    annotation: _Construct

    def text(self) -> str:
        return f"{self.keyword}={self.annotation.text()}"

    def classes(self, module: types.ModuleType) -> set[type]:
        return self.annotation.classes(module)


def _texts_of(constructs: Iterable[_Construct]) -> str:
    return ", ".join(construct.text() for construct in constructs)


def _classes_of(constructs: Iterable[_Construct], module: types.ModuleType) -> set[type]:
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
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
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


def _is_class_or_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a class or a routine, the objects surface_form spells, an Enum aside, by their signature rather than by their type."""
    return inspect.isclass(obj) or _is_routine(obj)


def _is_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a routine as inspect.isroutine reads one from Python 3.14, on every admitted minor: before 3.14 inspect counts no functools.partial as one."""
    return inspect.isroutine(obj) or isinstance(obj, functools.partial)


def _signature(obj: Callable[..., object]) -> inspect.Signature:
    """The signature inspect reads for *obj*, a class or a routine, once _refuse_minor_dependent_constructor has passed the class at the end of the chain inspect follows from *obj*, if it ends at one that carries no signature.

    A routine whose signature inspect cannot read, as _unreadable_link finds one, raises
    the TypeError _unreadable_routine_error gives for it, before anything else is read.
    """
    link = _unreadable_link(obj)
    if link is not None:
        raise _unreadable_routine_error(_label(obj), obj, link)
    end = _chain_end(obj, stop=_carries_signature)
    if inspect.isclass(end) and not _carries_signature(end):
        _refuse_minor_dependent_constructor(end)
    return inspect.signature(obj)


def _chain_end(
    obj: Callable[..., object], stop: Callable[[object], bool] | None = None
) -> Callable[..., object]:
    """The end of the chain inspect follows from *obj*, the callable whose own signature it reads: through a bound method's __func__, else the callables a wrapper records as __wrapped__, else a functools.partial's func, ending early at the first object *stop* holds of."""
    if isinstance(obj, types.MethodType):
        return _chain_end(obj.__func__, stop)
    unwrapped: Callable[..., object] = inspect.unwrap(obj, stop=stop)
    if unwrapped is not obj:
        return _chain_end(unwrapped, stop)
    if isinstance(obj, functools.partial) and (stop is None or not stop(obj)):
        return _chain_end(obj.func, stop)
    return obj


def _carries_signature(obj: object) -> bool:
    """Whether *obj* carries a signature: an inspect.Signature as its __signature__, the one value inspect.signature reads as given on every admitted minor, whatever *obj* is or wraps.

    Any other __signature__ is none: None, or a string or a callable, which Python 3.12
    and 3.13 convert or call and 3.11 and 3.14 refuse.
    """
    return isinstance(getattr(obj, "__signature__", None), inspect.Signature)


def _unreadable_link(obj: object) -> object | None:
    """The link of the chain inspect follows from *obj* at which it fails to read a signature, if *obj* is a routine whose signature it cannot read; None otherwise.

    That link is *obj* itself if it is not callable, as no functools.partialmethod or
    functools.singledispatchmethod is, since inspect checks that before it follows any
    chain. Else it is the end of the chain, as _chain_end follows it, if that is a
    routine whose class defines __get__ in Python and that carries no signature, which
    inspect reads as a builtin, by a text signature only a routine defined in C gives.
    """
    if not _is_routine(obj):
        return None
    if not callable(obj):
        return obj
    end = _chain_end(obj, stop=_carries_signature)
    getter = inspect.getattr_static(type(end), "__get__", None)
    if _is_routine(end) and isinstance(getter, types.FunctionType) and not _carries_signature(end):
        return end
    return None


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


_C_CONSTRUCTOR_KINDS = (types.BuiltinFunctionType, types.WrapperDescriptorType)


def _refuse_minor_dependent_constructor(cls: type) -> None:
    """Raise TypeError naming *cls* and the class holding its constructor if inspect reads that constructor differently by minor.

    The constructors it refuses, in the order it checks them:

    - the __call__ *cls*'s metaclass resolves, which inspect looks up before any __new__
      or __init__, if it wraps a callable defined in C;
    - the constructor inspect reads first of those the holder's own namespace holds, if
      it wraps a callable defined in C, as the __new__ warnings.deprecated writes for a
      class wraps object.__new__;
    - a functools.partial the holder's own namespace holds as __init__, unless that
      namespace also holds a __new__ not defined in C, which inspect reads first;
    - the constructor of a holder other than object that _constructed_in_c counts as
      defined in C.
    """
    metaclass = type(cls)
    _refuse_wrapper_of_c_callable(
        cls, metaclass, "__call__", inspect.getattr_static(metaclass, "__call__")
    )
    holder = _constructor_holder(cls)
    name, constructor = _first_read_constructor(holder)
    _refuse_wrapper_of_c_callable(cls, holder, name, constructor)
    if name == "__init__" and isinstance(constructor, functools.partial):
        raise TypeError(
            f"{_label(cls)} is constructed through {_label(holder)}.__init__, a "
            "functools.partial, which Python 3.14 binds to the instance as a method and "
            "earlier minors call without it: define __init__ with def"
        )
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
    """Raise TypeError naming *cls*, *owner*'s *name* and the callable defined in C if *constructor*, the one *owner* holds as *name* that inspect reads first for *cls*, wraps one.

    inspect reads such a wrapper through that callable on some Python releases, and skips
    it as defined in C on others, reading the next constructor instead.
    """
    if isinstance(constructor, _C_CONSTRUCTOR_KINDS) or not callable(constructor):
        return
    wrapped = inspect.unwrap(constructor, stop=_carries_signature)
    if isinstance(wrapped, _C_CONSTRUCTOR_KINDS):
        raise TypeError(
            f"{_label(cls)} is constructed through {_label(owner)}.{name}, which wraps "
            f"{wrapped.__qualname__}, defined in C: inspect reads such a wrapper through "
            "that callable on some Python releases and skips it as defined in C on "
            f"others: make the name private, or define {name} with def, wrapping no "
            "callable defined in C"
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


def _spelling_modules(
    obj: Callable[..., object], names: Iterable[str]
) -> dict[str, types.ModuleType]:
    """The module whose source spells the annotation inspect.signature(*obj*) gives each of *names*, parameter names or "return".

    A routine's is that of the end of its chain, which _chain_end follows through to
    where inspect.get_annotations finds the namespace of a wrapper's annotations. If
    that end is an object its class makes callable, it is read as the __call__ its
    class resolves, from which inspect derives its signature. A __signature__ a wrapper
    carries does not change that: it records no module. A class's is that of the class
    holding its constructor; but for a generated __init__, that of the nearest class in
    the holder's MRO that the dataclass decorator processed and whose own body
    annotates the name, or the holder's if none does. _signature_holder checks every
    class that carries a signature, and if _constructed_in_c counts the holder, which
    spells no annotation, the class's is that of the class _signature_holder gives.
    """
    end = _chain_end(obj)
    if not inspect.isclass(end):
        if not _is_routine(end):
            return _spelling_modules(type(end).__call__, names)
        return dict.fromkeys(names, _defining_module(end))
    holder = _constructor_holder(end)
    if _carries_signature(end):
        signature_holder = _signature_holder(end)
        if _constructed_in_c(holder):
            return dict.fromkeys(names, _defining_module(signature_holder))
    if not _holds_generated_init(holder):
        return dict.fromkeys(names, _defining_module(holder))
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


def _holds_generated_init(cls: type) -> bool:
    """Whether the constructor inspect.signature reads in *cls*'s own namespace is an __init__ the dataclass decorator generated.

    The decorator compiles that __init__ outside the class body and renames it into the
    class, so its code keeps another qualified name; one the body defines, wrapped or
    not, keeps its own. What the body assigns that is no function, such as a callable
    object, the decorator never generated. A __new__ the body defines is read first and
    is never generated.
    """
    if not _is_decorated_dataclass(cls) or "__new__" in vars(cls):
        return False
    init: object = inspect.unwrap(vars(cls)["__init__"])
    return isinstance(init, types.FunctionType) and init.__code__.co_qualname != init.__qualname__


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
    routine that carries no globals, as a routine CPython defines in C carries none,
    records nothing to check its module by, so the one its __module__ names is looked up
    unchecked.
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

    A class defined outside any function must be bound there under its qualified name; for
    one defined inside a function, the module's globals must be those the first function
    its body compiled carries. Otherwise, as once another module of the same name has
    replaced its own in sys.modules, LookupError names *cls* and the module found. An
    immutable type carries no source or annotation to misread, and a class inside a
    function whose body compiled no function carries nothing to check it by, so their
    module is looked up unchecked.
    """
    module = _module_named(cls.__module__, cls)
    if _is_immutable_type(cls):
        return module
    if "<locals>" in cls.__qualname__:
        function = _function_compiled_in_body(cls)
        if function is not None and function.__globals__ is not vars(module):
            raise _defined_elsewhere(_label(cls), function.__globals__, module, cls.__module__)
        return module
    bound = _bound_under(cls.__qualname__, module)
    if bound is not cls:
        raise LookupError(
            f"{_label(cls)} is not bound under {cls.__qualname__!r} in "
            f"the module at {getattr(module, '__file__', None)}, which sys.modules holds under "
            f"the name {cls.__module__!r}: that module binds "
            f"{'nothing' if bound is None else 'another object'} there. Read each module's "
            "objects before importing another module of that name, or bind the class under "
            "its qualified name"
        )
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
    """The first function *cls*'s own body compiled, read through _spelled_function and unwrapped from any decorator that records it as __wrapped__: one whose code's qualified name is *cls*'s dotted with the code's name; None if the body compiled none, as an annotation-only body compiles none, and as the dataclass decorator and EnumType compile the functions they add elsewhere."""
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
    """*annotation* evaluated in a copy of *module*'s globals, with the imports of its top-level `if TYPE_CHECKING:` blocks run over them."""
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


def _pinned_by_class_form(cls: type) -> set[str]:
    """The names member_forms leaves to surface_form(cls): an Enum's members, or each dataclass field its constructor takes."""
    if issubclass(cls, enum.Enum):
        return set(cls.__members__)
    if dataclasses.is_dataclass(cls):
        return _fields(cls).keys() & _constructor_parameters(cls)
    return set()


def _fields(cls: type) -> dict[str, dataclasses.Field[object]]:
    """*cls*'s dataclass fields by name, inherited ones included; none if *cls* is no dataclass."""
    if not dataclasses.is_dataclass(cls):
        return {}
    return {field.name: field for field in dataclasses.fields(cls)}


def _constructor_parameters(cls: type) -> set[str]:
    """The names of the parameters of *cls*'s constructor that surface_form(cls) spells, self excluded."""
    return set(_signature(cls).parameters)


def _defaulted_fields(cls: type) -> set[str]:
    """The names of *cls*'s dataclass fields with a default, which instances read from the class, or a default factory, which the generated __init__ calls."""
    return {
        name
        for name, field in _fields(cls).items()
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
    return (annotated & _constructor_parameters(cls)) - _fields(cls).keys()


@dataclasses.dataclass(frozen=True)
class _AnnotatedAttribute:
    """The annotation of a name a class body declares as an instance attribute, by annotating it alone or as a dataclass field."""

    annotation: object


def _public_members(cls: type) -> dict[str, object]:
    """The members member_forms(cls) spells, by name: the public names *cls*'s own body defines or declares, less those surface_form(cls) pins.

    A member that _spelled_function has no rule for and whose signature inspect cannot
    read, as _unreadable_link finds one, raises the TypeError _unreadable_routine_error
    gives for it, naming *cls* and the member.
    """
    pinned = _pinned_by_class_form(cls)
    members = {
        name: member
        for name, member in _own_members(cls).items()
        if not name.startswith("_") and name not in pinned
    }
    for name, member in members.items():
        link = _unreadable_link(member)
        if link is not None and _spelled_function(member) is None:
            raise _unreadable_routine_error(f"{_label(cls)}.{name}", member, link)
    return members


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
    class_values = vars(cls).keys() - _fields(cls).keys()
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
