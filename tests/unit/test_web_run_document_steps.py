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

Last it pins v5, the step that sets each stored SummaryStatistics document lacking a window to the
window of its run's own time series, read through the documents' StoredTimeSeries, and drops each
one's simulation_days: which summaries it sets, from which series, in a run's files and its runs
row alike; that it drops simulation_days from every summary, reporting only one that differs from
its window's days, and keeps a FleetSummary's; that v2 keeps a summary's simulation_days for it;
that it reads no series for a summary holding a window and leaves every other document as it is;
and that it refuses a summary whose series is missing or is not a run's.
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
    result = _V2.apply("home", _fixture_documents("pre_786_dispatch_home"))

    battery = result.documents.config.read(HomeConfig).battery_config

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
    name = "pre_787_dispatch_fleet"

    result = _V3.apply("fleet", _documents_before(_V3, name))

    assert result.dropped == ()
    assert result.rewritten == (
        RewrittenValue(name, "config.json", "homes[0].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
        RewrittenValue(name, "config.json", "homes[1].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
        RewrittenValue(name, "config.json", "homes[2].dispatch_strategy", "tou_optimized", "greedy"),
        RewrittenValue(name, "config.json", "homes[2].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None),
    )
    assert result.documents.config.read(FleetRunConfig).homes == (
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
    name = "pre_839_flat_grid_charging_fleet"
    v4 = _step(4)

    result = v4.apply("fleet", _documents_before(v4, name))

    assert result.dropped == ()
    assert result.rewritten == tuple(
        RewrittenValue(name, "config.json", f"homes[{index}].battery_config.grid_charging", _GRID_CHARGING_TO_80_PERCENT, None)
        for index in range(3)
    )
    assert result.documents.config.read(FleetRunConfig).homes == (
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
            BatteryConfig(capacity_kwh=5.0),
            tariff_config=TariffConfig.flat_rate(0.25),
            dispatch_strategy="tou_optimized",
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
    battery = result.documents.config.read(HomeConfig).battery_config
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


def _no_series(run_dir: Path) -> None:
    """Delete *run_dir*'s data.parquet."""
    (run_dir / "data.parquet").unlink()


def _a_series_of_no_dates(run_dir: Path) -> None:
    """Write over *run_dir*'s data.parquet a frame whose index is not a DatetimeIndex."""
    pd.DataFrame({"generation_kw": [0.0]}).to_parquet(run_dir / "data.parquet", engine="pyarrow")


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        pytest.param(_no_series, "is missing", id="missing"),
        pytest.param(
            _a_series_of_no_dates,
            "is not the time series of a run: SimulationWindow.of_index reads a DatetimeIndex: got RangeIndex of dtype int64",
            id="not-a-run-s-time-series",
        ),
    ],
)
def test_v5_refuses_a_summary_without_a_window_whose_time_series_it_cannot_read_naming_the_series(
    damage: Callable[[Path], None], reason: str, tmp_path: Path
) -> None:
    run_dir = _copy_of_the_fixture_run("pre_469_home", tmp_path)
    damage(run_dir)
    documents = _documents_before_v5_read_from(run_dir, "pre_469_home")

    with pytest.raises(StoredRunUnreadable) as refused:
        _step(5).apply("home", documents)

    assert (refused.value.run_id, refused.value.document, refused.value.field, refused.value.reason) == (
        "pre_469_home",
        "data.parquet",
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
