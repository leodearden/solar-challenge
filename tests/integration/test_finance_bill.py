# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for the finance bill module (task/44 – δ).

Layout:
  - Fast (no-network) classes: H1 invariants, H2 override, annualisation,
    bill_distribution, report rendering, CLI help/error paths.
  - One @pytest.mark.slow class for the real-PVGIS end-to-end path.

NOTE: This file intentionally mixes fast and slow tests; it must NOT be
added to test_marker_registration.py's INTEGRATION_FILES list.
"""
import warnings
from typing import Optional

import pytest

from solar_challenge.config import FinanceConfig
from solar_challenge.home import SummaryStatistics


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_summary(
    *,
    total_generation_kwh: float = 4000.0,
    total_demand_kwh: float = 3400.0,
    total_self_consumption_kwh: float = 2200.0,
    total_grid_import_kwh: float = 1200.0,
    total_grid_export_kwh: float = 1800.0,
    total_import_cost_gbp: float = 276.0,   # 1200 kWh × 23 p/kWh
    total_export_revenue_gbp: float = 73.8,  # 1800 kWh × 4.1 p/kWh
    net_cost_gbp: float = 202.2,             # 276.0 - 73.8
    simulation_days: int = 365,
    seg_revenue_gbp: Optional[float] = 73.8,
) -> SummaryStatistics:
    """Build a synthetic SummaryStatistics for finance tests."""
    sc_ratio = total_self_consumption_kwh / max(total_generation_kwh, 1e-9)
    gd_ratio = total_grid_import_kwh / max(total_demand_kwh, 1e-9)
    ex_ratio = total_grid_export_kwh / max(total_generation_kwh, 1e-9)
    return SummaryStatistics(
        total_generation_kwh=total_generation_kwh,
        total_demand_kwh=total_demand_kwh,
        total_self_consumption_kwh=total_self_consumption_kwh,
        total_grid_import_kwh=total_grid_import_kwh,
        total_grid_export_kwh=total_grid_export_kwh,
        total_battery_charge_kwh=0.0,
        total_battery_discharge_kwh=0.0,
        peak_generation_kw=3.5,
        peak_demand_kw=2.0,
        self_consumption_ratio=sc_ratio,
        grid_dependency_ratio=gd_ratio,
        export_ratio=ex_ratio,
        simulation_days=simulation_days,
        total_import_cost_gbp=total_import_cost_gbp,
        total_export_revenue_gbp=total_export_revenue_gbp,
        net_cost_gbp=net_cost_gbp,
        seg_revenue_gbp=seg_revenue_gbp,
    )


def _make_finance(
    *,
    standing_charge_pence_per_day: float = 60.0,
    vat_rate: float = 0.05,
    retail_baseline_rate_pence_per_kwh: float = 23.0,
    self_consumption_override: Optional[float] = None,
) -> FinanceConfig:
    """Build a FinanceConfig for finance tests."""
    return FinanceConfig(
        standing_charge_pence_per_day=standing_charge_pence_per_day,
        vat_rate=vat_rate,
        retail_baseline_rate_pence_per_kwh=retail_baseline_rate_pence_per_kwh,
        self_consumption_override=self_consumption_override,
    )


# ---------------------------------------------------------------------------
# Step-1: H1 – householder_bill physics path invariants
# ---------------------------------------------------------------------------

class TestHouseholderBillPhysics:
    """Fast (no-network) tests for householder_bill physics path (H1)."""

    def test_bill_definitional_invariants(self) -> None:
        """BillBreakdown definitional invariants must all hold exactly."""
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        finance = _make_finance()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        assert isinstance(bill, BillBreakdown)

        # --- Field values from summary ---
        assert bill.import_cost_gbp == pytest.approx(summary.total_import_cost_gbp)
        assert bill.seg_export_income_gbp == pytest.approx(summary.total_export_revenue_gbp)

        # --- Standing charge ---
        expected_standing = finance.standing_charge_pence_per_day * 365 / 100
        assert bill.standing_charge_gbp == pytest.approx(expected_standing)

        # --- VAT invariant: vat_gbp == vat_rate × (import_cost + standing) ---
        expected_vat = finance.vat_rate * (bill.import_cost_gbp + bill.standing_charge_gbp)
        assert bill.vat_gbp == pytest.approx(expected_vat)

        # --- Gross bill invariant: gross_bill == (import_cost + standing) × (1 + vat_rate) ---
        expected_gross = (bill.import_cost_gbp + bill.standing_charge_gbp) * (1 + finance.vat_rate)
        assert bill.gross_bill_gbp == pytest.approx(expected_gross)

        # --- Net annual bill: gross_bill - seg_export_income ---
        expected_net = bill.gross_bill_gbp - bill.seg_export_income_gbp
        assert bill.net_annual_bill_gbp == pytest.approx(expected_net)

        # --- Self-consumption fraction ---
        expected_sc_fraction = (
            summary.total_self_consumption_kwh / summary.total_generation_kwh
        )
        assert bill.self_consumption_fraction == pytest.approx(expected_sc_fraction)

        # --- Exact net_cost_gbp reconciliation ---
        # net_annual_bill == net_cost_gbp + import_cost × vat_rate + standing × (1 + vat_rate)
        expected_exact = (
            summary.net_cost_gbp
            + bill.import_cost_gbp * finance.vat_rate
            + bill.standing_charge_gbp * (1 + finance.vat_rate)
        )
        assert bill.net_annual_bill_gbp == pytest.approx(expected_exact)

    def test_saving_fields(self) -> None:
        """Saving fields must be derived from baseline and net bills."""
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        finance = _make_finance()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        # saving_vs_baseline = baseline - net_annual_bill
        expected_saving = bill.baseline_bill_gbp - bill.net_annual_bill_gbp
        assert bill.saving_vs_baseline_gbp == pytest.approx(expected_saving)

        # saving_pct = saving / baseline × 100
        if bill.baseline_bill_gbp != 0:
            expected_pct = (bill.saving_vs_baseline_gbp / bill.baseline_bill_gbp) * 100
            assert bill.saving_pct == pytest.approx(expected_pct)


# ---------------------------------------------------------------------------
# Step-3: H2 – self-consumption override switch + annualisation
# ---------------------------------------------------------------------------


class TestHouseholderBillOverrideAndAnnualisation:
    """Fast (no-network) tests for override switch (H2) and annualisation."""

    def test_override_self_consumption_fraction(self) -> None:
        """With self_consumption_override=0.70, fraction must equal 0.70."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        finance = _make_finance(self_consumption_override=0.70)

        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        assert bill.self_consumption_fraction == pytest.approx(0.70)

    def test_override_implied_self_consumption(self) -> None:
        """Implied self_consumption == override × total_generation."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        finance = _make_finance(self_consumption_override=0.70)

        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        expected_sc = 0.70 * summary.total_generation_kwh
        # self_consumption_saving reflects self-consumed energy at baseline rate
        # so we can back-calculate sc_kwh = saving / (rate × (1+vat) / 100)
        rate = finance.retail_baseline_rate_pence_per_kwh
        vat = finance.vat_rate
        implied_sc = bill.self_consumption_saving_gbp / (rate * (1 + vat) / 100.0)
        assert implied_sc == pytest.approx(expected_sc, rel=1e-6)

    def test_override_differs_from_physics(self) -> None:
        """Override bill differs from physics on import_cost, export income, and net bill."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        physics_fraction = summary.total_self_consumption_kwh / summary.total_generation_kwh
        # Use an override that is distinctly different from the physics fraction
        override_val = 0.90

        assert abs(physics_fraction - override_val) > 0.1, (
            "Test requires override to differ materially from physics fraction"
        )

        bill_physics = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=None),
            simulation_days=summary.simulation_days,
        )
        bill_override = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=override_val),
            simulation_days=summary.simulation_days,
        )

        # Higher self-consumption → different self-consumption saving
        assert bill_override.self_consumption_saving_gbp != pytest.approx(
            bill_physics.self_consumption_saving_gbp
        )
        # import_cost_gbp must change: override implies different grid import
        assert bill_override.import_cost_gbp != pytest.approx(bill_physics.import_cost_gbp)
        # seg_export_income_gbp must change: override implies different grid export
        assert bill_override.seg_export_income_gbp != pytest.approx(
            bill_physics.seg_export_income_gbp
        )
        # The headline net bill must also differ
        assert bill_override.net_annual_bill_gbp != pytest.approx(bill_physics.net_annual_bill_gbp)

    def test_override_bill_shape_identical(self) -> None:
        """Override path produces same BillBreakdown shape (all 11 fields)."""
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.70),
            simulation_days=summary.simulation_days,
        )

        assert isinstance(bill, BillBreakdown)
        for field in [
            "standing_charge_gbp", "import_cost_gbp", "vat_gbp", "gross_bill_gbp",
            "seg_export_income_gbp", "self_consumption_saving_gbp", "baseline_bill_gbp",
            "net_annual_bill_gbp", "saving_vs_baseline_gbp", "saving_pct",
            "self_consumption_fraction",
        ]:
            assert hasattr(bill, field)
            assert isinstance(getattr(bill, field), float), f"{field} must be float"

    def test_short_period_triggers_warning(self) -> None:
        """simulation_days=30 must emit a UserWarning."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary(
            simulation_days=30,
            # Scale down the financials to be consistent with 30-day period
            total_import_cost_gbp=22.68,
            total_export_revenue_gbp=6.07,
            net_cost_gbp=16.61,
            total_generation_kwh=328.77,
            total_demand_kwh=279.45,
            total_self_consumption_kwh=180.82,
            total_grid_import_kwh=98.63,
            total_grid_export_kwh=147.95,
            seg_revenue_gbp=6.07,
        )
        finance = _make_finance()

        with pytest.warns(UserWarning, match="30 days"):
            bill = householder_bill(
                summary=summary,
                annual_self_consumption_kwh=summary.total_self_consumption_kwh,
                finance=finance,
                simulation_days=30,
            )

        # After annualisation to 365 days, standing charge must be the full annual value
        expected_standing = finance.standing_charge_pence_per_day * 365 / 100
        assert bill.standing_charge_gbp == pytest.approx(expected_standing)

    def test_full_year_no_warning(self) -> None:
        """simulation_days=365 must not emit any warning."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary(simulation_days=365)
        finance = _make_finance()

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            bill = householder_bill(
                summary=summary,
                annual_self_consumption_kwh=summary.total_self_consumption_kwh,
                finance=finance,
                simulation_days=365,
            )

        # No exception means no warning was emitted
        assert bill.net_annual_bill_gbp > 0

    def test_annualisation_scales_energy_quantities(self) -> None:
        """Short-period bill's net cost must be approximately (365/30)× the 30-day sim values."""
        from solar_challenge.finance import householder_bill

        # 30-day summary: energy quantities are 30/365 of typical annual
        scale_factor = 365 / 30
        gen_30 = 4000.0 / scale_factor
        demand_30 = 3400.0 / scale_factor
        sc_30 = 2200.0 / scale_factor
        import_kwh_30 = 1200.0 / scale_factor
        export_kwh_30 = 1800.0 / scale_factor
        import_cost_30 = 276.0 / scale_factor
        export_rev_30 = 73.8 / scale_factor
        net_cost_30 = (276.0 - 73.8) / scale_factor

        summary_30 = _make_summary(
            simulation_days=30,
            total_generation_kwh=gen_30,
            total_demand_kwh=demand_30,
            total_self_consumption_kwh=sc_30,
            total_grid_import_kwh=import_kwh_30,
            total_grid_export_kwh=export_kwh_30,
            total_import_cost_gbp=import_cost_30,
            total_export_revenue_gbp=export_rev_30,
            net_cost_gbp=net_cost_30,
            seg_revenue_gbp=export_rev_30,
        )

        summary_365 = _make_summary(simulation_days=365)
        finance = _make_finance()

        with pytest.warns(UserWarning):
            bill_30 = householder_bill(
                summary=summary_30,
                annual_self_consumption_kwh=summary_30.total_self_consumption_kwh,
                finance=finance,
                simulation_days=30,
            )

        bill_365 = householder_bill(
            summary=summary_365,
            annual_self_consumption_kwh=summary_365.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )

        # Annualised 30-day bill should be approximately equal to the 365-day bill
        assert bill_30.import_cost_gbp == pytest.approx(bill_365.import_cost_gbp, rel=1e-6)
        assert bill_30.seg_export_income_gbp == pytest.approx(
            bill_365.seg_export_income_gbp, rel=1e-6
        )


