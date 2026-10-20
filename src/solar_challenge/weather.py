# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weather data retrieval and handling."""

import calendar
import hashlib
import json
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Protocol

import pandas as pd
from pvlib.iotools import get_pvgis_hourly, get_pvgis_tmy

from solar_challenge.location import Location


# Default cache directory
DEFAULT_CACHE_DIR = Path(".cache/weather")

CACHE_DIR_VARIABLE = "SOLAR_CHALLENGE_WEATHER_CACHE_DIR"
"""The environment variable naming the directory WeatherCache() uses when given none."""

IRRADIANCE_COLUMNS = ("ghi", "dni", "dhi")
"""The TMY's irradiance columns, in W/m²: global horizontal, direct normal and diffuse horizontal."""

TMY_HOURS = 8760
"""The rows of PVGIS's TMY as pvlib returns it: one hourly year, coerced to the non-leap 1990."""

PVGIS_API_URL = "https://re.jrc.ec.europa.eu/api/v5_3/"
"""The one PVGIS release, v5.3 (PVGIS-SARAH3 radiation), that both the TMY and its long-term mean come from."""

CLIMATE_YEARS = range(2005, 2021)
"""The years PVGIS builds the TMY from, and the years its mean annual GHI is taken over."""

PVGIS_TIMEOUT_S = 120
"""Seconds to wait for each PVGIS response; the 2005-2020 hourly series takes about 9 s to arrive."""

PVGIS_TMY_REQUEST: Mapping[str, object] = MappingProxyType(
    {
        "outputformat": "json",
        "usehorizon": True,
        "startyear": CLIMATE_YEARS[0],
        "endyear": CLIMATE_YEARS[-1],
        "url": PVGIS_API_URL,
        "timeout": PVGIS_TIMEOUT_S,
        "map_variables": True,
    }
)
"""The arguments of PvgisTmy's get_pvgis_tmy request, except the point's latitude and longitude."""


class WeatherDataError(RuntimeError):
    """PVGIS could not supply usable weather for a point: a request failed, or what it returned could not be used."""


