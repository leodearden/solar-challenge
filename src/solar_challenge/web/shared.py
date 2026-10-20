# SPDX-License-Identifier: AGPL-3.0-or-later
"""The accessors of the services the web application holds: its run storage and its job manager."""

from __future__ import annotations

from flask import current_app

from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RunStorage


def get_storage() -> RunStorage:
    """Return the RunStorage singleton from current Flask app extensions."""
    return current_app.extensions["storage"]  # type: ignore[no-any-return]


def get_job_manager() -> JobManager:
    """Return the JobManager singleton from current Flask app extensions."""
    return current_app.extensions["job_manager"]  # type: ignore[no-any-return]
