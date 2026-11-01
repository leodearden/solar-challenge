# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every pointer into tests/ from a scanned file resolves, and names a test only by its node-id.

The scanned files are those git lists outside RECORD_DIRECTORIES, the records, which name tests as they were when
written, such as the PRDs and research notes under docs/.

A pointer is written from the project root: a path rooted at tests/, optionally followed by the ::<Class> and ::<test>
names of a pytest node-id, as in tests/<file>.py::<Class>::<test>. It is looked for in a file's whole text, comments,
docstrings and code alike, but a Python file under tests/ is read only in its comments and the strings it writes as
statements, such as docstrings, since its other strings are its tests' data, such as a throwaway project's files. A
file that is not UTF-8 text holds none. The path is looked up in the files git lists, as a fresh clone would hold them,
so a file git ignores is not there to point at. Its names are looked up in the syntax tree of the Python file there, so
a pointer naming a test in a Python file that is not UTF-8 text, or that does not parse, is reported. A path in another
repository, or in a throwaway checkout a test builds, is written from that tree's name, as in
reify/tests/infra/run_all.sh or <project>/tests/<file>.py, so it is not rooted at tests/. A path not rooted at tests/
that ends a test file tests/ holds, as test_<name>.py or <dir>/test_<name>.py, is refused, naming the path to write.
One that ends no file of tests/ names another tree's or a throwaway project's file, so it is no pointer, but each
test_<name> or Test<Name> after its .py, as in test_<name>.py::<Class> or test_<name>.py.<Class>, is read as a name
given alone, as below.

A test, test class or test file named any other way is refused, and the refusal names each node-id to write: a test or
test class as test_<name> or Test<Name>, alone or next to its file in prose, or joined to a node-id's last name with a
dot, as in ::<Class>.<test>, and a test file by its stem alone, as test_<name>. The settled form is the node-id, which
pytest runs as written and this gate resolves. A name given alone is a pointer only if tests/ holds a test, test class
or test file by that name, so a name tests/ holds nothing by is none, such as a config key, a third-party class or a
throwaway project's test. Nor is a name the file uses itself, in its Python code or as a key of its YAML mappings; a
name written straight after def or class, as an example defines it; or, outside a node-id, a name written straight
after a dot.
"""

import ast
import functools
import io
import re
import tokenize
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import assert_never

import pytest
import yaml

from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import WorkingTreePaths, working_tree_paths

_TESTS = PurePosixPath("tests")


def _is_python_file_under_tests(path: PurePosixPath) -> bool:
    """Return whether *path*, relative to the checkout's root, names a Python file under tests/."""
    return path.suffix == ".py" and path.is_relative_to(_TESTS)


_TEST_LIKE_NAME = re.compile(r"test_\w+|Test[A-Z]\w*")

_POINTER = re.compile(
    rf"""
    (?<![\w./-])
    (?:
        (?:
            (?P<path>tests/(?:[\w.-]+/)*[\w.-]*\w)
          | (?P<relative>(?:[\w.-]+/)*test_\w+\.py(?P<after_py>(?:[\w.-]*\w)?))
        )
        (?P<names>(?:::\w+)*)(?P<dotted_names>(?:\.\w+)*)
      | (?<!def\ )(?<!class\ )(?P<bare>{_TEST_LIKE_NAME.pattern})
    )
    """,
    re.VERBOSE,
)

_POINTERS_UNTOLD = "so its pointers cannot be told from the rest of its text"


@dataclass(frozen=True)
class _Pointer:
    """A pointer into tests/ from the project root: the file holding it, its line, and the path and names it gives.

    The dotted names follow the last name with a dot, as in <Class>.<test>, and a node-id has none.
    """

    source: PurePosixPath
    line: int
    path: PurePosixPath
    names: tuple[str, ...]
    dotted_names: tuple[str, ...]

    def __str__(self) -> str:
        dotted = "".join(f".{name}" for name in self.dotted_names)
        return f"{self.source}:{self.line}: {'::'.join((str(self.path), *self.names))}{dotted}"


@dataclass(frozen=True)
class _UnrootedPointer:
    """A pointer into tests/ written without its path from the project root: the file holding it, its line, its text.

    Its node-ids are those of what it names, one for each test, test class or test file tests/ holds by it, sorted. Its
    refusal names them for the writer to choose from, so it has at least one, and one built with none raises ValueError.
    """

    source: PurePosixPath
    line: int
    written: str
    node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.node_ids:
            raise ValueError(f"{self} names no node-id to write, so it is no pointer")

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {self.written}"


class _NoSyntaxTree(Enum):
    """Why a Python file has no syntax tree for the gate to read.

    A reason for a pointer gives the member's value after the file's path.
    """

    NOT_UTF8 = "is not UTF-8 text"
    DOES_NOT_PARSE = "does not parse"


