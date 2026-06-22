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
    own_use_rate_pence_per_kwh: float = 15.0,
) -> FinanceConfig:
    """Build a FinanceConfig for finance tests."""
    return FinanceConfig(
        standing_charge_pence_per_day=standing_charge_pence_per_day,
        vat_rate=vat_rate,
        retail_baseline_rate_pence_per_kwh=retail_baseline_rate_pence_per_kwh,
        self_consumption_override=self_consumption_override,
        own_use_rate_pence_per_kwh=own_use_rate_pence_per_kwh,
    )


# ---------------------------------------------------------------------------
# Step-1: H1 – householder_bill physics path invariants
# ---------------------------------------------------------------------------

class TestHouseholderBillPhysics:
    """Fast (no-network) tests for householder_bill physics path (H1)."""

    def test_bill_definitional_invariants(self) -> None:
        """BillBreakdown CR3 definitional invariants must all hold exactly.

        CR3 contract (§3.1):
          own_use_payment_gbp   = own_use_rate × sc_kwh / 100
          vat_gbp               = vat_rate × (import_cost + standing + own_use_payment)
          total_outlay_gbp      = (import_cost + standing + own_use_payment) × (1 + vat_rate)
          self_consumption_saving_gbp = sc × (retail − own_use) × (1+vat)/100
          saving_vs_baseline_gbp = baseline_bill_gbp − total_outlay_gbp

        Removed fields (CBS owns assets): gross_bill_gbp, seg_export_income_gbp,
        net_annual_bill_gbp.
        """
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        finance = _make_finance()  # own_use_rate=15.0 p/kWh
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        assert isinstance(bill, BillBreakdown)

        # --- Removed W2 fields must NOT exist on BillBreakdown ---
        assert not hasattr(bill, "gross_bill_gbp"), "gross_bill_gbp must be removed in CR3"
        assert not hasattr(bill, "seg_export_income_gbp"), "seg_export_income_gbp must be removed in CR3"
        assert not hasattr(bill, "net_annual_bill_gbp"), "net_annual_bill_gbp must be removed in CR3"

        # --- import_cost from summary (unchanged) ---
        assert bill.import_cost_gbp == pytest.approx(summary.total_import_cost_gbp)

        # --- Standing charge (unchanged) ---
        expected_standing = finance.standing_charge_pence_per_day * 365 / 100
        assert bill.standing_charge_gbp == pytest.approx(expected_standing)

        # --- Own-use payment (NEW): own_use_rate × sc_kwh / 100 ---
        sc_kwh = summary.total_self_consumption_kwh
        own_use_rate = finance.own_use_rate_pence_per_kwh
        expected_own_use = own_use_rate * sc_kwh / 100.0
        assert bill.own_use_payment_gbp == pytest.approx(expected_own_use)

        # --- VAT invariant (REDEFINED): vat_rate × (import + standing + own_use_payment) ---
        expected_vat = finance.vat_rate * (
            bill.import_cost_gbp + bill.standing_charge_gbp + bill.own_use_payment_gbp
        )
        assert bill.vat_gbp == pytest.approx(expected_vat)

        # --- Total outlay (NEW HEADLINE): (import + standing + own_use_payment) × (1+vat) ---
        expected_outlay = (
            bill.import_cost_gbp + bill.standing_charge_gbp + bill.own_use_payment_gbp
        ) * (1.0 + finance.vat_rate)
        assert bill.total_outlay_gbp == pytest.approx(expected_outlay)

        # --- Self-consumption saving (REDEFINED): sc × (retail − own_use) × (1+vat)/100 ---
        retail = finance.retail_baseline_rate_pence_per_kwh
        expected_sc_saving = sc_kwh * (retail - own_use_rate) * (1.0 + finance.vat_rate) / 100.0
        assert bill.self_consumption_saving_gbp == pytest.approx(expected_sc_saving)

        # --- Self-consumption fraction (unchanged formula) ---
        expected_sc_fraction = sc_kwh / summary.total_generation_kwh
        assert bill.self_consumption_fraction == pytest.approx(expected_sc_fraction)

    def test_saving_fields(self) -> None:
        """Saving fields must be derived from baseline and total_outlay."""
        from solar_challenge.finance import BillBreakdown, householder_bill

        summary = _make_summary()
        finance = _make_finance()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        # saving_vs_baseline = baseline - total_outlay (CR3 redefinition)
        expected_saving = bill.baseline_bill_gbp - bill.total_outlay_gbp
        assert bill.saving_vs_baseline_gbp == pytest.approx(expected_saving)

        # saving_pct = saving / baseline × 100 (formula unchanged)
        if bill.baseline_bill_gbp != 0:
            expected_pct = (bill.saving_vs_baseline_gbp / bill.baseline_bill_gbp) * 100
            assert bill.saving_pct == pytest.approx(expected_pct)

    def test_h3_board_identity(self) -> None:
        """H3 board identity: saving_vs_baseline == sc × (retail − own_use) × (1+vat).

        This identity holds exactly when import is retail-priced and
        import_kwh == demand − sc (energy balance), as in the default fixture:
          demand 3400 − sc 2200 = import 1200 kWh; import_cost 1200×23p=£276.
        Worked: baseline=(782+219)×1.05=£1051.05; own_use 15p ⇒ own_use_payment=£330;
        total_outlay=(276+219+330)×1.05=£866.25; saving=£184.80
        == 2200×(23−15)×1.05/100=£184.80 ✓
        """
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        finance = _make_finance(own_use_rate_pence_per_kwh=15.0)
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=summary.simulation_days,
        )

        sc_kwh = summary.total_self_consumption_kwh
        retail = finance.retail_baseline_rate_pence_per_kwh
        own_use = finance.own_use_rate_pence_per_kwh
        vat = finance.vat_rate

        # H3 identity: saving == sc × (retail − own_use) × (1+vat) / 100
        expected = sc_kwh * (retail - own_use) * (1.0 + vat) / 100.0
        assert bill.saving_vs_baseline_gbp == pytest.approx(expected, rel=1e-9)

        # Edge case: own_use == retail → saving == 0 and self_consumption_saving == 0
        finance_parity = _make_finance(own_use_rate_pence_per_kwh=retail)
        bill_parity = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance_parity,
            simulation_days=summary.simulation_days,
        )
        assert bill_parity.saving_vs_baseline_gbp == pytest.approx(0.0, abs=1e-9)
        assert bill_parity.self_consumption_saving_gbp == pytest.approx(0.0, abs=1e-9)

    def test_physics_missing_tariff_fallback(self) -> None:
        """Physics path with £0 import cost but real import kWh falls back to retail rate.

        Homes generated from a fleet_distribution carry tariff_config=None, so
        simulate_home reports total_import_cost_gbp == 0 even though energy was
        imported.  householder_bill must price that imported energy at the
        retail baseline rate (and warn) rather than silently emit a £0 import.
        """
        from solar_challenge.finance import householder_bill

        # 1200 kWh imported but tariff absent => physics import cost reported £0
        summary = _make_summary(
            total_import_cost_gbp=0.0,
            total_export_revenue_gbp=0.0,
            net_cost_gbp=0.0,
            seg_revenue_gbp=None,
        )
        finance = _make_finance(retail_baseline_rate_pence_per_kwh=23.0)

        with pytest.warns(UserWarning, match="no tariff configured"):
            bill = householder_bill(
                summary=summary,
                annual_self_consumption_kwh=summary.total_self_consumption_kwh,
                finance=finance,
                simulation_days=summary.simulation_days,
            )

        # import priced at retail baseline rate: 1200 kWh × 23 p/kWh = £276
        expected_import = summary.total_grid_import_kwh * 23.0 / 100.0
        assert bill.import_cost_gbp == pytest.approx(expected_import)
        # the headline bill must now exceed just standing + VAT
        assert bill.import_cost_gbp > 0.0

    def test_physics_no_import_no_fallback(self) -> None:
        """When import kWh is genuinely zero, no fallback and no warning fire."""
        import warnings as _warnings

        from solar_challenge.finance import householder_bill

        summary = _make_summary(
            total_grid_import_kwh=0.0,
            total_import_cost_gbp=0.0,
            net_cost_gbp=0.0,
        )
        finance = _make_finance()

        with _warnings.catch_warnings():
            _warnings.simplefilter("error")
            bill = householder_bill(
                summary=summary,
                annual_self_consumption_kwh=summary.total_self_consumption_kwh,
                finance=finance,
                simulation_days=summary.simulation_days,
            )

        assert bill.import_cost_gbp == pytest.approx(0.0)


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
        """Implied self_consumption == override × total_generation.

        CR3: self_consumption_saving = sc × (retail − own_use) × (1+vat)/100
        So back-calc: sc_kwh = saving / ((retail − own_use) × (1+vat) / 100)
        """
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
        # CR3: sc_saving = sc × (retail − own_use) × (1+vat)/100
        # ⇒ sc_kwh = saving / ((retail − own_use) × (1+vat) / 100)
        retail = finance.retail_baseline_rate_pence_per_kwh
        own_use = finance.own_use_rate_pence_per_kwh
        vat = finance.vat_rate
        implied_sc = bill.self_consumption_saving_gbp / ((retail - own_use) * (1 + vat) / 100.0)
        assert implied_sc == pytest.approx(expected_sc, rel=1e-6)

    def test_override_differs_from_physics(self) -> None:
        """Override bill differs from physics on import_cost, own_use_payment, and total_outlay."""
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
        # own_use_payment_gbp must change: override implies different sc_kwh
        assert bill_override.own_use_payment_gbp != pytest.approx(bill_physics.own_use_payment_gbp)
        # The headline total_outlay must also differ
        assert bill_override.total_outlay_gbp != pytest.approx(bill_physics.total_outlay_gbp)

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
        assert bill.total_outlay_gbp > 0

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
        # CR3: own_use_payment and total_outlay must also annualise correctly
        assert bill_30.own_use_payment_gbp == pytest.approx(
            bill_365.own_use_payment_gbp, rel=1e-6
        )
        assert bill_30.total_outlay_gbp == pytest.approx(bill_365.total_outlay_gbp, rel=1e-6)


