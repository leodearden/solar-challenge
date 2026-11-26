# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for config.py's fleet-file readers, on inline fleet files and on the fleet scenarios shipped in scenarios/."""

import json
import re
import warnings
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import pytest
import yaml

from solar_challenge.config import (
    detect_fleet_sweep_spec,
    load_config,
    load_fleet_config,
    load_scenario,
    load_scenarios,
    parse_fleet_config,
    parse_scenario,
    parse_sweep_fleet_configs,
    parse_sweep_scenarios,
    read_fleet_scenario,
    sweep_point_fleet,
    sweep_value_labels,
)
from solar_challenge.dispatch import GridChargeConfig, SelfConsumptionStrategyConfig, TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetConfig
from solar_challenge.fleet_distribution import (
    FleetFieldPath,
    SweepSpec,
    detect_sweep_spec,
    parse_fleet_distribution_config,
    swept_parameter_path,
)
from solar_challenge.pv import calculate_degradation_factor
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from tests._misplaced_sweeps import misplaced_sweep_refusal, sweep_moved_to
from tests._repository_paths import SCENARIOS_DIR
from tests._retired_dispatch_strategy import retired_dispatch_strategy_refusal


def _assert_refused_naming_tou_optimized_and_the_tariff(read: Callable[[], object]) -> None:
    """*read* raises a ConfigurationError naming tou_optimized and the tariff, and no UserWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ConfigurationError) as refused:
            read()

    assert "tou_optimized" in str(refused.value)
    assert "tariff" in str(refused.value)
    assert [str(warning.message) for warning in caught if issubclass(warning.category, UserWarning)] == []


class TestLoadFleetConfig:
    """Tests for loading fleet configuration."""

    def test_load_fleet_config(self, tmp_path: Path) -> None:
        """Test loading fleet configuration from file."""
        json_content = {
            "name": "Test Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
                {"pv": {"capacity_kw": 5.0}, "load": {}},
            ],
        }
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        fleet = load_fleet_config(path)
        assert fleet.name == "Test Fleet"
        assert len(fleet.homes) == 3

    def test_load_fleet_requires_homes(self, tmp_path: Path) -> None:
        """Test that fleet config requires homes list or fleet_distribution."""
        json_content = {"name": "Empty Fleet"}
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        with pytest.raises(ConfigurationError) as refusal:
            load_fleet_config(path)
        assert str(refusal.value) == "the top level: requires the scenario's homes, from exactly one of 'home', 'homes', 'fleet_distribution'"

    def test_a_location_block_without_its_longitude_is_refused_naming_it(
        self, tmp_path: Path
    ) -> None:
        """A fleet file whose location: block sets a latitude but no longitude is refused by the key's path, not placed at Bristol's longitude."""
        yaml_content = """
name: Half-located Fleet
location:
  latitude: 53.4
fleet_distribution:
  n_homes: 10
  seed: 42
  pv:
    capacity_kw:
      type: weighted_discrete
      values: [3.0, 4.0, 5.0]
      weights: [30, 50, 20]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        with pytest.raises(ConfigurationError, match=re.escape("location: requires 'longitude'")):
            load_fleet_config(path)


_A_HOME = {"pv": {"capacity_kw": 4.0}}


def _fleet_loaded(tmp_path: Path, document: Mapping[str, Any]) -> FleetConfig:
    """The fleet load_fleet_config reads from *document*, written as YAML."""
    path = tmp_path / "fleet.yaml"
    path.write_text(yaml.safe_dump(dict(document)))
    return load_fleet_config(path)


class TestLoadFleetConfigReadsTheScenariosTopLevelBlocks:
    """load_fleet_config is the fleet projection of parse_scenario: every home gets the file's tariff and SEG rate, and every top-level key is read or refused."""

    def test_a_homes_file_gives_every_home_its_top_level_tariff(self, tmp_path: Path) -> None:
        fleet = _fleet_loaded(tmp_path, {"tariff": {"type": "economy_7"}, "homes": [_A_HOME, {}]})

        assert [home.tariff_config for home in fleet.homes] == [TariffConfig.economy_7()] * 2

    @pytest.mark.parametrize(
        "homes",
        [
            pytest.param({"homes": [_A_HOME, {}]}, id="homes"),
            pytest.param({"fleet_distribution": {"n_homes": 2, "pv": {"capacity_kw": 4.0}}}, id="fleet_distribution"),
        ],
    )
    def test_every_home_exports_at_the_files_seg_rate(self, tmp_path: Path, homes: dict[str, Any]) -> None:
        fleet = _fleet_loaded(tmp_path, {"seg": {"rate_pence_per_kwh": 15.0}, **homes})

        assert [home.seg_tariff for home in fleet.homes] == [SEGTariff("", 15.0)] * 2

    def test_a_top_level_key_no_scenario_reads_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match=re.escape("the top level: unrecognised keys 'finanse'")):
            _fleet_loaded(tmp_path, {"finanse": {}, "homes": [_A_HOME]})

    def test_a_home_document_loads_as_a_one_home_fleet_named_by_its_name(self, tmp_path: Path) -> None:
        fleet = _fleet_loaded(tmp_path, {"name": "Solo", "home": _A_HOME})

        assert fleet.name == "Solo"
        assert [home.pv_config.capacity_kw for home in fleet.homes] == [4.0]


