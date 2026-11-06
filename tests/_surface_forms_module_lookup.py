# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module that defined an object, as sys.modules holds it, checked to be that object's own, and what is read there: a string annotation, evaluated as a type checker reads it, and the class statement that defines a class, parsed from that module's source.

That lookup reads an object's kind through is_routine, is_get_delete_descriptor,
is_immutable_type and spelled_function, and the helper's other modules read objects
through them too; they read, through class_namespace_defs, the def statements that bind
in the namespace of the class a class statement defines.
Of the helper, this module imports only the modules below it in
tests/unit/test_surface_forms_layers.py's LAYERS, which checks that.
"""

import ast
import functools
import inspect
import sys
import types
import typing
import weakref
from collections.abc import Callable, Collection, Iterable, Iterator

from tests._surface_forms_class_reads import own_namespace
from tests._surface_forms_generators import MethodGenerator, may_be_generated
from tests._surface_forms_labels import label_of


def is_routine(obj: object) -> typing.TypeGuard[Callable[..., object]]:
    """Whether *obj* is a routine as inspect.isroutine reads one from Python 3.14, on every admitted minor: before 3.14 inspect counts no functools.partial as one, and before 3.13 it counts each descriptor is_get_delete_descriptor finds."""
    return isinstance(obj, functools.partial) or (
        inspect.isroutine(obj) and not is_get_delete_descriptor(obj)
    )


def is_get_delete_descriptor(obj: object) -> bool:
    """Whether *obj*'s type defines __get__ and __delete__ but no __set__: a data descriptor, as inspect.isdatadescriptor reads one on every admitted minor, that inspect before Python 3.13 also counts as a method descriptor."""
    kind = type(obj)
    return (
        inspect.isdatadescriptor(obj) and hasattr(kind, "__get__") and not hasattr(kind, "__set__")
    )


def defining_module(obj: object) -> types.ModuleType:
    """The module that defined *obj*, as sys.modules holds it: the one place this helper looks a module up by name, through _module_named, checked for a routine and for a class; a functools.partial's is that of the callable it wraps, and anything else records only its module's name, so that module is looked up unchecked."""
    if isinstance(obj, functools.partial):
        return defining_module(obj.func)
    if is_routine(obj):
        return _routine_module(obj)
    if inspect.isclass(obj):
        return _class_module(obj)
    return _module_named(obj.__module__, obj)


def _module_named(name: str, obj: object) -> types.ModuleType:
    """The module sys.modules holds under *name*, the name of the module that defined *obj*; LookupError naming both if sys.modules holds none there, as once that module has left it."""
    module = sys.modules.get(name)
    if module is None:
        raise LookupError(
            f"{label_of(obj)} is defined in the module named {name!r}, but sys.modules holds "
            "no module under that name: read each module's objects while sys.modules holds it"
        )
    return module


def _routine_module(routine: Callable[..., object]) -> types.ModuleType:
    """The module whose globals *routine* carries, whatever module its __module__ names: the one sys.modules holds under the name that module was imported as, its spec's, or its __name__ if it has no spec.

    Globals that are no module's own, as a generator may compile a method it writes
    with, raise LookupError naming *routine* and the file its code was compiled from:
    globals that record no module's name, which every module's globals record from
    their creation, or a copy of the globals of the module sys.modules holds under the
    name they record, as _copies_globals_of finds one. If sys.modules holds another
    module under that name, as once another module of the same name has replaced it
    there, LookupError names *routine* and both modules. A routine that carries no
    globals, as a descriptor object that carries a signature carries none, records
    nothing to check its module by, so the one its __module__ names is looked up
    unchecked.
    """
    namespace = getattr(routine, "__globals__", None)
    if namespace is None:
        return _module_named(routine.__module__, routine)
    spec = namespace.get("__spec__")
    name = namespace.get("__name__") if spec is None else spec.name
    if name is None:
        raise _compiled_with_globals_of_no_module(routine, "globals that record no module's name")
    module = _module_named(name, routine)
    if vars(module) is namespace:
        return module
    if _copies_globals_of(namespace, module):
        raise _compiled_with_globals_of_no_module(routine, _copy_of_globals_clause(module, name))
    raise _defined_elsewhere(label_of(routine), namespace, module, name)


