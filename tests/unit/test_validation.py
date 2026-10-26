"""Tests for validation and sanity checks."""

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest
from pvlib.pvsystem import PVSystem

from solar_challenge import pv
from solar_challenge.home import SimulationResults
from solar_challenge.pv import (
    PVConfig,
    create_pv_system,
    create_simple_module_params,
    wired_dc_capacity_kw,
)
from solar_challenge.timebase import SimulationWindow
from solar_challenge.validation import (
    BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP,
    UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT,
    UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT,
    UK_YIELD_BENCHMARK_KWH_PER_KWP,
    ValidationReport,
    ValidationResult,
    validate_consumption,
    validate_pv_generation,
    validate_self_consumption_pv_only,
    validate_self_consumption_with_battery,
    validate_simulation,
)
from tests._pv_modules import default_module_beyond_every_mppt_window, pvwatts_300_w_module


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


def _with_generation_over_demand(results: SimulationResults, ratio: float) -> SimulationResults:
    """results with its demand rescaled so its generation total is ratio times its demand total; its self-consumption ratio is unchanged."""
    return dataclasses.replace(
        results,
        demand=results.demand * (results.generation.sum() / (ratio * results.demand.sum())),
    )


def _a_day_of_demand_kwh(results: SimulationResults) -> float:
    """A day of results' own demand: its mean kW over 24 hours."""
    return float(results.demand.mean()) * 24


def _edges_and_whether_inside(band: tuple[float, float]) -> list[tuple[float, bool]]:
    """Each edge of band, 0.1 percentage point either side, with whether it lies inside band."""
    low, high = band
    return [(low - 0.1, False), (low + 0.1, True), (high - 0.1, True), (high + 0.1, False)]


def _minute_index_over(first_day: str, last_day: str) -> pd.DatetimeIndex:
    """1-minute rows on the UK clock from first_day's midnight to last_day's last minute."""
    return pd.date_range(first_day, f"{last_day} 23:59", freq="1min", tz="Europe/London")


def _generation_over(index: pd.DatetimeIndex, total_kwh: float) -> pd.Series:
    """1-minute generation on index, zero at night, whose energy is total_kwh."""
    shape = _create_valid_generation(index, capacity_kw=1.0)
    return shape * (total_kwh / (shape.sum() / 60))


def _year_of_generation(total_kwh: float) -> pd.Series:
    """1-minute generation over calendar 2023, zero at night, whose energy is total_kwh; its window's annualisation_scale is 1."""
    return _generation_over(_minute_index_over("2023-01-01", "2023-12-31"), total_kwh)


def _annual_yield_check(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if r.check_name == "annual_yield_range")


def _annual_consumption_check(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if r.check_name == "annual_consumption_target")


def _peak_check(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if r.check_name == "peak_within_capacity")


# Wires four 250 W modules, 1.0 kWp; DEFAULT_CEC_MODULE (400.428 W at STC) would wire three, 1.2 kWp.
_PVWATTS_250_W_AT_1_1_KW = PVConfig(
    capacity_kw=1.1, custom_module_params=create_simple_module_params(module_power_w=250.0)
)


