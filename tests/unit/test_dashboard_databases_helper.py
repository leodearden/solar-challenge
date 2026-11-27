# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_dashboard_databases.py, which writes, reads and seeds the dashboard database files of tests: what it does with a path no database file is at."""

import functools
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._dashboard_databases import insert_runs_row, runs_rows_of, schema_of, user_version_of

FUNCTIONS_OF_AN_EXISTING_STORE = [
    pytest.param(schema_of, id="schema_of"),
    pytest.param(user_version_of, id="user_version_of"),
    pytest.param(runs_rows_of, id="runs_rows_of"),
    pytest.param(functools.partial(insert_runs_row, columns={"id": "run-1"}), id="insert_runs_row"),
]
"""Each function that reads or seeds a store a test already holds, as a function of the store's path alone."""


@pytest.mark.parametrize("function_of_an_existing_store", FUNCTIONS_OF_AN_EXISTING_STORE)
def test_reading_or_seeding_a_store_refuses_a_path_no_file_is_at_and_creates_no_database_there(
    function_of_an_existing_store: Callable[[Path], object], tmp_path: Path
) -> None:
    """sqlite3.connect creates the file it is pointed at, so without the refusal user_version_of would read 0 from a new, empty database where a test expected none."""
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match=re.escape(str(missing))):
        function_of_an_existing_store(missing)

    assert not missing.exists()
