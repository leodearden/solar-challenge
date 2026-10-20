# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Shared fixture factories for the finance and optimize result dataclasses.

Nine test modules used to spell out their own ``BillBreakdown`` literal, so
every field added to the dataclass cost nine mechanical edits and a tenth
fabricator could silently disagree with the other nine.  This module is the
single place the fixture shape lives; call sites pass only the fields their
assertions actually care about.

``make_bill_breakdown`` *derives* the CBS-collectable pair from the own-use
payment rather than accepting it, so a fixture that violates
``BillBreakdown``'s ``cbs_amount_due_gbp == own_use_payment_gbp +
own_use_vat_gbp`` invariant is unconstructible here.
``make_cost_recovery_solution`` and ``make_config_result`` likewise read each
field their dataclass mirrors from the value it mirrors.

Usage::

    from tests._factories import make_bill_breakdown, make_bill_distribution, make_config_result

    rep = make_bill_breakdown(total_outlay_gbp=420.0)
    dist = make_bill_distribution(representative=rep, max_gbp=420.0)
    best = make_config_result(representative_outlay_gbp=300.0, binding="floor")

"""
from __future__ import annotations

from typing import Optional

from solar_challenge.finance import BillBreakdown, BillDistribution, CostRecoverySolution
from solar_challenge.optimize import ConfigPoint, ConfigResult

DEFAULT_VAT_RATE = 0.05
"""VAT rate the default line items are internally consistent with."""


def make_bill_breakdown(
    *,
    standing_charge_gbp: float = 100.0,
    import_cost_gbp: float = 200.0,
    own_use_payment_gbp: float = 50.0,
    vat_gbp: float = 17.5,
    total_outlay_gbp: float = 367.5,
    self_consumption_saving_gbp: float = 30.0,
    baseline_bill_gbp: float = 500.0,
    saving_vs_baseline_gbp: float = 132.5,
    saving_pct: float = 26.5,
    self_consumption_fraction: float = 0.35,
    vat_rate: float = DEFAULT_VAT_RATE,
) -> BillBreakdown:
    """Build a synthetic BillBreakdown, deriving the CBS-collectable pair.

    ``own_use_vat_gbp`` and ``cbs_amount_due_gbp`` are computed from
    *own_use_payment_gbp* and *vat_rate* exactly as :func:`bill` computes them,
    so they can never drift out of step with the rest of the fixture.

    Args:
        vat_rate: Rate used to derive ``own_use_vat_gbp``.  Independent of
            *vat_gbp*, which is whole-outlay VAT and stays caller-supplied.
    """
    own_use_vat_gbp = vat_rate * own_use_payment_gbp
    return BillBreakdown(
        standing_charge_gbp=standing_charge_gbp,
        import_cost_gbp=import_cost_gbp,
        own_use_payment_gbp=own_use_payment_gbp,
        vat_gbp=vat_gbp,
        total_outlay_gbp=total_outlay_gbp,
        own_use_vat_gbp=own_use_vat_gbp,
        cbs_amount_due_gbp=own_use_payment_gbp + own_use_vat_gbp,
        self_consumption_saving_gbp=self_consumption_saving_gbp,
        baseline_bill_gbp=baseline_bill_gbp,
        saving_vs_baseline_gbp=saving_vs_baseline_gbp,
        saving_pct=saving_pct,
        self_consumption_fraction=self_consumption_fraction,
    )


def make_bill_distribution(
    *,
    representative: Optional[BillBreakdown] = None,
    per_home_net_bill_gbp: Optional[tuple[float, ...]] = None,
    min_gbp: float = 367.5,
    mean_gbp: float = 367.5,
    median_gbp: float = 367.5,
    max_gbp: float = 367.5,
) -> BillDistribution:
    """Build a synthetic BillDistribution around *representative*.

    Defaults to the single-home degenerate distribution: one home, every
    statistic equal to the representative's ``total_outlay_gbp``.
    """
    rep = representative if representative is not None else make_bill_breakdown()
    per_home = (
        per_home_net_bill_gbp
        if per_home_net_bill_gbp is not None
        else (rep.total_outlay_gbp,)
    )
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=per_home,
        min_gbp=min_gbp,
        mean_gbp=mean_gbp,
        median_gbp=median_gbp,
        max_gbp=max_gbp,
    )


def make_bill_distribution_from_statistics(
    *,
    representative_outlay_gbp: float,
    min_gbp: float,
    mean_gbp: float,
    median_gbp: float,
    max_gbp: float,
) -> BillDistribution:
    """Build a synthetic BillDistribution of these statistics around a representative home.

    The representative is make_bill_breakdown's, paying *representative_outlay_gbp*.
    """
    return make_bill_distribution(
        representative=make_bill_breakdown(total_outlay_gbp=representative_outlay_gbp),
        min_gbp=min_gbp,
        mean_gbp=mean_gbp,
        median_gbp=median_gbp,
        max_gbp=max_gbp,
    )


def _one_home_paying(total_outlay_gbp: float) -> BillDistribution:
    """The distribution of a single home whose total outlay is *total_outlay_gbp*."""
    return make_bill_distribution_from_statistics(
        representative_outlay_gbp=total_outlay_gbp,
        min_gbp=total_outlay_gbp,
        mean_gbp=total_outlay_gbp,
        median_gbp=total_outlay_gbp,
        max_gbp=total_outlay_gbp,
    )


def make_cost_recovery_solution(
    *,
    own_use_rate_pence_per_kwh: float = 15.0,
    outlay: Optional[BillDistribution] = None,
    representative_outlay_gbp: Optional[float] = None,
    net_surplus_per_home_per_year_gbp: float = 100.0,
    feasible: bool = True,
    binding: str = "floor",
) -> CostRecoverySolution:
    """Build a synthetic CostRecoverySolution, reading its mirrored fields from its outlay.

    The outlay is *outlay*, or else one home paying *representative_outlay_gbp*,
    or else ``make_bill_distribution()``.  ``representative_outlay_gbp``,
    ``saving_vs_baseline_gbp`` and ``saving_pct`` are its representative's.
    """
    if outlay is None:
        outlay = (
            make_bill_distribution()
            if representative_outlay_gbp is None
            else _one_home_paying(representative_outlay_gbp)
        )
    elif representative_outlay_gbp is not None:
        raise TypeError(
            "pass outlay or representative_outlay_gbp, not both; "
            f"got outlay={outlay!r} and representative_outlay_gbp={representative_outlay_gbp!r}"
        )
    representative = outlay.representative
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate_pence_per_kwh,
        outlay=outlay,
        representative_outlay_gbp=representative.total_outlay_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus_per_home_per_year_gbp,
        saving_vs_baseline_gbp=representative.saving_vs_baseline_gbp,
        saving_pct=representative.saving_pct,
        feasible=feasible,
        binding=binding,
    )


def make_config_result(
    *,
    pv_kwp: float = 4.0,
    battery_kwh: float = 6.0,
    inverter_kw: float = 3.6,
    solved_own_use_rate_pence_per_kwh: float = 15.0,
    outlay: Optional[BillDistribution] = None,
    representative_outlay_gbp: Optional[float] = None,
    surplus_at_solved_gbp: float = 100.0,
    feasible: bool = True,
    binding: str = "floor",
    total_capex_gbp: float = 10_000.0,
    min_dscr: float = 1.5,
    equity_irr: float = 0.08,
    payback_years: Optional[float] = 12.0,
    baseline_outlay_gbp: float = 450.0,
    baseline_surplus_per_home_gbp: float = 80.0,
) -> ConfigResult:
    """Build a synthetic ConfigResult, reading its five solved fields from its solution.

    The solution is make_cost_recovery_solution's for the solve arguments, so
    it takes *outlay* or *representative_outlay_gbp* as that builder does.
    ``representative_outlay_gbp``, ``solved_own_use_rate_pence_per_kwh``,
    ``surplus_at_solved_gbp``, ``feasible`` and ``binding`` are the solution's.
    """
    solution = make_cost_recovery_solution(
        own_use_rate_pence_per_kwh=solved_own_use_rate_pence_per_kwh,
        outlay=outlay,
        representative_outlay_gbp=representative_outlay_gbp,
        net_surplus_per_home_per_year_gbp=surplus_at_solved_gbp,
        feasible=feasible,
        binding=binding,
    )
    return ConfigResult(
        config=ConfigPoint(pv_kwp=pv_kwp, battery_kwh=battery_kwh, inverter_kw=inverter_kw),
        solution=solution,
        representative_outlay_gbp=solution.representative_outlay_gbp,
        solved_own_use_rate_pence_per_kwh=solution.own_use_rate_pence_per_kwh,
        surplus_at_solved_gbp=solution.net_surplus_per_home_per_year_gbp,
        feasible=solution.feasible,
        binding=solution.binding,
        total_capex_gbp=total_capex_gbp,
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        baseline_outlay_gbp=baseline_outlay_gbp,
        baseline_surplus_per_home_gbp=baseline_surplus_per_home_gbp,
    )