def _pvwatts_300_w_without_stc_at_4_kw() -> PVConfig:
    """A 4 kW PVConfig of pvwatts_300_w_module(): it wires thirteen 300 W modules, 3.9 kWp, each rated at its pdc0."""
    return PVConfig(capacity_kw=4.0, custom_module_params=pvwatts_300_w_module())


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
    """Tests for PV generation validation."""

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

    def test_the_annual_yield_refuses_an_index_its_window_cannot_be_read_from(self) -> None:
        """Text, as read_csv leaves an export across a clock change, describes no window."""
        index = _minute_index_over("2024-03-30", "2024-04-01")
        generation = _generation_over(index, 10.0).set_axis(index.astype(str))

        with pytest.raises(ValueError, match="SimulationWindow.of_index reads a DatetimeIndex"):
            validate_pv_generation(generation, PVConfig(capacity_kw=4.0), check_annual=True)

    def test_a_config_create_pv_system_refuses_is_refused_with_its_error(self) -> None:
        """No CEC inverter's MPPT window admits that module's string voltage."""
        config = PVConfig(
            capacity_kw=4.0, custom_module_params=default_module_beyond_every_mppt_window()
        )

        with pytest.raises(ValueError) as building:
            create_pv_system(config)
        with pytest.raises(ValueError) as validating:
            validate_pv_generation(_year_of_generation(4000.0), config, check_annual=True)

        assert str(validating.value) == str(building.value)


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
        """0.3 kW wires one DEFAULT_CEC_MODULE (400.428 W at STC), so 400.428 kWh a year is 1000 kWh/kWp."""
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
        assert result.expected_range == UK_YIELD_BENCHMARK_KWH_PER_KWP

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

    def test_the_default_systems_measured_bristol_yield_passes(self) -> None:
        pv_config = PVConfig.default_4kw()
        generation = _year_of_generation(
            BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP * wired_dc_capacity_kw(pv_config)
        )

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is True
        assert result.value == pytest.approx(BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP)

    def test_a_pvwatts_module_without_an_stc_is_judged_per_the_dc_its_pdc0_wires(self) -> None:
        generation = _year_of_generation(1000.0 * 3.9)

        result = _annual_yield_check(
            validate_pv_generation(
                generation, _pvwatts_300_w_without_stc_at_4_kw(), check_annual=True
            )
        )

        assert result.value == pytest.approx(1000.0)
        assert "3.90 kWp" in result.message


class TestAnnualYieldScaledByItsWindow:
    """A window of 365 days or more is judged on its yield times its annualisation_scale, the rule validate_consumption scales by."""

    @pytest.mark.parametrize(
        ("first_day", "last_day", "days", "year_days", "kwh_per_wired_kwp", "passed"),
        [
            pytest.param("2024-01-01", "2024-12-31", 366, 366.0, 1000.0, True, id="leap-year-2024"),
            pytest.param("2023-01-01", "2024-12-31", 731, 365.25, 1000.0, True, id="2023-and-2024"),
            pytest.param(
                "2023-01-01", "2024-12-31", 731, 365.25, 250.0, False,
                id="2023-and-2024-below-the-band",
            ),
            pytest.param(
                "2024-01-01", "2025-02-03", 400, 365.25, 1000.0, True,
                id="400-days-across-a-year-end",
            ),
        ],
    )
    def test_a_yield_is_judged_per_year_of_its_window(
        self,
        first_day: str,
        last_day: str,
        days: int,
        year_days: float,
        kwh_per_wired_kwp: float,
        passed: bool,
    ) -> None:
        pv_config = PVConfig(capacity_kw=4.0)
        wired_kw = wired_dc_capacity_kw(pv_config)
        generation = _generation_over(
            _minute_index_over(first_day, last_day),
            kwh_per_wired_kwp * wired_kw * days / year_days,
        )

        result = _annual_yield_check(
            validate_pv_generation(generation, pv_config, check_annual=True)
        )

        assert result.passed is passed
        assert result.value == pytest.approx(kwh_per_wired_kwp)


class TestPeakWithinWiredCapacity:
    """The peak may exceed the DC of the modules the PV model wires by 10%."""

    def test_a_peak_above_the_configured_capacity_passes_within_the_wired_dc(self) -> None:
        """0.7 kW wires two DEFAULT_CEC_MODULE (400.428 W at STC) modules, 0.80 kWp.

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

    def test_a_pvwatts_module_without_an_stc_is_judged_per_the_dc_its_pdc0_wires(self) -> None:
        generation = _create_valid_generation(_create_minute_index(7), capacity_kw=4.0)

        result = _peak_check(
            validate_pv_generation(
                generation, _pvwatts_300_w_without_stc_at_4_kw(), check_annual=False
            )
        )

        assert "3.90 kWp" in result.message
        assert result.expected_range is not None
        assert result.expected_range[1] == pytest.approx(3.9 * 1.1)


class TestOneWiredDcPerValidation:
    """Both checks judge against one read of the DC the PV model wires for the config, pv.wired_dc_capacity_kw, which builds the config's PV system."""

    def test_a_year_of_generation_builds_the_pv_system_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pv_config = PVConfig(capacity_kw=4.0)
        generation = _year_of_generation(4000.0)
        built: list[PVConfig] = []

        def recording_create_pv_system(config: PVConfig) -> PVSystem:
            built.append(config)
            return create_pv_system(config)

        monkeypatch.setattr(pv, "create_pv_system", recording_create_pv_system)

        results = validate_pv_generation(generation, pv_config, check_annual=True)

        assert {"peak_within_capacity", "annual_yield_range"} <= {r.check_name for r in results}
        assert built, (
            "the spy saw no build: it counts the create_pv_system that "
            "pv.wired_dc_capacity_kw looks up in pv's module globals"
        )
        assert built == [pv_config], f"one validation built the PV system {len(built)} times"


