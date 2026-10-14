"""Runtime behaviour tests for the frozen public API surface in solar_challenge.__init__.

T3 owns this file (tests/unit/test_init_lazy_surface.py) and src/solar_challenge/__init__.py.
T4 owns the surface-lock/freeze test (tests/unit/test_public_api_surface.py — a SEPARATE file).
"""

import ast
import pathlib
import subprocess
import sys
from importlib import import_module

import pytest

import solar_challenge
import solar_challenge.dispatch as _dispatch
import solar_challenge.tariff as _tariff


def _type_checking_imports() -> dict[str, tuple[str, str]]:
    """Each name the package's top-level `if TYPE_CHECKING:` block binds, mapped to
    the module it imports from and the name it imports there."""
    source = pathlib.Path(solar_challenge.__file__).read_text(encoding="utf-8")
    blocks = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
    ]
    return {
        alias.asname or alias.name: (statement.module, alias.name)
        for block in blocks
        for statement in block.body
        if isinstance(statement, ast.ImportFrom) and statement.module is not None
        for alias in statement.names
    }


# ---------------------------------------------------------------------------
# Step-1 gate: structural __all__ checks (T3 owns no-dups / no-CLI / count)
# T4 (test_public_api_surface.py) is the authoritative freeze test that pins
# the exact set of 69 names — avoid maintaining a second EXPECTED_ALL copy here.
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
    # Exact count matches PRD §3.1 (69 names, includes bill); T4 pins the actual names
    assert len(as_list) == 69, f"Expected 69 names in __all__, got {len(as_list)}"
    # CLI stays out of __all__
    actual = set(solar_challenge.__all__)
    assert "get_cli_app" not in actual
    assert not any(n.startswith("cli") or n.startswith("web") for n in actual)


# ---------------------------------------------------------------------------
# Step-3 gate: lazy resolver runtime behaviour
# ---------------------------------------------------------------------------


def test_every_name_resolves_to_its_type_checking_import() -> None:
    """Each __all__ name, on a first and on a repeat access, is the object the
    package's `if TYPE_CHECKING:` block imports under that name.

    Type checkers read that block, so the runtime and typed surfaces must agree.
    A name the block does not import is test_type_checking_block_names_match_all's
    to report.
    """
    imports = _type_checking_imports()
    misresolved: list[str] = []
    for name in solar_challenge.__all__:
        if name not in imports:
            continue
        module, source = imports[name]
        imported = getattr(import_module(module), source)
        first, repeat = getattr(solar_challenge, name), getattr(solar_challenge, name)
        if first is not imported or repeat is not imported:
            misresolved.append(f"solar_challenge.{name} is not {module}.{source}")
    assert not misresolved, (
        "Names that resolve to an object other than their TYPE_CHECKING import:\n"
        + "\n".join(misresolved)
    )


def test_unknown_attribute_raises() -> None:
    """Accessing an undefined attribute raises AttributeError."""
    with pytest.raises(AttributeError):
        _ = solar_challenge.does_not_exist


def test_tariffperiod_collision_resolved() -> None:
    """dispatch.TariffPeriod (Enum) and tariff.TariffPeriod (dataclass) are distinct objects;
    the alias DispatchTariffPeriod resolves to the dispatch Enum."""
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

    Reads the names the block binds through _type_checking_imports() and verifies
    they stay in sync with __all__. Adding a name to __all__ and to the lazy
    loader's map but forgetting its TYPE_CHECKING re-export would otherwise
    silently break mypy --strict for consumers without failing this package's own checks.
    """
    tc_names = set(_type_checking_imports())

    # TYPE_CHECKING block includes "Typer" for get_cli_app()'s return annotation;
    # Typer is NOT in __all__ — CLI is shipped but unfrozen.
    expected = set(solar_challenge.__all__) | {"Typer"}
    assert tc_names == expected, (
        f"TYPE_CHECKING block out of sync with __all__.\n"
        f"Extra (not in __all__ + Typer): {tc_names - expected}\n"
        f"Missing (in __all__ but not TYPE_CHECKING): {expected - tc_names}"
    )
