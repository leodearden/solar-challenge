# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_job_days.py, the clear June days a real web job simulates when a test sends it days."""

import pytest

pytest.importorskip("flask")

from solar_challenge.web.simulation_params import parse_date_range
from tests._web_job_days import web_job_days


@pytest.mark.parametrize("count", [1, 3])
def test_a_job_sent_days_runs_over_exactly_the_web_job_days_of_that_count(count: int) -> None:
    first_day, last_day = web_job_days(count=count).window()

    assert parse_date_range({"days": count}) == (first_day.date().isoformat(), last_day.date().isoformat())
