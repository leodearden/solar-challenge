# SPDX-License-Identifier: AGPL-3.0-or-later
"""optimize, cli and web name their knobs only through scenario_knobs, and sweep values come only from SweepSpec: docs/prds/sweep-knob-registry.md §4.3 K1 and K4, and §5 row I2."""

import ast
import dataclasses
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from solar_challenge.fleet_distribution import SweepMode
from solar_challenge.scenario_knobs import Knob, is_knob_name
from tests._repository_paths import REPOSITORY_ROOT

_PACKAGE_DIR = REPOSITORY_ROOT / "src" / "solar_challenge"
_ENTRY_MODULES = ("optimize.py", "cli/**/*.py", "web/**/*.py")
_RETIRED_NAMES = ("apply_knob", "_apply_install", "_SWEEP_PARAMETER_HOME_KEYS", "_SENSITIVITY_ALIAS_MAP")
_KNOB_EDIT = "apply"
_MATHS_MODULES = ("math", "numpy")
_LOG_EXP = frozenset({"log", "log2", "log10", "log1p", "exp", "exp2", "expm1", "logspace", "geomspace"})
_JS_LOG_EXP = re.compile(r"\bMath\.(log|exp)\w*")
_PARAMETER_SWEEP_JS = "web/static/js/parameter-sweep.js"
_MODES = tuple(mode.value for mode in SweepMode)
_MODE_MEMBERS = " or ".join(f"{SweepMode.__name__}.{mode.name}.value" for mode in SweepMode)
_QUOTED_MODE = re.compile(r"""(['"`])(""" + "|".join(re.escape(mode) for mode in _MODES) + r")\1")
_SWEEP_MODE_MODULE = SweepMode.__module__.removeprefix("solar_challenge.").replace(".", "/") + ".py"


class _Rule(Enum):
    """A rule of the knob vocabulary, its value the invariant's text."""

    KNOB_TABLE = (
        "optimize, cli and web map no knob's name to an edit or to another knob's name,"
        " in a dict or in a tuple, list or set of pairs"
    )
    KNOB_BRANCH = (
        "optimize, cli and web compare nothing with a knob's name written as a string:"
        " a branch on a knob compares the Knob that knob_named resolves"
    )
    KNOB_CONSTRUCTED = "optimize, cli and web define no knob edit"
    RETIRED_NAME = "the retired knob vocabulary stays retired"
    WEB_LOG_EXP = f"web/ calls no log, exp, logspace or geomspace of {' or '.join(_MATHS_MODULES)}"
    JS_LOG_EXP = "parameter-sweep.js computes no log or exp"
    MODE_LITERAL = (
        f"no module restates a sweep mode: {' and '.join(map(repr, _MODES))} are {SweepMode.__name__}'s,"
        f" so a sweep writes {_MODE_MEMBERS}; the scan reads every quoted {' or '.join(map(repr, _MODES))}"
        " in the package, so one that names no sweep mode, such as a pandas method or a Plotly axis type,"
        f" trips it too and calls for narrowing this scan, not for {SweepMode.__name__}"
    )


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
    """Whether *value* is a scenario edit: a lambda, a partial, a Knob or a Knob's edit, or a function the module defines."""
    if isinstance(value, ast.Lambda):
        return True
    if isinstance(value, ast.Attribute):
        return value.attr == _KNOB_EDIT
    if isinstance(value, ast.Call):
        return _callee_name(value) in ("partial", "Knob")
    return isinstance(value, ast.Name) and value.id in defined_functions


def _table_entries(node: ast.AST) -> Iterator[tuple[str | None, int, ast.expr]]:
    """Each entry of *node*, a dict display, a dict(...) call or a tuple, list or set of pairs, as its key's text (None for a key not written as a string), the key's line and its value."""
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is not None:
                yield _string(key), key.lineno, value
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        for keyword in node.keywords:
            if keyword.arg is not None:
                yield keyword.arg, keyword.lineno, keyword.value
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for pair in node.elts:
            if isinstance(pair, (ast.Tuple, ast.List)) and len(pair.elts) == 2:
                key, value = pair.elts
                yield _string(key), key.lineno, value


