# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure the default PV system's annual performance ratio at UK sites, with and without its system losses.

docs/pv-system-losses.md records what this prints and defines the performance ratio. From
the repository root:

    uv run --locked --extra dev python scripts/measure_pv_performance_ratio.py [--cache-dir DIR]

For each of fourteen UK sites it reads PVGIS's TMY through get_tmy_data, which the weather
cache serves when it holds it, and fetches PVGIS's own hourly estimate for the same system
at PVGIS's 14% loss over the climate years, from the release get_tmy_data uses, so it needs
network access to PVGIS; it takes about five minutes. It simulates PVConfig.default_4kw() with
its system losses and without them. tests/unit/test_measurement_scripts.py runs measure
offline on synthetic weather; the PVGIS fetches and the full run are not part of the test
suite.
"""

import argparse
import dataclasses
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from pvlib.iotools import get_pvgis_hourly

from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    create_model_chain,
    simulate_pv_output,
    wired_dc_capacity_kw,
)
from solar_challenge.weather import (
    CLIMATE_YEARS,
    DEFAULT_CACHE_DIR,
    PVGIS_API_URL,
    PVGIS_TIMEOUT_S,
    WeatherCache,
    get_tmy_data,
    set_weather_cache,
)

# docs/pv-annual-yield-benchmark.md §3's sites, at its points.
SITES: Mapping[str, Location] = {
    "Weymouth": Location(latitude=50.61, longitude=-2.45),
    "Shanklin, Isle of Wight": Location(latitude=50.63, longitude=-1.18),
    "St Mary's, Isles of Scilly": Location(latitude=49.92, longitude=-6.30),
    "Eastbourne": Location(latitude=50.77, longitude=0.29),
    "Plymouth": Location(latitude=50.37, longitude=-4.14),
    "London": Location(latitude=51.51, longitude=-0.13),
    "Penzance": Location(latitude=50.12, longitude=-5.54),
    "Bristol": Location.bristol(),
    "Belfast": Location(latitude=54.60, longitude=-5.93),
    "Aberdeen": Location(latitude=57.15, longitude=-2.09),
    "Manchester": Location(latitude=53.48, longitude=-2.24),
    "Glasgow": Location(latitude=55.86, longitude=-4.25),
    "Stornoway": Location(latitude=58.21, longitude=-6.39),
    "Lerwick": Location(latitude=60.15, longitude=-1.15),
}
CONFIG = PVConfig.default_4kw()
LOSSLESS = dataclasses.replace(CONFIG, system_losses=0.0)
PVGIS_LOSS_PERCENT = 14.0
"""PVGIS's default system loss, the one its estimate here takes."""


@dataclass(frozen=True)
class Yield:
    """One configuration's year at a site: AC energy in kWh, that per wired kWp, and that per in-plane kWh/m²."""

    ac_kwh: float
    kwh_per_kwp: float
    performance_ratio: float

    @classmethod
    def of(cls, ac_kwh: float, wired_kwp: float, poa_kwh_per_m2: float) -> "Yield":
        kwh_per_kwp = ac_kwh / wired_kwp
        return cls(ac_kwh, kwh_per_kwp, kwh_per_kwp / poa_kwh_per_m2)


@dataclass(frozen=True)
class SiteMeasurement:
    """CONFIG's year at one site from its TMY, without and with its system losses; irradiation in kWh/m²."""

    name: str
    location: Location
    ghi_kwh_per_m2: float
    poa_kwh_per_m2: float
    wired_kwp: float
    lossless: Yield
    with_losses: Yield


@dataclass(frozen=True)
class PvgisEstimate:
    """PVGIS's mean year for 1 kWp at CONFIG's tilt and azimuth: AC in kWh, in-plane irradiation in kWh/m²."""

    kwh_per_kwp: float
    poa_kwh_per_m2: float

    @property
    def performance_ratio(self) -> float:
        return self.kwh_per_kwp / self.poa_kwh_per_m2


def in_plane_irradiation(location: Location, tmy: pd.DataFrame) -> float:
    """CONFIG's in-plane irradiation over tmy in kWh/m², from its model chain's first array; every array shares the mount."""
    chain = create_model_chain(CONFIG, location)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered",
            category=RuntimeWarning,
            module=r"scipy\.optimize\._chandrupatla",
        )
        chain.run_model(tmy)
    in_plane = chain.results.total_irrad
    first_array = in_plane[0] if isinstance(in_plane, tuple) else in_plane
    return float(first_array["poa_global"].sum()) / 1000.0


def annual_ac_kwh(config: PVConfig, location: Location, weather: pd.DataFrame) -> float:
    """config's AC energy over hourly weather."""
    return float(simulate_pv_output(config, location, weather).sum())


