# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every block of a scenario file refuses a key its parser does not read, naming the block's path, the key and the keys it recognises."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.config import FLEET_TEMPLATE, HOME_TEMPLATE, SCENARIO_TEMPLATE
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.config import (
    BatteryDistributionConfig,
    ConfigurationError,
    DispatchStrategyConfig,
    EVDistributionConfig,
    FleetDistributionConfig,
    GridChargeConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    OutputConfig,
    ProportionalDistribution,
    PVDistributionConfig,
    ShuffledPoolDistribution,
    SimulationPeriod,
    SweepSpec,
    UniformDistribution,
    WeightedDiscreteDistribution,
    detect_sweep_spec,
    expand_sweep_configs,
    generate_homes_from_distribution,
    load_community_config,
    load_config,
    load_fleet_config,
    load_home_config,
    load_scenarios,
    parse_finance_config,
    parse_fleet_distribution_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.ev import EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig, TariffPeriod

_PERIOD = {"start_date": "2024-01-01", "end_date": "2024-01-07"}

_SCENARIO = {
    "name": "Scenario",
    "period": _PERIOD,
    "home": {"pv": {"capacity_kw": 4.0}, "load": {"annual_consumption_kwh": 3400}},
}

_CLI_TEMPLATES = {"home": HOME_TEMPLATE, "fleet": FLEET_TEMPLATE, "scenario": SCENARIO_TEMPLATE}


def _parsed_home(**blocks: Any) -> HomeConfig:
    """Parse a ``home:`` block holding only *blocks*, at the Bristol default location."""
    return parse_home_block(blocks, Location.bristol())


def _parsed_fleet_distribution(**sections: Any) -> FleetDistributionConfig:
    """Parse a one-home ``fleet_distribution:`` block with a 4 kW pv section, overridden by *sections*."""
    return parse_fleet_distribution_config({"n_homes": 1, "pv": {"capacity_kw": 4.0}, **sections})


def _refusal(block_path: str, *keys: str) -> str:
    """Match the refusal of *keys* by the block at *block_path*."""
    return re.escape(
        f"Unrecognised keys in {block_path}: " + ", ".join(repr(key) for key in sorted(keys)) + ";"
    )


def _write(tmp_path: Path, document: object) -> Path:
    """Write *document* as a YAML file under *tmp_path* and return its path."""
    path = tmp_path / "doc.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


def _parse_every_block(path: Path) -> None:
    """Read every block of the file at *path* through the public reader that consumes it.

    A fleet_distribution carrying a sweep is read as ``fleet sweep`` reads it, any
    other fleet as ``fleet run`` does; only a file naming its scenario is read as one.
    """
    document = load_config(path)
    if "home" in document:
        parse_home_block(document["home"], parse_location_block(document.get("location")))
    if "fleet_distribution" in document:
        distribution = parse_fleet_distribution_config(document["fleet_distribution"])
        if detect_sweep_spec(distribution) is None:
            load_fleet_config(path)
    elif "homes" in document:
        load_fleet_config(path)
    if {"name", "period"} <= document.keys() and ("home" in document or "homes" in document):
        load_scenarios(path)
    parse_seg_rate(document.get("seg"))
    parse_finance_config(document.get("finance"))
    load_community_config(path)


class TestHomeBlockKeys:
    """A home: block and every sub-block refuse a key their parser does not read."""

    @pytest.mark.parametrize(
        ("blocks", "block_path", "key"),
        [
            pytest.param(
                {"pv": {"capacity_kw": 4.0}, "batteries": {}}, "home", "batteries", id="home"
            ),
            pytest.param({"pv": {"capacity_kwp": 4.0}}, "home.pv", "capacity_kwp", id="pv"),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "capacity": 10.0}},
                "home.battery",
                "capacity",
                id="battery",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "grid_charging": {"target_soc": 0.8}}},
                "home.battery.grid_charging",
                "target_soc",
                id="grid_charging",
            ),
            pytest.param(
                {
                    "battery": {
                        "capacity_kwh": 5.0,
                        "dispatch_strategy": {
                            "strategy_type": "tou_optimized",
                            "peak_hours": [[16, 19]],
                            "off_peak_hours": [[0, 7]],
                        },
                    }
                },
                "home.battery.dispatch_strategy",
                "off_peak_hours",
                id="dispatch_strategy",
            ),
            pytest.param({"load": {"annual_kwh": 3000}}, "home.load", "annual_kwh", id="load"),
            pytest.param(
                {
                    "heat_pump": {
                        "heat_pump_type": "ASHP",
                        "thermal_capacity_kw": 8.0,
                        "thermal_capacity": 12.0,
                    }
                },
                "home.heat_pump",
                "thermal_capacity",
                id="heat_pump",
            ),
            pytest.param(
                {"ev": {"charger_type": "7kW", "arrival_hour": 18, "departure": 7}},
                "home.ev",
                "departure",
                id="ev",
            ),
        ],
    )
    def test_unrecognised_key_is_refused_naming_its_block(
        self, blocks: dict[str, Any], block_path: str, key: str
    ) -> None:
        """A key outside a block's grammar is refused, naming the block's path and the key."""
        with pytest.raises(ConfigurationError, match=_refusal(block_path, key)):
            _parsed_home(**blocks)

    def test_refusal_names_every_unrecognised_key_and_the_recognised_set(self) -> None:
        """The refusal lists every unrecognised key, then every key the block recognises."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_home(load={"annual_kwh": 3000, "people": 2})
        assert str(refusal.value) == (
            "Unrecognised keys in home.load: 'annual_kwh', 'people'; recognised keys: "
            "annual_consumption_kwh, household_occupants, name, seed, use_stochastic"
        )

    @pytest.mark.parametrize(
        ("blocks", "block_path", "type_name"),
        [
            pytest.param({"pv": 4.0}, "home.pv", "float", id="pv"),
            pytest.param({"load": None}, "home.load", "NoneType", id="load"),
            pytest.param({"battery": "big"}, "home.battery", "str", id="battery"),
            pytest.param({"heat_pump": ["ASHP"]}, "home.heat_pump", "list", id="heat_pump"),
            pytest.param({"ev": 7}, "home.ev", "int", id="ev"),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "dispatch_strategy": "tou_optimized"}},
                "home.battery.dispatch_strategy",
                "str",
                id="dispatch_strategy",
            ),
        ],
    )
    def test_non_mapping_block_is_refused_naming_its_block(
        self, blocks: dict[str, Any], block_path: str, type_name: str
    ) -> None:
        """A block that is not a mapping is refused, naming the block's path and the type it got."""
        with pytest.raises(
            ConfigurationError, match=re.escape(f"{block_path} must be a mapping, got {type_name}")
        ):
            _parsed_home(**blocks)

    @pytest.mark.parametrize(
        ("load", "document", "block_path"),
        [
            pytest.param(
                load_fleet_config,
                {"homes": [{"pv": {"capacity_kw": 4.0}}, {"pv": {"capacity_kwp": 4.0}}]},
                "homes[1].pv",
                id="fleet-homes",
            ),
            pytest.param(
                load_scenarios,
                {"name": "root", "period": _PERIOD, "home": {"pv": {"capacity_kwp": 4.0}}},
                "home.pv",
                id="root-scenario",
            ),
            pytest.param(
                load_scenarios,
                {
                    "scenario": {
                        "name": "nested",
                        "period": _PERIOD,
                        "home": {"pv": {"capacity_kwp": 4.0}},
                    }
                },
                "scenario.home.pv",
                id="scenario",
            ),
            pytest.param(
                load_scenarios,
                {
                    "scenarios": [
                        {"name": "first", "period": _PERIOD, "home": {"pv": {"capacity_kw": 4.0}}},
                        {
                            "name": "second",
                            "period": _PERIOD,
                            "homes": [{"pv": {"capacity_kw": 4.0}}, {"pv": {"capacity_kwp": 4.0}}],
                        },
                    ]
                },
                "scenarios[1].homes[1].pv",
                id="scenarios",
            ),
        ],
    )
    def test_block_path_names_the_home_within_its_file(
        self,
        tmp_path: Path,
        load: Callable[[Path], object],
        document: dict[str, Any],
        block_path: str,
    ) -> None:
        """A refusal inside a file names the block's path from the file's top level."""
        path = _write(tmp_path, document)
        with pytest.raises(ConfigurationError, match=_refusal(block_path, "capacity_kwp")):
            load(path)

    def test_flat_home_file_names_blocks_from_the_top_level(self, tmp_path: Path) -> None:
        """A home file without a home: key is itself the home block, so its blocks are named from the top level."""
        path = _write(tmp_path, {"pv": {"capacity_kwp": 4.0}})
        with pytest.raises(ConfigurationError, match=_refusal("pv", "capacity_kwp")):
            load_home_config(path)

    def test_flat_home_file_location_block_is_read_not_refused(self, tmp_path: Path) -> None:
        """load_home_config reads a flat home file's location: block itself, beside the home keys."""
        location = {"latitude": 52.0, "longitude": -1.5, "name": "Midlands"}
        path = _write(tmp_path, {"location": location, "pv": {"capacity_kw": 4.0}})
        assert load_home_config(path).location.latitude == 52.0

    def test_block_setting_every_recognised_key_is_accepted(self) -> None:
        """A home block setting every key of every sub-block parses to the HomeConfig built from those values."""
        pv: dict[str, Any] = {
            "capacity_kw": 5.0,
            "azimuth": 170.0,
            "tilt": 30.0,
            "name": "Roof",
            "module_efficiency": 0.21,
            "temperature_coefficient": -0.0035,
            "inverter_efficiency": 0.97,
            "inverter_capacity_kw": 3.68,
            "system_age_years": 2.0,
            "degradation_rate_per_year": 0.006,
        }
        grid_charging: dict[str, Any] = {"target_soc_fraction": 0.8}
        dispatch_strategy: dict[str, Any] = {
            "strategy_type": "tou_optimized",
            "peak_hours": [[16, 19]],
            "import_limit_kw": 3.5,
        }
        battery: dict[str, Any] = {
            "capacity_kwh": 9.5,
            "max_charge_kw": 3.0,
            "max_discharge_kw": 3.5,
            "name": "Wall",
            "dispatch_strategy": dispatch_strategy,
            "grid_charging": grid_charging,
            "min_soc_fraction": 0.15,
            "max_soc_fraction": 0.95,
            "charge_efficiency": 0.96,
            "discharge_efficiency": 0.97,
            "efficiency": 0.9,
            "system_age_years": 1.0,
            "calendar_fade_rate_per_year": 0.03,
            "cycle_fade_per_equivalent_full_cycle": 6e-5,
            "soh_floor": 0.6,
            "soh": 0.95,
        }
        load: dict[str, Any] = {
            "annual_consumption_kwh": 3400.0,
            "household_occupants": 2,
            "name": "Household",
            "use_stochastic": False,
            "seed": 7,
        }
        heat_pump: dict[str, Any] = {
            "heat_pump_type": "GSHP",
            "thermal_capacity_kw": 6.0,
            "annual_heat_demand_kwh": 9000.0,
            "name": "Heat pump",
        }
        ev: dict[str, Any] = {
            "charger_type": "7kW",
            "arrival_hour": 19,
            "departure_hour": 6,
            "required_charge_kwh": 30.0,
            "smart_charging_mode": "solar",
            "name": "Car",
        }
        block = {
            "name": "Every key",
            "pv": pv,
            "battery": battery,
            "load": load,
            "tariff": {"type": "flat_rate", "rate_per_kwh": 0.25, "name": "Flat"},
            "dispatch_strategy": "tou_optimized",
            "heat_pump": heat_pump,
            "ev": ev,
        }

        expected = HomeConfig(
            pv_config=PVConfig(**pv),
            battery_config=BatteryConfig(
                **{
                    **battery,
                    "dispatch_strategy": DispatchStrategyConfig(
                        **{**dispatch_strategy, "peak_hours": [(16, 19)]}
                    ),
                    "grid_charging": GridChargeConfig(**grid_charging),
                }
            ),
            load_config=LoadConfig(**load),
            location=Location.bristol(),
            name="Every key",
            tariff_config=TariffConfig.flat_rate(rate_per_kwh=0.25, name="Flat"),
            dispatch_strategy="tou_optimized",
            heat_pump_config=HeatPumpConfig(**heat_pump),
            ev_config=EVConfig(**ev),
        )
        assert parse_home_block(block, Location.bristol()) == expected


