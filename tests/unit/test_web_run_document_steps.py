# SPDX-License-Identifier: AGPL-3.0-or-later
"""The run-document steps, each of which brings a stored run's documents one format version forward (contract C5).

The generic tests run every step in RUN_DOCUMENT_STEPS over every committed legacy fixture of
tests/_stored_run_fixtures.py: the steps' versions ascend to RUN_FORMAT_VERSION, each step is
idempotent on every fixture, and each step changes at least one fixture's documents, so a new
step (contract C10) ships with a fixture that exercises it. Each step also changes nothing in
documents a later step brought forward, a fixture's or each a save of a home run or a fleet run
in the current format writes, which migration relies on to bring a runs row, which records no
format, forward from the first format.

The rest pins v2, the step that drops each key a document's dataclass does not have: what it
drops, which dropped values it reports, what it leaves for the strict reader to refuse, and that
it changes none of its input. It walks a document as the strict reader reads it: a key no field
has, added to each object of a config of every field shape, is dropped from a dataclass's object
and kept in a dict field's, and the config then reads back as the home saved. A run stored before
the battery's dispatch strategies were variants of one union migrates, then loads.

Then it pins v3, the step that reads each stored home's dispatch as it ran: which home
dispatch_strategy it reads as greedy, which grid_charging it drops, what it leaves as it is, and
that it changes none of its input.

Then it pins v4, the step that drops each battery's grid_charging that its run ignored on a tariff
with no cheap period, one whose periods all charge the same rate: which grid_charging it drops,
what it leaves as it is, and that it changes none of its input.

Then it pins v5, the step that sets each stored SummaryStatistics document lacking a window to the
window of its run's own time series, read through the documents' StoredTimeSeries, and drops each
one's simulation_days: which summaries it sets, from which series, in a run's files and its runs
row alike; that it drops simulation_days from every summary, reporting only one that differs from
its window's days, and keeps a FleetSummary's; that v2 keeps a summary's simulation_days for it;
that it reads no series for a summary holding a window and leaves every other document as it is;
and that it refuses a summary whose series is missing or is not a run's.

Then it pins v6, the step that drops each stored FleetSummary's total_seg_revenue_gbp and
per_home_seg_revenue_mean_gbp, a second copy of its total_export_revenue_gbp: that it drops them
from a fleet run's summary, in its files and its runs row alike, reporting each value that is not
null; that the dropped total is the export revenue the summary keeps; that v2 keeps the pair for
it; that it leaves a home run's documents, every home summary and every config as they are; and
that it changes none of its input.

Then it pins v7, the step that drops each stored BatteryConfig's efficiency, the round trip its
charge_efficiency and discharge_efficiency were derived from: that it drops it from a home run's
battery, in its files and its runs row alike, reporting a value that is not null by its path, a
fleet home's under its homes, and keeps the pair; that it drops each legacy fixture's null
efficiency, reporting nothing; that v2 keeps a battery's efficiency for it, at whatever depth the
battery is; that it leaves a config that is not an object as it is; that it changes none of its
input; and that a run saved with a round trip reads, once every step has brought it forward, as
the home whose battery holds the pair.

Then it pins v8, the step that moves each stored home's dispatch_strategy into its battery, the
battery's own setting, then drops the home's key, which no HomeConfig has: that a battery naming no
strategy, whose home asked for tou_optimized, takes tou_optimized on its tariff's clock, reported by
its path, in a fleet's files and its runs row alike; that every other battery naming no strategy
names self_consumption, the dispatch it ran, reporting nothing, whether or not its home holds the
key; that every other home only loses its
key, reporting nothing, a home run's at its root, a battery naming its own strategy keeping it and a
home with no battery having none to take; that v2 keeps each home's dispatch_strategy for v3 and v8; that
it leaves a config, or a fleet's home, that is not an object as it is; and that it changes none of
its input.

Last it pins v9, the step that drops each stored SummaryStatistics' seg_revenue_gbp, a second copy
of its total_export_revenue_gbp: that it drops it from a home run's summary and from each fleet
home summary, in a run's files and its runs row alike, reporting each value that is not null, the
dropped values being the export revenue each summary keeps; that it drops each legacy fixture's
null one, reporting nothing; that v2 keeps it for v9; that it leaves a fleet's FleetSummary and
config, and a summary that is not an object, as they are; that it changes none of its input; and
that a run stored with one reads once brought forward.
"""

import copy
import dataclasses
import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.fleet import aggregate_home_summaries, calculate_home_summaries
from solar_challenge.home import HomeConfig, SummaryStatistics, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import SimulationWindow
from solar_challenge.web.field_tree import field_tree
from solar_challenge.web.stored_runs import (
    RUN_DOCUMENT_STEPS,
    RUN_FORMAT_VERSION,
    DroppedValue,
    RewrittenValue,
    FleetRunConfig,
    RunDocumentStep,
    RunType,
    StoredDocument,
    StoredFleetRun,
    StoredHomeRun,
    StoredRunDocuments,
    StoredRunUnreadable,
    StoredTimeSeries,
    documents_in_current_format,
    read_run_documents,
)
from tests._every_field_shape import home_of_every_field_shape
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._stored_run_fixtures import (
    PRE_975_FLEET_SEG_REVENUE_KEYS,
    STORED_RUN_FIXTURES,
    fixture_run_type,
    fixture_runs_row,
    pre_dispatch_union_home_config,
    stored_run_fixture_dir,
)


def _step(version: int) -> RunDocumentStep:
    """The one of RUN_DOCUMENT_STEPS of *version*."""
    return next(step for step in RUN_DOCUMENT_STEPS if step.version == version)


_V2 = _step(2)
_V3 = _step(3)

_STRATEGIES_AND_THE_GRID_CHARGING_THEY_RAN_BY = [
    pytest.param(SelfConsumptionStrategyConfig(), None, id="self_consumption"),
    pytest.param(
        TOUOptimizedStrategyConfig(peak_hours=((16, 19),)), GridChargeConfig(target_soc_fraction=0.8), id="tou_optimized"
    ),
    pytest.param(
        PeakShavingStrategyConfig(import_limit_kw=3.0), GridChargeConfig(target_soc_fraction=0.8), id="peak_shaving"
    ),
]
"""One example of each dispatch strategy, those of the stored configs above, and the grid charging each ran by:
self-consumption dispatch ignored the stored configs' grid charging."""

Keys = tuple[str | int, ...]

_ECONOMY_7_AS_STORED = TariffConfig.economy_7(off_peak_rate=0.09, peak_rate=0.25)
"""The Economy 7 tariff the stored runs below were priced at, the preset's default rates when they ran."""


def _dispatching_home(strategy: Any, grid_charging: GridChargeConfig | None, name: str) -> HomeConfig:
    """A home on Economy 7 whose battery dispatches by *strategy* and grid-charges by *grid_charging*."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0),
        battery_config=BatteryConfig(capacity_kwh=5.0, dispatch_strategy=strategy, grid_charging=grid_charging),
        tariff_config=_ECONOMY_7_AS_STORED,
        name=name,
    )


def _fixture_documents(name: str) -> StoredRunDocuments:
    """The documents of fixture *name*'s run directory, read as a run whose id is *name*."""
    return read_run_documents(stored_run_fixture_dir(name), name, fixture_run_type(name))


def _current_documents(name: str) -> StoredRunDocuments:
    """The documents of fixture *name*, brought forward by every step to the current format."""
    return documents_in_current_format(fixture_run_type(name), _fixture_documents(name))


def _documents_before(step: RunDocumentStep, name: str) -> StoredRunDocuments:
    """The documents of fixture *name*, brought forward by every step before *step*."""
    return _brought_forward_before(step, fixture_run_type(name), _fixture_documents(name))


def _brought_forward_before(step: RunDocumentStep, run_type: RunType, documents: StoredRunDocuments) -> StoredRunDocuments:
    """*documents*, of a run of type *run_type*, brought forward by every step before *step*."""
    for earlier in RUN_DOCUMENT_STEPS[: RUN_DOCUMENT_STEPS.index(step)]:
        documents = earlier.apply(run_type, documents).documents
    return documents


def _with_value(documents: StoredRunDocuments, document: str, keys: Keys, value: Any) -> StoredRunDocuments:
    """*documents*, with a copy of the one named *document* holding *value* at *keys*, a key or an index per level."""

    def edited(stored: StoredDocument) -> StoredDocument:
        if stored.name != document:
            return stored
        content = copy.deepcopy(stored.content)
        *parents, last = keys
        target = content
        for key in parents:
            target = target[key]
        target[last] = value
        return dataclasses.replace(stored, content=content)

    return dataclasses.replace(
        documents,
        config=edited(documents.config),
        summary=edited(documents.summary),
        home_summaries=tuple(edited(each) for each in documents.home_summaries),
    )


def _without(documents: StoredRunDocuments, document: str, key: str) -> StoredRunDocuments:
    """*documents*, with a copy of the one named *document* lacking *key* at its root."""

    def edited(stored: StoredDocument) -> StoredDocument:
        if stored.name != document:
            return stored
        return dataclasses.replace(stored, content={name: item for name, item in stored.content.items() if name != key})

    return dataclasses.replace(
        documents,
        config=edited(documents.config),
        summary=edited(documents.summary),
        home_summaries=tuple(edited(each) for each in documents.home_summaries),
    )


def test_the_steps_versions_ascend_to_the_format_version() -> None:
    versions = [step.version for step in RUN_DOCUMENT_STEPS]

    assert versions, "RUN_DOCUMENT_STEPS holds no step"
    assert all(earlier < later for earlier, later in zip(versions, versions[1:])), versions
    assert RUN_FORMAT_VERSION == RUN_DOCUMENT_STEPS[-1].version


