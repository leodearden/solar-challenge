"""Tests for Battery configuration and state."""

import dataclasses
import math
import pickle

import pytest
from solar_challenge.battery import BatteryConfig, Battery, compute_soh
from solar_challenge.config import GridChargeConfig


class TestBatteryConfigBasics:
    """Test basic BatteryConfig functionality."""

    def test_create_with_all_params(self):
        """BatteryConfig can be created with all parameters."""
        config = BatteryConfig(
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            name="Test battery"
        )
        assert config.capacity_kwh == 10.0
        assert config.max_charge_kw == 5.0
        assert config.max_discharge_kw == 5.0
        assert config.name == "Test battery"

    def test_default_values(self):
        """BatteryConfig uses correct defaults."""
        config = BatteryConfig(capacity_kwh=5.0)
        assert config.max_charge_kw == 2.5
        assert config.max_discharge_kw == 2.5
        assert config.name == ""


class TestBatteryConfigDefaults:
    """Test default battery configurations."""

    def test_default_5kwh(self):
        """Default 5 kWh battery has correct values."""
        config = BatteryConfig.default_5kwh()
        assert config.capacity_kwh == 5.0
        assert config.max_charge_kw == 2.5
        assert config.max_discharge_kw == 2.5
        assert config.name  # Has a name


class TestBatteryConfigValidation:
    """Test parameter validation."""

    def test_capacity_must_be_positive(self):
        """Capacity <= 0 raises error."""
        with pytest.raises(ValueError, match="Capacity"):
            BatteryConfig(capacity_kwh=0)
        with pytest.raises(ValueError, match="Capacity"):
            BatteryConfig(capacity_kwh=-1.0)

    def test_max_charge_must_be_positive(self):
        """Max charge <= 0 raises error."""
        with pytest.raises(ValueError, match="charge"):
            BatteryConfig(capacity_kwh=5.0, max_charge_kw=0)
        with pytest.raises(ValueError, match="charge"):
            BatteryConfig(capacity_kwh=5.0, max_charge_kw=-1.0)

    def test_max_discharge_must_be_positive(self):
        """Max discharge <= 0 raises error."""
        with pytest.raises(ValueError, match="discharge"):
            BatteryConfig(capacity_kwh=5.0, max_discharge_kw=0)
        with pytest.raises(ValueError, match="discharge"):
            BatteryConfig(capacity_kwh=5.0, max_discharge_kw=-1.0)


class TestBatteryConfigGridCharging:
    """Contract guard: grid_charging field on BatteryConfig is frozen and picklable."""

    def test_grid_charging_default_is_none(self) -> None:
        """BatteryConfig without grid_charging has grid_charging == None."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.grid_charging is None

    def test_grid_charging_stored_value(self) -> None:
        """BatteryConfig.grid_charging stores the GridChargeConfig correctly."""
        gc = GridChargeConfig(target_soc_fraction=0.8)
        cfg = BatteryConfig(capacity_kwh=5.0, grid_charging=gc)
        assert cfg.grid_charging is not None
        assert cfg.grid_charging.target_soc_fraction == 0.8

    def test_battery_config_frozen_grid_charging(self) -> None:
        """Assigning to BatteryConfig.grid_charging raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.grid_charging = None  # type: ignore[misc]

    def test_grid_charge_config_frozen(self) -> None:
        """Assigning to GridChargeConfig.target_soc_fraction raises FrozenInstanceError."""
        gc = GridChargeConfig(target_soc_fraction=0.8)
        cfg = BatteryConfig(capacity_kwh=5.0, grid_charging=gc)
        assert cfg.grid_charging is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.grid_charging.target_soc_fraction = 0.5  # type: ignore[misc]

    def test_picklable_with_grid_charging(self) -> None:
        """BatteryConfig with GridChargeConfig round-trips through pickle."""
        gc = GridChargeConfig(target_soc_fraction=0.8)
        cfg = BatteryConfig(capacity_kwh=5.0, grid_charging=gc)
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg


