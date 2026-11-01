# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every pointer into tests/ from a scanned file resolves, and names a test only by its node-id.

The scanned files are those git lists outside the _UNSCANNED directories, which hold the tests themselves and records
that name tests as they were when written, such as the PRDs and research notes under docs/.

A pointer is written from the project root: a path rooted at tests/, optionally followed by the ::<Class> and ::<test>
names of a pytest node-id, as in tests/<file>.py::<Class>::<test>. It is looked for anywhere in a file's text, comments,
docstrings and code alike. A file that is not UTF-8 text holds none. The path is looked up in the files git lists, as a
fresh clone would hold them, so a file git ignores is not there to point at. Its names are looked up in the syntax tree
of the Python file there, so a pointer naming a test in a Python file that is not UTF-8 text, or that does not parse, is
reported. A path in another repository is written from that repository's name, as in reify/tests/infra/run_all.sh, so
it is not rooted at tests/. A path not rooted at tests/ that ends a test file tests/ holds, as test_<name>.py or
<dir>/test_<name>.py, is refused, naming the path to write. One that ends no file of tests/ names another tree's or a
throwaway project's file, so it is no pointer.

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
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

import pytest
import yaml

from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import WorkingTreePaths, working_tree_paths

_TESTS = PurePosixPath("tests")

_UNSCANNED = (_TESTS, *RECORD_DIRECTORIES)

_POINTER = re.compile(
    r"""
    (?<![\w./-])
    (?:
        (?:
            (?P<path>tests/(?:[\w.-]+/)*[\w.-]*\w)
          | (?P<relative>(?:[\w.-]+/)*test_\w+\.py(?!\w))
        )
        (?P<names>(?:::\w+)*)(?P<dotted_names>(?:\.\w+)*)
      | (?<!def\ )(?<!class\ )(?P<bare>test_\w+|Test[A-Z]\w*)
    )
    """,
    re.VERBOSE,
)

_OWN_NAMES_UNREADABLE = "does not parse, so the names it uses itself cannot be told from pointers"


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

    Its node-ids are those of what it names, one for each test, test class or test file tests/ holds by it, sorted.
    """

    source: PurePosixPath
    line: int
    written: str
    node_ids: tuple[str, ...]

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
            if path.suffix != ".py" or not path.is_relative_to(_TESTS):
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
    name is given alone in it.
    """
    matches = list(_POINTER.finditer(text))
    has_bare_name = any(match["bare"] is not None for match in matches)
    own_names = _own_names(checkout, source, text) if has_bare_name else frozenset()
    found = (_pointer(checkout, source, text.count("\n", 0, match.start()) + 1, match, own_names) for match in matches)
    return [pointer for pointer in found if pointer is not None]


def _pointer(
    checkout: _Checkout, source: PurePosixPath, line: int, match: re.Match[str], own_names: frozenset[str]
) -> _Pointer | _UnrootedPointer | None:
    """Return the pointer *match* gives on *line* of the file *source* in the *checkout*, or None if it gives none.

    A path not rooted at tests/ gives one only if it ends a file of tests/. A test-like name given alone gives one only
    if it is not among *own_names*, those the file uses itself, and tests/ holds a test, test class or test file by it.
    """
    if match["bare"] is not None:
        name = match["bare"]
        node_ids = () if name in own_names else checkout.node_ids_named(name)
        return _UnrootedPointer(source=source, line=line, written=name, node_ids=node_ids) if node_ids else None
    names = tuple(match["names"].split("::")[1:])
    dotted_names = tuple(match["dotted_names"].split(".")[1:])
    if match["path"] is not None:
        return _Pointer(
            source=source, line=line, path=PurePosixPath(match["path"]), names=names, dotted_names=dotted_names
        )
    files = checkout.test_files_ending(PurePosixPath(match["relative"]))
    node_ids = tuple("::".join((str(file), *names, *dotted_names)) for file in files)
    return _UnrootedPointer(source=source, line=line, written=match[0], node_ids=node_ids) if node_ids else None


