# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year, the multi-year projection's forward-march driver.

The projection runs on an injected synthetic simulate.  The tests cover the
curve's shape and energy aggregation, PV and battery ageing, CBS revenue,
adaptive node refinement, scenario-level SEG and short-window annualisation,
and the projection's SEG helpers _seg_export_income_gbp and _reconcile_seg_homes.

All tests are offline/fast — no PVGIS/network is touched.
"""
from __future__ import annotations

import dataclasses

import pytest


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
    export_revenue_gbp: float = 0.0,
    n_steps: int = 8760,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Constant-power SimulationResults whose totals are the kWh and £ arguments; a full year by default.

    Hourly index with kW = kWh / (n_steps / 60), so calculate_summary's 1/60
    integration returns the kWh totals, and the default 8760 steps give
    simulation_days 365.  export_revenue_gbp is spread evenly over the steps,
    so it is the summary's total_export_revenue_gbp, the physics SEG income.
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_steps, freq="1h", tz="Europe/London")
    sc_kw = self_kwh / (n_steps / 60.0)
    exp_kw = export_kwh / (n_steps / 60.0)
    imp_kw = import_kwh / (n_steps / 60.0)
    dis_kw = discharge_kwh / (n_steps / 60.0)
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
        export_revenue=pd.Series(export_revenue_gbp / n_steps, index=idx),
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
    per_home = [_make_sim_results(self_kwh, export_kwh, import_kwh)
                for _ in range(n_homes)]
    return FleetResults(
        per_home_results=per_home,
        home_configs=homes,
    )


def _make_grid_charging_sim_results(
    sc_kwh: float = 2000.0,
    export_kwh: float = 400.0,
    import_to_load_kwh: float = 800.0,
    grid_charge_kwh: float = 200.0,
    peak_pence: float = 30.0,
    off_peak_pence: float = 9.0,
    n_steps: int = 8760,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Full-year TOU home whose battery grid-charges off-peak through the grid meter.

    Grid charge is metered import: grid_import = import_to_load + grid_charge, with
    load import priced at peak and grid charge at off-peak, and grid_charge_cost the
    grid-charge slice of import_cost.  self_consumption is B-style (it includes the
    grid-charged discharge), so basis-C own-use = demand − import = sc − grid_charge.
    Defaults give per home: total_import_cost_gbp £258.00, of which
    total_grid_charge_cost_gbp £18.00; basis-C own-use 1800 kWh.

    Hourly index with kW = kWh / (n_steps / 60), so calculate_summary's 1/60
    integration returns the kWh totals and simulation_days is 365.
    """
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2024-01-01", periods=n_steps, freq="1h", tz="Europe/London")

    def constant_kw(kwh: float) -> "pd.Series":
        return pd.Series(kwh / (n_steps / 60.0), index=idx)

    def constant_gbp(pence: float) -> "pd.Series":
        return pd.Series(pence / 100.0 / n_steps, index=idx)

    zeros = pd.Series(0.0, index=idx)
    grid_charge_pence = grid_charge_kwh * off_peak_pence
    return SimulationResults(
        generation=constant_kw(sc_kwh + export_kwh),
        demand=constant_kw(sc_kwh + import_to_load_kwh),
        self_consumption=constant_kw(sc_kwh),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=constant_kw(import_to_load_kwh + grid_charge_kwh),
        grid_export=constant_kw(export_kwh),
        import_cost=constant_gbp(import_to_load_kwh * peak_pence + grid_charge_pence),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=constant_gbp(grid_charge_pence),
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
# Battery SOH counts the throughput up to each sampled age
# ---------------------------------------------------------------------------

_ANNUAL_DISCHARGE_KWH = 800.0


def _make_battery_ageing_simulate(
    discharge_kwh: "Callable[[HomeConfig], float]",  # type: ignore[name-defined]
) -> "Callable":  # type: ignore[name-defined]
    """A simulate whose own-use decays with PV age and whose battery discharges discharge_kwh(home) a year.

    ``home`` is the aged HomeConfig the projection simulates, so a profile can
    read its PV age or its injected battery SOH.  Basis-C own-use
    (demand − import) is 3000 kWh × exp(−0.1 × PV age) whatever the discharge,
    so the ages bisection samples depend on PV age alone.
    """
    import math

    def _simulate(fc: "FleetConfig", s: "pd.Timestamp", e: "pd.Timestamp") -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        per_home = []
        for home in fc.homes:
            pv_decay = math.exp(-0.1 * home.pv_config.system_age_years)
            discharge = discharge_kwh(home)
            per_home.append(
                _make_sim_results(
                    self_kwh=3000.0 * pv_decay + discharge,
                    export_kwh=1000.0 * pv_decay,
                    import_kwh=500.0,
                    discharge_kwh=discharge,
                )
            )
        return FleetResults(per_home_results=per_home, home_configs=list(fc.homes))

    return _simulate


class TestBatterySohCountsThroughputToEachAge:
    """Each sampled age's battery SOH counts the battery throughput from installation to that age.

    Seed and bisection-trial ages alike, so battery_soh never rises year on
    year.  Every battery fades 0.005/yr by calendar and 0.0002 per equivalent
    full cycle.
    """

    _ERROR_TARGET_PCT = 0.1  # tight enough that bisection samples ages between the seeds

    def test_constant_discharge_soh_counts_discharge_times_years(self) -> None:
        """With a constant annual discharge D, year y's battery SOH is compute_soh(y, D × y)."""
        from solar_challenge.battery import compute_soh
        from solar_challenge.finance import project_multi_year

        scenario, finance, battery, _ = _make_battery_scenario(cycle_fade=0.0002, calendar_fade=0.005)
        usable_kwh = battery.capacity_kwh * (battery.max_soc_fraction - battery.min_soc_fraction)

        curve = project_multi_year(
            scenario,
            finance,
            error_target_pct=self._ERROR_TARGET_PCT,
            simulate=_make_battery_ageing_simulate(lambda home: _ANNUAL_DISCHARGE_KWH),
        )

        assert len(curve.sampled_ages) > 3, "premise: bisection sampled ages between the three seeds"
        assert curve.points[-1].battery_soh > battery.soh_floor, "premise: the SOH floor clamps no year"
        for point in curve.points:
            expected_soh = compute_soh(
                float(point.year), _ANNUAL_DISCHARGE_KWH * point.year, usable_kwh, battery
            )
            assert point.battery_soh == pytest.approx(expected_soh, abs=1e-12), f"year {point.year}"

    def test_each_home_counts_its_own_discharge_and_battery_soh_is_their_mean(self) -> None:
        """Each home's SOH counts its own constant discharge D_h, and battery_soh is the mean over homes.

        The two homes' batteries differ in size and discharge, so year y's
        battery_soh is the mean over homes of compute_soh(y, D_h × y).
        """
        import dataclasses

        from solar_challenge.battery import BatteryConfig, compute_soh
        from solar_challenge.finance import project_multi_year

        one_home_scenario, finance, battery, _ = _make_battery_scenario(cycle_fade=0.0002, calendar_fade=0.005)
        small_battery = dataclasses.replace(battery, capacity_kwh=5.0)
        (home,) = one_home_scenario.homes
        scenario = dataclasses.replace(
            one_home_scenario, homes=[home, dataclasses.replace(home, battery_config=small_battery)]
        )
        annual_discharge_kwh_by_capacity = {
            battery.capacity_kwh: _ANNUAL_DISCHARGE_KWH,
            small_battery.capacity_kwh: 200.0,
        }

        def expected_soh(bc: BatteryConfig, year: int) -> float:
            usable_kwh = bc.capacity_kwh * (bc.max_soc_fraction - bc.min_soc_fraction)
            throughput_kwh = annual_discharge_kwh_by_capacity[bc.capacity_kwh] * year
            return compute_soh(float(year), throughput_kwh, usable_kwh, bc)

        curve = project_multi_year(
            scenario,
            finance,
            error_target_pct=self._ERROR_TARGET_PCT,
            simulate=_make_battery_ageing_simulate(
                lambda home: annual_discharge_kwh_by_capacity[home.battery_config.capacity_kwh]
            ),
        )

        final_year = curve.points[-1].year
        assert len(curve.sampled_ages) > 3, "premise: bisection sampled ages between the three seeds"
        assert expected_soh(battery, final_year) != pytest.approx(expected_soh(small_battery, final_year)), (
            "premise: the two batteries age differently"
        )
        assert all(expected_soh(bc, final_year) > bc.soh_floor for bc in (battery, small_battery)), (
            "premise: the SOH floor clamps neither battery in any year"
        )
        for point in curve.points:
            mean_soh = (expected_soh(battery, point.year) + expected_soh(small_battery, point.year)) / 2
            assert point.battery_soh == pytest.approx(mean_soh, abs=1e-12), f"year {point.year}"

    @pytest.mark.parametrize(
        "discharge_kwh",
        [
            pytest.param(
                lambda home: _ANNUAL_DISCHARGE_KWH * home.battery_config.soh,
                id="discharge-falls-with-soh",
            ),
            pytest.param(
                lambda home: _ANNUAL_DISCHARGE_KWH * (1.0 + 0.5 * home.pv_config.system_age_years),
                id="discharge-rises-with-age",
            ),
        ],
    )
    def test_battery_soh_never_rises(
        self,
        discharge_kwh: "Callable[[HomeConfig], float]",  # type: ignore[name-defined]
    ) -> None:
        """battery_soh is non-increasing year on year, whether discharge falls or rises with age."""
        from solar_challenge.finance import project_multi_year

        scenario, finance, _, _ = _make_battery_scenario(cycle_fade=0.0002, calendar_fade=0.005)

        curve = project_multi_year(
            scenario,
            finance,
            error_target_pct=self._ERROR_TARGET_PCT,
            simulate=_make_battery_ageing_simulate(discharge_kwh),
        )

        assert len(curve.sampled_ages) > 3, "premise: bisection sampled ages between the three seeds"
        rises = [
            (later.year, earlier.battery_soh, later.battery_soh)
            for earlier, later in zip(curve.points, curve.points[1:])
            if later.battery_soh > earlier.battery_soh + 1e-12
        ]
        assert rises == [], f"battery_soh rose at (year, previous SOH, SOH): {rises}"


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
        """fleet_revenue_gbp at age 0 equals CBS formula: own_use + seg (no grid-charge term).

        CR2 RED test: the old formula used self_consumption_saving_gbp (priced at
        retail_baseline_rate=30p/kWh); the new formula uses own_use_rate_pence_per_kwh
        (default 15p/kWh) × fleet_sc + Σ _seg_export_income_gbp.
        CR3: SEG is now computed via _seg_export_income_gbp (extracted from householder_bill).
        """
        from solar_challenge.finance import _seg_export_income_gbp, project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc, exp, imp = 3000.0, 1500.0, 500.0
        scenario, finance = self._make_revenue_scenario(n_homes=n_homes)
        fr = self._fixed_fleet_results(n_homes=n_homes, self_kwh=sc, export_kwh=exp, import_kwh=imp)

        # Compute expected CBS revenue via new formula (PRD §3.2)
        summaries = [calculate_summary(r, seg_tariff_pence_per_kwh=scenario.seg_tariff_pence_per_kwh)
                     for r in fr.per_home_results]
        fleet_sc_kwh = sum(s.total_self_consumption_kwh for s in summaries)
        # New formula (no grid_services since homes have no battery):
        own_use_revenue = finance.own_use_rate_pence_per_kwh * fleet_sc_kwh / 100.0
        seg_revenue = sum(
            _seg_export_income_gbp(s, finance, s.simulation_days) for s in summaries
        )
        expected_revenue = own_use_revenue + seg_revenue

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

    def test_override_seg_counts_generation_above_demand_as_export(self) -> None:
        """Override 0.90 implies 3,600 kWh of own-use per home against a 2,800 kWh demand.

        Capped at demand, each home exports 4,000 − 2,800 = 1,200 kWh, paid at its
        physics export rate (£72 / 2,400 kWh = 3 p).  Own-use revenue stays basis C:
        1,600 kWh at 15 p (test_self_consumption_override_does_not_change_own_use_revenue).
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.fleet import FleetResults

        n_homes = 2
        fleet = FleetResults(
            per_home_results=[
                _make_sim_results(
                    self_kwh=1600.0, export_kwh=2400.0, import_kwh=1200.0, export_revenue_gbp=72.0
                )
                for _ in range(n_homes)
            ],
            home_configs=[_make_home_config() for _ in range(n_homes)],
        )
        scenario, finance = self._make_revenue_scenario(
            n_homes=n_homes, self_consumption_override=0.90
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)

        assert curve.points[0].fleet_revenue_gbp == pytest.approx(
            n_homes * (15.0 * 1600.0 / 100.0 + 1200.0 * 3.0 / 100.0)
        )

    def test_fleet_revenue_non_negative(self) -> None:
        """fleet_revenue_gbp is non-negative for all years (updated for CR2 formula)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = self._make_revenue_scenario(n_homes=1)
        # every CBS revenue term is non-negative
        fr = _make_fleet_results(n_homes=1, self_kwh=2000.0, export_kwh=800.0, import_kwh=300.0)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.fleet_revenue_gbp >= 0.0


class TestGridChargeEnergyPaidOnce:
    """H9 under basis C: each grid-charged kWh is paid once, by the householder, as import.

    Three observation points on one TOU + grid-charging fleet: the householder ledger
    (householder_bill import_cost_gbp), the CBS ledger (project_multi_year
    fleet_revenue_gbp) and the metered truth (calculate_summary total_import_cost_gbp).
    See docs/cost-recovery-finance-model.md §4.
    """

    N_HOMES = 2

    def _fleet(self) -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        return FleetResults(
            per_home_results=[_make_grid_charging_sim_results() for _ in range(self.N_HOMES)],
            home_configs=[_make_home_config() for _ in range(self.N_HOMES)],
        )

    @staticmethod
    def _without_grid_charge_cost_series(fleet: "FleetResults") -> "FleetResults":  # type: ignore[name-defined]
        from solar_challenge.fleet import FleetResults

        return FleetResults(
            per_home_results=[
                dataclasses.replace(r, grid_charge_cost=None) for r in fleet.per_home_results
            ],
            home_configs=fleet.home_configs,
        )

    @staticmethod
    def _householder_import_cost_gbp(
        summary: "SummaryStatistics",  # type: ignore[name-defined]
        finance: "FinanceConfig",  # type: ignore[name-defined]
    ) -> float:
        from solar_challenge.finance import householder_bill

        basis_c_own_use_kwh = summary.total_demand_kwh - summary.total_grid_import_kwh
        return householder_bill(
            summary, basis_c_own_use_kwh, finance, summary.simulation_days
        ).import_cost_gbp

    @staticmethod
    def _cbs_revenue_at_age_0(
        fleet: "FleetResults",  # type: ignore[name-defined]
        scenario: "ScenarioConfig",  # type: ignore[name-defined]
        finance: "FinanceConfig",  # type: ignore[name-defined]
    ) -> float:
        from solar_challenge.finance import project_multi_year

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)
        return curve.points[0].fleet_revenue_gbp

    def test_householder_import_cost_includes_grid_charging(self) -> None:
        """The householder pays the retailer for grid-charge energy inside import_cost_gbp.

        Pins which ledger bears the cost: the bill carries the full metered import cost,
        more than the builder's load-import-only £240 (800 kWh at 30p).
        """
        from solar_challenge.home import calculate_summary

        _, finance = _make_scenario(n_homes=self.N_HOMES, asset_life_years=5)
        load_import_only_gbp = 800.0 * 30.0 / 100.0
        for result in self._fleet().per_home_results:
            summary = calculate_summary(result)
            householder_import_gbp = self._householder_import_cost_gbp(summary, finance)
            assert householder_import_gbp == pytest.approx(summary.total_import_cost_gbp)
            assert householder_import_gbp > load_import_only_gbp

    def test_cbs_revenue_has_no_grid_charge_term(self) -> None:
        """CBS revenue on the grid-charging fleet is own-use + SEG + grid services, nothing else.

        The fleet earns no SEG and no grid services, so year-0 revenue is exactly
        own_use_rate × Σ basis-C own-use (demand − import) / 100.
        """
        from solar_challenge.home import calculate_summary

        scenario, finance = _make_scenario(n_homes=self.N_HOMES, asset_life_years=5)
        fleet = self._fleet()
        summaries = [calculate_summary(r) for r in fleet.per_home_results]
        assert all(s.total_export_revenue_gbp == 0.0 for s in summaries), "premise: no SEG"
        assert finance.grid_services_income_per_kw_per_year_gbp == 0.0, "premise: no grid services"

        own_use_kwh = sum(s.total_demand_kwh - s.total_grid_import_kwh for s in summaries)
        own_use_gbp = finance.own_use_rate_pence_per_kwh * own_use_kwh / 100.0
        cbs_gbp = self._cbs_revenue_at_age_0(fleet, scenario, finance)

        assert cbs_gbp == pytest.approx(own_use_gbp, abs=1e-9), (
            f"CBS revenue £{cbs_gbp:.2f} != own-use £{own_use_gbp:.2f} + SEG £0 + "
            f"grid services £0; extra term £{cbs_gbp - own_use_gbp:.2f}"
        )

    def test_grid_charge_energy_paid_once_across_ledgers(self) -> None:
        """Σ householder import cost + grid-charge cost borne by the CBS == metered import cost.

        The CBS share is the revenue drop against a twin fleet with identical energy and
        import cost but no grid_charge_cost series.
        """
        from solar_challenge.home import calculate_summary

        scenario, finance = _make_scenario(n_homes=self.N_HOMES, asset_life_years=5)
        fleet = self._fleet()
        summaries = [calculate_summary(r) for r in fleet.per_home_results]

        householder_gbp = sum(self._householder_import_cost_gbp(s, finance) for s in summaries)
        metered_gbp = sum(s.total_import_cost_gbp for s in summaries)
        cbs_gbp = self._cbs_revenue_at_age_0(
            self._without_grid_charge_cost_series(fleet), scenario, finance
        ) - self._cbs_revenue_at_age_0(fleet, scenario, finance)

        assert householder_gbp + cbs_gbp == pytest.approx(metered_gbp, abs=1e-9), (
            "grid-charge energy paid twice: householder import already includes it and "
            f"CBS revenue deducts it again (householder £{householder_gbp:.2f} + "
            f"CBS £{cbs_gbp:.2f} vs metered £{metered_gbp:.2f}; "
            f"excess £{householder_gbp + cbs_gbp - metered_gbp:.2f})"
        )


