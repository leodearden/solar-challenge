# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every pointer from a file git lists under src/solar_challenge into tests/ resolves, and names a test only by its node-id.

A pointer is a path rooted at tests/, optionally followed by the ::<Class> and ::<test> names of a pytest node-id, as in
tests/<file>.py::<Class>::<test>. It is looked for anywhere in a file's text, comments, docstrings and code alike. A
file that is not UTF-8 text holds none.
"""

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

_POINTER = re.compile(
    r"""
    (?<![\w./-])
    (?P<path>tests/(?:[\w.-]+/)*[\w.-]*\w)
    (?P<names>(?:::\w+)*)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Pointer:
    """A pointer into tests/: the file holding it, relative to the project root, its line, and the path and names it gives."""

    source: PurePosixPath
    line: int
    path: PurePosixPath
    names: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {'::'.join([str(self.path), *self.names])}"


def _pointers(root: Path, sources: Iterable[PurePosixPath]) -> list[_Pointer]:
    """Return every pointer in the *sources*, POSIX paths relative to *root*, file by file and in text order."""
    pointers: list[_Pointer] = []
    for source in sources:
        text = _utf8_text(root / source)
        if text is not None:
            pointers.extend(_pointers_in(source, text))
    return pointers


def _utf8_text(path: Path) -> str | None:
    """Return the text of the file at *path*, or None if it is not UTF-8."""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None


def _pointers_in(source: PurePosixPath, text: str) -> list[_Pointer]:
    """Return the pointers in *text*, the text of the file *source*, in text order."""
    return [
        _Pointer(
            source=source,
            line=text.count("\n", 0, match.start()) + 1,
            path=PurePosixPath(match["path"]),
            names=tuple(match["names"].split("::")[1:]),
        )
        for match in _POINTER.finditer(text)
    ]


def _dangling(root: Path, pointers: Iterable[_Pointer]) -> list[str]:
    """Return "<pointer>: <reason>" for each of the *pointers* that does not resolve under *root*, in their order."""
    return [f"{pointer}: {reason}" for pointer in pointers if (reason := _unresolved(root, pointer)) is not None]


def _unresolved(root: Path, pointer: _Pointer) -> str | None:
    """Return why *pointer* leads to no file, directory or test under *root*, or None if it leads to one.

    Its path must exist. Its names are read from the Python file's syntax tree, and the file is never imported.
    """
    target = root / pointer.path
    if not target.exists():
        return f"{pointer.path} does not exist"
    if not pointer.names:
        return None
    if target.suffix != ".py" or not target.is_file():
        return f"{pointer.path} is not a Python file, so it defines no {pointer.names[0]}"
    return _undefined(pointer.path, pointer.names, ast.parse(target.read_text(encoding="utf-8")))


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


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a project root whose tests/unit holds notes.txt and test_pointed_at.py, defining a test, a class and a nested class."""
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_pointed_at.py").write_text(
        "def test_top(): pass\n"
        "class TestGroup:\n"
        "    def test_member(self): pass\n"
        "    class TestNested:\n"
        "        def test_deep(self): pass\n",
        encoding="utf-8",
    )
    (tests / "notes.txt").write_text("Not Python.\n", encoding="utf-8")
    return tmp_path


def _write_source(project: Path, source: str, text: str) -> PurePosixPath:
    """Write *text* to *source*, a POSIX path relative to *project*, and return that path."""
    path = project / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return PurePosixPath(source)


def test_pointers_to_existing_files_directories_and_tests_resolve(project: Path) -> None:
    source = _write_source(
        project,
        "src/pkg/module.py",
        "# Pinned by tests/unit/test_pointed_at.py.\n"
        "# Its siblings (tests/unit) say why.\n"
        "# tests/unit/test_pointed_at.py::test_top\n"
        "# tests/unit/test_pointed_at.py::test_top[3.14]\n"
        "# tests/unit/test_pointed_at.py::TestGroup\n"
        "# tests/unit/test_pointed_at.py::TestGroup::test_member\n"
        "# tests/unit/test_pointed_at.py::TestGroup::TestNested::test_deep\n"
        "# Not rooted at tests/: src/tests/test_gone.py and https://example.org/pvlib/tests/test_gone.py\n",
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
    source = _write_source(
        project,
        "src/pkg/module.py",
        "# tests/unit/test_absent.py\n"
        "# tests/unit/test_pointed_at.py::test_member\n"
        "# tests/unit/test_pointed_at.py::TestGroup::test_absent\n"
        "# tests/unit/test_pointed_at.py::test_top::test_inner\n"
        "# tests/unit/notes.txt::test_top\n"
        "# tests/unit::test_top\n",
    )

    assert _dangling(project, _pointers(project, [source])) == [
        "src/pkg/module.py:1: tests/unit/test_absent.py: tests/unit/test_absent.py does not exist",
        "src/pkg/module.py:2: tests/unit/test_pointed_at.py::test_member:"
        " tests/unit/test_pointed_at.py defines no test_member at its top level",
        "src/pkg/module.py:3: tests/unit/test_pointed_at.py::TestGroup::test_absent: TestGroup defines no test_absent",
        "src/pkg/module.py:4: tests/unit/test_pointed_at.py::test_top::test_inner:"
        " test_top is a function, so it defines no test_inner",
        "src/pkg/module.py:5: tests/unit/notes.txt::test_top:"
        " tests/unit/notes.txt is not a Python file, so it defines no test_top",
        "src/pkg/module.py:6: tests/unit::test_top: tests/unit is not a Python file, so it defines no test_top",
    ]


def test_skips_a_file_that_is_not_utf8_text(project: Path) -> None:
    logo = project / "src" / "pkg" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG\xff\xfe tests/unit/test_absent.py")

    pointers = _pointers(project, [PurePosixPath("src/pkg/logo.png")])

    assert pointers == []
    assert _dangling(project, pointers) == []


_NAMED_WITHOUT_ITS_NODE_ID = (
    "names a test without its file: point at it by its node-id from the project root,"
    " tests/<file>.py::[<Class>::]<name>"
)


def test_reports_a_test_or_test_class_named_without_its_node_id(project: Path) -> None:
    source = _write_source(
        project,
        "src/pkg/script.js",
        "// pinned by test_top\n"
        "// TestGroup covers the rest.\n"
        "// test_member in tests/unit/test_pointed_at.py says why.\n"
        "// tests/unit/test_pointed_at.py's test_top shows it.\n"
        "// Testing it needs pytest_configure and build_test_app, then app.test_client().\n"
        "// Not a test name: src/tests/test_gone.py\n",
    )

    assert _dangling(project, _pointers(project, [source])) == [
        f"src/pkg/script.js:1: test_top: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:2: TestGroup: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:3: test_member: {_NAMED_WITHOUT_ITS_NODE_ID}",
        f"src/pkg/script.js:4: test_top: {_NAMED_WITHOUT_ITS_NODE_ID}",
    ]


def test_a_python_module_may_use_test_prefixed_identifiers_of_its_own(project: Path) -> None:
    using = _write_source(
        project,
        "src/pkg/app.py",
        "def build(test_config=None):\n"
        '    """Build the app.\n'
        "\n"
        "    test_config: overrides.\n"
        '    """\n'
        "    return test_config\n",
    )
    naming = _write_source(project, "src/pkg/other.py", "# Set test_config first.\ndef build():\n    return None\n")

    assert _pointers(project, [using]) == []
    assert _dangling(project, _pointers(project, [naming])) == [
        f"src/pkg/other.py:1: test_config: {_NAMED_WITHOUT_ITS_NODE_ID}"
    ]
