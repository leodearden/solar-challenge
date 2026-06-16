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
