# SPDX-License-Identifier: AGPL-3.0-or-later
"""The surface form of a public name: the text that pins what its callers rely on.

A surface form reads the same on every Python minor that requires-python admits, which
inspect's own rendering does not. surface_form spells a name's form. member_forms spells
the forms of the public members a class's own body defines or declares. named_classes
gives the classes those forms name, and signature_closure the classes of a package that
some names' forms name, directly or through another such class. member_forms reads class
bodies, so undeclared_attributes and unset_attributes check the attributes a class
declares against those its own source sets on self.

tests/unit/test_surface_forms_helper.py pins each function's rules, one rule per test.

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
from collections.abc import Iterable


def surface_form(obj: object) -> str:
    """The surface form of *obj*.

    An Enum's is its members, as NAME=value in definition order. A constant's, that of
    anything neither a class nor a routine, is its type's qualified name. Any other
    class's or routine's is its signature, a class's being its constructor's without self.
    An annotation in that signature which it has no rule for, such as a type alias, raises
    TypeError naming it and its type.
    """
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        return ", ".join(f"{member.name}={member.value!r}" for member in obj)
    if not (inspect.isclass(obj) or inspect.isroutine(obj)):
        return type(obj).__qualname__
    signature = inspect.signature(obj)
    return str(
        signature.replace(
            parameters=[
                parameter.replace(annotation=_spelled(parameter.annotation))
                for parameter in signature.parameters.values()
            ],
            return_annotation=_spelled(signature.return_annotation),
        )
    )


def member_forms(cls: type) -> dict[str, str]:
    """The form of each public member of *cls*, by name.

    A member is a public name that *cls*'s own body defines, or declares as an instance
    attribute by annotating it alone or as a dataclass field, except those
    surface_form(cls) already pins: the dataclass fields and init-only variables its
    constructor's signature takes, and an Enum's members. The attributes the body
    declares come first, in annotation order, then the other names it defines, in
    class-body order. A ClassVar annotation declares a class variable, not an instance
    attribute; a string annotation is read as named_classes reads one, so a name its
    module does not bind raises NameError.
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
    NameError. Met again inside its own evaluation in the same module, as each "JSON" is
    in JSON = Union[dict[str, "JSON"], list["JSON"], str, None], a string names no class
    there: that evaluation names them all.
    An annotation none of these rules reads, such as a type alias, raises TypeError
    naming it and its type. A class's constructor is spelled in the module of the class
    in its MRO whose own body defines __init__ or __new__, which may be a base defined in
    another module. What a type variable or a NewType carries is spelled in the module
    that declares it; inside its own declaration, as in TypeVar("T", bound="Node[T]"), it
    names no class. A type parameter, as in def f[T: "Node"](x: T), reports no module of
    its own: what it carries is spelled in the module that spells the signature holding
    it. That module binds no type parameter, so a string that names one, as "Node[T]"
    names T, raises NameError. A constant names its type, and an Enum's members name
    nothing.
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


def undeclared_attributes(cls: type) -> set[str]:
    """The public attributes *cls*'s own source sets on self that no class body in its MRO defines or declares.

    A string annotation in any of those class bodies is read as named_classes reads one,
    so a name its module does not bind raises NameError.
    """
    declared = {name for base in cls.__mro__ for name in _own_members(base)}
    return _attributes_set_on_self(cls) - declared


def unset_attributes(cls: type) -> set[str]:
    """The attributes member_forms(cls) lists as declared that instances would lack: those *cls*'s own source never sets on self, less each dataclass field with a default or a default factory, whose value the dataclass supplies.

    A string annotation in *cls*'s own body is read as named_classes reads one, so a name
    its module does not bind raises NameError.

    A known gap: a default factory counts as called by the generated __init__, so a field
    with one that a hand-written __init__ skips goes unreported, though instances lack it.
    """
    declared = member_forms(cls).keys() & _declared_attributes(cls).keys()
    return declared - _attributes_set_on_self(cls) - _defaulted_fields(cls)


class _Spelling(str):
    """An annotation's spelling, which inspect prints unquoted, as it prints an annotation it does not know by its repr."""

    def __repr__(self) -> str:
        return str(self)


def _spelled(annotation: object) -> object:
    if annotation is inspect.Parameter.empty:
        return annotation
    return _Spelling(_parsed(annotation, frozenset()).text())


class _Construct(abc.ABC):
    """An annotation parsed as the construct it is, the annotations inside it parsed in turn: the one grammar both its spelling and the classes it names are read by."""

    @abc.abstractmethod
    def text(self) -> str:
        """The spelling, alike on every admitted minor."""

    @abc.abstractmethod
    def classes(self, module: str) -> set[type]:
        """The classes it names, a name in it resolved in *module*."""


