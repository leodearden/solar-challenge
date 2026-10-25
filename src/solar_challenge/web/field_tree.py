# SPDX-License-Identifier: AGPL-3.0-or-later
"""A dataclass's field tree in JSON, written by field_tree and read back strictly by read_field_tree, as the class's annotations declare.

A field tree is a dataclass's fields as a JSON object, each value in its JSON form: a dataclass
as an object, a list or tuple as an array, a dict as an object of its keys, a pd.Timestamp as
its ISO text. read_field_tree reads one strictly: each JSON value must be one its field's
annotation can be, and the dataclass built from them must accept them. A key no field has, a
missing field that has no default, a value of a JSON type its annotation cannot be (an object
for a dataclass, an array for a sequence, a number but no bool for a number, null only for an
Optional field, one of a Literal's values), an unknown union tag, or a dataclass that refuses
its values is refused with a FieldTreeRefused naming the value's dotted path, with [i] for an
item and None for the root, and the reason. A missing field that has a default takes it.
without_unknown_keys drops each key the reader would refuse as one no field has, reporting each
as an UnknownKey.

The module imports no solar_challenge module. web/stored_runs.py writes and reads a run's
documents through it, and its StoredDocument.read maps a FieldTreeRefused to a
StoredRunUnreadable.
"""

import functools
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass
from types import MappingProxyType, UnionType
from typing import Any, Literal, TypeVar, Union, get_args, get_origin, get_type_hints

import pandas as pd

T = TypeVar("T")


def field_tree(obj: Any) -> dict[str, Any]:
    """Serialize a dataclass instance to a JSON-compatible dict.

    Each field is emitted as _field_tree_value emits it.

    Args:
        obj: Dataclass instance to serialize

    Returns:
        JSON-compatible dictionary
    """
    if not is_dataclass(obj):
        raise TypeError(f"Expected dataclass, got {type(obj)}")

    return {
        field_info.name: _field_tree_value(getattr(obj, field_info.name))
        for field_info in fields(obj)
    }


def _field_tree_value(value: Any) -> Any:
    """Emit one value in its JSON-compatible form.

    A dataclass becomes a dict. A pd.Timestamp becomes its ISO string. A list or
    tuple becomes a list, and a dict keeps its keys, with every item serialized the
    same way. Anything else, None included, is returned unchanged.
    """
    if is_dataclass(value):
        return field_tree(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_field_tree_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _field_tree_value(item) for key, item in value.items()}
    return value