def _copies_globals_of(namespace: dict[str, object], module: types.ModuleType) -> bool:
    """Whether *namespace* is a copy of *module*'s globals, not those globals themselves: it holds the very __spec__ object they hold, as the copy attrs compiles each __init__ it writes with does.

    The import system makes a new spec for each module it imports, so the globals of a
    module another has since replaced in sys.modules hold a spec of their own, and a
    copy holds the spec of the module it was copied from. A module with no spec gives
    nothing to tell a copy by.
    """
    own = vars(module)
    spec = namespace.get("__spec__")
    return namespace is not own and spec is not None and spec is own.get("__spec__")


_PY_TPFLAGS_IMMUTABLETYPE = 1 << 8


def is_immutable_type(cls: type) -> bool:
    """Whether *cls*'s flags mark it an immutable type, which only C code defines.

    Python marks no class a class statement or type() creates, and CPython marks every
    static type and many heap types it defines in C, though not all, such as ast.AST.
    """
    return bool(cls.__flags__ & _PY_TPFLAGS_IMMUTABLETYPE)


def _class_module(cls: type) -> types.ModuleType:
    """The module sys.modules holds under the name *cls*'s __module__ records, where typing and inspect read a class's annotations and source, checked to be the module that defined *cls*.

    A class defined outside any function must be bound there under its qualified name,
    and one defined inside a function must find there the globals its body witness
    carries, as _body_witness finds it. A module inspect reads no source for, such as a
    built-in or extension module, holds no class statement to misread, and evaluated_in
    refuses a string read there, so a class such a module does not bind under its
    qualified name, as _json binds _json.Scanner as make_scanner, is checked as one
    defined inside a function is. Otherwise, as once another module of the same name has
    replaced its own in sys.modules, LookupError names *cls* and the module found. An
    immutable type carries no source or annotation to misread, and a class so checked
    for which _body_witness finds no witness carries nothing to check it by, so their
    module is looked up unchecked. docs/surface-forms-inspect-readings.md §4.10 says which
    __module__ dataclasses.make_dataclass records on each minor, and so when a class it
    makes is refused.
    """
    module = _module_named(cls.__module__, cls)
    if is_immutable_type(cls):
        return module
    if "<locals>" in cls.__qualname__:
        return _checked_by_body_witness(cls, module)
    bound = bound_under(cls.__qualname__, module)
    if bound is cls:
        return module
    if not _has_source(module):
        return _checked_by_body_witness(cls, module)
    raise LookupError(
        f"{label_of(cls)} is not bound under {cls.__qualname__!r} in "
        f"{_located(module)}, which sys.modules holds under "
        f"the name {cls.__module__!r}: that module binds "
        f"{'nothing' if bound is None else 'another object'} there. Either "
        f"{_REPLACED_MODULE_REMEDY}, or bind the class under its qualified name. If the "
        "class's __module__ names a module that never bound it, as that of a class "
        "dataclasses.make_dataclass makes on Python 3.11 names types, assign it the "
        "__module__ of the module that binds it under its qualified name"
    )


def _checked_by_body_witness(cls: type, module: types.ModuleType) -> types.ModuleType:
    """*module*, checked to hold as its globals those *cls*'s body witness carries, as _body_witness finds it; unchecked if it finds none.

    Otherwise LookupError. If the witness carries a copy of *module*'s globals, as
    _copies_globals_of finds one, or globals that name no file, either of which a
    generator may compile a method it writes with, the error names the witness's code
    file and a MethodGenerator record; otherwise it names *cls* and both modules.
    """
    witness = _body_witness(cls)
    if witness is None or witness.__globals__ is vars(module):
        return module
    if _copies_globals_of(witness.__globals__, module):
        raise _compiled_with_a_copy_of_its_modules_globals(cls, witness, module)
    if witness.__globals__.get("__file__") is None:
        raise _written_by_an_unlisted_generator(cls, witness, module)
    raise _defined_elsewhere(label_of(cls), witness.__globals__, module, cls.__module__)


