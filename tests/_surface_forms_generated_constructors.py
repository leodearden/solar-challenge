# SPDX-License-Identifier: AGPL-3.0-or-later
"""The constructor a generator wrote into a class, the dataclass decorator's __init__ or collections.namedtuple's __new__, told from one the class statement defined, and the module that spells each of its parameters.

Of the helper, this module imports only the modules below it in
tests/unit/test_surface_forms_layers.py's LAYERS, which checks that.
docs/surface-forms-inspect-readings.md §3.5 says how each minor reads such constructors.
"""

import dataclasses
import inspect
import itertools
import types
from collections.abc import Callable, Collection, Iterable, Mapping

from tests._surface_forms_class_reads import own_annotations, recorded_mro
from tests._surface_forms_generators import (
    DATACLASS_DECORATOR,
    NAMEDTUPLE,
    MethodGenerator,
    dataclass_parameter,
)
from tests._surface_forms_labels import label_of
from tests._surface_forms_module_lookup import (
    NoSourceError,
    bound_under,
    class_namespace_defs,
    class_statement,
    defining_module,
    missing_class_statement_clause,
    source_of,
)


def generated_constructor_spelling_modules(
    cls: type, holder: type, name: str, author: object, names: Collection[str]
) -> Mapping[str, types.ModuleType] | None:
    """The module spelling each of *names* in the constructor *holder* holds as *name*, through which *cls* is constructed, if a generator wrote *author*, the function whose annotations the end of that constructor's chain holds, there as that constructor; None if none did.

    TypeError names *cls* and *author* if the generator's record of *holder* says it writes
    no such constructor there, as _refuse_constructor_its_generator_records_unwritten
    finds, or if *author* was generated for another class, as
    _refuse_constructor_generated_for_another_class finds.
    """
    generated = _generated_constructor_of(cls, holder, name, author)
    if generated is None:
        _refuse_constructor_generated_for_another_class(cls, holder, author)
        return None
    _refuse_constructor_its_generator_records_unwritten(cls, holder, author, generated)
    return generated.parameter_modules(holder, names)


def _refuse_constructor_generated_for_another_class(
    cls: type, holder: type, author: object
) -> None:
    """Raise TypeError naming *cls* and *author*, the function whose annotations the end of the chain of *holder*'s constructor holds, if _class_named_by finds a class other than *holder* into which _generated_constructor_of finds a generator wrote *author* as its constructor.

    A generated function assigned into *holder* keeps the name the generator gave it in
    the class it was generated for, and no module is known to spell the fields that
    class declares.
    """
    named = _class_named_by(author)
    if named is None:
        return
    owner, name = named
    if owner is not holder and _generated_constructor_of(cls, owner, name, author) is not None:
        raise TypeError(
            f"{label_of(cls)} is constructed through {label_of(author)}, a function generated "
            f"for another class and assigned in the body of {label_of(holder)}, so no module is "
            "known to spell the fields of the class it was generated for: make the name "
            f"private, or define {name} with def"
        )


def _class_named_by(author: object) -> tuple[type, str] | None:
    """The class *author*'s qualified name names before its last dot, as bound_under finds it in the module defining_module gives for *author*, with the name after that dot; None if *author* is no function, its qualified name holds no dot, or no class is bound there, as for a class defined inside a function."""
    if not isinstance(author, types.FunctionType):
        return None
    owner_path, _, name = author.__qualname__.rpartition(".")
    if not owner_path:
        return None
    owner = bound_under(owner_path, defining_module(author))
    return (owner, name) if inspect.isclass(owner) else None


