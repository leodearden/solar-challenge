# SPDX-License-Identifier: AGPL-3.0-or-later
"""A migration of a dashboard store at schema version 1 refused at the step to version 3, once the step to version 2 has committed.

the_step_to_version_3_refused refuses, while its block runs, each update of the runs row of the
run installed from the pre_787_dispatch_fleet fixture. Of the migration steps only v3 rewrites
that row: v2 leaves that run's documents as they are, and a step updates a runs row only where
it changes one of its documents. So a migration of a store at version 1 holding that run
commits v2, brings the run files forward by v3, and is then refused at v3's transaction, the
store staying at version 2.

Usage::

    from tests._refused_migration_steps import the_step_to_version_3_refused

    with (
        the_step_to_version_3_refused(store, legacy_run_ids["pre_787_dispatch_fleet"]) as refusal,
        pytest.raises(MigrationRefused) as refused,
    ):
        migrate_store(store, store.parent)
    assert refused.value.step == MIGRATIONS[2]
    assert refusal in str(refused.value)
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from solar_challenge.web.database import Database, sql_string_literal

_REFUSAL = "the pre-787 fleet may not be updated"


@contextmanager
def the_step_to_version_3_refused(database_path: Path, pre_787_fleet_id: str) -> Iterator[str]:
    """Refuse each update of the runs row of run *pre_787_fleet_id*, the pre_787_dispatch_fleet fixture's, in the store at *database_path* until the block ends; give the block the refusal's text."""
    with Database(database_path).transaction() as conn:
        conn.execute(
            "CREATE TRIGGER refuse_pre_787_fleet_updates BEFORE UPDATE ON runs "
            f"WHEN OLD.id = {sql_string_literal(pre_787_fleet_id)} "
            f"BEGIN SELECT RAISE(ABORT, {sql_string_literal(_REFUSAL)}); END"
        )
    try:
        yield _REFUSAL
    finally:
        with Database(database_path).transaction() as conn:
            conn.execute("DROP TRIGGER refuse_pre_787_fleet_updates")
