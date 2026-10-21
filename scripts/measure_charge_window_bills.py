# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bill bristol-arbitrage's home under four dispatch arms, two of them a Victron GX's scheduled-charge windows.

docs/scheduled-charge-windows.md records what this prints and why. From the repository root:

    uv run --locked --extra dev python scripts/measure_charge_window_bills.py [--cache-dir DIR] [--start YYYY-MM-DD --end YYYY-MM-DD]

It simulates scenarios/bristol-arbitrage.yaml's home under each arm arms() names, over 2025 by
default, on PVGIS's TMY at the home's location. It reads the TMY from the weather cache, so once
the cache holds Bristol's TMY it runs offline; the default year takes about 2 minutes. It bills
each arm with finance.bill and prints the bills with the library version, the weather, the
tariff clock and the windows they were measured on. tests/unit/test_measurement_scripts.py runs
it offline on synthetic weather; the full year is not part of the test suite.
"""

import argparse
import dataclasses
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

import solar_challenge
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.finance import BillBreakdown, FinanceConfig, bill
from solar_challenge.home import HomeConfig, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.weather import (
    CLIMATE_YEARS,
    DEFAULT_CACHE_DIR,
    PVGIS_API_URL,
    PvgisTmy,
    WeatherCache,
    WeatherProvider,
)

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "bristol-arbitrage.yaml"

WINDOWS = (ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, allow_discharge=False),)
"""Arms B's and D's windows: Economy 7's cheap period, charging to the scenario's grid-charging target."""

TOU_PEAK_HOURS = [(0, 1), (7, 24)]
"""Arm B's base peak hours: every whole hour but those the cheap period fills, which the window covers."""

FINANCE = FinanceConfig(standing_charge_pence_per_day=60.0)

DEFAULT_START = pd.Timestamp("2025-01-01")
DEFAULT_END = pd.Timestamp("2025-12-31")


@dataclass(frozen=True)
class Arm:
    """One way of dispatching the home: its label, what it dispatches by, the home it runs and any strategy given to simulate_home."""

    label: str
    dispatch: str
    home: HomeConfig
    strategy: Optional[DispatchStrategy]


@dataclass(frozen=True)
class ArmBill:
    """An arm's run of the home, summarised and billed."""

    arm: str
    dispatch: str
    summary: SummaryStatistics
    bill: BillBreakdown


def arms(home: HomeConfig) -> Iterator[Arm]:
    """The four arms, A to D, each run on home's battery, B's and D's windows on its location's clock.

    Raises:
        ValueError: If home has no battery, which every arm dispatches.
    """
    battery = home.battery_config
    if battery is None:
        raise ValueError(f"the arms dispatch a battery, and {home.name!r} has none")
    tz = ZoneInfo(home.location.timezone)
    yield Arm("A", "as configured", home, None)
    yield Arm("B", "windows over tou_optimized", home, ScheduledChargeStrategy(TOUOptimizedStrategy(TOU_PEAK_HOURS), WINDOWS, tz))
    no_grid_charging = dataclasses.replace(
        home, dispatch_strategy="greedy", battery_config=dataclasses.replace(battery, grid_charging=None)
    )
    yield Arm("C", "greedy, no grid charging", no_grid_charging, None)
    yield Arm("D", "windows over self-consumption", home, ScheduledChargeStrategy(SelfConsumptionStrategy(), WINDOWS, tz))


def own_use_kwh(summary: SummaryStatistics) -> float:
    """The run's own use on basis C, its demand less its import (docs/cost-recovery-finance-model.md)."""
    return summary.total_demand_kwh - summary.total_grid_import_kwh


