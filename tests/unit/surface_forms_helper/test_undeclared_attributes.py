# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's undeclared_attributes, one per test."""

import _json
import _random
import ast
import collections
import decimal
import functools
import pathlib
import re
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from tests._surface_forms import member_forms, undeclared_attributes, unset_attributes
from tests.unit.surface_forms_helper._fixtures import (
    REFUSED_ROUTINE_AND_PARTIAL_MEMBERS,
    dict_intercepting_refusal,
    dict_shadowing_refusal,
    imported_module,
    metaclass_whose_dict_gives,
    metaclass_whose_getattribute_gives_dict,
    metaclass_whose_mro_gives,
)


def test_each_assignment_to_a_public_attribute_of_self_sets_it() -> None:
    class Meter:
        def __init__(self, site: pathlib.Path, readings: list[float]) -> None:
            self.site = site
            self.reading: float = 0.0
            self.low, self.high = 0.0, 1.0
            for kwh in readings:
                self.total += kwh

    assert undeclared_attributes(Meter) == {"site", "reading", "low", "high", "total"}


def test_object_setattr_on_self_sets_the_attribute_it_names() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float

        def __post_init__(self) -> None:
            object.__setattr__(self, "kwh", float(self.kwh))
            object.__setattr__(self, "label", f"{self.kwh} kWh")

    assert undeclared_attributes(Reading) == {"label"}


def test_setattr_or___setattr___on_the_receiver_with_a_string_constant_sets_the_attribute_it_names() -> None:
    class Meter:
        def __init__(self) -> None:
            setattr(self, "site", "roof")
            object.__setattr__(self, "reading", 0.0)
            self.__setattr__("low", 0.0)
            super().__setattr__("high", 1.0)

    assert vars(Meter()).keys() == {"site", "reading", "low", "high"}
    assert undeclared_attributes(Meter) == {"site", "reading", "low", "high"}


def test_only_the_init_and_post_init_the_class_body_itself_defines_are_read() -> None:
    class Meter:
        def __init__(self) -> None:
            self.ok = 1

        def reset(self) -> None:
            self.reading = 0.0

        @staticmethod
        def build(self: object) -> None:
            self.fromstatic = 1

        class _Helper:
            def __init__(self) -> None:
                self.leaked = 1

    assert undeclared_attributes(Meter) == {"ok"}


def test_an_assignment_to_the_receiver_in_a_closure_inside_an_initialiser_sets_it() -> None:
    class Meter:
        def __init__(self) -> None:
            def fill() -> None:
                self.site = "roof"

            fill()

    assert vars(Meter()).keys() == {"site"}
    assert undeclared_attributes(Meter) == {"site"}


def test_the_receiver_is_the_first_parameter_whatever_its_name() -> None:
    class Meter:
        def __init__(this, self: object) -> None:
            this.renamed = 1
            self.elsewhere = 2

    assert undeclared_attributes(Meter) == {"renamed"}


def test_an_attribute_a_class_body_in_the_mro_declares_or_defines_is_not_undeclared() -> None:
    class Base:
        site: pathlib.Path

    class Meter(Base):
        UNITS = "kWh"
        reading: float

        def __init__(self, site: pathlib.Path) -> None:
            self.site = site
            self.UNITS = "MWh"
            self.reading = 0.0

    assert undeclared_attributes(Meter) == set()


def test_an_attribute_a_base_body_declares_is_declared_whatever_mro_the_class_metaclass_gives() -> None:
    class Declaring:
        site: pathlib.Path

    class Setting(Declaring, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))):
        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    assert undeclared_attributes(Setting) == set()


@pytest.mark.parametrize("scan", [undeclared_attributes, unset_attributes])
@pytest.mark.parametrize(
    "shadow",
    [
        pytest.param({"label": None}, id="dict-giving-the-attribute-the-initialiser-sets"),
        pytest.param(None, id="dict-giving-no-mapping"),
    ],
)
def test_a_class_whose_metaclass_shadows_dict_raises_a_type_error_naming_it_and_its_metaclass_from_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]], shadow: object
) -> None:
    class Meter(metaclass=metaclass_whose_dict_gives(lambda cls: shadow)):
        def __init__(self) -> None:
            self.label = "roof"

    with pytest.raises(TypeError, match=dict_shadowing_refusal("Meter")):
        scan(Meter)


@pytest.mark.parametrize("scan", [undeclared_attributes, unset_attributes])
def test_a_class_whose_metaclass_overrides_types_getattribute_raises_a_type_error_naming_it_and_its_metaclass_from_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
) -> None:
    class Meter(metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {"label": None})):
        def __init__(self) -> None:
            self.label = "roof"

    with pytest.raises(TypeError, match=dict_intercepting_refusal("Meter")):
        scan(Meter)


