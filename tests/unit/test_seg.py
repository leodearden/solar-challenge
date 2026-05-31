"""Tests for Smart Export Guarantee (SEG) tariff and revenue calculation."""

import pytest
from solar_challenge.seg import SEGTariff, SEG_PRESETS, calculate_seg_revenue, resolve_seg_tariff


class TestSEGTariffBasics:
    """Test SEGTariff dataclass creation and basic functionality."""

    def test_create_with_all_params(self):
        """SEGTariff can be created with name and rate."""
        tariff = SEGTariff(name="Test Supplier", rate_pence_per_kwh=5.0)
        assert tariff.name == "Test Supplier"
        assert tariff.rate_pence_per_kwh == 5.0

    def test_zero_rate_is_valid(self):
        """A zero rate is valid (non-negative)."""
        tariff = SEGTariff(name="Zero Rate", rate_pence_per_kwh=0.0)
        assert tariff.rate_pence_per_kwh == 0.0

    def test_fractional_rate(self):
        """Fractional rates are valid."""
        tariff = SEGTariff(name="Supplier", rate_pence_per_kwh=3.75)
        assert tariff.rate_pence_per_kwh == pytest.approx(3.75)

    def test_name_stored_correctly(self):
        """Name is stored exactly as provided."""
        tariff = SEGTariff(name="Octopus Energy", rate_pence_per_kwh=4.1)
        assert tariff.name == "Octopus Energy"


class TestSEGTariffValidation:
    """Test SEGTariff parameter validation."""

    def test_negative_rate_raises_value_error(self):
        """Negative rate raises ValueError."""
        with pytest.raises(ValueError):
            SEGTariff(name="Bad Rate", rate_pence_per_kwh=-1.0)

    def test_negative_rate_error_message(self):
        """ValueError message mentions the invalid rate."""
        with pytest.raises(ValueError, match="non-negative"):
            SEGTariff(name="Bad Rate", rate_pence_per_kwh=-0.5)

    def test_very_negative_rate_raises(self):
        """Strongly negative rate also raises ValueError."""
        with pytest.raises(ValueError):
            SEGTariff(name="Bad Rate", rate_pence_per_kwh=-100.0)


class TestSEGTariffImmutability:
    """Test that SEGTariff is frozen (immutable)."""

    def test_cannot_modify_rate(self):
        """Modifying rate raises FrozenInstanceError."""
        tariff = SEGTariff(name="Supplier", rate_pence_per_kwh=4.0)
        with pytest.raises(Exception):  # FrozenInstanceError is a subclass of AttributeError
            tariff.rate_pence_per_kwh = 5.0  # type: ignore

    def test_cannot_modify_name(self):
        """Modifying name raises FrozenInstanceError."""
        tariff = SEGTariff(name="Supplier", rate_pence_per_kwh=4.0)
        with pytest.raises(Exception):
            tariff.name = "Other Supplier"  # type: ignore


class TestSEGPresets:
    """Test SEG_PRESETS dictionary of UK supplier tariffs."""

    def test_presets_is_dict(self):
        """SEG_PRESETS is a dictionary."""
        assert isinstance(SEG_PRESETS, dict)

    def test_contains_octopus(self):
        """Octopus Energy is in presets."""
        assert "Octopus" in SEG_PRESETS

    def test_contains_british_gas(self):
        """British Gas is in presets."""
        assert "British Gas" in SEG_PRESETS

    def test_contains_edf(self):
        """EDF is in presets."""
        assert "EDF" in SEG_PRESETS

    def test_contains_eon(self):
        """E.ON is in presets."""
        assert "E.ON" in SEG_PRESETS

    def test_contains_scottish_power(self):
        """Scottish Power is in presets."""
        assert "Scottish Power" in SEG_PRESETS

    def test_contains_ovo(self):
        """OVO Energy is in presets."""
        assert "OVO" in SEG_PRESETS

    def test_all_presets_are_seg_tariffs(self):
        """All presets are SEGTariff instances."""
        for key, tariff in SEG_PRESETS.items():
            assert isinstance(tariff, SEGTariff), f"Preset '{key}' is not a SEGTariff"

    def test_all_presets_have_positive_rates(self):
        """All preset rates are positive (> 0)."""
        for key, tariff in SEG_PRESETS.items():
            assert tariff.rate_pence_per_kwh > 0, f"Preset '{key}' has non-positive rate"

    def test_octopus_rate(self):
        """Octopus Energy rate is as expected."""
        assert SEG_PRESETS["Octopus"].rate_pence_per_kwh == pytest.approx(4.1)

    def test_british_gas_rate(self):
        """British Gas rate is as expected."""
        assert SEG_PRESETS["British Gas"].rate_pence_per_kwh == pytest.approx(3.0)

    def test_ovo_rate(self):
        """OVO Energy rate is as expected."""
        assert SEG_PRESETS["OVO"].rate_pence_per_kwh == pytest.approx(4.0)

    def test_all_presets_have_names(self):
        """All presets have non-empty names."""
        for key, tariff in SEG_PRESETS.items():
            assert tariff.name, f"Preset '{key}' has empty name"

    def test_at_least_six_presets(self):
        """At least six UK suppliers are in presets."""
        assert len(SEG_PRESETS) >= 6


