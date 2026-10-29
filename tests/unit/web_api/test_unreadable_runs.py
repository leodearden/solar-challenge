# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every page and /api endpoint reading a stored run it cannot rebuild answers alike (B6; D-S19-9 in docs/prds/run-store-one-owner.md).

A page flashes the StoredRunUnreadable's message, which names the run id, the document and
the field, and redirects; an /api endpoint, and the sweep page's chart endpoint, POST
/scenarios/sweep/chart, answer 409 with the message as error and the run_id, document and
field as data. None answers 500.

Each test saves a current home run as a finished job saves it, then damages one document
alike in both its copies: the file in the run's directory, which the results page and the
CSV export read, and the runs row's column, which the run's detail, its job's results and
the YAML export read. So a refusal's document names the copy the endpoint read. A run's time
series has no copy in its runs row, so it is damaged in its file alone, which only the results
page and the CSV export read.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import NonCallableMagicMock

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from solar_challenge.web.jobs import JobState
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import make_home_config, make_sim_results
from tests._html_page import texts
from tests._run_storage_layout import stored_run_dir
from tests._web_runs import store_home_run

_RUN_ID = "damaged-run"


@dataclass(frozen=True)
class _Damage:
    """One document of a run, damaged alike in its file and its runs column, and the field its refusal names.

    edit changes a decoded copy of the document in place.
    """

    file: str
    column: str
    edit: Callable[[dict[str, Any]], None]
    field: str


def _without_total_generation_kwh(document: dict[str, Any]) -> None:
    del document["total_generation_kwh"]


def _with_a_retired_figure(document: dict[str, Any]) -> None:
    document["retired_figure"] = 12.5


def _with_a_generation_no_float_can_hold(document: dict[str, Any]) -> None:
    document["total_generation_kwh"] = 10**400


def _with_a_big_battery(document: dict[str, Any]) -> None:
    document["battery_config"] = "big"


_SUMMARY_LACKS_A_REQUIRED_FIELD = _Damage("summary.json", "summary_json", _without_total_generation_kwh, "total_generation_kwh")
_SUMMARY_HOLDS_AN_UNKNOWN_KEY = _Damage("summary.json", "summary_json", _with_a_retired_figure, "retired_figure")
_SUMMARY_HOLDS_A_NUMBER_NO_FLOAT_CAN_HOLD = _Damage(
    "summary.json", "summary_json", _with_a_generation_no_float_can_hold, "total_generation_kwh"
)
_CONFIG_HOLDS_A_VALUE_OF_A_WRONG_TYPE = _Damage("config.json", "config_json", _with_a_big_battery, "battery_config")

_SUMMARY_DAMAGES = [
    pytest.param(_SUMMARY_LACKS_A_REQUIRED_FIELD, id="summary-lacks-a-required-field"),
    pytest.param(_SUMMARY_HOLDS_AN_UNKNOWN_KEY, id="summary-holds-an-unknown-key"),
    pytest.param(_SUMMARY_HOLDS_A_NUMBER_NO_FLOAT_CAN_HOLD, id="summary-holds-a-number-no-float-can-hold"),
]
_CONFIG_DAMAGES = [pytest.param(_CONFIG_HOLDS_A_VALUE_OF_A_WRONG_TYPE, id="config-holds-a-string-for-a-battery")]
_DAMAGES = [*_SUMMARY_DAMAGES, *_CONFIG_DAMAGES]


def _store_a_damaged_run(storage: RunStorage, damage: _Damage) -> None:
    """Save a day's home run under _RUN_ID, then apply *damage* to its file and to its runs column."""
    store_home_run(storage, _RUN_ID, make_home_config(), make_sim_results(days=1))
    path = stored_run_dir(storage, _RUN_ID) / damage.file
    file_document = json.loads(path.read_text())
    damage.edit(file_document)
    path.write_text(json.dumps(file_document, indent=2))
    with storage.database.transaction() as conn:
        (text,) = conn.execute(f"SELECT {damage.column} FROM runs WHERE id = ?", (_RUN_ID,)).fetchone()
        column_document = json.loads(text)
        damage.edit(column_document)
        conn.execute(f"UPDATE runs SET {damage.column} = ? WHERE id = ?", (json.dumps(column_document), _RUN_ID))


def _store_a_run_whose_time_series_has_a_range_index(storage: RunStorage) -> None:
    """Save a day's home run under _RUN_ID, then rewrite its data.parquet with a RangeIndex in the place of its timestamps."""
    store_home_run(storage, _RUN_ID, make_home_config(), make_sim_results(days=1))
    path = stored_run_dir(storage, _RUN_ID) / "data.parquet"
    pd.read_parquet(path, engine="pyarrow").reset_index(drop=True).to_parquet(path, engine="pyarrow")


def _named(document: str, field: str | None) -> tuple[str, ...]:
    """The texts a refusal of run _RUN_ID's *document* at *field* names: the run id and the document, and the field unless it is None, the document as a whole."""
    return (_RUN_ID, document) if field is None else (_RUN_ID, document, field)