@contextmanager
def _staged_beside(entry_file: Path) -> Iterator[Path]:
    """A fresh path beside entry_file, for the block to write entry_file's replacement to and os.replace onto it.

    Beside it, so that the replace is atomic. The block creates the file, so it has the mode a plain write
    gives, which tempfile's owner-only files would not. If the block raises, KeyboardInterrupt included, the
    path is removed; after an os.replace there is nothing left to remove.
    """
    staged = entry_file.with_name(f".{entry_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        yield staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _require_timezone_name(name: str) -> None:
    """Refuse a name pandas resolves to no timezone: put records a frame's timezone as its str, and get restores the timezone from it."""
    try:
        pd.DatetimeIndex([], tz="UTC").tz_convert(name)
    except (LookupError, ValueError) as e:
        raise ValueError(
            "A cached frame's timezone must have a str that names it, such as 'Europe/London', 'UTC' or "
            f"'UTC+01:00', for WeatherCache to restore it, got {name!r}"
        ) from e


class WeatherCache:
    """Cache for weather data to avoid repeated API calls.

    Stores each DataFrame as a CSV file, with a JSON sidecar recording its
    timezone and frequency, keyed by prefix, location and an optional date range.
    """

    cache_dir: Path

    _KEY_VERSION = 2
    """Part of every key: bump it whenever what an entry means changes, so that older entries are never read.

    2: PvgisTmy.get caches the TMY scaled to the 2005-2020 mean annual GHI (docs/tmy-irradiation-scaling.md).
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Directory for cache files. Given none, the directory CACHE_DIR_VARIABLE names when it is
                set and non-empty, else DEFAULT_CACHE_DIR, under the working directory
        """
        if cache_dir is None:
            cache_dir = Path(os.environ.get(CACHE_DIR_VARIABLE) or DEFAULT_CACHE_DIR)
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, prefix: str, location: Location,
                  start_date: Optional[pd.Timestamp] = None,
                  end_date: Optional[pd.Timestamp] = None) -> str:
        """Generate cache key from parameters."""
        key_parts = [
            f"v{self._KEY_VERSION}",
            prefix,
            f"{location.latitude:.4f}",
            f"{location.longitude:.4f}",
        ]
        if start_date is not None:
            key_parts.append(start_date.strftime("%Y%m%d"))
        if end_date is not None:
            key_parts.append(end_date.strftime("%Y%m%d"))
        key_str = "_".join(key_parts)
        # Use hash for shorter filename
        key_hash = hashlib.md5(key_str.encode()).hexdigest()[:12]
        return f"{prefix}_{key_hash}"

    def _cache_path(self, key: str) -> Path:
        """Get path for cache file."""
        return self.cache_dir / f"{key}.csv"

    def _meta_path(self, key: str) -> Path:
        """Get path for metadata file."""
        return self.cache_dir / f"{key}.meta.json"

    def get(self, prefix: str, location: Location,
            start_date: Optional[pd.Timestamp] = None,
            end_date: Optional[pd.Timestamp] = None) -> Optional[pd.DataFrame]:
        """Retrieve the frame put stored under the key: its values exactly, and its index in the timezone and frequency it was put in.

        Args:
            prefix: Data type prefix (e.g., 'tmy')
            location: Location for the data
            start_date: Optional start of a date-ranged entry (part of the key)
            end_date: Optional end of a date-ranged entry (part of the key)

        Returns:
            The cached DataFrame, or None if not found

        Raises:
            ValueError: If the entry records its timezone as a str that names none; put refuses such a timezone
        """
        key = self._make_key(prefix, location, start_date, end_date)
        cache_file = self._cache_path(key)
        meta_file = self._meta_path(key)

        if cache_file.exists():
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True, float_precision="round_trip")
            # Restore timezone from metadata if available
            if meta_file.exists():
                with open(meta_file) as f:
                    metadata = json.load(f)
                tz = metadata.get("timezone")
                if tz:
                    _require_timezone_name(tz)
                    df.index = pd.to_datetime(df.index, utc=True).tz_convert(tz)
                freq = metadata.get("freq")
                if freq:
                    df = df.asfreq(freq)
            return df
        return None

    def put(self, data: pd.DataFrame, prefix: str, location: Location,
            start_date: Optional[pd.Timestamp] = None,
            end_date: Optional[pd.Timestamp] = None) -> None:
        """Store data in cache, replacing any entry under the same key whole.

        A get racing this put, in any thread or process, finds the previous entry (or none) or this one,
        never part of either. A put that raises part-way, as on Ctrl-C, leaves the previous entry, or none,
        as it was. Both hold while every put under one key stores the same timezone and frequency, since
        the CSV and its metadata are replaced one after the other.

        Args:
            data: DataFrame to cache
            prefix: Data type prefix
            location: Location for the data
            start_date: Optional start of a date-ranged entry (part of the key)
            end_date: Optional end of a date-ranged entry (part of the key)

        Raises:
            ValueError: If data's index is in a timezone get could not restore from its str, such as a dateutil
                zone; nothing is then written
        """
        key = self._make_key(prefix, location, start_date, end_date)
        cache_file = self._cache_path(key)
        meta_file = self._meta_path(key)

        tz_str = str(data.index.tz) if data.index.tz else None
        if tz_str is not None:
            _require_timezone_name(tz_str)
        freq_str = data.index.freqstr if hasattr(data.index, "freqstr") and data.index.freqstr else None
        metadata = {
            "prefix": prefix,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "timezone": tz_str,
            "freq": freq_str,
        }

        with _staged_beside(cache_file) as staged_csv, _staged_beside(meta_file) as staged_meta:
            data.to_csv(staged_csv)
            staged_meta.write_text(json.dumps(metadata))
            # Meta first: get takes the CSV as the entry, so a get that finds the new CSV also finds the new
            # meta. A put killed between the two replaces leaves a miss in an empty cache, else the old CSV
            # under the new meta (see the caveat in the docstring).
            os.replace(staged_meta, meta_file)
            os.replace(staged_csv, cache_file)

    def clear(self) -> int:
        """Clear all cached data.

        Returns:
            Number of files removed
        """
        count = 0
        if self.cache_dir.exists():
            for file in self.cache_dir.glob("*"):
                file.unlink()
                count += 1
        return count

    def invalidate(self, prefix: str, location: Location,
                   start_date: Optional[pd.Timestamp] = None,
                   end_date: Optional[pd.Timestamp] = None) -> bool:
        """Remove specific cached data.

        Args:
            prefix: Data type prefix
            location: Location for the data
            start_date: Optional start of a date-ranged entry (part of the key)
            end_date: Optional end of a date-ranged entry (part of the key)

        Returns:
            True if cache entry was removed, False if not found
        """
        key = self._make_key(prefix, location, start_date, end_date)
        cache_file = self._cache_path(key)
        meta_file = self._meta_path(key)
        removed = False
        if cache_file.exists():
            cache_file.unlink()
            removed = True
        if meta_file.exists():
            meta_file.unlink()
        return removed


