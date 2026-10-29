# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field-tree codec of web/field_tree.py: a dataclass written as its field tree in JSON, read back strictly, and stripped of the keys no field has.

field_tree writes a dataclass's field tree. read_field_tree reads one back as its class's
annotations declare, refusing a value with a FieldTreeRefused that names the value's dotted path,
with [i] for an item and None for the root, and the reason. without_unknown_keys drops each key
the reader refuses as one no field has, reporting each as an UnknownKey. The tests drive those
names over this module's dataclasses, which hold every shape the codec reads, shapes no stored
dataclass has today included: a list, a dict of dataclasses, a pd.Timestamp and Any. The
agreement test pins the drop to the reader: a key no field has, added to each dataclass's object,
is refused by the reader at exactly the path where the drop reports it.
"""

import copy
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import pandas as pd
import pytest

from solar_challenge.web.field_tree import (
    FieldTreeRefused,
    UnknownKey,
    field_tree,
    read_field_tree,
    without_unknown_keys,
)

Keys = tuple[str | int, ...]


@dataclass(frozen=True)
class _Point:
    """A dataclass with a field that has a default."""

    x: float
    y: float = 0.0


@dataclass(frozen=True)
class _FlatRate:
    """One variant of a tagged union: its kind, which no constructor takes, tags it."""

    rate: float
    kind: Literal["flat"] = field(default="flat", init=False)


@dataclass(frozen=True)
class _SteppedRate:
    """The other variant of that union, holding a tuple of fixed tuples."""

    steps: tuple[tuple[int, int], ...]
    kind: Literal["stepped"] = field(default="stepped", init=False)


@dataclass(frozen=True)
class _Positive:
    """A dataclass that refuses a value with a ValueError."""

    value: float

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError(f"value must be positive, got {self.value}")


@dataclass(frozen=True)
class _EveryShape:
    """A dataclass with a field of every shape the codec reads."""

    point: _Point
    optional_point: _Point | None
    rate: _FlatRate | _SteppedRate
    pair: tuple[int, int]
    points: tuple[_Point, ...]
    names: list[str]
    by_name: dict[str, _Point]
    weights: dict[str, float]
    shade: Literal["light", "dark"]
    flag: bool
    count: int
    ratio: float
    label: str
    at: pd.Timestamp
    anything: Any
    positive: _Positive
    note: str | None = None


@dataclass(frozen=True)
class _Unstored:
    """A dataclass with a field of an annotation the codec has no stored form for."""

    numbers: set[int]


_EVERY = _EveryShape(
    point=_Point(1.0, 2.0),
    optional_point=_Point(7.0),
    rate=_SteppedRate(((16, 19),)),
    pair=(1, 2),
    points=(_Point(3.0), _Point(4.0, 5.0)),
    names=["north", "south"],
    by_name={"a": _Point(6.0)},
    weights={"w": 0.5},
    shade="dark",
    flag=True,
    count=3,
    ratio=0.25,
    label="every shape",
    at=pd.Timestamp("2024-06-01T09:00:00+01:00"),
    anything={"free": [1, {"x": None}]},
    positive=_Positive(2.0),
    note="every field set",
)
"""An _EveryShape with every field set."""

_TREE = json.loads(json.dumps(field_tree(_EVERY)))
"""_EVERY's field tree, as JSON text decodes it."""


def _at(content: Any, keys: Sequence[str | int]) -> Any:
    """The value *content* holds at *keys*, a key or an index per level; *content* itself for no keys."""
    for key in keys:
        content = content[key]
    return content


def _with_value(content: Any, keys: Keys, value: Any) -> Any:
    """A copy of *content* holding *value* at *keys*, a key or an index per level."""
    edited = copy.deepcopy(content)
    *parents, last = keys
    _at(edited, parents)[last] = value
    return edited


def _without(content: Any, keys: Keys) -> Any:
    """A copy of *content* lacking the key at *keys*, a key or an index per level."""
    edited = copy.deepcopy(content)
    *parents, last = keys
    del _at(edited, parents)[last]
    return edited


def _refusal(content: Any, cls: type) -> FieldTreeRefused:
    """The FieldTreeRefused with which read_field_tree refuses *content* as a *cls*."""
    with pytest.raises(FieldTreeRefused) as refused:
        read_field_tree(content, cls)
    return refused.value


def _nested_array(depth: int) -> list[Any]:
    """An array holding an array, *depth* arrays deep, built in Python, so no JSON decoder's nesting limit applies."""
    array: list[Any] = []
    for _ in range(depth - 1):
        array = [array]
    return array


