# SPDX-License-Identifier: AGPL-3.0-or-later
"""The surface form of a public name: the text that pins what its callers rely on.

A class's or a routine's surface form is its signature: its parameters' names, kinds,
defaults and annotations, and its return annotation. A class's signature is its
constructor's. An Enum's surface form is its members, and a constant's is its type.

A surface form is spelled identically on every Python minor that requires-python admits,
because inspect's own rendering is not. Measured: 3.11 renders an Enum's call signature
unlike 3.12, 3.13 renders pathlib.Path as pathlib._local.Path, and 3.14 renders an
evaluated Optional[X] as X | None. So inspect lays out the signature, and each annotation
is respelled: a union with bars, a typing alias by its builtin origin (a bare one, as
List is, by that origin alone), an empty subscription, as tuple[()] is, with
parentheses, a class by its qualified name without its module, Callable's parameter
types as a bracketed list, and a forward reference, a string inside a generic included,
by its name. A string annotation is spelled verbatim, never evaluated. Literal's values
and Annotated's metadata are values, not annotations: each is spelled by its repr, so
Literal['a'] never reads as Literal[a]. A ParamSpec's args and kwargs are spelled by
their repr as well, P.args and P.kwargs, which keeps the two apart.

A class's public members, the methods, properties and class constants its own body
defines, and the attributes it only annotates, have forms too. A method's form is its
signature, self included. A classmethod, staticmethod, property or cached_property is
spelled by its kind, then its function's signature, and a constant by its type. An
attribute the body only annotates, as an instance attribute is declared, is spelled
attribute, then its annotation. A ClassVar annotation declares a class variable, not an
attribute, so its name is a member only if the body assigns it a value, as a constant.
A property that can be set or deleted says so in its kind, as property[settable,
deletable] does, and an abstract member's form begins with abstract. An inherited
member belongs to the class that defines it.

member_forms reads class bodies, so it sees an instance attribute only once a body
declares it. undeclared_attributes names each public attribute a class's own source
sets on self, by assignment or, as a frozen dataclass must, by object.__setattr__, that
no class body in its MRO defines or declares; unset_attributes names each declared
attribute member_forms lists that the source never sets, which instances would lack.

Usage::

    from tests._surface_forms import member_forms, surface_form, undeclared_attributes

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
    assert undeclared_attributes(Meter) == {"label"}
"""

import ast
import dataclasses
import enum
import functools
import inspect
import textwrap
import types
import typing
from collections.abc import Iterable


def surface_form(obj: object) -> str:
    """The surface form of *obj*.

    An Enum's is its members, as NAME=value in definition order. A constant's, that of
    anything neither a class nor a routine, is its type's qualified name. Any other
    class's or routine's is its signature, a class's being its constructor's without self.
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
    attribute by annotating it alone, except those surface_form(cls) already pins: a
    dataclass's fields, which its constructor's signature carries, and an Enum's
    members. The names the body only annotates come first, in annotation order, then
    the names it defines, in class-body order.
    """
    pinned = _pinned_by_class_form(cls)
    return {
        name: _member_form(member)
        for name, member in _own_members(cls).items()
        if not name.startswith("_") and name not in pinned
    }


def undeclared_attributes(cls: type) -> set[str]:
    """The public attributes *cls*'s own source sets on self that no class body in its MRO defines or declares."""
    declared = {name for base in cls.__mro__ for name in _own_members(base)}
    return _attributes_set_on_self(cls) - declared


def unset_attributes(cls: type) -> set[str]:
    """The attributes member_forms(cls) lists as declared that *cls*'s own source never sets on self."""
    declared = member_forms(cls).keys() & _declared_attributes(cls).keys()
    return declared - _attributes_set_on_self(cls)


class _Spelling(str):
    """An annotation's spelling, which inspect prints unquoted, as it prints an annotation it does not know by its repr."""

    def __repr__(self) -> str:
        return str(self)


