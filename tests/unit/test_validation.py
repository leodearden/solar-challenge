"""Tests for validation and sanity checks."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from solar_challenge.home import SimulationResults
from solar_challenge.pv import PVConfig, create_simple_module_params, wired_dc_capacity_kw
from solar_challenge.validation import (
    ValidationReport,
    ValidationResult,
    validate_consumption,
    validate_pv_generation,
    validate_self_consumption_pv_only,
    validate_self_consumption_with_battery,
    validate_simulation,
)


def _create_minute_index(days: int = 7) -> pd.DatetimeIndex:
    """Create a 1-minute DatetimeIndex for testing."""
    return pd.date_range(
        start="2024-06-01",
        periods=days * 24 * 60,
        freq="1min",
        tz="Europe/London",
    )


def _create_valid_generation(index: pd.DatetimeIndex, capacity_kw: float) -> pd.Series:
    """Create valid PV generation data."""
    # Simple sinusoidal pattern for daylight hours
    hour = index.hour
    generation = np.where(
        (hour >= 6) & (hour <= 20),
        capacity_kw * 0.5 * np.sin(np.pi * (hour - 6) / 14),
        0.0,
    )
    return pd.Series(generation, index=index, name="generation_kw")


def _create_valid_demand(
    index: pd.DatetimeIndex,
    annual_kwh: float = 3400.0,
) -> pd.Series:
    """Create valid demand data."""
    # Base load with evening peak
    hour = index.hour
    base = 0.3  # 300W baseload
    peak = np.where((hour >= 17) & (hour <= 21), 1.5, 0.5)

    # Scale to annual consumption
    days = len(index) / (24 * 60)
    daily_target = annual_kwh / 365
    raw_demand = base + peak * 0.7

    # Scale factor
    raw_daily = raw_demand.mean() * 24  # kWh per day
    scale = daily_target / raw_daily if raw_daily > 0 else 1.0

    return pd.Series(raw_demand * scale, index=index, name="demand_kw")


def _create_simulation_results(
    index: pd.DatetimeIndex,
    pv_capacity_kw: float = 4.0,
    self_consumption_ratio: float = 0.3,
    has_battery: bool = False,
) -> SimulationResults:
    """Create simulation results for testing."""
    generation = _create_valid_generation(index, pv_capacity_kw)
    demand = _create_valid_demand(index)

    # Calculate self-consumption as fraction of generation
    self_consumption = generation * self_consumption_ratio

    # Calculate grid flows
    excess = (generation - self_consumption).clip(lower=0)
    shortfall = (demand - self_consumption).clip(lower=0)

    battery_charge = pd.Series(np.zeros(len(index)), index=index)
    battery_discharge = pd.Series(np.zeros(len(index)), index=index)
    battery_soc = pd.Series(np.zeros(len(index)), index=index)

    if has_battery:
        # Simulate some battery activity
        battery_charge = excess * 0.5
        battery_discharge = shortfall * 0.3
        battery_soc = pd.Series(np.full(len(index), 2.5), index=index)

    grid_export = excess - battery_charge
    grid_import = shortfall - battery_discharge

    # Create zero-filled series for financial fields
    import_cost = pd.Series(np.zeros(len(index)), index=index)
    export_revenue = pd.Series(np.zeros(len(index)), index=index)
    tariff_rate = pd.Series(np.zeros(len(index)), index=index)

    return SimulationResults(
        generation=generation,
        demand=demand,
        self_consumption=self_consumption,
        battery_charge=battery_charge,
        battery_discharge=battery_discharge,
        battery_soc=battery_soc,
        grid_import=grid_import,
        grid_export=grid_export,
        import_cost=import_cost,
        export_revenue=export_revenue,
        tariff_rate=tariff_rate,
    )


def _year_of_generation(total_kwh: float) -> pd.Series:
    """A year of 1-minute generation, zero at night, whose energy is total_kwh."""
    index = _create_minute_index(365)
    shape = _create_valid_generation(index, capacity_kw=1.0)
    return shape * (total_kwh / (shape.sum() / 60))


def _annual_yield_check(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if r.check_name == "annual_yield_range")


def _peak_check(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if r.check_name == "peak_within_capacity")


# Wires four 250 W modules, 1.0 kWp; the default 400.428 W module would wire three, 1.2 kWp.
_PVWATTS_250_W_AT_1_1_KW = PVConfig(
    capacity_kw=1.1, custom_module_params=create_simple_module_params(module_power_w=250.0)
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_passed_result(self) -> None:
        """Test creating a passed result."""
        result = ValidationResult(
            passed=True,
            check_name="test_check",
            message="All good",
            value=42.0,
        )
        assert result.passed is True
        assert result.check_name == "test_check"

    def test_failed_result_with_range(self) -> None:
        """Test creating a failed result with expected range."""
        result = ValidationResult(
            passed=False,
            check_name="range_check",
            message="Out of range",
            value=150.0,
            expected_range=(0, 100),
        )
        assert result.passed is False
        assert result.expected_range == (0, 100)


class TestValidationReport:
    """Tests for ValidationReport class."""

    def test_all_passed(self) -> None:
        """Test report with all checks passed."""
        results = [
            ValidationResult(passed=True, check_name="check1", message="OK"),
            ValidationResult(passed=True, check_name="check2", message="OK"),
        ]
        report = ValidationReport(results=results)
        assert report.all_passed is True
        assert len(report.failures) == 0

    def test_some_failed(self) -> None:
        """Test report with some failures."""
        results = [
            ValidationResult(passed=True, check_name="check1", message="OK"),
            ValidationResult(passed=False, check_name="check2", message="Failed"),
        ]
        report = ValidationReport(results=results)
        assert report.all_passed is False
        assert len(report.failures) == 1
        assert report.failures[0].check_name == "check2"

    def test_string_representation(self) -> None:
        """Test report string formatting."""
        results = [
            ValidationResult(passed=True, check_name="check1", message="OK"),
            ValidationResult(passed=False, check_name="check2", message="Failed"),
        ]
        report = ValidationReport(results=results)
        report_str = str(report)
        assert "PASS" in report_str
        assert "FAIL" in report_str
        assert "1/2 passed" in report_str


class TestValidatePVGeneration:
    """Tests for PV generation validation (VAL-001)."""

    def test_valid_generation(self) -> None:
        """Test validation of valid generation data."""
        index = _create_minute_index(7)
        generation = _create_valid_generation(index, capacity_kw=4.0)

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=False)

        assert all(r.passed for r in results)

    def test_negative_generation_fails(self) -> None:
        """Test that negative generation fails validation."""
        index = _create_minute_index(7)
        generation = _create_valid_generation(index, capacity_kw=4.0)
        generation.iloc[100] = -1.0  # Introduce negative value

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=False)

        non_negative_check = next(r for r in results if "non_negative" in r.check_name)
        assert non_negative_check.passed is False

    def test_peak_exceeding_capacity_fails(self) -> None:
        """Test that peak exceeding capacity fails."""
        index = _create_minute_index(7)
        generation = _create_valid_generation(index, capacity_kw=4.0)
        generation.iloc[500] = 10.0  # Way above 4 kW capacity

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=False)

        peak_check = next(r for r in results if "peak" in r.check_name)
        assert peak_check.passed is False

    def test_night_generation_fails(self) -> None:
        """Test that significant night generation fails."""
        index = _create_minute_index(7)
        generation = pd.Series(np.full(len(index), 0.5), index=index)  # Constant 0.5 kW

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=False)

        night_check = next(r for r in results if "night" in r.check_name)
        assert night_check.passed is False

    def test_zero_at_night_passes(self) -> None:
        """Test that zero night generation passes."""
        index = _create_minute_index(7)
        generation = _create_valid_generation(index, capacity_kw=4.0)

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=False)

        night_check = next(r for r in results if "night" in r.check_name)
        assert night_check.passed is True

    @pytest.mark.parametrize(("days", "checked"), [(364, False), (365, True)])
    def test_the_annual_yield_check_needs_a_full_year_of_data(
        self, days: int, checked: bool
    ) -> None:
        generation = _create_valid_generation(_create_minute_index(days), capacity_kw=4.0)

        results = validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=True)

        assert ("annual_yield_range" in [r.check_name for r in results]) is checked


class TestAnnualYieldPerWiredKwp:
    """A year's yield is per kWp of the modules the PV model wires, not per configured kW."""

    @pytest.mark.parametrize("capacity_kw", [0.3, 0.5, 1.5, 4.0])
    def test_a_typical_uk_yield_passes_whatever_the_module_rounding(
        self, capacity_kw: float
    ) -> None:
        pv_config = PVConfig(capacity_kw=capacity_kw)
        wired_kw = wired_dc_capacity_kw(pv_config)
        generation = _year_of_generation(1000.0 * wired_kw)

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is True
        assert result.value == pytest.approx(1000.0)

    @pytest.mark.parametrize(
        ("capacity_kw", "kwh_per_wired_kwp"),
        [(0.5, 1300.0), (0.3, 250.0), (4.0, 1300.0), (4.0, 200.0), (4.0, 0.0)],
    )
    def test_a_yield_outside_the_uk_benchmark_fails(
        self, capacity_kw: float, kwh_per_wired_kwp: float
    ) -> None:
        pv_config = PVConfig(capacity_kw=capacity_kw)
        wired_kw = wired_dc_capacity_kw(pv_config)
        generation = _year_of_generation(kwh_per_wired_kwp * wired_kw)

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is False
        assert result.value == pytest.approx(kwh_per_wired_kwp)

    def test_0_3_kw_is_judged_per_the_one_400_428_w_module_it_wires(self) -> None:
        """0.3 kW wires one 400.428 W module, so 400.428 kWh a year is 1000 kWh/kWp."""
        generation = _year_of_generation(400.428)

        result = _annual_yield_check(
            validate_pv_generation(generation, PVConfig(capacity_kw=0.3), check_annual=True)
        )

        assert result.passed is True
        assert result.value == pytest.approx(1000.0)

    @pytest.mark.parametrize(
        ("kwh_per_wired_kwp", "passed"),
        [(350.0, True), (1300.0, False)],
    )
    def test_a_custom_module_is_judged_per_the_dc_its_modules_wire(
        self, kwh_per_wired_kwp: float, passed: bool
    ) -> None:
        """1.0 kWp is the four 250 W modules _PVWATTS_250_W_AT_1_1_KW wires.

        Per the default module's 1.2 kWp, 350 would read 291 and fail, and 1300
        would read 1082 and pass.
        """
        assert wired_dc_capacity_kw(PVConfig(capacity_kw=1.1)) != pytest.approx(1.0)
        generation = _year_of_generation(kwh_per_wired_kwp * 1.0)

        result = _annual_yield_check(
            validate_pv_generation(generation, _PVWATTS_250_W_AT_1_1_KW, check_annual=True)
        )

        assert result.passed is passed
        assert result.value == pytest.approx(kwh_per_wired_kwp)

    @pytest.mark.parametrize(
        ("kwh_per_wired_kwp", "passed"),
        [(299.99, False), (300.01, True), (1199.99, True), (1200.01, False)],
    )
    def test_the_uk_benchmark_band_runs_from_300_to_1200(
        self, kwh_per_wired_kwp: float, passed: bool
    ) -> None:
        pv_config = PVConfig(capacity_kw=4.0)
        wired_kw = wired_dc_capacity_kw(pv_config)
        generation = _year_of_generation(kwh_per_wired_kwp * wired_kw)

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is passed

    @pytest.mark.parametrize(
        "kwh_per_wired_kwp",
        [
            pytest.param(1175.2, id="pvgis-eastbourne-optimal"),
            pytest.param(367.3, id="pvgis-unst-east-wall"),
        ],
    )
    def test_the_pvgis_yields_that_set_the_band_edges_pass(
        self, kwh_per_wired_kwp: float
    ) -> None:
        """docs/pv-annual-yield-benchmark.md §2 sources each and rounds it outward to its edge."""
        pv_config = PVConfig(capacity_kw=4.0)
        wired_kw = wired_dc_capacity_kw(pv_config)
        generation = _year_of_generation(kwh_per_wired_kwp * wired_kw)

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is True
        assert result.value == pytest.approx(kwh_per_wired_kwp)


