# SPDX-License-Identifier: AGPL-3.0-or-later
"""FinanceConfig.grid_services_model holds the pricing value, one of the GridServicesModel types, and refuses any other value at construction.

The rule is the ε column of docs/prds/grid-services-pricing-model.md §5.2.
"""

import dataclasses
import pickle

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import (
    FlatGridServices,
    GridServicesBand,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
)

_PRICINGS: list[GridServicesModel] = [
    NoGridServices(),
    FlatGridServices(12.0),
    GridServicesEventsConfig(band=GridServicesBand.HIGH, aggregator_share=0.1),
]
_PRICING_IDS = ["none", "flat", "events"]


def _finance(**fields: object) -> FinanceConfig:
    return FinanceConfig(standing_charge_pence_per_day=60, **fields)  # type: ignore[arg-type]


def test_a_finance_without_a_pricing_earns_no_grid_services_income() -> None:
    assert FinanceConfig(standing_charge_pence_per_day=60).grid_services_model == NoGridServices()


@pytest.mark.parametrize("pricing", _PRICINGS, ids=_PRICING_IDS)
def test_a_finance_holds_the_pricing_it_is_given(pricing: GridServicesModel) -> None:
    assert FinanceConfig(standing_charge_pence_per_day=60, grid_services_model=pricing).grid_services_model is pricing


@pytest.mark.parametrize("pricing", _PRICINGS, ids=_PRICING_IDS)
@pytest.mark.parametrize("replacement", _PRICINGS, ids=_PRICING_IDS)
def test_a_replaced_finance_holds_the_pricing_it_is_replaced_with(
    pricing: GridServicesModel, replacement: GridServicesModel
) -> None:
    finance = FinanceConfig(standing_charge_pence_per_day=60, grid_services_model=pricing)

    assert dataclasses.replace(finance, grid_services_model=replacement).grid_services_model is replacement


@pytest.mark.parametrize("pricing", _PRICINGS, ids=_PRICING_IDS)
def test_a_finance_survives_a_pickle_round_trip_equal(pricing: GridServicesModel) -> None:
    finance = FinanceConfig(standing_charge_pence_per_day=60, grid_services_model=pricing)

    assert pickle.loads(pickle.dumps(finance)) == finance


_NOT_PRICINGS = [
    pytest.param("flat", id="flat-selector"),
    pytest.param("capacity_at_events", id="events-selector"),
    pytest.param(12.0, id="rate"),
    pytest.param(None, id="none"),
    pytest.param({"type": "flat"}, id="block"),
]


def _assert_refuses_naming_the_pricing_types(refusal: pytest.ExceptionInfo[ValueError], value: object) -> None:
    assert refusal.type is ConfigurationError
    message = str(refusal.value)
    for token in ("grid_services_model", "NoGridServices", "FlatGridServices", "GridServicesEventsConfig", repr(value)):
        assert token in message, message


@pytest.mark.parametrize("value", _NOT_PRICINGS)
def test_a_value_that_is_no_pricing_is_refused_naming_the_pricing_types(value: object) -> None:
    with pytest.raises(ValueError) as refusal:
        _finance(grid_services_model=value)

    _assert_refuses_naming_the_pricing_types(refusal, value)


def test_a_finance_replaced_with_a_value_that_is_no_pricing_is_refused_naming_the_pricing_types() -> None:
    finance = FinanceConfig(standing_charge_pence_per_day=60)

    with pytest.raises(ValueError) as refusal:
        dataclasses.replace(finance, grid_services_model="flat")  # type: ignore[arg-type]

    _assert_refuses_naming_the_pricing_types(refusal, "flat")
