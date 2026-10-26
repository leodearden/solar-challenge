# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a home: block and the battery, pv, heat_pump and ev sub-blocks inside it."""

import json
import math
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.config import (
    load_fleet_config,
    load_home_config,
    parse_dispatch_strategy_config,
    parse_home_block,
)
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


def _parsed_home(**blocks: Any) -> HomeConfig:
    """Parse a ``home:`` block holding only *blocks*, at the Bristol default location."""
    return parse_home_block(blocks, Location.bristol())


def _refusal(build: Callable[[], object]) -> tuple[type[BaseException], str]:
    """The type and message of the exception *build* raises."""
    with pytest.raises(Exception) as raised:
        build()
    return type(raised.value), str(raised.value)


class TestBatteryGridChargeParsing:
    """The home battery block's grid_charging support, read through parse_home_block."""

    def test_parse_absent_grid_charging_is_none(self) -> None:
        """Absent grid_charging block -> grid_charging is None."""
        result = _parsed_home(battery={"capacity_kwh": 5.0}).battery_config
        assert result is not None
        assert result.grid_charging is None

    def test_parse_out_of_range_raises(self) -> None:
        """Out-of-range target_soc_fraction propagates ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            _parsed_home(
                battery={
                    "capacity_kwh": 5.0,
                    "grid_charging": {"target_soc_fraction": 1.5},
                }
            )

    @pytest.mark.parametrize(
        ("grid_charging", "type_name"),
        [
            pytest.param(0.8, "float", id="number"),
            pytest.param("not-a-dict", "str", id="string"),
            pytest.param([1, 2], "list", id="list"),
        ],
    )
    def test_parse_grid_charging_non_mapping_raises(
        self, grid_charging: object, type_name: str
    ) -> None:
        """grid_charging supplied as a number, string or list raises ConfigurationError."""
        with pytest.raises(
            ConfigurationError,
            match=f"grid_charging must be a mapping, got {type_name}",
        ):
            _parsed_home(
                battery={"capacity_kwh": 5.0, "grid_charging": grid_charging}
            )

    def test_yaml_round_trip_grid_charging(self, tmp_path: Path) -> None:
        """YAML with battery.grid_charging round-trips into home.battery_config.grid_charging."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    grid_charging:
      target_soc_fraction: 0.8
"""
        path = tmp_path / "home.yaml"
        path.write_text(yaml_content)

        home = load_home_config(path)
        assert home.battery_config is not None
        assert home.battery_config.grid_charging is not None
        assert home.battery_config.grid_charging.target_soc_fraction == 0.8


class TestBatterySOCEfficiencyParsing:
    """Tests for parse_home_block battery SOC + efficiency key forwarding."""

    def test_parse_explicit_soc_and_eff_keys(self) -> None:
        """All five SOC/eff keys are forwarded to BatteryConfig."""
        result = _parsed_home(
            battery={
                "capacity_kwh": 5.0,
                "min_soc_fraction": 0.2,
                "max_soc_fraction": 0.85,
                "charge_efficiency": 0.96,
                "discharge_efficiency": 0.97,
            }
        ).battery_config
        assert result is not None
        assert result.min_soc_fraction == 0.2
        assert result.max_soc_fraction == 0.85
        assert result.charge_efficiency == 0.96
        assert result.discharge_efficiency == 0.97

    def test_out_of_range_soc_raises_value_error(self) -> None:
        """Out-of-range SOC fractions propagate as ValueError."""
        with pytest.raises(
            ValueError,
            match=re.escape(
                "min_soc_fraction must be less than max_soc_fraction, "
                "got min_soc_fraction=0.9 and max_soc_fraction=0.5"
            ),
        ):
            _parsed_home(
                battery={
                    "capacity_kwh": 5.0,
                    "min_soc_fraction": 0.9,
                    "max_soc_fraction": 0.5,
                }
            )

    def test_out_of_range_efficiency_raises_value_error(self) -> None:
        """Out-of-range efficiency propagates as ValueError."""
        with pytest.raises(ValueError, match="[Cc]harge"):
            _parsed_home(battery={"capacity_kwh": 5.0, "charge_efficiency": 0.0})

    def test_yaml_round_trip_efficiency(self, tmp_path: Path) -> None:
        """YAML with battery.efficiency round-trips into home.battery_config.charge_efficiency."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    efficiency: 0.95
