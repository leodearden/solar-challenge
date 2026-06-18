# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.gridservices — EventWindow, rate bands, events config."""

import dataclasses
import pickle

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Step-1: EventWindow mask
# ---------------------------------------------------------------------------


class TestEventWindowMask:
    """Tests for EventWindow.mask() — selects winter-weekday-evening hours."""

    def test_event_window_mask_selects_winter_weekday_evening(self) -> None:
        """mask() returns True exactly for winter weekday 16/17/18:xx hours."""
        from solar_challenge.gridservices import EventWindow  # type: ignore[import]

        # Build a tz-aware DatetimeIndex with hand-verifiable points.
        # Dec 2024: Dec 2 = Monday, Dec 7 = Saturday.
        # Jul 2024: Jul 1 = Monday.
        idx = pd.DatetimeIndex(
            [
                # Monday Dec 2 — various hours
                "2024-12-02 15:00",
                "2024-12-02 16:00",
                "2024-12-02 17:00",
                "2024-12-02 18:00",
                "2024-12-02 19:00",
                # Saturday Dec 7 — in-window hour (but weekend)
                "2024-12-07 17:00",
                # Monday Jul 1 — in-window hour (but summer)
                "2024-07-01 17:00",
            ],
            tz="Europe/London",
        )

        ew = EventWindow(
            months=(11, 12, 1, 2),
            weekdays=(0, 1, 2, 3, 4),
            hours=(16, 17, 18),
            events_per_year=12,
            event_hours=3.0,
        )

        mask = ew.mask(idx)

        # Return type is a bool pd.Series indexed by the input
        assert isinstance(mask, pd.Series)
        assert mask.dtype == bool
        assert mask.index.equals(idx)

        # Mon Dec 15:00 — before window
        assert mask.iloc[0] is False or mask.iloc[0] == False  # noqa: E712
        # Mon Dec 16:00 — in window
        assert mask.iloc[1] is True or mask.iloc[1] == True  # noqa: E712
        # Mon Dec 17:00 — in window
        assert mask.iloc[2] is True or mask.iloc[2] == True  # noqa: E712
        # Mon Dec 18:00 — in window
        assert mask.iloc[3] is True or mask.iloc[3] == True  # noqa: E712
        # Mon Dec 19:00 — hour excluded
        assert mask.iloc[4] is False or mask.iloc[4] == False  # noqa: E712
        # Sat Dec 17:00 — weekend excluded
        assert mask.iloc[5] is False or mask.iloc[5] == False  # noqa: E712
        # Mon Jul 17:00 — summer excluded
        assert mask.iloc[6] is False or mask.iloc[6] == False  # noqa: E712

        # Exactly 3 in-window rows: Mon Dec 16, 17, 18
        assert int(mask.sum()) == 3
