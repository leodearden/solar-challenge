# SPDX-License-Identifier: AGPL-3.0-or-later
"""The modules pytest imports for the entries a module gives its pytest_plugins, read from the module's syntax tree without running it.

plugin_imports follows a literal assigned to the name, or added to it with +=, in the
module's own scope. It fails, naming the file, the line and the statement, on any other
form that can bind or change pytest_plugins. The declared-dependency contract,
tests/_declared_dependencies.py, counts each import it yields as one the module requires.

Usage::

    from tests._pytest_plugins_reader import plugin_imports

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    plugin_modules = [alias.name for node in plugin_imports(source, tree) for alias in node.names]
"""

import ast
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from _pytest.config import builtin_plugins

_PYTEST_PLUGINS = "pytest_plugins"
_NAMESPACE_FUNCTIONS = frozenset({"globals", "locals", "vars"})
_NAMESPACE_ATTRIBUTES = frozenset({"__dict__", "f_globals", "f_locals", "__globals__"})
_ATTRIBUTE_FUNCTIONS = frozenset({"getattr", "setattr", "delattr"})
_CODE_RUNNING_FUNCTIONS = frozenset({"exec", "eval"})
_NAMESPACE_PARAMETERS = ("globals", "locals")


# A unit is what this reader judges and names a failure by: a statement, or an except or
# case clause, which has a header of its own that evaluates expressions and binds names.
_Unit = ast.stmt | ast.excepthandler | ast.match_case
# A def or a class, whose body runs in a scope of its own.
_ScopeOwner = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _scope_units(nodes: Iterable[ast.AST]) -> Iterator[_Unit]:
    """Yield the units under *nodes* that run in the scope *nodes* belong to: those in a block of
    a compound statement such as an if, a try or a with too, however deep.

    Not those in the body of a function or class, which runs in a scope of its own. The def or
    class itself is yielded.
    """
    for node in nodes:
        if isinstance(node, _Unit):
            yield node
        if not isinstance(node, _ScopeOwner):
            yield from _scope_units(ast.iter_child_nodes(node))


def _own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield *node*, a unit or a part of one, and the nodes under it that lie under no unit nested
    in it: what the unit itself evaluates and binds, such as its name, targets, values, tests,
    context managers, exception type and patterns, not what the statements of its blocks or its
    except and case clauses do.
    """
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, _Unit):
            yield from _own_nodes(child)


def _assignment_parts(unit: _Unit) -> tuple[ast.expr | None, ast.expr | None]:
    """Return (target, value) for a *unit* that assigns to one target, annotates or augments: the
    expression it writes to, and the value it assigns or adds, None for an annotation with no
    value.

    Any other unit has no target and no value, a chained assignment among them: its targets alias
    one another, so none is the sole one.
    """
    if isinstance(unit, ast.Assign) and len(unit.targets) == 1:
        return unit.targets[0], unit.value
    if isinstance(unit, (ast.AnnAssign, ast.AugAssign)):
        return unit.target, unit.value
    return None, None


def _bound_name_and_value(node: ast.AST) -> tuple[str, ast.expr] | None:
    """Return (name, value) when *node* binds one bare name to a value: an assignment to that one
    name, an annotated assignment of it with a value, or a walrus. Otherwise return None.

    An augmented assignment binds the result of its operation, not its value, so it is no binding
    here. Nor is a chained assignment, whose targets alias one another, or one to a target of
    another form, such as a tuple, a star, an attribute or a subscript.
    """
    match node:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return name, value
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            return name, value
        case ast.NamedExpr(target=ast.Name(id=name), value=value):
            return name, value
    return None


def _binds_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* binds the name pytest_plugins: as a target, the position of a Name
    that binds it; as the name of a def, a class or an except clause; as a capture of a match
    pattern, whether of one value, of the rest of a sequence or of the rest of a mapping; or as a
    name a from-import binds, which `from m import *` does for every public name of m.

    An import statement binds a module, which pytest reads as naming no plugin, so it binds
    nothing the contract follows.
    """
    match node:
        case (
            ast.Name(id=name, ctx=ast.Store())
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=name)
            | ast.MatchAs(name=name)
            | ast.MatchStar(name=name)
            | ast.MatchMapping(rest=name)
        ):
            return name == _PYTEST_PLUGINS
        case ast.ImportFrom(names=aliases):
            return any((alias.asname or alias.name) in (_PYTEST_PLUGINS, "*") for alias in aliases)
    return False