class TestPeakWithinWiredCapacity:
    """The peak may exceed the DC of the modules the PV model wires by 10%."""

    def test_a_peak_above_the_configured_capacity_passes_within_the_wired_dc(self) -> None:
        """0.7 kW wires two 400.428 W modules, 0.80 kWp.

        Behind a 1.0 kW inverter the model's AC peaked at 0.804 kW, as
        docs/pv-annual-yield-benchmark.md §4 records.
        """
        pv_config = PVConfig(capacity_kw=0.7, inverter_capacity_kw=1.0)
        generation = _create_valid_generation(_create_minute_index(7), capacity_kw=0.7)
        generation.iloc[780] = 0.80

        result = _peak_check(validate_pv_generation(generation, pv_config, check_annual=False))

        assert result.passed is True

    def test_a_peak_over_the_wired_dc_fails_though_within_the_configured_capacity(self) -> None:
        """The limit is 10% over the 1.0 kWp four 250 W modules wire: 1.1 kW, not 1.21 kW."""
        generation = _create_valid_generation(_create_minute_index(7), capacity_kw=1.1)
        generation.iloc[780] = 1.15

        result = _peak_check(
            validate_pv_generation(generation, _PVWATTS_250_W_AT_1_1_KW, check_annual=False)
        )

        assert result.passed is False
        assert result.expected_range is not None
        assert result.expected_range[1] == pytest.approx(1.1)


