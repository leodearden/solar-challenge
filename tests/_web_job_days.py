# SPDX-License-Identifier: AGPL-3.0-or-later
"""The clear June days a real web job simulates when a test sends it ``days``, for the test to seed as Bristol's TMY.

parse_date_range reads the window of every home and fleet job the web API runs or the assistant submits.
It runs a ``days`` other than the full-year sentinel over that many days from timebase.SHORT_WINDOW_START,
so these days start there.

Usage::

    pytest.importorskip("flask")

    from tests._web_job_days import web_job_days

    _JOB_DAYS = web_job_days(count=1)
    bristol_june_tmy = _JOB_DAYS.bristol_tmy_fixture()

    @pytest.mark.usefixtures("bristol_june_tmy")
    class TestRealHomeJob:
        def test_the_job_completes(self, client: FlaskClient) -> None:
            client.post("/api/simulate/home", json={"location": "bristol", "days": _JOB_DAYS.count})
"""

from __future__ import annotations

import pandas as pd

from solar_challenge.timebase import SHORT_WINDOW_START
from tests._seeded_tmy import ClearJuneDays


def web_job_days(*, count: int) -> ClearJuneDays:
    """The *count* clear June days from timebase.SHORT_WINDOW_START: the days a web job sent ``days`` = *count* simulates."""
    return ClearJuneDays(first_day=pd.Timestamp(SHORT_WINDOW_START), count=count)
