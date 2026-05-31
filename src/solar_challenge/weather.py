# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weather data retrieval and handling."""

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pvlib.iotools import get_pvgis_tmy, get_pvgis_hourly

from solar_challenge.location import Location


# Default cache directory
DEFAULT_CACHE_DIR = Path(".cache/weather")


class WeatherCache:
    """Cache for weather data to avoid repeated API calls.

    Stores TMY and hourly data as parquet files keyed by location and date range.
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
            prefix: Data type prefix (e.g., 'tmy', 'hourly')
            location: Location for the data
            start_date: Start date (for hourly data)
            end_date: End date (for hourly data)

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
            start_date: Start date (for hourly data)
            end_date: End date (for hourly data)
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
            start_date: Start date (for hourly data)
            end_date: End date (for hourly data)

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


def get_tmy_data(
    location: Location,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Retrieve Typical Meteorological Year (TMY) data from PVGIS.

    Uses pvlib.iotools.get_pvgis_tmy() to fetch TMY data for the given location.
    Results are cached to avoid repeated API calls.

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
        RuntimeError: If PVGIS API request fails
    """
    # Check cache first
    if use_cache:
        cache = get_weather_cache()
        cached_data = cache.get("tmy", location)
        if cached_data is not None:
            return cached_data

    try:
        # PVGIS returns a tuple: (data, months_selected, inputs, metadata)
        data: tuple[pd.DataFrame, Any, Any, Any] = get_pvgis_tmy(
            latitude=location.latitude,
            longitude=location.longitude,
            outputformat="json",
            usehorizon=True,
            startyear=2005,
            endyear=2020,
            map_variables=True,  # Map to standard pvlib column names
        )
        tmy_data = data[0]

        # Ensure we have the expected columns
        required_columns = {"temp_air", "ghi", "dni", "dhi"}
        if not required_columns.issubset(tmy_data.columns):
            missing = required_columns - set(tmy_data.columns)
            raise RuntimeError(f"TMY data missing required columns: {missing}")

        # Cache the result
        if use_cache:
            cache = get_weather_cache()
            cache.put(tmy_data, "tmy", location)

        return tmy_data

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve TMY data from PVGIS: {e}") from e


def get_hourly_data(
    location: Location,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Retrieve hourly historical data from PVGIS for a date range.

    Uses pvlib.iotools.get_pvgis_hourly() to fetch hourly irradiance and
    temperature data for the specified period.

    Args:
        location: Location object with latitude, longitude, and altitude
        start_date: Start of date range (year used for query)
        end_date: End of date range (year used for query)
        use_cache: Whether to use caching (default True)

    Returns:
        DataFrame with datetime index and columns:
        - temp_air: Ambient temperature (°C)
        - ghi: Global horizontal irradiance (W/m²)
        - dni: Direct normal irradiance (W/m²)
        - dhi: Diffuse horizontal irradiance (W/m²)
        - wind_speed: Wind speed (m/s)

    Raises:
        RuntimeError: If PVGIS API request fails
    """
    # Normalize to start of year for caching purposes
    start_year = start_date.year
    end_year = end_date.year

    # Check cache first
    cache_start = pd.Timestamp(f"{start_year}-01-01")
    cache_end = pd.Timestamp(f"{end_year}-12-31")

    if use_cache:
        cache = get_weather_cache()
        cached_data = cache.get("hourly", location, cache_start, cache_end)
        if cached_data is not None:
            # Ensure timezone consistency for comparison
            data_tz = cached_data.index.tz
            filter_start = start_date
            filter_end = end_date + pd.Timedelta(days=1)
            if data_tz is not None:
                if filter_start.tz is None:
                    filter_start = filter_start.tz_localize(data_tz)
                if filter_end.tz is None:
                    filter_end = filter_end.tz_localize(data_tz)
            # Filter to requested date range
            return cached_data.loc[
                (cached_data.index >= filter_start) &
                (cached_data.index <= filter_end)
            ]

    try:
        # PVGIS hourly returns (data, inputs, metadata)
        data: tuple[pd.DataFrame, Any, Any] = get_pvgis_hourly(
            latitude=location.latitude,
            longitude=location.longitude,
            start=start_year,
            end=end_year,
            outputformat="json",
            usehorizon=True,
            pvcalculation=False,  # We just want irradiance data
            components=True,  # Get GHI, DNI, DHI separately
            map_variables=True,  # Map to standard pvlib names
        )
        hourly_data = data[0]

        # Ensure we have expected columns
        required_columns = {"ghi", "dni", "dhi"}
        if not required_columns.issubset(hourly_data.columns):
            missing = required_columns - set(hourly_data.columns)
            raise RuntimeError(f"Hourly data missing required columns: {missing}")

        # Add temp_air if not present (some PVGIS requests don't include it)
        if "temp_air" not in hourly_data.columns:
            # Use a reasonable default for UK climate
            hourly_data["temp_air"] = 10.0

        # Cache the full year data
        if use_cache:
            cache = get_weather_cache()
            cache.put(hourly_data, "hourly", location, cache_start, cache_end)

        # Filter to requested date range with timezone consistency
        data_tz = hourly_data.index.tz
        filter_start = start_date
        filter_end = end_date + pd.Timedelta(days=1)
        if data_tz is not None:
            if filter_start.tz is None:
                filter_start = filter_start.tz_localize(data_tz)
            if filter_end.tz is None:
                filter_end = filter_end.tz_localize(data_tz)
        return hourly_data.loc[
            (hourly_data.index >= filter_start) &
            (hourly_data.index <= filter_end)
        ]

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve hourly data from PVGIS: {e}") from e


def validate_irradiance_data(data: pd.DataFrame) -> None:
    """Validate irradiance data quality.

    Args:
        data: DataFrame with ghi, dni, dhi columns

    Raises:
        ValueError: If validation fails with specific issue identified
    """
    required = ["ghi", "dni", "dhi"]
    for col in required:
        if col not in data.columns:
            raise ValueError(f"Missing required column: {col}")

    for col in required:
        if (data[col] < 0).any():
            neg_count = (data[col] < 0).sum()
            raise ValueError(
                f"Column '{col}' contains {neg_count} negative values"
            )

    # GHI should approximately equal DNI * cos(zenith) + DHI
    # For simplicity, check GHI <= DNI + DHI (conservative upper bound)
    if (data["ghi"] > data["dni"] + data["dhi"] + 1).any():  # 1 W/m² tolerance
        violations = (data["ghi"] > data["dni"] + data["dhi"] + 1).sum()
        raise ValueError(
            f"GHI exceeds DNI + DHI in {violations} rows (physical impossibility)"
        )


def extract_temperature_data(
    weather_data: pd.DataFrame,
    default_wind_speed: float = 1.0
) -> pd.DataFrame:
    """Extract temperature and wind data for cell temperature modelling.

    Args:
        weather_data: DataFrame containing weather data
        default_wind_speed: Default wind speed if not available (m/s)

    Returns:
        DataFrame with columns:
        - temp_air: Ambient temperature (°C)
        - wind_speed: Wind speed (m/s)
        Aligned with input DataFrame index.
    """
    result = pd.DataFrame(index=weather_data.index)

    if "temp_air" in weather_data.columns:
        result["temp_air"] = weather_data["temp_air"]
    else:
        raise ValueError("Weather data must contain 'temp_air' column")

    if "wind_speed" in weather_data.columns:
        result["wind_speed"] = weather_data["wind_speed"]
    else:
        # Use default wind speed if not available
        result["wind_speed"] = default_wind_speed

    return result
