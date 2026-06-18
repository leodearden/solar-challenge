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


# ---------------------------------------------------------------------------
# Step-3: EventWindow validation
# ---------------------------------------------------------------------------


class TestEventWindowValidation:
    """EventWindow __post_init__ raises ConfigurationError for invalid fields."""

    def test_empty_months_raises(self) -> None:
        """Empty months tuple raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=1.0)

    def test_empty_weekdays_raises(self) -> None:
        """Empty weekdays tuple raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(), hours=(16,), events_per_year=1, event_hours=1.0)

    def test_empty_hours_raises(self) -> None:
        """Empty hours tuple raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(), events_per_year=1, event_hours=1.0)

    def test_month_out_of_range_raises(self) -> None:
        """Month value outside 1..12 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(0,), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=1.0)
        with pytest.raises(ConfigurationError):
            EventWindow(months=(13,), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=1.0)

    def test_weekday_out_of_range_raises(self) -> None:
        """Weekday value outside 0..6 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(-1,), hours=(16,), events_per_year=1, event_hours=1.0)
        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(7,), hours=(16,), events_per_year=1, event_hours=1.0)

    def test_hour_out_of_range_raises(self) -> None:
        """Hour value outside 0..23 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(-1,), events_per_year=1, event_hours=1.0)
        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(24,), events_per_year=1, event_hours=1.0)

    def test_events_per_year_zero_raises(self) -> None:
        """events_per_year == 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(16,), events_per_year=0, event_hours=1.0)

    def test_events_per_year_negative_raises(self) -> None:
        """events_per_year < 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(16,), events_per_year=-1, event_hours=1.0)

    def test_event_hours_zero_raises(self) -> None:
        """event_hours == 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=0.0)

    def test_event_hours_negative_raises(self) -> None:
        """event_hours < 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import EventWindow

        with pytest.raises(ConfigurationError):
            EventWindow(months=(12,), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=-1.0)

    def test_valid_event_window_is_frozen(self) -> None:
        """Valid EventWindow is frozen — attribute assignment raises FrozenInstanceError."""
        from solar_challenge.gridservices import EventWindow

        ew = EventWindow(months=(12,), weekdays=(0,), hours=(16,), events_per_year=1, event_hours=1.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ew.months = (11,)  # type: ignore[misc]

    def test_valid_event_window_is_picklable(self) -> None:
        """Valid EventWindow survives a pickle round-trip equal to the original."""
        from solar_challenge.gridservices import EventWindow

        ew = EventWindow(
            months=(11, 12, 1, 2),
            weekdays=(0, 1, 2, 3, 4),
            hours=(16, 17, 18),
            events_per_year=12,
            event_hours=3.0,
        )
        assert pickle.loads(pickle.dumps(ew)) == ew


# ---------------------------------------------------------------------------
# Step-5: GridServicesRateBand + GridServicesRateBands + module constant
# ---------------------------------------------------------------------------


class TestGridServicesRateBands:
    """Tests for GridServicesRateBand, GridServicesRateBands, and module helpers."""

    def test_module_constant_has_three_bands(self) -> None:
        """GRID_SERVICES_RATE_BANDS has resolvable low/central/high bands."""
        from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS

        for band_name in ("low", "central", "high"):
            band = GRID_SERVICES_RATE_BANDS.resolve(band_name)
            assert band is not None

    def test_resolve_helper_and_constant_agree(self) -> None:
        """resolve_grid_services_rate_band('central') equals GRID_SERVICES_RATE_BANDS.resolve('central')."""
        from solar_challenge.gridservices import (
            GRID_SERVICES_RATE_BANDS,
            GridServicesRateBand,
            resolve_grid_services_rate_band,
        )

        central_via_helper = resolve_grid_services_rate_band("central")
        central_via_constant = GRID_SERVICES_RATE_BANDS.resolve("central")
        assert central_via_helper == central_via_constant
        assert isinstance(central_via_helper, GridServicesRateBand)

    def test_central_rates_are_positive(self) -> None:
        """Central band availability and utilisation rates are > 0."""
        from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS

        central = GRID_SERVICES_RATE_BANDS.resolve("central")
        assert central.availability_gbp_per_kw_per_event > 0
        assert central.utilisation_gbp_per_mwh > 0

    def test_low_le_central_le_high_availability(self) -> None:
        """Low <= Central <= High for availability_gbp_per_kw_per_event."""
        from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS

        low = GRID_SERVICES_RATE_BANDS.resolve("low")
        central = GRID_SERVICES_RATE_BANDS.resolve("central")
        high = GRID_SERVICES_RATE_BANDS.resolve("high")
        assert low.availability_gbp_per_kw_per_event <= central.availability_gbp_per_kw_per_event
        assert central.availability_gbp_per_kw_per_event <= high.availability_gbp_per_kw_per_event

    def test_low_le_central_le_high_utilisation(self) -> None:
        """Low <= Central <= High for utilisation_gbp_per_mwh."""
        from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS

        low = GRID_SERVICES_RATE_BANDS.resolve("low")
        central = GRID_SERVICES_RATE_BANDS.resolve("central")
        high = GRID_SERVICES_RATE_BANDS.resolve("high")
        assert low.utilisation_gbp_per_mwh <= central.utilisation_gbp_per_mwh
        assert central.utilisation_gbp_per_mwh <= high.utilisation_gbp_per_mwh

    def test_unknown_band_raises_value_error(self) -> None:
        """resolve of an unknown band raises ValueError."""
        from solar_challenge.gridservices import resolve_grid_services_rate_band

        with pytest.raises(ValueError):
            resolve_grid_services_rate_band("extreme")

    def test_rate_band_rejects_negative_availability(self) -> None:
        """GridServicesRateBand raises ValueError for negative availability."""
        from solar_challenge.gridservices import GridServicesRateBand

        with pytest.raises(ValueError):
            GridServicesRateBand(availability_gbp_per_kw_per_event=-1.0, utilisation_gbp_per_mwh=5.0)

    def test_rate_band_rejects_negative_utilisation(self) -> None:
        """GridServicesRateBand raises ValueError for negative utilisation."""
        from solar_challenge.gridservices import GridServicesRateBand

        with pytest.raises(ValueError):
            GridServicesRateBand(availability_gbp_per_kw_per_event=1.0, utilisation_gbp_per_mwh=-5.0)

    def test_rate_band_is_frozen(self) -> None:
        """GridServicesRateBand is frozen — attribute assignment raises FrozenInstanceError."""
        from solar_challenge.gridservices import GridServicesRateBand

        band = GridServicesRateBand(availability_gbp_per_kw_per_event=1.0, utilisation_gbp_per_mwh=5.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            band.availability_gbp_per_kw_per_event = 2.0  # type: ignore[misc]
