# SPDX-License-Identifier: AGPL-3.0-or-later
"""The typed reads of a run's record, and the headline a run list shows for a run.

A record reads its summary_json and config_json through its kind, in RunRecord.summary()
and RunRecord.home_configs(): a home run's summary is a SummaryStatistics and a fleet run's
a FleetSummary, and each run's config is its homes' HomeConfigs, in order. A run with no
document yet answers None. A document that cannot be read is refused with a
StoredRunUnreadable naming the run, the column, e.g. runs.summary_json, and the field; so is
each document of a record with no type, naming runs.type. run_headline maps a summary of
either kind to the generation and self-consumption ratio a run list shows, and refuses a
summary whose figure for either is not a finite number.

RunStorage.page_runs answers one page of the run list a RunQuery asks for, filtered by
type, text and creation date and sorted by one column, with the count of every run the
query matches; RunQuery refuses a query no page answers.

headline_figures is a run list row's figures for a run's record, named as the run lists
name them. A run has no figures while it has no summary, and none, with a warning naming the
run, when its summary is damaged: it cannot be read, its refusal then being the row's
unreadable, or run_headline refuses it. RunStorage.totals counts the completed runs and their
homes and sums the generation of those whose headline reads.
"""

import dataclasses
import json
import logging
import math
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, FleetSummary, calculate_fleet_summary
from solar_challenge.home import SummaryStatistics, calculate_summary
from solar_challenge.web.storage import (
    RUN_SORTS,
    RunHeadline,
    RunPage,
    RunQuery,
    RunRecord,
    RunStorage,
    RunTotals,
    headline_figures,
    run_headline,
)
from solar_challenge.web.stored_runs import RUN_TYPES, StoredRunUnreadable
from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_home_config, make_sim_results
from tests._run_stores import empty_run_storage
from tests._run_summaries import fleet_summary, home_summary, summary_json
from tests._web_runs import store_fleet_run, store_home_run


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """The store of no app whose runs the tests read, page and total."""
    return empty_run_storage(tmp_path)


def _record(storage: RunStorage, run_id: str) -> RunRecord:
    """The record of run *run_id*, which the test has written."""
    record = storage.run_record(run_id)
    assert record is not None, f"no run has id {run_id!r}"
    return record


def _two_unlike_homes() -> FleetResults:
    """A fleet of two homes whose totals and batteries differ, so a mix-up of their order shows."""
    return make_fleet_results_of(
        [
            make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
            make_sim_results(self_kwh=10.0, export_kwh=20.0, import_kwh=30.0, days=1),
        ],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )


def _store_a_home_run(
    storage: RunStorage, run_id: str, *, name: str | None = None, created_at: str | None = None
) -> RunRecord:
    """Save a day of a default home's results as home run *run_id*, named *name* and created at *created_at*, and answer its record."""
    store_home_run(storage, run_id, make_home_config(), make_sim_results(days=1), name=name, created_at=created_at)
    return _record(storage, run_id)


def _store_a_fleet_run(
    storage: RunStorage, run_id: str, *, name: str | None = None, created_at: str | None = None
) -> RunRecord:
    """Save a day of two default homes' results as fleet run *run_id*, named *name* and created at *created_at*, and answer its record."""
    store_fleet_run(storage, run_id, make_fleet_results(n_homes=2, days=1), name=name, created_at=created_at)
    return _record(storage, run_id)


_STORE_A_RUN_OF_EACH_KIND = [
    pytest.param(_store_a_home_run, id="home-run"),
    pytest.param(_store_a_fleet_run, id="fleet-run"),
]


def _summary_of(record: RunRecord) -> object:
    return record.summary()


def _home_configs_of(record: RunRecord) -> object:
    return record.home_configs()


_READ_OF_COLUMN: dict[str, Callable[[RunRecord], object]] = {
    "summary_json": _summary_of,
    "config_json": _home_configs_of,
}


def _with_a_retired_key(document_json: str | None) -> str:
    """*document_json*, a document's JSON text, with '{"retired": 1}' merged into its root: a key no field has."""
    assert document_json is not None, "the run holds no such document"
    return json.dumps({**json.loads(document_json), "retired": 1})


def _without_total_generation_kwh(document_json: str | None) -> str:
    """*document_json*, a summary's JSON text, without total_generation_kwh, a field each kind's summary requires."""
    assert document_json is not None, "the run holds no summary"
    document = json.loads(document_json)
    del document["total_generation_kwh"]
    return json.dumps(document)


