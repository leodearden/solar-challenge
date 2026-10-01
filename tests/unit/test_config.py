"""Tests for configuration file support."""

import json
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeAlias

import pandas as pd
import pytest
import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityConfig
from solar_challenge.config import (
    BatteryDistributionConfig,
    ConfigurationError,
    DispatchStrategyConfig,
    FinanceConfig,
    FleetDistributionConfig,
    GridChargeConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    OutputConfig,
    ParameterSweepConfig,
    PVDistributionConfig,
    ScenarioConfig,
    SimulationPeriod,
    UniformDistribution,
    WeightedDiscreteDistribution,
    load_community_config,
    generate_homes_from_distribution,
    load_config,
    load_config_json,
    load_config_yaml,
    load_fleet_config,
    load_home_config,
    load_scenarios,
    parse_dispatch_strategy_config,
    parse_finance_config,
    parse_fleet_distribution_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
    run_parameter_sweep,
)
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, calculate_degradation_factor
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig, TariffPeriod
from solar_challenge.weather import WeatherCache, set_weather_cache
from tests._synthetic_weather import synthetic_june_weather


class TestParameterSweepConfig:
    """Tests for ParameterSweepConfig class."""

    def test_explicit_values(self) -> None:
        """Test sweep with explicit values."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            values=[0, 5, 10, 15],
        )
        assert sweep.get_values() == [0, 5, 10, 15]

    def test_range_with_step(self) -> None:
        """Test sweep with range and step."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            min_value=0,
            max_value=10,
            step=2,
        )
        values = sweep.get_values()
        assert values == [0, 2, 4, 6, 8, 10]

    def test_range_with_n_steps(self) -> None:
        """Test sweep with range and n_steps."""
        sweep = ParameterSweepConfig(
            parameter_name="pv_capacity_kw",
            min_value=2,
            max_value=6,
            n_steps=4,
        )
        values = sweep.get_values()
        assert len(values) == 5
        assert values[0] == 2
        assert values[-1] == 6

    def test_empty_values_raises(self) -> None:
        """Test that empty values list raises error."""
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            ParameterSweepConfig(
                parameter_name="test",
                values=[],
            )

    def test_invalid_range_raises(self) -> None:
        """Test that invalid range raises error."""
        with pytest.raises(ConfigurationError, match="must be less than"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=10,
                max_value=5,
                step=1,
            )

    def test_missing_step_raises(self) -> None:
        """Test that missing step raises error."""
        with pytest.raises(ConfigurationError, match="requires either"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=0,
                max_value=10,
            )


