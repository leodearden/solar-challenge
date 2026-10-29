# SPDX-License-Identifier: AGPL-3.0-or-later
"""Community energy sharing: peer-to-peer netting over an already-simulated fleet.

Homes are not re-simulated. This layer reads the public aggregate API of
:class:`~solar_challenge.fleet.FleetResults` and nets the fleet's grid flows at
the community's one connection point, optionally through a shared community
battery. docs/prds/inter-home-community-energy-sharing.md §3.1 proves the
COMMUNITY-BALANCE invariant that :func:`validate_community_balance` checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

import pandas as pd

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import SelfConsumptionStrategy
from solar_challenge.flow import simulate_timestep, validate_energy_balance
from solar_challenge.number_fields import NON_NEGATIVE, as_finite_float, read_field
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.tariff import TariffConfig, calculate_bill
from solar_challenge.timebase import SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults


# ---------------------------------------------------------------------------
# CommunityBillingConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommunityBillingConfig:
    """The community's import tariff and SEG export rate.

    :func:`simulate_community` prices the community's grid flows only when both
    are set; otherwise the result's ``baseline_net_cost_gbp``,
    ``community_net_cost_gbp`` and ``community_savings_gbp`` stay ``None``.

    Attributes
    ----------
    tariff:
        Community import tariff configuration.
    seg_rate_pence_per_kwh:
        Smart Export Guarantee rate in pence per kWh, a finite number of at
        least 0, or ``None``.
    """

    tariff: Optional[TariffConfig] = None
    seg_rate_pence_per_kwh: Optional[float] = None

    def __post_init__(self) -> None:
        """Read a set seg_rate_pence_per_kwh as a finite number of at least 0, holding the float read; None stays None."""
        read_field(self, "seg_rate_pence_per_kwh", as_finite_float, NON_NEGATIVE, optional=True)


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
        The community's import tariff and SEG rate, for pricing its grid
        flows; ``None`` (default) skips billing.
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

    All series are in **kW** on the fleet's DatetimeIndex
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
    sharing_mode:
        Authoritative sharing mode copied directly from
        :attr:`CommunityConfig.sharing_mode` at construction time.
        Either ``"p2p"`` or ``"community_battery"``.
    """

    grid_import: pd.Series
    grid_export: pd.Series
    battery_charge: pd.Series
    battery_discharge: pd.Series
    battery_soc: pd.Series
    fleet_results: "FleetResults"
    sharing_mode: Literal["p2p", "community_battery"]
    # Billing fields populated by simulate_community when config.billing is
    # fully specified (both tariff and seg_rate_pence_per_kwh present).
    baseline_net_cost_gbp: Optional[float] = None
    community_net_cost_gbp: Optional[float] = None
    community_savings_gbp: Optional[float] = None


# ---------------------------------------------------------------------------
# _price_grid_flows
# ---------------------------------------------------------------------------