class TestValidateConsumption:
    """Tests for consumption validation (VAL-002)."""

    def test_valid_consumption(self) -> None:
        """Test validation of valid consumption data."""
        index = _create_minute_index(7)
        demand = _create_valid_demand(index, annual_kwh=3400)

        results = validate_consumption(demand, target_annual_kwh=None)

        assert all(r.passed for r in results)

    def test_negative_consumption_fails(self) -> None:
        """Test that negative consumption fails."""
        index = _create_minute_index(7)
        demand = _create_valid_demand(index)
        demand.iloc[100] = -0.5  # Negative value

        results = validate_consumption(demand)

        neg_check = next(r for r in results if "non_negative" in r.check_name)
        assert neg_check.passed is False

    def test_unrealistic_peak_fails(self) -> None:
        """Test that unrealistic peak demand fails."""
        index = _create_minute_index(7)
        demand = _create_valid_demand(index)
        demand.iloc[100] = 100.0  # 100 kW - way too high for domestic

        results = validate_consumption(demand)

        peak_check = next(r for r in results if "peak" in r.check_name)
        assert peak_check.passed is False

    def test_baseload_check(self) -> None:
        """Test baseload presence validation."""
        index = _create_minute_index(7)
        demand = _create_valid_demand(index)

        results = validate_consumption(demand)

        baseload_check = next(r for r in results if "baseload" in r.check_name)
        assert baseload_check.passed is True

    def test_missing_baseload_fails(self) -> None:
        """Test that mostly-zero consumption fails baseload check."""
        index = _create_minute_index(7)
        # Mostly zeros with occasional spikes
        demand = pd.Series(np.zeros(len(index)), index=index)
        demand.iloc[::1000] = 1.0  # Sparse non-zero values

        results = validate_consumption(demand)

        baseload_check = next(r for r in results if "baseload" in r.check_name)
        assert baseload_check.passed is False

    def test_annual_target_matching(self) -> None:
        """Test annual consumption target validation."""
        index = _create_minute_index(365)  # Full year
        demand = _create_valid_demand(index, annual_kwh=3400)

        results = validate_consumption(demand, target_annual_kwh=3400)

        target_check = [r for r in results if "target" in r.check_name]
        # May or may not have this check depending on data
        if target_check:
            assert target_check[0].passed is True


