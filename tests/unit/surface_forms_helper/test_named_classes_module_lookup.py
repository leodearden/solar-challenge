# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the module a string annotation is read in, found from the routine, class or type variable that spells it, and the errors raised when no such module can be read, one per test."""

import _json
import collections
import decimal
import fractions
import functools
import gc
import inspect
import pathlib
import sys
import types
import weakref
from typing import TYPE_CHECKING, Optional

import pytest

from tests._surface_forms import named_classes
from tests.unit.surface_forms_helper._fixtures import Outer, Preset, imported_module

if TYPE_CHECKING:
    from decimal import Decimal


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