@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_every_step_is_idempotent_on_the_fixture(name: str) -> None:
    run_type = fixture_run_type(name)
    documents = _fixture_documents(name)

    for step in RUN_DOCUMENT_STEPS:
        once = step.apply(run_type, documents)
        twice = step.apply(run_type, once.documents)

        assert twice.documents == once.documents, f"step {step.version} changes its own result"
        assert twice.dropped == (), f"step {step.version} drops from its own result"
        assert twice.rewritten == (), f"step {step.version} rewrites its own result"
        documents = once.documents


@pytest.mark.parametrize("step", RUN_DOCUMENT_STEPS, ids=lambda step: f"v{step.version}")
def test_every_step_changes_a_fixture_s_documents(step: RunDocumentStep) -> None:
    """A step no fixture exercises ships untested: add a fixture of the documents it changes (contract C10)."""
    changed = [
        name
        for name in STORED_RUN_FIXTURES
        if step.apply(fixture_run_type(name), _documents_before(step, name)).documents != _documents_before(step, name)
    ]

    assert changed, f"step {step.version} changes no fixture in {list(STORED_RUN_FIXTURES)}"


_EACH_FIXTURE_AND_STEP_BEFORE_A_LATER_STEP = [
    pytest.param(name, earlier, later, id=f"{name}-v{earlier.version}-after-v{later.version}")
    for name in STORED_RUN_FIXTURES
    for earlier in RUN_DOCUMENT_STEPS
    for later in RUN_DOCUMENT_STEPS
    if earlier.version < later.version
]


@pytest.mark.parametrize(("name", "earlier", "later"), _EACH_FIXTURE_AND_STEP_BEFORE_A_LATER_STEP)
def test_every_step_changes_nothing_in_a_fixture_s_documents_a_later_step_brought_forward(
    name: str, earlier: RunDocumentStep, later: RunDocumentStep
) -> None:
    """A runs row records no format, so migration brings a row it cannot bring forward from its store's format forward from the first (storage.migrate_runs_table_documents).

    That is exact only while each step changes nothing in documents a later step brought
    forward: a step that cannot keep to it must first give each runs row a format of its own.
    """
    run_type = fixture_run_type(name)
    brought_forward = later.apply(run_type, _documents_before(later, name)).documents

    result = earlier.apply(run_type, brought_forward)

    assert result.documents == brought_forward
    assert (result.dropped, result.rewritten) == ((), ())


_SAVED_RUN = "saved"


def _as_saved(name: str, content: dict[str, Any]) -> StoredDocument:
    """Document *name* of run _SAVED_RUN holding *content* as its file and its runs row hold it: decoded from the JSON a save writes."""
    return StoredDocument(_SAVED_RUN, name, json.loads(json.dumps(content)))


def _documents_a_home_run_s_save_writes() -> StoredRunDocuments:
    """The documents a save of a home of every field shape writes, built as StoredHomeRun builds them: its config and its summary.

    Its summary holds its window, so no step reads its time series, and the documents name no directory.
    """
    results = make_sim_results(days=1)
    run = StoredHomeRun(_SAVED_RUN, home_of_every_field_shape(), results, calculate_summary(results))
    return StoredRunDocuments(
        config=_as_saved("config.json", run.config_document()),
        summary=_as_saved("summary.json", run.summary_document()),
        time_series=StoredTimeSeries(_SAVED_RUN, None),
    )


def _documents_a_fleet_run_s_save_writes() -> StoredRunDocuments:
    """The documents a save of a fleet of a home of every field shape and a default home writes, built as StoredFleetRun builds them: its config, its summary and each home's summary."""
    fleet_results = make_fleet_results_of(
        [make_sim_results(days=1), make_sim_results(days=1)], homes=[home_of_every_field_shape(), make_home_config()]
    )
    home_summaries = tuple(calculate_home_summaries(fleet_results))
    run = StoredFleetRun(_SAVED_RUN, fleet_results, aggregate_home_summaries(home_summaries), home_summaries)
    return StoredRunDocuments(
        config=_as_saved("config.json", run.config_document()),
        summary=_as_saved("summary.json", run.summary_document()),
        time_series=StoredTimeSeries(_SAVED_RUN, None),
        home_summaries=tuple(
            _as_saved(f"homes/home_{index}_summary.json", field_tree(summary)) for index, summary in enumerate(home_summaries)
        ),
    )


_DOCUMENTS_A_SAVE_WRITES = [
    pytest.param("home", _documents_a_home_run_s_save_writes, id="home-run"),
    pytest.param("fleet", _documents_a_fleet_run_s_save_writes, id="fleet-run"),
]


@pytest.mark.parametrize("step", RUN_DOCUMENT_STEPS, ids=lambda step: f"v{step.version}")
@pytest.mark.parametrize(("run_type", "documents_a_save_writes"), _DOCUMENTS_A_SAVE_WRITES)
def test_every_step_changes_nothing_in_the_documents_a_save_in_the_current_format_writes(
    step: RunDocumentStep, run_type: RunType, documents_a_save_writes: Callable[[], StoredRunDocuments]
) -> None:
    """Each document a save of a home run or a fleet run writes, to its files and its runs row alike, is in the current format: no step changes it.

    The home run's home, and the fleet's first, is of every field shape; the fleet's second is a default home.
    """
    documents = documents_a_save_writes()

    result = step.apply(run_type, documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v2_drops_the_null_keys_of_the_other_dispatch_variants_and_reports_nothing() -> None:
    """Once every later step has brought its result forward, the config reads as the variant its dispatch strategy names."""
    result = _V2.apply("home", _fixture_documents("pre_786_dispatch_home"))

    battery = documents_in_current_format("home", result.documents).config.read(HomeConfig).battery_config

    assert result.dropped == ()
    assert result.documents.config.content["battery_config"]["dispatch_strategy"] == {
        "strategy_type": "tou_optimized",
        "peak_hours": [[16, 19]],
    }
    assert battery is not None
    assert battery.dispatch_strategy == TOUOptimizedStrategyConfig(peak_hours=((16, 19),))
    assert battery.grid_charging == GridChargeConfig(target_soc_fraction=0.8)


@pytest.mark.parametrize(("strategy", "grid_charging"), _STRATEGIES_AND_THE_GRID_CHARGING_THEY_RAN_BY)
def test_v2_migrates_a_config_stored_before_the_dispatch_union_then_it_loads_as_its_variant_as_it_ran(
    strategy: Any, grid_charging: GridChargeConfig | None
) -> None:
    """786's pre-union configs: v2 reports nothing, and once every step has brought one forward it reads as the home that ran."""
    tag = strategy.strategy_type
    stored = pre_dispatch_union_home_config(tag)
    documents = dataclasses.replace(
        _fixture_documents("pre_786_dispatch_home"), config=StoredDocument("pre-union-001", "config.json", stored)
    )

    assert _V2.apply("home", documents).dropped == ()
    assert documents_in_current_format("home", documents).config.read(HomeConfig) == _dispatching_home(
        strategy, grid_charging, name=f"Stored before the dispatch union: {tag}"
    )


_UNKNOWN_KEYS = [
    ("pre_786_dispatch_home", "config.json", ("retired_setting",), "retired_setting"),
    ("pre_786_dispatch_home", "config.json", ("pv_config", "retired"), "pv_config.retired"),
    ("pre_786_dispatch_home", "config.json", ("tariff_config", "periods", 0, "x"), "tariff_config.periods[0].x"),
    (
        "pre_786_dispatch_home",
        "config.json",
        ("battery_config", "dispatch_strategy", "x"),
        "battery_config.dispatch_strategy.x",
    ),
    ("legacy_fleet", "config.json", ("homes", 1, "pv_config", "x"), "homes[1].pv_config.x"),
    ("pre_786_dispatch_home", "summary.json", ("retired_figure",), "retired_figure"),
    ("legacy_fleet", "summary.json", ("retired_figure",), "retired_figure"),
    ("legacy_fleet", "homes/home_0_summary.json", ("retired_figure",), "retired_figure"),
]
_UNKNOWN_KEY_IDS = [
    "at-the-root",
    "in-a-nested-dataclass",
    "in-an-array-item",
    "inside-a-union-variant",
    "in-a-fleet-home",
    "in-a-summary",
    "in-a-fleet-summary",
    "in-a-fleet-home-summary",
]


@pytest.mark.parametrize(("name", "document", "keys", "field"), _UNKNOWN_KEYS, ids=_UNKNOWN_KEY_IDS)
@pytest.mark.parametrize("value", [12.5, "retired", [1, 2], {"a": 1}, False], ids=repr)
def test_v2_drops_an_unknown_key_reporting_its_value(
    name: str, document: str, keys: Keys, field: str, value: Any
) -> None:
    current = _current_documents(name)

    result = _V2.apply(fixture_run_type(name), _with_value(current, document, keys, value))

    assert result.documents == current
    assert result.dropped == (DroppedValue(name, document, field, value),)


@pytest.mark.parametrize(("name", "document", "keys", "field"), _UNKNOWN_KEYS, ids=_UNKNOWN_KEY_IDS)
def test_v2_drops_an_unknown_key_holding_null_without_reporting_it(
    name: str, document: str, keys: Keys, field: str
) -> None:
    current = _current_documents(name)

    result = _V2.apply(fixture_run_type(name), _with_value(current, document, keys, None))

    assert result.documents == current
    assert result.dropped == ()


def test_v2_reports_each_dropped_value_of_each_document_of_a_fleet_run() -> None:
    current = _current_documents("legacy_fleet")
    documents = _with_value(current, "config.json", ("homes", 1, "pv_config", "x"), 1)
    documents = _with_value(documents, "summary.json", ("retired_figure",), 2)
    documents = _with_value(documents, "homes/home_1_summary.json", ("retired_figure",), 3)

    result = _V2.apply("fleet", documents)

    assert result.documents == current
    assert result.dropped == (
        DroppedValue("legacy_fleet", "config.json", "homes[1].pv_config.x", 1),
        DroppedValue("legacy_fleet", "summary.json", "retired_figure", 2),
        DroppedValue("legacy_fleet", "homes/home_1_summary.json", "retired_figure", 3),
    )


_EVERY_SHAPE_RUN = "every-shape"

_EVERY_SHAPE_CONFIG = json.loads(json.dumps(dataclasses.asdict(home_of_every_field_shape())))
"""home_of_every_field_shape()'s config document: its field tree in JSON, as a save writes it (tests/unit/test_web_storage_roundtrip.py::TestPersistedJson)."""

_A_DICT_FIELD: Keys = ("pv_config", "custom_module_params")
"""The one object of that document that is a dict field's, whose keys are its own rather than fields."""


def _object_keys(content: Any, keys: Keys = ()) -> Iterator[Keys]:
    """The keys of each JSON object within *content*, itself first when it is one, a key or an index per level."""
    if isinstance(content, dict):
        yield keys
        for key, item in content.items():
            yield from _object_keys(item, (*keys, key))
    elif isinstance(content, list):
        for index, item in enumerate(content):
            yield from _object_keys(item, (*keys, index))


def _dotted(keys: Keys) -> str:
    """The path of the value at *keys* as a DroppedValue names its field: dotted, with [i] for an item."""
    return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in keys).lstrip(".")


