# SPDX-License-Identifier: AGPL-3.0-or-later
"""One night / day / peak / day schedule written as two different period lists.

Night 0.10 £/kWh (00:00-07:00), day 0.20 (07:00-16:00), peak 0.35 (16:00-19:00) and
day 0.20 (19:00-00:00): as four periods, and as five with the night split at 03:00.
Every minute has the same rate in both, so whatever reads a tariff's schedule, its
cheap minutes or its dispatch, must give the same answer for both
(docs/prds/tariff-coverage-classifier-presets.md §2.1, §9 row 3).

Usage::

    from tests._same_schedule_tariffs import (
        NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS,
        NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS,
    )

    assert (
        NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS.cheap_minutes_of_day
        == NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS.cheap_minutes_of_day
    )
"""

from solar_challenge.tariff import TariffConfig, TariffPeriod

_DAY_PEAK_DAY = (
    TariffPeriod("07:00", "16:00", 0.20, "Day"),
    TariffPeriod("16:00", "19:00", 0.35, "Peak"),
    TariffPeriod("19:00", "00:00", 0.20, "Evening"),
)

NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS = TariffConfig(
    periods=(TariffPeriod("00:00", "07:00", 0.10, "Night"), *_DAY_PEAK_DAY),
    name="Night, day, peak, day as four periods",
)

NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS = TariffConfig(
    periods=(
        TariffPeriod("00:00", "03:00", 0.10, "Early night"),
        TariffPeriod("03:00", "07:00", 0.10, "Late night"),
        *_DAY_PEAK_DAY,
    ),
    name="Night, day, peak, day as five periods",
)
