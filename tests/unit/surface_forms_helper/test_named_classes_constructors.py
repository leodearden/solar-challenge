# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the callable or class that spells a class's signature, the constructor inspect reads for it, and the errors raised when none is known, one per test.

A class that carries an inspect.Signature, and the module the strings that signature
names are read in, have their rules in tests/unit/surface_forms_helper/test_named_classes_carried_signatures.py.
"""

import decimal
import fractions
import pathlib

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import (
    GIVEN_BY_A_METACLASS_GET,
    imported_module,
)


_TAPPING_SOURCE = (
    "from dataclasses import dataclass\n"
    "from fractions import Fraction as Tap\n"
    "\n"
    "@dataclass\n"
    "class Meter:\n"
    "    tap: 'Tap'\n"
)


def test_an_inherited_constructor_names_the_classes_the_module_defining_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metering = imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, ratio: 'Fraction') -> None: ...\n",
    )

    class Submeter(metering.Meter):
        pass

    assert named_classes(Submeter) == {fractions.Fraction}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Plain", id="no-constructor"),
        pytest.param("Initialised", id="own-init"),
        pytest.param("Inherited", id="call-a-base-metaclass-defines"),
        pytest.param("Halved", id="call-assigned-as-a-descriptor"),
        pytest.param("Signed", id="carries-a-signature"),
    ],
)
def test_a_class_whose_metaclass_resolves_a_call_defined_in_python_names_the_classes_that_call_names_read_where_it_is_spelled_not_where_its_constructor_is(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "charging",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Charging(type):\n"
        "    def __call__(cls, share: 'Share') -> None: ...\n"
        "\n"
        "def settle(cls, share: 'Share', rate=1) -> None: ...\n",
    )
    recharging = imported_module(
        tmp_path,
        monkeypatch,
        "recharging",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "from functools import partialmethod\n"
        "\n"
        "from charging import Charging, settle\n"
        "\n"
        "class Recharging(Charging):\n"
        "    pass\n"
        "\n"
        "class Halving(type):\n"
        "    __call__ = partialmethod(settle, rate=2)\n"
        "\n"
        "class Plain(metaclass=Charging):\n"
        "    pass\n"
        "\n"
        "class Initialised(metaclass=Charging):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Inherited(metaclass=Recharging):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Halved(metaclass=Halving):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Signed(metaclass=Charging):\n"
        "    __signature__ = inspect.Signature(\n"
        "        [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        "    )\n",
    )

    assert named_classes(getattr(recharging, name)) == {fractions.Fraction}


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
    assert named_classes(revalving.LoggedSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.Resubmeter) == {decimal.Decimal}
    assert named_classes(revalving.CalledSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.BlockSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.UnwrittenSubmeter) == {decimal.Decimal}


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
        r"its record of retapping\.Submeter says it writes none there, ",
    ):
        named_classes(retapping.Submeter)


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


def test_a_generated_dataclass_constructor_of_a_class_whose_module_holds_another_class_statement_under_its_qualified_name_raises_type_error_naming_the_class(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "tapping", _TAPPING_SOURCE)
    branching = imported_module(
        tmp_path,
        monkeypatch,
        "branching",
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
    )

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
    "name",
    [
        pytest.param("Assigned", id="assigned-function"),
        pytest.param("Called", id="assigned-callable-object"),
        pytest.param("Made", id="assigned-new"),
        pytest.param("Wrapping", id="functools-wraps-wrapper"),
    ],
)
def test_a_constructor_spelled_in_another_module_than_its_class_body_names_the_classes_that_module_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "building",
        "from fractions import Fraction as Share\n"
        "\n"
        "def build(self, share: 'Share') -> None: ...\n"
        "\n"
        "def make(cls, share: 'Share'): ...\n"
        "\n"
        "class Builder:\n"
        "    def __call__(self, share: 'Share') -> None: ...\n",
    )
    rebuilding = imported_module(
        tmp_path,
        monkeypatch,
        "rebuilding",
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "from building import Builder, build, make\n"
        "\n"
        "class Assigned:\n"
        "    __init__ = build\n"
        "\n"
        "class Called:\n"
        "    __init__ = Builder()\n"
        "\n"
        "class Made:\n"
        "    __new__ = make\n"
        "\n"
        "class Wrapping:\n"
        "    @wraps(build)\n"
        "    def __init__(self, *args, **kwargs) -> None: ...\n",
    )

    assert named_classes(getattr(rebuilding, name)) == {fractions.Fraction}


def test_a_constructor_that_wraps_another_callable_but_carries_a_signature_of_none_names_the_classes_the_annotations_it_holds_name_read_where_they_are_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Meter:\n"
        "    def __new__(cls, share: 'Share') -> None: ...\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "from metering import Meter\n"
        "\n"
        "class Rewrapped(Meter):\n"
        "    @wraps(Meter.__new__)\n"
        "    def __new__(cls, share: 'Share') -> None: ...\n"
        "\n"
        "    __new__.__signature__ = None\n"
        "\n"
        "class Relinked(Meter):\n"
        "    def __new__(cls, share: 'Share') -> None: ...\n"
        "\n"
        "    __new__.__wrapped__ = Meter.__new__\n"
        "    __new__.__signature__ = None\n"
        "\n"
        "class Initialised:\n"
        "    @wraps(object.__init__)\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "    __init__.__signature__ = None\n",
    )

    assert named_classes(submetering.Rewrapped) == {fractions.Fraction}
    assert named_classes(submetering.Relinked) == {decimal.Decimal}
    assert named_classes(submetering.Initialised) == {decimal.Decimal}


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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Halved", id="partialmethod"),
        pytest.param("Dispatched", id="singledispatchmethod"),
    ],
)
def test_a_constructor_assigned_as_a_descriptor_is_read_once_bound_to_its_class_and_names_the_classes_the_module_of_the_function_it_wraps_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "settling",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(self, share: 'Share', rate: int) -> None: ...\n",
    )
    resettling = imported_module(
        tmp_path,
        monkeypatch,
        "resettling",
        "from decimal import Decimal as Share\n"
        "from functools import partialmethod, singledispatchmethod\n"
        "\n"
        "from settling import settle\n"
        "\n"
        "class Halved:\n"
        "    __init__ = partialmethod(settle, rate=1)\n"
        "\n"
        "class Dispatched:\n"
        "    __init__ = singledispatchmethod(settle)\n",
    )

    assert named_classes(getattr(resettling, name)) == {fractions.Fraction, int}


def test_a_new_is_read_as_getattr_gives_it_not_bound_to_the_class_again_so_names_the_classes_the_module_spelling_that_object_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reader is a callable data descriptor: inspect reads it through its __call__, and binding it again would give rebound, which the module of Gated spells."""
    imported_module(
        tmp_path,
        monkeypatch,
        "gating",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Reader:\n"
        "    def __init__(self, rebound):\n"
        "        self.rebound = rebound\n"
        "\n"
        "    def __call__(self, cls, share: 'Share') -> None: ...\n"
        "\n"
        "    def __get__(self, instance, owner):\n"
        "        return self.rebound\n"
        "\n"
        "    def __set__(self, instance, value): ...\n",
    )
    regating = imported_module(
        tmp_path,
        monkeypatch,
        "regating",
        "from decimal import Decimal as Share\n"
        "\n"
        "from gating import Reader\n"
        "\n"
        "def rebound(cls, share: 'Share') -> None: ...\n"
        "\n"
        "class Gated:\n"
        "    __new__ = staticmethod(Reader(rebound))\n",
    )

    assert named_classes(regating.Gated) == {fractions.Fraction}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Reinitialised", id="init"),
        pytest.param("Renewed", id="new"),
        pytest.param("Recalled", id="metaclass-call"),
    ],
)
def test_a_class_whose_new_init_or_metaclass_call_inspect_binds_to_none_names_the_classes_the_module_spelling_the_constructor_inspect_reads_in_its_place_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "skipping",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Created:\n"
        "    def __new__(cls, share: 'Share') -> None: ...\n"
        "\n"
        "class Initialised:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )
    reskipping = imported_module(
        tmp_path,
        monkeypatch,
        "reskipping",
        "from decimal import Decimal as Share\n"
        "\n"
        "from skipping import Created, Initialised\n"
        "\n"
        "class Skipping(type):\n"
        "    __call__ = staticmethod(None)\n"
        "\n"
        "class Reinitialised(Created):\n"
        "    __init__ = None\n"
        "\n"
        "class Renewed(Initialised):\n"
        "    __new__ = None\n"
        "\n"
        "class Recalled(Initialised, metaclass=Skipping):\n"
        "    pass\n",
    )

    assert named_classes(getattr(reskipping, name)) == {fractions.Fraction}


