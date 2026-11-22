# SPDX-License-Identifier: AGPL-3.0-or-later
"""The services one dashboard app holds, its Dashboard: its run storage, its job manager, its database and its store lock.

create_app builds one Dashboard per app and attaches it with attach_dashboard. The views reach it
through dashboard_of(current_app), as web/shared.py's accessors do, and the root that built the
app closes it once it stops.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from flask import Flask

from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager
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
