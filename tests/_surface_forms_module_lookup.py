# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module that defined an object, as sys.modules holds it, checked to be that object's own, and what is read there: a string annotation, evaluated as a type checker reads it, and the class statement that defines a class, parsed from that module's source.

That lookup reads an object's kind through is_routine, is_get_delete_descriptor,
is_immutable_type and spelled_function, which the helper's other modules read objects
through too. Of the helper, this module imports only the modules below it in
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

    If sys.modules holds another module under that name, as once another module of the
    same name has replaced it there, LookupError names *routine* and both modules. A
    routine that carries no globals, as a descriptor object that carries a signature
    carries none, records nothing to check its module by, so the one its __module__
    names is looked up unchecked.
    """
    namespace = getattr(routine, "__globals__", None)
    if namespace is None:
        return _module_named(routine.__module__, routine)
    spec = namespace.get("__spec__")
    name = namespace.get("__name__") if spec is None else spec.name
    module = _module_named(name, routine)
    if vars(module) is not namespace:
        raise _defined_elsewhere(label_of(routine), namespace, module, name)
    return module


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
    carries, as _body_witness finds it. A module inspect reads no
    source for, such as a built-in or extension module, holds no class statement to
    misread, and evaluated_in refuses a string read there, so a class such a module does
    not bind under its qualified name, as _json binds _json.Scanner as make_scanner, is
    checked as one defined inside a function is. Otherwise, as once another module of the
    same name has replaced its own in sys.modules, LookupError names *cls* and the module
    found. An immutable type carries no source or annotation to misread, and a class so
    checked for which _body_witness finds no witness carries nothing to check it by, so
    their module is looked up unchecked.
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
        f"the module at {getattr(module, '__file__', None)}, which sys.modules holds under "
        f"the name {cls.__module__!r}: that module binds "
        f"{'nothing' if bound is None else 'another object'} there. Read each module's "
        "objects before importing another module of that name, or bind the class under "
        "its qualified name"
    )


def _checked_by_body_witness(cls: type, module: types.ModuleType) -> types.ModuleType:
    """*module*, checked to hold as its globals those *cls*'s body witness carries, as _body_witness finds it; unchecked if it finds none.

    Otherwise LookupError. If the globals that function carries name no file, as the globals
    a generator may compile a method it writes with name none, the error names that
    function's code file and a MethodGenerator record; if they name one, it names *cls* and
    both modules.
    """
    witness = _body_witness(cls)
    if witness is None or witness.__globals__ is vars(module):
        return module
    if witness.__globals__.get("__file__") is None:
        raise _written_by_an_unlisted_generator(cls, witness, module)
    raise _defined_elsewhere(label_of(cls), witness.__globals__, module, cls.__module__)


def _defined_elsewhere(
    label: str, namespace: dict[str, object], module: types.ModuleType, name: str
) -> LookupError:
    """The error for *label*, defined in the module whose globals are *namespace*, once sys.modules holds *module* in its place under *name*."""
    return LookupError(
        f"{label} is defined in the module at {namespace.get('__file__')}, but sys.modules "
        f"holds the module at {getattr(module, '__file__', None)} under the name {name!r}: "
        "read each module's objects before importing another module of that name"
    )


def _located(module: types.ModuleType) -> str:
    """How an error names *module*: by the file it was read from, which tells two modules of one name apart; by its repr if it names none, as a module types.ModuleType makes names none."""
    file = getattr(module, "__file__", None)
    return repr(module) if file is None else f"the module at {file}"


def _written_by_an_unlisted_generator(
    cls: type, function: types.FunctionType, module: types.ModuleType
) -> LookupError:
    """The error for *cls*, whose method *function*, named after it, carries globals that name no file and are not those of *module*, which sys.modules holds under *cls*'s module name: a generator that no MethodGenerator record lists may have written that method with globals of its own, or *cls*'s module, one with no file, may since have been replaced there."""
    return LookupError(
        f"{label_of(cls)}.{function.__name__} was compiled from "
        f"{function.__code__.co_filename!r} with globals that name no file and are not those "
        f"of {_located(module)}, which sys.modules holds under the name {cls.__module__!r}. "
        f"If a generator wrote it, add a {MethodGenerator.__qualname__} record for that "
        f"generator to the generators that {MethodGenerator.__module__} lists. If a module "
        f"with no file defined {label_of(cls)}, read each module's objects before importing "
        "another module of that name"
    )


def _body_witness(cls: type) -> types.FunctionType | None:
    """The first function in *cls*'s own namespace, read through spelled_function and unwrapped from any decorator that records it as __wrapped__, whose globals may check the module *cls*'s body ran in, as _witnesses_its_body finds; None if there is none.

    There is none if no function there is named after *cls*, as when its body compiled
    none (an annotation-only body before Python 3.14, which compiles its __annotate__
    unless the module imports annotations from __future__) and nothing since wrote one
    there; or if may_be_generated finds a generator may have written each one that is,
    as for a dataclass body whose only method is a hand-written __init__. So a function
    a generator wrote there after the body ran is the witness unless may_be_generated
    finds it, even where the body compiled none.
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
    """Whether the globals *function* carries may check the module *cls*'s body ran in: it is named after *cls*, as the compiler names each function a class body compiles, and no generator may have written it there, as may_be_generated finds, since only *cls*'s class statement, read once its module is checked, could tell those apart, even if *cls*'s body did compile it, as it compiles a dataclass's hand-written __init__."""
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
    """The class statement that defined *cls*: the one the source of the module defining_module gives for *cls* holds under *cls*'s qualified name, as _class_statements_in spells the name each statement there gives, alike on every minor; None if that source holds none, as for a class collections.namedtuple or dataclasses.make_dataclass makes, or one whose __module__ names a module that re-exports it.

    TypeError names *cls* if inspect reads no source for that module, as for a built-in
    or extension module, which may hold a class statement that defined it; or if that
    source holds several class statements under *cls*'s qualified name, which does not
    tell which of them defined it. docs/surface-forms-inspect-readings.md §3.5 says how
    each minor finds a class's statement.
    """
    module = defining_module(cls)
    try:
        source = _source(module)
    except _NoSourceError as unread:
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


