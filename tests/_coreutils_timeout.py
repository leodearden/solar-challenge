# SPDX-License-Identifier: AGPL-3.0-or-later
"""The DURATION of the coreutils `timeout` an orchestrator command starts with, read as coreutils reads it.

dark-factory-orchestrator.yaml bounds each step of an offline-lane job with a
`timeout` prefix, as in `timeout -k 60 10800 uv run ... pytest ...`, and a lane
contract test checks that bound against what the step runs. timeout_secs reads
the bound as coreutils 9.4's `timeout` does, or fails naming the step: it never
reads another word as the DURATION.

Usage::

    from tests._coreutils_timeout import timeout_secs

    bound_secs = timeout_secs(lane_job_steps(project_root, "e2e").suite)
"""

import re
import shlex
from collections.abc import Sequence

from tests._orchestrator_config import OrchestratorCommand

_END_OF_OPTIONS = "--"

_LONG_OPTIONS_TAKING_A_VALUE = frozenset({"--kill-after", "--signal"})

_LONG_FLAGS = frozenset({"--foreground", "--preserve-status", "--verbose"})

_SHORT_OPTIONS_TAKING_A_VALUE = frozenset("ks")

_SHORT_FLAGS = frozenset("v")

_DURATION = re.compile(r"(?P<number>[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?P<unit>[smhd]?)")

_SECONDS_PER_UNIT = {"": 1, "s": 1, "m": 60, "h": 60 * 60, "d": 24 * 60 * 60}


def timeout_secs(step: OrchestratorCommand) -> float:
    """Return the DURATION, in seconds, of the coreutils `timeout` *step*'s command starts with.

    The options before it are read as `timeout --help` lists them: -k,
    --kill-after, -s and --signal take a value, joined to the option or as the
    next word, and -v, --verbose, --foreground and --preserve-status take none.
    Short options may share a word, as in -vk 60, and `--` ends the options. The
    DURATION is a decimal number with an optional unit: s, the default, m, h or
    d. It asserts, naming the step, that the command starts with `timeout`, that
    each option is one of those, spelled in full, and that the DURATION is a
    number so written and not 0, which coreutils reads as no timeout at all.
    """
    words = shlex.split(step.command)
    assert words[:1] == ["timeout"], (
        f"the {step.label} runs {step.command!r}, which does not start with `timeout`, so no `timeout` bounds its "
        "run; docs/orchestrator-config.md §8 says why each lane step is bounded"
    )
    operands = _operands(step, words[1:])
    assert operands, f"the {step.label} runs {step.command!r}, whose `timeout` gives no DURATION after its options"
    duration = operands[0]
    match = _DURATION.fullmatch(duration)
    assert match, (
        f"the {step.label} runs {step.command!r}, whose `timeout` DURATION {duration!r} is not a decimal number with "
        "an optional unit s, m, h or d, so its bound cannot be read"
    )
    secs = float(match["number"]) * _SECONDS_PER_UNIT[match["unit"]]
    assert secs > 0, (
        f"the {step.label} runs {step.command!r}, whose `timeout` DURATION {duration!r} is 0, which coreutils reads "
        "as no timeout at all, so nothing bounds its run"
    )
    return secs


def _operands(step: OrchestratorCommand, arguments: Sequence[str]) -> Sequence[str]:
    """Return `timeout`'s *arguments* from the first that is neither an option nor an option's value: the DURATION, then the command it bounds."""
    index = 0
    while index < len(arguments) and _is_option(arguments[index]):
        if arguments[index] == _END_OF_OPTIONS:
            return arguments[index + 1 :]
        index += _words_of_option(step, arguments[index])
    return arguments[index:]


def _is_option(word: str) -> bool:
    """Whether `timeout` reads *word*, met among its options, as an option: a word starting with `-`, other than `-` alone."""
    return word.startswith("-") and word != "-"


def _words_of_option(step: OrchestratorCommand, option: str) -> int:
    """Return how many words `timeout` reads as *option*: 1, or 2 when the option's value is the next word.

    It asserts, naming the step, that *option* is one `timeout --help` lists, spelled in full.
    """
    words = _words_of_long_option(option) if option.startswith("--") else _words_of_short_options(option)
    assert words is not None, (
        f"the {step.label} runs {step.command!r}, whose `timeout` option {option!r} is none of those `timeout --help` "
        "lists, spelled in full, so which word is its DURATION cannot be told; spell each option as listed there"
    )
    return words


def _words_of_long_option(option: str) -> int | None:
    """Return how many words `timeout` reads as the long *option*, None if it is none of its long options spelled in full."""
    name, equals, _ = option.partition("=")
    if name in _LONG_OPTIONS_TAKING_A_VALUE:
        return 1 if equals else 2
    if name in _LONG_FLAGS and not equals:
        return 1
    return None


def _words_of_short_options(option: str) -> int | None:
    """Return how many words `timeout` reads as the short options sharing *option*, None if a letter is none of them.

    An option taking a value takes the rest of the word, or the next word when no rest is left.
    """
    letters = option[1:]
    for index, letter in enumerate(letters):
        if letter in _SHORT_OPTIONS_TAKING_A_VALUE:
            return 1 if letters[index + 1 :] else 2
        if letter not in _SHORT_FLAGS:
            return None
    return 1
