#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""External-consumer proof program (H1 boundary test).

Run INSIDE an isolated uv environment that contains ONLY the solar_challenge
wheel and its declared runtime dependencies (stdlib + wheel deps; no dev
extras).  Invoked by tests/integration/test_external_install.py via::

    uv run --no-project --isolated --with <wheel> python _external_probe.py

NOT collected by pytest (underscore prefix; matches tests/integration/_helpers.py
convention; pytest's python_files=["test_*.py"] never touches it).

Exit codes:
  0 — all symbols in solar_challenge.__all__ resolved and passed checks.
  1 — at least one symbol failed to resolve or failed the callable/not-None check.
"""
from __future__ import annotations

import inspect
import sys


# ---------------------------------------------------------------------------
# 1. Import the installed package
# ---------------------------------------------------------------------------
import solar_challenge as s

# ---------------------------------------------------------------------------
# 2. Site-packages guard: confirm we loaded from the INSTALLED wheel,
#    not from the worktree src/ (which would make the test vacuous).
# ---------------------------------------------------------------------------
pkg_file: str = getattr(s, "__file__", "") or ""
if "site-packages" not in pkg_file:
    print(
        f"ERROR: solar_challenge loaded from unexpected path: {pkg_file!r}\n"
        "Expected 'site-packages' in the path — the wheel was not installed correctly\n"
        "or a src/ directory leaked into sys.path.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Resolve every name in __all__ and classify it.
#    Pattern adapted from tests/unit/test_init_lazy_surface.py:47-64,
#    but running in the isolated subprocess against the installed wheel.
# ---------------------------------------------------------------------------
failures: list[str] = []

for name in s.__all__:
    # Attempt to resolve the symbol via the lazy loader (or cached attribute).
    try:
        obj = getattr(s, name)
    except (AttributeError, ImportError, Exception) as exc:  # noqa: BLE001
        failures.append(f"  RESOLVE ERROR  {name!r}: {type(exc).__name__}: {exc}")
        continue

    # Classification: class or routine → must be callable; otherwise → must be non-None.
    # Surface-agnostic: avoids fragile per-class constructor knowledge (H1 relaxed contract).
    if inspect.isclass(obj) or inspect.isroutine(obj):
        if not callable(obj):
            failures.append(
                f"  CALLABLE FAIL  {name!r}: expected callable, got {type(obj)!r}"
            )
    else:
        if obj is None:
            failures.append(
                f"  NONE CONSTANT  {name!r}: expected non-None constant, got None"
            )

# ---------------------------------------------------------------------------
# 4. Report and exit.
# ---------------------------------------------------------------------------
n = len(s.__all__)
if failures:
    print(f"EXTERNAL-INSTALL-FAIL {len(failures)}/{n} symbols failed:", file=sys.stderr)
    for msg in failures:
        print(msg, file=sys.stderr)
    sys.exit(1)
else:
    print(f"EXTERNAL-INSTALL-OK {n}/{n}")
    sys.exit(0)