class TestSelfConsumptionBenchmarks:
    """Tests for self-consumption benchmark validation (VAL-003, VAL-004)."""

    def test_pv_only_in_range(self) -> None:
        """Test PV-only self-consumption within benchmark range."""
        index = _create_minute_index(30)  # 30 days
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.30,  # 30% - in range
            has_battery=False,
        )

        validation = validate_self_consumption_pv_only(
            results,
            capacity_kw=4.0,
            annual_consumption_kwh=3400,
        )

        assert validation.passed is True
        assert "benchmark" in validation.check_name

    def test_pv_only_below_range(self) -> None:
        """Test PV-only self-consumption below benchmark."""
        index = _create_minute_index(30)
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.10,  # 10% - too low
            has_battery=False,
        )

        validation = validate_self_consumption_pv_only(
            results,
            capacity_kw=4.0,
            annual_consumption_kwh=3400,
        )

        assert validation.passed is False

    def test_with_battery_in_range(self) -> None:
        """Test PV+battery self-consumption within benchmark range."""
        index = _create_minute_index(30)
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.70,  # 70% - in range
            has_battery=True,
        )

        validation = validate_self_consumption_with_battery(
            results,
            capacity_kw=4.0,
            battery_kwh=5.0,
            annual_consumption_kwh=3400,
        )

        assert validation.passed is True

    def test_with_battery_below_range(self) -> None:
        """Test PV+battery self-consumption below benchmark."""
        index = _create_minute_index(30)
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.30,  # 30% - too low for battery system
            has_battery=True,
        )

        validation = validate_self_consumption_with_battery(
            results,
            capacity_kw=4.0,
            battery_kwh=5.0,
            annual_consumption_kwh=3400,
        )

        assert validation.passed is False


