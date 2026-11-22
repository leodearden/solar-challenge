# SPDX-License-Identifier: AGPL-3.0-or-later
"""The accessors of the services the web application holds: the database, run storage and job manager of its Dashboard, and its job stream policy."""

from __future__ import annotations

from flask import current_app

from solar_challenge.web.dashboard import dashboard_of
from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.sse import JobStreamPolicy
from solar_challenge.web.storage import RunStorage


def get_database() -> Database:
    """Return the Database the current app's Dashboard keeps its tables in.

    Raises:
        LookupError: If the current app holds no Dashboard, naming the app.
    """
    return dashboard_of(current_app).database


def get_storage() -> RunStorage:
    """Return the RunStorage the current app's Dashboard keeps its runs in.

    Raises:
        LookupError: If the current app holds no Dashboard, naming the app.
    """
    return dashboard_of(current_app).storage


def get_job_manager() -> JobManager:
    """Return the JobManager the current app's Dashboard runs its jobs on.

    Raises:
        LookupError: If the current app holds no Dashboard, naming the app.
    """
    return dashboard_of(current_app).jobs


def get_job_stream_policy() -> JobStreamPolicy:
    """Return the JobStreamPolicy the app's job progress streams are served under, the one create_app registers in the current Flask app's extensions.

    Raises:
        TypeError: If the app's job_stream_policy extension is not a JobStreamPolicy, naming the type it holds.
    """
    policy = current_app.extensions["job_stream_policy"]
    if not isinstance(policy, JobStreamPolicy):
        raise TypeError(
            f"the app's job_stream_policy extension must be a JobStreamPolicy, got {type(policy).__name__}"
        )
    return policy
