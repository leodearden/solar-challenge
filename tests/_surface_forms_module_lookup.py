# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module that defined an object, as sys.modules holds it, checked to be that object's own, and a string annotation evaluated there as a type checker reads it.

That lookup reads an object's kind through is_routine, is_get_delete_descriptor,
is_immutable_type and spelled_function, a class's own namespace through own_namespace,
which walks its metaclass's MRO through recorded_mro and overriding_getattribute_holder,
and names it in errors through label_of: the helper's other modules read and name objects
through them too, and read a class's own annotations through own_annotations, which
refuses each class own_namespace refuses. This module imports no other module of the
helper, as tests/unit/test_surface_forms_layers.py checks.
"""

import ast
import functools
import inspect
import sys
import types
import typing
import weakref
from collections.abc import Callable, Mapping


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


def label_of(obj: object) -> str:
    """The name this helper's errors give *obj*: its module's name and its qualified name, dotted; its repr if it records no qualified name, as a type variable does not."""
    qualified_name = getattr(obj, "__qualname__", None)
    return repr(obj) if qualified_name is None else f"{obj.__module__}.{qualified_name}"


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
    and one defined inside a function must find there the globals the first function its
    body compiled carries. A module inspect reads no source for, such as a built-in or
    extension module, holds no class statement to misread, and evaluated_in refuses a
    string read there, so a class such a module does not bind under its qualified name,
    as _json binds _json.Scanner as make_scanner, is checked as one defined inside a
    function is. Otherwise, as once another module of the same name has replaced its own
    in sys.modules, LookupError names *cls* and the module found. An immutable type
    carries no source or annotation to misread, and a class so checked whose body
    compiled no function carries nothing to check it by, so their module is looked up
    unchecked.
    """
    module = _module_named(cls.__module__, cls)
    if is_immutable_type(cls):
        return module
    if "<locals>" in cls.__qualname__:
        return _checked_by_body_function(cls, module)
    bound = _bound_under(cls.__qualname__, module)
    if bound is cls:
        return module
    if not _has_source(module):
        return _checked_by_body_function(cls, module)
    raise LookupError(
        f"{label_of(cls)} is not bound under {cls.__qualname__!r} in "
        f"the module at {getattr(module, '__file__', None)}, which sys.modules holds under "
        f"the name {cls.__module__!r}: that module binds "
        f"{'nothing' if bound is None else 'another object'} there. Read each module's "
        "objects before importing another module of that name, or bind the class under "
        "its qualified name"
    )


def _checked_by_body_function(cls: type, module: types.ModuleType) -> types.ModuleType:
    """*module*, checked to hold as its globals those the first function *cls*'s body compiled carries: LookupError naming *cls* and both modules if it does not; unchecked if that body compiled none."""
    function = _function_compiled_in_body(cls)
    if function is not None and function.__globals__ is not vars(module):
        raise _defined_elsewhere(label_of(cls), function.__globals__, module, cls.__module__)
    return module


def _defined_elsewhere(
    label: str, namespace: dict[str, object], module: types.ModuleType, name: str
) -> LookupError:
    """The error for *label*, defined in the module whose globals are *namespace*, once sys.modules holds *module* in its place under *name*."""
    return LookupError(
        f"{label} is defined in the module at {namespace.get('__file__')}, but sys.modules "
        f"holds the module at {getattr(module, '__file__', None)} under the name {name!r}: "
        "read each module's objects before importing another module of that name"
    )


def _function_compiled_in_body(cls: type) -> types.FunctionType | None:
    """The first function *cls*'s own body compiled, read through spelled_function and unwrapped from any decorator that records it as __wrapped__: one whose code's qualified name is *cls*'s dotted with the code's name; None if the body compiled none, as an annotation-only body compiles none before Python 3.14, which compiles its __annotate__ unless the module imports annotations from __future__, and as the dataclass decorator and EnumType compile the functions they add elsewhere."""
    functions = (spelled_function(member) or member for member in own_namespace(cls).values())
    unwrapped = (
        inspect.unwrap(function) for function in functions if isinstance(function, types.FunctionType)
    )
    return next(
        (
            function
            for function in unwrapped
            if isinstance(function, types.FunctionType)
            and function.__code__.co_qualname == f"{cls.__qualname__}.{function.__code__.co_name}"
        ),
        None,
    )


def _bound_under(qualified_name: str, module: types.ModuleType) -> object:
    """What *module* binds under the dotted *qualified_name*, one attribute at a time; None if it binds nothing there."""
    bound: object = module
    for name in qualified_name.split("."):
        bound = getattr(bound, name, None)
    return bound


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
    for node in ast.parse(inspect.getsource(module)).body:
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


@_cached_while_alive
def _has_source(module: types.ModuleType) -> bool:
    """Whether inspect reads a source for *module*: not for a built-in or extension module, nor for one with no file, as a module types.ModuleType makes has none."""
    try:
        inspect.getsource(module)
    except (OSError, TypeError):
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