class TestTariffBlockKeys:
    """A tariff: block recognises the keys of its own type."""

    _NIGHT: dict[str, Any] = {"start_time": "00:00", "end_time": "07:00", "rate_per_kwh": 0.10}
    _DAY: dict[str, Any] = {"start_time": "07:00", "end_time": "00:00", "rate_per_kwh": 0.30}
    _ECONOMY_7_OVERRIDES: dict[str, Any] = {
        "off_peak_rate": 0.10,
        "peak_rate": 0.30,
        "off_peak_start": "01:00",
        "off_peak_end": "08:00",
    }
    _ECONOMY_10_OVERRIDES: dict[str, Any] = {
        "off_peak_rate": 0.09,
        "peak_rate": 0.29,
        "night_start": "00:30",
        "night_end": "05:30",
        "afternoon_start": "13:30",
        "afternoon_end": "16:30",
        "evening_start": "20:30",
        "evening_end": "22:30",
    }
    _MISKEYED_ECONOMY_7: dict[str, Any] = {"type": "economy_7", "rate_per_kwh": 0.30}

    @pytest.mark.parametrize(
        ("block", "key"),
        [
            pytest.param(
                {"type": "flat_rate", "rate_per_kwh": 0.30, "rate": 0.25}, "rate", id="flat_rate"
            ),
            pytest.param(_MISKEYED_ECONOMY_7, "rate_per_kwh", id="economy_7-flat_rate-key"),
            pytest.param({"type": "economy_7", "name": "E7"}, "name", id="economy_7-name"),
            pytest.param(
                {"type": "economy_10", "off_peak_start": "00:30"},
                "off_peak_start",
                id="economy_10-economy_7-key",
            ),
            pytest.param(
                {"type": "custom", "periods": [_NIGHT], "currency": "GBP"}, "currency", id="custom"
            ),
        ],
    )
    def test_key_another_tariff_type_reads_is_refused(
        self, block: dict[str, Any], key: str
    ) -> None:
        """A key outside the grammar of the block's own type is refused, even one another type reads."""
        with pytest.raises(ConfigurationError, match=_refusal("tariff", key)):
            parse_tariff_config(block)

    def test_custom_period_refuses_an_unrecognised_key(self) -> None:
        """Each custom period refuses a key a tariff period does not read, naming the period."""
        periods = [self._NIGHT, {**self._DAY, "rate": 0.30}]
        with pytest.raises(ConfigurationError, match=_refusal("tariff.periods[1]", "rate")):
            parse_tariff_config({"type": "custom", "periods": periods})

    @pytest.mark.parametrize(
        ("block", "block_path", "type_name"),
        [
            pytest.param("flat_rate", "tariff", "str", id="string"),
            pytest.param("", "tariff", "str", id="empty-string"),
            pytest.param(
                {"type": "custom", "periods": ["00:00-07:00"]},
                "tariff.periods[0]",
                "str",
                id="period",
            ),
        ],
    )
    def test_non_mapping_tariff_or_period_is_refused_naming_it(
        self, block: Any, block_path: str, type_name: str
    ) -> None:
        """A tariff or custom period that is not a mapping is refused, naming it; only None means no tariff."""
        with pytest.raises(
            ConfigurationError, match=re.escape(f"{block_path} must be a mapping, got {type_name}")
        ):
            parse_tariff_config(block)

    @pytest.mark.parametrize(
        ("load", "document", "block_path"),
        [
            pytest.param(
                load_home_config, {"home": {"tariff": _MISKEYED_ECONOMY_7}}, "home.tariff", id="home"
            ),
            pytest.param(
                load_fleet_config,
                {"homes": [{"pv": {"capacity_kw": 4.0}, "tariff": _MISKEYED_ECONOMY_7}]},
                "homes[0].tariff",
                id="fleet-homes",
            ),
            pytest.param(
                load_scenarios,
                {**_SCENARIO, "tariff_config": _MISKEYED_ECONOMY_7},
                "tariff_config",
                id="scenario",
            ),
            pytest.param(
                load_fleet_config,
                {
                    "fleet_distribution": {"n_homes": 1, "pv": {"capacity_kw": 4.0}},
                    "tariff": _MISKEYED_ECONOMY_7,
                },
                "tariff",
                id="fleet_distribution",
            ),
            pytest.param(
                load_community_config,
                {"community": {"sharing_mode": "p2p", "billing": {"tariff": _MISKEYED_ECONOMY_7}}},
                "community.billing.tariff",
                id="community-billing",
            ),
        ],
    )
    def test_tariff_path_names_where_the_block_sits(
        self,
        tmp_path: Path,
        load: Callable[[Path], object],
        document: dict[str, Any],
        block_path: str,
    ) -> None:
        """A tariff refusal names the block's path wherever the block sits in its file."""
        with pytest.raises(ConfigurationError, match=_refusal(block_path, "rate_per_kwh")):
            load(_write(tmp_path, document))

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            pytest.param(
                {"type": "flat_rate", "rate_per_kwh": 0.28, "name": "Flat"},
                TariffConfig.flat_rate(rate_per_kwh=0.28, name="Flat"),
                id="flat_rate",
            ),
            pytest.param(
                {"type": "economy_7", **_ECONOMY_7_OVERRIDES},
                TariffConfig.economy_7(**_ECONOMY_7_OVERRIDES),
                id="economy_7",
            ),
            pytest.param(
                {"type": "economy_10", **_ECONOMY_10_OVERRIDES},
                TariffConfig.economy_10(**_ECONOMY_10_OVERRIDES),
                id="economy_10",
            ),
            pytest.param(
                {
                    "type": "custom",
                    "name": "Two-rate",
                    "periods": [{**_NIGHT, "name": "Night"}, {**_DAY, "name": "Day"}],
                },
                TariffConfig(
                    periods=(TariffPeriod(**_NIGHT, name="Night"), TariffPeriod(**_DAY, name="Day")),
                    name="Two-rate",
                ),
                id="custom",
            ),
        ],
    )
    def test_every_key_of_each_type_is_accepted(
        self, block: dict[str, Any], expected: TariffConfig
    ) -> None:
        """A block setting every key its type reads parses to the TariffConfig built from those values."""
        assert parse_tariff_config(block) == expected