class WeatherProvider(Protocol):
    """Supplies the hourly weather a simulation at a location runs on."""

    def get(self, location: Location) -> pd.DataFrame:
        """One year of hourly weather for location: temp_air, ghi, dni and dhi at least, on a DatetimeIndex."""
        ...


@dataclass(frozen=True)
class PvgisTmy:
    """PVGIS's TMY for each location, scaled to the point's 2005-2020 mean annual GHI (docs/tmy-irradiation-scaling.md): read from cache, else fetched and put there; with no cache, fetched on every get."""

    cache: WeatherCache | None

    def get(self, location: Location) -> pd.DataFrame:
        """The scaled TMY for location, as its cache holds it, else as fetched from PVGIS.

        Its ghi, dni and dhi are those of PVGIS's TMY multiplied by one factor, so that the year's GHI equals
        the mean annual GHI of PVGIS's 2005-2020 hourly series at the point.

        Returns:
            DataFrame with columns including:
            - temp_air: Ambient temperature (°C)
            - ghi: Global horizontal irradiance (W/m²)
            - dni: Direct normal irradiance (W/m²)
            - dhi: Diffuse horizontal irradiance (W/m²)
            - wind_speed: Wind speed at 10m (m/s)
            Index is a DatetimeIndex in UTC, as PVGIS supplies it; a TMY seeded with WeatherCache.put comes back in
            the timezone it was put in.

        Raises:
            WeatherDataError: If a PVGIS request fails, its TMY lacks a required column, its hourly series lacks
                or repeats hours of a climate year, or scale_tmy_to_annual_ghi refuses what PVGIS returned, its
                ValueError then being the cause; nothing is then put. A WeatherDataError is a RuntimeError
        """
        if self.cache is None:
            return _fetch_scaled_tmy(location)
        cached = self.cache.get("tmy", location)
        if cached is not None:
            return cached
        tmy = _fetch_scaled_tmy(location)
        self.cache.put(tmy, "tmy", location)
        return tmy


@dataclass(frozen=True, eq=False)
class PrefetchedWeather:
    """Weather already in memory for the locations it holds; it pickles, so a worker reads no cache and no network.

    The locations it holds are fixed at construction. Its frames are the ones it is given, not copies, so a frame
    changed in place is changed for every later get.
    """

    frames: Mapping[Location, pd.DataFrame]

    def __post_init__(self) -> None:
        """Hold frames in a read-only mapping of its own, so that no later change adds or removes a location."""
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))

    def __reduce__(self) -> tuple[type["PrefetchedWeather"], tuple[dict[Location, pd.DataFrame]]]:
        """Rebuild through the constructor from a dict of the frames, since a mappingproxy does not pickle."""
        return (type(self), (dict(self.frames),))

    def get(self, location: Location) -> pd.DataFrame:
        """The frame held for location itself; LookupError naming location and the locations held, for any other."""
        if location not in self.frames:
            raise LookupError(
                f"A PrefetchedWeather answers only for the locations it holds: asked for {location!r}, "
                f"it holds {list(self.frames)!r}"
            )
        return self.frames[location]

    @classmethod
    def fetch(cls, weather: WeatherProvider, locations: Iterable[Location]) -> "PrefetchedWeather":
        """weather.get once for each distinct location, in this process, in first-seen order."""
        return cls({location: weather.get(location) for location in dict.fromkeys(locations)})


