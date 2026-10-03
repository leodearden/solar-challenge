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

Usage::

    from tests._surface_forms import surface_form

    def scale(values: Optional[List[float]], factor: float = 1.0) -> "Series": ...

    assert surface_form(scale) == "(values: list[float] | None, factor: float = 1.0) -> Series"
    assert surface_form({"peak": 0.3}) == "dict"
"""

import enum
import inspect
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
