# SPDX-License-Identifier: AGPL-3.0-or-later
"""The event-day tests' run of calendar dates: every date from a first to a last, as a simulated period covers them.

Usage::

    from tests._calendar_dates import every_date

    january = every_date(date(2024, 1, 1), date(2024, 1, 31))
"""

from datetime import date, timedelta


def every_date(first: date, last: date) -> tuple[date, ...]:
    """Every date from *first* to *last*, both included, in order."""
    return tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))
