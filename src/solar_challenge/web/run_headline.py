# SPDX-License-Identifier: AGPL-3.0-or-later
"""The figures the web shows for a run of either kind, RunHeadline, read from its summary by run_headline.

run_headline is the one place the web maps a fleet summary's names (D-S19-8 in
docs/prds/run-store-one-owner.md). This module imports no web module, so the run store,
web/storage.py, and the charts, web/charts.py, both import it from below.
"""

from dataclasses import dataclass, field, fields
from typing import assert_never

from solar_challenge.fleet import FleetSummary
from solar_challenge.home import SummaryStatistics
from solar_challenge.number_fields import as_finite_real


_MAY_BE_NONE = "may_be_none"


@dataclass(frozen=True)
class RunHeadline:
    """The figures the web shows for a run of either kind: its five energy totals, its self-consumption, grid dependency and export ratios, and the share of its generation the battery stored from PV.

    The run lists show its generation and self-consumption ratio, and the comparison every
    figure. pv_stored_share is None for a fleet run, as FleetSummary carries no battery totals.

    Raises:
        ConfigurationError: A figure is not a finite number a float can hold, e.g. None, a text,
            a bool, NaN, an infinity or an int too large for a float; the message names the figure
            and its value. A pv_stored_share of None is not refused. It is a ValueError.
    """

    generation_kwh: float
    demand_kwh: float
    self_consumption_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    self_consumption_ratio: float
    grid_dependency_ratio: float
    export_ratio: float
    pv_stored_share: float | None = field(metadata={_MAY_BE_NONE: True})

    def __post_init__(self) -> None:
        for figure in fields(self):
            value = getattr(self, figure.name)
            if value is None and figure.metadata.get(_MAY_BE_NONE, False):
                continue
            as_finite_real(value, f"RunHeadline.{figure.name}")


def _share_of_generation(figure: str, kwh: float, generation_kwh: float) -> float:
    """RunHeadline's *figure*: *kwh*'s share of *generation_kwh*, or 0.0 when the generation is not positive, as calculate_summary's export_ratio is.

    Raises:
        ConfigurationError: *generation_kwh* or *kwh* is not a finite number a float can hold,
            as as_finite_real refuses it, naming generation_kwh or *figure*, before anything is
            divided.
    """
    as_finite_real(generation_kwh, "RunHeadline.generation_kwh")
    as_finite_real(kwh, f"RunHeadline.{figure}")
    return kwh / generation_kwh if generation_kwh > 0 else 0.0


def run_headline(summary: SummaryStatistics | FleetSummary) -> RunHeadline:
    """The headline of the run whose summary is *summary*, a home run's or a fleet run's.

    It is the one place the web maps a fleet summary's names, such as fleet_self_consumption_ratio,
    to a headline's (D-S19-8 in docs/prds/run-store-one-owner.md). It also derives the two figures
    a summary does not hold, each a share of the generation: a fleet's export ratio, its grid
    export's share, and a home's pv_stored_share, the share of the PV its battery stored, which
    total_pv_charge_kwh counts without the grid charge. A fleet's pv_stored_share is None.

    Raises:
        ConfigurationError: A figure of the summary that the headline holds, or that a share is
            derived from, is not a finite number a float can hold, e.g. None, a text, a bool, NaN,
            an infinity or an int too large for a float, as RunHeadline refuses it. It is a
            ValueError.
    """
    match summary:
        case SummaryStatistics():
            return RunHeadline(
                generation_kwh=summary.total_generation_kwh,
                demand_kwh=summary.total_demand_kwh,
                self_consumption_kwh=summary.total_self_consumption_kwh,
                grid_import_kwh=summary.total_grid_import_kwh,
                grid_export_kwh=summary.total_grid_export_kwh,
                self_consumption_ratio=summary.self_consumption_ratio,
                grid_dependency_ratio=summary.grid_dependency_ratio,
                export_ratio=summary.export_ratio,
                pv_stored_share=_share_of_generation(
                    "pv_stored_share", summary.total_pv_charge_kwh, summary.total_generation_kwh
                ),
            )
        case FleetSummary():
            return RunHeadline(
                generation_kwh=summary.total_generation_kwh,
                demand_kwh=summary.total_demand_kwh,
                self_consumption_kwh=summary.total_self_consumption_kwh,
                grid_import_kwh=summary.total_grid_import_kwh,
                grid_export_kwh=summary.total_grid_export_kwh,
                self_consumption_ratio=summary.fleet_self_consumption_ratio,
                grid_dependency_ratio=summary.fleet_grid_dependency_ratio,
                export_ratio=_share_of_generation(
                    "export_ratio", summary.total_grid_export_kwh, summary.total_generation_kwh
                ),
                pv_stored_share=None,
            )
        case _:
            assert_never(summary)
