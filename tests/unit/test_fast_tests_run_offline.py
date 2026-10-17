# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/conftest.py runs every test not marked slow or e2e offline, with every fixture it sets up or tears down.

The guard decides outcomes at teardown, so the scenarios run in a session of
their own under a copy of tests/conftest.py. They need no session apiece, so
they share one (tests/_scenario_session.py).
"""

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import DEFAULT_CACHE_DIR, WeatherCache, get_tmy_data
from tests._scenario_session import ScenarioSession
from tests._synthetic_weather import synthetic_june_weather


@pytest.fixture
def suite(pytester_under_root_conftest: pytest.Pytester) -> pytest.Pytester:
    """pytester, whose sessions run under a copy of tests/conftest.py, whose guard refuses and names each scenario test's network access, its child processes' included."""
    return pytester_under_root_conftest


def test_get_tmy_data_reads_the_tmy_a_test_seeds_into_weather_cache(weather_cache: WeatherCache) -> None:
    seeded = synthetic_june_weather("2024-06-21")
    weather_cache.put(seeded, "tmy", Location.bristol())

    pd.testing.assert_frame_equal(get_tmy_data(Location.bristol()), seeded, check_exact=True)


FETCHES_A_TMY = """
    from solar_challenge.location import Location
    from solar_challenge.weather import get_tmy_data


    def test_fetches_bristols_tmy():
        get_tmy_data(Location.bristol())
    """


def test_a_fast_test_that_fetches_a_tmy_fails_and_leaves_no_weather_cache_behind(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_fetches_a_tmy") == {"failed": 1, "errors": 1}
    run.result.stdout.fnmatch_lines(["*test_fetches_bristols_tmy reached the network*"])
    assert not (run.session_dir / DEFAULT_CACHE_DIR).exists()


SUBMITS_A_HOME_JOB = """
    import pytest

    pytest.importorskip("flask")

    from tests._web_app import build_test_app


    def test_submits_a_home_job_and_ends(tmp_path):
        client = build_test_app(tmp_path).test_client()

        assert client.post("/api/simulate/home", json={"days": 1}).status_code == 201
    """


def test_a_fast_test_whose_job_reaches_the_network_fails_once_the_job_has_run(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """The job fetches after the test body has passed, so the guard must check only once the job has drained."""
    pytest.importorskip("flask")
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_submits_a_home_job") == {"passed": 1, "errors": 1}
    run.result.stdout.fnmatch_lines(["*test_submits_a_home_job_and_ends reached the network*"])


FETCHES_AND_CARRIES_ON = """
    import urllib.request

    try:
        urllib.request.urlopen("https://example.invalid/", timeout=30)
    except OSError:
        pass
    """

RUNS_A_CHILD_THAT_FETCHES = """
    import subprocess
    import sys


    def test_runs_a_child_that_fetches_and_carries_on():
        subprocess.run([sys.executable, "fetches_and_carries_on.py"], check=True)
    """


def test_a_fast_test_whose_child_process_reaches_the_network_fails_even_if_the_child_carries_on(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """The child swallows its fetch's error and exits 0, so only the guard can catch it."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_runs_a_child_that_fetches") == {"passed": 1, "errors": 1}
    run.result.stdout.fnmatch_lines(
        ["*test_runs_a_child_that_fetches_and_carries_on reached the network (example.invalid:443)*"]
    )


MODULE_FIXTURE_FETCHES = """
    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import get_tmy_data


    @pytest.fixture(scope="module")
    def bristols_tmy():
        return get_tmy_data(Location.bristol())


    def test_sets_up_bristols_tmy(bristols_tmy):
        pass
    """


def test_a_module_fixture_that_fetches_a_tmy_fails_the_fast_test_that_sets_it_up_and_leaves_no_weather_cache_behind(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """It errors at setup, where the PVGIS fetch is refused, and at teardown, where the guard names it."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_module_fixture_fetches") == {"errors": 2}
    run.result.stdout.fnmatch_lines(["*test_sets_up_bristols_tmy reached the network*"])
    assert not (run.session_dir / DEFAULT_CACHE_DIR).exists()


MODULE_FIXTURE_LOOKS_UP_AT_TEARDOWN = """
    import socket

    import pytest


    @pytest.fixture(scope="module")
    def looks_up_a_host_at_teardown():
        yield
        try:
            socket.getaddrinfo("example.invalid", 443)
        except OSError:
            pass


    def test_sets_up_the_fixture(looks_up_a_host_at_teardown):
        pass


    def test_tears_down_the_fixture(looks_up_a_host_at_teardown):
        pass
    """


def test_a_module_fixture_that_reaches_the_network_at_teardown_fails_the_fast_test_that_tears_it_down(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """pytest tears a module fixture down in the teardown of the module's last test, and the fixture swallows its lookup's error, so only the guard can catch it."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_module_fixture_looks_up_at_teardown") == {"passed": 2, "errors": 1}
    run.result.stdout.fnmatch_lines(["*test_tears_down_the_fixture reached the network (example.invalid:443)*"])


