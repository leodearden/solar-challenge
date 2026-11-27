# SPDX-License-Identifier: AGPL-3.0-or-later
"""optimize, cli and web name their knobs only through scenario_knobs: docs/prds/sweep-knob-registry.md §4.3 K1 and K4, and §5 row I2."""

import ast
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from solar_challenge.scenario_knobs import is_knob_name
from tests._repository_paths import REPOSITORY_ROOT

_PACKAGE_DIR = REPOSITORY_ROOT / "src" / "solar_challenge"
_ENTRY_MODULES = ("optimize.py", "cli/**/*.py", "web/**/*.py")
_RETIRED_NAMES = ("apply_knob", "_apply_install", "_SWEEP_PARAMETER_HOME_KEYS", "_SENSITIVITY_ALIAS_MAP")


class _Rule(Enum):
    """A rule of the knob vocabulary, its value the invariant's text."""

    KNOB_TABLE = "optimize, cli and web define no knob-name table"
    KNOB_CONSTRUCTED = "optimize, cli and web define no knob edit"
    RETIRED_NAME = "the retired knob vocabulary stays retired"


@dataclass(frozen=True)
class _Violation:
    """A line of a scanned tree that breaks a rule, its path relative to the tree's root."""

    path: str
    line: int
    rule: _Rule

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule.value}"


