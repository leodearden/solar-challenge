# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed runs in the web dashboard's RunStorage as simulation jobs leave them.

A test seeds a stored run from results it built, without simulating. The helpers save
through the RunStorage methods a finished job saves through, save_home_run_from_results
and save_fleet_run_from_results, so a seeded run's summaries are derived where a job's are.
A save writes no status, so each helper then records the seeded run's status with
record_run_status, through the lifecycle methods its job's end would call:
mark_run_completed, or mark_run_failed. A test that creates a run through create_run, as a
job's submit does, records its status with record_run_status too.
A run given no name is named as a job given none names its run.

Usage::

    from tests._web_runs import record_run_status, store_fleet_run, store_home_run

    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1), name="North Roof")
    store_fleet_run(storage, "fleet-1", make_fleet_results(n_homes=2, days=1), name="Community Fleet")
    record_run_status(storage, "run-1", "failed")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from solar_challenge.web.stored_runs import RUN_KINDS

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults
    from solar_challenge.home import HomeConfig, SimulationResults
    from solar_challenge.web.storage import RunStatus, RunStorage


def store_fleet_run(
    storage: RunStorage,
    run_id: str,
    fleet_results: FleetResults,
    *,
    name: str | None = None,
    created_at: str | None = None,
) -> None:
    """Save *fleet_results* to *storage* as fleet run *run_id*, with the fleet and per-home summaries a finished fleet job saves, then complete it.

    The run is named *name*; None names it as a fleet job given no name creates its run, the
    fleet kind's default_name of its homes.
    """
    run_name = RUN_KINDS["fleet"].default_name(fleet_results.home_configs) if name is None else name
    storage.save_fleet_run_from_results(run_id, fleet_results, name=run_name, created_at=created_at)
    record_run_status(storage, run_id, "completed")


def store_home_run(
    storage: RunStorage,
    run_id: str,
    config: HomeConfig,
    results: SimulationResults,
    *,
    name: str | None = None,
    status: RunStatus = "completed",
    created_at: str | None = None,
) -> None:
    """Save *config*'s *results* to *storage* as home run *run_id*, with the summary a finished home job saves, then record *status* for it.

    The run is named *name*; None names it as a home job given no name creates its run, the
    home kind's default_name of *config*. The status is recorded as record_run_status records it.
    """
    run_name = RUN_KINDS["home"].default_name((config,)) if name is None else name
    storage.save_home_run_from_results(run_id, config, results, name=run_name, created_at=created_at)
    record_run_status(storage, run_id, status)


def record_run_status(storage: RunStorage, run_id: str, status: RunStatus) -> None:
    """Move run *run_id*, which is running, to *status* through *storage*'s lifecycle methods, as its job's end would.

    A new run is running, whether create_run or a save recorded it. A running run needs no
    move; mark_run_completed completes it, and mark_run_failed fails it with "the simulation
    failed", as a failed job's message.
    """
    match status:
        case "running":
            pass
        case "completed":
            storage.mark_run_completed(run_id)
        case "failed":
            storage.mark_run_failed(run_id, "the simulation failed")
        case _:
            assert_never(status)
