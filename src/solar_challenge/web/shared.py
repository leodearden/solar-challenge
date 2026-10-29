# SPDX-License-Identifier: AGPL-3.0-or-later
"""The accessors of the services the web application holds: its database, run storage, job manager and job stream policy."""

from __future__ import annotations

from flask import current_app

from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.sse import JobStreamPolicy
from solar_challenge.web.storage import RunStorage


def get_database() -> Database:
    """Return the app's Database, the one create_app registers in the current Flask app's extensions.

    Raises:
        TypeError: If the app's database extension is not a Database, naming the type it holds.
    """
    database = current_app.extensions["database"]
    if not isinstance(database, Database):
        raise TypeError(f"the app's database extension must be a Database, got {type(database).__name__}")
    return database


def get_storage() -> RunStorage:
    """Return the RunStorage singleton from current Flask app extensions."""
    return current_app.extensions["storage"]  # type: ignore[no-any-return]


def get_job_manager() -> JobManager:
    """Return the JobManager singleton from current Flask app extensions."""
    return current_app.extensions["job_manager"]  # type: ignore[no-any-return]


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
