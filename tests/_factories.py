# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Shared fixture factories for the finance result dataclasses.

Nine test modules used to spell out their own ``BillBreakdown`` literal, so
every field added to the dataclass cost nine mechanical edits and a tenth
fabricator could silently disagree with the other nine.  This module is the
single place the fixture shape lives; call sites pass only the fields their
assertions actually care about.

``make_bill_breakdown`` *derives* the CBS-collectable pair from the own-use
payment rather than accepting it, so a fixture that violates
``BillBreakdown``'s ``cbs_amount_due_gbp == own_use_payment_gbp +
own_use_vat_gbp`` invariant is unconstructible here.

Usage::

    from tests._factories import make_bill_breakdown, make_bill_distribution

    rep = make_bill_breakdown(total_outlay_gbp=420.0)
    dist = make_bill_distribution(representative=rep, max_gbp=420.0)

"""
from __future__ import annotations

from typing import Optional

from solar_challenge.finance import BillBreakdown, BillDistribution

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