class TestLoadFleetConfig:
    """Tests for loading fleet configuration."""

    def test_load_fleet_config(self) -> None:
        """Test loading fleet configuration from file."""
        json_content = {
            "name": "Test Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
                {"pv": {"capacity_kw": 5.0}, "load": {}},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "Test Fleet"
            assert len(fleet.homes) == 3
        finally:
            path.unlink()

    def test_load_fleet_requires_homes(self) -> None:
        """Test that fleet config requires homes list or fleet_distribution."""
        json_content = {"name": "Empty Fleet"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(
                ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
            ):
                load_fleet_config(path)
        finally:
            path.unlink()


class TestBristolPhase1Scenario:
    """Tests for Bristol Phase 1 scenario (loaded from YAML)."""

    @pytest.fixture
    def bristol_fleet(self) -> "FleetConfig":
        """Load Bristol Phase 1 from YAML."""
        from solar_challenge.fleet import FleetConfig
        yaml_path = Path(__file__).parent.parent.parent / "scenarios" / "bristol-phase1.yaml"
        return load_fleet_config(yaml_path)

    def test_load_bristol_phase1(self, bristol_fleet: "FleetConfig") -> None:
        """Test loading Bristol Phase 1 from YAML."""
        assert bristol_fleet.name == "Bristol Phase 1"
        assert len(bristol_fleet.homes) == 100

    def test_pv_distribution(self, bristol_fleet: "FleetConfig") -> None:
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

    def test_battery_distribution(self, bristol_fleet: "FleetConfig") -> None:
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

    def test_consumption_distribution(self, bristol_fleet: "FleetConfig") -> None:
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
        yaml_path = Path(__file__).parent.parent.parent / "scenarios" / "bristol-phase1.yaml"
        fleet1 = load_fleet_config(yaml_path)
        fleet2 = load_fleet_config(yaml_path)

        for h1, h2 in zip(fleet1.homes, fleet2.homes, strict=True):
            assert h1.pv_config.capacity_kw == h2.pv_config.capacity_kw
            assert h1.battery_config == h2.battery_config
            assert h1.load_config.annual_consumption_kwh == h2.load_config.annual_consumption_kwh


class TestLoadFleetConfigWithDistribution:
    """Tests for load_fleet_config with fleet_distribution."""

    def test_load_fleet_distribution_yaml(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
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
        finally:
            path.unlink()

    def test_load_fleet_distribution_json(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "JSON Distribution Fleet"
            assert len(fleet.homes) == 5

            # Check PV sizes are in uniform range
            for home in fleet.homes:
                assert 3.0 <= home.pv_config.capacity_kw <= 6.0
                assert home.load_config.annual_consumption_kwh == 3400
        finally:
            path.unlink()

    def test_load_fleet_backward_compatibility(self) -> None:
        """Test that explicit homes list still works."""
        json_content = {
            "name": "Explicit Fleet",
            "homes": [
                {"pv": {"capacity_kw": 3.0}, "load": {}},
                {"pv": {"capacity_kw": 4.0}, "load": {}},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert fleet.name == "Explicit Fleet"
            assert len(fleet.homes) == 2
            assert fleet.homes[0].pv_config.capacity_kw == 3.0
            assert fleet.homes[1].pv_config.capacity_kw == 4.0
        finally:
            path.unlink()

    def test_load_fleet_missing_homes_and_distribution_raises(self) -> None:
        """Test that missing both homes and fleet_distribution raises error."""
        json_content = {"name": "Empty Fleet"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(
                ConfigurationError, match="requires either 'homes' list or 'fleet_distribution'"
            ):
                load_fleet_config(path)
        finally:
            path.unlink()

    def test_load_fleet_empty_homes_list_raises(self) -> None:
        """Test that empty homes list raises error."""
        json_content = {"name": "Empty Fleet", "homes": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(json_content, f)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigurationError, match="cannot be empty"):
                load_fleet_config(path)
        finally:
            path.unlink()


class TestBristolPhase1DistributionEquivalence:
    """Tests that distribution config can reproduce Bristol Phase 1 scenario."""

    def test_distribution_config_matches_programmatic(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
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
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# Community config parsing
# ---------------------------------------------------------------------------


LoadCommunityBlock: TypeAlias = Callable[[dict[str, Any]], CommunityConfig | None]


@pytest.fixture
def load_community_block(tmp_path: Path) -> LoadCommunityBlock:
    """Read a ``community:`` block the way the CLI does: from a YAML file, through load_community_config."""
    path = tmp_path / "community.yaml"

    def load(block: dict[str, Any]) -> CommunityConfig | None:
        path.write_text(yaml.safe_dump({"community": block}))
        return load_community_config(path)

    return load


class TestCommunityBlockParsing:
    """The community: block, as load_community_config reads it from a file."""

    def test_minimal_p2p(self, load_community_block: LoadCommunityBlock) -> None:
        """A minimal dict with sharing_mode='p2p' returns a valid CommunityConfig."""
        cfg = load_community_block({"sharing_mode": "p2p"})
        assert isinstance(cfg, CommunityConfig)
        assert cfg.sharing_mode == "p2p"
        assert cfg.community_battery is None
        assert cfg.billing is None

    # ------------------------------------------------------------------
    # community_battery mode + invalid combinations (step-3)
    # ------------------------------------------------------------------

    def test_community_battery_mode_without_battery_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """community_battery mode without a community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block({"sharing_mode": "community_battery"})

    def test_p2p_with_battery_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """p2p + community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "community_battery": {"capacity_kwh": 50.0},
                }
            )

    def test_bogus_mode_raises(self, load_community_block: LoadCommunityBlock) -> None:
        """An unrecognised sharing_mode raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block({"sharing_mode": "bogus"})

    # ------------------------------------------------------------------
    # billing: nested SEG forms (step-7)
    # ------------------------------------------------------------------

    def test_billing_both_scalar_and_seg_block_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """Supplying both seg_rate_pence_per_kwh and seg block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "billing": {
                        "seg_rate_pence_per_kwh": 4.1,
                        "seg": {"preset": "Octopus"},
                    },
                }
            )

    # ------------------------------------------------------------------
    # Amendment: additional robustness tests (reviewer pass)
    # ------------------------------------------------------------------

    def test_billing_seg_non_dict_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """A bare scalar for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "billing": {"seg": 4.1},
                }
            )

    def test_billing_seg_string_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """A bare string for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "billing": {"seg": "Octopus"},
                }
            )

    def test_empty_billing_block_returns_none_billing(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """An empty billing: {} block normalises to billing=None (same as absent key)."""
        cfg = load_community_block({"sharing_mode": "p2p", "billing": {}})
        assert cfg is not None
        assert cfg.billing is None


class TestLoadCommunityConfig:
    """Tests for load_community_config."""

    def test_load_yaml_with_community_block(self) -> None:
        """YAML file with community: block returns a populated CommunityConfig."""
        yaml_content = """\
community:
  sharing_mode: community_battery
  community_battery:
    capacity_kwh: 50.0
    max_charge_kw: 20.0
    max_discharge_kw: 20.0
  billing:
    tariff:
      type: flat_rate
      rate_per_kwh: 0.30
    seg_rate_pence_per_kwh: 4.1
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            cfg = load_community_config(path)
            assert isinstance(cfg, CommunityConfig)
            assert cfg.sharing_mode == "community_battery"
            assert cfg.community_battery is not None
            assert cfg.community_battery.capacity_kwh == pytest.approx(50.0)
            assert cfg.billing is not None
            assert cfg.billing.tariff is not None
            assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(4.1)
        finally:
            path.unlink()

    def test_load_yaml_without_community_block_returns_none(self) -> None:
        """YAML file with no community: key returns None."""
        yaml_content = """\
name: Bristol Phase 1
period:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            result = load_community_config(path)
            assert result is None
        finally:
            path.unlink()

    def test_load_non_dict_yaml_returns_none(self) -> None:
        """A YAML file whose top-level value is a list (not a dict) returns None
        instead of raising AttributeError on .get('community').
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("- item1\n- item2\n")  # top-level list, no community key
            f.flush()
            path = Path(f.name)

        try:
            result = load_community_config(path)
            assert result is None
        finally:
            path.unlink()


class TestCommunityConfigFrozenPicklable:
    """Contract guard: full CommunityConfig object graph is frozen and picklable (step-11)."""

    @pytest.fixture
    def full_community_config(
        self, load_community_block: LoadCommunityBlock
    ) -> CommunityConfig:
        """Return a CommunityConfig that exercises every nested dataclass."""
        cfg = load_community_block(
            {
                "sharing_mode": "community_battery",
                "community_battery": {
                    "capacity_kwh": 50.0,
                    "max_charge_kw": 20.0,
                    "max_discharge_kw": 20.0,
                },
                "billing": {
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
                    "seg_rate_pence_per_kwh": 4.1,
                },
            }
        )
        assert cfg is not None
        return cfg

    def test_picklable_round_trip(self, full_community_config: CommunityConfig) -> None:
        """CommunityConfig (with nested BatteryConfig + CommunityBillingConfig + TariffConfig)
        round-trips through pickle with structural equality."""
        import pickle

        cfg = full_community_config
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg

    def test_frozen_top_level(self, full_community_config: CommunityConfig) -> None:
        """Assigning a new attribute on CommunityConfig raises FrozenInstanceError."""
        import dataclasses

        cfg = full_community_config
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.sharing_mode = "p2p"  # type: ignore[misc]

    def test_frozen_nested_battery(self, full_community_config: CommunityConfig) -> None:
        """BatteryConfig inside CommunityConfig is also frozen."""
        import dataclasses

        cfg = full_community_config
        assert cfg.community_battery is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.community_battery.capacity_kwh = 99.0  # type: ignore[misc]

    def test_frozen_nested_billing(self, full_community_config: CommunityConfig) -> None:
        """CommunityBillingConfig inside CommunityConfig is also frozen."""
        import dataclasses

        cfg = full_community_config
        assert cfg.billing is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.billing.seg_rate_pence_per_kwh = 0.0  # type: ignore[misc]


class TestPVParameterSweepPreservesDegradation:
    """A PV parameter sweep simulates the base home's aged array with only the swept parameter changed."""

    _DAY = "2024-06-21"
    _AGED_ARRAY = PVConfig(
        capacity_kw=4.0,
        system_age_years=20.0,
        degradation_rate_per_year=0.008,
    )
    _LOAD = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)

    @pytest.fixture
    def synthetic_tmy(self, tmp_path: Path) -> Iterator[None]:
        """Serve a clear June day as Bristol's TMY, so the sweep and the reference simulation need no PVGIS call."""
        cache = WeatherCache(cache_dir=tmp_path / "weather")
        cache.put(synthetic_june_weather(self._DAY), "tmy", Location.bristol())
        set_weather_cache(cache)
        yield
        set_weather_cache(None)

    @pytest.mark.usefixtures("synthetic_tmy")
    @pytest.mark.parametrize(
        ("parameter_name", "pv_field", "value"),
        [
            ("pv_capacity_kw", "capacity_kw", 6.0),
            ("pv_tilt", "tilt", 45.0),
            ("pv_azimuth", "azimuth", 90.0),
        ],
    )
    def test_swept_array_keeps_its_age_and_degradation_rate(
        self, parameter_name: str, pv_field: str, value: float
    ) -> None:
        """Generation matches the aged array with *pv_field* set to *value*, so age and rate carried over."""
        period = SimulationPeriod(start_date=self._DAY, end_date=self._DAY)
        scenario = ScenarioConfig(
            name="aged array",
            period=period,
            home=HomeConfig(pv_config=self._AGED_ARRAY, load_config=self._LOAD),
        )

        [point] = run_parameter_sweep(
            scenario, ParameterSweepConfig(parameter_name=parameter_name, values=[value])
        )

        expected = simulate_home(
            HomeConfig(
                pv_config=replace(self._AGED_ARRAY, **{pv_field: value}),
                load_config=self._LOAD,
            ),
            period.get_start_timestamp(),
            period.get_end_timestamp(),
        )
        assert point.parameter_value == value
        assert isinstance(point.results, SimulationResults)
        pd.testing.assert_series_equal(point.results.generation, expected.generation)


class TestAgedScenario:
    """Full product read-path test: load_fleet_config propagates system_age_years from YAML."""

    _SCENARIOS_DIR = Path(__file__).parent.parent.parent / "scenarios"

    def test_aged_scenario_has_100_homes_all_aged_20(self) -> None:
        """Loading bristol-phase1-aged.yaml returns 100 homes each with system_age_years=20.0."""
        aged_path = self._SCENARIOS_DIR / "bristol-phase1-aged.yaml"
        fleet = load_fleet_config(aged_path)
        assert len(fleet.homes) == 100
        for home in fleet.homes:
            assert home.pv_config.system_age_years == 20.0

    def test_baseline_scenario_has_age_zero(self) -> None:
        """Loading bristol-phase1.yaml returns homes with default system_age_years=0.0."""
        baseline_path = self._SCENARIOS_DIR / "bristol-phase1.yaml"
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
        aged_path = self._SCENARIOS_DIR / "bristol-phase1-aged.yaml"
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


# ---------------------------------------------------------------------------
# FinanceConfig tests (step-1: construction + defaults)
# ---------------------------------------------------------------------------


class TestFinanceConfig:
    """Tests for FinanceConfig dataclass construction, defaults, and immutability."""

    def test_construction_with_required_arg(self) -> None:
        """FinanceConfig can be constructed with only standing_charge_pence_per_day."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.standing_charge_pence_per_day == 60.0

    def test_defaults_vat_rate(self) -> None:
        """Default vat_rate is 0.05."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.vat_rate == 0.05

    def test_defaults_retail_baseline_rate(self) -> None:
        """Default retail_baseline_rate_pence_per_kwh is 23.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retail_baseline_rate_pence_per_kwh == 23.0

    def test_defaults_self_consumption_override_is_none(self) -> None:
        """Default self_consumption_override is None."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.self_consumption_override is None

    def test_defaults_pv_cost_per_kwp(self) -> None:
        """Default pv_cost_per_kwp_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.pv_cost_per_kwp_gbp == 1000.0

    def test_defaults_roof_fit_cost(self) -> None:
        """Default roof_fit_cost_gbp is 1000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.roof_fit_cost_gbp == 1000.0

    def test_defaults_battery_cost_per_kwh(self) -> None:
        """Default battery_cost_per_kwh_gbp is 250.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.battery_cost_per_kwh_gbp == 250.0

    def test_defaults_grant_gbp(self) -> None:
        """Default grant_gbp is 250000.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grant_gbp == 250000.0

    def test_defaults_equity_fraction(self) -> None:
        """Default equity_fraction is 0.75."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.equity_fraction == 0.75

    def test_defaults_loan_term_years(self) -> None:
        """Default loan_term_years is 15."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_term_years == 15

    def test_defaults_loan_rate(self) -> None:
        """Default loan_rate is 0.07."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.loan_rate == 0.07

    def test_defaults_opex_per_home_per_year(self) -> None:
        """Default opex_per_home_per_year_gbp is 131.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.opex_per_home_per_year_gbp == 131.0

    def test_defaults_asset_life_years(self) -> None:
        """Default asset_life_years is 25."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.asset_life_years == 25

    def test_defaults_inverter_cost_per_kw_is_zero(self) -> None:
        """Default inverter_cost_per_kw_gbp is 0.0 (opt-in, zero-allowed)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    def test_defaults_own_use_rate_pence_per_kwh(self) -> None:
        """Default own_use_rate_pence_per_kwh is 15.0 (CBS transfer price)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.own_use_rate_pence_per_kwh == 15.0

    def test_defaults_retained_cash_floor_per_home_per_year_gbp(self) -> None:
        """Default retained_cash_floor_per_home_per_year_gbp is 27.0."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 27.0

    def test_defaults_grid_services_income_per_kw_per_year_gbp(self) -> None:
        """Default grid_services_income_per_kw_per_year_gbp is 0.0 (theta-safe seam)."""
        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_frozen_raises_on_assignment(self) -> None:
        """FinanceConfig is frozen: attribute assignment raises FrozenInstanceError."""
        import dataclasses

        fc = FinanceConfig(standing_charge_pence_per_day=60.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fc.vat_rate = 0.20  # type: ignore[misc]

    def test_standing_charge_is_required(self) -> None:
        """standing_charge_pence_per_day has no default; omitting it raises TypeError."""
        with pytest.raises(TypeError):
            FinanceConfig()  # type: ignore[call-arg]

    def test_custom_values_round_trip(self) -> None:
        """All fields can be set to custom values and are retrievable."""
        fc = FinanceConfig(
            standing_charge_pence_per_day=75.0,
            vat_rate=0.20,
            retail_baseline_rate_pence_per_kwh=28.0,
            self_consumption_override=0.80,
            pv_cost_per_kwp_gbp=900.0,
            roof_fit_cost_gbp=1200.0,
            battery_cost_per_kwh_gbp=300.0,
            inverter_cost_per_kw_gbp=200.0,
            grant_gbp=200000.0,
            equity_fraction=0.60,
            loan_term_years=20,
            loan_rate=0.06,
            opex_per_home_per_year_gbp=150.0,
            asset_life_years=25,
            own_use_rate_pence_per_kwh=12.0,
            retained_cash_floor_per_home_per_year_gbp=30.0,
            grid_services_income_per_kw_per_year_gbp=5.0,
        )
        assert fc.standing_charge_pence_per_day == 75.0
        assert fc.vat_rate == 0.20
        assert fc.retail_baseline_rate_pence_per_kwh == 28.0
        assert fc.self_consumption_override == 0.80
        assert fc.pv_cost_per_kwp_gbp == 900.0
        assert fc.roof_fit_cost_gbp == 1200.0
        assert fc.battery_cost_per_kwh_gbp == 300.0
        assert fc.inverter_cost_per_kw_gbp == 200.0
        assert fc.grant_gbp == 200000.0
        assert fc.equity_fraction == 0.60
        assert fc.loan_term_years == 20
        assert fc.loan_rate == 0.06
        assert fc.opex_per_home_per_year_gbp == 150.0
        assert fc.asset_life_years == 25
        assert fc.own_use_rate_pence_per_kwh == 12.0
        assert fc.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert fc.grid_services_income_per_kw_per_year_gbp == 5.0


# ---------------------------------------------------------------------------
# FinanceConfig validation tests (step-3: __post_init__ rejections + acceptances)
# ---------------------------------------------------------------------------


class TestFinanceConfigValidation:
    """Tests for FinanceConfig.__post_init__ validation (raises ConfigurationError)."""

    _BASE = dict(standing_charge_pence_per_day=60.0)

    # ---- vat_rate ----

    def test_vat_rate_too_high_raises(self) -> None:
        """vat_rate > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=2.0)

    def test_vat_rate_negative_raises(self) -> None:
        """vat_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, vat_rate=-0.1)

    def test_vat_rate_zero_ok(self) -> None:
        """vat_rate == 0 is valid (VAT-exempt scenario)."""
        fc = FinanceConfig(**self._BASE, vat_rate=0.0)
        assert fc.vat_rate == 0.0

    def test_vat_rate_one_ok(self) -> None:
        """vat_rate == 1 is valid (100% VAT, boundary)."""
        fc = FinanceConfig(**self._BASE, vat_rate=1.0)
        assert fc.vat_rate == 1.0

    # ---- equity_fraction ----

    def test_equity_fraction_too_high_raises(self) -> None:
        """equity_fraction > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=1.5)

    def test_equity_fraction_negative_raises(self) -> None:
        """equity_fraction < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, equity_fraction=-0.1)

    def test_equity_fraction_zero_ok(self) -> None:
        """equity_fraction == 0 is valid (fully debt-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=0.0)
        assert fc.equity_fraction == 0.0

    def test_equity_fraction_one_ok(self) -> None:
        """equity_fraction == 1 is valid (fully equity-financed)."""
        fc = FinanceConfig(**self._BASE, equity_fraction=1.0)
        assert fc.equity_fraction == 1.0

    # ---- self_consumption_override ----

    def test_self_consumption_override_zero_raises(self) -> None:
        """self_consumption_override == 0 raises ConfigurationError (must be > 0)."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=0.0)

    def test_self_consumption_override_too_high_raises(self) -> None:
        """self_consumption_override > 1 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, self_consumption_override=1.5)

    def test_self_consumption_override_one_ok(self) -> None:
        """self_consumption_override == 1 is valid (100% self-consumed)."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=1.0)
        assert fc.self_consumption_override == 1.0

    def test_self_consumption_override_none_ok(self) -> None:
        """self_consumption_override == None skips override validation."""
        fc = FinanceConfig(**self._BASE, self_consumption_override=None)
        assert fc.self_consumption_override is None

    # ---- loan_term_years ----

    def test_loan_term_years_zero_raises(self) -> None:
        """loan_term_years == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=0)

    def test_loan_term_years_negative_raises(self) -> None:
        """loan_term_years < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_term_years=-1)

    # ---- loan_rate ----

    def test_loan_rate_negative_raises(self) -> None:
        """loan_rate < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, loan_rate=-0.01)

    def test_loan_rate_zero_ok(self) -> None:
        """loan_rate == 0 is valid (interest-free loan)."""
        fc = FinanceConfig(**self._BASE, loan_rate=0.0)
        assert fc.loan_rate == 0.0

    # ---- asset_life_years vs loan_term_years ----

    def test_asset_life_less_than_loan_term_raises(self) -> None:
        """asset_life_years < loan_term_years raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, asset_life_years=10, loan_term_years=15)

    def test_asset_life_equals_loan_term_ok(self) -> None:
        """asset_life_years == loan_term_years is valid (equality allowed)."""
        fc = FinanceConfig(**self._BASE, asset_life_years=15, loan_term_years=15)
        assert fc.asset_life_years == 15

    # ---- cost fields (must be > 0) ----

    def test_standing_charge_zero_raises(self) -> None:
        """standing_charge_pence_per_day == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(standing_charge_pence_per_day=0.0)

    def test_retail_baseline_rate_zero_raises(self) -> None:
        """retail_baseline_rate_pence_per_kwh == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retail_baseline_rate_pence_per_kwh=0.0)

    def test_pv_cost_per_kwp_zero_raises(self) -> None:
        """pv_cost_per_kwp_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, pv_cost_per_kwp_gbp=0.0)

    def test_roof_fit_cost_negative_raises(self) -> None:
        """roof_fit_cost_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, roof_fit_cost_gbp=-1.0)

    def test_battery_cost_per_kwh_zero_raises(self) -> None:
        """battery_cost_per_kwh_gbp == 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, battery_cost_per_kwh_gbp=0.0)

    def test_opex_per_home_per_year_negative_raises(self) -> None:
        """opex_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, opex_per_home_per_year_gbp=-1.0)

    # ---- grant_gbp (must be >= 0) ----

    def test_grant_negative_raises(self) -> None:
        """grant_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grant_gbp=-1.0)

    def test_grant_zero_ok(self) -> None:
        """grant_gbp == 0 is valid (no grant received)."""
        fc = FinanceConfig(**self._BASE, grant_gbp=0.0)
        assert fc.grant_gbp == 0.0

    # ---- inverter_cost_per_kw_gbp (must be >= 0) ----

    def test_inverter_cost_negative_raises(self) -> None:
        """inverter_cost_per_kw_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=-5.0)

    def test_inverter_cost_zero_accepted(self) -> None:
        """inverter_cost_per_kw_gbp == 0.0 is valid (opt-in with zero default)."""
        fc = FinanceConfig(**self._BASE, inverter_cost_per_kw_gbp=0.0)
        assert fc.inverter_cost_per_kw_gbp == 0.0

    # ---- own_use_rate_pence_per_kwh (must be >= 0) ----

    def test_own_use_rate_negative_raises(self) -> None:
        """own_use_rate_pence_per_kwh < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=-1.0)

    def test_own_use_rate_zero_ok(self) -> None:
        """own_use_rate_pence_per_kwh == 0.0 is valid (zero transfer price allowed)."""
        fc = FinanceConfig(**self._BASE, own_use_rate_pence_per_kwh=0.0)
        assert fc.own_use_rate_pence_per_kwh == 0.0

    # ---- retained_cash_floor_per_home_per_year_gbp (must be >= 0) ----

    def test_retained_cash_floor_negative_raises(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=-1.0)

    def test_retained_cash_floor_zero_ok(self) -> None:
        """retained_cash_floor_per_home_per_year_gbp == 0.0 is valid (no floor allowed)."""
        fc = FinanceConfig(**self._BASE, retained_cash_floor_per_home_per_year_gbp=0.0)
        assert fc.retained_cash_floor_per_home_per_year_gbp == 0.0

    # ---- grid_services_income_per_kw_per_year_gbp (must be >= 0) ----

    def test_grid_services_income_negative_raises(self) -> None:
        """grid_services_income_per_kw_per_year_gbp < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=-1.0)

    def test_grid_services_income_zero_ok(self) -> None:
        """grid_services_income_per_kw_per_year_gbp == 0.0 is valid (theta-safe default)."""
        fc = FinanceConfig(**self._BASE, grid_services_income_per_kw_per_year_gbp=0.0)
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0


