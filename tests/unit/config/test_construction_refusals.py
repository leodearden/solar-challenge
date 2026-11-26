# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every block reader that builds an input type refuses as its type does, prefixed by the block's path."""

import math
from typing import Any, Callable

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityConfig
from solar_challenge.dispatch import GridChargeConfig, PeakShavingStrategyConfig, TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import EventWindow, FlatGridServices, GridServicesEventsConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import (
    constructed,
    parse_community_config,
    parse_finance_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import PRESET_RATES, PresetRates, TariffConfig, TariffPeriod
from tests._construction_refusals import construction_refusal, prefixed_construction_refusal


class TestConstructed:
    """constructed builds a type from the values given, and re-raises its refusal prefixed by the block's path."""

    def test_it_is_the_type_built_from_the_values(self) -> None:
        assert constructed("home.pv", PVConfig, capacity_kw=4.0) == PVConfig(capacity_kw=4.0)

    def test_a_refusal_of_the_type_is_re_raised_prefixed_by_the_blocks_path_from_the_refusal(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("home.pv", PVConfig, capacity_kw=True)

        assert str(refusal.value) == prefixed_construction_refusal("home.pv", lambda: PVConfig(capacity_kw=True))
        assert isinstance(refusal.value.__cause__, ConfigurationError)
        assert str(refusal.value.__cause__) == construction_refusal(lambda: PVConfig(capacity_kw=True))

    def test_the_top_level_is_named_the_top_level(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("", PVConfig, capacity_kw=True)

        assert str(refusal.value) == prefixed_construction_refusal(
            "the top level", lambda: PVConfig(capacity_kw=True)
        )

    def test_a_type_error_is_re_raised_as_a_configuration_error_prefixed_by_the_blocks_path_from_it(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            constructed("x", PVConfig, capacity_kw=4.0, no_such_key=1)

        assert isinstance(refusal.value.__cause__, TypeError)
        assert "no_such_key" in str(refusal.value.__cause__)
        assert str(refusal.value) == f"x: {refusal.value.__cause__}"


def _home(blocks: dict[str, Any], *, block_path: str = "home") -> Callable[[], HomeConfig]:
    """Read a home: block holding only *blocks*, at *block_path* in its file, at the Bristol default location."""
    return lambda: parse_home_block(blocks, Location.bristol(), block_path=block_path)


_COMPONENT_BLOCK_ROWS = [
    pytest.param(
        lambda: parse_location_block({"latitude": 51.45, "longitude": -2.58, "altitude": math.nan}),
        "location",
        lambda: Location(latitude=51.45, longitude=-2.58, altitude=math.nan),
        id="location-altitude-nan",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}),
        "home.pv",
        lambda: PVConfig(capacity_kw=True),
        id="home-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}, block_path="homes[1]"),
        "homes[1].pv",
        lambda: PVConfig(capacity_kw=True),
        id="homes-entry-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": True}}, block_path=""),
        "pv",
        lambda: PVConfig(capacity_kw=True),
        id="flat-home-pv-capacity-boolean",
    ),
    pytest.param(
        _home({"pv": {"capacity_kw": 4.0, "azimuth": "south"}}),
        "home.pv",
        lambda: PVConfig(capacity_kw=4.0, azimuth="south"),
        id="home-pv-azimuth-word",
    ),
    pytest.param(
        _home({"battery": {"capacity_kwh": True}}),
        "home.battery",
        lambda: BatteryConfig(capacity_kwh=True),
        id="home-battery-capacity-boolean",
    ),
    pytest.param(
        _home({
            "battery": {
                "capacity_kwh": 5.0,
                "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": True},
            },
        }),
        "home.battery.dispatch_strategy",
        lambda: PeakShavingStrategyConfig(import_limit_kw=True),
        id="home-battery-peak-shaving-limit-boolean",
    ),
    pytest.param(
        _home({
            "battery": {
                "capacity_kwh": 5.0,
                "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[20, 16]]},
            },
        }),
        "home.battery.dispatch_strategy",
        lambda: TOUOptimizedStrategyConfig(((20, 16),)),
        id="home-battery-tou-window-reversed",
    ),
    pytest.param(
        _home({"battery": {"capacity_kwh": 5.0, "grid_charging": {"target_soc_fraction": True}}}),
        "home.battery.grid_charging",
        lambda: GridChargeConfig(target_soc_fraction=True),
        id="home-battery-grid-charging-target-boolean",
    ),
    pytest.param(
        _home({"load": {"household_occupants": 2.5}}),
        "home.load",
        lambda: LoadConfig(household_occupants=2.5),
        id="home-load-occupants-not-whole",
    ),
    pytest.param(
        _home({"heat_pump": {"heat_pump_type": "ASHP", "thermal_capacity_kw": math.nan}}),
        "home.heat_pump",
        lambda: HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=math.nan),
        id="home-heat-pump-capacity-nan",
    ),
    pytest.param(
        _home({"ev": {"charger_type": "7kW", "arrival_hour": 18.9}}),
        "home.ev",
        lambda: EVConfig(charger_type="7kW", arrival_hour=18.9),
        id="home-ev-arrival-not-whole",
    ),
]


