# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the callable or class that spells a class's signature, the constructor inspect reads for it or the class holding a signature it carries, and the errors raised when neither is known, one per test."""

import decimal
import fractions
import functools
import inspect
import pathlib
import warnings
from collections.abc import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR,
    imported_module,
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


def test_a_class_names_the_classes_its_signature_names_read_where_its_constructor_is_spelled_though_the_class_carries_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, share: 'Share', rate: int) -> None: ...\n",
    )
    imported_module(
        tmp_path,
        monkeypatch,
        "decorating",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "def without_rate(cls):\n"
        "    signature = inspect.signature(cls)\n"
        "    parameters = list(signature.parameters.values())[:1]\n"
        "    cls.__signature__ = signature.replace(parameters=parameters)\n"
        "    return cls\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "\n"
        "from decorating import without_rate\n"
        "from metering import Meter\n"
        "\n"
        "@without_rate\n"
        "class Submeter(Meter):\n"
        "    pass\n",
    )

    assert named_classes(submetering.Submeter) == {fractions.Fraction}


def test_a_class_constructed_by_object_or_in_c_names_the_classes_its_signature_names_read_where_the_class_holding_that_signature_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rates = imported_module(
        tmp_path,
        monkeypatch,
        "rates",
        "import collections\n"
        "import functools\n"
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Rated(dict):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Ordered(collections.OrderedDict):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Plain:\n"
        "    __signature__ = signature\n"
        "\n"
        "class Counting(type):\n"
        "    @functools.wraps(type.__call__)\n"
        "    def __call__(cls, *args, **kwargs):\n"
        "        return super().__call__(*args, **kwargs)\n"
        "\n"
        "class Counted(metaclass=Counting):\n"
        "    __signature__ = signature\n",
    )
    rerates = imported_module(
        tmp_path,
        monkeypatch,
        "rerates",
        "from decimal import Decimal as Share\n"
        "\n"
        "from rates import Rated\n"
        "\n"
        "class Rerated(Rated):\n"
        "    pass\n",
    )

    assert named_classes(rates.Rated) == {fractions.Fraction}
    assert named_classes(rates.Ordered) == {fractions.Fraction}
    assert named_classes(rates.Plain) == {fractions.Fraction}
    assert named_classes(rates.Counted) == {fractions.Fraction}
    assert named_classes(functools.partial(rates.Rated)) == {fractions.Fraction}
    assert named_classes(rerates.Rerated) == {fractions.Fraction}


def test_a_class_whose_metaclass_holds_its_signature_raises_type_error_naming_the_class_and_that_metaclass_whatever_its_constructor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metas",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Signed(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "class PropertySigned(type):\n"
        "    @property\n"
        "    def __signature__(cls):\n"
        "        return signature\n"
        "\n"
        "class CallingSigned(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "    def __call__(cls, share: 'Share') -> None: ...\n",
    )
    users = imported_module(
        tmp_path,
        monkeypatch,
        "users",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from metas import CallingSigned, PropertySigned, Signed\n"
        "\n"
        "class Rated(dict, metaclass=Signed):\n"
        "    pass\n"
        "\n"
        "class DefinedRated(metaclass=Signed):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Overridden(dict, metaclass=PropertySigned):\n"
        "    __signature__ = inspect.Signature()\n"
        "\n"
        "class DefinedOverridden(metaclass=PropertySigned):\n"
        "    __signature__ = inspect.Signature()\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Called(metaclass=CallingSigned):\n"
        "    pass\n",
    )

    with pytest.raises(TypeError) as plain:
        named_classes(users.Rated)
    with pytest.raises(TypeError) as defined_plain:
        named_classes(users.DefinedRated)
    with pytest.raises(TypeError) as overriding:
        named_classes(users.Overridden)
    with pytest.raises(TypeError) as defined_overriding:
        named_classes(users.DefinedOverridden)
    with pytest.raises(TypeError) as called:
        named_classes(users.Called)

    assert "users.Rated" in str(plain.value)
    assert "metas.Signed" in str(plain.value)
    assert "users.DefinedRated" in str(defined_plain.value)
    assert "metas.Signed" in str(defined_plain.value)
    assert "users.Overridden" in str(overriding.value)
    assert "metas.PropertySigned" in str(overriding.value)
    assert "users.DefinedOverridden" in str(defined_overriding.value)
    assert "metas.PropertySigned" in str(defined_overriding.value)
    assert "users.Called" in str(called.value)
    assert "metas.CallingSigned" in str(called.value)


