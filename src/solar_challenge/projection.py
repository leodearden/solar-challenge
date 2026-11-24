# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""The multi-year projection, project economics and cost-recovery solve of a
scenario's fleet, above finance's bill arithmetic.

Provides:
  - ``ScenarioFleet`` — frozen dataclass of the homes a scenario projects, its
    SEG filled, and the window to simulate them over.
  - ``scenario_fleet`` — the one resolution of a scenario to its ScenarioFleet.
  - ``YearPoint`` — frozen dataclass for one year in a multi-year projection.
  - ``MultiYearCurve`` — frozen dataclass for a full multi-year projection curve.
  - ``ProjectEconomics`` — frozen dataclass of project-level economics.
  - ``FleetProjection`` — frozen dataclass of a fleet's projection curve and
    its age-0 per-home summaries.
  - ``MAX_NODES`` — cap on the number of ages a projection interpolates through.
  - ``project_fleet`` — forward-march driver for adaptive PCHIP projection of a
    ScenarioFleet.
  - ``project_multi_year`` — ``project_fleet`` of a scenario's fleet, its curve.
  - ``project_economics`` — project-level financial appraisal of a curve.
  - ``spreadsheet_revenue_curve`` — analytic revenue curve from spreadsheet inputs.
  - ``solve_cost_recovery_rate`` — own-use rate that meets the retained-cash floor.

All monetary values are in GBP (£); energy in kWh.  The model behind these
functions is set out in ``docs/cost-recovery-finance-model.md``.
"""
from __future__ import annotations

import dataclasses
import functools
import itertools
import math
import warnings
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Iterator, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from solar_challenge.battery import BatteryConfig, compute_soh
from solar_challenge.config import ScenarioConfig
from solar_challenge.finance import (
    CostRecoverySolution,
    FinanceConfig,
    annualise,
    annuity_payment,
    bill_distribution,
    grid_services_model_of,
    home_ledger,
    irr,
    one_window,
    refuse_analysis_only_forecasts,
)
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.gridservices import GridServicesModel
from solar_challenge.home import HomeConfig, SummaryStatistics, calculate_summary
from solar_challenge.pv import calculate_degradation_factor, wired_dc_capacity_kw
from solar_challenge.timebase import SimulationWindow
from solar_challenge.whole_numbers import whole_number


@dataclass(frozen=True)
class ScenarioFleet:
    """The homes a scenario projects, its SEG filled, and the window to simulate them over.

    Attributes:
        homes: The homes, in the scenario's order; at least one.
        start: The window's first day's local midnight.
        end: The window's last day's local midnight, inclusive.
    """

    homes: tuple[HomeConfig, ...]
    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        """Raise ValueError, naming homes, when there are none."""
        if not self.homes:
            raise ValueError(f"ScenarioFleet projects at least one home: got homes={self.homes!r}")


def scenario_fleet(scenario: ScenarioConfig) -> ScenarioFleet:
    """The one resolution of a scenario: its simulated_homes(), SEG filled, over its simulation_bounds()."""
    start, end = scenario.simulation_bounds()
    return ScenarioFleet(homes=scenario.simulated_homes(), start=start, end=end)


# ---------------------------------------------------------------------------
# YearPoint — one year in a multi-year projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearPoint:
    """Energy and financial snapshot for one year in a multi-year projection.

    ``year`` is the age of the system in calendar years (0-based from
    installation).  SOH fractions are mean fleet values:
    ``pv_soh`` from :func:`pv.calculate_degradation_factor`; ``battery_soh``
    from :func:`battery.compute_soh` (1.0 when the fleet has no batteries).
    Every number must be finite.

    Energy fields and ``fleet_revenue_gbp`` share one basis, the window's
    year: :func:`project_multi_year` scales each home's window totals and its
    SEG income by the window's annualisation_scale (year_days / days), so
    £/kWh derivations from a :class:`YearPoint` are consistent.  A short
    window is still one season's sample, and its annual figures carry that
    season's bias.

    ``fleet_revenue_gbp`` is the CBS revenue:
    own-use revenue (own_use_rate × fleet_billed_own_use_kwh / 100)
    + the year's income: SEG export income (Σ each home's ledger
    ``seg_income_gbp``, :func:`~solar_challenge.finance.home_ledger`)
    + grid-services income (``grid_services_model_of(finance).annual_income_gbp``
    of the simulated fleet).  Between simulated ages the income follows PCHIP
    through the income at the simulated ages, which reads no own-use rate, so
    the revenue is affine in the rate in every year.
    """

    year: int
    """Calendar age of the system, a whole number of years (≥ 0).

    A whole-number float such as 2.0 is held as the int 2; a bool, Python's or
    numpy's, is refused.
    """

    pv_soh: float
    """Mean PV state-of-health across the fleet (fraction, 0–1)."""

    battery_soh: float
    """Mean battery state-of-health across the fleet (fraction, 0–1;
    1.0 when the fleet has no batteries)."""

    fleet_billed_own_use_kwh: float
    """Own-use the CBS bills the fleet at the own-use rate that year (kWh, ≥ 0)."""

    fleet_export_kwh: float
    """Total grid export from the fleet that year, Σ each home's ledger export: the simulated export, or generation − own-use with ``self_consumption_override`` set (kWh, ≥ 0)."""

    fleet_import_kwh: float
    """Total grid import by the fleet that year, Σ each home's ledger import: the simulated import, or demand − own-use with ``self_consumption_override`` set (kWh, ≥ 0)."""

    fleet_revenue_gbp: float
    """CBS revenue, own_use_rate × fleet_billed_own_use_kwh / 100 + the year's SEG and grid-services income (£); finite, and may have any sign."""

    def __post_init__(self) -> None:
        whole_year = whole_number(self.year)
        if whole_year is None or whole_year < 0:
            raise ValueError(f"year must be a whole number >= 0, got {self.year!r}")
        object.__setattr__(self, "year", whole_year)
        if not (0.0 <= self.pv_soh <= 1.0):
            raise ValueError(
                f"pv_soh must be in [0, 1], got {self.pv_soh!r}"
            )
        if not (0.0 <= self.battery_soh <= 1.0):
            raise ValueError(
                f"battery_soh must be in [0, 1], got {self.battery_soh!r}"
            )
        fleet_energies_kwh = {
            "fleet_billed_own_use_kwh": self.fleet_billed_own_use_kwh,
            "fleet_export_kwh": self.fleet_export_kwh,
            "fleet_import_kwh": self.fleet_import_kwh,
        }
        for field_name, kwh in fleet_energies_kwh.items():
            if not 0.0 <= kwh < math.inf:
                raise ValueError(
                    f"{field_name} must be >= 0 and finite, got {kwh!r}"
                )
        if not -math.inf < self.fleet_revenue_gbp < math.inf:
            raise ValueError(
                f"fleet_revenue_gbp must be finite, got {self.fleet_revenue_gbp!r}"
            )


