"""Community energy sharing layer (post-hoc, read-only over FleetResults).

This module implements the peer-to-peer (P2P) community netting layer described
in PRD §3.  Homes are NOT re-simulated; this layer consumes the public aggregate
API of :class:`~solar_challenge.fleet.FleetResults` and derives shared grid flows.

Exported symbols
----------------
CommunityBillingConfig  — forward-compatible billing data container (α; logic in ε)
CommunityConfig         — frozen, picklable simulation configuration
CommunityResults        — output of :func:`simulate_community`
simulate_community      — run P2P netting over an existing FleetResults
validate_community_balance — cross-check the COMMUNITY-BALANCE invariant (PRD §3.1)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import SelfConsumptionStrategy
from solar_challenge.flow import simulate_timestep, validate_energy_balance

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults
    from solar_challenge.tariff import TariffConfig


# ---------------------------------------------------------------------------
# CommunityBillingConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommunityBillingConfig:
    """Forward-compatible billing data container.

    This is a pure data holder populated by γ (config parsing) and consumed by
    ε (VNM pricing).  No pricing logic lives here.

    Attributes
    ----------
    tariff:
        Community import tariff configuration (optional; None = no cost tracking).
    seg_rate_pence_per_kwh:
        Smart Export Guarantee rate in pence per kWh (optional; None = no SEG).
    """

    tariff: Optional["TariffConfig"] = None
    seg_rate_pence_per_kwh: Optional[float] = None


# ---------------------------------------------------------------------------
# CommunityConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommunityConfig:
    """Configuration for a community energy sharing simulation.

    Attributes
    ----------
    sharing_mode:
        Either ``"p2p"`` (peer-to-peer netting, no community battery) or
        ``"community_battery"`` (P2P netting + shared community battery dispatch).
    community_battery:
        Battery configuration for the shared community battery.  *Must* be
        provided when ``sharing_mode="community_battery"`` and *must not* be
        provided when ``sharing_mode="p2p"``.
    billing:
        Optional billing container for γ/ε to populate; no pricing logic here.
    """

    sharing_mode: Literal["p2p", "community_battery"]
    community_battery: Optional[BatteryConfig] = None
    billing: Optional[CommunityBillingConfig] = None

    def __post_init__(self) -> None:
        """Validate mode / battery consistency."""
        if self.sharing_mode not in ("p2p", "community_battery"):
            raise ValueError(
                f"sharing_mode must be 'p2p' or 'community_battery', "
                f"got {self.sharing_mode!r}"
            )
        if self.sharing_mode == "p2p" and self.community_battery is not None:
            raise ValueError(
                "sharing_mode='p2p' must not have a community_battery; "
                "set sharing_mode='community_battery' to enable battery dispatch."
            )
        if self.sharing_mode == "community_battery" and self.community_battery is None:
            raise ValueError(
                "sharing_mode='community_battery' requires a community_battery config; "
                "provide a BatteryConfig or switch to sharing_mode='p2p'."
            )


# ---------------------------------------------------------------------------
# CommunityResults
# ---------------------------------------------------------------------------

@dataclass
class CommunityResults:
    """Output of :func:`simulate_community`.

    All series are in **kW** on the fleet's 1-minute DatetimeIndex
    (``battery_soc`` is in kWh, matching the per-home convention).

    Attributes
    ----------
    grid_import:
        Community-level grid import after P2P netting (kW).
    grid_export:
        Community-level grid export after P2P netting (kW).
    battery_charge:
        Community battery charging power (kW).  Zero for p2p mode.
    battery_discharge:
        Community battery discharging power (kW).  Zero for p2p mode.
    battery_soc:
        Community battery state of charge (kWh).  Zero for p2p mode.
    fleet_results:
        Reference to the source :class:`~solar_challenge.fleet.FleetResults`.
    """

    grid_import: pd.Series
    grid_export: pd.Series
    battery_charge: pd.Series
    battery_discharge: pd.Series
    battery_soc: pd.Series
    fleet_results: "FleetResults"


# ---------------------------------------------------------------------------
# simulate_community
# ---------------------------------------------------------------------------

def simulate_community(
    fleet_results: "FleetResults",
    config: CommunityConfig,
    *,
    validate_balance: bool = True,
) -> CommunityResults:
    """Run community energy sharing over an already-simulated fleet.

    The community layer does NOT re-simulate individual homes.  Instead it
    performs post-hoc P2P netting:

    For each timestep *t*:

    * ``net_surplus  = max(0, total_grid_export[t] - total_grid_import[t])``
    * ``net_deficit  = max(0, total_grid_import[t] - total_grid_export[t])``

    These are fed into :func:`~solar_challenge.flow.simulate_timestep` with
    ``battery=None`` (p2p mode), reusing the self-consumption dispatch path to
    model instantaneous netting at the community connection point.  The output is
    then scaled from kWh-per-step back to kW (×60) in line with the
    ``conversion_factor=60.0`` convention in ``home.py``.

    Parameters
    ----------
    fleet_results:
        Aggregate results from :func:`~solar_challenge.fleet.simulate_fleet`.
    config:
        Community configuration; only ``sharing_mode="p2p"`` is supported in α.
    validate_balance:
        When ``True`` (default), call
        :func:`~solar_challenge.flow.validate_energy_balance` on each timestep
        result to enforce the (◆) per-step invariant.

    Returns
    -------
    CommunityResults
    """
    if config.sharing_mode != "p2p":
        raise NotImplementedError(
            f"sharing_mode={config.sharing_mode!r} is not yet implemented; "
            "community_battery dispatch will be added in β (task #31)."
        )

    surplus: pd.Series = fleet_results.total_grid_export
    deficit: pd.Series = fleet_results.total_grid_import
    index: pd.DatetimeIndex = surplus.index

    strategy = SelfConsumptionStrategy()

    cg_exp_list: list[float] = []
    cg_imp_list: list[float] = []
    cb_ch_list: list[float] = []
    cb_dis_list: list[float] = []
    cb_soc_list: list[float] = []

    for t in index:
        ns = max(0.0, float(surplus[t]) - float(deficit[t]))
        nd = max(0.0, float(deficit[t]) - float(surplus[t]))

        r = simulate_timestep(
            generation_kw=ns,
            demand_kw=nd,
            battery=None,
            timestep_minutes=1.0,
            timestamp=t.to_pydatetime(),
            strategy=strategy,
        )

        if validate_balance:
            validate_energy_balance(r)

        # Convert kWh-per-1-min-step → kW  (×60, matching home.py convention)
        cg_exp_list.append(r.grid_export * 60.0)
        cg_imp_list.append(r.grid_import * 60.0)
        cb_ch_list.append(r.battery_charge * 60.0)
        cb_dis_list.append(r.battery_discharge * 60.0)
        cb_soc_list.append(r.battery_soc)  # kWh, recorded as-is

    return CommunityResults(
        grid_export=pd.Series(cg_exp_list, index=index, dtype=float),
        grid_import=pd.Series(cg_imp_list, index=index, dtype=float),
        battery_charge=pd.Series(cb_ch_list, index=index, dtype=float),
        battery_discharge=pd.Series(cb_dis_list, index=index, dtype=float),
        battery_soc=pd.Series(cb_soc_list, index=index, dtype=float),
        fleet_results=fleet_results,
    )


# ---------------------------------------------------------------------------
# validate_community_balance
# ---------------------------------------------------------------------------

def validate_community_balance(
    fleet_results: "FleetResults",
    community_results: CommunityResults,
    tolerance: float = 0.001,
) -> bool:
    """Validate the COMMUNITY-BALANCE invariant (PRD §3.1) at every timestep.

    The invariant (in kW on the 1-minute index) is::

        Σgen + cg_imp == Σdem + cg_exp + Σ(bch_i − bdis_i) + (cb_ch − cb_dis)

    with ``cb_ch = cb_dis = 0`` in p2p mode.

    This is an *independent cross-check* — it sums from :class:`FleetResults`
    totals and the recorded community deltas, rather than re-deriving dispatch.

    Parameters
    ----------
    fleet_results:
        Source aggregate results.
    community_results:
        Output of :func:`simulate_community`.
    tolerance:
        Maximum allowed imbalance in kW per timestep.

    Returns
    -------
    bool
        ``True`` if every timestep is within tolerance.

    Raises
    ------
    ValueError
        If any timestep violates the balance by more than *tolerance*.
    """
    total_gen: pd.Series = fleet_results.total_generation
    total_dem: pd.Series = fleet_results.total_demand
    home_bch: pd.Series = fleet_results.get_aggregate_series("battery_charge")
    home_bdis: pd.Series = fleet_results.get_aggregate_series("battery_discharge")

    index = total_gen.index

    for t in index:
        energy_in = float(total_gen[t]) + float(community_results.grid_import[t])
        energy_out = (
            float(total_dem[t])
            + float(community_results.grid_export[t])
            + (float(home_bch[t]) - float(home_bdis[t]))
            + (float(community_results.battery_charge[t]) - float(community_results.battery_discharge[t]))
        )
        imbalance = abs(energy_in - energy_out)
        if imbalance > tolerance:
            raise ValueError(
                f"Community energy balance violated at {t}: "
                f"energy_in={energy_in:.6f} kW, energy_out={energy_out:.6f} kW, "
                f"imbalance={imbalance:.6f} kW (tolerance={tolerance} kW)"
            )

    return True