class TestRunRecordTypedDocuments:
    """RunRecord.summary() and RunRecord.home_configs(): the run's documents, decoded through its kind."""

    def test_a_saved_home_run_has_the_summary_of_its_results_and_its_one_home_s_config(
        self, storage: RunStorage
    ) -> None:
        config = make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))
        results = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
        store_home_run(storage, "home-1", config, results)

        record = _record(storage, "home-1")

        assert record.summary() == calculate_summary(results)
        assert record.home_configs() == (config,)

    def test_a_saved_fleet_run_has_the_fleet_summary_of_its_results_and_each_home_s_config_in_order(
        self, storage: RunStorage
    ) -> None:
        fleet = _two_unlike_homes()
        store_fleet_run(storage, "fleet-1", fleet)

        record = _record(storage, "fleet-1")

        assert record.summary() == calculate_fleet_summary(fleet)
        assert record.home_configs() == tuple(fleet.home_configs)

    def test_a_run_whose_job_is_still_running_has_no_summary_and_no_homes_yet(self, storage: RunStorage) -> None:
        storage.create_run("running-1", run_type="fleet", name="North Roof", n_homes=3, created_at="2026-10-20T09:00:00+00:00")

        record = _record(storage, "running-1")

        assert (record.summary(), record.home_configs()) == (None, None)

    @pytest.mark.parametrize("store_a_run", _STORE_A_RUN_OF_EACH_KIND)
    @pytest.mark.parametrize(
        ("column", "text"),
        [
            pytest.param("summary_json", "{not json", id="summary-not-json"),
            pytest.param("summary_json", "[]", id="summary-not-an-object"),
            pytest.param("summary_json", '{"total_generation_kwh": 100.0}', id="summary-missing-required-fields"),
            pytest.param("config_json", "{not json", id="config-not-json"),
            pytest.param("config_json", "[]", id="config-not-an-object"),
            pytest.param("config_json", '{"pv_config": {"capacity_kw": 4.0}}', id="config-missing-load-config"),
        ],
    )
    def test_a_document_that_cannot_be_read_is_refused_as_unreadable_naming_the_run_and_its_column(
        self,
        storage: RunStorage,
        store_a_run: Callable[[RunStorage, str], RunRecord],
        column: str,
        text: str,
    ) -> None:
        garbled = dataclasses.replace(store_a_run(storage, "garbled-run"), **{column: text})

        with pytest.raises(StoredRunUnreadable) as refusal:
            _READ_OF_COLUMN[column](garbled)

        assert (refusal.value.run_id, refusal.value.document) == ("garbled-run", f"runs.{column}")
        assert "'garbled-run'" in str(refusal.value)
        assert f"runs.{column}" in str(refusal.value)

    @pytest.mark.parametrize("store_a_run", _STORE_A_RUN_OF_EACH_KIND)
    @pytest.mark.parametrize(
        ("damage", "field"),
        [
            pytest.param(_with_a_retired_key, "retired", id="a-key-no-field-has"),
            pytest.param(_without_total_generation_kwh, "total_generation_kwh", id="a-required-field-missing"),
        ],
    )
    def test_a_summary_holding_a_key_no_field_has_or_lacking_a_required_field_is_refused_naming_that_field(
        self,
        storage: RunStorage,
        store_a_run: Callable[[RunStorage, str], RunRecord],
        damage: Callable[[str | None], str],
        field: str,
    ) -> None:
        record = store_a_run(storage, "damaged-run")
        damaged = dataclasses.replace(record, summary_json=damage(record.summary_json))

        with pytest.raises(StoredRunUnreadable) as refusal:
            damaged.summary()

        assert (refusal.value.run_id, refusal.value.document, refusal.value.field) == (
            "damaged-run",
            "runs.summary_json",
            field,
        )
        assert field in str(refusal.value)

    @pytest.mark.parametrize("column", list(_READ_OF_COLUMN))
    def test_a_record_with_no_type_is_refused_its_documents_by_the_kind_s_refusal_naming_its_run_and_runs_type(
        self, storage: RunStorage, column: str
    ) -> None:
        untyped = dataclasses.replace(_store_a_home_run(storage, "untyped-run"), type=None)
        with pytest.raises(StoredRunUnreadable) as kind_refusal:
            _ = untyped.kind

        with pytest.raises(StoredRunUnreadable) as refusal:
            _READ_OF_COLUMN[column](untyped)

        assert (refusal.value.run_id, refusal.value.document, refusal.value.field) == ("untyped-run", "runs.type", None)
        assert "untyped-run" in str(refusal.value)
        assert str(refusal.value) == str(kind_refusal.value)


