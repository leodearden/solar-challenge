# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes, one per test.

_typed is defined at module level, where its lambda carries this module's globals.
"""

import _json
import collections
import collections.abc
import datetime
import decimal
import fractions
import functools
import gc
import inspect
import operator
import pathlib
import sys
import types
import weakref
from typing import TYPE_CHECKING, Callable, Optional

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import Outer, Preset, imported_module

if TYPE_CHECKING:
    from decimal import Decimal


def _typed(function: Callable[..., object], *receivers: str) -> Callable[..., object]:
    """A wrapper of *function*, as functools.wraps records one, given a signature here: *receivers*, then share annotated with the string "Decimal", which this module binds only for type checking."""
    wrapper = functools.wraps(function)(lambda *args: function(*args))
    wrapper.__signature__ = inspect.Signature(
        [
            *(inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD) for name in receivers),
            inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Decimal"),
        ]
    )
    return wrapper


_RELAYING_SOURCE = (
    "import inspect\n"
    "from fractions import Fraction as Decimal\n"
    "from functools import wraps\n"
    "\n"
    "def relay(function):\n"
    "    return wraps(function)(lambda *args: function(*args))\n"
    "\n"
    "def resign(function, dropping=0):\n"
    "    signature = inspect.signature(function)\n"
    "    resigned = relay(function)\n"
    "    parameters = list(signature.parameters.values())[dropping:]\n"
    "    resigned.__signature__ = signature.replace(parameters=parameters)\n"
    "    return resigned\n"
)


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
    """Local's __init__ annotates nothing, so only Local's own module is looked up, for its attribute, and __init__ carries the globals of the module that built Local."""
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
        "        share: 'Share'\n"
        "\n"
        "        def __init__(self): ...\n"
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
        "        share: 'Share'\n"
        "\n"
        "        def __init__(self): ...\n"
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


def test_a_routine_that_wraps_a_callable_object_whose_call_methods_module_another_module_of_the_same_name_has_since_replaced_in_sys_modules_raises_a_lookup_error_naming_that_method_and_the_replacement(
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
        "class Caller:\n"
        "    def __call__(self, share: 'Share') -> None: ...\n"
        "\n"
        "caller = Caller()\n"
        "\n"
        "@wraps(caller)\n"
        "def call(*args, **kwargs):\n"
        "    return caller(*args, **kwargs)\n",
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
        "class Caller:\n"
        "    def __call__(self, share: 'Share') -> None: ...\n"
        "\n"
        "caller = Caller()\n"
        "\n"
        "@wraps(caller)\n"
        "def call(*args, **kwargs):\n"
        "    return caller(*args, **kwargs)\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(earlier.call)

    assert "auditing.Caller.__call__" in str(raised.value)
    assert later.__file__ in str(raised.value)


@pytest.fixture
def removed_auditing(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """The module 'auditing', imported and then removed from sys.modules, that defines a type variable, a routine, a class, a routine that wraps the class, and a class whose instances are callable."""
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
    monkeypatch.delitem(sys.modules, "auditing")
    return auditing


def test_a_routine_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_it_and_that_modules_name(
    removed_auditing: types.ModuleType,
) -> None:
    with pytest.raises(LookupError) as raised:
        named_classes(removed_auditing.settle)

    assert "auditing.settle" in str(raised.value)
    assert "'auditing'" in str(raised.value)


def test_a_class_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_it_and_that_modules_name(
    removed_auditing: types.ModuleType,
) -> None:
    with pytest.raises(LookupError) as raised:
        named_classes(removed_auditing.Audit)

    assert "auditing.Audit" in str(raised.value)
    assert "'auditing'" in str(raised.value)


def test_a_routine_that_wraps_a_class_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_the_class_and_that_modules_name(
    removed_auditing: types.ModuleType,
) -> None:
    with pytest.raises(LookupError) as raised:
        named_classes(removed_auditing.audit)

    assert "auditing.Audit" in str(raised.value)
    assert "'auditing'" in str(raised.value)


def test_a_type_variable_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_it_and_that_modules_name(
    removed_auditing: types.ModuleType,
) -> None:
    def portion(share: removed_auditing.Portion) -> None: ...

    with pytest.raises(LookupError) as raised:
        named_classes(portion)

    assert repr(removed_auditing.Portion) in str(raised.value)
    assert "'auditing'" in str(raised.value)


def test_a_method_bound_to_a_callable_object_whose_module_has_since_left_sys_modules_raises_a_lookup_error_naming_its_call_method_and_that_modules_name(
    removed_auditing: types.ModuleType,
) -> None:
    called = types.MethodType(removed_auditing.Caller(), object())

    with pytest.raises(LookupError) as raised:
        named_classes(called)

    assert "auditing.Caller.__call__" in str(raised.value)
    assert "'auditing'" in str(raised.value)


@pytest.mark.parametrize(
    "cls",
    [
        pytest.param(types.FunctionType, id="types.FunctionType"),
        pytest.param(type(reversed(collections.deque())), id="deque_reverse_iterator"),
    ],
)
def test_a_partial_that_carries_a_signature_over_an_immutable_type_its_module_does_not_bind_under_its_qualified_name_names_that_signatures_classes(
    cls: type,
) -> None:
    """types.FunctionType is a static type; the deque reverse iterator is a heap type from Python 3.12."""
    made = functools.partial(cls)
    made.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    assert named_classes(made) == {int}


def test_a_class_defined_in_c_that_carries_a_signature_names_the_classes_its_forms_name_though_its_module_with_no_source_binds_it_under_another_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_json, built in or an extension module, binds _json.Scanner as make_scanner; the class's public members are member descriptors."""
    monkeypatch.setattr(
        _json.make_scanner,
        "__signature__",
        inspect.Signature(
            [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
        ),
        raising=False,
    )

    assert named_classes(_json.make_scanner) == {int, types.MemberDescriptorType}


def test_a_class_whose_module_one_with_no_source_has_since_replaced_in_sys_modules_raises_a_lookup_error_naming_it_and_its_own_module_if_its_body_compiled_a_function(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit's __init__ annotates nothing, so only Audit's own module is looked up, for its attribute. The replacement binds nothing under Audit, as a module inspect reads no source for may bind a class under another name, but __init__ carries the globals of the module that defined Audit."""
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "class Audit:\n    share: int\n\n    def __init__(self): ...\n",
    )
    monkeypatch.setitem(sys.modules, "auditing", types.ModuleType("auditing"))

    with pytest.raises(LookupError) as raised:
        named_classes(auditing.Audit)

    assert "auditing.Audit" in str(raised.value)
    assert auditing.__file__ in str(raised.value)


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


def test_a_string_annotation_read_in_a_module_inspect_reads_no_source_for_raises_a_type_error_naming_it_and_that_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsourced = types.ModuleType("unsourced")
    monkeypatch.setitem(sys.modules, "unsourced", unsourced)
    exec("def settle(share: 'Share') -> None: ...\n", vars(unsourced))

    with pytest.raises(TypeError, match=r"'Share'.*\bmodule 'unsourced'.*\bno source\b"):
        named_classes(unsourced.settle)

    monkeypatch.setattr(
        _json.make_scanner,
        "__signature__",
        inspect.Signature(
            [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Share")]
        ),
        raising=False,
    )

    with pytest.raises(TypeError, match=r"'Share'.*\bmodule '_json'.*\bno source\b"):
        named_classes(_json.make_scanner)


def test_an_unresolvable_forward_reference_raises_a_name_error_naming_it() -> None:
    def f(a: "Nowhere") -> None: ...  # noqa: F821

    with pytest.raises(NameError, match="Nowhere"):
        named_classes(f)


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


def test_a_partial_that_wraps_another_callable_as_functools_wraps_records_one_names_the_classes_that_callable_names_read_where_that_callable_is_spelled_not_where_its_func_is(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    billing = imported_module(
        tmp_path,
        monkeypatch,
        "billing",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    reconciling = imported_module(
        tmp_path,
        monkeypatch,
        "reconciling",
        "from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    audited = functools.update_wrapper(functools.partial(billing.settle, rate=1), reconciling.audit)

    assert named_classes(audited) == {decimal.Decimal}


def test_a_partial_that_wraps_another_callable_as_functools_wraps_records_one_but_carries_a_signature_of_none_names_the_classes_its_func_names_read_where_its_func_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    billing = imported_module(
        tmp_path,
        monkeypatch,
        "billing",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    reconciling = imported_module(
        tmp_path,
        monkeypatch,
        "reconciling",
        "from decimal import Decimal as Share\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n",
    )

    audited = functools.update_wrapper(functools.partial(billing.settle, rate=1), reconciling.audit)
    audited.__signature__ = None

    assert named_classes(audited) == {fractions.Fraction, int}


def test_a_routine_that_wraps_another_callable_names_the_classes_that_callable_names_read_where_that_callable_is_spelled_though_the_routine_carries_a_signature(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    imported_module(
        tmp_path,
        monkeypatch,
        "decorating",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "def without_rate(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "\n"
        "    signature = inspect.signature(function)\n"
        "    parameters = list(signature.parameters.values())[:1]\n"
        "    wrapper.__signature__ = signature.replace(parameters=parameters)\n"
        "    return wrapper\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decorating import without_rate\n"
        "from metering import settle\n"
        "\n"
        "settled = without_rate(settle)\n",
    )

    assert named_classes(submetering.settled) == {fractions.Fraction}


def test_a_routine_that_wraps_another_callable_but_carries_a_signature_of_none_names_the_classes_the_annotations_it_holds_name_read_where_they_are_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(share: 'Share', rate: int) -> None: ...\n",
    )
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "from datetime import date as Share\n"
        "\n"
        "from metering import settle\n"
        "\n"
        "def audit(share: 'Share') -> None: ...\n"
        "\n"
        "audit.__wrapped__ = settle\n"
        "audit.__signature__ = None\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "from functools import wraps\n"
        "\n"
        "from auditing import audit\n"
        "\n"
        "@wraps(audit)\n"
        "def reaudit(share: 'Share', extra: 'Share') -> 'Share': ...\n"
        "\n"
        "reaudit.__signature__ = None\n",
    )

    assert named_classes(auditing.audit) == {datetime.date}
    assert named_classes(submetering.reaudit) == {datetime.date}


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


@pytest.mark.parametrize(
    "routine",
    [
        pytest.param(_typed(len), id="builtin-function"),
        pytest.param(_typed(str.join), id="method-descriptor"),
        pytest.param(_typed(vars(dict)["fromkeys"]), id="classmethod-descriptor"),
        pytest.param(_typed((1).__add__), id="method-wrapper"),
        pytest.param(_typed(operator.itemgetter(1)), id="object-of-a-class-defined-in-c"),
        pytest.param(types.MethodType(_typed(len, "receiver"), object()), id="bound-method"),
    ],
)
def test_a_signature_a_link_carries_over_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    routine: Callable[..., object],
) -> None:
    assert named_classes(routine) == {decimal.Decimal}


def test_a_signature_a_link_carries_over_the_call_a_metaclass_resolves_that_wraps_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled() -> None:
    class Counting(type):
        __call__ = _typed(type.__call__, "receiver")

    class Counted(metaclass=Counting):
        pass

    assert named_classes(Counted) == {decimal.Decimal}


def test_a_signature_a_link_carries_over_the_call_of_a_callable_object_that_wraps_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled() -> None:
    class Caller:
        __call__ = _typed(len, "receiver")

    assert named_classes(functools.partial(Caller())) == {decimal.Decimal}


@pytest.mark.parametrize(
    "wrapped",
    [
        pytest.param(_typed(len), id="function"),
        pytest.param(types.MethodType(_typed(len, "receiver"), object()), id="bound-method"),
    ],
)
def test_a_signature_functools_wraps_copies_from_a_link_that_carries_one_over_a_routine_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    wrapped: Callable[..., object], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relaying = imported_module(tmp_path, monkeypatch, "relaying", _RELAYING_SOURCE)

    assert named_classes(relaying.relay(wrapped)) == {decimal.Decimal}


@pytest.mark.parametrize(
    ("wrapped", "dropping"),
    [
        pytest.param(_typed(len, "receiver"), 0, id="equal-copy"),
        pytest.param(_typed(len, "receiver"), 1, id="parameters-dropped"),
        pytest.param(functools.partial(_typed(len, "receiver"), 1), 0, id="copy-of-a-partials"),
    ],
)
def test_a_signature_given_to_a_function_that_wraps_a_link_carrying_a_signature_of_its_own_over_a_routine_defined_in_c_raises_type_error_for_a_string_annotation_naming_the_string_and_that_it_may_be_a_copy(
    wrapped: Callable[..., object],
    dropping: int,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relaying = imported_module(tmp_path, monkeypatch, "relaying", _RELAYING_SOURCE)

    with pytest.raises(TypeError, match=r"annotation 'Decimal' no module is known to spell:.*\bmay be a copy\b"):
        named_classes(relaying.resign(wrapped, dropping))


def test_a_partial_that_carries_a_signature_over_a_routine_defined_in_c_records_no_module_so_a_string_annotation_there_raises_type_error_naming_it_and_the_string() -> None:
    rating = functools.partial(len)
    rating.__signature__ = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    counting = functools.partial(len)
    counting.__signature__ = inspect.Signature(
        [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="Decimal")]
    )
    relayed = functools.wraps(counting)(lambda *args: counting(*args))

    assert named_classes(rating) == {int}
    naming_the_partial_and_the_string = (
        r"\bfunctools\.partial\(<built-in function len>\).*'Decimal'.*\brecords no module of its own\b"
    )
    with pytest.raises(TypeError, match=naming_the_partial_and_the_string):
        named_classes(counting)
    with pytest.raises(TypeError, match=naming_the_partial_and_the_string):
        named_classes(relayed)


def test_a_signature_a_link_carries_over_a_constructor_defined_in_c_names_the_classes_it_names_read_where_the_link_given_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialising = imported_module(
        tmp_path,
        monkeypatch,
        "initialising",
        "from fractions import Fraction as Decimal\n"
        "\n"
        "class Initialised:\n"
        "    pass\n",
    )
    initialising.Initialised.__init__ = _typed(object.__init__, "receiver")

    class Plain:
        pass

    assert named_classes(_typed(zip)) == {decimal.Decimal}
    assert named_classes(_typed(Plain)) == {decimal.Decimal}
    assert named_classes(initialising.Initialised) == {decimal.Decimal}


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


def test_a_routine_that_wraps_a_callable_object_names_the_classes_its_call_method_names_read_where_that_method_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "calling",
        "from fractions import Fraction as Share\n"
        "from functools import wraps\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, share: 'Share') -> None: ...\n"
        "\n"
        "def settle(self, share: 'Share') -> None: ...\n"
        "\n"
        "def logged(function):\n"
        "    @wraps(function)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return function(*args, **kwargs)\n"
        "    return wrapper\n",
    )
    recalling = imported_module(
        tmp_path,
        monkeypatch,
        "recalling",
        "from decimal import Decimal as Share\n"
        "from functools import partial\n"
        "\n"
        "from calling import Caller, logged, settle\n"
        "\n"
        "class Subcaller(Caller):\n"
        "    pass\n"
        "\n"
        "class Settler:\n"
        "    __call__ = settle\n"
        "\n"
        "called = logged(Subcaller())\n"
        "settled = logged(Settler())\n"
        "halved = partial(Subcaller())\n",
    )

    assert named_classes(recalling.called) == {fractions.Fraction}
    assert named_classes(recalling.settled) == {fractions.Fraction}
    assert named_classes(recalling.halved) == {fractions.Fraction}


def test_a_method_bound_to_a_callable_object_names_the_classes_its_call_method_names_read_where_that_method_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "calling",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Caller:\n"
        "    def __call__(self, owner, share: 'Share') -> None: ...\n",
    )
    recalling = imported_module(
        tmp_path,
        monkeypatch,
        "recalling",
        "from decimal import Decimal as Share\n"
        "\n"
        "from calling import Caller\n"
        "\n"
        "class Subcaller(Caller):\n"
        "    pass\n",
    )

    classes = named_classes(types.MethodType(recalling.Subcaller(), object()))

    assert classes == {fractions.Fraction}


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
