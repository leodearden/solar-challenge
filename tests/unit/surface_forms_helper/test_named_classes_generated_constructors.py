# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for a constructor a generator wrote, the dataclass decorator's __init__ or collections.namedtuple's __new__, or a function named as one: the module that spells each of its parameters, how the class statement tells it from a constructor that statement defined, and the TypeError raised where that is not known, one per test.

tests/unit/surface_forms_helper/test_named_classes_constructors.py holds the rules for
every other constructor.
"""

import decimal
import fractions
import pathlib

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import imported_module


_TAPPING_SOURCE = (
    "from dataclasses import dataclass\n"
    "from fractions import Fraction as Tap\n"
    "\n"
    "@dataclass\n"
    "class Meter:\n"
    "    tap: 'Tap'\n"
)

_SOURCING_SOURCE = (
    "from dataclasses import dataclass\n"
    "from fractions import Fraction as Share\n"
    "\n"
    "@dataclass\n"
    "class Source:\n"
    "    share: 'Share'\n"
)

_BORROWING_SOURCE = (
    "from decimal import Decimal as Share\n"
    "from functools import wraps\n"
    "\n"
    "from sourcing import Source\n"
    "\n"
    "class Assigned:\n"
    "    __init__ = Source.__init__\n"
    "\n"
    "class Wrapping:\n"
    "    @wraps(Source.__init__)\n"
    "    def __init__(self, *args, **kwargs) -> None: ...\n"
)

_BORROWING_CLASSES = (
    pytest.param("Assigned", id="assigned"),
    pytest.param("Wrapping", id="functools-wraps-wrapper"),
)


def test_a_generated_dataclass_constructor_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "tapping",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Tap\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    tap: 'Tap'\n"
        "    spare: 'Tap'\n",
    )
    retapping = imported_module(
        tmp_path,
        monkeypatch,
        "retapping",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    spare: 'Tap'\n",
    )

    assert named_classes(retapping.Submeter) == {fractions.Fraction, decimal.Decimal}


def test_a_generated_dataclass_constructor_whose_code_carries_its_own_qualified_name_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    retapping = imported_module(
        tmp_path,
        monkeypatch,
        "retapping",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Spare\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    spare: 'Spare'\n",
    )
    init = vars(retapping.Submeter)["__init__"]
    monkeypatch.setattr(init, "__code__", init.__code__.replace(co_qualname=init.__qualname__))

    assert named_classes(retapping.Submeter) == {fractions.Fraction, decimal.Decimal}


def test_a_generated_dataclass_constructor_does_not_read_a_field_in_the_module_of_a_class_the_dataclass_decorator_never_processed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "gauging",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Gauge\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    gauge: 'Gauge'\n",
    )
    regauging = imported_module(
        tmp_path,
        monkeypatch,
        "regauging",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Gauge\n"
        "\n"
        "from gauging import Meter\n"
        "\n"
        "class Mixin:\n"
        "    gauge: 'Gauge'\n"
        "\n"
        "class Plain(Meter):\n"
        "    gauge: 'Gauge'\n"
        "\n"
        "@dataclass\n"
        "class Mixed(Mixin, Meter): ...\n"
        "\n"
        "@dataclass\n"
        "class Replaced(Plain): ...\n",
    )

    assert named_classes(regauging.Mixed) == {fractions.Fraction}
    assert named_classes(regauging.Replaced) == {fractions.Fraction}


def test_a_constructor_a_dataclass_body_defines_names_the_classes_its_own_module_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "valving",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Valve\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    valve: 'Valve'\n",
    )
    revalving = imported_module(
        tmp_path,
        monkeypatch,
        "revalving",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Valve\n"
        "from functools import wraps\n"
        "\n"
        "from valving import Meter\n"
        "\n"
        "def logged(init):\n"
        "    @wraps(init)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return init(*args, **kwargs)\n"
        "    return wrapper\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    def __init__(self, valve: 'Valve') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class AsyncSubmeter(Meter):\n"
        "    async def __init__(self, valve: 'Valve') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class LoggedSubmeter(Meter):\n"
        "    @logged\n"
        "    def __init__(self, valve: 'Valve') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class Resubmeter(Meter):\n"
        "    def __new__(cls, valve: 'Valve'):\n"
        "        return object.__new__(cls)\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, valve: 'Valve') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class CalledSubmeter(Meter):\n"
        "    __init__ = Caller()\n"
        "\n"
        "@dataclass\n"
        "class BlockSubmeter(Meter):\n"
        "    if Meter:\n"
        "        def __init__(self, valve: 'Valve') -> None: ...\n"
        "\n"
        "@dataclass(init=False)\n"
        "class UnwrittenSubmeter(Meter):\n"
        "    def __init__(self, valve: 'Valve') -> None: ...\n",
    )

    assert named_classes(revalving.Submeter) == {decimal.Decimal}
    assert named_classes(revalving.AsyncSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.LoggedSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.Resubmeter) == {decimal.Decimal}
    assert named_classes(revalving.CalledSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.BlockSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.UnwrittenSubmeter) == {decimal.Decimal}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("Stubbed", {fractions.Fraction}, id="dataclass-init-under-type-checking"),
        pytest.param(
            "Excepted",
            {fractions.Fraction},
            id="dataclass-init-in-an-except-handler-never-entered",
        ),
        pytest.param(
            "Deleted", {fractions.Fraction}, id="dataclass-init-deleted-in-its-class-body"
        ),
        pytest.param("Pointed", {decimal.Decimal}, id="named-tuple-new-under-type-checking"),
    ],
)
def test_a_generated_constructor_whose_class_body_holds_a_def_of_its_name_that_did_not_write_it_is_spelled_as_its_generator_spells_what_it_wrote(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str, expected: set[type]
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    stubbing = imported_module(
        tmp_path,
        monkeypatch,
        "stubbing",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "from typing import TYPE_CHECKING, NamedTuple\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Stubbed(Meter):\n"
        "    if TYPE_CHECKING:\n"
        "        def __init__(self, tap: 'Tap') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class Excepted(Meter):\n"
        "    try:\n"
        "        pass\n"
        "    except ImportError:\n"
        "        def __init__(self, tap: 'Tap') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class Deleted(Meter):\n"
        "    def __init__(self, tap: 'Tap') -> None: ...\n"
        "    del __init__\n"
        "\n"
        "class Pointed(NamedTuple):\n"
        "    tap: 'Tap'\n"
        "    if TYPE_CHECKING:\n"
        "        def __new__(cls, tap: 'Tap') -> 'Pointed': ...\n",
    )

    assert named_classes(getattr(stubbing, name)) == expected


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "from typing import TYPE_CHECKING\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "exec(\n"
            "    '@dataclass\\n'\n"
            "    'class Submeter(Meter):\\n'\n"
            "    '    def __init__(self, tap: \"Tap\") -> None: ...\\n'\n"
            ")\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n",
            id="exec-written-def-below-a-stub-under-type-checking",
        ),
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "from typing import TYPE_CHECKING\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "@dataclass\n"
            "class Submeter(Meter):\n"
            "    if TYPE_CHECKING:\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "init = Submeter.__init__\n"
            "init.__code__ = init.__code__.replace(co_qualname='Submeter.__init__')\n",
            id="generated-code-renamed",
        ),
    ],
)
def test_a_constructor_named_as_generated_that_inspect_reads_no_source_for_whose_class_statement_defines_it_by_a_def_and_whose_code_carries_the_qualified_name_a_def_in_its_class_body_gives_raises_type_error_naming_the_class_the_constructor_and_that_module(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    decoyed = imported_module(tmp_path, monkeypatch, "decoyed", source)

    with pytest.raises(
        TypeError,
        match=r"^decoyed\.Submeter is constructed through "
        r"decoyed\.Submeter\.__init__, which carries the "
        r"name the dataclass decorator gives the __init__ it writes into decoyed\.Submeter, "
        r"and its code carries the qualified name 'Submeter\.__init__', as for a function a "
        r"def statement in a class body wrote, but inspect reads no source for it\b"
        r".*\bso the class statement that source holds under the qualified name 'Submeter' "
        r"may not be the one that defined decoyed\.Submeter\b.*: make the name private, or "
        r"define decoyed\.Submeter by the class statement that source holds$",
    ):
        named_classes(decoyed.Submeter)


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            "if TYPE_CHECKING:\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n",
            id="found-statement",
        ),
        pytest.param("", id="statementless"),
    ],
)
def test_a_constructor_named_as_generated_that_inspect_reads_no_source_for_whose_code_carries_another_qualified_name_than_a_def_in_its_class_body_gives_is_spelled_as_its_generator_spells_what_it_writes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    requalified = imported_module(
        tmp_path,
        monkeypatch,
        "requalified",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "from typing import TYPE_CHECKING\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "exec(\n"
        "    '@dataclass\\n'\n"
        "    'class Submeter(Meter):\\n'\n"
        "    '    def __init__(self, tap: \"Tap\") -> None: ...\\n'\n"
        ")\n"
        "init = Submeter.__init__\n"
        "init.__code__ = init.__code__.replace(co_qualname='Other.__init__')\n"
        "\n" + statement,
    )

    assert named_classes(requalified.Submeter) == {fractions.Fraction}


def test_a_function_assigned_as_a_dataclass_constructor_after_its_class_statement_names_the_classes_the_module_defining_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    share: 'Share'\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from metering import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    pass\n"
        "\n"
        "def settle(self, share: 'Share') -> None: ...\n"
        "\n"
        "Submeter.__init__ = settle\n",
    )

    assert named_classes(submetering.Submeter) == {decimal.Decimal}


def test_a_constructor_named_as_the_dataclass_decorator_names_the_one_it_writes_in_a_class_it_last_processed_with_init_off_raises_type_error_naming_the_class_and_the_function(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    retapping = imported_module(
        tmp_path,
        monkeypatch,
        "retapping",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass(init=False)\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    pass\n",
    )

    with pytest.raises(
        TypeError,
        match=r"^retapping\.Submeter is constructed through retapping\.Submeter\.__init__, "
        r"which carries the name the dataclass decorator gives the __init__ it writes, though "
        r"its record of retapping\.Submeter says it writes none there, so no module is known "
        r"to spell its parameters: make the name private, or define __init__ with def$",
    ):
        named_classes(retapping.Submeter)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Meter", id="init-named-as-the-dataclass-decorator-names-it"),
        pytest.param("Point", id="new-named-as-collections-namedtuple-names-it"),
    ],
)
def test_a_constructor_named_as_a_generator_names_the_one_it_writes_in_a_class_it_never_processed_names_the_classes_the_module_defining_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "lending",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Point:\n"
        "    def __new__(cls, share: 'Share'):\n"
        "        return object.__new__(cls)\n",
    )
    relending = imported_module(
        tmp_path,
        monkeypatch,
        "relending",
        "from decimal import Decimal as Share\n"
        "\n"
        "import lending\n"
        "\n"
        "class Meter:\n"
        "    __init__ = lending.Meter.__init__\n"
        "\n"
        "class Point:\n"
        "    __new__ = lending.Point.__new__\n",
    )

    assert named_classes(getattr(relending, name)) == {fractions.Fraction}


def test_a_generated_dataclass_constructor_of_a_nested_class_whose_source_holds_a_line_left_of_its_class_statement_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    nesting = imported_module(
        tmp_path,
        monkeypatch,
        "nesting",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "class Outer:\n"
        "    @dataclass\n"
        "    class Noted(Meter):\n"
        "        note: str = '''\n"
        "unindented'''\n"
        "\n"
        "    @dataclass\n"
        "    class Commented(Meter):\n"
        "# unindented\n"
        "        pass\n",
    )

    assert named_classes(nesting.Outer.Noted) == {fractions.Fraction, str}
    assert named_classes(nesting.Outer.Commented) == {fractions.Fraction}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "import sys\n"
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "if sys.version_info < (3, 0):\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n"
            "else:\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        pass\n",
            id="branches-of-an-if",
        ),
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "@dataclass\n"
            "class Submeter(Meter):\n"
            "    def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "def rebuild() -> None:\n"
            "    global Submeter\n"
            "\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        pass\n"
            "\n"
            "rebuild()\n",
            id="a-function-declaring-it-global",
        ),
    ],
)
def test_a_generated_dataclass_constructor_of_a_class_whose_module_holds_another_class_statement_under_its_qualified_name_raises_type_error_naming_the_class(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    branching = imported_module(tmp_path, monkeypatch, "branching", source)

    with pytest.raises(
        TypeError, match=r"^branching\.Submeter is defined by one of several class statements"
    ):
        named_classes(branching.Submeter)


def test_a_generated_dataclass_constructor_of_a_class_whose_name_class_statements_inside_a_function_or_class_also_give_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    scoping = imported_module(
        tmp_path,
        monkeypatch,
        "scoping",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    pass\n"
        "\n"
        "def build():\n"
        "    @dataclass\n"
        "    class Submeter(Meter):\n"
        "        pass\n"
        "    return Submeter\n"
        "\n"
        "class Outer:\n"
        "    @dataclass\n"
        "    class Submeter(Meter):\n"
        "        pass\n",
    )

    assert named_classes(scoping.Submeter) == {fractions.Fraction}
    assert named_classes(scoping.build()) == {fractions.Fraction}
    assert named_classes(scoping.Outer.Submeter) == {fractions.Fraction}


def test_a_generated_dataclass_constructor_of_a_class_whose_module_inspect_reads_no_source_for_raises_type_error_naming_the_class(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    unsourced = imported_module(
        tmp_path,
        monkeypatch,
        "unsourced",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    def __init__(self, tap: 'Tap') -> None: ...\n",
    )
    monkeypatch.delattr(unsourced, "__file__")

    with pytest.raises(
        TypeError, match=r"^unsourced\.Submeter has no class statement inspect can read"
    ) as raised:
        named_classes(unsourced.Submeter)

    assert raised.value.__cause__ is not None


@pytest.mark.parametrize(
    ("source", "constructed"),
    [
        pytest.param(
            "from facade import Submeter as Read\n", r"facade\.Submeter", id="the-dataclass"
        ),
        pytest.param(
            "from facade import Submeter\n\nclass Read(Submeter):\n    pass\n",
            r"reading\.Read",
            id="a-subclass-inheriting-it",
        ),
        pytest.param(
            "from facade import Submeter\n\nclass Read:\n    __init__ = Submeter.__init__\n",
            r"reading\.Read",
            id="a-class-assigning-it",
        ),
    ],
)
def test_a_constructor_defined_with_def_in_a_dataclass_whose_module_re_exports_it_raises_type_error_naming_the_class_the_constructor_and_that_module(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str, constructed: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    imported_module(
        tmp_path,
        monkeypatch,
        "implementing",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    def __init__(self, tap: 'Tap') -> None: ...\n",
    )
    imported_module(
        tmp_path,
        monkeypatch,
        "facade",
        "from implementing import Submeter\n\nSubmeter.__module__ = __name__\n",
    )
    reading = imported_module(tmp_path, monkeypatch, "reading", source)

    with pytest.raises(
        TypeError,
        match=rf"^{constructed} is constructed through implementing\.Submeter\.__init__, "
        r"which carries the name the dataclass decorator gives the __init__ it writes into "
        r"facade\.Submeter, and inspect reads a source for it\b"
        r".*\bmodule 'facade' holds no class statement under the qualified name 'Submeter'"
        r".*: make the name private, or leave the __module__ and __qualname__ of "
        r"facade\.Submeter as its class statement set them$",
    ):
        named_classes(reading.Read)


def test_a_generated_dataclass_constructor_of_a_class_whose_modules_source_holds_no_class_statement_for_it_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    imported_module(
        tmp_path,
        monkeypatch,
        "implementing",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    pass\n",
    )
    facade = imported_module(
        tmp_path,
        monkeypatch,
        "facade",
        "from implementing import Submeter\n\nSubmeter.__module__ = __name__\n",
    )
    making = imported_module(
        tmp_path,
        monkeypatch,
        "making",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "Typed = dataclass(type('Typed', (Meter,), {'__annotations__': {'spare': 'Tap'}}))\n",
    )

    assert named_classes(facade.Submeter) == {fractions.Fraction}
    assert named_classes(making.Typed) == {fractions.Fraction, decimal.Decimal}


def test_a_named_tuple_constructor_of_a_class_no_class_statement_made_names_the_classes_the_module_of_that_class_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointing = imported_module(
        tmp_path,
        monkeypatch,
        "pointing",
        "from decimal import Decimal as Share\n"
        "from typing import NamedTuple\n"
        "\n"
        "Pointed = NamedTuple('Pointed', [('share', 'Share')])\n",
    )

    assert named_classes(pointing.Pointed) == {decimal.Decimal}


@pytest.mark.parametrize(
    ("source", "read", "constructed", "qualname"),
    [
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "exec(\n"
            "    '@dataclass\\n'\n"
            "    'class Submeter(Meter):\\n'\n"
            "    '    def __init__(self, tap: \"Tap\") -> None: ...\\n'\n"
            ")\n",
            "Submeter",
            r"statementless\.Submeter is constructed through statementless\.Submeter\.__init__, "
            r"which carries the name the dataclass decorator gives the __init__ it writes into "
            r"statementless\.Submeter, and its code carries the qualified name "
            r"'Submeter\.__init__'",
            r"Submeter",
            id="exec-written-def",
        ),
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "exec(\n"
            "    'def make():\\n'\n"
            "    '    @dataclass\\n'\n"
            "    '    class Inner(Meter):\\n'\n"
            "    '        def __init__(self, tap: \"Tap\") -> None: ...\\n'\n"
            "    '    return Inner\\n'\n"
            "    'Inner = make()\\n'\n"
            ")\n",
            "Inner",
            r"statementless\.make\.<locals>\.Inner is constructed through "
            r"statementless\.make\.<locals>\.Inner\.__init__, which carries the name the "
            r"dataclass decorator gives the __init__ it writes into "
            r"statementless\.make\.<locals>\.Inner, and its code carries the qualified name "
            r"'make\.<locals>\.Inner\.__init__'",
            r"make\.<locals>\.Inner",
            id="exec-written-def-in-a-function",
        ),
        pytest.param(
            "from decimal import Decimal as Share\n"
            "from typing import NamedTuple\n"
            "\n"
            "Pointed = NamedTuple('Pointed', [('share', 'Share')])\n"
            "new = Pointed.__new__\n"
            "new.__code__ = new.__code__.replace(co_qualname='Pointed.__new__')\n",
            "Pointed",
            r"statementless\.Pointed is constructed through namedtuple_Pointed\.Pointed\.__new__, which carries "
            r"the name collections\.namedtuple gives the __new__ it writes into "
            r"statementless\.Pointed, and its code carries the qualified name 'Pointed\.__new__'",
            r"Pointed",
            id="generated-code-renamed",
        ),
    ],
)
def test_a_constructor_named_as_generated_in_a_class_whose_modules_source_holds_no_class_statement_for_it_whose_code_carries_the_qualified_name_a_def_in_its_class_body_gives_raises_type_error_naming_the_class_the_constructor_and_that_module(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    read: str,
    constructed: str,
    qualname: str,
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    statementless = imported_module(tmp_path, monkeypatch, "statementless", source)

    with pytest.raises(
        TypeError,
        match=rf"^{constructed}.*\bmodule 'statementless' holds no class statement under the "
        rf"qualified name '{qualname}'.*: make the name private, or define "
        rf"statementless\.{qualname} by a class statement in the source of the module "
        r"'statementless'$",
    ):
        named_classes(getattr(statementless, read))


def test_a_dataclass_constructor_of_a_class_whose_module_assigns_it_the_module_name_it_already_holds_is_read_as_the_class_statement_that_defined_it_defines_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    rehoming = imported_module(
        tmp_path,
        monkeypatch,
        "rehoming",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    def __init__(self, tap: 'Tap') -> None: ...\n"
        "\n"
        "@dataclass\n"
        "class Plain(Meter):\n"
        "    pass\n"
        "\n"
        "Submeter.__module__ = __name__\n"
        "Plain.__module__ = __name__\n",
    )

    assert named_classes(rehoming.Submeter) == {decimal.Decimal}
    assert named_classes(rehoming.Plain) == {fractions.Fraction}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "def build() -> None:\n"
            "    global Submeter\n"
            "\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "build()\n",
            id="a-function",
        ),
        pytest.param(
            "from dataclasses import dataclass\n"
            "from decimal import Decimal as Tap\n"
            "\n"
            "from tapping import Meter\n"
            "\n"
            "class Building:\n"
            "    if True:\n"
            "        global Submeter\n"
            "\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n",
            id="a-block-of-a-class-body",
        ),
    ],
)
def test_a_constructor_defined_with_def_in_a_dataclass_its_enclosing_function_or_class_body_declares_global_names_the_classes_its_own_module_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    declaring = imported_module(tmp_path, monkeypatch, "declaring", source)

    assert named_classes(declaring.Submeter) == {decimal.Decimal}


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param(
            "def build():\n"
            "    Submeter = None\n"
            "\n"
            "    def rebuild() -> None:\n"
            "        nonlocal Submeter\n"
            "\n"
            "        @dataclass\n"
            "        class Submeter(Meter):\n"
            "            def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "    rebuild()\n"
            "    return Submeter\n"
            "\n"
            "Submeter = build()\n",
            id="a-function",
        ),
        pytest.param(
            "def build():\n"
            "    Submeter = None\n"
            "\n"
            "    class Building:\n"
            "        nonlocal Submeter\n"
            "\n"
            "        @dataclass\n"
            "        class Submeter(Meter):\n"
            "            def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "    return Submeter\n"
            "\n"
            "Submeter = build()\n",
            id="a-class-body",
        ),
    ],
)
def test_a_constructor_defined_with_def_in_a_dataclass_its_enclosing_function_or_class_body_declares_nonlocal_names_the_classes_its_own_module_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, definition: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    declaring = imported_module(
        tmp_path,
        monkeypatch,
        "declaring",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n" + definition,
    )

    assert named_classes(declaring.Submeter) == {decimal.Decimal}


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param(
            "@dataclass\n"
            "class Submeter(Meter):\n"
            "    global __init__\n"
            "    def __init__(self, tap: 'Tap') -> None: ...\n",
            id="global",
        ),
        pytest.param(
            "@dataclass\n"
            "class Submeter(Meter):\n"
            "    if Meter:\n"
            "        global __init__\n"
            "    def __init__(self, tap: 'Tap') -> None: ...\n",
            id="global-in-a-block",
        ),
        pytest.param(
            "@dataclass\n"
            "class Submeter(Meter):\n"
            "    if False:\n"
            "        global __init__\n"
            "    def __init__(self, tap: 'Tap') -> None: ...\n",
            id="global-in-a-block-that-never-runs",
        ),
        pytest.param(
            "def build():\n"
            "    __init__ = None\n"
            "\n"
            "    @dataclass\n"
            "    class Submeter(Meter):\n"
            "        nonlocal __init__\n"
            "        def __init__(self, tap: 'Tap') -> None: ...\n"
            "\n"
            "    return Submeter\n"
            "\n"
            "Submeter = build()\n",
            id="nonlocal",
        ),
    ],
)
def test_a_generated_dataclass_constructor_whose_name_its_class_body_declares_global_or_nonlocal_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, definition: str
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    rebinding = imported_module(
        tmp_path,
        monkeypatch,
        "rebinding",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "from tapping import Meter\n"
        "\n" + definition,
    )

    assert named_classes(rebinding.Submeter) == {fractions.Fraction}


def test_a_wrapper_carrying_a_signature_of_none_over_a_generated_dataclass_constructor_names_the_classes_the_module_of_each_field_declaration_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    share: 'Share'\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "from metering import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter):\n"
        "    pass\n"
        "\n"
        "@wraps(Submeter.__init__)\n"
        "def rewrapped(self, share) -> None: ...\n"
        "\n"
        "rewrapped.__signature__ = None\n"
        "Submeter.__init__ = rewrapped\n",
    )

    assert named_classes(submetering.Submeter) == {fractions.Fraction}


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param("class Point(NamedTuple):\n    share: 'Share'\n", id="at-module-level"),
        pytest.param(
            "def define():\n"
            "    class Point(NamedTuple):\n"
            "        share: 'Share'\n"
            "    return Point\n"
            "\n"
            "Point = define()\n",
            id="inside-a-function",
        ),
    ],
)
def test_a_constructor_compiled_outside_its_class_body_names_the_classes_the_module_of_that_class_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, definition: str
) -> None:
    pointing = imported_module(
        tmp_path,
        monkeypatch,
        "pointing",
        "from decimal import Decimal as Share\n"
        "from typing import NamedTuple\n"
        "\n" + definition,
    )

    class Subpoint(pointing.Point):
        pass

    assert named_classes(Subpoint) == {decimal.Decimal}


def test_a_named_tuple_constructor_whose_code_carries_its_own_qualified_name_names_the_classes_the_module_of_that_class_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointing = imported_module(
        tmp_path,
        monkeypatch,
        "pointing",
        "from decimal import Decimal as Share\n"
        "from typing import NamedTuple\n"
        "\n"
        "class Point(NamedTuple):\n"
        "    share: 'Share'\n",
    )
    held = vars(pointing.Point)["__new__"]
    new = getattr(held, "__func__", held)
    monkeypatch.setattr(new, "__code__", new.__code__.replace(co_qualname=new.__qualname__))

    class Subpoint(pointing.Point):
        pass

    assert named_classes(Subpoint) == {decimal.Decimal}


@pytest.mark.parametrize("name", _BORROWING_CLASSES)
def test_a_constructor_generated_for_another_class_than_the_one_assigning_it_raises_type_error_naming_that_class_and_the_function(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(tmp_path, monkeypatch, "sourcing", _SOURCING_SOURCE)
    borrowing = imported_module(tmp_path, monkeypatch, "borrowing", _BORROWING_SOURCE)

    with pytest.raises(
        TypeError,
        match=rf"^borrowing\.{name} is constructed through sourcing\.Source\.__init__, "
        rf"a function generated for another class and assigned in the body of borrowing\.{name}, ",
    ):
        named_classes(getattr(borrowing, name))


@pytest.mark.parametrize("name", _BORROWING_CLASSES)
@pytest.mark.parametrize(
    ("statements_after_source", "refusal"),
    [
        pytest.param(
            "\ndel __file__\n",
            r"^sourcing\.Source has no class statement inspect can read",
            id="whose-module-inspect-reads-no-source-for",
        ),
        pytest.param(
            "\nif False:\n    class Source:\n        pass\n",
            r"^sourcing\.Source is defined by one of several class statements",
            id="whose-module-holds-another-class-statement-under-its-qualified-name",
        ),
    ],
)
def test_a_constructor_generated_for_another_class_whose_class_statement_cannot_be_read_raises_type_error_naming_the_class_it_was_generated_for(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    statements_after_source: str,
    refusal: str,
) -> None:
    imported_module(tmp_path, monkeypatch, "sourcing", _SOURCING_SOURCE + statements_after_source)
    borrowing = imported_module(tmp_path, monkeypatch, "borrowing", _BORROWING_SOURCE)

    with pytest.raises(TypeError, match=refusal):
        named_classes(getattr(borrowing, name))
