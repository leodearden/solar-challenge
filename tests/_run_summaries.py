# SPDX-License-Identifier: AGPL-3.0-or-later
"""A run's summary with chosen figures, for tests that write runs rows themselves.

home_summary and fleet_summary are each a full summary of fixed round figures, with the
figures a test gives in place of those; summary_json is the runs row's summary_json text a
save writes for a summary: its field tree in JSON.

Usage::

    from tests._run_summaries import fleet_summary, home_summary, summary_json

    marker = home_summary(total_generation_kwh=987.65)
    conn.execute(
        "INSERT INTO runs (id, name, type, summary_json) VALUES (?, ?, ?, ?)",
        ("run-1", "Run 1", "home", summary_json(marker)),
    )
    fleet = fleet_summary(fleet_self_consumption_ratio=0.25)
"""

from __future__ import annotations

import dataclasses
import json

from solar_challenge.fleet import FleetSummary
from solar_challenge.home import SummaryStatistics

_HOME_SUMMARY = SummaryStatistics(
    total_generation_kwh=100.0,
    total_demand_kwh=80.0,
    total_self_consumption_kwh=60.0,
    total_grid_import_kwh=20.0,
    total_grid_export_kwh=40.0,
    total_battery_charge_kwh=10.0,
    total_battery_discharge_kwh=8.0,
    peak_generation_kw=3.5,
    peak_demand_kw=2.5,
    self_consumption_ratio=0.6,
    grid_dependency_ratio=0.25,
    export_ratio=0.4,
    simulation_days=7,
    total_import_cost_gbp=5.0,
    total_export_revenue_gbp=6.0,
    net_cost_gbp=-1.0,
)

_FLEET_SUMMARY = FleetSummary(
    n_homes=2,
    total_generation_kwh=200.0,
    total_demand_kwh=160.0,
    total_self_consumption_kwh=120.0,
    total_grid_import_kwh=40.0,
    total_grid_export_kwh=80.0,
    fleet_self_consumption_ratio=0.6,
    fleet_grid_dependency_ratio=0.25,
    per_home_generation_min_kwh=90.0,
    per_home_generation_max_kwh=110.0,
    per_home_generation_mean_kwh=100.0,
    per_home_generation_median_kwh=100.0,
    per_home_self_consumption_ratio_min=0.5,
    per_home_self_consumption_ratio_max=0.7,
    per_home_self_consumption_ratio_mean=0.6,
    simulation_days=7,
    total_net_cost_gbp=-2.0,
    total_import_cost_gbp=10.0,
    total_export_revenue_gbp=12.0,
)


def home_summary(**figures: object) -> SummaryStatistics:
    """A home run's full summary: 100 kWh generated, 60 of it self-consumed (ratio 0.6), over 7 days, with *figures* in place of those fields' figures."""
    return dataclasses.replace(_HOME_SUMMARY, **figures)  # type: ignore[arg-type]  # callers pass ill-typed figures on purpose, to write rows no save writes


def fleet_summary(**figures: object) -> FleetSummary:
    """A 2-home fleet run's full summary: 200 kWh generated, 120 of it self-consumed (ratio 0.6), over 7 days, with *figures* in place of those fields' figures."""
    return dataclasses.replace(_FLEET_SUMMARY, **figures)  # type: ignore[arg-type]  # callers pass ill-typed figures on purpose, to write rows no save writes


def summary_json(summary: SummaryStatistics | FleetSummary) -> str:
    """The summary_json text a save writes in a runs row for *summary*: its field tree in JSON."""
    return json.dumps(dataclasses.asdict(summary))
