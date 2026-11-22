# SPDX-License-Identifier: AGPL-3.0-or-later
"""The services one dashboard app holds, and the accessors its views read them with: its Dashboard, which holds its run storage, its job manager, its database and its store lock, and the JobStreamPolicy its job progress streams are served under.

create_app builds one Dashboard per app and attaches it with attach_dashboard, and the root that
built the app closes it once it stops. The views read the current app's services through
get_storage, get_job_manager and get_database, which read its Dashboard with dashboard_of, and
through get_job_stream_policy, which reads the policy create_app registers beside the Dashboard,
not in it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from flask import Flask, current_app

from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.sse import JobStreamPolicy
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.store_lock import StoreLock

JobManagerFactory: TypeAlias = Callable[[RunStorage], JobManager]
"""Builds the JobManager an app's jobs run on, over the app's RunStorage, as create_app's jobs parameter takes it."""

_DASHBOARD_KEY = "dashboard"


@dataclass(frozen=True)
class Dashboard:
    """An app's run storage, the job manager whose jobs record their runs in it, the database it keeps them in, and the lock on that store.

    Its storage keeps its runs in its database: they are one store, which the lock holds for this process.
    """

    storage: RunStorage
    jobs: JobManager
    database: Database
    lock: StoreLock

    def __post_init__(self) -> None:
        """Refuse, with a ValueError naming both databases, a storage that keeps its runs in another database than this one."""
        if self.storage.database != self.database:
            raise ValueError(
                "A Dashboard's storage and database are one store: its storage keeps its runs in "
                f"{self.storage.database.path}, not in its database {self.database.path}"
            )

    def close(self) -> None:
        """Drop the queued jobs and wait for the running ones, then release the store's lock.

        The lock is released only once every running job has finished, so never while a job can still
        write the store, as StoreLock.release requires; if the jobs' shutdown raises, the lock is kept,
        and the end of the process frees it. Closing a closed Dashboard is harmless.
        """
        self.jobs.shutdown(wait=True)
        self.lock.release()


def attach_dashboard(app: Flask, dashboard: Dashboard) -> None:
    """Hold *dashboard* on *app*, where dashboard_of reads it."""
    app.extensions[_DASHBOARD_KEY] = dashboard


def dashboard_of(app: Flask) -> Dashboard:
    """The Dashboard attach_dashboard holds on *app*.

    Raises:
        LookupError: If *app* holds no Dashboard, naming the app.
    """
    dashboard = app.extensions.get(_DASHBOARD_KEY)
    if not isinstance(dashboard, Dashboard):
        raise LookupError(
            f"The Flask app {app.name!r} holds no Dashboard: create_app attaches one to each app it builds"
        )
    return dashboard


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
