# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/conftest.py runs every test not marked slow or e2e offline.

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
