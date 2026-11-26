# SPDX-License-Identifier: AGPL-3.0-or-later
"""error_records: the records a test's caplog captured at ERROR or above.

A web boundary answers a ConfigurationError as a refusal and logs nothing; it logs any
other ValueError it answers once at ERROR, through request_boundary.refusal_text, as a
probable defect. A test reads that record, or its absence, here.
"""

import logging

import pytest


def error_records(caplog: pytest.LogCaptureFixture, logger: str | None = None) -> list[logging.LogRecord]:
    """The records *caplog* captured at ERROR or above, in the order they were logged: only those of the logger named *logger*, when it names one."""
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR and (logger is None or record.name == logger)
    ]