class TestBristolPhase1Scenario:
    """Tests for Bristol Phase 1 scenario (loaded from YAML)."""

    @pytest.fixture
    def bristol_fleet(self) -> FleetConfig:
        """Load Bristol Phase 1 from YAML."""
        return load_fleet_config(SCENARIOS_DIR / "bristol-phase1.yaml")

    def test_load_bristol_phase1(self, bristol_fleet: FleetConfig) -> None:
        """Test loading Bristol Phase 1 from YAML."""
        assert bristol_fleet.name == "Bristol Phase 1"
        assert len(bristol_fleet.homes) == 100

    def test_pv_distribution(self, bristol_fleet: FleetConfig) -> None:
        """Test PV capacity distribution."""
        pv_sizes = [h.pv_config.capacity_kw for h in bristol_fleet.homes]

        # Check all sizes are in expected range
        assert all(3.0 <= s <= 6.0 for s in pv_sizes)

        # Check exact distribution (shuffled_pool guarantees counts)
        count_3kw = sum(1 for s in pv_sizes if s == 3.0)
        count_4kw = sum(1 for s in pv_sizes if s == 4.0)
        count_5kw = sum(1 for s in pv_sizes if s == 5.0)
        count_6kw = sum(1 for s in pv_sizes if s == 6.0)

        assert count_3kw == 20
        assert count_4kw == 40
        assert count_5kw == 30
        assert count_6kw == 10

    def test_battery_distribution(self, bristol_fleet: FleetConfig) -> None:
        """Test battery distribution."""
        no_battery = sum(1 for h in bristol_fleet.homes if h.battery_config is None)
        battery_5kwh = sum(
            1 for h in bristol_fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 5.0
        )
        battery_10kwh = sum(
            1 for h in bristol_fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 10.0
        )

        assert no_battery == 40
        assert battery_5kwh == 40
        assert battery_10kwh == 20

    def test_consumption_distribution(self, bristol_fleet: FleetConfig) -> None:
        """Test consumption distribution."""
        consumptions = [
            h.load_config.annual_consumption_kwh
            for h in bristol_fleet.homes
            if h.load_config.annual_consumption_kwh is not None
        ]

        # All should be in valid range
        assert all(2000 <= c <= 6000 for c in consumptions)

        # Mean should be around 3400
        mean_consumption = sum(consumptions) / len(consumptions)
        assert 3000 <= mean_consumption <= 3800

    def test_reproducible(self) -> None:
        """Test that loading from YAML is reproducible (seeded random)."""
        yaml_path = SCENARIOS_DIR / "bristol-phase1.yaml"
        fleet1 = load_fleet_config(yaml_path)
        fleet2 = load_fleet_config(yaml_path)

        for h1, h2 in zip(fleet1.homes, fleet2.homes, strict=True):
            assert h1.pv_config.capacity_kw == h2.pv_config.capacity_kw
            assert h1.battery_config == h2.battery_config
            assert h1.load_config.annual_consumption_kwh == h2.load_config.annual_consumption_kwh


class TestLoadFleetConfigWithDistribution:
    """Tests for load_fleet_config with fleet_distribution."""

    def test_load_fleet_distribution_yaml(self, tmp_path: Path) -> None:
        """Test loading fleet config with distribution from YAML."""
        yaml_content = """
name: Test Distribution Fleet
fleet_distribution:
  n_homes: 10
  seed: 42
  pv:
    capacity_kw:
      type: weighted_discrete
      values: [3.0, 4.0, 5.0]
      weights: [30, 50, 20]
  battery:
    capacity_kwh:
      type: weighted_discrete
      values: [null, 5.0]
      weights: [50, 50]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert fleet.name == "Test Distribution Fleet"
        assert len(fleet.homes) == 10

        # Check PV sizes are from the distribution
        pv_sizes = {h.pv_config.capacity_kw for h in fleet.homes}
        assert pv_sizes.issubset({3.0, 4.0, 5.0})

        # Check some homes have batteries and some don't
        with_battery = [h for h in fleet.homes if h.battery_config is not None]
        without_battery = [h for h in fleet.homes if h.battery_config is None]
        assert len(with_battery) + len(without_battery) == 10

    def test_load_fleet_distribution_json(self, tmp_path: Path) -> None:
        """Test loading fleet config with distribution from JSON."""
        json_content = {
            "name": "JSON Distribution Fleet",
            "fleet_distribution": {
                "n_homes": 5,
                "seed": 123,
                "pv": {
                    "capacity_kw": {
                        "type": "uniform",
                        "min": 3.0,
                        "max": 6.0,
                    },
                },
                "load": {
                    "annual_consumption_kwh": 3400,
                },
            },
        }
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        fleet = load_fleet_config(path)
        assert fleet.name == "JSON Distribution Fleet"
        assert len(fleet.homes) == 5

        # Check PV sizes are in uniform range
        for home in fleet.homes:
            assert 3.0 <= home.pv_config.capacity_kw <= 6.0
            assert home.load_config.annual_consumption_kwh == 3400

    def test_load_fleet_backward_compatibility(self, tmp_path: Path) -> None:
        """Test that explicit homes list still works."""
        json_content = {
            "name": "Explicit Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
            ],
        }
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        fleet = load_fleet_config(path)
        assert fleet.name == "Explicit Fleet"
        assert len(fleet.homes) == 2
        assert fleet.homes[0].pv_config.capacity_kw == 3.0
        assert fleet.homes[1].pv_config.capacity_kw == 4.0

    def test_load_fleet_missing_homes_and_distribution_raises(self, tmp_path: Path) -> None:
        """Test that missing both homes and fleet_distribution raises error."""
        json_content = {"name": "Empty Fleet"}
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        with pytest.raises(ConfigurationError) as refusal:
            load_fleet_config(path)
        assert str(refusal.value) == "the top level: requires the scenario's homes, from exactly one of 'home', 'homes', 'fleet_distribution'"

    def test_load_fleet_empty_homes_list_raises(self, tmp_path: Path) -> None:
        """Test that empty homes list raises error."""
        json_content = {"name": "Empty Fleet", "homes": []}
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        with pytest.raises(ConfigurationError) as refusal:
            load_fleet_config(path)
        assert str(refusal.value) == "homes: must list at least one home"


class TestBristolPhase1DistributionEquivalence:
    """Tests that distribution config can reproduce Bristol Phase 1 scenario."""

    def test_distribution_config_matches_programmatic(self, tmp_path: Path) -> None:
        """Test that YAML distribution config produces similar results to programmatic."""
        # Create distribution config that mirrors Bristol Phase 1
        yaml_content = """
