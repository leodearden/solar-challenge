# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for the module a string annotation is read in, found from the routine or class that spells it, and the errors raised when no such module can be read, one per test."""

import _json
import collections
import decimal
import fractions
import functools
import gc
import importlib.machinery
import importlib.util
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


_UNBOUND_IN_TYPES = (
    r"^types\.Made is not bound under 'Made' in the module at .*types\.py, which sys\.modules "
    r"holds under the name 'types': that module binds nothing there\. .*\. If the class's "
    r"__module__ names a module that never bound it, as that of a class "
    r"dataclasses\.make_dataclass makes on Python 3\.11 names types, assign it the "
    r"__module__ of the module that binds it under its qualified name$"
)


def test_a_dataclass_types_new_class_makes_raises_a_lookup_error_naming_it_and_the_module_types_with_the_remedy_of_assigning_it_the_module_that_binds_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    newclassing = imported_module(
        tmp_path,
        monkeypatch,
        "newclassing",
        "import types\n"
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "Made = dataclass(types.new_class('Made', (), {}, lambda namespace: "
        "namespace.update({'__annotations__': {'spare': 'Tap'}})))\n",
    )

    with pytest.raises(LookupError, match=_UNBOUND_IN_TYPES):
        named_classes(newclassing.Made)


def test_a_dataclass_dataclasses_make_dataclass_makes_raises_that_lookup_error_on_python_3_11_and_from_python_3_12_names_the_classes_the_module_calling_it_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On 3.11, make_dataclass leaves the class's __module__ as 'types'; from 3.12 it assigns the calling module's name."""
    dataclassmaking = imported_module(
        tmp_path,
        monkeypatch,
        "dataclassmaking",
        "from dataclasses import make_dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "Made = make_dataclass('Made', [('spare', 'Tap')])\n",
    )

    if sys.version_info < (3, 12):
        with pytest.raises(LookupError, match=_UNBOUND_IN_TYPES):
            named_classes(dataclassmaking.Made)
    else:
        assert named_classes(dataclassmaking.Made) == {decimal.Decimal}


def test_a_dataclass_dataclasses_make_dataclass_makes_whose_calling_module_then_assigns_it_that_modules_name_as_its_module_names_the_classes_that_module_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On 3.11 the __init__ the dataclass decorator compiled still carries the globals of types, which binds nothing under 'Tap'."""
    remaking = imported_module(
        tmp_path,
        monkeypatch,
        "remaking",
        "from dataclasses import make_dataclass\n"
        "from decimal import Decimal as Tap\n"
        "\n"
        "Made = make_dataclass('Made', [('spare', 'Tap')])\n"
        "Made.__module__ = __name__\n",
    )

    assert named_classes(remaking.Made) == {decimal.Decimal}


def _name_each_code_as_if_compiled_at_module_level(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Give the code of each function *cls* holds, until *monkeypatch* is undone, its function's own name as its qualified name, as the compiler names the code of a function at module level."""
    for function in vars(cls).values():
        if isinstance(function, types.FunctionType):
            monkeypatch.setattr(
                function, "__code__", function.__code__.replace(co_qualname=function.__name__)
            )


@pytest.mark.parametrize(
    "rename_codes",
    [pytest.param(False, id="as-compiled"), pytest.param(True, id="codes-named-at-module-level")],
)
def test_a_class_a_function_of_a_module_built_once_another_module_of_the_same_name_has_since_replaced_it_in_sys_modules_raises_a_lookup_error_naming_both(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, rename_codes: bool
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
    if rename_codes:
        _name_each_code_as_if_compiled_at_module_level(local, monkeypatch)

    with pytest.raises(LookupError) as raised:
        named_classes(local)

    assert earlier.__file__ in str(raised.value)
    assert later.__file__ in str(raised.value)
    assert "MethodGenerator" not in str(raised.value)


@pytest.mark.parametrize(
    "slots", [pytest.param(False, id="dataclass"), pytest.param(True, id="slots-dataclass")]
)
def test_a_dataclass_whose_body_compiled_no_function_is_read_in_its_own_module_though_the_decorator_wrote_its_methods_while_another_module_of_that_name_held_its_place_in_sys_modules(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, slots: bool
) -> None:
    """The module imports annotations from __future__, so on every minor, 3.14 included, Local's body compiles no function, not even __annotate__: only the functions the decorator wrote, which carry later's globals, could check its module."""
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "def build():\n"
        f"    @dataclass(order=True, frozen=True, slots={slots})\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        "    return Local\n",
    )
    imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "def build():\n"
        f"    @dataclass(order=True, frozen=True, slots={slots})\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        "    return Local\n",
    )
    local = earlier.build()
    monkeypatch.setitem(sys.modules, "auditing", earlier)

    assert named_classes(local) == {fractions.Fraction}