def test_field_tree_writes_a_dataclass_as_the_json_tree_of_its_fields() -> None:
    """A dataclass becomes an object, its tag included; a tuple or a list an array; a dict keeps its keys; a pd.Timestamp becomes its ISO text; None stays None."""
    assert field_tree(_EVERY) == {
        "point": {"x": 1.0, "y": 2.0},
        "optional_point": {"x": 7.0, "y": 0.0},
        "rate": {"steps": [[16, 19]], "kind": "stepped"},
        "pair": [1, 2],
        "points": [{"x": 3.0, "y": 0.0}, {"x": 4.0, "y": 5.0}],
        "names": ["north", "south"],
        "by_name": {"a": {"x": 6.0, "y": 0.0}},
        "weights": {"w": 0.5},
        "shade": "dark",
        "flag": True,
        "count": 3,
        "ratio": 0.25,
        "label": "every shape",
        "at": "2024-06-01T09:00:00+01:00",
        "anything": {"free": [1, {"x": None}]},
        "positive": {"value": 2.0},
        "note": "every field set",
    }


def test_field_tree_refuses_a_value_that_is_no_dataclass() -> None:
    with pytest.raises(TypeError):
        field_tree(5)


@pytest.mark.parametrize(
    "written",
    [
        pytest.param(_EVERY, id="every-field-set"),
        pytest.param(replace(_EVERY, optional_point=None, note=None), id="the-optional-fields-none"),
    ],
)
def test_read_field_tree_reads_a_field_tree_back_as_the_instance_written(written: _EveryShape) -> None:
    assert read_field_tree(json.loads(json.dumps(field_tree(written))), _EveryShape) == written


def test_read_field_tree_gives_a_missing_field_that_has_a_default_its_default() -> None:
    lacking = _without(_without(_TREE, ("point", "y")), ("note",))

    assert read_field_tree(lacking, _EveryShape) == replace(_EVERY, point=_Point(x=1.0, y=0.0), note=None)


@pytest.mark.parametrize(
    "count",
    [
        pytest.param(4.5, id="a-fraction"),
        pytest.param(10**400, id="a-whole-number-no-float-can-hold"),
    ],
)
def test_read_field_tree_reads_any_number_but_a_bool_for_an_int_as_decoded(count: float) -> None:
    assert read_field_tree(_with_value(_TREE, ("count",), count), _EveryShape).count == count


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(int(sys.float_info.max), id="the-largest-float-s-whole-number"),
        pytest.param(-int(sys.float_info.max), id="the-lowest-float-s-whole-number"),
        pytest.param(math.inf, id="infinity"),
        pytest.param(-math.inf, id="minus-infinity"),
    ],
)
def test_read_field_tree_reads_a_float_field_s_number_a_float_can_hold_as_decoded(value: float) -> None:
    """Each is at the edge of what a float can hold, so a rule refusing more than float() does refuses one of them."""
    ratio = read_field_tree(_with_value(_TREE, ("ratio",), value), _EveryShape).ratio

    assert ratio == value
    assert type(ratio) is type(value)


def test_read_field_tree_reads_an_any_field_s_value_as_it_is() -> None:
    anything = [None, True, "free", {"k": [1.5]}]

    assert read_field_tree(_with_value(_TREE, ("anything",), anything), _EveryShape).anything == anything


_TUPLE_OF_2_OF_3 = "holds 3 items, not the 2 of a tuple[int, int]"