_OFF_PEAK_EV = {"charger_type": "7kW", "smart_charging_mode": "off_peak"}


def _home_with_an_off_peak_ev_and_no_tariff() -> HomeConfig:
    """The home a home: block holding only an ev: block of _OFF_PEAK_EV describes, which HomeConfig refuses: off_peak charging needs a tariff."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(),
        ev_config=EVConfig(**_OFF_PEAK_EV),
        location=Location.bristol(),
    )


_HOME_ROWS = [
    pytest.param(
        _home({"ev": _OFF_PEAK_EV}),
        "home",
        _home_with_an_off_peak_ev_and_no_tariff,
        id="home-off-peak-ev-without-a-tariff",
    ),
    pytest.param(
        _home({"ev": _OFF_PEAK_EV}, block_path="homes[0]"),
        "homes[0]",
        _home_with_an_off_peak_ev_and_no_tariff,
        id="homes-entry-off-peak-ev-without-a-tariff",
    ),
    pytest.param(
        _home({"ev": _OFF_PEAK_EV}, block_path=""),
        "the top level",
        _home_with_an_off_peak_ev_and_no_tariff,
        id="flat-home-off-peak-ev-without-a-tariff",
    ),
]


def _tariff(block: dict[str, Any]) -> Callable[[], object]:
    """Read *block* as a tariff: block at the path parse_tariff_config names by default, "tariff"."""
    return lambda: parse_tariff_config(block)


_TARIFF_ROWS = [
    pytest.param(
        _tariff({"type": "flat_rate", "rate_per_kwh": True}),
        "tariff",
        lambda: TariffConfig.flat_rate(rate_per_kwh=True),
        id="flat-rate-boolean",
    ),
    pytest.param(
        _tariff({"type": "flat_rate", "rate_per_kwh": "cheap"}),
        "tariff",
        lambda: TariffConfig.flat_rate(rate_per_kwh="cheap"),
        id="flat-rate-word",
    ),
    pytest.param(
        _tariff({"type": "economy_7", "peak_rate": True}),
        "tariff",
        lambda: PresetRates(off_peak_rate=PRESET_RATES["economy_7"].off_peak_rate, peak_rate=True),
        id="economy-7-peak-rate-boolean",
    ),
    pytest.param(
        _tariff({"type": "economy_10", "off_peak_rate": "cheap"}),
        "tariff",
        lambda: PresetRates(off_peak_rate="cheap", peak_rate=PRESET_RATES["economy_10"].peak_rate),
        id="economy-10-off-peak-rate-word",
    ),
    pytest.param(
        _tariff({"type": "economy_7", "off_peak_start": "25:00"}),
        "tariff",
        lambda: TariffConfig.economy_7(off_peak_start="25:00"),
        id="economy-7-start-off-the-clock",
    ),
    pytest.param(
        _tariff({"type": "custom", "periods": [{"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": True}]}),
        "tariff.periods[0]",
        lambda: TariffPeriod("00:00", "00:00", True),
        id="custom-period-rate-boolean",
    ),
    pytest.param(
        _tariff({"type": "custom", "periods": [{"start_time": "07:00", "end_time": "23:00", "rate_per_kwh": 0.30}]}),
        "tariff",
        lambda: TariffConfig(periods=(TariffPeriod("07:00", "23:00", 0.30),)),
        id="custom-periods-leaving-a-gap",
    ),
]


def _community(block: dict[str, Any]) -> Callable[[], object]:
    """Read *block* as a community: block at "community", the path load_community_config reads it at."""
    return lambda: parse_community_config(block, block_path="community")


_SEG_AND_COMMUNITY_ROWS = [
    pytest.param(
        lambda: parse_seg_rate({"rate_pence_per_kwh": True}),
        "seg",
        lambda: SEGTariff(name="", rate_pence_per_kwh=True),
        id="seg-rate-boolean",
    ),
    pytest.param(
        lambda: parse_seg_rate({"rate_pence_per_kwh": -1}),
        "seg",
        lambda: SEGTariff(name="", rate_pence_per_kwh=-1),
        id="seg-rate-negative",
    ),
    pytest.param(
        lambda: parse_seg_rate({"rate_pence_per_kwh": True}, block_path="scenario.seg"),
        "scenario.seg",
        lambda: SEGTariff(name="", rate_pence_per_kwh=True),
        id="scenario-seg-rate-boolean",
    ),
    pytest.param(
        _community({"sharing_mode": "p2p", "billing": {"seg_rate_pence_per_kwh": None}}),
        "community.billing.seg_rate_pence_per_kwh",
        lambda: SEGTariff(name="", rate_pence_per_kwh=None),
        id="billing-scalar-rate-null",
    ),
    pytest.param(
        _community({"sharing_mode": "p2p", "billing": {"seg_rate_pence_per_kwh": True}}),
        "community.billing.seg_rate_pence_per_kwh",
        lambda: SEGTariff(name="", rate_pence_per_kwh=True),
        id="billing-scalar-rate-boolean",
    ),
    pytest.param(
        _community({"sharing_mode": "p2p", "billing": {"seg": {"rate_pence_per_kwh": True}}}),
        "community.billing.seg",
        lambda: SEGTariff(name="", rate_pence_per_kwh=True),
        id="billing-seg-rate-boolean",
    ),
    pytest.param(
        _community({"sharing_mode": "p3"}),
        "community",
        lambda: CommunityConfig(sharing_mode="p3"),
        id="community-sharing-mode-unknown",
    ),
]


def _finance(block: dict[str, Any]) -> Callable[[], object]:
    """Read *block* as a finance: block at the path parse_finance_config names by default, "finance"."""
    return lambda: parse_finance_config(block)


_STANDING_CHARGE = {"standing_charge_pence_per_day": 60.0}


_EVENT_WINDOW = {"months": [1, 2], "weekdays": [0, 1], "hours": [17, 18], "events_per_year": 5, "event_hours": 2.0}


def _priced_at_events(events_block: dict[str, object]) -> dict[str, object]:
    """A finance block whose grid_services_model block prices capacity at events, setting *events_block*'s keys."""
    return {**_STANDING_CHARGE, "grid_services_model": {"type": "capacity_at_events", **events_block}}


