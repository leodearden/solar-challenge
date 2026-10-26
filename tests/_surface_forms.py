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
__init__.py says which module holds which. This module reads signatures through
tests/_surface_forms_signatures.py, and both look modules up through
tests/_surface_forms_module_lookup.py.

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
import inspect
import textwrap
import types
import typing
from collections.abc import Callable, Collection, Iterable, Iterator

from tests._surface_forms_module_lookup import (
    defining_module,
    evaluated_in,
    is_immutable_type,
    is_routine,
    label_of,
    spelled_function,
)
from tests._surface_forms_signatures import (
    ModuleOrUnspelled,
    Unspelled,
    is_decorated_dataclass,
    is_enum,
    namespace_holders,
    refuse_member_without_a_portable_form,
    signature_of,
    spelling_modules,
)


def surface_form(obj: object) -> str:
    """The surface form of *obj*.

    An Enum's is its members, as NAME=value in definition order. A constant's, that of
    anything neither a class nor a routine, is its type's qualified name; a
    functools.partial is a routine on every admitted minor, and any other descriptor
    whose type defines __get__ and __delete__ but no __set__ is no routine on any. Any
    other class's or routine's is its signature, a class's being its constructor's
    without self and a partial's the one it leaves of the callable it wraps.
    A class's constructor is the __call__ its metaclass resolves if that is not defined
    in C, which inspect reads before any __new__ or __init__, else the __new__ or
    __init__ it reads. A dataclass's signature follows its kind: dataclass, then in
    brackets those of eq, order, unsafe_hash and frozen that are on, whether set on the
    class or on the base it inherits them from. An annotation in that signature which it
    has no rule for, such as a type alias, raises TypeError naming it and its type.

    A class whose constructor inspect reads differently by minor, or cannot read on any,
    and a routine whose signature inspect reads differently by minor, raise TypeError
    naming what inspect reads that way and saying what to do instead. A signature, an
    inspect.Signature as __signature__, which inspect reads as given, lifts each of
    these refusals when the class or routine itself carries it.
    docs/surface-forms-inspect-readings.md says how each minor reads the objects this
    docstring names, where else a signature lifts each refusal, and which rule tests pin
    each rule; signature_of in tests/_surface_forms_signatures.py reads the signature
    and says which constructors it refuses.

    A routine whose signature inspect cannot read raises TypeError naming it and its
    kind: one that is not callable, as no functools.partialmethod or
    functools.singledispatchmethod is; a descriptor defined in Python whose
    __signature__ is None, or that lacks a __signature__ and records no __wrapped__,
    as functools.wraps records one, since inspect then reads it as itself; or a
    routine that inspect reads through such a descriptor, which the TypeError names
    too, with its kind.
    """
    if is_enum(obj):
        return ", ".join(f"{member.name}={member.value!r}" for member in obj)
    if not _is_class_or_routine(obj):
        return type(obj).__qualname__
    signature = signature_of(obj)
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
    whose signature inspect cannot read, as surface_form describes one, or a
    functools.partial whose type takes __get__ from a class other than functools.partial
    and defines no __set__, which inspect reads as a builtin on Python 3.11 and 3.12
    alone, raises TypeError naming *cls*, the member and its kind; any other that is a
    functools.partial, which Python 3.14 binds to the instance as a method and earlier
    minors call without it, raises TypeError naming *cls*, the member and that binding.
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
    carries a __signature__ of None, where its annotations were
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
    __call__ its metaclass resolves if inspect reads that, as spelling_modules in
    tests/_surface_forms_signatures.py says, whether or not the class carries a
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


class _Construct(abc.ABC):
    """An annotation parsed as the construct it is, the annotations inside it parsed in turn: the one grammar both its spelling and the classes it names are read by."""

    @abc.abstractmethod
    def text(self) -> str:
        """The spelling, alike on every admitted minor."""

    @abc.abstractmethod
    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        """The classes it names, a name in it resolved in *module*; a string raises TypeError where *module* is Unspelled, as no module is known to spell it."""


@dataclasses.dataclass(frozen=True)
class _Unevaluated(_Construct):
    """A string annotation or a forward reference: spelled as written, naming the classes of the annotation it evaluates to, read inside the declarations and evaluations that enclose it where it is written; inside its own evaluation in the same module it names no class."""

    source: str
    enclosing: _Enclosing

    def text(self) -> str:
        return self.source

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        if isinstance(module, Unspelled):
            raise module.refusal(self.source)
        evaluation = _Evaluation(self.source, module)
        if evaluation in self.enclosing:
            return set()
        evaluated = evaluated_in(self.source, module)
        return _parsed(evaluated, self.enclosing | {evaluation}).classes(module)


@dataclasses.dataclass(frozen=True)
class _Leaf(_Construct):
    """A part read whole, an annotation or a value inside one: spelled as given, naming the classes it carries."""

    spelling: str
    named: frozenset[type] = frozenset()

    def text(self) -> str:
        return self.spelling

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        return set(self.named)


@dataclasses.dataclass(frozen=True)
class _Union(_Construct):
    """A union: spelled by its members with bars, naming its members' classes alone."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return " | ".join(member.text() for member in self.members)

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Subscripted(_Construct):
    """An origin and its arguments: spelled origin[arguments], origin[()] with none, naming the classes of both."""

    origin: _Construct
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        inside = _texts_of(self.arguments) if self.arguments else "()"
        return f"{self.origin.text()}[{inside}]"

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        return self.origin.classes(module) | _classes_of(self.arguments, module)


@dataclasses.dataclass(frozen=True)
class _ParameterTypes(_Construct):
    """A Callable's list of parameter types: spelled in brackets, naming its members' classes."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return f"[{_texts_of(self.members)}]"

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
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

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        return _classes_of(self.arguments, module if self.module is None else self.module)


