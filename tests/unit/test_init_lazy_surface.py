"""Runtime behaviour tests for the frozen public API surface in solar_challenge.__init__.

T3 owns this file (tests/unit/test_init_lazy_surface.py) and src/solar_challenge/__init__.py.
T4 owns the surface-lock/freeze test (tests/unit/test_public_api_surface.py — a SEPARATE file).
"""

import subprocess
import sys

import pytest

import solar_challenge


# ---------------------------------------------------------------------------
# Step-1 gate: __all__ completeness and no-duplicates / no-CLI check
# ---------------------------------------------------------------------------

EXPECTED_ALL: set[str] = {
    # --- finance / bill engine (finance.py) ---
    "householder_bill",
    "solve_cost_recovery_rate",
    "bill_distribution",
    "BillBreakdown",
    "BillDistribution",
    "CostRecoverySolution",
    "FinanceConfig",
    # --- signature-closure types (home.py / config.py / fleet.py) ---
    "SummaryStatistics",
    "ScenarioConfig",
    "FleetConfig",
    "FleetResults",
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy",
    "DispatchDecision",
    "GridChargeContext",
    "compute_grid_charge_power_kw",
    "SelfConsumptionStrategy",
    "TOUOptimizedStrategy",
    "PeakShavingStrategy",
    "DispatchTariffPeriod",  # alias for dispatch.TariffPeriod (collision-renamed)
    # --- battery (battery.py) ---
    "Battery",
    "BatteryConfig",
    "compute_soh",
    # --- flow (flow.py) ---
    "EnergyFlowResult",
    "simulate_timestep",
    "simulate_timestep_tou",
    "validate_energy_balance",
    "calculate_self_consumption",
    "calculate_excess_pv",
    "calculate_shortfall",
    # --- tariff (tariff.py) ---
    "TariffConfig",
    "TariffPeriod",
    "calculate_bill",
    "FlatRateTariff",
    # --- seg (seg.py) ---
    "SEGTariff",
    "resolve_seg_tariff",
    "calculate_seg_revenue",
    "SEG_PRESETS",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand",
    "GridServicesRateBands",
    "resolve_grid_services_rate_band",
    "EventWindow",
    "GridServicesEventsConfig",
    "GridServicesAtEvents",
    "compute_fleet_spare_capacity_kw",
    "compute_grid_services_at_events",
    "GRID_SERVICES_RATE_BANDS",
    "DEFAULT_EVENT_WINDOWS",
    # --- community (community.py) ---
    "CommunityConfig",
    "CommunityBillingConfig",
    "CommunityResults",
    "simulate_community",
    "validate_community_balance",
    # --- pv (pv.py) ---
    "PVConfig",
    "simulate_pv_output",
    "create_model_chain",
    "create_pv_system",
    "apply_degradation",
    "calculate_degradation_factor",
    "interpolate_to_minute_resolution",
    # --- weather (weather.py) ---
    "get_tmy_data",
    "WeatherCache",
    "get_weather_cache",
    "set_weather_cache",
    # --- load (load.py) ---
    "LoadConfig",
    "OFGEM_TDCV_BY_OCCUPANTS",
    "ELEXON_PROFILE_CLASS_1",
    "SEASONAL_FACTORS",
    # --- location (location.py) ---
    "Location",
}


def test_all_is_complete_frozen_surface() -> None:
    """__all__ must be exactly the 68-name frozen surface from PRD §3.1."""
    assert hasattr(solar_challenge, "__all__"), "__all__ not defined on package"
    actual = set(solar_challenge.__all__)
    assert actual == EXPECTED_ALL, (
        f"Extra names: {actual - EXPECTED_ALL}\nMissing names: {EXPECTED_ALL - actual}"
    )
    # No duplicates
    as_list = list(solar_challenge.__all__)
    assert len(as_list) == len(set(as_list)), "Duplicate names in __all__"
    # CLI stays out of __all__
    assert "get_cli_app" not in actual
    assert not any(n.startswith("cli") or n.startswith("web") for n in actual)


# ---------------------------------------------------------------------------
# Step-3 gate: lazy resolver runtime behaviour
# ---------------------------------------------------------------------------


def test_every_name_resolves_and_caches() -> None:
    """Each name in __all__ resolves via lazy __getattr__ and is cached on second access."""
    for name in solar_challenge.__all__:
        obj = getattr(solar_challenge, name)
        assert obj is not None, f"solar_challenge.{name} resolved to None"
        # After first access the resolved object is cached in the module namespace
        assert name in vars(solar_challenge), f"{name!r} not in vars() after first access"
        # Repeat access returns the identical (cached) object
        obj2 = getattr(solar_challenge, name)
        assert obj is obj2, f"Cached and fresh {name!r} differ"


def test_unknown_attribute_raises() -> None:
    """Accessing an undefined attribute raises AttributeError."""
    with pytest.raises(AttributeError):
        _ = solar_challenge.does_not_exist  # type: ignore[attr-defined]


def test_tariffperiod_collision_resolved() -> None:
    """dispatch.TariffPeriod (Enum) and tariff.TariffPeriod (dataclass) are distinct objects;
    the alias DispatchTariffPeriod resolves to the dispatch Enum."""
    import solar_challenge.dispatch as _dispatch
    import solar_challenge.tariff as _tariff

    assert solar_challenge.DispatchTariffPeriod is _dispatch.TariffPeriod
    assert solar_challenge.TariffPeriod is _tariff.TariffPeriod
    assert solar_challenge.DispatchTariffPeriod is not solar_challenge.TariffPeriod


def test_import_is_pvlib_free() -> None:
    """`import solar_challenge` alone must NOT pull pvlib into sys.modules."""
    code = (
        "import sys, solar_challenge; "
        "sys.exit(0 if 'pvlib' not in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"pvlib was imported by 'import solar_challenge'.\nstderr: {result.stderr}"
    )


def test_touching_pv_imports_pvlib() -> None:
    """`solar_challenge.PVConfig` (pv.py) DOES pull pvlib — lazy proven in both directions."""
    code = (
        "import sys, solar_challenge; "
        "solar_challenge.PVConfig; "  # trigger lazy load of pv.py
        "sys.exit(0 if 'pvlib' in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"pvlib was NOT imported after touching solar_challenge.PVConfig.\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Step-5 gate: __dir__
# ---------------------------------------------------------------------------


def test_dir_returns_sorted_all() -> None:
    """`dir(solar_challenge)` returns exactly sorted(__all__)."""
    assert dir(solar_challenge) == sorted(solar_challenge.__all__)
