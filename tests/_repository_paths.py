# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paths of the repository's committed directories, absolute and computed once from this module's location, for tests that read the files in them.

Usage::

    from tests._repository_paths import SCENARIOS_DIR

    raw = load_config(SCENARIOS_DIR / "bristol-phase1-flex.yaml")
"""

from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = _REPOSITORY_ROOT / "scenarios"