class TestBatteryConfigRoundTripEfficiency:
    """Test BatteryConfig round-trip efficiency split via sqrt."""

    def test_efficiency_splits_into_sqrt(self) -> None:
        """efficiency=0.9 -> charge_efficiency==sqrt(0.9), discharge_efficiency==sqrt(0.9)."""
        cfg = BatteryConfig(capacity_kwh=5.0, efficiency=0.9)
        assert cfg.charge_efficiency == pytest.approx(math.sqrt(0.9))
        assert cfg.discharge_efficiency == pytest.approx(math.sqrt(0.9))

    def test_efficiency_retained_as_raw(self) -> None:
        """efficiency field retains the original round-trip value."""
        cfg = BatteryConfig(capacity_kwh=5.0, efficiency=0.9)
        assert cfg.efficiency == 0.9

    def test_efficiency_overrides_explicit_charge_discharge(self) -> None:
        """efficiency takes precedence over explicit charge_efficiency/discharge_efficiency."""
        cfg = BatteryConfig(
            capacity_kwh=5.0,
            efficiency=0.81,
            charge_efficiency=0.99,
            discharge_efficiency=0.99,
        )
        assert cfg.charge_efficiency == pytest.approx(math.sqrt(0.81))
        assert cfg.discharge_efficiency == pytest.approx(math.sqrt(0.81))

    def test_efficiency_zero_raises(self) -> None:
        """efficiency == 0 raises ValueError."""
        with pytest.raises(ValueError, match="efficiency"):
            BatteryConfig(capacity_kwh=5.0, efficiency=0.0)

    def test_efficiency_greater_than_one_raises(self) -> None:
        """efficiency > 1 raises ValueError."""
        with pytest.raises(ValueError, match="efficiency"):
            BatteryConfig(capacity_kwh=5.0, efficiency=1.5)

    def test_efficiency_negative_raises(self) -> None:
        """efficiency < 0 raises ValueError."""
        with pytest.raises(ValueError, match="efficiency"):
            BatteryConfig(capacity_kwh=5.0, efficiency=-0.5)

    def test_efficiency_one_is_valid(self) -> None:
        """efficiency == 1 is valid (100% round-trip)."""
        cfg = BatteryConfig(capacity_kwh=5.0, efficiency=1.0)
        assert cfg.charge_efficiency == pytest.approx(1.0)
        assert cfg.discharge_efficiency == pytest.approx(1.0)

    def test_efficiency_pickles_idempotently(self) -> None:
        """BatteryConfig with efficiency round-trips through pickle correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, efficiency=0.9)
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg
        # After pickle, charge_efficiency should still equal sqrt(0.9)
        assert restored.charge_efficiency == pytest.approx(math.sqrt(0.9))


class TestBatteryConfigSOCEfficiencyValidation:
    """Test BatteryConfig.__post_init__ validates SOC fractions and efficiencies."""

    # --- SOC fraction validation ---

    def test_min_soc_equal_to_max_raises(self) -> None:
        """min_soc_fraction == max_soc_fraction raises ValueError."""
        with pytest.raises(ValueError, match="SOC"):
            BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.5, max_soc_fraction=0.5)

    def test_min_soc_greater_than_max_raises(self) -> None:
        """min_soc_fraction > max_soc_fraction raises ValueError."""
        with pytest.raises(ValueError, match="SOC"):
            BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.8, max_soc_fraction=0.3)

    def test_min_soc_fraction_negative_raises(self) -> None:
        """min_soc_fraction < 0 raises ValueError."""
        with pytest.raises(ValueError, match="SOC"):
            BatteryConfig(capacity_kwh=5.0, min_soc_fraction=-0.1, max_soc_fraction=0.9)

    def test_max_soc_fraction_exceeds_one_raises(self) -> None:
        """max_soc_fraction > 1 raises ValueError."""
        with pytest.raises(ValueError, match="SOC"):
            BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.1, max_soc_fraction=1.1)

    # --- charge_efficiency validation ---

    def test_charge_efficiency_zero_raises(self) -> None:
        """charge_efficiency == 0 raises ValueError."""
        with pytest.raises(ValueError, match="[Cc]harge"):
            BatteryConfig(capacity_kwh=5.0, charge_efficiency=0.0)

    def test_charge_efficiency_greater_than_one_raises(self) -> None:
        """charge_efficiency > 1 raises ValueError."""
        with pytest.raises(ValueError, match="[Cc]harge"):
            BatteryConfig(capacity_kwh=5.0, charge_efficiency=1.1)

    def test_charge_efficiency_negative_raises(self) -> None:
        """charge_efficiency < 0 raises ValueError."""
        with pytest.raises(ValueError, match="[Cc]harge"):
            BatteryConfig(capacity_kwh=5.0, charge_efficiency=-0.5)

    # --- discharge_efficiency validation ---

    def test_discharge_efficiency_zero_raises(self) -> None:
        """discharge_efficiency == 0 raises ValueError."""
        with pytest.raises(ValueError, match="[Dd]ischarge"):
            BatteryConfig(capacity_kwh=5.0, discharge_efficiency=0.0)

    def test_discharge_efficiency_greater_than_one_raises(self) -> None:
        """discharge_efficiency > 1 raises ValueError."""
        with pytest.raises(ValueError, match="[Dd]ischarge"):
            BatteryConfig(capacity_kwh=5.0, discharge_efficiency=1.2)

    def test_discharge_efficiency_negative_raises(self) -> None:
        """discharge_efficiency < 0 raises ValueError."""
        with pytest.raises(ValueError, match="[Dd]ischarge"):
            BatteryConfig(capacity_kwh=5.0, discharge_efficiency=-0.1)

    # --- valid in-range values pass ---

    def test_valid_custom_values_construct_successfully(self) -> None:
        """In-range custom SOC/eff values construct without error."""
        cfg = BatteryConfig(
            capacity_kwh=5.0,
            min_soc_fraction=0.2,
            max_soc_fraction=0.8,
            charge_efficiency=0.9,
            discharge_efficiency=0.92,
        )
        assert cfg.min_soc_fraction == 0.2
        assert cfg.max_soc_fraction == 0.8
        assert cfg.charge_efficiency == 0.9
        assert cfg.discharge_efficiency == 0.92

    def test_zero_min_soc_is_valid(self) -> None:
        """min_soc_fraction == 0 is valid (no minimum reserve required)."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.0, max_soc_fraction=0.9)
        assert cfg.min_soc_fraction == 0.0

    def test_one_max_soc_is_valid(self) -> None:
        """max_soc_fraction == 1 is valid (full capacity usable)."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.0, max_soc_fraction=1.0)
        assert cfg.max_soc_fraction == 1.0

    def test_efficiency_one_is_valid(self) -> None:
        """charge_efficiency == 1 is valid (perfect efficiency)."""
        cfg = BatteryConfig(capacity_kwh=5.0, charge_efficiency=1.0, discharge_efficiency=1.0)
        assert cfg.charge_efficiency == 1.0
        assert cfg.discharge_efficiency == 1.0


class TestBatteryConfigSOCEfficiencyFields:
    """Contract guard: SOC-limit and efficiency fields on BatteryConfig are frozen and picklable."""

    def test_default_min_soc_fraction(self) -> None:
        """BatteryConfig default min_soc_fraction is 0.1."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.min_soc_fraction == 0.1

    def test_default_max_soc_fraction(self) -> None:
        """BatteryConfig default max_soc_fraction is 0.9."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.max_soc_fraction == 0.9

    def test_default_charge_efficiency(self) -> None:
        """BatteryConfig default charge_efficiency is 0.975."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.charge_efficiency == 0.975

    def test_default_discharge_efficiency(self) -> None:
        """BatteryConfig default discharge_efficiency is 0.975."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.discharge_efficiency == 0.975

    def test_default_efficiency_is_none(self) -> None:
        """BatteryConfig default efficiency (round-trip) is None."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.efficiency is None

    def test_custom_soc_fractions(self) -> None:
        """Custom SOC fractions are stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.2, max_soc_fraction=0.8)
        assert cfg.min_soc_fraction == 0.2
        assert cfg.max_soc_fraction == 0.8

    def test_custom_efficiencies(self) -> None:
        """Custom per-direction efficiencies are stored correctly."""
        cfg = BatteryConfig(
            capacity_kwh=5.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.92,
        )
        assert cfg.charge_efficiency == 0.95
        assert cfg.discharge_efficiency == 0.92

    def test_min_soc_fraction_frozen(self) -> None:
        """Assigning to BatteryConfig.min_soc_fraction raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.min_soc_fraction = 0.2  # type: ignore[misc]

    def test_max_soc_fraction_frozen(self) -> None:
        """Assigning to BatteryConfig.max_soc_fraction raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.max_soc_fraction = 0.8  # type: ignore[misc]

    def test_charge_efficiency_frozen(self) -> None:
        """Assigning to BatteryConfig.charge_efficiency raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.charge_efficiency = 0.9  # type: ignore[misc]

    def test_discharge_efficiency_frozen(self) -> None:
        """Assigning to BatteryConfig.discharge_efficiency raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.discharge_efficiency = 0.9  # type: ignore[misc]

    def test_picklable_with_custom_soc_eff(self) -> None:
        """BatteryConfig with custom SOC/efficiency values round-trips through pickle."""
        cfg = BatteryConfig(
            capacity_kwh=5.0,
            min_soc_fraction=0.15,
            max_soc_fraction=0.85,
            charge_efficiency=0.96,
            discharge_efficiency=0.94,
        )
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg


class TestBatteryReadsSOCEffFromConfig:
    """Battery inherits SOC limits and efficiencies from BatteryConfig when not overridden."""

    def test_battery_inherits_min_soc_from_config(self) -> None:
        """Battery reads min_soc_fraction from BatteryConfig."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.2, max_soc_fraction=0.8)
        battery = Battery(cfg)
        assert battery.min_soc_fraction == 0.2

    def test_battery_inherits_max_soc_from_config(self) -> None:
        """Battery reads max_soc_fraction from BatteryConfig."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.2, max_soc_fraction=0.8)
        battery = Battery(cfg)
        assert battery.max_soc_fraction == 0.8

    def test_battery_inherits_charge_efficiency_from_config(self) -> None:
        """Battery reads charge_efficiency from BatteryConfig."""
        cfg = BatteryConfig(capacity_kwh=5.0, charge_efficiency=0.9, discharge_efficiency=0.92)
        battery = Battery(cfg)
        assert battery.charge_efficiency == 0.9

    def test_battery_inherits_discharge_efficiency_from_config(self) -> None:
        """Battery reads discharge_efficiency from BatteryConfig."""
        cfg = BatteryConfig(capacity_kwh=5.0, charge_efficiency=0.9, discharge_efficiency=0.92)
        battery = Battery(cfg)
        assert battery.discharge_efficiency == 0.92

    def test_constructor_arg_overrides_config_charge_efficiency(self) -> None:
        """Explicit charge_efficiency arg overrides config value."""
        cfg = BatteryConfig(capacity_kwh=5.0, charge_efficiency=0.9)
        battery = Battery(cfg, charge_efficiency=0.5)
        assert battery.charge_efficiency == 0.5

    def test_constructor_arg_overrides_config_discharge_efficiency(self) -> None:
        """Explicit discharge_efficiency arg overrides config value."""
        cfg = BatteryConfig(capacity_kwh=5.0, discharge_efficiency=0.9)
        battery = Battery(cfg, discharge_efficiency=0.6)
        assert battery.discharge_efficiency == 0.6

    def test_battery_uses_config_efficiency_for_charging(self) -> None:
        """Battery built from config with efficiency=0.9 charges with sqrt(0.9)."""
        cfg = BatteryConfig(capacity_kwh=10.0, efficiency=0.9)
        battery = Battery(cfg, initial_soc_kwh=cfg.capacity_kwh * cfg.min_soc_fraction + 1.0)
        initial_soc = battery.soc_kwh
        # Charge 1 kW for 1 hour
        battery.charge(power_kw=1.0, duration_minutes=60)
        expected_stored = 1.0 * math.sqrt(0.9)
        assert battery.soc_kwh == pytest.approx(initial_soc + expected_stored)

    def test_backward_compat_default_config_keeps_existing_values(self) -> None:
        """Battery(BatteryConfig(capacity_kwh=5.0)) is bit-identical to today (H7)."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        battery = Battery(cfg)
        assert battery.min_soc_fraction == 0.1
        assert battery.max_soc_fraction == 0.9
        assert battery.charge_efficiency == 0.975
        assert battery.discharge_efficiency == 0.975
        # Initial SOC: midpoint of 0.5-4.5 = 2.5
        assert battery.soc_kwh == 2.5

    def test_constructor_arg_overrides_config_min_soc_fraction(self) -> None:
        """Explicit min_soc_fraction arg overrides config value."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.1, max_soc_fraction=0.9)
        battery = Battery(cfg, min_soc_fraction=0.2)
        assert battery.min_soc_fraction == 0.2

    def test_constructor_arg_overrides_config_max_soc_fraction(self) -> None:
        """Explicit max_soc_fraction arg overrides config value."""
        cfg = BatteryConfig(capacity_kwh=5.0, min_soc_fraction=0.1, max_soc_fraction=0.9)
        battery = Battery(cfg, max_soc_fraction=0.8)
        assert battery.max_soc_fraction == 0.8

    def test_out_of_range_min_soc_constructor_override_raises(self) -> None:
        """min_soc_fraction > max_soc_fraction explicit override raises ValueError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(ValueError, match="SOC"):
            Battery(cfg, min_soc_fraction=0.95, max_soc_fraction=0.1)

    def test_out_of_range_charge_efficiency_constructor_override_raises(self) -> None:
        """charge_efficiency > 1 explicit override raises ValueError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(ValueError, match="[Cc]harge"):
            Battery(cfg, charge_efficiency=1.5)

    def test_out_of_range_discharge_efficiency_constructor_override_raises(self) -> None:
        """discharge_efficiency == 0 explicit override raises ValueError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(ValueError, match="[Dd]ischarge"):
            Battery(cfg, discharge_efficiency=0.0)