# Global cache instance (can be replaced for testing)
_weather_cache: Optional[WeatherCache] = None


def get_weather_cache() -> WeatherCache:
    """The cache installed with set_weather_cache, else a new WeatherCache(), so that CACHE_DIR_VARIABLE is read at each call."""
    return WeatherCache() if _weather_cache is None else _weather_cache


def set_weather_cache(cache: Optional[WeatherCache]) -> None:
    """Set the global weather cache (for testing)."""
    global _weather_cache
    _weather_cache = cache


def default_weather() -> PvgisTmy:
    """The weather a composition root uses when it is given none.

    Until the surface bump it is PvgisTmy over get_weather_cache(), so it reads the cache set_weather_cache
    installs. At the bump it becomes PvgisTmy(WeatherCache()); docs/prds/weather-as-explicit-input.md says why,
    in its decisions 3 and 9.
    """
    return PvgisTmy(get_weather_cache())


def scale_tmy_to_annual_ghi(tmy: pd.DataFrame, annual_ghi_kwh_per_m2: float) -> pd.DataFrame:
    """A copy of tmy whose ghi, dni and dhi are multiplied by one factor, so its GHI sums to annual_ghi_kwh_per_m2.

    tmy must be one TMY year of TMY_HOURS hourly rows with some GHI, and the target positive; else ValueError.
    """
    if len(tmy) != TMY_HOURS:
        raise ValueError(f"the TMY must be one year of {TMY_HOURS} hourly rows, got {len(tmy)}")
    if annual_ghi_kwh_per_m2 <= 0:
        raise ValueError(f"annual_ghi_kwh_per_m2 must be positive, got {annual_ghi_kwh_per_m2}")
    tmy_annual_ghi_kwh_per_m2 = tmy["ghi"].sum() / 1000.0
    if tmy_annual_ghi_kwh_per_m2 <= 0:
        raise ValueError(f"the TMY's annual ghi total must be positive, got {tmy_annual_ghi_kwh_per_m2} kWh/m²")
    factor = annual_ghi_kwh_per_m2 / tmy_annual_ghi_kwh_per_m2
    return tmy.assign(**{column: tmy[column] * factor for column in IRRADIANCE_COLUMNS})


