"""Tests for heat pump configuration and modelling."""

import doctest
import re

import numpy as np
import pandas as pd
import pytest
import solar_challenge.heat_pump
from solar_challenge.heat_pump import (
    HeatPumpConfig,
    BASE_TEMPERATURE_C,
    ASHP_COP_INTERCEPT,
    ASHP_COP_SLOPE,
    ASHP_COP_MIN,
    ASHP_COP_MAX,
    GSHP_COP_BASE,
    GSHP_COP_MIN,
    GSHP_COP_MAX,
    calculate_heating_degree_minutes,
    calculate_cop,
    generate_heat_pump_load,
)


class TestHeatPumpConfigBasics:
    """Test basic HeatPumpConfig functionality."""

    def test_create_with_all_params(self):
        """HeatPumpConfig can be created with all parameters."""
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=10.0,
            annual_heat_demand_kwh=12000.0,
            name="Test heat pump"
        )
        assert config.heat_pump_type == "ASHP"
        assert config.thermal_capacity_kw == 10.0
        assert config.annual_heat_demand_kwh == 12000.0
        assert config.name == "Test heat pump"

    def test_create_gshp(self):
        """HeatPumpConfig can be created with GSHP type."""
        config = HeatPumpConfig(
            heat_pump_type="GSHP",
            thermal_capacity_kw=8.0,
        )
        assert config.heat_pump_type == "GSHP"
        assert config.thermal_capacity_kw == 8.0

    def test_default_values(self):
        """HeatPumpConfig uses sensible defaults."""
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=8.0
        )
        assert config.annual_heat_demand_kwh == 8000.0  # Typical UK home
        assert config.name == ""


class TestHeatPumpConfigDefaults:
    """Test default heat pump configurations."""

    def test_default_ashp(self):
        """Default ASHP has correct values."""
        config = HeatPumpConfig.default_ashp()
        assert config.heat_pump_type == "ASHP"
        assert config.thermal_capacity_kw == 8.0
        assert config.annual_heat_demand_kwh == 8000.0
        assert config.name  # Has a name

    def test_default_gshp(self):
        """Default GSHP has correct values."""
        config = HeatPumpConfig.default_gshp()
        assert config.heat_pump_type == "GSHP"
        assert config.thermal_capacity_kw == 8.0
        assert config.annual_heat_demand_kwh == 8000.0
        assert config.name  # Has a name


class TestHeatPumpConfigValidation:
    """Test parameter validation."""

    def test_invalid_heat_pump_type(self):
        """Invalid heat pump type raises error."""
        with pytest.raises(ValueError, match="Heat pump type"):
            HeatPumpConfig(
                heat_pump_type="WSHP",  # Invalid type
                thermal_capacity_kw=8.0
            )

    def test_capacity_must_be_positive(self):
        """Thermal capacity <= 0 raises error."""
        with pytest.raises(ValueError, match="capacity must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=0
            )
        with pytest.raises(ValueError, match="capacity must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=-5.0
            )

    def test_capacity_unrealistic_high_raises(self):
        """Unrealistically high capacity raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=100.0
            )

    def test_annual_demand_must_be_positive(self):
        """Annual heat demand <= 0 raises error."""
        with pytest.raises(ValueError, match="demand must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=0
            )
        with pytest.raises(ValueError, match="demand must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=-1000.0
            )

    def test_annual_demand_unrealistic_high_raises(self):
        """Unrealistically high annual demand raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=100000.0
            )


