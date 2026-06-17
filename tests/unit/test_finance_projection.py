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
    grid_charge_cost_gbp: float = 0.0,  # CR2: total grid-charge cost to inject (£)
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

    # Optionally inject grid_charge_cost as a constant-per-minute series.
    # NOTE: this bypasses the production grid_charge×rate path intentionally —
    # finance-layer tests need to control the cost total without re-running the
    # dispatch simulation.  gc_cost_per_min_gbp is cost-per-minute (£/min), not kW.
    gc_cost_series: "pd.Series | None" = None
    if grid_charge_cost_gbp != 0.0:
        gc_cost_per_min_gbp = grid_charge_cost_gbp / n_minutes
        gc_cost_series = pd.Series(gc_cost_per_min_gbp, index=idx, name="grid_charge_cost_gbp")

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
        grid_charge_cost=gc_cost_series,
    )


def _make_fleet_results(
    n_homes: int = 1,
    self_kwh: float = 24.0,
    export_kwh: float = 48.0,
    import_kwh: float = 12.0,
    grid_charge_cost_gbp: float = 0.0,  # CR2: per-home grid-charge cost to inject (£)
) -> "FleetResults":  # type: ignore[name-defined]
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [_make_sim_results(self_kwh, export_kwh, import_kwh,
                                   grid_charge_cost_gbp=grid_charge_cost_gbp)
                for _ in range(n_homes)]
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


# ---------------------------------------------------------------------------
# fleet_revenue_gbp + self-consumption override (step-13 / step-14)
# ---------------------------------------------------------------------------


