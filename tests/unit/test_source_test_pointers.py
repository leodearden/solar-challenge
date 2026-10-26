# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every pointer into tests/ from a scanned file resolves, and names a test only by its node-id.

The scanned files are those git lists outside the _UNSCANNED directories, which hold the tests themselves and records
that name tests as they were when written, such as the PRDs and research notes under docs/.

A pointer is a path rooted at tests/, optionally followed by the ::<Class> and ::<test> names of a pytest node-id, as in
tests/<file>.py::<Class>::<test>. It is looked for anywhere in a file's text, comments, docstrings and code alike. A
file that is not UTF-8 text holds none. The path is looked up in the files git lists, as a fresh clone would hold them,
so a file git ignores is not there to point at. Its names are looked up in the syntax tree of the Python file there, so
a pointer naming a test in a Python file that is not UTF-8 text, or that does not parse, is reported. A path in another
repository is written from that repository's name, as in reify/tests/infra/run_all.sh, so it is not rooted at tests/.

A test function or class named any other way is refused: as test_<name> or Test<Name>, alone or next to its file in
prose, or joined to a node-id's last name with a dot, as in ::<Class>.<test>. So is a test file named by its file name
alone, as test_<name>.py. The settled form is the node-id, which pytest runs as written and this gate resolves. A name
a file uses itself is no pointer: a name the Python module's own code uses, such as a parameter called test_config, or
a key of the YAML file's own mappings, such as test_command. In any other file, such a key is written in words, as in
"the verify's test command". Nor, outside a node-id, is a name written straight after a dot, so a third-party name
that reads as a test, such as Werkzeug's TestResponse, is written after its module: werkzeug.test.TestResponse.
"""

import ast
import functools
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

import pytest
import yaml

from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text
from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import WorkingTreePaths, working_tree_paths

_UNSCANNED = (PurePosixPath("tests"), *RECORD_DIRECTORIES)

_POINTER = re.compile(
    r"""
    (?<![\w./-])
    (?:
        (?P<path>tests/(?:[\w.-]+/)*[\w.-]*\w)(?P<names>(?:::\w+)*)(?P<dotted_names>(?:\.\w+)*)
      | (?P<bare>test_\w+|Test[A-Z]\w*)
    )
    """,
    re.VERBOSE,
)

_NAMED_WITHOUT_ITS_NODE_ID = (
    "names a test or test file without its path: point at it from the project root, by its path tests/<file>.py"
    " or its node-id tests/<file>.py::[<Class>::]<name>"
)


@dataclass(frozen=True)
class _Pointer:
    """A pointer into tests/: the file holding it, relative to the project root, its line, and the path and names it gives.

    A test named without its file has no path, and its name is the one name. The dotted names follow the last name with
    a dot, as in <Class>.<test>, and a node-id has none.
    """

    source: PurePosixPath
    line: int
    path: PurePosixPath | None
    names: tuple[str, ...]
    dotted_names: tuple[str, ...]

    def __str__(self) -> str:
        parts = self.names if self.path is None else (str(self.path), *self.names)
        dotted = "".join(f".{name}" for name in self.dotted_names)
        return f"{self.source}:{self.line}: {'::'.join(parts)}{dotted}"


def _pointers(root: Path, sources: Iterable[PurePosixPath]) -> list[_Pointer]:
    """Return every pointer in the *sources*, POSIX paths relative to *root*, file by file and in text order."""
    pointers: list[_Pointer] = []
    for source in sources:
        text = utf8_text(root / source)
        if text is not None:
            pointers.extend(_pointers_in(source, text))
    return pointers


def _pointers_in(source: PurePosixPath, text: str) -> list[_Pointer]:
    """Return the pointers in *text*, the text of the file *source*, in text order.

    A test name given alone that the file uses itself, as a Python module's identifier or a YAML file's key, is not one.
    """
    matches = list(_POINTER.finditer(text))
    has_bare_name = any(match["bare"] is not None for match in matches)
    own_names = _own_names(source, text) if has_bare_name else frozenset()
    return [
        _pointer(source, text, match)
        for match in matches
        if match["bare"] is None or match["bare"] not in own_names
    ]


def _pointer(source: PurePosixPath, text: str, match: re.Match[str]) -> _Pointer:
    """Return the pointer *match* found in *text*, the text of the file *source*."""
    line = text.count("\n", 0, match.start()) + 1
    if match["bare"] is not None:
        return _Pointer(source=source, line=line, path=None, names=(match["bare"],), dotted_names=())
    return _Pointer(
        source=source,
        line=line,
        path=PurePosixPath(match["path"]),
        names=tuple(match["names"].split("::")[1:]),
        dotted_names=tuple(match["dotted_names"].split(".")[1:]),
    )


def _own_names(source: PurePosixPath, text: str) -> frozenset[str]:
    """Return the names the file *source*, whose text is *text*, uses itself.

    They are a Python module's identifiers or a YAML file's mapping keys. A file of any other kind uses none. A Python or
    YAML file that does not parse raises ValueError, naming the file.
    """
    match source.suffix:
        case ".py":
            read_names = _code_names
        case ".yaml" | ".yml":
            read_names = _yaml_keys
        case _:
            return frozenset()
    try:
        return read_names(text)
    except (SyntaxError, yaml.YAMLError) as error:
        raise ValueError(
            f"{source} does not parse, so the names it uses itself cannot be told from pointers: {error}"
        ) from error


def _code_names(text: str) -> frozenset[str]:
    """Return the names of the variables, arguments, attributes, keywords, defs and classes in the Python module *text*."""
    return frozenset(name for node in ast.walk(ast.parse(text)) if (name := _code_name(node)) is not None)


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


def _dangling(root: Path, pointers: Iterable[_Pointer]) -> list[str]:
    """Return "<pointer>: <reason>" for each of the *pointers* that does not resolve in *root*'s working tree, in their order."""
    tree = working_tree_paths(root)

    @functools.cache
    def syntax_tree_of(path: PurePosixPath) -> ast.Module | _NoSyntaxTree:
        return _syntax_tree(root / path)

    return [
        f"{pointer}: {reason}"
        for pointer in pointers
        if (reason := _unresolved(tree, syntax_tree_of, pointer)) is not None
    ]


