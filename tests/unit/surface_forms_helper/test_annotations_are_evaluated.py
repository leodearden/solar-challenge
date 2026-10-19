# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule every module of this package follows; the package's __init__ docstring says why."""

import ast
import pathlib


def test_no_module_of_this_package_imports_annotations_from_future() -> None:
    importing = [
        path.name
        for path in sorted(pathlib.Path(__file__).parent.glob("*.py"))
        for statement in ast.parse(path.read_bytes()).body
        if isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and any(alias.name == "annotations" for alias in statement.names)
    ]

    assert importing == []
