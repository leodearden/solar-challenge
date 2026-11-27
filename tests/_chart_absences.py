# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reasons solar_challenge.web.charts gives for a chart that applies to a run or a sweep but
has nothing to draw, written out as the chart's card shows them, so every test that expects a
reason reads the one copy here.

A builder test compares a panel's absence_reason with one, a page test reads one after its
chart's title, and an e2e test reads one in the browser.

Usage::

    from tests._chart_absences import SANKEY_REASON, monthly_reason, seasonal_reason

    assert sankey_diagram(summary).absence_reason == SANKEY_REASON
    assert monthly_summary(make_sinusoidal_sim_results(days=30)).absence_reason == monthly_reason(30)
"""

SANKEY_REASON = "No energy flowed in this run: every flow is 0.01 kWh or less."


def monthly_reason(days: int) -> str:
    """Why a run whose window covers *days* calendar days, fewer than 90, has no monthly summary."""
    return f"The monthly summary needs at least 90 days; this run covers {days}."


def seasonal_reason(days: int) -> str:
    """Why a run whose window covers *days* calendar days, fewer than 180, has no seasonal comparison."""
    return f"The seasonal comparison needs at least 180 days; this run covers {days}."


def sweep_reason(points: int) -> str:
    """Why a sweep of *points* finished points, fewer than 2, has no sweep chart."""
    return f"The sweep chart needs at least 2 finished points; this sweep has {points}."
