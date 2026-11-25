# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario grammar builds every refusal through scenario_blocks.refusal, and every reader of a block takes block_path (docs/prds/scenario-grammar-partition.md §4.2, C4 and C5)."""

import ast
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from tests._exemption_reasons import Permanent
from tests._module_sources import module_source
from tests._repository_paths import REPOSITORY_ROOT
from tests._scenario_grammar import CONFIG, FLEET_DISTRIBUTION, GRAMMAR_MODULES, SCENARIO_BLOCKS

_SRC_DIR = REPOSITORY_ROOT / "src"
_ERRORS = "solar_challenge.errors"
_CONFIGURATION_ERROR = "ConfigurationError"
_THE_ONE_CONSTRUCTOR = (SCENARIO_BLOCKS, "refusal")
_READER_NAME = re.compile(r"^_?parse_|^_build_")
_BLOCK_PATH = "block_path"
_PRD_SECTION = "docs/prds/scenario-grammar-partition.md §4.2"

_FILE_LOADER = Permanent(
    f"a file loader, whose subject is a file path, not a block of the document ({_PRD_SECTION}, C4)"
)

#: The module-level functions of the grammar that may construct a ConfigurationError themselves.
ONE_CONSTRUCTOR_EXEMPTIONS: Mapping[tuple[str, str], Permanent] = {
    (CONFIG, "load_config_yaml"): _FILE_LOADER,
    (CONFIG, "load_config_json"): _FILE_LOADER,
    (CONFIG, "load_config"): _FILE_LOADER,
    (CONFIG, "_refuse_unmatched_variables"): Permanent(
        "its subject is the variables the caller supplies, not a block of the document "
        f"(task 707's note; {_PRD_SECTION}, C4)"
    ),
    (FLEET_DISTRIBUTION, "write_distribution_spec"): Permanent(
        "a writer, whose subject is a spec value its caller holds, which no block of a file "
        f"holds ({_PRD_SECTION}, C4)"
    ),
}

_WHOLE_FLEET_DOCUMENT = Permanent(
    "it reads a whole fleet document at the top level, under which the fleet grammar's own "
    f"paths are fixed at fleet_distribution (_FLEET_DISTRIBUTION_PATH; {_PRD_SECTION}, C5)"
)

#: The readers of the grammar that take no block_path.
BLOCK_PATH_EXEMPTIONS: Mapping[tuple[str, str], Permanent] = {
    (CONFIG, "parse_fleet_config"): _WHOLE_FLEET_DOCUMENT,
    (CONFIG, "parse_sweep_fleet_configs"): _WHOLE_FLEET_DOCUMENT,
}


class _RefusalRule(Enum):
    """A rule of the grammar's refusal form (docs/prds/scenario-grammar-partition.md §4.2), its value the invariant's text."""

    ONE_CONSTRUCTOR = (
        "C4: inside a module-level function of a grammar module, nothing but "
        "scenario_blocks.refusal constructs a ConfigurationError"
    )
    BLOCK_PATH = "C5: every _parse_* or _build_* reader of the grammar takes block_path"


@dataclass(frozen=True)
class _RefusalViolation:
    """A site of a grammar module that breaks a refusal-form rule: its file and line, the module-level function it is in, and the rule."""

    path: Path
    line: int
    function: str
    rule: _RefusalRule

    def __str__(self) -> str:
        breach = (
            "constructs a ConfigurationError"
            if self.rule is _RefusalRule.ONE_CONSTRUCTOR
            else "takes no block_path"
        )
        return f"{self.path.as_posix()}:{self.line}: {self.function} {breach} ({self.rule.value})"


def _parsed(src_dir: Path, module: str) -> tuple[Path, ast.Module]:
    """Return *module*'s file under *src_dir*, relative to *src_dir*'s parent, and its parsed source."""
    source = module_source(src_dir, module)
    return source.relative_to(src_dir.parent), ast.parse(source.read_text(encoding="utf-8"))


def _configuration_error_names(tree: ast.Module) -> frozenset[str]:
    """Return the local names *tree*'s import statements bind to solar_challenge.errors.ConfigurationError."""
    return frozenset(
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == _ERRORS and node.level == 0
        for alias in node.names
        if alias.name == _CONFIGURATION_ERROR
    )


