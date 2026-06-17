"""Tests for flex.py flexibility value-model (banded Low/Central/High + grid-services £/kW resolver).

Canonical numbers from consulting model §1.1/§1.4 and PRD §6
(all £/battery-home/yr unless noted).
"""

import pytest
from solar_challenge.flex import (
    FlexibilityValueBand,
    FLEX_VALUE_BANDS,
    REPRESENTATIVE_DISCHARGE_POWER_KW,
    resolve_flex_band,
    resolve_grid_services_band,
)


class TestFlexibilityValueBand:
    """Test FlexibilityValueBand frozen dataclass construction, storage, and validation."""

    def _make_band(self, **overrides):
        """Helper: construct a valid FlexibilityValueBand, applying overrides."""
        defaults = dict(
            name="test",
            time_shift_gbp=100.0,
            grid_services_per_home_gbp=4.0,
            grid_services_per_kw_gbp=1.5,
            total_gbp=120.0,
            provenance="consulting §1.1",
        )
        defaults.update(overrides)
        return FlexibilityValueBand(**defaults)

    # --- construction & field storage ---

    def test_constructs_with_all_fields(self):
        """FlexibilityValueBand constructs with all documented fields."""
        band = self._make_band()
        assert band.name == "test"
        assert band.time_shift_gbp == pytest.approx(100.0)
        assert band.grid_services_per_home_gbp == pytest.approx(4.0)
        assert band.grid_services_per_kw_gbp == pytest.approx(1.5)
        assert band.total_gbp == pytest.approx(120.0)
        assert band.provenance == "consulting §1.1"

    def test_stores_name(self):
        """name field is stored exactly."""
        band = self._make_band(name="central")
        assert band.name == "central"

    def test_stores_time_shift_gbp(self):
        """time_shift_gbp is stored exactly."""
        band = self._make_band(time_shift_gbp=250.0)
        assert band.time_shift_gbp == pytest.approx(250.0)

    def test_stores_grid_services_per_home_gbp(self):
        """grid_services_per_home_gbp is stored exactly."""
        band = self._make_band(grid_services_per_home_gbp=30.0)
        assert band.grid_services_per_home_gbp == pytest.approx(30.0)

    def test_stores_grid_services_per_kw_gbp(self):
        """grid_services_per_kw_gbp is stored exactly."""
        band = self._make_band(grid_services_per_kw_gbp=12.0)
        assert band.grid_services_per_kw_gbp == pytest.approx(12.0)

    def test_stores_total_gbp(self):
        """total_gbp is stored exactly."""
        band = self._make_band(total_gbp=280.0)
        assert band.total_gbp == pytest.approx(280.0)

    def test_stores_provenance(self):
        """provenance is stored exactly."""
        band = self._make_band(provenance="PRD §6")
        assert band.provenance == "PRD §6"

    # --- immutability (frozen=True) ---

    def test_name_is_immutable(self):
        """Assigning name raises (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(Exception):
            band.name = "other"  # type: ignore

    def test_time_shift_gbp_is_immutable(self):
        """Assigning time_shift_gbp raises (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(Exception):
            band.time_shift_gbp = 999.0  # type: ignore

    def test_grid_services_per_kw_gbp_is_immutable(self):
        """Assigning grid_services_per_kw_gbp raises (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(Exception):
            band.grid_services_per_kw_gbp = 0.0  # type: ignore

    def test_total_gbp_is_immutable(self):
        """Assigning total_gbp raises (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(Exception):
            band.total_gbp = 0.0  # type: ignore

    # --- validation: negative monetary fields ---

    def test_negative_time_shift_raises(self):
        """Negative time_shift_gbp raises ValueError."""
        with pytest.raises(ValueError, match="time_shift_gbp"):
            self._make_band(time_shift_gbp=-1.0)

    def test_negative_grid_services_per_home_raises(self):
        """Negative grid_services_per_home_gbp raises ValueError."""
        with pytest.raises(ValueError, match="grid_services_per_home_gbp"):
            self._make_band(grid_services_per_home_gbp=-0.01)

    def test_negative_grid_services_per_kw_raises(self):
        """Negative grid_services_per_kw_gbp raises ValueError."""
        with pytest.raises(ValueError, match="grid_services_per_kw_gbp"):
            self._make_band(grid_services_per_kw_gbp=-5.0)

    def test_negative_total_gbp_raises(self):
        """Negative total_gbp raises ValueError."""
        with pytest.raises(ValueError, match="total_gbp"):
            self._make_band(total_gbp=-1.0)

    def test_zero_monetary_fields_are_valid(self):
        """Zero values for monetary fields are valid (non-negative)."""
        band = self._make_band(
            time_shift_gbp=0.0,
            grid_services_per_home_gbp=0.0,
            grid_services_per_kw_gbp=0.0,
            total_gbp=0.0,
        )
        assert band.time_shift_gbp == 0.0
        assert band.total_gbp == 0.0

    # --- validation: empty name/provenance ---

    def test_empty_name_raises(self):
        """Empty name string raises ValueError."""
        with pytest.raises(ValueError, match="name"):
            self._make_band(name="")

    def test_empty_provenance_raises(self):
        """Empty provenance string raises ValueError."""
        with pytest.raises(ValueError, match="provenance"):
            self._make_band(provenance="")