class _Checkout:
    """A git checkout as the gate reads it, from its root.

    Its paths are the files git lists in it and the directories holding them, as a fresh clone would hold them, listed
    once, when it is built. It reads each file's text, and parses each Python file, at most once, in caches of its own,
    so none outlives it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self.paths: WorkingTreePaths = working_tree_paths(root)
        self._texts: dict[PurePosixPath, str | None] = {}
        self._syntax_trees: dict[PurePosixPath, ast.Module | _NoSyntaxTree] = {}

    def text(self, path: PurePosixPath) -> str | None:
        """Return the text of the file at *path*, relative to the root, as utf8_text reads it."""
        if path not in self._texts:
            self._texts[path] = utf8_text(self._root / path)
        return self._texts[path]

    def syntax_tree(self, path: PurePosixPath) -> ast.Module | _NoSyntaxTree:
        """Return the syntax tree of the Python file at *path*, relative to the root, or why it has none."""
        if path not in self._syntax_trees:
            self._syntax_trees[path] = _syntax_tree(self.text(path))
        return self._syntax_trees[path]

    def node_ids_named(self, name: str) -> tuple[str, ...]:
        """Return the node-ids, sorted, of each def, class and test file the Python files under tests/ hold by *name*.

        A def or class counts where a node-id resolves to it, as _undefined resolves one, and a test file goes by its
        stem, as test_<name>, its node-id being its path. A file that is not UTF-8 text or does not parse adds no def.
        """
        return self._node_ids_by_name.get(name, ())

    @functools.cached_property
    def _node_ids_by_name(self) -> Mapping[str, tuple[str, ...]]:
        node_ids: defaultdict[str, list[str]] = defaultdict(list)
        for path in self.paths.files:
            if not _is_python_file_under_tests(path):
                continue
            if path.name.startswith("test_"):
                node_ids[path.stem].append(str(path))
            module = self.syntax_tree(path)
            if isinstance(module, ast.Module):
                for name, node_id in _node_ids_defined(str(path), module.body):
                    node_ids[name].append(node_id)
        return {name: tuple(sorted(named)) for name, named in node_ids.items()}

    def test_files_ending(self, relative: PurePosixPath) -> tuple[PurePosixPath, ...]:
        """Return the files under tests/ whose last parts are all the parts of the *relative* path, sorted."""
        candidates = self._tests_files_by_name.get(relative.name, ())
        return tuple(sorted(path for path in candidates if path.parts[-len(relative.parts) :] == relative.parts))

    @functools.cached_property
    def _tests_files_by_name(self) -> Mapping[str, tuple[PurePosixPath, ...]]:
        files: defaultdict[str, list[PurePosixPath]] = defaultdict(list)
        for path in self.paths.files:
            if path.is_relative_to(_TESTS):
                files[path.name].append(path)
        return {name: tuple(named) for name, named in files.items()}


def _syntax_tree(text: str | None) -> ast.Module | _NoSyntaxTree:
    """Return the syntax tree of the Python module whose text, as utf8_text reads it, is *text*, or why it has none."""
    if text is None:
        return _NoSyntaxTree.NOT_UTF8
    try:
        return ast.parse(text)
    except SyntaxError:
        return _NoSyntaxTree.DOES_NOT_PARSE


def _pointers(checkout: _Checkout, sources: Iterable[PurePosixPath]) -> list[_Pointer | _UnrootedPointer]:
    """Return every pointer in the *sources*, paths relative to the *checkout*'s root, file by file and in text order."""
    pointers: list[_Pointer | _UnrootedPointer] = []
    for source in sources:
        text = checkout.text(source)
        if text is not None:
            pointers.extend(_pointers_in(checkout, source, text))
    return pointers


def _pointers_in(checkout: _Checkout, source: PurePosixPath, text: str) -> list[_Pointer | _UnrootedPointer]:
    """Return the pointers in *text*, the text of the file *source* in the *checkout*, in text order.

    The names the file uses itself, as a Python module's identifiers or a YAML file's keys, are read only if a test-like
    name is read as given alone in it.
    """

    @functools.cache
    def own_names() -> frozenset[str]:
        return _own_names(checkout, source, text)

    return [
        pointer
        for first_line, passage in _passages(checkout, source, text)
        for match in _POINTER.finditer(passage)
        for pointer in _pointers_given(
            checkout, source, first_line + passage.count("\n", 0, match.start()), match, own_names
        )
    ]


def _passages(checkout: _Checkout, source: PurePosixPath, text: str) -> list[tuple[int, str]]:
    """Return the passages of *text*, the text of the file *source* in the *checkout*, each after its first line's number.

    A Python file under tests/ gives each of its comments and each string it writes as a statement, in text order, a
    string statement before a comment on a line they share. They are read from its raw text, so a line counted within a
    passage is a line of the file. Any other file gives its whole text.
    """
    if not _is_python_file_under_tests(source):
        return [(1, text)]
    strings = _string_statements(_parsed_source(checkout, source), text)
    comments = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]
    return sorted([*strings, *comments], key=lambda passage: passage[0])