def own_namespace(cls: type) -> Mapping[str, object]:
    """The namespace *cls* holds itself, which attribute lookup reads: what type's own __dict__ descriptor gives for *cls*, whatever __dict__ its metaclass gives.

    A class whose metaclass shadows __dict__ raises TypeError naming it, its metaclass, the
    class in that metaclass's MRO that holds the __dict__ in place of type's, and that
    __dict__'s type. By inspect's own rule, a metaclass shadows __dict__ if a class in the
    MRO it records holds, in its own namespace, a __dict__ other than the descriptor CPython
    made for that very class, as a metaclass that defines __dict__ as a property does. Each
    such namespace is read as the class holds it, since inspect never asks whether the
    metaclass's own metaclass shadows __dict__. A class whose metaclass shadows no __dict__,
    but whose metaclass's MRO holds a __getattribute__ that overriding_getattribute_holder
    finds, which may give another __dict__, raises TypeError naming it, its metaclass and the
    class holding that __getattribute__. docs/surface-forms-inspect-readings.md §4.8 says how
    each minor reads such classes.
    """
    _refuse_dict_other_than_held(cls)
    return _held_namespace(cls)


def own_annotations(cls: type) -> Mapping[str, object]:
    """The annotations *cls*'s own body wrote, as inspect.get_annotations reads them: never a base's, and each string left a string; the TypeError own_namespace raises for each class it refuses, since before Python 3.14 inspect.get_annotations reads such a class's annotations from the __dict__ its metaclass gives."""
    _refuse_dict_other_than_held(cls)
    return inspect.get_annotations(cls)


def overriding_getattribute_holder(metaclass: type) -> type | None:
    """The first class in the MRO *metaclass* records, type and object aside, whose own namespace, read unchecked as attribute lookup reads it, holds __getattribute__; None if none does. Attribute lookup on a class of *metaclass* may then call that __getattribute__ for every name, __dict__ and __signature__ among them."""
    return next(
        (
            holder
            for holder in recorded_mro(metaclass)
            if holder not in (type, object) and "__getattribute__" in _held_namespace(holder)
        ),
        None,
    )


def _refuse_dict_other_than_held(cls: type) -> None:
    """Raise the TypeError own_namespace raises for *cls* if its metaclass shadows __dict__, or else if overriding_getattribute_holder finds a __getattribute__ in its metaclass's MRO."""
    _refuse_shadowed_dict(cls)
    holder = overriding_getattribute_holder(type(cls))
    if holder is not None:
        raise _dict_intercepted_error(cls, holder)


def _refuse_shadowed_dict(cls: type) -> None:
    """Raise the TypeError own_namespace raises for *cls* if its metaclass shadows __dict__."""
    for holder in recorded_mro(type(cls)):
        namespace = _held_namespace(holder)
        if "__dict__" in namespace and not _is_own_dict_descriptor(holder, namespace["__dict__"]):
            raise _dict_shadowed_error(cls, holder, namespace["__dict__"])


def _held_namespace(cls: type) -> Mapping[str, object]:
    """The namespace *cls* holds itself, as type's own __dict__ descriptor gives it, read unchecked."""
    namespace: Mapping[str, object] = type.__dict__["__dict__"].__get__(cls)
    return namespace


def _is_own_dict_descriptor(holder: type, held: object) -> bool:
    """Whether *held*, which *holder*'s own namespace holds as __dict__, is the descriptor CPython makes for *holder* as it creates the class, through which its instances read their own __dict__: a getset descriptor called __dict__ whose __objclass__ is *holder*."""
    return (
        type(held) is types.GetSetDescriptorType
        and held.__name__ == "__dict__"
        and held.__objclass__ is holder
    )


def _dict_shadowed_error(cls: type, holder: type, held: object) -> TypeError:
    """The error for *cls*, whose metaclass's MRO holds *holder*, whose own namespace holds *held* as __dict__ in place of the descriptor CPython made for it."""
    return TypeError(
        f"{label_of(cls)} has the metaclass {label_of(type(cls))}, whose MRO holds "
        f"{label_of(holder)}.__dict__, a {label_of(type(held))}, in place of the __dict__ "
        "type gives each class: inspect.getattr_static skips a class whose metaclass so "
        "shadows __dict__, attribute lookup reads the namespace the class holds, and inspect "
        "chooses which of its __new__ and __init__ it reads, and before Python 3.14 reads its "
        "annotations, by what that __dict__ gives, readings no rule of this helper reads: "
        "make the name private, or leave __dict__ to type"
    )


def _dict_intercepted_error(cls: type, holder: type) -> TypeError:
    """The error for *cls*, whose metaclass's MRO holds *holder*, whose own namespace holds a __getattribute__ in place of type's."""
    return TypeError(
        f"{label_of(cls)} has the metaclass {label_of(type(cls))}, whose MRO holds "
        f"{label_of(holder)}.__getattribute__, in place of the __getattribute__ type gives "
        "each class: inspect.getattr_static, and inspect's choice of which of the class's "
        "__new__ and __init__ it reads, read its __dict__ through that __getattribute__, "
        "which may give another namespace than the one the class holds; inspect also reads "
        "its annotations by that __dict__ before Python 3.14, and finds its source by it "
        "from 3.13; these are readings no rule of this helper reads: make the name private, "
        "or leave __getattribute__ to type"
    )


def recorded_mro(cls: type) -> tuple[type, ...]:
    """The MRO *cls* records, which attribute lookup and inspect.getattr_static walk: what type's own __mro__ descriptor gives for *cls*, whatever __mro__ its metaclass gives."""
    mro: tuple[type, ...] = type.__dict__["__mro__"].__get__(cls)
    return mro
