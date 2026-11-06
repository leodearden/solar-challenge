# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs as earlier solar-challenge code stored them, with no format version, for tests that read and migrate them.

pre_469_home, legacy_fleet and pre_786_dispatch_home are runs that the code of main at commit
9ce8827 saved. That commit is the one before task 469 merged (aca7236's first parent), so its
summaries have no total_grid_charge_kwh, and a battery's dispatch strategy is not yet task
786's tagged union. A one-off script, which is not committed, wrote them: it built synthetic
one-day SimulationResults at 1-minute resolution, with no simulation and no network; it
summarised them with that tree's calculate_summary, and a fleet's with its
calculate_fleet_summary too; and it saved them through that tree's
RunStorage(db_path, data_dir).save_home_run and save_fleet_run into a temporary store.

pre_787_dispatch_fleet is a run that the code of main at commit b8d39b9 saved, before task 787
refused a dispatch setting its run would ignore. A one-off script, which is not committed,
simulated each home for one day, 2024-06-15, offline with synthetic_june_weather; it
summarised them with that tree's calculate_home_summaries and calculate_fleet_summary; and it
saved them through that tree's RunStorage.save_fleet_run into a temporary store. That save
also wrote a format.json, which was then deleted, so the run reads as one stored before a run
carried a format version, and every step brings it forward.

Each fixture holds:

- run/: the run's directory as that save wrote it, without a format.json. A home run's
  holds config.json, summary.json and data.parquet. A fleet run's holds config.json
  ({"homes": [...], "n_homes": N}), summary.json, and in homes/ each home's home_<i>.parquet
  and home_<i>_summary.json.
- runs_row.json: every column of the runs row that save wrote, read back from its database,
  with config_json and summary_json as their verbatim text.

The fixtures, in STORED_RUN_FIXTURES' order:

- pre_469_home: a home run with a 5 kWh battery and no dispatch strategy.
- legacy_fleet: a fleet run of two homes, the first with a 5 kWh battery.
- pre_786_dispatch_home: a home run on an Economy 7 tariff whose battery dispatches
  tou_optimized with peak_hours [[16, 19]] and grid-charges to 0.8. Its dispatch strategy has
  the three-key shape of before the tagged union:
  {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]], "import_limit_kw": null}.
- pre_787_dispatch_fleet: a fleet run of three homes, each with a 5 kWh battery that
  grid-charges to 0.8, whose dispatch charged nothing from the grid:
  homes[0]'s battery dispatches self_consumption, on an Economy 7 tariff, with home
  dispatch_strategy "greedy"; homes[1]'s battery dispatches tou_optimized with peak_hours
  [[16, 19]], with no tariff; homes[2] has home dispatch_strategy "tou_optimized", a battery
  that names no dispatch strategy and no tariff, so it ran self-consumption.

PRE_DISPATCH_UNION_HOME_CONFIGS is a JSON file of FIXTURES_DIR beside those directories, whose
docstring says what it holds; pre_dispatch_union_home_config reads one of its configs.

install_stored_run_fixture puts a fixture into a store: its row into the runs table, with SQL,
and a copy of its run/ as that run's directory, under the fixture's run id or another, so a
store can hold a copy of a fixture beside the fixture itself. The functions import the web
package only when they are called, so importing this module needs no web extra.

Usage::

    from tests._stored_run_fixtures import STORED_RUN_FIXTURES, install_stored_run_fixture

    for name in STORED_RUN_FIXTURES:
        run_id = install_stored_run_fixture(name, database, data_dir)
    copy_id = install_stored_run_fixture("pre_469_home", database, data_dir, run_id="pre-469-copy")
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from solar_challenge.web.database import Database
    from solar_challenge.web.stored_runs import RunType

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "stored_runs"

