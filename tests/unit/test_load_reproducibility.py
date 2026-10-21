# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stochastic load profile depends only on its LoadConfig: not on what ran before it in the process, nor on what runs beside it on another thread, nor, in a forked child, on a window a parent thread held. load.py's RNG hand-off makes it so, and refuses a household model that generates a profile inside its own window (docs/prds/rng-hand-off.md §5 C3, C4 and C5, §7)."""

import datetime
import logging
import logging.handlers
import multiprocessing
import random
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from solar_challenge.load import DaySimulator, HouseholdModel, LoadConfig, generate_load_profile


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


_needs_fork = pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="multiprocessing has no fork start method on this platform",
)
# Every fork here warns: pandas imports pyarrow, whose native thread survives the fork, and CPython
# counts the process's OS threads.
_ignores_the_multi_threaded_fork_warning = pytest.mark.filterwarnings(
    r"ignore:This process .* is multi-threaded, use of fork\(\) may lead to deadlocks in the child.:DeprecationWarning"
)


def _generate_the_seed_42_profile_of_21_june_2024_expecting(expected: pd.Series) -> None:
    """A forked child's work: it fails unless its seed-42 profile of 21 June 2024 is expected."""
    day = pd.Timestamp("2024-06-21")
    if not generate_load_profile(_stochastic(42), day, day).equals(expected):
        raise AssertionError("the forked child's seed-42 profile differs from its parent's")


@_needs_fork
@_ignores_the_multi_threaded_fork_warning
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


def _generate_a_profile_inside_a_household_model() -> None:
    """A forked child's work: it fails unless a profile generated inside a household model is the Elexon profile, logged with the one warning that names the rule."""
    day = pd.Timestamp("2024-06-21")
    profiles_inside: list[pd.Series] = []

    def household_that_generates_a_profile(
        config: LoadConfig, days: Sequence[datetime.date]
    ) -> DaySimulator:
        profiles_inside.append(generate_load_profile(config, day, day))
        return lambda _: np.ones(1440)

    logged = logging.handlers.BufferingHandler(capacity=10)
    logging.getLogger("solar_challenge.load").addHandler(logged)
    generate_load_profile(
        _stochastic(7), day, day, household_model=household_that_generates_a_profile
    )

    elexon = generate_load_profile(replace(_stochastic(7), use_stochastic=False), day, day)
    if not (len(profiles_inside) == 1 and profiles_inside[0].equals(elexon)):
        raise AssertionError("the profile generated inside the household model is not the Elexon profile")
    messages = [record.getMessage() for record in logged.buffer]
    if messages != [
        "richardsonpy stochastic generation failed; falling back to Elexon deterministic profile: "
        "RuntimeError: a household model must not generate a load profile: the RNG hand-off is "
        "not re-entrant"
    ]:
        raise AssertionError(f"the forked child logged {messages}")


@_needs_fork
@_ignores_the_multi_threaded_fork_warning
def test_a_profile_generated_inside_a_household_model_is_the_elexon_profile_with_a_warning_naming_the_rule() -> None:
    """The RNG hand-off is not re-entrant, so it refuses the inner profile's window rather than wait forever on the lock its own window holds. A forked child runs the case, so that such a wait hangs only the child."""
    child = multiprocessing.get_context("fork").Process(
        target=_generate_a_profile_inside_a_household_model
    )
    child.start()
    try:
        child.join(30)
        assert child.exitcode == 0, (
            f"the child whose household model generates a load profile exited {child.exitcode}: "
            "None if it did not finish within 30 s, as when the profile inside waits on the RNG "
            "hand-off's lock its own window holds, or 1 if that profile or the warning differed"
        )
    finally:
        if child.is_alive():
            child.kill()
            child.join()
