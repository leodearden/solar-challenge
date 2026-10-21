# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every pointer from a file git lists under src/solar_challenge into tests/ resolves, and names a test only by its node-id."""

from pathlib import Path, PurePosixPath

import pytest


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