_REFUSALS = [
    pytest.param(
        _without(_TREE, ("point",)), "point", "is missing, and _EveryShape has no default for it", id="point-missing"
    ),
    pytest.param(
        _without(_TREE, ("point", "x")), "point.x", "is missing, and _Point has no default for it", id="point.x-missing"
    ),
    pytest.param(
        _without(_TREE, ("rate", "kind")),
        "rate.kind",
        "is missing, not one of ['flat', 'stepped']",
        id="rate.kind-missing",
    ),
    pytest.param(
        _with_value(_TREE, ("rate", "kind"), "turbo"),
        "rate.kind",
        "is the string 'turbo', not one of ['flat', 'stepped']",
        id="rate.kind-no-member-s",
    ),
    pytest.param(_with_value(_TREE, ("rate",), 5), "rate", "is the number 5, not an object", id="rate-a-number"),
    pytest.param(
        _with_value(_TREE, ("rate",), None),
        "rate",
        "is null, not an object, as a _FlatRate is stored or an object, as a _SteppedRate is stored",
        id="rate-null",
    ),
    pytest.param(
        _with_value(_TREE, ("point",), None), "point", "is null, not an object, as a _Point is stored", id="point-null"
    ),
    pytest.param(
        _with_value(_TREE, ("ratio",), None), "ratio", "is null, not a number a float can hold", id="ratio-null"
    ),
    pytest.param(
        _with_value(_TREE, ("weights", "w"), None),
        "weights.w",
        "is null, not a number a float can hold",
        id="weights.w-null",
    ),
    pytest.param(
        _with_value(_TREE, ("point",), "big"),
        "point",
        "is the string 'big', not an object, as a _Point is stored",
        id="point-a-string",
    ),
    pytest.param(_with_value(_TREE, ("pair",), "x"), "pair", "is the string 'x', not an array", id="pair-a-string"),
    pytest.param(_with_value(_TREE, ("by_name",), []), "by_name", "is an array, not an object", id="by_name-an-array"),
    pytest.param(
        _with_value(_TREE, ("ratio",), "4.0"),
        "ratio",
        "is the string '4.0', not a number a float can hold",
        id="ratio-a-string",
    ),
    pytest.param(
        _with_value(_TREE, ("ratio",), True), "ratio", "is true, not a number a float can hold", id="ratio-true"
    ),
    pytest.param(
        _with_value(_TREE, ("ratio",), 10**400),
        "ratio",
        f"is the number {10**400!r}, not a number a float can hold",
        id="ratio-a-number-no-float-can-hold",
    ),
    pytest.param(
        _with_value(_TREE, ("weights", "w"), -(10**400)),
        "weights.w",
        f"is the number {-(10**400)!r}, not a number a float can hold",
        id="weights.w-a-number-below-every-float",
    ),
    pytest.param(_with_value(_TREE, ("flag",), 1), "flag", "is the number 1, not true or false", id="flag-a-number"),
    pytest.param(_with_value(_TREE, ("label",), 5), "label", "is the number 5, not a string", id="label-a-number"),
    pytest.param(
        _with_value(_TREE, ("shade",), "grey"),
        "shade",
        "is the string 'grey', not one of ['light', 'dark']",
        id="shade-no-option",
    ),
    pytest.param(_with_value(_TREE, ("at",), 5), "at", "is the number 5, not a string", id="at-a-number"),
    pytest.param(_with_value(_TREE, ("pair",), [1, 2, 3]), "pair", _TUPLE_OF_2_OF_3, id="pair-of-3-items"),
    pytest.param(
        _with_value(_TREE, ("rate", "steps", 0), [16, 19, 20]),
        "rate.steps[0]",
        _TUPLE_OF_2_OF_3,
        id="rate.steps[0]-of-3-items",
    ),
    pytest.param(
        _with_value(_TREE, ("positive", "value"), -1.0),
        "positive",
        "is refused by _Positive: value must be positive, got -1.0",
        id="positive-refused-by-its-class",
    ),
    pytest.param([1], None, "is an array, not an object, as a _EveryShape is stored", id="the-root-an-array"),
    pytest.param(None, None, "is null, not an object, as a _EveryShape is stored", id="the-root-null"),
]


@pytest.mark.parametrize(("content", "path", "reason"), _REFUSALS)
def test_read_field_tree_refuses_a_value_naming_its_path_and_the_reason(
    content: Any, path: str | None, reason: str
) -> None:
    refused = _refusal(content, _EveryShape)

    assert (refused.path, refused.reason) == (path, reason)


def test_read_field_tree_refuses_a_tag_nested_deeper_than_repr_recurses_naming_it_an_array() -> None:
    """repr of an array 100,000 deep exceeds what CPython's repr recurses through on every admitted minor, so the refusal names the tag by its JSON type.

    _with_value copies the tree before it inserts the array, so the array is never copied.
    """
    refused = _refusal(_with_value(_TREE, ("rate", "kind"), _nested_array(100_000)), _EveryShape)

    assert (refused.path, refused.reason) == ("rate.kind", "is an array, not one of ['flat', 'stepped']")


def test_read_field_tree_refuses_a_string_that_is_no_timestamp_from_pandas_refusal() -> None:
    """Only the reason's prefix is pinned: pandas' own text after the colon varies by release."""
    refused = _refusal(_with_value(_TREE, ("at",), "not a time"), _EveryShape)

    assert refused.path == "at"
    assert refused.reason.startswith("is the string 'not a time', not a timestamp: ")
    assert isinstance(refused.__cause__, ValueError)


def test_read_field_tree_refuses_a_root_dataclass_s_refusal_at_the_root_from_that_refusal() -> None:
    refused = _refusal({"value": -1.0}, _Positive)

    assert (refused.path, refused.reason) == (None, "is refused by _Positive: value must be positive, got -1.0")
    assert type(refused.__cause__) is ValueError
    assert str(refused.__cause__) == "value must be positive, got -1.0"


def test_read_field_tree_refuses_an_annotation_with_no_stored_form() -> None:
    refused = _refusal({"numbers": [1]}, _Unstored)

    assert (refused.path, refused.reason) == ("numbers", "has no stored form: the stored-run format reads no set[int]")


def test_read_field_tree_refuses_a_key_no_field_has_before_any_field() -> None:
    content = _with_value(_with_value(_TREE, ("point",), "bad"), ("zzz",), 1)

    refused = _refusal(content, _EveryShape)

    assert (refused.path, refused.reason) == ("zzz", "is not a field of _EveryShape")


