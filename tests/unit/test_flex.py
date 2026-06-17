"""Tests for flex.py flexibility value-model (banded Low/Central/High + grid-services £/kW resolver).

Canonical numbers from consulting model §1.1/§1.4 and PRD §6
(all £/battery-home/yr unless noted).
"""

import dataclasses

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

    # --- immutability (frozen=True) ---

    def test_name_is_immutable(self):
        """Assigning name raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.name = "other"  # noqa: no assignment to frozen field

    def test_time_shift_gbp_is_immutable(self):
        """Assigning time_shift_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.time_shift_gbp = 999.0  # noqa: no assignment to frozen field

    def test_grid_services_per_kw_gbp_is_immutable(self):
        """Assigning grid_services_per_kw_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.grid_services_per_kw_gbp = 0.0  # noqa: no assignment to frozen field

    def test_total_gbp_is_immutable(self):
        """Assigning total_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.total_gbp = 0.0  # noqa: no assignment to frozen field

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


class TestFlexValueBands:
    """Test FLEX_VALUE_BANDS canonical constants and REPRESENTATIVE_DISCHARGE_POWER_KW.

    Numbers from consulting §1.1/§1.4 and PRD §6 (all £/battery-home/yr).
    """

    # --- module constant ---

    def test_representative_discharge_power_kw(self):
        """REPRESENTATIVE_DISCHARGE_POWER_KW is 2.5 (matches BatteryConfig default)."""
        assert REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(2.5)

    # --- FLEX_VALUE_BANDS dict structure ---

    def test_flex_value_bands_is_dict(self):
        """FLEX_VALUE_BANDS is a dict."""
        assert isinstance(FLEX_VALUE_BANDS, dict)

    def test_has_low_band(self):
        """FLEX_VALUE_BANDS has 'low' key."""
        assert "low" in FLEX_VALUE_BANDS

    def test_has_central_band(self):
        """FLEX_VALUE_BANDS has 'central' key."""
        assert "central" in FLEX_VALUE_BANDS

    def test_has_high_band(self):
        """FLEX_VALUE_BANDS has 'high' key."""
        assert "high" in FLEX_VALUE_BANDS

    def test_has_exactly_three_bands(self):
        """FLEX_VALUE_BANDS has exactly three entries."""
        assert len(FLEX_VALUE_BANDS) == 3

    def test_all_values_are_flex_value_bands(self):
        """Every value in FLEX_VALUE_BANDS is a FlexibilityValueBand instance."""
        for key, band in FLEX_VALUE_BANDS.items():
            assert isinstance(band, FlexibilityValueBand), (
                f"FLEX_VALUE_BANDS['{key}'] is not a FlexibilityValueBand"
            )

    # --- Per-band canonical values (consulting §1.1 + PRD §6) ---

    @pytest.mark.parametrize("band,expected", [
        ("low",     {"time_shift_gbp": 100.0, "grid_services_per_home_gbp":   4.0, "grid_services_per_kw_gbp":  1.5, "total_gbp": 120.0}),  # noqa: E241
        ("central", {"time_shift_gbp": 250.0, "grid_services_per_home_gbp":  30.0, "grid_services_per_kw_gbp": 12.0, "total_gbp": 280.0}),  # noqa: E241
        ("high",    {"time_shift_gbp": 330.0, "grid_services_per_home_gbp": 120.0, "grid_services_per_kw_gbp": 48.0, "total_gbp": 450.0}),  # noqa: E241
    ])
    def test_band_canonical_values(self, band: str, expected: dict[str, float]) -> None:
        """Canonical monetary fields for each band match consulting §1.1 + PRD §6."""
        fb = FLEX_VALUE_BANDS[band]
        for field, value in expected.items():
            assert getattr(fb, field) == pytest.approx(value), f"{band}.{field}"
        assert fb.provenance  # non-empty provenance string

    def test_total_gbp_not_less_than_time_shift(self) -> None:
        """total_gbp >= time_shift_gbp for every band (grid services always add value)."""
        for band, fb in FLEX_VALUE_BANDS.items():
            assert fb.total_gbp >= fb.time_shift_gbp, (
                f"{band}: total_gbp ({fb.total_gbp}) < time_shift_gbp ({fb.time_shift_gbp})"
            )


