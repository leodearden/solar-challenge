# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleets simulated over clear June days seeded as Bristol's TMY, each equal fleet and day count once per memo.

A module's tests share one memo through a module-scoped fixture. The first test that
asks for a fleet over some days simulates it, from the TMY that test seeded; every
later test that asks for an equal fleet over as many days gets that same result, which
it must only read.

Usage::

    from tests._computed_once import ComputedOnce
    from tests._june_fleet_runs import june_fleet_runs
    from tests._seeded_tmy import ClearJuneDays

    _JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=3)

    @pytest.fixture(scope="module")
    def june_fleet_run() -> ComputedOnce[FleetResults]:
        return june_fleet_runs(_JUNE_DAYS)

    def test_fleet_summary(june_fleet_run, fleet_config):  # a test that seeds _JUNE_DAYS
        results = june_fleet_run(fleet_config, 2)
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from solar_challenge.fleet import FleetConfig, FleetResults, default_runner
from tests._computed_once import ComputedOnce
from tests._seeded_tmy import ClearJuneDays


def june_fleet_runs(june_days: ClearJuneDays) -> ComputedOnce[FleetResults]:
    """A memo of fleets simulated over the first days of *june_days*: call it with a FleetConfig and a day count."""
    return ComputedOnce(partial(_simulate_over_first_days, june_days))


def _simulate_over_first_days(june_days: ClearJuneDays, config: FleetConfig, days: int) -> FleetResults:
    """*config*'s fleet simulated in this process over the first *days* of *june_days*, with every minute's energy balance validated, by the default runner run in turn."""
    start, end = june_days.window(days)
    return replace(default_runner(), parallel=False).simulate(config, start, end)