def test_read_field_tree_refuses_the_fields_in_field_order_a_missing_one_in_its_place() -> None:
    content = _without(_with_value(_TREE, ("ratio",), "bad"), ("label",))

    assert _refusal(content, _EveryShape).path == "ratio"


@pytest.mark.parametrize(
    ("keys", "path", "cls"),
    [
        pytest.param((), "retired", _EveryShape, id="the-root"),
        pytest.param(("point",), "point.retired", _Point, id="point"),
        pytest.param(("optional_point",), "optional_point.retired", _Point, id="optional_point"),
        pytest.param(("rate",), "rate.retired", _SteppedRate, id="rate"),
        pytest.param(("points", 1), "points[1].retired", _Point, id="points[1]"),
        pytest.param(("by_name", "a"), "by_name.a.retired", _Point, id="by_name.a"),
        pytest.param(("positive",), "positive.retired", _Positive, id="positive"),
    ],
)
def test_without_unknown_keys_drops_the_key_the_reader_refuses_as_no_field_s_at_the_same_path(
    keys: Keys, path: str, cls: type
) -> None:
    """The one-dispatch property: the drop walks each dataclass's object as the reader reads it, so the tree it leaves reads back."""
    content = _with_value(_TREE, (*keys, "retired"), 1.5)

    refused = _refusal(content, _EveryShape)
    dropped = without_unknown_keys(content, _EveryShape)

    assert (refused.path, refused.reason) == (path, f"is not a field of {cls.__name__}")
    assert dropped == (_TREE, (UnknownKey(path, 1.5),))
    assert read_field_tree(dropped[0], _EveryShape) == _EVERY


@pytest.mark.parametrize(
    ("keys", "value", "expected"),
    [
        pytest.param(
            ("weights", "retired"), 1.5, replace(_EVERY, weights={"w": 0.5, "retired": 1.5}), id="a-dict-field-s-key"
        ),
        pytest.param(("anything",), {"retired": 1}, replace(_EVERY, anything={"retired": 1}), id="an-any-field-s-object"),
    ],
)
def test_without_unknown_keys_keeps_the_keys_of_a_dict_field_and_of_an_any_field_s_value(
    keys: Keys, value: Any, expected: _EveryShape
) -> None:
    """Their keys are their own, not a dataclass's fields."""
    content = _with_value(_TREE, keys, value)

    assert without_unknown_keys(content, _EveryShape) == (content, ())
    assert read_field_tree(content, _EveryShape) == expected


def test_without_unknown_keys_reports_a_dropped_null_as_it_reports_any_value() -> None:
    """Which dropped values to report is stored_runs' choice, not the codec's."""
    content = _with_value(_TREE, ("point", "retired"), None)

    assert without_unknown_keys(content, _EveryShape) == (_TREE, (UnknownKey("point.retired", None),))


def test_without_unknown_keys_reports_the_dropped_keys_in_document_order() -> None:
    content = {"aaa": None, **_TREE}
    for keys, value in ((("point", "retired"), 1), (("rate", "old"), 2), (("by_name", "a", "gone"), 3), (("zzz",), 4)):
        content = _with_value(content, keys, value)

    assert without_unknown_keys(content, _EveryShape) == (
        _TREE,
        (
            UnknownKey("aaa", None),
            UnknownKey("point.retired", 1),
            UnknownKey("rate.old", 2),
            UnknownKey("by_name.a.gone", 3),
            UnknownKey("zzz", 4),
        ),
    )


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        pytest.param(("rate",), {"kind": "turbo", "retired": 1}, id="a-tag-no-member-has"),
        pytest.param(("point",), [{"retired": 1}], id="an-array-for-a-dataclass"),
        pytest.param(("by_name",), [{"x": 1.0, "retired": 1}], id="an-array-for-a-dict"),
        pytest.param(("pair",), [1, 2, 3], id="a-fixed-tuple-s-array-of-another-length"),
        pytest.param(("optional_point",), "big", id="a-string-for-an-optional-dataclass"),
    ],
)
def test_without_unknown_keys_keeps_whole_a_value_the_reader_refuses(keys: Keys, value: Any) -> None:
    """Nothing within such a value is dropped: the reader refuses the value itself."""
    content = _with_value(_TREE, keys, value)

    assert without_unknown_keys(content, _EveryShape) == (content, ())
    _refusal(content, _EveryShape)


def test_without_unknown_keys_changes_none_of_its_input() -> None:
    content = _with_value(_with_value(_TREE, ("retired",), 1), ("points", 0, "retired"), 2)
    before = copy.deepcopy(content)

    without_unknown_keys(content, _EveryShape)

    assert content == before
