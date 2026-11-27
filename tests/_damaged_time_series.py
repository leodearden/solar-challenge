# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stored run's time series rewritten as a damage of the frame it holds, as tests damage one that no save writes.

Usage::

    from tests._damaged_time_series import rewrite_time_series

    def test_a_time_series_with_a_range_index_is_refused_naming_its_file(storage: RunStorage) -> None:
        store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
        rewrite_time_series(stored_run_dir(storage, "home-1") / "data.parquet", lambda frame: frame.reset_index(drop=True))
        with pytest.raises(StoredRunUnreadable):
            storage.load_run("home-1")
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd


def rewrite_time_series(path: Path, damage: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    """Rewrite the time series at *path* as *damage* of the frame it holds."""
    damage(pd.read_parquet(path, engine="pyarrow")).to_parquet(path, engine="pyarrow")