@pytest.mark.parametrize("given", GIVEN_BY_A_METACLASS_GET)
@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Built", id="init"),
        pytest.param("Called", id="metaclass-call"),
    ],
)
def test_a_class_whose_init_or_metaclass_call_is_a_class_whose_metaclass_defines_get_names_the_classes_the_module_spelling_that_class_constructor_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str, given: object
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "getting",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Getting(type):\n"
        "    def __get__(cls, instance, owner=None):\n"
        f"        return {given!r}\n"
        "\n"
        "class Held(metaclass=Getting):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )
    regetting = imported_module(
        tmp_path,
        monkeypatch,
        "regetting",
        "from decimal import Decimal as Share\n"
        "\n"
        "from getting import Held\n"
        "\n"
        "class Built:\n"
        "    __init__ = Held\n"
        "\n"
        "class Calling(type):\n"
        "    __call__ = Held\n"
        "\n"
        "class Called(metaclass=Calling):\n"
        "    pass\n",
    )

    assert named_classes(getattr(regetting, name)) == {fractions.Fraction}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("RenewedByABuiltin", id="builtin-as-new"),
        pytest.param("RenewedByAMethodWrapper", id="staticmethod-of-a-method-wrapper-as-new"),
        pytest.param("ReinitialisedByASlotWrapper", id="slot-wrapper-as-init"),
        pytest.param("ReinitialisedByAMethodWrapper", id="method-wrapper-as-init"),
    ],
)
def test_a_class_whose_new_or_init_inspect_skips_as_defined_in_c_names_the_classes_the_module_spelling_the_constructor_inspect_reads_in_its_place_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "shadowing",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Created:\n"
        "    def __new__(cls, share: 'Share') -> None: ...\n"
        "\n"
        "class Initialised:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )
    reshadowing = imported_module(
        tmp_path,
        monkeypatch,
        "reshadowing",
        "from decimal import Decimal as Share\n"
        "\n"
        "from shadowing import Created, Initialised\n"
        "\n"
        "class RenewedByABuiltin(Initialised):\n"
        "    __new__ = object.__new__\n"
        "\n"
        "class RenewedByAMethodWrapper(Initialised):\n"
        "    __new__ = staticmethod(object().__init__)\n"
        "\n"
        "class ReinitialisedByASlotWrapper(Created):\n"
        "    __init__ = object.__init__\n"
        "\n"
        "class ReinitialisedByAMethodWrapper(Created):\n"
        "    __init__ = object().__init__\n",
    )

    assert named_classes(getattr(reshadowing, name)) == {fractions.Fraction}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Assigned", id="assigned"),
        pytest.param("Wrapping", id="functools-wraps-wrapper"),
    ],
)
def test_a_constructor_generated_for_another_class_than_the_one_assigning_it_raises_type_error_naming_that_class_and_the_function(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "sourcing",
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "@dataclass\n"
        "class Source:\n"
        "    share: 'Share'\n",
    )
    borrowing = imported_module(
        tmp_path,
        monkeypatch,
        "borrowing",
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
        "    def __init__(self, *args, **kwargs) -> None: ...\n",
    )

    with pytest.raises(
        TypeError,
        match=rf"^borrowing\.{name} is constructed through sourcing\.Source\.__init__, "
        rf"a function generated for another class and assigned in the body of borrowing\.{name}, ",
    ):
        named_classes(getattr(borrowing, name))
