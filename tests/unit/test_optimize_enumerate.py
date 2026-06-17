"""Tests for optimize.enumerate_configs and ConfigPoint."""

import dataclasses
import itertools

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import FinanceConfig, GridChargeConfig, ScenarioConfig, SimulationPeriod
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.optimize import ConfigPoint, enumerate_configs
from solar_challenge.pv import PVConfig


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_fleet_base(n_homes: int = 3) -> ScenarioConfig:
    """Build a minimal synthetic fleet ScenarioConfig with distinct LoadConfigs."""
    finance = FinanceConfig(
        standing_charge_pence_per_day=60.0,
        own_use_rate_pence_per_kwh=18.5,
        retained_cash_floor_per_home_per_year_gbp=50.0,
        grid_services_income_per_kw_per_year_gbp=12.0,
    )
    homes = [
        HomeConfig(
            pv_config=PVConfig(capacity_kw=float(3 + i)),
            load_config=LoadConfig(
                annual_consumption_kwh=2800.0 + 400.0 * i,
                household_occupants=1 + i,
            ),
        )
        for i in range(n_homes)
    ]
    return ScenarioConfig(
        name="test-fleet",
        period=SimulationPeriod("2024-01-01", "2024-12-31"),
        homes=homes,
        seg_tariff_pence_per_kwh=7.5,
        finance=finance,
    )


class TestConfigPoint:
    """Tests for the ConfigPoint frozen value-object."""

    def test_construction_and_fields(self) -> None:
        """ConfigPoint constructs and exposes all three fields."""
        cp = ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=3.68)
        assert cp.pv_kwp == 4.0
        assert cp.battery_kwh == 5.0
        assert cp.inverter_kw == 3.68

    def test_is_frozen(self) -> None:
        """ConfigPoint raises FrozenInstanceError on attribute assignment."""
        cp = ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=3.68)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cp.pv_kwp = 99.0  # type: ignore[misc]

    def test_battery_kwh_zero_allowed(self) -> None:
        """battery_kwh==0.0 is the no-battery sentinel and must be accepted."""
        cp = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.68)
        assert cp.battery_kwh == 0.0

    def test_pv_kwp_zero_raises(self) -> None:
        """pv_kwp==0 raises ValueError."""
        with pytest.raises(ValueError, match="pv_kwp"):
            ConfigPoint(pv_kwp=0.0, battery_kwh=5.0, inverter_kw=3.68)

    def test_pv_kwp_negative_raises(self) -> None:
        """pv_kwp<0 raises ValueError."""
        with pytest.raises(ValueError, match="pv_kwp"):
            ConfigPoint(pv_kwp=-1.0, battery_kwh=5.0, inverter_kw=3.68)

    def test_battery_kwh_negative_raises(self) -> None:
        """battery_kwh<0 raises ValueError."""
        with pytest.raises(ValueError, match="battery_kwh"):
            ConfigPoint(pv_kwp=4.0, battery_kwh=-0.1, inverter_kw=3.68)

    def test_inverter_kw_zero_raises(self) -> None:
        """inverter_kw==0 raises ValueError."""
        with pytest.raises(ValueError, match="inverter_kw"):
            ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=0.0)

    def test_inverter_kw_negative_raises(self) -> None:
        """inverter_kw<0 raises ValueError."""
        with pytest.raises(ValueError, match="inverter_kw"):
            ConfigPoint(pv_kwp=4.0, battery_kwh=5.0, inverter_kw=-3.68)