"""
        path = tmp_path / "home.yaml"
        path.write_text(yaml_content)

        home = load_home_config(path)
        assert home.battery_config is not None
        assert home.battery_config.efficiency == 0.95
        assert home.battery_config.charge_efficiency == pytest.approx(math.sqrt(0.95))
        assert home.battery_config.discharge_efficiency == pytest.approx(math.sqrt(0.95))

    def test_yaml_round_trip_min_max_soc(self, tmp_path: Path) -> None:
        """YAML with battery.min_soc_fraction/max_soc_fraction round-trips correctly."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    min_soc_fraction: 0.15
    max_soc_fraction: 0.85
"""
        path = tmp_path / "home.yaml"
        path.write_text(yaml_content)

        home = load_home_config(path)
        assert home.battery_config is not None
        assert home.battery_config.min_soc_fraction == 0.15
        assert home.battery_config.max_soc_fraction == 0.85


class TestBatterySOHParsing:
    """Tests for parse_home_block battery SOH/aging key forwarding."""

    def test_parse_explicit_soh_keys(self) -> None:
        """All five SOH keys are forwarded to BatteryConfig."""
        result = _parsed_home(
            battery={
                "capacity_kwh": 5.0,
                "system_age_years": 8.0,
                "calendar_fade_rate_per_year": 0.025,
                "cycle_fade_per_equivalent_full_cycle": 6e-5,
                "soh_floor": 0.6,
                "soh": 0.85,
            }
        ).battery_config
        assert result is not None
        assert result.system_age_years == 8.0
        assert result.calendar_fade_rate_per_year == 0.025
        assert result.cycle_fade_per_equivalent_full_cycle == 6e-5
        assert result.soh_floor == 0.6
        assert result.soh == pytest.approx(0.85)

    def test_yaml_round_trip_system_age_years(self, tmp_path: Path) -> None:
        """YAML with battery.system_age_years round-trips into battery_config.system_age_years."""
        yaml_content = """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
  battery:
    capacity_kwh: 5.0
    system_age_years: 10