@pytest.fixture
def default_config():
    """Create a default 5 kWh battery config."""
    return BatteryConfig.default_5kwh()


@pytest.fixture
def default_battery(default_config):
    """Create a default battery with standard settings."""
    return Battery(default_config)


class TestBatterySOCTracking:
    """Test state of charge tracking (BAT-002)."""

    def test_initial_soc_default(self, default_config):
        """Default initial SOC is midpoint of usable range."""
        battery = Battery(default_config)
        # For 5 kWh with 10-90% limits: min=0.5, max=4.5, mid=2.5
        assert battery.soc_kwh == 2.5

    def test_initial_soc_custom(self, default_config):
        """Can set custom initial SOC."""
        battery = Battery(default_config, initial_soc_kwh=3.0)
        assert battery.soc_kwh == 3.0

    def test_initial_soc_out_of_range_raises(self, default_config):
        """Initial SOC outside limits raises error."""
        with pytest.raises(ValueError, match="outside allowed range"):
            Battery(default_config, initial_soc_kwh=0.0)  # Below min
        with pytest.raises(ValueError, match="outside allowed range"):
            Battery(default_config, initial_soc_kwh=5.0)  # Above max

    def test_soc_updated_after_charge(self, default_battery):
        """SOC increases after charging."""
        initial_soc = default_battery.soc_kwh
        default_battery.charge(power_kw=1.0, duration_minutes=60)
        assert default_battery.soc_kwh > initial_soc

    def test_soc_updated_after_discharge(self, default_battery):
        """SOC decreases after discharging."""
        initial_soc = default_battery.soc_kwh
        default_battery.discharge(power_kw=1.0, duration_minutes=60)
        assert default_battery.soc_kwh < initial_soc

    def test_soc_queryable(self, default_battery):
        """SOC is queryable at any time."""
        assert isinstance(default_battery.soc_kwh, float)
        assert isinstance(default_battery.soc_fraction, float)