class TestEnumerateContract:
    """Contract tests for enumerate_configs (ordering, count, field preservation)."""

    def test_returns_eight_combos_for_2x2x2_grid(self) -> None:
        """enumerate_configs([4,5],[0,5],[3.68,5]) returns exactly 8 pairs."""
        base = _make_fleet_base(3)
        result = enumerate_configs(base, [4.0, 5.0], [0.0, 5.0], [3.68, 5.0])
        assert len(result) == 8

    def test_result_is_list_of_config_point_scenario_pairs(self) -> None:
        """Each element is a (ConfigPoint, ScenarioConfig) tuple."""
        base = _make_fleet_base(3)
        result = enumerate_configs(base, [4.0, 5.0], [0.0, 5.0], [3.68, 5.0])
        for cp, sc in result:
            assert isinstance(cp, ConfigPoint)
            assert isinstance(sc, ScenarioConfig)

    def test_config_point_ordering_is_pv_battery_inverter(self) -> None:
        """ConfigPoints follow itertools.product(pv, battery, inverter) order."""
        base = _make_fleet_base(2)
        pv_vals = [4.0, 5.0]
        batt_vals = [0.0, 5.0]
        inv_vals = [3.68, 5.0]
        result = enumerate_configs(base, pv_vals, batt_vals, inv_vals)
        expected_points = [
            ConfigPoint(pv_kwp=p, battery_kwh=b, inverter_kw=i)
            for p, b, i in itertools.product(pv_vals, batt_vals, inv_vals)
        ]
        actual_points = [cp for cp, _ in result]
        assert actual_points == expected_points

    def test_each_scenario_has_same_number_of_homes_as_base(self) -> None:
        """Every returned scenario contains exactly as many homes as the base."""
        n = 3
        base = _make_fleet_base(n)
        result = enumerate_configs(base, [4.0, 5.0], [0.0, 5.0], [3.68, 5.0])
        for _, sc in result:
            assert len(sc.homes) == n

    def test_finance_config_preserved_with_cost_recovery_knobs(self) -> None:
        """FinanceConfig — including cost-recovery knobs — is preserved unchanged."""
        base = _make_fleet_base(2)
        result = enumerate_configs(base, [4.0], [5.0], [3.68])
        _, sc = result[0]
        assert sc.finance is not None
        assert sc.finance.own_use_rate_pence_per_kwh == pytest.approx(18.5)
        assert sc.finance.retained_cash_floor_per_home_per_year_gbp == pytest.approx(50.0)
        assert sc.finance.grid_services_income_per_kw_per_year_gbp == pytest.approx(12.0)

    def test_scenario_level_fields_preserved(self) -> None:
        """name, period, seg_tariff_pence_per_kwh are preserved in every scenario."""
        base = _make_fleet_base(2)
        result = enumerate_configs(base, [4.0, 5.0], [0.0], [3.68])
        for _, sc in result:
            assert sc.name == "test-fleet"
            assert sc.period.start_date == "2024-01-01"
            assert sc.seg_tariff_pence_per_kwh == pytest.approx(7.5)

    def test_empty_pv_list_raises(self) -> None:
        """Empty pv_kwp sequence raises ValueError."""
        base = _make_fleet_base(2)
        with pytest.raises(ValueError, match="pv_kwp"):
            enumerate_configs(base, [], [5.0], [3.68])

    def test_empty_battery_list_raises(self) -> None:
        """Empty battery_kwh sequence raises ValueError."""
        base = _make_fleet_base(2)
        with pytest.raises(ValueError, match="battery_kwh"):
            enumerate_configs(base, [4.0], [], [3.68])

    def test_empty_inverter_list_raises(self) -> None:
        """Empty inverter_kw sequence raises ValueError."""
        base = _make_fleet_base(2)
        with pytest.raises(ValueError, match="inverter_kw"):
            enumerate_configs(base, [4.0], [5.0], [])

    def test_single_home_base_raises(self) -> None:
        """A single-home base (home= not homes=) raises ValueError."""
        single_home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000),
        )
        base_single = ScenarioConfig(
            name="single",
            period=SimulationPeriod("2024-01-01", "2024-12-31"),
            home=single_home,
        )
        with pytest.raises(ValueError, match="fleet"):
            enumerate_configs(base_single, [4.0], [5.0], [3.68])