def _every_shape_documents() -> StoredRunDocuments:
    """A home run's documents whose config is _EVERY_SHAPE_CONFIG and which has no summary yet."""
    return StoredRunDocuments(
        config=StoredDocument(_EVERY_SHAPE_RUN, "config.json", copy.deepcopy(_EVERY_SHAPE_CONFIG)),
        summary=StoredDocument(_EVERY_SHAPE_RUN, "summary.json", None),
        time_series=StoredTimeSeries(_EVERY_SHAPE_RUN, None),
    )


@pytest.mark.parametrize(
    "keys",
    [keys for keys in _object_keys(_EVERY_SHAPE_CONFIG) if keys != _A_DICT_FIELD],
    ids=lambda keys: _dotted(keys) or "the-home",
)
def test_v2_drops_a_key_no_field_has_from_each_dataclass_s_object_of_a_config_of_every_field_shape(keys: Keys) -> None:
    """Review suggestion 3: v2 must walk each value as the strict reader reads it, or the reader refuses the key v2 kept."""
    documents = _every_shape_documents()

    result = _V2.apply("home", _with_value(documents, "config.json", (*keys, "retired"), 1.5))

    assert result.documents == documents
    assert result.dropped == (DroppedValue(_EVERY_SHAPE_RUN, "config.json", _dotted((*keys, "retired")), 1.5),)
    assert result.documents.config.read(HomeConfig) == home_of_every_field_shape()


def test_v2_keeps_a_key_of_a_dict_field_s_object() -> None:
    """A dict's keys are its own, not a dataclass's fields, so none is a key v2 drops."""
    documents = _with_value(_every_shape_documents(), "config.json", (*_A_DICT_FIELD, "retired"), 1.5)

    result = _V2.apply("home", documents)

    assert (result.documents, result.dropped) == (documents, ())
    assert result.documents.config.read(HomeConfig).pv_config.custom_module_params == {
        "pdc0": 250.0,
        "gamma_pdc": -0.004,
        "retired": 1.5,
    }


def test_v2_leaves_a_missing_required_field_for_the_strict_reader_to_refuse() -> None:
    lacking = _without(_current_documents("pre_786_dispatch_home"), "summary.json", "total_generation_kwh")

    result = _V2.apply("home", _with_value(lacking, "summary.json", ("retired_figure",), 12.5))

    assert result.documents == lacking
    with pytest.raises(StoredRunUnreadable) as refused:
        result.documents.summary.read(SummaryStatistics)
    assert refused.value.field == "total_generation_kwh"


def test_v2_leaves_a_value_of_a_type_its_field_cannot_be_for_the_strict_reader_to_refuse() -> None:
    big = _with_value(_current_documents("pre_786_dispatch_home"), "config.json", ("battery_config",), "big")

    result = _V2.apply("home", _with_value(big, "config.json", ("pv_config", "retired"), 1.0))

    assert result.documents == big
    assert result.dropped == (DroppedValue("pre_786_dispatch_home", "config.json", "pv_config.retired", 1.0),)
    with pytest.raises(StoredRunUnreadable) as refused:
        result.documents.config.read(HomeConfig)
    assert refused.value.field == "battery_config"


def test_v2_leaves_a_summary_that_is_not_an_object_as_it_is() -> None:
    current = _current_documents("pre_786_dispatch_home")
    not_an_object = dataclasses.replace(current, summary=dataclasses.replace(current.summary, content=["not", "a", "summary"]))

    result = _V2.apply("home", not_an_object)

    assert result.documents == not_an_object
    assert result.dropped == ()


def test_v2_changes_none_of_its_input_documents() -> None:
    documents = _with_value(_fixture_documents("pre_786_dispatch_home"), "config.json", ("pv_config", "retired"), "x")
    before = copy.deepcopy(documents)

    _V2.apply("home", documents)

    assert documents == before


_GRID_CHARGING_TO_80_PERCENT = {"target_soc_fraction": 0.8}
"""The grid_charging object of every battery of pre_786_dispatch_home, pre_787_dispatch_fleet and pre_839_flat_grid_charging_fleet."""

_PEAK_SHAVING = {"strategy_type": "peak_shaving", "import_limit_kw": 3.0}


def _home_run_before(step: RunDocumentStep, *edits: tuple[Keys, Any]) -> StoredRunDocuments:
    """pre_786_dispatch_home's documents as *step* is given them, its config holding each edit's value at the edit's keys."""
    documents = _documents_before(step, "pre_786_dispatch_home")
    for keys, value in edits:
        documents = _with_value(documents, "config.json", keys, value)
    return documents


