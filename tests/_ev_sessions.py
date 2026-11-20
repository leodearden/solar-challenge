# SPDX-License-Identifier: AGPL-3.0-or-later
"""The unbroken charging sessions in a power series with one row a minute, for a test that checks when an EV charges.

Usage::

    from tests._ev_sessions import charging_sessions

    profile = generate_ev_charging_profile(config, start_date, end_date)
    first_minute, minute_after_the_last = charging_sessions(profile)[0]
"""

import numpy as np
import pandas as pd


def charging_sessions(power_kw: pd.Series, above_kw: float = 0.0) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """The (first minute, minute after the last) of each unbroken run of minutes in *power_kw* that draw more than *above_kw*.

    The minute after a run is counted from the series' start, since a run can
    end with the series, where the index has no entry.
    """
    charging = np.concatenate(([False], power_kw.to_numpy() > above_kw, [False]))
    edges = power_kw.index[0] + pd.to_timedelta(np.flatnonzero(np.diff(charging)), unit="min")
    return list(zip(edges[::2], edges[1::2]))
