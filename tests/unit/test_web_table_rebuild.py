# SPDX-License-Identifier: AGPL-3.0-or-later
"""The table mechanism of solar_challenge.web.database, on toy tables rather than the dashboard's.

A TableSchema renders the CREATE TABLE statement a new database stores for it, and create_table
creates the table and its indexes. rebuild_table rebuilds a table to a schema inside its caller's
transaction, keeping every row, so the file then holds the schema a new file created from that
schema holds. It refuses, before it renames anything, a table another table's foreign key
references. RowRefused names the row a migration cannot keep, the table and the column.
"""

from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pytest

from solar_challenge.web.database import Database, RowRefused, TableSchema, check_one_of, create_table, rebuild_table
from tests._dashboard_databases import schema_of

ITEMS = TableSchema(
    name="items",
    columns=(
        ("id", "TEXT PRIMARY KEY"),
        ("label", "TEXT NOT NULL"),
        ("kind", f"TEXT {check_one_of('kind', ('small', 'large'))}"),
    ),
    indexes=("CREATE INDEX idx_items_kind ON items(kind)",),
)
"""The toy table's current schema: every item is labelled, and is small or large."""

OLD_ITEMS = TableSchema(
    name="items",
    columns=(
        ("id", "TEXT PRIMARY KEY"),
        ("label", "TEXT"),
        ("kind", f"TEXT {check_one_of('kind', ('small', 'large', 'medium'))}"),
    ),
    indexes=("CREATE INDEX idx_items_kind ON items(kind)",),
)
"""The toy table's older schema: an item may be unlabelled, and may be medium too."""

Item = tuple[str, str | None, str | None]


def _created_from(schema: TableSchema, path: Path, items: Sequence[Item] = ()) -> Path:
    """A new database file at *path* holding the table *schema* states, created by create_table, and *items* in it."""
    with closing(Database(path).connect()) as conn:
        conn.execute("BEGIN")
        create_table(conn, schema)
        conn.executemany("INSERT INTO items (id, label, kind) VALUES (?, ?, ?)", items)
        conn.commit()
    return path


def _rebuilt(path: Path, schema: TableSchema) -> None:
    """Rebuild the items table of the database at *path* to *schema*, as rebuild_table does, in a transaction this commits."""
    with closing(Database(path).connect()) as conn:
        conn.execute("BEGIN")
        rebuild_table(conn, schema)
        conn.commit()


def _items(path: Path) -> list[Item]:
    """Every row of the items table of the database at *path*, by id."""
    with closing(Database(path).connect()) as conn:
        return [(row["id"], row["label"], row["kind"]) for row in conn.execute("SELECT * FROM items ORDER BY id")]


def test_a_table_schema_creates_its_table_in_one_statement_whose_text_the_database_stores(tmp_path: Path) -> None:
    with closing(Database(tmp_path / "t.db").connect()) as conn:
        conn.execute(ITEMS.create)  # execute refuses more than one statement
        for index in ITEMS.indexes:
            conn.execute(index)

        assert [row["name"] for row in conn.execute("PRAGMA table_info(items)")] == ["id", "label", "kind"]
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'items'").fetchone()["sql"] == ITEMS.create
    assert ITEMS.column_names == ("id", "label", "kind")
    assert ITEMS.create.startswith("CREATE TABLE items (")


def test_create_table_creates_the_table_and_each_of_its_indexes(tmp_path: Path) -> None:
    created = _created_from(ITEMS, tmp_path / "t.db")

    assert schema_of(created) == [
        ("index", "idx_items_kind", "items", "CREATE INDEX idx_items_kind ON items(kind)"),
        ("index", "sqlite_autoindex_items_1", "items", None),
        ("table", "items", "items", ITEMS.create),
    ]


def test_rebuild_table_keeps_every_row_and_leaves_the_schema_a_new_file_created_from_the_schema_holds(
    tmp_path: Path,
) -> None:
    """The file then holds no quoted CREATE TABLE "items" and no table left from before the rebuild."""
    items: list[Item] = [("r-1", "first", "small"), ("r-2", "second", "large"), ("r-3", "third", None)]
    rebuilt = _created_from(OLD_ITEMS, tmp_path / "t.db", items)
    fresh = _created_from(ITEMS, tmp_path / "fresh.db")
    assert schema_of(rebuilt) != schema_of(fresh)

    _rebuilt(rebuilt, ITEMS)

    assert _items(rebuilt) == items
    assert schema_of(rebuilt) == schema_of(fresh)


@pytest.mark.parametrize("referenced_as", ["items", "ITEMS"])
def test_rebuild_table_refuses_a_table_another_tables_foreign_key_references_before_it_renames_anything(
    referenced_as: str, tmp_path: Path
) -> None:
    """Renaming the table would rewrite the child's REFERENCES clause to the renamed table, and
    dropping that table would then delete the child's rows with it. SQLite names a table in any
    case, so a reference written in another case refers to it too."""
    items: list[Item] = [("r-1", "first", "small")]
    database = _created_from(OLD_ITEMS, tmp_path / "t.db", items)
    with closing(Database(database).connect()) as conn:
        conn.execute(
            f"CREATE TABLE item_notes (id TEXT PRIMARY KEY, item_id TEXT REFERENCES {referenced_as}(id) ON DELETE CASCADE)"
        )
        conn.execute("INSERT INTO item_notes (id, item_id) VALUES ('n-1', 'r-1')")
        conn.commit()
    schema_before = schema_of(database)

    with closing(Database(database).connect()) as conn:
        conn.execute("BEGIN")
        with pytest.raises(ValueError, match=r"item_notes.*'items'|'items'.*item_notes"):
            rebuild_table(conn, ITEMS)
        conn.commit()

    assert schema_of(database) == schema_before
    assert _items(database) == items
    with closing(Database(database).connect()) as conn:
        assert [tuple(row) for row in conn.execute("SELECT id, item_id FROM item_notes")] == [("n-1", "r-1")]


def test_row_refused_names_the_table_the_rows_id_and_the_column_and_is_not_a_value_error() -> None:
    refused = RowRefused("items", "r-1", "kind", "'x' is not one of ['small', 'large']")

    assert not isinstance(refused, ValueError)
    assert str(refused) == "The items row 'r-1' cannot be migrated: its kind 'x' is not one of ['small', 'large']"
    assert (refused.table, refused.row_id, refused.column) == ("items", "r-1", "kind")