"""
        path = tmp_path / "home.yaml"
        path.write_text(yaml_content)

        home = load_home_config(path)
        assert home.battery_config is not None
        assert home.battery_config.system_age_years == 10

    def test_out_of_range_system_age_raises(self) -> None:
        """Negative system_age_years surfaces as ValueError."""
        with pytest.raises(ValueError, match="system_age_years"):
            _parsed_home(battery={"capacity_kwh": 5.0, "system_age_years": -1.0})


class TestOmittedAndNullKeys:
    """A block gives its dataclass only the keys it sets, and so does the home block, to HomeConfig.

    An omitted key takes the dataclass's declared default, or the table's when-omitted value where
    the dataclass declares none, and a key written as null reads as absent; test_component_blocks.py
    sweeps every key of every table. Two nulls are kept gaps, each owned by a task: a null home
    dispatch_strategy is held as None (task 787), and a null grid_charging target_soc_fraction is
    refused by GridChargeConfig itself (task 866).
    """

    def test_omitted_home_keys_take_the_declared_defaults(self) -> None:
        """An empty home block is HomeConfig's declared defaults, its absent pv and load read as empty blocks."""
        assert _parsed_home() == HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            location=Location.bristol(),
        )

    def test_omitted_pv_keys_take_the_declared_defaults(self) -> None:
        """PVConfig declares no capacity, so a pv block omitting capacity_kw is a 4 kW array."""
        assert _parsed_home(pv={}).pv_config == PVConfig(capacity_kw=4.0)

    def test_omitted_battery_keys_take_the_declared_defaults(self) -> None:
        """BatteryConfig declares no capacity, so a battery block omitting capacity_kwh is 5 kWh."""
        assert _parsed_home(battery={}).battery_config == BatteryConfig(capacity_kwh=5.0)

    def test_omitted_load_keys_take_the_declared_defaults(self) -> None:
        """A load block omitting every key is LoadConfig's declared defaults."""
        assert _parsed_home(load={}).load_config == LoadConfig()

    def test_omitted_grid_charging_keys_take_the_declared_defaults(self) -> None:
        """A grid_charging block omitting target_soc_fraction is GridChargeConfig's default."""
        battery = _parsed_home(battery={"capacity_kwh": 5.0, "grid_charging": {}}).battery_config
        assert battery == BatteryConfig(capacity_kwh=5.0, grid_charging=GridChargeConfig())

    @pytest.mark.parametrize(
        ("blocks", "attribute", "expected"),
        [
            pytest.param(
                {"pv": {"tilt": None}}, "pv_config", PVConfig(capacity_kw=4.0, tilt=35.0), id="pv-tilt"
            ),
            pytest.param(
                {"heat_pump": {"heat_pump_type": "ASHP", "annual_heat_demand_kwh": None}},
                "heat_pump_config",
                HeatPumpConfig("ASHP", annual_heat_demand_kwh=8000.0),
                id="heat_pump-annual_heat_demand_kwh",
            ),
        ],
    )
    def test_a_null_key_takes_the_declared_default(
        self, blocks: dict[str, Any], attribute: str, expected: object
    ) -> None:
        """B4: a null tilt is a 35° array and a null annual demand an 8000 kWh heat pump, as if omitted."""
        assert getattr(_parsed_home(**blocks), attribute) == expected

    @pytest.mark.parametrize("key", ["module_efficiency", "temperature_coefficient"])
    def test_a_null_module_setting_is_the_modules_own_as_an_omitted_one_is(self, key: str) -> None:
        """A null module setting reads as absent: PVConfig's declared None, the module's own value."""
        pv_config = _parsed_home(pv={key: None}).pv_config

        assert pv_config == PVConfig(capacity_kw=4.0)
        assert getattr(pv_config, key) is None

    def test_a_null_home_name_reads_as_absent(self) -> None:
        """A null home name takes HomeConfig's declared empty name."""
        assert _parsed_home(name=None).name == ""

    def test_a_null_home_dispatch_strategy_is_held_as_none(self) -> None:
        """Kept gap, task 787's: HomeConfig checks no value, so a null home dispatch_strategy is held as None, not defaulted."""
        assert _parsed_home(dispatch_strategy=None).dispatch_strategy is None

    def test_a_null_grid_charging_target_is_refused_as_constructing_it_refuses_it(self) -> None:
        """Kept gap, task 866's: the null reaches GridChargeConfig, whose refusal names its key but not its block."""
        grid_charging = {"target_soc_fraction": None}

        assert _refusal(lambda: _parsed_home(battery={"grid_charging": grid_charging})) == _refusal(
            lambda: GridChargeConfig(**grid_charging)
        )

    def test_a_bad_dispatch_strategy_is_reported_before_a_bad_grid_charging_block(self) -> None:
        """The battery block reads its dispatch_strategy before its grid_charging, in whatever order the file lists them."""
        battery = {
            "grid_charging": {"target_soc_fraction": 2},
            "dispatch_strategy": {"strategy_type": "nope"},
        }
        with pytest.raises(ConfigurationError, match="strategy_type"):
            _parsed_home(battery=battery)

    def test_a_bad_grid_charging_block_is_reported_before_the_batterys_own_limits(self) -> None:
        """BatteryConfig checks its own limits last: alone, a min_soc_fraction of 0.95 is refused as a ValueError."""
        battery = {"min_soc_fraction": 0.95, "grid_charging": {"target_soc_fraction": 2}}
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            _parsed_home(battery=battery)


_DISPATCH_STRATEGY_PATH = "home.battery.dispatch_strategy"
"""The path parse_home_block names a home battery's dispatch_strategy: block by."""


def _parsed_strategy(block: object) -> object:
    """The dispatch strategy a home battery's dispatch_strategy: block reads as, through parse_home_block."""
    battery_config = _parsed_home(battery={"dispatch_strategy": block}).battery_config
    assert battery_config is not None
    return battery_config.dispatch_strategy


