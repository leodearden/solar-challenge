# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two-home fleet the `fleet sweep` tests sweep, and each way `fleet sweep` sweeps its battery capacity.

Usage::

    from tests._fleet_sweep_paths import SWEEP_PATHS, SweepPath, two_home_fleet_distribution

    @pytest.mark.parametrize("path", SWEEP_PATHS)
    def test_each_point(path: SweepPath) -> None:
        document = {"fleet_distribution": two_home_fleet_distribution(battery={"capacity_kwh": path.capacity_kwh})}
        ...  # run `fleet sweep` on document with path.options; it sweeps path.param_name over path.values
"""

from dataclasses import dataclass

import pytest


def two_home_fleet_distribution(**blocks: object) -> dict[str, object]:
    """A fleet_distribution of two homes with 4 kW of PV and a deterministic 3400 kWh a year of load, and blocks besides."""
    return {
        "n_homes": 2,
        "seed": 42,
        "pv": {"capacity_kw": 4.0},
        "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
        **blocks,
    }


@dataclass(frozen=True)
class SweepPath:
    """A way `fleet sweep` sweeps a fleet file's battery capacity: the file's capacity_kwh, the options that sweep it, the name of the swept parameter, and the values it takes."""

    capacity_kwh: object
    options: tuple[str, ...]
    param_name: str
    values: tuple[float, ...]


YAML_SWEEP = SweepPath(
    capacity_kwh={
        "type": "proportional_to",
        "source": "pv.capacity_kw",
        "multiplier": {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"},
    },
    options=(),
    param_name="battery.capacity_kwh.multiplier",
    values=(1.25, 2.5),
)

PARAM_SWEEP = SweepPath(
    capacity_kwh="${CAP}",
    options=("--param", "CAP", "--min", "5", "--max", "10", "--steps", "2", "--mode", "linear"),
    param_name="CAP",
    values=(5.0, 10.0),
)

SWEEP_PATHS = (
    pytest.param(YAML_SWEEP, id="yaml-sweep"),
    pytest.param(PARAM_SWEEP, id="param-sweep"),
)