# ---------------------------------------------------------------------------
# Override exact-numeric validation (Suggestion 1)
# ---------------------------------------------------------------------------


class TestOverrideExactValues:
    """Verify exact import/export recomputation in the spreadsheet override path.

    Uses _make_summary() which has consistent physics figures:
      - import_rate  = 276.0 / 1200.0 × 100 = 23.0 p/kWh
      - export_rate  =  73.8 / 1800.0 × 100 =  4.1 p/kWh

    With override = 0.90 and gen = 4000 kWh, demand = 3400 kWh:
      - sc_kwh               = 0.90 × 4000 = 3600.0 kWh
      - override_export_kwh  = max(4000 - 3600, 0) = 400.0 kWh
      - override_import_kwh  = max(3400 - 3600, 0) = 0.0 kWh  (clamped)
      - import_cost_gbp      = 0.0 × 23.0 / 100 = 0.0 £
      - seg_export_income    = 400.0 × 4.1 / 100 = 16.4 £
      - standing             = 60.0 × 365 / 100  = 219.0 £
      - gross_bill           = (0.0 + 219.0) × 1.05 = 229.95 £
      - net_annual_bill      = 229.95 - 16.4 = 213.55 £
    """

    def test_override_exact_import_cost(self) -> None:
        """import_cost_gbp must match hand-computed expectation for override=0.90."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()  # import_rate = 23.0 p/kWh, gen=4000, demand=3400
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.90),
            simulation_days=365,
        )
        # demand(3400) < sc(3600) → override_import_kwh = 0 → import_cost = 0
        assert bill.import_cost_gbp == pytest.approx(0.0, abs=1e-6)

    def test_override_exact_seg_export_income(self) -> None:
        """seg_export_income_gbp must match hand-computed expectation for override=0.90."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()  # export_rate = 4.1 p/kWh, gen=4000
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.90),
            simulation_days=365,
        )
        # override_export_kwh = max(4000 - 3600, 0) = 400 kWh
        # seg_export_income = 400 × 4.1 / 100 = 16.4 £
        assert bill.seg_export_income_gbp == pytest.approx(16.4, rel=1e-6)

    def test_override_exact_net_annual_bill(self) -> None:
        """net_annual_bill_gbp must match hand-computed expectation for override=0.90."""
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.90),
            simulation_days=365,
        )
        # gross = (0.0 + 219.0) × 1.05 = 229.95; net = 229.95 - 16.4 = 213.55
        assert bill.net_annual_bill_gbp == pytest.approx(213.55, rel=1e-5)

    def test_override_zero_import_kwh_fallback(self) -> None:
        """When total_grid_import_kwh==0, effective import rate falls back to retail_baseline_rate."""
        from solar_challenge.finance import householder_bill

        # Summary where physics import is zero (all demand met by solar/battery)
        summary_no_import = _make_summary(
            total_grid_import_kwh=0.0,
            total_import_cost_gbp=0.0,
            total_grid_export_kwh=1800.0,
            total_export_revenue_gbp=73.8,
            net_cost_gbp=-73.8,  # exporter only
        )
        finance = _make_finance(self_consumption_override=0.50)  # will need some import

        bill = householder_bill(
            summary=summary_no_import,
            annual_self_consumption_kwh=summary_no_import.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        # With override=0.50: sc=2000kWh, import=max(3400-2000,0)=1400kWh
        # fallback import rate = retail_baseline_rate = 23.0 p/kWh
        expected_import_cost = 1400.0 * 23.0 / 100.0
        assert bill.import_cost_gbp == pytest.approx(expected_import_cost, rel=1e-5)

    def test_override_zero_export_kwh_fallback(self) -> None:
        """When total_grid_export_kwh==0, effective export rate falls back to 0.0."""
        from solar_challenge.finance import householder_bill

        # Summary where physics export is zero (no surplus)
        summary_no_export = _make_summary(
            total_grid_export_kwh=0.0,
            total_export_revenue_gbp=0.0,
            total_grid_import_kwh=1200.0,
            total_import_cost_gbp=276.0,
            net_cost_gbp=276.0,
        )
        finance = _make_finance(self_consumption_override=0.30)  # leaves surplus

        bill = householder_bill(
            summary=summary_no_export,
            annual_self_consumption_kwh=summary_no_export.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        # export_rate fallback = 0.0, so seg_export_income = 0 regardless of export kWh
        assert bill.seg_export_income_gbp == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Step-5: bill_distribution / BillDistribution tests
# ---------------------------------------------------------------------------


class TestBillDistribution:
    """Fast (no-network) tests for bill_distribution and BillDistribution."""

    def _make_fleet(self) -> list:
        """Create a 5-home fleet with varying costs."""
        # Five homes with increasing import costs → distinct net bills
        homes = []
        for multiplier in [0.5, 0.8, 1.0, 1.3, 1.6]:
            homes.append(
                _make_summary(
                    total_import_cost_gbp=276.0 * multiplier,
                    total_export_revenue_gbp=73.8 * multiplier,
                    net_cost_gbp=202.2 * multiplier,
                    total_generation_kwh=4000.0,
                    total_demand_kwh=3400.0,
                    total_self_consumption_kwh=2200.0 * multiplier,
                    total_grid_import_kwh=1200.0 * multiplier,
                    total_grid_export_kwh=1800.0 * multiplier,
                    seg_revenue_gbp=73.8 * multiplier,
                )
            )
        return homes

    def test_distribution_length(self) -> None:
        """per_home_net_bill_gbp must have length == n_homes."""
        from solar_challenge.finance import bill_distribution

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        assert len(dist.per_home_net_bill_gbp) == len(summaries)

    def test_per_home_bills_match_individual(self) -> None:
        """per_home_net_bill_gbp[i] must equal householder_bill(summaries[i]).net_annual_bill_gbp."""
        from solar_challenge.finance import bill_distribution, householder_bill

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        for i, s in enumerate(summaries):
            expected_bill = householder_bill(
                summary=s,
                annual_self_consumption_kwh=s.total_self_consumption_kwh,
                finance=finance,
                simulation_days=365,
            )
            assert dist.per_home_net_bill_gbp[i] == pytest.approx(expected_bill.net_annual_bill_gbp)

    def test_stats_match_net_bills(self) -> None:
        """min/mean/median/max must match pd.Series stats of per_home_net_bill_gbp."""
        import pandas as pd
        from solar_challenge.finance import bill_distribution

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        series = pd.Series(list(dist.per_home_net_bill_gbp))
        assert dist.min_gbp == pytest.approx(float(series.min()))
        assert dist.mean_gbp == pytest.approx(float(series.mean()))
        assert dist.median_gbp == pytest.approx(float(series.median()))
        assert dist.max_gbp == pytest.approx(float(series.max()))

    def test_representative_is_median_home(self) -> None:
        """representative must be the BillBreakdown of the median-net-bill home."""
        from solar_challenge.finance import bill_distribution, householder_bill

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        # Find the median home index manually
        import pandas as pd
        net_bills = list(dist.per_home_net_bill_gbp)
        series = pd.Series(net_bills)
        median_val = float(series.median())
        rep_idx = int((series - median_val).abs().idxmin())

        expected_rep = householder_bill(
            summary=summaries[rep_idx],
            annual_self_consumption_kwh=summaries[rep_idx].total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        assert dist.representative.net_annual_bill_gbp == pytest.approx(
            expected_rep.net_annual_bill_gbp
        )

    def test_single_home_fleet(self) -> None:
        """Single-home fleet: representative equals that home, min==mean==median==max."""
        from solar_challenge.finance import bill_distribution

        summary = _make_summary()
        finance = _make_finance()
        dist = bill_distribution([summary], finance, 365)

        assert len(dist.per_home_net_bill_gbp) == 1
        net = dist.per_home_net_bill_gbp[0]
        assert dist.representative.net_annual_bill_gbp == pytest.approx(net)
        assert dist.min_gbp == pytest.approx(net)
        assert dist.mean_gbp == pytest.approx(net)
        assert dist.median_gbp == pytest.approx(net)
        assert dist.max_gbp == pytest.approx(net)

    def test_per_home_net_bill_is_tuple(self) -> None:
        """per_home_net_bill_gbp must be a tuple (immutable)."""
        from solar_challenge.finance import bill_distribution

        summaries = self._make_fleet()
        dist = bill_distribution(summaries, _make_finance(), 365)

        assert isinstance(dist.per_home_net_bill_gbp, tuple)

    def test_empty_summaries_raises_value_error(self) -> None:
        """bill_distribution must raise ValueError for an empty summaries sequence."""
        from solar_challenge.finance import bill_distribution

        with pytest.raises(ValueError, match="at least one summary"):
            bill_distribution([], _make_finance(), 365)


# ---------------------------------------------------------------------------
# Step-7: generate_finance_report rendering tests
# ---------------------------------------------------------------------------


def _make_bill_distribution(multiplier: float = 1.0) -> "BillDistribution":  # type: ignore[name-defined]
    """Build a synthetic BillDistribution for report rendering tests."""
    from solar_challenge.finance import BillBreakdown, BillDistribution

    rep = BillBreakdown(
        standing_charge_gbp=219.0 * multiplier,
        import_cost_gbp=276.0 * multiplier,
        vat_gbp=24.75 * multiplier,
        gross_bill_gbp=519.75 * multiplier,
        seg_export_income_gbp=73.8 * multiplier,
        self_consumption_saving_gbp=531.3 * multiplier,
        baseline_bill_gbp=980.0 * multiplier,
        net_annual_bill_gbp=445.95 * multiplier,
        saving_vs_baseline_gbp=534.05 * multiplier,
        saving_pct=54.5 * multiplier,
        self_consumption_fraction=0.55 * multiplier,
    )
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(rep.net_annual_bill_gbp,),
        min_gbp=300.0 * multiplier,
        mean_gbp=440.0 * multiplier,
        median_gbp=rep.net_annual_bill_gbp,
        max_gbp=600.0 * multiplier,
    )


class TestGenerateFinanceReport:
    """Fast (no-network) tests for output.generate_finance_report rendering."""

    def test_returns_string(self) -> None:
        """generate_finance_report must return a str."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)
        assert isinstance(report, str)

    def test_physics_bill_block_present(self) -> None:
        """Report must contain the householder-bill block headings."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        # Key line items must be present
        assert "Standing Charge" in report or "standing" in report.lower()
        assert "Import" in report or "import" in report.lower()
        assert "VAT" in report or "vat" in report.lower()
        assert "Gross Bill" in report or "gross" in report.lower()
        assert "SEG" in report or "seg" in report.lower() or "Export" in report
        assert "Net Annual Bill" in report or "net" in report.lower()

    def test_distribution_table_present(self) -> None:
        """Report must contain a per-home distribution table with min/mean/median/max."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        assert "min" in report.lower() or "Min" in report
        assert "mean" in report.lower() or "Mean" in report
        assert "median" in report.lower() or "Median" in report
        assert "max" in report.lower() or "Max" in report

    def test_representative_values_in_report(self) -> None:
        """Report must include representative bill values."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        # Check net_annual_bill_gbp appears (formatted to 2 dp)
        net = dist.representative.net_annual_bill_gbp
        assert f"{net:.2f}" in report

    def test_scenario_name_in_report(self) -> None:
        """When scenario_name is provided it must appear in the report."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist, scenario_name="Bristol Phase 1")

        assert "Bristol Phase 1" in report

    def test_both_assumptions_side_by_side(self) -> None:
        """With physics AND spreadsheet BillDistributions, both labels must appear."""
        from solar_challenge.output import generate_finance_report

        dist_physics = _make_bill_distribution(multiplier=1.0)
        dist_spreadsheet = _make_bill_distribution(multiplier=1.2)

        report = generate_finance_report(
            dist_physics,
            bill_spreadsheet=dist_spreadsheet,
        )

        # Both assumption labels must be present
        assert "physics" in report.lower() or "Physics" in report
        assert "spreadsheet" in report.lower() or "Spreadsheet" in report

    def test_physics_only_no_spreadsheet_label(self) -> None:
        """With only physics BillDistribution, 'Spreadsheet' label must NOT appear."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        assert "spreadsheet" not in report.lower()


# ---------------------------------------------------------------------------
# Step-9: CLI tests (fast + slow e2e)
# ---------------------------------------------------------------------------


class TestFinanceCLI:
    """Fast CLI tests using typer CliRunner (no simulation)."""

    def test_help_exits_zero(self) -> None:
        """`finance run --help` must exit 0."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output

    def test_help_shows_run_command(self) -> None:
        """`finance --help` must list the `run` command."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "--help"])
        assert result.exit_code == 0, result.output
        assert "run" in result.output.lower()

    def test_help_shows_assumptions_option(self) -> None:
        """`finance run --help` must show `--assumptions` with physics|spreadsheet|both."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        output = result.output.lower()
        assert "assumptions" in output
        assert "physics" in output
        assert "spreadsheet" in output
        assert "both" in output

    def test_missing_finance_block_exits_nonzero(self, tmp_path: "Path") -> None:
        """Invoking `finance run` on a scenario without `finance:` must exit non-zero."""
        import yaml
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        # Minimal scenario without finance:
        scenario = {
            "name": "No Finance Test",
            "location": {
                "latitude": 51.45,
                "longitude": -2.58,
                "timezone": "Europe/London",
            },
            "fleet_distribution": {
                "n_homes": 1,
                "seed": 1,
                "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
                "battery": {"capacity_kwh": None},
                "load": {"annual_consumption_kwh": 3400},
            },
        }
        scenario_file = tmp_path / "no_finance.yaml"
        scenario_file.write_text(yaml.dump(scenario))

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", str(scenario_file)])
        assert result.exit_code != 0

    def test_missing_finance_block_error_message(self, tmp_path: "Path") -> None:
        """Error message must mention 'finance' when finance: block is missing."""
        import yaml
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario = {
            "name": "No Finance Test",
            "location": {
                "latitude": 51.45,
                "longitude": -2.58,
                "timezone": "Europe/London",
            },
            "fleet_distribution": {
                "n_homes": 1,
                "seed": 1,
                "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
                "battery": {"capacity_kwh": None},
                "load": {"annual_consumption_kwh": 3400},
            },
        }
        scenario_file = tmp_path / "no_finance2.yaml"
        scenario_file.write_text(yaml.dump(scenario))

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", str(scenario_file)])
        combined = (result.output or "") + (str(result.exception) if result.exception else "")
        assert "finance" in combined.lower()


@pytest.mark.slow
class TestFinanceCLIEndToEnd:
    """Slow end-to-end CLI test using real PVGIS (weather cache must be warm)."""

    def test_finance_run_bristol_short_window(self) -> None:
        """E2E: `finance run scenarios/bristol-phase1.yaml` exits 0 with report headings."""
        from pathlib import Path
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario = Path("scenarios/bristol-phase1.yaml")
        if not scenario.exists():
            pytest.skip("bristol-phase1.yaml not found")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "finance",
                "run",
                str(scenario),
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-03",
            ],
        )
        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        output = result.output.lower()
        # Householder-bill block headings must be present
        assert "finance" in output or "bill" in output
        assert "net" in output or "annual" in output