class TestDispatchStrategyParsing:
    """A battery's dispatch_strategy: block reads as the variant its strategy_type names.

    The block's other keys are that variant's fields. A null key another variant reads, as the
    writer before the union wrote every key, reads as absent; any other key the variant does not
    read is refused.
    """

    def test_parse_none(self) -> None:
        """A null block is no strategy."""
        assert parse_dispatch_strategy_config(None) is None

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            pytest.param(
                {"strategy_type": "self_consumption"}, SelfConsumptionStrategyConfig(), id="self_consumption"
            ),
            pytest.param(
                {"strategy_type": "tou_optimized", "peak_hours": [[16, 20], [7, 9]]},
                TOUOptimizedStrategyConfig(((16, 20), (7, 9))),
                id="tou_optimized",
            ),
            pytest.param(
                {"strategy_type": "peak_shaving", "import_limit_kw": 5.0},
                PeakShavingStrategyConfig(5.0),
                id="peak_shaving",
            ),
        ],
    )
    def test_a_block_reads_as_the_variant_its_strategy_type_names(self, block: dict[str, Any], expected: object) -> None:
        """Its peak_hours lists read as tuples, so the variant is a hashable value."""
        strategy = _parsed_strategy(block)

        assert strategy == expected
        assert hash(strategy) == hash(expected)

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            pytest.param(
                {"strategy_type": "self_consumption", "peak_hours": None, "import_limit_kw": None},
                SelfConsumptionStrategyConfig(),
                id="self_consumption",
            ),
            pytest.param(
                {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]], "import_limit_kw": None},
                TOUOptimizedStrategyConfig(((16, 19),)),
                id="tou_optimized",
            ),
            pytest.param(
                {"strategy_type": "peak_shaving", "peak_hours": None, "import_limit_kw": 3.0},
                PeakShavingStrategyConfig(3.0),
                id="peak_shaving",
            ),
        ],
    )
    def test_a_block_the_writer_wrote_before_the_union_reads_as_its_variant(
        self, block: dict[str, Any], expected: object
    ) -> None:
        """That writer wrote all three keys, the ones a strategy does not read null."""
        assert _parsed_strategy(block) == expected

    @pytest.mark.parametrize(
        "block",
        [
            pytest.param({"strategy_type": "tou_optimised"}, id="misspelt"),
            pytest.param({"strategy_type": ""}, id="empty"),
            pytest.param({"strategy_type": 42}, id="number"),
            pytest.param({"strategy_type": ["tou_optimized"]}, id="list"),
            pytest.param({}, id="missing"),
        ],
    )
    def test_a_strategy_type_outside_the_table_is_refused_naming_its_path_and_the_tags(
        self, block: dict[str, Any]
    ) -> None:
        with pytest.raises(ConfigurationError) as raised:
            _parsed_strategy(block)

        message = str(raised.value)
        assert f"{_DISPATCH_STRATEGY_PATH}.strategy_type" in message
        assert repr(block.get("strategy_type")) in message
        assert "['peak_shaving', 'self_consumption', 'tou_optimized']" in message

    @pytest.mark.parametrize(
        ("block", "unrecognised", "recognised"),
        [
            pytest.param(
                {"strategy_type": "self_consumption", "peak_hours": [[16, 19]]},
                "'peak_hours'",
                "strategy_type",
                id="self_consumption-peak_hours",
            ),
            pytest.param(
                {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]], "import_limit_kw": 3.5},
                "'import_limit_kw'",
                "peak_hours, strategy_type",
                id="tou_optimized-import_limit_kw",
            ),
            pytest.param(
                {"strategy_type": "self_consumption", "turbo": None},
                "'turbo'",
                "strategy_type",
                id="a-null-key-no-variant-reads",
            ),
        ],
    )
    def test_a_key_its_variant_does_not_read_is_refused_naming_the_block(
        self, block: dict[str, Any], unrecognised: str, recognised: str
    ) -> None:
        """A key no variant reads is refused even when null: it is a typo, not the old writer's output."""
        expected = f"Unrecognised keys in {_DISPATCH_STRATEGY_PATH}: {unrecognised}; recognised keys: {recognised}"

        with pytest.raises(ConfigurationError, match=re.escape(expected)):
            _parsed_strategy(block)

    @pytest.mark.parametrize(
        ("block", "required_key"),
        [
            pytest.param({"strategy_type": "tou_optimized"}, "peak_hours", id="tou_optimized-absent"),
            pytest.param({"strategy_type": "tou_optimized", "peak_hours": None}, "peak_hours", id="tou_optimized-null"),
            pytest.param({"strategy_type": "peak_shaving"}, "import_limit_kw", id="peak_shaving-absent"),
        ],
    )
    def test_a_required_key_left_out_or_null_is_refused_by_its_path(
        self, block: dict[str, Any], required_key: str
    ) -> None:
        expected = f"Missing required keys in {_DISPATCH_STRATEGY_PATH}: {_DISPATCH_STRATEGY_PATH}.{required_key}"

        with pytest.raises(ConfigurationError, match=re.escape(expected)):
            _parsed_strategy(block)

    def test_a_window_its_variant_refuses_is_refused_as_constructing_the_variant_refuses_it(self) -> None:
        block = {"strategy_type": "tou_optimized", "peak_hours": [[20, 16]]}

        assert _refusal(lambda: _parsed_strategy(block)) == _refusal(lambda: TOUOptimizedStrategyConfig(((20, 16),)))