class TestCalculateCOP:
    """Test COP calculation for different heat pump types."""

    def test_ashp_cop_at_zero_degrees(self):
        """ASHP COP at 0°C matches intercept."""
        cop = calculate_cop("ASHP", 0.0)
        assert cop == pytest.approx(ASHP_COP_INTERCEPT, rel=0.001)

    def test_ashp_cop_increases_with_temperature(self):
        """ASHP COP increases with outdoor temperature."""
        cop_minus_10 = calculate_cop("ASHP", -10.0)
        cop_zero = calculate_cop("ASHP", 0.0)
        cop_plus_10 = calculate_cop("ASHP", 10.0)

        assert cop_minus_10 < cop_zero < cop_plus_10

    def test_ashp_cop_linear_relationship(self):
        """ASHP COP follows linear relationship in mid-range."""
        # At temperatures where we're not hitting min/max bounds
        temp = 5.0
        expected_cop = ASHP_COP_INTERCEPT + ASHP_COP_SLOPE * temp
        actual_cop = calculate_cop("ASHP", temp)
        assert actual_cop == pytest.approx(expected_cop, rel=0.001)

    def test_ashp_cop_min_bound(self):
        """ASHP COP doesn't go below minimum."""
        # Very cold temperature should hit minimum
        cop = calculate_cop("ASHP", -20.0)
        assert cop >= ASHP_COP_MIN
        assert cop == pytest.approx(ASHP_COP_MIN, rel=0.001)

    def test_ashp_cop_max_bound(self):
        """ASHP COP doesn't exceed maximum."""
        # Very warm temperature should hit maximum
        cop = calculate_cop("ASHP", 30.0)
        assert cop <= ASHP_COP_MAX
        assert cop == pytest.approx(ASHP_COP_MAX, rel=0.001)

    def test_gshp_cop_more_stable(self):
        """GSHP COP is more stable than ASHP across temperatures."""
        gshp_cop_cold = calculate_cop("GSHP", -10.0)
        gshp_cop_warm = calculate_cop("GSHP", 20.0)
        ashp_cop_cold = calculate_cop("ASHP", -10.0)
        ashp_cop_warm = calculate_cop("ASHP", 20.0)

        gshp_variation = abs(gshp_cop_warm - gshp_cop_cold)
        ashp_variation = abs(ashp_cop_warm - ashp_cop_cold)

        assert gshp_variation < ashp_variation

    def test_gshp_cop_at_base_temp(self):
        """GSHP COP near base value at typical temperatures."""
        cop = calculate_cop("GSHP", 10.0)
        # Should be close to base, slightly influenced by temperature
        assert cop >= GSHP_COP_MIN
        assert cop <= GSHP_COP_MAX

    def test_gshp_cop_min_bound(self):
        """GSHP COP doesn't go below minimum."""
        cop = calculate_cop("GSHP", -30.0)
        assert cop >= GSHP_COP_MIN

    def test_gshp_cop_max_bound(self):
        """GSHP COP doesn't exceed maximum."""
        cop = calculate_cop("GSHP", 40.0)
        assert cop <= GSHP_COP_MAX

    def test_invalid_heat_pump_type_raises(self):
        """Invalid heat pump type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid heat pump type"):
            calculate_cop("INVALID", 10.0)

    def test_gshp_generally_higher_cop(self):
        """GSHP generally has higher COP than ASHP in cold weather."""
        temp = -5.0
        gshp_cop = calculate_cop("GSHP", temp)
        ashp_cop = calculate_cop("ASHP", temp)
        assert gshp_cop > ashp_cop


class TestCalculateHeatingDegreeMinutes:
    """Test heating degree minutes calculation."""

    def test_temperature_below_base(self):
        """Temperature below base produces positive degree minutes."""
        temps = pd.Series([10.0, 12.0, 5.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # Base is 15.5°C by default
        # Deficits: 5.5, 3.5, 10.5
        assert degree_mins.iloc[0] == pytest.approx(5.5, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(3.5, rel=0.001)
        assert degree_mins.iloc[2] == pytest.approx(10.5, rel=0.001)

    def test_temperature_above_base_gives_zero(self):
        """Temperature above base gives zero degree minutes."""
        temps = pd.Series([20.0, 18.0, 16.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # All temperatures above base (15.5°C)
        assert (degree_mins >= 0).all()
        assert degree_mins.iloc[0] == 0.0
        assert degree_mins.iloc[1] == 0.0
        assert degree_mins.iloc[2] == 0.0

    def test_temperature_at_base_gives_zero(self):
        """Temperature exactly at base gives zero degree minutes."""
        temps = pd.Series([BASE_TEMPERATURE_C])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert degree_mins.iloc[0] == 0.0

    def test_custom_base_temperature(self):
        """Can use custom base temperature."""
        temps = pd.Series([18.0, 15.0])
        degree_mins = calculate_heating_degree_minutes(temps, base_temp_c=20.0)

        # Deficits from 20°C: 2.0, 5.0
        assert degree_mins.iloc[0] == pytest.approx(2.0, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(5.0, rel=0.001)

    def test_negative_temperatures(self):
        """Handles negative temperatures correctly."""
        temps = pd.Series([-5.0, -10.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # Deficits from 15.5°C: 20.5, 25.5
        assert degree_mins.iloc[0] == pytest.approx(20.5, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(25.5, rel=0.001)

    def test_returns_series_same_length(self):
        """Output series has same length as input."""
        temps = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert len(degree_mins) == len(temps)

    def test_no_negative_values(self):
        """Output never contains negative values."""
        temps = pd.Series([5.0, 10.0, 15.0, 20.0, 25.0])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert (degree_mins >= 0).all()


def _utc_1990_minute_index() -> pd.DatetimeIndex:
    """The minutes of a PVGIS TMY year once interpolated to 1-minute resolution."""
    return pd.date_range("1990-01-01", periods=525_600, freq="1min", tz="UTC")


def _days_at(temperature_c: float, first_day: str, days: int = 1) -> pd.Series:
    """A constant temperature, minute by minute, over *days* whole Europe/London days from *first_day*."""
    index = pd.date_range(first_day, periods=days * 1440, freq="1min", tz="Europe/London")
    return pd.Series(temperature_c, index=index)


@pytest.fixture(scope="module")
def year_at_10c() -> pd.Series:
    """A reference year at a constant 10 °C: 5.5 heating degree-minutes in every minute."""
    return pd.Series(10.0, index=_utc_1990_minute_index())


@pytest.fixture(scope="module")
def seasonal_year() -> pd.Series:
    """A reference year that swings with the seasons and with the time of day.

    Its coldest minute is 0 °C at 03:00 on 15 January, its warmest 20 °C mid-afternoon in mid-July,
    when only the small hours fall below the 15.5 °C base temperature.
    """
    index = _utc_1990_minute_index()
    day_of_year_angle = 2 * np.pi * (index.dayofyear.to_numpy() - 15) / 365
    minute_of_day_angle = 2 * np.pi * (index.hour.to_numpy() * 60 + index.minute.to_numpy() - 180) / 1440
    return pd.Series(10.0 - 7.0 * np.cos(day_of_year_angle) - 3.0 * np.cos(minute_of_day_angle), index=index)


@pytest.fixture(scope="module")
def seasonal_year_load(seasonal_year) -> pd.Series:
    """The default ASHP's load over the whole of seasonal_year."""
    return generate_heat_pump_load(HeatPumpConfig.default_ashp(), seasonal_year, annual_temperature_c=seasonal_year)


