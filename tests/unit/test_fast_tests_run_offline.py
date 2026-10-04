# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/conftest.py runs every test not marked slow or e2e offline, with every fixture it sets up or tears down.

The guard decides a test's outcome at its teardown, so each scenario runs in a
separate pytest session under a copy of tests/conftest.py, in a directory of its
own and with no HTTP proxy configured, as in tests/unit/test_web_jobs_drain_scope.py.
"""

import numpy as np
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import DEFAULT_CACHE_DIR, WeatherCache, get_tmy_data
from tests._synthetic_weather import synthetic_june_weather

_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture
def suite(pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A pytest session of its own, under a copy of tests/conftest.py and with no HTTP proxy configured.

    Through a proxy, requests would look up only the proxy's loopback host, so the
    guard would never see the PVGIS destination.
    """
    for name in _PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return pytester_under_root_conftest


def test_get_tmy_data_reads_the_tmy_a_test_seeds_into_weather_cache(weather_cache: WeatherCache) -> None:
    seeded = synthetic_june_weather("2024-06-21")
    weather_cache.put(seeded, "tmy", Location.bristol())

    # The cache's CSV round trip keeps the instants but turns the zone into a fixed offset.
    np.testing.assert_array_equal(get_tmy_data(Location.bristol()).to_numpy(), seeded.to_numpy())


def test_a_fast_test_that_fetches_a_tmy_fails_and_leaves_no_weather_cache_behind(suite: pytest.Pytester) -> None:
    scenario = suite.makepyfile(
        """
        from solar_challenge.location import Location
        from solar_challenge.weather import get_tmy_data


        def test_fetches_bristols_tmy():
            get_tmy_data(Location.bristol())
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(failed=1, errors=1)
    result.stdout.fnmatch_lines(["*test_fetches_bristols_tmy reached the network*"])
    assert not (suite.path / DEFAULT_CACHE_DIR).exists()


def test_a_fast_test_whose_job_reaches_the_network_fails_once_the_job_has_run(suite: pytest.Pytester) -> None:
    """The job fetches after the test body has passed, so the guard must check only once the job has drained."""
    pytest.importorskip("flask")
    scenario = suite.makepyfile(
        """
        from tests._web_app import build_test_app


        def test_submits_a_home_job_and_ends(tmp_path):
            client = build_test_app(tmp_path).test_client()

            assert client.post("/api/simulate/home", json={"days": 1}).status_code == 201
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*test_submits_a_home_job_and_ends reached the network*"])


def test_a_fast_test_whose_child_process_reaches_the_network_fails_even_if_the_child_carries_on(
    suite: pytest.Pytester,
) -> None:
    """The child swallows its fetch's error and exits 0, so only the guard can catch it."""
    suite.makepyfile(
        fetches_and_carries_on="""
        import urllib.request

        try:
            urllib.request.urlopen("https://example.invalid/", timeout=30)
        except OSError:
            pass
        """
    )
    scenario = suite.makepyfile(
        """
        import subprocess
        import sys


        def test_runs_a_child_that_fetches_and_carries_on():
            subprocess.run([sys.executable, "fetches_and_carries_on.py"], check=True)
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(
        ["*test_runs_a_child_that_fetches_and_carries_on reached the network (example.invalid:443)*"]
    )


def test_a_module_fixture_that_fetches_a_tmy_fails_the_fast_test_that_sets_it_up_and_leaves_no_weather_cache_behind(
    suite: pytest.Pytester,
) -> None:
    """It errors at setup, where the PVGIS fetch is refused, and at teardown, where the guard names it."""
    scenario = suite.makepyfile(
        """
        import pytest

        from solar_challenge.location import Location
        from solar_challenge.weather import get_tmy_data


        @pytest.fixture(scope="module")
        def bristols_tmy():
            return get_tmy_data(Location.bristol())


        def test_sets_up_bristols_tmy(bristols_tmy):
            pass
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(errors=2)
    result.stdout.fnmatch_lines(["*test_sets_up_bristols_tmy reached the network*"])
    assert not (suite.path / DEFAULT_CACHE_DIR).exists()


def test_a_module_fixture_that_reaches_the_network_at_teardown_fails_the_fast_test_that_tears_it_down(
    suite: pytest.Pytester,
) -> None:
    """pytest tears a module fixture down in the teardown of the module's last test, and the fixture swallows its lookup's error, so only the guard can catch it."""
    scenario = suite.makepyfile(
        """
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
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(["*test_tears_down_the_fixture reached the network (example.invalid:443)*"])


def test_get_tmy_data_reads_the_tmy_a_test_seeds_into_weather_cache_after_a_module_fixture_installs_a_cache_of_its_own(
    suite: pytest.Pytester,
) -> None:
    """pytest sets the module fixture up first, inside the test's window, so weather_cache must install the test's cache over the fixture's."""
    scenario = suite.makepyfile(
        """
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
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=1)


def test_a_fast_test_whose_weather_cache_directory_cannot_be_removed_leaves_the_session_running(
    suite: pytest.Pytester,
) -> None:
    """A job still writing into the cache could make removing it fail, and the window closes after the test is reported, where an error would abort the session."""
    scenario = suite.makepyfile(
        """
        files_left_behind = []


        def test_leaves_a_file_where_its_weather_cache_directory_was(weather_cache):
            weather_cache.cache_dir.rmdir()
            weather_cache.cache_dir.touch()
            files_left_behind.append(weather_cache.cache_dir)


        def test_runs_next_and_removes_that_file():
            files_left_behind.pop().unlink(missing_ok=True)
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=2)
    assert result.ret == pytest.ExitCode.OK


def test_a_slow_test_that_requests_weather_cache_errors_at_setup(suite: pytest.Pytester) -> None:
    """A slow test reads the working directory's weather cache, so it has none of its own for weather_cache to return."""
    scenario = suite.makepyfile(
        """
        import pytest


        @pytest.mark.slow
        def test_requests_weather_cache_while_marked_slow(weather_cache):
            pass
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*test_requests_weather_cache_while_marked_slow is marked slow*"])


def test_slow_and_e2e_tests_read_the_weather_cache_in_their_working_directory(suite: pytest.Pytester) -> None:
    """Neither is guarded, so each reads the cache its working directory holds, not an empty one of its own."""
    WeatherCache(cache_dir=suite.path / DEFAULT_CACHE_DIR).put(
        synthetic_june_weather("2024-06-21"), "tmy", Location.bristol()
    )
    scenario = suite.makepyfile(
        """
        import pytest

        from solar_challenge.location import Location
        from solar_challenge.weather import get_tmy_data


        @pytest.mark.slow
        def test_a_slow_test_reads_bristols_tmy():
            get_tmy_data(Location.bristol())


        @pytest.mark.e2e
        def test_an_e2e_test_reads_bristols_tmy():
            get_tmy_data(Location.bristol())
        """
    )

    result = suite.runpytest_subprocess(scenario)

    result.assert_outcomes(passed=2)
