# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule every module of this package follows; the package's __init__ docstring says why."""

import ast
import importlib.util
import pathlib
from collections.abc import Iterator


def _imported_names(tree: ast.Module, package: str) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            module = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            yield module
            for alias in node.names:
                yield f"{module}.{alias.name}"


def test_no_module_of_this_package_imports_a_rule_module_of_it() -> None:
    package = __name__.rpartition(".")[0]
    directory = pathlib.Path(__file__).parent
    rule_modules = {f"{package}.{path.stem}" for path in directory.glob("test_*.py")}
    importing = [
        f"{path.name} imports {name}"
        for path in sorted(directory.glob("*.py"))
        for name in _imported_names(ast.parse(path.read_bytes()), package)
        if name in rule_modules
    ]

    assert importing == []
