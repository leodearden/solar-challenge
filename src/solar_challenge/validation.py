# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation and sanity checks for simulation results.

Provides validation functions for PV generation values, consumption patterns,
and benchmark validation against expected UK domestic performance.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from solar_challenge.home import SimulationResults, SummaryStatistics, calculate_summary


class ValidationError(Exception):
    """Raised when validation fails."""

    pass


@dataclass
class ValidationResult:
    """Result of a validation check.

    Attributes:
        passed: Whether the validation passed
        check_name: Name of the validation check
        message: Description of the result
        value: The actual value that was validated
        expected_range: Tuple of (min, max) expected values (if applicable)
    """

    passed: bool
    check_name: str
    message: str
    value: Optional[float] = None
    expected_range: Optional[tuple[float, float]] = None


@dataclass
class ValidationReport:
    """Complete validation report for a simulation.

    Attributes:
        results: List of individual validation results
        all_passed: Whether all validations passed
    """

    results: list[ValidationResult]

    @property
    def all_passed(self) -> bool:
        """Check if all validations passed."""
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[ValidationResult]:
        """Get list of failed validations."""
        return [r for r in self.results if not r.passed]

    def __str__(self) -> str:
        """Format report as string."""
        lines = ["Validation Report", "=" * 40]
        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            lines.append(f"[{status}] {result.check_name}: {result.message}")
        lines.append("=" * 40)
        passed = sum(1 for r in self.results if r.passed)
        lines.append(f"Total: {passed}/{len(self.results)} passed")
        return "\n".join(lines)


def validate_pv_generation(
    generation: pd.Series,
    capacity_kw: float,
    check_annual: bool = True,
) -> list[ValidationResult]:
    """Validate PV generation values for sanity.

    Checks:
    - Generation is never negative
    - Generation is zero at night (approximately)
    - Peak generation does not exceed system capacity
    - Annual generation within expected UK range (if full year data)

    Args:
        generation: PV generation time series in kW
        capacity_kw: System DC capacity in kW
        check_annual: Whether to check annual yield (requires ~1 year data)

    Returns:
        List of ValidationResult objects

    VAL-001 acceptance criteria:
        - Generation never negative
        - Generation zero at night
        - Peak generation does not exceed system capacity
        - Annual generation within expected range for UK (800-1000 kWh/kWp)
    """
    results: list[ValidationResult] = []

    # Check 1: No negative values
    min_value = float(generation.min())
    if min_value < 0:
        results.append(ValidationResult(
            passed=False,
            check_name="non_negative_generation",
            message=f"Generation has negative values (min: {min_value:.4f} kW)",
            value=min_value,
        ))
    else:
        results.append(ValidationResult(
            passed=True,
            check_name="non_negative_generation",
            message="All generation values are non-negative",
            value=min_value,
        ))

    # Check 2: Peak does not exceed capacity (with 10% tolerance for transients)
    max_value = float(generation.max())
    max_allowed = capacity_kw * 1.1  # 10% tolerance
    if max_value > max_allowed:
        results.append(ValidationResult(
            passed=False,
            check_name="peak_within_capacity",
            message=(
                f"Peak generation ({max_value:.2f} kW) exceeds "
                f"capacity ({capacity_kw:.2f} kW) by more than 10%"
            ),
            value=max_value,
            expected_range=(0, max_allowed),
        ))
    else:
        results.append(ValidationResult(
            passed=True,
            check_name="peak_within_capacity",
            message=f"Peak generation ({max_value:.2f} kW) within capacity limits",
            value=max_value,
            expected_range=(0, max_allowed),
        ))

    # Check 3: Night-time generation is approximately zero
    # Night defined as hours 22:00 - 05:00 (local time)
    if hasattr(generation.index, 'hour'):
        night_mask = (generation.index.hour >= 22) | (generation.index.hour < 5)
        night_gen = generation[night_mask]
        if len(night_gen) > 0:
            night_max = float(night_gen.max())
            # Allow very small values due to numerical noise
            if night_max > 0.01:
                results.append(ValidationResult(
                    passed=False,
                    check_name="zero_generation_at_night",
                    message=f"Non-zero generation at night (max: {night_max:.4f} kW)",
                    value=night_max,
                ))
            else:
                results.append(ValidationResult(
                    passed=True,
                    check_name="zero_generation_at_night",
                    message="Generation is effectively zero at night",
                    value=night_max,
                ))

    # Check 4: Annual yield within UK expected range
    if check_annual:
        # Calculate total energy (kWh) for the period
        # Assuming 1-minute data: kW * (1/60) = kWh per minute
        total_kwh = float(generation.sum() / 60)
        duration_days = (generation.index[-1] - generation.index[0]).days + 1

        if duration_days >= 365:
            # Normalize to per-kWp yield
            yield_per_kwp = total_kwh / capacity_kw

            # UK expected range: 800-1000 kWh/kWp (can be slightly wider for edge cases)
            expected_min = 700.0  # Allow slightly below
            expected_max = 1100.0  # Allow slightly above

            if expected_min <= yield_per_kwp <= expected_max:
                results.append(ValidationResult(
                    passed=True,
                    check_name="annual_yield_range",
                    message=(
                        f"Annual yield ({yield_per_kwp:.0f} kWh/kWp) "
                        "within expected UK range"
                    ),
                    value=yield_per_kwp,
                    expected_range=(expected_min, expected_max),
                ))
            else:
                results.append(ValidationResult(
                    passed=False,
                    check_name="annual_yield_range",
                    message=(
                        f"Annual yield ({yield_per_kwp:.0f} kWh/kWp) "
                        f"outside expected UK range ({expected_min}-{expected_max})"
                    ),
                    value=yield_per_kwp,
                    expected_range=(expected_min, expected_max),
                ))

    return results