def test_an_attribute_only_a_base_sets_on_self_is_undeclared_in_the_base_not_its_subclass() -> None:
    class Base:
        def __init__(self, site: pathlib.Path) -> None:
            self.site = site

    class Meter(Base):
        def __init__(self, site: pathlib.Path) -> None:
            super().__init__(site)
            self.reading = 0.0

    assert undeclared_attributes(Base) == {"site"}
    assert undeclared_attributes(Meter) == {"reading"}


def test_a_private_attribute_set_on_self_is_never_undeclared() -> None:
    class Meter:
        def __init__(self) -> None:
            self._cache: dict[str, float] = {}
            object.__setattr__(self, "_level", 0.0)

    assert undeclared_attributes(Meter) == set()


@pytest.mark.parametrize(("routine", "kind"), REFUSED_ROUTINE_AND_PARTIAL_MEMBERS)
def test_a_class_with_a_member_member_forms_refuses_still_has_its_undeclared_attributes_read(
    routine: object, kind: str
) -> None:
    class Meter:
        half = routine

        def __init__(self) -> None:
            self.reading = 0.0

    with pytest.raises(TypeError, match=rf"\.Meter\.half\b.*\b{re.escape(kind)}\b"):
        member_forms(Meter)
    assert undeclared_attributes(Meter) == {"reading"}


def test_a_class_body_string_annotation_naming_a_name_its_module_does_not_bind_raises_a_name_error_from_undeclared_attributes_and_unset_attributes() -> None:
    class Base:
        site: "Nowhere"  # noqa: F821

    class Meter(Base):
        def __init__(self) -> None:
            self.reading = 0.0

    with pytest.raises(NameError, match="Nowhere"):
        undeclared_attributes(Meter)
    with pytest.raises(NameError, match="Nowhere"):
        unset_attributes(Base)


def test_a_write_under_a_computed_name_raises_a_type_error_naming_the_class_and_each_such_write_from_undeclared_attributes_and_unset_attributes() -> None:
    class Meter:
        def __init__(self, name: str) -> None:
            setattr(self, name, 0.0)
            object.__setattr__(self, f"{name}_low", 0.0)
            super().__setattr__(name.upper(), 1.0)

    writes = [
        "setattr(self, name, 0.0)",
        "object.__setattr__(self, f'{name}_low', 0.0)",
        "super().__setattr__(name.upper(), 1.0)",
    ]
    for scan in (undeclared_attributes, unset_attributes):
        with pytest.raises(TypeError) as refusal:
            scan(Meter)
        for text in ["Meter", *writes]:
            assert text in str(refusal.value)


def test_a_reach_into_the_receivers___dict___raises_a_type_error_naming_the_class_and_each_reach_from_undeclared_attributes_and_unset_attributes() -> None:
    class Meter:
        def __init__(self) -> None:
            self.__dict__["site"] = "roof"
            vars(self).update(low=0.0)

    for scan in (undeclared_attributes, unset_attributes):
        with pytest.raises(TypeError) as refusal:
            scan(Meter)
        for text in ["Meter", "self.__dict__", "vars(self)"]:
            assert text in str(refusal.value)


def test_a_reviewed_write_under_a_computed_name_is_not_refused_and_the_other_writes_are_still_read() -> None:
    class Meter:
        def __init__(self, name: str) -> None:
            setattr(self, name, 0.0)
            self.site = "roof"

    assert undeclared_attributes(Meter, reviewed={"setattr(self, name, 0.0)"}) == {"site"}


def test_a_reviewed_write_the_initialisers_do_not_make_raises_a_value_error_naming_it_from_undeclared_attributes_and_unset_attributes() -> None:
    class Meter:
        def __init__(self) -> None:
            self.site = "roof"

    stale = "setattr(self, name, 0.0)"
    with pytest.raises(ValueError, match=re.escape(stale)):
        undeclared_attributes(Meter, reviewed={stale})
    with pytest.raises(ValueError, match=re.escape(stale)):
        unset_attributes(Meter, reviewed={stale})


def test_reviewed_given_as_one_string_raises_a_type_error_naming_it_from_undeclared_attributes_and_unset_attributes() -> None:
    class Meter:
        def __init__(self) -> None:
            self.site = "roof"

    text = "setattr(self, name, 0.0)"
    for scan in (undeclared_attributes, unset_attributes):
        with pytest.raises(TypeError, match=re.escape(text)):
            scan(Meter, reviewed=text)


