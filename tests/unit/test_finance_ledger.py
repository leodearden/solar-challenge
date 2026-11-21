# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home's billed year as one ledger (docs/prds/finance-partition.md §5.2).

``annualise`` scales a summary's window totals to the window's year, beside the
window and how its run was priced, as one :class:`AnnualPhysics`: the annual
record every billed figure of the home is read from.
"""
from __future__ import annotations

import dataclasses

import pytest

from solar_challenge.finance import AnnualPhysics, annualise
from solar_challenge.home import RunPricing, SummaryStatistics, calculate_summary
from tests._finance_builders import make_sim_results, make_window

_PRICING = RunPricing(0.30, 4.1)
"""A run priced by a 30 p/kWh import tariff whose export earns 4.1 p/kWh of SEG."""


def _thirty_day_summary() -> SummaryStatistics:
    """The summary of 30 days from 2021-01-01: 180 kWh self-consumed, 150 exported, 100 imported and 20 discharged, priced at _PRICING."""
    return calculate_summary(
        make_sim_results(
            days=30, self_kwh=180.0, export_kwh=150.0, import_kwh=100.0, discharge_kwh=20.0, pricing=_PRICING
        )
    )


class TestAnnualise:
    """annualise multiplies each window total by the window's annualisation_scale, and keeps the window and the run's pricing."""

    def test_each_window_total_is_scaled_to_the_windows_year(self) -> None:
        """A 30-day window in 2021 scales by 365/30; generation is self + export and demand self + import − discharge."""
        scale = 365 / 30

        physics = annualise(_thirty_day_summary())

        assert physics.generation_kwh == pytest.approx((180.0 + 150.0) * scale)
        assert physics.demand_kwh == pytest.approx((180.0 + 100.0 - 20.0) * scale)
        assert physics.import_kwh == pytest.approx(100.0 * scale)
        assert physics.import_cost_gbp == pytest.approx(100.0 * 0.30 * scale)
        assert physics.export_kwh == pytest.approx(150.0 * scale)
        assert physics.battery_discharge_kwh == pytest.approx(20.0 * scale)

    def test_it_keeps_the_summarys_window_and_pricing(self) -> None:
        summary = _thirty_day_summary()

        physics = annualise(summary)

        assert physics.window is summary.window
        assert physics.window == make_window(days=30)
        assert physics.pricing == summary.pricing == _PRICING

    def test_its_scale_is_the_windows_annualisation_scale(self) -> None:
        summary = _thirty_day_summary()
        assert summary.window is not None

        assert annualise(summary).scale == summary.window.annualisation_scale

    def test_a_summary_with_no_window_is_refused_naming_calculate_summary(self) -> None:
        windowless = dataclasses.replace(_thirty_day_summary(), window=None)

        with pytest.raises(ValueError, match=r"window.*calculate_summary"):
            annualise(windowless)

    def test_a_summary_with_no_pricing_is_refused_naming_calculate_summary(self) -> None:
        unpriced = dataclasses.replace(_thirty_day_summary(), pricing=None)

        with pytest.raises(ValueError, match=r"pricing.*calculate_summary"):
            annualise(unpriced)

    def test_annual_physics_is_frozen(self) -> None:
        physics: AnnualPhysics = annualise(_thirty_day_summary())

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(physics, "generation_kwh", 0.0)
