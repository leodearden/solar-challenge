# SPDX-License-Identifier: AGPL-3.0-or-later
"""Relocation contract tests for FinanceConfig (T2).

These tests pin:
  1. FinanceConfig is DEFINED in solar_challenge.finance (not merely aliased there).
  2. Importing solar_challenge.config and solar_challenge.finance in either order
     produces no circular-import error, and constructing an instance (which
     triggers __post_init__ => lazy ConfigurationError import) works in both.
  3. Validation is preserved: the defaults hold, and a bad vat_rate raises
     ConfigurationError.

solar_challenge.config no longer re-exports FinanceConfig (H5 as amended in
docs/prds/domain-library-extraction.md, task 242).
"""
from __future__ import annotations

import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# 1. FinanceConfig is DEFINED in finance module
# ---------------------------------------------------------------------------


def test_finance_config_defined_in_finance_module() -> None:
    """FinanceConfig.__module__ must be 'solar_challenge.finance' (not config)."""
    import solar_challenge.finance as f  # type: ignore[attr-defined]

    fc_cls = f.FinanceConfig  # AttributeError pre-move => RED
    assert fc_cls.__module__ == "solar_challenge.finance", (
        f"Expected __module__=='solar_challenge.finance', got '{fc_cls.__module__}'"
    )


# ---------------------------------------------------------------------------
# 2. Both import orders are acyclic and instance-construction works
# ---------------------------------------------------------------------------

_PROG_A = (
    "import solar_challenge.config; "
    "import solar_challenge.finance as f; "
    "assert f.FinanceConfig.__module__ == 'solar_challenge.finance', '__module__'; "
    "fc = f.FinanceConfig(standing_charge_pence_per_day=50.0); "
    "assert fc.vat_rate == 0.05, 'default vat_rate'"
)

_PROG_B = (
    "import solar_challenge.finance as f; "
    "import solar_challenge.config; "
    "assert f.FinanceConfig.__module__ == 'solar_challenge.finance', '__module__'; "
    "fc = f.FinanceConfig(standing_charge_pence_per_day=50.0); "
    "assert fc.vat_rate == 0.05, 'default vat_rate'"
)


@pytest.mark.parametrize(
    "prog,label",
    [
        (_PROG_A, "config-first"),
        (_PROG_B, "finance-first"),
    ],
)
def test_both_import_orders_acyclic(prog: str, label: str) -> None:
    """Importing in either order (config-first or finance-first) must not cycle."""
    result = subprocess.run(
        [sys.executable, "-c", prog],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{label}] subprocess exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# 3. Validation is preserved (defaults + bad-input raises ConfigurationError)
# ---------------------------------------------------------------------------


def test_validation_preserved() -> None:
    """FinanceConfig reachable from finance module; bad vat_rate raises ConfigurationError."""
    from solar_challenge.config import ConfigurationError
    import solar_challenge.finance as f  # type: ignore[attr-defined]

    # Valid construction — check key defaults
    fc = f.FinanceConfig(standing_charge_pence_per_day=50.0)
    assert fc.vat_rate == 0.05
    assert fc.own_use_rate_pence_per_kwh == 15.0

    # Validation preserved: vat_rate > 1 must raise ConfigurationError
    with pytest.raises(ConfigurationError):
        f.FinanceConfig(standing_charge_pence_per_day=50.0, vat_rate=2.0)
