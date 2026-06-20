"""Authoritative surface-lock / freeze guard for the solar_challenge public-API seam.

This is the T4 contract file (PRD docs/prds/domain-library-extraction.md §3.5,
§9 H2/H3/H4, decomposition §10 T4).  It is the single canonical executable
specification that future maintainers must update when the public surface changes.

Concerns:
  H2 surface-lock  — FROZEN_SET pins the exact 68 public names (test_all_equals_frozen_set)
  H2 kind          — EXPECTED_KIND pins the introspected kind of each name
                     (test_expected_kind_keys_match_frozen_set,
                      test_every_name_resolves_to_expected_kind)
  H3 laziness      — pvlib is absent after bare import; present after touching PVConfig
                     (test_import_is_pvlib_free, test_touching_pvconfig_imports_pvlib)
  H4 collision     — DispatchTariffPeriod / TariffPeriod are distinct objects pointing
                     to different origin classes (test_tariffperiod_collision_resolved)

Relationship to T3 (tests/unit/test_init_lazy_surface.py):
  T3 owns structural checks (count / no-dup / no-CLI / lazy-resolver caching / __dir__ /
  TYPE_CHECKING sync).  T3 defers exact-name pinning to T4.  Bounded overlap in H3 / H4
  is deliberate — this file must stand alone as the complete executable contract.
"""

import inspect
import subprocess
import sys

import solar_challenge


# ---------------------------------------------------------------------------
# H2 surface-lock: committed frozenset of the exact 68 public names
#
# Mirrors PRD §3.1 grouped by origin module.  Any add/remove to __all__ must
# be reflected here; the test below fails with a clear symmetric-difference
# message naming the drifted symbol(s).
# ---------------------------------------------------------------------------
FROZEN_SET: frozenset[str] = frozenset({
    # --- finance / bill engine (finance.py) ---
    "householder_bill",
    "solve_cost_recovery_rate",
    "bill_distribution",
    "BillBreakdown",
    "BillDistribution",
    "CostRecoverySolution",
    "FinanceConfig",
    # --- signature-closure types ---
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
    "DispatchTariffPeriod",
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
})


def test_all_equals_frozen_set() -> None:
    """H2 surface-lock: solar_challenge.__all__ must equal FROZEN_SET exactly.

    Fails on any add/remove to __all__ without updating FROZEN_SET.
    The symmetric-difference message names the exact drifted symbol(s).

    Also asserts len==68 explicitly — a bare set-compare would silently pass
    if __all__ contained a duplicate entry (set collapses duplicates).
    """
    actual = set(solar_challenge.__all__)
    diff = actual.symmetric_difference(FROZEN_SET)
    assert actual == FROZEN_SET, (
        f"__all__ has drifted from FROZEN_SET.  "
        f"Symmetric difference: {sorted(diff)}"
    )
    assert len(solar_challenge.__all__) == len(FROZEN_SET) == 68, (
        f"Length mismatch: __all__ has {len(solar_challenge.__all__)} names, "
        f"FROZEN_SET has {len(FROZEN_SET)} (expected 68 each)"
    )
    # Document the CLI-excluded invariant explicitly
    assert "get_cli_app" not in solar_challenge.__all__, (
        "get_cli_app must remain excluded from __all__ (shipped but unfrozen CLI)"
    )


# ---------------------------------------------------------------------------
# H2 kind: targeted gotcha-guard for names whose kind would be WRONG if
# inferred from naming convention alone.
#
# The full surface is pinned by FROZEN_SET above.  This table supplements
# it with explicit kind checks only for the non-obvious entries:
#   • FlatRateTariff  — CamelCase looks like a class; it is a factory function
#   • GRID_SERVICES_RATE_BANDS — UPPER_CASE looks like a plain constant; it is
#     a frozen-dataclass instance (still "constant" in our taxonomy, but the
#     distinction is worth pinning)
#   • DispatchTariffPeriod — Enum alias; verifies it resolves to a class, not
#     to a string/sentinel from a botched re-export
#
# taxonomy (for reference):
#   class    → inspect.isclass  (covers dataclasses, Enums, ABCs)
#   function → inspect.isroutine (covers all def functions / factory callables)
#   constant → neither           (dicts, tuples, lists, frozen-dataclass instances)
# ---------------------------------------------------------------------------
EXPECTED_KIND: dict[str, str] = {
    "FlatRateTariff": "function",           # GOTCHA: CamelCase factory, NOT a class
    "GRID_SERVICES_RATE_BANDS": "constant", # GOTCHA: frozen-dataclass instance, NOT a class
    "DispatchTariffPeriod": "class",        # Enum alias — verifies clean class re-export
}