def _event_window_row(key: str, value: object, row_id: str) -> Any:
    """The row of a finance block priced at events whose one event window sets *key* to *value*, which EventWindow refuses."""
    window = {**_EVENT_WINDOW, key: value}
    return pytest.param(
        _finance(_priced_at_events({"event_windows": [window]})),
        "finance.grid_services_model.event_windows[0]",
        lambda: EventWindow(**window),
        id=row_id,
    )


_FINANCE_ROWS = [
    pytest.param(
        _finance({**_STANDING_CHARGE, "vat_rate": True}),
        "finance",
        lambda: FinanceConfig(**_STANDING_CHARGE, vat_rate=True),
        id="finance-vat-rate-boolean",
    ),
    pytest.param(
        _finance({**_STANDING_CHARGE, "grid_services_model": {"type": "flat", "income_per_kw_per_year_gbp": True}}),
        "finance.grid_services_model",
        lambda: FlatGridServices(income_per_kw_per_year_gbp=True),
        id="flat-rate-boolean",
    ),
    pytest.param(
        _finance(_priced_at_events({"aggregator_share": True})),
        "finance.grid_services_model",
        lambda: GridServicesEventsConfig(aggregator_share=True),
        id="events-aggregator-share-boolean",
    ),
    pytest.param(
        _finance(_priced_at_events({"band": 5})),
        "finance.grid_services_model",
        lambda: GridServicesEventsConfig(band=5),  # type: ignore[arg-type]
        id="events-band-a-number",
    ),
    _event_window_row("event_hours", math.inf, "event-window-hours-infinite"),
    _event_window_row("months", [1.5], "event-window-month-a-fraction"),
    _event_window_row("events_per_year", 5.5, "event-window-events-per-year-a-fraction"),
]


@pytest.mark.parametrize(
    ("read", "label", "construct"),
    [*_COMPONENT_BLOCK_ROWS, *_HOME_ROWS, *_TARIFF_ROWS, *_SEG_AND_COMMUNITY_ROWS, *_FINANCE_ROWS],
)
def test_a_value_its_blocks_type_refuses_is_refused_prefixed_by_the_blocks_path(
    read: Callable[[], object], label: str, construct: Callable[[], object]
) -> None:
    with pytest.raises(ConfigurationError) as refusal:
        read()

    assert str(refusal.value) == prefixed_construction_refusal(label, construct)
