# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home's billed year as one ledger (docs/prds/finance-partition.md §5.2).

``annualise`` scales a summary's window totals to the window's year, beside the
window and how its run was priced, as one :class:`AnnualPhysics`: the annual
record every billed figure of the home is read from.  A :class:`HomeLedger` is
the home's year as the CBS bills it, and refuses a year whose balances break:
L1 every figure finite and >= 0, L2 own-use within demand, L3 own-use and import
covering demand, and L4, on the override's basis, own-use + import = demand and
own-use + export = generation, each to a relative 1e-12.  ``home_ledger`` is the
one assembly of a ledger from a home's AnnualPhysics, holding every pricing rule
of the PRD's table and warning about nothing.
"""
from __future__ import annotations

import dataclasses
import math
import warnings
from typing import Any

import pytest

from solar_challenge.finance import (
    AnnualPhysics,
    FinanceConfig,
    HomeLedger,
    OwnUseBasis,
    annualise,
    home_ledger,
)
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


def _ledger(**overrides: Any) -> HomeLedger:
    """A balanced SIMULATED year, with *overrides* in place of its figures.

    It generates 4000 kWh and demands 3400: 2200 of the demand is own-use and
    1200 is imported at 30 p/kWh (£360), and the 1800 exported earns 4.1 p/kWh
    of SEG (£73.80).
    """
    figures: dict[str, Any] = {
        "basis": OwnUseBasis.SIMULATED,
        "generation_kwh": 4000.0,
        "demand_kwh": 3400.0,
        "own_use_kwh": 2200.0,
        "import_kwh": 1200.0,
        "import_cost_gbp": 360.0,
        "import_at_retail": False,
        "export_kwh": 1800.0,
        "seg_income_gbp": 73.8,
        "own_use_capped": False,
    }
    return HomeLedger(**{**figures, **overrides})


_OVERRIDE_SPLIT: dict[str, Any] = {
    "basis": OwnUseBasis.OVERRIDE,
    "own_use_kwh": 2800.0,
    "import_kwh": 600.0,
    "import_cost_gbp": 180.0,
    "export_kwh": 1200.0,
    "seg_income_gbp": 49.2,
}
"""_ledger's year split by an override of 0.7: own-use 0.7 × 4000 = 2800, import 3400 − 2800, export 4000 − 2800."""

_FIGURES = (
    "generation_kwh",
    "demand_kwh",
    "own_use_kwh",
    "import_kwh",
    "import_cost_gbp",
    "export_kwh",
    "seg_income_gbp",
)


def _named(name: str, value: float) -> str:
    """How a refusal names the figure *name* holding *value*."""
    return f"{name}={value!r}"


