# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 2: a TariffConfig's periods cover each minute of the local day exactly once.

Construction refuses a gap or an overlap with one ConfigurationError naming the clock
times, so every tariff that constructs has a rate at every minute
(docs/prds/tariff-coverage-classifier-presets.md §5.1, §5.7).
"""

import functools
from collections.abc import Callable

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.tariff import FlatRateTariff, TariffConfig, TariffPeriod
from tests._minutes_of_a_winter_day import MINUTES_OF_A_WINTER_DAY


def test_a_gap_across_midnight_is_refused_naming_it_as_one_range() -> None:
    with pytest.raises(ConfigurationError) as refusal:
        TariffConfig((TariffPeriod("07:00", "23:00", 0.3),))

    message = str(refusal.value)
    assert "23:00-07:00" in message
    assert "00:00-07:00" not in message


def test_an_overlap_is_refused_naming_its_range_and_both_periods() -> None:
    with pytest.raises(ConfigurationError) as refusal:
        TariffConfig(
            (
                TariffPeriod("00:00", "12:00", 0.10, "Off-peak"),
                TariffPeriod("06:00", "00:00", 0.30, "Day"),
            )
        )

    message = str(refusal.value)
    assert "06:00-12:00" in message
    assert "'Off-peak' 00:00-12:00" in message
    assert "'Day' 06:00-00:00" in message


def test_one_refusal_names_every_gap_and_every_overlap() -> None:
    with pytest.raises(ConfigurationError) as refusal:
        TariffConfig(
            (
                TariffPeriod("00:00", "08:00", 0.10, "Night"),
                TariffPeriod("07:00", "20:00", 0.30, "Day"),
            )
        )

    message = str(refusal.value)
    assert "07:00-08:00" in message
    assert "20:00-00:00" in message


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(functools.partial(TariffConfig.flat_rate, 0.25), id="flat_rate"),
        pytest.param(functools.partial(FlatRateTariff, 0.25), id="FlatRateTariff"),
        pytest.param(TariffConfig.economy_7, id="economy_7"),
        pytest.param(TariffConfig.economy_10, id="economy_10"),
    ],
)
def test_a_tiling_tariff_constructs_and_rates_each_minute_as_its_first_matching_period(
    build: Callable[[], TariffConfig],
) -> None:
    tariff = build()

    rates = {minute: tariff.get_rate(minute) for minute in MINUTES_OF_A_WINTER_DAY}

    assert rates == {
        minute: next(p.rate_per_kwh for p in tariff.periods if p.matches_time(minute))
        for minute in MINUTES_OF_A_WINTER_DAY
    }