def _defined_elsewhere(
    label: str, namespace: dict[str, object], module: types.ModuleType, name: str
) -> LookupError:
    """The error for *label*, defined in the module whose globals are *namespace*, once sys.modules holds *module* in its place under *name*."""
    return LookupError(
        f"{label} is defined in {_located_by_globals(namespace)}, but sys.modules "
        f"holds {_located(module)} under the name {name!r}: {_REPLACED_MODULE_REMEDY}"
    )


def _located(module: types.ModuleType) -> str:
    """How an error names *module*: by the file it was read from, which tells two modules of one name apart; by its repr if it names none, as a module types.ModuleType makes names none."""
    file = getattr(module, "__file__", None)
    return repr(module) if file is None else f"the module at {file}"


def _located_by_globals(namespace: dict[str, object]) -> str:
    """How an error names the module whose globals are *namespace*: as _located names a types.ModuleType holding a copy of them."""
    holder = types.ModuleType("?")
    vars(holder).update(namespace)
    return _located(holder)


def _copy_of_globals_clause(module: types.ModuleType, name: str) -> str:
    """How an error names globals that copy *module*'s, as _copies_globals_of finds them, *module* being the one sys.modules holds under *name*."""
    return (
        f"a copy of the globals of {_located(module)}, which sys.modules holds under the "
        f"name {name!r}"
    )


def _method_compiled_from_clause(cls: type, function: types.FunctionType) -> str:
    """How an error names *cls*'s method *function*, as *cls*'s label dotted with the method's name, and the file its code was compiled from."""
    return (
        f"{label_of(cls)}.{function.__name__} was compiled from "
        f"{function.__code__.co_filename!r}"
    )


_REPLACED_MODULE_REMEDY = "read each module's objects before importing another module of that name"


_GENERATOR_RECORD_REMEDY = (
    f"If a generator wrote it, add a {MethodGenerator.__qualname__} record for that generator "
    f"to the generators that {MethodGenerator.__module__} lists"
)


def _compiled_with_a_copy_of_its_modules_globals(
    cls: type, function: types.FunctionType, module: types.ModuleType
) -> LookupError:
    """The error for *cls*, whose method *function*, named after it, carries a copy of the globals of *module*, which sys.modules holds under *cls*'s module name, as _copies_globals_of finds one: a generator that no MethodGenerator record lists may have written that method with that copy, which tells which module sys.modules held when the generator ran, not which module *cls*'s body ran in."""
    return LookupError(
        f"{_method_compiled_from_clause(cls, function)} with "
        f"{_copy_of_globals_clause(module, cls.__module__)}, not with those globals "
        "themselves, as a generator may compile a method it writes, so it does not tell which "
        f"module {label_of(cls)}'s body ran in. {_GENERATOR_RECORD_REMEDY}. If "
        f"{label_of(cls)} was built once another module named {cls.__module__!r} had taken its "
        f"own module's place in sys.modules, {_REPLACED_MODULE_REMEDY}"
    )


def _written_by_an_unlisted_generator(
    cls: type, function: types.FunctionType, module: types.ModuleType
) -> LookupError:
    """The error for *cls*, whose method *function*, named after it, carries globals that name no file and are not those of *module*, which sys.modules holds under *cls*'s module name: a generator that no MethodGenerator record lists may have written that method with globals of its own, or *cls*'s module, one with no file, may since have been replaced there."""
    return LookupError(
        f"{_method_compiled_from_clause(cls, function)} with globals that name no file and are "
        f"not those of {_located(module)}, which sys.modules holds under the name "
        f"{cls.__module__!r}. {_GENERATOR_RECORD_REMEDY}. If a module with no file defined "
        f"{label_of(cls)}, {_REPLACED_MODULE_REMEDY}"
    )


