# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weather data retrieval and handling."""

import hashlib
import json
from pathlib import Path
from typing import Optional

import pandas as pd
from pvlib.iotools import get_pvgis_hourly, get_pvgis_tmy

from solar_challenge.location import Location


# Default cache directory
DEFAULT_CACHE_DIR = Path(".cache/weather")

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


class WeatherCache:
    """Cache for weather data to avoid repeated API calls.

    Stores each DataFrame as a CSV file, with a JSON sidecar recording its
    timezone and frequency, keyed by prefix, location and an optional date range.
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Directory for cache files. Defaults to .cache/weather/
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, prefix: str, location: Location,
                  start_date: Optional[pd.Timestamp] = None,
                  end_date: Optional[pd.Timestamp] = None) -> str:
        """Generate cache key from parameters."""
        key_parts = [
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
        """Retrieve cached data if available.

        Args:
            prefix: Data type prefix (e.g., 'tmy')
            location: Location for the data
            start_date: Optional start of a date-ranged entry (part of the key)
            end_date: Optional end of a date-ranged entry (part of the key)

        Returns:
            Cached DataFrame or None if not found
        """
        key = self._make_key(prefix, location, start_date, end_date)
        cache_file = self._cache_path(key)
        meta_file = self._meta_path(key)

        if cache_file.exists():
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            # Restore timezone from metadata if available
            if meta_file.exists():
                with open(meta_file) as f:
                    metadata = json.load(f)
                tz = metadata.get("timezone")
                if tz and df.index.tz is None:
                    df.index = df.index.tz_localize(tz)
                freq = metadata.get("freq")
                if freq:
                    df = df.asfreq(freq)
            return df
        return None

    def put(self, data: pd.DataFrame, prefix: str, location: Location,
            start_date: Optional[pd.Timestamp] = None,
            end_date: Optional[pd.Timestamp] = None) -> None:
        """Store data in cache.

        Args:
            data: DataFrame to cache
            prefix: Data type prefix
            location: Location for the data
            start_date: Optional start of a date-ranged entry (part of the key)
            end_date: Optional end of a date-ranged entry (part of the key)
        """
        key = self._make_key(prefix, location, start_date, end_date)
        cache_file = self._cache_path(key)
        meta_file = self._meta_path(key)

        # Save data
        data.to_csv(cache_file)

        # Save metadata including timezone info
        tz_str = str(data.index.tz) if data.index.tz else None
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
        with open(meta_file, "w") as f:
            json.dump(metadata, f)

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


# Global cache instance (can be replaced for testing)
_weather_cache: Optional[WeatherCache] = None


def get_weather_cache() -> WeatherCache:
    """Get or create the global weather cache."""
    global _weather_cache
    if _weather_cache is None:
        _weather_cache = WeatherCache()
    return _weather_cache


def set_weather_cache(cache: Optional[WeatherCache]) -> None:
    """Set the global weather cache (for testing)."""
    global _weather_cache
    _weather_cache = cache


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

    The TMY's ghi, dni and dhi are multiplied by one factor so that the year's GHI equals the mean annual GHI
    of PVGIS's 2005-2020 hourly series at the point; docs/tmy-irradiation-scaling.md has the measurements
    and the rejected alternatives. The scaled TMY is cached, and a cached TMY is returned as stored.

    Args:
        location: Location object with latitude, longitude, and altitude
        use_cache: Whether to use caching (default True)

    Returns:
        DataFrame with columns including:
        - temp_air: Ambient temperature (°C)
        - ghi: Global horizontal irradiance (W/m²)
        - dni: Direct normal irradiance (W/m²)
        - dhi: Diffuse horizontal irradiance (W/m²)
        - wind_speed: Wind speed at 10m (m/s)
        Index is DatetimeIndex in UTC.

    Raises:
        RuntimeError: If a PVGIS request fails
        ValueError: If PVGIS's TMY is not one TMY_HOURS-hour year with some GHI (from scale_tmy_to_annual_ghi)
    """
    if use_cache:
        cached_data = get_weather_cache().get("tmy", location)
        if cached_data is not None:
            return cached_data

    tmy = scale_tmy_to_annual_ghi(_fetch_pvgis_tmy(location), _fetch_mean_annual_ghi_kwh_per_m2(location))
    if use_cache:
        get_weather_cache().put(tmy, "tmy", location)
    return tmy


def _fetch_pvgis_tmy(location: Location) -> pd.DataFrame:
    """PVGIS's TMY for location, built from CLIMATE_YEARS with the horizon, in pvlib's column names."""
    try:
        tmy: pd.DataFrame = get_pvgis_tmy(
            latitude=location.latitude,
            longitude=location.longitude,
            outputformat="json",
            usehorizon=True,
            startyear=CLIMATE_YEARS[0],
            endyear=CLIMATE_YEARS[-1],
            url=PVGIS_API_URL,
            timeout=PVGIS_TIMEOUT_S,
            map_variables=True,
        )[0]

        required_columns = {"temp_air", *IRRADIANCE_COLUMNS}
        if not required_columns.issubset(tmy.columns):
            missing = required_columns - set(tmy.columns)
            raise RuntimeError(f"TMY data missing required columns: {missing}")
        return tmy

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve TMY data from PVGIS: {e}") from e


def _fetch_mean_annual_ghi_kwh_per_m2(location: Location) -> float:
    """The mean of the calendar-year GHI totals, in kWh/m², of PVGIS's CLIMATE_YEARS hourly series at location.

    The series is requested for a horizontal plane, so its poa_global is GHI.
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
        ghi = series["poa_global"]
        return float((ghi.groupby(ghi.index.year).sum() / 1000.0).mean())

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve long-term irradiation from PVGIS: {e}") from e


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
