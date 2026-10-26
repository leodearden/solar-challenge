# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's adaptive node refinement (H4).

Bisection adds sampled ages beyond the three seeds until the PCHIP error
estimate meets error_target_pct, capped at MAX_NODES.  The tests run on an
injected synthetic simulate.
"""
from __future__ import annotations

import dataclasses
import math
import warnings
from typing import TYPE_CHECKING, Callable

import pytest

from solar_challenge.config import ScenarioConfig, SimulationPeriod
from solar_challenge.finance import MAX_NODES, FinanceConfig, project_multi_year
from tests._finance_builders import make_fleet_results, make_home_config

if TYPE_CHECKING:
    import pandas as pd

    from solar_challenge.fleet import FleetConfig, FleetResults


def _make_curved_simulate(curvature: float = 0.35) -> Callable:
    """Return a synthetic simulate with strongly non-linear (exponential) decline.

    fleet_billed_own_use_kwh declines as base * exp(-curvature * age).
    With only 3 seed nodes, PCHIP will have large midpoint errors for high
    curvature values (the function is far from piecewise-cubic on wide intervals).
    """
    BASE_SC = 12_000.0
    BASE_EXP = 3_000.0

    def _simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        homes = fleet_config.homes
        mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
        factor = math.exp(-curvature * mean_age)
        return make_fleet_results(
            homes=homes,
            self_kwh=max(0.1, BASE_SC * factor),
            export_kwh=max(0.1, BASE_EXP * factor),
            import_kwh=500.0,
        )

    return _simulate


def _make_seg_income_simulate(seg_income_at_age_0_gbp: float) -> Callable:
    """Return a synthetic simulate whose homes earn SEG income seg_income_at_age_0_gbp × exp(-0.05 × age).

    Every home's energy is the same at every age, so revenue is the only metric
    that varies with age.
    """

    def _simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        homes = fleet_config.homes
        mean_age = sum(h.pv_config.system_age_years for h in homes) / len(homes)
        return make_fleet_results(
            homes=homes,
            self_kwh=100.0,
            export_kwh=800.0,
            import_kwh=300.0,
            export_revenue_gbp=seg_income_at_age_0_gbp * math.exp(-0.05 * mean_age),
        )

    return _simulate


def _make_adaptive_scenario(asset_life: int = 10) -> tuple:
    """Build a scenario+finance pair for adaptive refinement tests."""
    homes = [make_home_config()]
    finance = FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life,
        loan_term_years=min(asset_life, 15),
        retail_baseline_rate_pence_per_kwh=30.0,
        vat_rate=0.05,
    )
    scenario = ScenarioConfig(
        name="adaptive-test",
        period=SimulationPeriod(start_date="2020-01-01", end_date="2020-12-31"),
        description="Adaptive refinement test",
        homes=homes,
    )
    return scenario, finance


class TestProjectMultiYearAdaptive:
    """Adaptive node refinement tests (H4).

    Uses an injected simulate that returns an exponential decline, which has
    substantial PCHIP midpoint error when only 3 coarse seed nodes are used.
    The tests assert that adaptive bisection reduces that error.
    """

    _ASSET_LIFE = 10  # short life makes tests faster; {0, 5, 9} are the 3 seeds

    def test_adaptive_adds_nodes_beyond_seeds_with_tight_target(self) -> None:
        """With a curved simulate and tight error target, more than 3 nodes are sampled."""
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)  # steep exponential — large PCHIP error
        n_seeds = len({0, self._ASSET_LIFE // 2, self._ASSET_LIFE - 1})  # == 3

        # Very tight target → adaptive bisection must add nodes beyond the 3 seeds
        curve = project_multi_year(scenario, finance, error_target_pct=0.01, simulate=sim)
        assert len(curve.sampled_ages) > n_seeds, (
            f"Expected more than {n_seeds} sampled ages with tight 0.01% target; "
            f"got {len(curve.sampled_ages)}: {curve.sampled_ages}"
        )

    def test_tighter_target_yields_strictly_more_nodes(self) -> None:
        """A tighter error_target_pct produces strictly more sampled_ages than a loose target."""
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)

        # Loose target (50%): likely satisfied by the 3 seed nodes alone
        loose_curve = project_multi_year(scenario, finance, error_target_pct=50.0, simulate=sim)
        # Tight target (0.01%): requires many more nodes
        tight_curve = project_multi_year(scenario, finance, error_target_pct=0.01, simulate=sim)

        assert len(tight_curve.sampled_ages) > len(loose_curve.sampled_ages), (
            f"tight (0.01%) should yield more nodes than loose (50.0%): "
            f"tight={len(tight_curve.sampled_ages)}, loose={len(loose_curve.sampled_ages)}"
        )

    def test_sampled_ages_bounded_by_max_nodes(self) -> None:
        """sampled_ages count never exceeds MAX_NODES (safety invariant).

        An impossibly tight target causes the adaptive loop to run until capped.
        MAX_NODES is the hard bound.
        """
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.5)

        # Impossible target: will hit cap
        curve = project_multi_year(scenario, finance, error_target_pct=1e-9, simulate=sim)
        assert len(curve.sampled_ages) <= MAX_NODES, (
            f"sampled_ages count {len(curve.sampled_ages)} exceeds MAX_NODES {MAX_NODES}"
        )

    def test_interp_error_estimate_non_negative(self) -> None:
        """interp_error_estimate is always >= 0 (convergence invariant)."""
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.3)
        curve = project_multi_year(scenario, finance, error_target_pct=1.0, simulate=sim)
        assert curve.interp_error_estimate >= 0.0

    def test_interp_error_within_target_when_converged(self) -> None:
        """After convergence, interp_error_estimate <= error_target_pct.

        A loose enough target (50%) lets adaptive bisection converge quickly;
        the surfaced error estimate must be <= that target.
        """
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.3)
        curve = project_multi_year(scenario, finance, error_target_pct=50.0, simulate=sim)
        assert curve.interp_error_estimate <= 50.0, (
            f"interp_error_estimate {curve.interp_error_estimate:.4f} > target 50.0"
        )

    def test_a_negative_revenue_converges_as_its_positive_mirror_does(self) -> None:
        """Revenue error is a percentage of the age-0 revenue's magnitude, whatever its sign.

        Over a 25-year life, one fleet earns SEG income of £50 × exp(-0.05 × age)
        and its mirror loses that much; at an own-use rate of 0 p neither earns
        anything else, so their revenues differ only in sign.  A caller's simulate
        may report such a loss.  The losing fleet's projection samples the ages
        the earning fleet's does, with the same error estimate, within the default
        1 % target and without the MAX_NODES warning.
        """
        scenario, finance = _make_adaptive_scenario(asset_life=25)
        finance = dataclasses.replace(finance, own_use_rate_pence_per_kwh=0.0)

        earning = project_multi_year(scenario, finance, simulate=_make_seg_income_simulate(50.0))
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            losing = project_multi_year(scenario, finance, simulate=_make_seg_income_simulate(-50.0))

        assert losing.points[0].fleet_revenue_gbp == pytest.approx(-50.0), "premise: the fleet loses £50 at age 0"
        assert [str(w.message) for w in record if issubclass(w.category, UserWarning)] == []
        assert losing.sampled_ages == earning.sampled_ages
        assert losing.interp_error_estimate == pytest.approx(earning.interp_error_estimate)
        assert losing.interp_error_estimate <= 1.0

    def test_per_year_curves_monotone_after_adaptive(self) -> None:
        """Per-year curves remain monotone non-increasing after adaptive refinement."""
        scenario, finance = _make_adaptive_scenario(asset_life=self._ASSET_LIFE)
        sim = _make_curved_simulate(curvature=0.4)
        curve = project_multi_year(scenario, finance, error_target_pct=1.0, simulate=sim)
        for i in range(1, len(curve.points)):
            assert curve.points[i].fleet_billed_own_use_kwh <= (
                curve.points[i - 1].fleet_billed_own_use_kwh + 1e-6
            ), (
                f"fleet_billed_own_use_kwh not monotone at year {i}: "
                f"{curve.points[i].fleet_billed_own_use_kwh:.3f} > "
                f"{curve.points[i-1].fleet_billed_own_use_kwh:.3f}"
            )