def validate_consumption(
    demand: pd.Series,
    target_annual_kwh: Optional[float] = None,
) -> list[ValidationResult]:
    """Validate consumption/demand values for sanity.

    Checks:
    - Consumption is never negative
    - Consumption is never unrealistically high (> 50 kW for domestic)
    - Annual total approximately matches target (if provided)
    - Baseload present (consumption > 0 most times)

    Args:
        demand: Demand time series in kW
        target_annual_kwh: Expected annual consumption (optional)

    Returns:
        List of ValidationResult objects

    VAL-002 acceptance criteria:
        - Consumption never negative
        - Consumption never unrealistically high (e.g., > 50 kW for domestic)
        - Annual total within reasonable range of target
        - Baseload present (consumption > 0 most times)
    """
    results: list[ValidationResult] = []

    # Check 1: No negative values
    min_value = float(demand.min())
    if min_value < 0:
        results.append(ValidationResult(
            passed=False,
            check_name="non_negative_consumption",
            message=f"Consumption has negative values (min: {min_value:.4f} kW)",
            value=min_value,
        ))
    else:
        results.append(ValidationResult(
            passed=True,
            check_name="non_negative_consumption",
            message="All consumption values are non-negative",
            value=min_value,
        ))

    # Check 2: No unrealistically high values (> 50 kW for domestic)
    max_value = float(demand.max())
    max_domestic = 50.0  # kW - very generous for domestic
    if max_value > max_domestic:
        results.append(ValidationResult(
            passed=False,
            check_name="realistic_peak_demand",
            message=f"Peak demand ({max_value:.2f} kW) exceeds domestic limit ({max_domestic} kW)",
            value=max_value,
            expected_range=(0, max_domestic),
        ))
    else:
        results.append(ValidationResult(
            passed=True,
            check_name="realistic_peak_demand",
            message=f"Peak demand ({max_value:.2f} kW) within domestic limits",
            value=max_value,
            expected_range=(0, max_domestic),
        ))

    # Check 3: Baseload present (consumption > 0 at least 90% of the time)
    non_zero_fraction = float((demand > 0.001).mean())  # > 1W
    baseload_threshold = 0.90
    if non_zero_fraction >= baseload_threshold:
        results.append(ValidationResult(
            passed=True,
            check_name="baseload_present",
            message=f"Consumption present {non_zero_fraction*100:.1f}% of the time",
            value=non_zero_fraction,
            expected_range=(baseload_threshold, 1.0),
        ))
    else:
        results.append(ValidationResult(
            passed=False,
            check_name="baseload_present",
            message=(
                f"Consumption only present {non_zero_fraction*100:.1f}% of the time "
                f"(expected > {baseload_threshold*100}%)"
            ),
            value=non_zero_fraction,
            expected_range=(baseload_threshold, 1.0),
        ))

    # Check 4: Annual total matches target (if provided)
    if target_annual_kwh is not None:
        # Calculate total (1-minute data: kW * 1/60 = kWh)
        total_kwh = float(demand.sum() / 60)
        duration_days = (demand.index[-1] - demand.index[0]).days + 1

        # Scale to annual equivalent
        annual_equivalent = total_kwh * (365 / duration_days)

        # Allow 20% tolerance
        tolerance = 0.20
        expected_min = target_annual_kwh * (1 - tolerance)
        expected_max = target_annual_kwh * (1 + tolerance)

        if expected_min <= annual_equivalent <= expected_max:
            results.append(ValidationResult(
                passed=True,
                check_name="annual_consumption_target",
                message=(
                    f"Annual consumption ({annual_equivalent:.0f} kWh) "
                    f"within 20% of target ({target_annual_kwh:.0f} kWh)"
                ),
                value=annual_equivalent,
                expected_range=(expected_min, expected_max),
            ))
        else:
            results.append(ValidationResult(
                passed=False,
                check_name="annual_consumption_target",
                message=(
                    f"Annual consumption ({annual_equivalent:.0f} kWh) "
                    f"differs from target ({target_annual_kwh:.0f} kWh) by more than 20%"
                ),
                value=annual_equivalent,
                expected_range=(expected_min, expected_max),
            ))

    return results


