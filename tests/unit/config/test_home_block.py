# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a home: block and the battery, pv, heat_pump and ev sub-blocks inside it."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.config import (
    ConfigurationError,
    DispatchStrategyConfig,
    GridChargeConfig,
    load_home_config,
    parse_dispatch_strategy_config,
    parse_home_block,
)
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location


def _parsed_home(**blocks: Any) -> HomeConfig:
    """Parse a ``home:`` block holding only *blocks*, at the Bristol default location."""
    return parse_home_block(blocks, Location.bristol())


class TestDispatchStrategyConfig:
    """Tests for DispatchStrategyConfig class."""

    def test_self_consumption_strategy(self) -> None:
        """Test self-consumption strategy configuration."""
        config = DispatchStrategyConfig(strategy_type="self_consumption")
        assert config.strategy_type == "self_consumption"
        assert config.peak_hours is None
        assert config.import_limit_kw is None

    def test_tou_optimized_strategy(self) -> None:
        """Test TOU optimized strategy configuration."""
        config = DispatchStrategyConfig(
            strategy_type="tou_optimized",
            peak_hours=[(16, 20), (7, 9)],
        )
        assert config.strategy_type == "tou_optimized"
        assert config.peak_hours == [(16, 20), (7, 9)]

    def test_peak_shaving_strategy(self) -> None:
        """Test peak-shaving strategy configuration."""
        config = DispatchStrategyConfig(
            strategy_type="peak_shaving",
            import_limit_kw=5.0,
        )
        assert config.strategy_type == "peak_shaving"
        assert config.import_limit_kw == 5.0

    def test_invalid_strategy_type_raises(self) -> None:
        """Test invalid strategy type raises error."""
        with pytest.raises(ConfigurationError, match="Invalid strategy_type"):
            DispatchStrategyConfig(strategy_type="invalid_strategy")

    def test_tou_without_peak_hours_raises(self) -> None:
        """Test TOU strategy without peak_hours raises error."""
        with pytest.raises(ConfigurationError, match="requires 'peak_hours'"):
            DispatchStrategyConfig(strategy_type="tou_optimized")

    def test_tou_with_invalid_hour_range_raises(self) -> None:
        """Test TOU strategy with invalid hour range raises error."""
        with pytest.raises(ConfigurationError, match="must be in range"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 25)],  # 25 is invalid
            )

    def test_tou_with_negative_hour_raises(self) -> None:
        """Test TOU strategy with negative hour raises error."""
        with pytest.raises(ConfigurationError, match="must be in range"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(-1, 10)],
            )

    def test_tou_with_start_after_end_raises(self) -> None:
        """Test TOU strategy with start_hour >= end_hour raises error."""
        with pytest.raises(ConfigurationError, match="start_hour must be less than"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(20, 16)],
            )

    def test_tou_with_equal_start_end_raises(self) -> None:
        """Test TOU strategy with equal start and end hours raises error."""
        with pytest.raises(ConfigurationError, match="start_hour must be less than"):
            DispatchStrategyConfig(
                strategy_type="tou_optimized",
                peak_hours=[(16, 16)],
            )

    def test_peak_shaving_without_limit_raises(self) -> None:
        """Test peak-shaving strategy without import_limit_kw raises error."""
        with pytest.raises(ConfigurationError, match="requires 'import_limit_kw'"):
            DispatchStrategyConfig(strategy_type="peak_shaving")

    def test_peak_shaving_with_negative_limit_raises(self) -> None:
        """Test peak-shaving strategy with negative limit raises error."""
        with pytest.raises(ConfigurationError, match="must be positive"):
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=-5.0,
            )

    def test_peak_shaving_with_zero_limit_raises(self) -> None:
        """Test peak-shaving strategy with zero limit raises error."""
        with pytest.raises(ConfigurationError, match="must be positive"):
            DispatchStrategyConfig(
                strategy_type="peak_shaving",
                import_limit_kw=0.0,
            )