class TestHomeLedgerBalances:
    """B4: a HomeLedger refuses, naming the invariant and its values, a year whose balances L1-L4 break."""

    def test_a_balanced_year_constructs_on_either_basis(self) -> None:
        assert _ledger().own_use_kwh == 2200.0
        assert _ledger(**_OVERRIDE_SPLIT).own_use_kwh == 2800.0

    @pytest.mark.parametrize("value", [-1.0, math.nan, math.inf], ids=["negative", "nan", "inf"])
    @pytest.mark.parametrize("figure", _FIGURES)
    def test_l1_refuses_a_figure_that_is_negative_or_not_finite(self, figure: str, value: float) -> None:
        with pytest.raises(ValueError, match="L1") as refusal:
            _ledger(**{figure: value})

        assert _named(figure, value) in str(refusal.value)

    def test_l1_names_every_figure_it_refuses(self) -> None:
        with pytest.raises(ValueError, match="L1") as refusal:
            _ledger(import_kwh=math.inf, import_cost_gbp=math.inf, own_use_kwh=math.nan)

        assert _named("own_use_kwh", math.nan) in str(refusal.value)
        assert _named("import_kwh", math.inf) in str(refusal.value)
        assert _named("import_cost_gbp", math.inf) in str(refusal.value)

    def test_l2_refuses_own_use_above_demand(self) -> None:
        """Own-use 3500 and import 1200 cover the 3400 demand, so only L2 is broken."""
        with pytest.raises(ValueError, match="L2") as refusal:
            _ledger(own_use_kwh=3500.0)

        assert "3500.0" in str(refusal.value)
        assert "3400.0" in str(refusal.value)

    def test_l3_refuses_a_windows_own_use_against_annual_import_and_demand(self) -> None:
        """A 30-day window's own-use, unscaled, beside the year's import does not cover the year's demand."""
        window_own_use_kwh = 2200.0 * 30 / 365

        with pytest.raises(ValueError, match="L3") as refusal:
            _ledger(own_use_kwh=window_own_use_kwh)

        assert _named("demand_kwh", 3400.0) in str(refusal.value)
        assert _named("own_use_kwh", window_own_use_kwh) in str(refusal.value)
        assert _named("import_kwh", 1200.0) in str(refusal.value)

    def test_l3_allows_a_relative_1e_12_and_no_more(self) -> None:
        covered_kwh = 2200.0 + 1200.0

        assert _ledger(demand_kwh=covered_kwh * (1 + 1e-13)).demand_kwh == pytest.approx(covered_kwh)
        with pytest.raises(ValueError, match="L3"):
            _ledger(demand_kwh=covered_kwh * (1 + 1e-9))

    def test_l4_refuses_an_override_whose_own_use_and_export_are_not_its_generation(self) -> None:
        with pytest.raises(ValueError, match="L4") as refusal:
            _ledger(**{**_OVERRIDE_SPLIT, "export_kwh": 1300.0})

        assert _named("own_use_kwh", 2800.0) in str(refusal.value)
        assert _named("export_kwh", 1300.0) in str(refusal.value)
        assert _named("generation_kwh", 4000.0) in str(refusal.value)

    def test_l4_refuses_an_override_whose_own_use_and_import_are_not_its_demand(self) -> None:
        with pytest.raises(ValueError, match="L4") as refusal:
            _ledger(**{**_OVERRIDE_SPLIT, "import_kwh": 700.0})

        assert _named("own_use_kwh", 2800.0) in str(refusal.value)
        assert _named("import_kwh", 700.0) in str(refusal.value)
        assert _named("demand_kwh", 3400.0) in str(refusal.value)

    def test_l4_binds_the_override_only(self) -> None:
        """On the simulated basis, import above demand − own-use is a B-style grid charge, which L3 allows."""
        figures = {**_OVERRIDE_SPLIT, "basis": OwnUseBasis.SIMULATED, "import_kwh": 700.0}

        assert _ledger(**figures).import_kwh == 700.0

    def test_home_ledger_is_frozen(self) -> None:
        ledger = _ledger()

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(ledger, "own_use_kwh", 0.0)


def _physics(**overrides: Any) -> AnnualPhysics:
    """A year over make_window(), scale 1, with *overrides* in place of its figures.

    It generates 4000 kWh and demands 3400, imports 1200 at 30 p/kWh (£360) and
    exports 1800, its run priced at _PRICING.
    """
    figures: dict[str, Any] = {
        "window": make_window(),
        "generation_kwh": 4000.0,
        "demand_kwh": 3400.0,
        "import_kwh": 1200.0,
        "import_cost_gbp": 360.0,
        "export_kwh": 1800.0,
        "battery_discharge_kwh": 0.0,
        "pricing": _PRICING,
    }
    return AnnualPhysics(**{**figures, **overrides})


_RETAIL_PENCE_PER_KWH = 23.0


def _finance(self_consumption_override: float | None = None) -> FinanceConfig:
    """A FinanceConfig at a 23 p/kWh retail baseline, with *self_consumption_override*."""
    return FinanceConfig(
        standing_charge_pence_per_day=28.0,
        retail_baseline_rate_pence_per_kwh=_RETAIL_PENCE_PER_KWH,
        self_consumption_override=self_consumption_override,
    )


