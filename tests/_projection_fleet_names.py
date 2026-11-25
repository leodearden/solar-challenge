# SPDX-License-Identifier: AGPL-3.0-or-later
"""The names of the fleets a smooth projection asks its simulator for, in the order it asks.

A projection names each fleet it simulates proj-age-<age>. A fleet whose curve is smooth asks for its seed ages,
then its first bisection pass's midpoints, and no more: fewest_simulated_ages(asset_life_years) fleets.

Usage::

    from tests._projection_fleet_names import PROJECTION_AGES_OVER_25_YEARS

    assert tuple(asked_names) == PROJECTION_AGES_OVER_25_YEARS
"""

PROJECTION_AGES_OVER_25_YEARS = ("proj-age-0", "proj-age-12", "proj-age-24", "proj-age-6", "proj-age-18")
"""The fleets a smooth projection over a 25-year asset life asks for: its seeds 0, 12 and 24, then its first pass's midpoints 6 and 18."""
