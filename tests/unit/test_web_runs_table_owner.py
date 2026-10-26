# SPDX-License-Identifier: AGPL-3.0-or-later
"""D27 invariant 4: each seam of the dashboard's store has one owner module (contract C1).

Under src/solar_challenge/web:

- only database.py opens a SQLite connection (Database.connect);
- only storage.py issues SQL against the runs table, its schema migrations included;
- only app.py, the composition root, builds a RunStorage, reads the Flask config by key
  (``current_app.config[``) and names the config keys of the store's location
  (``"DATA_DIR"``, ``"DATABASE"``).

schema.py holds none of these. Every other module takes the store from the app through
shared.get_database() and shared.get_storage(). docs/prds/run-store-one-owner.md §3.1 lays
out the modules and §3.12 states the invariant.

The scan reads the text of each module that tests/_dashboard_sources.py's
dashboard_python_sources returns, comments and docstrings included. A statement is runs SQL
when it names the table after one of: FROM or JOIN; INSERT INTO, REPLACE INTO or UPDATE, with
or without a conflict clause such as OR REPLACE; CREATE, ALTER or DROP TABLE; or the ON of an
index, a trigger or a join. An SQL keyword matches in any case and with any whitespace, line
breaks included, before the table name, so prose that reads as runs SQL is reworded. A text
scan cannot see a table named only at run time: database.py's rebuild_table builds its
statements from the TableSchema it is given. The Python patterns are literal. The tests on
synthetic sources show that a planted use is reported, so the real-tree tests cannot pass by
finding nothing.
"""

import itertools
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

import pytest

from tests._dashboard_sources import dashboard_python_sources

_WEB_PACKAGE = "src/solar_challenge/web"


@dataclass(frozen=True)
class _Seam:
    """A way of reaching the dashboard's store, the pattern that finds it in a module's text, and the one module of the web package, keyed like ``app.py``, that may use it."""

    does: str
    pattern: re.Pattern[str]
    owner: str


_OR_CONFLICT = r"(?:\s+OR\s+(?:ROLLBACK|ABORT|REPLACE|FAIL|IGNORE))?"
"""SQLite's optional conflict clause of an INSERT or UPDATE, such as ``OR REPLACE``."""

_SEAMS: tuple[_Seam, ...] = (
    _Seam("opens a SQLite connection", re.compile(r"\bsqlite3\.connect\b"), "database.py"),
    _Seam(
        "reads or deletes rows of the runs table",
        re.compile(r"\b(?:FROM|JOIN)\s+runs\b", re.IGNORECASE),
        "storage.py",
    ),
    _Seam(
        "inserts into the runs table",
        re.compile(rf"\b(?:INSERT{_OR_CONFLICT}|REPLACE)\s+INTO\s+runs\b", re.IGNORECASE),
        "storage.py",
    ),
    _Seam(
        "updates the runs table",
        re.compile(rf"\bUPDATE{_OR_CONFLICT}\s+runs\b", re.IGNORECASE),
        "storage.py",
    ),
    _Seam(
        "creates, alters or drops the runs table",
        re.compile(r"\b(?:CREATE|ALTER|DROP)\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?runs\b", re.IGNORECASE),
        "storage.py",
    ),
    _Seam(
        "creates an index or trigger on the runs table, or joins on it",
        re.compile(r"\bON\s+runs\b", re.IGNORECASE),
        "storage.py",
    ),
    _Seam("builds a RunStorage", re.compile(r"\bRunStorage\("), "app.py"),
    _Seam("reads the Flask config by key", re.compile(r"\bcurrent_app\.config\["), "app.py"),
    _Seam(
        "names a config key of the store's location",
        re.compile(r"[\"'](?:DATA_DIR|DATABASE)[\"']"),
        "app.py",
    ),
)


@dataclass(frozen=True)
class _Use:
    """A match of a seam's pattern in a module of the web package: the line it starts on, and that line's text."""

    seam: _Seam
    module: str
    line: int
    text: str

    def __str__(self) -> str:
        return (
            f"{_WEB_PACKAGE}/{self.module}:{self.line} {self.seam.does}, "
            f"which only {self.seam.owner} may: {self.text.strip()}"
        )