class TestValidateConsumption:
    """Tests for consumption validation."""

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

    @pytest.mark.parametrize(
        ("first_day", "last_day", "year_days"),
        [
            pytest.param("2023-01-01", "2023-12-31", 365.0, id="2023"),
            pytest.param("2024-01-01", "2024-12-31", 366.0, id="2024"),
            pytest.param("2024-06-01", "2024-06-30", 366.0, id="june-2024"),
            pytest.param("2023-01-01", "2024-12-31", 365.25, id="2023-and-2024"),
            pytest.param("2024-01-01", "2025-02-03", 365.25, id="400-days-from-2024"),
        ],
    )
    def test_the_annual_total_is_the_window_energy_times_its_annualisation_scale(
        self, first_day: str, last_day: str, year_days: float
    ) -> None:
        """Each window's clock changes cancel, so 0.5 kW delivers 12 kWh a calendar day."""
        demand = pd.Series(0.5, index=_minute_index_over(first_day, last_day))
        window = SimulationWindow.of_index(demand.index)

        target = _annual_consumption_check(validate_consumption(demand, target_annual_kwh=4383.0))

        assert target.value == pytest.approx(window.energy_kwh(demand) * window.annualisation_scale)
        assert target.value == pytest.approx(12.0 * year_days)

    def test_a_window_across_the_spring_clock_change_is_scaled_from_its_calendar_days(
        self,
    ) -> None:
        """March 2024's 743 hours are scaled by 2024's 366 days over its 31 calendar days."""
        march = pd.date_range("2024-03-01", "2024-03-31 23:59", freq="1min", tz="Europe/London")
        assert len(march) == (31 * 24 - 1) * 60
        demand = pd.Series(3400.0 * 31 / 366 / (len(march) / 60), index=march)

        target = _annual_consumption_check(validate_consumption(demand, target_annual_kwh=3400.0))

        assert target.value == pytest.approx(3400.0)

    def test_the_annual_target_refuses_unevenly_spaced_rows(self) -> None:
        index = pd.date_range(
            "2024-06-01", periods=24 * 60, freq="1min", tz="Europe/London"
        ).delete(700)

        with pytest.raises(ValueError, match="evenly spaced"):
            validate_consumption(pd.Series(0.5, index=index), target_annual_kwh=3400.0)