# ---------------------------------------------------------------------------
# _seg_export_income_gbp — direct unit tests (amendment: suggestion 3)
# ---------------------------------------------------------------------------


def _make_seg_summary(
    total_generation_kwh: float = 4000.0,
    total_grid_export_kwh: float = 800.0,
    total_export_revenue_gbp: float = 24.0,
) -> "SummaryStatistics":  # type: ignore[name-defined]
    """Minimal SummaryStatistics for testing _seg_export_income_gbp."""
    from solar_challenge.home import SummaryStatistics

    sc_kwh = total_generation_kwh - total_grid_export_kwh
    return SummaryStatistics(
        total_generation_kwh=total_generation_kwh,
        total_demand_kwh=sc_kwh + 1200.0,
        total_self_consumption_kwh=sc_kwh,
        total_grid_import_kwh=1200.0,
        total_grid_export_kwh=total_grid_export_kwh,
        total_battery_charge_kwh=0.0,
        total_battery_discharge_kwh=0.0,
        peak_generation_kw=2.0,
        peak_demand_kw=1.5,
        self_consumption_ratio=sc_kwh / total_generation_kwh if total_generation_kwh > 0 else 0.0,
        grid_dependency_ratio=0.3,
        export_ratio=total_grid_export_kwh / total_generation_kwh if total_generation_kwh > 0 else 0.0,
        simulation_days=365,
        total_import_cost_gbp=276.0,
        total_export_revenue_gbp=total_export_revenue_gbp,
        net_cost_gbp=276.0 - total_export_revenue_gbp,
    )