class TestLoadHomeConfig:
    """Tests for loading home configuration."""

    def test_load_home_config(self, tmp_path: Path) -> None:
        """Test loading home configuration from file."""
        json_content = {
            "home": {
                "pv": {"capacity_kw": 5.0, "tilt": 30},
                "battery": {"capacity_kwh": 10.0},
                "load": {"annual_consumption_kwh": 4000},
            }
        }
        path = tmp_path / "home.json"
        path.write_text(json.dumps(json_content))

        home = load_home_config(path)
        assert home.pv_config.capacity_kw == 5.0
        assert home.pv_config.tilt == 30
        assert home.battery_config is not None
        assert home.battery_config.capacity_kwh == 10.0
        assert home.load_config.annual_consumption_kwh == 4000

    def test_load_home_without_battery(self, tmp_path: Path) -> None:
        """Test loading home without battery."""
        json_content = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400},
        }
        path = tmp_path / "home.json"
        path.write_text(json.dumps(json_content))

        home = load_home_config(path)
        assert home.pv_config.capacity_kw == 4.0
        assert home.battery_config is None

    @pytest.mark.parametrize(
        ("document", "number_read", "expected"),
        [
            pytest.param(
                'home:\n  pv:\n    capacity_kw: "4"\n',
                lambda home: home.pv_config.capacity_kw,
                4.0,
                id="pv",
            ),
            pytest.param(
                'home:\n  battery:\n    capacity_kwh: "5"\n',
                lambda home: home.battery_config.capacity_kwh,
                5.0,
                id="battery",
            ),
            pytest.param(
                'home:\n  load:\n    household_occupants: "2"\n',
                lambda home: home.load_config.household_occupants,
                2,
                id="load",
            ),
            pytest.param(
                'location:\n  latitude: "51.5"\nhome: {}\n',
                lambda home: home.location.latitude,
                51.5,
                id="location",
            ),
        ],
    )
    def test_a_quoted_number_in_a_block_reads_as_that_number(
        self,
        tmp_path: Path,
        document: str,
        number_read: Callable[[HomeConfig], object],
        expected: object,
    ) -> None:
        """A YAML string spelling a number, such as "4", is held as that number in its field's type."""
        path = tmp_path / "home.yaml"
        path.write_text(document, encoding="utf-8")

        number = number_read(load_home_config(path))

        assert number == expected
        assert type(number) is type(expected)


class TestParseHomeBlockHeatPumpEV:
    """Tests that parse_home_block honours heat_pump and ev blocks."""

    def test_parse_home_block_with_heat_pump_and_ev(self) -> None:
        """parse_home_block populates heat_pump_config and ev_config when blocks present."""
        data: dict = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
            "heat_pump": {
                "heat_pump_type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
            "ev": {
                "charger_type": "7kW",
                "arrival_hour": 18,
                "departure_hour": 7,
                "required_charge_kwh": 35,
            },
        }
        result = parse_home_block(data, Location.bristol())

        assert result.heat_pump_config is not None, "heat_pump_config should not be None"
        assert isinstance(result.heat_pump_config, HeatPumpConfig)
        assert result.heat_pump_config.heat_pump_type == "ASHP"
        assert result.heat_pump_config.thermal_capacity_kw == 8.0

        assert result.ev_config is not None, "ev_config should not be None"
        assert isinstance(result.ev_config, EVConfig)
        assert result.ev_config.charger_type == "7kW"
        assert result.ev_config.arrival_hour == 18

    def test_parse_home_block_without_heat_pump_ev_yields_none(self) -> None:
        """parse_home_block backward-compat: absent heat_pump/ev keys yield None."""
        data: dict = {
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        }
        result = parse_home_block(data, Location.bristol())

        assert result.heat_pump_config is None, "heat_pump_config should be None when key absent"
        assert result.ev_config is None, "ev_config should be None when key absent"