@dataclasses.dataclass(frozen=True)
class _GeneratedConstructor:
    """The constructor *generator* writes into each class it processes, by the rule it documents: its method *name*, unless that class's statement defines one, which it leaves in place; _GENERATED_CONSTRUCTORS holds one for each constructor such a generator writes, and _refuse_constructor_recorded_twice refuses two for one constructor.

    *writes* finds whether the generator's record of a class it processed says it writes
    the constructor there, and *parameter_modules* gives the module spelling each parameter
    of the one it wrote.
    """

    generator: MethodGenerator
    name: str
    writes: Callable[[type], bool]
    parameter_modules: Callable[[type, Iterable[str]], Mapping[str, types.ModuleType]]

    def __post_init__(self) -> None:
        """Refuse a constructor its generator's methods do not list, which _generated_constructor_of would never find written."""
        if self.name not in self.generator.methods:
            raise ValueError(
                f"The constructor {self.name} is recorded as written by "
                f"{self.generator.label}, whose methods do not list it, so no {self.name} "
                f"would be read as one it wrote: list {self.name} among its methods"
            )


def _refuse_constructor_recorded_twice(constructors: Iterable[_GeneratedConstructor]) -> None:
    """Raise ValueError naming the constructor and the generators of two of *constructors* that name the same constructor, since _generated_constructor_of could not tell which of those generators wrote a function both may have written, as into a class both processed."""
    for earlier, later in itertools.combinations(constructors, 2):
        if earlier.name == later.name:
            raise ValueError(
                f"The constructor {later.name} is recorded as written by both "
                f"{earlier.generator.label} and {later.generator.label}, so which of them "
                f"wrote a function both may have written into a class as its {later.name} "
                "is not known: record each constructor once, or give "
                "_generated_constructor_of a rule that tells which of them wrote it"
            )


def _generated_constructor_of(
    cls: type, holder: type, name: str, author: object
) -> _GeneratedConstructor | None:
    """The constructor _GENERATED_CONSTRUCTORS holds that is named *name* and whose generator may have written *author*, a function, into *holder* as that constructor, as MethodGenerator.may_have_written finds, if no def statement of *holder*'s class statement wrote *author*, as _defined_in_body finds; None otherwise.

    A function assigned from elsewhere keeps its own name. A function that records
    __wrapped__ is none, whatever its name: functools.wraps named it after what it wraps.
    _defined_in_body refuses, naming *cls*, the class constructed through *author*, where
    it cannot tell whether a def statement wrote *author*.
    """
    if not isinstance(author, types.FunctionType) or hasattr(author, "__wrapped__"):
        return None
    written = tuple(
        constructor
        for constructor in _GENERATED_CONSTRUCTORS
        if constructor.name == name and constructor.generator.may_have_written(holder, name, author)
    )
    _refuse_constructor_recorded_twice(written)
    constructor = next(iter(written), None)
    if constructor is None or _defined_in_body(cls, holder, constructor, author):
        return None
    return constructor


def _refuse_constructor_its_generator_records_unwritten(
    cls: type, holder: type, author: object, constructor: _GeneratedConstructor
) -> None:
    """Raise TypeError naming *cls* and *author*, the constructor *holder* holds that _generated_constructor_of finds *constructor*'s generator may have written there, if that generator's record of *holder* says it writes none there.

    The dataclass decorator's says so once it last processed *holder* with init off,
    though an earlier decoration may have written *author*: no rule tells what wrote it,
    so no module is known to spell its parameters.
    """
    if not constructor.writes(holder):
        raise TypeError(
            f"{_generated_name_clause(cls, author, constructor)}, though its record of "
            f"{label_of(holder)} says it writes none there, so no module is known to spell its "
            f"parameters: make the name private, or define {constructor.name} with def"
        )


def _generated_name_clause(cls: type, author: object, constructor: _GeneratedConstructor) -> str:
    """The clause opening a refusal of *cls*, constructed through *author*, that states *author* carries the name *constructor*'s generator gives the constructor it writes."""
    return (
        f"{label_of(cls)} is constructed through {label_of(author)}, which carries the name "
        f"{constructor.generator.label} gives the {constructor.name} it writes"
    )


