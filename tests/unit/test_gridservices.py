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
        assert not bool(mask.iloc[0])
        # Mon Dec 16:00 — in window
        assert bool(mask.iloc[1])
        # Mon Dec 17:00 — in window
        assert bool(mask.iloc[2])
        # Mon Dec 18:00 — in window
        assert bool(mask.iloc[3])
        # Mon Dec 19:00 — hour excluded
        assert not bool(mask.iloc[4])
        # Sat Dec 17:00 — weekend excluded
        assert not bool(mask.iloc[5])
        # Mon Jul 17:00 — summer excluded
        assert not bool(mask.iloc[6])

        # Exactly 3 in-window rows: Mon Dec 16, 17, 18
        assert int(mask.sum()) == 3

    def test_event_window_mask_tz_naive(self) -> None:
        """mask() works on tz-naive DatetimeIndex as well as tz-aware."""
        from solar_challenge.gridservices import EventWindow

        # tz-naive index with same hand-verifiable points
        idx = pd.DatetimeIndex(
            [
                "2024-12-02 15:00",  # Mon Dec, before window
                "2024-12-02 17:00",  # Mon Dec, in window
                "2024-12-07 17:00",  # Sat Dec, weekend excluded
            ]
        )

        ew = EventWindow(
            months=(11, 12, 1, 2),
            weekdays=(0, 1, 2, 3, 4),
            hours=(16, 17, 18),
            events_per_year=12,
            event_hours=3.0,
        )
        mask = ew.mask(idx)

        assert isinstance(mask, pd.Series)
        assert mask.dtype == bool
        assert mask.index.equals(idx)
        assert mask.tolist() == [False, True, False]


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


# ---------------------------------------------------------------------------
# Step-7: GridServicesEventsConfig defaults + construction
# ---------------------------------------------------------------------------


class TestGridServicesEventsConfigDefaults:
    """GridServicesEventsConfig construction, defaults, immutability, and pickling."""

    def test_default_event_windows_structure(self) -> None:
        """DEFAULT_EVENT_WINDOWS is a non-empty tuple of EventWindow with the winter schedule."""
        from solar_challenge.gridservices import DEFAULT_EVENT_WINDOWS, EventWindow

        assert isinstance(DEFAULT_EVENT_WINDOWS, tuple)
        assert len(DEFAULT_EVENT_WINDOWS) >= 1
        assert all(isinstance(ew, EventWindow) for ew in DEFAULT_EVENT_WINDOWS)

        ew = DEFAULT_EVENT_WINDOWS[0]
        assert set(ew.months) == {11, 12, 1, 2}
        assert set(ew.weekdays) == {0, 1, 2, 3, 4}
        assert set(ew.hours) == {16, 17, 18}
        assert ew.events_per_year == 12
        assert ew.event_hours == 3.0

    def test_default_construction(self) -> None:
        """GridServicesEventsConfig() uses all expected defaults."""
        from solar_challenge.gridservices import DEFAULT_EVENT_WINDOWS, GridServicesEventsConfig

        cfg = GridServicesEventsConfig()
        assert cfg.band == "central"
        assert cfg.event_windows == DEFAULT_EVENT_WINDOWS
        assert 0.0 <= cfg.aggregator_share < 1.0
        assert 0.0 <= cfg.utilisation_factor <= 1.0
        assert cfg.availability_gbp_per_kw_per_event is None
        assert cfg.utilisation_gbp_per_mwh is None

    def test_fully_specified_config_round_trips(self) -> None:
        """All fields survive round-trip when explicitly set."""
        from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig

        ews = (EventWindow(months=(12,), weekdays=(0,), hours=(17,), events_per_year=6, event_hours=2.0),)
        cfg = GridServicesEventsConfig(
            band="high",
            event_windows=ews,
            aggregator_share=0.1,
            utilisation_factor=0.8,
            availability_gbp_per_kw_per_event=2.5,
            utilisation_gbp_per_mwh=80.0,
        )
        assert cfg.band == "high"
        assert cfg.event_windows == ews
        assert cfg.aggregator_share == 0.1
        assert cfg.utilisation_factor == 0.8
        assert cfg.availability_gbp_per_kw_per_event == 2.5
        assert cfg.utilisation_gbp_per_mwh == 80.0

    def test_is_frozen(self) -> None:
        """GridServicesEventsConfig is frozen — assignment raises FrozenInstanceError."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.band = "low"  # type: ignore[misc]

    def test_is_picklable(self) -> None:
        """GridServicesEventsConfig survives a pickle round-trip equal to the original."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig()
        assert pickle.loads(pickle.dumps(cfg)) == cfg


