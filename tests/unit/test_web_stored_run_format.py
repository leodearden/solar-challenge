# SPDX-License-Identifier: AGPL-3.0-or-later
"""The stored-run format: RunStorage.load_run refuses a stored run it cannot rebuild with StoredRunUnreadable.

This module holds D27 invariant 6's checkable form (docs/prds/run-store-one-owner.md §14),
asserted through the public loader: a current run whose summary.json lacks a required field,
or holds a key no field has, is refused naming the run id, the document and the field, and a
current run loads. Each test saves a run as a finished job saves it, edits one of its
documents, and loads it.

The refusal's field is the dotted path in the document, with [i] for an item; None means the
document as a whole.
"""

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import GridChargeConfig, TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import calculate_home_summaries
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, calculate_summary
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.schema import open_database
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.stored_runs import StoredFleetRun, StoredHomeRun, StoredRunUnreadable
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._run_storage_layout import stored_run_dir
from tests._web_runs import store_fleet_run, store_home_run

_HOME_RUN_ID = "home-1"
_FLEET_RUN_ID = "fleet-1"

Edit = Callable[[Any], None]


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """An empty RunStorage under tmp_path, its database a new store open_database created."""
    return RunStorage(open_database(tmp_path / "runs.db"), tmp_path)


def _home_of_every_shape() -> HomeConfig:
    """A home whose config.json holds every shape the format reads.

    Those are nested dataclasses, a tagged union (the battery's dispatch strategy), a tuple of
    fixed tuples (its peak hours), a tuple of dataclasses (the tariff's periods), a Literal
    (the heat pump's type), and Optional fields set and unset.
    """
    battery = BatteryConfig(
        capacity_kwh=5.0,
        dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
        grid_charging=GridChargeConfig(target_soc_fraction=0.8),
    )
    return dataclasses.replace(
        make_home_config(battery_config=battery),
        heat_pump_config=HeatPumpConfig(heat_pump_type="ASHP"),
        tariff_config=TariffConfig.economy_7(),
        seg_tariff=SEGTariff(name="Outgoing", rate_pence_per_kwh=15.0),
        name="Every Shape",
    )


def _store_home_run_of_every_shape(storage: RunStorage) -> HomeConfig:
    """Save a day's run of _home_of_every_shape() under _HOME_RUN_ID, and return its config."""
    config = _home_of_every_shape()
    store_home_run(storage, _HOME_RUN_ID, config, make_sim_results(days=1))
    return config


def _store_fleet_run_of_two_homes(storage: RunStorage) -> None:
    """Save a day's fleet run of two homes, the second with a 5 kWh battery, under _FLEET_RUN_ID."""
    fleet = make_fleet_results_of(
        [make_sim_results(days=1), make_sim_results(self_kwh=10.0, days=1)],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)


def _edit_document(path: Path, edit: Edit) -> None:
    """Rewrite the JSON document at *path* with *edit* applied to its content."""
    document = json.loads(path.read_text())
    edit(document)
    path.write_text(json.dumps(document, indent=2))


def _set(*keys: str | int, value: Any) -> Edit:
    """An edit setting the value a document holds at *keys*, a key or an index for each level, to *value*."""

    def edit(document: Any) -> None:
        *parents, last = keys
        for key in parents:
            document = document[key]
        document[last] = value

    return edit


def _delete(key: str) -> Edit:
    """An edit deleting *key* from a document's root object."""

    def edit(document: Any) -> None:
        del document[key]

    return edit


def _refusal(storage: RunStorage, run_id: str, document: str, field: str | None) -> StoredRunUnreadable:
    """Load run *run_id*, check that it is refused naming *document* and *field*, and return the refusal.

    The refusal's message names the run id, the document and the field, when there is one.
    """
    with pytest.raises(StoredRunUnreadable) as refused:
        storage.load_run(run_id)
    refusal = refused.value
    assert (refusal.run_id, refusal.document, refusal.field) == (run_id, document, field)
    message = str(refusal)
    assert run_id in message
    assert document in message
    if field is not None:
        assert field in message
    return refusal


def test_a_stored_run_unreadable_is_not_a_value_error() -> None:
    """A request's bad value is a ValueError the boundary answers 400; an unreadable stored run is answered 409 or flashed."""
    assert not issubclass(StoredRunUnreadable, ValueError)


def test_a_current_home_run_loads_unchanged(storage: RunStorage) -> None:
    config = _home_of_every_shape()
    results = make_sim_results(days=1)
    store_home_run(storage, _HOME_RUN_ID, config, results)

    loaded = storage.load_run(_HOME_RUN_ID)

    assert isinstance(loaded, StoredHomeRun)
    assert loaded.config == config
    assert loaded.summary == calculate_summary(results)


def test_a_current_fleet_run_loads_unchanged(storage: RunStorage) -> None:
    fleet = make_fleet_results_of(
        [make_sim_results(days=1), make_sim_results(self_kwh=10.0, days=1)],
        homes=[make_home_config(), _home_of_every_shape()],
    )
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)

    loaded = storage.load_run(_FLEET_RUN_ID)

    assert isinstance(loaded, StoredFleetRun)
    assert loaded.fleet_results.home_configs == fleet.home_configs
    assert list(loaded.home_summaries) == calculate_home_summaries(fleet)


def test_a_run_whose_optional_fields_are_stored_as_null_loads(storage: RunStorage) -> None:
    config = make_home_config()
    store_home_run(storage, _HOME_RUN_ID, config, make_sim_results(days=1))
    stored = json.loads((stored_run_dir(storage, _HOME_RUN_ID) / "config.json").read_text())

    loaded = storage.load_run(_HOME_RUN_ID)

    assert [stored["battery_config"], stored["seg_tariff"], stored["heat_pump_config"]] == [None, None, None]
    assert isinstance(loaded, StoredHomeRun)
    assert loaded.config == config