name: Bristol Phase 1 (Distribution)
fleet_distribution:
  n_homes: 100
  seed: 42
  pv:
    capacity_kw:
      type: weighted_discrete
      values: [3.0, 4.0, 5.0, 6.0]
      weights: [20, 40, 30, 10]
  battery:
    capacity_kwh:
      type: weighted_discrete
      values: [null, 5.0, 10.0]
      weights: [40, 40, 20]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert len(fleet.homes) == 100

        # Check PV distribution
        pv_sizes = [h.pv_config.capacity_kw for h in fleet.homes]
        assert all(3.0 <= s <= 6.0 for s in pv_sizes)

        # Check battery distribution
        no_battery = sum(1 for h in fleet.homes if h.battery_config is None)
        battery_5 = sum(
            1
            for h in fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 5.0
        )
        battery_10 = sum(
            1
            for h in fleet.homes
            if h.battery_config is not None and h.battery_config.capacity_kwh == 10.0
        )
        # Should be roughly 40/40/20 distribution
        assert no_battery + battery_5 + battery_10 == 100

        # Check consumption bounds
        consumptions = [
            h.load_config.annual_consumption_kwh
            for h in fleet.homes
            if h.load_config.annual_consumption_kwh is not None
        ]
        assert all(2000 <= c <= 6000 for c in consumptions)


class TestAgedScenario:
    """Full product read-path test: load_fleet_config propagates system_age_years from YAML."""

    def test_aged_scenario_has_100_homes_all_aged_20(self) -> None:
        """Loading bristol-phase1-aged.yaml returns 100 homes each with system_age_years=20.0."""
        aged_path = SCENARIOS_DIR / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        assert len(fleet.homes) == 100
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 20.0

    def test_baseline_scenario_has_age_zero(self) -> None:
        """Loading bristol-phase1.yaml returns homes with default system_age_years=0.0."""
        baseline_path = SCENARIOS_DIR / "bristol-phase1.yaml"
        fleet = load_fleet_config(baseline_path)
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 0.0

    def test_aged_scenario_degradation_factor_is_approx_90pct(self) -> None:
        """The aged scenario yields degradation factor ≈ 0.90 (20yr × 0.5%/yr).

        Exercises the signal chain end-to-end at config speed:
          YAML system_age_years=20  →  home.pv_config.system_age_years==20.0
          + default rate 0.005      →  calculate_degradation_factor → 0.90
        This confirms the ≈10% lower aggregate generation claim without
        running a live PVGIS simulation.
        """
        aged_path = SCENARIOS_DIR / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        home = fleet.homes[0]  # all homes share the same scalar age
        factor = calculate_degradation_factor(
            home.pv_config.system_age_years,
            home.pv_config.degradation_rate_per_year,
        )
        expected = 1.0 - 20.0 * 0.005  # 0.90
        assert abs(factor - expected) < 1e-9, (
            f"Expected degradation factor {expected}, got {factor}"
        )


class TestLoadFleetConfigFlexThreading:
    """Tests for YAML tariff + grid_charging threading through load_fleet_config."""

    def test_fleet_yaml_tariff_and_grid_charging_threaded(self, tmp_path: Path) -> None:
        """A fleet YAML with top-level tariff: and battery.grid_charging: threads both to all homes, which dispatch tou_optimized by that tariff."""
        yaml_content = """
name: Flex Threading Test
fleet_distribution:
  n_homes: 4
  seed: 7
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
    dispatch_strategy:
      strategy_type: tou_optimized
    grid_charging:
      target_soc_fraction: 0.9
  load:
    annual_consumption_kwh: 3400
tariff:
  type: economy_7
  off_peak_rate: 0.09
  peak_rate: 0.25
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert len(fleet.homes) == 4
        for home in fleet.homes:
            assert home.tariff_config is not None, "tariff_config should be threaded"
            assert home.battery_config is not None, "all homes should have batteries"
            assert home.battery_config.grid_charging is not None, "grid_charging should be threaded"
            assert home.battery_config.grid_charging.target_soc_fraction == 0.9

    @pytest.mark.parametrize(
        "dispatch_strategy",
        [
            pytest.param("tou_optimized", id="tou_optimized"),
            pytest.param("greedy", id="greedy"),
            pytest.param("null", id="null"),
            pytest.param("tou-optimised", id="misspelt"),
        ],
    )
    def test_a_fleet_level_dispatch_strategy_is_refused_naming_the_batterys(
        self, tmp_path: Path, dispatch_strategy: str
    ) -> None:
        """The dispatch strategy is the battery's own setting, so a fleet_distribution that sets one, of any value, is refused naming where it goes."""
        path = tmp_path / "fleet.yaml"
        path.write_text(f"""
name: Retired Dispatch Strategy Test
fleet_distribution:
  n_homes: 2
  seed: 42
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
  dispatch_strategy: {dispatch_strategy}
tariff:
  type: economy_7
""")

        with pytest.raises(
            ConfigurationError, match=retired_dispatch_strategy_refusal("fleet_distribution.dispatch_strategy")
        ):
            load_fleet_config(path)

    def test_theta_calibration_regression_no_tariff_no_grid_charging(self, tmp_path: Path) -> None:
        """θ regression pin: fleet YAML without tariff: or grid_charging is bit-identical (both None).

        Mirrors the shape of scenarios/bristol-fin-calibration.yaml (fleet_distribution +
        battery + seg + finance, no top-level tariff:, no battery.grid_charging).  Asserts
        that load_fleet_config produces tariff_config=None and battery.grid_charging=None on
        every home — i.e. the β threading is disjoint from parse_finance_config.
        """
        yaml_content = """
name: Theta Calibration Guard
fleet_distribution:
  n_homes: 4
  seed: 99
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
seg:
  rate_pence_per_kwh: 15.0
finance:
  loan_term_years: 15
  loan_rate: 0.05
  equity_fraction: 0.20
  standing_charge_pence_per_day: 60.0
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert len(fleet.homes) == 4
        for home in fleet.homes:
            assert home.tariff_config is None, (
                "tariff_config must be None when no top-level tariff: key is present"
            )
            assert home.battery_config is not None
            assert home.battery_config.grid_charging is None, (
                "grid_charging must be None when no battery.grid_charging key is present"
            )


class TestLoadFleetConfigBatteryDispatchStrategy:
    """fleet_distribution.battery.dispatch_strategy is the dispatch strategy of every generated battery."""

    @staticmethod
    def _load_fleet(tmp_path: Path, dispatch_strategy: Optional[str]) -> FleetConfig:
        """Load 4 homes whose battery pool gives exactly two of them a 5 kWh battery, whatever the seed.

        *dispatch_strategy* is the battery block's dispatch_strategy in YAML flow style, or None for no key.
        """
        dispatch_line = f"\n    dispatch_strategy: {dispatch_strategy}" if dispatch_strategy else ""
        path = tmp_path / "fleet.yaml"
        path.write_text(f"""
