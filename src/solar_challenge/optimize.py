# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discrete install-config sweep and optimisation tools (W3).

This module provides the homogeneous-install config enumerator that is the
foundation of the W3 cost-recovery sweep (PRD §3.1/§3.2/§10-A).

Exported symbols
----------------
ConfigPoint           — frozen (pv_kwp, battery_kwh, inverter_kw) value object
enumerate_configs     — cartesian-product enumerator over three discrete install dims
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Optional, Sequence

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.home import HomeConfig


# ---------------------------------------------------------------------------
# ConfigPoint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigPoint:
    """A single discrete install specification for the W3 sweep.

    Attributes:
        pv_kwp: PV DC rated capacity in kWp (must be > 0).
        battery_kwh: Battery usable capacity in kWh (0 = no battery; must be >= 0).
        inverter_kw: AC inverter rated capacity in kW (must be > 0).
    """

    pv_kwp: float
    battery_kwh: float
    inverter_kw: float

    def __post_init__(self) -> None:
        """Validate install dimensions."""
        if self.pv_kwp <= 0:
            raise ValueError(
                f"pv_kwp must be > 0, got {self.pv_kwp}"
            )
        if self.battery_kwh < 0:
            raise ValueError(
                f"battery_kwh must be >= 0, got {self.battery_kwh}"
            )
        if self.inverter_kw <= 0:
            raise ValueError(
                f"inverter_kw must be > 0, got {self.inverter_kw}"
            )


# ---------------------------------------------------------------------------
# enumerate_configs
# ---------------------------------------------------------------------------

def enumerate_configs(
    base: ScenarioConfig,
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> list[tuple[ConfigPoint, ScenarioConfig]]:
    """Enumerate homogeneous-install scenarios over the cartesian product of three
    discrete install dimensions.

    For each combination in ``itertools.product(pv_kwp, battery_kwh, inverter_kw)``
    (pv outermost, inverter innermost) a :class:`ConfigPoint` is built and a new
    :class:`~solar_challenge.config.ScenarioConfig` is produced from *base* via
    ``dataclasses.replace`` so that all scenario-level fields (finance,
    location, period, tariff, seg, name) are preserved automatically.  The homes
    in the returned scenario are homogeneous in PV/battery/inverter install
    (see :func:`_apply_install`).

    Args:
        base: Fleet :class:`~solar_challenge.config.ScenarioConfig`; must have
            ``homes`` populated (``base.homes`` non-empty).  Single-home
            scenarios are rejected because the W3 sweep operates at fleet level.
        pv_kwp: Discrete PV DC capacities in kWp (non-empty).
        battery_kwh: Discrete battery capacities in kWh (non-empty; 0 = no battery).
        inverter_kw: Discrete AC inverter capacities in kW (non-empty).

    Returns:
        A list of ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product`` order.

    Raises:
        ValueError: If *base* is not a fleet scenario or any sequence is empty.
    """
    if not base.homes:
        raise ValueError(
            "enumerate_configs requires a fleet base (base.homes non-empty); "
            "single-home scenarios are not supported."
        )
    if not pv_kwp:
        raise ValueError("pv_kwp must be a non-empty sequence.")
    if not battery_kwh:
        raise ValueError("battery_kwh must be a non-empty sequence.")
    if not inverter_kw:
        raise ValueError("inverter_kw must be a non-empty sequence.")

    result: list[tuple[ConfigPoint, ScenarioConfig]] = []
    for pv, batt, inv in itertools.product(pv_kwp, battery_kwh, inverter_kw):
        point = ConfigPoint(pv_kwp=pv, battery_kwh=batt, inverter_kw=inv)
        new_homes = [_apply_install(h, point) for h in base.homes]
        scenario = replace(base, homes=new_homes)
        result.append((point, scenario))
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _apply_install(home: HomeConfig, point: ConfigPoint) -> HomeConfig:
    """Return a new :class:`~solar_challenge.home.HomeConfig` with the PV,
    inverter, and battery install from *point* applied homogeneously.

    *PV/inverter*: ``pv_config.capacity_kw`` and ``pv_config.inverter_capacity_kw``
    are set to *point.pv_kwp* and *point.inverter_kw* respectively.

    *Battery*:

    - ``point.battery_kwh == 0.0`` → ``battery_config = None`` (no battery).
    - ``point.battery_kwh > 0`` and the home already has a battery →
      ``dataclasses.replace(home.battery_config, capacity_kwh=point.battery_kwh)``
      preserving ``max_discharge_kw``, ``grid_charging``, ``dispatch_strategy``,
      ``efficiency``, and all other base fields (PRD §3.2 / design decision 2).
    - ``point.battery_kwh > 0`` and the home has NO battery → a fresh
      :class:`~solar_challenge.battery.BatteryConfig` is FABRICATED at defaults
      (``max_discharge_kw=2.5``).  This is the intentional divergence from
      ``apply_fleet_overlay`` (which never fabricates a battery).

    ``load_config`` and ``HomeConfig.dispatch_strategy`` are left untouched so
    load/occupancy diversity and the board dispatch strategy are preserved
    (PRD §3.2, W-H2).

    Args:
        home: Original (frozen) home configuration.
        point: Install specification for this grid cell.

    Returns:
        A fresh :class:`~solar_challenge.home.HomeConfig` with updated install.
    """
    new_pv = replace(
        home.pv_config,
        capacity_kw=point.pv_kwp,
        inverter_capacity_kw=point.inverter_kw,
    )

    new_battery: Optional[BatteryConfig]
    if point.battery_kwh == 0.0:
        new_battery = None
    elif home.battery_config is not None:
        new_battery = replace(home.battery_config, capacity_kwh=point.battery_kwh)
    else:
        new_battery = BatteryConfig(capacity_kwh=point.battery_kwh)

    return replace(home, pv_config=new_pv, battery_config=new_battery)
