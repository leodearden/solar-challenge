# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes, one per test.

Gauge is defined at module level, where its forward reference to itself resolves in this
module's namespace.
"""

import collections.abc
import datetime
import decimal
import enum
import fractions
import functools
import gc
import pathlib
import sys
import types
import weakref
from dataclasses import InitVar, dataclass
from typing import (
    TYPE_CHECKING,
    Annotated,
    Callable,
    List,
    Literal,
    NewType,
    NoReturn,
    Optional,
    ParamSpec,
    Self,
    Type,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
)

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import Outer, Preset, imported_module

if TYPE_CHECKING:
    from decimal import Decimal


class Gauge:
    """A class with a public member of each kind member_forms spells, each annotated with its own class, and a private one."""

    reading: datetime.timedelta
    UNITS = "kWh"

    def __init__(self, site: pathlib.Path) -> None: ...

    def read(self, at: datetime.datetime) -> float: ...

    @classmethod
    def default(cls) -> "Gauge": ...

    @staticmethod
    def scale(kwh: int) -> int: ...

    @property
    def tariff(self) -> Preset: ...

    @functools.cached_property
    def inner(self) -> Outer.Inner: ...

    def _cache(self) -> bytes: ...


def test_a_generic_names_its_origin_and_its_arguments_classes() -> None:
    def f(
        a: list[Preset],
        b: dict[str, Outer.Inner],
        c: Callable[[Preset], float],
        d: tuple[int, ...],
    ) -> None: ...

    assert named_classes(f) == {
        list,
        Preset,
        dict,
        str,
        Outer.Inner,
        collections.abc.Callable,
        float,
        tuple,
        int,
    }


def test_a_bare_typing_alias_names_its_origin() -> None:
    def f(a: List, b: Callable, c: Type) -> None: ...

    assert named_classes(f) == {list, collections.abc.Callable, type}


def test_a_union_names_its_members_classes_alone() -> None:
    def f(a: Optional[Preset], b: Union[int, str], c: float | None) -> None: ...

    assert named_classes(f) == {Preset, int, str, float}


def test_an_init_only_variable_names_its_type_classes_alone() -> None:
    @dataclass(frozen=True)
    class Reading:
        kwh: float
        ratio: InitVar[Optional[fractions.Fraction]]
        preset: "InitVar[Preset]"

    assert named_classes(Reading) == {float, fractions.Fraction, Preset}


def test_literal_values_and_annotated_metadata_name_no_class() -> None:
    def f(a: Literal["Preset"], b: Annotated[float, Preset]) -> None: ...

    assert named_classes(f) == {float}


def test_a_param_spec_args_and_kwargs_name_no_class() -> None:
    P = ParamSpec("P")

    def f(*args: P.args, **kwargs: P.kwargs) -> None: ...

    assert named_classes(f) == set()


def test_a_type_variable_declaring_nothing_or_a_special_form_names_no_class() -> None:
    T = TypeVar("T")
    P = ParamSpec("P")
    Ts = TypeVarTuple("Ts")

    def f(a: T, b: P, c: Ts, d: Self) -> NoReturn: ...

    assert named_classes(f) == set()


def test_a_type_variable_names_the_classes_its_constraints_and_its_bound_name() -> None:
    Rated = TypeVar("Rated", bound=Optional[Preset])
    Pending = TypeVar("Pending", bound="Outer.Inner")
    Ratio = TypeVar("Ratio", int, fractions.Fraction)

    def f(a: Rated, b: Pending) -> Ratio: ...

    assert named_classes(f) == {Preset, Outer.Inner, int, fractions.Fraction}


@pytest.mark.skipif(
    sys.version_info < (3, 13), reason="a type variable's default is new in Python 3.13"
)
def test_a_type_variable_names_the_classes_its_default_names() -> None:
    Rated = TypeVar("Rated", default=Preset)
    Hook = ParamSpec("Hook", default=[fractions.Fraction])
    Shape = TypeVarTuple("Shape", default=Unpack[tuple[Outer.Inner]])

    def f(a: Rated, b: Callable[Hook, None], c: tuple[Unpack[Shape]]) -> None: ...

    assert named_classes(f) == {
        Preset,
        collections.abc.Callable,
        fractions.Fraction,
        tuple,
        Outer.Inner,
    }


def test_a_new_type_names_its_supertype_classes_alone() -> None:
    PresetId = NewType("PresetId", Preset)
    Readings = NewType("Readings", list[Outer.Inner])

    def f(a: PresetId, b: Readings) -> None: ...

    assert named_classes(f) == {Preset, list, Outer.Inner}


def test_none_and_type_none_name_no_class() -> None:
    def with_none(readings: list[None]) -> None: ...

    def with_type_none(readings: List[None]) -> types.NoneType: ...

    assert named_classes(with_none) == {list}
    assert named_classes(with_type_none) == {list}


def test_a_string_annotation_or_a_forward_reference_names_the_class_its_module_binds_the_name_to() -> None:
    def f(a: "Preset", b: Optional["Outer.Inner"]) -> "list[Preset]": ...

    assert named_classes(f) == {Preset, Outer.Inner, list}


def test_a_name_its_module_imports_only_for_type_checking_names_the_class_that_import_binds() -> None:
    def f(amount: "Decimal") -> None: ...

    assert named_classes(f) == {decimal.Decimal}


def test_a_name_its_module_imports_only_for_type_checking_names_the_class_its_own_import_binds_whatever_an_earlier_module_of_the_same_name_imported(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )
    assert named_classes(earlier.audit) == {fractions.Fraction}
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    assert named_classes(later.audit) == {decimal.Decimal}


def test_a_routine_whose_module_another_module_of_the_same_name_has_since_replaced_in_sys_modules_raises_a_lookup_error_naming_both(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(earlier.audit)

    assert earlier.__file__ in str(raised.value)
    assert later.__file__ in str(raised.value)


def test_a_routine_relabelled_with_another_modules_name_names_the_class_the_module_whose_globals_it_carries_binds_the_name_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(tmp_path, monkeypatch, "publishing", "from decimal import Decimal as Share\n")
    relabelling = imported_module(
        tmp_path,
        monkeypatch,
        "relabelling",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n"
        "\n"
        "audit.__module__ = 'publishing'\n",
    )
    renaming = imported_module(
        tmp_path,
        monkeypatch,
        "renaming",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "__name__ = 'publishing'\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    assert named_classes(relabelling.audit) == {fractions.Fraction}
    assert named_classes(renaming.audit) == {fractions.Fraction}


def test_a_class_its_module_no_longer_binds_since_another_module_of_the_same_name_replaced_it_in_sys_modules_raises_a_lookup_error_naming_it_and_the_replacement(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "class Plain:\n"
        "    share: 'Share'\n"
        "\n"
        "class Lone:\n"
        "    share: 'Share'\n",
    )
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "class Plain:\n"
        "    share: 'Share'\n",
    )

    with pytest.raises(LookupError) as replaced:
        named_classes(earlier.Plain)
    with pytest.raises(LookupError) as unbound:
        named_classes(earlier.Lone)

    assert "auditing.Plain" in str(replaced.value)
    assert later.__file__ in str(replaced.value)
    assert "auditing.Lone" in str(unbound.value)
    assert later.__file__ in str(unbound.value)


def test_a_class_a_function_of_a_module_built_once_another_module_of_the_same_name_has_since_replaced_it_in_sys_modules_raises_a_lookup_error_naming_both(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "def build():\n"
        "    class Local:\n"
        "        def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "    return Local\n",
    )
    local = earlier.build()
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "def build():\n"
        "    class Local:\n"
        "        def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "    return Local\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(local)

    assert earlier.__file__ in str(raised.value)
    assert later.__file__ in str(raised.value)


def test_a_routine_that_wraps_a_class_whose_module_another_module_of_the_same_name_has_since_replaced_in_sys_modules_raises_a_lookup_error_naming_the_class_and_the_replacement(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from functools import wraps\n"
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "class Audit:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "@wraps(Audit)\n"
        "def audit(*args, **kwargs):\n"
        "    return Audit(*args, **kwargs)\n",
    )
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from functools import wraps\n"
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal as Share\n"
        "\n"
        "class Audit:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "@wraps(Audit)\n"
        "def audit(*args, **kwargs):\n"
        "    return Audit(*args, **kwargs)\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(earlier.audit)

    assert "auditing.Audit" in str(raised.value)
    assert later.__file__ in str(raised.value)


def test_a_routine_a_class_or_a_type_variable_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_it_and_that_modules_name(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "from functools import wraps\n"
        "from typing import TYPE_CHECKING, TypeVar\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
        "\n"
        "Portion = TypeVar('Portion', bound='Share')\n"
        "\n"
        "def settle(share: 'Share') -> None: ...\n"
        "\n"
        "class Audit:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "@wraps(Audit)\n"
        "def audit(*args, **kwargs):\n"
        "    return Audit(*args, **kwargs)\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, owner, share: 'Share') -> None: ...\n",
    )

    def portion(share: auditing.Portion) -> None: ...

    called = types.MethodType(auditing.Caller(), object())
    monkeypatch.delitem(sys.modules, "auditing")

    for obj, label in (
        (auditing.settle, "auditing.settle"),
        (auditing.Audit, "auditing.Audit"),
        (auditing.audit, "auditing.Audit"),
        (portion, repr(auditing.Portion)),
        (called, repr(called)),
    ):
        with pytest.raises(LookupError) as raised:
            named_classes(obj)
        assert label in str(raised.value)
        assert "'auditing'" in str(raised.value)


def test_a_static_type_its_module_does_not_bind_under_its_qualified_name_names_the_classes_its_forms_name() -> None:
    assert named_classes(types.ModuleType) == set()
    assert named_classes(types.FunctionType) == set()


def test_a_routine_cpython_defines_in_c_names_no_class() -> None:
    assert named_classes(str.join) == set()
    assert named_classes(", ".join) == set()
    assert named_classes(vars(dict)["fromkeys"]) == set()
    assert named_classes(object.__init__) == set()
    assert named_classes((1).__add__) == set()


def test_a_routine_or_class_whose_signature_annotates_nothing_names_no_class_though_another_module_of_the_same_name_has_since_replaced_its_own(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "def audit(share): ...\n\n\nclass Audit:\n    def __init__(self, share): ...\n"
    earlier = imported_module(tmp_path_factory.mktemp("earlier"), monkeypatch, "auditing", source)
    imported_module(tmp_path_factory.mktemp("later"), monkeypatch, "auditing", source)

    assert named_classes(earlier.audit) == set()
    assert named_classes(earlier.Audit) == set()


def test_a_module_whose_string_annotation_named_classes_read_is_not_kept_alive_once_dropped(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        settling = imported_module(
            tmp_path,
            monkeypatch,
            "settling",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from decimal import Decimal\n"
            "\n"
            "def settle(amount: 'Decimal') -> None: ...\n",
        )
        assert named_classes(settling.settle) == {decimal.Decimal}
    dropped = weakref.ref(settling)
    del settling
    gc.collect()

    assert dropped() is None


def test_an_unresolvable_forward_reference_raises_a_name_error_naming_it() -> None:
    def f(a: "Nowhere") -> None: ...  # noqa: F821

    with pytest.raises(NameError, match="Nowhere"):
        named_classes(f)


def test_a_class_names_the_classes_its_constructor_and_each_public_member_name() -> None:
    assert named_classes(Gauge) == {
        pathlib.Path,
        datetime.timedelta,
        str,
        datetime.datetime,
        float,
        Gauge,
        int,
        Preset,
        Outer.Inner,
    }


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


def test_a_partial_names_the_classes_the_callable_it_wraps_names_each_read_where_that_callable_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    halving = imported_module(
        tmp_path,
        monkeypatch,
        "halving",
        "from fractions import Fraction\n"
        "from functools import partial\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, ratio: 'Fraction') -> None: ...\n"
        "\n"
        "def settle(share: 'Fraction', rate: int) -> None: ...\n"
        "\n"
        "half = partial(settle, rate=1)\n",
    )

    class Submeter(halving.Meter):
        pass

    assert named_classes(halving.half) == {fractions.Fraction, int}
    assert named_classes(functools.partial(Submeter)) == {fractions.Fraction}


def test_a_routine_that_wraps_another_callable_names_the_classes_that_callable_names_each_read_where_that_callable_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "from functools import partial, wraps\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n"
        "\n"
        "half = partial(settle, rate=1)\n"
        "\n"
        "def logged(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "    return wrapper\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "\n"
        "from metering import Meter, half, logged\n"
        "\n"
        "class Submeter(Meter):\n"
        "    pass\n"
        "\n"
        "submeter = logged(Submeter)\n"
        "halved = logged(half)\n"
        "\n"
        "@logged\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    assert named_classes(submetering.submeter) == {fractions.Fraction}
    assert named_classes(submetering.halved) == {fractions.Fraction, int}
    assert named_classes(submetering.audit) == {decimal.Decimal}


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


def test_a_forward_reference_a_type_variable_declares_names_the_class_the_module_declaring_it_binds_the_name_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rating = imported_module(
        tmp_path,
        monkeypatch,
        "rating",
        "from fractions import Fraction\n"
        "from typing import TypeVar\n"
        "\n"
        "Ratio = TypeVar('Ratio', bound='Fraction')\n",
    )

    def f(ratio: rating.Ratio) -> None: ...

    assert named_classes(f) == {fractions.Fraction}


def test_a_forward_reference_a_new_type_declares_names_the_class_the_module_declaring_it_binds_the_name_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ratingnewtype = imported_module(
        tmp_path,
        monkeypatch,
        "ratingnewtype",
        "from fractions import Fraction\n"
        "from typing import NewType\n"
        "\n"
        "Ratio = NewType('Ratio', 'Fraction')\n",
    )

    def f(ratio: ratingnewtype.Ratio) -> None: ...

    assert named_classes(f) == {fractions.Fraction}


def test_a_type_variable_or_a_new_type_inside_its_own_declaration_names_no_class_there(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linking = imported_module(
        tmp_path,
        monkeypatch,
        "linking",
        "from typing import Generic, NewType, TypeVar\n"
        "\n"
        "Linked = TypeVar('Linked', bound='Node[Linked]')\n"
        "Ranked = TypeVar('Ranked', bound='list[Graded]')\n"
        "Graded = TypeVar('Graded', bound='dict[str, Ranked]')\n"
        "Chain = NewType('Chain', 'list[Chain]')\n"
        "\n"
        "class Node(Generic[Linked]): ...\n",
    )

    def f(a: linking.Linked, b: linking.Ranked, c: linking.Chain) -> None: ...

    assert (
        surface_form(f)
        == "(a: ~Linked(bound=Node[Linked]), b: ~Ranked(bound=list[Graded]), c: Chain(list[Chain])) -> None"
    )
    assert named_classes(f) == {linking.Node, list, dict, str}


def test_a_forward_reference_inside_its_own_evaluation_names_no_class_there(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = imported_module(
        tmp_path,
        monkeypatch,
        "documents",
        "from typing import Union\n"
        "\n"
        "JSON = Union[dict[str, 'JSON'], list['JSON'], str, None]\n"
        "Tree = tuple[int, 'Forest']\n"
        "Forest = list['Tree']\n"
        "\n"
        "def store(document: JSON) -> None: ...\n"
        "\n"
        "def send(document: 'JSON') -> None: ...\n"
        "\n"
        "def plant(tree: Tree) -> None: ...\n",
    )

    assert named_classes(documents.store) == {dict, str, list}
    assert named_classes(documents.send) == {dict, str, list}
    assert named_classes(documents.plant) == {tuple, int, list}


def test_a_forward_reference_inside_its_own_evaluation_names_the_class_another_module_evaluating_it_binds_it_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "sharing",
        "from fractions import Fraction as Ratio\n"
        "from typing import NewType\n"
        "\n"
        "Share = NewType('Share', 'Ratio')\n",
    )
    pooling = imported_module(
        tmp_path,
        monkeypatch,
        "pooling",
        "from typing import Union\n"
        "\n"
        "import sharing\n"
        "\n"
        "Ratio = Union[sharing.Share, list['Ratio']]\n"
        "\n"
        "def pool(ratio: 'Ratio') -> None: ...\n",
    )

    assert named_classes(pooling.pool) == {fractions.Fraction, list}


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="type parameter syntax is new in Python 3.12"
)
def test_a_forward_reference_a_type_parameter_declares_names_the_class_the_module_of_its_routine_binds_the_name_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoping = imported_module(
        tmp_path,
        monkeypatch,
        "scoping",
        "class Counter: ...\n\n\ndef tally[T: 'Counter'](counter: T) -> T: ...\n",
    )

    assert named_classes(scoping.tally) == {scoping.Counter}


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="type parameter syntax is new in Python 3.12"
)
def test_a_forward_reference_to_a_type_parameter_raises_a_name_error_naming_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bounding = imported_module(
        tmp_path,
        monkeypatch,
        "bounding",
        "class Node[T]: ...\n\n\ndef link[T: 'Node[T]'](node: T) -> T: ...\n",
    )

    with pytest.raises(NameError, match="'T'"):
        named_classes(bounding.link)


def test_a_default_value_names_no_class() -> None:
    def f(at: object = Preset(rate=0.1)) -> None: ...

    assert named_classes(f) == {object}


def test_an_enum_names_its_methods_classes_but_not_its_members() -> None:
    class Period(enum.Enum):
        PEAK = 1.5

        def label(self) -> str: ...

    assert named_classes(Period) == {str}


def test_a_constant_names_its_type() -> None:
    assert named_classes({"a": 1}) == {dict}
    assert named_classes(Preset(rate=0.1)) == {Preset}