def _compiled_with_globals_of_no_module(
    routine: Callable[..., object], globals_clause: str
) -> LookupError:
    """The error for *routine*, compiled with the globals *globals_clause* describes, which are no module's own, as a generator may compile a method it writes, so that no module is known to spell its annotations."""
    return LookupError(
        f"{label_of(routine)} was compiled from {routine.__code__.co_filename!r} with globals "
        "that are no module's own, as a generator may compile a method it writes: "
        f"{globals_clause}. So no module is known to spell its annotations. "
        f"{_GENERATOR_RECORD_REMEDY}, and record each constructor it writes with the module "
        f"that spells each of its parameters, since a {MethodGenerator.__qualname__} record "
        "alone does not say where a constructor it writes is spelled. If another generator's "
        "record already names a constructor of the same name, also give a rule that tells "
        "which of the two generators wrote it. If no generator wrote it, define it with def "
        "in a module"
    )


def _body_witness(cls: type) -> types.FunctionType | None:
    """The first function in *cls*'s own namespace, read through spelled_function and unwrapped from any decorator that records it as __wrapped__, whose globals may check the module *cls*'s body ran in, as _witnesses_its_body finds; None if there is none.

    There is none if no function there is named after *cls*, as when its body compiled
    none (an annotation-only body) and nothing since wrote one there; or if
    may_be_generated finds a generator may have written each one that is, as for a
    dataclass body whose only method is a hand-written __init__. So a function a
    generator wrote there after the body ran, named after *cls*, can be the witness
    unless may_be_generated finds it, even where the body compiled none.

    Both examples have no witness only where the body compiles no __annotate__.
    Python 3.14 compiles one for an annotated body unless its module imports annotations
    from __future__; named after *cls* and not found by may_be_generated, it is a witness.
    """
    functions = (spelled_function(member) or member for member in own_namespace(cls).values())
    unwrapped = (
        inspect.unwrap(function) for function in functions if isinstance(function, types.FunctionType)
    )
    return next(
        (
            function
            for function in unwrapped
            if isinstance(function, types.FunctionType) and _witnesses_its_body(cls, function)
        ),
        None,
    )


def _witnesses_its_body(cls: type, function: types.FunctionType) -> bool:
    """Whether the globals *function* carries may check the module *cls*'s body ran in: it is named after *cls*, as the compiler names each function a class body compiles, and no generator may have written it there, as may_be_generated finds, even if *cls*'s body did compile it, as it compiles a dataclass's hand-written __init__."""
    return (
        function.__qualname__ == f"{cls.__qualname__}.{function.__name__}"
        and not may_be_generated(cls, function)
    )


def bound_under(qualified_name: str, module: types.ModuleType) -> object:
    """What *module* binds under the dotted *qualified_name*, one attribute at a time; None if it binds nothing there."""
    bound: object = module
    for name in qualified_name.split("."):
        bound = getattr(bound, name, None)
    return bound


def class_statement(cls: type) -> ast.ClassDef | None:
    """The class statement that defined *cls*: the one the source of the module defining_module gives for *cls* holds under *cls*'s qualified name, as _class_statements_in spells the name each statement there gives, alike on every minor; None if that source holds none, as for a class collections.namedtuple makes, one type() makes that the dataclass decorator then processes, or one whose __module__ names a module that re-exports it.

    TypeError names *cls* if inspect reads no source for that module, as for a built-in
    or extension module, which may hold a class statement that defined it; or if that
    source holds several class statements under *cls*'s qualified name, which does not
    tell which of them defined it. docs/surface-forms-inspect-readings.md §3.5 says how
    each minor finds a class's statement.
    """
    module = defining_module(cls)
    try:
        source = source_of(module)
    except NoSourceError as unread:
        raise TypeError(
            f"{label_of(cls)} has no class statement inspect can read, since inspect reads no "
            f"source for its module {module.__name__!r}, as for a built-in or extension "
            "module, so what a class statement there defined is not known: pass a class that "
            "a class statement in a source file defines"
        ) from unread
    match _class_statements_named(cls.__qualname__, source):
        case ():
            return None
        case (statement,):
            return statement
    raise TypeError(
        f"{label_of(cls)} is defined by one of several class statements its module's "
        f"source holds under the qualified name {cls.__qualname__!r}, which does not tell "
        "which of them defined it: define the class with one class statement"
    )


