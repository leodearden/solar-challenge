# SPDX-License-Identifier: AGPL-3.0-or-later
"""The run-document steps, each of which brings a stored run's documents one format version forward (contract C5).

The generic tests run every step in RUN_DOCUMENT_STEPS over every committed legacy fixture of
tests/_stored_run_fixtures: the steps' versions ascend to RUN_FORMAT_VERSION, each step is
idempotent on every fixture, and each step changes at least one fixture's documents, so a new
step (contract C10) ships with a fixture that exercises it.

The rest pins v2, the step that drops each key a document's dataclass does not have: what it
drops, which dropped values it reports, what it leaves for the strict reader to refuse, and that
it changes none of its input. It walks a document as the strict reader reads it: a key no field
has, added to each object of a config of every field shape, is dropped from a dataclass's object
and kept in a dict field's, and the config then reads back as the home saved. A run stored before
the battery's dispatch strategies were variants of one union migrates, then loads.
"""

import copy
import dataclasses
import json
from collections.abc import Iterator
from typing import Any

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.home import HomeConfig, SummaryStatistics
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.stored_runs import (
    RUN_DOCUMENT_STEPS,
    RUN_FORMAT_VERSION,
    DroppedValue,
    RunDocumentStep,
    StoredDocument,
    StoredRunDocuments,
    StoredRunUnreadable,
    documents_in_current_format,
    read_run_documents,
)
from tests._every_field_shape import home_of_every_field_shape
from tests._stored_run_fixtures import FIXTURES_DIR, STORED_RUN_FIXTURES, fixture_run_type, stored_run_fixture_dir

_V2 = next(step for step in RUN_DOCUMENT_STEPS if step.version == 2)

_PRE_DISPATCH_UNION_HOME_CONFIGS = FIXTURES_DIR / "pre_dispatch_union_home_configs.json"
"""Task 786's fixture: a home run's stored config per dispatch strategy, as runs stored it before
the strategies were variants of one union, with all three strategy keys, the ones the strategy
does not read null. Each is the config of _dispatching_home(strategy) named after its strategy."""

_STRATEGIES = (
    SelfConsumptionStrategyConfig(),
    TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
    PeakShavingStrategyConfig(import_limit_kw=3.0),
)
"""One example of each dispatch strategy, those of the stored configs above."""

Keys = tuple[str | int, ...]


def _dispatching_home(strategy: Any, name: str) -> HomeConfig:
    """A home on Economy 7 whose battery dispatches by *strategy* and grid-charges to 0.8, as the stored configs above."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            dispatch_strategy=strategy,
            grid_charging=GridChargeConfig(target_soc_fraction=0.8),
        ),
        tariff_config=TariffConfig.economy_7(),
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
    run_type = fixture_run_type(name)
    documents = _fixture_documents(name)
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

    return StoredRunDocuments(
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

    return StoredRunDocuments(
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


@pytest.mark.parametrize("strategy", _STRATEGIES, ids=lambda strategy: strategy.strategy_type)
def test_v2_migrates_a_config_stored_before_the_dispatch_union_then_it_loads_as_its_variant(strategy: Any) -> None:
    """786's pre-union configs: once migrated, each reads as the home it was saved from."""
    tag = strategy.strategy_type
    stored = json.loads(_PRE_DISPATCH_UNION_HOME_CONFIGS.read_text())[tag]
    documents = dataclasses.replace(
        _fixture_documents("pre_786_dispatch_home"), config=StoredDocument("pre-union-001", "config.json", stored)
    )

    result = _V2.apply("home", documents)

    assert result.dropped == ()
    assert result.documents.config.read(HomeConfig) == _dispatching_home(
        strategy, name=f"Stored before the dispatch union: {tag}"
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
"""home_of_every_field_shape()'s config document: its field tree in JSON, as a save writes it (test_web_storage_roundtrip.py's TestPersistedJson)."""

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
