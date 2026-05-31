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

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import SelfConsumptionStrategy
from solar_challenge.flow import simulate_timestep, validate_energy_balance
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.tariff import TariffConfig, calculate_bill

if TYPE_CHECKING:
    from solar_challenge.fleet import FleetResults


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

    tariff: Optional[TariffConfig] = None
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
    # Billing fields populated by simulate_community when config.billing is
    # fully specified (both tariff and seg_rate_pence_per_kwh present).
    baseline_net_cost_gbp: Optional[float] = None
    community_net_cost_gbp: Optional[float] = None
    community_savings_gbp: Optional[float] = None


# ---------------------------------------------------------------------------
# _safe_calculate_bill  (workaround for tariff.py flat_rate end_time="23:59")
# ---------------------------------------------------------------------------

def _safe_calculate_bill(energy_kwh: pd.Series, tariff: TariffConfig) -> float:
    """Calculate bill like :func:`~solar_challenge.tariff.calculate_bill`.

    Adds a fallback for timestamps that fall in known period-boundary gaps:
    :meth:`TariffConfig.flat_rate` uses ``end_time="23:59"`` (exclusive), so
    ``23:59:00`` in 1-minute simulation data is not covered.  For any such
    gap, this function retries with ``timestamp − 1 s``, which falls within
    the period and carries the same rate.  For all other timestamps the
    behaviour is bit-identical to ``calculate_bill``.

    Parameters
    ----------
    energy_kwh:
        Time-series of energy in kWh (must have a ``DatetimeIndex``).
    tariff:
        Tariff configuration used to look up per-timestep rates.

    Returns
    -------
    float
        Total bill cost in £.
    """
    total_cost = 0.0
    for timestamp, energy in energy_kwh.items():
        try:
            rate = tariff.get_rate(timestamp)
        except ValueError:
            # Fallback: rate at 1 second before the failing timestamp.
            # This handles flat_rate's "23:59" exclusive boundary — the
            # previous second (23:58:59) is inside the period.
            rate = tariff.get_rate(timestamp - pd.Timedelta(seconds=1))
        total_cost += energy * rate
    return total_cost


# ---------------------------------------------------------------------------
# _price_grid_flows
# ---------------------------------------------------------------------------