PRE_DISPATCH_UNION_HOME_CONFIGS = FIXTURES_DIR / "pre_dispatch_union_home_configs.json"
"""A home run's stored config per dispatch strategy, as runs stored it before the strategies were
variants of one union: all three strategy keys, the ones the strategy does not read null. Each
config is that of a home with the strategy and a grid charge of 0.8, keyed by the strategy's name."""

STORED_RUN_FIXTURES: tuple[str, ...] = (
    "pre_469_home",
    "legacy_fleet",
    "pre_786_dispatch_home",
    "pre_787_dispatch_fleet",
)
"""The name of each legacy stored-run fixture, a directory of FIXTURES_DIR."""


def stored_run_fixture_dir(name: str) -> Path:
    """The run directory of fixture *name*, exactly as the old save wrote it.

    Raises:
        ValueError: *name* is not one of STORED_RUN_FIXTURES.
    """
    return _fixture_dir(name) / "run"


def fixture_run_type(name: str) -> RunType:
    """The type of the run that fixture *name* holds, as its runs row records it.

    Raises:
        ValueError: *name* is not one of STORED_RUN_FIXTURES.
    """
    from solar_challenge.web.stored_runs import RUN_TYPES
    from solar_challenge.web.text_options import one_of

    return one_of(_runs_row(name)["type"], RUN_TYPES, f"the type in {name}'s runs_row.json")


def install_stored_run_fixture(name: str, database: Database, data_dir: Path, *, run_id: str | None = None) -> str:
    """Put fixture *name* into the store of *database* and *data_dir* as the run *run_id*, the fixture's own id when None; return the run's id.

    The fixture's row is inserted into the store's runs table with SQL, as the old save wrote
    it but for its id, and its run directory is copied to that run's directory under
    *data_dir*. Nothing is migrated or checked: the store holds the run as the old
    solar-challenge left it.

    Raises:
        ValueError: *name* is not one of STORED_RUN_FIXTURES.
        sqlite3.Error: The runs table refuses the row, e.g. for an id one of its runs already has.
    """
    from solar_challenge.web.storage import RunStorage

    from tests._run_storage_layout import stored_run_dir

    row = _runs_row(name)
    if run_id is not None:
        row["id"] = run_id
    columns = ", ".join(row)
    placeholders = ", ".join(f":{column}" for column in row)
    with database.transaction() as conn:
        conn.execute(f"INSERT INTO runs ({columns}) VALUES ({placeholders})", row)
    installed_id: str = row["id"]
    shutil.copytree(stored_run_fixture_dir(name), stored_run_dir(RunStorage(database, data_dir), installed_id))
    return installed_id


def pre_dispatch_union_home_config(strategy_type: str) -> dict[str, Any]:
    """The stored config that PRE_DISPATCH_UNION_HOME_CONFIGS holds for dispatch strategy *strategy_type*.

    Raises:
        ValueError: The file holds no config for *strategy_type*.
    """
    configs: dict[str, dict[str, Any]] = json.loads(PRE_DISPATCH_UNION_HOME_CONFIGS.read_text())
    if strategy_type not in configs:
        raise ValueError(
            f"{PRE_DISPATCH_UNION_HOME_CONFIGS.name} has no config for dispatch strategy {strategy_type!r}; "
            f"its strategies are {list(configs)}"
        )
    return configs[strategy_type]


def _fixture_dir(name: str) -> Path:
    """The directory of fixture *name*, which holds its run/ and runs_row.json.

    Raises:
        ValueError: *name* is not one of STORED_RUN_FIXTURES.
    """
    if name not in STORED_RUN_FIXTURES:
        raise ValueError(f"{name!r} is not a stored-run fixture; the fixtures are {list(STORED_RUN_FIXTURES)}")
    return FIXTURES_DIR / name


def _runs_row(name: str) -> dict[str, Any]:
    """Every column of the runs row of fixture *name*, by column name, as its runs_row.json holds it."""
    row: dict[str, Any] = json.loads((_fixture_dir(name) / "runs_row.json").read_text())
    return row