class TestPvInverterHomogenization:
    """Tests that PV and inverter are homogenized; load and dispatch are preserved."""

    def _make_diverse_base(self) -> ScenarioConfig:
        """Fleet with 3 homes: distinct PV sizes, loads, and dispatch strategies."""
        homes = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=3.0),
                load_config=LoadConfig(annual_consumption_kwh=2000, household_occupants=1),
                dispatch_strategy="greedy",
            ),
            HomeConfig(
                pv_config=PVConfig(capacity_kw=5.0),
                load_config=LoadConfig(annual_consumption_kwh=3500, household_occupants=3),
                dispatch_strategy="tou_optimized",
            ),
            HomeConfig(
                pv_config=PVConfig(capacity_kw=6.5, inverter_capacity_kw=5.0),
                load_config=LoadConfig(annual_consumption_kwh=4200, household_occupants=4),
                dispatch_strategy="greedy",
            ),
        ]
        return ScenarioConfig(
            name="diverse",
            period=SimulationPeriod("2024-06-01", "2024-06-30"),
            homes=homes,
        )

    def test_all_homes_get_homogenized_pv_capacity(self) -> None:
        """Every home has pv_config.capacity_kw == pv_kwp after enumeration."""
        base = self._make_diverse_base()
        result = enumerate_configs(base, [4.0, 5.0], [0.0], [3.68])
        for cp, sc in result:
            for home in sc.homes:
                assert home.pv_config.capacity_kw == pytest.approx(cp.pv_kwp)

    def test_all_homes_get_homogenized_inverter_capacity(self) -> None:
        """Every home has pv_config.inverter_capacity_kw == inverter_kw."""
        base = self._make_diverse_base()
        result = enumerate_configs(base, [4.0], [0.0], [3.68, 5.0])
        for cp, sc in result:
            for home in sc.homes:
                assert home.pv_config.inverter_capacity_kw == pytest.approx(cp.inverter_kw)

    def test_load_config_diversity_preserved(self) -> None:
        """Homes still have distinct LoadConfigs (occupancy/consumption unchanged)."""
        base = self._make_diverse_base()
        result = enumerate_configs(base, [4.0], [0.0], [3.68])
        _, sc = result[0]
        annual_consumptions = [h.load_config.annual_consumption_kwh for h in sc.homes]
        assert len(set(annual_consumptions)) > 1, "Loads should still differ"
        for orig, updated in zip(base.homes, sc.homes):
            assert orig.load_config == updated.load_config

    def test_dispatch_strategy_preserved(self) -> None:
        """HomeConfig.dispatch_strategy is unchanged per home."""
        base = self._make_diverse_base()
        result = enumerate_configs(base, [4.0], [0.0], [3.68])
        _, sc = result[0]
        for orig, updated in zip(base.homes, sc.homes):
            assert orig.dispatch_strategy == updated.dispatch_strategy

    def test_base_scenario_and_homes_not_mutated(self) -> None:
        """Base ScenarioConfig and its HomeConfig/PVConfig objects are never mutated."""
        base = self._make_diverse_base()
        orig_pv_capacities = [h.pv_config.capacity_kw for h in base.homes]
        orig_inverter_caps = [h.pv_config.inverter_capacity_kw for h in base.homes]
        _ = enumerate_configs(base, [4.0, 5.0], [0.0, 5.0], [3.68, 5.0])
        for i, home in enumerate(base.homes):
            assert home.pv_config.capacity_kw == pytest.approx(orig_pv_capacities[i])
            assert home.pv_config.inverter_capacity_kw == orig_inverter_caps[i]