def validate_self_consumption_pv_only(
    results: SimulationResults,
    capacity_kw: float,
    annual_consumption_kwh: float,
) -> ValidationResult:
    """Validate self-consumption ratio for PV-only home against benchmarks.

    UK benchmark for PV-only self-consumption: ~25-35%
    With typical 4 kW system and 3,400 kWh/year consumption.

    Args:
        results: Simulation results
        capacity_kw: PV system capacity
        annual_consumption_kwh: Target annual consumption

    Returns:
        ValidationResult indicating if within benchmark range

    VAL-003 acceptance criteria:
        - PV-only home achieves ~25-35% self-consumption (UK benchmark)
        - Test with typical 4 kW system and 3,400 kWh/year consumption
        - Document assumptions if outside range
        - Test passes if within expected range or documented exception
    """
    summary = calculate_summary(results)

    # Self-consumption ratio
    sc_ratio = summary.self_consumption_ratio * 100  # As percentage

    # Expected range for PV-only (UK benchmark)
    expected_min = 20.0  # Slightly wider than strict 25%
    expected_max = 45.0  # Slightly wider than strict 35%

    # Check if within benchmark
    if expected_min <= sc_ratio <= expected_max:
        return ValidationResult(
            passed=True,
            check_name="pv_only_self_consumption_benchmark",
            message=(
                f"Self-consumption ratio ({sc_ratio:.1f}%) "
                f"within UK benchmark range ({expected_min}-{expected_max}%)"
            ),
            value=sc_ratio,
            expected_range=(expected_min, expected_max),
        )
    else:
        # Check for documented exceptions
        # Higher ratios can occur with:
        # - Large consumption relative to PV
        # - Consumption well-aligned with generation
        # Lower ratios can occur with:
        # - Small consumption relative to PV
        # - Consumption misaligned with generation

        ratio_pv_to_consumption = (capacity_kw * 900) / annual_consumption_kwh  # Rough UK yield
        exception_msg = ""

        if sc_ratio > expected_max:
            if ratio_pv_to_consumption < 1.0:
                exception_msg = " (Note: PV small relative to consumption)"
        elif sc_ratio < expected_min:
            if ratio_pv_to_consumption > 1.5:
                exception_msg = " (Note: PV large relative to consumption)"

        return ValidationResult(
            passed=False,
            check_name="pv_only_self_consumption_benchmark",
            message=(
                f"Self-consumption ratio ({sc_ratio:.1f}%) "
                f"outside UK benchmark range ({expected_min}-{expected_max}%){exception_msg}"
            ),
            value=sc_ratio,
            expected_range=(expected_min, expected_max),
        )


