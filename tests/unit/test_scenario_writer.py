"""Tests for scenario_writer: configs written as scenario YAML that config.py's loaders read back."""

import dataclasses
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.config import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    LOCATION_BLOCK,
    PV_BLOCK,
    ComponentBlock,
    load_fleet_config,
    load_home_config,
    load_scenarios,
    parse_seg_rate,
)
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_writer import fleet_scenario, home_scenario, scenario_yaml
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig


def _setting_every_key(block: ComponentBlock[Any], **values: Any) -> Any:
    """*block*'s dataclass built from *values*, refused unless each of *block*'s keys is set away from what an omitted key reads as."""
    config = block.config_type(**values)
    unset = [key for key in block.keys if getattr(config, key) == block.value_when_omitted(key)]
    assert not unset, f"{block.config_type.__name__} leaves {unset} as an omitted key reads"
    return config


def _every_grammar_field_home() -> HomeConfig:
    """A Dublin home with every key of every component block table set away from what an omitted key reads as."""
    return HomeConfig(
        pv_config=_setting_every_key(
            PV_BLOCK,
            capacity_kw=9.0,
            azimuth=135.0,
            tilt=20.0,
            name="South roof",
            module_efficiency=0.21,
            temperature_coefficient=-0.0035,
            inverter_efficiency=0.97,
            inverter_capacity_kw=8.0,
            system_age_years=3.0,
            degradation_rate_per_year=0.006,
            system_losses=0.05,
        ),
        battery_config=_setting_every_key(
            BATTERY_BLOCK,
            capacity_kwh=10.0,
            max_charge_kw=3.0,
            max_discharge_kw=3.5,
            name="Wall",
            dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
            grid_charging=GridChargeConfig(target_soc_fraction=0.8),
            min_soc_fraction=0.15,
            max_soc_fraction=0.95,
            efficiency=0.9,
            system_age_years=2.0,
            calendar_fade_rate_per_year=0.03,
            cycle_fade_per_equivalent_full_cycle=6e-05,
            soh_floor=0.6,
            soh=0.95,
        ),
        load_config=_setting_every_key(
            LOAD_BLOCK,
            annual_consumption_kwh=4200.0,
            household_occupants=4,
            name="Family",
            use_stochastic=False,
            seed=7,
        ),
        heat_pump_config=_setting_every_key(
            HEAT_PUMP_BLOCK,
            heat_pump_type="GSHP",
            thermal_capacity_kw=6.0,
            annual_heat_demand_kwh=9000.0,
            name="Ground loop",
        ),
        ev_config=_setting_every_key(
            EV_BLOCK,
            charger_type="7kW",
            arrival_hour=19,
            departure_hour=6,
            required_charge_kwh=20.0,
            smart_charging_mode="solar",
            name="Car",
        ),
        location=_setting_every_key(
            LOCATION_BLOCK,
            latitude=53.35,
            longitude=-6.26,
            timezone="Europe/Dublin",
            altitude=8.0,
            name="Dublin, IE",
        ),
        name="Nine kW home",
        tariff_config=TariffConfig.economy_7(),
        dispatch_strategy="tou_optimized",
        seg_tariff=SEGTariff(name="Octopus Outgoing", rate_pence_per_kwh=15.0),
    )


def _load_through_home_run(document: dict[str, Any], tmp_path: Path) -> HomeConfig:
    """Write *document* as a scenario file and load it the way `home run` does."""
    path = tmp_path / "home.yaml"
    path.write_text(scenario_yaml(document), encoding="utf-8")
    return home_config_for_run(path)


def _written(document: dict[str, Any], tmp_path: Path) -> Path:
    """The path of a scenario file holding *document*."""
    path = tmp_path / "scenario.yaml"
    path.write_text(scenario_yaml(document), encoding="utf-8")
    return path


def _two_every_key_homes() -> list[HomeConfig]:
    """Two homes setting every key, differing only in their names and one value of each block."""
    first = _every_grammar_field_home()
    second = dataclasses.replace(
        first,
        name="Second home",
        pv_config=dataclasses.replace(first.pv_config, tilt=25.0),
        battery_config=dataclasses.replace(first.battery_config, capacity_kwh=12.0),
        load_config=dataclasses.replace(first.load_config, seed=8),
        heat_pump_config=dataclasses.replace(first.heat_pump_config, thermal_capacity_kw=7.0),
        ev_config=dataclasses.replace(first.ev_config, departure_hour=5),
    )
    return [first, second]


def _through_home_run(tmp_path: Path) -> tuple[object, object]:
    """The home `home run` reads back, and the home written, its SEG tariff unnamed: a seg: block names none."""
    home = _every_grammar_field_home()
    loaded = home_config_for_run(_written(home_scenario(home, name="Nine kW home"), tmp_path))
    return loaded, dataclasses.replace(home, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=15.0))


