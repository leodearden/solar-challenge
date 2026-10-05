# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure how PVGIS's TMY compares with the real years it is built from, and what scaling it changes.

docs/tmy-irradiation-scaling.md records what this prints. From the repository root:

    uv run --locked --extra dev python scripts/measure_tmy_irradiation.py

For each of seven UK sites it fetches PVGIS's TMY and the hourly series of its climate
years from the release get_tmy_data uses, so it needs network access to PVGIS; it takes
about two to three minutes. It simulates PVConfig.default_4kw() over every real year and
over three versions of the TMY: raw, scaled as get_tmy_data scales it, and scaled month
by month, the rejected alternative. tests/unit/test_measurement_scripts.py runs measure
offline on synthetic weather; the PVGIS fetches and the full run are not part of the test
suite.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pvlib.iotools import get_pvgis_hourly, get_pvgis_tmy

from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, simulate_pv_output
from solar_challenge.weather import (
    CLIMATE_YEARS,
    IRRADIANCE_COLUMNS,
    PVGIS_API_URL,
    PVGIS_TIMEOUT_S,
    PVGIS_TMY_REQUEST,
    scale_tmy_to_annual_ghi,
)

# Pinned: a site's factor depends on the exact point (Glasgow read 0.978 at a nearby one).
SITES: Mapping[str, Location] = {
    "Bristol": Location.bristol(),
    "London": Location(latitude=51.5074, longitude=-0.1278),
    "Penzance": Location(latitude=50.1188, longitude=-5.5376),
    "Eastbourne": Location(latitude=50.7684, longitude=0.2903),
    "Belfast": Location(latitude=54.5973, longitude=-5.9301),
    "Glasgow": Location(latitude=55.8642, longitude=-4.2518),
    "Plymouth": Location(latitude=50.3755, longitude=-4.1427),
}
CONFIG = PVConfig.default_4kw()
DARKER_HALF = len(CLIMATE_YEARS) // 2


@dataclass(frozen=True)
class TmyMonth:
    """One month of the TMY against the same calendar month of every real year."""

    month: int
    source_year: int
    ghi_kwh_per_m2: float
    rank: int
    vs_mean: float


@dataclass(frozen=True)
class SiteMeasurement:
    """Every figure measured at one site; AC in kWh, GHI totals in kWh/m², peaks in W/m²."""

    name: str
    location: Location
    tmy_ghi: float
    year_ghi: pd.Series
    year_ac: pd.Series
    ac_by_tmy: Mapping[str, float]
    peak_by_tmy: Mapping[str, float]
    record_peak: float
    scaled_hours_above_record: int
    months: Sequence[TmyMonth]

    @property
    def factor(self) -> float:
        return float(self.year_ghi.mean()) / self.tmy_ghi

    def ac_vs_real_years(self, tmy: str) -> float:
        return self.ac_by_tmy[tmy] / float(self.year_ac.mean()) - 1


def fetch_tmy(location: Location) -> tuple[pd.DataFrame, dict[int, int]]:
    """PVGIS's TMY requested with get_tmy_data's PVGIS_TMY_REQUEST, and the real year each month comes from."""
    tmy, meta = get_pvgis_tmy(latitude=location.latitude, longitude=location.longitude, **PVGIS_TMY_REQUEST)
    return tmy, {selected["month"]: selected["year"] for selected in meta["months_selected"]}


def fetch_real_years(location: Location) -> pd.DataFrame:
    """PVGIS's hourly weather over the climate years, decomposed into ghi, dni and dhi.

    At surface_tilt=0, poa_direct and poa_sky_diffuse are beam and diffuse horizontal; DNI is
    beam horizontal over the sine of the solar elevation, and 0 with the sun down.
    """
    series = get_pvgis_hourly(
        latitude=location.latitude,
        longitude=location.longitude,
        start=CLIMATE_YEARS[0],
        end=CLIMATE_YEARS[-1],
        components=True,
        surface_tilt=0,
        usehorizon=True,
        url=PVGIS_API_URL,
        timeout=PVGIS_TIMEOUT_S,
        map_variables=True,
    )[0]
    sun_up = series["solar_elevation"] > 0
    sine_of_elevation = np.sin(np.radians(series["solar_elevation"].where(sun_up)))
    return pd.DataFrame(
        {
            "ghi": series["poa_direct"] + series["poa_sky_diffuse"],
            "dni": (series["poa_direct"] / sine_of_elevation).where(sun_up, 0.0),
            "dhi": series["poa_sky_diffuse"],
            "temp_air": series["temp_air"],
            "wind_speed": series["wind_speed"],
        }
    )


def annual_ac_kwh(location: Location, weather: pd.DataFrame) -> float:
    """CONFIG's AC energy over hourly weather."""
    return float(simulate_pv_output(CONFIG, location, weather).sum())


def ghi_by_month(weather: pd.DataFrame) -> pd.Series:
    """The GHI total of each calendar month in weather, in kWh/m²."""
    return weather["ghi"].groupby(weather.index.month).sum() / 1000.0


def scale_tmy_by_month(tmy: pd.DataFrame, month_mean_ghi: pd.Series) -> pd.DataFrame:
    """The TMY with each month's ghi, dni and dhi scaled to that month's mean GHI over the real years."""
    factor = (month_mean_ghi / ghi_by_month(tmy)).reindex(tmy.index.month).to_numpy()
    return tmy.assign(**{column: tmy[column] * factor for column in IRRADIANCE_COLUMNS})