# ---------------------------------------------------------------------------
# MultiYearCurve — full projection curve
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiYearCurve:
    """Full multi-year projection curve for a fleet.

    ``points`` covers years 0 .. asset_life_years - 1 (one :class:`YearPoint`
    per year).  ``sampled_ages`` records the ages at which the driver actually
    ran simulations; the remaining years are filled by PCHIP interpolation.
    ``interp_error_estimate`` is the maximum interpolation deviation when the
    adaptive loop converged (or was capped at ``MAX_NODES``): own-use and
    income as a percentage of their largest magnitude at the seed ages, export
    and import as a percentage of the largest fleet generation and demand
    there.
    """

    points: tuple[YearPoint, ...]
    """Per-year snapshots (len == asset_life_years)."""

    sampled_ages: tuple[int, ...]
    """Ages at which full simulations were run (subset of 0..asset_life-1)."""

    interp_error_estimate: float
    """Max remaining PCHIP midpoint deviation (%, ≥ 0 and finite) across the four driven metrics,
    the fleet's own-use, export, import and income (SEG + grid services),
    convergence invariant of the adaptive loop: own-use and income as a
    percentage of their largest magnitude at the seed ages, export and import
    as a percentage of the largest fleet generation and demand there."""

    annualised_from: SimulationWindow | None
    """The window the projection's yearly figures were annualised from, the fleet's one window.

    None for an analytic curve whose yearly figures are yearly assumptions,
    annualised from no simulated window (:func:`spreadsheet_revenue_curve`).
    """

    fleet_pv_dc_kw: float
    """The PV DC the curve's generation came from (kWp, > 0 and finite), on which
    :func:`project_economics` prices the PV capex."""

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("points must be non-empty")
        if not self.sampled_ages:
            raise ValueError("sampled_ages must be non-empty")
        if not 0.0 <= self.interp_error_estimate < math.inf:
            raise ValueError(
                f"interp_error_estimate must be >= 0 and finite, "
                f"got {self.interp_error_estimate!r}"
            )
        if not 0.0 < self.fleet_pv_dc_kw < math.inf:
            raise ValueError(f"fleet_pv_dc_kw must be > 0 and finite, got {self.fleet_pv_dc_kw!r}")


@dataclass(frozen=True)
class FleetProjection:
    """A fleet's multi-year projection, and each home's summary of the fleet simulated at age 0."""

    curve: MultiYearCurve
    """The projection over the asset life."""

    age0_summaries: tuple[SummaryStatistics, ...]
    """Each home's summary of its simulated window at age 0, in fleet order."""


# ---------------------------------------------------------------------------
# ProjectEconomics — project-level economics result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectEconomics:
    """Project-level financial appraisal results for a community PV/battery fleet.

    Produced by :func:`project_economics` from a :class:`MultiYearCurve` and a
    :class:`~solar_challenge.finance.FinanceConfig`.  All monetary values are in
    nominal GBP (£).

    Attributes:
        total_capex_gbp: Total capital expenditure across the fleet (£).
            4-term build-up: Σ_home(pv_kwp × pv_cost + roof_fit
            + battery_kwh × battery_cost + eff_inv_kw × inverter_cost).
            Inverter term is zero when inverter_cost_per_kw_gbp == 0.0 (default).
        grant_gbp: Total grant received by the project (£, passthrough from
            FinanceConfig).
        equity_gbp: Equity portion of the financed amount (£):
            (capex − grant) × equity_fraction.
        debt_gbp: Debt portion of the financed amount (£):
            (capex − grant) × (1 − equity_fraction).
        annual_debt_service_gbp: Level annuity payment on debt over
            loan_term_years at loan_rate (£/year).
        per_year_surplus_gbp: Per-year fleet surplus (£), one entry per
            asset_life year (0-based).  surplus_y = revenue_y − fleet_opex
            − debt_service (y < loan_term) or revenue_y − fleet_opex
            (y ≥ loan_term).
        min_dscr: Minimum Debt Service Coverage Ratio over loan years only:
            min_y<loan_term ((revenue_y − fleet_opex) / annual_debt_service).
            float('inf') when annual_debt_service_gbp == 0.
        equity_irr: Internal rate of return on equity (fraction), computed via
            NPV bisection on cashflow [−equity, surplus_0 … surplus_{N-1}].
            float('nan') when equity_gbp == 0 or cashflow has no sign change.
        payback_years: First 1-based year where cumulative equity cashflow
            (−equity + Σ surplus) ≥ 0 (float), or None if never within the
            asset life.
        net_surplus_per_home_per_year_gbp: Mean per-year surplus divided by
            the number of homes (£/home/year).
        mean_fleet_surplus_per_year_gbp: Mean annual fleet surplus across the
            full asset life (£/year).  Equals mean(per_year_surplus_gbp).
    """

    total_capex_gbp: float
    """Total capital expenditure across the fleet (£)."""

    grant_gbp: float
    """Grant received by the project (£)."""

    equity_gbp: float
    """Equity portion of project financing (£)."""

    debt_gbp: float
    """Debt portion of project financing (£)."""

    annual_debt_service_gbp: float
    """Annual level annuity debt service payment (£/year)."""

    per_year_surplus_gbp: tuple[float, ...]
    """Per-year fleet surplus after opex and debt service (£), len == asset_life_years."""

    min_dscr: float
    """Minimum DSCR over loan years (float('inf') when debt-free)."""

    equity_irr: float
    """Equity IRR as a fraction (float('nan') when undefined)."""

    payback_years: Optional[float]
    """First year cumulative equity cashflow ≥ 0 (1-based), or None."""

    net_surplus_per_home_per_year_gbp: float
    """Mean per-year surplus per home (£/home/year)."""

    fleet_opex_gbp: float
    """Total fleet operating expenditure per year (£/year):
    opex_per_home_per_year_gbp × n_homes."""

    mean_fleet_surplus_per_year_gbp: float
    """Mean annual fleet surplus across the full asset life (£/year):
    mean(per_year_surplus_gbp).  Single source of truth used by the economics
    report; avoids recomputing the mean from the tuple at render time."""

    def __post_init__(self) -> None:
        if not self.per_year_surplus_gbp:
            raise ValueError(
                "per_year_surplus_gbp must be non-empty; got empty tuple"
            )
        if self.payback_years is not None and self.payback_years < 0.0:
            raise ValueError(
                f"payback_years must be None or ≥ 0, got {self.payback_years!r}"
            )


# ---------------------------------------------------------------------------
# Per-year interpolation — PCHIP
# ---------------------------------------------------------------------------


def _interpolate_per_year(
    sampled_ages: List[int],
    sampled_values: List[float],
    all_years: int,
) -> List[float]:
    """Interpolate sampled (age, value) pairs to every year in 0..all_years-1.

    Uses :class:`scipy.interpolate.PchipInterpolator`, the shape-preserving
    monotone cubic, which never overshoots the sampled values.

    The degenerate single-node case returns a constant for all years.

    Args:
        sampled_ages: Strictly ascending integer ages at which values are known.
        sampled_values: Corresponding values (same length as sampled_ages).
        all_years: Number of integer years (0 .. all_years-1) to interpolate.

    Returns:
        List of length ``all_years`` with one interpolated value per year.
    """
    if len(sampled_ages) == 0:
        raise ValueError("sampled_ages must be non-empty")
    if len(sampled_ages) == 1:
        return [sampled_values[0]] * all_years

    xs = np.array(sampled_ages, dtype=float)
    ys = np.array(sampled_values, dtype=float)
    pchip = PchipInterpolator(xs, ys, extrapolate=False)
    all_x = np.arange(all_years, dtype=float)
    vals = pchip(all_x)
    # Extrapolation outside the node range → clip to boundary values
    vals = np.where(np.isnan(vals), np.interp(all_x, xs, ys), vals)
    return [float(v) for v in vals]


# ---------------------------------------------------------------------------
# project_fleet — the adaptive forward-march projection
# ---------------------------------------------------------------------------

#: Maximum number of simulation nodes before the adaptive loop is capped.
MAX_NODES: int = 12


class _AggregateShape(Enum):
    """Whether a :class:`_NodeData` aggregate holds one value for the fleet or one per home, in fleet order."""

    FLEET = auto()
    PER_HOME = auto()