# ---------------------------------------------------------------------------
# Step-9: GridServicesEventsConfig validation
# ---------------------------------------------------------------------------


class TestGridServicesEventsConfigValidation:
    """GridServicesEventsConfig.__post_init__ rejects invalid fields."""

    def test_negative_availability_override_raises(self) -> None:
        """Negative availability_gbp_per_kw_per_event raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(availability_gbp_per_kw_per_event=-0.01)

    def test_negative_utilisation_override_raises(self) -> None:
        """Negative utilisation_gbp_per_mwh raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(utilisation_gbp_per_mwh=-1.0)

    def test_aggregator_share_negative_raises(self) -> None:
        """aggregator_share < 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(aggregator_share=-0.01)

    def test_aggregator_share_exactly_one_raises(self) -> None:
        """aggregator_share == 1.0 raises ConfigurationError ([0, 1) bound)."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(aggregator_share=1.0)

    def test_aggregator_share_greater_than_one_raises(self) -> None:
        """aggregator_share > 1 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(aggregator_share=1.1)

    def test_utilisation_factor_negative_raises(self) -> None:
        """utilisation_factor < 0 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(utilisation_factor=-0.01)

    def test_utilisation_factor_greater_than_one_raises(self) -> None:
        """utilisation_factor > 1 raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(utilisation_factor=1.01)

    def test_empty_event_windows_raises(self) -> None:
        """Empty event_windows tuple raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(event_windows=())

    def test_unknown_band_raises(self) -> None:
        """Unknown band name raises ConfigurationError."""
        from solar_challenge.config import ConfigurationError
        from solar_challenge.gridservices import GridServicesEventsConfig

        with pytest.raises(ConfigurationError):
            GridServicesEventsConfig(band="mid")

    def test_aggregator_share_zero_ok(self) -> None:
        """aggregator_share == 0.0 is valid."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig(aggregator_share=0.0)
        assert cfg.aggregator_share == 0.0

    def test_utilisation_factor_zero_ok(self) -> None:
        """utilisation_factor == 0.0 is valid."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig(utilisation_factor=0.0)
        assert cfg.utilisation_factor == 0.0

    def test_utilisation_factor_one_ok(self) -> None:
        """utilisation_factor == 1.0 is valid."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig(utilisation_factor=1.0)
        assert cfg.utilisation_factor == 1.0

    def test_override_rates_zero_ok(self) -> None:
        """Override rates set to 0.0 (non-negative) are accepted."""
        from solar_challenge.gridservices import GridServicesEventsConfig

        cfg = GridServicesEventsConfig(
            availability_gbp_per_kw_per_event=0.0,
            utilisation_gbp_per_mwh=0.0,
        )
        assert cfg.availability_gbp_per_kw_per_event == 0.0
        assert cfg.utilisation_gbp_per_mwh == 0.0


# ---------------------------------------------------------------------------
# Helpers for TestComputeFleetSpareCapacityKw (steps 1, 3)
# ---------------------------------------------------------------------------


def _make_gs_sim_results(
    battery_soc: "list[float]",
    battery_discharge: "list[float]",
    index: pd.DatetimeIndex,
) -> "SimulationResults":  # type: ignore[name-defined]
    """Build a minimal SimulationResults with hand-set battery_soc and battery_discharge.

    All other series are set to zero.  Use this helper for grid-services spare-capacity
    tests that only read battery_soc / battery_discharge.
    """
    from solar_challenge.home import SimulationResults

    zeros = pd.Series(0.0, index=index)
    return SimulationResults(
        generation=zeros.copy(),
        demand=zeros.copy(),
        self_consumption=zeros.copy(),
        battery_charge=zeros.copy(),
        battery_discharge=pd.Series(battery_discharge, index=index, dtype=float),
        battery_soc=pd.Series(battery_soc, index=index, dtype=float),
        grid_import=zeros.copy(),
        grid_export=zeros.copy(),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
    )


def _make_gs_fleet_results(
    homes_data: "list[tuple]",
) -> "FleetResults":  # type: ignore[name-defined]
    """Build a FleetResults from per-home (SimulationResults, HomeConfig) pairs."""
    from solar_challenge.fleet import FleetResults

    per_home = [sim for sim, _ in homes_data]
    configs = [cfg for _, cfg in homes_data]
    return FleetResults(per_home_results=per_home, home_configs=configs)


def _make_gs_home_config(
    battery_config: "BatteryConfig",  # type: ignore[name-defined]
) -> "HomeConfig":  # type: ignore[name-defined]
    """Build a minimal HomeConfig with the given BatteryConfig."""
    from solar_challenge.home import HomeConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.location import Location
    from solar_challenge.pv import PVConfig

    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0, azimuth=180.0, tilt=35.0),
        load_config=LoadConfig(annual_consumption_kwh=3500.0),
        battery_config=battery_config,
        location=Location.bristol(),
    )


# ---------------------------------------------------------------------------
# Step-1: compute_fleet_spare_capacity_kw — RED
# ---------------------------------------------------------------------------


class TestComputeFleetSpareCapacityKw:
    """Tests for compute_fleet_spare_capacity_kw — firm spare battery capacity at events."""

    def test_firm_multihome_avail_kw(self) -> None:
        """Two-home fleet: floor-pinned home contributes zero, other contributes min(P,E/h).

        Hand-computed expected value (non-tautological):

        Config: capacity_kwh=10, min_soc_fraction=0.1, soh=1.0, max_discharge_kw=3.0
            => min_soc_kwh = 10.0 * 1.0 * 0.1 = 1.0

        Home A in-window: soc=[4.0, 3.5, 3.0], discharge=[1.0, 1.5, 0.5]
            P_spare = 3.0 - max(1.0, 1.5, 0.5) = 3.0 - 1.5 = 1.5
            E_spare = min(4.0-1.0, 3.5-1.0, 3.0-1.0) = min(3.0, 2.5, 2.0) = 2.0
            avail_A = min(1.5, 2.0/3.0) = min(1.5, 0.6667) = 2/3

        Home B (floor-pinned): soc=[1.0, 1.0, 1.0], discharge=[0.0, 0.0, 0.0]
            E_spare = min(0.0, 0.0, 0.0) = 0.0 => avail_B = max(0, min(..., 0)) = 0

        Total = 2/3
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw

        # Dec 2 2024 = Monday (weekday=0), December (month=12) — confirmed in existing tests
        idx = pd.DatetimeIndex(
            [
                "2024-12-02 16:00",  # in-window
                "2024-12-02 17:00",  # in-window
                "2024-12-02 18:00",  # in-window
                "2024-12-02 19:00",  # out-of-window (hour 19 excluded)
            ],
            tz="Europe/London",
        )

        w = EventWindow(
            months=(12,),
            weekdays=(0,),
            hours=(16, 17, 18),
            events_per_year=12,
            event_hours=3.0,
        )

        # BatteryConfig: soh=1.0 so min_soc_kwh = capacity * min_soc_fraction exactly
        bat_cfg = BatteryConfig(
            capacity_kwh=10.0,
            max_discharge_kw=3.0,
            min_soc_fraction=0.1,
            soh=1.0,
        )
        home_cfg = _make_gs_home_config(bat_cfg)

        # Home A: partial discharge, well above floor
        sim_a = _make_gs_sim_results(
            battery_soc=[4.0, 3.5, 3.0, 3.0],
            battery_discharge=[1.0, 1.5, 0.5, 0.5],
            index=idx,
        )
        # Home B: floor-pinned (soc = min_soc_kwh throughout)
        sim_b = _make_gs_sim_results(
            battery_soc=[1.0, 1.0, 1.0, 1.0],
            battery_discharge=[0.0, 0.0, 0.0, 0.0],
            index=idx,
        )

        fleet = _make_gs_fleet_results([(sim_a, home_cfg), (sim_b, home_cfg)])

        result = compute_fleet_spare_capacity_kw(fleet, (w,))

        assert len(result) == 1, "one window → one result"
        assert result[0] >= 0.0, "I1: capacity must be non-negative"
        assert result == pytest.approx((2.0 / 3.0,))

    # -----------------------------------------------------------------------
    # Step-3: zero-condition and guard tests — RED
    # -----------------------------------------------------------------------

    def test_at_max_discharge_contributes_zero(self) -> None:
        """Home at max_discharge_kw in-window contributes 0 (I2 firmness guard).

        Hand-computed:
            Config: max_discharge_kw=3.0, capacity_kwh=10, min_soc_fraction=0.1, soh=1.0
            in-window discharge=[2.0, 3.0, 1.0]  ← touches max
            P_spare = 3.0 - max(2.0, 3.0, 1.0) = 3.0 - 3.0 = 0.0
            avail = max(0, min(0.0, ...)) = 0

        This exercises the I2 clamping — the clamped min(P_spare, ...) expression
        already handles this; no special-case code is needed.
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        bat_cfg = BatteryConfig(capacity_kwh=10.0, max_discharge_kw=3.0, min_soc_fraction=0.1, soh=1.0)
        home_cfg = _make_gs_home_config(bat_cfg)

        # Discharge touches max_discharge_kw (=3.0) during window ⇒ P_spare = 0
        sim = _make_gs_sim_results(
            battery_soc=[5.0, 4.0, 3.0],
            battery_discharge=[2.0, 3.0, 1.0],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])

        result = compute_fleet_spare_capacity_kw(fleet, (w,))

        assert len(result) == 1
        assert result[0] == pytest.approx(0.0), "at-max-discharge home must contribute 0"

    def test_home_without_battery_contributes_zero(self) -> None:
        """Fleet with a PV-only home (battery_config=None) must not crash.

        The PV-only home must be skipped (contributes 0) and the battery home's
        avail is returned unchanged.

        Hand-computed for battery home:
            Config: max_discharge_kw=3.0, capacity_kwh=10, min_soc_fraction=0.1, soh=1.0
            soc=[4.0, 3.5, 3.0], discharge=[1.0, 1.5, 0.5]
            P_spare = 1.5, E_spare = 2.0, avail = 2/3
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw
        from solar_challenge.home import HomeConfig
        from solar_challenge.load import LoadConfig
        from solar_challenge.location import Location
        from solar_challenge.pv import PVConfig

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )

        # Battery home
        bat_cfg = BatteryConfig(capacity_kwh=10.0, max_discharge_kw=3.0, min_soc_fraction=0.1, soh=1.0)
        bat_home = _make_gs_home_config(bat_cfg)
        sim_bat = _make_gs_sim_results(
            battery_soc=[4.0, 3.5, 3.0],
            battery_discharge=[1.0, 1.5, 0.5],
            index=idx,
        )

        # PV-only home (battery_config=None)
        pv_only_home = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0, azimuth=180.0, tilt=35.0),
            load_config=LoadConfig(annual_consumption_kwh=3500.0),
            battery_config=None,  # PV-only
            location=Location.bristol(),
        )
        sim_pv = _make_gs_sim_results(
            battery_soc=[0.0, 0.0, 0.0],
            battery_discharge=[0.0, 0.0, 0.0],
            index=idx,
        )

        fleet = _make_gs_fleet_results([(sim_bat, bat_home), (sim_pv, pv_only_home)])

        result = compute_fleet_spare_capacity_kw(fleet, (w,))

        assert len(result) == 1
        assert result[0] >= 0.0, "I1: non-negative"
        # Result must equal battery home's avail alone (2/3), PV-only home contributes 0
        assert result == pytest.approx((2.0 / 3.0,))

    def test_window_absent_from_index_is_zero(self) -> None:
        """Window absent from the home's index contributes 0; order is preserved.

        Two windows: w1 selectable by the index (hours 16-18), w2 with hours (2, 3)
        that never appear in the index.

        Hand-computed for w1 (one battery home):
            Config: max_discharge_kw=3.0, capacity_kwh=10, min_soc_fraction=0.1, soh=1.0
            soc=[4.0, 3.5, 3.0], discharge=[1.0, 1.5, 0.5]
            avail_w1 = 2/3

        For w2 (empty mask): no timesteps → contributes 0.
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w1 = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        # w2 matches hours 2-3, which never appear in the 3-point index above
        w2 = EventWindow(
            months=(12,), weekdays=(0,), hours=(2, 3),
            events_per_year=12, event_hours=2.0,
        )

        bat_cfg = BatteryConfig(capacity_kwh=10.0, max_discharge_kw=3.0, min_soc_fraction=0.1, soh=1.0)
        home_cfg = _make_gs_home_config(bat_cfg)
        sim = _make_gs_sim_results(
            battery_soc=[4.0, 3.5, 3.0],
            battery_discharge=[1.0, 1.5, 0.5],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])

        result = compute_fleet_spare_capacity_kw(fleet, (w1, w2))

        assert len(result) == 2, "two windows → two results"
        assert all(v >= 0.0 for v in result), "I1: all non-negative"
        assert result[0] == pytest.approx(2.0 / 3.0), "w1 avail matches hand-computed"
        assert result[1] == pytest.approx(0.0), "absent window contributes 0"

    # -----------------------------------------------------------------------
    # Amendment pass: additional coverage — SOH derating + below-floor clamp
    # -----------------------------------------------------------------------

    def test_degraded_battery_uses_effective_capacity(self) -> None:
        """Battery with soh=0.8: min_soc_kwh must use effective (SOH-derated) capacity.

        With soh=0.8, effective_capacity = 10.0 * 0.8 = 8.0 and
        min_soc_kwh = 8.0 * 0.1 = 0.8.  A regression that used nominal
        capacity (soh=1.0) would compute min_soc_kwh=1.0 and return 1/3
        instead of 0.4, so the two values are distinguishable.

        Hand-computed (soh=0.8):
            effective_capacity = 10.0 * 0.8 = 8.0
            min_soc_kwh        = 8.0 * 0.1  = 0.8
            in-window soc=[3.0, 2.5, 2.0], discharge=[0.5, 0.5, 0.5]
            P_spare = 3.0 - max(0.5, 0.5, 0.5) = 3.0 - 0.5 = 2.5
            E_spare = min(3.0-0.8, 2.5-0.8, 2.0-0.8) = min(2.2, 1.7, 1.2) = 1.2
            avail   = min(2.5, 1.2/3.0) = min(2.5, 0.4) = 0.4

        Wrong result with soh=1.0 floor (regression):
            min_soc_kwh = 1.0
            E_spare = min(2.0, 1.5, 1.0) = 1.0
            avail   = min(2.5, 1/3) ≈ 0.333  (different — detectable)
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        # soh=0.8 ⇒ effective_capacity=8.0 ⇒ min_soc_kwh=0.8
        bat_cfg = BatteryConfig(
            capacity_kwh=10.0, max_discharge_kw=3.0, min_soc_fraction=0.1, soh=0.8,
        )
        home_cfg = _make_gs_home_config(bat_cfg)
        sim = _make_gs_sim_results(
            battery_soc=[3.0, 2.5, 2.0],
            battery_discharge=[0.5, 0.5, 0.5],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])

        result = compute_fleet_spare_capacity_kw(fleet, (w,))

        assert len(result) == 1
        assert result[0] >= 0.0, "I1: non-negative"
        # 0.4 is the correct answer for soh=0.8 floor; 1/3 ≈ 0.333 would signal
        # a regression to nominal-capacity (soh=1.0) floor
        assert result == pytest.approx((0.4,))

    def test_soc_below_floor_clamps_to_zero(self) -> None:
        """Home whose soc dips below min_soc_kwh mid-window must contribute 0.

        This is the only path where the outer max(0.0, ...) clamp matters for
        the energy term (E_spare goes negative).  The at-max-discharge test
        exercises P_spare=0; this test exercises E_spare < 0.

        Hand-computed:
            Config: capacity_kwh=10, min_soc_fraction=0.1, soh=1.0
                ⇒ min_soc_kwh = 10.0 * 1.0 * 0.1 = 1.0
            in-window soc=[2.0, 0.8, 2.0]  ← 0.8 < 1.0 = min_soc_kwh
                discharge=[0.5, 0.5, 0.5]
            P_spare = 3.0 - 0.5 = 2.5
            E_spare = min(2.0-1.0, 0.8-1.0, 2.0-1.0) = min(1.0, -0.2, 1.0) = -0.2
            avail   = max(0.0, min(2.5, -0.2/3.0)) = max(0.0, negative) = 0.0
        """
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow, compute_fleet_spare_capacity_kw

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        bat_cfg = BatteryConfig(
            capacity_kwh=10.0, max_discharge_kw=3.0, min_soc_fraction=0.1, soh=1.0,
        )
        home_cfg = _make_gs_home_config(bat_cfg)
        # Middle soc value dips below the floor (1.0) ⇒ E_spare = -0.2 < 0
        sim = _make_gs_sim_results(
            battery_soc=[2.0, 0.8, 2.0],
            battery_discharge=[0.5, 0.5, 0.5],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])

        result = compute_fleet_spare_capacity_kw(fleet, (w,))

        assert len(result) == 1
        assert result[0] >= 0.0, "I1: non-negative"
        assert result == pytest.approx((0.0,)), (
            "below-floor soc ⇒ E_spare<0 ⇒ avail must be clamped to 0"
        )