def measure(name: str, location: Location, tmy: pd.DataFrame) -> SiteMeasurement:
    """Measure CONFIG over one site's TMY, without its system losses and with them."""
    poa_kwh_per_m2 = in_plane_irradiation(location, tmy)
    wired_kwp = wired_dc_capacity_kw(CONFIG)
    return SiteMeasurement(
        name=name,
        location=location,
        ghi_kwh_per_m2=float(tmy["ghi"].sum()) / 1000.0,
        poa_kwh_per_m2=poa_kwh_per_m2,
        wired_kwp=wired_kwp,
        lossless=Yield.of(annual_ac_kwh(LOSSLESS, location, tmy), wired_kwp, poa_kwh_per_m2),
        with_losses=Yield.of(annual_ac_kwh(CONFIG, location, tmy), wired_kwp, poa_kwh_per_m2),
    )


def fetch_pvgis_estimate(location: Location) -> PvgisEstimate:
    """PVGIS's hourly estimate for 1 kWp at CONFIG's tilt and azimuth over the climate years, at its 14% loss, as annual means."""
    series = get_pvgis_hourly(
        latitude=location.latitude,
        longitude=location.longitude,
        start=CLIMATE_YEARS[0],
        end=CLIMATE_YEARS[-1],
        pvcalculation=True,
        peakpower=1,
        loss=PVGIS_LOSS_PERCENT,
        surface_tilt=CONFIG.tilt,
        surface_azimuth=CONFIG.azimuth,
        components=True,
        usehorizon=True,
        mountingplace="free",
        url=PVGIS_API_URL,
        timeout=PVGIS_TIMEOUT_S,
        map_variables=True,
    )[0]
    years = series.index.year
    in_plane = series["poa_direct"] + series["poa_sky_diffuse"] + series["poa_ground_diffuse"]
    return PvgisEstimate(
        kwh_per_kwp=float((series["P"].groupby(years).sum() / 1000.0).mean()),
        poa_kwh_per_m2=float((in_plane.groupby(years).sum() / 1000.0).mean()),
    )


def print_table(rows: Sequence[tuple[SiteMeasurement, PvgisEstimate]]) -> None:
    """Print each site's yields and performance ratios beside PVGIS's as a markdown table, then the ratios' ranges."""
    print(
        "\n| Site (lat, lon) | GHI kWh/m² | POA kWh/m² | lossless kWh/kWp | lossless PR"
        " | with losses kWh/kWp | with losses PR | PVGIS-14% kWh/kWp | PVGIS-14% PR"
        " | with losses vs PVGIS |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for site, pvgis in rows:
        print(
            f"| {site.name} ({site.location.latitude}, {site.location.longitude})"
            f" | {site.ghi_kwh_per_m2:.1f} | {site.poa_kwh_per_m2:.1f}"
            f" | {site.lossless.kwh_per_kwp:.1f} | {site.lossless.performance_ratio:.3f}"
            f" | {site.with_losses.kwh_per_kwp:.1f} | {site.with_losses.performance_ratio:.3f}"
            f" | {pvgis.kwh_per_kwp:.1f} | {pvgis.performance_ratio:.3f}"
            f" | {site.with_losses.kwh_per_kwp / pvgis.kwh_per_kwp - 1:+.1%} |"
        )
    ranges = {
        "lossless": [site.lossless.performance_ratio for site, _ in rows],
        "with losses": [site.with_losses.performance_ratio for site, _ in rows],
        "PVGIS-14%": [pvgis.performance_ratio for _, pvgis in rows],
    }
    print(
        "\nPerformance ratio ranges: "
        + "; ".join(f"{label} {min(ratios):.3f}-{max(ratios):.3f}" for label, ratios in ranges.items())
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="weather cache holding the TMYs"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    set_weather_cache(WeatherCache(args.cache_dir))
    print(
        f"PVGIS {PVGIS_API_URL}, climate years {CLIMATE_YEARS[0]}-{CLIMATE_YEARS[-1]};"
        f" PVConfig.default_4kw(), {CONFIG.capacity_kw} kW at tilt {CONFIG.tilt} and azimuth"
        f" {CONFIG.azimuth}, system_losses {CONFIG.system_losses:.4%}; PVGIS at"
        f" {PVGIS_LOSS_PERCENT}% loss; PR = AC / (in-plane irradiation x wired kWp)"
    )
    rows = [
        (measure(name, location, get_tmy_data(location)), fetch_pvgis_estimate(location))
        for name, location in SITES.items()
    ]
    print_table(rows)


if __name__ == "__main__":
    main()
