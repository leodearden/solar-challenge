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
        ConfigurationError: :func:`~solar_challenge.number_fields.as_finite_real` refuses a figure;
            the message names it RunHeadline.<figure>. A pv_stored_share of None is not refused. A
            ConfigurationError is a ValueError.
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
            _read_figure(figure.name, value)


def _read_figure(name: str, value: object) -> float:
    """*value* as the float of RunHeadline's figure *name*, as as_finite_real reads it.

    Raises:
        ConfigurationError: :func:`~solar_challenge.number_fields.as_finite_real` refuses *value*;
            the message names RunHeadline.<name>.
    """
    return as_finite_real(value, f"RunHeadline.{name}")


def _share_of_generation(figure: str, kwh: float, generation_kwh: float) -> float:
    """RunHeadline's *figure*: *kwh*'s share of *generation_kwh*, or 0.0 when the generation is not positive, as calculate_summary's export_ratio is.

    Both are read as floats before they are divided, so the share is a float whatever kind of
    number a total is, a Fraction included.

    Raises:
        ConfigurationError: :func:`~solar_challenge.number_fields.as_finite_real` refuses
            *generation_kwh* or *kwh*, before anything is divided; the message names
            RunHeadline.generation_kwh or RunHeadline.<figure>.
    """
    generation = _read_figure("generation_kwh", generation_kwh)
    share_kwh = _read_figure(figure, kwh)
    return share_kwh / generation if generation > 0 else 0.0


def run_headline(summary: SummaryStatistics | FleetSummary) -> RunHeadline:
    """The headline of the run whose summary is *summary*, a home run's or a fleet run's.

    It is the one place the web maps a fleet summary's names, such as fleet_self_consumption_ratio,
    to a headline's (D-S19-8 in docs/prds/run-store-one-owner.md). It also derives the two figures
    a summary does not hold, each a share of the generation: a fleet's export ratio, its grid
    export's share, and a home's pv_stored_share, the share of the PV its battery stored, which
    total_pv_charge_kwh counts without the grid charge. A fleet's pv_stored_share is None.

    Raises:
        ConfigurationError: :func:`~solar_challenge.number_fields.as_finite_real` refuses a figure
            of the summary that the headline holds, or that a share is derived from; the message
            names the headline figure it is read for, RunHeadline.<figure>. A ConfigurationError is
            a ValueError.
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