class TestGenerateHeatPumpLoad:
    """Test heat pump load profile generation."""

    @pytest.fixture
    def ashp_config(self) -> HeatPumpConfig:
        """Standard ASHP test configuration."""
        return HeatPumpConfig.default_ashp()

    @pytest.fixture
    def gshp_config(self) -> HeatPumpConfig:
        """Standard GSHP test configuration."""
        return HeatPumpConfig.default_gshp()

    @pytest.fixture
    def winter_temps(self) -> pd.Series:
        """Winter day temperature profile."""
        # Cold winter day, one day at 1-minute resolution
        index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        # Temperature varies between 2°C and 8°C
        temps = 5.0 + 3.0 * np.sin(np.linspace(0, 2*np.pi, 1440))
        return pd.Series(temps, index=index)

    @pytest.fixture
    def summer_temps(self) -> pd.Series:
        """Summer day temperature profile."""
        # Warm summer day, one day at 1-minute resolution
        index = pd.date_range("2024-06-21", periods=1440, freq="1min", tz="UTC")
        # Temperature varies between 16°C and 22°C (all above 15.5°C base temp)
        temps = 19.0 + 3.0 * np.sin(np.linspace(0, 2*np.pi, 1440))
        return pd.Series(temps, index=index)

    def test_returns_series_with_correct_index(self, ashp_config, winter_temps, year_at_10c):
        """Output has same index as input temperature."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)

        assert isinstance(load, pd.Series)
        assert len(load) == len(winter_temps)
        assert load.index.equals(winter_temps.index)

    def test_output_in_kw(self, ashp_config, winter_temps, year_at_10c):
        """Output values are electrical power in kW."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)

        # Typical domestic heat pump electrical load is 1-5 kW
        assert load.max() < 10.0  # Reasonable upper bound
        assert load.mean() > 0.1  # Non-trivial consumption in winter

    def test_no_negative_values(self, ashp_config, winter_temps, year_at_10c):
        """Output has no negative values."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)
        assert (load >= 0).all()

    def test_summer_has_zero_load(self, ashp_config, summer_temps, year_at_10c):
        """Summer temperatures above base temp produce zero load."""
        load = generate_heat_pump_load(ashp_config, summer_temps, annual_temperature_c=year_at_10c)
        # All temperatures above base, so no heating needed
        assert load.sum() == 0.0

    def test_winter_has_positive_load(self, ashp_config, winter_temps, year_at_10c):
        """Winter temperatures below base temp produce positive load."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)
        assert load.sum() > 0.0
        assert load.max() > 0.0

    def test_colder_weather_higher_load(self, ashp_config, year_at_10c):
        """Colder weather produces higher electrical load."""
        # Very cold day
        cold_index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        cold_temps = pd.Series([0.0] * 1440, index=cold_index)

        # Mild day
        mild_index = pd.date_range("2024-03-15", periods=1440, freq="1min", tz="UTC")
        mild_temps = pd.Series([10.0] * 1440, index=mild_index)

        cold_load = generate_heat_pump_load(ashp_config, cold_temps, annual_temperature_c=year_at_10c)
        mild_load = generate_heat_pump_load(ashp_config, mild_temps, annual_temperature_c=year_at_10c)

        # Cold day should have higher average load
        assert cold_load.mean() > mild_load.mean()

    def test_capacity_limiting(self, year_at_10c):
        """Heat is capped at the thermal capacity.

        Each minute of a -5 °C day would get 8.51 kW of heat from 20,000 kWh a year shared over a 10 °C year,
        more than the 5 kW capacity, so it draws 5 kW / COP.
        """
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=5.0,
            annual_heat_demand_kwh=20000.0,
        )
        day_at_minus_5c = _days_at(-5.0, "2025-01-15")

        load = generate_heat_pump_load(config, day_at_minus_5c, annual_temperature_c=year_at_10c)

        expected = pd.Series(5.0 / calculate_cop("ASHP", -5.0), index=day_at_minus_5c.index, name="heat_pump_load_kw")
        pd.testing.assert_series_equal(load, expected)

    def test_gshp_vs_ashp_efficiency(self, year_at_10c):
        """GSHP uses less electricity than ASHP for same thermal output."""
        # Cold weather where COP difference is significant
        index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        temps = pd.Series([0.0] * 1440, index=index)

        ashp_config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0
        )
        gshp_config = HeatPumpConfig(
            heat_pump_type="GSHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0
        )

        ashp_load = generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)
        gshp_load = generate_heat_pump_load(gshp_config, temps, annual_temperature_c=year_at_10c)

        # GSHP should use less electricity due to higher COP
        assert gshp_load.sum() < ashp_load.sum()

    def test_requires_datetime_index(self, ashp_config, year_at_10c):
        """Raises error if temperature doesn't have DatetimeIndex."""
        temps = pd.Series([10.0, 12.0, 14.0])  # No DatetimeIndex

        with pytest.raises(ValueError, match="DatetimeIndex"):
            generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

    def test_requires_timezone_aware_index(self, ashp_config, year_at_10c):
        """Raises error if index is not timezone-aware."""
        index = pd.date_range("2024-01-15", periods=1440, freq="1min")  # No tz
        temps = pd.Series([10.0] * 1440, index=index)

        with pytest.raises(ValueError, match="timezone-aware"):
            generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

    def test_multi_day_profile(self, ashp_config, year_at_10c):
        """Generates profile for multiple days."""
        # 3 days of cold winter weather
        index = pd.date_range("2024-01-15", periods=3*1440, freq="1min", tz="UTC")
        temps = pd.Series([5.0] * (3*1440), index=index)

        load = generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

        assert len(load) == 3 * 1440
        assert load.sum() > 0.0


