# SPDX-License-Identifier: AGPL-3.0-or-later
"""In src/solar_challenge only load.py's RNG hand-off calls a module-level function of random or numpy.random, a seed, state or draw function alike; constructing an explicit generator, and drawing from it, is free anywhere (docs/prds/rng-hand-off.md §5 C6)."""

import ast
import inspect
import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "solar_challenge"


# The modules whose module-level functions draw from, seed or set the state of a generator the
# whole process shares.
_PROCESS_GENERATOR_MODULES = {"random": random, "numpy.random": np.random}


@dataclass(frozen=True)
class _GlobalRngCall:
    """One call of a module-level function of random or numpy.random.

    Its file, relative to the scanned root; the def and class names it sits in, dotted, or
    "<module>"; the function's qualified name; and the call's line.
    """

    path: str
    function: str
    name: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}, in {self.function}, calls {self.name}"


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """The qualified name each name an import in tree binds stands for: `import numpy as np` binds np to numpy, `from random import seed` binds seed to random.seed."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is None:
                    top_level = alias.name.partition(".")[0]
                    names[top_level] = top_level
                else:
                    names[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _qualified_name(expression: ast.expr, imported: dict[str, str]) -> str | None:
    """The dotted name expression spells from a name an import binds, or None if it spells none."""
    attributes: list[str] = []
    while isinstance(expression, ast.Attribute):
        attributes.append(expression.attr)
        expression = expression.value
    if not isinstance(expression, ast.Name) or expression.id not in imported:
        return None
    return ".".join([imported[expression.id], *reversed(attributes)])


def _is_process_generator_function(name: str) -> bool:
    """Whether name is a module-level function of random or numpy.random; a class there, or numpy.random.default_rng, constructs an explicit generator instead."""
    module_name, _, attribute = name.rpartition(".")
    module = _PROCESS_GENERATOR_MODULES.get(module_name)
    if module is None or name == "numpy.random.default_rng":
        return False
    return not inspect.isclass(getattr(module, attribute, None))


def _calls_in_scopes(
    node: ast.AST, scope: tuple[str, ...] = ()
) -> Iterator[tuple[ast.Call, tuple[str, ...]]]:
    """Yield each call under node with the names of the defs and classes it sits in."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child, scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _calls_in_scopes(child, (*scope, child.name))
        else:
            yield from _calls_in_scopes(child, scope)


def _global_rng_calls(root: Path) -> list[_GlobalRngCall]:
    """Every call of a module-level function of random or numpy.random in the Python files under root, in path then line order."""
    found: list[_GlobalRngCall] = []
    for source in sorted(root.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imported = _imported_names(tree)
        for call, scope in _calls_in_scopes(tree):
            name = _qualified_name(call.func, imported)
            if name is not None and _is_process_generator_function(name):
                found.append(
                    _GlobalRngCall(
                        source.relative_to(root).as_posix(),
                        ".".join(scope) or "<module>",
                        name,
                        call.lineno,
                    )
                )
    return sorted(found, key=lambda call: (call.path, call.line))


def test_only_the_rng_hand_off_calls_a_module_level_function_of_random_or_numpy_random() -> None:
    calls = _global_rng_calls(_PACKAGE_DIR)

    sites = "\n".join(str(call) for call in calls)
    assert {(call.path, call.function) for call in calls} == {("load.py", "_rng_hand_off")}, (
        "only load.py's RNG hand-off may seed, set or draw from the generators of random and "
        f"numpy.random the whole process shares, and these calls do:\n{sites}\n"
        "Draw from an explicit generator elsewhere: random.Random(seed) or "
        "numpy.random.default_rng(seed)"
    )


def test_a_call_of_a_module_level_random_function_is_reported_by_file_function_and_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "seeded.py").write_text(
        "import random\n"
        "import numpy as np\n"
        "\n"
        "\n"
        "def draw():\n"
        "    random.seed(1)\n"
        "    return np.random.rand()\n"
    )

    assert _global_rng_calls(tmp_path) == [
        _GlobalRngCall("seeded.py", "draw", "random.seed", 6),
        _GlobalRngCall("seeded.py", "draw", "numpy.random.rand", 7),
    ]


@pytest.mark.parametrize(
    ("source", "name"),
    [
        pytest.param("from random import seed\nseed(1)\n", "random.seed", id="from-random-import"),
        pytest.param(
            "import numpy.random as npr\nnpr.rand()\n", "numpy.random.rand", id="import-as"
        ),
        pytest.param(
            "from numpy import random\nrandom.rand()\n", "numpy.random.rand", id="from-numpy-import"
        ),
        pytest.param(
            "import numpy.random\nnumpy.random.rand()\n", "numpy.random.rand", id="import-dotted"
        ),
    ],
)
def test_a_call_is_reported_by_the_qualified_name_its_import_spells(
    tmp_path: Path, source: str, name: str
) -> None:
    (tmp_path / "spelled.py").write_text(source)

    assert _global_rng_calls(tmp_path) == [_GlobalRngCall("spelled.py", "<module>", name, 2)]


def test_constructing_and_drawing_from_an_explicit_generator_is_not_reported(
    tmp_path: Path,
) -> None:
    (tmp_path / "explicit.py").write_text(
        "import random\n"
        "import numpy as np\n"
        "\n"
        "random.Random(1).random()\n"
        "np.random.default_rng(1).random()\n"
        "np.random.SeedSequence(1)\n"
        "np.random.Generator(np.random.PCG64(1))\n"
    )

    assert _global_rng_calls(tmp_path) == []