@dataclasses.dataclass(frozen=True)
class _Unevaluated(_Construct):
    """A string annotation or a forward reference: spelled as written, naming the classes of the annotation it evaluates to, read inside the declarations and evaluations that enclose it where it is written; inside its own evaluation in the same module it names no class."""

    source: str
    enclosing: frozenset[object]

    def text(self) -> str:
        return self.source

    def classes(self, module: str) -> set[type]:
        evaluation = _Evaluation(self.source, module)
        if evaluation in self.enclosing:
            return set()
        evaluated = _evaluated(self.source, module)
        return _parsed(evaluated, self.enclosing | {evaluation}).classes(module)


@dataclasses.dataclass(frozen=True)
class _Evaluation:
    """A string evaluated in a module, held in *enclosing* while what it evaluates to is read, so that the same string met again there, in the same module, names no class."""

    source: str
    module: str


@dataclasses.dataclass(frozen=True)
class _Leaf(_Construct):
    """A part read whole, an annotation or a value inside one: spelled as given, naming the classes it carries."""

    spelling: str
    named: frozenset[type] = frozenset()

    def text(self) -> str:
        return self.spelling

    def classes(self, module: str) -> set[type]:
        return set(self.named)


@dataclasses.dataclass(frozen=True)
class _Union(_Construct):
    """A union: spelled by its members with bars, naming its members' classes alone."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return " | ".join(member.text() for member in self.members)

    def classes(self, module: str) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Subscripted(_Construct):
    """An origin and its arguments: spelled origin[arguments], origin[()] with none, naming the classes of both."""

    origin: _Construct
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        inside = _texts_of(self.arguments) if self.arguments else "()"
        return f"{self.origin.text()}[{inside}]"

    def classes(self, module: str) -> set[type]:
        return self.origin.classes(module) | _classes_of(self.arguments, module)


@dataclasses.dataclass(frozen=True)
class _ParameterTypes(_Construct):
    """A Callable's list of parameter types: spelled in brackets, naming its members' classes."""

    members: tuple[_Construct, ...]

    def text(self) -> str:
        return f"[{_texts_of(self.members)}]"

    def classes(self, module: str) -> set[type]:
        return _classes_of(self.members, module)


@dataclasses.dataclass(frozen=True)
class _Declared(_Construct):
    """A type variable or a NewType: spelled by its name, then in parentheses the annotations its declaration passes, if any; naming their classes alone, a name in them resolved in the module that declares it, or, where none is known, in the module that spells the signature holding it."""

    name: str
    module: str | None
    arguments: tuple[_Construct, ...]

    def text(self) -> str:
        if not self.arguments:
            return self.name
        return f"{self.name}({_texts_of(self.arguments)})"

    def classes(self, module: str) -> set[type]:
        return _classes_of(self.arguments, module if self.module is None else self.module)


@dataclasses.dataclass(frozen=True)
class _Keyword(_Construct):
    """An annotation a declaration passes by keyword: spelled keyword=annotation, naming its classes."""

    keyword: str
    annotation: _Construct

    def text(self) -> str:
        return f"{self.keyword}={self.annotation.text()}"

    def classes(self, module: str) -> set[type]:
        return self.annotation.classes(module)


def _texts_of(constructs: Iterable[_Construct]) -> str:
    return ", ".join(construct.text() for construct in constructs)


def _classes_of(constructs: Iterable[_Construct], module: str) -> set[type]:
    return set().union(*(construct.classes(module) for construct in constructs))


_CLASSLESS_NAME_KINDS: tuple[type, ...] = (
    typing.ParamSpecArgs,
    typing.ParamSpecKwargs,
    typing._SpecialForm,
)

_TYPE_VARIABLE_KINDS: tuple[type, ...] = (
    typing.TypeVar,
    typing.ParamSpec,
    typing.TypeVarTuple,
)


def _parsed(annotation: object, enclosing: frozenset[object]) -> _Construct:
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
    if isinstance(annotation, _TYPE_VARIABLE_KINDS):
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


def _parsed_type_variable(
    variable: typing.TypeVar | typing.ParamSpec | typing.TypeVarTuple,
    enclosing: frozenset[object],
) -> _Declared:
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
        arguments.append(_Keyword("default", _parsed(variable.__default__, inside)))
    return _Declared(repr(variable), module, tuple(arguments))


def _declaring_module(
    variable: typing.TypeVar | typing.ParamSpec | typing.TypeVarTuple,
) -> str | None:
    """The module *variable*'s __module__ names; None if that is typing, which a type parameter (`def f[T]`) reports in place of the module of the routine or class that declares it."""
    return None if variable.__module__ == "typing" else variable.__module__


