# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discrete install-config sweep and optimisation tools (W3).

This module provides the homogeneous-install config enumerator that is the
foundation of the W3 cost-recovery sweep (PRD §3.1/§3.2/§10-A).

Exported symbols
----------------
ConfigPoint           — frozen (pv_kwp, battery_kwh, inverter_kw) value object
enumerate_configs     — cartesian-product enumerator → eager list (small grids)
iter_configs          — generator variant of enumerate_configs (large grids / streaming)
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Iterator, Optional, Sequence

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
        battery_kwh: Battery usable capacity in kWh (must be >= 0).
            The value **exactly** ``0.0`` is the no-battery sentinel; it causes
            :func:`_apply_install` (and therefore :func:`enumerate_configs` /
            :func:`iter_configs`) to set ``battery_config = None`` on every home
            in the scenario.  Any strictly positive value — however small —
            triggers battery fabrication or replacement; there is no epsilon
            tolerance.  Callers must pass ``0.0`` (not, e.g., ``1e-9``) to mean
            "no battery".
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

def iter_configs(
    base: ScenarioConfig,
    pv_kwp: Sequence[float],
    battery_kwh: Sequence[float],
    inverter_kw: Sequence[float],
) -> Iterator[tuple[ConfigPoint, ScenarioConfig]]:
    """Generator variant of :func:`enumerate_configs` for memory-efficient sweeps.

    Yields one ``(ConfigPoint, ScenarioConfig)`` pair at a time, so the caller
    can process each grid cell without holding the entire product in memory.
    Prefer this over :func:`enumerate_configs` when the grid is large (e.g. a
    10×10×10 = 1 000-cell sweep over a 100-home fleet would otherwise produce
    100 000 :class:`~solar_challenge.home.HomeConfig` objects simultaneously).

    Args and raises are identical to :func:`enumerate_configs`.

    Yields:
        ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product(pv_kwp, battery_kwh, inverter_kw)`` order.
    """
    if not base.homes:
        raise ValueError(
            "iter_configs requires a fleet base (base.homes non-empty); "
            "single-home scenarios are not supported."
        )
    if not pv_kwp:
        raise ValueError("pv_kwp must be a non-empty sequence.")
    if not battery_kwh:
        raise ValueError("battery_kwh must be a non-empty sequence.")
    if not inverter_kw:
        raise ValueError("inverter_kw must be a non-empty sequence.")

    for pv, batt, inv in itertools.product(pv_kwp, battery_kwh, inverter_kw):
        point = ConfigPoint(pv_kwp=pv, battery_kwh=batt, inverter_kw=inv)
        new_homes = [_apply_install(h, point) for h in base.homes]
        yield point, replace(base, homes=new_homes)


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

    .. note::
        This function eagerly materialises the full product into a list.  For a
        moderately dense grid (e.g. 10 × 10 × 10 = 1 000 cells, 100-home fleet)
        that is ~100 000 :class:`~solar_challenge.home.HomeConfig` objects held
        simultaneously.  Use :func:`iter_configs` when memory is a concern or
        when scenarios are processed one at a time.

    Args:
        base: Fleet :class:`~solar_challenge.config.ScenarioConfig`; must have
            ``homes`` populated (``base.homes`` non-empty).  Single-home
            scenarios are rejected because the W3 sweep operates at fleet level.
        pv_kwp: Discrete PV DC capacities in kWp (non-empty).
        battery_kwh: Discrete battery capacities in kWh (non-empty; 0.0 = no battery).
        inverter_kw: Discrete AC inverter capacities in kW (non-empty).

    Returns:
        A list of ``(ConfigPoint, ScenarioConfig)`` pairs in
        ``itertools.product`` order.

    Raises:
        ValueError: If *base* is not a fleet scenario or any sequence is empty.
    """
    return list(iter_configs(base, pv_kwp, battery_kwh, inverter_kw))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _apply_install(home: HomeConfig, point: ConfigPoint) -> HomeConfig:
    """Return a new :class:`~solar_challenge.home.HomeConfig` with the PV,
    inverter, and battery install from *point* applied.

    **What is homogenized** (equalized across the fleet for a given
    :class:`ConfigPoint`):

    - PV DC capacity (``pv_config.capacity_kw``)
    - AC inverter capacity (``pv_config.inverter_capacity_kw``)
    - Battery *energy* capacity (``battery_config.capacity_kwh``)

    **What is intentionally left diverse** (preserved from the base home):

    - Battery power limit (``max_discharge_kw``), grid-charging schedule
      (``grid_charging``), and battery dispatch strategy (``dispatch_strategy``).
      Homes that already have a battery therefore retain their individual power
      and dispatch characteristics, while only capacity is swept.
    - Household load profile (``load_config``) and home-level dispatch strategy
      (``HomeConfig.dispatch_strategy``) — occupancy diversity and the board
      dispatch are preserved (PRD §3.2, W-H2).

    .. note::
        Because battery power limits and ``grid_charging`` are left diverse,
        two homes at the same :class:`ConfigPoint` may behave economically
        differently if their base configs differ in those fields.  "Homogeneous
        install" means equal *install capacity*, not equal *dispatch behaviour*.

    *PV/inverter*: ``pv_config.capacity_kw`` and ``pv_config.inverter_capacity_kw``
    are set to *point.pv_kwp* and *point.inverter_kw* respectively.

    *Battery*:

    - ``point.battery_kwh == 0.0`` (exact) → ``battery_config = None`` (no battery).
      There is no epsilon tolerance; a small positive value fabricates a battery.
    - ``point.battery_kwh > 0`` and the home already has a battery →
      ``dataclasses.replace(home.battery_config, capacity_kwh=point.battery_kwh)``
      preserving ``max_discharge_kw``, ``grid_charging``, ``dispatch_strategy``,
      ``efficiency``, and all other base fields (PRD §3.2 / design decision 2).
    - ``point.battery_kwh > 0`` and the home has NO battery → a fresh
      :class:`~solar_challenge.battery.BatteryConfig` is FABRICATED at defaults
      (``max_discharge_kw=2.5``, ``grid_charging=None``, ``dispatch_strategy=None``).
      This is the intentional divergence from ``apply_fleet_overlay`` (which
      never fabricates a battery).

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