def _pytest_plugins_assignments(tree: ast.Module) -> Iterator[tuple[_Unit, ast.expr]]:
    """Yield (unit, value) for each unit of *tree*'s module scope, as _scope_units finds them,
    that assigns pytest_plugins as its one target, annotated or not, or augments it. *value* is
    what the unit assigns or adds.

    pytest reads pytest_plugins as an attribute of the module once the module has run, so each
    such unit can give it entries. An annotation with no value assigns nothing.
    """
    for unit in _scope_units(tree.body):
        target, value = _assignment_parts(unit)
        if value is not None and target is not None and _binds_pytest_plugins(target):
            yield unit, value


def _reads_or_deletes_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* is the name pytest_plugins in a position that does not bind it: a read
    or a deletion.

    A read is how a method call such as append, a subscript or an alias changes the list the name
    holds.
    """
    return isinstance(node, ast.Name) and node.id == _PYTEST_PLUGINS and not isinstance(node.ctx, ast.Store)


def _spells_namespace(node: ast.expr, namespace_names: frozenset[str]) -> bool:
    """Return whether *node* is spelled as a namespace dict that may be a module's: a call of
    globals(), locals() or vars(); the __dict__ of an object, a frame's f_globals or f_locals, or
    a function's __globals__; getattr given the str of one of those attributes; a name in
    *namespace_names*, those that hold a namespace where *node* runs; or a walrus of any of these.

    Whatever the call is given counts, so vars(module) does. The object is not resolved, so the
    attribute of any object counts, since the object may be a module whose namespace pytest reads,
    such as sys.modules[__name__], or that module's frame or function. A frame's f_builtins holds
    the builtins, which pytest never consults, so it is not one.
    """
    match node:
        case ast.Call(func=ast.Name(id="getattr"), args=[_, ast.Constant(value=attribute), *_]):
            return attribute in _NAMESPACE_ATTRIBUTES
        case ast.Call(func=ast.Name(id=name)):
            return name in _NAMESPACE_FUNCTIONS
        case ast.Attribute(attr=attr):
            return attr in _NAMESPACE_ATTRIBUTES
        case ast.Name(id=name):
            return name in namespace_names
        case ast.NamedExpr(value=value):
            return _spells_namespace(value, namespace_names)
    return False


def _spells_pytest_plugins_key(node: ast.AST) -> bool:
    """Return whether the str pytest_plugins is anywhere in *node*: as a str constant, or as the
    name of a keyword argument.

    That finds the key wherever an expression gives it: as a subscript, a positional argument, a
    keyword, a key of a dict display, a pair of a list, or dict(pytest_plugins=...). A key held in
    a variable is not read, nor is a mapping that does not spell it, such as `update(SETTINGS)`
    or `update(**SETTINGS)`.
    """
    for part in ast.walk(node):
        match part:
            case ast.Constant(value=name) | ast.keyword(arg=name) if name == _PYTEST_PLUGINS:
                return True
    return False


def _subscripts_namespace_with_pytest_plugins(node: ast.AST, namespace_names: frozenset[str]) -> bool:
    """Return whether *node* subscripts a namespace, as _spells_namespace reads one given
    *namespace_names*, with the key pytest_plugins, as _spells_pytest_plugins_key reads it, in any
    position, as `globals()["pytest_plugins"]` and
    `sys.modules[__name__].__dict__["pytest_plugins"]` do.
    """
    return (
        isinstance(node, ast.Subscript)
        and _spells_namespace(node.value, namespace_names)
        and _spells_pytest_plugins_key(node.slice)
    )


def _calls_on_namespace_with_pytest_plugins(node: ast.AST, namespace_names: frozenset[str]) -> bool:
    """Return whether *node* is a call on a namespace, as _spells_namespace reads one given
    *namespace_names*, that is given the key pytest_plugins, as _spells_pytest_plugins_key reads
    it, in any argument, positional or keyword; or a |= of a namespace with that key.

    A call is on a namespace when it is a method of one, as `globals().update(...)` is, or when
    one of its arguments, positional or a keyword's value, spells one, as `dict.update(globals(),
    ...)` does. No method is singled out: get or pop hand out the list as surely as update or
    setdefault write it. The |= of a namespace calls its __ior__, which updates it in place as
    update does.
    """
    match node:
        case ast.AugAssign(target=target, op=ast.BitOr(), value=value):
            return _spells_namespace(target, namespace_names) and _spells_pytest_plugins_key(value)
        case ast.Call(func=function, args=args, keywords=keywords):
            operands = [*args, *(keyword.value for keyword in keywords)]
            if isinstance(function, ast.Attribute):
                operands.append(function.value)
            return any(_spells_namespace(operand, namespace_names) for operand in operands) and any(
                _spells_pytest_plugins_key(argument) for argument in [*args, *keywords]
            )
    return False


def _reaches_attribute_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* reaches an attribute named pytest_plugins: as one in any context, a
    load, a store or a del, as `sys.modules[__name__].pytest_plugins = ...` does; through getattr,
    setattr or delattr given the str pytest_plugins; or by a from-import of the name, whatever name
    it binds, which reads that attribute of its module.

    The object is not resolved, so an attribute of that name on any object counts, since the
    object may be a module whose attribute pytest reads, such as sys.modules[__name__]. hasattr is
    not read, since the bool it returns cannot change the attribute.
    """
    if isinstance(node, ast.Attribute):
        return node.attr == _PYTEST_PLUGINS
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == _PYTEST_PLUGINS for alias in node.names)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _ATTRIBUTE_FUNCTIONS
        and len(node.args) > 1
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == _PYTEST_PLUGINS
    )


def _may_run_in_a_namespace_of_the_module(call: ast.Call, namespace_names: frozenset[str]) -> bool:
    """Return whether the exec or eval *call* may run its code in the namespace of the module: it is
    given no globals, or None for them, so the code runs in the caller's; or it is given, for
    globals or locals, positionally or by keyword, a namespace, as _spells_namespace reads one given
    *namespace_names*.

    A dict display, a copy of a namespace or a name that holds none is a namespace of the code's
    own.
    """
    given = dict(zip(_NAMESPACE_PARAMETERS, call.args[1:3]))
    given.update(
        (keyword.arg, keyword.value) for keyword in call.keywords if keyword.arg in _NAMESPACE_PARAMETERS
    )
    globals_argument = given.get("globals")
    return (
        globals_argument is None
        or (isinstance(globals_argument, ast.Constant) and globals_argument.value is None)
        or any(_spells_namespace(argument, namespace_names) for argument in given.values())
    )


def _code_can_bind_or_change_pytest_plugins(source: str | bytes, namespace_names: frozenset[str]) -> bool:
    """Return whether the literal *source* of an exec or eval can bind or change pytest_plugins:
    it does not parse as a module, or _pytest_plugins_units finds a unit in it.

    The code is judged as a module is, given *namespace_names*, those that hold a namespace where
    exec runs, so code that names no pytest_plugins counts for nothing, wherever it runs, and a
    literal exec nested in it is judged the same way. Code that does not parse counts, since eval
    strips leading blanks, which a module does not accept.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return True
    return next(_pytest_plugins_units(tree, namespace_names), None) is not None


def _runs_code_that_can_change_pytest_plugins(node: ast.AST, namespace_names: frozenset[str]) -> bool:
    """Return whether *node* is a call of exec or eval, by its bare name, with code to run, that
    can change pytest_plugins: a literal str or bytes that _code_can_bind_or_change_pytest_plugins
    says can, or any other code that _may_run_in_a_namespace_of_the_module says may run in the
    namespace of the module.

    Only the spelling is read: builtins.exec and an alias of exec are not. Code that exec runs in
    a namespace of its own and cannot be read can still reach the module through sys.modules, like
    any code the file runs but does not spell.
    """
    match node:
        case ast.Call(
            func=ast.Name(id=name), args=[ast.Constant(value=str() | bytes() as source), *_]
        ) if name in _CODE_RUNNING_FUNCTIONS:
            return _code_can_bind_or_change_pytest_plugins(source, namespace_names)
        case ast.Call(func=ast.Name(id=name), args=[_, *_]) if name in _CODE_RUNNING_FUNCTIONS:
            return _may_run_in_a_namespace_of_the_module(node, namespace_names)
    return False


def _unreadable_pytest_plugins_bindings(tree: ast.Module) -> Iterator[_Unit]:
    """Yield each unit of *tree*'s module scope, as _scope_units finds them, that binds
    pytest_plugins in a form _pytest_plugins_assignments does not read: it holds the name as a
    target other than the sole target of an assignment, an annotation or an augmentation, such as
    one of a tuple, a for, a with or a walrus, or beside another target of a chained assignment;
    as the name of a def, a class or an except clause; as a capture of a match pattern; or as a
    name a from-import binds.
    """
    for unit in _scope_units(tree.body):
        read_target, _ = _assignment_parts(unit)
        if any(_binds_pytest_plugins(node) and node is not read_target for node in _own_nodes(unit)):
            yield unit


def _bindings_in(units: Iterable[_Unit]) -> Iterator[tuple[str, ast.expr]]:
    """Yield (name, value) for each binding _bound_name_and_value reads in the own nodes of
    *units*, a walrus among them.
    """
    for unit in units:
        for node in _own_nodes(unit):
            if (binding := _bound_name_and_value(node)) is not None:
                yield binding


def _declared_name_bindings_in_nested_scopes(units: Sequence[_Unit]) -> Iterator[tuple[str, ast.expr]]:
    """Yield (name, value) for each binding that a def or class under *units*, however deep, makes
    of a name it declares global or nonlocal.

    Such a binding sets the name in the scope the declaration points to, not in the one that makes
    it, so every scope around has to count it.
    """
    for unit in units:
        if isinstance(unit, _ScopeOwner):
            inner_units = list(_scope_units(unit.body))
            declared = {
                name
                for inner in inner_units
                if isinstance(inner, (ast.Global, ast.Nonlocal))
                for name in inner.names
            }
            yield from ((name, value) for name, value in _bindings_in(inner_units) if name in declared)
            yield from _declared_name_bindings_in_nested_scopes(inner_units)


def _namespace_names(units: Sequence[_Unit], enclosing: frozenset[str]) -> frozenset[str]:
    """Return the names that hold a namespace in the scope whose units are *units*, given those of
    the scope around it, *enclosing*: each name a binding in the units binds to a namespace,
    directly or through another such name, and each of *enclosing* that no binding in the units
    rebinds.

    The names are the same for every unit of the scope, wherever in it the binding is. A name the
    scope binds to anything else shadows the one around it. A name a def or class nested in the
    scope declares global or nonlocal and binds to a namespace holds one here too, and shadows
    nothing. What it leaves unread is listed in _unreadable_pytest_plugins_uses.
    """
    bindings = list(_bindings_in(units))
    declared_name_bindings = list(_declared_name_bindings_in_nested_scopes(units))
    names = enclosing - {name for name, _ in bindings}
    while True:
        holding = names | {
            name for name, value in [*bindings, *declared_name_bindings] if _spells_namespace(value, names)
        }
        if holding == names:
            return names
        names = holding


def _units_with_their_namespace_names(
    nodes: Iterable[ast.AST], enclosing: frozenset[str], is_class_body: bool = False
) -> Iterator[tuple[_Unit, frozenset[str]]]:
    """Yield (unit, names) for each unit of the scope *nodes* belong to, as _scope_units finds
    them, followed by those of the body of each def or class among them, in document order.
    *names* are the names that hold a namespace where the unit runs, as _namespace_names finds
    them, given *enclosing*, those of the scope around *nodes*. *is_class_body* says that *nodes*
    are a class's.

    Unlike the name pytest_plugins, whose reads count in any scope, the names that hold a
    namespace are resolved by scope, since a name may hold a namespace in one function and a copy
    of one in another. A class body does not enclose the defs in it: they see the names around the
    class, not its variables. A def's decorators and defaults are its own nodes, so they run, and
    a walrus in them binds, in the scope around it, where Python evaluates them.
    """
    units = list(_scope_units(nodes))
    names = _namespace_names(units, enclosing)
    seen_by_nested_scopes = enclosing if is_class_body else names
    for unit in units:
        yield unit, names
        if isinstance(unit, _ScopeOwner):
            yield from _units_with_their_namespace_names(
                unit.body, seen_by_nested_scopes, isinstance(unit, ast.ClassDef)
            )


def _unreadable_pytest_plugins_uses(tree: ast.Module, enclosing: frozenset[str]) -> Iterator[_Unit]:
    """Yield each unit of *tree*, in any scope, that can change pytest_plugins in a form
    _pytest_plugins_assignments does not read: one that declares the name global, since a def or
    class that does can rebind the attribute of the module, and one with a node that any of
    _reads_or_deletes_pytest_plugins, _subscripts_namespace_with_pytest_plugins,
    _calls_on_namespace_with_pytest_plugins, _runs_code_that_can_change_pytest_plugins and
    _reaches_attribute_pytest_plugins reads.

    A read of the name in a function or class body counts even where the name is a local there,
    since that name is not resolved by scope. So does a read in an except type or a case pattern
    or guard, which belongs to its clause, not to the try or match around it. The names that hold
    a namespace are resolved by scope, as _units_with_their_namespace_names says, from *enclosing*,
    those that hold one around *tree*'s code, which matter for the code an exec runs.

    This is the one list of what the reader does not read, here or in the functions above: a key
    _spells_pytest_plugins_key does not spell; exec or eval, or the code they run, as
    _runs_code_that_can_change_pytest_plugins does not read them; a name bound to a namespace in a
    form _bound_name_and_value does not follow, or, by a def or class that declares it global or
    nonlocal, to a name of its own that holds one; a namespace passed into a function and written
    there, or returned by one; a method of one held in a variable.
    """
    for unit, namespace_names in _units_with_their_namespace_names(tree.body, enclosing):
        if (isinstance(unit, ast.Global) and _PYTEST_PLUGINS in unit.names) or any(
            _reads_or_deletes_pytest_plugins(node)
            or _subscripts_namespace_with_pytest_plugins(node, namespace_names)
            or _calls_on_namespace_with_pytest_plugins(node, namespace_names)
            or _runs_code_that_can_change_pytest_plugins(node, namespace_names)
            or _reaches_attribute_pytest_plugins(node)
            for node in _own_nodes(unit)
        ):
            yield unit


def _pytest_plugins_units(
    tree: ast.Module, enclosing: frozenset[str] = frozenset()
) -> Iterator[tuple[_Unit, ast.expr | None]]:
    """Yield (unit, value) for each unit of *tree* that can give or change its pytest_plugins: first
    those that bind or change it in a form the contract cannot read, as
    _unreadable_pytest_plugins_bindings and _unreadable_pytest_plugins_uses find them, with None
    for *value*; then those _pytest_plugins_assignments reads, with the value each assigns or adds.

    This is the one definition of what can give or change a module's pytest_plugins. It serves
    the judgement of a module, whose assignments are read and the rest fail, and that of the code
    an exec or eval runs, where any of them fails. *enclosing* are the names that hold a
    namespace around *tree*'s code, as _unreadable_pytest_plugins_uses takes them.
    """
    for unit in _unreadable_pytest_plugins_bindings(tree):
        yield unit, None
    for unit in _unreadable_pytest_plugins_uses(tree, enclosing):
        yield unit, None
    yield from _pytest_plugins_assignments(tree)


def _first_unparsed_line(tree: ast.Module, unit: _Unit) -> str:
    """Return the first line of *unit*, a part of *tree*, as ast.unparse renders it, except that an
    except clause of a try* keeps its star, which ast.unparse leaves out when it renders the clause
    alone. That clause is rendered in a try* of its own, and its line is the one after the try.
    """
    if isinstance(unit, ast.ExceptHandler) and any(
        unit in try_star.handlers for try_star in ast.walk(tree) if isinstance(try_star, ast.TryStar)
    ):
        try_star_of_the_clause = ast.TryStar(body=[], handlers=[unit], orelse=[], finalbody=[])
        _try_line, clause_line, *_rest = ast.unparse(try_star_of_the_clause).splitlines()
        return clause_line
    return ast.unparse(unit).partition("\n")[0]


def _pytest_plugins_failure(source: Path, tree: ast.Module, unit: _Unit, fault: str) -> AssertionError:
    """Return the failure for the pytest_plugins *unit* in *source*, whose syntax tree is *tree*,
    that the contract cannot follow. It names *source*, the line and the unit, quoted by its first
    line when it is compound; *fault* says what is wrong with it, such as "whose value is not a
    literal". It also says how to write pytest_plugins instead.

    A case clause carries no position of its own, so its line is its pattern's.
    """
    quoted = _first_unparsed_line(tree, unit)
    line = unit.pattern.lineno if isinstance(unit, ast.match_case) else unit.lineno
    return AssertionError(
        f"{source}:{line} has `{quoted}`, {fault}; "
        "assign pytest_plugins, in the module's own scope, a literal list or tuple of module names "
        "or a comma-separated string, and add to it only with += and such a literal, "
        "for the declared-dependency contract to follow the plugins it names"
    )


def plugin_imports(source: Path, tree: ast.Module) -> Iterator[ast.Import]:
    """Yield an import of the module pytest imports for each entry that the assignments
    _pytest_plugins_assignments finds in *tree*, the syntax tree of *source*, give pytest_plugins.
    Each import sits where the value of its assignment does.

    pytest imports each entry when it loads a conftest, test module or plugin that sets one. A
    built-in plugin's short name, such as pytester, names that module of pytest's own _pytest
    package, as PytestPluginManager.import_plugin reads builtin_plugins; any other entry names
    the module it spells. The entries are read without running *source*, so each value must be a
    literal: a str, whose entries are its pieces between commas, or a list or tuple of str. None
    names no plugin. Any other value fails, naming *source*, the line and the unit, and so does a
    unit that _pytest_plugins_units finds in a form the assignments do not read.

    Each assignment's value is read on its own, not added to what the module held before it. That
    is why a str's empty pieces are dropped, such as the one before the comma of `+= ",x"`, and why
    a str added to a list reads as the module it spells, not as the characters list.extend adds.
    """
    for unit, value in _pytest_plugins_units(tree):
        if value is None:
            raise _pytest_plugins_failure(
                source,
                tree,
                unit,
                "which can bind or change pytest_plugins in a form the contract cannot read",
            )
        try:
            plugins = ast.literal_eval(value)
        except ValueError:
            raise _pytest_plugins_failure(source, tree, unit, "whose value is not a literal") from None
        if plugins is None:
            continue
        if not isinstance(plugins, (str, list, tuple)):
            raise _pytest_plugins_failure(
                source, tree, unit, "whose value is neither a str nor a list or tuple"
            )
        entries = [piece for piece in plugins.split(",") if piece] if isinstance(plugins, str) else plugins
        for entry in entries:
            if not isinstance(entry, str):
                raise _pytest_plugins_failure(
                    source, tree, unit, f"whose value names {entry!r}, not a module name"
                )
            module = f"_pytest.{entry}" if entry in builtin_plugins else entry
            yield ast.copy_location(ast.Import(names=[ast.alias(name=module)]), value)