# ---------------------------------------------------------------------------
# Override exact-numeric validation (Suggestion 1)
# ---------------------------------------------------------------------------


class TestOverrideExactValues:
    """Verify exact import/own_use recomputation in the spreadsheet override path (CR3).

    Uses _make_summary() which has consistent physics figures:
      - import_rate  = 276.0 / 1200.0 × 100 = 23.0 p/kWh
      - retail_rate  = 23.0 p/kWh  (default)
      - own_use_rate = 15.0 p/kWh  (default)

    With override = 0.90 and gen = 4000 kWh, demand = 3400 kWh, vat = 5%:
      - sc_kwh               = 0.90 × 4000 = 3600.0 kWh
      - override_export_kwh  = max(4000 - 3600, 0) = 400.0 kWh
      - override_import_kwh  = max(3400 - 3600, 0) = 0.0 kWh  (clamped)
      - import_cost_gbp      = 0.0 £
      - own_use_payment_gbp  = 3600 × 15 / 100 = 540.0 £
      - standing             = 60.0 × 365 / 100  = 219.0 £
      - vat_gbp              = 0.05 × (0.0 + 219.0 + 540.0) = 37.95 £
      - total_outlay_gbp     = (0.0 + 219.0 + 540.0) × 1.05 = 796.95 £
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

    def test_override_exact_own_use_payment(self) -> None:
        """own_use_payment_gbp must match hand-computed expectation for override=0.90.

        CR3 replaces seg_export_income with own_use_payment (CBS-owned solar transfer price).
        """
        from solar_challenge.finance import householder_bill

        summary = _make_summary()  # gen=4000
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.90),
            simulation_days=365,
        )
        # sc_kwh = 0.90 × 4000 = 3600; own_use_payment = 3600 × 15 / 100 = 540
        assert bill.own_use_payment_gbp == pytest.approx(540.0, rel=1e-6)

    def test_override_exact_total_outlay(self) -> None:
        """total_outlay_gbp must match hand-computed expectation for override=0.90.

        CR3 headline replaces net_annual_bill_gbp with total_outlay_gbp (no SEG credit).
        """
        from solar_challenge.finance import householder_bill

        summary = _make_summary()
        bill = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=_make_finance(self_consumption_override=0.90),
            simulation_days=365,
        )
        # total_outlay = (0.0 + 219.0 + 540.0) × 1.05 = 759 × 1.05 = 796.95
        assert bill.total_outlay_gbp == pytest.approx(796.95, rel=1e-5)

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
        """Override path with zero physics export: total_outlay must still be positive.

        CR3: The householder has no SEG field; the export-rate fallback logic
        is irrelevant to the householder bill (it moved to _seg_export_income_gbp
        for CBS-revenue use).  Assert the bill computes without error and yields
        a sensible total_outlay.
        """
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
        # CR3: no seg_export_income_gbp on the bill; total_outlay must be positive
        assert bill.total_outlay_gbp > 0.0
        assert not hasattr(bill, "seg_export_income_gbp")


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
        """per_home_net_bill_gbp[i] must equal householder_bill(summaries[i]).total_outlay_gbp.

        CR3: per_home_net_bill_gbp name retained (back-compat §12-Q4), value
        redefined to per-home total_outlay_gbp.

        Basis C (task-84 §6): bill_distribution uses _cbs_own_use_kwh (demand −
        import) as annual_self_consumption_kwh.  The expected bill must use the
        same basis so the assertion reflects the actual contract.
        """
        from solar_challenge.finance import _cbs_own_use_kwh, bill_distribution, householder_bill

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        for i, s in enumerate(summaries):
            expected_bill = householder_bill(
                summary=s,
                # Basis C: matches what bill_distribution passes internally
                annual_self_consumption_kwh=_cbs_own_use_kwh(s),
                finance=finance,
                simulation_days=365,
            )
            assert dist.per_home_net_bill_gbp[i] == pytest.approx(expected_bill.total_outlay_gbp)

    def test_stats_match_total_outlay(self) -> None:
        """min/mean/median/max must match pd.Series stats of per-home total_outlay values."""
        import pandas as pd
        from solar_challenge.finance import bill_distribution

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        # per_home_net_bill_gbp now holds per-home total_outlay values (CR3)
        series = pd.Series(list(dist.per_home_net_bill_gbp))
        assert dist.min_gbp == pytest.approx(float(series.min()))
        assert dist.mean_gbp == pytest.approx(float(series.mean()))
        assert dist.median_gbp == pytest.approx(float(series.median()))
        assert dist.max_gbp == pytest.approx(float(series.max()))

    def test_representative_is_median_outlay_home(self) -> None:
        """representative must be the BillBreakdown of the median-total_outlay home (CR3)."""
        from solar_challenge.finance import bill_distribution, householder_bill

        summaries = self._make_fleet()
        finance = _make_finance()
        dist = bill_distribution(summaries, finance, 365)

        # Find the median-total_outlay home index manually
        import pandas as pd
        outlay_vals = list(dist.per_home_net_bill_gbp)  # now holds total_outlay_gbp
        series = pd.Series(outlay_vals)
        median_val = float(series.median())
        rep_idx = int((series - median_val).abs().idxmin())

        expected_rep = householder_bill(
            summary=summaries[rep_idx],
            annual_self_consumption_kwh=summaries[rep_idx].total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        # CR3: representative keyed on total_outlay_gbp
        assert dist.representative.total_outlay_gbp == pytest.approx(
            expected_rep.total_outlay_gbp
        )

    def test_single_home_fleet(self) -> None:
        """Single-home fleet: representative equals that home, min==mean==median==max."""
        from solar_challenge.finance import bill_distribution

        summary = _make_summary()
        finance = _make_finance()
        dist = bill_distribution([summary], finance, 365)

        assert len(dist.per_home_net_bill_gbp) == 1
        outlay = dist.per_home_net_bill_gbp[0]
        # CR3: per_home_net_bill_gbp holds total_outlay_gbp values
        assert dist.representative.total_outlay_gbp == pytest.approx(outlay)
        assert dist.min_gbp == pytest.approx(outlay)
        assert dist.mean_gbp == pytest.approx(outlay)
        assert dist.median_gbp == pytest.approx(outlay)
        assert dist.max_gbp == pytest.approx(outlay)

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
    """Build a synthetic BillDistribution for report rendering tests (CR3 contract).

    Uses the default _make_summary fixture values (retail 23p, own_use 15p):
      standing=219, import=276, own_use_payment=330, vat=41.25,
      total_outlay=866.25, sc_saving=184.80, baseline=1051.05,
      saving_vs_baseline=184.80, saving_pct≈17.58, sc_fraction=0.55
    """
    from solar_challenge.finance import BillBreakdown, BillDistribution

    rep = BillBreakdown(
        standing_charge_gbp=219.0 * multiplier,
        import_cost_gbp=276.0 * multiplier,
        own_use_payment_gbp=330.0 * multiplier,
        vat_gbp=41.25 * multiplier,
        total_outlay_gbp=866.25 * multiplier,
        self_consumption_saving_gbp=184.80 * multiplier,
        baseline_bill_gbp=1051.05 * multiplier,
        saving_vs_baseline_gbp=184.80 * multiplier,
        saving_pct=17.58 * multiplier,
        self_consumption_fraction=0.55 * multiplier,
    )
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(rep.total_outlay_gbp,),
        min_gbp=700.0 * multiplier,
        mean_gbp=850.0 * multiplier,
        median_gbp=rep.total_outlay_gbp,
        max_gbp=1000.0 * multiplier,
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
        """Report must contain the CR3 householder-bill block headings (no Gross Bill / SEG)."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        # CR3 line items that MUST appear
        assert "Standing Charge" in report or "standing" in report.lower()
        assert "Import" in report or "import" in report.lower()
        assert "VAT" in report or "vat" in report.lower()
        assert "Own-Use Payment" in report or "own-use" in report.lower() or "own_use" in report.lower()
        assert "Total Outlay" in report or "total outlay" in report.lower()

        # W2 fields that must NOT appear (CBS owns assets; no SEG to householder)
        assert "Gross Bill" not in report
        assert "SEG Export Income" not in report
        assert "Net Annual Bill" not in report

    def test_distribution_table_present(self) -> None:
        """Report must contain a per-home total-outlay distribution table."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        assert "min" in report.lower() or "Min" in report
        assert "mean" in report.lower() or "Mean" in report
        assert "median" in report.lower() or "Median" in report
        assert "max" in report.lower() or "Max" in report
        # CR3: distribution heading must reference "outlay" not the old "Net Annual Bill"
        assert "Total Annual Outlay" in report or "total annual outlay" in report.lower()

    def test_representative_values_in_report(self) -> None:
        """Report must include representative total_outlay_gbp value."""
        from solar_challenge.output import generate_finance_report

        dist = _make_bill_distribution()
        report = generate_finance_report(dist)

        # CR3: check total_outlay_gbp appears (formatted to 2 dp)
        outlay = dist.representative.total_outlay_gbp
        assert f"{outlay:.2f}" in report

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


# ---------------------------------------------------------------------------
# Step-3 (task 83): TestHouseholderBillWrapperEquivalence
# ---------------------------------------------------------------------------


class TestHouseholderBillWrapperEquivalence:
    """Regression guard: householder_bill must be a thin wrapper over bill().

    RED pre-refactor (step-4): householder_bill uses retail directly for
    self_consumption_saving while bill() uses eff_rate (a float round-trip),
    so the two can differ by ≤1 ULP. These tests require the wrapper IS that
    bill() call (exact frozen-dataclass equality over all 10 fields).
    """

    def test_wrapper_equals_bill_annual_physics(self) -> None:
        """householder_bill(365-day, physics path) == bill(period_days=365, ...).

        Byte-identical guard over all 10 BillBreakdown fields.
        Pre-refactor: fails by ≤1 ULP on self_consumption_saving_gbp.
        Post-refactor (step-4): passes because the wrapper IS that call.
        """
        from solar_challenge.finance import bill, householder_bill

        summary = _make_summary()   # 365-day, import_cost=276>0
        finance = _make_finance()

        actual = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        baseline_import_cost_gbp = (
            summary.total_demand_kwh * finance.retail_baseline_rate_pence_per_kwh / 100.0
        )
        expected = bill(
            period_days=365,
            generation_kwh=summary.total_generation_kwh,
            demand_kwh=summary.total_demand_kwh,
            self_consumption_kwh=summary.total_self_consumption_kwh,
            import_kwh=summary.total_grid_import_kwh,
            import_cost_gbp=summary.total_import_cost_gbp,
            baseline_import_cost_gbp=baseline_import_cost_gbp,
            finance=finance,
        )
        # Exact frozen-dataclass equality (all 10 fields)
        assert actual == expected

    def test_wrapper_equals_bill_annual_override(self) -> None:
        """householder_bill(365-day, override=0.90) == bill(period_days=365, ...) with override inputs.

        Uses pytest.approx(rel=1e-12, abs=1e-12) to be robust to incidental
        operand-order drift in the override path's intermediate computations.
        """
        from solar_challenge.finance import bill, householder_bill

        summary = _make_summary()   # import_rate = 23.0 p/kWh, gen=4000, demand=3400
        finance = _make_finance(self_consumption_override=0.90)

        actual = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )

        # Reproduce wrapper's override path inputs with IDENTICAL expressions
        gen_kwh = summary.total_generation_kwh
        demand_kwh = summary.total_demand_kwh
        import_kwh = summary.total_grid_import_kwh
        import_cost_physics = summary.total_import_cost_gbp
        retail_rate = finance.retail_baseline_rate_pence_per_kwh

        sc_kwh = finance.self_consumption_override * gen_kwh   # type: ignore[operator]  # 3600.0
        if import_kwh > 0.0:
            eff_import_rate = (import_cost_physics / import_kwh) * 100.0
        else:
            eff_import_rate = retail_rate
        override_import_kwh = max(demand_kwh - sc_kwh, 0.0)
        override_import_cost = override_import_kwh * eff_import_rate / 100.0
        baseline_import_cost_gbp = demand_kwh * retail_rate / 100.0

        expected = bill(
            period_days=365,
            generation_kwh=gen_kwh,
            demand_kwh=demand_kwh,
            self_consumption_kwh=sc_kwh,
            import_kwh=override_import_kwh,
            import_cost_gbp=override_import_cost,
            baseline_import_cost_gbp=baseline_import_cost_gbp,
            finance=finance,
        )
        # Field-by-field approximate equality (robust to incidental operand-order drift)
        assert actual.standing_charge_gbp == pytest.approx(
            expected.standing_charge_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.import_cost_gbp == pytest.approx(
            expected.import_cost_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.own_use_payment_gbp == pytest.approx(
            expected.own_use_payment_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.vat_gbp == pytest.approx(expected.vat_gbp, rel=1e-12, abs=1e-12)
        assert actual.total_outlay_gbp == pytest.approx(
            expected.total_outlay_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.self_consumption_saving_gbp == pytest.approx(
            expected.self_consumption_saving_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.baseline_bill_gbp == pytest.approx(
            expected.baseline_bill_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.saving_vs_baseline_gbp == pytest.approx(
            expected.saving_vs_baseline_gbp, rel=1e-12, abs=1e-12
        )
        assert actual.saving_pct == pytest.approx(expected.saving_pct, rel=1e-12, abs=1e-12)
        assert actual.self_consumption_fraction == pytest.approx(
            expected.self_consumption_fraction, rel=1e-12, abs=1e-12
        )

    def test_wrapper_standing_still_annual_for_short_period(self) -> None:
        """householder_bill for a short-period sim still annualises standing to 365 days.

        The wrapper always calls bill(period_days=365, ...) regardless of simulation_days,
        so the standing charge stays at the full annual value even for a 30-day sim.
        """
        from solar_challenge.finance import householder_bill

        finance = _make_finance(standing_charge_pence_per_day=60.0)
        summary = _make_summary(
            simulation_days=30,
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

        with pytest.warns(UserWarning, match="30 days"):
            b = householder_bill(
                summary=summary,
                annual_self_consumption_kwh=summary.total_self_consumption_kwh,
                finance=finance,
                simulation_days=30,
            )

        # Wrapper passes period_days=365 regardless of simulation_days → annual standing
        expected_annual_standing = 60.0 * 365 / 100.0
        assert b.standing_charge_gbp == pytest.approx(expected_annual_standing)

    def test_physics_path_literal_bill_values(self) -> None:
        """householder_bill(physics, 365d) output matches hand-computed literal £ values.

        Anchors key fields on independently verified numbers rather than
        re-deriving them from the same source expressions, so a regression in
        bill() arithmetic surfaces as a divergence from these literals.

        Inputs (all round numbers for pencil-and-paper verification):
          gen=4000, demand=3000, sc=2400, import=600 kWh, import_cost=£138
          standing=60 p/day, own_use=15 p/kWh, VAT=5%, retail=23 p/kWh
        """
        from solar_challenge.finance import householder_bill

        finance = _make_finance(
            standing_charge_pence_per_day=60.0,
            own_use_rate_pence_per_kwh=15.0,
            vat_rate=0.05,
            retail_baseline_rate_pence_per_kwh=23.0,
        )
        summary = _make_summary(
            simulation_days=365,
            total_generation_kwh=4000.0,
            total_demand_kwh=3000.0,
            total_self_consumption_kwh=2400.0,
            total_grid_import_kwh=600.0,
            total_grid_export_kwh=1600.0,
            total_import_cost_gbp=138.0,       # 600 kWh × 23 p/kWh
            total_export_revenue_gbp=0.0,
            net_cost_gbp=138.0,
            seg_revenue_gbp=0.0,
        )
        b = householder_bill(
            summary=summary,
            annual_self_consumption_kwh=summary.total_self_consumption_kwh,
            finance=finance,
            simulation_days=365,
        )
        # Hand-computed literals:
        #   standing      = 60 × 365 / 100         = £219.00
        #   own_use       = 15 × 2400 / 100         = £360.00
        #   import_cost   = 138.00 (physics)         = £138.00
        #   VAT           = 0.05 × (138+219+360)     = 0.05×717 = £35.85
        #   total_outlay  = 717 × 1.05               = £752.85
        #   baseline_import = 3000×23/100             = £690.00
        #   baseline_bill = (690+219) × 1.05 = 909×1.05 = £954.45
        #   eff_rate      = 690/3000×100              = 23.0 p/kWh (== retail)
        #   sc_saving     = 2400×(23−15)×1.05/100     = 2400×8×1.05/100 = £201.60
        #   saving_vs_baseline = 954.45 − 752.85      = £201.60
        #   sc_fraction   = 2400 / 4000               = 0.60
        assert b.standing_charge_gbp == pytest.approx(219.00)
        assert b.import_cost_gbp == pytest.approx(138.00)
        assert b.own_use_payment_gbp == pytest.approx(360.00)
        assert b.vat_gbp == pytest.approx(35.85)
        assert b.total_outlay_gbp == pytest.approx(752.85)
        assert b.baseline_bill_gbp == pytest.approx(954.45)
        assert b.self_consumption_saving_gbp == pytest.approx(201.60)
        assert b.saving_vs_baseline_gbp == pytest.approx(201.60)
        assert b.self_consumption_fraction == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# Step-1 (task 83): TestBillCore — period-native bill() core
# ---------------------------------------------------------------------------


class TestBillCore:
    """Fast (no-network) tests for the period-native bill() core function.

    RED until step-2 (bill() implemented in finance.py).
    """

    def test_30day_standing_charge(self) -> None:
        """bill() with period_days=30 produces period-proportional standing charge.

        Must NOT annualise to 365 days — that is the wrapper's responsibility.
        """
        from solar_challenge.finance import bill

        finance = _make_finance(standing_charge_pence_per_day=60.0)
        b = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=280.0,
            self_consumption_kwh=180.0,
            import_kwh=100.0,
            import_cost_gbp=23.0,
            baseline_import_cost_gbp=280.0 * 23.0 / 100.0,
            finance=finance,
        )
        expected_standing = 60.0 * 30 / 100.0  # = 18.0
        annual_standing = 60.0 * 365 / 100.0    # = 219.0  (must NOT be this)
        assert b.standing_charge_gbp == pytest.approx(expected_standing)
        assert b.standing_charge_gbp != pytest.approx(annual_standing)

    def test_period_native_identities(self) -> None:
        """bill() must satisfy all definitional BillBreakdown identities (CR3).

        With period_days=30, standing=18.0, import=23.0, own_use=27.0.
        """
        from solar_challenge.finance import bill

        own_use_rate = 15.0  # p/kWh
        vat_rate = 0.05
        finance = _make_finance(
            standing_charge_pence_per_day=60.0,
            own_use_rate_pence_per_kwh=own_use_rate,
            vat_rate=vat_rate,
            retail_baseline_rate_pence_per_kwh=23.0,
        )
        baseline_import_cost = 280.0 * 23.0 / 100.0  # = 64.4
        b = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=280.0,
            self_consumption_kwh=180.0,
            import_kwh=100.0,
            import_cost_gbp=23.0,
            baseline_import_cost_gbp=baseline_import_cost,
            finance=finance,
        )

        standing = 60.0 * 30 / 100.0    # 18.0
        own_use = own_use_rate * 180.0 / 100.0   # 27.0
        import_cost = 23.0

        # own_use_payment
        assert b.own_use_payment_gbp == pytest.approx(own_use)

        # vat
        expected_vat = vat_rate * (import_cost + standing + own_use)
        assert b.vat_gbp == pytest.approx(expected_vat)

        # total_outlay
        expected_outlay = (import_cost + standing + own_use) * (1.0 + vat_rate)
        assert b.total_outlay_gbp == pytest.approx(expected_outlay)

        # baseline_bill
        expected_baseline = (baseline_import_cost + standing) * (1.0 + vat_rate)
        assert b.baseline_bill_gbp == pytest.approx(expected_baseline)

        # eff_rate = baseline_import_cost / demand * 100
        eff_rate = baseline_import_cost / 280.0 * 100.0  # = 23.0 here
        expected_sc_saving = 180.0 * (eff_rate - own_use_rate) * (1.0 + vat_rate) / 100.0
        assert b.self_consumption_saving_gbp == pytest.approx(expected_sc_saving)

        # saving_vs_baseline
        assert b.saving_vs_baseline_gbp == pytest.approx(
            b.baseline_bill_gbp - b.total_outlay_gbp
        )

        # saving_pct
        expected_pct = (b.saving_vs_baseline_gbp / b.baseline_bill_gbp) * 100.0
        assert b.saving_pct == pytest.approx(expected_pct)

        # self_consumption_fraction
        assert b.self_consumption_fraction == pytest.approx(180.0 / 300.0)

    def test_caller_priced_import(self) -> None:
        """import_cost_gbp is passed verbatim to the bill — no internal re-pricing.

        An arbitrary import_cost_gbp=99.99 (unrelated to import_kwh) must appear
        in the output unmodified and flow through to vat and total_outlay.
        """
        from solar_challenge.finance import bill

        finance = _make_finance()
        b = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=280.0,
            self_consumption_kwh=180.0,
            import_kwh=100.0,
            import_cost_gbp=99.99,   # arbitrary, unrelated to import_kwh
            baseline_import_cost_gbp=280.0 * 23.0 / 100.0,
            finance=finance,
        )
        assert b.import_cost_gbp == 99.99
        # Flows into total_outlay
        standing = finance.standing_charge_pence_per_day * 30 / 100.0
        own_use = finance.own_use_rate_pence_per_kwh * 180.0 / 100.0
        expected_outlay = (99.99 + standing + own_use) * (1.0 + finance.vat_rate)
        assert b.total_outlay_gbp == pytest.approx(expected_outlay)

    def test_eff_rate_is_tou_consistent(self) -> None:
        """self_consumption_saving uses eff_rate derived from baseline_import_cost,
        not the configured retail rate.

        baseline_import_cost = 280 * 30/100 = 84.0 → eff_rate = 30 p/kWh
        finance.retail = 23 p/kWh
        saving must use eff_rate=30, NOT retail=23.
        """
        from solar_challenge.finance import bill

        finance = _make_finance(
            retail_baseline_rate_pence_per_kwh=23.0,
            own_use_rate_pence_per_kwh=15.0,
        )
        # baseline implies avg rate of 30 p/kWh (not 23 p retail)
        baseline_import_cost = 280.0 * 30.0 / 100.0   # = 84.0

        b = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=280.0,
            self_consumption_kwh=180.0,
            import_kwh=100.0,
            import_cost_gbp=23.0,
            baseline_import_cost_gbp=baseline_import_cost,
            finance=finance,
        )

        eff_rate = 30.0  # derived: 84.0 / 280.0 * 100
        expected_sc_saving = (
            180.0 * (eff_rate - finance.own_use_rate_pence_per_kwh)
            * (1.0 + finance.vat_rate) / 100.0
        )
        retail_sc_saving = (
            180.0 * (finance.retail_baseline_rate_pence_per_kwh - finance.own_use_rate_pence_per_kwh)
            * (1.0 + finance.vat_rate) / 100.0
        )
        assert b.self_consumption_saving_gbp == pytest.approx(expected_sc_saving)
        # must NOT use the configured retail rate
        assert b.self_consumption_saving_gbp != pytest.approx(retail_sc_saving)

    def test_demand_zero_falls_back_to_retail(self) -> None:
        """demand_kwh==0 must not raise ZeroDivisionError.

        (a) demand=0, sc=0: self_consumption_saving == 0.
        (b) demand=0, sc>0: eff_rate falls back to retail_baseline_rate.
        """
        from solar_challenge.finance import bill

        finance = _make_finance(
            retail_baseline_rate_pence_per_kwh=23.0,
            own_use_rate_pence_per_kwh=15.0,
        )

        # (a) demand=0, sc=0: no ZeroDivisionError, saving == 0
        b_zero = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=0.0,
            self_consumption_kwh=0.0,
            import_kwh=0.0,
            import_cost_gbp=0.0,
            baseline_import_cost_gbp=0.0,
            finance=finance,
        )
        assert b_zero.self_consumption_saving_gbp == pytest.approx(0.0)

        # (b) demand=0, sc>0: eff_rate == retail (fallback), saving uses retail
        sc_kwh = 180.0
        b_sc_only = bill(
            period_days=30,
            generation_kwh=300.0,
            demand_kwh=0.0,
            self_consumption_kwh=sc_kwh,
            import_kwh=0.0,
            import_cost_gbp=0.0,
            baseline_import_cost_gbp=0.0,
            finance=finance,
        )
        expected_sc_saving = (
            sc_kwh
            * (finance.retail_baseline_rate_pence_per_kwh - finance.own_use_rate_pence_per_kwh)
            * (1.0 + finance.vat_rate) / 100.0
        )
        assert b_sc_only.self_consumption_saving_gbp == pytest.approx(expected_sc_saving)


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
        # Householder-bill block headings must be present (CR3: outlay-based)
        assert "finance" in output or "bill" in output
        assert "outlay" in output or "import" in output
