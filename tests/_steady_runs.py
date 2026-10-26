# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home's simulation results at one row a minute over the calendar days a test chooses, every
series steady, for tests that need a run over exact dates, such as a window that crosses a
clock change.

The run covers whole Europe/London days, from the first day's midnight to the last day's 23:59.
Demand, the heat-pump load, the import cost and the export revenue are steady at the levels the
caller gives, and every other series is zero; there is no heat pump unless its load is given. A
test that chooses a run's totals over days from 1 January 2020 builds it with
tests._finance_builders.make_sim_results instead, and one that needs flows varying through each
day from 1 June 2024 with tests._sinusoidal_sim_results.make_sinusoidal_sim_results.

Usage::

    from tests._steady_runs import steady_run

    results = steady_run("2024-10-01", "2024-11-30")
    assert results.window.days == 61
    heated = steady_run("2024-06-01", "2024-06-01", demand_kw=4.0, heat_pump_kw=1.5)
"""

import pandas as pd

from solar_challenge.home import SimulationResults


def steady_run(
    first_day: str,
    last_day: str,
    *,
    demand_kw: float = 0.0,
    heat_pump_kw: float | None = None,
    import_cost_gbp: float = 0.0,
    export_revenue_gbp: float = 0.0,
) -> SimulationResults:
    """A run at one row a minute over whole Europe/London days, first_day's midnight to last_day's 23:59, every series steady.

    Demand, heat pump, import cost and export revenue are at the levels given,
    every other series is zero, and there is no heat pump unless heat_pump_kw is given.
    """
    index = pd.date_range(first_day, f"{last_day} 23:59", freq="min", tz="Europe/London")

    def steady(level: float) -> pd.Series:
        return pd.Series(level, index=index)

    return SimulationResults(
        generation=steady(0.0),
        demand=steady(demand_kw),
        self_consumption=steady(0.0),
        battery_charge=steady(0.0),
        battery_discharge=steady(0.0),
        battery_soc=steady(0.0),
        grid_import=steady(0.0),
        grid_export=steady(0.0),
        import_cost=steady(import_cost_gbp),
        export_revenue=steady(export_revenue_gbp),
        tariff_rate=steady(0.0),
        heat_pump_load=None if heat_pump_kw is None else steady(heat_pump_kw),
    )