class TestBatterySOCLimits:
    """Test SOC limit enforcement (BAT-005)."""

    def test_default_limits(self, default_config):
        """Default limits are 10% min, 90% max."""
        battery = Battery(default_config)
        assert battery.min_soc_fraction == 0.1
        assert battery.max_soc_fraction == 0.9
        assert battery.min_soc_kwh == 0.5  # 10% of 5 kWh
        assert battery.max_soc_kwh == 4.5  # 90% of 5 kWh

    def test_usable_capacity(self, default_battery):
        """Usable capacity is max - min."""
        assert default_battery.usable_capacity_kwh == 4.0  # 4.5 - 0.5

    def test_charge_stops_at_max_soc(self, default_config):
        """Charging stops when max SOC reached."""
        # Start at max SOC
        battery = Battery(default_config, initial_soc_kwh=4.5)
        energy_charged = battery.charge(power_kw=2.5, duration_minutes=60)
        assert energy_charged == 0.0
        assert battery.soc_kwh == 4.5

    def test_discharge_stops_at_min_soc(self, default_config):
        """Discharging stops when min SOC reached."""
        # Start at min SOC
        battery = Battery(default_config, initial_soc_kwh=0.5)
        energy_discharged = battery.discharge(power_kw=2.5, duration_minutes=60)
        assert energy_discharged == 0.0
        assert battery.soc_kwh == 0.5