def _knob_table_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each table key naming a knob whose value is an edit or another knob's name."""
    defined_functions = frozenset(
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for node in ast.walk(tree):
        for key, line, value in _table_entries(node):
            if _names_a_knob(key) and (_is_edit(value, defined_functions) or _names_a_knob(_string(value))):
                yield line


def _holds_a_knob_name(operand: ast.expr) -> bool:
    """Whether *operand* is a knob's name written as a string, or a tuple, list or set display holding one."""
    if isinstance(operand, (ast.Tuple, ast.List, ast.Set)):
        return any(_names_a_knob(_string(element)) for element in operand.elts)
    return _names_a_knob(_string(operand))


def _knob_branch_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each comparison, and of each match case, of a value with a knob's name written as a string."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(map(_holds_a_knob_name, (node.left, *node.comparators))):
            yield node.lineno
        elif isinstance(node, ast.MatchValue) and _holds_a_knob_name(node.value):
            yield node.lineno


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


def _log_exp_lines(tree: ast.Module) -> Iterator[int]:
    """The line of each use of a log or exp function of math or numpy through a name bound to its module, and of each import of one from its module."""
    module_names = frozenset(
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in _MATHS_MODULES
    )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _LOG_EXP
            and isinstance(node.value, ast.Name)
            and node.value.id in module_names
        ):
            yield node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module in _MATHS_MODULES:
            yield from (alias.lineno for alias in node.names if alias.name in _LOG_EXP)


def _sweep_mode_lines(module: str, tree: ast.Module) -> range:
    """The lines of SweepMode's class, which *tree*, the module at *module*, holds when it is SweepMode's own module."""
    for node in tree.body:
        if module == _SWEEP_MODE_MODULE and isinstance(node, ast.ClassDef) and node.name == SweepMode.__name__:
            return range(node.lineno, (node.end_lineno or node.lineno) + 1)
    return range(0)


_Lines = Callable[[str, str], Iterator[int]]
"""The lines of a file that break a rule, given the file's path under the package directory and its text."""