def _defined_in_body(
    cls: type, holder: type, constructor: _GeneratedConstructor, function: types.FunctionType
) -> bool:
    """Whether a def statement of *holder*'s class statement, as class_statement reads it, wrote *function*, the one *cls* is constructed through, as *constructor*'s name: a def or async def statement of that body binds that name in *holder*'s namespace, as class_namespace_defs finds it, and inspect reads a source for *function*, as _inspect_reads_a_source_for finds.

    Where that body binds the name so but inspect reads no source for *function*, TypeError
    names *cls* if _refuse_def_written_member_of_another_class_statement finds a sign that
    a def statement of another class statement wrote *function*. Where class_statement
    reads no class statement for *holder*, False only once
    _refuse_def_written_member_of_statementless_class finds no sign that a def statement
    wrote *function*. docs/surface-forms-inspect-readings.md §3.5 says how each minor reads
    a class's statement, and which def statements there write nothing the class holds, as
    one under `if TYPE_CHECKING:` writes nothing.
    """
    statement = class_statement(holder)
    if statement is None:
        _refuse_def_written_member_of_statementless_class(cls, holder, constructor, function)
        return False
    if not any(node.name == constructor.name for node in class_namespace_defs(statement)):
        return False
    if _inspect_reads_a_source_for(function):
        return True
    _refuse_def_written_member_of_another_class_statement(cls, holder, constructor, function)
    return False


def _inspect_reads_a_source_for(function: types.FunctionType) -> bool:
    """Whether inspect reads a source for *function*, as source_of finds.

    On every admitted minor it reads one for each function a def statement in a source
    file wrote, and none for a function compiled from text no file holds: one the
    dataclass decorator or collections.namedtuple wrote, each compiled from text it writes,
    or one a def statement in text given to exec wrote. docs/surface-forms-inspect-readings.md
    §3.5 records these readings.
    """
    try:
        source_of(function)
    except NoSourceError:
        return False
    return True


def _compiled_in_a_class_body(holder: type, name: str, function: types.FunctionType) -> bool:
    """Whether *function*'s code carries *holder*'s __qualname__ dotted with *name*, the qualified name a def statement of *name* in the body of a class statement under *holder*'s qualified name compiles it under, while the dataclass decorator and collections.namedtuple compile each function they write under a qualified name of their own.

    A generated function whose code was given that name, as code.replace gives it, carries
    it too, so a rule reads it only to refuse: it fails closed.
    docs/surface-forms-inspect-readings.md §3.5 records the qualified name each minor
    compiles such code under.
    """
    return function.__code__.co_qualname == f"{holder.__qualname__}.{name}"


def _compiled_in_a_class_body_clause(function: types.FunctionType) -> str:
    """The clause stating the sign _compiled_in_a_class_body reads in *function*: the qualified name its code carries."""
    return (
        f"its code carries the qualified name {function.__code__.co_qualname!r}, as for a "
        "function a def statement in a class body wrote"
    )


def _refuse_def_written_member_of_another_class_statement(
    cls: type, holder: type, constructor: _GeneratedConstructor, function: types.FunctionType
) -> None:
    """Raise TypeError naming *cls*, *function*, through which *cls* is constructed, which carries the name *constructor*'s generator gives the constructor it writes into *holder* and for which inspect reads no source, and the module defining_module gives for *holder*, whose class statement in that module's source defines that constructor by a def statement, if *function*'s code carries the qualified name a def statement in *holder*'s class body gives it, as _compiled_in_a_class_body finds.

    inspect reads a source for each function a def statement of that class statement
    wrote, as _inspect_reads_a_source_for says, so none of them wrote *function*. A def
    statement in another class statement under *holder*'s qualified name, as in text given
    to exec, may have written it, and that statement, not the one the source holds, may
    have defined *holder*, so whether it defines that constructor is not known. The remedy
    defines *holder* by the class statement the source holds.
    """
    if not _compiled_in_a_class_body(holder, constructor.name, function):
        return
    module = defining_module(holder).__name__
    raise TypeError(
        f"{_generated_name_clause(cls, function, constructor)} into {label_of(holder)}, and "
        f"{_compiled_in_a_class_body_clause(function)}, but inspect reads no source for it, "
        "though it reads one for each function a def statement in the source of the module "
        f"{module!r} wrote, so the class statement that source holds under the qualified name "
        f"{holder.__qualname__!r} may not be the one that defined {label_of(holder)}, and "
        f"whether that one defines {constructor.name} is not known: make the name private, or "
        f"define {label_of(holder)} by the class statement that source holds"
    )


