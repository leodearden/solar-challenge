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
from solar_challenge.config import (
    ConfigurationError,
    DispatchStrategyConfig,
    GridChargeConfig,
    detect_sweep_spec,
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
