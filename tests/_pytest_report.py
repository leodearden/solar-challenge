# SPDX-License-Identifier: AGPL-3.0-or-later
"""The failure sections of a pytest run's terminal report, which hold each failing test's traceback and captured output.

pytest opens each section of its report with a header line, the section's title
between runs of '='. It prints its failure sections, ERRORS then FAILURES, then
its tail: the sections of _TAIL_TITLES, in that order, then its stats line. A
test's captured output is printed raw inside a failure section, so it can hold
header lines of its own, such as those of a nested pytest run's report, which
pytester prints; such a line ends no section.

Usage::

    from tests._pytest_report import failure_sections

    for section in failure_sections(result.stdout):
        print(section)
"""

import re
from collections.abc import Sequence
from itertools import pairwise

# The line TerminalWriter.sep("=", title) prints to open each section of pytest's report.
_SECTION_HEADER = re.compile(r"^=+ (?P<title>.+?) =+$", re.MULTILINE)

_FAILURE_TITLES = ("ERRORS", "FAILURES")

# The sections pytest prints after its failure sections and before its stats line, in the order
# TerminalReporter.pytest_terminal_summary prints them.
_TAIL_TITLES = (
    "XFAILURES",
    "warnings summary",
    "PASSES",
    "XPASSES",
    "short test summary info",
    "warnings summary (final)",
)


def failure_sections(report: str) -> list[str]:
    """Return the text of each ERRORS and FAILURES section of *report*, a pytest run's terminal report, in report order.

    pytest prints each of them at most once, ERRORS first, so a header line opens
    one only if its title comes later in _FAILURE_TITLES than that of the section
    open before it; any other is part of a test's captured output. A section runs
    from its header line to the header line of the next one, or to the report's
    tail.
    """
    headers = list(_SECTION_HEADER.finditer(report))
    tail = _tail_start(headers)
    starts = []
    titles_to_come: tuple[str, ...] = _FAILURE_TITLES
    for header in headers[:tail]:
        if header["title"] in titles_to_come:
            starts.append(header.start())
            titles_to_come = titles_to_come[titles_to_come.index(header["title"]) + 1 :]
    end = headers[tail].start() if tail < len(headers) else len(report)
    return [report[start:stop] for start, stop in pairwise([*starts, end])]


def _tail_start(headers: Sequence[re.Match[str]]) -> int:
    """Return the index in *headers* of the first header line of the report's tail, or len(*headers*) if it has none.

    The tail holds the sections of _TAIL_TITLES, each at most once and in that
    order, then the stats line, the report's last header line. So it runs back from
    that line until a header line out of that order: a failure section's, a
    plugin's, or one that a test's captured output printed, such as the stats line
    of a nested run. A report whose last header line opens a failure section was
    cut short in it, so it has no tail.
    """
    if not headers or headers[-1]["title"] in _FAILURE_TITLES:
        return len(headers)
    start = len(headers) - 1
    titles_before: tuple[str, ...] = _TAIL_TITLES
    while start > 0 and headers[start - 1]["title"] in titles_before:
        titles_before = titles_before[: titles_before.index(headers[start - 1]["title"])]
        start -= 1
    return start