class TestSelfConsumptionBenchmarks:
    """Tests for self-consumption benchmark validation, PV-only and with a battery."""

    @pytest.mark.parametrize(
        ("percent", "passed"),
        _edges_and_whether_inside(UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT) + [(30.0, True)],
    )
    def test_the_pv_only_check_passes_exactly_inside_its_band(
        self, percent: float, passed: bool
    ) -> None:
        results = _create_simulation_results(
            _create_minute_index(30), self_consumption_ratio=percent / 100
        )

        validation = validate_self_consumption_pv_only(results)

        low, high = UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT
        assert validation.passed is passed
        assert validation.value == pytest.approx(percent)
        assert validation.expected_range == UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT
        assert f"({low:g}-{high:g}%)" in validation.message

    @pytest.mark.parametrize(
        ("percent", "passed"),
        _edges_and_whether_inside(UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT) + [(70.0, True)],
    )
    def test_the_battery_check_passes_exactly_inside_its_band(
        self, percent: float, passed: bool
    ) -> None:
        results = _create_simulation_results(
            _create_minute_index(30), self_consumption_ratio=percent / 100, has_battery=True
        )

        validation = validate_self_consumption_with_battery(results, battery_kwh=5.0)

        low, high = UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT
        assert validation.passed is passed
        assert validation.value == pytest.approx(percent)
        assert validation.expected_range == UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT
        assert f"({low:g}-{high:g}%)" in validation.message

    @pytest.mark.parametrize(
        "percent",
        [
            pytest.param(13.0, id="mgd003-table-7-22-out-during-the-day-4500-4799-kwh"),
            pytest.param(43.0, id="mgd003-table-7-4-home-all-day-1500-1799-kwh"),
        ],
    )
    def test_the_mgd003_ratios_that_set_the_pv_only_band_pass(self, percent: float) -> None:
        """docs/self-consumption-benchmark.md §2 sources each and rounds it outward to its edge."""
        results = _create_simulation_results(
            _create_minute_index(30), self_consumption_ratio=percent / 100
        )

        validation = validate_self_consumption_pv_only(results)

        assert validation.passed is True

    @pytest.mark.parametrize(
        "percent",
        [
            pytest.param(
                36.0, id="mgd003-table-7-22-out-during-the-day-4500-4799-kwh-3.1-4.1-kwh-usable"
            ),
            pytest.param(
                89.0, id="mgd003-table-7-4-home-all-day-1500-1799-kwh-4.1-5.1-kwh-usable"
            ),
        ],
    )
    def test_the_mgd003_ratios_that_set_the_battery_band_pass(self, percent: float) -> None:
        """docs/self-consumption-benchmark.md §2 sources each and rounds it outward to its edge."""
        results = _create_simulation_results(
            _create_minute_index(30), self_consumption_ratio=percent / 100, has_battery=True
        )

        validation = validate_self_consumption_with_battery(results, battery_kwh=5.0)

        assert validation.passed is True