def _fleet_fixture_home(name: str, battery: BatteryConfig, **home: Any) -> HomeConfig:
    """A home of pre_787_dispatch_fleet or pre_839_flat_grid_charging_fleet, whose homes share their PV and load, named *name*, with *battery* and the rest of *home*."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
        battery_config=battery,
        name=name,
        **home,
    )


def test_v3_reads_each_home_of_the_pre_787_fleet_as_it_ran_reporting_each_value_it_changes() -> None:
    """Once every later step has brought its result forward, the config reads as the homes that ran."""
    name = "pre_787_dispatch_fleet"

    result = _V3.apply("fleet", _documents_before(_V3, name))

    assert result.dropped == ()
    assert result.rewritten == (
        RewrittenValue(name, "config.json", "homes[0].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
        RewrittenValue(name, "config.json", "homes[1].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
        RewrittenValue(name, "config.json", "homes[2].dispatch_strategy", "tou_optimized", "greedy"),
        RewrittenValue(name, "config.json", "homes[2].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
    )
    assert documents_in_current_format("fleet", result.documents).config.read(FleetRunConfig).homes == (
        _fleet_fixture_home(
            "Elm Row 1",
            BatteryConfig(capacity_kwh=5.0, dispatch_strategy=SelfConsumptionStrategyConfig()),
            tariff_config=_ECONOMY_7_AS_STORED,
        ),
        _fleet_fixture_home(
            "Elm Row 2",
            BatteryConfig(capacity_kwh=5.0, dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19),))),
        ),
        _fleet_fixture_home("Elm Row 3", BatteryConfig(capacity_kwh=5.0)),
    )


_RAN_DIFFERENTLY = [
    pytest.param(
        [(("battery_config", "dispatch_strategy"), {"strategy_type": "self_consumption"})],
        [(("battery_config", "grid_charging"), None)],
        [("battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None)],
        id="grid-charging-under-self-consumption",
    ),
    pytest.param(
        [(("tariff_config",), None)],
        [(("battery_config", "grid_charging"), None)],
        [("battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None)],
        id="grid-charging-without-a-tariff",
    ),
    pytest.param(
        [(("dispatch_strategy",), "tou_optimized"), (("battery_config", "dispatch_strategy"), None), (("tariff_config",), None)],
        [(("dispatch_strategy",), "greedy"), (("battery_config", "grid_charging"), None)],
        [
            ("dispatch_strategy", "tou_optimized", "greedy"),
            ("battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
        ],
        id="home-tou-optimized-without-a-tariff",
    ),
    pytest.param(
        [(("dispatch_strategy",), "tou_optimised")],
        [(("dispatch_strategy",), "greedy")],
        [("dispatch_strategy", "tou_optimised", "greedy")],
        id="unknown-home-dispatch-strategy",
    ),
]


@pytest.mark.parametrize(("edits", "as_it_ran", "reported"), _RAN_DIFFERENTLY)
def test_v3_reads_a_home_run_s_dispatch_as_it_ran_reporting_each_value_it_changes(
    edits: list[tuple[Keys, Any]], as_it_ran: list[tuple[Keys, Any]], reported: list[tuple[str, Any, Any]]
) -> None:
    result = _V3.apply("home", _home_run_before(_V3, *edits))

    assert result.documents == _home_run_before(_V3, *edits, *as_it_ran)
    assert result.dropped == ()
    assert result.rewritten == tuple(
        RewrittenValue("pre_786_dispatch_home", "config.json", field, was, now) for field, was, now in reported
    )


_RAN_AS_STORED = [
    pytest.param([], id="tou-optimized-battery-grid-charging-on-economy-7"),
    pytest.param(
        [(("dispatch_strategy",), "tou_optimized"), (("battery_config", "dispatch_strategy"), None)],
        id="home-tou-optimized-on-economy-7-grid-charging",
    ),
    pytest.param(
        [(("battery_config", "dispatch_strategy"), _PEAK_SHAVING)], id="peak-shaving-battery-grid-charging-on-economy-7"
    ),
    pytest.param(
        [(("dispatch_strategy",), "tou_optimized"), (("battery_config", "dispatch_strategy"), _PEAK_SHAVING)],
        id="home-tou-optimized-beside-a-peak-shaving-battery",
    ),
    pytest.param(
        [(("dispatch_strategy",), "tou_optimized"), (("battery_config",), None), (("tariff_config",), None)],
        id="batteryless-home-tou-optimized-without-a-tariff",
    ),
    pytest.param([(("battery_config",), "not a battery")], id="battery-config-not-an-object"),
]


@pytest.mark.parametrize("edits", _RAN_AS_STORED)
def test_v3_leaves_a_home_run_that_ran_as_stored_as_it_is(edits: list[tuple[Keys, Any]]) -> None:
    documents = _home_run_before(_V3, *edits)

    result = _V3.apply("home", documents)

    assert result.documents == documents
    assert result.dropped == ()
    assert result.rewritten == ()


@pytest.mark.parametrize("content", ["not a config", ["not", "a", "config"]], ids=["text", "array"])
def test_v3_leaves_a_config_that_is_not_an_object_as_it_is(content: Any) -> None:
    documents = dataclasses.replace(
        _home_run_before(_V3), config=StoredDocument("pre_786_dispatch_home", "config.json", content)
    )

    result = _V3.apply("home", documents)

    assert result.documents == documents
    assert result.dropped == ()
    assert result.rewritten == ()


def test_v3_changes_none_of_its_input_documents() -> None:
    documents = _documents_before(_V3, "pre_787_dispatch_fleet")
    before = copy.deepcopy(documents)

    _V3.apply("fleet", documents)

    assert documents == before


def test_v4_drops_the_grid_charging_each_home_of_the_pre_839_fleet_ignored_on_its_flat_tariff() -> None:
    """Once every later step has brought its result forward, the config reads as the homes that ran."""
    name = "pre_839_flat_grid_charging_fleet"
    v4 = _step(4)

    result = v4.apply("fleet", _documents_before(v4, name))

    assert result.dropped == ()
    assert result.rewritten == tuple(
        RewrittenValue(name, "config.json", f"homes[{index}].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None)
        for index in range(3)
    )
    assert documents_in_current_format("fleet", result.documents).config.read(FleetRunConfig).homes == (
        _fleet_fixture_home(
            "Flat Row 1",
            BatteryConfig(capacity_kwh=5.0, dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19),))),
            tariff_config=TariffConfig.flat_rate(0.25),
        ),
        _fleet_fixture_home(
            "Flat Row 2",
            BatteryConfig(capacity_kwh=5.0, dispatch_strategy=PeakShavingStrategyConfig(import_limit_kw=3.0)),
            tariff_config=TariffConfig.flat_rate(0.25),
        ),
        _fleet_fixture_home(
            "Flat Row 3",
            BatteryConfig(capacity_kwh=5.0, dispatch_strategy=TOUOptimizedStrategyConfig()),
            tariff_config=TariffConfig.flat_rate(0.25),
        ),
    )


_FLAT_TARIFF = field_tree(TariffConfig.flat_rate(0.25))
"""A flat tariff of 0.25 £/kWh as a stored home's tariff_config holds it: one period, all day."""

_RAN_WITHOUT_GRID_CHARGE = [
    pytest.param([(("tariff_config",), _FLAT_TARIFF)], id="tou-optimized-battery-on-a-flat-tariff"),
    pytest.param(
        [(("tariff_config", "periods", 0, "rate_per_kwh"), 0.25)], id="tou-optimized-battery-on-two-periods-of-one-rate"
    ),
    pytest.param(
        [
            (("dispatch_strategy",), "tou_optimized"),
            (("battery_config", "dispatch_strategy"), None),
            (("tariff_config",), _FLAT_TARIFF),
        ],
        id="home-tou-optimized-on-a-flat-tariff",
    ),
]
"""Edits to pre_786_dispatch_home's config before v4, each giving its grid-charging battery a tariff with no cheap period.

Its Economy 7 tariff's first period is the off-peak one, so charging the second period's 0.25 there
leaves both periods charging one rate.
"""


@pytest.mark.parametrize("edits", _RAN_WITHOUT_GRID_CHARGE)
def test_v4_drops_the_grid_charging_a_home_run_ignored_on_a_tariff_with_no_cheap_period_reporting_it(
    edits: list[tuple[Keys, Any]],
) -> None:
    v4 = _step(4)

    result = v4.apply("home", _home_run_before(v4, *edits))

    assert result.documents == _home_run_before(v4, *edits, (("battery_config", "grid_charging"), None))
    assert result.dropped == ()
    assert result.rewritten == (
        RewrittenValue(
            "pre_786_dispatch_home", "config.json", "battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None
        ),
    )
    battery = documents_in_current_format("home", result.documents).config.read(HomeConfig).battery_config
    assert battery is not None and battery.grid_charging is None


_FLAT_PERIOD = _FLAT_TARIFF["periods"][0]

_LEFT_AS_IT_IS_BY_V4 = [
    pytest.param([], id="tou-optimized-battery-grid-charging-on-economy-7"),
    pytest.param(
        [(("battery_config", "dispatch_strategy"), _PEAK_SHAVING)], id="peak-shaving-battery-grid-charging-on-economy-7"
    ),
    pytest.param([(("tariff_config",), None)], id="no-tariff"),
    pytest.param([(("tariff_config",), "Flat rate 0.25")], id="tariff-not-an-object"),
    pytest.param([(("tariff_config",), {**_FLAT_TARIFF, "periods": _FLAT_PERIOD})], id="periods-not-a-list"),
    pytest.param([(("tariff_config",), {**_FLAT_TARIFF, "periods": []})], id="no-periods"),
    pytest.param([(("tariff_config",), {**_FLAT_TARIFF, "periods": ["All day"]})], id="a-period-not-an-object"),
    pytest.param(
        [(("tariff_config",), _FLAT_TARIFF), (("tariff_config", "periods", 0, "rate_per_kwh"), "0.25")],
        id="a-rate-not-a-number",
    ),
    pytest.param(
        [
            (("tariff_config",), _FLAT_TARIFF),
            (("tariff_config", "periods", 0), {key: value for key, value in _FLAT_PERIOD.items() if key != "rate_per_kwh"}),
        ],
        id="a-period-without-a-rate",
    ),
    pytest.param(
        [(("tariff_config", "periods", 0, "rate_per_kwh"), True), (("tariff_config", "periods", 1, "rate_per_kwh"), True)],
        id="rates-that-are-booleans",
    ),
    pytest.param([(("battery_config",), None), (("tariff_config",), _FLAT_TARIFF)], id="batteryless-home-on-a-flat-tariff"),
    pytest.param(
        [(("battery_config", "grid_charging"), None), (("tariff_config",), _FLAT_TARIFF)],
        id="no-grid-charging-on-a-flat-tariff",
    ),
]
"""Edits to pre_786_dispatch_home's config before v4 that leave no grid_charging set beside a tariff whose periods v4 can read as all charging one number."""


@pytest.mark.parametrize("edits", _LEFT_AS_IT_IS_BY_V4)
def test_v4_leaves_a_home_run_that_is_not_grid_charging_on_one_rate_as_it_is(edits: list[tuple[Keys, Any]]) -> None:
    v4 = _step(4)
    documents = _home_run_before(v4, *edits)

    result = v4.apply("home", documents)

    assert result.documents == documents
    assert result.dropped == ()
    assert result.rewritten == ()


@pytest.mark.parametrize(
    ("run_type", "name", "content"),
    [
        pytest.param("home", "pre_786_dispatch_home", "not a config", id="home-text"),
        pytest.param("home", "pre_786_dispatch_home", ["not", "a", "config"], id="home-array"),
        pytest.param("fleet", "pre_839_flat_grid_charging_fleet", ["not", "a", "config"], id="fleet-array"),
        pytest.param(
            "fleet", "pre_839_flat_grid_charging_fleet", {"homes": "not a list", "n_homes": 3}, id="fleet-homes-not-a-list"
        ),
    ],
)
def test_v4_leaves_a_config_that_is_not_an_object_or_whose_homes_are_not_a_list_as_it_is(
    run_type: RunType, name: str, content: Any
) -> None:
    v4 = _step(4)
    documents = dataclasses.replace(
        _documents_before(v4, name), config=StoredDocument(name, "config.json", content)
    )

    result = v4.apply(run_type, documents)

    assert result.documents == documents
    assert result.dropped == ()
    assert result.rewritten == ()


def test_v4_changes_none_of_its_input_documents() -> None:
    v4 = _step(4)
    documents = _documents_before(v4, "pre_839_flat_grid_charging_fleet")
    before = copy.deepcopy(documents)

    v4.apply("fleet", documents)

    assert documents == before