class TestBatteryChargeEfficiency:
    """Test charge efficiency (BAT-003)."""

    def test_default_charge_efficiency(self, default_battery):
        """Default charge efficiency is 97.5%."""
        assert default_battery.charge_efficiency == 0.975

    def test_energy_stored_with_efficiency(self, default_config):
        """Energy stored = input * efficiency."""
        battery = Battery(default_config, initial_soc_kwh=1.0, charge_efficiency=0.95)
        initial_soc = battery.soc_kwh

        # Charge 1 kWh input
        battery.charge(power_kw=1.0, duration_minutes=60)

        # Should store 0.95 kWh
        assert battery.soc_kwh == pytest.approx(initial_soc + 0.95, rel=1e-6)


class TestBatteryDischargeEfficiency:
    """Test discharge efficiency (BAT-004)."""

    def test_default_discharge_efficiency(self, default_battery):
        """Default discharge efficiency is 97.5%."""
        assert default_battery.discharge_efficiency == 0.975

    def test_energy_output_with_efficiency(self, default_config):
        """Energy output = withdrawn * efficiency."""
        battery = Battery(default_config, initial_soc_kwh=3.0, discharge_efficiency=0.95)
        initial_soc = battery.soc_kwh

        # Request 1 kWh output
        energy_out = battery.discharge(power_kw=1.0, duration_minutes=60)

        # Should get ~0.95 kWh output (limited by efficiency)
        # Actually, we request 1 kWh power for 1 hour, withdraw 1/0.95 kWh, output 1 kWh
        # Wait - the logic is: we request power, we limit by rate, we calculate needed from battery
        # With 1 kW for 1 hour, we need to withdraw 1/0.95 = 1.053 kWh to output 1 kWh
        # So output is actually 1 kWh if we have capacity
        assert energy_out == pytest.approx(1.0, rel=0.01)
        # SOC drops by 1/0.95 = 1.053 kWh
        assert battery.soc_kwh == pytest.approx(initial_soc - 1.0 / 0.95, rel=0.01)


class TestBatteryChargeFromExcess:
    """Test charging from excess PV (BAT-006)."""

    def test_charge_method_basic(self, default_battery):
        """Charge method accepts power and duration."""
        initial_soc = default_battery.soc_kwh
        energy = default_battery.charge(power_kw=1.0, duration_minutes=30)
        assert energy > 0
        assert default_battery.soc_kwh > initial_soc

    def test_charge_respects_max_rate(self, default_config):
        """Charge rate limited to max_charge_kw."""
        battery = Battery(default_config, initial_soc_kwh=1.0)

        # Try to charge at 10 kW (max is 2.5 kW)
        energy = battery.charge(power_kw=10.0, duration_minutes=60)

        # Should only charge at 2.5 kW rate
        # 2.5 kW * 1 hour * 0.975 efficiency = 2.4375 kWh
        assert energy == pytest.approx(2.4375, rel=0.01)

    def test_charge_returns_actual_energy(self, default_battery):
        """Charge returns actual energy stored."""
        energy = default_battery.charge(power_kw=1.0, duration_minutes=60)
        assert isinstance(energy, float)
        assert energy >= 0