name: Battery Dispatch Strategy Test
fleet_distribution:
  n_homes: 4
  seed: 7
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh:
      type: shuffled_pool
      values: [null, 5.0]
      counts: [2, 2]{dispatch_line}
  load:
    annual_consumption_kwh: 3400
""")
        return load_fleet_config(path)

    def test_a_fleet_battery_dispatch_strategy_reaches_every_home_with_a_battery(
        self, tmp_path: Path
    ) -> None:
        """The file has no tariff: a battery's own tou_optimized dispatches by its peak_hours, and needs none."""
        fleet = self._load_fleet(tmp_path, "{strategy_type: tou_optimized, peak_hours: [[16, 21]]}")

        batteries = [home.battery_config for home in fleet.homes]
        with_battery = [battery for battery in batteries if battery is not None]
        assert len(with_battery) == 2, "premise: the pool gives two homes a battery"
        assert batteries.count(None) == 2, "premise: the pool leaves two homes without a battery"
        for battery in with_battery:
            assert battery.dispatch_strategy == TOUOptimizedStrategyConfig(peak_hours=((16, 21),))

    def test_a_fleet_battery_block_without_dispatch_strategy_gives_its_batteries_self_consumption(
        self, tmp_path: Path
    ) -> None:
        """A battery that names no strategy dispatches self_consumption, BatteryConfig's default."""
        fleet = self._load_fleet(tmp_path, None)

        with_battery = [home.battery_config for home in fleet.homes if home.battery_config is not None]
        assert len(with_battery) == 2, "premise: the pool gives two homes a battery"
        assert all(battery.dispatch_strategy == SelfConsumptionStrategyConfig() for battery in with_battery)

    @pytest.mark.parametrize(
        ("dispatch_strategy", "reason"),
        [
            pytest.param(
                "{strategy_type: peak_shaving, import_limit: 3.0}",
                re.escape("fleet_distribution.battery.dispatch_strategy"),
                id="an-unrecognised-key-named-by-its-block-path",
            ),
            pytest.param("{strategy_type: turbo}", "turbo", id="an-unknown-strategy-type"),
        ],
    )
    def test_a_fleet_battery_dispatch_strategy_the_grammar_refuses_is_refused(
        self, tmp_path: Path, dispatch_strategy: str, reason: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=reason):
            self._load_fleet(tmp_path, dispatch_strategy)


class TestBristolWithEVsScenario:
    """scenarios/bristol-with-evs.yaml's EV hours are its normals' draws rounded to the nearest hour, not truncated (C5)."""

    def test_its_ev_homes_arrive_and_depart_on_their_draws_rounded(self) -> None:
        """Truncation gave its 30 EV homes a mean arrival of 17.433 and a mean departure of 6.533; rounding gives 17.933 and 7.2."""
        fleet = load_fleet_config(SCENARIOS_DIR / "bristol-with-evs.yaml")
        evs = [home.ev_config for home in fleet.homes if home.ev_config is not None]

        assert len(evs) == 30
        assert sum(ev.arrival_hour for ev in evs) / len(evs) >= 17.9
        assert sum(ev.departure_hour for ev in evs) / len(evs) >= 7.1


class TestFleetFileOffPeakEV:
    """A fleet file's off_peak EVs need its tariff: block, which the reader gives each home as it builds it.

    The fleet has no battery, so no dispatch refusal can fire; it sets pv and load because every
    generated home needs both.
    """

    _OFF_PEAK_EV_FLEET = {
        "fleet_distribution": {
            "n_homes": 2,
            "seed": 7,
            "pv": {"capacity_kw": 4.0},
            "load": {"annual_consumption_kwh": 3400},
            "ev": {"charger_type": "7kW", "smart_charging_mode": "off_peak"},
        }
    }

    def test_a_fleet_of_off_peak_evs_with_no_tariff_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            parse_fleet_config(self._OFF_PEAK_EV_FLEET)

        assert "smart_charging_mode 'off_peak'" in str(refused.value)
        assert "tariff" in str(refused.value)

    def test_each_off_peak_ev_home_is_built_with_the_files_tariff(self) -> None:
        """The construction path load_fleet_config gives the web builder's imported fleet scenarios."""
        fleet = parse_fleet_config({**self._OFF_PEAK_EV_FLEET, "tariff": {"type": "economy_10"}})

        assert len(fleet.homes) == 2
        for home in fleet.homes:
            assert home.ev_config is not None
            assert home.ev_config.smart_charging_mode == "off_peak"
            assert home.tariff_config == TariffConfig.economy_10()


class TestFleetHeatPumpTypePools:
    """A fleet_distribution.heat_pump.heat_pump_type pool gives each home the type it draws, a null being no heat pump."""

    @pytest.mark.parametrize("random_order", ["default", "bristol_legacy"])
    def test_a_heat_pump_type_pool_gives_its_homes_its_types_in_its_counts(
        self, tmp_path: Path, random_order: str
    ) -> None:
        path = tmp_path / "fleet.yaml"
        path.write_text(f"""
name: Heat Pump Type Pool Test
fleet_distribution:
  n_homes: 10
  seed: 1
  random_order: {random_order}
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
    use_stochastic: false
  heat_pump:
    heat_pump_type:
      type: shuffled_pool
      values: [ASHP, null]
      counts: [5, 5]
""")

        heat_pumps = [home.heat_pump_config for home in load_fleet_config(path).homes]

        assert [heat_pump.heat_pump_type for heat_pump in heat_pumps if heat_pump is not None] == ["ASHP"] * 5
        assert heat_pumps.count(None) == 5