def _mode_literal_lines(module: str, text: str) -> Iterator[int]:
    """The line of each str constant equal to a sweep mode's value, outside SweepMode's class."""
    tree = ast.parse(text, filename=module)
    owner = _sweep_mode_lines(module, tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in _MODES and node.lineno not in owner:
            yield node.lineno


def _parsed_lines(scan: Callable[[ast.Module], Iterator[int]]) -> _Lines:
    """The _Lines that run *scan* over a Python file's syntax tree."""

    def lines(module: str, text: str) -> Iterator[int]:
        return scan(ast.parse(text, filename=module))

    return lines


def _matching_lines(pattern: re.Pattern[str]) -> _Lines:
    """The _Lines numbering each line of a file that *pattern* matches."""

    def lines(module: str, text: str) -> Iterator[int]:
        return (number for number, line in enumerate(text.splitlines(), start=1) if pattern.search(line))

    return lines


@dataclass(frozen=True)
class _Scan:
    """A scan of a rule: the files under the package directory it reads, as glob patterns, and the lines of each that break the rule."""

    files: tuple[str, ...]
    lines: _Lines


_SCANS: Mapping[_Rule, tuple[_Scan, ...]] = {
    _Rule.KNOB_TABLE: (_Scan(_ENTRY_MODULES, _parsed_lines(_knob_table_lines)),),
    _Rule.KNOB_BRANCH: (_Scan(_ENTRY_MODULES, _parsed_lines(_knob_branch_lines)),),
    _Rule.KNOB_CONSTRUCTED: (_Scan(_ENTRY_MODULES, _parsed_lines(_knob_construction_lines)),),
    _Rule.RETIRED_NAME: (_Scan(_ENTRY_MODULES, _parsed_lines(_retired_name_lines)),),
    _Rule.WEB_LOG_EXP: (_Scan(("web/**/*.py",), _parsed_lines(_log_exp_lines)),),
    _Rule.JS_LOG_EXP: (_Scan((_PARAMETER_SWEEP_JS,), _matching_lines(_JS_LOG_EXP)),),
    _Rule.MODE_LITERAL: (
        _Scan(("**/*.py",), _mode_literal_lines),
        _Scan(("web/templates/**/*.html", "web/static/js/**/*.js"), _matching_lines(_QUOTED_MODE)),
    ),
}


def _violations(package_dir: Path, rule: _Rule) -> list[_Violation]:
    """Every line of the solar_challenge package at *package_dir* that breaks *rule*, in path and line order."""
    root = package_dir.parents[1]
    sites = {
        (path, line)
        for scan in _SCANS[rule]
        for path in _sources(package_dir, scan.files)
        for line in scan.lines(path.relative_to(package_dir).as_posix(), path.read_text(encoding="utf-8"))
    }
    return [_Violation(path.relative_to(root).as_posix(), line, rule) for path, line in sorted(sites)]


@dataclass(frozen=True)
class _Seed:
    """A module written into a seeded package, at *module* under its directory, whose last line breaks a rule."""

    module: str
    text: str


def _with_line_appended(text: str, line: str) -> str:
    """*text* with *line* as its last line."""
    return text.rstrip("\n") + "\n" + line + "\n"


_PARAMETER_SWEEP_JS_TEXT = (_PACKAGE_DIR / _PARAMETER_SWEEP_JS).read_text(encoding="utf-8")

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
        _Rule.KNOB_TABLE,
        _Seed(
            "web/seeded.py",
            "from solar_challenge.scenario_knobs import KNOBS\n"
            "\n"
            '_EDITS = {"battery_capacity_kwh": KNOBS["pv_capacity_kw"].apply}\n',
        ),
        id="knob_table-another-knobs-edit",
    ),
    pytest.param(
        _Rule.KNOB_TABLE,
        _Seed("cli/seeded.py", 'import typer\n\n_EDITS = (("battery_capacity_kwh", lambda scenario, value: scenario),)\n'),
        id="knob_table-a-tuple-of-pairs",
    ),
    pytest.param(
        _Rule.KNOB_BRANCH,
        _Seed("web/seeded.py", 'import flask\n\nis_battery = parameter == "battery_capacity_kwh"\n'),
        id="knob_branch-an-equality",
    ),
    pytest.param(
        _Rule.KNOB_BRANCH,
        _Seed("optimize.py", 'import itertools\n\nis_seg = name in ("seg", "seg_tariff_pence_per_kwh")\n'),
        id="knob_branch-a-membership",
    ),
    pytest.param(
        _Rule.KNOB_BRANCH,
        _Seed("cli/seeded.py", 'def point(parameter):\n    match parameter:\n        case "seg": ...\n'),
        id="knob_branch-a-match-case",
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
    pytest.param(
        _Rule.WEB_LOG_EXP,
        _Seed("web/seeded.py", "import math\n\npoints = [math.exp(x) for x in xs]\n"),
        id="web_log_exp-math",
    ),
    pytest.param(
        _Rule.WEB_LOG_EXP,
        _Seed("web/seeded.py", "import numpy as np\n\npoints = np.geomspace(low, high, steps)\n"),
        id="web_log_exp-numpy",
    ),
    pytest.param(
        _Rule.JS_LOG_EXP,
        _Seed(_PARAMETER_SWEEP_JS, _with_line_appended(_PARAMETER_SWEEP_JS_TEXT, "const ratio = Math.log(maxVal / minVal);")),
        id="js_log_exp-a-copy-of-parameter-sweep-js",
    ),
    pytest.param(
        _Rule.MODE_LITERAL,
        _Seed("web/seeded.py", 'import flask\n\nmode = body.get("mode", "linear")\n'),
        id="mode_literal-python",
    ),
    pytest.param(
        _Rule.MODE_LITERAL,
        _Seed(_PARAMETER_SWEEP_JS, _with_line_appended(_PARAMETER_SWEEP_JS_TEXT, "mode: 'geometric',")),
        id="mode_literal-a-copy-of-parameter-sweep-js",
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
        pytest.param('_BLOCK = {"seg": fields.seg}\n', id="an-attribute-read-under-a-knob-name"),
        pytest.param(
            '_LOAD = {"annual_consumption_kwh": home.load_config.annual_consumption_kwh}\n',
            id="a-nested-attribute-read-under-a-knob-name",
        ),
        pytest.param('_NAMES = ("retained_floor", "grid_services")\n', id="a-sequence-of-knob-names"),
    ],
)
def test_block_data_under_a_knob_name_is_no_knob_table(tmp_path: Path, text: str) -> None:
    """A table whose knob-named key holds data, not an edit or another knob's name, and a sequence of knob names, are not reported."""
    package_dir = _seeded_package(tmp_path, _Seed("web/seeded.py", text))

    assert _violations(package_dir, _Rule.KNOB_TABLE) == []


