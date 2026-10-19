# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for tests/_factories.py's cost-recovery solution and config-result builders."""

from collections.abc import Callable

import pytest

from solar_challenge.optimize import ConfigPoint
from tests._factories import (
    make_bill_breakdown,
    make_bill_distribution,
    make_config_result,
    make_cost_recovery_solution,
)


def test_cost_recovery_solution_reads_its_representative_outlay_and_saving_from_its_outlay() -> None:
    outlay = make_bill_distribution(
        representative=make_bill_breakdown(total_outlay_gbp=350.0, saving_vs_baseline_gbp=90.0, saving_pct=18.0),
        per_home_net_bill_gbp=(300.0, 350.0, 400.0),
        min_gbp=300.0,
        mean_gbp=345.0,
        median_gbp=350.0,
        max_gbp=400.0,
    )

    solution = make_cost_recovery_solution(
        own_use_rate_pence_per_kwh=12.5,
        outlay=outlay,
        net_surplus_per_home_per_year_gbp=35.0,
        feasible=False,
        binding="infeasible_above_retail",
    )

    assert solution.outlay is outlay
    assert (
        solution.representative_outlay_gbp,
        solution.saving_vs_baseline_gbp,
        solution.saving_pct,
    ) == (350.0, 90.0, 18.0)
    assert (
        solution.own_use_rate_pence_per_kwh,
        solution.net_surplus_per_home_per_year_gbp,
        solution.feasible,
        solution.binding,
    ) == (12.5, 35.0, False, "infeasible_above_retail")


def test_cost_recovery_solution_without_an_outlay_is_one_home_paying_the_representative_outlay() -> None:
    outlay = make_cost_recovery_solution(representative_outlay_gbp=420.0).outlay

    assert outlay.representative == make_bill_breakdown(total_outlay_gbp=420.0)
    assert outlay.per_home_net_bill_gbp == (420.0,)
    assert (outlay.min_gbp, outlay.mean_gbp, outlay.median_gbp, outlay.max_gbp) == (420.0,) * 4


def test_cost_recovery_solution_defaults_to_make_bill_distributions_outlay() -> None:
    assert make_cost_recovery_solution().outlay == make_bill_distribution()


@pytest.mark.parametrize(
    "builder",
    [pytest.param(make_cost_recovery_solution, id="solution"), pytest.param(make_config_result, id="config-result")],
)
def test_builders_refuse_both_an_outlay_and_a_representative_outlay(builder: Callable[..., object]) -> None:
    with pytest.raises(TypeError, match="outlay or representative_outlay_gbp"):
        builder(outlay=make_bill_distribution(), representative_outlay_gbp=400.0)


def test_config_result_reads_its_solved_fields_from_its_solution() -> None:
    result = make_config_result(
        solved_own_use_rate_pence_per_kwh=12.5,
        representative_outlay_gbp=300.0,
        surplus_at_solved_gbp=35.0,
        feasible=False,
        binding="infeasible_above_retail",
    )

    assert result.solution == make_cost_recovery_solution(
        own_use_rate_pence_per_kwh=12.5,
        representative_outlay_gbp=300.0,
        net_surplus_per_home_per_year_gbp=35.0,
        feasible=False,
        binding="infeasible_above_retail",
    )
    assert (
        result.representative_outlay_gbp,
        result.solved_own_use_rate_pence_per_kwh,
        result.surplus_at_solved_gbp,
        result.feasible,
        result.binding,
    ) == (300.0, 12.5, 35.0, False, "infeasible_above_retail")


def test_config_result_over_a_given_outlay_ranks_by_its_representatives_outlay() -> None:
    outlay = make_bill_distribution(
        representative=make_bill_breakdown(total_outlay_gbp=350.0),
        per_home_net_bill_gbp=(300.0, 350.0, 400.0),
        min_gbp=300.0,
        mean_gbp=345.0,
        median_gbp=350.0,
        max_gbp=400.0,
    )

    result = make_config_result(outlay=outlay)

    assert result.solution.outlay is outlay
    assert result.representative_outlay_gbp == 350.0


def test_config_result_holds_the_given_install_and_baseline_economics() -> None:
    result = make_config_result(
        pv_kwp=5.0,
        battery_kwh=10.0,
        inverter_kw=4.6,
        total_capex_gbp=48_000.0,
        min_dscr=float("inf"),
        equity_irr=0.09,
        payback_years=None,
        baseline_outlay_gbp=375.0,
        baseline_surplus_per_home_gbp=40.0,
    )

    assert result.config == ConfigPoint(pv_kwp=5.0, battery_kwh=10.0, inverter_kw=4.6)
    assert (
        result.total_capex_gbp,
        result.min_dscr,
        result.equity_irr,
        result.payback_years,
        result.baseline_outlay_gbp,
        result.baseline_surplus_per_home_gbp,
    ) == (48_000.0, float("inf"), 0.09, None, 375.0, 40.0)