MODULE_FIXTURE_INSTALLS_A_CACHE = """
    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import WeatherCache, get_tmy_data, set_weather_cache
    from tests._synthetic_weather import synthetic_june_weather


    @pytest.fixture(scope="module")
    def installs_a_weather_cache_of_its_own(tmp_path_factory):
        set_weather_cache(WeatherCache(cache_dir=tmp_path_factory.mktemp("weather")))


    def test_reads_the_tmy_it_seeds(installs_a_weather_cache_of_its_own, weather_cache):
        weather_cache.put(synthetic_june_weather("2024-06-21"), "tmy", Location.bristol())

        get_tmy_data(Location.bristol())
    """


def test_get_tmy_data_reads_the_tmy_a_test_seeds_into_weather_cache_after_a_module_fixture_installs_a_cache_of_its_own(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """pytest sets the module fixture up first, inside the test's window, so weather_cache must install the test's cache over the fixture's."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_module_fixture_installs_a_cache") == {"passed": 1}


CACHE_DIRECTORY_CANNOT_BE_REMOVED = """
    files_left_behind = []


    def test_leaves_a_file_where_its_weather_cache_directory_was(weather_cache):
        weather_cache.cache_dir.rmdir()
        weather_cache.cache_dir.touch()
        files_left_behind.append(weather_cache.cache_dir)


    def test_runs_next_and_removes_that_file():
        files_left_behind.pop().unlink(missing_ok=True)
    """


def test_a_fast_test_whose_weather_cache_directory_cannot_be_removed_leaves_the_session_running(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """A job still writing into the cache could make removing it fail, and the window closes after the test is reported, where an error would abort the session."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_cache_directory_cannot_be_removed") == {"passed": 2}
    assert run.result.ret in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED)


SLOW_REQUESTS_WEATHER_CACHE = """
    import pytest


    @pytest.mark.slow
    def test_requests_weather_cache_while_marked_slow(weather_cache):
        pass
    """


def test_a_slow_test_that_requests_weather_cache_errors_at_setup(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """A slow test reads the working directory's weather cache, so it has none of its own for weather_cache to return."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_slow_requests_weather_cache") == {"errors": 1}
    run.result.stdout.fnmatch_lines(["*test_requests_weather_cache_while_marked_slow is marked slow*"])


SLOW_AND_E2E_READ_THEIR_WORKING_DIRECTORY_CACHE = """
    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import DEFAULT_CACHE_DIR, WeatherCache, get_tmy_data
    from tests._synthetic_weather import synthetic_june_weather


    @pytest.fixture(autouse=True)
    def working_directory_caching_bristols_tmy(tmp_path, monkeypatch):
        WeatherCache(cache_dir=tmp_path / DEFAULT_CACHE_DIR).put(
            synthetic_june_weather("2024-06-21"), "tmy", Location.bristol()
        )
        monkeypatch.chdir(tmp_path)


    @pytest.mark.slow
    def test_a_slow_test_reads_bristols_tmy():
        get_tmy_data(Location.bristol())


    @pytest.mark.e2e
    def test_an_e2e_test_reads_bristols_tmy():
        get_tmy_data(Location.bristol())
    """


def test_slow_and_e2e_tests_read_the_weather_cache_in_their_working_directory(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """Neither is guarded, so each reads the cache its working directory holds, not an empty one of its own."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_slow_and_e2e_read_their_working_directory_cache") == {"passed": 2}


SCENARIOS = {
    "test_fetches_a_tmy": FETCHES_A_TMY,
    "test_submits_a_home_job": SUBMITS_A_HOME_JOB,
    "fetches_and_carries_on": FETCHES_AND_CARRIES_ON,
    "test_runs_a_child_that_fetches": RUNS_A_CHILD_THAT_FETCHES,
    "test_module_fixture_fetches": MODULE_FIXTURE_FETCHES,
    "test_module_fixture_looks_up_at_teardown": MODULE_FIXTURE_LOOKS_UP_AT_TEARDOWN,
    "test_module_fixture_installs_a_cache": MODULE_FIXTURE_INSTALLS_A_CACHE,
    "test_cache_directory_cannot_be_removed": CACHE_DIRECTORY_CANNOT_BE_REMOVED,
    "test_slow_requests_weather_cache": SLOW_REQUESTS_WEATHER_CACHE,
    "test_slow_and_e2e_read_their_working_directory_cache": SLOW_AND_E2E_READ_THEIR_WORKING_DIRECTORY_CACHE,
}


@pytest.fixture(scope="module")
def offline_scenarios() -> ScenarioSession:
    """The one session all the scenarios above run in, under the suite of whichever test here asks for its run first."""
    return ScenarioSession(SCENARIOS)
