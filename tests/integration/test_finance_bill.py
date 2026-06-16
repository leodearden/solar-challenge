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

    def test_bill_fields_present(self) -> None:
        """BillBreakdown must expose all 11 required fields."""
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        finance = _make_finance()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        # All 11 fields must be present and numeric
        assert hasattr(bill, "standing_charge_gbp")
        assert hasattr(bill, "import_cost_gbp")
        assert hasattr(bill, "vat_gbp")
        assert hasattr(bill, "gross_bill_gbp")
        assert hasattr(bill, "seg_export_income_gbp")
        assert hasattr(bill, "self_consumption_saving_gbp")
        assert hasattr(bill, "baseline_bill_gbp")
        assert hasattr(bill, "net_annual_bill_gbp")
        assert hasattr(bill, "saving_vs_baseline_gbp")
        assert hasattr(bill, "saving_pct")
        assert hasattr(bill, "self_consumption_fraction")

        for field in [
            "standing_charge_gbp", "import_cost_gbp", "vat_gbp", "gross_bill_gbp",
            "seg_export_income_gbp", "self_consumption_saving_gbp", "baseline_bill_gbp",
            "net_annual_bill_gbp", "saving_vs_baseline_gbp", "saving_pct",
            "self_consumption_fraction",
        ]:
            assert isinstance(getattr(bill, field), float), f"{field} must be float"

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
        """Override self_consumption_saving_gbp differs from physics when override ≠ physics fraction."""
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

        # Higher self-consumption → less export, less import → different bill
        assert bill_override.self_consumption_saving_gbp != pytest.approx(
            bill_physics.self_consumption_saving_gbp
        )

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
