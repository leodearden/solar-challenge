# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_run_stores.py, which builds the RunStorages of no app that tests driving the run store directly use."""

import re
from pathlib import Path

import pytest

from solar_challenge.web.schema import open_database
from solar_challenge.web.storage import RunQuery
from tests._run_stores import empty_run_storage


def test_an_empty_run_storage_holds_no_run_and_its_run_files_directory_holds_nothing(tmp_path: Path) -> None:
    storage = empty_run_storage(tmp_path)

    assert storage.page_runs(RunQuery()).total == 0
    assert list(storage.data_dir.iterdir()) == []


def test_an_empty_run_storage_keeps_a_store_at_the_schema_version_in_the_given_directory(tmp_path: Path) -> None:
    storage = empty_run_storage(tmp_path)

    assert storage.database.path.is_file()
    assert open_database(storage.database.path) == storage.database
    assert storage.database.path.is_relative_to(tmp_path)
    assert storage.data_dir.is_relative_to(tmp_path)


def test_empty_run_storage_refuses_a_directory_that_already_holds_its_store(tmp_path: Path) -> None:
    """open_database would open the store already there, so the RunStorage would not be empty."""
    empty_run_storage(tmp_path)

    with pytest.raises(AssertionError, match=re.escape(str(tmp_path))):
        empty_run_storage(tmp_path)
