# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stochastic load profile depends only on its LoadConfig: not on what ran before it in the process, nor on what runs beside it on another thread, and only load.py's RNG hand-off calls the module-level random and numpy.random functions (docs/prds/rng-hand-off.md §5 C3, C4 and C6, §7)."""

import ast
import datetime
import inspect
import logging
import multiprocessing
import random
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from solar_challenge.load import DaySimulator, HouseholdModel, LoadConfig, generate_load_profile

_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "solar_challenge"


def _stochastic(seed: int | None) -> LoadConfig:
    return LoadConfig(
        annual_consumption_kwh=3400.0, household_occupants=3, use_stochastic=True, seed=seed
    )


class _GlobalDrawsHousehold:
    """A household model that draws only from the module-level random and numpy.random generators, as richardsonpy's does.

    Each household it builds records its first draw from each generator in first_draws; each day it
    simulates is 1,440 draws from random.
    """

    def __init__(self) -> None:
        self.first_draws: list[tuple[float, float]] = []

    def __call__(self, config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator:
        self.first_draws.append((random.random(), float(np.random.random_sample())))
        return lambda day: np.array([random.random() for _ in range(1440)])


def _household_that_draws_then_raises(
    config: LoadConfig, days: Sequence[datetime.date]
) -> DaySimulator:
    random.random()
    np.random.random_sample()
    raise RuntimeError("the household failed after drawing from both generators")


def _numpy_state() -> tuple[object, ...]:
    """np.random.get_state(), its key array as bytes, so that two states compare with ==."""
    name, keys, position, has_gauss, cached_gaussian = np.random.get_state()
    return name, keys.tobytes(), position, has_gauss, cached_gaussian


def test_seeded_profiles_generated_on_two_threads_at_once_equal_their_serial_profiles() -> None:
    start, end = pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-07")
    references = {seed: generate_load_profile(_stochastic(seed), start, end) for seed in (42, 43)}
    assert not references[42].equals(references[43]), (
        "seeds 42 and 43 gave one profile, so neither profile is stochastic"
    )

    differing = []
    for trial in range(5):
        with ThreadPoolExecutor(max_workers=2) as pool:
            profiles = {
                seed: pool.submit(generate_load_profile, _stochastic(seed), start, end)
                for seed in (42, 43)
            }
        differing += [
            (trial, seed)
            for seed, profile in profiles.items()
            if not profile.result().equals(references[seed])
        ]

    assert differing == []


def test_a_seed_from_0_to_2_to_the_32_seeds_the_generators_as_random_seed_and_numpy_random_seed_do() -> None:
    household = _GlobalDrawsHousehold()
    day = pd.Timestamp("2024-06-01")

    generate_load_profile(_stochastic(42), day, day, household_model=household)

    assert household.first_draws == [
        (random.Random(42).random(), np.random.RandomState(42).random_sample())
    ]


def test_unseeded_profiles_generated_right_after_the_same_seeded_profile_differ() -> None:
    household = _GlobalDrawsHousehold()
    start, end = pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-02")

    seeded, unseeded = [], []
    for _ in range(2):
        seeded.append(generate_load_profile(_stochastic(5), start, end, household_model=household))
        unseeded.append(
            generate_load_profile(_stochastic(None), start, end, household_model=household)
        )

    assert seeded[0].equals(seeded[1])
    assert not unseeded[0].equals(unseeded[1])


@pytest.mark.parametrize(
    "household_model",
    [
        pytest.param(_GlobalDrawsHousehold(), id="completes"),
        pytest.param(_household_that_draws_then_raises, id="raises"),
    ],
)
def test_a_profile_leaves_the_module_level_generators_as_it_found_them(
    household_model: HouseholdModel,
) -> None:
    random_state, numpy_state = random.getstate(), _numpy_state()
    day = pd.Timestamp("2024-06-01")

    generate_load_profile(_stochastic(7), day, day, household_model=household_model)

    assert random.getstate() == random_state
    assert _numpy_state() == numpy_state


@pytest.mark.parametrize("seed", [-1, 2**32, 2**40])
def test_an_int_seed_outside_0_to_2_to_the_32_gives_a_reproducible_stochastic_profile(
    seed: int, caplog: pytest.LogCaptureFixture
) -> None:
    config = _stochastic(seed)
    start, end = pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-02")

    with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
        profile = generate_load_profile(config, start, end)
        again = generate_load_profile(config, start, end)

    assert not profile.equals(
        generate_load_profile(replace(config, use_stochastic=False), start, end)
    )
    assert again.equals(profile)
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "solar_challenge.load" and record.levelno >= logging.WARNING
    ] == []


@pytest.mark.parametrize("seed", [1, 2**32])
def test_a_negative_seed_and_its_absolute_value_give_different_profiles(seed: int) -> None:
    start, end = pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-02")

    negative = generate_load_profile(_stochastic(-seed), start, end)
    positive = generate_load_profile(_stochastic(seed), start, end)

    assert not negative.equals(positive)


def _generate_the_seed_42_profile_of_21_june_2024_expecting(expected: pd.Series) -> None:
    """A forked child's work: it fails unless its seed-42 profile of 21 June 2024 is expected."""
    day = pd.Timestamp("2024-06-21")
    if not generate_load_profile(_stochastic(42), day, day).equals(expected):
        raise AssertionError("the forked child's seed-42 profile differs from its parent's")


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="multiprocessing has no fork start method on this platform",
)
@pytest.mark.filterwarnings(
    r"ignore:This process .* is multi-threaded, use of fork\(\) may lead to deadlocks in the child.:DeprecationWarning"
)
def test_a_child_forked_while_a_thread_holds_the_window_runs_its_own_seeded_profile() -> None:
    day = pd.Timestamp("2024-06-21")
    expected = generate_load_profile(_stochastic(42), day, day)
    entered, release = threading.Event(), threading.Event()

    def blocking(config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator:
        entered.set()
        release.wait(60)
        return lambda _: np.ones(1440)

    holder = threading.Thread(
        target=generate_load_profile,
        args=(_stochastic(7), day, day),
        kwargs={"household_model": blocking},
        daemon=True,
    )
    child = multiprocessing.get_context("fork").Process(
        target=_generate_the_seed_42_profile_of_21_june_2024_expecting, args=(expected,)
    )
    holder.start()
    try:
        assert entered.wait(30)
        child.start()
        child.join(30)
        assert child.exitcode == 0, (
            f"the child forked while a thread held the stochastic window exited {child.exitcode}: "
            "None if it did not finish its profile within 30 s, as when it inherits the RNG "
            "hand-off's lock held, or 1 if its profile differed"
        )
    finally:
        release.set()
        holder.join(30)
        if child.is_alive():
            child.kill()
            child.join()
    assert not holder.is_alive()


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
