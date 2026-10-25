# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_committed_weather_cache.py: its read of Bristol's TMY fails the calling test, naming the fix, when the cache's directory or its entry is missing.

The read of the committed entry itself is the one tests/integration/test_pv_performance_ratio.py measures.
"""

from pathlib import Path

import pytest

from tests._committed_weather_cache import REWRITE_THE_COMMITTED_BRISTOL_TMY, committed_bristol_tmy


def test_a_missing_directory_fails_the_read_naming_it_and_is_not_created(tmp_path: Path) -> None:
    cache_dir = tmp_path / "weather_cache"

    with pytest.raises(pytest.fail.Exception) as failure:
        committed_bristol_tmy(cache_dir=cache_dir)

    assert f"No directory is at {cache_dir}, where the weather cache holding Bristol's TMY is committed" in str(
        failure.value
    )
    assert not cache_dir.exists()


def test_a_directory_without_the_bristol_entry_fails_the_read_naming_the_rewrite_and_is_left_empty(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "weather_cache"
    cache_dir.mkdir()

    with pytest.raises(pytest.fail.Exception) as failure:
        committed_bristol_tmy(cache_dir=cache_dir)

    assert f"WeatherCache reads no Bristol TMY entry in {cache_dir}" in str(failure.value)
    assert REWRITE_THE_COMMITTED_BRISTOL_TMY in str(failure.value)
    assert list(cache_dir.iterdir()) == []