def _string_statements(module: ast.Module, text: str) -> list[tuple[int, str]]:
    """Return each string the *module* parsed from *text* writes as a statement, as its raw text after its line's number.

    The raw text is sliced from *text*'s UTF-8 bytes at the string's line and byte columns, as ast.get_source_segment
    slices it, but over line starts found once for the module rather than once for each string.
    """
    data = text.encode()
    line_starts = [0, *(line_break.end() for line_break in re.finditer(rb"\r\n|\r|\n", data))]
    strings: list[tuple[int, str]] = []
    for statement in _statements(module):
        match statement:
            case ast.Expr(
                value=ast.Constant(
                    value=str(),
                    lineno=line,
                    col_offset=column,
                    end_lineno=int() as end_line,
                    end_col_offset=int() as end_column,
                )
            ):
                raw = data[line_starts[line - 1] + column : line_starts[end_line - 1] + end_column]
                strings.append((line, raw.decode()))
    return strings


def _statements(node: ast.AST) -> Iterator[ast.stmt]:
    """Yield each statement written in *node*'s syntax tree, at any depth, in text order.

    A statement is written only in a module, another statement, an except handler or a match case, so the walk never
    looks into an expression.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            yield child
        if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
            yield from _statements(child)


def _pointers_given(
    checkout: _Checkout,
    source: PurePosixPath,
    line: int,
    match: re.Match[str],
    own_names: Callable[[], frozenset[str]],
) -> Sequence[_Pointer | _UnrootedPointer]:
    """Return the pointers *match* gives on *line* of the file *source* in the *checkout*, in text order.

    A path rooted at tests/ gives one, and so does a path not rooted there that ends a file of tests/. A test-like name
    given alone, and each test-like name after the .py of any other path, is read by _pointers_named_alone with
    *own_names*.
    """
    if match["bare"] is not None:
        return _pointers_named_alone(checkout, source, line, [match["bare"]], own_names)
    names = tuple(match["names"].split("::")[1:])
    dotted_names = tuple(match["dotted_names"].split(".")[1:])
    if match["path"] is not None:
        path = PurePosixPath(match["path"])
        return [_Pointer(source=source, line=line, path=path, names=names, dotted_names=dotted_names)]
    files = checkout.test_files_ending(PurePosixPath(match["relative"]))
    if files:
        node_ids = tuple("::".join((str(file), *names, *dotted_names)) for file in files)
        return [_UnrootedPointer(source=source, line=line, written=match[0], node_ids=node_ids)]
    words_after_py = re.findall(r"\w+", match["after_py"] + match["names"] + match["dotted_names"])
    test_like_names = [word for word in words_after_py if _TEST_LIKE_NAME.fullmatch(word)]
    return _pointers_named_alone(checkout, source, line, test_like_names, own_names)


def _pointers_named_alone(
    checkout: _Checkout,
    source: PurePosixPath,
    line: int,
    names: Iterable[str],
    own_names: Callable[[], frozenset[str]],
) -> list[_UnrootedPointer]:
    """Return a pointer for each of the test-like *names* read as given alone on *line* of the file *source*, in order.

    A name gives one only if it is not among *own_names*, those the file uses itself, and the *checkout*'s tests/ holds a
    test, test class or test file by it.
    """
    return [
        _UnrootedPointer(source=source, line=line, written=name, node_ids=node_ids)
        for name in names
        if name not in own_names() and (node_ids := checkout.node_ids_named(name))
    ]


def _own_names(checkout: _Checkout, source: PurePosixPath, text: str) -> frozenset[str]:
    """Return the names the file *source* in the *checkout*, whose text is *text*, uses itself.

    They are a Python module's identifiers or a YAML file's mapping keys. A file of any other kind uses none. A Python or
    YAML file that does not parse raises ValueError, naming the file.
    """
    match source.suffix:
        case ".py":
            return _code_names(_parsed_source(checkout, source))
        case ".yaml" | ".yml":
            try:
                return _yaml_keys(text)
            except yaml.YAMLError as error:
                raise ValueError(f"{source} does not parse, {_POINTERS_UNTOLD}: {error}") from error
        case _:
            return frozenset()


def _parsed_source(checkout: _Checkout, source: PurePosixPath) -> ast.Module:
    """Return the syntax tree of the Python file *source* in the *checkout*, or raise ValueError naming it if it has none."""
    module = checkout.syntax_tree(source)
    if isinstance(module, _NoSyntaxTree):
        raise ValueError(f"{source} {module.value}, {_POINTERS_UNTOLD}")
    return module


def _code_names(module: ast.Module) -> frozenset[str]:
    """Return the names of the variables, arguments, attributes, keywords, defs and classes in the Python *module*."""
    return frozenset(name for node in ast.walk(module) if (name := _code_name(node)) is not None)


def _code_name(node: ast.AST) -> str | None:
    """Return the name *node* gives, if it is a variable, argument, attribute, keyword, def or class; None otherwise."""
    match node:
        case (
            ast.Name(id=name)
            | ast.arg(arg=name)
            | ast.Attribute(attr=name)
            | ast.keyword(arg=str() as name)
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            return name
    return None


def _yaml_keys(text: str) -> frozenset[str]:
    """Return the scalar keys of every mapping in each YAML document in *text*, at any depth.

    They are read from the composed nodes, so no tag needs a constructor.
    """
    documents = yaml.compose_all(text, Loader=yaml.SafeLoader)
    return frozenset(key for document in documents for key in _mapping_keys(document))


def _mapping_keys(node: yaml.Node) -> Iterator[str]:
    """Yield the scalar keys of *node*, a composed YAML node, if it is a mapping, and of each mapping nested in it."""
    match node:
        case yaml.MappingNode(value=pairs):
            for key, item in pairs:
                if isinstance(key, yaml.ScalarNode):
                    yield key.value
                yield from _mapping_keys(item)
        case yaml.SequenceNode(value=items):
            for item in items:
                yield from _mapping_keys(item)


def _dangling(checkout: _Checkout, pointers: Iterable[_Pointer | _UnrootedPointer]) -> list[str]:
    """Return "<pointer>: <reason>" for each of the *pointers* that does not resolve in the *checkout*, in their order."""
    return [f"{pointer}: {reason}" for pointer in pointers if (reason := _refusal(checkout, pointer)) is not None]


def _refusal(checkout: _Checkout, pointer: _Pointer | _UnrootedPointer) -> str | None:
    """Return why *pointer* does not resolve in the *checkout*, or None if it resolves.

    One written without its path from the project root never resolves, and its reason names the node-ids to write.
    """
    match pointer:
        case _UnrootedPointer(node_ids=node_ids):
            return _named_without_its_path(node_ids)
        case _Pointer():
            return _unresolved(checkout, pointer)
        case _:
            assert_never(pointer)


def _named_without_its_path(node_ids: Iterable[str]) -> str:
    """Return the reason that refuses a pointer written without its path from the project root, naming *node_ids*."""
    return f"names a test or test file without its path from the project root, so write {' or '.join(node_ids)}"


def _unresolved(checkout: _Checkout, pointer: _Pointer) -> str | None:
    """Return why *pointer* leads to no file, directory or test in the *checkout*, or None if it leads to one.

    Its names must be joined by ::, and the checkout's paths must hold its path. Its names are looked up in the syntax
    tree of the Python file there, and the file is never imported.
    """
    if pointer.dotted_names:
        node_id = "::".join((str(pointer.path), *pointer.names, *pointer.dotted_names))
        return f"a node-id joins its names with ::, so write {node_id}"
    if not checkout.paths.holds(pointer.path):
        return f"{pointer.path} does not exist, or git ignores it"
    if not pointer.names:
        return None
    if pointer.path.suffix != ".py" or pointer.path not in checkout.paths.files:
        return f"{pointer.path} is not a Python file, so it defines no {pointer.names[0]}"
    module = checkout.syntax_tree(pointer.path)
    if isinstance(module, _NoSyntaxTree):
        return f"{pointer.path} {module.value}, so it defines no {pointer.names[0]}"
    return _undefined(pointer.path, pointer.names, module)


def _undefined(path: PurePosixPath, names: tuple[str, ...], module: ast.Module) -> str | None:
    """Return why *names* lead to no definition in *module*, the syntax tree of *path*, or None if they lead to one.

    The first name must be a def or class written at the module's top level, and each later name one written directly
    in the previous class's body: a pointer names where its test is written. So a test inherited, generated or defined
    under a condition does not count, though pytest may collect it.
    """
    definition = _definitions(module.body).get(names[0])
    if definition is None:
        return f"{path} defines no {names[0]} at its top level"
    for name in names[1:]:
        if not isinstance(definition, ast.ClassDef):
            return f"{definition.name} is a function, so it defines no {name}"
        member = _definitions(definition.body).get(name)
        if member is None:
            return f"{definition.name} defines no {name}"
        definition = member
    return None


def _definitions(body: list[ast.stmt]) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Map the name of each def, async def and class written directly in *body* to its node."""
    return {
        statement.name: statement
        for statement in body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _node_ids_defined(prefix: str, body: list[ast.stmt]) -> Iterator[tuple[str, str]]:
    """Yield the name and node-id, <prefix>::<name>, of each _definitions entry of *body*, and of each class's, nested."""
    for name, definition in _definitions(body).items():
        node_id = f"{prefix}::{name}"
        yield name, node_id
        if isinstance(definition, ast.ClassDef):
            yield from _node_ids_defined(node_id, definition.body)


def _sources(root: Path) -> list[PurePosixPath]:
    """Return the files the gate scans in the checkout at *root*: those git lists outside the records."""
    return scanned_files(root, RECORD_DIRECTORIES)


def test_every_pointer_from_the_scanned_files_into_tests_resolves(project_root: Path) -> None:
    checkout = _Checkout(project_root)
    pointers = _pointers(checkout, _sources(project_root))
    records = ", ".join(f"{directory}/" for directory in RECORD_DIRECTORIES)
    assert pointers, (
        f"found no pointer into tests/ in any file git lists outside the records ({records}), so this gate would pass"
        " vacuously; fix the listing or the grammar"
    )

    dangling = _dangling(checkout, pointers)

    assert dangling == [], "\n".join(
        [
            *dangling,
            "A renamed or moved test's pointers must follow it. Point at a test by its node-id from the project root,"
            " tests/<file>.py::<test> or tests/<file>.py::<Class>::<test>, which this gate resolves and pytest runs"
            " as written. A path in another repository, or in a throwaway checkout a test builds, is written from"
            " that tree's name, as in reify/tests/infra/run_all.sh or <project>/tests/<file>.py, so it is not rooted"
            " at tests/.",
        ]
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a git checkout whose tests/unit holds notes.txt and test_pointed_at.py, defining tests, a class and a nested one."""
    return synthetic_checkout(
        tmp_path,
        {
            "tests/unit/test_pointed_at.py": (
                "def test_top(): pass\n"
                "class TestGroup:\n"
                "    def test_member(self): pass\n"
                "    class TestNested:\n"
                "        def test_deep(self): pass\n"
            ),
            "tests/unit/notes.txt": "Not Python.\n",
        },
    )


def test_scans_every_file_git_lists_outside_the_records(project: Path) -> None:
    scanned = {
        "CLAUDE.md",
        "docs/guide.md",
        "pyproject.toml",
        "scenarios/fleet.yaml",
        "scripts/measure.py",
        "src/pkg/module.py",
        "tests/fixtures/schema.sql",
        "tests/unit/test_module.py",
    }
    unscanned = ["docs/prds/record.md", "docs/research/survey.md", "plans/plan.md", "review/briefing.yaml"]
    for source in [*scanned, *unscanned]:
        write_file(project, source, "")
    project_fixture_files = ["tests/unit/notes.txt", "tests/unit/test_pointed_at.py"]

    assert set(_sources(project)) == {PurePosixPath(source) for source in [*scanned, *project_fixture_files]}


def test_pointers_to_existing_files_directories_and_tests_resolve(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/module.py",
        "# Pinned by tests/unit/test_pointed_at.py.\n"
        "# Its siblings (tests/unit) say why.\n"
        "# tests/unit/test_pointed_at.py::test_top\n"
        "# tests/unit/test_pointed_at.py::test_top[3.14]\n"
        "# tests/unit/test_pointed_at.py::TestGroup\n"
        "# tests/unit/test_pointed_at.py::TestGroup::test_member\n"
        "# tests/unit/test_pointed_at.py::TestGroup::TestNested::test_deep\n"
        "# Not rooted at tests/: src/tests/test_gone.py, https://example.org/pvlib/tests/test_gone.py,\n"
        "# unittests/test_gone.py, my-tests/test_gone.py and site.tests/test_gone.py\n",
    )
    checkout = _Checkout(project)

    pointers = _pointers(checkout, [source])

    assert [str(pointer) for pointer in pointers] == [
        "src/pkg/module.py:1: tests/unit/test_pointed_at.py",
        "src/pkg/module.py:2: tests/unit",
        "src/pkg/module.py:3: tests/unit/test_pointed_at.py::test_top",
        "src/pkg/module.py:4: tests/unit/test_pointed_at.py::test_top",
        "src/pkg/module.py:5: tests/unit/test_pointed_at.py::TestGroup",
        "src/pkg/module.py:6: tests/unit/test_pointed_at.py::TestGroup::test_member",
        "src/pkg/module.py:7: tests/unit/test_pointed_at.py::TestGroup::TestNested::test_deep",
    ]
    assert _dangling(checkout, pointers) == []


def test_reports_each_pointer_that_does_not_resolve_on_its_line(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_absent.py\n"
        "# tests/unit/test_pointed_at.py::test_member\n"
        "# tests/unit/test_pointed_at.py::TestGroup::test_absent\n"
        "# tests/unit/test_pointed_at.py::TestGroup.test_absent\n"
        "# tests/unit/test_pointed_at.py::test_top::test_inner\n"
        "# tests/unit/notes.txt::test_top\n"
        "# tests/unit::test_top\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_absent.py:"
        " tests/unit/test_absent.py does not exist, or git ignores it",
        "src/pkg/module.py:2: tests/unit/test_pointed_at.py::test_member:"
        " tests/unit/test_pointed_at.py defines no test_member at its top level",
        "src/pkg/module.py:3: tests/unit/test_pointed_at.py::TestGroup::test_absent: TestGroup defines no test_absent",
        "src/pkg/module.py:4: tests/unit/test_pointed_at.py::TestGroup.test_absent:"
        " a node-id joins its names with ::, so write tests/unit/test_pointed_at.py::TestGroup::test_absent",
        "src/pkg/module.py:5: tests/unit/test_pointed_at.py::test_top::test_inner:"
        " test_top is a function, so it defines no test_inner",
        "src/pkg/module.py:6: tests/unit/notes.txt::test_top:"
        " tests/unit/notes.txt is not a Python file, so it defines no test_top",
        "src/pkg/module.py:7: tests/unit::test_top: tests/unit is not a Python file, so it defines no test_top",
    ]


def test_a_file_or_directory_git_ignores_does_not_resolve(project: Path) -> None:
    write_file(project, ".gitignore", "generated/\n")
    write_file(project, "tests/unit/generated/test_made.py", "def test_made(): pass\n")
    source = write_file(
        project, "src/pkg/module.py", "# tests/unit/generated/test_made.py::test_made\n# tests/unit/generated\n"
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/generated/test_made.py::test_made:"
        " tests/unit/generated/test_made.py does not exist, or git ignores it",
        "src/pkg/module.py:2: tests/unit/generated: tests/unit/generated does not exist, or git ignores it",
    ]


def test_reports_each_pointer_into_a_python_file_that_is_not_utf8_text(project: Path) -> None:
    write_file(project, "tests/unit/test_latin1.py", "def test_top(): pass  # café\n".encode("latin-1"))
    source = write_file(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_latin1.py::test_top\n"
        "# tests/unit/test_latin1.py::TestGroup::test_member\n"
        "# tests/unit/test_latin1.py names no test\n"
        "# pinned by test_top\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_latin1.py::test_top:"
        " tests/unit/test_latin1.py is not UTF-8 text, so it defines no test_top",
        "src/pkg/module.py:2: tests/unit/test_latin1.py::TestGroup::test_member:"
        " tests/unit/test_latin1.py is not UTF-8 text, so it defines no TestGroup",
        "src/pkg/module.py:4: test_top: " + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
    ]


def test_reports_each_pointer_into_a_python_file_that_does_not_parse(project: Path) -> None:
    write_file(project, "tests/unit/test_broken.py", "def test_top(): pass\ndef test_broken(:\n")
    source = write_file(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_broken.py::test_top\n"
        "# tests/unit/test_broken.py::TestGroup::test_member\n"
        "# tests/unit/test_broken.py names no test\n"
        "# pinned by test_top\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_broken.py::test_top:"
        " tests/unit/test_broken.py does not parse, so it defines no test_top",
        "src/pkg/module.py:2: tests/unit/test_broken.py::TestGroup::test_member:"
        " tests/unit/test_broken.py does not parse, so it defines no TestGroup",
        "src/pkg/module.py:4: test_top: " + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
    ]


def test_resolves_a_pointer_into_a_python_file_that_starts_with_a_byte_order_mark(project: Path) -> None:
    write_file(project, "tests/unit/test_marked.py", "def test_top(): pass\n".encode("utf-8-sig"))
    source = write_file(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_marked.py::test_top\n# tests/unit/test_marked.py::test_absent\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:2: tests/unit/test_marked.py::test_absent:"
        " tests/unit/test_marked.py defines no test_absent at its top level",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = write_file(project, "src/pkg/logo.png", b"\x89PNG\xff\xfe tests/unit/test_absent.py")
    checkout = _Checkout(project)

    pointers = _pointers(checkout, [logo])

    assert pointers == []
    assert _dangling(checkout, pointers) == []


def test_reads_the_pointers_in_a_python_source_that_starts_with_a_byte_order_mark(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/marked.py",
        "# pinned by test_top\ndef build(test_config=None):\n    return test_config\n".encode("utf-8-sig"),
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/marked.py:1: test_top: " + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"])
    ]


def test_reports_a_test_its_class_or_its_file_named_without_its_path(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/script.js",
        "// pinned by test_top\n"
        "// TestGroup covers the rest.\n"
        "// test_member in tests/unit/test_pointed_at.py says why.\n"
        "// tests/unit/test_pointed_at.py's test_top shows it.\n"
        "// Testing it needs pytest_configure and build_test_app, then app.test_client().\n"
        "// Its response is a werkzeug.test.TestResponse.\n"
        "// Not a test name: src/tests/test_gone.py or pre-test_gone\n"
        "// test_pointed_at holds them.\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/script.js:1: test_top: " + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
        "src/pkg/script.js:2: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/script.js:3: test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
        "src/pkg/script.js:4: test_top: " + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
        "src/pkg/script.js:8: test_pointed_at: " + _named_without_its_path(["tests/unit/test_pointed_at.py"]),
    ]


def test_reports_a_name_tests_defines_twice_naming_both_node_ids(project: Path) -> None:
    write_file(project, "tests/e2e/test_other.py", "def test_top(): pass\n")
    source = write_file(project, "src/pkg/script.js", "// pinned by test_top\n")
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/script.js:1: test_top: names a test or test file without its path from the project root, so write"
        " tests/e2e/test_other.py::test_top or tests/unit/test_pointed_at.py::test_top"
    ]


def test_a_test_like_name_tests_holds_nothing_by_is_no_pointer(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/script.js",
        "// Flask reads test_config; Werkzeug's TestResponse; a throwaway project's test_gamma.\n",
    )
    checkout = _Checkout(project)

    assert _pointers(checkout, [source]) == []


def test_a_name_written_straight_after_def_or_class_is_no_pointer(project: Path) -> None:
    example = write_file(
        project, "docs/example.md", "    def test_top():\n    class TestGroup:\n    async def test_member(self):\n"
    )
    checkout = _Checkout(project)

    assert _pointers(checkout, [example]) == []


def test_reports_a_test_file_named_by_a_path_not_rooted_at_tests_naming_its_path(project: Path) -> None:
    write_file(project, "tests/unit/test_twin.py", "")
    write_file(project, "tests/e2e/test_twin.py", "")
    source = write_file(
        project,
        "src/pkg/module.py",
        "# test_pointed_at.py says why.\n"
        "# unit/test_pointed_at.py::TestGroup::test_member\n"
        "# test_pointed_at.py::TestGroup.test_member\n"
        "# test_twin.py\n"
        "# config/test_pointed_at.py and lib/test_pointed_at.py end no file of tests/,"
        " nor does a throwaway test_gamma.py.\n"
        "# Nor do backups such as test_pointed_at.py.bak and unit/test_pointed_at.py-old.\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: test_pointed_at.py: " + _named_without_its_path(["tests/unit/test_pointed_at.py"]),
        "src/pkg/module.py:2: unit/test_pointed_at.py::TestGroup::test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
        "src/pkg/module.py:3: test_pointed_at.py::TestGroup.test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
        "src/pkg/module.py:4: test_twin.py: "
        + _named_without_its_path(["tests/e2e/test_twin.py", "tests/unit/test_twin.py"]),
    ]


def test_a_test_like_name_after_a_path_that_ends_no_file_of_tests_is_read_as_given_alone(project: Path) -> None:
    write_file(project, "tests/unit/_cases.py", "def make_case(): pass\n")
    source = write_file(
        project,
        "src/pkg/module.py",
        "# test_gone.py::TestGroup covers it.\n"
        "# unit/test_gone.py::TestGroup.test_member\n"
        "# test_gone.py::make_case and test_gone.py::test_gamma name no test tests/ holds.\n"
        "# test_pointed_at.py.TestGroup.test_member joins its names to the file's with dots,\n"
        "# unit/test_gone.py-TestGroup with a hyphen; test_gone.py.make_case names no test.\n"
        "# test_gone.py.TestGroup::test_member joins one name with a dot and the next with ::, read in text order.\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/module.py:2: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/module.py:2: test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
        "src/pkg/module.py:4: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/module.py:4: test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
        "src/pkg/module.py:5: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/module.py:6: TestGroup: " + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup"]),
        "src/pkg/module.py:6: test_member: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::TestGroup::test_member"]),
    ]


def test_a_pointer_written_without_its_path_names_a_node_id_to_write() -> None:
    with pytest.raises(ValueError, match=r"^src/pkg/module\.py:3: test_gone names no node-id to write"):
        _UnrootedPointer(source=PurePosixPath("src/pkg/module.py"), line=3, written="test_gone", node_ids=())


@pytest.mark.parametrize(
    ("source", "line_break", "lines_and_letters"),
    [
        (
            "tests/unit/test_prose.py",
            "\n",
            [(1, "a"), (2, "b"), (3, "c"), (6, "d"), (11, "e"), (12, "f"), (13, "g"), (16, "h")],
        ),
        (
            "tests/unit/test_prose.py",
            "\r\n",
            [(1, "a"), (2, "b"), (3, "c"), (6, "d"), (11, "e"), (12, "f"), (13, "g"), (16, "h")],
        ),
        (
            "src/pkg/prose.py",
            "\n",
            [(1, "a"), (2, "b"), (3, "x"), (3, "c"), (6, "d"), (8, "y"), (11, "e"), (12, "f"), (13, "g"), (16, "h")],
        ),
    ],
    ids=["under-tests", "under-tests-crlf", "outside-tests"],
)
def test_reads_a_test_module_only_in_its_comments_and_string_statements(
    project: Path, source: str, line_break: str, lines_and_letters: list[tuple[int, str]]
) -> None:
    lines = [
        '"""Prose naming tests/unit/test_absent_a.py."""',
        "# tests/unit/test_absent_b.py says why.",
        'FORM = "tests/unit/test_absent_x.py"  # tests/unit/test_absent_c.py',
        "def test_case():",
        '    """Check the case.',
        "    tests/unit/test_absent_d.py pins it.",
        '    """',
        '    assert check("tests/unit/test_absent_y.py")',
        "class TestCase:",
        "    FIELDS = {}",
        '    """tests/unit/test_absent_e.py lists them."""',
        '"tests/unit/test_absent_f.py is named in a string statement that is no docstring."',
        'ANGLE = "θé"; "tests/unit/test_absent_g.py follows text that is not ASCII on its line."',
        "def test_angle():",
        '    """Check θ, the angle § 2 gives —',
        '    tests/unit/test_absent_h.py pins it."""',
    ]
    prose = write_file(project, source, "".join(f"{line}{line_break}" for line in lines))
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [prose])) == [
        f"{source}:{line}: tests/unit/test_absent_{letter}.py:"
        f" tests/unit/test_absent_{letter}.py does not exist, or git ignores it"
        for line, letter in lines_and_letters
    ]


