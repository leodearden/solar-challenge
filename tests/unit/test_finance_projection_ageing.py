# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for PV and battery ageing in project_multi_year.

PV state of health follows the degradation factor; battery state of health
counts calendar fade and the throughput from installation to each sampled age,
and never rises.  The tests run on an injected synthetic simulate, with no
PVGIS or network.
"""
from __future__ import annotations

import pytest

from tests._finance_builders import (
    make_fleet_results,
    make_load_config,
    make_pv_config,
    make_scenario_and_finance,
    make_sim_results,
)


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
            make_sim_results(
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

        scenario, finance = make_scenario_and_finance(asset_life_years=25)
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

        scenario, finance = make_scenario_and_finance(asset_life_years=25)
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
                make_sim_results(
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
                pv_config=make_pv_config(),
                load_config=make_load_config(),
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
                make_sim_results(
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
                pv_config=make_pv_config(),
                load_config=make_load_config(),
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
        scenario, finance = make_scenario_and_finance(asset_life_years=25)
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

        scenario, finance = make_scenario_and_finance(asset_life_years=25)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for pt in curve.points:
            assert pt.battery_soh == pytest.approx(1.0)


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
            pv_config=make_pv_config(),
            load_config=make_load_config(),
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
                make_sim_results(
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
                pv_config=make_pv_config(),
                load_config=make_load_config(),
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
                make_sim_results(
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