_AGGREGATE_SHAPE = "aggregate_shape"
_FLEET_AGGREGATE: Mapping[str, _AggregateShape] = {_AGGREGATE_SHAPE: _AggregateShape.FLEET}
_PER_HOME_AGGREGATE: Mapping[str, _AggregateShape] = {_AGGREGATE_SHAPE: _AggregateShape.PER_HOME}


@dataclass(frozen=True)
class _NodeData:
    """Aggregates from one simulated fleet age in the forward-march.

    Built once per simulated age by :func:`_simulate_node`.  Each float
    aggregate gives its :class:`_AggregateShape` in its field metadata, and
    construction refuses one that is NaN or infinite, naming the age and each
    such aggregate with its value.
    """

    age: int
    """System age in calendar years at which the fleet was simulated."""

    fleet_own_use_kwh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet billed own-use, Σ each home's :func:`~solar_challenge.finance.home_ledger` own-use (kWh/yr)."""

    fleet_export_kwh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet grid export, Σ each home's ledger export (kWh/yr)."""

    fleet_import_kwh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet grid import, Σ each home's ledger import (kWh/yr)."""

    fleet_generation_kwh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet generation, Σ each home's ledger generation (kWh/yr): the scale export's interpolation error is measured against."""

    fleet_demand_kwh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet demand, Σ each home's ledger demand (kWh/yr): the scale import's interpolation error is measured against."""

    per_home_discharge: tuple[float, ...] = dataclasses.field(metadata=_PER_HOME_AGGREGATE)
    """Per-home battery discharge, its window total × annualisation_scale (kWh/yr)."""

    mean_pv_soh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Mean PV state-of-health across the fleet (fraction, 0–1)."""

    mean_battery_soh: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Mean battery state-of-health across the fleet (fraction, 0–1)."""

    fleet_income_gbp: float = dataclasses.field(metadata=_FLEET_AGGREGATE)
    """Fleet income, Σ each home's ledger SEG income + the fleet's grid-services income (£/yr); it reads no own-use rate."""

    annualised_from: SimulationWindow
    """The fleet's one simulated window, the energy totals were annualised from."""

    per_home_throughput: tuple[float, ...] = dataclasses.field(metadata=_PER_HOME_AGGREGATE)
    """Per-home battery discharge (kWh) from installation to this age, the cumulative throughput :func:`battery.compute_soh` counts."""

    def __post_init__(self) -> None:
        """Refuse an aggregate that is NaN or infinite, naming the age and each such aggregate and its value."""
        refused = [f"{name}={value!r}" for name, value in self._aggregates() if not math.isfinite(value)]
        if refused:
            raise ValueError(
                f"every aggregate of the fleet simulated at age {self.age} must be finite: got {', '.join(refused)}"
            )

    def _aggregates(self) -> Iterator[tuple[str, float]]:
        """Each aggregate's name and value in field order, a per-home aggregate's value for home i as name[i]."""
        for attribute in dataclasses.fields(self):
            shape = attribute.metadata.get(_AGGREGATE_SHAPE)
            if shape is _AggregateShape.FLEET:
                yield attribute.name, getattr(self, attribute.name)
            elif shape is _AggregateShape.PER_HOME:
                for i, value in enumerate(getattr(self, attribute.name)):
                    yield f"{attribute.name}[{i}]", value


@dataclass(frozen=True)
class _SimulatedAge:
    """One simulated fleet age: its node, each home's summary, and the warnings pricing its grid services raised."""

    node: _NodeData

    summaries: tuple[SummaryStatistics, ...]
    """Each home's summary of its simulated window, in fleet order."""

    grid_services_warnings: tuple[warnings.WarningMessage, ...]
    """The warnings pricing this age's grid-services income raised, in the order raised."""


@dataclass(frozen=True)
class _DrivenMetric:
    """A node aggregate the adaptive bisection interpolates to the error target, and the quantity its deviation is a percentage of."""

    value: Callable[[_NodeData], float]
    scale_of: Callable[[_NodeData], float]


_OWN_USE = _DrivenMetric(value=lambda node: node.fleet_own_use_kwh, scale_of=lambda node: node.fleet_own_use_kwh)
_EXPORT = _DrivenMetric(value=lambda node: node.fleet_export_kwh, scale_of=lambda node: node.fleet_generation_kwh)
_IMPORT = _DrivenMetric(value=lambda node: node.fleet_import_kwh, scale_of=lambda node: node.fleet_demand_kwh)
_INCOME = _DrivenMetric(value=lambda node: node.fleet_income_gbp, scale_of=lambda node: node.fleet_income_gbp)

_DRIVEN_METRICS: tuple[_DrivenMetric, ...] = (_OWN_USE, _EXPORT, _IMPORT, _INCOME)
"""Every metric the bisection drives, none of which reads the own-use rate.  Export and import are measured against
the generation and demand they are parts of, so a flow that is 0 at age 0 still has a scale
(docs/cost-recovery-finance-model.md §4)."""


def _aged_homes(
    homes: Sequence[HomeConfig],
    age: int,
    cum_throughput: Optional[Sequence[float]] = None,
) -> list[HomeConfig]:
    """Return HomeConfig list with PV system_age_years and battery SOH set to ``age``.

    For each home the PV config's ``system_age_years`` is updated to ``age``.
    Each battery's SOH at that age comes from :func:`battery.compute_soh`,
    passed the home's discharged energy since installation (its
    ``cum_throughput`` entry, the throughput compute_soh counts; 0.0 when
    ``cum_throughput`` is omitted) and the battery's nominal usable capacity.
    It is injected into the battery config via
    ``dataclasses.replace(battery_config, soh=soh_i)`` so :class:`~solar_challenge.battery.Battery`
    uses it directly at construction time.

    Args:
        homes: Original fleet home configs.
        age: System age in calendar years.
        cum_throughput: Per-home battery discharge in kWh since installation,
            the throughput :func:`battery.compute_soh` counts (0.0 if no
            history yet or if the home has no battery).

    Returns:
        New list of HomeConfig with aged PV and (optionally) aged battery.
    """
    if cum_throughput is None:
        cum_throughput = [0.0] * len(homes)

    result = []
    for i, home in enumerate(homes):
        # Age the PV config
        new_pv = dataclasses.replace(home.pv_config, system_age_years=float(age))

        # Age the battery config (inject SOH via dataclasses.replace if present)
        new_bc = home.battery_config
        if new_bc is not None:
            soh_i = compute_soh(
                system_age_years=float(age),
                cumulative_throughput_kwh=cum_throughput[i],
                usable_capacity_kwh=new_bc.nominal_usable_capacity_kwh,
                params=new_bc,
            )
            new_bc = dataclasses.replace(new_bc, soh=soh_i)

        result.append(dataclasses.replace(home, pv_config=new_pv, battery_config=new_bc))
    return result


def _throughput_at(age: int, seeds: Mapping[int, _NodeData]) -> List[float]:
    """Each home's battery discharge (kWh) from installation to ``age``, the cumulative throughput :func:`battery.compute_soh` counts.

    Throughput accrues at the annual discharge simulated at the latest seed age
    at or below ``age``.  Every sampled age, seed or bisection trial, reads this
    one rule, so throughput is a continuous, non-decreasing function of age and
    the battery SOH :func:`battery.compute_soh` derives from it never rises.

    Args:
        age: System age in calendar years; ``seeds`` must hold an age at or below it.
        seeds: The seed-age nodes simulated so far, keyed by age.

    Returns:
        One cumulative battery discharge (kWh) per home, in fleet order.
    """
    base_age = max(seed_age for seed_age in seeds if seed_age <= age)
    base = seeds[base_age]
    years = age - base_age
    return [
        throughput + discharge * years
        for throughput, discharge in zip(base.per_home_throughput, base.per_home_discharge, strict=True)
    ]