class TestBatteryDischargeToMeetDemand:
    """Test discharging to meet demand (BAT-007)."""

    def test_discharge_method_basic(self, default_battery):
        """Discharge method accepts power and duration."""
        initial_soc = default_battery.soc_kwh
        energy = default_battery.discharge(power_kw=1.0, duration_minutes=30)
        assert energy > 0
        assert default_battery.soc_kwh < initial_soc

    def test_discharge_respects_max_rate(self, default_config):
        """Discharge rate limited to max_discharge_kw."""
        battery = Battery(default_config, initial_soc_kwh=4.0)

        # Try to discharge at 10 kW (max is 2.5 kW)
        energy = battery.discharge(power_kw=10.0, duration_minutes=60)

        # Should only discharge at 2.5 kW rate
        # Limited by rate: 2.5 kWh output (approximately, with efficiency)
        assert energy <= 2.5 * 1.0  # max_rate * duration

    def test_discharge_returns_actual_energy(self, default_battery):
        """Discharge returns actual energy output."""
        energy = default_battery.discharge(power_kw=1.0, duration_minutes=60)
        assert isinstance(energy, float)
        assert energy >= 0


class TestBatterySOCTimeSeries:
    """Test SOC time series output (BAT-008)."""

    def test_soc_history_tracking(self, default_config):
        """Battery can provide SOC history over multiple timesteps."""
        battery = Battery(default_config)
        soc_history = [battery.soc_kwh]

        # Simulate several charge/discharge cycles
        battery.charge(power_kw=1.0, duration_minutes=60)
        soc_history.append(battery.soc_kwh)

        battery.charge(power_kw=1.0, duration_minutes=60)
        soc_history.append(battery.soc_kwh)

        battery.discharge(power_kw=2.0, duration_minutes=60)
        soc_history.append(battery.soc_kwh)

        # Verify history is tracked correctly
        assert len(soc_history) == 4
        assert all(isinstance(s, float) for s in soc_history)
        assert soc_history[1] > soc_history[0]  # Charged
        assert soc_history[2] > soc_history[1]  # Charged more
        assert soc_history[3] < soc_history[2]  # Discharged

    def test_soc_kwh_always_queryable(self, default_battery):
        """SOC in kWh is always queryable."""
        assert hasattr(default_battery, 'soc_kwh')
        assert isinstance(default_battery.soc_kwh, float)

    def test_soc_fraction_queryable(self, default_battery):
        """SOC as fraction is queryable."""
        assert hasattr(default_battery, 'soc_fraction')
        assert isinstance(default_battery.soc_fraction, float)
        assert 0 <= default_battery.soc_fraction <= 1

    def test_soc_percentage_calculation(self, default_config):
        """SOC percentage can be calculated from fraction."""
        battery = Battery(default_config, initial_soc_kwh=2.5)  # 50% of 5 kWh
        percentage = battery.soc_fraction * 100
        assert percentage == pytest.approx(50.0, rel=0.01)

    def test_soc_recorded_at_each_timestep(self, default_config):
        """SOC is available after each operation."""
        battery = Battery(default_config, initial_soc_kwh=2.0)

        # 60 one-minute timesteps
        soc_values = []
        for i in range(60):
            # Alternate charge/discharge
            if i % 2 == 0:
                battery.charge(power_kw=0.5, duration_minutes=1)
            else:
                battery.discharge(power_kw=0.3, duration_minutes=1)
            soc_values.append(battery.soc_kwh)

        assert len(soc_values) == 60
        assert all(0.5 <= s <= 4.5 for s in soc_values)  # Within limits