def _module_level_functions(
    tree: ast.Module,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield the functions *tree*'s module body defines, never a method of one of its classes."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _constructs(node: ast.AST, names: frozenset[str]) -> bool:
    """Return whether *node* calls one of *names*, or an attribute of one, or raises one bare."""
    if isinstance(node, ast.Call):
        target = node.func.value if isinstance(node.func, ast.Attribute) else node.func
        return isinstance(target, ast.Name) and target.id in names
    return isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name) and node.exc.id in names


def _constructions(src_dir: Path, module: str) -> list[_RefusalViolation]:
    """Return, in line order, every site of a module-level function of *module* under *src_dir* that constructs a ConfigurationError, nested functions and lambdas included, exempting none."""
    path, tree = _parsed(src_dir, module)
    names = _configuration_error_names(tree)
    sites = [
        _RefusalViolation(path, node.lineno, function.name, _RefusalRule.ONE_CONSTRUCTOR)
        for function in _module_level_functions(tree)
        for node in ast.walk(function)
        if _constructs(node, names)
    ]
    return sorted(sites, key=lambda site: site.line)


def _one_constructor_violations(src_dir: Path, module: str) -> list[_RefusalViolation]:
    """Return the C4 sites of *module* under *src_dir*: its _constructions outside refusal and the exempted functions."""
    allowed = {_THE_ONE_CONSTRUCTOR, *ONE_CONSTRUCTOR_EXEMPTIONS}
    return [site for site in _constructions(src_dir, module) if (module, site.function) not in allowed]


def _readers_without_block_path(src_dir: Path, module: str) -> list[_RefusalViolation]:
    """Return, in line order, every module-level _parse_* or _build_* function of *module* under *src_dir* with no parameter named block_path, exempting none."""
    path, tree = _parsed(src_dir, module)
    return [
        _RefusalViolation(path, function.lineno, function.name, _RefusalRule.BLOCK_PATH)
        for function in _module_level_functions(tree)
        if _READER_NAME.match(function.name)
        and _BLOCK_PATH
        not in {
            parameter.arg
            for parameter in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        }
    ]


def _block_path_violations(src_dir: Path, module: str) -> list[_RefusalViolation]:
    """Return the C5 sites of *module* under *src_dir*: its readers without block_path outside the exempted ones."""
    return [
        site
        for site in _readers_without_block_path(src_dir, module)
        if (module, site.function) not in BLOCK_PATH_EXEMPTIONS
    ]


_SEED_IMPORT = "from solar_challenge.errors import ConfigurationError\n"
_SEED_REFUSAL = (
    "\n"
    "\n"
    "def refusal(block_path, problem):\n"
    '    return ConfigurationError(f"{block_path}: {problem}")\n'
)


def _seeded_tree(src_dir: Path, modules: Mapping[str, str]) -> Path:
    """Write each grammar module of *modules*, keyed by its dotted name, under *src_dir*, an empty one for every grammar module left out, and return *src_dir*."""
    for module in GRAMMAR_MODULES:
        source = module_source(src_dir, module)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(modules.get(module, ""), encoding="utf-8")
    return src_dir


def _sites(violations: list[_RefusalViolation]) -> list[tuple[str, int, str]]:
    return [(violation.path.as_posix(), violation.line, violation.function) for violation in violations]


_SCENARIO_BLOCKS_FILE = "src/solar_challenge/scenario_blocks.py"