def evaluated_in(annotation: str, module: types.ModuleType) -> object:
    """*annotation* evaluated in a copy of *module*'s globals, with the imports of its top-level `if TYPE_CHECKING:` blocks run over them; TypeError naming both if inspect reads no source for *module*, which then has no such block to read."""
    if not _has_source(module):
        raise TypeError(
            f"The string annotation {annotation!r} is read in the module {module.__name__!r}, "
            "for which inspect reads no source, as for a built-in or extension module, so no "
            "`if TYPE_CHECKING:` import there can be read: make the name private, or annotate "
            "with the class, not a string"
        )
    namespace = dict(vars(module))
    exec(_type_checking_imports(module), namespace)
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
    for node in ast.parse(_source(module)).body:
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
    """Each class statement among *nodes*, or in any block or body of theirs, with the qualified name it gives the class it defines, as the compiler spells it: _qualified_name spells each class or function name from the scope of the body holding its statement and the names that body's global statements declare, *scope* and *declared_global* for the body *nodes* belong to; a class's body has its qualified name, dotted, as its scope, and a function's its qualified name, dotted with <locals>."""
    for node in nodes:
        match node:
            case ast.ClassDef(name=name, body=body) as statement:
                qualified_name = _qualified_name(name, scope, declared_global)
                yield qualified_name, statement
                yield from _class_statements_in(
                    body, f"{qualified_name}.", frozenset(_global_names(body))
                )
            case ast.FunctionDef(name=name, body=body) | ast.AsyncFunctionDef(
                name=name, body=body
            ):
                yield from _class_statements_in(
                    body,
                    f"{_qualified_name(name, scope, declared_global)}.<locals>.",
                    frozenset(_global_names(body)),
                )
            case ast.expr():
                pass
            case _:
                yield from _class_statements_in(ast.iter_child_nodes(node), scope, declared_global)


def _qualified_name(name: str, scope: str, declared_global: Collection[str]) -> str:
    """The qualified name the compiler gives the class or function a statement named *name* defines in a body of *scope*: *name* alone if a global statement of that body declares it, as *declared_global* holds each name one does, else *name* after *scope*."""
    return name if name in declared_global else f"{scope}{name}"


def _global_names(nodes: Iterable[ast.AST]) -> Iterator[str]:
    """The names the global statements among *nodes*, or in any block of theirs, declare in the body *nodes* belong to, wherever in it they stand; never those of one in a def or class statement among them, whose body declares its own."""
    for node in nodes:
        match node:
            case ast.Global(names=names):
                yield from names
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.expr():
                pass
            case _:
                yield from _global_names(ast.iter_child_nodes(node))


class _NoSourceError(Exception):
    """The error _source raises, from the OSError or TypeError inspect.getsource raised, when inspect reads no source for a module."""


def _source(module: types.ModuleType) -> str:
    """The source inspect reads for *module*, read afresh on each call, the one place this helper reads a module's source; _NoSourceError if inspect reads none, as for a built-in or extension module, or for one with no file, as a module types.ModuleType makes has none."""
    try:
        return inspect.getsource(module)
    except (OSError, TypeError) as unread:
        raise _NoSourceError from unread


@_cached_while_alive
def _has_source(module: types.ModuleType) -> bool:
    """Whether inspect reads a source for *module*, as _source finds, computed once and kept while *module* lives."""
    try:
        _source(module)
    except _NoSourceError:
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
