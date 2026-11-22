# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure the board fleet's net cost and householder bill under each grid-charge forecast.

docs/grid-charge-forecast.md records what this prints and why. From the repository root:

    uv run --locked --extra dev python scripts/measure_grid_charge_forecast.py [--cache-dir DIR] [--start YYYY-MM-DD --end YYYY-MM-DD] [--homes N] [--no-parallel]

It simulates the homes `solar-challenge finance run scenarios/bristol-phase1-flex.yaml` simulates,
each exporting at the scenario's SEG rate, once under each forecast dispatch.GRID_CHARGE_FORECASTS
names, every battery's grid charging sized by that forecast, over 2024 by default, on PVGIS's TMY
at the scenario's location. It reads the TMY from the weather cache, so once the cache holds
Bristol's TMY it runs offline. The whole fleet over the year is some 300 home-years of simulation,
about a minute of CPU each, run in a process pool unless --no-parallel; --homes N measures only the
first N homes. It prints each forecast's per-home mean net cost (import cost less export revenue)
in each meteorological season the window covers and over the window, its mean grid charge and
export, and the mean householder bill finance.bill_distribution gives under the scenario's
finance: block, then each figure's delta against pv_blind, with the library version, the weather
and the window. finance refuses to bill a perfect_foresight run, so that bill prints as refused,
with finance's reason. tests/unit/test_measurement_scripts.py runs it offline on synthetic weather;
the full fleet is not part of the test suite.
"""

import argparse
import dataclasses
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Optional, Union

import pandas as pd

import solar_challenge
from solar_challenge.config import ScenarioConfig, SimulationPeriod, load_config, load_fleet_config
from solar_challenge.dispatch import GRID_CHARGE_FORECASTS, GridChargeForecast
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig, bill_distribution
from solar_challenge.fleet import FleetConfig, FleetRunner, HomesDone
from solar_challenge.grid_charge_forecast import GRID_CHARGE_FORECAST_LABELS
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.scenario_blocks import parse_finance_config, parse_seg_rate
from solar_challenge.weather import (
    CACHE_DIR_VARIABLE,
    CLIMATE_YEARS,
    DEFAULT_CACHE_DIR,
    PVGIS_API_URL,
    PvgisTmy,
    WeatherCache,
)

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "bristol-phase1-flex.yaml"

BASELINE: Final[GridChargeForecast] = "pv_blind"
"""The forecast every delta is taken against: the default, which fills to the target every cheap period."""

SEASONS: Final[Mapping[str, tuple[int, ...]]] = MappingProxyType(
    {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
)
"""The meteorological seasons in the order the report prints them, each with its calendar months."""

_SEASON_OF_MONTH: Final = MappingProxyType({month: season for season, months in SEASONS.items() for month in months})

DEFAULT_START = pd.Timestamp("2024-01-01")
DEFAULT_END = pd.Timestamp("2024-12-31")


@dataclass(frozen=True)
class Refused:
    """finance's refusal to bill an arm's runs, in the words of its ConfigurationError."""

    reason: str


@dataclass(frozen=True)
class HomeRun:
    """One home's run under one forecast: its summary, and its net cost in £, import cost less export revenue, in each season its window covers, in SEASONS order."""

    summary: SummaryStatistics
    net_cost_by_season_gbp: Mapping[str, float]


@dataclass(frozen=True)
class Arm:
    """The homes' runs under one forecast, in home order, and the mean of their householder bills a year in £, or finance's refusal to bill them."""

    forecast: GridChargeForecast
    homes: tuple[HomeRun, ...]
    householder_bill: Union[float, Refused]


def read_scenario(
    path: Path, *, start: pd.Timestamp, end: pd.Timestamp, homes: Optional[int] = None
) -> ScenarioConfig:
    """The fleet scenario at path as `solar-challenge finance run` reads it, over start to end: the first homes of its fleet (all when homes is None), its location, its SEG rate, which simulated_homes gives each home, and its finance: block."""
    raw = load_config(path)
    fleet = load_fleet_config(path)
    return ScenarioConfig(
        name=raw.get("name", str(path)),
        period=SimulationPeriod(start_date=start, end_date=end),
        homes=tuple(fleet.homes[:homes]),
        location=fleet.homes[0].location,
        seg_tariff_pence_per_kwh=parse_seg_rate(raw.get("seg")),
        finance=parse_finance_config(raw.get("finance")),
    )


