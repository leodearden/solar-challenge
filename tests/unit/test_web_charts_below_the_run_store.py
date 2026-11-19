# SPDX-License-Identifier: AGPL-3.0-or-later
"""web/run_headline.py is a leaf below the run store, and the charts reach a run's figures through it without loading the run store (task 1413).

Importing web.run_headline loads no solar_challenge.web module but the package and itself,
and importing web.charts loads none of the run store's modules web.database,
web.stored_runs and web.storage.

Each case imports in a fresh ``python -I`` interpreter, so modules imported earlier
cannot hide what the import loads.
"""

import pytest

from tests._modules_loaded_by_importing import web_modules_loaded_by_importing

pytest.importorskip("plotly")

_RUN_STORE_MODULES = frozenset(
    {"solar_challenge.web.database", "solar_challenge.web.stored_runs", "solar_challenge.web.storage"}
)


def test_importing_run_headline_loads_no_other_web_module() -> None:
    assert web_modules_loaded_by_importing("solar_challenge.web.run_headline") == {
        "solar_challenge.web",
        "solar_challenge.web.run_headline",
    }


def test_importing_charts_loads_no_module_of_the_run_store() -> None:
    loaded = web_modules_loaded_by_importing("solar_challenge.web.charts")

    assert _RUN_STORE_MODULES.isdisjoint(loaded), (
        f"importing solar_challenge.web.charts loaded the run store's {sorted(_RUN_STORE_MODULES & loaded)}"
    )
