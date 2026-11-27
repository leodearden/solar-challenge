# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the progress tracker, simulate/partials/progress-tracker.html, in which the simulate
pages follow a submitted job: a finished job's message is drawn in the role palette the token
file's tailwind.status group names for the job's run status, as its run status badge is."""

import pytest

pytest.importorskip("flask")
from flask import Flask

from tests._css_classes import names_palette
from tests._html_page import element_attributes


def _progress_tracker(app: Flask) -> str:
    """The markup *app*'s progress_tracker macro draws."""
    partial = app.jinja_env.get_template("simulate/partials/progress-tracker.html")
    return str(partial.module.progress_tracker())


@pytest.mark.parametrize(
    ("status", "message_classes"),
    [
        pytest.param(
            "completed",
            {"text-status-completed-600", "dark:text-status-completed-400"},
            id="completed",
        ),
        pytest.param(
            "failed",
            {
                "bg-status-failed-50",
                "dark:bg-status-failed-900/20",
                "border-status-failed-200",
                "dark:border-status-failed-800",
                "text-status-failed-700",
                "dark:text-status-failed-400",
                "text-status-failed-600",
                "dark:text-status-failed-300",
            },
            id="failed",
        ),
    ],
)
def test_the_progress_tracker_draws_a_finished_jobs_message_in_its_run_status_palette(
    app: Flask, status: str, message_classes: set[str]
) -> None:
    """The classes of the tracker's divs and paragraphs that name status-<status> are its message's for that status."""
    tracker = _progress_tracker(app)

    status_classes = {
        css_class
        for tag in ("div", "p")
        for element in element_attributes(tracker, tag)
        for css_class in (element.get("class") or "").split()
        if names_palette(css_class, f"status-{status}")
    }

    assert status_classes == message_classes
