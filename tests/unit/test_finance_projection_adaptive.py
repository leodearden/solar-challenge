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

from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.home import RunPricing
from solar_challenge.projection import MAX_NODES, project_multi_year
from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_period,
    make_scenario_and_finance,
)

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
        period=make_period(),
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


def _override_capped_at_demand(f: float) -> tuple[float, float, float]:
    """Self 2200 f, export 1800 f and import 3400 - 2200 f kWh: generation 4000 f against a constant demand of 3400.

    Under a 0.9 override, 0.9 x generation caps own-use at demand, so the ledger
    import is 0 until about age 4 at 1.5 %/yr.
    """
    return 2200.0 * f, 1800.0 * f, 3400.0 - 2200.0 * f


def _battery_covers_demand(f: float) -> tuple[float, float, float]:
    """Self min(3400, 3800 f), export 4400 f less that, import 3400 less that (kWh): demand stays 3400.

    The simulated import is 0 until about age 7 at 1.5 %/yr.
    """
    own_use = min(3400.0, 3800.0 * f)
    return own_use, 4400.0 * f - own_use, 3400.0 - own_use


def _declining_simulate(
    home_year: Callable[[float], tuple[float, float, float]],
    *,
    kept_each_year: float = 0.985,
) -> Callable:
    """Return a simulate whose homes' self-consumption, export and import kWh are *home_year* of f.

    f = kept_each_year ** age is the share of its new generation the aged PV
    gives, falling 1.5 %/yr compounding by default, as _aged_homes ages the PV.
    The flows are priced at a 30 p/kWh import tariff and a 4.1 p/kWh SEG rate.
    """

    def _simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        f = kept_each_year ** fleet_config.homes[0].pv_config.system_age_years
        self_kwh, export_kwh, import_kwh = home_year(f)
        return make_fleet_results(
            homes=fleet_config.homes,
            self_kwh=self_kwh,
            export_kwh=export_kwh,
            import_kwh=import_kwh,
            pricing=RunPricing(0.30, 4.1),
        )

    return _simulate


def _finance_over_25_years(self_consumption_override: float | None) -> tuple[ScenarioConfig, FinanceConfig]:
    """make_scenario_and_finance's one home over a 25-year asset life (seeds 0, 12, 24), at *self_consumption_override*."""
    scenario, finance = make_scenario_and_finance(asset_life_years=25)
    return scenario, dataclasses.replace(finance, self_consumption_override=self_consumption_override)


class TestTheDeviationScaleSeesAZeroAtAgeZero:
    """An export or import that is 0 at age 0 and grows with age is measured against the age-0 fleet generation or demand.

    So its interpolation error stays a finite percentage.
    """

    @pytest.mark.parametrize(
        ("home_year", "self_consumption_override"),
        [
            pytest.param(_override_capped_at_demand, 0.9, id="override-capped-at-demand"),
            pytest.param(_battery_covers_demand, None, id="simulated-basis-battery-covers-demand"),
        ],
    )
    def test_a_fleet_that_imports_nothing_at_age_zero_converges_below_max_nodes(
        self,
        home_year: Callable[[float], tuple[float, float, float]],
        self_consumption_override: float | None,
    ) -> None:
        """The default 1 % target is met with fewer than MAX_NODES ages, and no MAX_NODES warning."""
        scenario, finance = _finance_over_25_years(self_consumption_override)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            curve = project_multi_year(scenario, finance, simulate=_declining_simulate(home_year))
        assert len(curve.sampled_ages) < MAX_NODES, curve.sampled_ages
        assert curve.interp_error_estimate <= 1.0

    def test_an_override_fleet_whose_curves_interpolate_within_target_from_the_seeds_simulates_only_the_seeds(
        self,
    ) -> None:
        """Each reported curve's PCHIP midpoint error from the seeds alone is under 1 % of its scale.

        So no bisection age is simulated, as at base.
        """
        scenario, finance = _finance_over_25_years(0.9)
        curve = project_multi_year(
            scenario,
            finance,
            simulate=_declining_simulate(_override_capped_at_demand, kept_each_year=0.997),
        )
        assert curve.sampled_ages == (0, 12, 24)
        assert curve.interp_error_estimate <= 1.0
