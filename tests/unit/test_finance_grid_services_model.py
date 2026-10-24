# SPDX-License-Identifier: AGPL-3.0-or-later
"""finance.grid_services_model_of maps FinanceConfig's three grid-services fields to one pricing value.

The mapping is the α column of docs/prds/grid-services-pricing-model.md §5.2.
"""

import dataclasses
import re

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig, grid_services_model_of
from solar_challenge.gridservices import (
    FlatGridServices,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
)

_EVENTS = GridServicesEventsConfig(band="high", aggregator_share=0.1)


def _finance(
    model: str, rate: float, events: GridServicesEventsConfig | None
) -> FinanceConfig:
    return dataclasses.replace(
        FinanceConfig(standing_charge_pence_per_day=60.0),
        grid_services_model=model,
        grid_services_income_per_kw_per_year_gbp=rate,
        grid_services_events=events,
    )


@pytest.mark.parametrize(
    ("model", "rate", "events", "expected"),
    [
        ("flat", 0.0, None, NoGridServices()),
        ("flat", 12.0, None, FlatGridServices(12.0)),
        ("flat", 12.0, _EVENTS, FlatGridServices(12.0)),
        ("flat", 0.0, _EVENTS, NoGridServices()),
        ("capacity_at_events", 0.0, _EVENTS, _EVENTS),
        ("capacity_at_events", 12.0, _EVENTS, _EVENTS),
    ],
    ids=[
        "flat-zero-rate",
        "flat-rate",
        "flat-rate-events-ignored",
        "flat-zero-rate-events-ignored",
        "events",
        "events-rate-ignored",
    ],
)
def test_grid_services_model_of_maps_todays_three_fields(
    model: str,
    rate: float,
    events: GridServicesEventsConfig | None,
    expected: GridServicesModel,
) -> None:
    assert grid_services_model_of(_finance(model, rate, events)) == expected


@pytest.mark.parametrize("rate", [0.0, 12.0])
def test_grid_services_model_of_refuses_the_events_model_without_events(
    rate: float,
) -> None:
    finance = _finance("capacity_at_events", rate, None)

    with pytest.raises(
        ConfigurationError,
        match=re.escape(
            "grid_services_model='capacity_at_events' requires "
            "grid_services_events to be configured"
        ),
    ):
        grid_services_model_of(finance)