class TestGenerateHeatPumpLoadSharesTheAnnualHeatDemand:
    """Each minute gets the annual heat demand in proportion to its share of the reference year's heating degree-minutes.

    Delivered heat is recovered from the electrical load as load × COP.
    """

    @pytest.mark.parametrize("days", [1, 30])
    def test_a_window_gets_its_days_share_of_a_constant_years_heat(self, days, year_at_10c):
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=20.0,
            annual_heat_demand_kwh=12000.0,
        )
        window = _days_at(10.0, "2025-01-15", days)

        load = generate_heat_pump_load(config, window, annual_temperature_c=year_at_10c)

        heat_delivered_kwh = (load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(days * 12000.0 / 365)

    @pytest.mark.parametrize(
        ("first_minute", "last_minute"),
        [
            pytest.param("1990-01-15", "1990-01-15 23:59", id="one-january-day"),
            pytest.param("1990-01-01", "1990-01-30 23:59", id="thirty-january-days"),
            pytest.param("1990-07-15", "1990-07-15 23:59", id="one-july-day"),
        ],
    )
    def test_a_window_draws_the_same_load_as_those_minutes_of_the_full_year_run(
        self, first_minute, last_minute, seasonal_year, seasonal_year_load
    ):
        window = seasonal_year.loc[first_minute:last_minute]

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), window, annual_temperature_c=seasonal_year)

        pd.testing.assert_series_equal(load, seasonal_year_load.loc[first_minute:last_minute])

    def test_a_summer_day_with_one_cool_hour_draws_only_that_hours_share(self, year_at_10c):
        summer_day = _days_at(20.0, "2025-07-15")
        summer_day.iloc[180:240] = 14.5

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), summer_day, annual_temperature_c=year_at_10c)

        year_heating_degree_minutes = 5.5 * 525_600
        cool_hour_heating_degree_minutes = 1.0 * 60
        cool_hour_heat_kwh = 8000.0 * cool_hour_heating_degree_minutes / year_heating_degree_minutes
        assert load.sum() / 60 == pytest.approx(cool_hour_heat_kwh / calculate_cop("ASHP", 14.5))

    def test_a_year_that_never_needs_heating_gives_no_load(self):
        year_at_20c = pd.Series(20.0, index=_utc_1990_minute_index())
        day_at_0c = _days_at(0.0, "2025-01-15")

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), day_at_0c, annual_temperature_c=year_at_20c)

        pd.testing.assert_series_equal(load, pd.Series(0.0, index=day_at_0c.index, name="heat_pump_load_kw"))