class TestFleetDistributionBlockKeys:
    """A fleet_distribution: block, its component blocks and their distribution specs refuse a key their parser does not read."""

    _ONLY_7KW_CHARGERS: dict[str, Any] = {"type": "weighted_discrete", "values": ["7kW"], "weights": [1]}

    @pytest.mark.parametrize(
        ("sections", "block_path", "key"),
        [
            pytest.param({"homes_count": 5}, "fleet_distribution", "homes_count", id="fleet_distribution"),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "orientation": 180}},
                "fleet_distribution.pv",
                "orientation",
                id="pv",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "power_kw": 2.5}},
                "fleet_distribution.battery",
                "power_kw",
                id="battery",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "grid_charging": {"target": 0.8}}},
                "fleet_distribution.battery.grid_charging",
                "target",
                id="grid_charging",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": 3400, "occupants": 3}},
                "fleet_distribution.load",
                "occupants",
                id="load",
            ),
            pytest.param(
                {"heat_pump": {"heat_pump_type": "ASHP", "capacity_kw": 8.0}},
                "fleet_distribution.heat_pump",
                "capacity_kw",
                id="heat_pump",
            ),
            pytest.param(
                {"ev": {"charger_type": _ONLY_7KW_CHARGERS, "arrival": 18}},
                "fleet_distribution.ev",
                "arrival",
                id="ev",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0, "minimum": 2.0}}},
                "fleet_distribution.pv.capacity_kw",
                "minimum",
                id="normal",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 5.0, "mean": 4.0}}},
                "fleet_distribution.pv.capacity_kw",
                "mean",
                id="uniform",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "weighted_discrete",
                            "values": [3.0, 4.0],
                            "weights": [1, 1],
                            "counts": [1, 1],
                        }
                    }
                },
                "fleet_distribution.pv.capacity_kw",
                "counts",
                id="weighted_discrete",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "shuffled_pool",
                            "values": [4.0],
                            "counts": [1],
                            "weights": [1],
                        }
                    }
                },
                "fleet_distribution.pv.capacity_kw",
                "weights",
                id="shuffled_pool",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "fixed", "value": 4.0, "values": [4.0]}}},
                "fleet_distribution.pv.capacity_kw",
                "values",
                id="fixed",
            ),
            pytest.param(
                {
                    "battery": {
                        "capacity_kwh": {
                            "type": "proportional_to",
                            "source": "pv.capacity_kw",
                            "factor": 2.0,
                        }
                    }
                },
                "fleet_distribution.battery.capacity_kwh",
                "factor",
                id="proportional_to",
            ),
            pytest.param(
                {
                    "battery": {
                        "capacity_kwh": {
                            "type": "proportional_to",
                            "source": "pv.capacity_kw",
                            "multiplier": {"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3, "step": 1},
                        }
                    }
                },
                "fleet_distribution.battery.capacity_kwh.multiplier",
                "step",
                id="sweep-multiplier",
            ),
        ],
    )
    def test_unrecognised_key_is_refused_naming_its_block(
        self, sections: dict[str, Any], block_path: str, key: str
    ) -> None:
        """A key outside a block's or distribution spec's grammar is refused, naming its path and the key."""
        with pytest.raises(ConfigurationError, match=_refusal(block_path, key)):
            _parsed_fleet_distribution(**sections)

    def test_block_setting_every_recognised_key_is_accepted(self) -> None:
        """A block setting every key of every component block, with a spec of each distribution type, parses to the FleetDistributionConfig built from those values."""
        fleet_distribution: dict[str, Any] = {
            "n_homes": 2,
            "seed": 42,
            "random_order": "bristol_legacy",
            "dispatch_strategy": "tou_optimized",
            "pv": {
                "capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0, "min": 2.0, "max": 6.0},
                "azimuth": {"type": "uniform", "min": 170.0, "max": 190.0},
                "tilt": {"type": "fixed", "value": 30.0},
                "module_efficiency": {"type": "weighted_discrete", "values": [0.2, 0.22], "weights": [3, 1]},
                "inverter_efficiency": 0.97,
                "system_age_years": 1.0,
                "degradation_rate_per_year": 0.006,
            },
            "battery": {
                "capacity_kwh": {
                    "type": "proportional_to",
                    "source": "pv.capacity_kw",
                    "multiplier": {"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3, "mode": "linear"},
                    "offset": 0.5,
                },
                "max_charge_kw": {"type": "shuffled_pool", "values": [2.5, 3.0], "counts": [1, 1]},
                "max_discharge_kw": 3.0,
                "grid_charging": {"target_soc_fraction": 0.8},
            },
            "load": {"annual_consumption_kwh": 3400.0, "household_occupants": 2, "use_stochastic": False},
            "heat_pump": {"heat_pump_type": "GSHP", "thermal_capacity_kw": 6.0, "annual_heat_demand_kwh": 9000.0},
            "ev": {
                "charger_type": self._ONLY_7KW_CHARGERS,
                "arrival_hour": 19,
                "departure_hour": 6,
                "required_charge_kwh": 30.0,
                "smart_charging_mode": "solar",
            },
        }

        expected = FleetDistributionConfig(
            n_homes=2,
            pv=PVDistributionConfig(
                capacity_kw=NormalDistribution(mean=4.0, std=1.0, min=2.0, max=6.0),
                azimuth=UniformDistribution(min=170.0, max=190.0),
                tilt=30.0,
                module_efficiency=WeightedDiscreteDistribution(values=(0.2, 0.22), weights=(3.0, 1.0)),
                inverter_efficiency=0.97,
                system_age_years=1.0,
                degradation_rate_per_year=0.006,
            ),
            load=LoadDistributionConfig(
                annual_consumption_kwh=3400.0, household_occupants=2.0, use_stochastic=False
            ),
            battery=BatteryDistributionConfig(
                capacity_kwh=ProportionalDistribution(
                    source="pv.capacity_kw",
                    multiplier=SweepSpec(min=0.5, max=2.0, steps=3, mode="linear"),
                    offset=0.5,
                ),
                max_charge_kw=ShuffledPoolDistribution(values=(2.5, 3.0), counts=(1, 1)),
                max_discharge_kw=3.0,
                grid_charging=GridChargeConfig(target_soc_fraction=0.8),
            ),
            heat_pump=HeatPumpDistributionConfig(
                heat_pump_type="GSHP", thermal_capacity_kw=6.0, annual_heat_demand_kwh=9000.0
            ),
            ev=EVDistributionConfig(
                charger_type=WeightedDiscreteDistribution(values=("7kW",), weights=(1.0,)),
                arrival_hour=19.0,
                departure_hour=6.0,
                required_charge_kwh=30.0,
                smart_charging_mode="solar",
            ),
            seed=42,
            random_order="bristol_legacy",
            dispatch_strategy="tou_optimized",
        )
        assert parse_fleet_distribution_config(fleet_distribution) == expected

    @pytest.mark.parametrize(
        "dispatch_strategy",
        [
            pytest.param("tou-optimised", id="misspelt"),
            pytest.param("", id="empty"),
            pytest.param({"strategy_type": "tou_optimized"}, id="mapping"),
        ],
    )
    def test_dispatch_strategy_outside_the_valid_strategies_is_refused_naming_its_path(
        self, dispatch_strategy: object
    ) -> None:
        """The block parser refuses a dispatch_strategy that names no strategy, so every reader of the block does."""
        with pytest.raises(
            ConfigurationError,
            match=re.escape(f"Invalid fleet_distribution.dispatch_strategy {dispatch_strategy!r};"),
        ):
            _parsed_fleet_distribution(dispatch_strategy=dispatch_strategy)

    def test_every_home_of_every_sweep_point_carries_grid_charging_and_dispatch_strategy(self) -> None:
        """Homes generated from each sweep point of a parsed block, as fleet sweep builds them, carry its dispatch_strategy and battery.grid_charging."""
        sweep = {"type": "sweep", "min": 1.0, "max": 2.0, "steps": 2}
        distribution = _parsed_fleet_distribution(
            dispatch_strategy="tou_optimized",
            battery={
                "capacity_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": sweep},
                "grid_charging": {"target_soc_fraction": 0.8},
            },
        )

        homes = [
            home
            for _, point in expand_sweep_configs(distribution)
            for home in generate_homes_from_distribution(point, Location.bristol())
        ]

        assert [
            (home.dispatch_strategy, home.battery_config and home.battery_config.grid_charging)
            for home in homes
        ] == [("tou_optimized", GridChargeConfig(target_soc_fraction=0.8))] * 2

    @pytest.mark.parametrize(
        ("sections", "block_path", "type_name"),
        [
            pytest.param({"load": None}, "fleet_distribution.load", "NoneType", id="load"),
            pytest.param({"pv": 4.0}, "fleet_distribution.pv", "float", id="pv"),
        ],
    )
    def test_non_mapping_component_block_is_refused_naming_it(
        self, sections: dict[str, Any], block_path: str, type_name: str
    ) -> None:
        """A component block that is not a mapping is refused, naming its path and the type it got."""
        with pytest.raises(
            ConfigurationError, match=re.escape(f"{block_path} must be a mapping, got {type_name}")
        ):
            _parsed_fleet_distribution(**sections)