def _parsed_new_type(new_type: typing.NewType, enclosing: frozenset[object]) -> _Declared:
    """*new_type* by its qualified name, as a class is spelled, then its supertype, read inside its declaration; its name alone if that declaration encloses it."""
    if new_type in enclosing:
        return _Declared(new_type.__qualname__, new_type.__module__, ())
    supertype = _parsed(new_type.__supertype__, enclosing | {new_type})
    return _Declared(new_type.__qualname__, new_type.__module__, (supertype,))


def _parsed_subscription(annotation: object, enclosing: frozenset[object]) -> _Construct:
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
    annotations: Iterable[object], enclosing: frozenset[object]
) -> tuple[_Construct, ...]:
    return tuple(_parsed(annotation, enclosing) for annotation in annotations)


def _value_leaves(values: Iterable[object]) -> tuple[_Leaf, ...]:
    """The values inside an annotation, a Literal's values and an Annotated's metadata: each spelled by its repr, naming no class."""
    return tuple(_Leaf(repr(value)) for value in values)


def _form_classes(obj: object) -> set[type]:
    """The classes surface_form(obj) names: none for an Enum, a constant's type, else those its signature's annotations name."""
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        return set()
    if not (inspect.isclass(obj) or inspect.isroutine(obj)):
        return {type(obj)}
    signature = inspect.signature(obj)
    annotations = [parameter.annotation for parameter in signature.parameters.values()]
    annotations.append(signature.return_annotation)
    annotated = (
        annotation
        for annotation in annotations
        if annotation is not inspect.Parameter.empty
    )
    return _classes_of(_each_parsed(annotated, frozenset()), _signature_module(obj))


def _signature_module(obj: object) -> str:
    """The module whose source spells inspect.signature(*obj*)'s annotations: a routine's own; for a class, that of the class in its MRO whose own body defines __init__ or __new__."""
    if not inspect.isclass(obj):
        return obj.__module__
    return next(
        base.__module__
        for base in obj.__mro__
        if "__init__" in vars(base) or "__new__" in vars(base)
    )


def _member_form_classes(member: object, cls: type) -> set[type]:
    """The classes the form of *member*, one of *cls*'s, names."""
    if isinstance(member, _AnnotatedAttribute):
        return _parsed(member.annotation, frozenset()).classes(cls.__module__)
    function = _spelled_function(member)
    return _form_classes(member if function is None else function)


def _evaluated(annotation: str, module: str) -> object:
    """*annotation* evaluated in a copy of *module*'s globals, with the imports of its top-level `if TYPE_CHECKING:` blocks run over them."""
    namespace = dict(vars(sys.modules[module]))
    exec(_type_checking_imports(module), namespace)
    return eval(annotation, namespace)


@functools.cache
def _type_checking_imports(module: str) -> types.CodeType:
    """The Import and ImportFrom statements of *module*'s top-level `if TYPE_CHECKING:` blocks, compiled, so running them binds each name as Python binds it."""
    imports: list[ast.stmt] = []
    for node in ast.parse(inspect.getsource(sys.modules[module])).body:
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
    return compile(ast.Module(body=imports, type_ignores=[]), module, "exec")


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
    return set(inspect.signature(cls).parameters)


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
        if not _is_class_var(annotation, cls.__module__)
    }
    return (annotated & _constructor_parameters(cls)) - _fields(cls).keys()


@dataclasses.dataclass(frozen=True)
class _AnnotatedAttribute:
    """The annotation of a name a class body declares as an instance attribute, by annotating it alone or as a dataclass field."""

    annotation: object


def _public_members(cls: type) -> dict[str, object]:
    """The members member_forms(cls) spells, by name: the public names *cls*'s own body defines or declares, less those surface_form(cls) pins."""
    pinned = _pinned_by_class_form(cls)
    return {
        name: member
        for name, member in _own_members(cls).items()
        if not name.startswith("_") and name not in pinned
    }


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
        if name not in class_values and not _is_class_var(annotation, cls.__module__)
    }


def _is_class_var(annotation: object, module: str) -> bool:
    """Whether *annotation* is ClassVar, bare or subscripted, which declares a class variable, not an instance attribute; a string annotation is evaluated as named_classes evaluates one, in *module*."""
    if isinstance(annotation, str):
        return _is_class_var(_evaluated(annotation, module), module)
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
    return f"property[{', '.join(abilities)}]" if abilities else "property"


def _attributes_set_on_self(cls: type) -> set[str]:
    """The public attributes *cls*'s own source sets on self.

    A frozen dataclass can set one only by object.__setattr__(self, "name", value), so
    that call counts as setting it too.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(cls)))):
        match node:
            case ast.Attribute(value=ast.Name(id="self"), attr=name, ctx=ast.Store()):
                names.add(name)
            case ast.Call(
                func=ast.Attribute(value=ast.Name(id="object"), attr="__setattr__"),
                args=[ast.Name(id="self"), ast.Constant(value=str() as name), *_],
            ):
                names.add(name)
    return {name for name in names if not name.startswith("_")}