def test_a_class_whose_module_another_module_of_the_same_name_has_replaced_in_sys_modules_raises_a_lookup_error_from_undeclared_attributes_and_unset_attributes(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "metering",
        "class Meter:\n"
        "    def __init__(self) -> None:\n"
        "        self.early = 1\n",
    )
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "metering",
        "class Meter:\n"
        "    def __init__(self) -> None:\n"
        "        self.late = 1\n",
    )

    with pytest.raises(LookupError) as undeclared:
        undeclared_attributes(earlier.Meter)
    with pytest.raises(LookupError) as unset:
        unset_attributes(earlier.Meter)

    assert later.__file__ in str(undeclared.value)
    assert later.__file__ in str(unset.value)


@pytest.mark.parametrize("scan", [undeclared_attributes, unset_attributes])
def test_a_class_whose_module_one_with_no_source_has_replaced_in_sys_modules_raises_a_lookup_error_naming_its_own_module_from_undeclared_attributes_and_unset_attributes_if_it_has_a_witness(
    scan: Callable[[type], set[str]], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metering = imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "class Meter:\n    def __init__(self) -> None:\n        self.early = 1\n",
    )
    monkeypatch.setitem(sys.modules, "metering", types.ModuleType("metering"))

    with pytest.raises(LookupError) as replaced:
        scan(metering.Meter)

    assert "metering.Meter" in str(replaced.value)
    assert metering.__file__ in str(replaced.value)


@pytest.mark.parametrize("scan", [undeclared_attributes, unset_attributes])
@pytest.mark.parametrize(
    ("cls", "naming_it"),
    [
        pytest.param(types.ModuleType, r"\bbuiltins\.module\b.*\bimmutable type\b", id="types.ModuleType"),
        pytest.param(int, r"\bbuiltins\.int\b.*\bimmutable type\b", id="int"),
        pytest.param(
            collections.OrderedDict,
            r"\bcollections\.OrderedDict\b.*\bimmutable type\b",
            id="collections.OrderedDict",
        ),
        pytest.param(
            functools.partial, r"\bfunctools\.partial\b.*\bimmutable type\b", id="functools.partial"
        ),
        pytest.param(decimal.Decimal, r"\bdecimal\.Decimal\b.*\bimmutable type\b", id="decimal.Decimal"),
    ],
)
def test_an_immutable_type_raises_a_type_error_naming_it_before_anything_is_read_from_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]], cls: type, naming_it: str
) -> None:
    with pytest.raises(TypeError, match=naming_it):
        scan(cls)


@pytest.mark.parametrize("scan", [undeclared_attributes, unset_attributes])
@pytest.mark.parametrize(
    ("cls", "naming_it"),
    [
        pytest.param(ast.AST, r"\bast\.AST\b.*\bno class statement inspect can read\b", id="ast.AST"),
        pytest.param(
            _random.Random,
            r"\b_random\.Random\b.*\bno class statement inspect can read\b",
            id="_random.Random",
        ),
        pytest.param(
            _json.make_scanner,
            r"\b_json\.Scanner\b.*\bno class statement inspect can read\b",
            id="_json.Scanner",
        ),
    ],
)
def test_a_class_with_no_class_statement_inspect_can_read_raises_a_type_error_naming_it_from_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]], cls: type, naming_it: str
) -> None:
    """None is an immutable type: ast.AST's module has a source, _random.Random's has none, and _json.Scanner's has none and binds it as make_scanner, not under its qualified name."""
    with pytest.raises(TypeError, match=naming_it):
        scan(cls)


_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE = pytest.mark.parametrize(
    ("scan", "expected"),
    [
        pytest.param(undeclared_attributes, {"site"}, id="undeclared_attributes"),
        pytest.param(unset_attributes, {"rate"}, id="unset_attributes"),
    ],
)


@_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE
def test_a_class_whose_module_assigns_it_the_module_name_it_already_holds_has_its_class_statement_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rehoming = imported_module(
        tmp_path,
        monkeypatch,
        "rehoming",
        "class Meter:\n"
        "    rate: float\n"
        "\n"
        "    def __init__(self) -> None:\n"
        "        self.site = 1\n"
        "\n"
        "Meter.__module__ = __name__\n",
    )

    assert scan(rehoming.Meter) == expected


@_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE
def test_a_class_its_enclosing_function_declares_global_has_its_class_statement_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaring = imported_module(
        tmp_path,
        monkeypatch,
        "declaring",
        "def build() -> None:\n"
        "    global Meter\n"
        "\n"
        "    class Meter:\n"
        "        rate: float\n"
        "\n"
        "        def __init__(self) -> None:\n"
        "            self.site = 1\n"
        "\n"
        "build()\n",
    )

    assert scan(declaring.Meter) == expected