class TestHeatPumpEvRequiredAndOmittedKeys:
    """A heat_pump or ev block may leave out every key but its type, which it is refused without, by the key's path."""

    def test_heat_pump_missing_heat_pump_type_raises(self) -> None:
        """heat_pump block without heat_pump_type raises ConfigurationError naming its path."""
        with pytest.raises(ConfigurationError, match=re.escape("home.heat_pump.heat_pump_type")):
            _parsed_home(heat_pump={"thermal_capacity_kw": 8.0})

    def test_ev_missing_charger_type_raises(self) -> None:
        """ev block without charger_type raises ConfigurationError naming its path."""
        with pytest.raises(ConfigurationError, match=re.escape("home.ev.charger_type")):
            _parsed_home(ev={"arrival_hour": 18})

    def test_ev_with_a_null_charger_type_raises(self) -> None:
        """A null charger_type reads as absent, so the block is refused as one without it."""
        with pytest.raises(ConfigurationError, match=re.escape("home.ev.charger_type")):
            _parsed_home(ev={"charger_type": None, "arrival_hour": 18})

    def test_a_fleet_homes_ev_missing_charger_type_raises_naming_the_homes_place(
        self, tmp_path: Path
    ) -> None:
        """Read through load_fleet_config, the path names the home by its place in the homes: list."""
        path = tmp_path / "fleet.json"
        path.write_text(
            json.dumps({
                "homes": [
                    {"pv": {"capacity_kw": 4.0}},
                    {"pv": {"capacity_kw": 4.0}, "ev": {"arrival_hour": 18}},
                ]
            })
        )

        with pytest.raises(ConfigurationError, match=re.escape("homes[1].ev.charger_type")):
            load_fleet_config(path)

    def test_a_heat_pump_block_giving_only_its_type_is_an_8_kw_heat_pump(self) -> None:
        """B4, P10: an omitted thermal_capacity_kw takes HeatPumpConfig's declared 8 kW."""
        heat_pump = _parsed_home(heat_pump={"heat_pump_type": "ASHP"}).heat_pump_config

        assert heat_pump == HeatPumpConfig("ASHP", thermal_capacity_kw=8.0)

    def test_an_ev_block_giving_only_its_charger_type_arrives_at_18(self) -> None:
        """B4, P11: an omitted arrival_hour takes EVConfig's declared 18:00."""
        ev = _parsed_home(ev={"charger_type": "7kW"}).ev_config

        assert ev == EVConfig("7kW", arrival_hour=18)


class TestPVBlockParsing:
    """A home's pv: block's keys reach its PVConfig."""

    def test_explicit_degradation_keys_are_passed_through(self) -> None:
        """system_age_years and degradation_rate_per_year from data reach PVConfig."""
        data = {
            "capacity_kw": 4.0,
            "system_age_years": 15.0,
            "degradation_rate_per_year": 0.008,
        }
        pv = _parsed_home(pv=data).pv_config
        assert pv.system_age_years == 15.0
        assert pv.degradation_rate_per_year == 0.008

    def test_a_home_file_sets_the_system_losses_home_run_simulates_with(self, tmp_path: Path) -> None:
        """B1: a home file's pv: block sets system_losses, the losses `home run` simulates with."""
        path = tmp_path / "home.yaml"
        path.write_text("home:\n  pv:\n    capacity_kw: 4\n    system_losses: 0.05\n", encoding="utf-8")

        assert home_config_for_run(path).pv_config == PVConfig(capacity_kw=4, system_losses=0.05)