class _NoSyntaxTree(Enum):
    """Why a Python file has no syntax tree to look the names of a pointer up in.

    A reason for a pointer gives the member's value after the file's path.
    """

    NOT_UTF8 = "is not UTF-8 text"
    DOES_NOT_PARSE = "does not parse"


def _syntax_tree(path: Path) -> ast.Module | _NoSyntaxTree:
    """Return the syntax tree of the Python file at *path*, or why it has none.

    It is parsed from the file's text as utf8_text reads it.
    """
    text = utf8_text(path)
    if text is None:
        return _NoSyntaxTree.NOT_UTF8
    try:
        return ast.parse(text)
    except SyntaxError:
        return _NoSyntaxTree.DOES_NOT_PARSE


def _unresolved(
    tree: WorkingTreePaths,
    syntax_tree_of: Callable[[PurePosixPath], ast.Module | _NoSyntaxTree],
    pointer: _Pointer,
) -> str | None:
    """Return why *pointer* leads to no file, directory or test in the working *tree*, or None if it leads to one.

    It must give a path, with its names joined by ::, and the tree must hold that path. Its names are looked up in the
    syntax tree *syntax_tree_of* gives for the Python file there, and the file is never imported.
    """
    if pointer.path is None:
        return _NAMED_WITHOUT_ITS_NODE_ID
    if pointer.dotted_names:
        node_id = "::".join((str(pointer.path), *pointer.names, *pointer.dotted_names))
        return f"a node-id joins its names with ::, so write {node_id}"
    if not tree.holds(pointer.path):
        return f"{pointer.path} does not exist, or git ignores it"
    if not pointer.names:
        return None
    if pointer.path.suffix != ".py" or pointer.path not in tree.files:
        return f"{pointer.path} is not a Python file, so it defines no {pointer.names[0]}"
    module = syntax_tree_of(pointer.path)
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