class TestValidateSimulation:
    """Tests for complete simulation validation."""

    def test_full_validation(self) -> None:
        """Test running full validation on simulation results."""
        index = _create_minute_index(30)
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.30,
            has_battery=False,
        )

        report = validate_simulation(
            results,
            PVConfig(capacity_kw=4.0),
            battery_capacity_kwh=None,
            target_annual_consumption_kwh=3400,
        )

        assert isinstance(report, ValidationReport)
        assert len(report.results) > 0

    def test_validation_with_battery(self) -> None:
        """Test validation with battery system."""
        index = _create_minute_index(30)
        results = _create_simulation_results(
            index,
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.70,
            has_battery=True,
        )

        report = validate_simulation(
            results,
            PVConfig(capacity_kw=4.0),
            battery_capacity_kwh=5.0,
            target_annual_consumption_kwh=3400,
        )

        assert isinstance(report, ValidationReport)
        # Should include battery benchmark check
        check_names = [r.check_name for r in report.results]
        assert any("battery" in name for name in check_names)

    def test_the_pv_checks_use_the_wired_dc_of_the_pv_config_given(self) -> None:
        """Per the 1.0 kWp of four 250 W modules: 800 kWh/kWp, and a 1.1 kW peak limit."""
        results = dataclasses.replace(
            _create_simulation_results(_create_minute_index(365)),
            generation=_year_of_generation(800.0),
        )

        report = validate_simulation(results, _PVWATTS_250_W_AT_1_1_KW)

        annual_yield = _annual_yield_check(report.results)
        assert annual_yield.passed is True
        assert annual_yield.value == pytest.approx(800.0)
        peak = _peak_check(report.results)
        assert peak.expected_range is not None
        assert peak.expected_range[1] == pytest.approx(1.1)