@_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE
@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def build():\n"
            "    def inner() -> None:\n"
            "        global Meter\n"
            "\n"
            "    class Meter:\n"
            "        rate: float\n"
            "\n"
            "        def __init__(self) -> None:\n"
            "            self.site = 1\n"
            "\n"
            "    return Meter\n"
            "\n"
            "Local = build()\n",
            id="a-def-in-the-function-holding-it",
        ),
        pytest.param(
            "def build():\n"
            "    async def inner() -> None:\n"
            "        global Meter\n"
            "\n"
            "    class Meter:\n"
            "        rate: float\n"
            "\n"
            "        def __init__(self) -> None:\n"
            "            self.site = 1\n"
            "\n"
            "    return Meter\n"
            "\n"
            "Local = build()\n",
            id="an-async-def-in-the-function-holding-it",
        ),
        pytest.param(
            "def build():\n"
            "    class Housing:\n"
            "        global Meter\n"
            "\n"
            "    class Meter:\n"
            "        rate: float\n"
            "\n"
            "        def __init__(self) -> None:\n"
            "            self.site = 1\n"
            "\n"
            "    return Meter\n"
            "\n"
            "Local = build()\n",
            id="a-class-body-in-the-function-holding-it",
        ),
        pytest.param(
            "def build():\n"
            "    global Meter\n"
            "\n"
            "    class Housing:\n"
            "        class Meter:\n"
            "            rate: float\n"
            "\n"
            "            def __init__(self) -> None:\n"
            "                self.site = 1\n"
            "\n"
            "    return Housing\n"
            "\n"
            "Local = build().Meter\n",
            id="the-function-holding-the-class-body-holding-it",
        ),
        pytest.param(
            "def build():\n"
            "    global Meter\n"
            "\n"
            "    def make():\n"
            "        class Meter:\n"
            "            rate: float\n"
            "\n"
            "            def __init__(self) -> None:\n"
            "                self.site = 1\n"
            "\n"
            "        return Meter\n"
            "\n"
            "    return make\n"
            "\n"
            "Local = build()()\n",
            id="the-function-holding-the-function-body-holding-it",
        ),
    ],
)
def test_a_class_whose_name_a_global_statement_in_another_body_declares_has_its_class_statement_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    source: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enclosing = imported_module(tmp_path, monkeypatch, "enclosing", source)

    assert scan(enclosing.Local) == expected


@_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE
def test_a_class_in_a_function_its_enclosing_function_declares_global_has_its_class_statement_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporting = imported_module(
        tmp_path,
        monkeypatch,
        "exporting",
        "def build() -> None:\n"
        "    global make\n"
        "\n"
        "    def make():\n"
        "        class Meter:\n"
        "            rate: float\n"
        "\n"
        "            def __init__(self) -> None:\n"
        "                self.site = 1\n"
        "\n"
        "        return Meter\n"
        "\n"
        "build()\n"
        "Local = make()\n",
    )

    assert scan(exporting.Local) == expected


@_EACH_SCAN_OF_A_CLASS_THAT_SETS_SITE_AND_DECLARES_RATE
def test_a_class_in_an_async_def_has_its_class_statement_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    awaiting = imported_module(
        tmp_path,
        monkeypatch,
        "awaiting",
        "import asyncio\n"
        "\n"
        "async def build():\n"
        "    class Meter:\n"
        "        rate: float\n"
        "\n"
        "        def __init__(self) -> None:\n"
        "            self.site = 1\n"
        "\n"
        "    return Meter\n"
        "\n"
        "_loop = asyncio.new_event_loop()\n"
        "Local = _loop.run_until_complete(build())\n"
        "_loop.close()\n",
    )

    assert scan(awaiting.Local) == expected


@pytest.mark.parametrize(
    ("scan", "expected"),
    [
        pytest.param(undeclared_attributes, {"site"}, id="undeclared_attributes"),
        pytest.param(unset_attributes, set(), id="unset_attributes"),
    ],
)
@pytest.mark.parametrize(
    "block",
    [
        pytest.param("    if True:\n", id="an-if-block"),
        pytest.param(
            "    try:\n        raise LookupError\n    except LookupError:\n", id="an-except-handler"
        ),
        pytest.param("    match 'roof':\n      case str():\n", id="a-match-case"),
        pytest.param("    with contextlib.nullcontext():\n", id="a-with-block"),
    ],
)
def test_an_initialiser_the_class_body_defines_in_a_block_of_another_statement_is_read_by_undeclared_attributes_and_unset_attributes(
    scan: Callable[[type], set[str]],
    expected: set[str],
    block: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocking = imported_module(
        tmp_path,
        monkeypatch,
        "blocking",
        "import contextlib\n"
        "\n"
        "class Meter:\n"
        "    rate: float\n"
        "\n"
        + block
        + "        def __init__(self) -> None:\n"
        "            self.rate = 1.0\n"
        "            self.site = 'roof'\n",
    )

    assert vars(blocking.Meter()).keys() == {"rate", "site"}
    assert scan(blocking.Meter) == expected
