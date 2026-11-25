# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_coreutils_timeout.py, the lane contract tests' reader of the DURATION a step's `timeout` prefix gives.

Each case reads the command of a throwaway lane step, spelled as coreutils 9.4's
`timeout --help` lists its options; no command is run.
"""

import re
from pathlib import Path

import pytest

from tests._coreutils_timeout import timeout_secs
from tests._orchestrator_config import OrchestratorCommand

_SUITE = "uv run --locked --extra dev pytest -m 'not slow' -p no:cacheprovider"

_LABEL = "lane job 'probe'"


def _step(command: str, directory: Path) -> OrchestratorCommand:
    """Return the lane step labelled _LABEL that runs *command* in *directory*."""
    return OrchestratorCommand(label=_LABEL, command=command, directory=directory, role="offline")


def _assert_names_the_step(refusal: pytest.ExceptionInfo[AssertionError], command: str) -> None:
    """Assert that *refusal*'s message names the step: its label and its command."""
    message = str(refusal.value)
    assert _LABEL in message and repr(command) in message, message


@pytest.mark.parametrize(
    ("prefix", "secs"),
    [
        pytest.param("timeout 10800", 10800, id="duration-alone"),
        pytest.param("timeout -k 60 1800", 1800, id="short-option-with-its-value-as-the-next-word"),
        pytest.param("timeout -k60 1.5h", 5400, id="short-option-with-its-value-joined"),
        pytest.param("timeout --kill-after=60 30m", 1800, id="long-option-with-its-value-after-an-equals-sign"),
        pytest.param("timeout --kill-after 20000 1800", 1800, id="long-option-with-its-value-as-the-next-word"),
        pytest.param("timeout --signal TERM --foreground .5m", 30, id="long-flag-after-a-long-options-value"),
        pytest.param("timeout --preserve-status -s KILL 1d", 86400, id="short-option-after-a-long-flag"),
        pytest.param("timeout -vk 20000 1800", 1800, id="short-options-sharing-a-word-the-last-taking-the-next"),
        pytest.param("timeout -vk20000 1800", 1800, id="short-options-sharing-a-word-with-the-last-ones-value"),
        pytest.param("timeout -v 10s", 10, id="short-flag-then-seconds"),
        pytest.param("timeout -- 2h", 7200, id="end-of-options"),
        pytest.param("timeout 5.", 5, id="number-ending-in-a-point"),
    ],
)
def test_the_duration_is_the_word_coreutils_timeout_reads_as_it(prefix: str, secs: float, tmp_path: Path) -> None:
    assert timeout_secs(_step(f"{prefix} {_SUITE}", tmp_path)) == secs


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        pytest.param(_SUITE, "does not start with `timeout`", id="no-timeout"),
        pytest.param(
            f"PLAYWRIGHT_SKIP_BROWSER_GC=1 timeout 600 {_SUITE}",
            "does not start with `timeout`",
            id="assignment-before-timeout",
        ),
        pytest.param(f"timeout 0 {_SUITE}", "DURATION '0' is 0", id="zero"),
        pytest.param(f"timeout -k 60 0.0m {_SUITE}", "DURATION '0.0m' is 0", id="zero-with-a-unit"),
    ],
)
def test_a_step_no_timeout_bounds_is_refused_naming_it(command: str, reason: str, tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match=re.escape(reason)) as refusal:
        timeout_secs(_step(command, tmp_path))

    _assert_names_the_step(refusal, command)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        pytest.param("timeout -k 60", "gives no DURATION", id="no-duration"),
        pytest.param(f"timeout --kill 60 1800 {_SUITE}", "option '--kill'", id="abbreviated-long-option"),
        pytest.param(f"timeout -f 1800 {_SUITE}", "option '-f'", id="short-option-timeout-lacks"),
        pytest.param(
            f"timeout --foreground=yes 1800 {_SUITE}", "option '--foreground=yes'", id="long-flag-given-a-value"
        ),
        pytest.param(f"timeout abc {_SUITE}", "DURATION 'abc'", id="word"),
        pytest.param(f"timeout 10x {_SUITE}", "DURATION '10x'", id="unknown-unit"),
        pytest.param(f"timeout 1e3 {_SUITE}", "DURATION '1e3'", id="exponent"),
        pytest.param(f"timeout inf {_SUITE}", "DURATION 'inf'", id="infinity"),
        pytest.param(f"timeout -- -1 {_SUITE}", "DURATION '-1'", id="negative-after-the-end-of-options"),
    ],
)
def test_a_spelling_whose_duration_cannot_be_told_is_refused_naming_the_step(
    command: str, reason: str, tmp_path: Path
) -> None:
    with pytest.raises(AssertionError, match=re.escape(reason)) as refusal:
        timeout_secs(_step(command, tmp_path))

    _assert_names_the_step(refusal, command)