def _uses_in(module: str, source: str, seam: _Seam) -> Iterator[_Use]:
    """Yield a use for each match of *seam*'s pattern in *source*, the text of *module*, in line order."""
    lines = source.split("\n")
    for match in seam.pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        yield _Use(seam, module, line, lines[line - 1])


def _uses(sources: Mapping[str, str]) -> list[_Use]:
    """Return the use of each seam in each of *sources*, keyed by module, in seam, then module, then line order."""
    uses: list[_Use] = []
    for seam, (module, source) in itertools.product(_SEAMS, sorted(sources.items())):
        uses.extend(_uses_in(module, source, seam))
    return uses


def _misplaced(uses: Iterable[_Use]) -> list[_Use]:
    """Return the *uses* in a module other than their seam's owner."""
    return [use for use in uses if use.module != use.seam.owner]


@pytest.fixture(scope="module")
def web_sources() -> dict[str, str]:
    """The text of every Python module of the web package, keyed like ``app.py``, read once for every real-tree test."""
    return dashboard_python_sources()


def test_only_its_owner_uses_each_seam_of_the_store(web_sources: Mapping[str, str]) -> None:
    """No module of the web package but a seam's owner opens a SQLite connection, issues runs SQL, builds a RunStorage or reads the store's location."""
    misplaced = _misplaced(_uses(web_sources))

    uses = "\n".join(str(use) for use in misplaced)
    assert not misplaced, (
        f"these modules of the web package use a seam of the dashboard's store that only its "
        f"owner may:\n{uses}\n"
        "Each seam has one owner: database.py opens every SQLite connection, storage.py issues "
        "every runs statement, and app.py builds the RunStorage and reads the store's location. "
        "Open a connection through Database.connect() (the app's database through "
        "shared.get_database()). Put runs SQL in storage.py, as a RunStorage method, or for a "
        "schema step as a storage.py function like migrate_runs_table_v1. Take the app's "
        "RunStorage through shared.get_storage(). Read the store's location only in create_app. "
        "Reword prose the scan reads as runs SQL. "
        "(D27 invariant 4; docs/prds/run-store-one-owner.md §3.1 and §4 C1)"
    )