@pytest.mark.parametrize(
    ("edit", "field"),
    [
        (_delete("total_generation_kwh"), "total_generation_kwh"),
        (_set("retired_figure", value=12.5), "retired_figure"),
    ],
    ids=["lacks-a-required-field", "holds-an-unknown-key"],
)
def test_a_summary_lacking_a_required_field_or_holding_an_unknown_key_is_refused_naming_it(
    storage: RunStorage, edit: Edit, field: str
) -> None:
    """Invariant 6's second and fourth clauses."""
    _store_home_run_of_every_shape(storage)
    _edit_document(stored_run_dir(storage, _HOME_RUN_ID) / "summary.json", edit)

    _refusal(storage, _HOME_RUN_ID, "summary.json", field)


@pytest.mark.parametrize(
    ("edit", "field"),
    [
        (_set("battery_config", value="big"), "battery_config"),
        (_set("pv_config", "capacity_kw", value="4.0"), "pv_config.capacity_kw"),
        (_set("pv_config", "capacity_kw", value=True), "pv_config.capacity_kw"),
        (_set("tariff_config", "periods", value="x"), "tariff_config.periods"),
        (_set("location", value=None), "location"),
        (_set("heat_pump_config", "heat_pump_type", value="XSHP"), "heat_pump_config.heat_pump_type"),
        (
            _set("battery_config", "dispatch_strategy", "peak_hours", 0, value=[16, 19, 20]),
            "battery_config.dispatch_strategy.peak_hours[0]",
        ),
        (
            _set("battery_config", "dispatch_strategy", "strategy_type", value="turbo"),
            "battery_config.dispatch_strategy.strategy_type",
        ),
    ],
    ids=[
        "a-string-for-a-dataclass",
        "a-string-for-a-number",
        "a-bool-for-a-number",
        "a-string-for-a-sequence",
        "null-for-a-field-that-is-not-optional",
        "a-value-its-literal-does-not-name",
        "a-window-of-three-hours-for-a-pair",
        "a-strategy-type-no-variant-has",
    ],
)
def test_a_config_value_of_a_type_its_field_cannot_be_is_refused_naming_its_path(
    storage: RunStorage, edit: Edit, field: str
) -> None:
    _store_home_run_of_every_shape(storage)
    _edit_document(stored_run_dir(storage, _HOME_RUN_ID) / "config.json", edit)

    _refusal(storage, _HOME_RUN_ID, "config.json", field)


def test_a_tariff_whose_periods_do_not_tile_the_day_is_refused_naming_the_tariff_caused_by_its_refusal(
    storage: RunStorage,
) -> None:
    """TariffConfig's own refusal is the cause: the stored values reached its __post_init__."""
    _store_home_run_of_every_shape(storage)
    _edit_document(
        stored_run_dir(storage, _HOME_RUN_ID) / "config.json",
        _set("tariff_config", "periods", 0, "end_time", value="06:30"),
    )

    refusal = _refusal(storage, _HOME_RUN_ID, "config.json", "tariff_config")

    assert isinstance(refusal.__cause__, ConfigurationError)


def test_a_summary_its_dataclass_refuses_is_refused_as_a_whole(storage: RunStorage) -> None:
    """SummaryStatistics refuses a grid charge above the battery's charge; the document's root is the dataclass refusing."""
    _store_home_run_of_every_shape(storage)
    summary_path = stored_run_dir(storage, _HOME_RUN_ID) / "summary.json"
    battery_charge_kwh = json.loads(summary_path.read_text())["total_battery_charge_kwh"]
    _edit_document(summary_path, _set("total_grid_charge_kwh", value=battery_charge_kwh + 1.0))

    refusal = _refusal(storage, _HOME_RUN_ID, "summary.json", None)

    assert isinstance(refusal.__cause__, ValueError)


def test_a_summary_that_is_not_json_is_refused_as_a_whole(storage: RunStorage) -> None:
    _store_home_run_of_every_shape(storage)
    (stored_run_dir(storage, _HOME_RUN_ID) / "summary.json").write_text("{not json")

    _refusal(storage, _HOME_RUN_ID, "summary.json", None)


def test_a_time_series_that_is_not_parquet_is_refused_naming_its_file(storage: RunStorage) -> None:
    _store_home_run_of_every_shape(storage)
    (stored_run_dir(storage, _HOME_RUN_ID) / "data.parquet").write_bytes(b"THIS IS NOT A VALID PARQUET FILE")

    _refusal(storage, _HOME_RUN_ID, "data.parquet", None)


def test_a_fleet_homes_config_value_of_a_wrong_type_is_refused_naming_the_home(storage: RunStorage) -> None:
    _store_fleet_run_of_two_homes(storage)
    _edit_document(
        stored_run_dir(storage, _FLEET_RUN_ID) / "config.json", _set("homes", 1, "pv_config", "capacity_kw", value="4.0")
    )

    _refusal(storage, _FLEET_RUN_ID, "config.json", "homes[1].pv_config.capacity_kw")


def test_a_fleet_home_summary_lacking_a_required_field_is_refused_naming_its_document(storage: RunStorage) -> None:
    _store_fleet_run_of_two_homes(storage)
    _edit_document(stored_run_dir(storage, _FLEET_RUN_ID) / "homes" / "home_0_summary.json", _delete("total_demand_kwh"))

    _refusal(storage, _FLEET_RUN_ID, "homes/home_0_summary.json", "total_demand_kwh")