def test_reads_a_file_under_tests_that_is_not_python_whole(project: Path) -> None:
    schema = write_file(project, "tests/fixtures/schema.sql", "-- tests/unit/test_absent_g.py writes it.\n")
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [schema])) == [
        "tests/fixtures/schema.sql:1: tests/unit/test_absent_g.py:"
        " tests/unit/test_absent_g.py does not exist, or git ignores it"
    ]


def test_a_test_module_names_tests_of_its_own_and_of_its_throwaway_projects_freely(project: Path) -> None:
    mentions = write_file(
        project,
        "tests/unit/test_mentions.py",
        "def test_here():\n"
        '    """Unlike test_top, test_here reads a throwaway project\'s test_gamma."""\n'
        "# test_pointed_at.py and test_pointed_at hold test_top.\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [mentions])) == [
        "tests/unit/test_mentions.py:2: test_top: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
        "tests/unit/test_mentions.py:3: test_pointed_at.py: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py"]),
        "tests/unit/test_mentions.py:3: test_pointed_at: " + _named_without_its_path(["tests/unit/test_pointed_at.py"]),
        "tests/unit/test_mentions.py:3: test_top: "
        + _named_without_its_path(["tests/unit/test_pointed_at.py::test_top"]),
    ]


def test_a_python_module_may_use_test_prefixed_identifiers_of_its_own(project: Path) -> None:
    write_file(project, "tests/unit/test_app.py", "def test_config(): pass\n")
    using = write_file(
        project,
        "src/pkg/app.py",
        "def build(test_config=None):\n"
        '    """Build the app.\n'
        "\n"
        "    test_config: overrides.\n"
        '    """\n'
        "    return test_config\n",
    )
    naming = write_file(project, "src/pkg/other.py", "# Set test_config first.\ndef build():\n    return None\n")
    checkout = _Checkout(project)

    assert _pointers(checkout, [using]) == []
    assert _dangling(checkout, _pointers(checkout, [naming])) == [
        "src/pkg/other.py:1: test_config: " + _named_without_its_path(["tests/unit/test_app.py::test_config"])
    ]