class TestBatterySOHFields:
    """Contract guard: SOH/aging fields on BatteryConfig are frozen and picklable."""

    def test_default_system_age_years(self) -> None:
        """BatteryConfig default system_age_years is 0.0."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.system_age_years == 0.0

    def test_default_calendar_fade_rate_per_year(self) -> None:
        """BatteryConfig default calendar_fade_rate_per_year is 0.02."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.calendar_fade_rate_per_year == 0.02

    def test_default_cycle_fade_per_equivalent_full_cycle(self) -> None:
        """BatteryConfig default cycle_fade_per_equivalent_full_cycle is 5e-5."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.cycle_fade_per_equivalent_full_cycle == 5e-5

    def test_default_soh_floor(self) -> None:
        """BatteryConfig default soh_floor is 0.5."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.soh_floor == 0.5

    def test_default_soh_is_none(self) -> None:
        """BatteryConfig default soh (override) is None."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        assert cfg.soh is None

    def test_custom_system_age_years(self) -> None:
        """Custom system_age_years is stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, system_age_years=10.0)
        assert cfg.system_age_years == 10.0

    def test_custom_calendar_fade_rate_per_year(self) -> None:
        """Custom calendar_fade_rate_per_year is stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, calendar_fade_rate_per_year=0.03)
        assert cfg.calendar_fade_rate_per_year == 0.03

    def test_custom_cycle_fade_per_equivalent_full_cycle(self) -> None:
        """Custom cycle_fade_per_equivalent_full_cycle is stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, cycle_fade_per_equivalent_full_cycle=1e-4)
        assert cfg.cycle_fade_per_equivalent_full_cycle == 1e-4

    def test_custom_soh_floor(self) -> None:
        """Custom soh_floor is stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh_floor=0.7)
        assert cfg.soh_floor == 0.7

    def test_custom_soh_override(self) -> None:
        """Custom soh override is stored correctly."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh=0.85)
        assert cfg.soh == pytest.approx(0.85)

    def test_system_age_years_frozen(self) -> None:
        """Assigning to BatteryConfig.system_age_years raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.system_age_years = 5.0  # type: ignore[misc]

    def test_calendar_fade_rate_per_year_frozen(self) -> None:
        """Assigning to BatteryConfig.calendar_fade_rate_per_year raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.calendar_fade_rate_per_year = 0.01  # type: ignore[misc]

    def test_cycle_fade_per_equivalent_full_cycle_frozen(self) -> None:
        """Assigning to BatteryConfig.cycle_fade_per_equivalent_full_cycle raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.cycle_fade_per_equivalent_full_cycle = 1e-4  # type: ignore[misc]

    def test_soh_floor_frozen(self) -> None:
        """Assigning to BatteryConfig.soh_floor raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.soh_floor = 0.6  # type: ignore[misc]

    def test_soh_frozen(self) -> None:
        """Assigning to BatteryConfig.soh raises FrozenInstanceError."""
        cfg = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.soh = 0.9  # type: ignore[misc]

    def test_picklable_with_custom_soh_fields(self) -> None:
        """BatteryConfig with custom SOH fields round-trips through pickle."""
        cfg = BatteryConfig(
            capacity_kwh=5.0,
            system_age_years=8.0,
            calendar_fade_rate_per_year=0.025,
            cycle_fade_per_equivalent_full_cycle=6e-5,
            soh_floor=0.6,
            soh=0.8,
        )
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg


