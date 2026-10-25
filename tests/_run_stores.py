# SPDX-License-Identifier: AGPL-3.0-or-later
"""The RunStorages that belong to no app, for tests that drive the run store directly rather than through the dashboard.

empty_run_storage builds a new, empty store in a directory a test gives it. The RunStorage
an app keeps its runs in is tests/_web_app.py's run_storage_of(app).

Usage::

    from tests._run_stores import empty_run_storage

    storage = empty_run_storage(tmp_path)
    storage.save_home_run_from_results("home-1", config, results, name="North Roof")
"""

from __future__ import annotations

from pathlib import Path

from solar_challenge.web.schema import open_database
from solar_challenge.web.storage import RunStorage


def empty_run_storage(directory: Path) -> RunStorage:
    """Return a RunStorage of no app over a new, empty store in *directory*.

    Its database is a new store open_database creates at directory/runs.db, and its run files
    are in directory/data, an empty directory of their own, so what a save writes is all that
    directory holds. *directory* must hold neither yet.
    """
    database_path, data_dir = directory / "runs.db", directory / "data"
    assert not database_path.exists() and not data_dir.exists(), (
        f"{directory} already holds runs.db or data, so a RunStorage built there would not be empty: "
        "open_database opens the store already there"
    )
    data_dir.mkdir(parents=True)
    return RunStorage(open_database(database_path), data_dir)