def _refuse_def_written_member_of_statementless_class(
    cls: type, holder: type, constructor: _GeneratedConstructor, function: types.FunctionType
) -> None:
    """Raise TypeError naming *cls*, *function*, through which *cls* is constructed and which carries the name *constructor*'s generator gives the constructor it writes into *holder*, and the module defining_module gives for *holder*, whose source class_statement found holds no class statement for *holder*, if inspect reads a source for *function*, as _inspect_reads_a_source_for finds, or if its code carries the qualified name a def statement in *holder*'s class body gives it, as _compiled_in_a_class_body finds.

    A function with either sign may be one the class statement that defined *holder*
    defines, and that statement is elsewhere, as for a class whose __module__ names a
    module that re-exports it, or in text given to exec, so whether it defines that
    constructor is not known. class_statement looks that statement up by *holder*'s
    __module__ and __qualname__ in the source of the module they name; the remedy leaves
    those as the statement set them where inspect reads a source for *function*, and puts
    the statement in that source otherwise. docs/surface-forms-inspect-readings.md §3.5
    says how each minor reads the source of such a class.
    """
    module = defining_module(holder).__name__
    if _inspect_reads_a_source_for(function):
        evidence = "inspect reads a source for it, as for a function a def statement wrote"
        remedy = (
            f"leave the __module__ and __qualname__ of {label_of(holder)} as its class "
            "statement set them"
        )
    elif _compiled_in_a_class_body(holder, constructor.name, function):
        evidence = _compiled_in_a_class_body_clause(function)
        remedy = (
            f"define {label_of(holder)} by a class statement in the source of the module "
            f"{module!r}"
        )
    else:
        return
    raise TypeError(
        f"{_generated_name_clause(cls, function, constructor)} into {label_of(holder)}, and "
        f"{evidence}, but {missing_class_statement_clause(holder)}, so whether the class "
        f"statement that defined {label_of(holder)} defines {constructor.name} is not known: "
        f"make the name private, or {remedy}"
    )


def _field_declaration_modules(
    holder: type, names: Iterable[str]
) -> dict[str, types.ModuleType]:
    """The module spelling each of *names* in the __init__ the dataclass decorator wrote into *holder*: that of the nearest class in *holder*'s MRO that the decorator processed and whose own body annotates the name, or *holder*'s if none does."""
    decorated = tuple(base for base in recorded_mro(holder) if DATACLASS_DECORATOR.processed(base))
    return {
        name: defining_module(
            next((base for base in decorated if name in own_annotations(base)), holder)
        )
        for name in names
    }


_GENERATED_CONSTRUCTORS: tuple[_GeneratedConstructor, ...] = (
    _GeneratedConstructor(
        generator=DATACLASS_DECORATOR,
        name="__init__",
        writes=lambda cls: dataclass_parameter(cls, "init"),
        parameter_modules=_field_declaration_modules,
    ),
    _GeneratedConstructor(
        generator=NAMEDTUPLE,
        name="__new__",
        writes=lambda cls: True,
        parameter_modules=lambda cls, names: dict.fromkeys(names, defining_module(cls)),
    ),
)
_refuse_constructor_recorded_twice(_GENERATED_CONSTRUCTORS)
