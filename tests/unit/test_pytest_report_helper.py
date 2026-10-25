# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pytest_report.py, which finds the failure sections of a pytest run's terminal report.

Each report is canned text laid out as pytest prints it. The describe_pytest_outcome
tests in tests/unit/test_command_runner_helper.py read a real pytest run's report.
"""

import pytest

from tests._pytest_report import failure_sections


def _separator(sepchar: str, title: str) -> str:
    """Return the line TerminalWriter.sep(sepchar, title) prints in pytest's report: runs of *sepchar* either side of *title*."""
    fill = sepchar * 30
    return f"{fill} {title} {fill}\n"


_SESSION_START = _separator("=", "test session starts") + "collected 3 items\n\n"

_TAIL = (
    _separator("=", "warnings summary")
    + "  an outer warning\n"
    + _separator("=", "short test summary info")
    + "FAILED test_outer.py::test_runs_a_nested_session\n"
    + _separator("=", "2 failed, 1 warning in 0.02s")
)

_NESTED_REPORT = (
    _separator("=", "test session starts")
    + "collected 1 item\n\n"
    + _separator("=", "FAILURES")
    + _separator("_", "test_inner")
    + "E   AssertionError: the inner test failed\n"
    + _separator("=", "warnings summary")
    + "  an inner warning\n"
    + _separator("=", "short test summary info")
    + "FAILED test_inner.py::test_inner\n"
    + _separator("=", "1 failed, 1 warning in 0.01s")
)

# pytest -q prints no session header, and no '=' runs around its stats line.
_QUIET_NESTED_REPORT = (
    _separator("=", "FAILURES")
    + _separator("_", "test_inner")
    + "E   AssertionError: the inner test failed\n"
    + _separator("=", "short test summary info")
    + "FAILED test_inner.py::test_inner\n"
    + "1 failed in 0.01s\n"
)

_NESTED_REPORT_WITH_AN_ERROR = (
    _separator("=", "test session starts")
    + "collected 2 items\n\n"
    + _separator("=", "ERRORS")
    + _separator("_", "ERROR at setup of test_inner_errs")
    + "E   RuntimeError: the inner fixture failed\n"
    + _separator("=", "FAILURES")
    + _separator("_", "test_inner")
    + "E   AssertionError: the inner test failed\n"
    + _separator("=", "short test summary info")
    + "FAILED test_inner.py::test_inner\n"
    + _separator("=", "1 failed, 1 error in 0.01s")
)

_PASSING_NESTED_REPORT = (
    _separator("=", "test session starts")
    + "collected 1 item\n\n"
    + _separator("=", "warnings summary")
    + "  an inner warning\n"
    + _separator("=", "1 passed, 1 warning in 0.01s")
)


@pytest.mark.parametrize(
    "printed",
    [
        pytest.param(_NESTED_REPORT, id="nested-report"),
        pytest.param(_QUIET_NESTED_REPORT, id="quiet-nested-report"),
        pytest.param(_NESTED_REPORT_WITH_AN_ERROR, id="nested-report-with-an-error"),
    ],
)
def test_a_report_that_a_failing_test_printed_is_part_of_its_failures_section(printed: str) -> None:
    """pytest prints a test's captured output raw, so a nested run's report, such as pytester prints, keeps its header lines."""
    failures = (
        _separator("=", "FAILURES")
        + _separator("_", "test_runs_a_nested_session")
        + "E   AssertionError: the outer test failed\n"
        + _separator("-", "Captured stdout call")
        + printed
        + _separator("_", "test_fails_later")
        + "E   AssertionError: the later test failed\n"
    )

    sections = failure_sections(_SESSION_START + failures + _TAIL)

    assert [(section.start, section.text) for section in sections] == [(len(_SESSION_START), failures)]


def test_a_report_that_an_erroring_test_printed_is_part_of_its_errors_section() -> None:
    errors = (
        _separator("=", "ERRORS")
        + _separator("_", "ERROR at setup of test_runs_a_nested_session")
        + "E   RuntimeError: the outer fixture failed\n"
        + _separator("-", "Captured stdout setup")
        + _PASSING_NESTED_REPORT
    )
    failures = (
        _separator("=", "FAILURES") + _separator("_", "test_fails") + "E   AssertionError: the outer test failed\n"
    )
    report = _SESSION_START + errors + failures + _TAIL

    sections = failure_sections(report)

    assert [(section.start, section.text) for section in sections] == [
        (report.index(errors), errors),
        (report.index(failures), failures),
    ]


def test_a_report_cut_short_in_a_failure_section_keeps_that_section_to_its_end() -> None:
    """As when pytest is killed while it prints its report, before its stats line."""
    failures = _separator("=", "FAILURES") + _separator("_", "test_fails") + "E   AssertionError: the outer"

    sections = failure_sections(_SESSION_START + failures)

    assert [(section.start, section.text) for section in sections] == [(len(_SESSION_START), failures)]


@pytest.mark.parametrize(
    "report",
    [
        pytest.param("", id="no-report"),
        pytest.param(
            _SESSION_START + "test_outer.py::test_passes PASSED\n" + _separator("=", "1 passed in 0.01s"),
            id="green-report",
        ),
    ],
)
def test_a_report_with_no_failure_section_has_none(report: str) -> None:
    assert failure_sections(report) == []