class TestGenerateHeatPumpLoadRejectsAReferenceThatIsNotAYear:
    """annual_temperature_c must be one year of minutes, 365 to 366 days; any other length raises ValueError."""

    @pytest.mark.parametrize(
        ("rows", "freq"),
        [
            pytest.param(1440, "1min", id="one-day-of-minutes"),
            pytest.param(8760, "1h", id="an-hourly-year"),
            pytest.param(365 * 1440 - 1, "1min", id="one-minute-short-of-a-year"),
            pytest.param(366 * 1440 + 1, "1min", id="one-minute-past-a-leap-year"),
            pytest.param(2 * 525_600, "1min", id="two-years-of-minutes"),
        ],
    )
    def test_a_reference_that_is_not_a_year_of_minutes_raises_with_its_length(self, rows, freq):
        reference = pd.Series(10.0, index=pd.date_range("1990-01-01", periods=rows, freq=freq, tz="UTC"))

        with pytest.raises(
            ValueError,
            match=re.escape(f"annual_temperature_c has {rows:,} rows, not one year of minutes (525,600 to 527,040)"),
        ):
            generate_heat_pump_load(
                HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
            )

    @pytest.mark.parametrize("days", [365, 366])
    def test_a_reference_of_a_whole_year_of_minutes_shares_the_demand_over_its_days(self, days):
        reference = pd.Series(10.0, index=pd.date_range("1992-01-01", periods=days * 1440, freq="1min", tz="UTC"))

        load = generate_heat_pump_load(
            HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
        )

        heat_delivered_kwh = (load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(8000.0 / days)


class TestGenerateHeatPumpLoadNamesItsLoad:
    """generate_heat_pump_load names its load heat_pump_load_kw, not after its temperature input.

    That holds whether or not the reference year has any heating degree-minutes.
    """

    @pytest.mark.parametrize(
        "reference_temperature_c",
        [
            pytest.param(10.0, id="heating-year"),
            pytest.param(20.0, id="no-heating-year"),
        ],
    )
    def test_load_is_named_heat_pump_load_kw(self, reference_temperature_c):
        reference_year = pd.Series(reference_temperature_c, index=_utc_1990_minute_index(), name="temp_air")
        cold_day = _days_at(5.0, "2025-01-15").rename("temp_air")

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), cold_day, annual_temperature_c=reference_year)

        assert load.name == "heat_pump_load_kw"


class TestHeatPumpDocstringExamples:
    """The examples in solar_challenge.heat_pump's docstrings run and hold."""

    def test_every_example_holds(self):
        failed, attempted = doctest.testmod(solar_challenge.heat_pump, verbose=False)

        assert attempted > 0
        assert failed == 0