def bill_arm(arm: Arm, start: pd.Timestamp, end: pd.Timestamp, *, weather: WeatherProvider) -> ArmBill:
    """arm's run from start to end on weather, billed at FINANCE against its demand priced at the run's tariff rates."""
    results = simulate_home(arm.home, start, end, weather=weather, strategy=arm.strategy)
    summary = calculate_summary(results)
    baseline_import_cost_gbp = float((results.per_minute_amounts()["demand_kwh"] * results.tariff_rate).sum())
    breakdown = bill(
        period_days=summary.simulation_days,
        generation_kwh=summary.total_generation_kwh,
        demand_kwh=summary.total_demand_kwh,
        self_consumption_kwh=own_use_kwh(summary),
        import_kwh=summary.total_grid_import_kwh,
        import_cost_gbp=summary.total_import_cost_gbp,
        baseline_import_cost_gbp=baseline_import_cost_gbp,
        finance=FINANCE,
    )
    return ArmBill(arm.label, arm.dispatch, summary, breakdown)


def measure(home: HomeConfig, start: pd.Timestamp, end: pd.Timestamp, *, weather: WeatherProvider) -> list[ArmBill]:
    """Each arm's bill for home from start to end on weather, A to D."""
    return [bill_arm(arm, start, end, weather=weather) for arm in arms(home)]


def print_report(
    home: HomeConfig,
    bills: Sequence[ArmBill],
    *,
    cache_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    """Print bills as a markdown table, after the library version, weather, tariff clock, windows, finance and period they were measured on."""
    location = home.location
    print(f"solar_challenge {solar_challenge.__version__}")
    print(
        f"Weather: PVGIS TMY at {location.name} ({location.latitude}, {location.longitude}) from {PVGIS_API_URL},"
        f" scaled to its {CLIMATE_YEARS[0]}-{CLIMATE_YEARS[-1]} mean annual GHI, read from the cache in {cache_dir}"
    )
    if home.tariff_config is not None:
        periods = "; ".join(
            f"{period.name} {period.start_time}-{period.end_time} at £{period.rate_per_kwh:.2f}/kWh"
            for period in home.tariff_config.periods
        )
        print(f"Tariff: {home.tariff_config.name}, on {location.timezone}'s clock: {periods}")
    for window in WINDOWS:
        discharge = "discharging down to it" if window.allow_discharge else "holding"
        print(
            f"Window (B, D): {window.days} from {window.start:%H:%M} for {window.duration}"
            f" to {window.target_soc_fraction} of capacity, {discharge}"
        )
    print(f"B's base: TOUOptimizedStrategy, peak hours {TOU_PEAK_HOURS}")
    print(
        f"Finance: standing charge {FINANCE.standing_charge_pence_per_day} p/day,"
        f" own use {FINANCE.own_use_rate_pence_per_kwh} p/kWh on basis C (demand less import),"
        f" VAT {FINANCE.vat_rate}"
    )
    print(f"Period: {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    print()
    print("| Arm | Dispatch | Strategy | Import kWh | Import £ | Standing £ | Own-use kWh | Own-use £ | VAT £ | Total £ |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for arm in bills:
        summary, breakdown = arm.summary, arm.bill
        print(
            f"| {arm.arm} | {arm.dispatch} | {summary.strategy_name}"
            f" | {summary.total_grid_import_kwh:.1f} | {breakdown.import_cost_gbp:.2f}"
            f" | {breakdown.standing_charge_gbp:.2f} | {own_use_kwh(summary):.1f}"
            f" | {breakdown.own_use_payment_gbp:.2f} | {breakdown.vat_gbp:.2f} | {breakdown.total_outlay_gbp:.2f} |"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="weather cache holding Bristol's TMY"
    )
    parser.add_argument("--start", type=pd.Timestamp, default=DEFAULT_START, help="first day, YYYY-MM-DD")
    parser.add_argument("--end", type=pd.Timestamp, default=DEFAULT_END, help="last day, YYYY-MM-DD")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    home = home_config_for_run(SCENARIO)
    bills = measure(home, args.start, args.end, weather=PvgisTmy(WeatherCache(args.cache_dir)))
    print_report(home, bills, cache_dir=args.cache_dir, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