class TestGridChargeConfig:
    """Tests for GridChargeConfig class."""

    def test_default_target_soc_fraction(self) -> None:
        """GridChargeConfig() default target_soc_fraction is 0.9."""
        config = GridChargeConfig()
        assert config.target_soc_fraction == 0.9

    def test_custom_target_soc_fraction(self) -> None:
        """GridChargeConfig accepts custom target_soc_fraction."""
        config = GridChargeConfig(target_soc_fraction=0.8)
        assert config.target_soc_fraction == 0.8

    def test_boundary_value_one_accepted(self) -> None:
        """GridChargeConfig accepts target_soc_fraction == 1.0."""
        config = GridChargeConfig(target_soc_fraction=1.0)
        assert config.target_soc_fraction == 1.0

    def test_small_positive_value_accepted(self) -> None:
        """GridChargeConfig accepts small positive target_soc_fraction."""
        config = GridChargeConfig(target_soc_fraction=0.01)
        assert config.target_soc_fraction == 0.01

    def test_zero_raises(self) -> None:
        """target_soc_fraction == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=0.0)

    def test_negative_raises(self) -> None:
        """target_soc_fraction < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=-0.1)

    def test_above_one_raises(self) -> None:
        """target_soc_fraction > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="target_soc_fraction"):
            GridChargeConfig(target_soc_fraction=1.5)


class TestBatteryGridChargeParsing:
    """The home battery block's grid_charging support, read through parse_home_block."""

    def test_parse_absent_grid_charging_is_none(self) -> None:
        """Absent grid_charging block -> grid_charging is None."""
        result = _parsed_home(battery={"capacity_kwh": 5.0}).battery_config
        assert result is not None
        assert result.grid_charging is None

    def test_parse_empty_grid_charging_uses_default(self) -> None:
        """Empty grid_charging dict -> default target_soc_fraction == 0.9."""
        result = _parsed_home(
            battery={"capacity_kwh": 5.0, "grid_charging": {}}
        ).battery_config
        assert result is not None
        assert result.grid_charging is not None
        assert result.grid_charging.target_soc_fraction == 0.9

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

    def test_absent_keys_use_defaults(self) -> None:
        """Absent SOC/eff keys yield the correct defaults."""
        result = _parsed_home(battery={"capacity_kwh": 5.0}).battery_config
        assert result is not None
        assert result.min_soc_fraction == 0.1
        assert result.max_soc_fraction == 0.9
        assert result.charge_efficiency == 0.975
        assert result.discharge_efficiency == 0.975
        assert result.efficiency is None

    def test_out_of_range_soc_raises_value_error(self) -> None:
        """Out-of-range SOC fractions propagate as ValueError."""
        with pytest.raises(ValueError, match="SOC"):
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

    def test_absent_soh_keys_use_defaults(self) -> None:
        """Absent SOH keys yield the correct BatteryConfig defaults."""
        result = _parsed_home(battery={"capacity_kwh": 5.0}).battery_config
        assert result is not None
        assert result.system_age_years == 0.0
        assert result.calendar_fade_rate_per_year == 0.02
        assert result.cycle_fade_per_equivalent_full_cycle == 5e-5
        assert result.soh_floor == 0.5
        assert result.soh is None

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


class TestDispatchStrategyParsing:
    """Tests for parse_dispatch_strategy_config function."""

    def test_parse_none(self) -> None:
        """Test parsing None returns None."""
        result = parse_dispatch_strategy_config(None)
        assert result is None

    def test_parse_self_consumption(self) -> None:
        """Test parsing self-consumption strategy."""
        data = {"strategy_type": "self_consumption"}
        result = parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "self_consumption"
        assert result.peak_hours is None
        assert result.import_limit_kw is None

    def test_parse_tou_optimized(self) -> None:
        """Test parsing TOU optimized strategy."""
        data = {
            "strategy_type": "tou_optimized",
            "peak_hours": [[16, 20], [7, 9]],
        }
        result = parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "tou_optimized"
        assert result.peak_hours == [(16, 20), (7, 9)]

    def test_parse_peak_shaving(self) -> None:
        """Test parsing peak-shaving strategy."""
        data = {
            "strategy_type": "peak_shaving",
            "import_limit_kw": 5.0,
        }
        result = parse_dispatch_strategy_config(data)
        assert result is not None
        assert result.strategy_type == "peak_shaving"
        assert result.import_limit_kw == 5.0

    def test_parse_missing_strategy_type_raises(self) -> None:
        """Test parsing without strategy_type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'strategy_type'"):
            parse_dispatch_strategy_config({})

    def test_parse_empty_strategy_type_raises(self) -> None:
        """Test parsing with empty strategy_type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'strategy_type'"):
            parse_dispatch_strategy_config({"strategy_type": ""})

    def test_parse_tou_with_null_peak_hours(self) -> None:
        """Test parsing TOU strategy with null peak_hours raises error."""
        data = {
            "strategy_type": "tou_optimized",
            "peak_hours": None,
        }
        with pytest.raises(ConfigurationError, match="requires 'peak_hours'"):
            parse_dispatch_strategy_config(data)


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


class TestHeatPumpEvBlockErrors:
    """parse_home_block refuses a heat_pump or ev block that lacks a required field, naming the field."""

    def test_heat_pump_missing_heat_pump_type_raises(self) -> None:
        """heat_pump block without heat_pump_type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="heat_pump_type"):
            _parsed_home(heat_pump={"thermal_capacity_kw": 8.0})

    def test_heat_pump_missing_thermal_capacity_raises(self) -> None:
        """heat_pump block without thermal_capacity_kw raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="thermal_capacity_kw"):
            _parsed_home(heat_pump={"heat_pump_type": "ASHP"})

    def test_ev_missing_charger_type_raises(self) -> None:
        """ev block without charger_type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="charger_type"):
            _parsed_home(ev={"arrival_hour": 18})

    def test_ev_missing_arrival_hour_raises(self) -> None:
        """ev block without arrival_hour raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="arrival_hour"):
            _parsed_home(ev={"charger_type": "7kW"})


class TestPVBlockParsing:
    """parse_home_block threads the pv: block's degradation keys through to PVConfig."""

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

    def test_missing_keys_yield_dataclass_defaults(self) -> None:
        """Omitting both keys gives PVConfig defaults (age 0.0, rate 0.005)."""
        data = {"capacity_kw": 4.0}
        pv = _parsed_home(pv=data).pv_config
        assert pv.system_age_years == 0.0
        assert pv.degradation_rate_per_year == 0.005
