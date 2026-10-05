# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_config, called directly."""

import pytest

pytest.importorskip("flask")

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.fleet_config import apply_fleet_overlay


def _make_test_homes() -> tuple:
    """Build two HomeConfig instances for overlay tests.

    Returns:
        (home_a, home_b) where home_a has a BatteryConfig and home_b does not.
    """
    pv_a = PVConfig(capacity_kw=4.0)
    pv_b = PVConfig(capacity_kw=3.0)
    load_a = LoadConfig(annual_consumption_kwh=3500.0)
    load_b = LoadConfig(annual_consumption_kwh=2800.0)
    battery_a = BatteryConfig(capacity_kwh=5.0)

    home_a = HomeConfig(pv_config=pv_a, load_config=load_a, battery_config=battery_a)
    home_b = HomeConfig(pv_config=pv_b, load_config=load_b, battery_config=None)
    return home_a, home_b


class TestApplyFleetOverlay:
    """Unit tests for the pure helper apply_fleet_overlay in web/fleet_config.py."""

    def test_tariff_applied_to_all_homes(self) -> None:
        """Passing tariff_config sets tariff_config on every home in the fleet."""
        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)

        result = apply_fleet_overlay([home_a, home_b], tariff_config=tariff)

        assert len(result) == 2
        assert result[0].tariff_config is tariff
        assert result[1].tariff_config is tariff

    def test_dispatch_applied_only_to_homes_with_battery(self) -> None:
        """dispatch_strategy is set on BatteryConfig only when battery_config is not None."""
        home_a, home_b = _make_test_homes()
        dispatch = DispatchStrategyConfig(
            strategy_type="tou_optimized", peak_hours=[(16, 21)]
        )

        result = apply_fleet_overlay([home_a, home_b], dispatch_strategy=dispatch)

        # Home A (has battery) — dispatch_strategy applied
        assert result[0].battery_config is not None
        assert result[0].battery_config.dispatch_strategy is dispatch
        # Home B (no battery) — battery_config stays None, no fabricated battery
        assert result[1].battery_config is None

    def test_seg_tariff_applied_to_all_homes(self) -> None:
        """Passing seg_tariff sets seg_tariff on every home in the fleet."""
        home_a, home_b = _make_test_homes()
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        result = apply_fleet_overlay([home_a, home_b], seg_tariff=seg)

        assert result[0].seg_tariff is seg
        assert result[1].seg_tariff is seg

    def test_original_homes_are_immutable(self) -> None:
        """After the call the original HomeConfig objects are unchanged (frozen dataclass)."""
        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        apply_fleet_overlay([home_a, home_b], tariff_config=tariff, seg_tariff=seg)

        # Originals must be unchanged
        assert home_a.tariff_config is None
        assert home_a.seg_tariff is None
        assert home_b.tariff_config is None
        assert home_b.seg_tariff is None

    def test_all_none_overlay_is_noop(self) -> None:
        """Calling with all None args returns homes that match the inputs field-for-field."""
        home_a, home_b = _make_test_homes()

        result = apply_fleet_overlay([home_a, home_b])

        # Should return the same objects (or equal ones) — no mutations
        assert result[0] is home_a
        assert result[1] is home_b