def with_forecast(home: HomeConfig, forecast: GridChargeForecast) -> HomeConfig:
    """home with its battery's grid charging sized by forecast; a home with no battery, or whose battery does not grid-charge, as it is."""
    battery = home.battery_config
    if battery is None or battery.grid_charging is None:
        return home
    grid_charging = dataclasses.replace(battery.grid_charging, forecast=forecast)
    return dataclasses.replace(home, battery_config=dataclasses.replace(battery, grid_charging=grid_charging))


def net_cost_by_season_gbp(results: SimulationResults) -> dict[str, float]:
    """results' net cost in £, import cost less export revenue, in each season its rows fall in on their own clock, in SEASONS order."""
    amounts = results.per_step_amounts()
    net_cost = amounts["import_cost_gbp"] - amounts["export_revenue_gbp"]
    by_season = net_cost.groupby(net_cost.index.month.map(_SEASON_OF_MONTH)).sum()
    return {season: float(by_season[season]) for season in SEASONS if season in by_season.index}


def householder_bill(summaries: Sequence[SummaryStatistics], finance: FinanceConfig) -> Union[float, Refused]:
    """The mean of the per-home bills a year finance.bill_distribution gives summaries under finance, or finance's refusal to bill them."""
    try:
        return bill_distribution(summaries, finance).mean_gbp
    except ConfigurationError as refusal:
        return Refused(str(refusal))


def _billing_finance(scenario: ScenarioConfig) -> FinanceConfig:
    """scenario's finance: block, which the householder bill reads.

    Raises:
        ConfigurationError: If scenario has none, naming it.
    """
    if scenario.finance is None:
        raise ConfigurationError(f"scenario {scenario.name!r} has no finance: block, which the householder bill reads")
    return scenario.finance


def _progress(forecast: GridChargeForecast) -> HomesDone:
    """Tell stderr of each home of forecast's arm as it finishes, so a long run shows how far it has got."""

    def homes_done(done: int, total: int) -> None:
        print(f"{forecast}: {done} of {total} homes simulated", file=sys.stderr, flush=True)

    return homes_done


def measure_arm(
    scenario: ScenarioConfig, finance: FinanceConfig, forecast: GridChargeForecast, runner: FleetRunner
) -> Arm:
    """scenario's homes run by runner over its window, every battery's grid charging sized by forecast, and billed under finance."""
    homes = scenario.map_homes(lambda home: with_forecast(home, forecast)).simulated_homes()
    start, end = scenario.simulation_bounds()
    fleet = runner.simulate(FleetConfig(homes=list(homes), name=forecast), start, end, progress=_progress(forecast))
    runs = tuple(HomeRun(calculate_summary(results), net_cost_by_season_gbp(results)) for results in fleet.per_home_results)
    return Arm(forecast, runs, householder_bill([run.summary for run in runs], finance))


def measure(scenario: ScenarioConfig, runner: FleetRunner) -> list[Arm]:
    """Each forecast's arm of scenario, in GRID_CHARGE_FORECASTS order, the arms run one after another, so one arm's minute series are held at a time.

    Raises:
        ConfigurationError: Before any run, if scenario has no finance: block.
    """
    finance = _billing_finance(scenario)
    return [measure_arm(scenario, finance, forecast, runner) for forecast in GRID_CHARGE_FORECASTS]


def seasons_of(arms: Sequence[Arm]) -> tuple[str, ...]:
    """The seasons the arms' runs cover, in SEASONS order."""
    covered = {season for arm in arms for home in arm.homes for season in home.net_cost_by_season_gbp}
    return tuple(season for season in SEASONS if season in covered)


def per_home_means(arm: Arm, seasons: Sequence[str]) -> dict[str, Optional[float]]:
    """Each figure the report prints for arm, by its column: the mean over arm's homes, and None for a bill finance refused."""
    summaries = [home.summary for home in arm.homes]
    bill = arm.householder_bill
    return {
        **{
            f"{season} net £": statistics.fmean(home.net_cost_by_season_gbp[season] for home in arm.homes)
            for season in seasons
        },
        "Window net £": statistics.fmean(summary.net_cost_gbp for summary in summaries),
        "Grid charge kWh": statistics.fmean(summary.total_grid_charge_kwh for summary in summaries),
        "Export kWh": statistics.fmean(summary.total_grid_export_kwh for summary in summaries),
        "Householder bill £/yr": None if isinstance(bill, Refused) else bill,
    }


def _difference(value: Optional[float], baseline: Optional[float]) -> Optional[float]:
    """value less baseline; None when either is None."""
    return None if value is None or baseline is None else value - baseline