class TestCalculateSEGRevenue:
    """Test calculate_seg_revenue() function."""

    @pytest.fixture
    def octopus_tariff(self) -> SEGTariff:
        """Octopus Energy tariff at 4.1 p/kWh."""
        return SEGTariff(name="Octopus Energy", rate_pence_per_kwh=4.1)

    @pytest.fixture
    def flat_tariff(self) -> SEGTariff:
        """Simple 10 p/kWh tariff for easy calculation."""
        return SEGTariff(name="Test Flat Rate", rate_pence_per_kwh=10.0)

    def test_returns_float(self, flat_tariff):
        """Revenue calculation returns a float."""
        revenue = calculate_seg_revenue(100.0, flat_tariff)
        assert isinstance(revenue, float)

    def test_basic_calculation(self, flat_tariff):
        """Revenue = export_kwh * rate / 100."""
        # 100 kWh * 10 p/kWh = 1000 pence = £10.00
        revenue = calculate_seg_revenue(100.0, flat_tariff)
        assert revenue == pytest.approx(10.0)

    def test_zero_export_returns_zero(self, octopus_tariff):
        """Zero export returns zero revenue."""
        revenue = calculate_seg_revenue(0.0, octopus_tariff)
        assert revenue == 0.0

    def test_octopus_rate_calculation(self, octopus_tariff):
        """Calculation correct with Octopus 4.1 p/kWh rate."""
        # 1000 kWh * 4.1 p/kWh = 4100 pence = £41.00
        revenue = calculate_seg_revenue(1000.0, octopus_tariff)
        assert revenue == pytest.approx(41.0)

    def test_result_in_pounds(self, flat_tariff):
        """Result is in GBP (pounds), not pence."""
        # 100 kWh * 10 p/kWh = £10.00
        revenue = calculate_seg_revenue(100.0, flat_tariff)
        assert revenue == pytest.approx(10.0)

    def test_negative_export_raises_value_error(self, flat_tariff):
        """Negative export_kwh raises ValueError."""
        with pytest.raises(ValueError):
            calculate_seg_revenue(-1.0, flat_tariff)

    def test_negative_export_error_message(self, flat_tariff):
        """ValueError message mentions non-negative requirement."""
        with pytest.raises(ValueError, match="non-negative"):
            calculate_seg_revenue(-100.0, flat_tariff)

    def test_small_export_value(self, flat_tariff):
        """Small export values produce correct small revenue."""
        # 1 kWh * 10 p/kWh = £0.10
        revenue = calculate_seg_revenue(1.0, flat_tariff)
        assert revenue == pytest.approx(0.10)

    def test_large_export_value(self, flat_tariff):
        """Large export values produce correct large revenue."""
        # 10000 kWh * 10 p/kWh = £1000.00
        revenue = calculate_seg_revenue(10000.0, flat_tariff)
        assert revenue == pytest.approx(1000.0)

    def test_fractional_export(self):
        """Fractional export values are handled correctly."""
        tariff = SEGTariff(name="Supplier", rate_pence_per_kwh=5.0)
        # 2.5 kWh * 5 p/kWh = 12.5 pence = £0.125
        revenue = calculate_seg_revenue(2.5, tariff)
        assert revenue == pytest.approx(0.125)

    def test_with_preset_tariff(self):
        """Works correctly using a preset tariff from SEG_PRESETS."""
        tariff = SEG_PRESETS["Octopus"]
        # 1000 kWh * 4.1 p/kWh = £41.00
        revenue = calculate_seg_revenue(1000.0, tariff)
        assert revenue == pytest.approx(41.0)

    def test_with_all_presets(self):
        """Revenue is positive for all presets with positive export."""
        for key, tariff in SEG_PRESETS.items():
            revenue = calculate_seg_revenue(100.0, tariff)
            assert revenue > 0, f"Preset '{key}' produced non-positive revenue"

    def test_zero_rate_returns_zero_revenue(self):
        """Zero tariff rate returns zero revenue regardless of export."""
        tariff = SEGTariff(name="Zero Rate", rate_pence_per_kwh=0.0)
        revenue = calculate_seg_revenue(1000.0, tariff)
        assert revenue == 0.0

    def test_revenue_scales_linearly_with_export(self):
        """Revenue scales linearly with export amount."""
        tariff = SEGTariff(name="Supplier", rate_pence_per_kwh=5.0)
        revenue_100 = calculate_seg_revenue(100.0, tariff)
        revenue_200 = calculate_seg_revenue(200.0, tariff)
        assert revenue_200 == pytest.approx(revenue_100 * 2)

    def test_revenue_scales_linearly_with_rate(self):
        """Revenue scales linearly with tariff rate."""
        tariff_low = SEGTariff(name="Low", rate_pence_per_kwh=2.0)
        tariff_high = SEGTariff(name="High", rate_pence_per_kwh=4.0)
        revenue_low = calculate_seg_revenue(100.0, tariff_low)
        revenue_high = calculate_seg_revenue(100.0, tariff_high)
        assert revenue_high == pytest.approx(revenue_low * 2)

    def test_annual_export_typical_home(self):
        """Typical UK home annual export produces reasonable revenue."""
        # Typical 3.5 kWp system might export ~1200 kWh/year
        tariff = SEG_PRESETS["Octopus"]
        revenue = calculate_seg_revenue(1200.0, tariff)
        # At 4.1 p/kWh: 1200 * 4.1 / 100 = £49.20
        assert revenue == pytest.approx(49.20)


