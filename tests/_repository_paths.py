# SPDX-License-Identifier: AGPL-3.0-or-later
"""The repository's root and its committed scenarios directory, as absolute paths computed once from this module's location, for tests that read files of the checkout.

Usage::

    from tests._repository_paths import REPOSITORY_ROOT, SCENARIOS_DIR

    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    raw = load_config(SCENARIOS_DIR / "bristol-phase1-flex.yaml")
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPOSITORY_ROOT / "scenarios"