class TestScenarioFileBlockKeys:
    """The location, period, output, seg, finance and community blocks refuse a key their parser does not read."""

    _MISKEYED_SEG: dict[str, Any] = {"rate_pence_per_kwh": 5.5, "currency": "GBP"}
    _MISKEYED_FINANCE: dict[str, Any] = {"standing_charge_pence_per_day": 60.0, "vat": 0.05}
    _EVENT_WINDOW: dict[str, Any] = {
        "months": [12, 1, 2],
        "weekdays": [0, 1, 2, 3, 4],
        "hours": [17, 18],
        "events_per_year": 10,
        "event_hours": 2.0,
    }

    @pytest.fixture
    def read(self, request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[Any], object]:
        """Read *data* through the public reader the case names: a loader reads it as a file, a parser as a block."""

        def from_file(load: Callable[[Path], object]) -> Callable[[Any], object]:
            return lambda document: load(_write(tmp_path, document))

        readers: dict[str, Callable[[Any], object]] = {
            "load_scenarios": from_file(load_scenarios),
            "load_community_config": from_file(load_community_config),
            "parse_location_block": parse_location_block,
            "parse_seg_rate": parse_seg_rate,
            "parse_finance_config": parse_finance_config,
        }
        return readers[request.param]

    @pytest.mark.parametrize(
        ("read", "data", "block_path", "key"),
        [
            pytest.param(
                "load_scenarios",
                {**_SCENARIO, "location": {"lat": 51.45}},
                "location",
                "lat",
                id="location",
            ),
            pytest.param(
                "parse_location_block",
                {"latitude": 51.45, "lon": -2.58},
                "location",
                "lon",
                id="parse_location_block",
            ),
            pytest.param(
                "load_scenarios",
                {**_SCENARIO, "period": {**_PERIOD, "days": 7}},
                "period",
                "days",
                id="period",
            ),
            pytest.param(
                "load_scenarios",
                {**_SCENARIO, "output": {"csv_path": "out.csv", "format": "csv"}},
                "output",
                "format",
                id="output",
            ),
            pytest.param(
                "load_scenarios",
                {**_SCENARIO, "seg": {"preset": "Octopus", "name": "x"}},
                "seg",
                "name",
                id="seg",
            ),
            pytest.param("parse_seg_rate", _MISKEYED_SEG, "seg", "currency", id="parse_seg_rate"),
            pytest.param(
                "load_community_config",
                {"community": {"sharing_mode": "p2p", "billing": {"seg": _MISKEYED_SEG}}},
                "community.billing.seg",
                "currency",
                id="community-billing-seg",
            ),
            pytest.param(
                "parse_finance_config", _MISKEYED_FINANCE, "finance", "vat", id="parse_finance_config"
            ),
            pytest.param(
                "parse_finance_config",
                {
                    "standing_charge_pence_per_day": 60.0,
                    "grid_services_events": {"band": "central", "events": []},
                },
                "finance.grid_services_events",
                "events",
                id="grid_services_events",
            ),
            pytest.param(
                "parse_finance_config",
                {
                    "standing_charge_pence_per_day": 60.0,
                    "grid_services_events": {
                        "band": "central",
                        "event_windows": [_EVENT_WINDOW, {**_EVENT_WINDOW, "duration": 2}],
                    },
                },
                "finance.grid_services_events.event_windows[1]",
                "duration",
                id="event_window",
            ),
            pytest.param(
                "load_community_config",
                {"community": {"sharing_mode": "p2p", "mode": "p2p"}},
                "community",
                "mode",
                id="community",
            ),
            pytest.param(
                "load_community_config",
                {
                    "community": {
                        "sharing_mode": "p2p",
                        "billing": {"seg_rate_pence_per_kwh": 4.1, "rate": 4.1},
                    }
                },
                "community.billing",
                "rate",
                id="community-billing",
            ),
            pytest.param(
                "load_community_config",
                {
                    "community": {
                        "sharing_mode": "community_battery",
                        "community_battery": {"capacity_kwh": 50.0, "size_kwh": 50.0},
                    }
                },
                "community.community_battery",
                "size_kwh",
                id="community-battery",
            ),
            pytest.param(
                "load_scenarios",
                {**_SCENARIO, "finance": _MISKEYED_FINANCE},
                "finance",
                "vat",
                id="scenario-finance",
            ),
        ],
        indirect=["read"],
    )
    def test_unrecognised_key_is_refused_naming_its_block(
        self, read: Callable[[Any], object], data: Any, block_path: str, key: str
    ) -> None:
        """A key outside a block's grammar is refused, naming the block's path and the key."""
        with pytest.raises(ConfigurationError, match=_refusal(block_path, key)):
            read(data)

    def test_block_paths_carry_the_scenario_prefix(self, tmp_path: Path) -> None:
        """A block of a scenarios: entry is named from the file's top level, through the entry's index."""
        second = {**_SCENARIO, "name": "Second", "period": {**_PERIOD, "days": 7}}
        path = _write(tmp_path, {"scenarios": [_SCENARIO, second]})
        with pytest.raises(ConfigurationError, match=_refusal("scenarios[1].period", "days")):
            load_scenarios(path)

    @pytest.mark.parametrize(
        ("read", "data", "block_path", "type_name"),
        [
            pytest.param(
                "load_scenarios", {**_SCENARIO, "period": "2024"}, "period", "str", id="period"
            ),
            pytest.param("parse_location_block", "bristol", "location", "str", id="location"),
            pytest.param(
                "load_community_config", {"community": "p2p"}, "community", "str", id="community"
            ),
            pytest.param(
                "load_scenarios", {**_SCENARIO, "output": ["csv"]}, "output", "list", id="output"
            ),
        ],
        indirect=["read"],
    )
    def test_non_mapping_block_is_refused_naming_it(
        self, read: Callable[[Any], object], data: Any, block_path: str, type_name: str
    ) -> None:
        """A block that is not a mapping is refused, naming the block's path and the type it got."""
        with pytest.raises(
            ConfigurationError, match=re.escape(f"{block_path} must be a mapping, got {type_name}")
        ):
            read(data)

    def test_every_recognised_key_is_accepted(self, tmp_path: Path) -> None:
        """A scenario setting every key of its location, period, output and finance blocks, and a seg block, parses to the values set."""
        location: dict[str, Any] = {
            "latitude": 52.2,
            "longitude": -1.5,
            "timezone": "Europe/London",
            "altitude": 80.0,
            "name": "Midlands",
        }
        output: dict[str, Any] = {
            "csv_path": "out.csv",
            "include_minute_data": False,
            "include_summary": False,
            "aggregation": "daily",
        }
        grid_services_events: dict[str, Any] = {
            "band": "high",
            "event_windows": [self._EVENT_WINDOW],
            "aggregator_share": 0.1,
            "utilisation_factor": 0.8,
            "availability_gbp_per_kw_per_event": 2.5,
            "utilisation_gbp_per_mwh": 80.0,
        }
        finance: dict[str, Any] = {
            "standing_charge_pence_per_day": 70.0,
            "vat_rate": 0.08,
            "retail_baseline_rate_pence_per_kwh": 28.5,
            "self_consumption_override": 0.70,
            "pv_cost_per_kwp_gbp": 950.0,
            "roof_fit_cost_gbp": 1100.0,
            "battery_cost_per_kwh_gbp": 280.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 200000.0,
            "equity_fraction": 0.60,
            "loan_term_years": 20,
            "loan_rate": 0.065,
            "opex_per_home_per_year_gbp": 140.0,
            "asset_life_years": 25,
            "own_use_rate_pence_per_kwh": 12.0,
            "retained_cash_floor_per_home_per_year_gbp": 30.0,
            "grid_services_income_per_kw_per_year_gbp": 5.0,
            "grid_services_model": "capacity_at_events",
            "grid_services_events": grid_services_events,
        }
        document = {
            **_SCENARIO,
            "location": location,
            "output": output,
            "seg": {"rate_pence_per_kwh": 5.5},
            "finance": finance,
        }

        (scenario,) = load_scenarios(_write(tmp_path, document))

        expected_events = GridServicesEventsConfig(
            **{
                **grid_services_events,
                "event_windows": (
                    EventWindow(
                        months=(12, 1, 2),
                        weekdays=(0, 1, 2, 3, 4),
                        hours=(17, 18),
                        events_per_year=10,
                        event_hours=2.0,
                    ),
                ),
            }
        )
        assert scenario.location == Location(**location)
        assert scenario.period == SimulationPeriod(**_PERIOD)
        assert scenario.output == OutputConfig(**output)
        assert scenario.seg_tariff_pence_per_kwh == 5.5
        assert scenario.finance == FinanceConfig(
            **{**finance, "grid_services_events": expected_events}
        )

    def test_every_recognised_community_key_is_accepted(self, tmp_path: Path) -> None:
        """A community block setting its mode, battery and billing, billed by a tariff and a scalar SEG rate, parses to the CommunityConfig built from those values."""
        community_battery: dict[str, Any] = {
            "capacity_kwh": 50.0,
            "max_charge_kw": 20.0,
            "max_discharge_kw": 20.0,
        }
        community = {
            "sharing_mode": "community_battery",
            "community_battery": community_battery,
            "billing": {
                "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30, "name": "Community"},
                "seg_rate_pence_per_kwh": 4.1,
            },
        }

        expected = CommunityConfig(
            sharing_mode="community_battery",
            community_battery=BatteryConfig(**community_battery),
            billing=CommunityBillingConfig(
                tariff=TariffConfig.flat_rate(rate_per_kwh=0.30, name="Community"),
                seg_rate_pence_per_kwh=4.1,
            ),
        )
        assert load_community_config(_write(tmp_path, {"community": community})) == expected


class TestShippedScenarios:
    """Every shipped scenario and CLI template parses under the refusals."""

    def test_every_shipped_scenario_and_template_parses(
        self, project_root: Path, tmp_path: Path
    ) -> None:
        """Every block of each scenarios/*.yaml file and each ``config template`` output parses."""
        paths = sorted((project_root / "scenarios").glob("*.yaml"))
        assert paths, "no shipped scenarios found"
        for name, template in _CLI_TEMPLATES.items():
            template_path = tmp_path / f"{name}-template.yaml"
            template_path.write_text(template)
            paths.append(template_path)

        refusals: dict[str, str] = {}
        for path in paths:
            try:
                _parse_every_block(path)
            except ConfigurationError as exc:
                refusals[path.name] = str(exc)
        assert refusals == {}