class FieldTreeRefused(Exception):
    """A value the strict reader refuses within one document: its dotted path, None for the document's root, and the reason."""

    def __init__(self, path: str | None, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class UnknownKey:
    """A key without_unknown_keys dropped, as no field of its object's dataclass has it: its dotted path and its value."""

    path: str
    value: Any


def read_field_tree(content: Any, cls: type[T]) -> T:
    """The *cls*, a dataclass, whose field tree *content*, decoded JSON, is, each value read as its field's annotation declares.

    Raises:
        FieldTreeRefused: *content* holds a key no field has, lacks a field that has no
            default, holds a value of a JSON type its annotation cannot be or an unknown union
            tag, or a dataclass refuses its values, whose refusal is then the cause.
    """
    value = _read_value(content, cls, None)
    assert isinstance(value, cls)
    return value


def without_unknown_keys(content: Any, cls: type) -> tuple[Any, tuple[UnknownKey, ...]]:
    """*content*, decoded JSON read as a *cls*, without each key no field of its dataclass has; and each dropped key, in the content's order.

    It is walked as _without_unknown_keys walks it, and is not itself changed.
    """
    return _without_unknown_keys(content, cls, None)


def _read_value(value: Any, annotation: Any, path: str | None) -> Any:
    """*value*, decoded JSON at *path* in its document, read as *annotation* declares.

    A union is read by _read_union. A dataclass is read from an object by _read_dataclass, a
    list or tuple from an array by _read_sequence, a dict's values from an object, a
    pd.Timestamp from its ISO text. A Literal, bool, int, float and str admit only values of
    their JSON type; an int or a float is any number but a bool, kept as decoded. Any admits
    anything as it is.

    Raises:
        FieldTreeRefused: *value* cannot be *annotation*, or *annotation* has no stored form.
    """
    origin = get_origin(annotation)
    if annotation is Any:
        return value
    if origin in (Union, UnionType):
        return _read_union(value, annotation, path)
    if value is None:
        raise FieldTreeRefused(path, f"is null, not {_stored_form(annotation)}")
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _read_dataclass(value, annotation, path)
    if origin in (list, tuple):
        return _read_sequence(value, annotation, path)
    if origin is dict:
        if not isinstance(value, dict):
            raise FieldTreeRefused(path, f"is {_json_value(value)}, not an object")
        value_annotation = _value_annotation(annotation)
        return {key: _read_value(item, value_annotation, _child(path, key)) for key, item in value.items()}
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in get_args(annotation)):
            return value
    elif annotation is bool:
        if isinstance(value, bool):
            return value
    elif annotation in (int, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    elif annotation is str:
        if isinstance(value, str):
            return value
    elif isinstance(annotation, type) and issubclass(annotation, pd.Timestamp):
        if isinstance(value, str):
            try:
                return pd.Timestamp(value)
            except ValueError as refusal:
                raise FieldTreeRefused(path, f"is {_json_value(value)}, not a timestamp: {refusal}") from refusal
    else:
        raise FieldTreeRefused(path, f"has no stored form: the stored-run format reads no {annotation!r}")
    raise FieldTreeRefused(path, f"is {_json_value(value)}, not {_stored_form(annotation)}")


def _read_union(value: Any, annotation: Any, path: str | None) -> Any:
    """*value* read as union *annotation*: null only when None is a member, else as the member _union_member picks.

    Raises:
        FieldTreeRefused: *value* is null and None is no member; its members tag themselves and it is
            no object, or its tag names no member, refused at the tag's path; or the member
            refuses it.
    """
    if value is None:
        if type(None) in get_args(annotation):
            return None
        raise FieldTreeRefused(path, f"is null, not {_stored_form(annotation)}")
    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    tag_field = _shared_tag_field(members)
    if tag_field is None:
        return _read_value(value, _union_member(annotation, value), path)
    if not isinstance(value, dict):
        raise FieldTreeRefused(path, f"is {_json_value(value)}, not an object")
    try:
        member = _union_member(annotation, value)
    except ValueError as unknown_tag:
        tags = [_tags(each)[tag_field] for each in members]
        stored = "missing" if tag_field not in value else repr(value[tag_field])
        raise FieldTreeRefused(_child(path, tag_field), f"is {stored}, not one of {tags}") from unknown_tag
    return _read_value(value, member, path)


def _read_dataclass(value: Any, cls: type, path: str | None) -> Any:
    """The *cls* the object *value* holds, each field read as its annotation declares.

    A field with a default that *value* lacks takes it. A field no constructor takes, a
    union's tag, is read as its annotation but not passed to *cls*.

    Raises:
        FieldTreeRefused: *value* is no object; it holds a key no field has, the first such key's path;
            it lacks a field with no default; a field's value is refused; or *cls* refuses the
            values with a ValueError or TypeError, the cause, at *path*.
    """
    if not isinstance(value, dict):
        raise FieldTreeRefused(path, f"is {_json_value(value)}, not an object, as a {cls.__name__} is stored")
    cls_fields = fields(cls)
    names = {each.name for each in cls_fields}
    for key in value:
        if key not in names:
            raise FieldTreeRefused(_child(path, key), f"is not a field of {cls.__name__}")
    field_types = _field_types(cls)
    kwargs: dict[str, Any] = {}
    for each in cls_fields:
        if each.name not in value:
            if each.init and each.default is MISSING and each.default_factory is MISSING:
                raise FieldTreeRefused(_child(path, each.name), f"is missing, and {cls.__name__} has no default for it")
            continue
        item = _read_value(value[each.name], field_types[each.name], _child(path, each.name))
        if each.init:
            kwargs[each.name] = item
    try:
        return cls(**kwargs)
    except (ValueError, TypeError) as refusal:
        raise FieldTreeRefused(path, f"is refused by {cls.__name__}: {refusal}") from refusal


def _read_sequence(value: Any, annotation: Any, path: str | None) -> Any:
    """The list or tuple *annotation* declares, read from the array *value*.

    A fixed tuple, as tuple[int, int], reads an array of exactly its arity, each item by
    position; list[X] and tuple[X, ...] read each item as X.

    Raises:
        FieldTreeRefused: *value* is no array, a fixed tuple's array has another length, or an item is refused.
    """
    if not isinstance(value, list):
        raise FieldTreeRefused(path, f"is {_json_value(value)}, not an array")
    item_annotations = _item_annotations(annotation, len(value))
    if item_annotations is None:
        raise FieldTreeRefused(path, f"holds {len(value)} items, not the {len(get_args(annotation))} of a {annotation!r}")
    items = [
        _read_value(item, item_annotation, _item(path, index))
        for index, (item, item_annotation) in enumerate(zip(value, item_annotations, strict=True))
    ]
    return tuple(items) if get_origin(annotation) is tuple else items


def _without_unknown_keys(value: Any, annotation: Any, path: str | None) -> tuple[Any, tuple[UnknownKey, ...]]:
    """*value*, decoded JSON at *path* in its document, without each key no field of its dataclass has; and each dropped key, an UnknownKey.

    *value* is walked as _read_value reads it: an object read as a dataclass keeps the keys its
    fields name, its tag's included; a union's value is walked as the member _union_member
    picks; an array's items and an object's values are walked as their annotations declare. A
    value of a JSON type its annotation cannot be, or of a tag no member of its union has, is
    kept as it is, for the strict reader to refuse. *value* itself is not changed.
    """
    origin = get_origin(annotation)
    if value is None:
        return value, ()
    if origin in (Union, UnionType):
        try:
            member = _union_member(annotation, value)
        except ValueError:
            return value, ()
        return _without_unknown_keys(value, member, path)
    if isinstance(annotation, type) and is_dataclass(annotation) and isinstance(value, dict):
        names = {each.name for each in fields(annotation)}
        field_types = _field_types(annotation)
        kept: dict[str, Any] = {}
        dropped: list[UnknownKey] = []
        for key, item in value.items():
            if key in names:
                kept[key], dropped_within = _without_unknown_keys(item, field_types[key], _child(path, key))
                dropped.extend(dropped_within)
            else:
                dropped.append(UnknownKey(_child(path, key), item))
        return kept, tuple(dropped)
    if origin in (list, tuple) and isinstance(value, list):
        item_annotations = _item_annotations(annotation, len(value))
        if item_annotations is None:
            return value, ()
        walked = [
            _without_unknown_keys(item, item_annotation, _item(path, index))
            for index, (item, item_annotation) in enumerate(zip(value, item_annotations, strict=True))
        ]
        return [item for item, _ in walked], tuple(each for _, dropped_within in walked for each in dropped_within)
    if origin is dict and isinstance(value, dict):
        value_annotation = _value_annotation(annotation)
        walked_values = {
            key: _without_unknown_keys(item, value_annotation, _child(path, key)) for key, item in value.items()
        }
        return (
            {key: item for key, (item, _) in walked_values.items()},
            tuple(each for _, dropped_within in walked_values.values() for each in dropped_within),
        )
    return value, ()


def _child(path: str | None, name: str) -> str:
    """The dotted path of field or key *name* of the object at *path*, None being the document's root."""
    return name if path is None else f"{path}.{name}"


def _item(path: str | None, index: int) -> str:
    """The path of item *index* of the array at *path*, None being the document's root."""
    return f"{'' if path is None else path}[{index}]"


def _json_value(value: Any) -> str:
    """*value*, decoded JSON, as a refusal names it: its JSON type, and a scalar's value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"the number {value!r}"
    if isinstance(value, str):
        return f"the string {value!r}"
    return "an array" if isinstance(value, list) else "an object"


def _stored_form(annotation: Any) -> str:
    """What JSON value *annotation* is stored as, as a refusal names it."""
    origin = get_origin(annotation)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return f"an object, as a {annotation.__name__} is stored"
    if origin in (list, tuple):
        return "an array"
    if origin is dict:
        return "an object"
    if origin is Literal:
        return f"one of {list(get_args(annotation))}"
    if origin in (Union, UnionType):
        return " or ".join(_stored_form(arg) for arg in get_args(annotation))
    if annotation is bool:
        return "true or false"
    if annotation in (int, float):
        return "a number"
    return "a string"


@functools.cache
def _field_types(cls: type) -> Mapping[str, Any]:
    """Return the type each field of dataclass *cls* is annotated with.

    Resolved once per class and shared by every later call, so the mapping is read-only.

    Raises:
        NameError: An annotation names a type cls's module does not bind.
    """
    return MappingProxyType(get_type_hints(cls))


def _union_member(annotation: Any, value: Any) -> Any:
    """The member of union *annotation* a stored, non-null *value* is rebuilt as.

    When the union's non-None members are dataclasses that each tag themselves with the
    same field, the member is the one whose tag is *value*'s; otherwise it is the first
    non-None member.

    Raises:
        ValueError: For members tagged with a field when no member's tag is *value*'s,
            naming the field, *value*'s value of it and the members' tags.
    """
    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    tag_field = _shared_tag_field(members)
    if tag_field is None:
        return next(iter(members), Any)
    tags = [_tags(member)[tag_field] for member in members]
    stored = value.get(tag_field) if isinstance(value, dict) else None
    if stored not in tags:
        raise ValueError(f"{tag_field} {stored!r} is not one of {tags}")
    return members[tags.index(stored)]


def _shared_tag_field(members: Sequence[Any]) -> str | None:
    """The one field each of *members* tags itself with; None when they share no such field, or more than one."""
    shared = set.intersection(*(set(_tags(member)) for member in members)) if members else set()
    return shared.pop() if len(shared) == 1 else None


def _tags(cls: Any) -> dict[str, Any]:
    """Each field of *cls*, a dataclass, that tags it: no constructor takes it and it is annotated with a one-value Literal, with that value.

    Empty for anything other than a dataclass.
    """
    if not (isinstance(cls, type) and is_dataclass(cls)):
        return {}
    field_types = _field_types(cls)
    return {
        each.name: get_args(field_types[each.name])[0]
        for each in fields(cls)
        if not each.init
        and get_origin(field_types[each.name]) is Literal
        and len(get_args(field_types[each.name])) == 1
    }


def _item_annotation(sequence_annotation: Any) -> Any:
    """Return the annotation shared by every item of list[X], tuple[X, ...] or tuple[X, X].

    Any when the items do not share one annotation, as in tuple[A, B].
    """
    item_annotations = {arg for arg in get_args(sequence_annotation) if arg is not Ellipsis}
    return item_annotations.pop() if len(item_annotations) == 1 else Any


def _item_annotations(sequence_annotation: Any, length: int) -> tuple[Any, ...] | None:
    """The annotation of each of the *length* items of an array stored as *sequence_annotation*.

    A fixed tuple, as tuple[int, int], annotates each item by position, and is None for an array
    of another length; list[X] and tuple[X, ...] annotate each item X.
    """
    args = get_args(sequence_annotation)
    if get_origin(sequence_annotation) is tuple and args and args[-1] is not Ellipsis:
        return args if length == len(args) else None
    return (_item_annotation(sequence_annotation),) * length


def _value_annotation(dict_annotation: Any) -> Any:
    """The annotation of each value of dict[K, V], V; Any for a bare dict."""
    args = get_args(dict_annotation)
    return args[1] if args else Any
