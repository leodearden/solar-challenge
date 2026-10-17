# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import-structure contract test (INV-5).

No module of solar_challenge imports another of its modules inside a function, except
the (importing module, imported module) pairs ALLOWED_FUNCTION_LOCAL_IMPORTS lists.
Each pair carries a Permanent reason, the documented contract that requires the
laziness, or a Transitional one, the task or program stream that removes the import.
The check runs both ways, so the change that removes a pair's last such import deletes
its entry. docs/prds/errors-leaf.md §7 measured and classified the list.
"""

import ast
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

_PACKAGE = "solar_challenge"


def _write_package(src_dir: Path, modules: dict[str, str]) -> Path:
    """Write each of *modules*, keyed by its path in the package, under src_dir/solar_challenge, and return *src_dir*."""
    for relative_path, source in modules.items():
        module = src_dir / _PACKAGE / relative_path
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(source, encoding="utf-8")
    return src_dir


def test_a_function_local_package_import_is_reported_with_its_file_line_and_module(
    tmp_path: Path,
) -> None:
    """The report names a seeded function-local import's file, line and module: the real-tree tests pass for a scan that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "__init__.py": "",
            "gridservices.py": (
                "import json\n"
                "\n"
                "\n"
                "def refuse(path):\n"
                "    from solar_challenge.config import load_scenarios\n"
                "    return load_scenarios(path)\n"
            ),
        },
    )

    unlisted = _unlisted(_function_local_package_imports(src_dir), frozenset())

    assert [(site.path.as_posix(), site.line, site.imported) for site in unlisted] == [
        ("src/solar_challenge/gridservices.py", 5, "solar_challenge.config")
    ]
    assert "src/solar_challenge/gridservices.py:5" in str(unlisted[0])
    assert "solar_challenge.config" in str(unlisted[0])


def test_an_allowed_pair_no_function_imports_is_reported_stale(tmp_path: Path) -> None:
    """A pair no function imports any more is reported stale: the real-tree tests pass for a report that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "finance.py": (
                "from solar_challenge.battery import compute_soh\n"
                "\n"
                "\n"
                "def aged(homes):\n"
                "    return compute_soh(homes)\n"
            ),
        },
    )
    pair = ("solar_challenge.finance", "solar_challenge.battery")

    assert _stale(_function_local_package_imports(src_dir), {pair}) == [pair]


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "finance.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "from solar_challenge.battery import compute_soh\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.home import HomeConfig\n",
            [],
            id="module-top",
        ),
        pytest.param(
            "finance.py",
            "def f():\n    import json\n    import solar_challenge_tools\n",
            [],
            id="not-the-package",
        ),
        pytest.param(
            "finance.py",
            "class C:\n    async def f(self):\n        def g():\n            import solar_challenge.ev\n",
            [("solar_challenge.finance", "solar_challenge.ev", 4)],
            id="nested-in-a-method",
        ),
        pytest.param(
            "web/routes.py",
            "def f():\n    from .charts import x\n    from .. import fleet\n",
            [
                ("solar_challenge.web.routes", "solar_challenge.web.charts", 2),
                ("solar_challenge.web.routes", "solar_challenge.fleet", 3),
            ],
            id="relative",
        ),
        pytest.param(
            "web/__init__.py",
            "def create():\n    from .app import create_app\n    return create_app()\n",
            [("solar_challenge.web", "solar_challenge.web.app", 2)],
            id="relative-in-package-init",
        ),
    ],
)
def test_the_scan_finds_only_package_imports_nested_in_a_function(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, str, int]]
) -> None:
    """The scan finds an import of the package only inside a function or method, and resolves a relative one."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _function_local_package_imports(src_dir)

    assert [(site.importer, site.imported, site.line) for site in found] == expected