class TestRunHeadline:
    """run_headline: the generation and self-consumption ratio a run list shows for a run's summary.

    Each summary's marker figures, its generation and its ratio, are figures no other field of
    it holds, so a headline read from the wrong field shows.
    """

    def test_a_home_run_s_headline_is_its_generation_and_its_self_consumption_ratio(self) -> None:
        summary = home_summary(total_generation_kwh=987.65, self_consumption_ratio=0.37)

        assert run_headline(summary) == RunHeadline(
            generation_kwh=summary.total_generation_kwh, self_consumption_ratio=summary.self_consumption_ratio
        )

    def test_a_fleet_run_s_headline_is_its_total_generation_and_its_fleet_self_consumption_ratio(self) -> None:
        summary = fleet_summary(total_generation_kwh=1975.3, fleet_self_consumption_ratio=0.43)

        assert run_headline(summary) == RunHeadline(
            generation_kwh=summary.total_generation_kwh, self_consumption_ratio=summary.fleet_self_consumption_ratio
        )

    @pytest.mark.parametrize(
        ("summary", "figure", "value"),
        [
            pytest.param(home_summary(total_generation_kwh=None), "generation_kwh", None, id="home-generation-null"),
            pytest.param(home_summary(self_consumption_ratio="0.6"), "self_consumption_ratio", "0.6", id="home-ratio-text"),
            pytest.param(fleet_summary(total_generation_kwh=math.nan), "generation_kwh", math.nan, id="fleet-generation-nan"),
            pytest.param(fleet_summary(total_generation_kwh=math.inf), "generation_kwh", math.inf, id="fleet-generation-inf"),
            pytest.param(
                fleet_summary(fleet_self_consumption_ratio=True), "self_consumption_ratio", True, id="fleet-ratio-bool"
            ),
            pytest.param(
                home_summary(total_generation_kwh=10**400),
                "generation_kwh",
                10**400,
                id="home-generation-too-large-for-a-float",
            ),
            pytest.param(
                fleet_summary(fleet_self_consumption_ratio=-(10**400)),
                "self_consumption_ratio",
                -(10**400),
                id="fleet-ratio-below-every-float",
            ),
        ],
    )
    def test_a_summary_whose_headline_figure_is_not_a_finite_number_is_refused_naming_the_figure_and_its_value(
        self, summary: SummaryStatistics | FleetSummary, figure: str, value: object
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            run_headline(summary)

        assert f"{figure} is {value!r}" in str(refusal.value)

    def test_a_figure_a_summary_holds_as_a_whole_number_is_a_headline_figure(self) -> None:
        """A stored summary's JSON may hold a figure as a whole number, 100 rather than 100.0, which decodes as an int."""
        summary = home_summary(total_generation_kwh=100, self_consumption_ratio=0)

        assert run_headline(summary) == RunHeadline(generation_kwh=100, self_consumption_ratio=0)


def _ids(page: RunPage) -> list[str]:
    """The id of each run *page* lists, in its order."""
    return [record.id for record in page.records]


class TestRunQuery:
    """RunQuery, the filters, sort and page of a run list, which refuses a query no page answers."""

    @pytest.mark.parametrize(
        ("field", "value", "options"),
        [
            pytest.param("page", 0, (), id="page-0"),
            pytest.param("per_page", 0, (), id="per-page-0"),
            pytest.param("per_page", 101, (), id="per-page-101"),
            pytest.param("sort", "evil", RUN_SORTS, id="sort-not-a-run-sort"),
            pytest.param("run_type", "sweep", RUN_TYPES, id="run-type-sweep"),
        ],
    )
    def test_a_query_no_page_answers_is_refused_naming_its_field_its_value_and_the_options(
        self, field: str, value: object, options: tuple[str, ...]
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            RunQuery(**{field: value})

        message = str(refusal.value)
        assert f"{field} is {value!r}" in message
        assert [option for option in options if repr(option) not in message] == []

    def test_a_query_of_no_fields_is_the_first_page_of_20_runs_of_every_kind_newest_first(self) -> None:
        query = RunQuery()

        assert (
            query.run_type,
            query.text,
            query.created_from,
            query.created_to,
            query.sort,
            query.descending,
            query.page,
            query.per_page,
        ) == (None, None, None, None, "created_at", True, 1, 20)

    @pytest.mark.parametrize("per_page", [1, 100])
    def test_a_page_of_1_to_100_runs_is_a_query(self, per_page: int) -> None:
        assert RunQuery(per_page=per_page).per_page == per_page


class TestPageRuns:
    """RunStorage.page_runs: the records of one page of the runs a RunQuery matches, and the count of them all."""

    def test_the_default_query_answers_the_record_of_every_run_newest_first_and_their_count(
        self, storage: RunStorage
    ) -> None:
        _store_a_home_run(storage, "oldest", created_at="2026-10-01T09:00:00+00:00")
        _store_a_fleet_run(storage, "newest", created_at="2026-10-03T09:00:00+00:00")
        _store_a_home_run(storage, "middle", created_at="2026-10-02T09:00:00+00:00")

        page = storage.page_runs(RunQuery())

        assert page == RunPage(records=tuple(_record(storage, run_id) for run_id in ("newest", "middle", "oldest")), total=3)

    def test_a_query_of_a_run_type_lists_only_the_runs_of_that_type(self, storage: RunStorage) -> None:
        _store_a_fleet_run(storage, "fleet-1", created_at="2026-10-01T09:00:00+00:00")
        _store_a_home_run(storage, "home-1", created_at="2026-10-02T09:00:00+00:00")
        _store_a_fleet_run(storage, "fleet-2", created_at="2026-10-03T09:00:00+00:00")

        page = storage.page_runs(RunQuery(run_type="fleet"))

        assert (_ids(page), page.total) == (["fleet-2", "fleet-1"], 2)

    def test_a_query_of_a_text_lists_the_runs_whose_name_or_notes_hold_it_in_any_case(
        self, storage: RunStorage
    ) -> None:
        _store_a_home_run(storage, "named", name="North Roof Survey", created_at="2026-10-01T09:00:00+00:00")
        _store_a_home_run(storage, "noted", name="South Roof", created_at="2026-10-02T09:00:00+00:00")
        storage.update_run_labels("noted", {"notes": "The NORTH-facing panels"})
        _store_a_home_run(storage, "neither", name="East Roof", created_at="2026-10-03T09:00:00+00:00")

        page = storage.page_runs(RunQuery(text="north"))

        assert (_ids(page), page.total) == (["noted", "named"], 2)

    @pytest.mark.parametrize(
        ("text", "holder", "lookalike"),
        [
            pytest.param("100%", "Survey of 100% of roofs", "Survey of 1000 roofs", id="percent"),
            pytest.param("north_roof", "north_roof", "north-roof", id="underscore"),
            pytest.param("%", "Survey of 100% of roofs", "East Roof", id="percent-alone"),
        ],
    )
    def test_a_query_of_a_text_holding_a_wildcard_of_like_lists_only_the_runs_that_hold_the_text_itself(
        self, storage: RunStorage, text: str, holder: str, lookalike: str
    ) -> None:
        """A % or _ in the text matches only itself, not any run of characters or any one character as in a LIKE pattern."""
        _store_a_home_run(storage, "holder", name=holder, created_at="2026-10-01T09:00:00+00:00")
        _store_a_home_run(storage, "lookalike", name=lookalike, created_at="2026-10-02T09:00:00+00:00")

        page = storage.page_runs(RunQuery(text=text))

        assert (_ids(page), page.total) == (["holder"], 1)

    def test_a_query_of_dates_lists_the_runs_created_from_the_first_date_to_the_end_of_the_last(
        self, storage: RunStorage
    ) -> None:
        _store_a_home_run(storage, "day-before", created_at="2026-10-01T23:59:59.900000+00:00")
        _store_a_home_run(storage, "first-day", created_at="2026-10-02T00:00:00+00:00")
        _store_a_home_run(storage, "last-moment", created_at="2026-10-03T23:59:59.500000+00:00")
        _store_a_home_run(storage, "next-midnight", created_at="2026-10-04T00:00:00+00:00")

        page = storage.page_runs(RunQuery(created_from=date(2026, 10, 2), created_to=date(2026, 10, 3)))

        assert (_ids(page), page.total) == (["last-moment", "first-day"], 2)

    @pytest.mark.parametrize(
        ("descending", "ids"),
        [
            pytest.param(False, ["alpha", "bravo", "charlie"], id="ascending"),
            pytest.param(True, ["charlie", "bravo", "alpha"], id="descending"),
        ],
    )
    def test_a_query_sorted_by_name_lists_the_runs_in_the_order_of_their_names(
        self, storage: RunStorage, descending: bool, ids: list[str]
    ) -> None:
        """The runs are created in an order other than their names', so a list by creation time shows."""
        _store_a_home_run(storage, "bravo", name="Bravo", created_at="2026-10-01T09:00:00+00:00")
        _store_a_home_run(storage, "alpha", name="Alpha", created_at="2026-10-02T09:00:00+00:00")
        _store_a_home_run(storage, "charlie", name="Charlie", created_at="2026-10-03T09:00:00+00:00")

        page = storage.page_runs(RunQuery(sort="name", descending=descending))

        assert _ids(page) == ids

    def test_a_page_lists_its_slice_of_the_runs_and_a_page_past_the_last_lists_none_with_the_same_count(
        self, storage: RunStorage
    ) -> None:
        for day in range(1, 6):
            _store_a_home_run(storage, f"run-{day}", created_at=f"2026-10-0{day}T09:00:00+00:00")

        second = storage.page_runs(RunQuery(page=2, per_page=2))
        past_the_last = storage.page_runs(RunQuery(page=4, per_page=2))

        assert (_ids(second), second.total) == (["run-3", "run-2"], 5)
        assert (past_the_last.records, past_the_last.total) == ((), 5)

    def test_runs_that_tie_on_the_sort_column_are_ordered_by_id_so_each_is_listed_on_exactly_one_page(
        self, storage: RunStorage
    ) -> None:
        for run_id in ("tie-b", "tie-c", "tie-a"):
            _store_a_home_run(storage, run_id, created_at="2026-10-01T09:00:00+00:00")

        pages = [storage.page_runs(RunQuery(page=page, per_page=2)) for page in (1, 2)]

        assert [_ids(page) for page in pages] == [["tie-c", "tie-b"], ["tie-a"]]


def _storage_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The message of each WARNING solar_challenge.web.storage logged in the test."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "solar_challenge.web.storage" and record.levelno == logging.WARNING
    ]


def _damage_summary(storage: RunStorage, run_id: str, damaged_summary_json: str) -> None:
    """Overwrite run *run_id*'s summary_json with *damaged_summary_json*."""
    with storage.database.transaction() as conn:
        conn.execute("UPDATE runs SET summary_json = ? WHERE id = ?", (damaged_summary_json, run_id))


class TestHeadlineFigures:
    """headline_figures: the figures a run list's row shows for a run's record, under the names the run lists give them."""

    def test_a_saved_fleet_run_s_figures_are_its_generation_and_its_fleet_self_consumption_ratio(
        self, storage: RunStorage
    ) -> None:
        fleet = _two_unlike_homes()
        store_fleet_run(storage, "fleet-1", fleet)
        summary = calculate_fleet_summary(fleet)

        assert headline_figures(_record(storage, "fleet-1")) == {
            "total_generation_kwh": summary.total_generation_kwh,
            "self_consumption_ratio": summary.fleet_self_consumption_ratio,
            "unreadable": None,
        }

    def test_a_run_with_no_headline_to_read_has_neither_figure(self, storage: RunStorage) -> None:
        storage.create_run("running-1", run_type="home", name="North Roof", n_homes=1, created_at="2026-10-20T09:00:00+00:00")

        assert headline_figures(_record(storage, "running-1")) == {
            "total_generation_kwh": None,
            "self_consumption_ratio": None,
            "unreadable": None,
        }

    @pytest.mark.parametrize(
        ("damaged_summary_json", "field"),
        [
            pytest.param("{not json", None, id="summary-not-json"),
            pytest.param(
                summary_json(home_summary(total_generation_kwh=None)), "total_generation_kwh", id="generation-null"
            ),
            pytest.param(_with_a_retired_key(summary_json(home_summary())), "retired", id="summary-with-a-key-no-field-has"),
            pytest.param(
                summary_json(home_summary(total_generation_kwh=10**400)),
                "total_generation_kwh",
                id="generation-no-float-can-hold",
            ),
        ],
    )
    def test_a_run_whose_summary_cannot_be_read_has_neither_figure_and_its_refusal_as_unreadable_and_a_warning_names_it(
        self, storage: RunStorage, caplog: pytest.LogCaptureFixture, damaged_summary_json: str, field: str | None
    ) -> None:
        """A run list shows the run without figures and says why (the G7 waiver in docs/prds/run-store-one-owner.md §15)."""
        _store_a_home_run(storage, "damaged-run")
        _damage_summary(storage, "damaged-run", damaged_summary_json)
        damaged = _record(storage, "damaged-run")
        with pytest.raises(StoredRunUnreadable) as refusal:
            damaged.summary()
        caplog.set_level(logging.WARNING, logger="solar_challenge.web.storage")

        figures = headline_figures(damaged)

        assert figures == {"total_generation_kwh": None, "self_consumption_ratio": None, "unreadable": str(refusal.value)}
        assert (refusal.value.run_id, refusal.value.document, refusal.value.field) == (
            "damaged-run",
            "runs.summary_json",
            field,
        )
        warnings = _storage_warnings(caplog)
        assert len(warnings) == 1 and "damaged-run" in warnings[0], warnings

    def test_a_run_whose_headline_figure_is_not_a_finite_number_has_neither_figure_and_a_warning_names_it_though_it_reads(
        self, storage: RunStorage, caplog: pytest.LogCaptureFixture
    ) -> None:
        """NaN is a number, so the summary reads; run_headline refuses it, and no document is unreadable."""
        _store_a_home_run(storage, "nan-run")
        _damage_summary(storage, "nan-run", summary_json(home_summary(total_generation_kwh=math.nan)))
        caplog.set_level(logging.WARNING, logger="solar_challenge.web.storage")

        figures = headline_figures(_record(storage, "nan-run"))

        assert figures == {"total_generation_kwh": None, "self_consumption_ratio": None, "unreadable": None}
        warnings = _storage_warnings(caplog)
        assert len(warnings) == 1 and "nan-run" in warnings[0], warnings


class TestRunTotals:
    """RunStorage.totals: the dashboard's count of the completed runs and of their homes, and the energy they generated."""

    def test_an_empty_store_has_no_runs_no_homes_and_no_generation(self, storage: RunStorage) -> None:
        assert storage.totals() == RunTotals(run_count=0, home_count=0, generation_kwh=0.0)

    def test_the_completed_runs_of_either_kind_count_with_their_homes_and_their_generation(
        self, storage: RunStorage
    ) -> None:
        results = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
        fleet = _two_unlike_homes()
        store_home_run(storage, "home-1", make_home_config(), results)
        store_fleet_run(storage, "fleet-1", fleet)
        store_home_run(storage, "failed-1", make_home_config(), make_sim_results(days=1), status="failed")
        storage.create_run("running-1", run_type="home", name="North Roof", n_homes=1, created_at="2026-10-20T09:00:00+00:00")

        totals = storage.totals()

        assert (totals.run_count, totals.home_count) == (2, 3)
        assert totals.generation_kwh == pytest.approx(
            calculate_summary(results).total_generation_kwh + calculate_fleet_summary(fleet).total_generation_kwh
        )

    def test_a_completed_run_whose_row_records_no_count_of_homes_counts_as_one_home(self, storage: RunStorage) -> None:
        _store_a_fleet_run(storage, "fleet-1")
        with storage.database.transaction() as conn:
            conn.execute("UPDATE runs SET n_homes = NULL WHERE id = ?", ("fleet-1",))

        assert storage.totals().home_count == 1

    @pytest.mark.parametrize(
        "damaged_summary_json",
        [
            pytest.param("{not json", id="summary-not-json"),
            pytest.param(summary_json(fleet_summary(total_generation_kwh=None)), id="generation-null"),
            pytest.param(_with_a_retired_key(summary_json(fleet_summary())), id="summary-with-a-key-no-field-has"),
            pytest.param(summary_json(fleet_summary(total_generation_kwh=10**400)), id="generation-no-float-can-hold"),
        ],
    )
    def test_a_completed_run_whose_summary_is_damaged_counts_with_its_homes_adds_no_generation_and_a_warning_names_it(
        self, storage: RunStorage, caplog: pytest.LogCaptureFixture, damaged_summary_json: str
    ) -> None:
        results = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
        store_home_run(storage, "home-1", make_home_config(), results)
        _store_a_fleet_run(storage, "damaged-run")
        _damage_summary(storage, "damaged-run", damaged_summary_json)
        caplog.set_level(logging.WARNING, logger="solar_challenge.web.storage")

        totals = storage.totals()

        assert (totals.run_count, totals.home_count) == (2, 3)
        assert totals.generation_kwh == pytest.approx(calculate_summary(results).total_generation_kwh)
        warnings = _storage_warnings(caplog)
        assert len(warnings) == 1 and "damaged-run" in warnings[0], warnings
