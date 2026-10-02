# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year, the multi-year projection's forward-march driver.

The projection runs on an injected synthetic simulate.  The tests cover the
curve's shape and energy aggregation and short-window annualisation.

All tests are offline/fast — no PVGIS/network is touched.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests._finance_builders import (
    make_fleet_results,
    make_load_config,
    make_pv_config,
    make_scenario_and_finance,
    make_sim_results,
)


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        from solar_challenge.finance import MultiYearCurve, project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_self_consumption_at_sampled_age(self) -> None:
        """fleet_self_consumption_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

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
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, export_kwh=exp_per_home)

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
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, import_kwh=imp_per_home)

        expected_import = sum(
            calculate_summary(r).total_grid_import_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_import_kwh == pytest.approx(expected_import, rel=1e-4)


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
            pv_config=make_pv_config(),
            load_config=make_load_config(),
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
                make_sim_results(
                    self_kwh=3000.0 * share_of_year,
                    export_kwh=1000.0 * share_of_year,
                    import_kwh=500.0 * share_of_year,
                    discharge_kwh=800.0 * share_of_year,
                    export_revenue_gbp=150.0 * share_of_year,
                    days=window_days,
                )
                for _ in homes
            ],
            home_configs=homes,
        )

    return scenario, finance, battery_config, fleet_over(365), fleet_over(_SHORT_WINDOW_DAYS)


class TestProjectMultiYearAnnualisesShortWindow:
    """A window under 360 days projects as the 365-day year it samples.

    project_multi_year scales each home's window totals to a 365-day year, so a
    short window at the same daily rates as a full year gives the same curve, with
    or without the override, and under the override its own-use is the one
    householder_bill charges for that year.  It warns once per projection that it
    annualised.
    """

    @pytest.mark.parametrize(
        "self_consumption_override",
        [
            pytest.param(None, id="physics"),
            pytest.param(0.5, id="override-cap-not-binding"),
            pytest.param(0.9, id="override-cap-binding"),
        ],
    )
    def test_short_window_projects_the_equivalent_full_year_curve(
        self, self_consumption_override: "float | None"
    ) -> None:
        """Every YearPoint field, energy, revenue and SOH alike, matches the full-year curve."""
        from solar_challenge.finance import project_multi_year
        from solar_challenge.home import calculate_summary

        scenario, finance, battery_config, fleet_full_year, fleet_short = (
            _make_full_year_and_short_window_fleets()
        )
        finance = dataclasses.replace(finance, self_consumption_override=self_consumption_override)
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

    @pytest.mark.parametrize(
        ("self_consumption_override", "annual_own_use_kwh"),
        [
            pytest.param(0.5, 2000.0, id="cap-not-binding"),
            pytest.param(0.9, 2700.0, id="cap-binding"),
        ],
    )
    def test_short_window_override_own_use_is_what_the_annual_bills_charge(
        self, self_consumption_override: float, annual_own_use_kwh: float
    ) -> None:
        """Under the override, year 0's own-use is the annual own-use householder_bill charges.

        Each home generates 4,000 kWh and demands 2,700 kWh a year, so the override bills
        min(override × 4,000, 2,700) kWh a year.  The projection and householder_bill both
        start from the 3-day window's summary, so both must annualise it.
        """
        import warnings

        from solar_challenge.finance import householder_bill, project_multi_year
        from solar_challenge.home import calculate_summary

        scenario, finance, _, fleet_full_year, fleet_short = _make_full_year_and_short_window_fleets()
        finance = dataclasses.replace(finance, self_consumption_override=self_consumption_override)
        annual = calculate_summary(fleet_full_year.per_home_results[0])
        assert (annual.total_generation_kwh, annual.total_demand_kwh) == pytest.approx((4000.0, 2700.0))
        summaries = [calculate_summary(r) for r in fleet_short.per_home_results]
        assert {s.simulation_days for s in summaries} == {_SHORT_WINDOW_DAYS}

        with warnings.catch_warnings():
            # The short window, the missing tariff and the cap all warn; none is under test here.
            warnings.simplefilter("ignore", UserWarning)
            year_0 = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet_short).points[0]
            bills = [
                householder_bill(
                    s,
                    annual_self_consumption_kwh=s.total_demand_kwh - s.total_grid_import_kwh,
                    finance=finance,
                    simulation_days=s.simulation_days,
                )
                for s in summaries
            ]

        billed_own_use_kwh = (
            sum(b.own_use_payment_gbp for b in bills) * 100.0 / finance.own_use_rate_pence_per_kwh
        )
        assert billed_own_use_kwh == pytest.approx(len(summaries) * annual_own_use_kwh)
        assert year_0.fleet_self_consumption_kwh == pytest.approx(billed_own_use_kwh)

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