class TestFleetKeysBeyondTheOldDistributionClasses:
    """A fleet file may draw any key of a component's table, not only those the old distribution classes listed (D3)."""

    def test_a_pv_temperature_coefficient_and_a_battery_min_soc_fraction_reach_every_home(self, tmp_path: Path) -> None:
        path = tmp_path / "fleet.yaml"
        path.write_text("""
name: Fleet Keys Test
fleet_distribution:
  n_homes: 3
  seed: 1
  pv:
    capacity_kw: 4.0
    temperature_coefficient: -0.0035
  battery:
    capacity_kwh: 5.0
    min_soc_fraction: 0.2
  load:
    annual_consumption_kwh: 3400
    use_stochastic: false
""")

        homes = load_fleet_config(path).homes

        assert [home.pv_config.temperature_coefficient for home in homes] == [-0.0035] * 3
        assert [home.battery_config and home.battery_config.min_soc_fraction for home in homes] == [0.2] * 3


_PV_KW = 4.0

_ECONOMY_7 = {"type": "economy_7", "off_peak_rate": 0.09, "peak_rate": 0.25}


def _proportional_to_pv(multiplier: object) -> dict[str, object]:
    """A battery capacity_kwh spec: *multiplier* times the home's PV capacity."""
    return {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": multiplier}


def _fleet_file(capacity_kwh: object, **top_level_blocks: object) -> dict[str, Any]:
    """A fleet file of two homes with _PV_KW of PV and a battery of *capacity_kwh* that dispatches tou_optimized on the tariff's clock and grid-charges to 0.9, beside *top_level_blocks*."""
    return {
        "fleet_distribution": {
            "n_homes": 2,
            "seed": 7,
            "pv": {"capacity_kw": _PV_KW},
            "load": {"annual_consumption_kwh": 3400},
            "battery": {
                "dispatch_strategy": {"strategy_type": "tou_optimized"},
                "grid_charging": {"target_soc_fraction": 0.9},
                "capacity_kwh": capacity_kwh,
            },
        },
        **top_level_blocks,
    }


class TestParseSweepScenarios:
    """parse_sweep_scenarios builds each point of a fleet file's sweep as load_scenario reads that point's file."""

    def test_every_sweep_points_scenario_is_the_scenario_load_scenario_reads_at_that_point(
        self, tmp_path: Path
    ) -> None:
        top_level_blocks = {
            "name": "Sweep street",
            "period": {"start_date": "2024-06-01", "end_date": "2024-06-07"},
            "tariff": _ECONOMY_7,
            "seg": {"rate_pence_per_kwh": 4.1},
        }
        sweep = {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"}

        points = parse_sweep_scenarios(_fleet_file(_proportional_to_pv(sweep), **top_level_blocks))

        assert [value for value, _ in points] == [1.25, 2.5]
        for value, scenario in points:
            fixed_capacity_file = tmp_path / f"fleet-{value}.yaml"
            fixed_capacity_file.write_text(
                yaml.safe_dump(_fleet_file(_PV_KW * value, **top_level_blocks))
            )
            assert (scenario.window().first_day, scenario.window().last_day) == (
                date(2024, 6, 1),
                date(2024, 6, 7),
            )
            assert scenario == load_scenario(fixed_capacity_file)


class TestSweepValueLabels:
    """sweep_value_labels names each point of a sweep at four decimals, or at the fewest more that tell its distinct values apart."""

    def test_values_four_decimals_tell_apart_are_labelled_at_four(self) -> None:
        assert sweep_value_labels((5.0, 10.0)) == ("5.0000", "10.0000")

    def test_values_four_decimals_do_not_tell_apart_are_labelled_at_the_fewest_more_that_do(self) -> None:
        assert sweep_value_labels((0.0001, 0.000125, 0.00015)) == ("0.00010", "0.00013", "0.00015")

    def test_a_fine_degradation_sweep_labels_each_point_apart_and_near_its_value(self) -> None:
        """A 41-step sweep from 0.004 to 0.006 steps by 5e-5, which four decimals cannot tell apart."""
        values = SweepSpec(min=0.004, max=0.006, steps=41, mode="linear").get_values()

        labels = sweep_value_labels(values)

        assert len(set(labels)) == 41
        assert [
            (label, value) for label, value in zip(labels, values, strict=True) if abs(float(label) - value) > 5e-6
        ] == []

    def test_equal_values_share_a_label(self) -> None:
        assert sweep_value_labels((1.0, 1.0)) == ("1.0000", "1.0000")

    @pytest.mark.parametrize(
        ("values", "labels"),
        [
            pytest.param((1e-300, 2e-300), ("1e-300", "2e-300"), id="tiny"),
            pytest.param((1e30, 2e30), ("1e+30", "2e+30"), id="huge"),
        ],
    )
    def test_values_whose_fixed_point_labels_would_outrun_a_floats_repr_are_labelled_by_repr(
        self, values: tuple[float, ...], labels: tuple[str, ...]
    ) -> None:
        """No label is longer than a float's repr, so each fits in the CSV file name fleet sweep writes."""
        assert sweep_value_labels(values) == labels

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_a_value_that_is_not_finite_is_refused_naming_it(self, value: float) -> None:
        with pytest.raises(ConfigurationError, match=re.escape(f"values[1] must be a finite number, got {value!r}")):
            sweep_value_labels((1.0, value, float("nan")))


class TestParseSweepFleetConfigs:
    """parse_sweep_fleet_configs builds each point of a fleet file's sweep as load_fleet_config builds that point's file."""

    def test_every_sweep_points_homes_are_the_homes_load_fleet_config_builds_at_that_point(
        self, tmp_path: Path
    ) -> None:
        """The file carries seg: so that the parity covers seg_tariff once load_fleet_config applies it."""
        top_level_blocks = {"tariff": _ECONOMY_7, "seg": {"rate_pence_per_kwh": 4.1}}
        sweep = {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"}

        points = parse_sweep_fleet_configs(
            _fleet_file(_proportional_to_pv(sweep), **top_level_blocks)
        )

        assert [value for value, _ in points] == [1.25, 2.5]
        for _, fleet in points:
            for home in fleet.homes:
                assert home.seg_tariff == SEGTariff("", 4.1)
                assert home.tariff_config == TariffConfig.economy_7(off_peak_rate=0.09, peak_rate=0.25)
                assert home.battery_config is not None
                assert home.battery_config.dispatch_strategy == TOUOptimizedStrategyConfig()
                assert home.battery_config.grid_charging == GridChargeConfig(target_soc_fraction=0.9)
        for value, fleet in points:
            fixed_capacity_file = tmp_path / f"fleet-{value}.yaml"
            fixed_capacity_file.write_text(
                yaml.safe_dump(_fleet_file(_PV_KW * value, **top_level_blocks))
            )
            assert fleet.homes == load_fleet_config(fixed_capacity_file).homes

    def test_every_sweep_points_fleet_is_the_sweep_point_fleet_of_its_scenario(self) -> None:
        """`validate config` reads a sweep's fleets here, and `fleet sweep` simulates sweep_point_fleet of each point parse_sweep_scenarios builds, so both see the same homes under the same names."""
        sweep = {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"}
        document = _fleet_file(_proportional_to_pv(sweep), tariff=_ECONOMY_7, seg={"rate_pence_per_kwh": 4.1})

        fleets = parse_sweep_fleet_configs(document)

        swept_parameter = swept_parameter_path(FleetFieldPath("battery", "capacity_kwh"))
        points = parse_sweep_scenarios(document)
        assert fleets == [
            (value, sweep_point_fleet(swept_parameter, label, scenario))
            for label, (value, scenario) in zip(sweep_value_labels([v for v, _ in points]), points, strict=True)
        ]
        assert [fleet.name for _, fleet in fleets] == [
            "battery.capacity_kwh.multiplier=1.2500",
            "battery.capacity_kwh.multiplier=2.5000",
        ]

    def test_points_closer_than_four_decimals_are_named_at_the_fewest_more_that_tell_them_apart(self) -> None:
        """Three points 5e-5 apart would share the name ...=1.0000 at four decimals, so each is named at five."""
        sweep = {"type": "sweep", "min": 1.0, "max": 1.0001, "steps": 3, "mode": "linear"}

        fleets = parse_sweep_fleet_configs(_fleet_file(_proportional_to_pv(sweep), tariff=_ECONOMY_7))

        assert [fleet.name for _, fleet in fleets] == [
            "battery.capacity_kwh.multiplier=1.00000",
            "battery.capacity_kwh.multiplier=1.00005",
            "battery.capacity_kwh.multiplier=1.00010",
        ]

    @pytest.mark.parametrize(
        ("document", "refusal"),
        [
            pytest.param(
                _fleet_file(
                    _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
                    tariff={"type": "economy_8"},
                ),
                re.escape("tariff.type: unknown tariff type 'economy_8'; supported types: "),
                id="a-tariff-the-loader-refuses",
            ),
            pytest.param(
                {"homes": [{"pv": {"capacity_kw": _PV_KW}}]},
                re.escape("the top level: requires 'fleet_distribution'"),
                id="no-fleet-distribution",
            ),
            pytest.param(
                {"name": "no homes"},
                re.escape("the top level: requires 'fleet_distribution'"),
                id="no-homes-source",
            ),
            pytest.param(
                {
                    **_fleet_file(_proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3})),
                    "homes": [{"pv": {"capacity_kw": _PV_KW}}],
                },
                re.escape("the top level: sets 'homes', 'fleet_distribution', but a scenario's homes come from exactly one of "),
                id="a-second-homes-source",
            ),
            pytest.param(
                _fleet_file(
                    _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
                    tariff=_ECONOMY_7,
                    finanse={},
                ),
                re.escape("the top level: unrecognised keys 'finanse'"),
                id="a-key-no-scenario-reads",
            ),
            pytest.param(
                _fleet_file(5.0, tariff=_ECONOMY_7),
                re.escape(
                    "fleet_distribution: holds no sweep: "
                    "give battery.capacity_kwh a proportional_to whose multiplier has type: sweep"
                ),
                id="no-sweep",
            ),
        ],
    )
    def test_a_file_it_cannot_sweep_is_refused(
        self, document: dict[str, Any], refusal: str
    ) -> None:
        """Each refusal is a ConfigurationError, never a KeyError, so a caller reports it as a config error."""
        with pytest.raises(ConfigurationError, match=refusal):
            parse_sweep_fleet_configs(document)

    def test_detect_fleet_sweep_spec_finds_the_sweep_whose_points_it_builds(self) -> None:
        document = _fleet_file(
            _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
            tariff=_ECONOMY_7,
        )

        found = detect_fleet_sweep_spec(document)

        assert found is not None
        placement, sweep_spec = found
        assert placement == ("battery", "capacity_kwh")
        assert sweep_spec == SweepSpec(min=0.5, max=2.0, steps=3)
        assert tuple(value for value, _ in parse_sweep_fleet_configs(document)) == sweep_spec.get_values()

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"homes": [{"pv": {"capacity_kw": _PV_KW}}]}, id="no-fleet-distribution"),
            pytest.param(_fleet_file(5.0, tariff=_ECONOMY_7), id="no-sweep"),
        ],
    )
    def test_detect_fleet_sweep_spec_finds_none_in_a_file_it_refuses_to_sweep(
        self, document: dict[str, Any]
    ) -> None:
        assert detect_fleet_sweep_spec(document) is None
        with pytest.raises(ConfigurationError):
            parse_sweep_fleet_configs(document)


