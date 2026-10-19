# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a RunStorage keeps the files of a run it stores.

The layout is the one solar_challenge.web.storage's module docstring documents,
``{data_dir}/runs/{run_id}/``. It is stated here, not asked of RunStorage's private
helpers, so a test that finds a run's files through stored_run_dir fails when the
stored layout moves, and a deliberate move changes this module only.

Usage::

    from tests._run_storage_layout import stored_run_dir

    assert (stored_run_dir(storage, run_id) / "config.json").exists()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solar_challenge.web.storage import RunStorage


def stored_run_dir(storage: RunStorage, run_id: str) -> Path:
    """Return the directory that holds the files of the run stored under *run_id*."""
    return storage.data_dir / "runs" / run_id
