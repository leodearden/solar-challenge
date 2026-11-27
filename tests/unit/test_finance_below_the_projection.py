# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finance's bill arithmetic sits below the projection: importing finance loads neither pvlib, the fleet nor the projection, and no module the projection builds on loads it (task 928).

Each case imports in a fresh ``python -I`` interpreter, so modules imported earlier
cannot hide what the import loads.
"""

import pytest

from tests._modules_loaded_by_importing import modules_loaded_by_importing, package_modules_loaded_by_importing

_PROJECTION = "solar_challenge.projection"
_ABOVE_FINANCE = frozenset({"pvlib", "solar_challenge.fleet", _PROJECTION})
_BELOW_THE_PROJECTION = (
    "solar_challenge.battery",
    "solar_challenge.config",
    "solar_challenge.finance",
    "solar_challenge.fleet",
    "solar_challenge.gridservices",
    "solar_challenge.home",
    "solar_challenge.pv",
)


def test_importing_finance_loads_neither_pvlib_the_fleet_nor_the_projection() -> None:
    loaded = modules_loaded_by_importing("solar_challenge.finance")

    assert _ABOVE_FINANCE.isdisjoint(loaded), (
        f"importing solar_challenge.finance loaded {sorted(_ABOVE_FINANCE & loaded)}"
    )


@pytest.mark.parametrize("module", _BELOW_THE_PROJECTION)
def test_importing_a_module_below_the_projection_does_not_load_it(module: str) -> None:
    assert _PROJECTION not in package_modules_loaded_by_importing(module), (
        f"importing {module} loaded {_PROJECTION}, which sits above it"
    )