class TestResolveGridServicesBand:
    """Test resolve_grid_services_band and resolve_flex_band resolvers.

    Pinned signal: resolve_grid_services_band("central") == 12.0 (PRD §6).
    Per-home cross-check: rate × 2.5 ≈ per-home within ±£1.0 (consulting §1.1 banding).
    """

    # --- resolve_grid_services_band return type and pinned values ---

    def test_returns_float(self):
        """resolve_grid_services_band returns a float."""
        result = resolve_grid_services_band("central")
        assert isinstance(result, float)

    def test_central_pinned_signal(self):
        """Central band returns exactly £12.0/kW/yr — the PRD §6 pinned signal."""
        assert resolve_grid_services_band("central") == pytest.approx(12.0)

    def test_low_rate(self):
        """Low band returns £1.5/kW/yr (PRD §6)."""
        assert resolve_grid_services_band("low") == pytest.approx(1.5)

    def test_high_rate(self):
        """High band returns £48.0/kW/yr (PRD §6)."""
        assert resolve_grid_services_band("high") == pytest.approx(48.0)

    def test_each_band_matches_flex_value_bands(self):
        """resolve_grid_services_band(band) equals FLEX_VALUE_BANDS[band].grid_services_per_kw_gbp."""
        for band in ("low", "central", "high"):
            assert resolve_grid_services_band(band) == pytest.approx(
                FLEX_VALUE_BANDS[band].grid_services_per_kw_gbp
            ), f"Mismatch for band '{band}'"

    # --- per-home cross-check: rate × 2.5 ≈ per-home within ±£1.0 ---

    def test_low_per_home_cross_check(self):
        """Low: rate × REPRESENTATIVE_DISCHARGE_POWER_KW ≈ grid_services_per_home_gbp (±£1.0)."""
        rate = resolve_grid_services_band("low")
        per_home = FLEX_VALUE_BANDS["low"].grid_services_per_home_gbp
        assert rate * REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(per_home, abs=1.0)

    def test_central_per_home_cross_check(self):
        """Central: rate × REPRESENTATIVE_DISCHARGE_POWER_KW ≈ grid_services_per_home_gbp (exact)."""
        rate = resolve_grid_services_band("central")
        per_home = FLEX_VALUE_BANDS["central"].grid_services_per_home_gbp
        assert rate * REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(per_home, abs=1.0)

    def test_high_per_home_cross_check(self):
        """High: rate × REPRESENTATIVE_DISCHARGE_POWER_KW ≈ grid_services_per_home_gbp (exact)."""
        rate = resolve_grid_services_band("high")
        per_home = FLEX_VALUE_BANDS["high"].grid_services_per_home_gbp
        assert rate * REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(per_home, abs=1.0)

    # --- unknown band raises ValueError ---

    def test_unknown_band_raises_value_error(self):
        """Unknown band name raises ValueError."""
        with pytest.raises(ValueError):
            resolve_grid_services_band("ultra")

    def test_unknown_band_error_mentions_band(self):
        """ValueError message mentions the unknown band name."""
        with pytest.raises(ValueError, match="ultra"):
            resolve_grid_services_band("ultra")

    def test_unknown_band_error_lists_available(self):
        """ValueError message lists available band names."""
        with pytest.raises(ValueError, match="central"):
            resolve_grid_services_band("bogus")

    # --- resolve_flex_band ---

    def test_resolve_flex_band_returns_flex_value_band(self):
        """resolve_flex_band returns a FlexibilityValueBand instance."""
        result = resolve_flex_band("central")
        assert isinstance(result, FlexibilityValueBand)

    def test_resolve_flex_band_central(self):
        """resolve_flex_band('central') returns the central preset."""
        assert resolve_flex_band("central") == FLEX_VALUE_BANDS["central"]

    def test_resolve_flex_band_all_bands(self):
        """resolve_flex_band resolves every band key to its preset."""
        for band, expected in FLEX_VALUE_BANDS.items():
            assert resolve_flex_band(band) == expected

    def test_resolve_flex_band_unknown_raises(self):
        """resolve_flex_band raises ValueError on unknown band."""
        with pytest.raises(ValueError, match="unknown_band"):
            resolve_flex_band("unknown_band")