def _price_grid_flows(
    import_kw: pd.Series,
    export_kw: pd.Series,
    tariff: TariffConfig,
    seg: SEGTariff,
) -> tuple[float, float]:
    """Price grid import and export flows using canonical billing primitives.

    Derives the timestep duration (dt_h) from the series index so the function
    is correct for any cadence (1-min, hourly, etc.).  This mirrors the
    convention used in :func:`~solar_challenge.output.compute_community_metrics`.

    Parameters
    ----------
    import_kw:
        Community-level grid import series (kW) with a DatetimeIndex.
    export_kw:
        Community-level grid export series (kW) with the same DatetimeIndex.
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
    # Infer dt_h from the index spacing; fall back to 1/60 for degenerate
    # single-element series (consistent with simulate_community's own fallback).
    if len(import_kw) >= 2:
        dt_h = (import_kw.index[1] - import_kw.index[0]).total_seconds() / 3600.0
    else:
        dt_h = 1.0 / 60.0

    # Import cost: per-timestep TOU-aware pricing via the canonical loop.
    # Use a safe wrapper: TariffConfig.flat_rate() defines end_time="23:59"
    # (exclusive), so the 23:59:00 timestamp in 1-minute simulation data falls
    # outside the period.  The wrapper falls back to the previous second so the
    # 23:59 minute is priced at the same rate as 23:58 — semantically correct
    # for a flat-rate period.  For non-boundary timestamps the behaviour is
    # identical to calculate_bill.
    import_cost_gbp: float = _safe_calculate_bill(import_kw * dt_h, tariff)

    # Export revenue: flat SEG rate → sum kWh first, then price once (exact).
    export_energy_kwh: float = float((export_kw * dt_h).sum())
    export_revenue_gbp: float = calculate_seg_revenue(export_energy_kwh, seg)

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

    Two dispatch branches are selected by *config.sharing_mode*:

    **p2p** (vectorised):
        Instantaneous netting at the community connection point with no battery.
        Grid flows are derived directly from ``(surplus − deficit)`` clips.
        All battery series in the result are zero.

    **community_battery** (sequential):
        A shared :class:`~solar_challenge.battery.Battery` is instantiated once
        and each net surplus/deficit step is dispatched in order via
        :func:`~solar_challenge.flow.simulate_timestep` with
        :class:`~solar_challenge.dispatch.SelfConsumptionStrategy`.  The
        sequential loop is required because SOC is stateful and cannot be
        vectorised.  Per-step outputs (kWh/step) are scaled back to kW using
        ``60 / timestep_minutes`` derived from the fleet index, matching the
        conversion convention in ``home.py``.  When *validate_balance* is
        ``True``, a per-step :func:`~solar_challenge.flow.validate_energy_balance`
        check (◆) is applied inside the loop before the tail
        :func:`validate_community_balance` cross-check.

    Parameters
    ----------
    fleet_results:
        Aggregate results from :func:`~solar_challenge.fleet.simulate_fleet`.
    config:
        Community configuration specifying ``sharing_mode`` and, for
        ``"community_battery"`` mode, the shared battery's
        :class:`~solar_challenge.battery.BatteryConfig`.
    validate_balance:
        When ``True`` (default), call :func:`validate_community_balance` on the
        completed result to enforce the COMMUNITY-BALANCE invariant (PRD §3.1).
        In ``community_battery`` mode a per-step ◆ check is also applied.

    Returns
    -------
    CommunityResults
    """
    surplus: pd.Series = fleet_results.total_grid_export
    deficit: pd.Series = fleet_results.total_grid_import
    index: pd.DatetimeIndex = surplus.index

    # Derive the timestep from the index so the kWh→kW conversion factor and
    # the simulate_timestep call are correct for any cadence (1-min operational,
    # hourly TMY, downsampled, etc.) rather than silently assuming 1-minute.
    # A single-element index is degenerate; the sequential loop won't execute.
    if len(index) >= 2:
        timestep_minutes = (index[1] - index[0]).total_seconds() / 60.0
    else:
        timestep_minutes = 1.0

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
        )
    else:
        # Community battery dispatch — sequential because SOC is stateful.
        # Reuses Battery + simulate_timestep + SelfConsumptionStrategy from α.
        #
        # Battery starts at the per-home default SOC envelope (initial_soc_kwh
        # defaults to mid-range, usable window 10%–90%).  This is an intentional
        # reuse of the per-home convention; callers that need a different starting
        # state (e.g. start empty) should pass an adjusted BatteryConfig.
        battery = Battery(cb_config)
        strategy = SelfConsumptionStrategy()

        # Pre-extract arrays to avoid repeated label-based .loc[t] hash lookups
        # and redundant pd.Timestamp construction inside the hot loop
        # (~525 k iterations for a full-year, 1-min, 100-home fleet run).
        surplus_arr = surplus.to_numpy()
        deficit_arr = deficit.to_numpy()
        scale = 60.0 / timestep_minutes  # kWh/step → kW

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
                timestep_minutes=timestep_minutes,
                timestamp=t.to_pydatetime(),
                strategy=strategy,
            )
            # Per-step ◆ invariant (PRD §3.2) — mirrors home.simulate_home:299-300.
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
        )

    # --- VNM billing: baseline vs community net cost (ε / task-34) ---
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
            fleet_results.total_grid_import,
            fleet_results.total_grid_export,
            billing.tariff,
            seg,
        )
        # Community: what the fleet pays/earns AFTER sharing
        comm_imp, comm_exp = _price_grid_flows(
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
