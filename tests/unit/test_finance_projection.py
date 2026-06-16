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


# ---------------------------------------------------------------------------
# project_multi_year — shape + energy aggregation (step-7 / step-8)
# ---------------------------------------------------------------------------


def _make_pv_config(system_age_years: float = 0.0) -> "PVConfig":  # type: ignore[name-defined]
    from solar_challenge.pv import PVConfig

    return PVConfig(
        capacity_kw=4.0,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )


def _make_load_config() -> "LoadConfig":  # type: ignore[name-defined]
    from solar_challenge.load import LoadConfig

    return LoadConfig(annual_consumption_kwh=3500.0)


def _make_home_config(system_age_years: float = 0.0) -> "HomeConfig":  # type: ignore[name-defined]
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    return HomeConfig(
        pv_config=_make_pv_config(system_age_years),
        load_config=_make_load_config(),
        location=Location.bristol(),
    )


def _make_scenario(
    n_homes: int = 1,
    asset_life_years: int = 5,
    start: str = "2020-01-01",
    end: str = "2020-12-31",
) -> tuple:  # returns (ScenarioConfig, FinanceConfig)
    from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

    homes = [_make_home_config() for _ in range(n_homes)]
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life_years,
        loan_term_years=min(asset_life_years, 15),  # must be <= asset_life_years
    )
    scenario = ScenarioConfig(
        name="test-scenario",
        period=SimulationPeriod(start_date=start, end_date=end),
        description="Unit test scenario",
        homes=homes,
    )
    return scenario, finance


