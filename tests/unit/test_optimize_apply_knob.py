# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests of optimize.apply_knob, through which sensitivity_panel sets each swept knob value; no sweep runs."""
from __future__ import annotations

import dataclasses

import pytest

from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.optimize import apply_knob
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from tests._finance_builders import make_home_config, make_scenario_and_finance


def _fleet_scenario(n_homes: int = 2) -> ScenarioConfig:
    """A fleet of *n_homes* default homes carrying make_scenario_and_finance's finance block."""
    scenario, finance = make_scenario_and_finance(n_homes=n_homes)
    return dataclasses.replace(scenario, finance=finance)


class TestApplyKnob:
    """apply_knob: one fleet scenario in, a copy with one sensitivity knob set out."""

    def test_finance_knob_sets_that_field_on_the_copy_only(self) -> None:
        """A FinanceConfig field is set on the returned finance; the rest and the input are kept."""
        scenario = _fleet_scenario()
        assert scenario.finance is not None
        old_battery_cost = scenario.finance.battery_cost_per_kwh_gbp

        new = apply_knob(scenario, "battery_cost_per_kwh_gbp", 999.0)

        assert new.finance is not None
        assert new.finance.battery_cost_per_kwh_gbp == pytest.approx(999.0)
        assert new.finance.pv_cost_per_kwp_gbp == pytest.approx(scenario.finance.pv_cost_per_kwp_gbp)
        assert scenario.finance.battery_cost_per_kwh_gbp == pytest.approx(old_battery_cost)

    def test_grid_services_income_knob_sets_the_finance_field(self) -> None:
        """grid_services_income_per_kw_per_year_gbp lands on the returned scenario's finance."""
        new = apply_knob(_fleet_scenario(), "grid_services_income_per_kw_per_year_gbp", 42.0)

        assert new.finance is not None
        assert new.finance.grid_services_income_per_kw_per_year_gbp == pytest.approx(42.0)

    @pytest.mark.parametrize("name", ["seg", "seg_tariff_pence_per_kwh"])
    def test_seg_knob_reprices_the_scenario_and_every_home(self, name: str) -> None:
        """Either SEG name sets the scenario's SEG rate and every home's tariff, leaving finance alone."""
        scenario = _fleet_scenario()

        new = apply_knob(scenario, name, 7.5)

        assert new.seg_tariff_pence_per_kwh == pytest.approx(7.5)
        assert [home.seg_tariff for home in new.homes] == [
            SEGTariff(name="", rate_pence_per_kwh=7.5)
        ] * len(scenario.homes)
        assert new.finance is scenario.finance

    def test_seg_knob_replaces_whatever_tariff_each_home_carried(self) -> None:
        """A preset, no tariff and another rate all end on the swept rate, as an unnamed tariff."""
        carried = [
            resolve_seg_tariff("Octopus"),
            None,
            SEGTariff(name="", rate_pence_per_kwh=9.9),
        ]
        scenario = _fleet_scenario(n_homes=len(carried))
        scenario = dataclasses.replace(
            scenario,
            homes=[
                dataclasses.replace(home, seg_tariff=tariff)
                for home, tariff in zip(scenario.homes, carried, strict=True)
            ],
        )

        new = apply_knob(scenario, "seg", 6.0)

        assert new.seg_tariff_pence_per_kwh == pytest.approx(6.0)
        assert [home.seg_tariff for home in new.homes] == [
            SEGTariff(name="", rate_pence_per_kwh=6.0)
        ] * len(carried)

    @pytest.mark.parametrize("name", ["degradation", "degradation_rate_per_year"])
    def test_degradation_knob_sets_every_homes_pv_degradation(self, name: str) -> None:
        """Either degradation name sets degradation_rate_per_year on every home's PV."""
        scenario = _fleet_scenario()

        new = apply_knob(scenario, name, 0.01)

        assert [home.pv_config.degradation_rate_per_year for home in new.homes] == [0.01] * len(
            scenario.homes
        )

    def test_unknown_knob_raises_value_error(self) -> None:
        """An unrecognised knob name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown sensitivity knob"):
            apply_knob(_fleet_scenario(), "nonexistent_knob_xyz", 1.0)

    def test_finance_knob_without_a_finance_block_raises(self) -> None:
        """A FinanceConfig knob on a scenario whose finance is None raises ValueError."""
        scenario = dataclasses.replace(_fleet_scenario(), finance=None)

        with pytest.raises(ValueError, match="finance"):
            apply_knob(scenario, "battery_cost_per_kwh_gbp", 999.0)

    @pytest.mark.parametrize("name", ["battery_cost_per_kwh_gbp", "seg", "degradation"])
    def test_single_home_scenario_is_refused_for_every_knob_family(self, name: str) -> None:
        """A single-home scenario raises ValueError naming the fleet requirement, whatever the knob."""
        _, finance = make_scenario_and_finance()
        scenario = ScenarioConfig(
            name="single-home",
            period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
            home=make_home_config(),
            finance=finance,
        )

        with pytest.raises(ValueError, match="fleet"):
            apply_knob(scenario, name, 0.01)
