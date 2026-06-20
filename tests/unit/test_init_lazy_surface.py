"""Runtime behaviour tests for the frozen public API surface in solar_challenge.__init__.

T3 owns this file (tests/unit/test_init_lazy_surface.py) and src/solar_challenge/__init__.py.
T4 owns the surface-lock/freeze test (tests/unit/test_public_api_surface.py — a SEPARATE file).
"""

import ast
import pathlib
import subprocess
import sys

import pytest

import solar_challenge


# ---------------------------------------------------------------------------
# Step-1 gate: structural __all__ checks (T3 owns no-dups / no-CLI / count)
# T4 (test_public_api_surface.py) is the authoritative freeze test that pins
# the exact set of 68 names — avoid maintaining a second EXPECTED_ALL copy here.
# ---------------------------------------------------------------------------


def test_all_is_complete_frozen_surface() -> None:
    """__all__ has no duplicates, excludes CLI names, and has the expected count.

    T4 (test_public_api_surface.py) is the authoritative surface-lock that pins
    the exact set of names. This test checks only structural properties T3 owns.
    """
    assert hasattr(solar_challenge, "__all__"), "__all__ not defined on package"
    as_list = list(solar_challenge.__all__)
    # No duplicates
    assert len(as_list) == len(set(as_list)), "Duplicate names in __all__"
    # Exact count matches PRD §3.1 (68 names); T4 pins the actual names
    assert len(as_list) == 68, f"Expected 68 names in __all__, got {len(as_list)}"
    # CLI stays out of __all__
    actual = set(solar_challenge.__all__)
    assert "get_cli_app" not in actual
    assert not any(n.startswith("cli") or n.startswith("web") for n in actual)


# ---------------------------------------------------------------------------
# Step-3 gate: lazy resolver runtime behaviour
# ---------------------------------------------------------------------------


def test_every_name_resolves_and_caches() -> None:
    """Each name resolves to the correct origin-module object and is cached on second access."""
    from importlib import import_module

    for name, mod_name in solar_challenge._SYMBOL_MODULE.items():  # type: ignore[attr-defined]
        source_name = solar_challenge._SOURCE_NAME.get(name, name)  # type: ignore[attr-defined]
        origin_obj = getattr(import_module(f"solar_challenge.{mod_name}"), source_name)
        # Resolve via lazy __getattr__ (or return already-cached value)
        resolved = getattr(solar_challenge, name)
        assert resolved is origin_obj, (
            f"solar_challenge.{name} resolved to wrong object; "
            f"expected solar_challenge.{mod_name}.{source_name}"
        )
        # After first access the resolved object is cached in the module namespace
        assert name in vars(solar_challenge), f"{name!r} not in vars() after first access"
        # Repeat access returns the identical (cached) object
        obj2 = getattr(solar_challenge, name)
        assert resolved is obj2, f"Cached and fresh {name!r} differ"


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


# ---------------------------------------------------------------------------
# TYPE_CHECKING sync guard: verifies the typed re-export block stays in sync
# with __all__ so a forgotten entry breaks this test rather than mypy for consumers.
# ---------------------------------------------------------------------------


def test_type_checking_block_names_match_all() -> None:
    """Names bound in the TYPE_CHECKING block must equal set(__all__) plus 'Typer'.

    Parses __init__.py with ast to extract the names bound in the TYPE_CHECKING
    block and verifies they stay in sync with __all__. Adding a name to __all__
    and _SYMBOL_MODULE but forgetting the TYPE_CHECKING re-export would otherwise
    silently break mypy --strict for consumers without failing this package's own checks.
    """
    src = pathlib.Path(solar_challenge.__file__).read_text()
    tree = ast.parse(src)

    tc_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                for stmt in node.body:
                    if isinstance(stmt, ast.ImportFrom):
                        for alias in stmt.names:
                            # asname is the local binding; fall back to the imported name
                            tc_names.add(alias.asname if alias.asname else alias.name)

    # TYPE_CHECKING block includes "Typer" for get_cli_app()'s return annotation;
    # Typer is NOT in __all__ — CLI is shipped but unfrozen.
    expected = set(solar_challenge.__all__) | {"Typer"}
    assert tc_names == expected, (
        f"TYPE_CHECKING block out of sync with __all__.\n"
        f"Extra (not in __all__ + Typer): {tc_names - expected}\n"
        f"Missing (in __all__ but not TYPE_CHECKING): {expected - tc_names}"
    )