def _spelled(annotation: object) -> object:
    if annotation is inspect.Parameter.empty:
        return annotation
    return _Spelling(_annotation_text(annotation))


def _annotation_text(annotation: object) -> str:
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, typing.ForwardRef):
        return annotation.__forward_arg__
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is Ellipsis:
        return "..."
    if isinstance(annotation, list):
        return f"[{_annotations_text(annotation)}]"
    if _is_bare_alias(annotation):
        return _annotation_text(typing.get_origin(annotation))
    if isinstance(annotation, (typing.ParamSpecArgs, typing.ParamSpecKwargs)):
        return repr(annotation)
    if typing.get_origin(annotation) is not None:
        return _subscripted_text(annotation)
    if inspect.isclass(annotation):
        return annotation.__qualname__
    return repr(annotation)


def _is_bare_alias(annotation: object) -> bool:
    """Bare List: a class as origin, and no __args__ at all.

    Not tuple[()], whose __args__ is (), nor P.args, whose origin is no class.
    """
    has_class_origin = inspect.isclass(typing.get_origin(annotation))
    return has_class_origin and not hasattr(annotation, "__args__")


def _subscripted_text(annotation: object) -> str:
    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_annotation_text(argument) for argument in arguments)
    if origin is typing.Literal:
        return f"Literal[{_values_text(arguments)}]"
    if origin is typing.Annotated:
        annotated, *metadata = arguments
        return f"Annotated[{_annotation_text(annotated)}, {_values_text(metadata)}]"
    if not arguments:
        return f"{_annotation_text(origin)}[()]"
    return f"{_annotation_text(origin)}[{_annotations_text(arguments)}]"


def _annotations_text(annotations: Iterable[object]) -> str:
    return ", ".join(_annotation_text(annotation) for annotation in annotations)


def _values_text(values: Iterable[object]) -> str:
    return ", ".join(repr(value) for value in values)


def _pinned_by_class_form(cls: type) -> set[str]:
    if issubclass(cls, enum.Enum):
        return set(cls.__members__)
    if dataclasses.is_dataclass(cls):
        return {field.name for field in dataclasses.fields(cls)}
    return set()


@dataclasses.dataclass(frozen=True)
class _AnnotatedAttribute:
    """The annotation of a name a class body only annotates, as an instance attribute is declared."""

    annotation: object


def _own_members(cls: type) -> dict[str, object]:
    """Each attribute *cls*'s own body declares, as an _AnnotatedAttribute, then each name it defines, as its value."""
    declared = {
        name: _AnnotatedAttribute(annotation)
        for name, annotation in _declared_attributes(cls).items()
    }
    return {**declared, **vars(cls)}


def _declared_attributes(cls: type) -> dict[str, object]:
    """The annotation of each attribute *cls*'s own body declares, by name: each name it only annotates, other than as a ClassVar.

    inspect.get_annotations reads the body's own annotations, never a base's, and leaves
    a string annotation a string.
    """
    defined = vars(cls)
    return {
        name: annotation
        for name, annotation in inspect.get_annotations(cls).items()
        if name not in defined and not _is_class_var(annotation)
    }


def _is_class_var(annotation: object) -> bool:
    """Whether *annotation* is ClassVar, bare or subscripted, which declares a class variable, not an instance attribute."""
    return annotation is typing.ClassVar or typing.get_origin(annotation) is typing.ClassVar


def _member_form(member: object) -> str:
    form = _form_by_kind(member)
    if getattr(member, "__isabstractmethod__", False):
        return f"abstract {form}"
    return form


def _form_by_kind(member: object) -> str:
    match member:
        case classmethod() | staticmethod():
            return f"{type(member).__name__} {surface_form(member.__func__)}"
        case property():
            return f"{_property_kind(member)} {surface_form(member.fget)}"
        case functools.cached_property():
            return f"cached_property {surface_form(member.func)}"
        case _AnnotatedAttribute(annotation=annotation):
            return f"attribute {_annotation_text(annotation)}"
        case _:
            return surface_form(member)


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