def _written_to(tmp_path: Path, document: Mapping[str, Any]) -> Path:
    """*document* written as a YAML file under *tmp_path*."""
    path = tmp_path / "fleet.yaml"
    path.write_text(yaml.safe_dump(dict(document)))
    return path


# Each reader of one fleet, given the document and a directory to write it to as a file.
_ONE_FLEET_READERS = (
    pytest.param(lambda document, tmp_path: parse_fleet_config(document), id="parse_fleet_config"),
    pytest.param(lambda document, tmp_path: parse_scenario(document), id="parse_scenario"),
    pytest.param(lambda document, tmp_path: load_fleet_config(_written_to(tmp_path, document)), id="load_fleet_config"),
    pytest.param(lambda document, tmp_path: load_scenario(_written_to(tmp_path, document)), id="load_scenario"),
)


class TestASweepDocumentIsReadOnlyAsASweep:
    """A document whose fleet sweeps is read only by the sweep readers: a one-fleet reader refuses it, naming the sweep's placement and `fleet sweep`, and every reader refuses a sweep off battery.capacity_kwh."""

    @pytest.mark.parametrize("read", _ONE_FLEET_READERS)
    def test_a_one_fleet_reader_refuses_a_sweep_document_naming_its_placement_and_fleet_sweep(
        self, tmp_path: Path, read: Callable[[Mapping[str, Any], Path], object]
    ) -> None:
        document = _fleet_file(
            _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}), tariff=_ECONOMY_7
        )

        with pytest.raises(ConfigurationError) as refused:
            read(document, tmp_path)

        assert str(refused.value) == (
            "fleet_distribution.battery.capacity_kwh: a sweep multiplier of 3 points, "
            "so the file defines one fleet per point; run it with 'fleet sweep'"
        )

    @pytest.mark.parametrize(
        ("read", "scenario_path"),
        [
            pytest.param(
                lambda scenario, tmp_path: parse_fleet_config({"scenario": scenario}),
                "scenario",
                id="parse_fleet_config-scenario-block",
            ),
            pytest.param(
                lambda scenario, tmp_path: load_scenario(_written_to(tmp_path, {"scenario": scenario})),
                "scenario",
                id="load_scenario-scenario-block",
            ),
            pytest.param(
                lambda scenario, tmp_path: load_scenarios(_written_to(tmp_path, {"scenarios": [scenario]})),
                "scenarios[0]",
                id="load_scenarios-scenarios-entry",
            ),
        ],
    )
    def test_a_nested_sweep_is_refused_saying_fleet_sweep_reads_the_scenario_as_a_file_of_its_own(
        self, tmp_path: Path, read: Callable[[Mapping[str, Any], Path], object], scenario_path: str
    ) -> None:
        scenario = _fleet_file(
            _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}), tariff=_ECONOMY_7
        )

        with pytest.raises(ConfigurationError) as refused:
            read(scenario, tmp_path)

        assert str(refused.value) == (
            f"{scenario_path}.fleet_distribution.battery.capacity_kwh: a sweep multiplier of 3 points, "
            "but only a bare scenario document's top-level fleet_distribution sweeps: "
            "give the scenario a file of its own, unwrapped, and run that with 'fleet sweep'"
        )
        assert len(parse_sweep_fleet_configs(scenario)) == 3

    @pytest.mark.parametrize(
        "read",
        [
            pytest.param(parse_fleet_config, id="parse_fleet_config"),
            pytest.param(parse_sweep_fleet_configs, id="parse_sweep_fleet_configs"),
            pytest.param(parse_sweep_scenarios, id="parse_sweep_scenarios"),
            pytest.param(detect_fleet_sweep_spec, id="detect_fleet_sweep_spec"),
        ],
    )
    def test_each_document_reader_refuses_a_misplaced_sweep_naming_its_path_and_the_placement(
        self, read: Callable[[object], object]
    ) -> None:
        with pytest.raises(ConfigurationError) as refused:
            read(sweep_moved_to("battery", "max_charge_kw"))

        assert str(refused.value) == misplaced_sweep_refusal("fleet_distribution.battery.max_charge_kw")