def _own_names(checkout: _Checkout, source: PurePosixPath, text: str) -> frozenset[str]:
    """Return the names the file *source* in the *checkout*, whose text is *text*, uses itself.

    They are a Python module's identifiers or a YAML file's mapping keys. A file of any other kind uses none. A Python or
    YAML file that does not parse raises ValueError, naming the file.
    """
    match source.suffix:
        case ".py":
            module = checkout.syntax_tree(source)
            if isinstance(module, _NoSyntaxTree):
                raise ValueError(f"{source} {_OWN_NAMES_UNREADABLE}")
            return _code_names(module)
        case ".yaml" | ".yml":
            try:
                return _yaml_keys(text)
            except yaml.YAMLError as error:
                raise ValueError(f"{source} {_OWN_NAMES_UNREADABLE}: {error}") from error
        case _:
            return frozenset()


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


def test_every_pointer_from_the_scanned_files_into_tests_resolves(project_root: Path) -> None:
    checkout = _Checkout(project_root)
    pointers = _pointers(checkout, scanned_files(project_root, _UNSCANNED))
    unscanned = ", ".join(f"{directory}/" for directory in _UNSCANNED)
    assert pointers, (
        f"found no pointer into tests/ in any file git lists outside the unscanned directories ({unscanned}), so this"
        " gate would pass vacuously; fix the listing or the grammar"
    )

    dangling = _dangling(checkout, pointers)

    assert dangling == [], "\n".join(
        [
            *dangling,
            "A renamed or moved test's pointers must follow it. Point at a test by its node-id from the project root,"
            " tests/<file>.py::<test> or tests/<file>.py::<Class>::<test>, which this gate resolves and pytest runs"
            " as written.",
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


def test_scans_every_file_git_lists_outside_the_unscanned_directories(project: Path) -> None:
    scanned = {
        "CLAUDE.md",
        "docs/guide.md",
        "pyproject.toml",
        "scenarios/fleet.yaml",
        "scripts/measure.py",
        "src/pkg/module.py",
    }
    unscanned = ["docs/prds/record.md", "docs/research/survey.md", "plans/plan.md", "review/briefing.yaml"]
    for source in [*scanned, *unscanned]:
        write_file(project, source, "")

    assert set(scanned_files(project, _UNSCANNED)) == {PurePosixPath(source) for source in scanned}


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
        "# tests/unit/test_latin1.py names no test\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_latin1.py::test_top:"
        " tests/unit/test_latin1.py is not UTF-8 text, so it defines no test_top",
        "src/pkg/module.py:2: tests/unit/test_latin1.py::TestGroup::test_member:"
        " tests/unit/test_latin1.py is not UTF-8 text, so it defines no TestGroup",
    ]


def test_reports_each_pointer_into_a_python_file_that_does_not_parse(project: Path) -> None:
    write_file(project, "tests/unit/test_broken.py", "def test_top(): pass\ndef test_broken(:\n")
    source = write_file(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_broken.py::test_top\n"
        "# tests/unit/test_broken.py::TestGroup::test_member\n"
        "# tests/unit/test_broken.py names no test\n",
    )
    checkout = _Checkout(project)

    assert _dangling(checkout, _pointers(checkout, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_broken.py::test_top:"
        " tests/unit/test_broken.py does not parse, so it defines no test_top",
        "src/pkg/module.py:2: tests/unit/test_broken.py::TestGroup::test_member:"
        " tests/unit/test_broken.py does not parse, so it defines no TestGroup",
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
        " nor does a throwaway test_gamma.py.\n",
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
    [("src/pkg/app.py", "def build(test_config:\n"), ("pipeline.yaml", "test_command: [pytest\n")],
    ids=["python", "yaml"],
)
def test_reports_a_python_or_yaml_file_that_does_not_parse_by_its_path(project: Path, source: str, text: str) -> None:
    broken = write_file(project, source, text)
    checkout = _Checkout(project)

    with pytest.raises(ValueError, match=f"^{re.escape(source)} does not parse"):
        _pointers(checkout, [broken])