def _assert_refused(response: TestResponse, document: str, field: str | None) -> None:
    """Check that *response* answers 409 refusing run _RUN_ID's *document* at *field*, None for the document as a whole, its error naming each text _named gives."""
    assert response.status_code == 409, response.get_data(as_text=True)
    body = response.get_json()
    assert body == {"error": body["error"], "run_id": _RUN_ID, "document": document, "field": field}
    assert [text for text in _named(document, field) if text not in body["error"]] == [], body["error"]


def _assert_redirected_flashing_refusal(response: TestResponse, document: str, field: str | None) -> None:
    """Check that *response*, its redirects followed, took one to the dashboard, which flashes one text naming each text _named gives for run _RUN_ID's *document* at *field*."""
    assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
    assert response.status_code == 200
    page_texts = texts(response.get_data(as_text=True))
    flashed = [text for text in page_texts if all(named in text for named in _named(document, field))]
    assert len(flashed) == 1, page_texts


@pytest.mark.parametrize("damage", _DAMAGES)
def test_the_results_page_of_an_unreadable_run_redirects_to_the_dashboard_flashing_its_refusal(
    storage: RunStorage, client: FlaskClient, damage: _Damage
) -> None:
    """The page reads the run's files, so the flash names the damaged file and the field."""
    _store_a_damaged_run(storage, damage)

    response = client.get(f"/results/{_RUN_ID}", follow_redirects=True)

    _assert_redirected_flashing_refusal(response, damage.file, damage.field)


def test_the_results_page_of_a_run_whose_time_series_has_no_timestamps_redirects_to_the_dashboard_flashing_its_refusal(
    storage: RunStorage, client: FlaskClient
) -> None:
    _store_a_run_whose_time_series_has_a_range_index(storage)

    response = client.get(f"/results/{_RUN_ID}", follow_redirects=True)

    _assert_redirected_flashing_refusal(response, "data.parquet", None)


@pytest.mark.parametrize("damage", _DAMAGES)
def test_the_csv_export_of_an_unreadable_run_answers_409_naming_the_damaged_file(
    storage: RunStorage, client: FlaskClient, damage: _Damage
) -> None:
    _store_a_damaged_run(storage, damage)

    response = client.get(f"/api/history/runs/{_RUN_ID}/export/csv")

    _assert_refused(response, damage.file, damage.field)


def test_the_csv_export_of_a_run_whose_time_series_has_no_timestamps_answers_409_naming_its_file(
    storage: RunStorage, client: FlaskClient
) -> None:
    _store_a_run_whose_time_series_has_a_range_index(storage)

    response = client.get(f"/api/history/runs/{_RUN_ID}/export/csv")

    _assert_refused(response, "data.parquet", None)


@pytest.mark.parametrize("damage", _DAMAGES)
def test_the_detail_of_an_unreadable_run_answers_409_naming_the_damaged_column(
    storage: RunStorage, client: FlaskClient, damage: _Damage
) -> None:
    _store_a_damaged_run(storage, damage)

    response = client.get(f"/api/history/runs/{_RUN_ID}")

    _assert_refused(response, f"runs.{damage.column}", damage.field)


@pytest.mark.parametrize("damage", _SUMMARY_DAMAGES)
def test_the_results_of_the_job_of_a_run_whose_summary_cannot_be_read_answer_409_naming_its_column(
    storage: RunStorage, client: FlaskClient, mock_job_manager: NonCallableMagicMock, damage: _Damage
) -> None:
    _store_a_damaged_run(storage, damage)
    mock_job_manager.job_state.return_value = JobState(
        job_id="job-1",
        run_id=_RUN_ID,
        status="completed",
        progress_pct=100.0,
        current_step="Done",
        message="Simulation completed successfully",
        created_at="2026-10-20T09:00:00+00:00",
    )

    response = client.get("/api/jobs/job-1/results")

    _assert_refused(response, "runs.summary_json", damage.field)


@pytest.mark.parametrize("damage", _CONFIG_DAMAGES)
def test_the_yaml_export_of_a_run_whose_config_cannot_be_read_answers_409_naming_its_column(
    storage: RunStorage, client: FlaskClient, damage: _Damage
) -> None:
    _store_a_damaged_run(storage, damage)

    response = client.get(f"/api/history/runs/{_RUN_ID}/export/yaml")

    _assert_refused(response, "runs.config_json", damage.field)


@pytest.mark.parametrize("damage", _SUMMARY_DAMAGES)
def test_the_sweep_charts_of_a_point_whose_summary_cannot_be_read_answer_409_naming_its_column(
    storage: RunStorage, client: FlaskClient, damage: _Damage
) -> None:
    _store_a_damaged_run(storage, damage)

    response = client.post(
        "/scenarios/sweep/chart",
        json={"parameter_label": "PV Capacity (kW)", "points": [{"value": 4.0, "run_id": _RUN_ID}]},
    )

    _assert_refused(response, "runs.summary_json", damage.field)