def _kind(obj: object) -> str:
    """Classify obj as 'class', 'function', or 'constant' by introspection."""
    if inspect.isclass(obj):
        return "class"
    if inspect.isroutine(obj):
        return "function"
    return "constant"


def test_expected_kind_keys_match_frozen_set() -> None:
    """Sync guard: every key in EXPECTED_KIND must exist in FROZEN_SET.

    EXPECTED_KIND is a targeted gotcha-guard (not a mirror of the full surface),
    so equality is not required — only that no stale / misspelled gotcha entry
    references a name that was removed from the public surface.
    """
    stale = set(EXPECTED_KIND) - FROZEN_SET
    assert not stale, (
        f"EXPECTED_KIND contains names not in FROZEN_SET (stale/misspelled?): "
        f"{sorted(stale)}"
    )


def test_every_name_resolves_to_expected_kind() -> None:
    """H2: all public names resolve via the PEP-562 lazy loader; gotcha kinds are correct.

    Iterates every name in FROZEN_SET — exercises solar_challenge.__getattr__
    and must not raise AttributeError for any name.

    For the small subset named in EXPECTED_KIND (the gotcha entries where naming
    convention would mislead), additionally asserts the introspected kind is correct.
    """
    for name in sorted(FROZEN_SET):
        obj = getattr(solar_challenge, name)  # triggers lazy loader; must not raise
        if name in EXPECTED_KIND:
            actual_kind = _kind(obj)
            assert actual_kind == EXPECTED_KIND[name], (
                f"solar_challenge.{name}: expected kind={EXPECTED_KIND[name]!r}, "
                f"got kind={actual_kind!r} (type={type(obj).__name__})"
            )


# ---------------------------------------------------------------------------
# H3 laziness: pvlib must NOT be imported by a bare `import solar_challenge`;
# it MUST be present after touching a pv-module symbol.
#
# Both sub-tests use a CLEAN interpreter via subprocess to avoid contamination
# from pvlib being already loaded by the test process.
# ---------------------------------------------------------------------------


def test_import_is_pvlib_free() -> None:
    """`import solar_challenge` alone must NOT pull pvlib into sys.modules (H3 clean direction)."""
    code = (
        "import sys, solar_challenge; "
        "sys.exit(0 if 'pvlib' not in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pvlib was imported by 'import solar_challenge'.\nstderr: {result.stderr}"
    )


def test_touching_pvconfig_imports_pvlib() -> None:
    """`solar_challenge.PVConfig` DOES pull pvlib — lazy proven in both directions (H3 load direction)."""
    code = (
        "import sys, solar_challenge; "
        "solar_challenge.PVConfig; "
        "sys.exit(0 if 'pvlib' in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pvlib was NOT imported after touching solar_challenge.PVConfig.\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# H4 collision: DispatchTariffPeriod (dispatch Enum) and TariffPeriod
# (tariff dataclass) are distinct objects with distinct origin classes.
# ---------------------------------------------------------------------------


def test_tariffperiod_collision_resolved() -> None:
    """H4: DispatchTariffPeriod and TariffPeriod are distinct objects (collision-renamed correctly).

    dispatch.TariffPeriod (Enum) is exposed as DispatchTariffPeriod.
    tariff.TariffPeriod (dataclass) is exposed as TariffPeriod.
    They must be distinct — otherwise one silently shadows the other.
    """
    import solar_challenge.dispatch as _dispatch
    import solar_challenge.tariff as _tariff

    assert solar_challenge.DispatchTariffPeriod is _dispatch.TariffPeriod, (
        "solar_challenge.DispatchTariffPeriod must be dispatch.TariffPeriod"
    )
    assert solar_challenge.TariffPeriod is _tariff.TariffPeriod, (
        "solar_challenge.TariffPeriod must be tariff.TariffPeriod"
    )
    assert solar_challenge.DispatchTariffPeriod is not solar_challenge.TariffPeriod, (
        "DispatchTariffPeriod and TariffPeriod must be distinct objects"
    )