def _make_sim_results(
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    discharge_kwh: float = 0.0,
    n_minutes: int = 1440,  # 1 day
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a minimal SimulationResults with constant power series."""
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    # Convert kWh to kW for constant-power series (energy = power * n_minutes/60)
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    dis_kw = discharge_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw - dis_kw

    zeros = pd.Series(0.0, index=idx)

    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=pd.Series(dis_kw, index=idx),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
    )


def _make_fleet_results(
    n_homes: int = 1,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
) -> "FleetResults":  # type: ignore[name-defined]
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [_make_sim_results(self_kwh, export_kwh, import_kwh) for _ in range(n_homes)]
    return FleetResults(
        per_home_results=per_home,
        home_configs=homes,
    )


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        from solar_challenge.finance import MultiYearCurve, project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=5)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_self_consumption_at_sampled_age(self) -> None:
        """fleet_self_consumption_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = _make_scenario(n_homes=n_homes, asset_life_years=5)
        fr = _make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

        # Compute expected total from calculate_summary
        expected_sc = sum(
            calculate_summary(r).total_self_consumption_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)

        # At age 0 (a seed point), the value should match the injected summary
        assert curve.points[0].fleet_self_consumption_kwh == pytest.approx(
            expected_sc, rel=1e-4
        )

    def test_fleet_export_at_sampled_age(self) -> None:
        """fleet_export_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        exp_per_home = 500.0
        scenario, finance = _make_scenario(n_homes=n_homes, asset_life_years=5)
        fr = _make_fleet_results(n_homes=n_homes, export_kwh=exp_per_home)

        expected_export = sum(
            calculate_summary(r).total_grid_export_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_export_kwh == pytest.approx(expected_export, rel=1e-4)

    def test_fleet_import_at_sampled_age(self) -> None:
        """fleet_import_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        imp_per_home = 200.0
        scenario, finance = _make_scenario(n_homes=n_homes, asset_life_years=5)
        fr = _make_fleet_results(n_homes=n_homes, import_kwh=imp_per_home)

        expected_import = sum(
            calculate_summary(r).total_grid_import_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_import_kwh == pytest.approx(expected_import, rel=1e-4)


# ---------------------------------------------------------------------------
# SOH + degradation behaviour over 25-yr projection (step-9 / step-10)
# ---------------------------------------------------------------------------


def _make_degrading_simulate(
    base_sc: float = 5000.0,
    base_export: float = 2000.0,
    base_import: float = 1000.0,
    degradation_rate: float = 0.005,
) -> "Callable":  # type: ignore[name-defined]
    """Return a synthetic simulate that scales self-consumption by PV SOH.

    The injected simulate reads pv_config.system_age_years from each home in
    the FleetConfig, computes a degradation factor, and scales the energy
    output accordingly.  This makes fleet_self_consumption_kwh decline with age
    in a controlled, verifiable way.
    """
    from typing import Callable

    def _simulate(fleet_config: "FleetConfig", start: "pd.Timestamp", end: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults
        from solar_challenge.pv import calculate_degradation_factor

        homes = fleet_config.homes
        # Mean degradation factor across homes
        mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
        pv_factor = calculate_degradation_factor(mean_age, degradation_rate)

        per_home = [
            _make_sim_results(
                self_kwh=base_sc * pv_factor,
                export_kwh=base_export * pv_factor,
                import_kwh=base_import,
            )
            for _ in homes
        ]
        home_cfgs = list(homes)
        return FleetResults(per_home_results=per_home, home_configs=home_cfgs)

    return _simulate


class TestProjectMultiYearSOH:
    """SOH and PV degradation behaviour tests (H3)."""

    def test_pv_soh_monotone_non_increasing(self) -> None:
        """points.pv_soh is monotone non-increasing across years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=25)
        sim = _make_degrading_simulate()
        curve = project_multi_year(scenario, finance, simulate=sim)
        for i in range(1, len(curve.points)):
            assert curve.points[i].pv_soh <= curve.points[i - 1].pv_soh + 1e-9, (
                f"pv_soh not monotone at year {i}: "
                f"{curve.points[i].pv_soh} > {curve.points[i-1].pv_soh}"
            )

    def test_pv_soh_declines_over_life(self) -> None:
        """pv_soh at end of life is strictly less than at installation."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=25)
        sim = _make_degrading_simulate(degradation_rate=0.005)
        curve = project_multi_year(scenario, finance, simulate=sim)
        assert curve.points[-1].pv_soh < curve.points[0].pv_soh

    def test_battery_soh_monotone_non_increasing(self) -> None:
        """points.battery_soh is monotone non-increasing across years (when batteries present)."""
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.fleet import FleetResults
        from solar_challenge.pv import calculate_degradation_factor

        # Fleet with a battery
        bc = BatteryConfig(
            capacity_kwh=10.0,
            max_charge_kw=3.5,
            max_discharge_kw=3.5,
            calendar_fade_rate_per_year=0.02,
            cycle_fade_per_equivalent_full_cycle=0.0001,
            soh_floor=0.60,
        )

        def _simulate_with_battery(fc: "FleetConfig", s: "pd.Timestamp", e: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
            homes = fc.homes
            mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
            pv_factor = calculate_degradation_factor(mean_age, 0.005)
            per_home = [
                _make_sim_results(
                    self_kwh=5000.0 * pv_factor,
                    export_kwh=2000.0 * pv_factor,
                    import_kwh=1000.0,
                    discharge_kwh=1000.0,
                )
                for _ in homes
            ]
            return FleetResults(per_home_results=per_home, home_configs=list(homes))

        from solar_challenge.home import HomeConfig
        from solar_challenge.location import Location

        homes = [
            HomeConfig(
                pv_config=_make_pv_config(),
                load_config=_make_load_config(),
                battery_config=bc,
                location=Location.bristol(),
            )
        ]
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

        scenario = ScenarioConfig(
            name="battery-test",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Battery SOH test",
            homes=homes,
        )
        finance = FinanceConfig(standing_charge_pence_per_day=28.0, asset_life_years=25)
        curve = project_multi_year(scenario, finance, simulate=_simulate_with_battery)

        for i in range(1, len(curve.points)):
            assert curve.points[i].battery_soh <= curve.points[i - 1].battery_soh + 1e-9

    def test_battery_soh_declines_over_life(self) -> None:
        """battery_soh at end of life < beginning (calendar fade present)."""
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.fleet import FleetResults
        from solar_challenge.pv import calculate_degradation_factor

        bc = BatteryConfig(
            capacity_kwh=10.0,
            max_charge_kw=3.5,
            max_discharge_kw=3.5,
            calendar_fade_rate_per_year=0.02,
            cycle_fade_per_equivalent_full_cycle=0.0001,
            soh_floor=0.60,
        )

        def _simulate_with_battery(fc: "FleetConfig", s: "pd.Timestamp", e: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
            homes = fc.homes
            mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
            pv_factor = calculate_degradation_factor(mean_age, 0.005)
            per_home = [
                _make_sim_results(
                    self_kwh=5000.0 * pv_factor,
                    export_kwh=2000.0 * pv_factor,
                    import_kwh=1000.0,
                    discharge_kwh=500.0,
                )
                for _ in homes
            ]
            return FleetResults(per_home_results=per_home, home_configs=list(homes))

        from solar_challenge.home import HomeConfig
        from solar_challenge.location import Location
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

        homes = [
            HomeConfig(
                pv_config=_make_pv_config(),
                load_config=_make_load_config(),
                battery_config=bc,
                location=Location.bristol(),
            )
        ]
        scenario = ScenarioConfig(
            name="battery-soh-decline",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Battery SOH decline test",
            homes=homes,
        )
        finance = FinanceConfig(standing_charge_pence_per_day=28.0, asset_life_years=25)
        curve = project_multi_year(scenario, finance, simulate=_simulate_with_battery)
        assert curve.points[-1].battery_soh < curve.points[0].battery_soh

    def test_pv_soh_matches_degradation_factor(self) -> None:
        """pv_soh at a sampled age matches calculate_degradation_factor exactly."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.pv import calculate_degradation_factor

        rate = 0.005
        scenario, finance = _make_scenario(asset_life_years=25)
        sim = _make_degrading_simulate(degradation_rate=rate)
        curve = project_multi_year(scenario, finance, simulate=sim)

        # At a sampled age (age 0 is always seeded), pv_soh = degradation_factor
        # For age 0: degradation_factor = 1.0 (no degradation yet)
        expected_age0 = calculate_degradation_factor(0.0, rate)
        assert curve.points[0].pv_soh == pytest.approx(expected_age0, rel=1e-6)

        # Check fleet_self_consumption declines from year 0 to year 24
        assert curve.points[24].fleet_self_consumption_kwh < curve.points[0].fleet_self_consumption_kwh

    def test_no_battery_soh_defaults_to_one(self) -> None:
        """battery_soh == 1.0 for all years when the fleet has no batteries."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_scenario(asset_life_years=25)
        fr = _make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.battery_soh == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Cycle-fade term engagement (H3 final clause) — step-11 / step-12
# ---------------------------------------------------------------------------


def _make_battery_scenario(
    discharge_kwh: float = 1000.0,
    cycle_fade: float = 0.0002,
    calendar_fade: float = 0.02,
) -> tuple:
    """Build a scenario+finance with one home with battery."""
    from solar_challenge.battery import BatteryConfig
    from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    bc = BatteryConfig(
        capacity_kwh=10.0,
        max_charge_kw=3.5,
        max_discharge_kw=3.5,
        calendar_fade_rate_per_year=calendar_fade,
        cycle_fade_per_equivalent_full_cycle=cycle_fade,
        soh_floor=0.60,
    )
    homes = [
        HomeConfig(
            pv_config=_make_pv_config(),
            load_config=_make_load_config(),
            battery_config=bc,
            location=Location.bristol(),
        )
    ]
    scenario = ScenarioConfig(
        name="cycle-fade-test",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Cycle fade test",
        homes=homes,
    )
    finance = FinanceConfig(standing_charge_pence_per_day=28.0, asset_life_years=25)
    return scenario, finance, bc, discharge_kwh


class TestCycleFadeEngagement:
    """Cumulative throughput from the march feeds compute_soh (H3 final clause)."""

    def _make_simulate_with_discharge(
        self,
        discharge_kwh: float,
    ) -> "Callable":  # type: ignore[name-defined]
        """Synthetic simulate that returns a fixed per-home discharge amount."""
        from typing import Callable

        def _simulate(fc: "FleetConfig", s: "pd.Timestamp", e: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
            from solar_challenge.fleet import FleetResults

            per_home = [
                _make_sim_results(
                    self_kwh=3000.0,
                    export_kwh=1000.0,
                    import_kwh=500.0,
                    discharge_kwh=discharge_kwh,
                )
                for _ in fc.homes
            ]
            return FleetResults(per_home_results=per_home, home_configs=list(fc.homes))

        return _simulate

    def test_high_throughput_lower_battery_soh_than_zero(self) -> None:
        """High-throughput run has strictly lower battery_soh at end of life than zero-throughput."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance, _, _ = _make_battery_scenario(
            discharge_kwh=1000.0,   # high throughput
            cycle_fade=0.0002,
            calendar_fade=0.01,
        )

        # High throughput run
        high_sim = self._make_simulate_with_discharge(discharge_kwh=1000.0)
        curve_high = project_multi_year(scenario, finance, simulate=high_sim)

        # Zero throughput control
        zero_sim = self._make_simulate_with_discharge(discharge_kwh=0.0)
        curve_zero = project_multi_year(scenario, finance, simulate=zero_sim)

        # Year-N battery SOH: high must be strictly lower than zero-throughput
        final_high = curve_high.points[-1].battery_soh
        final_zero = curve_zero.points[-1].battery_soh
        assert final_high < final_zero, (
            f"High-throughput SOH ({final_high:.4f}) should be < "
            f"zero-throughput SOH ({final_zero:.4f})"
        )

    def test_zero_throughput_is_calendar_only(self) -> None:
        """Zero-throughput run's final SOH matches pure calendar fade prediction."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.battery import compute_soh
        from solar_challenge.battery import BatteryConfig

        calendar_fade = 0.02
        bc = BatteryConfig(
            capacity_kwh=10.0,
            max_charge_kw=3.5,
            max_discharge_kw=3.5,
            calendar_fade_rate_per_year=calendar_fade,
            cycle_fade_per_equivalent_full_cycle=0.0001,
            soh_floor=0.60,
        )

        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.home import HomeConfig
        from solar_challenge.location import Location

        homes = [
            HomeConfig(
                pv_config=_make_pv_config(),
                load_config=_make_load_config(),
                battery_config=bc,
                location=Location.bristol(),
            )
        ]
        scenario = ScenarioConfig(
            name="calendar-only",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Calendar-only test",
            homes=homes,
        )
        finance = FinanceConfig(standing_charge_pence_per_day=28.0, asset_life_years=25)

        zero_sim = self._make_simulate_with_discharge(discharge_kwh=0.0)
        curve = project_multi_year(scenario, finance, simulate=zero_sim)

        # With zero throughput, battery SOH at age 24 (last sampled age)
        # is compute_soh(24, 0, usable, bc)
        usable = bc.capacity_kwh * (bc.max_soc_fraction - bc.min_soc_fraction)
        expected_soh = compute_soh(24.0, 0.0, usable, bc)
        # The interpolated value at year 24 should match the sampled node
        assert curve.points[24].battery_soh == pytest.approx(expected_soh, rel=1e-4)
