"""Tests for weather data handling."""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest
import pandas as pd
import numpy as np
from unittest.mock import call, patch

from solar_challenge.weather import (
    PVGIS_TMY_REQUEST,
    WeatherCache,
    WeatherDataError,
    get_tmy_data,
    scale_tmy_to_annual_ghi,
)
from solar_challenge.location import Location
from tests._synthetic_weather import synthetic_june_weather

PRE_SCALING_BRISTOL_TMY_STEM = "tmy_5dc8c8bca218"
"""The file stem of Bristol's cached TMY before task 285, when the cache held PVGIS's TMY unscaled."""


@pytest.fixture
def sample_index():
    """Create sample datetime index."""
    return pd.date_range("2024-01-01", periods=24, freq="h")


@pytest.fixture
def pvgis_tmy():
    """A TMY shaped like PVGIS's as pvlib returns it: one non-leap 1990 of hourly UTC rows, its irradiance varying day to day."""
    utc_1990 = pd.date_range("1990-01-01", periods=8760, freq="h", tz="UTC")
    return (
        synthetic_june_weather("1990-01-01", irradiance_scale_per_day=np.linspace(0.2, 1.0, 365))
        .set_axis(utc_1990)
        .assign(relative_humidity=80.0)
    )


@pytest.fixture
def pvgis_hourly_series():
    """PVGIS's 2005-2020 hourly series as get_pvgis_hourly returns it for components=False at surface_tilt=0.

    Its poa_global is then GHI. PVGIS stamps each hour HH:10 UTC. Calendar year Y's GHI sums to
    1000 + 10·(Y − 2005) kWh/m², so the 16 years' mean is 1075.0 kWh/m² and no single year equals it.
    """
    index = pd.date_range("2005-01-01 00:10", "2020-12-31 23:10", freq="h", tz="UTC")
    hours_after_six = index.hour + index.minute / 60 - 6
    daylight = pd.Series(np.sin(hours_after_six / 12 * np.pi), index=index).clip(lower=0.0)
    year_ghi_wh_per_m2 = 1000.0 * (1000 + 10 * (index.year.to_numpy() - 2005))
    return pd.DataFrame(
        {
            "poa_global": daylight / daylight.groupby(index.year).transform("sum") * year_ghi_wh_per_m2,
            "solar_elevation": 60.0 * daylight,
            "temp_air": 10.0,
            "wind_speed": 3.0,
            "Int": 0,
        },
        index=index,
    )


@pytest.fixture
def pvgis_requests(pvgis_tmy, pvgis_hourly_series):
    """weather.py's two PVGIS requests, patched: .tmy answers pvgis_tmy and .hourly pvgis_hourly_series.

    Each answers as pvlib does, with a (data, metadata) pair.
    """
    with (
        patch("solar_challenge.weather.get_pvgis_tmy", return_value=(pvgis_tmy, {})) as tmy,
        patch("solar_challenge.weather.get_pvgis_hourly", return_value=(pvgis_hourly_series, {})) as hourly,
    ):
        yield SimpleNamespace(tmy=tmy, hourly=hourly)


class _Interrupted(BaseException):
    """Raised part-way through a put, as Ctrl-C's KeyboardInterrupt would be."""


class _InterruptsWhenWritten:
    """A cell value that raises _Interrupted when the csv writer turns it into text, as it writes the cell's row."""

    def __str__(self):
        raise _Interrupted()