def test_the_scan_reads_each_seams_owner_and_schema(web_sources: Mapping[str, str]) -> None:
    """The scan reads each seam's owner and schema.py, so the rule cannot pass by reading none of them once a module is renamed or moved."""
    modules_the_rule_names = {seam.owner for seam in _SEAMS} | {"schema.py"}
    missing = sorted(modules_the_rule_names - set(web_sources))

    assert not missing, (
        f"the scan of {_WEB_PACKAGE} read no module named {missing}, so "
        "test_only_its_owner_uses_each_seam_of_the_store checks less than this file's docstring "
        "states. If a module was renamed or moved, point _SEAMS at the module that now owns the "
        "seam, and update review/briefing.yaml's invariant 4 line and "
        "docs/prds/run-store-one-owner.md §3.1 with it"
    )


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "api.py",
            'rows = conn.execute("SELECT id FROM runs")\n',
            [("api.py", 1, "reads or deletes rows of the runs table")],
            id="select",
        ),
        pytest.param(
            "chat_messages.py",
            'conn.execute("SELECT r.name FROM chat_messages m JOIN runs r ON r.id = m.run_id")\n',
            [("chat_messages.py", 1, "reads or deletes rows of the runs table")],
            id="join",
        ),
        pytest.param(
            "jobs.py",
            "\n\nconn.execute(\n    'insert into runs (id) values (?)', (run_id,)\n)\n",
            [("jobs.py", 4, "inserts into the runs table")],
            id="insert-in-lower-case",
        ),
        pytest.param(
            "jobs.py",
            'conn.execute("INSERT OR REPLACE INTO runs (id) VALUES (?)", (run_id,))\n',
            [("jobs.py", 1, "inserts into the runs table")],
            id="insert-or-replace",
        ),
        pytest.param(
            "jobs.py",
            'conn.execute("REPLACE INTO runs (id) VALUES (?)", (run_id,))\n',
            [("jobs.py", 1, "inserts into the runs table")],
            id="replace-into",
        ),
        pytest.param(
            "assistant.py",
            'SQL = """UPDATE\n    runs SET name = ?"""\n',
            [("assistant.py", 1, "updates the runs table")],
            id="update-across-lines",
        ),
        pytest.param(
            "api.py",
            'conn.execute("update or ignore runs set notes = ?", (notes,))\n',
            [("api.py", 1, "updates the runs table")],
            id="update-or-ignore",
        ),
        pytest.param(
            "schema.py",
            'conn.execute("ALTER TABLE runs ADD COLUMN x")\n',
            [("schema.py", 1, "creates, alters or drops the runs table")],
            id="alter-table-in-schema",
        ),
        pytest.param(
            "schema.py",
            'conn.execute("DROP TABLE IF EXISTS runs")\n'
            'conn.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT)")\n',
            [
                ("schema.py", 1, "creates, alters or drops the runs table"),
                ("schema.py", 2, "creates, alters or drops the runs table"),
            ],
            id="drop-and-create-table",
        ),
        pytest.param(
            "schema.py",
            'conn.execute("CREATE INDEX idx_runs_name ON runs(name)")\n',
            [("schema.py", 1, "creates an index or trigger on the runs table, or joins on it")],
            id="create-index",
        ),
        pytest.param(
            "schema.py",
            "import sqlite3\nconn = sqlite3.connect(path)\n",
            [("schema.py", 2, "opens a SQLite connection")],
            id="connect",
        ),
        pytest.param(
            "jobs.py",
            "storage = RunStorage(database, data_dir)\n",
            [("jobs.py", 1, "builds a RunStorage")],
            id="run-storage",
        ),
        pytest.param(
            "api.py",
            'path = current_app.config["DATABASE"]\n',
            [
                ("api.py", 1, "reads the Flask config by key"),
                ("api.py", 1, "names a config key of the store's location"),
            ],
            id="config-by-key",
        ),
        pytest.param(
            "assistant.py",
            "data_dir = current_app.config.get('DATA_DIR')\n",
            [("assistant.py", 1, "names a config key of the store's location")],
            id="config-get",
        ),
        pytest.param(
            "storage.py",
            'conn.execute("DELETE FROM runs WHERE id = ?")\n',
            [],
            id="the-owner",
        ),
        pytest.param(
            "api.py",
            'conn.execute("SELECT * FROM runs_archive")\n'
            'conn.execute("SELECT * FROM jobs JOIN runs_archive USING (id)")\n'
            'conn.execute("INSERT OR REPLACE INTO runs_archive (id) VALUES (?)")\n'
            'conn.execute("REPLACE INTO runs_archive (id) VALUES (?)")\n'
            'conn.execute("UPDATE OR IGNORE runs_archive SET notes = ?")\n'
            'conn.execute("ALTER TABLE runs_archive ADD COLUMN x")\n'
            'conn.execute("DROP TABLE IF EXISTS runs_archive")\n'
            'conn.execute("CREATE INDEX idx_runs_archive_name ON runs_archive(name)")\n'
            'RunStorageError("x")\n'
            "my_sqlite3.connect()\n"
            "writes nothing to the RunStorage (contract C8)\n"
            "the routes that update or delete runs take the app's RunStorage\n",
            [],
            id="near-misses",
        ),
    ],
)
def test_the_scan_reports_each_use_outside_its_owner_by_module_line_and_seam(
    module: str, source: str, expected: list[tuple[str, int, str]]
) -> None:
    """The scan reports a use of a seam outside its owner, the SQL in any case and across lines, by module, the line it starts on and the seam; it reports neither the owner's own use nor a near miss: another table, another name or prose."""
    found = _misplaced(_uses({module: source}))

    assert [(use.module, use.line, use.seam.does) for use in found] == expected


def test_a_misplaced_use_is_reported_naming_its_file_line_and_owner() -> None:
    """The report of a planted use names its file and line under the web package, and the module that owns its seam."""
    misplaced = _misplaced(
        _uses({"routes.py": 'import flask\nrows = conn.execute("SELECT name FROM runs")\n'})
    )

    assert len(misplaced) == 1, [str(use) for use in misplaced]
    report = str(misplaced[0])
    assert report.startswith("src/solar_challenge/web/routes.py:2 "), report
    assert "storage.py" in report, report