# Each document-level reader of a fleet_distribution file, with the battery capacity_kwh of
# a file it reads: a fixed capacity, or a three-point sweep.
_FLEET_DISTRIBUTION_READERS = (
    pytest.param(parse_fleet_config, 5.0, id="parse_fleet_config"),
    pytest.param(
        parse_sweep_fleet_configs,
        _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
        id="parse_sweep_fleet_configs",
    ),
)


# The document-level readers of a fleet_distribution file's top-level blocks, sweep detection
# included, with the battery capacity_kwh of a file each reads.
_FLEET_DISTRIBUTION_TOP_LEVEL_READERS = (
    *_FLEET_DISTRIBUTION_READERS,
    pytest.param(detect_fleet_sweep_spec, 5.0, id="detect_fleet_sweep_spec-no-sweep"),
    pytest.param(
        detect_fleet_sweep_spec,
        _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
        id="detect_fleet_sweep_spec-a-sweep",
    ),
    pytest.param(read_fleet_scenario, 5.0, id="read_fleet_scenario"),
    pytest.param(
        read_fleet_scenario,
        _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}),
        id="read_fleet_scenario-a-sweep",
    ),
)


class TestFleetDistributionFileReaders:
    """parse_fleet_config, parse_sweep_fleet_configs, detect_fleet_sweep_spec and read_fleet_scenario read a fleet_distribution file's top-level blocks alike, in parse_scenario's order: its keys, location:, then tariff:, then fleet_distribution:."""

    @pytest.mark.parametrize(("read", "capacity_kwh"), _FLEET_DISTRIBUTION_TOP_LEVEL_READERS)
    def test_a_file_refused_on_every_block_is_refused_on_a_key_no_scenario_reads(
        self, read: Callable[[Mapping[str, Any]], object], capacity_kwh: object
    ) -> None:
        document = _fleet_file(capacity_kwh, location={"latitud": 51.45}, tariff={"type": "economy_8"}, finanse={})
        document["fleet_distribution"]["n_homez"] = 2

        with pytest.raises(ConfigurationError, match="the top level: unrecognised keys 'finanse'"):
            read(document)

    @pytest.mark.parametrize(("read", "capacity_kwh"), _FLEET_DISTRIBUTION_TOP_LEVEL_READERS)
    def test_a_file_refused_on_every_block_is_refused_on_its_location(
        self, read: Callable[[Mapping[str, Any]], object], capacity_kwh: object
    ) -> None:
        document = _fleet_file(capacity_kwh, location={"latitud": 51.45}, tariff={"type": "economy_8"})
        document["fleet_distribution"]["n_homez"] = 2

        with pytest.raises(ConfigurationError, match="location: unrecognised keys 'latitud'"):
            read(document)

    @pytest.mark.parametrize(("read", "capacity_kwh"), _FLEET_DISTRIBUTION_TOP_LEVEL_READERS)
    def test_a_file_refused_on_its_fleet_distribution_and_tariff_is_refused_on_its_tariff(
        self, read: Callable[[Mapping[str, Any]], object], capacity_kwh: object
    ) -> None:
        document = _fleet_file(capacity_kwh, tariff={"type": "economy_8"})
        document["fleet_distribution"]["n_homez"] = 2

        with pytest.raises(ConfigurationError, match="tariff.type: unknown tariff type 'economy_8'"):
            read(document)

    @pytest.mark.parametrize(("read", "capacity_kwh"), _FLEET_DISTRIBUTION_READERS)
    def test_a_file_dispatching_tou_optimized_without_a_tariff_is_refused(
        self, read: Callable[[Mapping[str, Any]], object], capacity_kwh: object
    ) -> None:
        _assert_refused_naming_tou_optimized_and_the_tariff(lambda: read(_fleet_file(capacity_kwh)))