def test_a_reader_constructing_a_configuration_error_is_reported_with_its_file_line_and_function(
    tmp_path: Path,
) -> None:
    """A seeded reader that raises ConfigurationError itself is reported, and refusal is not: the real-tree checks pass for a scan that finds nothing."""
    src_dir = _seeded_tree(
        tmp_path / "src",
        {
            SCENARIO_BLOCKS: _SEED_IMPORT
            + _SEED_REFUSAL
            + "\n"
            + "\n"
            + "def _parse_x(data, *, block_path):\n"
            + '    raise ConfigurationError("x")\n'
        },
    )

    violations = _one_constructor_violations(src_dir, SCENARIO_BLOCKS)

    assert _sites(violations) == [(_SCENARIO_BLOCKS_FILE, 9, "_parse_x")]
    assert str(violations[0]) == (
        f"{_SCENARIO_BLOCKS_FILE}:9: _parse_x constructs a ConfigurationError "
        f"({_RefusalRule.ONE_CONSTRUCTOR.value})"
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            "def _held(path):\n    return ConfigurationError(f'{path}: x')\n",
            [(9, "_held")],
            id="returned-builder",
        ),
        pytest.param(
            "def _check(value):\n    raise ConfigurationError.must_be('x', 'a number', value)\n",
            [(9, "_check")],
            id="must_be",
        ),
        pytest.param(
            "def _check(value):\n    raise ConfigurationError\n",
            [(9, "_check")],
            id="bare-raise-of-the-class",
        ),
        pytest.param(
            "def _outer(data, *, block_path):\n"
            "    def inner():\n"
            "        raise ConfigurationError('x')\n"
            "\n"
            "    check = lambda: ConfigurationError('y')\n"
            "    inner()\n",
            [(10, "_outer"), (12, "_outer")],
            id="nested-function-and-lambda",
        ),
        pytest.param(
            "class _Block:\n"
            "    def __post_init__(self):\n"
            "        raise ConfigurationError('x')\n",
            [],
            id="a-method-is-out-of-scope",
        ),
        pytest.param(
            "def _reads(data):\n"
            "    try:\n"
            "        return data['x']\n"
            "    except ConfigurationError:\n"
            "        return isinstance(data, ConfigurationError)\n",
            [],
            id="naming-the-class-constructs-nothing",
        ),
    ],
)
def test_each_construction_in_a_module_level_function_is_reported(
    tmp_path: Path, body: str, expected: list[tuple[int, str]]
) -> None:
    """A returned builder, must_be, a bare raise of the class and a construction in a nested function or lambda are each reported; a method's raise is not."""
    src_dir = _seeded_tree(
        tmp_path / "src", {SCENARIO_BLOCKS: _SEED_IMPORT + _SEED_REFUSAL + "\n\n" + body}
    )

    violations = _one_constructor_violations(src_dir, SCENARIO_BLOCKS)

    assert _sites(violations) == [
        (_SCENARIO_BLOCKS_FILE, line, function) for line, function in expected
    ]


def test_an_aliased_import_of_configuration_error_is_resolved(tmp_path: Path) -> None:
    """A construction through a name the module binds with `as` is reported."""
    src_dir = _seeded_tree(
        tmp_path / "src",
        {
            FLEET_DISTRIBUTION: (
                "from solar_challenge.errors import ConfigurationError as CE\n"
                "\n"
                "\n"
                "def _parse_q(data, *, block_path):\n"
                "    raise CE('x')\n"
            )
        },
    )

    assert _sites(_one_constructor_violations(src_dir, FLEET_DISTRIBUTION)) == [
        ("src/solar_challenge/fleet_distribution.py", 5, "_parse_q")
    ]


def test_an_exempted_function_is_not_reported(tmp_path: Path) -> None:
    """A function the C4 exemption table names may construct a ConfigurationError itself."""
    src_dir = _seeded_tree(
        tmp_path / "src",
        {
            CONFIG: (
                _SEED_IMPORT
                + "\n"
                + "\n"
                + "def load_config(path):\n"
                + "    raise ConfigurationError(f'Configuration file not found: {path}')\n"
            )
        },
    )

    assert _constructions(src_dir, CONFIG) != []
    assert _one_constructor_violations(src_dir, CONFIG) == []