def test_a_class_whose_metaclass_defines_getattribute_raises_type_error_whatever_its_constructor_but_one_that_shadows_its_metaclass_attribute_names_its_own_signatures_classes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "lookup_metas",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('meta', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class PlainSigned(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Intercepting(type):\n"
        "    def __getattribute__(cls, name):\n"
        "        if name == '__signature__':\n"
        "            return signature\n"
        "        return super().__getattribute__(name)\n",
    )
    lookup_users = imported_module(
        tmp_path,
        monkeypatch,
        "lookup_users",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from lookup_metas import Intercepting, PlainSigned\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Shadowed(dict, metaclass=PlainSigned):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Intercepted(dict, metaclass=Intercepting):\n"
        "    __signature__ = signature\n"
        "\n"
        "class DefinedIntercepted(metaclass=Intercepting):\n"
        "    __signature__ = signature\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )

    with pytest.raises(TypeError) as intercepted:
        named_classes(lookup_users.Intercepted)
    with pytest.raises(TypeError) as defined_intercepted:
        named_classes(lookup_users.DefinedIntercepted)

    assert "lookup_users.Intercepted" in str(intercepted.value)
    assert "lookup_metas.Intercepting" in str(intercepted.value)
    assert "lookup_users.DefinedIntercepted" in str(defined_intercepted.value)
    assert "lookup_metas.Intercepting" in str(defined_intercepted.value)
    assert named_classes(lookup_users.Shadowed) == {decimal.Decimal}


def test_a_class_whose_signature_a_descriptor_gives_raises_type_error_naming_it_the_class_holding_that_descriptor_and_its_type_whatever_its_constructor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "describing",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Describing:\n"
        "    def __get__(self, instance, owner):\n"
        "        return signature\n",
    )
    described = imported_module(
        tmp_path,
        monkeypatch,
        "described",
        "from decimal import Decimal as Share\n"
        "\n"
        "from describing import Describing\n"
        "\n"
        "class Described(dict):\n"
        "    __signature__ = Describing()\n"
        "\n"
        "class Redescribed(Described):\n"
        "    pass\n"
        "\n"
        "class DefinedDescribed:\n"
        "    __signature__ = Describing()\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )

    with pytest.raises(TypeError) as own:
        named_classes(described.Described)
    with pytest.raises(TypeError) as inherited:
        named_classes(described.Redescribed)
    with pytest.raises(TypeError) as defined:
        named_classes(described.DefinedDescribed)

    assert "described.Described" in str(own.value)
    assert "describing.Describing" in str(own.value)
    assert "builtins.type" not in str(own.value)
    assert "described.Redescribed" in str(inherited.value)
    assert "described.Described" in str(inherited.value)
    assert "describing.Describing" in str(inherited.value)
    assert "described.DefinedDescribed" in str(defined.value)
    assert "describing.Describing" in str(defined.value)


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


def test_an_inherited_init_only_variable_names_the_classes_the_module_of_the_dataclass_declaring_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "priming",
        "from dataclasses import InitVar, dataclass\n"
        "from fractions import Fraction as Prime\n"
        "\n"
        "@dataclass\n"
        "class Meter:\n"
        "    prime: InitVar['Prime']\n",
    )
    repriming = imported_module(
        tmp_path,
        monkeypatch,
        "repriming",
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Prime\n"
        "\n"
        "from priming import Meter\n"
        "\n"
        "@dataclass\n"
        "class Submeter(Meter): ...\n",
    )

    assert named_classes(repriming.Submeter) == {fractions.Fraction}


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
        "    __init__ = Caller()\n",
    )

    assert named_classes(revalving.Submeter) == {decimal.Decimal}
    assert named_classes(revalving.LoggedSubmeter) == {decimal.Decimal}
    assert named_classes(revalving.Resubmeter) == {decimal.Decimal}
    assert named_classes(revalving.CalledSubmeter) == {decimal.Decimal}


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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Recreated", id="new"),
        pytest.param("Reinitialised", id="init"),
    ],
)
def test_a_class_that_carries_a_signature_over_a_constructor_that_wraps_a_callable_defined_in_c_names_the_classes_that_signature_names_read_where_the_class_holding_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "wrapping",
        "from fractions import Fraction as Share\n"
        "from functools import wraps\n"
        "\n"
        "class Created:\n"
        "    @wraps(object.__new__)\n"
        "    def __new__(cls, *args, **kwargs):\n"
        "        return object.__new__(cls)\n"
        "\n"
        "class Initialised:\n"
        "    @wraps(object.__init__)\n"
        "    def __init__(self, *args, **kwargs) -> None: ...\n",
    )
    signing = imported_module(
        tmp_path,
        monkeypatch,
        "signing",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from wrapping import Created, Initialised\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Recreated(Created):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Reinitialised(Initialised):\n"
        "    __signature__ = signature\n",
    )

    assert named_classes(getattr(signing, name)) == {decimal.Decimal}


@pytest.mark.parametrize("wrap", CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR)
def test_a_class_that_carries_a_signature_over_a_classmethod_constructor_whose_binding_differs_by_minor_names_the_classes_that_signature_names(
    wrap: Callable[[Callable[..., object]], object],
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Initialised:
        __signature__ = signature
        __init__ = classmethod(wrap(build))

    class Created:
        __signature__ = signature
        __new__ = classmethod(wrap(build))

    class Calling(type):
        __call__ = classmethod(wrap(build))

    class Called(metaclass=Calling):
        __signature__ = signature

    for cls in (Initialised, Created, Called):
        assert surface_form(cls) == "(rate: int)"
        assert named_classes(cls) == {int}


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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Initialised", id="init"),
        pytest.param("Called", id="metaclass-call"),
    ],
)
def test_a_functools_partial_constructor_of_a_class_that_carries_a_signature_is_read_unbound_without_a_warning_and_names_the_classes_the_module_of_the_function_it_wraps_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "partialling",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(self, share: 'Share', rate: int) -> None: ...\n",
    )
    repartialling = imported_module(
        tmp_path,
        monkeypatch,
        "repartialling",
        "import functools\n"
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from partialling import settle\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Settling(type):\n"
        "    __call__ = functools.partial(settle, rate=1)\n"
        "\n"
        "class Initialised:\n"
        "    __signature__ = signature\n"
        "    __init__ = functools.partial(settle, rate=1)\n"
        "\n"
        "class Called(metaclass=Settling):\n"
        "    __signature__ = signature\n",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        classes = named_classes(getattr(repartialling, name))

    assert classes == {fractions.Fraction}


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

    with pytest.raises(TypeError) as raised:
        named_classes(getattr(borrowing, name))

    assert f"borrowing.{name}" in str(raised.value)
    assert "sourcing.Source.__init__" in str(raised.value)