@pytest.mark.parametrize(
    "method", [pytest.param("__post_init__", id="post-init"), pytest.param("__repr__", id="repr")]
)
def test_a_method_a_dataclass_body_compiled_under_a_name_the_decorator_never_writes_or_writes_as_a_wrapper_of_a_function_named_after_no_class_raises_a_lookup_error_naming_both_modules_once_another_module_of_the_same_name_has_since_replaced_its_own(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """The module imports annotations from __future__, so on every minor, 3.14 included, *method* is the only function Local's body compiles. The decorator writes no __post_init__, and the __repr__ it writes, which this one keeps it from writing, unwraps to a function named after no class."""
    earlier = imported_module(
        tmp_path_factory.mktemp("earlier"),
        monkeypatch,
        "auditing",
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import dataclass\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "def build():\n"
        "    @dataclass\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        f"        def {method}(self): ...\n"
        "\n"
        "    return Local\n",
    )
    local = earlier.build()
    later = imported_module(
        tmp_path_factory.mktemp("later"),
        monkeypatch,
        "auditing",
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import dataclass\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "def build():\n"
        "    @dataclass\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        f"        def {method}(self): ...\n"
        "\n"
        "    return Local\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(local)

    assert earlier.__file__ in str(raised.value)
    assert later.__file__ in str(raised.value)


@pytest.mark.parametrize(
    "generator_globals",
    [pytest.param("{}", id="no-file-key"), pytest.param("{'__file__': None}", id="file-is-none")],
)
def test_a_class_whose_only_function_named_after_it_a_generator_compiled_with_globals_naming_no_file_raises_a_lookup_error_naming_that_functions_code_file_and_a_method_generator_record_as_the_remedy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, generator_globals: str
) -> None:
    """The module imports annotations from __future__, so on every minor, 3.14 included, Local's body compiles no function, not even __annotate__: the __init__ that generate writes, with globals of its own, is the only function named after Local. Those globals name no file, whether they hold no __file__ or hold one that is None."""
    generating = imported_module(
        tmp_path,
        monkeypatch,
        "generating",
        "from __future__ import annotations\n"
        "\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "def generate(cls):\n"
        "    namespace = {}\n"
        "    exec(compile('def __init__(self): ...\\n', '<unlisted generator>', 'exec'), "
        f"{generator_globals}, namespace)\n"
        "    namespace['__init__'].__qualname__ = f'{cls.__qualname__}.__init__'\n"
        "    cls.__init__ = namespace['__init__']\n"
        "    return cls\n"
        "\n"
        "def build():\n"
        "    @generate\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        "    return Local\n",
    )

    with pytest.raises(LookupError) as raised:
        named_classes(generating.build())

    message = str(raised.value)
    assert "generating.build.<locals>.Local" in message
    assert "'<unlisted generator>'" in message
    assert "add a MethodGenerator record" in message
    assert "module at None" not in message
    assert "None.build.<locals>.Local" not in message


def test_a_class_a_function_of_a_module_with_no_file_built_once_another_module_with_no_file_of_the_same_name_has_since_replaced_it_in_sys_modules_raises_a_lookup_error_naming_the_replacement_by_its_repr_and_the_remedy_of_reading_each_modules_objects_before_importing_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The earlier module's source imports annotations from __future__, so on every minor, 3.14 included, Local's __init__ is the only function its body compiles, and it carries the globals of the module that built Local. Neither module names a file, so the error names the replacement by its repr and the code file of that __init__, which exec compiles as '<string>'. The replacement's spec gives it an origin but no location, so it still names no file and its repr is not the earlier module's."""
    earlier = types.ModuleType("fileless")
    monkeypatch.setitem(sys.modules, "fileless", earlier)
    exec(
        "from __future__ import annotations\n"
        "\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "def build():\n"
        "    class Local:\n"
        "        share: Share\n"
        "\n"
        "        def __init__(self): ...\n"
        "\n"
        "    return Local\n",
        vars(earlier),
    )
    local = earlier.build()
    later = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec("fileless", None, origin="the replacement")
    )
    monkeypatch.setitem(sys.modules, "fileless", later)

    with pytest.raises(LookupError) as raised:
        named_classes(local)

    message = str(raised.value)
    assert "fileless.build.<locals>.Local.__init__" in message
    assert "'<string>'" in message
    assert repr(later) in message
    assert repr(earlier) not in message
    assert "module at None" not in message
    assert "before importing another module of that name" in message


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
    """The module 'auditing', imported and then removed from sys.modules, that defines a routine, a class, a routine that wraps the class, and a class whose instances are callable."""
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "from functools import wraps\n"
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from fractions import Fraction as Share\n"
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


@pytest.mark.parametrize(
    "rename_codes",
    [pytest.param(False, id="as-compiled"), pytest.param(True, id="codes-named-at-module-level")],
)
def test_a_class_whose_module_one_with_no_source_has_since_replaced_in_sys_modules_raises_a_lookup_error_naming_it_and_its_own_module_if_it_has_a_witness(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, rename_codes: bool
) -> None:
    """Audit's __init__ annotates nothing, so only Audit's own module is looked up, for its attribute. The replacement binds nothing under Audit, as a module inspect reads no source for may bind a class under another name, but __init__, its witness, carries the globals of the module that defined Audit."""
    auditing = imported_module(
        tmp_path,
        monkeypatch,
        "auditing",
        "class Audit:\n    share: int\n\n    def __init__(self): ...\n",
    )
    monkeypatch.setitem(sys.modules, "auditing", types.ModuleType("auditing"))
    if rename_codes:
        _name_each_code_as_if_compiled_at_module_level(auditing.Audit, monkeypatch)

    with pytest.raises(LookupError) as raised:
        named_classes(auditing.Audit)

    assert "auditing.Audit" in str(raised.value)
    assert auditing.__file__ in str(raised.value)


def test_a_named_tuple_class_a_module_with_no_source_binds_under_another_name_raises_a_type_error_naming_it_as_one_no_class_statement_inspect_can_read_defined_whatever_module_its_generated_methods_carry_from_an_error_naming_the_module_with_no_source_raised_from_the_error_inspect_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Of the functions collections.namedtuple wrote into Point, __new__ carries the globals of a namespace named 'namedtuple_Point' and the others collections', so none of them carries unsourced's."""
    unsourced = types.ModuleType("unsourced")
    monkeypatch.setitem(sys.modules, "unsourced", unsourced)
    exec(
        "from typing import NamedTuple\n\nReading = NamedTuple('Point', [('share', int)])\n",
        vars(unsourced),
    )

    with pytest.raises(
        TypeError, match=r"unsourced\.Point\b.*\bno class statement inspect can read\b"
    ) as raised:
        named_classes(unsourced.Reading)

    naming_the_module = raised.value.__cause__
    assert str(naming_the_module) == f"inspect reads no source for {unsourced!r}"
    assert isinstance(naming_the_module.__cause__, (OSError, TypeError))


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