class TestHomeLedgerPricingRules:
    """home_ledger holds each pricing rule of PRD §5.2's table, one case per row, and warns about nothing."""

    def test_without_an_own_use_figure_the_simulated_own_use_is_basis_c(self) -> None:
        ledger = home_ledger(_physics(), _finance())

        assert ledger.basis is OwnUseBasis.SIMULATED
        assert ledger.own_use_kwh == 3400.0 - 1200.0
        assert (ledger.import_kwh, ledger.export_kwh) == (1200.0, 1800.0)
        assert ledger.own_use_capped is False

    def test_an_own_use_figure_is_the_simulated_own_use(self) -> None:
        assert home_ledger(_physics(), _finance(), simulated_own_use_kwh=2500.0).own_use_kwh == 2500.0

    def test_basis_c_is_zero_without_a_warning_when_the_import_is_above_the_demand(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ledger = home_ledger(_physics(import_kwh=3600.0), _finance())

        assert ledger.own_use_kwh == 0.0

    def test_a_priced_simulated_import_costs_what_its_run_paid(self) -> None:
        ledger = home_ledger(_physics(), _finance())

        assert ledger.import_cost_gbp == 360.0
        assert ledger.import_at_retail is False

    def test_a_simulated_import_priced_at_zero_costs_nothing(self) -> None:
        ledger = home_ledger(_physics(import_cost_gbp=0.0, pricing=RunPricing(0.0, None)), _finance())

        assert ledger.import_cost_gbp == 0.0
        assert ledger.import_at_retail is False

    @pytest.mark.parametrize(
        ("override", "billed_import_kwh"), [(None, 1200.0), (0.7, 600.0)], ids=["simulated", "override"]
    )
    def test_an_unpriced_import_is_billed_at_retail_on_either_basis(
        self, override: float | None, billed_import_kwh: float
    ) -> None:
        unpriced = _physics(import_cost_gbp=0.0, pricing=RunPricing(None, 4.1))

        ledger = home_ledger(unpriced, _finance(override))

        assert ledger.import_cost_gbp == pytest.approx(billed_import_kwh * _RETAIL_PENCE_PER_KWH / 100)
        assert ledger.import_at_retail is True

    def test_an_override_splits_the_generation_and_the_demand(self) -> None:
        ledger = home_ledger(_physics(), _finance(0.7))

        assert ledger.basis is OwnUseBasis.OVERRIDE
        assert ledger.own_use_kwh == pytest.approx(0.7 * 4000.0)
        assert ledger.import_kwh == pytest.approx(3400.0 - 2800.0)
        assert ledger.export_kwh == pytest.approx(4000.0 - 2800.0)
        assert ledger.own_use_capped is False

    def test_an_override_own_use_above_the_demand_is_capped_at_the_demand(self) -> None:
        ledger = home_ledger(_physics(), _finance(0.9))

        assert (ledger.own_use_kwh, ledger.import_kwh, ledger.export_kwh) == (3400.0, 0.0, 600.0)
        assert ledger.own_use_capped is True

    def test_a_priced_override_import_costs_its_runs_price_per_kwh_imported(self) -> None:
        ledger = home_ledger(_physics(), _finance(0.7))

        assert ledger.import_cost_gbp == pytest.approx(600.0 * 360.0 / 1200.0)

    def test_a_priced_override_import_costs_the_tariffs_mean_rate_when_its_run_imported_nothing(self) -> None:
        ledger = home_ledger(_physics(import_kwh=0.0, import_cost_gbp=0.0), _finance(0.7))

        assert ledger.import_cost_gbp == pytest.approx(600.0 * 0.30)

    @pytest.mark.parametrize(
        ("override", "billed_export_kwh"), [(None, 1800.0), (0.7, 1200.0)], ids=["simulated", "override"]
    )
    def test_seg_income_is_the_billed_export_at_the_runs_seg_rate(
        self, override: float | None, billed_export_kwh: float
    ) -> None:
        ledger = home_ledger(_physics(), _finance(override))

        assert ledger.seg_income_gbp == pytest.approx(billed_export_kwh * 4.1 / 100)

    def test_a_run_no_seg_tariff_priced_earns_no_seg_income(self) -> None:
        assert home_ledger(_physics(pricing=RunPricing(0.30, None)), _finance()).seg_income_gbp == 0.0

    def test_home_ledger_warns_about_nothing(self) -> None:
        """An unpriced home and a capped override build silently: householder_bill warns its caller instead."""
        unpriced = _physics(import_cost_gbp=0.0, pricing=RunPricing(None, None))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            at_retail = home_ledger(unpriced, _finance())
            capped = home_ledger(_physics(), _finance(0.9))

        assert at_retail.import_at_retail is True
        assert capped.own_use_capped is True

    @pytest.mark.parametrize("override", [None, 0.3], ids=["simulated", "override"])
    @pytest.mark.parametrize(
        ("own_use_kwh", "invariant"),
        [(-0.1, "L1"), (math.nan, "L1"), (3400.1, "L2")],
        ids=["below-zero", "nan", "above-the-demand"],
    )
    def test_an_own_use_figure_outside_the_years_demand_is_refused_on_either_basis(
        self, own_use_kwh: float, invariant: str, override: float | None
    ) -> None:
        with pytest.raises(ValueError, match=invariant) as refusal:
            home_ledger(_physics(), _finance(override), simulated_own_use_kwh=own_use_kwh)

        assert repr(own_use_kwh) in str(refusal.value)
