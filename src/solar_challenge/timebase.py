# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long one row of a simulated series lasts: the simulation runs at one row a minute."""

import pandas as pd

HOURS_PER_MINUTE = 1 / 60
"""Hours in one minute: minutes times this is hours, and, as each row of a simulated series is one minute, a kW sample times this is that minute's kWh."""


def step_hours(index: pd.DatetimeIndex) -> float:
    """The hours one row of index lasts: the gap between its first two rows, or one minute when it has fewer."""
    if len(index) < 2:
        return HOURS_PER_MINUTE
    return float((index[1] - index[0]).total_seconds()) / 3600.0