@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_a_run_s_documents_read_from_its_directory_carry_its_time_series(name: str) -> None:
    assert _fixture_documents(name).time_series == StoredTimeSeries(name, stored_run_fixture_dir(name))


def _window_of_the_series(run_dir: Path, series: str) -> dict[str, Any]:
    """The JSON form, as a save writes it, of the window SimulationWindow.of_index reads from the index of the time series *series* in *run_dir*."""
    index = pd.read_parquet(run_dir / series, engine="pyarrow").index
    return json.loads(json.dumps(field_tree(SimulationWindow.of_index(index))))


_SUMMARIES_WITHOUT_A_WINDOW_AND_THEIR_SERIES: dict[str, tuple[tuple[str, str], ...]] = {
    "pre_469_home": (("summary.json", "data.parquet"),),
    "legacy_fleet": (
        ("homes/home_0_summary.json", "homes/home_0.parquet"),
        ("homes/home_1_summary.json", "homes/home_1.parquet"),
    ),
    "pre_786_dispatch_home": (("summary.json", "data.parquet"),),
}
"""Each fixture saved before summaries carried a window: each of its SummaryStatistics documents, all lacking one, and the time series of the results it summarises."""


_SUMMARIES_HOLDING_A_WINDOW = {
    "pre_787_dispatch_fleet": tuple(f"homes/home_{index}_summary.json" for index in range(3)),
    "pre_839_flat_grid_charging_fleet": tuple(f"homes/home_{index}_summary.json" for index in range(3)),
}
"""Each fixture saved once summaries carried a window: each of its SummaryStatistics documents, all holding one beside its simulation_days."""


def _with_the_windows_of_their_series(documents: StoredRunDocuments, name: str, run_dir: Path) -> StoredRunDocuments:
    """*documents*, of fixture *name*, with each summary _SUMMARIES_WITHOUT_A_WINDOW_AND_THEIR_SERIES names set to the window of its time series in *run_dir*, and without its simulation_days."""
    for document, series in _SUMMARIES_WITHOUT_A_WINDOW_AND_THEIR_SERIES[name]:
        documents = _with_value(documents, document, ("window",), _window_of_the_series(run_dir, series))
        documents = _without(documents, document, "simulation_days")
    return documents


@pytest.mark.parametrize("name", list(_SUMMARIES_WITHOUT_A_WINDOW_AND_THEIR_SERIES))
def test_v5_sets_each_summary_without_a_window_to_the_window_of_its_time_series_dropping_its_days_reporting_nothing(
    name: str,
) -> None:
    """A home run's summary is of data.parquet and a fleet's i-th home summary of homes/home_i.parquet; each stored simulation_days is its window's 1 day, so none is reported. A fleet's FleetSummary, its simulation_days with it, and every config are left as they are."""
    v5 = _step(5)
    documents = _documents_before(v5, name)

    result = v5.apply(fixture_run_type(name), documents)

    assert result.documents == _with_the_windows_of_their_series(documents, name, stored_run_fixture_dir(name))
    assert (result.dropped, result.rewritten) == ((), ())


def _runs_row_documents(name: str) -> StoredRunDocuments:
    """The documents fixture *name*'s runs row holds, runs.config_json and runs.summary_json, of a run whose id is *name* and whose time series are those of the fixture's run directory."""
    row = fixture_runs_row(name)
    return StoredRunDocuments(
        config=StoredDocument.decoded(name, "runs.config_json", row["config_json"]),
        summary=StoredDocument.decoded(name, "runs.summary_json", row["summary_json"]),
        time_series=StoredTimeSeries(name, stored_run_fixture_dir(name)),
    )


@pytest.mark.parametrize("name", ["pre_469_home", "pre_786_dispatch_home"])
def test_v5_sets_a_home_run_s_runs_row_summary_without_a_window_to_the_window_of_its_data_parquet(name: str) -> None:
    v5 = _step(5)
    documents = _brought_forward_before(v5, "home", _runs_row_documents(name))

    result = v5.apply("home", documents)

    window = _window_of_the_series(stored_run_fixture_dir(name), "data.parquet")
    with_its_window = _with_value(documents, "runs.summary_json", ("window",), window)
    assert result.documents == _without(with_its_window, "runs.summary_json", "simulation_days")
    assert (result.dropped, result.rewritten) == ((), ())


