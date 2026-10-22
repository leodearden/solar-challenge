# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/conftest.py runs every test not marked slow or e2e offline, with every fixture it sets up or tears down.

Each such test also runs on a weather cache of its own, which default_weather()
reads in the test and in a child process that inherits its environment.

The guard decides outcomes at teardown, so the scenarios run in a session of
their own under a copy of tests/conftest.py. They need no session apiece, so
they share one (tests/_scenario_session.py).
"""

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import CACHE_DIR_VARIABLE, DEFAULT_CACHE_DIR, PVGIS_API_URL, WeatherCache, default_weather
from tests._scenario_session import ScenarioSession
from tests._synthetic_weather import synthetic_june_weather


@pytest.fixture
def suite(pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """pytester, whose sessions run under a copy of tests/conftest.py, whose guard refuses and names each scenario test's network access, its child processes' included.

    Its sessions start with no weather cache directory named, as the lanes' shells do, not with the variable of the window that runs them.
    """
    monkeypatch.delenv(CACHE_DIR_VARIABLE, raising=False)
    return pytester_under_root_conftest


def test_default_weather_reads_the_tmy_a_test_seeds_into_weather_cache(weather_cache: WeatherCache) -> None:
    seeded = synthetic_june_weather("2024-06-21")
    weather_cache.put(seeded, "tmy", Location.bristol())

    pd.testing.assert_frame_equal(default_weather().get(Location.bristol()), seeded, check_exact=True)


def test_a_child_process_of_a_fast_test_reads_the_tmy_the_test_seeds_into_weather_cache(
    weather_cache: WeatherCache, tmp_path: Path
) -> None:
    """`home quick 4 --days 1`, run as a child with this test's environment in an empty working directory, simulates offline on the TMY seeded here, and leaves no cache there."""
    weather_cache.put(synthetic_june_weather("2024-06-01"), "tmy", Location.bristol())
    working = tmp_path / "working"
    working.mkdir()

    result = subprocess.run(
        [sys.executable, "-c", "from solar_challenge.cli import app; app()", "home", "quick", "4", "--days", "1"],
        cwd=working,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert not (working / DEFAULT_CACHE_DIR).exists()


RUNS_A_ROOT_UNSEEDED = """
    from typer.testing import CliRunner

    from solar_challenge.cli import app


    def test_runs_home_quick():
        CliRunner().invoke(app, ["home", "quick", "4", "--days", "1"])
    """


def test_a_fast_test_that_runs_a_root_unseeded_fails_naming_pvgis_and_leaves_no_weather_cache_behind(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """CliRunner keeps the refused fetch's error in its result, so the test itself passes and only the guard can catch it."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_runs_a_root_unseeded") == {"passed": 1, "errors": 1}
    run.result.stdout.fnmatch_lines(
        [f"*test_runs_home_quick reached the network ({urlsplit(PVGIS_API_URL).hostname}:443)*"]
    )
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
    from solar_challenge.weather import default_weather


    @pytest.fixture(scope="module")
    def bristols_tmy():
        return default_weather().get(Location.bristol())


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


MODULE_FIXTURE_PASSES_ITS_PROVIDER = """
    import pandas as pd
    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import PvgisTmy, WeatherCache, default_weather
    from tests._synthetic_weather import synthetic_june_weather


    @pytest.fixture(scope="module")
    def module_weather(tmp_path_factory):
        cache = WeatherCache(cache_dir=tmp_path_factory.mktemp("weather"))
        cache.put(synthetic_june_weather("2024-06-20"), "tmy", Location.bristol())
        return PvgisTmy(cache)


    def test_reads_each_tmy_from_its_own_provider(module_weather, weather_cache):
        weather_cache.put(synthetic_june_weather("2024-06-21"), "tmy", Location.bristol())

        pd.testing.assert_frame_equal(
            module_weather.get(Location.bristol()), synthetic_june_weather("2024-06-20"), check_exact=True
        )
        pd.testing.assert_frame_equal(
            default_weather().get(Location.bristol()), synthetic_june_weather("2024-06-21"), check_exact=True
        )
    """


def test_a_broader_scoped_fixture_passes_its_weather_provider_explicitly_and_default_weather_stays_the_tests_own(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """pytest sets the module fixture up first, inside the test's window; it hands its weather over as a provider, so default_weather() still reads the test's weather_cache."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_module_fixture_passes_its_provider") == {"passed": 1}


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
    import pandas as pd
    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import DEFAULT_CACHE_DIR, WeatherCache, default_weather
    from tests._synthetic_weather import synthetic_june_weather


    @pytest.fixture(autouse=True)
    def working_directory_caching_bristols_tmy(tmp_path, monkeypatch):
        WeatherCache(cache_dir=tmp_path / DEFAULT_CACHE_DIR).put(
            synthetic_june_weather("2024-06-21"), "tmy", Location.bristol()
        )
        monkeypatch.chdir(tmp_path)


    def test_a_fast_test_runs_first(weather_cache):
        pass


    @pytest.mark.slow
    def test_a_slow_test_reads_bristols_tmy():
        pd.testing.assert_frame_equal(
            default_weather().get(Location.bristol()), synthetic_june_weather("2024-06-21"), check_exact=True
        )


    @pytest.mark.e2e
    def test_an_e2e_test_reads_bristols_tmy():
        pd.testing.assert_frame_equal(
            default_weather().get(Location.bristol()), synthetic_june_weather("2024-06-21"), check_exact=True
        )
    """


def test_slow_and_e2e_tests_read_the_weather_cache_in_their_working_directory(
    suite: pytest.Pytester, offline_scenarios: ScenarioSession
) -> None:
    """Neither is guarded, so each reads the cache its working directory holds, not an empty one of its own, even after a fast test's window has closed."""
    run = offline_scenarios.run_in(suite)

    assert run.outcomes("test_slow_and_e2e_read_their_working_directory_cache") == {"passed": 3}


SCENARIOS = {
    "test_runs_a_root_unseeded": RUNS_A_ROOT_UNSEEDED,
    "test_submits_a_home_job": SUBMITS_A_HOME_JOB,
    "fetches_and_carries_on": FETCHES_AND_CARRIES_ON,
    "test_runs_a_child_that_fetches": RUNS_A_CHILD_THAT_FETCHES,
    "test_module_fixture_fetches": MODULE_FIXTURE_FETCHES,
    "test_module_fixture_looks_up_at_teardown": MODULE_FIXTURE_LOOKS_UP_AT_TEARDOWN,
    "test_module_fixture_passes_its_provider": MODULE_FIXTURE_PASSES_ITS_PROVIDER,
    "test_cache_directory_cannot_be_removed": CACHE_DIRECTORY_CANNOT_BE_REMOVED,
    "test_slow_requests_weather_cache": SLOW_REQUESTS_WEATHER_CACHE,
    "test_slow_and_e2e_read_their_working_directory_cache": SLOW_AND_E2E_READ_THEIR_WORKING_DIRECTORY_CACHE,
}


@pytest.fixture(scope="module")
def offline_scenarios() -> ScenarioSession:
    """The one session all the scenarios above run in, under the suite of whichever test here asks for its run first."""
    return ScenarioSession(SCENARIOS)