def _price_grid_flows(
    window: SimulationWindow,
    import_kw: pd.Series,
    export_kw: pd.Series,
    tariff: TariffConfig,
    seg: SEGTariff,
) -> tuple[float, float]:
    """Price grid import and export flows using canonical billing primitives.

    Each row's energy is its kW times the hours its row lasts on window, so it
    prices any cadence.

    Parameters
    ----------
    window:
        The run's window, whose rows both flows are on.
    import_kw:
        Community-level grid import series (kW) on window's rows.
    export_kw:
        Community-level grid export series (kW) on the same rows.
    tariff:
        Import tariff; the import leg is priced per-timestep via
        :func:`~solar_challenge.tariff.calculate_bill` (TOU-correct).
    seg:
        Smart Export Guarantee tariff; the export leg is priced flat via
        :func:`~solar_challenge.seg.calculate_seg_revenue` (sum-first, exact).

    Returns
    -------
    (import_cost_gbp, export_revenue_gbp)
        Both values in GBP.
    """
    # Import cost: per-timestep TOU-aware pricing via the canonical loop.
    import_cost_gbp: float = calculate_bill(window.row_energy_kwh(import_kw), tariff)

    # Export revenue: flat SEG rate → sum kWh first, then price once (exact).
    export_revenue_gbp: float = calculate_seg_revenue(window.energy_kwh(export_kw), seg)

    return import_cost_gbp, export_revenue_gbp


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
    performs post-hoc netting over the fleet's aggregate grid flows:

    * ``net_surplus = max(0, total_grid_export[t] - total_grid_import[t])``
    * ``net_deficit = max(0, total_grid_import[t] - total_grid_export[t])``

    Each row lasts the cadence of the fleet's window,
    :meth:`~solar_challenge.timebase.SimulationWindow.of_index` of
    ``total_grid_export``'s index, in either mode and whether or not it bills.

    Two dispatch branches are selected by *config.sharing_mode*:

    **p2p** (vectorised):
        Instantaneous netting at the community connection point with no battery.
        Grid flows are derived directly from ``(surplus − deficit)`` clips.
        All battery series in the result are zero.

    **community_battery** (sequential):
        A shared :class:`~solar_challenge.battery.Battery` is instantiated once
        and each net surplus/deficit step, the fleet window's ``step_minutes``
        long, is dispatched in order via
        :func:`~solar_challenge.flow.simulate_timestep` with
        :class:`~solar_challenge.dispatch.SelfConsumptionStrategy`.  The
        sequential loop is required because SOC is stateful and cannot be
        vectorised.  Per-step outputs (kWh/step) are scaled back to kW by
        dividing by the fleet window's ``step_hours``.

    Parameters
    ----------
    fleet_results:
        Aggregate results from :func:`~solar_challenge.fleet.simulate_fleet`.
    config:
        Community configuration specifying ``sharing_mode`` and, for
        ``"community_battery"`` mode, the shared battery's
        :class:`~solar_challenge.battery.BatteryConfig`.
    validate_balance:
        When ``True`` (default), check the completed result with
        :func:`validate_community_balance` and, in ``community_battery`` mode,
        each step's flow with :func:`~solar_challenge.flow.validate_energy_balance`
        as it is dispatched.

    Returns
    -------
    CommunityResults

    Raises
    ------
    ValueError
        If :meth:`~solar_challenge.timebase.SimulationWindow.of_index` refuses
        the fleet's index: it is not a DatetimeIndex, it is empty, it has one
        row and no fixed-duration freq, or its rows are not evenly spaced,
        naming the first position whose gap differs and both gaps.
    """
    surplus: pd.Series = fleet_results.total_grid_export
    deficit: pd.Series = fleet_results.total_grid_import
    index: pd.DatetimeIndex = surplus.index
    window = SimulationWindow.of_index(index)

    # Branch on the community battery config; using a local variable so mypy
    # narrows Optional[BatteryConfig] → BatteryConfig for the Battery(...) call.
    cb_config = config.community_battery

    if cb_config is None:
        # Vectorised P2P netting — exact for p2p because there is no SOC state
        # to track sequentially.
        cg_exp: pd.Series = (surplus - deficit).clip(lower=0)
        cg_imp: pd.Series = (deficit - surplus).clip(lower=0)
        zeros: pd.Series = pd.Series(0.0, index=index, dtype=float)

        result = CommunityResults(
            grid_export=cg_exp,
            grid_import=cg_imp,
            battery_charge=zeros.copy(),
            battery_discharge=zeros.copy(),
            battery_soc=zeros.copy(),
            fleet_results=fleet_results,
            sharing_mode=config.sharing_mode,
        )
    else:
        # Community battery dispatch — sequential because SOC is stateful.
        # Like each home's battery, it starts at the midpoint of its usable SOC window.
        battery = Battery(cb_config)
        strategy = SelfConsumptionStrategy()

        # Pre-extract arrays to avoid repeated label-based .loc[t] hash lookups
        # and redundant pd.Timestamp construction inside the hot loop
        # (~525 k iterations for a full-year, 1-min, 100-home fleet run).
        surplus_arr = surplus.to_numpy()
        deficit_arr = deficit.to_numpy()
        step_minutes = window.step_minutes
        scale = 1 / window.step_hours  # kWh/step → kW

        cg_imp_vals: list[float] = []
        cg_exp_vals: list[float] = []
        cb_ch_vals: list[float] = []
        cb_dis_vals: list[float] = []
        soc_vals: list[float] = []

        for t, s, d in zip(index, surplus_arr, deficit_arr):
            net_surplus = max(0.0, float(s) - float(d))
            net_deficit = max(0.0, float(d) - float(s))
            r = simulate_timestep(
                generation_kw=net_surplus,
                demand_kw=net_deficit,
                battery=battery,
                timestep_minutes=step_minutes,
                timestamp=t.to_pydatetime(),
                strategy=strategy,
            )
            if validate_balance:
                validate_energy_balance(r)
            # Scale kWh/step → kW; SOC is an energy state, kept in kWh.
            cg_imp_vals.append(r.grid_import * scale)
            cg_exp_vals.append(r.grid_export * scale)
            cb_ch_vals.append(r.battery_charge * scale)
            cb_dis_vals.append(r.battery_discharge * scale)
            soc_vals.append(r.battery_soc)

        result = CommunityResults(
            grid_export=pd.Series(cg_exp_vals, index=index, dtype=float),
            grid_import=pd.Series(cg_imp_vals, index=index, dtype=float),
            battery_charge=pd.Series(cb_ch_vals, index=index, dtype=float),
            battery_discharge=pd.Series(cb_dis_vals, index=index, dtype=float),
            battery_soc=pd.Series(soc_vals, index=index, dtype=float),
            fleet_results=fleet_results,
            sharing_mode=config.sharing_mode,
        )

    # --- Virtual-net-metering billing: baseline vs community net cost ---
    # Gated on BOTH tariff and seg_rate being present so _price_grid_flows
    # always receives non-None arguments (keeps it total / no None branches).
    billing = config.billing
    if (
        billing is not None
        and billing.tariff is not None
        and billing.seg_rate_pence_per_kwh is not None
    ):
        seg = SEGTariff(
            name="community",
            rate_pence_per_kwh=billing.seg_rate_pence_per_kwh,
        )
        # Baseline: what the fleet would pay/earn WITHOUT community sharing
        base_imp, base_exp = _price_grid_flows(
            window,
            fleet_results.total_grid_import,
            fleet_results.total_grid_export,
            billing.tariff,
            seg,
        )
        # Community: what the fleet pays/earns AFTER sharing
        comm_imp, comm_exp = _price_grid_flows(
            window,
            result.grid_import,
            result.grid_export,
            billing.tariff,
            seg,
        )
        result.baseline_net_cost_gbp = base_imp - base_exp
        result.community_net_cost_gbp = comm_imp - comm_exp
        result.community_savings_gbp = result.baseline_net_cost_gbp - result.community_net_cost_gbp

    if validate_balance:
        validate_community_balance(fleet_results, result)

    return result


# ---------------------------------------------------------------------------
# validate_community_balance
# ---------------------------------------------------------------------------

def validate_community_balance(
    fleet_results: "FleetResults",
    community_results: CommunityResults,
    tolerance: float = 0.001,
) -> bool:
    """Validate the COMMUNITY-BALANCE invariant at every timestep.

    The invariant (in kW on the fleet's index) is::

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

    # Vectorised balance check — avoids O(n) Python loop over minute-resolution series.
    imbalance: pd.Series = (
        total_gen + community_results.grid_import
    ) - (
        total_dem
        + community_results.grid_export
        + (home_bch - home_bdis)
        + (community_results.battery_charge - community_results.battery_discharge)
    )

    abs_imbalance: pd.Series = imbalance.abs()
    if (abs_imbalance > tolerance).any():
        worst_t = abs_imbalance.idxmax()
        worst_val = float(abs_imbalance.loc[worst_t])
        energy_in_w = float(total_gen.loc[worst_t] + community_results.grid_import.loc[worst_t])
        energy_out_w = float(
            total_dem.loc[worst_t]
            + community_results.grid_export.loc[worst_t]
            + (home_bch.loc[worst_t] - home_bdis.loc[worst_t])
            + (
                community_results.battery_charge.loc[worst_t]
                - community_results.battery_discharge.loc[worst_t]
            )
        )
        raise ValueError(
            f"Community energy balance violated at {worst_t}: "
            f"energy_in={energy_in_w:.6f} kW, energy_out={energy_out_w:.6f} kW, "
            f"imbalance={worst_val:.6f} kW (tolerance={tolerance} kW)"
        )

    return True