def _installed_battery(home: HomeConfig) -> Optional[BatteryConfig]:
    """*home*'s battery with its state of health set aside, or None for a home without one."""
    return None if home.battery_config is None else dataclasses.replace(home.battery_config, soh=None)


def _refuse_results_without_the_fleets_batteries(
    fleet_config: FleetConfig, fleet_results: FleetResults
) -> None:
    """Raise ValueError unless *fleet_results*' home_configs carry the batteries of *fleet_config*'s homes, in order, state of health aside.

    Grid-services income is priced from the batteries of the home_configs that
    ``simulate`` returns, so they must be those of the homes it was asked to
    simulate, as :meth:`~solar_challenge.fleet.FleetRunner.simulate` returns
    them.  Each sampled age asks for its own state of health, which a simulate
    that ignores ageing does not echo, so it is set aside.

    Raises:
        ValueError: If the two hold different numbers of homes, naming the fleet
            and both numbers, or at the first home whose batteries differ,
            naming the fleet, the home and both batteries.
    """
    rule = (
        "grid-services income is priced from the batteries of the home_configs simulate "
        "returns, so simulate must return fleet_config.homes' batteries, state of health "
        "aside, as FleetRunner.simulate does"
    )
    asked = [_installed_battery(home) for home in fleet_config.homes]
    returned = [_installed_battery(home) for home in fleet_results.home_configs]
    if len(returned) != len(asked):
        raise ValueError(
            f"simulate returned {len(returned)} homes for fleet {fleet_config.name!r} "
            f"of {len(asked)} homes; {rule}"
        )
    for index, (asked_battery, returned_battery) in enumerate(zip(asked, returned, strict=True)):
        if returned_battery != asked_battery:
            raise ValueError(
                f"simulate returned home {index} of fleet {fleet_config.name!r} with battery "
                f"{returned_battery!r} where the fleet's home has {asked_battery!r}; {rule}"
            )


def _simulate_node(
    fleet: ScenarioFleet,
    age: int,
    throughput: Sequence[float],
    finance: FinanceConfig,
    grid_services: GridServicesModel,
    simulate: FleetSimulate,
) -> _SimulatedAge:
    """Simulate *fleet* at *age*, each battery having discharged its *throughput* entry since installation, and total its year.

    Each home's year is one ledger, the one householder_bill bills
    (docs/cost-recovery-finance-model.md §4); battery discharge, which ageing
    integrates, stays the simulated flow.  Grid-services income is priced from
    this age's own simulated fleet, and the warnings that pricing raises are
    returned, not shown.
    """
    aged = _aged_homes(fleet.homes, age, throughput)
    fleet_config = FleetConfig(homes=tuple(aged), name=f"proj-age-{age}")
    fleet_results = simulate(fleet_config, fleet.start, fleet.end)
    _refuse_results_without_the_fleets_batteries(fleet_config, fleet_results)

    summaries = tuple(calculate_summary(r) for r in fleet_results.per_home_results)
    physics_of_homes = [annualise(s) for s in summaries]
    ledgers = [home_ledger(physics, finance) for physics in physics_of_homes]

    # The fleet's income (model doc §4), every term over the window's year:
    #   seg_revenue   = Σ ledger seg_income_gbp, each home's ledger export at its run's SEG rate
    #   grid_services = grid_services.annual_income_gbp(fleet_results), already annual
    # Own-use revenue is the rate times the year's own-use, added per year by
    # _assembled_curve, so no node reads the rate.  Grid-charge energy is paid by
    # the householder inside grid import, not a CBS outgoing
    # (docs/cost-recovery-finance-model.md §4).
    seg_revenue = sum(ledger.seg_income_gbp for ledger in ledgers)
    with warnings.catch_warnings(record=True) as raised_by_grid_services:
        grid_services_income = grid_services.annual_income_gbp(fleet_results)

    pv_sohs = [calculate_degradation_factor(float(age), h.pv_config.degradation_rate_per_year) for h in fleet.homes]
    # Each simulated battery's SOH is the one _aged_homes gave it; 1.0 for a fleet without batteries.
    battery_sohs = [h.battery_config.resolved_soh for h in aged if h.battery_config is not None]

    node = _NodeData(
        age=age,
        fleet_own_use_kwh=sum(ledger.own_use_kwh for ledger in ledgers),
        fleet_export_kwh=sum(ledger.export_kwh for ledger in ledgers),
        fleet_import_kwh=sum(ledger.import_kwh for ledger in ledgers),
        fleet_generation_kwh=sum(ledger.generation_kwh for ledger in ledgers),
        fleet_demand_kwh=sum(ledger.demand_kwh for ledger in ledgers),
        per_home_discharge=tuple(physics.battery_discharge_kwh for physics in physics_of_homes),
        mean_pv_soh=sum(pv_sohs) / len(pv_sohs),
        mean_battery_soh=sum(battery_sohs) / len(battery_sohs) if battery_sohs else 1.0,
        fleet_income_gbp=seg_revenue + grid_services_income,
        annualised_from=one_window(summaries),
        per_home_throughput=tuple(throughput),
    )
    return _SimulatedAge(node=node, summaries=summaries, grid_services_warnings=tuple(raised_by_grid_services))


_SimulateAt = Callable[[int, Sequence[float]], _SimulatedAge]
"""One projection's :func:`_simulate_node`, given the age and each battery's throughput to it."""


def _nodes_of(simulated: Mapping[int, _SimulatedAge]) -> dict[int, _NodeData]:
    """The node of each simulated age, keyed by age."""
    return {age: simulated_age.node for age, simulated_age in simulated.items()}