# ---------------------------------------------------------------------------
# Step-1 (γ): TestGridServicesAtEvents — frozen dataclass structure
# ---------------------------------------------------------------------------


class TestGridServicesAtEvents:
    """GridServicesAtEvents frozen dataclass: construction, immutability, pickling."""

    def test_import(self) -> None:
        """GridServicesAtEvents imports from solar_challenge.gridservices."""
        from solar_challenge.gridservices import GridServicesAtEvents  # noqa: F401

    def test_fields_round_trip(self) -> None:
        """All three fields survive construction and read back equal to inputs."""
        from solar_challenge.gridservices import GridServicesAtEvents

        obj = GridServicesAtEvents(
            annual_income_gbp=150.0,
            per_window_avail_kw=(1.0, 2.0),
            per_window_income_gbp=(60.0, 90.0),
        )
        assert obj.annual_income_gbp == 150.0
        assert obj.per_window_avail_kw == (1.0, 2.0)
        assert obj.per_window_income_gbp == (60.0, 90.0)

    def test_single_window_fields(self) -> None:
        """Single-window construction works and fields have correct types."""
        from solar_challenge.gridservices import GridServicesAtEvents

        obj = GridServicesAtEvents(
            annual_income_gbp=9.972,
            per_window_avail_kw=(1.0,),
            per_window_income_gbp=(9.972,),
        )
        assert isinstance(obj.annual_income_gbp, float)
        assert isinstance(obj.per_window_avail_kw, tuple)
        assert isinstance(obj.per_window_income_gbp, tuple)
        assert len(obj.per_window_avail_kw) == 1
        assert len(obj.per_window_income_gbp) == 1

    def test_is_frozen(self) -> None:
        """GridServicesAtEvents is frozen — attribute assignment raises FrozenInstanceError."""
        from solar_challenge.gridservices import GridServicesAtEvents

        obj = GridServicesAtEvents(
            annual_income_gbp=10.0,
            per_window_avail_kw=(1.0,),
            per_window_income_gbp=(10.0,),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            obj.annual_income_gbp = 20.0  # type: ignore[misc]

    def test_is_picklable(self) -> None:
        """GridServicesAtEvents survives a pickle round-trip equal to the original."""
        from solar_challenge.gridservices import GridServicesAtEvents

        obj = GridServicesAtEvents(
            annual_income_gbp=150.0,
            per_window_avail_kw=(1.5, 2.5),
            per_window_income_gbp=(75.0, 75.0),
        )
        assert pickle.loads(pickle.dumps(obj)) == obj


# ---------------------------------------------------------------------------
# Step-3 (γ): TestComputeGridServicesAtEvents — core banded pricing
# ---------------------------------------------------------------------------


class TestComputeGridServicesAtEvents:
    """Tests for compute_grid_services_at_events — banded availability + utilisation pricing.

    Fixture: single home, cap=10/soh=1.0 → floor=1.0, max_discharge_kw=4.0;
    in-window soc=[5,5,5], discharge=[3,3,3] → P_spare=1.0, E_spare=4.0, avail=1.0.
    """

    def _make_fixture(self):
        """Build a single-home fleet with hand-derived avail_kW=1.0."""
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import EventWindow

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        bat_cfg = BatteryConfig(
            capacity_kwh=10.0, max_discharge_kw=4.0, min_soc_fraction=0.1, soh=1.0,
        )
        home_cfg = _make_gs_home_config(bat_cfg)
        # in-window soc=[5,5,5], discharge=[3,3,3]:
        #   P_spare = 4.0 - 3.0 = 1.0
        #   E_spare = min(5-1, 5-1, 5-1) = 4.0
        #   avail   = min(1.0, 4.0/3.0) = 1.0
        sim = _make_gs_sim_results(
            battery_soc=[5.0, 5.0, 5.0],
            battery_discharge=[3.0, 3.0, 3.0],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        return fleet, w

    def test_single_window_central_income(self) -> None:
        """Single window, band='central', defaults agg=0.25/util_factor=0.6 → expected income.

        Hand-derived (non-tautological):
            avail = 1.0, band=central (avail_rate=1.0, util_rate=60.0)
            avail_income = 1.0 * 1.0 * 12 = 12.0
            util_income  = 1.0 * 0.6 * 3.0 * (60/1000) * 12 = 1.296
            gross        = 13.296
            net          = 13.296 * 0.75 = 9.972
        """
        from solar_challenge.gridservices import (
            GRID_SERVICES_RATE_BANDS,
            GridServicesEventsConfig,
            compute_grid_services_at_events,
        )

        fleet, w = self._make_fixture()
        cfg = GridServicesEventsConfig(band="central", event_windows=(w,))

        # Re-derive expected income independently from the band constant
        band = GRID_SERVICES_RATE_BANDS.resolve("central")
        avail_income = 1.0 * band.availability_gbp_per_kw_per_event * w.events_per_year
        util_income = (
            1.0
            * cfg.utilisation_factor
            * w.event_hours
            * (band.utilisation_gbp_per_mwh / 1000.0)
            * w.events_per_year
        )
        expected_net = (avail_income + util_income) * (1.0 - cfg.aggregator_share)

        result = compute_grid_services_at_events(fleet, cfg)

        assert result.annual_income_gbp == pytest.approx(expected_net)

    def test_per_window_avail_kw_matches_beta(self) -> None:
        """per_window_avail_kw == approx((1.0,)) and matches compute_fleet_spare_capacity_kw."""
        from solar_challenge.gridservices import (
            GridServicesEventsConfig,
            compute_fleet_spare_capacity_kw,
            compute_grid_services_at_events,
        )

        fleet, w = self._make_fixture()
        cfg = GridServicesEventsConfig(band="central", event_windows=(w,))

        result = compute_grid_services_at_events(fleet, cfg)
        beta_avails = compute_fleet_spare_capacity_kw(fleet, cfg.event_windows)

        assert result.per_window_avail_kw == pytest.approx((1.0,))
        assert result.per_window_avail_kw == pytest.approx(beta_avails)

    def test_per_window_income_sums_to_annual(self) -> None:
        """len(per_window_income_gbp)==1 and sum(per_window_income_gbp)==annual_income_gbp."""
        from solar_challenge.gridservices import (
            GridServicesEventsConfig,
            compute_grid_services_at_events,
        )

        fleet, w = self._make_fixture()
        cfg = GridServicesEventsConfig(band="central", event_windows=(w,))

        result = compute_grid_services_at_events(fleet, cfg)

        assert len(result.per_window_income_gbp) == 1
        assert sum(result.per_window_income_gbp) == pytest.approx(result.annual_income_gbp)

    def test_multi_window_income(self) -> None:
        """Two windows with distinct N=12/6, h=3.0/2.0 → per_window tuples of length 2.

        Hand-derived (both windows select same 3 in-window timesteps → avail=1.0 each):
            w1 (N=12, h=3.0): avail_income=12.0, util=1.296, gross=13.296, net=9.972
            w2 (N=6,  h=2.0): avail_income=6.0,  util=0.432, gross=6.432,  net=4.824
            annual = 9.972 + 4.824 = 14.796
        """
        from solar_challenge.gridservices import (
            GRID_SERVICES_RATE_BANDS,
            EventWindow,
            GridServicesEventsConfig,
            compute_grid_services_at_events,
        )

        fleet, w1 = self._make_fixture()
        w2 = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=6, event_hours=2.0,
        )
        cfg = GridServicesEventsConfig(band="central", event_windows=(w1, w2))

        band = GRID_SERVICES_RATE_BANDS.resolve("central")

        def _expected_net(w):
            avail_income = 1.0 * band.availability_gbp_per_kw_per_event * w.events_per_year
            util_income = (
                1.0
                * cfg.utilisation_factor
                * w.event_hours
                * (band.utilisation_gbp_per_mwh / 1000.0)
                * w.events_per_year
            )
            return (avail_income + util_income) * (1.0 - cfg.aggregator_share)

        exp_w1 = _expected_net(w1)
        exp_w2 = _expected_net(w2)

        result = compute_grid_services_at_events(fleet, cfg)

        assert len(result.per_window_avail_kw) == 2
        assert len(result.per_window_income_gbp) == 2
        assert result.per_window_income_gbp[0] == pytest.approx(exp_w1)
        assert result.per_window_income_gbp[1] == pytest.approx(exp_w2)
        assert result.annual_income_gbp == pytest.approx(exp_w1 + exp_w2)

    def test_zero_spare_fleet_income_is_zero(self) -> None:
        """Floor-pinned home: all income is 0.0 and all per-window entries are 0.0."""
        from solar_challenge.battery import BatteryConfig
        from solar_challenge.gridservices import (
            EventWindow,
            GridServicesEventsConfig,
            compute_grid_services_at_events,
        )

        idx = pd.DatetimeIndex(
            ["2024-12-02 16:00", "2024-12-02 17:00", "2024-12-02 18:00"],
            tz="Europe/London",
        )
        w = EventWindow(
            months=(12,), weekdays=(0,), hours=(16, 17, 18),
            events_per_year=12, event_hours=3.0,
        )
        # soc pinned at floor (min_soc_kwh=1.0) → E_spare=0 → avail=0
        bat_cfg = BatteryConfig(
            capacity_kwh=10.0, max_discharge_kw=4.0, min_soc_fraction=0.1, soh=1.0,
        )
        home_cfg = _make_gs_home_config(bat_cfg)
        sim = _make_gs_sim_results(
            battery_soc=[1.0, 1.0, 1.0],
            battery_discharge=[0.0, 0.0, 0.0],
            index=idx,
        )
        fleet = _make_gs_fleet_results([(sim, home_cfg)])
        cfg = GridServicesEventsConfig(band="central", event_windows=(w,))

        result = compute_grid_services_at_events(fleet, cfg)

        assert result.annual_income_gbp == 0.0
        assert all(v == 0.0 for v in result.per_window_income_gbp)
        assert all(v == 0.0 for v in result.per_window_avail_kw)

    def test_aggregator_multiplier(self) -> None:
        """agg=0.0 → full gross income; agg=0.5 → exactly half of agg=0.0 annual."""
        from solar_challenge.gridservices import (
            GridServicesEventsConfig,
            compute_grid_services_at_events,
        )

        fleet, w = self._make_fixture()

        cfg_full = GridServicesEventsConfig(
            band="central", event_windows=(w,), aggregator_share=0.0, utilisation_factor=0.6,
        )
        cfg_half = GridServicesEventsConfig(
            band="central", event_windows=(w,), aggregator_share=0.5, utilisation_factor=0.6,
        )

        result_full = compute_grid_services_at_events(fleet, cfg_full)
        result_half = compute_grid_services_at_events(fleet, cfg_half)

        assert result_half.annual_income_gbp == pytest.approx(result_full.annual_income_gbp * 0.5)

