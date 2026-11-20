# SPDX-License-Identifier: AGPL-3.0-or-later
"""FinanceConfig refuses an inconsistent grid-services choice at construction, and finance.grid_services_model_of maps a consistent one to its pricing value.

The rule is the β column of docs/prds/grid-services-pricing-model.md §5.2.
"""

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

# The refusal of the events model with no events configuration opens as it did when only project_multi_year refused it.
_EVENTS_MODEL_WITHOUT_EVENTS = (
    "grid_services_model='capacity_at_events' requires grid_services_events to be configured"
)


@pytest.mark.parametrize(
    ("model", "rate", "events", "expected"),
    [
        ("flat", 0.0, None, NoGridServices()),
        ("flat", 12.0, None, FlatGridServices(12.0)),
        ("capacity_at_events", 0.0, _EVENTS, _EVENTS),
    ],
    ids=["flat-zero-rate", "flat-rate", "events"],
)
def test_grid_services_model_of_maps_todays_three_fields(
    model: str,
    rate: float,
    events: GridServicesEventsConfig | None,
    expected: GridServicesModel,
) -> None:
    finance = FinanceConfig(
        standing_charge_pence_per_day=60,
        grid_services_model=model,
        grid_services_income_per_kw_per_year_gbp=rate,
        grid_services_events=events,
    )

    assert grid_services_model_of(finance) == expected


@pytest.mark.parametrize(
    ("model", "rate", "events", "named"),
    [
        pytest.param(
            "flat", 0.0, _EVENTS, ("'flat'", "grid_services_events"), id="flat-zero-rate-with-events"
        ),
        pytest.param(
            "flat", 12.0, _EVENTS, ("'flat'", "grid_services_events"), id="flat-rate-with-events"
        ),
        pytest.param(
            "capacity_at_events",
            12.0,
            _EVENTS,
            ("'capacity_at_events'", "grid_services_income_per_kw_per_year_gbp", "12.0"),
            id="events-with-a-flat-rate",
        ),
        pytest.param(
            "capacity_at_events",
            0.0,
            None,
            (_EVENTS_MODEL_WITHOUT_EVENTS, "grid_services_events=None"),
            id="events-model-zero-rate-without-events",
        ),
        pytest.param(
            "capacity_at_events",
            12.0,
            None,
            (_EVENTS_MODEL_WITHOUT_EVENTS, "grid_services_events=None"),
            id="events-model-rate-without-events",
        ),
        pytest.param(
            "foo", 0.0, None, ("'foo'", "flat", "capacity_at_events"), id="unknown-selector"
        ),
    ],
)
def test_an_inconsistent_grid_services_choice_is_refused_at_construction(
    model: str,
    rate: float,
    events: GridServicesEventsConfig | None,
    named: tuple[str, ...],
) -> None:
    """A field the chosen model does not read, a missing events configuration or an unknown selector is refused, naming the fields involved and their values."""
    with pytest.raises(ValueError) as refusal:
        FinanceConfig(
            standing_charge_pence_per_day=60,
            grid_services_model=model,
            grid_services_income_per_kw_per_year_gbp=rate,
            grid_services_events=events,
        )

    assert refusal.type is ConfigurationError
    message = str(refusal.value)
    for token in named:
        assert token in message, message