class TestProjectMultiYearRevenue:
    """fleet_revenue_gbp aggregation and self-consumption override switch."""

    def _make_revenue_scenario(
        self,
        n_homes: int = 2,
        self_consumption_override: Optional[float] = None,
        seg_tariff_pence: Optional[float] = 5.0,
    ) -> tuple:
        """Build scenario + finance for revenue tests."""
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

        homes = [_make_home_config() for _ in range(n_homes)]
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            self_consumption_override=self_consumption_override,
            retail_baseline_rate_pence_per_kwh=30.0,
            vat_rate=0.05,
        )
        scenario = ScenarioConfig(
            name="revenue-test",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Revenue test",
            homes=homes,
            seg_tariff_pence_per_kwh=seg_tariff_pence,
        )
        return scenario, finance

    def _fixed_fleet_results(
        self,
        n_homes: int,
        self_kwh: float,
        export_kwh: float,
        import_kwh: float,
    ) -> "FleetResults":  # type: ignore[name-defined]
        return _make_fleet_results(n_homes=n_homes, self_kwh=self_kwh,
                                   export_kwh=export_kwh, import_kwh=import_kwh)

    def test_fleet_revenue_at_sampled_age_matches_householder_bill_sum(self) -> None:
        """fleet_revenue_gbp at age 0 equals CBS formula: own_use + seg - cbs_grid_charge_cost.

        CR2 RED test: the old formula used self_consumption_saving_gbp (priced at
        retail_baseline_rate=30p/kWh); the new formula uses own_use_rate_pence_per_kwh
        (default 15p/kWh) × fleet_sc + Σ seg_export_income_gbp - Σ total_grid_charge_cost_gbp.
        These rates differ, so this test fails against the old _simulate_age implementation.
        """
        from solar_challenge.finance import householder_bill, project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc, exp, imp = 3000.0, 1500.0, 500.0
        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)
        fr = self._fixed_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp)

        # Compute expected CBS revenue via new formula (PRD §3.2)
        summaries = [calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
                     for r in fr.per_home_results]
        fleet_sc_kwh = sum(s.total_self_consumption_kwh for s in summaries)
        bills = [
            householder_bill(
                s,
                annual_self_consumption_kwh=s.total_self_consumption_kwh,
                finance=finance,
                simulation_days=s.simulation_days,
            )
            for s in summaries
        ]
        # New formula (no grid_services since homes have no battery):
        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc_kwh / 100.0
        seg_revenue = sum(b.seg_export_income_gbp for b in bills)
        cbs_grid_charge_cost = sum(s.total_grid_charge_cost_gbp for s in summaries)
        expected_revenue = own_use_revenue + seg_revenue - cbs_grid_charge_cost

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        # At year 0 (a seeded age), the revenue should match the CBS formula
        assert curve.points[0].fleet_revenue_gbp == pytest.approx(expected_revenue, rel=1e-4)

    def test_grid_services_included_in_fleet_revenue(self) -> None:
        """fleet_revenue_gbp includes grid_services = rate × Σ max_discharge_kw when rate > 0.

        CR2 RED test: the old _simulate_age has no grid_services term, so this assertion
        will fail until step-6 adds it.
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.fleet import FleetResults
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import HomeConfig
        from solar_challenge.location import Location

        # Battery-equipped home so max_discharge_kw is available
        bat_config = BatteryConfig(capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5)
        home_with_bat = HomeConfig(
            pv_config=_make_pv_config(),
            load_config=_make_load_config(),
            location=Location.bristol(),
            battery_config=bat_config,
        )
        n_homes = 2
        homes = [home_with_bat] * n_homes
        grid_services_rate = 50.0  # £/kW/year

        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=5,
            loan_term_years=5,  # must be <= asset_life_years
            own_use_rate_pence_per_kwh=15.0,
            grid_services_income_per_kw_per_year_gbp=grid_services_rate,
        )
        scenario = ScenarioConfig(
            name="gs-test",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Grid services test",
            homes=homes,
        )

        # Synthetic fleet results with no grid_charge_cost
        fr_bat = FleetResults(
            per_home_results=[_make_sim_results(self_kwh=3000.0, export_kwh=500.0, import_kwh=300.0)
                               for _ in range(n_homes)],
            home_configs=homes,
        )
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr_bat)

        # Expected grid_services contribution at age 0
        total_discharge_kw = n_homes * bat_config.max_discharge_kw
        expected_gs = grid_services_rate * total_discharge_kw
        assert curve.points[0].fleet_revenue_gbp >= expected_gs - 1e-6, (
            f"fleet_revenue_gbp ({curve.points[0].fleet_revenue_gbp:.4f}) should include "
            f"grid_services ({expected_gs:.4f} = {grid_services_rate} × {total_discharge_kw} kW)"
        )

    def test_h5_zero_grid_charge_cost_term(self) -> None:
        """H5 invariant: fleet with total_grid_charge_cost_gbp==0 → cbs_grid_charge_cost==0.

        fleet_revenue_gbp == own_use_revenue + seg_revenue + grid_services (no deduction).
        """
        from solar_challenge.finance import householder_bill, project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 1
        sc, exp, imp = 2000.0, 800.0, 300.0
        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)
        # Injected results have grid_charge_cost=None → total_grid_charge_cost_gbp=0.0
        fr = _make_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp,
                                  grid_charge_cost_gbp=0.0)

        summaries = [calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
                     for r in fr.per_home_results]
        fleet_sc_kwh = sum(s.total_self_consumption_kwh for s in summaries)
        bills = [
            householder_bill(
                s,
                annual_self_consumption_kwh=s.total_self_consumption_kwh,
                finance=finance,
                simulation_days=s.simulation_days,
            )
            for s in summaries
        ]

        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc_kwh / 100.0
        seg_revenue = sum(b.seg_export_income_gbp for b in bills)
        expected_revenue = own_use_revenue + seg_revenue  # no deduction (cbs_cost==0)

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_revenue_gbp == pytest.approx(expected_revenue, rel=1e-4)
        # And the cbs_cost is strictly 0 (H5)
        assert curve.points[0].fleet_revenue_gbp == pytest.approx(
            own_use_revenue + seg_revenue, rel=1e-4
        )

    def test_h9_grid_charge_cost_reduces_fleet_revenue(self) -> None:
        """H9 no-double-count: injecting grid_charge_cost reduces fleet_revenue by exactly
        Σ total_grid_charge_cost_gbp versus the same fleet with zero grid_charge_cost.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        n_homes = 2
        sc, exp, imp = 3000.0, 1500.0, 500.0
        per_home_gc_cost = 12.50  # £ per home

        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)

        # Zero grid_charge_cost fleet
        fr_zero = _make_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp,
                                       grid_charge_cost_gbp=0.0)
        # Non-zero grid_charge_cost fleet (same energy, but with cost)
        fr_gc = _make_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp,
                                     grid_charge_cost_gbp=per_home_gc_cost)

        curve_zero = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr_zero)
        curve_gc = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr_gc)

        expected_deduction = n_homes * per_home_gc_cost
        actual_deduction = curve_zero.points[0].fleet_revenue_gbp - curve_gc.points[0].fleet_revenue_gbp

        assert actual_deduction == pytest.approx(expected_deduction, rel=1e-4), (
            f"Expected fleet_revenue to be reduced by exactly {expected_deduction:.4f} £ "
            f"(Σ total_grid_charge_cost_gbp), got {actual_deduction:.4f} £"
        )

    def test_self_consumption_override_does_not_change_own_use_revenue(self) -> None:
        """CBS own_use_revenue is override-invariant: own_use_rate × fleet_sc / 100 uses
        physics fleet_sc regardless of self_consumption_override.

        Updated for CR2: the OLD formula (retail_rate × sc_saving_kwh) DID change with the
        override (different sc_kwh). The NEW formula (own_use_rate × PHYSICS fleet_sc) does
        NOT change because fleet_sc comes from the simulation results, not the override.
        This RED-fails against the old implementation which used self_consumption_saving_gbp.
        """
        from solar_challenge.finance import householder_bill, project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 1
        sc, exp, imp = 4000.0, 1000.0, 500.0
        fr = _make_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp)

        # Physics path (no override)
        scenario_phys, finance_phys = self._make_revenue_scenario(
            n_homes=n_homes,
            self_consumption_override=None,
        )
        curve_phys = project_multi_year(scenario_phys, finance_phys, simulate=lambda fc, s, e: fr)

        # Spreadsheet path (with override — different SC fraction)
        scenario_over, finance_over = self._make_revenue_scenario(
            n_homes=n_homes,
            self_consumption_override=0.50,  # 50% of gen, changes SC calc in householder_bill
        )
        curve_over = project_multi_year(scenario_over, finance_over, simulate=lambda fc, s, e: fr)

        # Under the NEW CBS formula: own_use_revenue = own_use_rate × PHYSICS fleet_sc / 100.
        # Physics fleet_sc is the same in both paths (from the injected SimulationResults),
        # so own_use_revenue is identical. With zero export_revenue in the mock SimulationResults,
        # seg_revenue is also zero. Hence both paths produce the SAME fleet_revenue_gbp.
        # (This would FAIL under the OLD formula where self_consumption_saving changed with override.)
        assert curve_phys.points[0].fleet_revenue_gbp == pytest.approx(
            curve_over.points[0].fleet_revenue_gbp, rel=1e-4
        )

    def test_fleet_revenue_non_negative(self) -> None:
        """fleet_revenue_gbp is non-negative for all years (updated for CR2 formula)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = self._make_revenue_scenario(n_homes=1)
        # No grid_charge_cost → CBS deduction is 0 → own_use + seg >= 0 always
        fr = _make_fleet_results(n_homes=1, self_kwh=2000.0, export_kwh=800.0, import_kwh=300.0,
                                  grid_charge_cost_gbp=0.0)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.fleet_revenue_gbp >= 0.0


# ---------------------------------------------------------------------------
# Adaptive node refinement — H4 (step-15 / step-16)
# ---------------------------------------------------------------------------


def _make_curved_simulate(curvature: float = 0.35) -> "Callable":  # type: ignore[name-defined]
    """Return a synthetic simulate with strongly non-linear (exponential) decline.

    fleet_self_consumption_kwh declines as base * exp(-curvature * age).
    With only 3 seed nodes, PCHIP will have large midpoint errors for high
    curvature values (the function is far from piecewise-cubic on wide intervals).
    """
    import math
    from typing import Callable

    BASE_SC = 12_000.0
    BASE_EXP = 3_000.0

    def _simulate(fleet_config: "FleetConfig", start: "pd.Timestamp", end: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        homes = fleet_config.homes
        mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
        factor = math.exp(-curvature * mean_age)
        per_home = [
            _make_sim_results(
                self_kwh=max(0.1, BASE_SC * factor),
                export_kwh=max(0.1, BASE_EXP * factor),
                import_kwh=500.0,
            )
            for _ in homes
        ]
        return FleetResults(per_home_results=per_home, home_configs=list(homes))

    return _simulate


def _make_adaptive_scenario(asset_life: int = 10) -> tuple:
    """Build a scenario+finance pair for adaptive refinement tests."""
    from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod

    homes = [_make_home_config()]
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life,
        loan_term_years=min(asset_life, 15),
        retail_baseline_rate_pence_per_kwh=30.0,
        vat_rate=0.05,
    )
    scenario = ScenarioConfig(
        name="adaptive-test",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Adaptive refinement test",
        homes=homes,
    )
    return scenario, finance


class TestProjectMultiYearAdaptive:
    """Adaptive node refinement tests (H4) for step-15/step-16.

    Uses an injected simulate that returns an exponential decline, which has
    substantial PCHIP midpoint error when only 3 coarse seed nodes are used.
    The tests assert that adaptive bisection (step-16) reduces that error.
    """

    _ASSET_LIFE = 10  # short life makes tests faster; {0, 5, 9} are the 3 seeds

    def test_adaptive_adds_nodes_beyond_seeds_with_tight_target(self) -> None:
        """With a curved simulate and tight error target, more than 3 nodes are sampled.

        Currently FAILS (RED) because project_multi_year always returns exactly
        the 3 seed ages with no adaptive bisection (step-16 not yet implemented).
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)  # steep exponential — large PCHIP error
        n_seeds = len({0, self._ASSET_LIFE // 2, self._ASSET_LIFE - 1})  # == 3

        # Very tight target → adaptive bisection must add nodes beyond the 3 seeds
        curve = project_multi_year(scenario, finance, error_target_pct=0.01, simulate=sim)
        assert len(curve.sampled_ages) > n_seeds, (
            f"Expected more than {n_seeds} sampled ages with tight 0.01% target; "
            f"got {len(curve.sampled_ages)}: {curve.sampled_ages}"
        )

    def test_tighter_target_yields_strictly_more_nodes(self) -> None:
        """A tighter error_target_pct produces strictly more sampled_ages than a loose target.

        Currently FAILS (RED): both loose and tight targets return exactly 3 nodes
        because adaptive bisection is not yet implemented.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)

        # Loose target (50%): likely satisfied by the 3 seed nodes alone
        loose_curve = project_multi_year(scenario, finance, error_target_pct=50.0, simulate=sim)
        # Tight target (0.01%): requires many more nodes
        tight_curve = project_multi_year(scenario, finance, error_target_pct=0.01, simulate=sim)

        assert len(tight_curve.sampled_ages) > len(loose_curve.sampled_ages), (
            f"tight (0.01%) should yield more nodes than loose (50.0%): "
            f"tight={len(tight_curve.sampled_ages)}, loose={len(loose_curve.sampled_ages)}"
        )

    def test_sampled_ages_bounded_by_max_nodes(self) -> None:
        """sampled_ages count never exceeds MAX_NODES (safety invariant).

        An impossibly tight target causes the adaptive loop to run until capped.
        MAX_NODES is the hard bound.
        """
        from solar_challenge.finance import MAX_NODES, project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)

        # Impossible target: will hit cap
        curve = project_multi_year(scenario, finance, error_target_pct=1e-9, simulate=sim)
        assert len(curve.sampled_ages) <= MAX_NODES, (
            f"sampled_ages count {len(curve.sampled_ages)} exceeds MAX_NODES {MAX_NODES}"
        )

    def test_interp_error_estimate_non_negative(self) -> None:
        """interp_error_estimate is always >= 0 (convergence invariant)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.3)
        curve = project_multi_year(scenario, finance, error_target_pct=1.0, simulate=sim)
        assert curve.interp_error_estimate >= 0.0

    def test_interp_error_within_target_when_converged(self) -> None:
        """After convergence, interp_error_estimate <= error_target_pct.

        A loose enough target (50%) lets adaptive bisection converge quickly;
        the surfaced error estimate must be <= that target.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.3)
        curve = project_multi_year(scenario, finance, error_target_pct=50.0, simulate=sim)
        assert curve.interp_error_estimate <= 50.0, (
            f"interp_error_estimate {curve.interp_error_estimate:.4f} > target 50.0"
        )

    def test_per_year_curves_monotone_after_adaptive(self) -> None:
        """Per-year curves remain monotone non-increasing after adaptive refinement."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.4)
        curve = project_multi_year(scenario, finance, error_target_pct=1.0, simulate=sim)
        for i in range(1, len(curve.points)):
            assert curve.points[i].fleet_self_consumption_kwh <= (
                curve.points[i - 1].fleet_self_consumption_kwh + 1e-6
            ), (
                f"fleet_self_consumption not monotone at year {i}: "
                f"{curve.points[i].fleet_self_consumption_kwh:.3f} > "
                f"{curve.points[i-1].fleet_self_consumption_kwh:.3f}"
            )