class TestSelfConsumptionSizeNotes:
    """Outside the band, a note compares the run's own generation total with its own demand total, or a battery with a day of the run's own demand."""

    @pytest.mark.parametrize("pv_capacity_kw", [1.0, 6.0])
    def test_generation_twice_demand_is_pv_large_whatever_the_capacity(
        self, pv_capacity_kw: float
    ) -> None:
        """Nameplate x 900 kWh put 1 kW at 0.26 and 6 kW at 1.59 of 3,400 kWh, so the same totals once got different notes."""
        results = _with_generation_over_demand(
            _create_simulation_results(
                _create_minute_index(30),
                pv_capacity_kw=pv_capacity_kw,
                self_consumption_ratio=0.05,
            ),
            2.0,
        )

        validation = validate_self_consumption_pv_only(results)

        assert validation.passed is False
        assert validation.message.endswith("(Note: PV large relative to consumption)")

    def test_generation_half_demand_is_pv_small(self) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(_create_minute_index(30), self_consumption_ratio=0.60),
            0.5,
        )

        validation = validate_self_consumption_pv_only(results)

        assert validation.message.endswith("(Note: PV small relative to consumption)")

    def test_comparable_generation_and_demand_add_no_note(self) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(_create_minute_index(30), self_consumption_ratio=0.05),
            1.2,
        )

        validation = validate_self_consumption_pv_only(results)

        assert "Note:" not in validation.message

    def test_generation_with_no_demand_is_pv_large(self) -> None:
        results = _create_simulation_results(_create_minute_index(30), self_consumption_ratio=0.05)
        results = dataclasses.replace(results, demand=results.demand * 0.0)

        validation = validate_self_consumption_pv_only(results)

        assert validation.passed is False
        assert validation.message.endswith("(Note: PV large relative to consumption)")

    @pytest.mark.parametrize(("generation_over_demand", "noted"), [(0.7, True), (0.9, False)])
    def test_generation_under_0_8_of_demand_is_pv_small_with_a_battery(
        self, generation_over_demand: float, noted: bool
    ) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(
                _create_minute_index(30), self_consumption_ratio=0.95, has_battery=True
            ),
            generation_over_demand,
        )

        validation = validate_self_consumption_with_battery(results, battery_kwh=5.0)

        assert validation.message.endswith("(Note: PV small relative to consumption)") is noted

    @pytest.mark.parametrize(("generation_over_demand", "noted"), [(1.9, False), (2.1, True)])
    def test_generation_over_twice_demand_is_pv_very_large_with_a_battery(
        self, generation_over_demand: float, noted: bool
    ) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(
                _create_minute_index(30), self_consumption_ratio=0.20, has_battery=True
            ),
            generation_over_demand,
        )

        validation = validate_self_consumption_with_battery(results, battery_kwh=5.0)

        assert (
            validation.message.endswith("(Note: PV very large relative to consumption)") is noted
        )

    @pytest.mark.parametrize(("days_of_demand", "noted"), [(0.25, True), (0.35, False)])
    def test_a_battery_under_0_3_of_a_day_of_the_runs_own_demand_is_small(
        self, days_of_demand: float, noted: bool
    ) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(
                _create_minute_index(30), self_consumption_ratio=0.20, has_battery=True
            ),
            1.2,
        )

        validation = validate_self_consumption_with_battery(
            results, battery_kwh=days_of_demand * _a_day_of_demand_kwh(results)
        )

        assert (
            validation.message.endswith("(Note: Battery small relative to daily consumption)")
            is noted
        )

    def test_pv_very_large_outranks_a_small_battery(self) -> None:
        results = _with_generation_over_demand(
            _create_simulation_results(
                _create_minute_index(30), self_consumption_ratio=0.20, has_battery=True
            ),
            3.0,
        )

        validation = validate_self_consumption_with_battery(
            results, battery_kwh=0.1 * _a_day_of_demand_kwh(results)
        )

        assert validation.message.endswith("(Note: PV very large relative to consumption)")

    def test_no_generation_and_no_demand_add_no_note_with_a_battery(self) -> None:
        results = _create_simulation_results(_create_minute_index(30), pv_capacity_kw=0.0)
        results = dataclasses.replace(results, demand=results.demand * 0.0)

        validation = validate_self_consumption_with_battery(results, battery_kwh=5.0)

        assert validation.passed is False
        assert "Note:" not in validation.message


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

    @pytest.mark.parametrize(
        ("battery_capacity_kwh", "requirement"),
        [
            pytest.param(math.nan, "a finite number", id="nan"),
            pytest.param(math.inf, "a finite number", id="inf"),
            pytest.param(-1.0, "at least 0", id="-1.0"),
        ],
    )
    def test_a_battery_capacity_that_is_not_one_is_refused_naming_it(
        self, battery_capacity_kwh: float, requirement: str
    ) -> None:
        """A battery capacity that is negative or not finite is refused naming battery_capacity_kwh, never benchmarked as no battery."""
        results = _create_simulation_results(
            _create_minute_index(30),
            pv_capacity_kw=4.0,
            self_consumption_ratio=0.30,
            has_battery=False,
        )

        with pytest.raises(ValueError) as exc_info:
            validate_simulation(
                results,
                PVConfig(capacity_kw=4.0),
                battery_capacity_kwh=battery_capacity_kwh,
                target_annual_consumption_kwh=3400,
            )
        assert str(exc_info.value) == (
            f"battery_capacity_kwh must be {requirement}, got {battery_capacity_kwh!r}"
        )

    def test_the_pv_checks_use_the_wired_dc_of_the_pv_config_given(self) -> None:
        """Per the 1.0 kWp of four 250 W modules: 800 kWh/kWp, and a 1.1 kW peak limit."""
        results = dataclasses.replace(
            _create_simulation_results(_minute_index_over("2023-01-01", "2023-12-31")),
            generation=_year_of_generation(800.0),
        )

        report = validate_simulation(results, _PVWATTS_250_W_AT_1_1_KW)

        annual_yield = _annual_yield_check(report.results)
        assert annual_yield.passed is True
        assert annual_yield.value == pytest.approx(800.0)
        peak = _peak_check(report.results)
        assert peak.expected_range is not None
        assert peak.expected_range[1] == pytest.approx(1.1)