def test_v5_leaves_a_fleet_run_s_runs_row_as_it_is() -> None:
    """A fleet's runs row holds its config and its FleetSummary, which has no window and keeps its simulation_days; it holds no home summary."""
    v5 = _step(5)
    documents = _brought_forward_before(v5, "fleet", _runs_row_documents("legacy_fleet"))

    result = v5.apply("fleet", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def _copy_of_the_fixture_run(name: str, tmp_path: Path) -> Path:
    """A copy of fixture *name*'s run directory in *tmp_path*, which a test may change."""
    return Path(shutil.copytree(stored_run_fixture_dir(name), tmp_path / name))


def _documents_before_v5_read_from(run_dir: Path, name: str) -> StoredRunDocuments:
    """The documents of the run *run_dir* holds, a copy of fixture *name*'s, read as run *name* and brought forward by every step before v5."""
    run_type = fixture_run_type(name)
    return _brought_forward_before(_step(5), run_type, read_run_documents(run_dir, name, run_type))


@pytest.mark.parametrize("name", list(_SUMMARIES_HOLDING_A_WINDOW))
def test_v5_drops_only_the_days_of_a_run_whose_summaries_hold_a_window_reading_none_of_its_time_series(
    name: str, tmp_path: Path
) -> None:
    """Each summary keeps its window, and its simulation_days, its window's 1 day, goes unreported; the fleet's FleetSummary and config are left as they are."""
    run_dir = _copy_of_the_fixture_run(name, tmp_path)
    for series in run_dir.glob("homes/*.parquet"):
        series.unlink()
    documents = _documents_before_v5_read_from(run_dir, name)

    result = _step(5).apply(fixture_run_type(name), documents)

    expected = documents
    for document in _SUMMARIES_HOLDING_A_WINDOW[name]:
        expected = _without(expected, document, "simulation_days")
    assert result.documents == expected
    assert (result.dropped, result.rewritten) == ((), ())


_DAYS_OTHER_THAN_THE_WINDOW_S = [
    pytest.param("pre_469_home", "summary.json", id="a-window-it-derives"),
    pytest.param("pre_787_dispatch_fleet", "homes/home_1_summary.json", id="a-window-the-summary-holds"),
]
"""A fixture and one of its SummaryStatistics documents, whose window, derived from its 1-day series or held, covers 1 day."""


@pytest.mark.parametrize(("name", "document"), _DAYS_OTHER_THAN_THE_WINDOW_S)
def test_v5_reports_a_dropped_simulation_days_that_differs_from_its_window_s_days(name: str, document: str) -> None:
    """A summary saved before simulation_days was its window's days, e.g. over a window crossing the autumn clock change, showed a day count the window does not: its run's page now shows the window's."""
    v5 = _step(5)
    before = _documents_before(v5, name)

    result = v5.apply(fixture_run_type(name), _with_value(before, document, ("simulation_days",), 2))

    assert result.documents == v5.apply(fixture_run_type(name), before).documents
    assert result.dropped == (DroppedValue(name, document, "simulation_days", 2),)
    assert result.rewritten == ()


@pytest.mark.parametrize("name", list(_SUMMARIES_WITHOUT_A_WINDOW_AND_THEIR_SERIES))
def test_v2_keeps_each_summary_s_simulation_days_for_v5_reporting_none(name: str) -> None:
    """v5 compares a summary's simulation_days with its window's days before it drops it, so v2, which drops each key a dataclass lacks, keeps it."""
    documents = _fixture_documents(name)

    result = _V2.apply(fixture_run_type(name), documents)

    summaries = [result.documents.summary, *result.documents.home_summaries]
    assert all(summary.content["simulation_days"] == 1 for summary in summaries)
    assert [each for each in result.dropped if each.field == "simulation_days"] == []


def test_v5_sets_a_summary_whose_window_is_null_to_the_window_of_its_time_series() -> None:
    """A summary whose window key is null holds no window, as one lacking the key does."""
    v5 = _step(5)
    lacking_the_key = _documents_before(v5, "pre_469_home")

    result = v5.apply("home", _with_value(lacking_the_key, "summary.json", ("window",), None))

    assert result.documents == v5.apply("home", lacking_the_key).documents
    assert (result.dropped, result.rewritten) == ((), ())


def _no_series(series: Path) -> None:
    """Delete the time series *series*."""
    series.unlink()


def _a_series_of_no_dates(series: Path) -> None:
    """Write over the time series *series* a frame whose index is not a DatetimeIndex."""
    pd.DataFrame({"generation_kw": [0.0]}).to_parquet(series, engine="pyarrow")


_NOT_A_RUN_S_TIME_SERIES = (
    "is not the time series of a run: SimulationWindow.of_index reads a DatetimeIndex: got RangeIndex of dtype int64"
)


@pytest.mark.parametrize(
    ("name", "series", "damage", "reason"),
    [
        pytest.param("pre_469_home", "data.parquet", _no_series, "is missing", id="home-missing"),
        pytest.param(
            "pre_469_home", "data.parquet", _a_series_of_no_dates, _NOT_A_RUN_S_TIME_SERIES, id="home-not-a-run-s"
        ),
        pytest.param("legacy_fleet", "homes/home_1.parquet", _no_series, "is missing", id="fleet-home-missing"),
        pytest.param(
            "legacy_fleet",
            "homes/home_1.parquet",
            _a_series_of_no_dates,
            _NOT_A_RUN_S_TIME_SERIES,
            id="fleet-home-not-a-run-s",
        ),
    ],
)
def test_v5_refuses_a_summary_without_a_window_whose_time_series_it_cannot_read_naming_the_series(
    name: str, series: str, damage: Callable[[Path], None], reason: str, tmp_path: Path
) -> None:
    """A home run's summary is refused by its data.parquet, and a fleet's i-th home summary by its homes/home_i.parquet."""
    run_dir = _copy_of_the_fixture_run(name, tmp_path)
    damage(run_dir / series)
    documents = _documents_before_v5_read_from(run_dir, name)

    with pytest.raises(StoredRunUnreadable) as refused:
        _step(5).apply(fixture_run_type(name), documents)

    assert (refused.value.run_id, refused.value.document, refused.value.field, refused.value.reason) == (
        name,
        series,
        None,
        reason,
    )


def test_v5_refuses_a_runs_row_summary_without_a_window_whose_run_has_no_directory() -> None:
    v5 = _step(5)
    row_documents = dataclasses.replace(
        _runs_row_documents("pre_469_home"), time_series=StoredTimeSeries("pre_469_home", None)
    )
    documents = _brought_forward_before(v5, "home", row_documents)

    with pytest.raises(StoredRunUnreadable) as refused:
        v5.apply("home", documents)

    assert (refused.value.run_id, refused.value.document, refused.value.field, refused.value.reason) == (
        "pre_469_home",
        "data.parquet",
        None,
        "is missing",
    )


def test_v5_changes_none_of_its_input_documents() -> None:
    v5 = _step(5)
    documents = _documents_before(v5, "legacy_fleet")
    before = copy.deepcopy(documents)

    v5.apply("fleet", documents)

    assert documents == before


def _without_the_seg_revenue_pair(documents: StoredRunDocuments, document: str) -> StoredRunDocuments:
    """*documents*, with the one named *document* lacking both keys of PRE_975_FLEET_SEG_REVENUE_KEYS at its root."""
    for key in PRE_975_FLEET_SEG_REVENUE_KEYS:
        documents = _without(documents, document, key)
    return documents


def test_v6_drops_the_seg_revenue_pair_from_pre_975_s_fleet_summary_reporting_each_value() -> None:
    """The dropped total is the summary's kept total_export_revenue_gbp: every home's export earned the SEG rate, so no figure moves."""
    v6 = _step(6)
    documents = _documents_before(v6, "pre_975_seg_fleet")
    stored = documents.summary.content

    result = v6.apply("fleet", documents)

    assert result.documents == _without_the_seg_revenue_pair(documents, "summary.json")
    assert result.dropped == tuple(
        DroppedValue("pre_975_seg_fleet", "summary.json", key, stored[key]) for key in PRE_975_FLEET_SEG_REVENUE_KEYS
    )
    assert result.rewritten == ()
    assert stored["total_seg_revenue_gbp"] == pytest.approx(
        result.documents.summary.content["total_export_revenue_gbp"], abs=1e-9
    )


def test_v6_drops_the_seg_revenue_pair_from_pre_975_s_runs_row_summary_reporting_each_value() -> None:
    v6 = _step(6)
    documents = _brought_forward_before(v6, "fleet", _runs_row_documents("pre_975_seg_fleet"))
    stored = documents.summary.content

    result = v6.apply("fleet", documents)

    assert result.documents == _without_the_seg_revenue_pair(documents, "runs.summary_json")
    assert result.dropped == tuple(
        DroppedValue("pre_975_seg_fleet", "runs.summary_json", key, stored[key]) for key in PRE_975_FLEET_SEG_REVENUE_KEYS
    )
    assert result.rewritten == ()


def test_v6_drops_legacy_fleet_s_null_seg_revenue_pair_reporting_nothing() -> None:
    v6 = _step(6)
    documents = _documents_before(v6, "legacy_fleet")

    result = v6.apply("fleet", documents)

    assert result.documents == _without_the_seg_revenue_pair(documents, "summary.json")
    assert (result.dropped, result.rewritten) == ((), ())


def test_v6_leaves_a_home_run_s_documents_as_they_are() -> None:
    v6 = _step(6)
    documents = _documents_before(v6, "pre_469_home")

    result = v6.apply("home", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v6_leaves_a_fleet_run_s_config_and_home_summaries_as_they_are_each_keeping_its_seg_revenue() -> None:
    """A home summary's seg_revenue_gbp is a SummaryStatistics key, not a FleetSummary's: its retirement's v9 drops it, not v6."""
    v6 = _step(6)
    documents = _documents_before(v6, "pre_975_seg_fleet")

    result = v6.apply("fleet", documents)

    assert (result.documents.config, result.documents.home_summaries) == (documents.config, documents.home_summaries)
    assert all(summary.content["seg_revenue_gbp"] is not None for summary in result.documents.home_summaries)


@pytest.mark.parametrize("content", ["not an object", [6.07, 3.03], None], ids=["text", "list", "null"])
def test_v6_leaves_a_fleet_summary_that_is_not_an_object_as_it_is(content: Any) -> None:
    v6 = _step(6)
    documents = dataclasses.replace(
        _documents_before(v6, "pre_975_seg_fleet"), summary=StoredDocument("pre_975_seg_fleet", "summary.json", content)
    )

    result = v6.apply("fleet", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v6_changes_none_of_its_input_documents() -> None:
    v6 = _step(6)
    documents = _documents_before(v6, "pre_975_seg_fleet")
    before = copy.deepcopy(documents)

    v6.apply("fleet", documents)

    assert documents == before


@pytest.mark.parametrize("name", ["legacy_fleet", "pre_975_seg_fleet"])
def test_v2_keeps_a_fleet_summary_s_seg_revenue_pair_for_v6_reporting_none(name: str) -> None:
    """v6 drops the pair and reports each of its values that is not null, so v2, which drops each key a dataclass lacks, keeps it."""
    documents = _fixture_documents(name)

    result = _V2.apply("fleet", documents)

    assert {key: result.documents.summary.content[key] for key in PRE_975_FLEET_SEG_REVENUE_KEYS} == {
        key: documents.summary.content[key] for key in PRE_975_FLEET_SEG_REVENUE_KEYS
    }
    assert [each for each in result.dropped if each.field in PRE_975_FLEET_SEG_REVENUE_KEYS] == []


_PRE_867 = "pre_867_round_trip_home"

_BATTERY_ROUND_TRIP = "efficiency"
"""The key of the round-trip efficiency a BatteryConfig stored before format 7 holds, which v7 drops."""


def _stored_batteries(config: Any, run_type: RunType) -> list[dict[str, Any]]:
    """The battery_config object of each home of *config*, a stored config of a run of *run_type*, that has a battery: a home run's own, each of a fleet run's homes in order."""
    homes = config["homes"] if run_type == "fleet" else [config]
    return [home["battery_config"] for home in homes if home["battery_config"] is not None]


def _without_battery_round_trips(documents: StoredRunDocuments, document: str, run_type: RunType) -> StoredRunDocuments:
    """*documents*, of a run of *run_type*, with a copy of the config named *document* lacking each stored battery's efficiency."""
    config = copy.deepcopy(documents.config.content)
    for battery in _stored_batteries(config, run_type):
        del battery[_BATTERY_ROUND_TRIP]
    assert documents.config.name == document
    return dataclasses.replace(documents, config=dataclasses.replace(documents.config, content=config))


@pytest.mark.parametrize(
    ("stored_documents", "document"),
    [
        pytest.param(_fixture_documents, "config.json", id="run-files"),
        pytest.param(_runs_row_documents, "runs.config_json", id="runs-row"),
    ],
)
def test_v7_drops_pre_867_s_battery_round_trip_reporting_it_and_keeps_the_pair_it_derived(
    stored_documents: Callable[[str], StoredRunDocuments], document: str
) -> None:
    v7 = _step(7)
    documents = _brought_forward_before(v7, "home", stored_documents(_PRE_867))

    result = v7.apply("home", documents)

    assert result.documents == _without_battery_round_trips(documents, document, "home")
    assert result.dropped == (DroppedValue(_PRE_867, document, "battery_config.efficiency", 0.81),)
    assert result.rewritten == ()
    battery = result.documents.config.content["battery_config"]
    assert (battery["charge_efficiency"], battery["discharge_efficiency"]) == (0.9, 0.9)


@pytest.mark.parametrize("name", [name for name in STORED_RUN_FIXTURES if name != _PRE_867])
def test_v7_drops_each_legacy_fixture_s_null_battery_round_trip_reporting_nothing(name: str) -> None:
    """A home run's battery_config and each of a fleet run's homes[i].battery_config alike; every other document is left as it is."""
    v7 = _step(7)
    run_type = fixture_run_type(name)
    documents = _documents_before(v7, name)
    assert [battery[_BATTERY_ROUND_TRIP] for battery in _stored_batteries(documents.config.content, run_type)]

    result = v7.apply(run_type, documents)

    assert result.documents == _without_battery_round_trips(documents, "config.json", run_type)
    assert (result.dropped, result.rewritten) == ((), ())


def test_v7_reports_a_fleet_home_s_dropped_round_trip_by_its_path_under_the_fleet_s_homes() -> None:
    v7 = _step(7)
    documents = _with_value(
        _documents_before(v7, "legacy_fleet"), "config.json", ("homes", 0, "battery_config", _BATTERY_ROUND_TRIP), 0.81
    )

    result = v7.apply("fleet", documents)

    assert result.documents == _without_battery_round_trips(documents, "config.json", "fleet")
    assert result.dropped == (DroppedValue("legacy_fleet", "config.json", "homes[0].battery_config.efficiency", 0.81),)


@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_v2_keeps_each_stored_battery_s_round_trip_for_v7_reporting_none(name: str) -> None:
    """v7 drops a battery's efficiency and reports each that is not null, so v2, which drops each key a dataclass lacks, keeps it, at whatever depth the battery is."""
    run_type = fixture_run_type(name)
    documents = _fixture_documents(name)

    result = _V2.apply(run_type, documents)

    def round_trips(stored: StoredRunDocuments) -> list[Any]:
        return [battery[_BATTERY_ROUND_TRIP] for battery in _stored_batteries(stored.config.content, run_type)]

    assert round_trips(result.documents) == round_trips(documents)
    assert [each for each in result.dropped if each.field.endswith(f"battery_config.{_BATTERY_ROUND_TRIP}")] == []


@pytest.mark.parametrize("content", ["not an object", [5.0], None], ids=["text", "list", "null"])
def test_v7_leaves_a_config_that_is_not_an_object_as_it_is(content: Any) -> None:
    v7 = _step(7)
    documents = dataclasses.replace(
        _documents_before(v7, _PRE_867), config=StoredDocument(_PRE_867, "config.json", content)
    )

    result = v7.apply("home", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v7_changes_none_of_its_input_documents() -> None:
    v7 = _step(7)
    documents = _documents_before(v7, _PRE_867)
    before = copy.deepcopy(documents)

    v7.apply("home", documents)

    assert documents == before


def test_a_run_saved_with_a_round_trip_reads_once_brought_forward_as_its_home_whose_battery_holds_the_pair() -> None:
    home = _current_documents(_PRE_867).config.read(HomeConfig)

    assert home.battery_config == BatteryConfig(capacity_kwh=5.0, charge_efficiency=0.9, discharge_efficiency=0.9)


_HOME_DISPATCH = "dispatch_strategy"
"""The key of the dispatch a HomeConfig stored before format 8 asked for by name, which v8 moves into its battery and drops."""

_TOU_OPTIMIZED_ON_THE_TARIFFS_CLOCK = {"strategy_type": "tou_optimized", "peak_hours": None}
"""tou_optimized on its tariff's clock, as format 8 stores a battery's dispatch_strategy: v8 gives it a battery naming no strategy whose home asked for tou_optimized."""

_PRE_839 = "pre_839_flat_grid_charging_fleet"
"""The fixture whose homes[2] asks for tou_optimized beside a battery naming no strategy, once v3 has read it as it ran."""


def _stored_homes(config: Any, run_type: RunType) -> list[Any]:
    """Each home object of *config*, a stored config of a run of *run_type*: a home run's own, each of a fleet run's homes in order."""
    return config["homes"] if run_type == "fleet" else [config]


def _without_home_dispatch(documents: StoredRunDocuments, run_type: RunType) -> StoredRunDocuments:
    """*documents*, of a run of *run_type*, with a copy of the config lacking each stored home's dispatch_strategy."""
    config = copy.deepcopy(documents.config.content)
    for home in _stored_homes(config, run_type):
        del home[_HOME_DISPATCH]
    return dataclasses.replace(documents, config=dataclasses.replace(documents.config, content=config))


@pytest.mark.parametrize(
    ("stored_documents", "document"),
    [
        pytest.param(_fixture_documents, "config.json", id="run-files"),
        pytest.param(_runs_row_documents, "runs.config_json", id="runs-row"),
    ],
)
def test_v8_moves_pre_839_s_tou_optimized_home_into_its_battery_reporting_it_and_drops_every_home_s_key(
    stored_documents: Callable[[str], StoredRunDocuments], document: str
) -> None:
    """homes[2] ran tou_optimized on its flat tariff's clock, which its battery now names; homes[0] and homes[1] ran their batteries' own strategies, which they keep."""
    v8 = _step(8)
    documents = _brought_forward_before(v8, "fleet", stored_documents(_PRE_839))
    assert [home[_HOME_DISPATCH] for home in documents.config.content["homes"]] == ["greedy", "greedy", "tou_optimized"]

    result = v8.apply("fleet", documents)

    battery_strategy = ("homes", 2, "battery_config", "dispatch_strategy")
    assert result.documents == _with_value(
        _without_home_dispatch(documents, "fleet"), document, battery_strategy, _TOU_OPTIMIZED_ON_THE_TARIFFS_CLOCK
    )
    assert result.dropped == ()
    assert result.rewritten == (
        RewrittenValue(_PRE_839, document, "homes[2].battery_config.dispatch_strategy", None, _TOU_OPTIMIZED_ON_THE_TARIFFS_CLOCK),
    )
    assert [home.battery_config and home.battery_config.dispatch_strategy for home in result.documents.config.read(FleetRunConfig).homes] == [
        TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
        PeakShavingStrategyConfig(import_limit_kw=3.0),
        TOUOptimizedStrategyConfig(),
    ]


def test_v8_gives_a_home_run_s_battery_naming_no_strategy_tou_optimized_on_its_tariffs_clock_when_its_home_asked_for_it() -> None:
    v8 = _step(8)
    documents = _home_run_before(v8, ((_HOME_DISPATCH,), "tou_optimized"), (("battery_config", "dispatch_strategy"), None))

    result = v8.apply("home", documents)

    with_its_battery_s = _with_value(
        documents, "config.json", ("battery_config", "dispatch_strategy"), _TOU_OPTIMIZED_ON_THE_TARIFFS_CLOCK
    )
    assert result.documents == _without(with_its_battery_s, "config.json", _HOME_DISPATCH)
    assert result.dropped == ()
    assert result.rewritten == (
        RewrittenValue(
            "pre_786_dispatch_home", "config.json", "battery_config.dispatch_strategy", None, _TOU_OPTIMIZED_ON_THE_TARIFFS_CLOCK
        ),
    )
    battery = result.documents.config.read(HomeConfig).battery_config
    assert battery is not None
    assert (battery.dispatch_strategy, battery.grid_charging) == (
        TOUOptimizedStrategyConfig(),
        GridChargeConfig(target_soc_fraction=0.8),
    )


def test_v8_drops_a_home_run_s_dispatch_strategy_at_its_root_reporting_nothing() -> None:
    """pre_786_dispatch_home's battery names its own strategy, so the home's key is all v8 changes."""
    v8 = _step(8)
    documents = _documents_before(v8, "pre_786_dispatch_home")
    assert documents.config.content[_HOME_DISPATCH] == "greedy"

    result = v8.apply("home", documents)

    assert result.documents == _without_home_dispatch(documents, "home")
    assert (result.dropped, result.rewritten) == ((), ())


_SELF_CONSUMPTION = {"strategy_type": "self_consumption"}
"""self_consumption, as format 8 stores a battery's dispatch_strategy: v8 gives it each battery naming no strategy whose home did not ask for tou_optimized."""


def _with_each_battery_naming_no_strategy_self_consumption(
    documents: StoredRunDocuments, run_type: RunType
) -> StoredRunDocuments:
    """*documents*, of a run of *run_type*, with a copy of the config whose every battery naming no strategy names self_consumption."""
    config = copy.deepcopy(documents.config.content)
    for home in _stored_homes(config, run_type):
        battery = home["battery_config"]
        if battery is not None and battery["dispatch_strategy"] is None:
            battery["dispatch_strategy"] = dict(_SELF_CONSUMPTION)
    return dataclasses.replace(documents, config=dataclasses.replace(documents.config, content=config))


@pytest.mark.parametrize(
    "name", ["legacy_fleet", "pre_469_home", "pre_867_round_trip_home", "pre_975_seg_fleet", "pre_787_dispatch_fleet"]
)
def test_v8_gives_each_battery_naming_no_strategy_whose_home_asked_for_greedy_self_consumption_reporting_nothing(
    name: str,
) -> None:
    """A greedy home's battery that named no strategy ran self-consumption, which it now names; the home loses its key."""
    run_type = fixture_run_type(name)
    v8 = _step(8)
    documents = _documents_before(v8, name)
    homes = _stored_homes(documents.config.content, run_type)
    assert {home[_HOME_DISPATCH] for home in homes} == {"greedy"}, "premise: every home asked for greedy"
    assert None in [home["battery_config"]["dispatch_strategy"] for home in homes if home["battery_config"]], (
        "premise: a battery names no strategy"
    )

    result = v8.apply(run_type, documents)

    assert result.documents == _with_each_battery_naming_no_strategy_self_consumption(
        _without_home_dispatch(documents, run_type), run_type
    )
    assert (result.dropped, result.rewritten) == ((), ())


def test_v8_gives_a_battery_naming_no_strategy_self_consumption_whose_home_holds_no_dispatch_strategy_reporting_nothing() -> None:
    """Filling a battery that names no strategy does not wait on its home's key: a home holding none asked for no tou_optimized, so its battery names self_consumption."""
    v8 = _step(8)
    documents = _without(
        _home_run_before(v8, (("battery_config", "dispatch_strategy"), None)), "config.json", _HOME_DISPATCH
    )

    result = v8.apply("home", documents)

    assert result.documents == _with_value(
        documents, "config.json", ("battery_config", "dispatch_strategy"), _SELF_CONSUMPTION
    )
    assert (result.dropped, result.rewritten) == ((), ())


_TOU_OPTIMIZED_HOMES_WHOSE_BATTERY_TAKES_NONE = [
    pytest.param([((_HOME_DISPATCH,), "tou_optimized")], id="a-battery-naming-tou_optimized-in-its-own-peak-hours"),
    pytest.param(
        [((_HOME_DISPATCH,), "tou_optimized"), (("battery_config", "dispatch_strategy"), _PEAK_SHAVING)],
        id="a-battery-naming-peak_shaving",
    ),
    pytest.param(
        [((_HOME_DISPATCH,), "tou_optimized"), (("battery_config", "dispatch_strategy"), {"strategy_type": "self_consumption"})],
        id="a-battery-naming-self_consumption",
    ),
    pytest.param([((_HOME_DISPATCH,), "tou_optimized"), (("battery_config",), None)], id="no-battery"),
    pytest.param([((_HOME_DISPATCH,), "tou_optimized"), (("battery_config",), "not a battery")], id="a-battery-not-an-object"),
]
"""Edits to pre_786_dispatch_home's config before v8, each a home asking for tou_optimized whose battery names its own strategy or that has no battery to name one."""


@pytest.mark.parametrize("edits", _TOU_OPTIMIZED_HOMES_WHOSE_BATTERY_TAKES_NONE)
def test_v8_only_drops_the_key_of_a_tou_optimized_home_whose_battery_names_its_own_strategy_or_that_has_none(
    edits: list[tuple[Keys, Any]],
) -> None:
    v8 = _step(8)
    documents = _home_run_before(v8, *edits)

    result = v8.apply("home", documents)

    assert result.documents == _without(documents, "config.json", _HOME_DISPATCH)
    assert (result.dropped, result.rewritten) == ((), ())


@pytest.mark.parametrize(
    ("run_type", "name", "content"),
    [
        pytest.param("home", "pre_786_dispatch_home", "not a config", id="home-text"),
        pytest.param("home", "pre_786_dispatch_home", ["not", "a", "config"], id="home-array"),
        pytest.param("home", "pre_786_dispatch_home", None, id="home-null"),
        pytest.param("fleet", _PRE_839, ["not", "a", "config"], id="fleet-array"),
        pytest.param("fleet", _PRE_839, {"homes": "not a list", "n_homes": 3}, id="fleet-homes-not-a-list"),
        pytest.param("fleet", _PRE_839, {"homes": ["not a home", None, 3], "n_homes": 3}, id="fleet-homes-not-objects"),
    ],
)
def test_v8_leaves_a_config_or_a_fleet_s_home_that_is_not_an_object_as_it_is(
    run_type: RunType, name: str, content: Any
) -> None:
    v8 = _step(8)
    documents = dataclasses.replace(_documents_before(v8, name), config=StoredDocument(name, "config.json", content))

    result = v8.apply(run_type, documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v8_changes_none_of_its_input_documents() -> None:
    v8 = _step(8)
    documents = _documents_before(v8, _PRE_839)
    before = copy.deepcopy(documents)

    v8.apply("fleet", documents)

    assert documents == before


@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_v2_keeps_each_stored_home_s_dispatch_strategy_for_v3_and_v8_reporting_none(name: str) -> None:
    """v3 reads a home's dispatch_strategy as it ran, and v8 moves it into its battery, so v2, which drops each key a dataclass lacks, keeps it, at a home run's root and at each of a fleet run's homes."""
    run_type = fixture_run_type(name)
    documents = _fixture_documents(name)

    result = _V2.apply(run_type, documents)

    def home_dispatch(stored: StoredRunDocuments) -> list[Any]:
        return [home[_HOME_DISPATCH] for home in _stored_homes(stored.config.content, run_type)]

    assert home_dispatch(result.documents) == home_dispatch(documents)
    assert [each for each in result.dropped if each.field.split(".")[-1] == _HOME_DISPATCH] == []


_PRE_975 = "pre_975_seg_fleet"

_SUMMARY_SEG_REVENUE = "seg_revenue_gbp"
"""The key of the SEG revenue a SummaryStatistics stored before format 9 holds, a second copy of its total_export_revenue_gbp, which v9 drops."""


def _summary_documents(documents: StoredRunDocuments, run_type: RunType) -> tuple[StoredDocument, ...]:
    """The SummaryStatistics documents of *documents*, of a run of *run_type*: a home run's summary, or each of a fleet run's home summaries."""
    return documents.home_summaries if run_type == "fleet" else (documents.summary,)


def _without_summary_seg_revenues(documents: StoredRunDocuments, run_type: RunType) -> StoredRunDocuments:
    """*documents*, of a run of *run_type*, with a copy of each SummaryStatistics document lacking its seg_revenue_gbp."""
    for summary in _summary_documents(documents, run_type):
        documents = _without(documents, summary.name, _SUMMARY_SEG_REVENUE)
    return documents


def test_v9_drops_pre_975_s_home_summaries_seg_revenue_reporting_each_value_no_figure_moving() -> None:
    """Each dropped value is its home summary's kept total_export_revenue_gbp: every home's export earned the SEG rate, so no figure moves."""
    v9 = _step(9)
    documents = _documents_before(v9, _PRE_975)
    stored = {summary.name: summary.content[_SUMMARY_SEG_REVENUE] for summary in documents.home_summaries}

    result = v9.apply("fleet", documents)

    assert result.documents == _without_summary_seg_revenues(documents, "fleet")
    assert result.dropped == tuple(
        DroppedValue(_PRE_975, document, _SUMMARY_SEG_REVENUE, stored[document])
        for document in ("homes/home_0_summary.json", "homes/home_1_summary.json")
    )
    assert result.rewritten == ()
    assert [each.value for each in result.dropped] == pytest.approx(
        [summary.content["total_export_revenue_gbp"] for summary in result.documents.home_summaries], abs=1e-9
    )


@pytest.mark.parametrize("name", [name for name in STORED_RUN_FIXTURES if name != _PRE_975])
def test_v9_drops_each_legacy_fixture_s_null_seg_revenue_reporting_nothing(name: str) -> None:
    """A home run's summary and each of a fleet run's home summaries alike; a fleet's FleetSummary and every config are left as they are."""
    v9 = _step(9)
    run_type = fixture_run_type(name)
    documents = _documents_before(v9, name)
    summaries = _summary_documents(documents, run_type)
    assert summaries and all(summary.content[_SUMMARY_SEG_REVENUE] is None for summary in summaries)

    result = v9.apply(run_type, documents)

    assert result.documents == _without_summary_seg_revenues(documents, run_type)
    assert (result.dropped, result.rewritten) == ((), ())


@pytest.mark.parametrize(
    ("stored_documents", "document"),
    [
        pytest.param(_fixture_documents, "summary.json", id="run-files"),
        pytest.param(_runs_row_documents, "runs.summary_json", id="runs-row"),
    ],
)
def test_v9_drops_a_home_run_s_seg_revenue_reporting_it(
    stored_documents: Callable[[str], StoredRunDocuments], document: str
) -> None:
    v9 = _step(9)
    brought_forward = _brought_forward_before(v9, "home", stored_documents("pre_469_home"))
    documents = _with_value(brought_forward, document, (_SUMMARY_SEG_REVENUE,), 1.23)

    result = v9.apply("home", documents)

    assert result.documents == _without(documents, document, _SUMMARY_SEG_REVENUE)
    assert result.dropped == (DroppedValue("pre_469_home", document, _SUMMARY_SEG_REVENUE, 1.23),)
    assert result.rewritten == ()


def test_v9_leaves_a_fleet_run_s_runs_row_as_it_is() -> None:
    """A fleet's runs row holds its config and its FleetSummary, which has no seg_revenue_gbp; it holds no home summary."""
    v9 = _step(9)
    documents = _brought_forward_before(v9, "fleet", _runs_row_documents(_PRE_975))

    result = v9.apply("fleet", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


@pytest.mark.parametrize("content", ["not an object", [1.23], None], ids=["text", "list", "null"])
def test_v9_leaves_a_summary_that_is_not_an_object_as_it_is(content: Any) -> None:
    v9 = _step(9)
    documents = dataclasses.replace(
        _documents_before(v9, "pre_469_home"), summary=StoredDocument("pre_469_home", "summary.json", content)
    )

    result = v9.apply("home", documents)

    assert result.documents == documents
    assert (result.dropped, result.rewritten) == ((), ())


def test_v9_changes_none_of_its_input_documents() -> None:
    v9 = _step(9)
    documents = _documents_before(v9, _PRE_975)
    before = copy.deepcopy(documents)

    v9.apply("fleet", documents)

    assert documents == before


@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_v2_keeps_each_stored_summary_s_seg_revenue_for_v9_reporting_none(name: str) -> None:
    """v9 drops a home summary's seg_revenue_gbp and reports each that is not null, so v2, which drops each key a dataclass lacks, keeps it."""
    run_type = fixture_run_type(name)
    documents = _fixture_documents(name)

    result = _V2.apply(run_type, documents)

    def seg_revenues(stored: StoredRunDocuments) -> list[Any]:
        return [summary.content[_SUMMARY_SEG_REVENUE] for summary in _summary_documents(stored, run_type)]

    assert seg_revenues(result.documents) == seg_revenues(documents)
    assert [each for each in result.dropped if each.field == _SUMMARY_SEG_REVENUE] == []


def test_each_home_summary_of_a_run_stored_with_a_seg_revenue_reads_once_brought_forward() -> None:
    """Each reads as the home's summary whose export revenue is the SEG revenue it held."""
    stored = [summary.content[_SUMMARY_SEG_REVENUE] for summary in _fixture_documents(_PRE_975).home_summaries]

    summaries = [summary.read(SummaryStatistics) for summary in _current_documents(_PRE_975).home_summaries]

    assert [summary.total_export_revenue_gbp for summary in summaries] == pytest.approx(stored, abs=1e-9)