class TestBatterySOHFieldValidation:
    """Test BatteryConfig.__post_init__ validates SOH/aging fields."""

    # --- system_age_years ---

    def test_negative_system_age_years_raises(self) -> None:
        """system_age_years < 0 raises ValueError."""
        with pytest.raises(ValueError, match="system_age_years"):
            BatteryConfig(capacity_kwh=5.0, system_age_years=-1.0)

    def test_zero_system_age_years_is_valid(self) -> None:
        """system_age_years == 0.0 is valid."""
        cfg = BatteryConfig(capacity_kwh=5.0, system_age_years=0.0)
        assert cfg.system_age_years == 0.0

    def test_positive_system_age_years_is_valid(self) -> None:
        """system_age_years > 0 is valid."""
        cfg = BatteryConfig(capacity_kwh=5.0, system_age_years=10.0)
        assert cfg.system_age_years == 10.0

    # --- calendar_fade_rate_per_year ---

    def test_negative_calendar_fade_rate_raises(self) -> None:
        """calendar_fade_rate_per_year < 0 raises ValueError."""
        with pytest.raises(ValueError, match="calendar_fade_rate_per_year"):
            BatteryConfig(capacity_kwh=5.0, calendar_fade_rate_per_year=-0.01)

    def test_zero_calendar_fade_rate_is_valid(self) -> None:
        """calendar_fade_rate_per_year == 0 is valid (no calendar fade)."""
        cfg = BatteryConfig(capacity_kwh=5.0, calendar_fade_rate_per_year=0.0)
        assert cfg.calendar_fade_rate_per_year == 0.0

    # --- cycle_fade_per_equivalent_full_cycle ---

    def test_negative_cycle_fade_raises(self) -> None:
        """cycle_fade_per_equivalent_full_cycle < 0 raises ValueError."""
        with pytest.raises(ValueError, match="cycle_fade_per_equivalent_full_cycle"):
            BatteryConfig(capacity_kwh=5.0, cycle_fade_per_equivalent_full_cycle=-1e-5)

    def test_zero_cycle_fade_is_valid(self) -> None:
        """cycle_fade_per_equivalent_full_cycle == 0 is valid (no cycle fade)."""
        cfg = BatteryConfig(capacity_kwh=5.0, cycle_fade_per_equivalent_full_cycle=0.0)
        assert cfg.cycle_fade_per_equivalent_full_cycle == 0.0

    # --- soh_floor ---

    def test_soh_floor_zero_raises(self) -> None:
        """soh_floor == 0 raises ValueError."""
        with pytest.raises(ValueError, match="soh_floor"):
            BatteryConfig(capacity_kwh=5.0, soh_floor=0.0)

    def test_soh_floor_negative_raises(self) -> None:
        """soh_floor < 0 raises ValueError."""
        with pytest.raises(ValueError, match="soh_floor"):
            BatteryConfig(capacity_kwh=5.0, soh_floor=-0.1)

    def test_soh_floor_greater_than_one_raises(self) -> None:
        """soh_floor > 1 raises ValueError."""
        with pytest.raises(ValueError, match="soh_floor"):
            BatteryConfig(capacity_kwh=5.0, soh_floor=1.1)

    def test_soh_floor_one_is_valid(self) -> None:
        """soh_floor == 1.0 is valid (floor at full SOH)."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh_floor=1.0)
        assert cfg.soh_floor == 1.0

    def test_soh_floor_small_positive_is_valid(self) -> None:
        """soh_floor == 0.1 is valid."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh_floor=0.1)
        assert cfg.soh_floor == 0.1

    # --- soh override ---

    def test_soh_override_zero_raises(self) -> None:
        """soh == 0 raises ValueError."""
        with pytest.raises(ValueError, match="soh"):
            BatteryConfig(capacity_kwh=5.0, soh=0.0)

    def test_soh_override_negative_raises(self) -> None:
        """soh < 0 raises ValueError."""
        with pytest.raises(ValueError, match="soh"):
            BatteryConfig(capacity_kwh=5.0, soh=-0.5)

    def test_soh_override_greater_than_one_raises(self) -> None:
        """soh > 1 raises ValueError."""
        with pytest.raises(ValueError, match="soh"):
            BatteryConfig(capacity_kwh=5.0, soh=1.5)

    def test_soh_override_one_is_valid(self) -> None:
        """soh == 1.0 is valid."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh=1.0)
        assert cfg.soh == 1.0

    def test_soh_none_is_valid(self) -> None:
        """soh == None (no override) is valid."""
        cfg = BatteryConfig(capacity_kwh=5.0, soh=None)
        assert cfg.soh is None


class TestComputeSOH:
    """Tests for the pure compute_soh function."""

    def test_age_zero_throughput_zero_returns_one(self) -> None:
        """compute_soh(age=0, throughput=0) == 1.0 (no degradation)."""
        params = BatteryConfig(capacity_kwh=5.0)
        assert compute_soh(0.0, 0.0, 4.0, params) == pytest.approx(1.0)

    def test_monotone_non_increasing_in_age(self) -> None:
        """compute_soh is non-increasing as system_age_years increases."""
        params = BatteryConfig(capacity_kwh=5.0)
        ages = [0, 5, 10, 15, 25]
        soh_values = [compute_soh(a, 100.0, 4.0, params) for a in ages]
        for i in range(1, len(soh_values)):
            assert soh_values[i] <= soh_values[i - 1], (
                f"SOH should not increase with age: soh[{ages[i]}]={soh_values[i]} "
                f"> soh[{ages[i-1]}]={soh_values[i-1]}"
            )

    def test_monotone_non_increasing_in_throughput(self) -> None:
        """compute_soh is non-increasing as cumulative_throughput_kwh increases."""
        params = BatteryConfig(capacity_kwh=5.0)
        throughputs = [0, 500, 1000, 5000, 10000]
        soh_values = [compute_soh(5.0, t, 4.0, params) for t in throughputs]
        for i in range(1, len(soh_values)):
            assert soh_values[i] <= soh_values[i - 1], (
                f"SOH should not increase with throughput: "
                f"soh[{throughputs[i]}]={soh_values[i]} > soh[{throughputs[i-1]}]={soh_values[i-1]}"
            )

    def test_clamp_upper_never_exceeds_one(self) -> None:
        """compute_soh never returns more than 1.0."""
        params = BatteryConfig(capacity_kwh=5.0)
        # Even with zero age and throughput, result is clamped to 1.0
        result = compute_soh(0.0, 0.0, 4.0, params)
        assert result <= 1.0

    def test_clamp_lower_returns_soh_floor(self) -> None:
        """compute_soh clamps to soh_floor when degradation is extreme."""
        # Use a high floor (0.9) so it's easy to trigger with age > 5yr at 0.02/yr
        params = BatteryConfig(capacity_kwh=5.0, soh_floor=0.9)
        # At 25 years, calendar fade = 0.02 * 25 = 0.5 -> raw SOH = 0.5 < floor 0.9
        result = compute_soh(25.0, 0.0, 4.0, params)
        assert result == pytest.approx(0.9)

    def test_combined_greater_than_calendar_alone(self) -> None:
        """At fixed nonzero age, adding throughput > 0 gives strictly lower SOH."""
        params = BatteryConfig(capacity_kwh=5.0)
        soh_calendar_only = compute_soh(5.0, 0.0, 4.0, params)
        soh_combined = compute_soh(5.0, 5000.0, 4.0, params)
        assert soh_combined < soh_calendar_only

    def test_usable_capacity_zero_does_not_raise(self) -> None:
        """compute_soh with usable_capacity_kwh=0 does not raise (efc guarded)."""
        params = BatteryConfig(capacity_kwh=5.0)
        result = compute_soh(5.0, 100.0, 0.0, params)
        # With usable=0, efc=0, so only calendar fade applies
        expected = 1.0 - params.calendar_fade_rate_per_year * 5.0
        assert result == pytest.approx(max(params.soh_floor, min(1.0, expected)))