def get_tmy_data(
    location: Location,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Retrieve PVGIS's Typical Meteorological Year (TMY) for location, scaled to the point's long-term mean GHI.

    It is default_weather()'s get, or PvgisTmy(None)'s when use_cache is False; PvgisTmy.get says what it
    returns and raises.

    Args:
        location: Location object with latitude, longitude, and altitude
        use_cache: Whether to use caching (default True)
    """
    return (default_weather() if use_cache else PvgisTmy(None)).get(location)


def _fetch_scaled_tmy(location: Location) -> pd.DataFrame:
    """PVGIS's TMY for location, scaled to the mean annual GHI of PVGIS's CLIMATE_YEARS hourly series at location."""
    pvgis_tmy = _fetch_pvgis_tmy(location)
    annual_ghi_kwh_per_m2 = _fetch_mean_annual_ghi_kwh_per_m2(location)
    try:
        return scale_tmy_to_annual_ghi(pvgis_tmy, annual_ghi_kwh_per_m2)
    except ValueError as e:
        raise WeatherDataError(f"Failed to scale PVGIS's TMY to its long-term mean GHI: {e}") from e


def _fetch_pvgis_tmy(location: Location) -> pd.DataFrame:
    """PVGIS's TMY for location, requested with PVGIS_TMY_REQUEST, so in pvlib's column names."""
    try:
        tmy: pd.DataFrame = get_pvgis_tmy(
            latitude=location.latitude, longitude=location.longitude, **PVGIS_TMY_REQUEST
        )[0]

        required_columns = {"temp_air", *IRRADIANCE_COLUMNS}
        if not required_columns.issubset(tmy.columns):
            missing = required_columns - set(tmy.columns)
            raise ValueError(f"TMY data missing required columns: {missing}")
        return tmy

    except Exception as e:
        raise WeatherDataError(f"Failed to retrieve TMY data from PVGIS: {e}") from e


def _fetch_mean_annual_ghi_kwh_per_m2(location: Location) -> float:
    """The mean of the calendar-year GHI totals, in kWh/m², of PVGIS's CLIMATE_YEARS hourly series at location.

    The series is requested for a horizontal plane, so its poa_global is GHI. A series that lacks or repeats
    hours of any of CLIMATE_YEARS raises WeatherDataError naming those years, since its mean would be skewed.
    """
    try:
        series: pd.DataFrame = get_pvgis_hourly(
            latitude=location.latitude,
            longitude=location.longitude,
            start=CLIMATE_YEARS[0],
            end=CLIMATE_YEARS[-1],
            components=False,
            surface_tilt=0,
            usehorizon=True,
            url=PVGIS_API_URL,
            timeout=PVGIS_TIMEOUT_S,
            map_variables=True,
        )[0]
        ghi_by_year = series["poa_global"].groupby(series.index.year)
        hours_by_year = ghi_by_year.size()
        incomplete_years = [year for year in CLIMATE_YEARS if hours_by_year.get(year) != _hours_in(year)]
        if incomplete_years:
            raise ValueError(f"the hourly series lacks or repeats hours of {incomplete_years}")
        return float((ghi_by_year.sum() / 1000.0).mean())

    except Exception as e:
        raise WeatherDataError(f"Failed to retrieve long-term irradiation from PVGIS: {e}") from e


def _hours_in(year: int) -> int:
    """The number of hours in calendar year year."""
    return 24 * (366 if calendar.isleap(year) else 365)


def align_tmy_to_index(tmy: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Map a TMY series onto index by UTC time of year.

    Each timestamp of index takes the TMY value from the same UTC month, day,
    hour and minute, so a TMY hour lands on the same instant whatever the
    index's timezone or DST state; pvlib places the sun at the TMY's UTC
    instants. A naive index on either side is read as UTC, following pvlib's
    convention. A timestamp on a UTC 29 February with no TMY match takes the
    TMY value at the same UTC time on 28 February, so against a non-leap TMY
    year a leap year's extra day repeats the day before it, while a TMY with
    part of 29 February keeps that part. Any other timestamp with no match
    maps to 0.0. Where the TMY repeats a UTC time of year, the later value
    wins. The result carries index and the TMY series' name.
    """
    lookup = tmy.set_axis(_utc_time_of_year_keys(tmy.index))
    lookup = lookup[~lookup.index.duplicated(keep="last")]
    aligned = lookup.reindex(_tmy_keys_to_read(index, lookup.index), fill_value=0.0)
    return pd.Series(aligned.to_numpy(), index=index, name=tmy.name)


def _tmy_keys_to_read(index: pd.DatetimeIndex, tmy_keys: pd.Index) -> pd.Index:
    """The UTC time-of-year key each timestamp of index reads from the TMY.

    That is its own key, unless the timestamp is on a UTC 29 February and the TMY lacks that key;
    then it is the key of the same UTC time on 28 February.
    """
    utc = _in_utc(index)
    own_keys = _utc_time_of_year_keys(utc)
    reads_28_february = (utc.month == 2) & (utc.day == 29) & ~own_keys.isin(tmy_keys)
    return own_keys.where(~reads_28_february, _utc_time_of_year_keys(utc - pd.Timedelta(days=1)))


def _utc_time_of_year_keys(index: pd.DatetimeIndex) -> pd.Index:
    """Each timestamp's UTC month, day, hour and minute packed as MMDDhhmm; a naive index is read as UTC."""
    utc = _in_utc(index)
    return ((utc.month * 100 + utc.day) * 100 + utc.hour) * 100 + utc.minute


def _in_utc(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The index in UTC; a naive index is read as UTC."""
    return index if index.tz is None else index.tz_convert("UTC")
