# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""householder_bill and bill_distribution price import from the summary's RunPricing, and refuse a summary that has none.

A run a tariff priced, at £0 or more, is billed at its own price: the simulated
import cost on the physics basis, and on the override basis the simulated cost
÷ simulated import kWh, or the tariff's time-weighted mean rate when the run
imported nothing.  A run no tariff priced is billed at the retail rate with a
"no tariff configured" UserWarning, whatever it imported.
"""
from __future__ import annotations

import dataclasses
import warnings
from collections.abc import Callable

import pandas as pd
import pytest

from solar_challenge.finance import BillBreakdown, FinanceConfig, bill_distribution, householder_bill
from solar_challenge.home import RunPricing, SummaryStatistics, calculate_summary
from tests._finance_builders import make_sim_results

_RETAIL_PENCE_PER_KWH = 23.0


def _finance(*, self_consumption_override: float | None = None) -> FinanceConfig:
    """A FinanceConfig at 60 p/day standing, 23 p/kWh retail, 15 p/kWh own-use and 5 % VAT, with *self_consumption_override*."""
    return FinanceConfig(
        standing_charge_pence_per_day=60.0,
        retail_baseline_rate_pence_per_kwh=_RETAIL_PENCE_PER_KWH,
        own_use_rate_pence_per_kwh=15.0,
        vat_rate=0.05,
        self_consumption_override=self_consumption_override,
    )


def _summary(*, self_kwh: float, export_kwh: float, import_kwh: float, pricing: RunPricing) -> SummaryStatistics:
    """calculate_summary of make_sim_results' home over its default whole year, its flows priced at *pricing*."""
    return calculate_summary(
        make_sim_results(self_kwh=self_kwh, export_kwh=export_kwh, import_kwh=import_kwh, pricing=pricing)
    )


def _bill(summary: SummaryStatistics, *, self_consumption_override: float | None = None) -> BillBreakdown:
    """householder_bill of *summary* under _finance(self_consumption_override=...), billing its self-consumption as own-use."""
    return householder_bill(
        summary,
        summary.total_self_consumption_kwh,
        _finance(self_consumption_override=self_consumption_override),
        summary.simulation_days,
    )


class TestPhysicsImport:
    """On the physics basis a priced run's import costs what its simulation priced it at."""

    def test_a_zero_tariff_bills_no_import_and_warns_of_no_missing_tariff(self) -> None:
        summary = _summary(self_kwh=2200.0, export_kwh=1800.0, import_kwh=1200.0, pricing=RunPricing(0.0, None))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            breakdown = _bill(summary)

        assert breakdown.import_cost_gbp == 0.0

    def test_a_run_no_tariff_priced_bills_its_import_at_retail_and_warns(self) -> None:
        summary = _summary(self_kwh=2200.0, export_kwh=1800.0, import_kwh=1200.0, pricing=RunPricing(None, None))

        with pytest.warns(UserWarning, match="no tariff configured"):
            breakdown = _bill(summary)

        assert breakdown.import_cost_gbp == pytest.approx(1200.0 * _RETAIL_PENCE_PER_KWH / 100.0)


class TestOverrideImport:
    """At override 0.5 a home of 4,000 kWh generation and 3,400 kWh demand uses 2,000 kWh and imports 1,400 kWh."""

    def test_a_priced_home_that_imported_nothing_bills_it_at_its_tariffs_mean_rate(self) -> None:
        """30 p, not the 23 p retail rate: the tariff priced the run, so its rate is known though no kWh was imported."""
        summary = _summary(self_kwh=3400.0, export_kwh=600.0, import_kwh=0.0, pricing=RunPricing(0.30, None))
        assert (summary.total_generation_kwh, summary.total_demand_kwh) == pytest.approx((4000.0, 3400.0)), "premise"

        breakdown = _bill(summary, self_consumption_override=0.5)

        assert breakdown.import_cost_gbp == pytest.approx(1400.0 * 0.30)

    def test_a_priced_home_bills_it_at_its_simulated_cost_per_kwh_imported(self) -> None:
        """£360 on 1,200 kWh is 30 p, the price the run paid, rather than the tariff's 20 p mean rate."""
        results = make_sim_results(self_kwh=2200.0, export_kwh=1800.0, import_kwh=1200.0, pricing=RunPricing(0.20, None))
        rows = results.import_cost.index
        summary = calculate_summary(dataclasses.replace(results, import_cost=pd.Series(360.0 / len(rows), index=rows)))
        assert summary.total_import_cost_gbp == pytest.approx(360.0), "premise"

        breakdown = _bill(summary, self_consumption_override=0.5)

        assert breakdown.import_cost_gbp == pytest.approx(1400.0 * 0.30)

    def test_a_home_no_tariff_priced_that_imported_nothing_bills_it_at_retail_and_warns(self) -> None:
        summary = _summary(self_kwh=3400.0, export_kwh=600.0, import_kwh=0.0, pricing=RunPricing(None, None))

        with pytest.warns(UserWarning, match="no tariff configured"):
            breakdown = _bill(summary, self_consumption_override=0.5)

        assert breakdown.import_cost_gbp == pytest.approx(1400.0 * _RETAIL_PENCE_PER_KWH / 100.0)


@pytest.mark.parametrize(
    "bill_it",
    [
        pytest.param(_bill, id="householder_bill"),
        pytest.param(
            lambda summary: bill_distribution([summary], _finance(), summary.simulation_days),
            id="bill_distribution",
        ),
    ],
)
def test_a_summary_without_pricing_is_refused_naming_calculate_summary(
    bill_it: Callable[[SummaryStatistics], object],
) -> None:
    """Its pricing cannot be read from its pounds, so it is refused rather than billed as if no tariff priced it."""
    priced = _summary(self_kwh=2200.0, export_kwh=1800.0, import_kwh=1200.0, pricing=RunPricing(0.30, None))

    with pytest.raises(ValueError) as excinfo:
        bill_it(dataclasses.replace(priced, pricing=None))

    assert "pricing" in str(excinfo.value)
    assert "calculate_summary" in str(excinfo.value)