class TestSegExportIncomeGbp:
    """Direct unit tests for _seg_export_income_gbp (amendment: reviewer suggestion 3).

    The helper's zero-export fallback and override-path arithmetic are not
    covered by hand-computed assertions in the projection tests (which use the
    function under test to compute expected values, making them wiring tests
    rather than contract tests).  These tests verify the helper's own logic.
    """

    def _make_finance_seg(
        self,
        self_consumption_override: "float | None" = None,
    ) -> "FinanceConfig":  # type: ignore[name-defined]
        from solar_challenge.config import FinanceConfig

        return FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=5,
            loan_term_years=5,
            self_consumption_override=self_consumption_override,
            own_use_rate_pence_per_kwh=15.0,
        )

    def test_physics_path_returns_annualised_export_revenue(self) -> None:
        """Physics path (no override): returns total_export_revenue_gbp directly."""
        from solar_challenge.finance import _seg_export_income_gbp  # type: ignore[attr-defined]

        summary = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=800.0,
            total_export_revenue_gbp=24.0,
        )
        finance = self._make_finance_seg(self_consumption_override=None)

        result = _seg_export_income_gbp(summary, finance, simulation_days=365)

        assert result == pytest.approx(24.0, rel=1e-9)

    def test_override_zero_export_kwh_returns_zero(self) -> None:
        """Override path with zero physics export kWh: returns 0.0 (rate fallback).

        When total_grid_export_kwh == 0, the effective export rate cannot be
        derived from physics figures and falls back to 0.0 p/kWh.  The result
        must be exactly 0.0 regardless of the override fraction.
        """
        from solar_challenge.finance import _seg_export_income_gbp  # type: ignore[attr-defined]

        # Summary with no export at all (e.g. all generation self-consumed)
        summary_no_export = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=0.0,
            total_export_revenue_gbp=0.0,
        )
        finance = self._make_finance_seg(self_consumption_override=0.60)

        result = _seg_export_income_gbp(summary_no_export, finance, simulation_days=365)

        # effective_export_rate_pence = 0.0 (fallback), so result = override_export * 0 = 0
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_override_nonzero_export_computes_override_kwh_times_effective_rate(self) -> None:
        """Override path with nonzero physics export: returns override_export_kwh × effective_rate.

        Contract (§3.2):
          own_use         = min(override × gen_kwh, demand_kwh)
          override_export = gen_kwh − own_use
          effective_rate  = (export_rev / export_kwh) × 100  p/kWh
          result          = override_export × effective_rate / 100

        Using override=0.60 (own-use 0.60×4000 = 2400 kWh, within the 4400 kWh
        demand) against physics that had 20% export (800 kWh, 24 £ → 3 p/kWh):
          override_export = 4000 - 2400 = 1600 kWh
          effective_rate  = (24/800)×100 = 3 p/kWh
          result          = 1600×3/100 = 48 £
        """
        from solar_challenge.finance import _seg_export_income_gbp  # type: ignore[attr-defined]

        summary = _make_seg_summary(
            total_generation_kwh=4000.0,
            total_grid_export_kwh=800.0,   # physics: 20% of gen
            total_export_revenue_gbp=24.0,  # => 3 p/kWh effective rate
        )
        # Override: 60% self-consumption → 40% export → 1600 kWh
        finance = self._make_finance_seg(self_consumption_override=0.60)

        result = _seg_export_income_gbp(summary, finance, simulation_days=365)

        # hand-checked: 1600 * 3 / 100 = 48.0
        assert result == pytest.approx(48.0, rel=1e-9)

    def test_short_period_annualises_physics_export_revenue(self) -> None:
        """Physics path: short simulation period is annualised to 365 days."""
        from solar_challenge.finance import _seg_export_income_gbp  # type: ignore[attr-defined]

        # Build a summary with a 182-day simulation (half year)
        from solar_challenge.home import SummaryStatistics

        summary_182 = SummaryStatistics(
            total_generation_kwh=2000.0,
            total_demand_kwh=2600.0,
            total_self_consumption_kwh=1600.0,
            total_grid_import_kwh=1000.0,
            total_grid_export_kwh=400.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=2.0,
            peak_demand_kw=1.5,
            self_consumption_ratio=0.80,
            grid_dependency_ratio=0.38,
            export_ratio=0.20,
            simulation_days=182,
            total_import_cost_gbp=230.0,
            total_export_revenue_gbp=12.0,  # half-year figure
            net_cost_gbp=218.0,
        )
        finance = self._make_finance_seg(self_consumption_override=None)

        result = _seg_export_income_gbp(summary_182, finance, simulation_days=182)

        expected = 12.0 * (365 / 182)
        assert result == pytest.approx(expected, rel=1e-6)


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