def missing_class_statement_clause(cls: type) -> str:
    """What the helper's errors say where class_statement returns None for *cls*: that the source of the module defining_module gives for *cls* holds no class statement under *cls*'s qualified name."""
    return (
        f"the source of the module {defining_module(cls).__name__!r} holds no class statement "
        f"under the qualified name {cls.__qualname__!r}"
    )


def evaluated_in(annotation: str, module: types.ModuleType) -> object:
    """*annotation* evaluated in a copy of *module*'s globals, with the imports of its top-level `if TYPE_CHECKING:` blocks run over them.

    Those imports are read from *module*'s source once and kept while *module* lives,
    whatever inspect reads for it later. TypeError naming *annotation* and *module* if
    inspect reads no source for *module* while they are unread, as for a built-in or
    extension module, which has no such block to read.
    """
    try:
        imports = _type_checking_imports(module)
    except NoSourceError as unread:
        raise TypeError(
            f"The string annotation {annotation!r} is read in the module {module.__name__!r}, "
            "for which inspect reads no source, as for a built-in or extension module, so no "
            "`if TYPE_CHECKING:` import there can be read: make the name private, or annotate "
            "with the class, not a string"
        ) from unread
    namespace = dict(vars(module))
    exec(imports, namespace)
    return eval(annotation, namespace)


_Argument = typing.TypeVar("_Argument")
_Result = typing.TypeVar("_Result")


def _cached_while_alive(function: Callable[[_Argument], _Result]) -> Callable[[_Argument], _Result]:
    """*function*, its result for each argument computed once and kept only while that argument lives, so the cache keeps no argument alive."""
    results: weakref.WeakKeyDictionary[_Argument, _Result] = weakref.WeakKeyDictionary()

    @functools.wraps(function)
    def cached(argument: _Argument) -> _Result:
        if argument not in results:
            results[argument] = function(argument)
        return results[argument]

    return cached


@_cached_while_alive
def _type_checking_imports(module: types.ModuleType) -> types.CodeType:
    """The Import and ImportFrom statements of *module*'s top-level `if TYPE_CHECKING:` blocks, compiled, so running them binds each name as Python binds it."""
    imports: list[ast.stmt] = []
    for node in ast.parse(source_of(module)).body:
        match node:
            case ast.If(
                test=ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"),
                body=body,
            ):
                imports += [
                    statement
                    for statement in body
                    if isinstance(statement, (ast.Import, ast.ImportFrom))
                ]
    return compile(ast.Module(body=imports, type_ignores=[]), module.__name__, "exec")


def _class_statements_named(qualified_name: str, source: str) -> tuple[ast.ClassDef, ...]:
    """The class statements in *source*, in source order, that give the class each defines *qualified_name*, as _class_statements_in spells it, parsed afresh on each call so each caller owns the statements it gets."""
    return tuple(
        statement
        for name, statement in _class_statements_in(ast.parse(source).body, "", frozenset())
        if name == qualified_name
    )


def _class_statements_in(
    nodes: Iterable[ast.AST], scope: str, declared_global: Collection[str]
) -> Iterator[tuple[str, ast.ClassDef]]:
    """Each class statement that _scope_statements finds among *nodes*, or in the body of a class or def statement it finds, at any depth, with the qualified name it gives the class it defines, as the compiler spells it: _qualified_name spells each class or function name from the scope of the body holding its statement and the names that body's global statements declare, *scope* and *declared_global* for the body *nodes* belong to; a class's body has its qualified name, dotted, as its scope, and a function's its qualified name, dotted with <locals>."""
    for statement in _scope_statements(nodes):
        match statement:
            case ast.ClassDef(name=name, body=body):
                qualified_name = _qualified_name(name, scope, declared_global)
                yield qualified_name, statement
                yield from _class_statements_in(
                    body, f"{qualified_name}.", frozenset(_names_declared_by(body, ast.Global))
                )
            case ast.FunctionDef(name=name, body=body) | ast.AsyncFunctionDef(
                name=name, body=body
            ):
                yield from _class_statements_in(
                    body,
                    f"{_qualified_name(name, scope, declared_global)}.<locals>.",
                    frozenset(_names_declared_by(body, ast.Global)),
                )