def test_every_pointer_from_the_scanned_files_into_tests_resolves(project_root: Path) -> None:
    pointers = _pointers(project_root, scanned_files(project_root, _UNSCANNED))
    unscanned = ", ".join(f"{directory}/" for directory in _UNSCANNED)
    assert pointers, (
        f"found no pointer into tests/ in any file git lists outside the unscanned directories ({unscanned}), so this"
        " gate would pass vacuously; fix the listing or the grammar"
    )

    dangling = _dangling(project_root, pointers)

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

    pointers = _pointers(project, [source])

    assert [str(pointer) for pointer in pointers] == [
        "src/pkg/module.py:1: tests/unit/test_pointed_at.py",
        "src/pkg/module.py:2: tests/unit",
        "src/pkg/module.py:3: tests/unit/test_pointed_at.py::test_top",
        "src/pkg/module.py:4: tests/unit/test_pointed_at.py::test_top",
        "src/pkg/module.py:5: tests/unit/test_pointed_at.py::TestGroup",
        "src/pkg/module.py:6: tests/unit/test_pointed_at.py::TestGroup::test_member",
        "src/pkg/module.py:7: tests/unit/test_pointed_at.py::TestGroup::TestNested::test_deep",
    ]
    assert _dangling(project, pointers) == []


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

    assert _dangling(project, _pointers(project, [source])) == [
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

    assert _dangling(project, _pointers(project, [source])) == [
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

    assert _dangling(project, _pointers(project, [source])) == [
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

    assert _dangling(project, _pointers(project, [source])) == [
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

    assert _dangling(project, _pointers(project, [source])) == [
        "src/pkg/module.py:2: tests/unit/test_marked.py::test_absent:"
        " tests/unit/test_marked.py defines no test_absent at its top level",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = write_file(project, "src/pkg/logo.png", b"\x89PNG\xff\xfe tests/unit/test_absent.py")

    pointers = _pointers(project, [logo])

    assert pointers == []
    assert _dangling(project, pointers) == []


def test_reads_the_pointers_in_a_python_source_that_starts_with_a_byte_order_mark(project: Path) -> None:
    source = write_file(
        project,
        "src/pkg/marked.py",
        "# pinned by test_top\ndef build(test_config=None):\n    return test_config\n".encode("utf-8-sig"),
    )

    assert _dangling(project, _pointers(project, [source])) == [
        f"src/pkg/marked.py:1: test_top: {_NAMED_WITHOUT_ITS_NODE_ID}"
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
        "// test_pointed_at.py holds them.\n",
    )

    assert _dangling(project, _pointers(project, [source])) == [
        f"src/pkg/script.js:1: test_top: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:2: TestGroup: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:3: test_member: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:4: test_top: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:8: test_pointed_at: {_NAMED_WITHOUT_ITS_NODE_ID}",
    ]


def test_a_python_module_may_use_test_prefixed_identifiers_of_its_own(project: Path) -> None:
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

    assert _pointers(project, [using]) == []
    assert _dangling(project, _pointers(project, [naming])) == [
        f"src/pkg/other.py:1: test_config: {_NAMED_WITHOUT_ITS_NODE_ID}"
    ]


@pytest.mark.parametrize("suffix", [".yaml", ".yml"])
def test_a_yaml_file_may_use_test_prefixed_keys_of_its_own(project: Path, suffix: str) -> None:
    using = write_file(
        project,
        f"pipeline{suffix}",
        "test_command: pytest\n"
        "jobs:\n"
        "  - name: lint\n"
        "    test_timeout: 60  # test_timeout bounds the job\n",
    )
    naming = write_file(project, f"other{suffix}", "# Set test_command first.\nname: lint\n")

    assert _pointers(project, [using]) == []
    assert _dangling(project, _pointers(project, [naming])) == [
        f"other{suffix}:1: test_command: {_NAMED_WITHOUT_ITS_NODE_ID}"
    ]


def test_a_yaml_file_may_use_test_prefixed_keys_of_its_own_in_any_document_under_any_tag(project: Path) -> None:
    using = write_file(project, "pipeline.yaml", "test_command: pytest\n---\njob: !job\n  test_timeout: 60\n")

    assert _pointers(project, [using]) == []


@pytest.mark.parametrize(
    ("source", "text"),
    [("src/pkg/app.py", "def build(test_config:\n"), ("pipeline.yaml", "test_command: [pytest\n")],
    ids=["python", "yaml"],
)
def test_reports_a_python_or_yaml_file_that_does_not_parse_by_its_path(project: Path, source: str, text: str) -> None:
    broken = write_file(project, source, text)

    with pytest.raises(ValueError, match=f"^{re.escape(source)} does not parse"):
        _pointers(project, [broken])
