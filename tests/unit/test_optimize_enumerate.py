"""Tests for optimize.enumerate_configs and ConfigPoint."""

import dataclasses

import pytest

from solar_challenge.optimize import ConfigPoint


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
