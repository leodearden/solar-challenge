"""Pins that tests/e2e/conftest.py runs a failed e2e test once more if, and only if, its browser lost a request to net::ERR_NETWORK_CHANGED during that attempt.

docs/e2e-network-change-reruns.md says why. A real browser cannot lose a request
to a network change on demand, so the scenarios share one pytest session of
their own (tests/_scenario_session.py), under copies of this project's
pyproject.toml and the e2e conftest, with stand-ins for pytest-playwright's
context and page fixtures.
"""

from pathlib import Path

import pytest

from tests._scenario_session import ScenarioSession

pytest.importorskip("flask")

ALPINE_CORE = "http://127.0.0.1:5000/static/vendor/alpinejs/alpinejs-3.14.8.min.js"

PRESETS_API = "http://127.0.0.1:5000/api/presets"

PLAYWRIGHT_FIXTURE_STUBS = '''

# ---------------------------------------------------------------------------
# Stand-ins for pytest-playwright's context and page fixtures
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class FailedRequest:
    """What a requestfailed listener reads of a Playwright Request: its failure is the browser's error text."""

    method: str
    url: str
    failure: str


class BrowserContextStub:
    """Calls the requestfailed listeners registered with on(), as a Playwright BrowserContext does, for each request a test fails."""

    def __init__(self):
        self._requestfailed_listeners = []

    def on(self, event, listener):
        if event == "requestfailed":
            self._requestfailed_listeners.append(listener)

    def fail_request(self, url, failure):
        for listener in self._requestfailed_listeners:
            listener(FailedRequest(method="GET", url=url, failure=failure))


@dataclass(frozen=True)
class PageStub:
    """What a test reads of a Playwright Page here: the browser context the page belongs to."""

    context: BrowserContextStub


@pytest.fixture
def context():
    """A BrowserContextStub; this conftest fixture overrides pytest-playwright's context when the e2e extra is installed."""
    return BrowserContextStub()


@pytest.fixture
def page(context):
    """A PageStub in the test's context, as pytest-playwright's page is a page of its context; it overrides that fixture likewise."""
    return PageStub(context)
'''


@pytest.fixture
def e2e_suite(
    pytester_importing_test_helpers: pytest.Pytester, project_root: Path, e2e_conftest: Path
) -> pytest.Pytester:
    """pytester, whose sessions read this project's pytest ini and run under the e2e conftest, with a stub browser context and page.

    The pytest ini is the one the offline lane's e2e job reads, so a pytest
    deprecation on the rerun path is an error here too.
    """
    pytester_importing_test_helpers.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    pytester_importing_test_helpers.makeconftest(e2e_conftest.read_text(encoding="utf-8") + PLAYWRIGHT_FIXTURE_STUBS)
    return pytester_importing_test_helpers


NETWORK_CHANGE_THEN_PASS = f"""
    from collections import Counter

    import pytest

    ALPINE_CORE = {ALPINE_CORE!r}

    attempts = Counter()


    def lose_alpine_to_a_network_change_on_the_first_attempt(context, test):
        attempts[test] += 1
        if attempts[test] == 1:
            context.fail_request(ALPINE_CORE, "net::ERR_NETWORK_CHANGED")
            pytest.fail("Alpine never started")


    def test_taking_page_loses_alpine_to_a_network_change_on_its_first_attempt(page):
        lose_alpine_to_a_network_change_on_the_first_attempt(page.context, "page")


    def test_taking_context_loses_alpine_to_a_network_change_on_its_first_attempt(context):
        lose_alpine_to_a_network_change_on_the_first_attempt(context, "context")
    """


def test_an_e2e_test_that_fails_after_its_browser_lost_a_request_to_a_network_change_runs_once_more(
    e2e_suite: pytest.Pytester, e2e_scenarios: ScenarioSession
) -> None:
    run = e2e_scenarios.run_in(e2e_suite)

    assert run.outcomes("test_network_change_then_pass") == {"rerun": 2, "passed": 2}
    for fixture in ("page", "context"):
        name = f"test_taking_{fixture}_loses_alpine_to_a_network_change_on_its_first_attempt"
        run.result.stdout.fnmatch_lines([f"*{name} RERUN*", f"*{name} PASSED*"])


FAILS_WITHOUT_NETWORK_CHANGE = f"""
    import pytest

    ALPINE_CORE = {ALPINE_CORE!r}


    def test_fails_having_lost_no_request(context):
        pytest.fail("Alpine never started")


    def test_fails_having_lost_a_request_to_another_error(context):
        context.fail_request(ALPINE_CORE, "net::ERR_CONNECTION_REFUSED")
        pytest.fail("Alpine never started")


    def test_fails_without_a_browser():
        pytest.fail("the live server answered 500")
    """


def test_an_e2e_failure_without_a_request_lost_to_a_network_change_does_not_run_again(
    e2e_suite: pytest.Pytester, e2e_scenarios: ScenarioSession
) -> None:
    run = e2e_scenarios.run_in(e2e_suite)

    assert run.outcomes("test_fails_without_network_change") == {"failed": 3}


RERUN_LISTS_LAST_ATTEMPT = f"""
    from collections import Counter

    import pytest

    LOST_ON_ATTEMPT = {{1: {ALPINE_CORE!r}, 2: {PRESETS_API!r}}}

    attempts = Counter()


    def test_loses_a_different_request_to_a_network_change_on_each_attempt(context):
        attempts["lossy"] += 1
        context.fail_request(LOST_ON_ATTEMPT[attempts["lossy"]], "net::ERR_NETWORK_CHANGED")
        pytest.fail("the page never became ready")
    """


def test_an_e2e_test_still_failing_after_its_rerun_lists_the_requests_its_last_attempt_lost_to_network_changes(
    e2e_suite: pytest.Pytester, e2e_scenarios: ScenarioSession
) -> None:
    """Its own failure report lists, right after its traceback, only the request its last attempt lost."""
    run = e2e_scenarios.run_in(e2e_suite)

    assert run.outcomes("test_rerun_lists_last_attempt") == {"rerun": 1, "failed": 1}
    run.result.stdout.fnmatch_lines(
        [
            "test_rerun_lists_last_attempt.py:*: in test_loses_a_different_request_to_a_network_change_on_each_attempt",
            '    pytest.fail("the page never became ready")',
            "E   Failed: the page never became ready",
            "*- requests Chromium failed with net::ERR_NETWORK_CHANGED -*",
            f"GET {PRESETS_API}",
            "docs/e2e-network-change-reruns.md says *",
        ],
        consecutive=True,
    )


SCENARIOS = {
    "test_network_change_then_pass": NETWORK_CHANGE_THEN_PASS,
    "test_fails_without_network_change": FAILS_WITHOUT_NETWORK_CHANGE,
    "test_rerun_lists_last_attempt": RERUN_LISTS_LAST_ATTEMPT,
}


@pytest.fixture(scope="module")
def e2e_scenarios() -> ScenarioSession:
    """The one session all the scenarios above run in, under the e2e_suite of whichever test here asks for its run first."""
    return ScenarioSession(SCENARIOS, "-v", "--tb=short", "-p", "no:cacheprovider")
