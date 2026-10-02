# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's short-window annualisation.

A simulated window under 360 days projects as the 365-day year it samples,
with or without the self-consumption override, and the projection warns once.
"""
from __future__ import annotations

import dataclasses

import pytest

from tests._finance_builders import make_load_config, make_pv_config, make_sim_results


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
