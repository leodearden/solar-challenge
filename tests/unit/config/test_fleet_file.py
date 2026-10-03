# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for load_fleet_config, on inline fleet files and on the fleet scenarios shipped in scenarios/."""

import json
import re
from pathlib import Path
from typing import Optional

import pytest

from solar_challenge.config import ConfigurationError, DispatchStrategyConfig, load_fleet_config
from solar_challenge.fleet import FleetConfig
from solar_challenge.pv import calculate_degradation_factor


@pytest.fixture
def scenarios_dir(project_root: Path) -> Path:
    """The scenarios/ directory of fleet files shipped with the repository."""
    return project_root / "scenarios"


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

        with pytest.raises(
            ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
        ):
            load_fleet_config(path)


class TestBristolPhase1Scenario:
    """Tests for Bristol Phase 1 scenario (loaded from YAML)."""

    @pytest.fixture
    def bristol_fleet(self, scenarios_dir: Path) -> FleetConfig:
        """Load Bristol Phase 1 from YAML."""
        return load_fleet_config(scenarios_dir / "bristol-phase1.yaml")

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

    def test_reproducible(self, scenarios_dir: Path) -> None:
        """Test that loading from YAML is reproducible (seeded random)."""
        yaml_path = scenarios_dir / "bristol-phase1.yaml"
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

        with pytest.raises(
            ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
        ):
            load_fleet_config(path)

    def test_load_fleet_empty_homes_list_raises(self, tmp_path: Path) -> None:
        """Test that empty homes list raises error."""
        json_content = {"name": "Empty Fleet", "homes": []}
        path = tmp_path / "fleet.json"
        path.write_text(json.dumps(json_content))

        with pytest.raises(ConfigurationError, match="cannot be empty"):
            load_fleet_config(path)


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

    def test_aged_scenario_has_100_homes_all_aged_20(self, scenarios_dir: Path) -> None:
        """Loading bristol-phase1-aged.yaml returns 100 homes each with system_age_years=20.0."""
        aged_path = scenarios_dir / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        assert len(fleet.homes) == 100
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 20.0

    def test_baseline_scenario_has_age_zero(self, scenarios_dir: Path) -> None:
        """Loading bristol-phase1.yaml returns homes with default system_age_years=0.0."""
        baseline_path = scenarios_dir / "bristol-phase1.yaml"
        fleet = load_fleet_config(baseline_path)
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 0.0

    def test_aged_scenario_degradation_factor_is_approx_90pct(self, scenarios_dir: Path) -> None:
        """The aged scenario yields degradation factor ≈ 0.90 (20yr × 0.5%/yr).

        Exercises the signal chain end-to-end at config speed:
          YAML system_age_years=20  →  home.pv_config.system_age_years==20.0
          + default rate 0.005      →  calculate_degradation_factor → 0.90
        This confirms the ≈10% lower aggregate generation claim without
        running a live PVGIS simulation.
        """
        aged_path = scenarios_dir / "bristol-phase1-aged.yaml"
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
        """A fleet YAML with top-level tariff: and battery.grid_charging: threads both to all homes."""
        yaml_content = """
name: Flex Threading Test
fleet_distribution:
  n_homes: 4
  seed: 7
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
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

    def test_fleet_yaml_dispatch_strategy_threaded(self, tmp_path: Path) -> None:
        """fleet_distribution.dispatch_strategy: tou_optimized threads to all homes via load_fleet_config."""
        yaml_content = """
name: Dispatch Strategy Threading Test
fleet_distribution:
  n_homes: 4
  seed: 11
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
  dispatch_strategy: tou_optimized
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert len(fleet.homes) == 4
        for home in fleet.homes:
            assert home.dispatch_strategy == "tou_optimized", (
                "dispatch_strategy should be threaded from YAML to every home"
            )

    def test_fleet_yaml_no_dispatch_strategy_defaults_greedy(self, tmp_path: Path) -> None:
        """fleet YAML without dispatch_strategy key: all homes default to dispatch_strategy='greedy'."""
        yaml_content = """
name: Dispatch Strategy Default Guard
fleet_distribution:
  n_homes: 4
  seed: 22
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        fleet = load_fleet_config(path)
        assert len(fleet.homes) == 4
        for home in fleet.homes:
            assert home.dispatch_strategy == "greedy", (
                "dispatch_strategy must default to 'greedy' when key is absent"
            )

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
  equity_share: 0.20
  capex_per_home_gbp: 3000
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

    def test_fleet_yaml_invalid_dispatch_strategy_raises(self, tmp_path: Path) -> None:
        """A typo in fleet_distribution.dispatch_strategy raises ConfigurationError.

        Catches config errors early rather than silently falling back to
        self-consumption at simulation time (e.g. 'tou-optimised' instead of
        'tou_optimized').
        """
        yaml_content = """
name: Invalid Strategy Test
fleet_distribution:
  n_homes: 2
  seed: 42
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
  dispatch_strategy: tou-optimised
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        with pytest.raises(ConfigurationError, match="tou-optimised"):
            load_fleet_config(path)

    def test_dispatch_strategy_tou_without_tariff_warns(self, tmp_path: Path) -> None:
        """tou_optimized without a tariff block emits a UserWarning.

        Strategy is still threaded to all homes so the config-layer assertion
        passes, but the warning surfaces the tariff omission early rather than
        letting the simulation silently fall back to self-consumption dispatch.
        """
        yaml_content = """
name: TOU No Tariff Warning Test
fleet_distribution:
  n_homes: 2
  seed: 42
  pv:
    capacity_kw: 4.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400
  dispatch_strategy: tou_optimized
"""
        path = tmp_path / "fleet.yaml"
        path.write_text(yaml_content)

        with pytest.warns(UserWarning, match="tou_optimized"):
            fleet = load_fleet_config(path)
        # Strategy is still threaded despite the warning.
        for home in fleet.homes:
            assert home.dispatch_strategy == "tou_optimized"


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
        fleet = self._load_fleet(tmp_path, "{strategy_type: tou_optimized, peak_hours: [[16, 21]]}")

        batteries = [home.battery_config for home in fleet.homes]
        with_battery = [battery for battery in batteries if battery is not None]
        assert len(with_battery) == 2, "premise: the pool gives two homes a battery"
        assert batteries.count(None) == 2, "premise: the pool leaves two homes without a battery"
        for battery in with_battery:
            assert battery.dispatch_strategy == DispatchStrategyConfig(
                "tou_optimized", peak_hours=[(16, 21)]
            )

    def test_a_fleet_battery_block_without_dispatch_strategy_gives_its_batteries_none(
        self, tmp_path: Path
    ) -> None:
        """Pins the default the new key leaves alone; it passes before the key exists too."""
        fleet = self._load_fleet(tmp_path, None)

        with_battery = [home.battery_config for home in fleet.homes if home.battery_config is not None]
        assert len(with_battery) == 2, "premise: the pool gives two homes a battery"
        assert all(battery.dispatch_strategy is None for battery in with_battery)

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
