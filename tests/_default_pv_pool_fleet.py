# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's default PV pool, FLEET_COMPONENTS['pv']'s starting shuffled pool, 100 values, set for a fleet of 200 homes: a fleet the grammar refuses, naming pv.capacity_kw and 200.

DEFAULT_PV_POOL_FLEET_FORM is that fleet as the fleet page posts it, and
DEFAULT_PV_POOL_FLEET_YAML as a scenario file writes it.
"""

from typing import Any

import yaml

_POOL_VALUES = (3.0, 4.0, 5.0, 6.0)
_POOL_COUNTS = (20, 40, 30, 10)
DEFAULT_PV_POOL_FLEET_HOMES = 200

DEFAULT_PV_POOL_FLEET_FORM: dict[str, Any] = {
    "n_homes": DEFAULT_PV_POOL_FLEET_HOMES,
    "seed": 1,
    "pv": {"capacity_kw": {"type": "shuffled_pool", "values": list(_POOL_VALUES), "counts": list(_POOL_COUNTS)}},
    "load": {"annual_consumption_kwh": 3500.0},
}

DEFAULT_PV_POOL_FLEET_YAML = yaml.safe_dump(
    {
        "name": "Default PV pool, 200 homes",
        "fleet_distribution": {
            "n_homes": DEFAULT_PV_POOL_FLEET_HOMES,
            "seed": 1,
            "pv": {
                "capacity_kw": {"type": "shuffled_pool", "values": list(_POOL_VALUES), "counts": list(_POOL_COUNTS)}
            },
            "load": {"annual_consumption_kwh": 3500.0},
        },
    }
)