def _sources(package_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    """The files under *package_dir* that *patterns* match, in path order, none installed by npm."""
    matched = {path for pattern in patterns for path in package_dir.glob(pattern)}
    return sorted(path for path in matched if "node_modules" not in path.relative_to(package_dir).parts)


def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _callee_name(call: ast.Call) -> str | None:
    """The name *call* calls: a bare name, or the attribute of a dotted one."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _string(node: ast.expr) -> str | None:
    """The text of *node*, a str constant, else None."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _names_a_knob(text: str | None) -> bool:
    return text is not None and is_knob_name(text)


def _is_edit(value: ast.expr, defined_functions: frozenset[str]) -> bool:
    """Whether *value* is a scenario edit: a lambda, a partial or a Knob, an attribute, or a function the module defines."""
    if isinstance(value, (ast.Lambda, ast.Attribute)):
        return True
    if isinstance(value, ast.Call):
        return _callee_name(value) in ("partial", "Knob")
    return isinstance(value, ast.Name) and value.id in defined_functions


def _dict_entries(node: ast.AST) -> Iterator[tuple[str | None, int, ast.expr]]:
    """Each entry of *node*, a dict display or a dict(...) call, as its key's text (None for a key not written as a string), the key's line and its value."""
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is not None:
                yield _string(key), key.lineno, value
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        for keyword in node.keywords:
            if keyword.arg is not None:
                yield keyword.arg, keyword.lineno, keyword.value


def _knob_table_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each dict key naming a knob whose value is an edit or another knob's name."""
    defined_functions = frozenset(
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for node in ast.walk(tree):
        for key, line, value in _dict_entries(node):
            if _names_a_knob(key) and (_is_edit(value, defined_functions) or _names_a_knob(_string(value))):
                yield line


def _knob_construction_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each call of Knob."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) == "Knob":
            yield node.lineno


def _bound_names(node: ast.stmt | ast.expr | ast.alias) -> tuple[str, ...]:
    """The names *node* defines, reads or imports."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    if isinstance(node, ast.alias):
        return (node.name.rsplit(".", 1)[-1], *((node.asname,) if node.asname else ()))
    return ()


def _retired_name_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each definition, use or import of a retired name."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.stmt, ast.expr, ast.alias)) and any(
            name in _RETIRED_NAMES for name in _bound_names(node)
        ):
            yield node.lineno


_AST_SCANS: Mapping[_Rule, Callable[[ast.Module], Iterator[int]]] = {
    _Rule.KNOB_TABLE: _knob_table_lines,
    _Rule.KNOB_CONSTRUCTED: _knob_construction_lines,
    _Rule.RETIRED_NAME: _retired_name_lines,
}


def _violations(package_dir: Path, rule: _Rule) -> list[_Violation]:
    """Every line of the solar_challenge package at *package_dir* that breaks *rule*, in path and line order."""
    root = package_dir.parents[1]
    return [
        _Violation(path.relative_to(root).as_posix(), line, rule)
        for path in _sources(package_dir, _ENTRY_MODULES)
        for line in sorted(set(_AST_SCANS[rule](_parsed(path))))
    ]


@dataclass(frozen=True)
class _Seed:
    """A module written into a seeded package, at *module* under its directory, whose last line breaks a rule."""

    module: str
    text: str


_SEEDS = [
    pytest.param(
        _Rule.KNOB_TABLE,
        _Seed("cli/seeded.py", 'import typer\n\n_EDITS = {"battery_capacity_kwh": lambda scenario, value: scenario}\n'),
        id="knob_table-a-name-to-edit-dict",
    ),
    pytest.param(
        _Rule.KNOB_TABLE,
        _Seed("web/seeded.py", 'import flask\n\n_ALIASES = {"retained_floor": "retained_cash_floor_per_home_per_year_gbp"}\n'),
        id="knob_table-an-alias-table",
    ),
    pytest.param(
        _Rule.KNOB_TABLE,
        _Seed(
            "web/seeded.py",
            "def _with_pv(scenario, value):\n    return scenario\n\n\n_EDITS = dict(pv_capacity_kw=_with_pv)\n",
        ),
        id="knob_table-a-dict-call-of-a-defined-edit",
    ),
    pytest.param(
        _Rule.KNOB_CONSTRUCTED,
        _Seed(
            "optimize.py",
            "from solar_challenge.scenario_knobs import Knob, KnobTarget\n"
            "\n"
            "\n"
            "def edit(scenario, value):\n"
            "    return scenario\n"
            "\n"
            "\n"
            'PV = Knob("pv_capacity_kw", edit, target=KnobTarget.HOMES)\n',
        ),
        id="knob_constructed",
    ),
    pytest.param(
        _Rule.RETIRED_NAME,
        _Seed("optimize.py", "import itertools\n\n\ndef apply_knob(scenario, name, value): ...\n"),
        id="retired_name",
    ),
]


def _seeded_package(tmp_path: Path, seed: _Seed) -> Path:
    """The directory of a solar_challenge package under *tmp_path* holding *seed* alone."""
    package_dir = tmp_path / "src" / "solar_challenge"
    module = package_dir / seed.module
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(seed.text, encoding="utf-8")
    return package_dir


@pytest.mark.parametrize("rule", list(_Rule), ids=lambda rule: rule.name.lower())
def test_the_tree_keeps_the_rule(rule: _Rule) -> None:
    """The real package breaks none of the knob vocabulary's rules."""
    violations = _violations(_PACKAGE_DIR, rule)
    assert violations == [], "\n".join(str(violation) for violation in violations)


@pytest.mark.parametrize(("rule", "seed"), _SEEDS)
def test_a_seeded_violation_is_reported_by_its_file_and_line(tmp_path: Path, rule: _Rule, seed: _Seed) -> None:
    """A package seeded with one module breaking *rule* on its last line reports that line, and nothing else, under its path."""
    package_dir = _seeded_package(tmp_path, seed)
    expected = _Violation(f"src/solar_challenge/{seed.module}", len(seed.text.splitlines()), rule)

    violations = [violation for each_rule in _Rule for violation in _violations(package_dir, each_rule)]

    assert violations == [expected]
    assert [str(violation) for violation in violations] == [f"{expected.path}:{expected.line}: {rule.value}"]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('_BLOCK = {"seg": _read_seg(body)}\n', id="a-block-read-under-a-knob-name"),
        pytest.param('_SCHEMA = {"annual_consumption_kwh": {"type": "number"}}\n', id="a-schema-under-a-knob-name"),
        pytest.param('_LABELS = {"pv_capacity_kw": "PV capacity (kW)"}\n', id="a-label-under-a-knob-name"),
    ],
)
def test_block_data_under_a_knob_name_is_no_knob_table(tmp_path: Path, text: str) -> None:
    """A dict whose knob-named key holds data, not an edit or another knob's name, is not reported."""
    package_dir = _seeded_package(tmp_path, _Seed("web/seeded.py", text))

    assert _violations(package_dir, _Rule.KNOB_TABLE) == []


def test_the_scan_reads_each_entry_point_that_varies_a_setting_by_name() -> None:
    """The entry modules scanned include the web sweep, `fleet sweep --param` and optimize configs, so a passing real-tree scan read them."""
    scanned = {path.relative_to(_PACKAGE_DIR).as_posix() for path in _sources(_PACKAGE_DIR, _ENTRY_MODULES)}

    assert {"web/sweep_request.py", "cli/fleet.py", "optimize.py", "cli/optimize.py"} <= scanned
