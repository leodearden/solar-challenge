# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit property-tests for rank / feasible_split / pareto_baseline / cheapest_feasible.

All tests run over synthetic ConfigResult sets — no simulation, no PVGIS.
"""
from __future__ import annotations

import random
from typing import Optional

import pytest

from solar_challenge.optimize import rank


# ---------------------------------------------------------------------------
# Synthetic builders (adapted from tests/integration/test_optimize_sweep.py)
# ---------------------------------------------------------------------------


def _make_cost_recovery_solution(
    own_use_rate: float = 15.0,
    feasible: bool = True,
    binding: str = "floor",
    outlay_gbp: float = 400.0,
    surplus: float = 100.0,
) -> object:
    from solar_challenge.finance import BillBreakdown, BillDistribution, CostRecoverySolution

    rep = BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=outlay_gbp,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=100.0,
        saving_pct=20.0,
        self_consumption_fraction=0.35,
    )
    dist = BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(outlay_gbp,),
        min_gbp=outlay_gbp,
        mean_gbp=outlay_gbp,
        median_gbp=outlay_gbp,
        max_gbp=outlay_gbp,
    )
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate,
        outlay=dist,
        representative_outlay_gbp=outlay_gbp,
        net_surplus_per_home_per_year_gbp=surplus,
        saving_vs_baseline_gbp=100.0,
        saving_pct=20.0,
        feasible=feasible,
        binding=binding,
    )


def _make_config_result(
    pv_kwp: float = 4.0,
    battery_kwh: float = 6.0,
    inverter_kw: float = 3.6,
    feasible: bool = True,
    binding: str = "floor",
    representative_outlay_gbp: float = 400.0,
    solved_own_use_rate_pence_per_kwh: float = 15.0,
    surplus_at_solved_gbp: float = 100.0,
    total_capex_gbp: float = 10000.0,
    min_dscr: float = 1.5,
    equity_irr: float = 0.08,
    payback_years: Optional[float] = 12.0,
    baseline_outlay_gbp: float = 450.0,
    baseline_surplus_per_home_gbp: float = 80.0,
) -> object:
    from solar_challenge.optimize import ConfigPoint, ConfigResult

    config = ConfigPoint(pv_kwp=pv_kwp, battery_kwh=battery_kwh, inverter_kw=inverter_kw)
    solution = _make_cost_recovery_solution(
        own_use_rate=solved_own_use_rate_pence_per_kwh,
        feasible=feasible,
        binding=binding,
        outlay_gbp=representative_outlay_gbp,
        surplus=surplus_at_solved_gbp,
    )
    return ConfigResult(
        config=config,
        solution=solution,
        representative_outlay_gbp=representative_outlay_gbp,
        solved_own_use_rate_pence_per_kwh=solved_own_use_rate_pence_per_kwh,
        surplus_at_solved_gbp=surplus_at_solved_gbp,
        feasible=feasible,
        binding=binding,
        total_capex_gbp=total_capex_gbp,
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        baseline_outlay_gbp=baseline_outlay_gbp,
        baseline_surplus_per_home_gbp=baseline_surplus_per_home_gbp,
    )


# ---------------------------------------------------------------------------
# TestRank — pure sort helper
# ---------------------------------------------------------------------------


class TestRank:
    """rank() pure stable sort over ConfigResult sequences."""

    def test_primary_ascending_by_outlay(self) -> None:
        """Primary sort: representative_outlay_gbp ascending."""
        high = _make_config_result(representative_outlay_gbp=500.0, pv_kwp=4.0)
        mid = _make_config_result(representative_outlay_gbp=400.0, pv_kwp=5.0)
        low = _make_config_result(representative_outlay_gbp=300.0, pv_kwp=6.0)

        result = rank([high, mid, low])
        assert [r.representative_outlay_gbp for r in result] == [300.0, 400.0, 500.0]

    def test_tiebreak_surplus_descending(self) -> None:
        """Level-2 tie-break: surplus_at_solved_gbp descending."""
        a = _make_config_result(representative_outlay_gbp=400.0, surplus_at_solved_gbp=200.0)
        b = _make_config_result(representative_outlay_gbp=400.0, surplus_at_solved_gbp=50.0)

        result = rank([b, a])
        assert result[0].surplus_at_solved_gbp == 200.0
        assert result[1].surplus_at_solved_gbp == 50.0

    def test_tiebreak_pv_kwp_ascending(self) -> None:
        """Level-3 tie-break: config.pv_kwp ascending."""
        a = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0, pv_kwp=6.0
        )
        b = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0, pv_kwp=4.0
        )

        result = rank([a, b])
        assert result[0].config.pv_kwp == 4.0
        assert result[1].config.pv_kwp == 6.0

    def test_tiebreak_battery_kwh_ascending(self) -> None:
        """Level-4 tie-break: config.battery_kwh ascending."""
        a = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0,
            pv_kwp=4.0, battery_kwh=10.0,
        )
        b = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0,
            pv_kwp=4.0, battery_kwh=6.0,
        )

        result = rank([a, b])
        assert result[0].config.battery_kwh == 6.0
        assert result[1].config.battery_kwh == 10.0

    def test_tiebreak_inverter_kw_ascending(self) -> None:
        """Level-5 tie-break: config.inverter_kw ascending."""
        a = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0,
            pv_kwp=4.0, battery_kwh=6.0, inverter_kw=5.0,
        )
        b = _make_config_result(
            representative_outlay_gbp=400.0, surplus_at_solved_gbp=100.0,
            pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6,
        )

        result = rank([a, b])
        assert result[0].config.inverter_kw == 3.6
        assert result[1].config.inverter_kw == 5.0

    def test_determinism_stable_sort(self) -> None:
        """Shuffled inputs produce identical sorted outputs on repeated calls."""
        items = [
            _make_config_result(representative_outlay_gbp=float(i * 100), pv_kwp=float(i + 1))
            for i in range(10)
        ]
        shuffled_a = items[:]
        random.shuffle(shuffled_a)
        shuffled_b = items[:]
        random.shuffle(shuffled_b)

        result_a = rank(shuffled_a)
        result_b = rank(shuffled_b)
        assert result_a == result_b

    def test_rank_does_not_filter(self) -> None:
        """rank() is a pure sort — infeasible-binding records appear in the output."""
        feasible_rec = _make_config_result(
            representative_outlay_gbp=300.0, binding="floor", feasible=True
        )
        infeasible_rec = _make_config_result(
            representative_outlay_gbp=200.0,
            binding="infeasible_above_retail",
            feasible=False,
        )

        result = rank([feasible_rec, infeasible_rec])
        assert len(result) == 2
        assert result[0].representative_outlay_gbp == 200.0  # infeasible appears first (cheaper)
        assert result[0].binding == "infeasible_above_retail"