def _through_load_home_config(tmp_path: Path) -> tuple[object, object]:
    """The home load_home_config reads back, and the home written, without the SEG tariff it does not read."""
    home = _every_grammar_field_home()
    loaded = load_home_config(_written(home_scenario(home, name="Nine kW home"), tmp_path))
    return loaded, dataclasses.replace(home, seg_tariff=None)


def _through_load_scenarios(tmp_path: Path) -> tuple[object, object]:
    """The home and SEG rate load_scenarios reads back from the document and a period: block, and those written."""
    home = _every_grammar_field_home()
    document = {
        **home_scenario(home, name="Nine kW home"),
        "period": {"start_date": "2024-06-01", "end_date": "2024-06-07"},
    }
    [scenario] = load_scenarios(_written(document, tmp_path))
    return (scenario.home, scenario.seg_tariff_pence_per_kwh), (
        dataclasses.replace(home, seg_tariff=None),
        15.0,
    )


def _through_load_fleet_config(tmp_path: Path) -> tuple[object, object]:
    """The homes load_fleet_config reads back, and the homes written, without the SEG tariff it does not read."""
    homes = _two_every_key_homes()
    fleet = load_fleet_config(_written(fleet_scenario(homes, name="Fleet run"), tmp_path))
    return fleet.homes, [dataclasses.replace(home, seg_tariff=None) for home in homes]


@pytest.mark.parametrize(
    "round_trip",
    [
        pytest.param(_through_home_run, id="home_config_for_run"),
        pytest.param(_through_load_home_config, id="load_home_config"),
        pytest.param(_through_load_scenarios, id="load_scenarios"),
        pytest.param(_through_load_fleet_config, id="load_fleet_config"),
    ],
)
def test_a_home_setting_every_key_written_as_a_scenario_reads_back_equal(
    round_trip: Callable[[Path], tuple[object, object]], tmp_path: Path
) -> None:
    """B2, R3: every key of every table survives the round trip through each loader."""
    loaded, written = round_trip(tmp_path)

    assert loaded == written


@pytest.mark.parametrize(
    ("written_block", "block"),
    [
        pytest.param(lambda document: document["home"]["pv"], PV_BLOCK, id="pv"),
        pytest.param(lambda document: document["home"]["load"], LOAD_BLOCK, id="load"),
        pytest.param(lambda document: document["home"]["heat_pump"], HEAT_PUMP_BLOCK, id="heat_pump"),
        pytest.param(lambda document: document["home"]["ev"], EV_BLOCK, id="ev"),
        pytest.param(lambda document: document["location"], LOCATION_BLOCK, id="location"),
    ],
)
def test_a_block_is_written_with_every_key_of_its_table_in_order(
    written_block: Callable[[dict[str, Any]], dict[str, Any]], block: ComponentBlock[Any]
) -> None:
    """R2: a component block carries every key of its table, in the table's order."""
    document = home_scenario(_every_grammar_field_home(), name="Nine kW home")

    assert list(written_block(document)) == list(block.keys)


def test_a_per_direction_battery_is_written_with_every_key_its_efficiency_null() -> None:
    """R2: an unset round-trip efficiency is written as null, which the reader reads as absent."""
    home = _home(
        4.0,
        battery_config=BatteryConfig(
            capacity_kwh=5.0, charge_efficiency=0.96, discharge_efficiency=0.97
        ),
    )

    battery = home_scenario(home, name="Split efficiencies")["home"]["battery"]

    assert list(battery) == list(BATTERY_BLOCK.keys)
    assert battery["efficiency"] is None


def test_a_round_trip_efficiency_battery_is_written_without_the_pair_it_derives() -> None:
    """R2's one stated exception: a battery with an efficiency omits the per-direction pair derived from it."""
    battery = home_scenario(_every_grammar_field_home(), name="Nine kW home")["home"]["battery"]

    assert list(battery) == [
        key for key in BATTERY_BLOCK.keys if key not in {"charge_efficiency", "discharge_efficiency"}
    ]


def test_a_home_without_optional_parts_loads_back_without_them(tmp_path: Path) -> None:
    home = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

    loaded = _load_through_home_run(home_scenario(home, name="Bare home"), tmp_path)

    assert loaded == home


def test_an_unset_module_setting_is_written_as_null_and_loads_back_unset(tmp_path: Path) -> None:
    """The pv: block carries every key, an unset one as null, which loads back as None: the module's own."""
    home = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

    document = home_scenario(home, name="Module's own settings")

    pv_block = document["home"]["pv"]
    assert pv_block["module_efficiency"] is None
    assert pv_block["temperature_coefficient"] is None
    assert _load_through_home_run(document, tmp_path) == home


def test_per_direction_battery_efficiencies_load_back(tmp_path: Path) -> None:
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            efficiency=None,
            charge_efficiency=0.96,
            discharge_efficiency=0.97,
        ),
    )

    loaded = _load_through_home_run(home_scenario(home, name="Split efficiencies"), tmp_path)

    assert loaded == home