def tmy_months(tmy: pd.DataFrame, source_years: Mapping[int, int], year_month_ghi: pd.DataFrame) -> list[TmyMonth]:
    """Each TMY month's GHI, its source month's rank among the real years (1 = darkest), and its deviation from their mean."""
    tmy_month_ghi = ghi_by_month(tmy)
    months = []
    for month, source_year in sorted(source_years.items()):
        real = year_month_ghi[month]
        months.append(
            TmyMonth(
                month=month,
                source_year=source_year,
                ghi_kwh_per_m2=float(tmy_month_ghi[month]),
                rank=int((real < real[source_year]).sum()) + 1,
                vs_mean=float(tmy_month_ghi[month] / real.mean()) - 1,
            )
        )
    return months


def measure(
    name: str,
    location: Location,
    tmy: pd.DataFrame,
    source_years: Mapping[int, int],
    real_years: pd.DataFrame,
) -> SiteMeasurement:
    """Measure one site's TMY, whose month m comes from real year source_years[m], against the hourly weather of its real years."""
    ghi = real_years["ghi"]
    year_ghi = ghi.groupby(ghi.index.year).sum() / 1000.0
    year_month_ghi = (ghi.groupby([ghi.index.year, ghi.index.month]).sum() / 1000.0).unstack()
    year_ac = pd.Series(
        {year: annual_ac_kwh(location, real_years[real_years.index.year == year]) for year in CLIMATE_YEARS}
    )
    tmys = {
        "raw": tmy,
        "annual": scale_tmy_to_annual_ghi(tmy, float(year_ghi.mean())),
        "monthly": scale_tmy_by_month(tmy, year_month_ghi.mean()),
    }
    record_peak = float(ghi.max())
    return SiteMeasurement(
        name=name,
        location=location,
        tmy_ghi=float(tmy["ghi"].sum()) / 1000.0,
        year_ghi=year_ghi,
        year_ac=year_ac,
        ac_by_tmy={label: annual_ac_kwh(location, version) for label, version in tmys.items()},
        peak_by_tmy={label: float(version["ghi"].max()) for label, version in tmys.items()},
        record_peak=record_peak,
        scaled_hours_above_record=int((tmys["annual"]["ghi"] > record_peak).sum()),
        months=tmy_months(tmy, source_years, year_month_ghi),
    )


def print_site(site: SiteMeasurement) -> None:
    """Print one site's figures, its TMY's months included."""
    print(f"\n== {site.name} ({site.location.latitude}, {site.location.longitude}) ==")
    print(
        f"GHI, kWh/m²: TMY {site.tmy_ghi:.1f}; real years {site.year_ghi.min():.1f}-{site.year_ghi.max():.1f}"
        f" (mean {site.year_ghi.mean():.3f}); factor k {site.factor:.5f}"
    )
    tmy_ac = "; ".join(
        f"{label} TMY {ac:.0f} ({site.ac_vs_real_years(label):+.1%})" for label, ac in site.ac_by_tmy.items()
    )
    print(
        f"AC, kWh: real years {site.year_ac.min():.0f}-{site.year_ac.max():.0f}"
        f" (mean {site.year_ac.mean():.0f}); {tmy_ac}"
    )
    tmy_peaks = "; ".join(f"{label} TMY {peak:.1f}" for label, peak in site.peak_by_tmy.items())
    print(
        f"Peak GHI, W/m²: {tmy_peaks}; record {site.record_peak:.1f};"
        f" annual-scaled hours above the record: {site.scaled_hours_above_record}"
    )
    print("TMY months: month, source year, GHI kWh/m², rank (1 = darkest), vs the real years' mean")
    for month in site.months:
        print(
            f"  {month.month:2d}  {month.source_year}  {month.ghi_kwh_per_m2:6.1f}  {month.rank:2d}"
            f"  {month.vs_mean:+.1%}"
        )
    darker = sum(month.rank <= DARKER_HALF for month in site.months)
    print(f"Months from the darker half (ranks 1-{DARKER_HALF}): {darker} of {len(site.months)}")


def print_summary(sites: Sequence[SiteMeasurement]) -> None:
    """Print the sites side by side, as a markdown table."""
    print("\n| Site (lat, lon) | k | raw TMY | annual scale | monthly scale | peak GHI raw / annual / monthly / record |")
    print("|---|---|---|---|---|---|")
    for site in sites:
        peaks = " / ".join(f"{site.peak_by_tmy[label]:.0f}" for label in ("raw", "annual", "monthly"))
        print(
            f"| {site.name} ({site.location.latitude}, {site.location.longitude}) | {site.factor:.3f}"
            f" | {site.ac_vs_real_years('raw'):+.1%} | {site.ac_vs_real_years('annual'):+.1%}"
            f" | {site.ac_vs_real_years('monthly'):+.1%} | {peaks} / {site.record_peak:.0f} |"
        )


def main() -> None:
    print(
        f"PVGIS {PVGIS_API_URL}, climate years {CLIMATE_YEARS[0]}-{CLIMATE_YEARS[-1]},"
        f" PVConfig.default_4kw(); AC deviations are against the mean of the real years"
    )
    sites = []
    for name, location in SITES.items():
        tmy, source_years = fetch_tmy(location)
        site = measure(name, location, tmy, source_years, fetch_real_years(location))
        print_site(site)
        sites.append(site)
    print_summary(sites)


if __name__ == "__main__":
    main()