def test_a_reader_without_block_path_is_reported_with_its_file_line_and_function(
    tmp_path: Path,
) -> None:
    """A _parse_* or _build_* function with no block_path parameter is reported; one that takes it in any position, and a reader of another name, are not."""
    src_dir = _seeded_tree(
        tmp_path / "src",
        {
            SCENARIO_BLOCKS: (
                "def _parse_y(data, path):\n"
                "    return data\n"
                "\n"
                "\n"
                "def _build_z(data):\n"
                "    return data\n"
                "\n"
                "\n"
                "def _build_w(data, block_path):\n"
                "    return data\n"
                "\n"
                "\n"
                "def parse_k(data, *, block_path):\n"
                "    return data\n"
                "\n"
                "\n"
                "def _parse_p(data, block_path, /):\n"
                "    return data\n"
                "\n"
                "\n"
                "def read_q(data):\n"
                "    return data\n"
            )
        },
    )

    violations = _block_path_violations(src_dir, SCENARIO_BLOCKS)

    assert _sites(violations) == [
        (_SCENARIO_BLOCKS_FILE, 1, "_parse_y"),
        (_SCENARIO_BLOCKS_FILE, 5, "_build_z"),
    ]
    assert str(violations[0]) == (
        f"{_SCENARIO_BLOCKS_FILE}:1: _parse_y takes no block_path ({_RefusalRule.BLOCK_PATH.value})"
    )


def test_every_exemption_still_exempts_a_function_that_needs_it() -> None:
    """Each C4 exemption names a function that still constructs a ConfigurationError itself, and each C5 one a reader that still takes no block_path."""
    constructing = {
        (module, site.function) for module in GRAMMAR_MODULES for site in _constructions(_SRC_DIR, module)
    }
    without_block_path = {
        (module, site.function)
        for module in GRAMMAR_MODULES
        for site in _readers_without_block_path(_SRC_DIR, module)
    }
    stale = [
        f"{module}.{function} (C4)"
        for module, function in ONE_CONSTRUCTOR_EXEMPTIONS
        if (module, function) not in constructing
    ] + [
        f"{module}.{function} (C5)"
        for module, function in BLOCK_PATH_EXEMPTIONS
        if (module, function) not in without_block_path
    ]
    assert stale == [], (
        "these exemptions exempt nothing any more; delete each from ONE_CONSTRUCTOR_EXEMPTIONS "
        "or BLOCK_PATH_EXEMPTIONS: " + ", ".join(stale)
    )


def test_every_exemption_gives_its_contract() -> None:
    """Each exemption's Permanent reason states a contract, not blank text."""
    exemptions = {**ONE_CONSTRUCTOR_EXEMPTIONS, **BLOCK_PATH_EXEMPTIONS}
    assert [key for key, reason in exemptions.items() if not reason.contract.strip()] == []


def test_scenario_blocks_defines_the_one_constructor() -> None:
    """scenario_blocks defines a module-level refusal that constructs a ConfigurationError, the one the C4 scan allows."""
    assert "refusal" in {site.function for site in _constructions(_SRC_DIR, SCENARIO_BLOCKS)}, (
        "scenario_blocks defines no module-level refusal that constructs a ConfigurationError, "
        "so C4 has no constructor to send the grammar's refusals to"
    )


def _module_id(module: str) -> str:
    return module.rsplit(".", 1)[-1]


@pytest.mark.parametrize("module", GRAMMAR_MODULES, ids=_module_id)
def test_only_refusal_constructs_a_configuration_error(module: str) -> None:
    """No module-level function of the grammar module constructs a ConfigurationError but scenario_blocks.refusal and the exempted ones."""
    violations = _one_constructor_violations(_SRC_DIR, module)
    assert violations == [], (
        "build each refusal as `raise refusal(block_path, problem)`, with `from exc` where a "
        "cause exists; if the function's subject is no block of a document, add it to "
        "ONE_CONSTRUCTOR_EXEMPTIONS with a Permanent reason:\n"
        + "\n".join(str(violation) for violation in violations)
    )


@pytest.mark.parametrize("module", GRAMMAR_MODULES, ids=_module_id)
def test_every_reader_takes_block_path(module: str) -> None:
    """Every _parse_* or _build_* function of the grammar module takes block_path, but the exempted ones."""
    violations = _block_path_violations(_SRC_DIR, module)
    assert violations == [], (
        "give each reader a block_path parameter naming the block it reads; if it reads a "
        "whole document whose paths are fixed, add it to BLOCK_PATH_EXEMPTIONS with a "
        "Permanent reason:\n" + "\n".join(str(violation) for violation in violations)
    )
