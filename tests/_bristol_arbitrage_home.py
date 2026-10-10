# SPDX-License-Identifier: AGPL-3.0-or-later
"""The home of the committed scenarios/bristol-arbitrage.yaml, read from the file.

On Economy 7 it charges its battery from the grid overnight. A test that simulates it
reads the file the way `home run` does, its SEG rate included, so the home it simulates
is the scenario's own and cannot drift from it.

Usage::

    from tests._bristol_arbitrage_home import bristol_arbitrage_home

    results = simulate_home(bristol_arbitrage_home(), start, end, weather_data=weather)
"""

from pathlib import Path

from solar_challenge.cli.home import home_config_for_run
from solar_challenge.home import HomeConfig

_SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "bristol-arbitrage.yaml"


def bristol_arbitrage_home() -> HomeConfig:
    """The HomeConfig that `home run` simulates from scenarios/bristol-arbitrage.yaml."""
    return home_config_for_run(_SCENARIO)
