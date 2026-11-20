# SPDX-License-Identifier: AGPL-3.0-or-later
"""§9 row 15 of docs/prds/tariff-coverage-classifier-presets.md: where an off_peak EV's first charging session falls on each tariff.

The EV is home from 18:00 to 07:00 and charges 35 kWh at 7 kW, a 300-minute session, over
10-12 January 2024. London's clock is UTC all through those days, so a minute's position in
the period is its wall-clock minute. tests/unit/test_ev.py checks the row on
generate_ev_charging_profile, tests/unit/test_home_ev_tariff.py on simulate_home.

Usage::

    from tests._off_peak_ev_on_each_tariff import FIRST_SESSION_ON_EACH_TARIFF, JANUARY_DAYS, OFF_PEAK_EV

    @pytest.mark.parametrize(("tariff", "first_session"), FIRST_SESSION_ON_EACH_TARIFF)
    def test_off_peak_charges_in_the_tariffs_cheap_minutes(tariff, first_session):
        profile = generate_ev_charging_profile(OFF_PEAK_EV, *JANUARY_DAYS, tariff=tariff)
"""

import pandas as pd
import pytest

from solar_challenge.ev import EVConfig
from solar_challenge.tariff import TariffConfig

OFF_PEAK_EV = EVConfig("7kW", 18, 7, 35.0, "off_peak")
"""The row's EV: home from 18:00 to 07:00, charging 35 kWh at 7 kW in its tariff's cheap minutes."""

JANUARY_DAYS = (pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-12"))
"""The first and last day of the row's period."""


def _london(text: str) -> pd.Timestamp:
    """The time *text* on London's clock."""
    return pd.Timestamp(text, tz="Europe/London")


FIRST_SESSION_ON_EACH_TARIFF = (
    pytest.param(
        TariffConfig.economy_7(),
        (_london("2024-01-11 00:30"), _london("2024-01-11 05:30")),
        id="economy-7",
    ),
    pytest.param(
        TariffConfig.economy_10(),
        (_london("2024-01-11 00:00"), _london("2024-01-11 05:00")),
        id="economy-10",
    ),
    pytest.param(
        TariffConfig.economy_7(off_peak_start="23:00", off_peak_end="06:00"),
        (_london("2024-01-10 23:00"), _london("2024-01-11 04:00")),
        id="economy-7-from-23-to-06",
    ),
    pytest.param(
        TariffConfig.flat_rate(0.25),
        (_london("2024-01-10 18:00"), _london("2024-01-10 23:00")),
        id="flat-rate-from-arrival",
    ),
)
"""Each tariff, then the (first minute, minute after the last) of the EV's first session on it.

Economy 10's session holds none of its peak-rate minutes. A flat rate has no cheap minute,
so the EV charges from arrival, as smart_charging_mode 'none' does.
"""
