# SPDX-License-Identifier: AGPL-3.0-or-later
"""The failure sections of a pytest run's terminal report, which hold each failing test's traceback and captured output.

pytest opens each section of its report with a header line, the section's title
between runs of '='. The failure sections are its ERRORS and FAILURES sections.

Usage::

    from tests._pytest_report import failure_sections

    for section in failure_sections(result.stdout):
        print(section.start, section.text)
"""

import re
from dataclasses import dataclass
from itertools import pairwise

# The line TerminalWriter.sep("=", title) prints to open each section of pytest's report.
_SECTION_HEADER = re.compile(r"^=+ (?P<title>.+?) =+$", re.MULTILINE)

_FAILURE_TITLES = frozenset({"ERRORS", "FAILURES"})


@dataclass(frozen=True)
class ReportSection:
    """A section of a pytest report: the offset in the report at which it starts, and its text, from its header line on."""

    start: int
    text: str


def failure_sections(report: str) -> list[ReportSection]:
    """Return the ERRORS and FAILURES sections of *report*, a pytest run's terminal report, in report order.

    A section runs from the line that opens it to the line that opens the next
    section, or to the end of *report*.
    """
    headers = list(_SECTION_HEADER.finditer(report))
    bounds = pairwise([*(header.start() for header in headers), len(report)])
    return [
        ReportSection(start, report[start:end])
        for header, (start, end) in zip(headers, bounds, strict=True)
        if header["title"] in _FAILURE_TITLES
    ]