@dataclasses.dataclass(frozen=True)
class _Keyword(_Construct):
    """An annotation a declaration passes by keyword: spelled keyword=annotation, naming its classes."""

    keyword: str
    annotation: _Construct

    def text(self) -> str:
        return f"{self.keyword}={self.annotation.text()}"

    def classes(self, module: ModuleOrUnspelled) -> set[type]:
        return self.annotation.classes(module)


def _texts_of(constructs: Iterable[_Construct]) -> str:
    return ", ".join(construct.text() for construct in constructs)


def _classes_of(constructs: Iterable[_Construct], module: ModuleOrUnspelled) -> set[type]:
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
    return None if variable.__module__ == "typing" else defining_module(variable)


def _parsed_new_type(new_type: typing.NewType, enclosing: _Enclosing) -> _Declared:
    """*new_type* by its qualified name, as a class is spelled, then its supertype, read inside its declaration; its name alone if that declaration encloses it."""
    qualified_name = new_type.__qualname__  # type: ignore[attr-defined]  # typeshed's NewType omits the __qualname__ its __init__ sets
    module = defining_module(new_type)
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
    if is_enum(obj):
        return set()
    if not _is_class_or_routine(obj):
        return {type(obj)}
    annotations = _signature_annotations(signature_of(obj))
    if not annotations:
        return set()
    modules = spelling_modules(obj, annotations)
    return set().union(
        *(
            _parsed(annotation, frozenset()).classes(modules[name])
            for name, annotation in annotations.items()
        )
    )


def _is_class_or_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a class or a routine, the objects surface_form spells, an Enum aside, by their signature rather than by their type."""
    return inspect.isclass(obj) or is_routine(obj)


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


def _member_form_classes(member: object, cls: type) -> set[type]:
    """The classes the form of *member*, one of *cls*'s, names."""
    if isinstance(member, _AnnotatedAttribute):
        return _parsed(member.annotation, frozenset()).classes(defining_module(cls))
    function = spelled_function(member)
    return _form_classes(member if function is None else function)


def _pinned_by_class_form(cls: type) -> set[str]:
    """The names member_forms leaves to surface_form(cls): an Enum's members, each dataclass field its constructor takes, or each named tuple field it takes that instances read from the tuple."""
    if is_enum(cls):
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
        if "_fields" in vars(next(namespace_holders(cls.__mro__, name, "_fields")))
    }


def _constructor_parameters(cls: type) -> set[str]:
    """The names of the parameters of *cls*'s constructor that surface_form(cls) spells, self excluded."""
    return set(signature_of(cls).parameters)


def _defaulted_fields(cls: type) -> set[str]:
    """The names of *cls*'s dataclass fields with a default, which instances read from the class, or a default factory, which the generated __init__ calls."""
    return {
        name
        for name, field in _dataclass_fields(cls).items()
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    }


def _init_only_variables(cls: type) -> set[str]:
    """The names of the dataclass init-only variables *cls*'s own body declares: those it annotates, other than as a ClassVar, that its constructor takes but that are no dataclass fields."""
    if not is_decorated_dataclass(cls):
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

    A member that spelled_function has no rule for raises the TypeError
    refuse_member_without_a_portable_form raises for it, if any, naming *cls* and the
    member.
    """
    pinned = _pinned_by_class_form(cls)
    members = {
        name: member
        for name, member in _own_members(cls).items()
        if not name.startswith("_") and name not in pinned
    }
    for name, member in members.items():
        if spelled_function(member) is None:
            refuse_member_without_a_portable_form(f"{label_of(cls)}.{name}", member)
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
    class_values = vars(cls).keys() - _dataclass_fields(cls).keys()
    return {
        name: annotation
        for name, annotation in inspect.get_annotations(cls).items()
        if name not in class_values and not _is_class_var(annotation, cls)
    }


def _is_class_var(annotation: object, cls: type) -> bool:
    """Whether *annotation*, which *cls*'s own body declares, is ClassVar, bare or subscripted, which declares a class variable, not an instance attribute; a string annotation is evaluated as named_classes evaluates one, in *cls*'s module."""
    if isinstance(annotation, str):
        return _is_class_var(evaluated_in(annotation, defining_module(cls)), cls)
    return annotation is typing.ClassVar or typing.get_origin(annotation) is typing.ClassVar


def _member_form(member: object) -> str:
    form = _form_by_kind(member)
    if getattr(member, "__isabstractmethod__", False):
        return f"abstract {form}"
    return form


def _form_by_kind(member: object) -> str:
    if isinstance(member, _AnnotatedAttribute):
        return f"attribute {_parsed(member.annotation, frozenset()).text()}"
    function = spelled_function(member)
    if function is None:
        return surface_form(member)
    if isinstance(member, property):
        return f"{_property_kind(member)} {surface_form(function)}"
    return f"{type(member).__name__} {surface_form(function)}"


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
    if is_immutable_type(cls):
        raise TypeError(
            f"{label_of(cls)} is an immutable type, so no class statement holds an __init__ "
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
    """*cls*'s source, dedented, read only once defining_module has looked *cls*'s module up, since inspect.getsource finds a class's file through sys.modules by the name its __module__ records; TypeError naming *cls* if inspect can read no class statement for it."""
    defining_module(cls)
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError) as unread:
        raise TypeError(
            f"{label_of(cls)} has no class statement inspect can read, so the scan has no "
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