class TestBatteryHomogenization:
    """Tests for battery homogenization in _apply_install / enumerate_configs."""

    def _make_mixed_battery_base(self) -> ScenarioConfig:
        """Fleet with one home that HAS a non-default battery and one without."""
        battery = BatteryConfig(
            capacity_kwh=7.0,
            max_discharge_kw=3.6,          # non-default
            grid_charging=GridChargeConfig(target_soc_fraction=0.8),
        )
        home_with_battery = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3000, household_occupants=2),
            battery_config=battery,
        )
        home_without_battery = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=2500, household_occupants=1),
            battery_config=None,
        )
        return ScenarioConfig(
            name="mixed-battery",
            period=SimulationPeriod("2024-01-01", "2024-12-31"),
            homes=[home_with_battery, home_without_battery],
        )

    def test_battery_kwh_zero_sets_all_battery_config_to_none(self) -> None:
        """battery_kwh==0.0 → every home has battery_config is None."""
        base = self._make_mixed_battery_base()
        result = enumerate_configs(base, [4.0], [0.0], [3.68])
        _, sc = result[0]
        for home in sc.homes:
            assert home.battery_config is None

    def test_battery_kwh_positive_preserves_existing_battery_fields(self) -> None:
        """battery_kwh>0 on the home with a battery preserves max_discharge_kw, grid_charging, dispatch_strategy."""
        base = self._make_mixed_battery_base()
        result = enumerate_configs(base, [4.0], [5.0], [3.68])
        _, sc = result[0]
        home_with = sc.homes[0]  # was home_with_battery
        assert home_with.battery_config is not None
        assert home_with.battery_config.capacity_kwh == pytest.approx(5.0)
        # Non-default base fields must be preserved
        assert home_with.battery_config.max_discharge_kw == pytest.approx(3.6)
        assert home_with.battery_config.grid_charging is not None
        assert home_with.battery_config.grid_charging.target_soc_fraction == pytest.approx(0.8)
        # dispatch_strategy carried over from base (None by default in fixture)
        assert home_with.battery_config.dispatch_strategy is None

    def test_battery_kwh_positive_fabricates_battery_for_battery_less_home(self) -> None:
        """battery_kwh>0 on the home WITHOUT a battery fabricates a BatteryConfig at defaults."""
        base = self._make_mixed_battery_base()
        result = enumerate_configs(base, [4.0], [5.0], [3.68])
        _, sc = result[0]
        home_without = sc.homes[1]  # was home_without_battery
        assert home_without.battery_config is not None
        assert home_without.battery_config.capacity_kwh == pytest.approx(5.0)
        # Fabricated battery must have the default max_discharge_kw (2.5)
        assert home_without.battery_config.max_discharge_kw == pytest.approx(2.5)
        # Fabricated battery must have no dispatch/grid-charging overrides (diverse dispatch preserved at None)
        assert home_without.battery_config.dispatch_strategy is None
        assert home_without.battery_config.grid_charging is None

    def test_small_positive_battery_kwh_fabricates_not_sentinel(self) -> None:
        """A small-positive battery_kwh (e.g. 1e-6) is NOT the no-battery sentinel.

        Only exactly 0.0 means no battery; any positive value — however small —
        triggers fabrication or replacement.  This pins the documented behaviour
        so a future epsilon-check regression is caught.
        """
        base = self._make_mixed_battery_base()
        tiny = 1e-6
        result = enumerate_configs(base, [4.0], [tiny], [3.68])
        _, sc = result[0]
        # Both homes must have a battery (not None) even though capacity is tiny
        for home in sc.homes:
            assert home.battery_config is not None, (
                f"Expected a battery for battery_kwh={tiny!r} but got None"
            )
            assert home.battery_config.capacity_kwh == pytest.approx(tiny)

    def test_base_battery_configs_not_mutated(self) -> None:
        """Original battery configs in base.homes are never mutated."""
        base = self._make_mixed_battery_base()
        orig_cap = base.homes[0].battery_config
        assert orig_cap is not None
        _ = enumerate_configs(base, [4.0, 5.0], [0.0, 5.0], [3.68])
        # Battery on home_with_battery must remain unchanged
        assert base.homes[0].battery_config is orig_cap
        assert base.homes[0].battery_config.capacity_kwh == pytest.approx(7.0)
        assert base.homes[1].battery_config is None