def against(figures: Mapping[str, Optional[float]], baseline: Mapping[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Each of figures less baseline's figure in the same column."""
    return {column: _difference(value, baseline[column]) for column, value in figures.items()}


def _cell(value: Optional[float], sign: str) -> str:
    """value to two places, signed when sign is '+'; 'refused' for None, a bill finance refused."""
    return "refused" if value is None else f"{value:{sign}.2f}"


def print_table(rows: Mapping[GridChargeForecast, Mapping[str, Optional[float]]], *, sign: str = "") -> None:
    """Print rows as a markdown table, one row per forecast and one column per figure, in their order."""
    columns = list(next(iter(rows.values())))
    print("| Forecast | " + " | ".join(columns) + " |")
    print("|---|" + "---:|" * len(columns))
    for forecast, figures in rows.items():
        print(f"| {forecast} | " + " | ".join(_cell(figures[column], sign) for column in columns) + " |")


def print_measured_on(scenario: ScenarioConfig, *, cache_dir: Path) -> None:
    """Print the library version, homes, weather, tariff, window, forecasts and figures the report was measured with."""
    homes, location, window = scenario.simulated_homes(), scenario.get_location(), scenario.window()
    print(f"solar_challenge {solar_challenge.__version__}")
    print(
        f"Homes: the first {len(homes)} of {SCENARIO.name}'s fleet ({scenario.name}), as `solar-challenge finance run`"
        f" simulates them, each exporting at the scenario's SEG rate of {scenario.seg_tariff_pence_per_kwh} p/kWh"
    )
    print(
        f"Weather: PVGIS TMY at {location.name} ({location.latitude}, {location.longitude}) from {PVGIS_API_URL},"
        f" scaled to its {CLIMATE_YEARS[0]}-{CLIMATE_YEARS[-1]} mean annual GHI, read from the cache in {cache_dir}"
    )
    tariff = homes[0].tariff_config
    if tariff is not None:
        periods = "; ".join(
            f"{period.name} {period.start_time}-{period.end_time} at £{period.rate_per_kwh:.2f}/kWh"
            for period in tariff.periods
        )
        print(f"Tariff: {tariff.name}, on {location.timezone}'s clock: {periods}")
    print(f"Window: {window.first_day.isoformat()} to {window.last_day.isoformat()}, {window.days} days")
    for forecast in GRID_CHARGE_FORECASTS:
        print(f"Forecast {forecast}: {GRID_CHARGE_FORECAST_LABELS[forecast]}")
    print(f"Net cost: import cost less export revenue, by meteorological season ({', '.join(SEASONS)}) and over the window")
    print(
        "Householder bill: the mean of finance.bill_distribution's per-home total outlay a year"
        " under the scenario's finance: block"
    )


def print_report(scenario: ScenarioConfig, arms: Sequence[Arm], *, cache_dir: Path) -> None:
    """Print arms' per-home means and their deltas against BASELINE as markdown tables, after what they were measured on, then each refusal to bill an arm."""
    print_measured_on(scenario, cache_dir=cache_dir)
    seasons = seasons_of(arms)
    means = {arm.forecast: per_home_means(arm, seasons) for arm in arms}
    print("\nPer-home means:\n")
    print_table(means)
    print(f"\nAgainst {BASELINE}:\n")
    print_table({forecast: against(figures, means[BASELINE]) for forecast, figures in means.items()}, sign="+")
    for arm in arms:
        if isinstance(arm.householder_bill, Refused):
            print(f"\n{arm.forecast}'s householder bill is refused: {arm.householder_bill.reason}")


def _at_least_one(text: str) -> int:
    """text read as a whole number of at least 1, as --homes takes it."""
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError(f"--homes takes a whole number of at least 1, not {text!r}")
    return count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "weather cache holding the TMY at the scenario's location "
            f"(default: the directory {CACHE_DIR_VARIABLE} names, else {DEFAULT_CACHE_DIR})"
        ),
    )
    parser.add_argument("--start", type=pd.Timestamp, default=DEFAULT_START, help="first day, YYYY-MM-DD")
    parser.add_argument("--end", type=pd.Timestamp, default=DEFAULT_END, help="last day, YYYY-MM-DD")
    parser.add_argument(
        "--homes", type=_at_least_one, default=None, help="measure only the fleet's first N homes (default: all)"
    )
    parser.add_argument(
        "--parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run the homes in a process pool (the default), or in turn in this process",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    scenario = read_scenario(SCENARIO, start=args.start, end=args.end, homes=args.homes)
    cache = WeatherCache(args.cache_dir)
    runner = FleetRunner(weather=PvgisTmy(cache), home_simulator=simulate_home, parallel=args.parallel)
    print_report(scenario, measure(scenario, runner), cache_dir=cache.cache_dir)


if __name__ == "__main__":
    main()