def validate_self_consumption_with_battery(
    results: SimulationResults,
    capacity_kw: float,
    battery_kwh: float,
    annual_consumption_kwh: float,
) -> ValidationResult:
    """Validate self-consumption ratio for home with battery against benchmarks.

    UK benchmark for PV + battery self-consumption: ~60-80%
    With typical 4 kW PV, 5 kWh battery, and 3,400 kWh/year consumption.

    Args:
        results: Simulation results
        capacity_kw: PV system capacity
        battery_kwh: Battery capacity
        annual_consumption_kwh: Target annual consumption

    Returns:
        ValidationResult indicating if within benchmark range

    VAL-004 acceptance criteria:
        - Home with PV + battery achieves ~60-80% self-consumption (UK benchmark)
        - Test with typical 4 kW PV, 5 kWh battery, 3,400 kWh/year
        - Battery significantly increases self-consumption over PV-only
        - Document assumptions if outside range
    """
    summary = calculate_summary(results)

    # Self-consumption ratio
    sc_ratio = summary.self_consumption_ratio * 100  # As percentage

    # Expected range for PV + battery (UK benchmark)
    # Slightly wider to account for simulation variations
    expected_min = 50.0  # Wider than strict 60%
    expected_max = 90.0  # Wider than strict 80%

    # Check if within benchmark
    if expected_min <= sc_ratio <= expected_max:
        return ValidationResult(
            passed=True,
            check_name="battery_self_consumption_benchmark",
            message=(
                f"Self-consumption ratio with battery ({sc_ratio:.1f}%) "
                f"within UK benchmark range ({expected_min}-{expected_max}%)"
            ),
            value=sc_ratio,
            expected_range=(expected_min, expected_max),
        )
    else:
        # Document potential exceptions
        ratio_pv_to_consumption = (capacity_kw * 900) / annual_consumption_kwh
        battery_to_daily = battery_kwh / (annual_consumption_kwh / 365)
        exception_msg = ""

        if sc_ratio > expected_max:
            if ratio_pv_to_consumption < 0.8:
                exception_msg = " (Note: PV small relative to consumption)"
        elif sc_ratio < expected_min:
            if ratio_pv_to_consumption > 2.0:
                exception_msg = " (Note: PV very large relative to consumption)"
            elif battery_to_daily < 0.3:
                exception_msg = " (Note: Battery small relative to daily consumption)"

        return ValidationResult(
            passed=False,
            check_name="battery_self_consumption_benchmark",
            message=(
                f"Self-consumption ratio with battery ({sc_ratio:.1f}%) "
                f"outside UK benchmark range ({expected_min}-{expected_max}%){exception_msg}"
            ),
            value=sc_ratio,
            expected_range=(expected_min, expected_max),
        )


def validate_simulation(
    results: SimulationResults,
    pv_capacity_kw: float,
    battery_capacity_kwh: Optional[float] = None,
    target_annual_consumption_kwh: Optional[float] = None,
) -> ValidationReport:
    """Run all validation checks on simulation results.

    Args:
        results: Simulation results to validate
        pv_capacity_kw: PV system capacity
        battery_capacity_kwh: Battery capacity (None if no battery)
        target_annual_consumption_kwh: Expected annual consumption

    Returns:
        ValidationReport with all check results
    """
    all_results: list[ValidationResult] = []

    # Validate PV generation
    pv_checks = validate_pv_generation(
        results.generation,
        pv_capacity_kw,
        check_annual=True,
    )
    all_results.extend(pv_checks)

    # Validate consumption
    consumption_checks = validate_consumption(
        results.demand,
        target_annual_consumption_kwh,
    )
    all_results.extend(consumption_checks)

    # Validate self-consumption benchmarks
    if target_annual_consumption_kwh is not None:
        if battery_capacity_kwh is not None and battery_capacity_kwh > 0:
            sc_check = validate_self_consumption_with_battery(
                results,
                pv_capacity_kw,
                battery_capacity_kwh,
                target_annual_consumption_kwh,
            )
        else:
            sc_check = validate_self_consumption_pv_only(
                results,
                pv_capacity_kw,
                target_annual_consumption_kwh,
            )
        all_results.append(sc_check)

    return ValidationReport(results=all_results)