class TestResolveSEGTariff:
    """Test resolve_seg_tariff() resolver for named SEG presets."""

    def test_octopus_returns_correct_tariff(self):
        """resolve_seg_tariff('Octopus') returns SEGTariff with 4.1 p/kWh."""
        tariff = resolve_seg_tariff("Octopus")
        assert isinstance(tariff, SEGTariff)
        assert tariff.rate_pence_per_kwh == pytest.approx(4.1)

    def test_octopus_equals_preset(self):
        """resolve_seg_tariff('Octopus') returns same object as SEG_PRESETS['Octopus']."""
        tariff = resolve_seg_tariff("Octopus")
        assert tariff == SEG_PRESETS["Octopus"]

    def test_all_preset_keys_resolve(self):
        """Every key in SEG_PRESETS resolves to its corresponding SEGTariff."""
        for name, expected in SEG_PRESETS.items():
            resolved = resolve_seg_tariff(name)
            assert resolved == expected, f"Resolved tariff for '{name}' does not match preset"

    def test_unknown_name_raises_value_error(self):
        """An unknown supplier name raises ValueError."""
        with pytest.raises(ValueError):
            resolve_seg_tariff("NoSuchSupplier")

    def test_unknown_name_error_message_mentions_name(self):
        """ValueError message mentions the unknown name."""
        with pytest.raises(ValueError, match="NoSuchSupplier"):
            resolve_seg_tariff("NoSuchSupplier")

    def test_unknown_name_error_message_lists_available(self):
        """ValueError message lists at least one available preset name."""
        with pytest.raises(ValueError, match="Octopus"):
            resolve_seg_tariff("UnknownSupplier")