def test_a_knobs_edit_is_read_off_the_field_a_knob_carries_it_in() -> None:
    """The attribute the table scan counts as an edit is the field of Knob that holds its edit."""
    assert _KNOB_EDIT in {field.name for field in dataclasses.fields(Knob)}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            '_FLAT_RATE = KNOBS["grid_services_income_per_kw_per_year_gbp"]\n\nis_flat = knob == _FLAT_RATE\n',
            id="a-knob-compared-with-a-knob",
        ),
        pytest.param('is_fleet = page == "fleet"\n', id="a-comparison-with-another-string"),
    ],
)
def test_a_comparison_with_no_knobs_name_is_no_knob_branch(tmp_path: Path, text: str) -> None:
    """A comparison of Knob values, and one with a string that names no knob, are not reported."""
    package_dir = _seeded_package(tmp_path, _Seed("web/seeded.py", text))

    assert _violations(package_dir, _Rule.KNOB_BRANCH) == []


def test_the_scan_reads_each_entry_point_that_varies_a_setting_by_name() -> None:
    """The entry modules scanned include the web sweep, `fleet sweep --param` and optimize configs, so a passing real-tree scan read them."""
    scanned = {path.relative_to(_PACKAGE_DIR).as_posix() for path in _sources(_PACKAGE_DIR, _ENTRY_MODULES)}

    assert {"web/sweep_request.py", "cli/fleet.py", "optimize.py", "cli/optimize.py"} <= scanned


@pytest.mark.parametrize("rule", list(_Rule), ids=lambda rule: rule.name.lower())
def test_each_scan_of_a_rule_reads_some_file_of_the_tree(rule: _Rule) -> None:
    """Every file pattern a rule scans matches a file of the real package, so the rule's passing scan read something."""
    assert [scan.files for scan in _SCANS[rule] if not _sources(_PACKAGE_DIR, scan.files)] == []


def test_sweep_modes_own_class_may_name_the_modes(tmp_path: Path) -> None:
    """The modes' literals in SweepMode's class in its own module are not reported, and the same class elsewhere is."""
    text = 'class SweepMode:\n    LINEAR = "linear"\n'
    owner = _seeded_package(tmp_path / "owner", _Seed(_SWEEP_MODE_MODULE, text))
    elsewhere = _seeded_package(tmp_path / "elsewhere", _Seed("web/seeded.py", text))

    assert _violations(owner, _Rule.MODE_LITERAL) == []
    assert _violations(elsewhere, _Rule.MODE_LITERAL) == [
        _Violation("src/solar_challenge/web/seeded.py", 2, _Rule.MODE_LITERAL)
    ]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("import math\n\nn = math.ceil(x)\nok = math.isfinite(x)\n", id="ceil-and-isfinite"),
        pytest.param("import numpy as np\n\ntotal = np.sum(xs)\n", id="numpys-sum"),
        pytest.param(
            'import logging\n\n_log = logging.getLogger(__name__)\n_log.log(logging.INFO, "started")\n',
            id="a-loggers-log",
        ),
    ],
)
def test_maths_other_functions_are_no_log_or_exp(tmp_path: Path, text: str) -> None:
    """math.ceil, math.isfinite and numpy.sum in web/, and the log of a logger, are not reported."""
    package_dir = _seeded_package(tmp_path, _Seed("web/seeded.py", text))

    assert _violations(package_dir, _Rule.WEB_LOG_EXP) == []