# ---------------------------------------------------------------------------
# parse_finance_config tests (step-5)
# ---------------------------------------------------------------------------


class TestFinanceConfigParsing:
    """Tests for parse_finance_config parser function."""

    def test_none_returns_none(self) -> None:
        """parse_finance_config(None) returns None (no finance block in YAML)."""
        assert parse_finance_config(None) is None

    def test_minimal_dict_uses_defaults(self) -> None:
        """Dict with only standing_charge_pence_per_day uses all other defaults."""
        result = parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result is not None
        assert result.standing_charge_pence_per_day == 60.0
        assert result.vat_rate == 0.05
        assert result.retail_baseline_rate_pence_per_kwh == 23.0
        assert result.self_consumption_override is None
        assert result.pv_cost_per_kwp_gbp == 1000.0
        assert result.roof_fit_cost_gbp == 1000.0
        assert result.battery_cost_per_kwh_gbp == 250.0
        assert result.inverter_cost_per_kw_gbp == 0.0
        assert result.grant_gbp == 250000.0
        assert result.equity_fraction == 0.75
        assert result.loan_term_years == 15
        assert result.loan_rate == 0.07
        assert result.opex_per_home_per_year_gbp == 131.0
        assert result.asset_life_years == 25
        assert result.own_use_rate_pence_per_kwh == 15.0
        assert result.retained_cash_floor_per_home_per_year_gbp == 27.0
        assert result.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_full_dict_round_trips(self) -> None:
        """All fields supplied in the dict are reflected on the returned FinanceConfig."""
        data = {
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
        }
        result = parse_finance_config(data)
        assert result is not None
        assert result.standing_charge_pence_per_day == 70.0
        assert result.vat_rate == 0.08
        assert result.retail_baseline_rate_pence_per_kwh == 28.5
        assert result.self_consumption_override == 0.70
        assert result.pv_cost_per_kwp_gbp == 950.0
        assert result.roof_fit_cost_gbp == 1100.0
        assert result.battery_cost_per_kwh_gbp == 280.0
        assert result.inverter_cost_per_kw_gbp == 200.0
        assert result.grant_gbp == 200000.0
        assert result.equity_fraction == 0.60
        assert result.loan_term_years == 20
        assert result.loan_rate == 0.065
        assert result.opex_per_home_per_year_gbp == 140.0
        assert result.asset_life_years == 25
        assert result.own_use_rate_pence_per_kwh == 12.0
        assert result.retained_cash_floor_per_home_per_year_gbp == 30.0
        assert result.grid_services_income_per_kw_per_year_gbp == 5.0

    def test_inverter_cost_omission_defaults_zero(self) -> None:
        """Parser with no inverter_cost_per_kw_gbp key returns 0.0 (acceptance guard)."""
        result = parse_finance_config({"standing_charge_pence_per_day": 60.0})
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 0.0

    def test_inverter_cost_key_round_trips(self) -> None:
        """inverter_cost_per_kw_gbp in dict is reflected on the returned FinanceConfig."""
        result = parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": 200.0}
        )
        assert result is not None
        assert result.inverter_cost_per_kw_gbp == 200.0

    def test_negative_inverter_cost_propagates_configuration_error(self) -> None:
        """negative inverter_cost_per_kw_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "inverter_cost_per_kw_gbp": -5.0}
            )

    def test_out_of_range_propagates_configuration_error(self) -> None:
        """An out-of-range field (vat_rate=2.0) raises ConfigurationError via __post_init__."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": 2.0}
            )

    def test_zero_grant_accepted(self) -> None:
        """grant_gbp=0 is accepted by the parser (non-negative allowed)."""
        result = parse_finance_config(
            {"standing_charge_pence_per_day": 60.0, "grant_gbp": 0.0}
        )
        assert result is not None
        assert result.grant_gbp == 0.0

    def test_missing_standing_charge_raises(self) -> None:
        """Finance block without standing_charge_pence_per_day raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="standing_charge_pence_per_day"):
            parse_finance_config({"vat_rate": 0.05})

    def test_int_coercion_of_year_fields(self) -> None:
        """loan_term_years/asset_life_years given as floats in the dict are coerced to int."""
        result = parse_finance_config(
            {
                "standing_charge_pence_per_day": 60.0,
                "loan_term_years": 20.0,
                "asset_life_years": 25.0,
            }
        )
        assert result is not None
        assert result.loan_term_years == 20
        assert isinstance(result.loan_term_years, int)
        assert result.asset_life_years == 25
        assert isinstance(result.asset_life_years, int)

    def test_non_numeric_value_raises_configuration_error(self) -> None:
        """A non-numeric string for a numeric field raises ConfigurationError (not ValueError)."""
        with pytest.raises(ConfigurationError, match="non-numeric"):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "vat_rate": "not-a-number"}
            )

    def test_negative_own_use_rate_propagates_configuration_error(self) -> None:
        """negative own_use_rate_pence_per_kwh in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {"standing_charge_pence_per_day": 60.0, "own_use_rate_pence_per_kwh": -1.0}
            )

    def test_negative_retained_cash_floor_propagates_configuration_error(self) -> None:
        """negative retained_cash_floor_per_home_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "retained_cash_floor_per_home_per_year_gbp": -1.0,
                }
            )

    def test_negative_grid_services_income_propagates_configuration_error(self) -> None:
        """negative grid_services_income_per_kw_per_year_gbp in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config(
                {
                    "standing_charge_pence_per_day": 60.0,
                    "grid_services_income_per_kw_per_year_gbp": -1.0,
                }
            )


