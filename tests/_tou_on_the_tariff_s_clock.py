# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOU dispatch on a tariff's clock, given to simulate_timestep or strategy_day from that one tariff.

TOUOptimizedStrategy(tariff=tariff) reads the tariff's cheap minutes, and simulate_timestep prices each step at its
own `tariff`. Neither checks that the two are one tariff, so a test that names it twice can drift into a mixed
configuration. on_the_tariff_s_clock names it once.

Usage::

    from tests._tou_on_the_tariff_s_clock import on_the_tariff_s_clock

    result = simulate_timestep(0.0, 0.0, battery, 60, off_peak_ts, **on_the_tariff_s_clock(TariffConfig.economy_7()))
"""

from typing import TypedDict

from solar_challenge.dispatch import TOUOptimizedStrategy
from solar_challenge.tariff import TariffConfig


class OnTheTariffsClock(TypedDict):
    """simulate_timestep's strategy and tariff keywords for TOU dispatch on one tariff's clock."""

    strategy: TOUOptimizedStrategy
    tariff: TariffConfig


def on_the_tariff_s_clock(tariff: TariffConfig) -> OnTheTariffsClock:
    """TOUOptimizedStrategy on tariff's clock, priced at that same tariff."""
    return {"strategy": TOUOptimizedStrategy(tariff=tariff), "tariff": tariff}