def _simulated_seeds(simulate_at: _SimulateAt, n_homes: int, asset_life: int) -> dict[int, _SimulatedAge]:
    """The seed ages 0, asset_life // 2 and asset_life - 1 simulated ascending, each aged by :func:`_throughput_at` over the seeds before it."""
    simulated = {0: simulate_at(0, [0.0] * n_homes)}
    for age in sorted({asset_life // 2, asset_life - 1} - {0}):
        simulated[age] = simulate_at(age, _throughput_at(age, _nodes_of(simulated)))
    return simulated


def _per_year(nodes: Sequence[_NodeData], value: Callable[[_NodeData], float], years: int) -> list[float]:
    """*value* at each of *nodes*, ascending by age, interpolated to every year 0 .. years-1 by :func:`_interpolate_per_year`."""
    return _interpolate_per_year([node.age for node in nodes], [value(node) for node in nodes], years)


def _deviation_scales(seeds: Mapping[int, _NodeData]) -> tuple[float, ...]:
    """Each driven metric's deviation scale, in :data:`_DRIVEN_METRICS` order: the largest magnitude of its scale quantity at the seed ages, floored at 1e-9.

    The scales are fixed once the seeds are simulated, and need no sign, so a
    metric that is 0 at age 0 still has one.
    """
    return tuple(
        max([1e-9, *(abs(metric.scale_of(node)) for node in seeds.values())]) for metric in _DRIVEN_METRICS
    )


def _midpoint_deviation_pct(curves: Sequence[Sequence[float]], trial: _NodeData, scales: Sequence[float]) -> float:
    """The largest deviation (%) of the driven curves at *trial*'s age from its simulated values, each against its metric's scale."""
    return max(
        abs(curve[trial.age] - metric.value(trial)) / scale * 100.0
        for metric, curve, scale in zip(_DRIVEN_METRICS, curves, scales, strict=True)
    )


def _bisection_midpoints(ages: Sequence[int]) -> list[int]:
    """The midpoint of each pair of neighbouring *ages*, ascending, that are more than one year apart."""
    return [(younger + older) // 2 for younger, older in itertools.pairwise(ages) if older - younger > 1]


@dataclass(frozen=True)
class _NodeSelection:
    """The ages one projection simulated, those its curve interpolates through, and how close they came to the target."""

    simulated: Mapping[int, _SimulatedAge]
    """Every age simulated, the seeds first and then the trials in the order the bisection asked for them."""

    accepted_ages: tuple[int, ...]
    """The ages the curve interpolates through, ascending."""

    max_deviation_pct: float
    """The last pass's largest midpoint deviation (%), the curve's interp_error_estimate."""

    capped: bool
    """Whether the bisection stopped at MAX_NODES with a midpoint still above the error target."""


def _selected_nodes(
    seeds: Mapping[int, _SimulatedAge],
    simulate_at: _SimulateAt,
    asset_life: int,
    error_target_pct: float,
) -> _NodeSelection:
    """Bisect between the accepted ages until every midpoint is within *error_target_pct*, or MAX_NODES ages are accepted.

    Each pass interpolates the driven metrics through the accepted ages and
    simulates each midpoint not yet simulated.  It accepts, in age order, each
    midpoint whose deviation is above the target, stopping mid-pass at
    MAX_NODES.  Each age is simulated at most once: :func:`_throughput_at`
    reads only the seeds, so a trial's simulation depends on its age alone.
    """
    simulated = dict(seeds)
    seed_nodes = _nodes_of(seeds)
    scales = _deviation_scales(seed_nodes)
    accepted = sorted(seeds)
    while True:
        accepted_nodes = [simulated[age].node for age in accepted]
        curves = [_per_year(accepted_nodes, metric.value, asset_life) for metric in _DRIVEN_METRICS]
        deviations: dict[int, float] = {}
        for mid in _bisection_midpoints(accepted):
            if mid not in simulated:
                simulated[mid] = simulate_at(mid, _throughput_at(mid, seed_nodes))
            deviations[mid] = _midpoint_deviation_pct(curves, simulated[mid].node, scales)
        above_target = [mid for mid, deviation in deviations.items() if deviation > error_target_pct]
        room = max(MAX_NODES - len(accepted), 0)
        accepted = sorted([*accepted, *above_target[:room]])
        if not above_target or len(above_target) > room:
            return _NodeSelection(
                simulated=simulated,
                accepted_ages=tuple(accepted),
                max_deviation_pct=max(deviations.values(), default=0.0),
                capped=bool(above_target),
            )


def _assembled_curve(
    nodes: Sequence[_NodeData], finance: FinanceConfig, interp_error_estimate: float, fleet_pv_dc_kw: float
) -> MultiYearCurve:
    """The curve over *finance*'s asset life through *nodes*, ascending by age from age 0, its generation from *fleet_pv_dc_kw* kWp.

    Each year's energy and state of health is the PCHIP of its node values,
    clipped to the range its :class:`YearPoint` field admits.  Each year's
    revenue is the own-use rate times that year's billed own-use, plus the PCHIP
    of the income nodes, so it is affine in the rate.
    """
    years = finance.asset_life_years
    pv_soh = _per_year(nodes, lambda node: node.mean_pv_soh, years)
    battery_soh = _per_year(nodes, lambda node: node.mean_battery_soh, years)
    own_use = [max(0.0, kwh) for kwh in _per_year(nodes, _OWN_USE.value, years)]
    grid_export = _per_year(nodes, _EXPORT.value, years)
    grid_import = _per_year(nodes, _IMPORT.value, years)
    income = _per_year(nodes, _INCOME.value, years)
    points = tuple(
        YearPoint(
            year=y,
            pv_soh=max(0.0, min(1.0, pv_soh[y])),
            battery_soh=max(0.0, min(1.0, battery_soh[y])),
            fleet_billed_own_use_kwh=own_use[y],
            fleet_export_kwh=max(0.0, grid_export[y]),
            fleet_import_kwh=max(0.0, grid_import[y]),
            fleet_revenue_gbp=finance.own_use_rate_pence_per_kwh * own_use[y] / 100.0 + income[y],
        )
        for y in range(years)
    )
    return MultiYearCurve(
        points=points,
        sampled_ages=tuple(node.age for node in nodes),
        interp_error_estimate=interp_error_estimate,
        annualised_from=nodes[0].annualised_from,
        fleet_pv_dc_kw=fleet_pv_dc_kw,
    )


def _cap_notices(selection: _NodeSelection, error_target_pct: float) -> tuple[Warning, ...]:
    """The warning a capped selection's projection shows, or none when the bisection reached its target."""
    if not selection.capped:
        return ()
    return (
        UserWarning(
            f"the projection's adaptive bisection reached MAX_NODES ({MAX_NODES}); "
            f"interp_error_estimate surfaced at {selection.max_deviation_pct:.3f}% "
            f"(target was {error_target_pct}%)."
        ),
    )


def _distinct_grid_services_warnings(simulated: Mapping[int, _SimulatedAge]) -> tuple[Warning, ...]:
    """Each distinct warning pricing grid services raised, by category and text, in the order first raised.

    Each age's grid-services income can raise a warning in the same words as
    every other age's, e.g. naming an event window the simulated period never
    enters, so a projection shows each once
    (docs/prds/grid-services-pricing-model.md §5.4).
    """
    distinct: dict[tuple[type[Warning], str], Warning] = {}
    for simulated_age in simulated.values():
        for raised in simulated_age.grid_services_warnings:
            message = raised.message if isinstance(raised.message, Warning) else raised.category(raised.message)
            distinct.setdefault((raised.category, str(raised.message)), message)
    return tuple(distinct.values())


def _project(
    fleet: ScenarioFleet,
    finance: FinanceConfig,
    simulate: FleetSimulate,
    error_target_pct: float,
) -> tuple[FleetProjection, tuple[Warning, ...]]:
    """Project *fleet* over *finance*'s asset life, with the warnings its caller is to be shown, in order."""
    refuse_analysis_only_forecasts(fleet.homes)
    fleet_pv_dc_kw = sum(wired_dc_capacity_kw(home.pv_config) for home in fleet.homes)
    simulate_at: _SimulateAt = functools.partial(
        _simulate_node, fleet, finance=finance, grid_services=grid_services_model_of(finance), simulate=simulate
    )
    asset_life = finance.asset_life_years
    seeds = _simulated_seeds(simulate_at, len(fleet.homes), asset_life)
    selection = _selected_nodes(seeds, simulate_at, asset_life, error_target_pct)
    curve = _assembled_curve(
        [selection.simulated[age].node for age in selection.accepted_ages],
        finance,
        selection.max_deviation_pct,
        fleet_pv_dc_kw,
    )
    notices = (*_cap_notices(selection, error_target_pct), *_distinct_grid_services_warnings(selection.simulated))
    return FleetProjection(curve=curve, age0_summaries=selection.simulated[0].summaries), notices


def _warn_the_caller(notices: Sequence[Warning]) -> None:
    """Show each of *notices*, attributed to the caller of the public function that calls this."""
    for notice in notices:
        warnings.warn(notice, stacklevel=3)


def project_fleet(
    fleet: ScenarioFleet,
    finance: FinanceConfig,
    *,
    simulate: FleetSimulate,
    error_target_pct: float = 1.0,
) -> FleetProjection:
    """Project *fleet*'s energy and revenue over the full asset life.

    Performs a forward-march over the asset lifetime, simulating the fleet at
    a set of *sampled ages* (seeded at 0, asset_life//2, asset_life-1 and
    adaptively refined by bisection), then interpolating the resulting
    per-year curves with PCHIP.  Each sampled age is simulated with every
    home's battery SOH counting its battery throughput from installation to
    that age (:func:`_throughput_at`), so ``battery_soh`` never rises.  Each
    sampled age's grid-services income is priced from that age's own simulated
    fleet by ``grid_services_model_of(finance)``, and is annual by
    construction.  Each distinct warning that grid-services pricing raises,
    such as one naming an event window the simulated period never enters, is
    shown once per call, however many ages raise it, and is attributed to the
    caller, as is the warning a bisection capped at :data:`MAX_NODES` shows.
    The curve's ``fleet_pv_dc_kw`` is Σ :func:`~solar_challenge.pv.wired_dc_capacity_kw`
    of the fleet's homes, and a PV config
    :func:`~solar_challenge.pv.create_pv_system` refuses is refused before any
    simulation.

    Args:
        fleet: The ScenarioFleet whose homes are simulated over its ``start``
            to ``end``, as :func:`scenario_fleet` resolves a scenario.
        finance: FinanceConfig with ``asset_life_years`` and other parameters.
        simulate: The fleet simulator each sampled age runs through, such as
            a :class:`~solar_challenge.fleet.FleetRunner`'s ``simulate``.
            Grid-services income is priced from the batteries of the
            ``home_configs`` it returns, so it must return the batteries of the
            ``fleet_config.homes`` it is given, in order and state of health
            aside, as ``FleetRunner.simulate`` does.
        error_target_pct: Target maximum PCHIP midpoint deviation (%) before
            adaptive bisection stops.

    Note:
        Every returned :class:`YearPoint` is the window's year: each home's
        own-use, export, import and SEG income are its ledger
        (:func:`~solar_challenge.finance.home_ledger`), the one :func:`~solar_challenge.finance.householder_bill` bills, and its
        battery discharge is its simulated flow, all from its window totals ×
        the window's annualisation_scale (year_days / days,
        :func:`~solar_challenge.finance.annualise`), so energy fields and ``fleet_revenue_gbp`` stay on
        one basis.  A short window is still one
        season's sample, so board figures want the fleet's window to cover
        about one full year.

    Returns:
        :class:`FleetProjection` whose ``curve`` has one :class:`YearPoint`
        per year and metadata about the sampled ages and interpolation error,
        and whose ``age0_summaries`` are each home's summary of the fleet
        simulated at age 0.

    Raises:
        ValueError: If ``simulate`` returns, for a sampled age, a FleetResults
            whose ``home_configs`` do not carry the batteries of the
            ``fleet_config.homes`` it was given, in order and state of health
            aside.  The message names the age's fleet, ``proj-age-<age>``, and
            the first home whose batteries differ with both batteries, or both
            numbers of homes.
        ValueError: If a home's ledger at a simulated age, seed or bisection
            trial, breaks L1-L4, such as an own-use, export or import that is
            NaN or infinite, naming the invariant and its values
            (:class:`~solar_challenge.finance.HomeLedger`).
        ValueError: If a simulated age gives another aggregate that is NaN or
            infinite: the fleet's income, its mean PV or battery state of
            health, or a home's battery discharge or cumulative battery
            throughput.  The message names the age and each such aggregate
            with its value.
        ValueError: If ``simulate`` returns a home's results that record no
            pricing, which only results simulate_home did not make lack, naming
            calculate_summary (:func:`~solar_challenge.finance.annualise`); or whose billed export
            at a recorded SEG rate is negative, which
            :func:`~solar_challenge.seg.calculate_seg_revenue` refuses, naming
            the export.
        ConfigurationError: Before any simulation, if a home's battery
            grid-charges by one of ANALYSIS_ONLY_FORECASTS, as
            :func:`~solar_challenge.finance.refuse_analysis_only_forecasts` refuses it.
    """
    projection, notices = _project(fleet, finance, simulate, error_target_pct)
    _warn_the_caller(notices)
    return projection


def project_multi_year(
    scenario: ScenarioConfig,
    finance: FinanceConfig,
    *,
    error_target_pct: float = 1.0,
    simulate: FleetSimulate,
) -> MultiYearCurve:
    """Project a scenario's fleet over the full asset life: :func:`project_fleet` of ``scenario_fleet(scenario)``, its curve.

    The scenario's homes, as ``simulated_homes()`` gives them, are simulated
    over ``simulation_bounds()``.  The projection's arguments, its warnings,
    which name this function's caller, and its errors are
    :func:`project_fleet`'s.
    """
    projection, notices = _project(scenario_fleet(scenario), finance, simulate, error_target_pct)
    _warn_the_caller(notices)
    return projection.curve


# ---------------------------------------------------------------------------
# project_economics — project-level financial appraisal
# ---------------------------------------------------------------------------

def project_economics(
    curve: MultiYearCurve,
    fleet: ScenarioFleet,
    finance: FinanceConfig,
) -> ProjectEconomics:
    """Compute project-level financial appraisal from a multi-year revenue curve.

    Pure and deterministic: given the same curve, fleet, and finance
    parameters, always returns the same :class:`ProjectEconomics`.

    Algorithm:
    1. Read the fleet's homes, a scenario's simulated homes as
       ``scenario_fleet(scenario)`` resolves them.
    2. Compute total_capex_gbp via the 4-term build-up:
       Σ_home(pv_kwp × pv_cost + roof_fit + battery_kwh × battery_cost
       + eff_inv_kw × inverter_cost).  Inverter term is zero when
       inverter_cost_per_kw_gbp == 0.0 (the default).
    3. financed = max(capex − grant, 0); equity = financed × equity_fraction;
       debt = financed × (1 − equity_fraction).
    4. annual_debt_service via level annuity (annuity_payment).
    5. fleet_opex = opex_per_home × n_homes.
    6. per_year_surplus[y] = revenue[y] − fleet_opex − debt_service (y < loan_term)
       or revenue[y] − fleet_opex (y ≥ loan_term).
    7. min_dscr = min over loan years of (revenue_y − opex) / debt_service;
       float('inf') when debt_service == 0.
    8. equity_irr via NPV bisection on [−equity, surplus_0 … surplus_{N-1}].
    9. payback_years = first 1-based year cumulative(−equity + Σ surplus) ≥ 0,
       or None.
    10. net_surplus_per_home_per_year_gbp = mean(surplus) / n_homes.

    Args:
        curve: MultiYearCurve produced by project_multi_year.
        fleet: The homes whose install is priced, ``scenario_fleet(scenario)``.
        finance: FinanceConfig with cost and finance parameters.

    Returns:
        Fully populated :class:`ProjectEconomics`.

    Raises:
        ValueError: When *curve* has fewer points than ``finance.asset_life_years``.
    """
    homes = fleet.homes
    n_homes = len(homes)

    # 2. Capex: 4-term build-up (pv + roof + battery + inverter)
    total_capex_gbp = 0.0
    for home in homes:
        pv_kwp = home.pv_config.capacity_kw
        batt_kwh = (
            home.battery_config.capacity_kwh
            if home.battery_config is not None
            else 0.0
        )
        eff_inv_kw = home.pv_config.effective_inverter_capacity_kw
        total_capex_gbp += (
            pv_kwp * finance.pv_cost_per_kwp_gbp
            + finance.roof_fit_cost_gbp
            + batt_kwh * finance.battery_cost_per_kwh_gbp
            + eff_inv_kw * finance.inverter_cost_per_kw_gbp
        )

    # 3. Grant / equity / debt split
    financed = max(total_capex_gbp - finance.grant_gbp, 0.0)
    equity_gbp = financed * finance.equity_fraction
    debt_gbp = financed * (1.0 - finance.equity_fraction)

    # 4. Annual debt service
    annual_debt_service_gbp = annuity_payment(
        debt_gbp, finance.loan_rate, finance.loan_term_years
    )

    # Guard: curve must be long enough to cover the full asset life.
    # Raised as a clear domain error rather than an opaque IndexError.
    if len(curve.points) < finance.asset_life_years:
        raise ValueError(
            f"curve has {len(curve.points)} points but finance.asset_life_years="
            f"{finance.asset_life_years}; pass a curve built from the same FinanceConfig"
        )

    # 5. Fleet opex
    fleet_opex = finance.opex_per_home_per_year_gbp * n_homes

    # 6. Per-year surplus
    asset_life = finance.asset_life_years
    loan_term = finance.loan_term_years
    per_year_surplus: List[float] = []
    for y in range(asset_life):
        revenue_y = curve.points[y].fleet_revenue_gbp
        debt_y = annual_debt_service_gbp if y < loan_term else 0.0
        per_year_surplus.append(revenue_y - fleet_opex - debt_y)

    # 7. min_dscr over loan years
    if annual_debt_service_gbp == 0.0:
        min_dscr = float("inf")
    else:
        dscr_values = [
            (curve.points[y].fleet_revenue_gbp - fleet_opex) / annual_debt_service_gbp
            for y in range(loan_term)
        ]
        min_dscr = min(dscr_values)

    # 8. Equity IRR
    cashflows: List[float] = [-equity_gbp] + per_year_surplus
    equity_irr = irr(cashflows)

    # 9. Payback years
    payback_years: Optional[float] = None
    cumulative = -equity_gbp
    for y, surplus in enumerate(per_year_surplus, start=1):
        cumulative += surplus
        if cumulative >= 0.0:
            payback_years = float(y)
            break

    # 10. Net surplus per home per year
    mean_surplus = sum(per_year_surplus) / len(per_year_surplus)
    net_surplus_per_home_per_year_gbp = mean_surplus / n_homes

    return ProjectEconomics(
        total_capex_gbp=total_capex_gbp,
        grant_gbp=finance.grant_gbp,
        equity_gbp=equity_gbp,
        debt_gbp=debt_gbp,
        annual_debt_service_gbp=annual_debt_service_gbp,
        per_year_surplus_gbp=tuple(per_year_surplus),
        min_dscr=min_dscr,
        equity_irr=equity_irr,
        payback_years=payback_years,
        net_surplus_per_home_per_year_gbp=net_surplus_per_home_per_year_gbp,
        fleet_opex_gbp=fleet_opex,
        mean_fleet_surplus_per_year_gbp=mean_surplus,
    )


# ---------------------------------------------------------------------------
# spreadsheet_revenue_curve — [FIN]-assumption analytic revenue curve
# ---------------------------------------------------------------------------


def spreadsheet_revenue_curve(
    *,
    n_homes: int,
    pv_kwp: float,
    kwh_per_kwp: float,
    self_consumption_fraction: float,
    own_use_rate_pence_per_kwh: float,
    export_rate_pence_per_kwh: float,
    asset_life_years: int,
) -> MultiYearCurve:
    """Build a flat [FIN]-assumption fleet-revenue :class:`MultiYearCurve`.

    Produces a deterministic, physics-free revenue curve matching the investor
    spreadsheet's named input assumptions:

    * ``inp_kWhPerkWp`` (Sensitivity!B8) → ``kwh_per_kwp``
    * Own-use rate 15 p/kWh (docs/finance-spreadsheet-reconciliation.md §3.1)
    * Export rate 6 p/kWh (Smart Export Guarantee [FIN] basis)
    * Self-consumption fraction: typically 0.45 (PV-only) or 0.70 (with battery,
      [FIN]); caller-supplied, not enforced by this function

    Per-home generation::

        gen = pv_kwp × kwh_per_kwp   [kWh/yr]

    Fleet revenue::

        fleet_revenue_gbp = n_homes × (
            self_consumption_fraction × gen × own_use_rate_pence_per_kwh / 100
            + (1 − self_consumption_fraction) × gen × export_rate_pence_per_kwh / 100
        )

    The curve is *flat* — SOH fractions are pinned at 1.0 for every year because
    the spreadsheet's revenue projection does not model PV/battery degradation
    (verified via Capital_Stack!B6 arithmetic).  This makes the curve suitable as
    the *spreadsheet-input column* fed into :func:`project_economics` for the [FIN]
    calibration (model doc §7).

    The curve's PV basis, ``fleet_pv_dc_kw``, is the fleet's nameplate,
    ``n_homes × pv_kwp``, as its generation is nameplate × yield.

    Do **not** use this curve for real simulation output — use
    :func:`project_multi_year` for physics-backed projections.

    Args:
        n_homes: Number of homes in the fleet.
        pv_kwp: PV capacity per home (kWp).
        kwh_per_kwp: Annual yield per kWp (kWh/kWp, e.g. 1050 from inp_kWhPerkWp).
        self_consumption_fraction: Fraction of generation consumed on-site (0–1).
        own_use_rate_pence_per_kwh: Retail value of self-consumed solar (p/kWh).
        export_rate_pence_per_kwh: SEG export rate for surplus generation (p/kWh).
        asset_life_years: Number of years in the projection (len of returned curve).

    Returns:
        A flat :class:`MultiYearCurve` with ``asset_life_years`` identical
        :class:`YearPoint` objects and ``interp_error_estimate == 0.0``.
    """
    # Validate domain constraints (mirror __post_init__ style used elsewhere)
    if not (0.0 <= self_consumption_fraction <= 1.0):
        raise ValueError(
            f"self_consumption_fraction must be in [0.0, 1.0], "
            f"got {self_consumption_fraction}"
        )
    if asset_life_years < 1:
        raise ValueError(
            f"asset_life_years must be >= 1, got {asset_life_years}"
        )

    # Per-home annual generation (kWh)
    gen_per_home_kwh: float = pv_kwp * kwh_per_kwp

    # Fleet generation (kWh)
    fleet_gen_kwh: float = float(n_homes) * gen_per_home_kwh

    # Energy split
    fleet_self_kwh: float = self_consumption_fraction * fleet_gen_kwh
    fleet_export_kwh: float = (1.0 - self_consumption_fraction) * fleet_gen_kwh

    # Fleet revenue (£/yr)  — own-use saving + SEG export income
    fleet_revenue_gbp: float = (
        fleet_self_kwh * own_use_rate_pence_per_kwh / 100.0
        + fleet_export_kwh * export_rate_pence_per_kwh / 100.0
    )

    # Build identical YearPoints for each year (flat — no degradation in spreadsheet)
    points: tuple[YearPoint, ...] = tuple(
        YearPoint(
            year=y,
            pv_soh=1.0,
            battery_soh=1.0,
            fleet_billed_own_use_kwh=fleet_self_kwh,
            fleet_export_kwh=fleet_export_kwh,
            fleet_import_kwh=0.0,   # not modelled by the spreadsheet; set to 0
            fleet_revenue_gbp=fleet_revenue_gbp,
        )
        for y in range(asset_life_years)
    )

    return MultiYearCurve(
        points=points,
        sampled_ages=(0,),          # analytic; no simulation nodes
        interp_error_estimate=0.0,  # exact; no interpolation
        annualised_from=None,       # yearly assumptions; no simulated window
        fleet_pv_dc_kw=float(n_homes) * pv_kwp,
    )


# ---------------------------------------------------------------------------
# solve_cost_recovery_rate — near-closed-form own-use-rate solve
# ---------------------------------------------------------------------------

#: Minimum absolute slope (kWh-weighted / pence) below which we treat the
#: project as having no billed own-use and fall through to the degenerate branch.
_SLOPE_EPS: float = 1e-9


def solve_cost_recovery_rate(
    scenario: ScenarioConfig,
    finance: FinanceConfig,
    *,
    simulate: FleetSimulate,
) -> CostRecoverySolution:
    """Find the minimum CBS own-use rate that meets the retained-cash floor.

    The CBS charges householders ``own_use_rate_pence_per_kwh`` p/kWh for every
    kWh of CBS-owned solar consumed on-site.  This function finds the lowest such
    rate *r** such that ``project_economics.net_surplus_per_home_per_year_gbp ≥
    finance.retained_cash_floor_per_home_per_year_gbp``.

    **Mechanism** (no re-sim per trial rate):

    ``surplus_at(r)`` is affine in *r* by construction: it shifts each year's
    revenue by ``(r − r0)/100 × own_use_y`` and ``project_economics`` is affine
    in per-year revenue.  Two trial rates (r=0, r=retail) therefore recover the
    line, and the solve is closed-form.  ``surplus_at(r)`` is exact and
    independent of the configured rate r0: node selection reads no rate, and
    each year's revenue is ``r0 × own_use_y / 100 + income_y``, so the shift is
    a re-projection at *r*, exactly, and the two-point fit's *r** is the
    re-projected solution whatever r0 is (docs/cost-recovery-finance-model.md §5).

    1. Run ``project_fleet`` **once** at the configured rate ``r0`` → base curve.
    2. ``surplus_at(r)`` rebuilds each ``YearPoint``'s ``fleet_revenue_gbp`` via
       ``dataclasses.replace``: ``rev_y' = rev_y + (r - r0)/100 × own_use_y``.
    3. Compute ``s0 = surplus_at(0)``, ``s_ret = surplus_at(retail)``,
       ``slope = (s_ret - s0) / retail``.
    4. Solve ``r* = (floor - s0) / slope``; clamp to [0, retail]; set *binding*.
    5. Compute outlay from a dedicated age-0 fleet sim (per-home granularity
       not available from the multi-year curve).

    The rate base (``YearPoint.fleet_billed_own_use_kwh``) and the revenue
    are the projection's annualised figures, so a short window is solved
    like-for-like against the annual opex, debt and floor, but carries that
    window's seasonal bias.

    **Clamp / binding convention**:

    * ``r* < 0``: ``rate_clamped_zero`` (feasible=True, surplus > floor).
    * ``0 ≤ r* ≤ retail``: ``floor`` (feasible=True, surplus ≈ floor to float ε).
    * ``r* > retail``: ``infeasible_above_retail`` (feasible=False, rate=retail,
      surplus < floor).
    * Degenerate (slope ≈ 0, no billed own-use): if ``s0 ≥ floor`` →
      ``rate_clamped_zero``; else → ``infeasible_above_retail``.

    Args:
        scenario: ScenarioConfig whose homes, as ``simulated_homes()`` gives
            them, are simulated over ``simulation_bounds()``.
        finance: FinanceConfig with cost-recovery fields populated.
        simulate: The fleet simulator the projection and the age-0 outlay
            run through, such as a :class:`~solar_challenge.fleet.FleetRunner`'s
            ``simulate``.  Grid-services income is priced from the batteries
            of the ``home_configs`` it returns, so it must return the batteries
            of the ``fleet_config.homes`` it is given, in order and state of
            health aside, as ``FleetRunner.simulate`` does;
            :func:`project_fleet` raises ValueError otherwise.

    Returns:
        A :class:`~solar_challenge.finance.CostRecoverySolution` with the solved rate and outlay.

    Raises:
        ConfigurationError: Before any simulation, if a home's battery
            grid-charges by one of ANALYSIS_ONLY_FORECASTS, as
            :func:`~solar_challenge.finance.refuse_analysis_only_forecasts` refuses it.
    """
    fleet = scenario_fleet(scenario)
    refuse_analysis_only_forecasts(fleet.homes)

    # ---- (1) Base curve at the configured r0 ---------------------------------
    r0 = finance.own_use_rate_pence_per_kwh
    base_curve = project_fleet(fleet, finance, simulate=simulate).curve

    # ---- (2) surplus_at(r): rebuild YearPoints with rate-shifted revenue -----
    def surplus_at(r: float) -> float:
        """Return net_surplus_per_home_per_year at trial rate r (p/kWh)."""
        new_points = tuple(
            dataclasses.replace(
                yp,
                fleet_revenue_gbp=yp.fleet_revenue_gbp
                + (r - r0) / 100.0 * yp.fleet_billed_own_use_kwh,
            )
            for yp in base_curve.points
        )
        rate_curve = dataclasses.replace(base_curve, points=new_points)
        # finance passed to project_economics can be the original; capex/debt
        # are rate-independent.  Surplus formula uses curve.points[y].fleet_revenue_gbp.
        return project_economics(rate_curve, fleet, finance).net_surplus_per_home_per_year_gbp

    # ---- (3) Two-point fit to recover the affine line ------------------------
    retail = finance.retail_baseline_rate_pence_per_kwh
    floor = finance.retained_cash_floor_per_home_per_year_gbp

    s0 = surplus_at(0.0)
    s_ret = surplus_at(retail)
    slope = (s_ret - s0) / retail  # retail > 0 (validated in FinanceConfig)

    # ---- (4) Solve + clamp ---------------------------------------------------
    if abs(slope) > _SLOPE_EPS:
        r_star = (floor - s0) / slope
        if r_star < 0.0:
            rate = 0.0
            binding = "rate_clamped_zero"
            feasible = True
        elif r_star <= retail:
            rate = r_star
            binding = "floor"
            feasible = True
        else:
            rate = retail
            binding = "infeasible_above_retail"
            feasible = False
    else:
        # Degenerate: near-zero billed own-use → surplus is constant
        if s0 >= floor:
            rate = 0.0
            binding = "rate_clamped_zero"
            feasible = True
        else:
            rate = retail
            binding = "infeasible_above_retail"
            feasible = False

    # ---- (5) Net surplus at the clamped/solved rate --------------------------
    net_surplus = surplus_at(rate)

    # ---- (6) Age-0 outlay BillDistribution -----------------------------------
    aged0 = _aged_homes(fleet.homes, 0)
    fleet_cfg = FleetConfig(homes=tuple(aged0), name="cr4-solve-age0")
    fr_age0 = simulate(fleet_cfg, fleet.start, fleet.end)

    summaries = [calculate_summary(r) for r in fr_age0.per_home_results]
    finance_solved = dataclasses.replace(finance, own_use_rate_pence_per_kwh=rate)
    outlay = bill_distribution(summaries, finance_solved)

    # ---- (7) Assemble result -------------------------------------------------
    rep = outlay.representative
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=rate,
        outlay=outlay,
        representative_outlay_gbp=rep.total_outlay_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus,
        saving_vs_baseline_gbp=rep.saving_vs_baseline_gbp,
        saving_pct=rep.saving_pct,
        feasible=feasible,
        binding=binding,
    )
