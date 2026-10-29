"""Tests for flex.py flexibility value-model (banded Low/Central/High, read with resolve_flex_band).

Canonical numbers from consulting model §1.1/§1.4 and
docs/prds/flexibility-value-finance-integration.md §6 (all £/battery-home/yr unless noted).
"""

import dataclasses
from collections.abc import Mapping

import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.flex import (
    FlexibilityValueBand,
    FLEX_VALUE_BANDS,
    REPRESENTATIVE_DISCHARGE_POWER_KW,
    resolve_flex_band,
)
from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS, GridServicesBand
from tests._unusable_numbers import UNUSABLE_NUMBERS


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
            band.name = "other"

    def test_time_shift_gbp_is_immutable(self):
        """Assigning time_shift_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.time_shift_gbp = 999.0

    def test_grid_services_per_kw_gbp_is_immutable(self):
        """Assigning grid_services_per_kw_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.grid_services_per_kw_gbp = 0.0

    def test_total_gbp_is_immutable(self):
        """Assigning total_gbp raises FrozenInstanceError (frozen dataclass)."""
        band = self._make_band()
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.total_gbp = 0.0

    # --- validation: negative monetary fields ---

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("time_shift_gbp", -1.0),
            ("grid_services_per_home_gbp", -0.01),
            ("grid_services_per_kw_gbp", -5.0),
            ("total_gbp", -1.0),
        ],
    )
    def test_a_negative_amount_is_refused_naming_its_bound(self, field, value):
        with pytest.raises(ConfigurationError) as exc_info:
            self._make_band(**{field: value})
        assert str(exc_info.value) == f"{field} must be at least 0, got {value!r}"

    @pytest.mark.parametrize(
        "field", ["time_shift_gbp", "grid_services_per_home_gbp", "grid_services_per_kw_gbp", "total_gbp"]
    )
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_an_amount_that_is_not_a_finite_number_is_refused_naming_it(self, field, value):
        with pytest.raises(ConfigurationError) as exc_info:
            self._make_band(**{field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    def test_a_whole_amount_is_held_as_the_float_it_reads(self):
        time_shift = self._make_band(time_shift_gbp=100).time_shift_gbp
        assert time_shift == 100.0
        assert type(time_shift) is float

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
        """Empty name string raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="name"):
            self._make_band(name="")

    def test_empty_provenance_raises(self):
        """Empty provenance string raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="provenance"):
            self._make_band(provenance="")


class TestFlexValueBands:
    """Test FLEX_VALUE_BANDS canonical constants and REPRESENTATIVE_DISCHARGE_POWER_KW.

    Numbers from consulting §1.1/§1.4 and docs/prds/flexibility-value-finance-integration.md §6
    (all £/battery-home/yr).
    """

    # --- module constant ---

    def test_representative_discharge_power_kw(self):
        """REPRESENTATIVE_DISCHARGE_POWER_KW is 2.5 (matches BatteryConfig default)."""
        assert REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(2.5)

    # --- FLEX_VALUE_BANDS mapping structure ---

    def test_flex_value_bands_is_a_read_only_mapping_keyed_by_band_in_band_order(self):
        """FLEX_VALUE_BANDS is a read-only Mapping whose keys are the GridServicesBand members, in band order.

        A str key compares equal to its member, so only the keys' type tells them apart.
        """
        assert isinstance(FLEX_VALUE_BANDS, Mapping)
        with pytest.raises(TypeError):
            FLEX_VALUE_BANDS[GridServicesBand.LOW] = FLEX_VALUE_BANDS[GridServicesBand.LOW]
        assert list(FLEX_VALUE_BANDS) == list(GridServicesBand)
        assert all(type(key) is GridServicesBand for key in FLEX_VALUE_BANDS)

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

    # --- Per-band canonical values (consulting §1.1 + docs/prds/flexibility-value-finance-integration.md §6) ---

    @pytest.mark.parametrize("band,expected", [
        ("low",     {"time_shift_gbp": 100.0, "grid_services_per_home_gbp":   4.0, "grid_services_per_kw_gbp":  1.5, "total_gbp": 120.0}),  # noqa: E241
        ("central", {"time_shift_gbp": 250.0, "grid_services_per_home_gbp":  30.0, "grid_services_per_kw_gbp": 12.0, "total_gbp": 280.0}),  # noqa: E241
        ("high",    {"time_shift_gbp": 330.0, "grid_services_per_home_gbp": 120.0, "grid_services_per_kw_gbp": 48.0, "total_gbp": 450.0}),  # noqa: E241
    ])
    def test_band_canonical_values(self, band: str, expected: dict[str, float]) -> None:
        """Canonical monetary fields for each band match consulting §1.1 and the PRD.

        PRD: docs/prds/flexibility-value-finance-integration.md §6.
        """
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

    # --- the per-kW rate is the rate table's flat rate (docs/prds/grid-services-pricing-model.md §9 P5) ---

    @pytest.mark.parametrize("band", list(GridServicesBand))
    def test_each_band_reads_its_per_kw_rate_from_the_rate_table(self, band: GridServicesBand) -> None:
        """A band's grid_services_per_kw_gbp is GRID_SERVICES_RATE_BANDS' flat rate for it, and its name is the band's value."""
        assert (
            FLEX_VALUE_BANDS[band].grid_services_per_kw_gbp
            == GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year
        )
        assert FLEX_VALUE_BANDS[band].name == band.value

    # --- per-home cross-check: rate × 2.5 ≈ per-home within ±£1.0 (consulting §1.1 banding) ---

    @pytest.mark.parametrize("band", list(GridServicesBand))
    def test_per_kw_rate_at_the_representative_power_is_the_per_home_figure(
        self, band: GridServicesBand
    ) -> None:
        """grid_services_per_kw_gbp × REPRESENTATIVE_DISCHARGE_POWER_KW ≈ grid_services_per_home_gbp (±£1.0).

        Low: 1.5 × 2.5 = 3.75 ≈ 4; central (30.0) and high (120.0) are exact.
        """
        flex_band = FLEX_VALUE_BANDS[band]
        assert flex_band.grid_services_per_kw_gbp * REPRESENTATIVE_DISCHARGE_POWER_KW == pytest.approx(
            flex_band.grid_services_per_home_gbp, abs=1.0
        )


class TestResolveFlexBand:
    """resolve_flex_band returns FLEX_VALUE_BANDS' entry for a band, and refuses any other value naming the bands."""

    @pytest.mark.parametrize("band", list(GridServicesBand))
    def test_returns_the_entry_a_band_string_names(self, band: GridServicesBand) -> None:
        assert resolve_flex_band(band.value) is FLEX_VALUE_BANDS[band]

    @pytest.mark.parametrize("band", list(GridServicesBand))
    def test_returns_the_entry_of_a_band_member(self, band: GridServicesBand) -> None:
        assert resolve_flex_band(band) is FLEX_VALUE_BANDS[band]

    def test_refuses_an_unknown_band_naming_the_bands(self) -> None:
        with pytest.raises(ConfigurationError) as excinfo:
            resolve_flex_band("medium")

        assert str(excinfo.value) == "flexibility band must be one of low, central, high, got 'medium'"