# ---------------------------------------------------------------------------
# ScenarioConfig.finance field + load_scenarios round-trip (step-7)
# ---------------------------------------------------------------------------


class TestScenarioFinance:
    """Tests for ScenarioConfig.finance field and _parse_scenario wiring."""

    _MINIMAL_PERIOD = {
        "start_date": "2024-01-01",
        "end_date": "2024-01-07",
    }
    _MINIMAL_HOME = {
        "pv": {"capacity_kw": 4.0},
        "load": {"annual_consumption_kwh": 3400},
    }

    def test_scenario_config_finance_defaults_to_none(self) -> None:
        """ScenarioConfig.finance is None when not provided (constructed directly)."""
        from solar_challenge.home import HomeConfig
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig

        home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
        )
        sc = ScenarioConfig(
            name="test",
            period=SimulationPeriod(**self._MINIMAL_PERIOD),
            home=home,
        )
        assert sc.finance is None

    def test_load_scenarios_with_finance_block_populates_field(self) -> None:
        """YAML with a top-level finance: block → scenarios[0].finance is FinanceConfig."""
        yaml_content = (
            "name: Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  vat_rate: 0.08\n"
            "  self_consumption_override: 0.75\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            fc = scenarios[0].finance
            assert fc is not None
            assert isinstance(fc, FinanceConfig)
            assert fc.standing_charge_pence_per_day == 65.0
            assert fc.vat_rate == 0.08
            assert fc.self_consumption_override == 0.75
            # Un-overridden fields use defaults
            assert fc.loan_term_years == 15
        finally:
            path.unlink()

    def test_load_scenarios_without_finance_block_is_none(self) -> None:
        """YAML without a finance: block → scenarios[0].finance is None."""
        yaml_content = (
            "name: No Finance Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            assert scenarios[0].finance is None
        finally:
            path.unlink()

    def test_load_scenarios_with_cost_recovery_fields_round_trip(self) -> None:
        """YAML finance: block with the three cost-recovery keys round-trips into FinanceConfig."""
        yaml_content = (
            "name: Cost Recovery Test\n"
            "period:\n"
            "  start_date: '2024-01-01'\n"
            "  end_date: '2024-01-07'\n"
            "home:\n"
            "  pv:\n"
            "    capacity_kw: 4.0\n"
            "  load:\n"
            "    annual_consumption_kwh: 3400\n"
            "finance:\n"
            "  standing_charge_pence_per_day: 65.0\n"
            "  own_use_rate_pence_per_kwh: 12.5\n"
            "  retained_cash_floor_per_home_per_year_gbp: 30.0\n"
            "  grid_services_income_per_kw_per_year_gbp: 8.0\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scenarios = load_scenarios(path)
            assert len(scenarios) == 1
            fc = scenarios[0].finance
            assert fc is not None
            assert isinstance(fc, FinanceConfig)
            assert fc.own_use_rate_pence_per_kwh == 12.5
            assert fc.retained_cash_floor_per_home_per_year_gbp == 30.0
            assert fc.grid_services_income_per_kw_per_year_gbp == 8.0
            # Un-overridden fields use documented defaults
            assert fc.loan_term_years == 15
        finally:
            path.unlink()


class TestLoadFleetConfigFlexThreading:
    """Tests for YAML tariff + grid_charging threading through load_fleet_config."""

    def test_fleet_yaml_tariff_and_grid_charging_threaded(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert len(fleet.homes) == 4
            for home in fleet.homes:
                assert home.tariff_config is not None, "tariff_config should be threaded"
                assert home.battery_config is not None, "all homes should have batteries"
                assert home.battery_config.grid_charging is not None, "grid_charging should be threaded"
                assert home.battery_config.grid_charging.target_soc_fraction == 0.9
        finally:
            path.unlink()

    def test_fleet_yaml_dispatch_strategy_threaded(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert len(fleet.homes) == 4
            for home in fleet.homes:
                assert home.dispatch_strategy == "tou_optimized", (
                    "dispatch_strategy should be threaded from YAML to every home"
                )
        finally:
            path.unlink()

    def test_fleet_yaml_no_dispatch_strategy_defaults_greedy(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            fleet = load_fleet_config(path)
            assert len(fleet.homes) == 4
            for home in fleet.homes:
                assert home.dispatch_strategy == "greedy", (
                    "dispatch_strategy must default to 'greedy' when key is absent"
                )
        finally:
            path.unlink()

    def test_theta_calibration_regression_no_tariff_no_grid_charging(self) -> None:
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
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
        finally:
            path.unlink()

    def test_fleet_yaml_invalid_dispatch_strategy_raises(self) -> None:
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigurationError, match="tou-optimised"):
                load_fleet_config(path)
        finally:
            path.unlink()

    def test_dispatch_strategy_tou_without_tariff_warns(self) -> None:
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.warns(UserWarning, match="tou_optimized"):
                fleet = load_fleet_config(path)
            # Strategy is still threaded despite the warning.
            for home in fleet.homes:
                assert home.dispatch_strategy == "tou_optimized"
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# FinanceConfig grid_services_model selector (step-11)
# ---------------------------------------------------------------------------


class TestFinanceConfigGridServicesModel:
    """FinanceConfig.grid_services_model + grid_services_events fields (step-11)."""

    _BASE: dict = {"standing_charge_pence_per_day": 60.0}

    def test_default_grid_services_model_is_flat(self) -> None:
        """Default grid_services_model is 'flat'."""
        fc = FinanceConfig(**self._BASE)
        assert fc.grid_services_model == "flat"

    def test_default_grid_services_events_is_none(self) -> None:
        """Default grid_services_events is None."""
        fc = FinanceConfig(**self._BASE)
        assert fc.grid_services_events is None

    def test_all_pre_existing_defaults_unchanged(self) -> None:
        """Adding new fields does not disturb any pre-existing FinanceConfig defaults."""
        fc = FinanceConfig(**self._BASE)
        assert fc.vat_rate == 0.05
        assert fc.retail_baseline_rate_pence_per_kwh == 23.0
        assert fc.self_consumption_override is None
        assert fc.pv_cost_per_kwp_gbp == 1000.0
        assert fc.grid_services_income_per_kw_per_year_gbp == 0.0

    def test_frozen_with_new_fields(self) -> None:
        """FinanceConfig is still frozen after adding new fields."""
        import dataclasses as dc
        fc = FinanceConfig(**self._BASE)
        with pytest.raises(dc.FrozenInstanceError):
            fc.grid_services_model = "capacity_at_events"  # type: ignore[misc]

    def test_picklable_with_new_fields(self) -> None:
        """FinanceConfig is picklable when grid_services_events is None."""
        import pickle
        fc = FinanceConfig(**self._BASE)
        assert pickle.loads(pickle.dumps(fc)) == fc

    def test_capacity_at_events_model_with_config(self) -> None:
        """Constructing with grid_services_model='capacity_at_events' + GridServicesEventsConfig round-trips."""
        import pickle
        from solar_challenge.gridservices import GridServicesEventsConfig
        events_cfg = GridServicesEventsConfig()
        fc = FinanceConfig(
            **self._BASE,
            grid_services_model="capacity_at_events",
            grid_services_events=events_cfg,
        )
        assert fc.grid_services_model == "capacity_at_events"
        assert fc.grid_services_events == events_cfg
        assert pickle.loads(pickle.dumps(fc)) == fc

    def test_unknown_grid_services_model_raises(self) -> None:
        """Unknown grid_services_model raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            FinanceConfig(**self._BASE, grid_services_model="foo")

    def test_capacity_at_events_without_config_ok(self) -> None:
        """grid_services_model='capacity_at_events' with grid_services_events=None still constructs."""
        fc = FinanceConfig(**self._BASE, grid_services_model="capacity_at_events")
        assert fc.grid_services_model == "capacity_at_events"
        assert fc.grid_services_events is None


# ---------------------------------------------------------------------------
# parse_finance_config: grid_services_model + nested grid_services_events (step-13)
# ---------------------------------------------------------------------------


class TestFinanceConfigParsingGridServices:
    """Tests for parse_finance_config with grid_services_model + grid_services_events."""

    _BASE = {"standing_charge_pence_per_day": 60.0}

    def test_omitting_model_defaults_flat(self) -> None:
        """Finance dict omitting grid_services_model yields 'flat' + None events."""
        result = parse_finance_config(self._BASE)
        assert result is not None
        assert result.grid_services_model == "flat"
        assert result.grid_services_events is None

    def test_capacity_at_events_with_nested_events_block(self) -> None:
        """grid_services_model='capacity_at_events' + events block parses fully."""
        from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
        data = {
            **self._BASE,
            "grid_services_model": "capacity_at_events",
            "grid_services_events": {
                "band": "high",
                "aggregator_share": 0.1,
                "utilisation_factor": 0.8,
                "availability_gbp_per_kw_per_event": 2.5,
                "utilisation_gbp_per_mwh": 80.0,
                "event_windows": [
                    {
                        "months": [11, 12, 1, 2],
                        "weekdays": [0, 1, 2, 3, 4],
                        "hours": [16, 17, 18],
                        "events_per_year": 12,
                        "event_hours": 3.0,
                    }
                ],
            },
        }
        result = parse_finance_config(data)
        assert result is not None
        assert result.grid_services_model == "capacity_at_events"
        assert isinstance(result.grid_services_events, GridServicesEventsConfig)
        cfg = result.grid_services_events
        assert cfg.band == "high"
        assert cfg.aggregator_share == 0.1
        assert cfg.utilisation_factor == 0.8
        assert cfg.availability_gbp_per_kw_per_event == 2.5
        assert cfg.utilisation_gbp_per_mwh == 80.0
        assert len(cfg.event_windows) == 1
        ew = cfg.event_windows[0]
        assert isinstance(ew, EventWindow)
        assert set(ew.months) == {11, 12, 1, 2}
        assert set(ew.weekdays) == {0, 1, 2, 3, 4}
        assert set(ew.hours) == {16, 17, 18}
        assert ew.events_per_year == 12
        assert ew.event_hours == 3.0

    def test_unknown_model_raises_configuration_error(self) -> None:
        """Unknown grid_services_model in dict raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({**self._BASE, "grid_services_model": "unknown"})

    def test_nested_negative_override_raises(self) -> None:
        """Negative availability override in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "availability_gbp_per_kw_per_event": -1.0,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    def test_nested_aggregator_share_one_raises(self) -> None:
        """aggregator_share=1 in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 1.0,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    def test_nested_empty_event_windows_raises(self) -> None:
        """Empty event_windows list in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [],
                },
            })

    def test_nested_unknown_band_raises(self) -> None:
        """Unknown band in nested block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "extreme",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": 1.0}
                    ],
                },
            })

    # ---- Robustness: malformed nested values (suggestions from code review) ----

    def test_non_dict_grid_services_events_raises(self) -> None:
        """grid_services_events as a string (not a dict) raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": "central",  # wrong type
            })

    def test_non_numeric_event_hours_raises(self) -> None:
        """event_hours='abc' (non-numeric string) raises ConfigurationError, not raw ValueError."""
        with pytest.raises(ConfigurationError):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        {"months": [12], "weekdays": [0], "hours": [17],
                         "events_per_year": 1, "event_hours": "abc"},
                    ],
                },
            })

    def test_missing_required_event_window_key_raises(self) -> None:
        """event_window dict missing a required key raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires 'hours'"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": [
                        # 'hours' key intentionally omitted
                        {"months": [12], "weekdays": [0],
                         "events_per_year": 1, "event_hours": 1.0},
                    ],
                },
            })

    def test_non_dict_event_window_entry_raises(self) -> None:
        """A non-dict entry in event_windows list raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            parse_finance_config({
                **self._BASE,
                "grid_services_model": "capacity_at_events",
                "grid_services_events": {
                    "band": "central",
                    "aggregator_share": 0.25,
                    "utilisation_factor": 0.6,
                    "event_windows": ["not-a-dict"],  # list entry is a string
                },
            })
