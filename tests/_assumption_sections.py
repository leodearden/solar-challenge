# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Builders of the finance report's input: one AssumptionSection per own-use basis, keyed by it.

``make_assumption_section`` puts its finance on the basis it is asked for with
``with_own_use_basis``, so a section's finance and its basis always agree, as
``finance run`` builds them.  ``sections_of`` keys sections by the basis their
own finance is on, the mapping ``generate_finance_report`` reads.

Usage::

    from tests._assumption_sections import make_assumption_section, sections_of

    report = generate_finance_report(sections_of(make_assumption_section(bill=dist)))
"""
from __future__ import annotations

from typing import Optional

from solar_challenge.board_report import AssumptionSection
from solar_challenge.finance import (
    BillDistribution,
    CostRecoverySolution,
    FinanceConfig,
    OwnUseBasis,
    own_use_basis,
    with_own_use_basis,
)
from solar_challenge.projection import FleetProjection, ProjectEconomics

from tests._factories import make_bill_distribution


def make_assumption_section(
    basis: OwnUseBasis = OwnUseBasis.SIMULATED,
    *,
    bill: Optional[BillDistribution] = None,
    override: Optional[float] = None,
    projection: Optional[FleetProjection] = None,
    economics: Optional[ProjectEconomics] = None,
    cost_recovery: Optional[CostRecoverySolution] = None,
) -> AssumptionSection:
    """One section on *basis*: its finance a 60 p/day standing charge with *override*, put on *basis*, and its bill *bill* or make_bill_distribution()'s."""
    finance = with_own_use_basis(
        FinanceConfig(standing_charge_pence_per_day=60.0, self_consumption_override=override), basis
    )
    return AssumptionSection(
        finance=finance,
        bill=bill if bill is not None else make_bill_distribution(),
        projection=projection,
        economics=economics,
        cost_recovery=cost_recovery,
    )


def sections_of(*sections: AssumptionSection) -> dict[OwnUseBasis, AssumptionSection]:
    """*sections* keyed by the basis each one's finance is on."""
    return {own_use_basis(section.finance): section for section in sections}
