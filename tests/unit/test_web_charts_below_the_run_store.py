# SPDX-License-Identifier: AGPL-3.0-or-later
"""The charts reach a run's figures through web/run_headline.py without loading the run store (task 1413).

Importing web.charts loads none of the run store's modules web.database, web.stored_runs
and web.storage. That web/run_headline.py is itself a leaf, loading no other web module, is
pinned beside its own tests, in tests/unit/test_web_run_headline.py.

The case imports in a fresh ``python -I`` interpreter, so modules imported earlier
cannot hide what the import loads.
"""

import pytest

from tests._modules_loaded_by_importing import web_modules_loaded_by_importing

pytest.importorskip("plotly")

_RUN_STORE_MODULES = frozenset(
    {"solar_challenge.web.database", "solar_challenge.web.stored_runs", "solar_challenge.web.storage"}
)


def test_importing_charts_loads_no_module_of_the_run_store() -> None:
    loaded = web_modules_loaded_by_importing("solar_challenge.web.charts")

    assert _RUN_STORE_MODULES.isdisjoint(loaded), (
        f"importing solar_challenge.web.charts loaded the run store's {sorted(_RUN_STORE_MODULES & loaded)}"
    )