# ---------------------------------------------------------------------------
# _reconcile_seg_homes — unit tests (task-89 step-1)
# ---------------------------------------------------------------------------


class TestReconcileSegHomes:
    """Unit tests for the _reconcile_seg_homes pure helper."""

    def test_none_scenario_rate_returns_homes_unchanged(self) -> None:
        """(a) When scenario_seg_rate is None, return the homes list unchanged."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]

        home = _make_home_config()
        result = _reconcile_seg_homes([home], scenario_seg_rate=None)
        assert result == [home]
        assert result[0] is home  # same object, no copy

    def test_none_seg_home_gets_tariff_threaded(self) -> None:
        """(b) Home with seg_tariff=None + scenario_seg_rate=6.0 → seg_tariff set to SEGTariff(6.0).

        Other HomeConfig fields (pv_config, load_config, location, battery_config)
        are preserved unchanged via dataclasses.replace semantics.
        """
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        home = _make_home_config()
        assert home.seg_tariff is None  # pre-condition

        result = _reconcile_seg_homes([home], scenario_seg_rate=6.0)
        assert len(result) == 1
        updated = result[0]
        # seg_tariff is threaded
        assert updated.seg_tariff is not None
        assert isinstance(updated.seg_tariff, SEGTariff)
        assert updated.seg_tariff.rate_pence_per_kwh == pytest.approx(6.0)
        # other fields preserved
        assert updated.pv_config == home.pv_config
        assert updated.load_config == home.load_config
        assert updated.location == home.location
        assert updated.battery_config == home.battery_config
        # input not mutated
        assert home.seg_tariff is None

    def test_home_with_existing_seg_and_none_scenario_rate_unchanged(self) -> None:
        """(c) Home with seg_tariff=SEGTariff(4.0) + scenario_seg_rate=None → unchanged."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="export", rate_pence_per_kwh=4.0)
        home = dataclasses.replace(_make_home_config(), seg_tariff=tariff)
        result = _reconcile_seg_homes([home], scenario_seg_rate=None)
        assert result == [home]
        assert result[0].seg_tariff is tariff

    def test_consistent_rate_no_raise_home_unchanged(self) -> None:
        """(d) Home seg=SEGTariff(6.0) + scenario_seg_rate=6.0 (CLI-style) → no raise, same home."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="", rate_pence_per_kwh=6.0)
        home = dataclasses.replace(_make_home_config(), seg_tariff=tariff)
        # Must not raise; home is returned as-is (rates match)
        result = _reconcile_seg_homes([home], scenario_seg_rate=6.0)
        assert len(result) == 1
        assert result[0] is home

    def test_inconsistent_rate_raises_value_error(self) -> None:
        """(e) Home seg=SEGTariff(4.0) + scenario_seg_rate=6.0 → raises ValueError naming both rates."""
        from solar_challenge.finance import _reconcile_seg_homes  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        tariff = SEGTariff(name="", rate_pence_per_kwh=4.0)
        home = dataclasses.replace(_make_home_config(), seg_tariff=tariff)
        import re

        with pytest.raises(ValueError, match=re.compile(r"inconsistent.*SEG", re.IGNORECASE)):
            _reconcile_seg_homes([home], scenario_seg_rate=6.0)


# ---------------------------------------------------------------------------
# SEG-aware factory + TestProjectHonoursScenarioLevelSeg (task-89 step-3)
# ---------------------------------------------------------------------------


def _seg_aware_fleet_results_factory(
    self_kwh: float = 5.0,
    export_kwh: float = 5.0,
    import_kwh: float = 3.0,
    n_minutes: int = 1440,
) -> "Callable":  # type: ignore[name-defined]
    """Return a simulate closure that prices export_revenue from each home's seg_tariff.

    Mirrors home.py:336-349 (Task-85 zeroing): export_revenue is non-zero only
    when home.seg_tariff is set, summing to export_kwh × rate/100 per home.
    The kWh arguments are for the simulated period; _annualise_physics handles
    scaling to 365 days.  Use as ``simulate=lambda fc, s, e: factory(fc)``.
    """
    from typing import Callable  # noqa: F401

    def _simulate(
        fleet_config: "FleetConfig",  # type: ignore[name-defined]
        start: "pd.Timestamp",  # type: ignore[name-defined]
        end: "pd.Timestamp",  # type: ignore[name-defined]
    ) -> "FleetResults":  # type: ignore[name-defined]
        import pandas as pd
        from solar_challenge.fleet import FleetResults
        from solar_challenge.home import SimulationResults

        idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
        sc_kw = self_kwh / (n_minutes / 60.0)
        exp_kw = export_kwh / (n_minutes / 60.0)
        imp_kw = import_kwh / (n_minutes / 60.0)
        gen_kw = sc_kw + exp_kw
        demand_kw = sc_kw + imp_kw
        zeros = pd.Series(0.0, index=idx)

        per_home = []
        for home in fleet_config.homes:
            # Price export_revenue from seg_tariff if set (mirrors Task-85 zeroing in home.py)
            if home.seg_tariff is not None:
                rev_per_min = exp_kw / 60.0 * home.seg_tariff.rate_pence_per_kwh / 100.0
                export_rev: "pd.Series" = pd.Series(rev_per_min, index=idx)
            else:
                export_rev = zeros.copy()

            per_home.append(SimulationResults(
                generation=pd.Series(gen_kw, index=idx),
                demand=pd.Series(demand_kw, index=idx),
                self_consumption=pd.Series(sc_kw, index=idx),
                battery_charge=zeros.copy(),
                battery_discharge=zeros.copy(),
                battery_soc=zeros.copy(),
                grid_import=pd.Series(imp_kw, index=idx),
                grid_export=pd.Series(exp_kw, index=idx),
                import_cost=zeros.copy(),
                export_revenue=export_rev,
                tariff_rate=zeros.copy(),
            ))

        return FleetResults(per_home_results=per_home, home_configs=list(fleet_config.homes))

    return _simulate


class TestProjectHonoursScenarioLevelSeg:
    """Integration tests: project_multi_year and solve_cost_recovery_rate
    must honour ScenarioConfig.seg_tariff_pence_per_kwh."""

    _SEG_RATE = 6.0
    _N_HOMES = 2

    def _make_three_scenarios(self) -> tuple:
        """Build three ScenarioConfigs and shared FinanceConfig.

        Returns (scenario_seg, home_ref, baseline_none, finance) where:
        - scenario_seg: homes have seg_tariff=None, scenario rate=_SEG_RATE
        - home_ref: homes have seg_tariff=SEGTariff(_SEG_RATE), scenario rate=None
        - baseline_none: homes have seg_tariff=None, scenario rate=None
        - finance: shared FinanceConfig with default grant/loan params
        """
        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.seg import SEGTariff

        homes_no_seg = [_make_home_config() for _ in range(self._N_HOMES)]
        homes_with_seg = [
            dataclasses.replace(h, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=self._SEG_RATE))
            for h in homes_no_seg
        ]
        period = SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31")
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            loan_term_years=15,
            retail_baseline_rate_pence_per_kwh=30.0,
            vat_rate=0.05,
        )
        scenario_seg = ScenarioConfig(
            name="test-seg",
            period=period,
            description="Scenario-level SEG",
            homes=homes_no_seg,
            seg_tariff_pence_per_kwh=self._SEG_RATE,
        )
        home_ref = ScenarioConfig(
            name="test-home-ref",
            period=period,
            description="Per-home SEG",
            homes=homes_with_seg,
        )
        baseline_none = ScenarioConfig(
            name="test-baseline",
            period=period,
            description="No SEG",
            homes=homes_no_seg,
        )
        return scenario_seg, home_ref, baseline_none, finance

    def test_project_multi_year_honours_scenario_level_seg(self) -> None:
        """project_multi_year: scenario_seg fleet_revenue equals home_ref at year 0 (non-vacuous).

        scenario_seg (homes seg=None, scenario rate=R) must produce the same
        fleet_revenue_gbp as home_ref (homes seg=SEGTariff(R), scenario rate=None)
        after _reconcile_seg_homes threads the tariff onto homes.
        Both must exceed baseline_none (no SEG at all) — proving the SEG
        income is load-bearing.
        """
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario_seg, home_ref, baseline_none, finance = self._make_three_scenarios()
        sim = _seg_aware_fleet_results_factory()

        curve_seg = project_multi_year(scenario_seg, finance, simulate=sim)
        curve_ref = project_multi_year(home_ref, finance, simulate=sim)
        curve_base = project_multi_year(baseline_none, finance, simulate=sim)

        rev_seg = curve_seg.points[0].fleet_revenue_gbp
        rev_ref = curve_ref.points[0].fleet_revenue_gbp
        rev_base = curve_base.points[0].fleet_revenue_gbp

        # Equivalence: scenario-level SEG must produce the same revenue as per-home SEG
        assert rev_seg == pytest.approx(rev_ref, rel=1e-6), (
            f"scenario_seg revenue {rev_seg:.4f} != home_ref revenue {rev_ref:.4f}; "
            "project_multi_year must reconcile scenario.seg_tariff_pence_per_kwh onto homes"
        )
        # Non-vacuousness: SEG income must raise fleet_revenue vs no-SEG baseline
        assert rev_ref > rev_base, (
            f"SEG income must increase fleet_revenue vs no-SEG baseline "
            f"(home_ref={rev_ref:.4f}, baseline={rev_base:.4f})"
        )

    def test_solve_cost_recovery_rate_honours_scenario_level_seg(self) -> None:
        """solve_cost_recovery_rate: scenario_seg solution equals home_ref (non-vacuous).

        Asserts equivalence on (own_use_rate, net_surplus, binding, feasible).
        Also asserts that home_ref differs from baseline_none on at least one
        of {own_use_rate, net_surplus} — proving SEG is load-bearing regardless
        of the binding regime (no tuned numeric threshold needed; equality is
        two code paths computing export_kwh × rate / 100).
        """
        import math

        from solar_challenge.finance import solve_cost_recovery_rate  # type: ignore[attr-defined]

        scenario_seg, home_ref, baseline_none, finance = self._make_three_scenarios()
        sim = _seg_aware_fleet_results_factory()

        sol_seg = solve_cost_recovery_rate(scenario_seg, finance, simulate=sim)
        sol_ref = solve_cost_recovery_rate(home_ref, finance, simulate=sim)
        sol_base = solve_cost_recovery_rate(baseline_none, finance, simulate=sim)

        # Equivalence: scenario-level SEG must produce the same solve as per-home SEG
        assert sol_seg.own_use_rate_pence_per_kwh == pytest.approx(
            sol_ref.own_use_rate_pence_per_kwh, rel=1e-6
        ), (
            f"own_use_rate: scenario_seg={sol_seg.own_use_rate_pence_per_kwh:.4f} "
            f"!= home_ref={sol_ref.own_use_rate_pence_per_kwh:.4f}"
        )
        assert sol_seg.net_surplus_per_home_per_year_gbp == pytest.approx(
            sol_ref.net_surplus_per_home_per_year_gbp, rel=1e-6
        ), (
            f"net_surplus: scenario_seg={sol_seg.net_surplus_per_home_per_year_gbp:.4f} "
            f"!= home_ref={sol_ref.net_surplus_per_home_per_year_gbp:.4f}"
        )
        assert sol_seg.binding == sol_ref.binding, (
            f"binding: scenario_seg={sol_seg.binding!r} != home_ref={sol_ref.binding!r}"
        )
        assert sol_seg.feasible == sol_ref.feasible, (
            f"feasible: scenario_seg={sol_seg.feasible} != home_ref={sol_ref.feasible}"
        )
        # Outlay-path equivalence: representative_outlay and saving both flow through
        # the step-6 age-0 outlay path (finance.py:2225); assert they match so a future
        # regression where the outlay path is export-dependent cannot go undetected.
        assert sol_seg.representative_outlay_gbp == pytest.approx(
            sol_ref.representative_outlay_gbp, rel=1e-6
        ), (
            f"representative_outlay: scenario_seg={sol_seg.representative_outlay_gbp:.4f} "
            f"!= home_ref={sol_ref.representative_outlay_gbp:.4f}"
        )
        assert sol_seg.saving_vs_baseline_gbp == pytest.approx(
            sol_ref.saving_vs_baseline_gbp, rel=1e-6
        ), (
            f"saving_vs_baseline: scenario_seg={sol_seg.saving_vs_baseline_gbp:.4f} "
            f"!= home_ref={sol_ref.saving_vs_baseline_gbp:.4f}"
        )

        # Non-vacuousness: SEG income must affect at least one solve metric vs no-SEG baseline
        rate_differs = not math.isclose(
            sol_ref.own_use_rate_pence_per_kwh,
            sol_base.own_use_rate_pence_per_kwh,
            rel_tol=1e-4,
            abs_tol=1e-6,
        )
        surplus_differs = not math.isclose(
            sol_ref.net_surplus_per_home_per_year_gbp,
            sol_base.net_surplus_per_home_per_year_gbp,
            rel_tol=1e-4,
            abs_tol=1e-6,
        )
        assert rate_differs or surplus_differs, (
            f"SEG income must change own_use_rate or net_surplus vs no-SEG baseline "
            f"(home_ref: rate={sol_ref.own_use_rate_pence_per_kwh:.4f}p, "
            f"surplus={sol_ref.net_surplus_per_home_per_year_gbp:.4f}; "
            f"baseline: rate={sol_base.own_use_rate_pence_per_kwh:.4f}p, "
            f"surplus={sol_base.net_surplus_per_home_per_year_gbp:.4f})"
        )

    def test_inconsistent_seg_inputs_raise_through_projection(self) -> None:
        """project_multi_year raises ValueError when per-home seg_tariff != scenario rate."""
        import re

        from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.seg import SEGTariff

        homes_inconsistent = [
            dataclasses.replace(
                _make_home_config(),
                seg_tariff=SEGTariff(name="", rate_pence_per_kwh=4.0),
            )
            for _ in range(self._N_HOMES)
        ]
        scenario_inconsistent = ScenarioConfig(
            name="test-inconsistent",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            description="Inconsistent SEG",
            homes=homes_inconsistent,
            seg_tariff_pence_per_kwh=6.0,  # 6.0 != 4.0 → should raise
        )
        finance = FinanceConfig(
            standing_charge_pence_per_day=28.0,
            asset_life_years=25,
            loan_term_years=15,
        )
        sim = _seg_aware_fleet_results_factory()

        with pytest.raises(ValueError, match=re.compile(r"inconsistent.*SEG", re.IGNORECASE)):
            project_multi_year(scenario_inconsistent, finance, simulate=sim)


# ---------------------------------------------------------------------------
# Short-window annualisation — a sub-360-day window projects as its 365-day year
# ---------------------------------------------------------------------------

_SHORT_WINDOW_DAYS = 3


def _make_full_year_and_short_window_fleets() -> tuple:
    """Return (scenario, finance, battery_config, fleet_full_year, fleet_short).

    Two battery homes at the same daily rates over a full year and over a
    _SHORT_WINDOW_DAYS window, so the short fleet's kWh and SEG £ totals are
    the annual ones × _SHORT_WINDOW_DAYS / 365.  Inject either fleet with
    ``simulate=lambda fc, s, e: fleet``.
    """
    from solar_challenge.battery import BatteryConfig
    from solar_challenge.config import FinanceConfig, ScenarioConfig, SimulationPeriod
    from solar_challenge.fleet import FleetResults
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location

    battery_config = BatteryConfig(
        capacity_kwh=10.0,
        max_charge_kw=3.5,
        max_discharge_kw=3.5,
        calendar_fade_rate_per_year=0.005,
        cycle_fade_per_equivalent_full_cycle=0.0002,
        soh_floor=0.60,
    )
    homes = [
        HomeConfig(
            pv_config=_make_pv_config(),
            load_config=_make_load_config(),
            location=Location.bristol(),
            battery_config=battery_config,
        )
        for _ in range(2)
    ]
    scenario = ScenarioConfig(
        name="short-window-test",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Short-window annualisation test",
        homes=homes,
    )
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=25,
        grid_services_income_per_kw_per_year_gbp=10.0,
    )

    def fleet_over(window_days: int) -> "FleetResults":  # type: ignore[name-defined]
        share_of_year = window_days / 365
        return FleetResults(
            per_home_results=[
                _make_sim_results(
                    self_kwh=3000.0 * share_of_year,
                    export_kwh=1000.0 * share_of_year,
                    import_kwh=500.0 * share_of_year,
                    discharge_kwh=800.0 * share_of_year,
                    export_revenue_gbp=150.0 * share_of_year,
                    n_steps=24 * window_days,
                )
                for _ in homes
            ],
            home_configs=homes,
        )

    return scenario, finance, battery_config, fleet_over(365), fleet_over(_SHORT_WINDOW_DAYS)


class TestProjectMultiYearAnnualisesShortWindow:
    """A window under 360 days projects as the 365-day year it samples.

    project_multi_year scales each home's window totals to a 365-day year, so a
    short window at the same daily rates as a full year gives the same curve,
    and it warns once per projection that it did so.
    """

    def test_short_window_projects_the_equivalent_full_year_curve(self) -> None:
        """Every YearPoint field, energy, revenue and SOH alike, matches the full-year curve."""
        from solar_challenge.finance import project_multi_year
        from solar_challenge.home import calculate_summary

        scenario, finance, battery_config, fleet_full_year, fleet_short = (
            _make_full_year_and_short_window_fleets()
        )
        short_summary = calculate_summary(fleet_short.per_home_results[0])
        assert short_summary.simulation_days == _SHORT_WINDOW_DAYS
        assert short_summary.total_export_revenue_gbp > 0.0, "premise: the window earns SEG income"

        curve_full = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_full_year)
        curve_short = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short)

        # Premise: SOH stays above the floor, so window-length discharge would show as higher SOH.
        assert curve_full.points[-1].battery_soh > battery_config.soh_floor
        assert curve_short.sampled_ages == curve_full.sampled_ages
        for short, full in zip(curve_short.points, curve_full.points, strict=True):
            assert dataclasses.asdict(short) == pytest.approx(dataclasses.asdict(full), rel=1e-9)

    def test_short_window_warns_once_naming_the_window(self) -> None:
        """Annualising a short window raises one UserWarning per projection, naming its days."""
        import re

        from solar_challenge.finance import project_multi_year

        scenario, finance, _, _, fleet_short = _make_full_year_and_short_window_fleets()
        names_the_window = re.compile(rf"\b{_SHORT_WINDOW_DAYS} days\b")

        with pytest.warns(UserWarning, match=names_the_window) as record:
            curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short)

        # Premise: several ages are simulated, so a warning raised per node would repeat.
        assert len(curve.sampled_ages) >= 3
        window_warnings = [
            str(w.message) for w in record if names_the_window.search(str(w.message))
        ]
        assert len(window_warnings) == 1, window_warnings

    def test_full_year_window_does_not_warn(self) -> None:
        """A full-year window is not annualised, so a board run stays warning-free."""
        import warnings

        from solar_challenge.finance import project_multi_year

        scenario, finance, _, fleet_full_year, _ = _make_full_year_and_short_window_fleets()

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_full_year)

        assert [str(w.message) for w in record if issubclass(w.category, UserWarning)] == []