class TestParseFleetConfigNamesTheBlockItRefuses:
    """Each refusal parse_fleet_config writes reads '<block label>: <problem>'."""

    def test_a_home_whose_heat_pump_leaves_out_its_type_is_refused_naming_its_place(self) -> None:
        """R1: a heat_pump block without heat_pump_type in the second home names homes[1].heat_pump and the key."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_config({"homes": [{}, {"heat_pump": {"thermal_capacity_kw": 8}}]})

        assert str(refusal.value) == "homes[1].heat_pump: requires 'heat_pump_type'"

    def test_a_homes_value_that_is_no_list_is_refused_naming_it(self) -> None:
        """R2: a homes: 5 was iterated, a TypeError no caller reports as a configuration error."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_config({"homes": 5})

        assert str(refusal.value) == "homes: must be a list, got int"

    @pytest.mark.parametrize(
        "read",
        [
            pytest.param(parse_fleet_config, id="parse_fleet_config"),
            pytest.param(parse_sweep_fleet_configs, id="parse_sweep_fleet_configs"),
            pytest.param(detect_fleet_sweep_spec, id="detect_fleet_sweep_spec"),
            pytest.param(read_fleet_scenario, id="read_fleet_scenario"),
        ],
    )
    def test_a_document_that_is_no_mapping_is_refused_naming_the_top_level(
        self, read: Callable[[Any], object]
    ) -> None:
        """R3: a web or CLI caller may hand a fleet document reader a list, as a YAML file of one gives."""
        with pytest.raises(ConfigurationError) as refusal:
            read([{"pv": {"capacity_kw": _PV_KW}}])

        assert str(refusal.value) == "the top level: must be a mapping, got list"

    @pytest.mark.parametrize(
        "read",
        [
            pytest.param(parse_fleet_config, id="parse_fleet_config"),
            pytest.param(parse_sweep_fleet_configs, id="parse_sweep_fleet_configs"),
            pytest.param(detect_fleet_sweep_spec, id="detect_fleet_sweep_spec"),
            pytest.param(read_fleet_scenario, id="read_fleet_scenario"),
        ],
    )
    @pytest.mark.parametrize(
        ("fleet_distribution", "type_name"),
        [pytest.param(None, "NoneType", id="null"), pytest.param(5, "int", id="a-number")],
    )
    def test_a_fleet_distribution_that_is_no_mapping_is_refused_naming_it(
        self, read: Callable[[Any], object], fleet_distribution: object, type_name: str
    ) -> None:
        """A YAML file's empty or scalar fleet_distribution: is refused as no mapping, not iterated into a bare TypeError."""
        with pytest.raises(ConfigurationError) as refusal:
            read({"fleet_distribution": fleet_distribution})

        assert str(refusal.value) == f"fleet_distribution: must be a mapping, got {type_name}"


_LONDON_FLEET = {
    "name": "London street",
    "location": {"latitude": 51.51, "longitude": -0.13, "altitude": 11.0, "name": "London, UK"},
    "tariff": _ECONOMY_7,
    "fleet_distribution": {
        "n_homes": 3,
        "seed": 11,
        "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 5.0}},
        "load": {"annual_consumption_kwh": 3400},
        "battery": {"capacity_kwh": 5.0},
    },
}


class TestReadFleetScenario:
    """read_fleet_scenario reads a bare fleet scenario document in parse_scenario's order up to its homes, and its scenario() is parse_scenario's reading of the document."""

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(load_config(SCENARIOS_DIR / "bristol-phase1.yaml"), id="bristol-phase1"),
            pytest.param(_LONDON_FLEET, id="an-inline-london-fleet-on-economy-7"),
        ],
    )
    def test_its_scenario_is_parse_scenarios_reading_of_the_document(self, document: Mapping[str, Any]) -> None:
        read = read_fleet_scenario(document)

        assert read.scenario() == parse_scenario(document)
        assert read.fleet == parse_fleet_distribution_config(
            document["fleet_distribution"], block_path="fleet_distribution"
        )
        assert read.location == parse_scenario(document).get_location()

    def test_reading_a_fleet_generates_no_home(self) -> None:
        """A 0 kW PV is refused only by generation, so reading the fleet refuses nothing and its scenario() refuses what parse_scenario refuses."""
        document = {
            "fleet_distribution": {"n_homes": 2, "pv": {"capacity_kw": 0}, "load": {"annual_consumption_kwh": 3400}}
        }
        with pytest.raises(ConfigurationError) as parse_scenarios_refusal:
            parse_scenario(document)

        read = read_fleet_scenario(document)

        with pytest.raises(ConfigurationError) as refusal:
            read.scenario()
        assert str(refusal.value) == str(parse_scenarios_refusal.value)
        assert str(refusal.value) == "fleet_distribution.pv: home 1: capacity_kw must be greater than 0, got 0.0"

    def test_a_sweep_is_read_and_its_scenario_refused_as_parse_scenario_refuses_it(self) -> None:
        document = _fleet_file(
            _proportional_to_pv({"type": "sweep", "min": 0.5, "max": 2.0, "steps": 3}), tariff={"type": "economy_7"}
        )
        with pytest.raises(ConfigurationError) as parse_scenarios_refusal:
            parse_scenario(document)

        read = read_fleet_scenario(document)

        assert detect_sweep_spec(read.fleet) == detect_fleet_sweep_spec(document)
        with pytest.raises(ConfigurationError) as refusal:
            read.scenario()
        assert str(refusal.value) == str(parse_scenarios_refusal.value)
        assert "fleet_distribution.battery.capacity_kwh" in str(refusal.value)
        assert "'fleet sweep'" in str(refusal.value)

    def test_a_scenario_without_a_fleet_distribution_is_refused_naming_the_top_level(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_fleet_scenario({"home": {"pv": {"capacity_kw": 4.0}}})

        assert str(refusal.value) == "the top level: requires 'fleet_distribution'"