@pytest.mark.parametrize(
    "strategy",
    [
        pytest.param(SelfConsumptionStrategyConfig(), id="self_consumption"),
        pytest.param(TOUOptimizedStrategyConfig(peak_hours=((16, 19), (20, 22))), id="tou_optimized"),
        pytest.param(PeakShavingStrategyConfig(import_limit_kw=3.0), id="peak_shaving"),
    ],
)
def test_a_battery_with_each_dispatch_strategy_loads_back_equal(strategy: object, tmp_path: Path) -> None:
    """Each strategy's dispatch_strategy: block, grid charging beside it, survives the round trip."""
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(),
        battery_config=BatteryConfig(
            capacity_kwh=5.0, dispatch_strategy=strategy, grid_charging=GridChargeConfig(0.8)
        ),
        tariff_config=TariffConfig.economy_7(),
    )

    loaded = _load_through_home_run(home_scenario(home, name="Dispatching home"), tmp_path)

    assert loaded == home


@pytest.mark.parametrize("field", list(PV_BLOCK.outside_grammar))
def test_a_pv_field_the_grammar_has_no_key_for_is_refused(field: str) -> None:
    """B3: a PV field outside the grammar, set away from its default, is refused by name."""
    home = HomeConfig(
        pv_config=dataclasses.replace(PVConfig(capacity_kw=4.0), **{field: {"pdc0": 250.0}}),
        load_config=LoadConfig(),
    )

    with pytest.raises(ValueError, match=field):
        home_scenario(home, name="Custom pvlib")


def test_every_pv_field_the_grammar_has_no_key_for_is_named_in_one_refusal() -> None:
    """B3: a PV config setting both custom pvlib parameter fields is refused naming both."""
    home = HomeConfig(
        pv_config=dataclasses.replace(
            PVConfig(capacity_kw=4.0),
            **{field: {"pdc0": 250.0} for field in PV_BLOCK.outside_grammar},
        ),
        load_config=LoadConfig(),
    )

    with pytest.raises(ValueError) as refused:
        home_scenario(home, name="Custom pvlib")

    assert [field for field in PV_BLOCK.outside_grammar if field not in str(refused.value)] == []


_EDINBURGH = Location(55.95, -3.19, altitude=47.0, name="Edinburgh, UK")


def _home(pv_kw: float, *, load_config: LoadConfig = LoadConfig(), **parts: Any) -> HomeConfig:
    """A home with *pv_kw* of PV, *load_config*, and whichever other HomeConfig *parts* are given."""
    return HomeConfig(pv_config=PVConfig(capacity_kw=pv_kw), load_config=load_config, **parts)


def test_a_fleet_written_as_a_scenario_loads_back_through_load_fleet_config(
    tmp_path: Path,
) -> None:
    homes = [
        _home(3.0, location=_EDINBURGH, name="Home 1"),
        _home(
            5.0,
            location=_EDINBURGH,
            name="Home 2",
            battery_config=BatteryConfig(capacity_kwh=5.0),
            tariff_config=TariffConfig.economy_7(),
            dispatch_strategy="tou_optimized",
        ),
        _home(
            4.0,
            location=_EDINBURGH,
            name="Home 3",
            load_config=LoadConfig(annual_consumption_kwh=2900.0, seed=44),
        ),
    ]
    path = tmp_path / "fleet.yaml"
    path.write_text(scenario_yaml(fleet_scenario(homes, name="Fleet run")), encoding="utf-8")

    fleet = load_fleet_config(path)

    assert fleet.homes == homes
    assert fleet.name == "Fleet run"


def test_a_fleet_seg_block_carries_the_rate_its_homes_share() -> None:
    """The homes' SEG tariffs share a rate but not a name, which no seg: block carries.

    load_fleet_config does not read seg: yet (pending task 185), so the block is
    checked through the SEG reader that finance and optimize use.
    """
    homes = [
        _home(3.0, seg_tariff=SEGTariff(name="Octopus Energy", rate_pence_per_kwh=4.1)),
        _home(4.0, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=4.1)),
    ]

    text = scenario_yaml(fleet_scenario(homes, name="SEG fleet"))

    assert parse_seg_rate(yaml.safe_load(text)["seg"]) == 4.1


@pytest.mark.parametrize(
    ("homes", "refusal"),
    [
        pytest.param(
            [_home(3.0), _home(4.0, location=_EDINBURGH)], "location", id="two locations"
        ),
        pytest.param(
            [
                _home(3.0, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=4.1)),
                _home(4.0, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=5.5)),
            ],
            "seg",
            id="two SEG rates",
        ),
        pytest.param(
            [_home(3.0, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=4.1)), _home(4.0)],
            "seg",
            id="SEG on one home only",
        ),
        pytest.param([], "at least one home", id="no homes"),
    ],
)
def test_a_fleet_the_grammar_cannot_carry_is_refused(
    homes: list[HomeConfig], refusal: str
) -> None:
    """The grammar has one location: block and one seg: block for the whole fleet."""
    with pytest.raises(ValueError, match=refusal):
        fleet_scenario(homes, name="Unwritable fleet")