@pytest.mark.parametrize("suffix", [".yaml", ".yml"])
def test_a_yaml_file_may_use_test_prefixed_keys_of_its_own(project: Path, suffix: str) -> None:
    write_file(project, "tests/unit/test_pipeline.py", "def test_command(): pass\ndef test_timeout(): pass\n")
    using = write_file(
        project,
        f"pipeline{suffix}",
        "test_command: pytest\n"
        "jobs:\n"
        "  - name: lint\n"
        "    test_timeout: 60  # test_timeout bounds the job\n",
    )
    naming = write_file(project, f"other{suffix}", "# Set test_command first.\nname: lint\n")
    checkout = _Checkout(project)

    assert _pointers(checkout, [using]) == []
    assert _dangling(checkout, _pointers(checkout, [naming])) == [
        f"other{suffix}:1: test_command: " + _named_without_its_path(["tests/unit/test_pipeline.py::test_command"])
    ]


def test_a_yaml_file_may_use_test_prefixed_keys_of_its_own_in_any_document_under_any_tag(project: Path) -> None:
    write_file(project, "tests/unit/test_pipeline.py", "def test_command(): pass\ndef test_timeout(): pass\n")
    using = write_file(project, "pipeline.yaml", "test_command: pytest\n---\njob: !job\n  test_timeout: 60\n")
    checkout = _Checkout(project)

    assert _pointers(checkout, [using]) == []


@pytest.mark.parametrize(
    ("source", "text"),
    [
        ("src/pkg/app.py", "def build(test_config:\n"),
        ("pipeline.yaml", "test_command: [pytest\n"),
        ("tests/unit/test_unparsed.py", "def test_x(:\n"),
    ],
    ids=["python", "yaml", "python-under-tests"],
)
def test_reports_a_python_or_yaml_file_that_does_not_parse_by_its_path(project: Path, source: str, text: str) -> None:
    broken = write_file(project, source, text)
    checkout = _Checkout(project)

    with pytest.raises(ValueError, match=f"^{re.escape(source)} does not parse"):
        _pointers(checkout, [broken])