def _qualified_name(name: str, scope: str, declared_global: Collection[str]) -> str:
    """The qualified name the compiler gives the class or function a statement named *name* defines in a body of *scope*: *name* alone if a global statement of that body declares it, as *declared_global* holds each name one does, else *name* after *scope*."""
    return name if name in declared_global else f"{scope}{name}"


def _names_declared_by(
    nodes: Iterable[ast.AST],
    kind: type[ast.Global] | type[ast.Nonlocal],
    *other_kinds: type[ast.Global] | type[ast.Nonlocal],
) -> Iterator[str]:
    """The names that the global or nonlocal statements of *kind* or one of *other_kinds* that _scope_statements finds among *nodes* declare in the body *nodes* belong to, wherever in it they stand, even in a block that never runs; never those of one in a def or class statement among them, whose body declares its own."""
    for statement in _scope_statements(nodes):
        match statement:
            case ast.Global(names=names) | ast.Nonlocal(names=names) if isinstance(
                statement, (kind, *other_kinds)
            ):
                yield from names


def class_namespace_defs(
    statement: ast.ClassDef,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Each def or async def statement that _scope_statements finds in *statement*'s body, in source order, even in a block that never runs, that binds its name in the namespace of the class *statement* defines: each one whose name no global or nonlocal statement of that body declares, as _names_declared_by finds them, since such a declaration makes the def bind it in the module's globals or an enclosing function's namespace."""
    bound_outside = frozenset(_names_declared_by(statement.body, ast.Global, ast.Nonlocal))
    for node in _scope_statements(statement.body):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name not in bound_outside
        ):
            yield node


def _scope_statements(nodes: Iterable[ast.AST]) -> Iterator[ast.stmt]:
    """Each statement among *nodes*, or in any block of theirs, in source order, even a block that never runs: an if, for, while, try, with or match statement's blocks, its except handlers and match cases included, so each statement of the scope *nodes* run in; never one in a def or class statement's body, which runs in a scope of its own, nor in an expression, which holds none."""
    for node in nodes:
        if isinstance(node, ast.stmt):
            yield node
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.expr():
                pass
            case _:
                yield from _scope_statements(ast.iter_child_nodes(node))


class NoSourceError(Exception):
    """The error source_of raises, from the OSError or TypeError inspect.getsource raised, when inspect reads no source for a module or a function; its message names that module or function."""


def source_of(obj: types.ModuleType | types.FunctionType) -> str:
    """The source inspect reads for *obj*, a module or a function, read afresh on each call, the one place this helper asks inspect for a source; NoSourceError naming *obj* if inspect reads none, as for a built-in or extension module, for a module with no file, as a module types.ModuleType makes has none, or for a function compiled from text no file holds."""
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError) as unread:
        raise NoSourceError(f"inspect reads no source for {label_of(obj)}") from unread


def _has_source(module: types.ModuleType) -> bool:
    """Whether source_of reads a source for *module*, asked afresh on each call."""
    try:
        source_of(module)
    except NoSourceError:
        return False
    return True


def spelled_function(member: object) -> object | None:
    """The function whose signature the form of *member* spells after its kind: a classmethod's or staticmethod's, a property's getter or a cached_property's; None for any other member."""
    match member:
        case classmethod() | staticmethod():
            return member.__func__
        case property():
            return member.fget
        case functools.cached_property():
            return member.func
        case _:
            return None