def _interrupted_half_way(frame):
    """frame, but putting it raises _Interrupted once about half of its rows have been written."""
    temp_air = frame["temp_air"].astype(object)
    temp_air.iloc[len(frame) // 2] = _InterruptsWhenWritten()
    return frame.assign(temp_air=temp_air)


class TestWeatherCache:
    """Test weather data caching (LOC-004)."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create temporary cache directory."""
        cache_dir = tmp_path / "weather_cache"
        cache_dir.mkdir()
        return cache_dir

    @pytest.fixture
    def cache(self, temp_cache_dir):
        """Create cache with temporary directory."""
        return WeatherCache(cache_dir=temp_cache_dir)

    @pytest.fixture
    def bristol(self):
        """Bristol location fixture."""
        return Location.bristol()

    @pytest.fixture
    def sample_weather_data(self, sample_index):
        """Sample weather data for caching."""
        return pd.DataFrame({
            "ghi": np.linspace(0, 800, 24),
            "dni": np.linspace(0, 600, 24),
            "dhi": np.linspace(0, 300, 24),
            "temp_air": np.linspace(5, 15, 24),
        }, index=sample_index)

    def test_cache_directory_created(self, temp_cache_dir):
        """Cache directory is created if it doesn't exist."""
        new_cache_dir = temp_cache_dir / "new_cache"
        cache = WeatherCache(cache_dir=new_cache_dir)
        assert new_cache_dir.exists()

    def test_put_and_get_tmy(self, cache, bristol, sample_weather_data):
        """Data can be stored and retrieved from cache."""
        cache.put(sample_weather_data, "tmy", bristol)
        result = cache.get("tmy", bristol)
        assert result is not None
        pd.testing.assert_frame_equal(result, sample_weather_data)

    def test_get_returns_none_for_missing(self, cache, bristol):
        """Get returns None when data not in cache."""
        result = cache.get("tmy", bristol)
        assert result is None

    def test_put_and_get_with_date_range(self, cache, bristol, sample_weather_data):
        """An entry keyed by a date range can be stored and retrieved."""
        start = pd.Timestamp("2023-01-01")
        end = pd.Timestamp("2023-12-31")
        cache.put(sample_weather_data, "dated", bristol, start, end)
        result = cache.get("dated", bristol, start, end)
        assert result is not None
        pd.testing.assert_frame_equal(result, sample_weather_data)

    def test_get_returns_a_scaled_tmy_bit_for_bit(self, cache, bristol, pvgis_tmy):
        """get returns every value put stored exactly, so a TMY served from the cache is the TMY that was fetched."""
        scaled = scale_tmy_to_annual_ghi(pvgis_tmy, 1069.5)
        cache.put(scaled, "tmy", bristol)

        pd.testing.assert_frame_equal(cache.get("tmy", bristol), scaled, check_exact=True)

    @pytest.mark.parametrize(
        ("start", "tz"),
        [
            pytest.param("2024-03-30", "UTC", id="UTC across the March clock change"),
            pytest.param("2024-06-21", "Europe/London", id="Europe/London at one offset"),
            pytest.param("2024-03-30", "Europe/London", id="Europe/London across the March clock change"),
            pytest.param("2024-10-26", "Europe/London", id="Europe/London across the October clock change"),
            pytest.param("2024-06-21", "UTC+01:00", id="a fixed UTC offset"),
            pytest.param("2024-03-30", None, id="naive"),
        ],
    )
    def test_get_returns_the_index_put_stored(self, cache, bristol, start, tz):
        """get returns the frame on the index put stored: its instants, its timezone and its frequency."""
        index = pd.date_range(start, periods=48, freq="h", tz=tz)
        frame = pd.DataFrame({"ghi": np.linspace(0.0, 870.0, len(index))}, index=index)
        cache.put(frame, "tmy", bristol)

        pd.testing.assert_frame_equal(cache.get("tmy", bristol), frame, check_exact=True)

    @pytest.mark.parametrize(
        "tz",
        [
            pytest.param("dateutil/Europe/London", id="a dateutil zone"),
            pytest.param(timezone(timedelta(hours=1), "BST"), id="a named fixed offset"),
        ],
    )
    def test_put_refuses_an_index_in_a_timezone_get_could_not_restore(self, cache, bristol, tz):
        """put refuses a frame indexed in a timezone whose str, from which get restores it, names none: its
        ValueError names that str, and put leaves no file, so a get finds no entry."""
        index = pd.date_range("2024-06-21", periods=48, freq="h", tz=tz)
        frame = pd.DataFrame({"ghi": np.linspace(0.0, 870.0, len(index))}, index=index)

        with pytest.raises(ValueError, match=re.escape(str(index.tz))):
            cache.put(frame, "tmy", bristol)

        assert list(cache.cache_dir.iterdir()) == []
        assert cache.get("tmy", bristol) is None

    def test_get_refuses_an_entry_recording_a_timezone_it_could_not_restore(self, cache, bristol):
        """get refuses an entry recording its timezone as a str that names none, a dateutil zone's say, which put
        refuses to record: its ValueError names that str."""
        index = pd.date_range("2024-06-21", periods=48, freq="h", tz="Europe/London")
        cache.put(pd.DataFrame({"ghi": np.linspace(0.0, 870.0, len(index))}, index=index), "tmy", bristol)
        dateutil_london = "tzfile('/usr/share/zoneinfo/Europe/London')"
        [meta_file] = cache.cache_dir.glob("*.meta.json")
        meta_file.write_text(json.dumps({**json.loads(meta_file.read_text()), "timezone": dateutil_london}))

        with pytest.raises(ValueError, match=re.escape(dateutil_london)):
            cache.get("tmy", bristol)

    def test_different_locations_different_cache(self, cache, sample_weather_data):
        """Different locations use different cache entries."""
        loc1 = Location(latitude=51.45, longitude=-2.58)
        loc2 = Location(latitude=52.0, longitude=-1.0)
        cache.put(sample_weather_data, "tmy", loc1)
        result = cache.get("tmy", loc2)
        assert result is None

    def test_a_get_racing_puts_finds_no_entry_or_the_whole_one(self, cache, bristol, pvgis_tmy):
        """While two threads each put one TMY twice under one key of an empty cache, every get from a third
        thread returns None or that whole TMY, its index's timezone and frequency included, and none raises."""
        writers_done = threading.Event()

        def put_twice():
            for _ in range(2):
                cache.put(pvgis_tmy, "tmy", bristol)

        def get_until_writers_finish():
            reads = []
            while not writers_done.is_set():
                reads.append(cache.get("tmy", bristol))
            return reads

        with ThreadPoolExecutor(max_workers=3) as pool:
            reader = pool.submit(get_until_writers_finish)
            writers = [pool.submit(put_twice) for _ in range(2)]
            try:
                for writer in writers:
                    writer.result()
            finally:
                writers_done.set()
            reads = reader.result()

        for read in reads:
            if read is not None:
                pd.testing.assert_frame_equal(read, pvgis_tmy)
        pd.testing.assert_frame_equal(cache.get("tmy", bristol), pvgis_tmy)

    def test_an_interrupted_put_leaves_the_entry_cached_before_it(self, cache, bristol, sample_weather_data):
        """A put interrupted part-way through writing leaves the entry cached before it, and no other file."""
        cache.put(sample_weather_data, "tmy", bristol)
        files_before = sorted(cache.cache_dir.iterdir())

        with pytest.raises(_Interrupted):
            cache.put(_interrupted_half_way(sample_weather_data), "tmy", bristol)

        assert sorted(cache.cache_dir.iterdir()) == files_before
        pd.testing.assert_frame_equal(cache.get("tmy", bristol), sample_weather_data)

    def test_an_interrupted_put_into_an_empty_cache_leaves_no_entry(self, cache, bristol, sample_weather_data):
        """A put interrupted part-way through writing into an empty cache leaves no file, so a get finds no entry."""
        with pytest.raises(_Interrupted):
            cache.put(_interrupted_half_way(sample_weather_data), "tmy", bristol)

        assert list(cache.cache_dir.iterdir()) == []
        assert cache.get("tmy", bristol) is None

    def test_clear_removes_all(self, cache, bristol, sample_weather_data):
        """Clear removes all cached data."""
        cache.put(sample_weather_data, "tmy", bristol)
        count = cache.clear()
        assert count >= 1
        result = cache.get("tmy", bristol)
        assert result is None

    def test_invalidate_specific_entry(self, cache, bristol, sample_weather_data):
        """Invalidate removes specific cache entry."""
        cache.put(sample_weather_data, "tmy", bristol)
        removed = cache.invalidate("tmy", bristol)
        assert removed is True
        result = cache.get("tmy", bristol)
        assert result is None

    def test_invalidate_returns_false_if_not_found(self, cache, bristol):
        """Invalidate returns False if entry doesn't exist."""
        removed = cache.invalidate("tmy", bristol)
        assert removed is False


class TestGetTmyDataWithCache:
    """Test TMY data retrieval with caching."""

    @pytest.fixture
    def mock_tmy_data(self, sample_index):
        """Mock TMY data from PVGIS."""
        return pd.DataFrame({
            "ghi": np.linspace(0, 800, 24),
            "dni": np.linspace(0, 600, 24),
            "dhi": np.linspace(0, 300, 24),
            "temp_air": np.linspace(5, 15, 24),
        }, index=sample_index)

    def test_uses_cache_when_available(self, weather_cache, pvgis_requests, mock_tmy_data):
        """Uses cached data when available, returned exactly as stored."""
        location = Location.bristol()
        weather_cache.put(mock_tmy_data, "tmy", location)

        result = get_tmy_data(location, use_cache=True)

        pvgis_requests.tmy.assert_not_called()
        pvgis_requests.hourly.assert_not_called()
        pd.testing.assert_frame_equal(result, mock_tmy_data)

    def test_skips_cache_when_disabled(self, weather_cache, pvgis_requests, mock_tmy_data):
        """Skips cache when use_cache=False."""
        location = Location.bristol()
        weather_cache.put(mock_tmy_data, "tmy", location)

        get_tmy_data(location, use_cache=False)

        pvgis_requests.tmy.assert_called_once()
        pvgis_requests.hourly.assert_called_once()


class TestGetTmyDataScalesToLongTermMeanGhi:
    """get_tmy_data scales PVGIS's TMY to the mean annual GHI of PVGIS's 2005-2020 hourly series."""

    def test_annual_ghi_is_the_series_mean(self, pvgis_tmy, pvgis_requests):
        """The TMY's GHI sums to the mean of the series' calendar-year totals; its temperatures are PVGIS's."""
        result = get_tmy_data(Location.bristol(), use_cache=False)

        assert result["ghi"].sum() / 1000 == pytest.approx(1075.0, rel=1e-9)
        pd.testing.assert_series_equal(result["temp_air"], pvgis_tmy["temp_air"])

    def test_tmy_is_requested_with_pvgis_tmy_request(self, pvgis_requests):
        """The TMY request is PVGIS_TMY_REQUEST at the location's point, so whatever imports it asks for the same TMY."""
        bristol = Location.bristol()
        get_tmy_data(bristol, use_cache=False)

        assert pvgis_requests.tmy.call_args == call(
            latitude=bristol.latitude, longitude=bristol.longitude, **PVGIS_TMY_REQUEST
        )

    def test_series_is_requested_as_ghi_for_the_tmys_point_years_and_horizon(self, pvgis_requests):
        """The series request asks for the TMY request's data as one GHI column, the response pvgis_hourly_series mirrors."""
        get_tmy_data(Location.bristol(), use_cache=False)

        tmy_request = pvgis_requests.tmy.call_args.kwargs
        series_request = pvgis_requests.hourly.call_args.kwargs
        for series_arg, tmy_arg in [
            ("latitude", "latitude"),
            ("longitude", "longitude"),
            ("url", "url"),
            ("start", "startyear"),
            ("end", "endyear"),
            ("usehorizon", "usehorizon"),
        ]:
            assert series_request[series_arg] == tmy_request[tmy_arg], series_arg
        assert series_request["surface_tilt"] == 0
        assert series_request["components"] is False

    def test_scaled_tmy_is_cached(self, weather_cache, pvgis_requests):
        """Once fetched, the scaled TMY is served from the cache exactly as fetched, with no further PVGIS request."""
        first = get_tmy_data(Location.bristol())
        pvgis_requests.tmy.side_effect = AssertionError("the TMY was requested again")
        pvgis_requests.hourly.side_effect = AssertionError("the series was requested again")
        second = get_tmy_data(Location.bristol())

        assert first["ghi"].sum() / 1000 == pytest.approx(1075.0, rel=1e-9)
        pd.testing.assert_frame_equal(second, first, check_exact=True)

    def test_a_tmy_cached_before_scaling_is_never_served(self, weather_cache, pvgis_tmy, pvgis_requests):
        """Bristol's unscaled TMY, as the cache stored it before task 285, is fetched afresh and scaled instead."""
        pvgis_tmy.to_csv(weather_cache.cache_dir / f"{PRE_SCALING_BRISTOL_TMY_STEM}.csv")
        (weather_cache.cache_dir / f"{PRE_SCALING_BRISTOL_TMY_STEM}.meta.json").write_text(
            json.dumps(
                {
                    "prefix": "tmy",
                    "latitude": 51.45,
                    "longitude": -2.58,
                    "start_date": None,
                    "end_date": None,
                    "timezone": "UTC",
                    "freq": None,
                }
            )
        )

        result = get_tmy_data(Location.bristol())

        pvgis_requests.tmy.assert_called_once()
        assert result["ghi"].sum() / 1000 == pytest.approx(1075.0, rel=1e-9)

    @pytest.mark.parametrize(
        "make_series",
        [
            pytest.param(lambda series: series.loc[:"2019"], id="year 2020 missing"),
            pytest.param(lambda series: series.loc[:"2020-12-30"], id="last day of 2020 missing"),
            pytest.param(
                lambda series: pd.concat([series, series.loc["2020-06-01"]]).sort_index(), id="a day of 2020 repeated"
            ),
        ],
    )
    def test_refuses_a_series_lacking_or_repeating_a_climate_years_hours(
        self, weather_cache, pvgis_hourly_series, pvgis_requests, make_series
    ):
        """A series lacking or repeating any hour of the climate years raises, naming the year, and leaves nothing cached."""
        pvgis_requests.hourly.return_value = (make_series(pvgis_hourly_series), {})

        with pytest.raises(WeatherDataError, match="2020"):
            get_tmy_data(Location.bristol())

        assert weather_cache.get("tmy", Location.bristol()) is None

    @pytest.mark.parametrize(
        "make_tmy",
        [
            pytest.param(lambda tmy: tmy.iloc[:24], id="TMY not one year"),
            pytest.param(lambda tmy: tmy.assign(ghi=0.0), id="TMY without GHI"),
        ],
    )
    def test_refuses_a_tmy_it_cannot_scale(self, weather_cache, pvgis_tmy, pvgis_requests, make_tmy):
        """A TMY scale_tmy_to_annual_ghi refuses raises WeatherDataError, as any bad PVGIS response does, and leaves nothing cached."""
        pvgis_requests.tmy.return_value = (make_tmy(pvgis_tmy), {})

        with pytest.raises(WeatherDataError) as refusal:
            get_tmy_data(Location.bristol())

        assert isinstance(refusal.value.__cause__, ValueError)
        assert str(refusal.value.__cause__) in str(refusal.value)
        assert weather_cache.get("tmy", Location.bristol()) is None


class TestGetTmyDataReportsPvgisFailures:
    """Every failure at the PVGIS boundary raises WeatherDataError naming why, and leaves nothing cached."""

    @pytest.mark.parametrize(
        "failing_request",
        [
            pytest.param("tmy", id="TMY request"),
            pytest.param("hourly", id="long-term series request"),
        ],
    )
    def test_a_failed_request_raises_weather_data_error(self, weather_cache, pvgis_requests, failing_request):
        """A PVGIS request that fails raises WeatherDataError carrying the failure's own text."""
        getattr(pvgis_requests, failing_request).side_effect = ConnectionError("PVGIS is unreachable")

        with pytest.raises(WeatherDataError, match="PVGIS is unreachable"):
            get_tmy_data(Location.bristol())

        assert weather_cache.get("tmy", Location.bristol()) is None

    def test_a_tmy_lacking_a_required_column_raises_weather_data_error(
        self, weather_cache, pvgis_tmy, pvgis_requests
    ):
        """A TMY lacking any of temp_air, ghi, dni and dhi raises WeatherDataError naming the missing column."""
        pvgis_requests.tmy.return_value = (pvgis_tmy.drop(columns="ghi"), {})

        with pytest.raises(WeatherDataError, match="ghi"):
            get_tmy_data(Location.bristol())

        assert weather_cache.get("tmy", Location.bristol()) is None

    def test_weather_data_error_is_a_runtime_error(self):
        """Callers that catch RuntimeError still catch every PVGIS failure."""
        assert issubclass(WeatherDataError, RuntimeError)


class TestScaleTmyToAnnualGhi:
    """scale_tmy_to_annual_ghi rescales one TMY year's irradiance to a given annual GHI."""

    IRRADIANCE = ["ghi", "dni", "dhi"]

    @pytest.fixture
    def target(self, pvgis_tmy):
        """An annual GHI 10% above the TMY's own, in kWh/m²."""
        return 1.1 * pvgis_tmy["ghi"].sum() / 1000

    def test_annual_ghi_equals_the_target(self, pvgis_tmy, target):
        """The scaled year's GHI sums to the target."""
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        assert result["ghi"].sum() / 1000 == pytest.approx(target, rel=1e-9)

    def test_ghi_dni_and_dhi_share_one_factor(self, pvgis_tmy, target):
        """Every irradiance component is multiplied by the same factor, so GHI = DNI·cos z + DHI still holds."""
        factor = target / (pvgis_tmy["ghi"].sum() / 1000)
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        for column in self.IRRADIANCE:
            pd.testing.assert_series_equal(result[column], pvgis_tmy[column] * factor, rtol=1e-12)

    def test_other_columns_and_index_are_unchanged(self, pvgis_tmy, target):
        """Temperature, wind, humidity and the timestamps are kept as they are."""
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        pd.testing.assert_frame_equal(
            result.drop(columns=self.IRRADIANCE), pvgis_tmy.drop(columns=self.IRRADIANCE)
        )

    def test_input_is_not_mutated(self, pvgis_tmy, target):
        """The TMY passed in is left as it was."""
        before = pvgis_tmy.copy(deep=True)
        scale_tmy_to_annual_ghi(pvgis_tmy, target)
        pd.testing.assert_frame_equal(pvgis_tmy, before)

    @pytest.mark.parametrize(
        ("make_tmy", "annual_ghi_kwh_per_m2", "condition"),
        [
            pytest.param(lambda tmy: tmy, 0.0, "annual_ghi_kwh_per_m2", id="target not positive"),
            pytest.param(lambda tmy: tmy.assign(ghi=0.0), 1000.0, "ghi total", id="no ghi in the year"),
            pytest.param(lambda tmy: tmy.iloc[:24], 1000.0, "8760", id="not one TMY year"),
        ],
    )
    def test_refuses_what_it_cannot_scale(self, pvgis_tmy, make_tmy, annual_ghi_kwh_per_m2, condition):
        """A ValueError names the condition that failed."""
        with pytest.raises(ValueError, match=condition):
            scale_tmy_to_annual_ghi(make_tmy(pvgis_tmy), annual_ghi_kwh_per_m2)
