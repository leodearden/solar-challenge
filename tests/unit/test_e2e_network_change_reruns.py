"""Pins that tests/e2e/conftest.py runs a failed e2e test once more if, and only if, its browser lost a request to net::ERR_NETWORK_CHANGED during that attempt.

docs/e2e-network-change-reruns.md says why. A real browser cannot lose a request
to a network change on demand, so each scenario runs in a pytest session of its
own, under copies of this project's pyproject.toml and the e2e conftest, with
stand-ins for pytest-playwright's context and page fixtures.
"""

from pathlib import Path

import pytest
pytest.importorskip("flask")

E2E_CONFTEST = Path(__file__).parents[1] / "e2e" / "conftest.py"

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
def e2e_suite(pytester_importing_test_helpers: pytest.Pytester, project_root: Path) -> pytest.Pytester:
    """pytester, whose sessions read this project's pytest ini and run under the e2e conftest, with a stub browser context and page.

    The pytest ini is the one the offline lane's e2e job reads, so a pytest
    deprecation on the rerun path is an error here too.
    """
    pytester_importing_test_helpers.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    pytester_importing_test_helpers.makeconftest(E2E_CONFTEST.read_text(encoding="utf-8") + PLAYWRIGHT_FIXTURE_STUBS)
    return pytester_importing_test_helpers


def test_an_e2e_test_that_fails_after_its_browser_lost_a_request_to_a_network_change_runs_once_more(
    e2e_suite: pytest.Pytester,
) -> None:
    scenario = e2e_suite.makepyfile(
        f"""
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
    )

    result = e2e_suite.runpytest_subprocess(scenario, "-v", "-p", "no:cacheprovider")

    outcomes = result.parseoutcomes()
    assert (outcomes.get("passed", 0), outcomes.get("rerun", 0), outcomes.get("failed", 0)) == (2, 2, 0), outcomes
    for fixture in ("page", "context"):
        name = f"test_taking_{fixture}_loses_alpine_to_a_network_change_on_its_first_attempt"
        result.stdout.fnmatch_lines([f"*{name} RERUN*", f"*{name} PASSED*"])


def test_an_e2e_failure_without_a_request_lost_to_a_network_change_does_not_run_again(
    e2e_suite: pytest.Pytester,
) -> None:
    scenarios = e2e_suite.makepyfile(
        f"""
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
    )

    result = e2e_suite.runpytest_subprocess(scenarios, "-v", "-p", "no:cacheprovider")

    outcomes = result.parseoutcomes()
    assert (outcomes.get("failed", 0), outcomes.get("passed", 0), outcomes.get("rerun", 0)) == (3, 0, 0), outcomes
    result.stdout.no_fnmatch_line("* RERUN*")


def test_an_e2e_test_still_failing_after_its_rerun_lists_the_requests_its_last_attempt_lost_to_network_changes(
    e2e_suite: pytest.Pytester,
) -> None:
    scenario = e2e_suite.makepyfile(
        f"""
        from collections import Counter

        import pytest

        LOST_ON_ATTEMPT = {{1: {ALPINE_CORE!r}, 2: {PRESETS_API!r}}}

        attempts = Counter()


        def test_loses_a_different_request_to_a_network_change_on_each_attempt(context):
            attempts["lossy"] += 1
            context.fail_request(LOST_ON_ATTEMPT[attempts["lossy"]], "net::ERR_NETWORK_CHANGED")
            pytest.fail("the page never became ready")
        """
    )

    result = e2e_suite.runpytest_subprocess(scenario, "-v", "-p", "no:cacheprovider")

    outcomes = result.parseoutcomes()
    assert (outcomes.get("failed", 0), outcomes.get("rerun", 0), outcomes.get("passed", 0)) == (1, 1, 0), outcomes
    result.stdout.fnmatch_lines([f"GET {PRESETS_API}"])
    result.stdout.no_fnmatch_line(f"GET {ALPINE_CORE}")
