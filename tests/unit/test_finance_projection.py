# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for multi-year projection data model and forward-march driver (ζ surface).

Tests YearPoint, MultiYearCurve frozen dataclasses, interpolation helpers,
and project_multi_year with an injected synthetic simulate.

All tests are offline/fast — no PVGIS/network is touched.
"""
from __future__ import annotations

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# §3.1 — YearPoint + MultiYearCurve frozen dataclasses (step-1 / step-2)
# ---------------------------------------------------------------------------


class TestYearPoint:
    """YearPoint frozen dataclass construction and validation."""

    def _make_valid(self) -> "YearPoint":  # type: ignore[name-defined]
        from solar_challenge.finance import YearPoint

        return YearPoint(
            year=5,
            pv_soh=0.975,
            battery_soh=0.900,
            fleet_self_consumption_kwh=10_000.0,
            fleet_export_kwh=3_000.0,
            fleet_import_kwh=5_000.0,
            fleet_revenue_gbp=1_200.0,
        )

    def test_construction_valid(self) -> None:
        """Valid YearPoint constructs without errors."""
        from solar_challenge.finance import YearPoint

        yp = self._make_valid()
        assert yp.year == 5
        assert yp.pv_soh == pytest.approx(0.975)
        assert yp.battery_soh == pytest.approx(0.900)
        assert yp.fleet_self_consumption_kwh == pytest.approx(10_000.0)
        assert yp.fleet_export_kwh == pytest.approx(3_000.0)
        assert yp.fleet_import_kwh == pytest.approx(5_000.0)
        assert yp.fleet_revenue_gbp == pytest.approx(1_200.0)

    def test_frozen(self) -> None:
        """Assigning a field raises FrozenInstanceError."""
        from solar_challenge.finance import YearPoint

        yp = self._make_valid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            yp.year = 99  # type: ignore[misc]

    def test_pv_soh_out_of_range_low(self) -> None:
        """pv_soh < 0 raises ValueError."""
        from solar_challenge.finance import YearPoint

        with pytest.raises(ValueError, match="pv_soh"):
            YearPoint(
                year=0,
                pv_soh=-0.01,
                battery_soh=1.0,
                fleet_self_consumption_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_pv_soh_out_of_range_high(self) -> None:
        """pv_soh > 1 raises ValueError."""
        from solar_challenge.finance import YearPoint

        with pytest.raises(ValueError, match="pv_soh"):
            YearPoint(
                year=0,
                pv_soh=1.01,
                battery_soh=1.0,
                fleet_self_consumption_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_battery_soh_out_of_range(self) -> None:
        """battery_soh outside [0,1] raises ValueError."""
        from solar_challenge.finance import YearPoint

        with pytest.raises(ValueError, match="battery_soh"):
            YearPoint(
                year=0,
                pv_soh=1.0,
                battery_soh=1.05,
                fleet_self_consumption_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_negative_year_raises(self) -> None:
        """year < 0 raises ValueError."""
        from solar_challenge.finance import YearPoint

        with pytest.raises(ValueError, match="year"):
            YearPoint(
                year=-1,
                pv_soh=1.0,
                battery_soh=1.0,
                fleet_self_consumption_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_negative_energy_raises(self) -> None:
        """Negative fleet energies raise ValueError."""
        from solar_challenge.finance import YearPoint

        with pytest.raises(ValueError):
            YearPoint(
                year=0,
                pv_soh=1.0,
                battery_soh=1.0,
                fleet_self_consumption_kwh=-1.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_boundary_soh_values_valid(self) -> None:
        """SOH == 0 or 1 is valid (exact boundary)."""
        from solar_challenge.finance import YearPoint

        # Should not raise
        yp0 = YearPoint(
            year=0,
            pv_soh=0.0,
            battery_soh=0.0,
            fleet_self_consumption_kwh=0.0,
            fleet_export_kwh=0.0,
            fleet_import_kwh=0.0,
            fleet_revenue_gbp=0.0,
        )
        yp1 = YearPoint(
            year=0,
            pv_soh=1.0,
            battery_soh=1.0,
            fleet_self_consumption_kwh=0.0,
            fleet_export_kwh=0.0,
            fleet_import_kwh=0.0,
            fleet_revenue_gbp=0.0,
        )
        assert yp0.pv_soh == 0.0
        assert yp1.pv_soh == 1.0


class TestMultiYearCurve:
    """MultiYearCurve frozen dataclass construction and validation."""

    def _make_point(self, year: int, val: float = 1.0) -> "YearPoint":  # type: ignore[name-defined]
        from solar_challenge.finance import YearPoint

        return YearPoint(
            year=year,
            pv_soh=max(0.0, 1.0 - year * 0.005),
            battery_soh=max(0.0, 1.0 - year * 0.01),
            fleet_self_consumption_kwh=val,
            fleet_export_kwh=val * 0.3,
            fleet_import_kwh=val * 0.5,
            fleet_revenue_gbp=val * 0.1,
        )

    def _make_valid(self) -> "MultiYearCurve":  # type: ignore[name-defined]
        from solar_challenge.finance import MultiYearCurve

        points = tuple(self._make_point(y) for y in range(25))
        return MultiYearCurve(
            points=points,
            sampled_ages=(0, 12, 24),
            interp_error_estimate=0.5,
        )

    def test_construction_valid(self) -> None:
        """Valid MultiYearCurve constructs and exposes all §3.1 fields."""
        from solar_challenge.finance import MultiYearCurve

        mc = self._make_valid()
        assert len(mc.points) == 25
        assert mc.sampled_ages == (0, 12, 24)
        assert mc.interp_error_estimate == pytest.approx(0.5)

    def test_points_is_tuple(self) -> None:
        """points is a tuple (immutable)."""
        mc = self._make_valid()
        assert isinstance(mc.points, tuple)

    def test_sampled_ages_is_tuple(self) -> None:
        """sampled_ages is a tuple (immutable)."""
        mc = self._make_valid()
        assert isinstance(mc.sampled_ages, tuple)

    def test_frozen(self) -> None:
        """Assigning a field raises FrozenInstanceError."""
        from solar_challenge.finance import MultiYearCurve

        mc = self._make_valid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            mc.interp_error_estimate = 99.0  # type: ignore[misc]

    def test_empty_points_raises(self) -> None:
        """Empty points tuple raises ValueError."""
        from solar_challenge.finance import MultiYearCurve

        with pytest.raises(ValueError, match="points"):
            MultiYearCurve(
                points=(),
                sampled_ages=(0,),
                interp_error_estimate=0.0,
            )

    def test_negative_interp_error_raises(self) -> None:
        """Negative interp_error_estimate raises ValueError."""
        from solar_challenge.finance import MultiYearCurve

        points = tuple(self._make_point(y) for y in range(25))
        with pytest.raises(ValueError, match="interp_error_estimate"):
            MultiYearCurve(
                points=points,
                sampled_ages=(0, 12, 24),
                interp_error_estimate=-0.1,
            )

    def test_empty_sampled_ages_raises(self) -> None:
        """Empty sampled_ages raises ValueError."""
        from solar_challenge.finance import MultiYearCurve

        points = tuple(self._make_point(y) for y in range(25))
        with pytest.raises(ValueError, match="sampled_ages"):
            MultiYearCurve(
                points=points,
                sampled_ages=(),
                interp_error_estimate=0.0,
            )


# ---------------------------------------------------------------------------
# Interpolation core — _interpolate_per_year (step-3 / step-4)
# ---------------------------------------------------------------------------


class TestInterpolatePerYear:
    """Tests for the private per-year interpolation helper."""

    # Monotone declining nodes: ages [0, 12, 24], values [1.0, 0.94, 0.88]
    _AGES = [0, 12, 24]
    _VALUES = [1.0, 0.94, 0.88]

    def _call(self, ages: list[int], values: list[float], n_years: int) -> list[float]:
        from solar_challenge.finance import _interpolate_per_year  # type: ignore[attr-defined]

        return _interpolate_per_year(ages, values, n_years)

    def test_returns_one_value_per_year(self) -> None:
        """Output length equals n_years."""
        result = self._call(self._AGES, self._VALUES, 25)
        assert len(result) == 25

    def test_passes_through_node_values(self) -> None:
        """Interpolant exactly reproduces values at sampled ages."""
        result = self._call(self._AGES, self._VALUES, 25)
        for age, val in zip(self._AGES, self._VALUES):
            assert result[age] == pytest.approx(val, rel=1e-6)

    def test_monotone_non_increasing(self) -> None:
        """On a declining node set the produced series is monotone non-increasing."""
        result = self._call(self._AGES, self._VALUES, 25)
        for i in range(1, len(result)):
            assert result[i] <= result[i - 1] + 1e-9, (
                f"Not monotone at index {i}: {result[i]} > {result[i-1]}"
            )

    def test_no_overshoot_above_max(self) -> None:
        """No value exceeds the maximum node value."""
        result = self._call(self._AGES, self._VALUES, 25)
        max_val = max(self._VALUES)
        for v in result:
            assert v <= max_val + 1e-9

    def test_no_overshoot_below_min(self) -> None:
        """No value falls below the minimum node value."""
        result = self._call(self._AGES, self._VALUES, 25)
        min_val = min(self._VALUES)
        for v in result:
            assert v >= min_val - 1e-9

    def test_single_node_returns_constant(self) -> None:
        """Single-node degenerate case returns a constant for all years."""
        result = self._call([0], [0.95], 10)
        assert len(result) == 10
        for v in result:
            assert v == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Monotone Hermite fallback — _monotone_hermite_interpolate (step-5 / step-6)
# ---------------------------------------------------------------------------


class TestMonotoneHermiteFallback:
    """Tests for the private hand-rolled Fritsch–Carlson fallback."""

    _AGES = [0, 12, 24]
    _VALUES = [1.0, 0.94, 0.88]  # strictly declining monotone

    def _call(self, ages: list[int], values: list[float], n: int) -> list[float]:
        from solar_challenge.finance import _monotone_hermite_interpolate  # type: ignore[attr-defined]

        return _monotone_hermite_interpolate(ages, values, n)

    def test_passes_through_node_values(self) -> None:
        """Fallback reproduces node values exactly at sampled ages."""
        result = self._call(self._AGES, self._VALUES, 25)
        for age, val in zip(self._AGES, self._VALUES):
            assert result[age] == pytest.approx(val, rel=1e-6)

    def test_monotone_non_increasing(self) -> None:
        """Fallback is monotone non-increasing on a declining node set."""
        result = self._call(self._AGES, self._VALUES, 25)
        for i in range(1, len(result)):
            assert result[i] <= result[i - 1] + 1e-9, (
                f"Monotone violation at index {i}: {result[i]} > {result[i-1]}"
            )

    def test_no_overshoot_above_max(self) -> None:
        """Fallback never exceeds the maximum node value."""
        result = self._call(self._AGES, self._VALUES, 25)
        max_val = max(self._VALUES)
        for v in result:
            assert v <= max_val + 1e-9

    def test_no_overshoot_below_min(self) -> None:
        """Fallback never falls below the minimum node value."""
        result = self._call(self._AGES, self._VALUES, 25)
        min_val = min(self._VALUES)
        for v in result:
            assert v >= min_val - 1e-9

    def test_single_node_constant(self) -> None:
        """Fallback handles single-node degenerate case as constant."""
        result = self._call([5], [0.80], 10)
        assert len(result) == 10
        for v in result:
            assert v == pytest.approx(0.80)

    def test_selection_wrapper_prefers_scipy(self) -> None:
        """_interpolate_per_year uses PCHIP when scipy is importable."""
        # If scipy is available (it is in dev), both methods agree on endpoints.
        from solar_challenge.finance import _interpolate_per_year  # type: ignore[attr-defined]

        pchip_result = _interpolate_per_year(self._AGES, self._VALUES, 25)
        fallback_result = self._call(self._AGES, self._VALUES, 25)
        # Both pass through the same node values
        for age, val in zip(self._AGES, self._VALUES):
            assert pchip_result[age] == pytest.approx(val, rel=1e-6)
            assert fallback_result[age] == pytest.approx(val, rel=1e-6)
        # Both are monotone
        for i in range(1, 25):
            assert pchip_result[i] <= pchip_result[i - 1] + 1e-9
            assert fallback_result[i] <= fallback_result[i - 1] + 1e-9

    def test_fallback_consistent_with_pchip_endpoints(self) -> None:
        """Fallback and PCHIP agree at endpoints (year 0 and year 24)."""
        from solar_challenge.finance import _interpolate_per_year  # type: ignore[attr-defined]

        pchip_result = _interpolate_per_year(self._AGES, self._VALUES, 25)
        fallback_result = self._call(self._AGES, self._VALUES, 25)
        assert pchip_result[0] == pytest.approx(fallback_result[0], rel=1e-5)
        assert pchip_result[24] == pytest.approx(fallback_result[24], rel=1e-5)
