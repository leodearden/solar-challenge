# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for sensitivity_panel (W3 task D/#67).

All tests are offline/fast — no PVGIS/network is touched.  An injected
constant synthetic simulate stands in for the real fleet simulator.
Per the repo's per-file convention there are NO cross-test-file imports;
all builders are self-contained copies/adaptations of the helpers in
tests/integration/test_optimize_sweep.py.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Shared offline scaffolding
# ---------------------------------------------------------------------------

_N_HOMES = 5  # default fleet size for all sensitivity tests


def _make_pv_config(
    capacity_kw: float = 4.0,
    system_age_years: float = 0.0,
) -> "PVConfig":  # type: ignore[name-defined]
    from solar_challenge.pv import PVConfig

    return PVConfig(
        capacity_kw=capacity_kw,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )


def _make_load_config() -> "LoadConfig":  # type: ignore[name-defined]
    from solar_challenge.load import LoadConfig

    return LoadConfig(annual_consumption_kwh=3500.0)


def _make_home_config(
    capacity_kw: float = 4.0,
    system_age_years: float = 0.0,
    with_battery: bool = False,
) -> "HomeConfig":  # type: ignore[name-defined]
    """Build a HomeConfig; pass with_battery=True to include a BatteryConfig."""
    from solar_challenge.battery import BatteryConfig
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location
    from solar_challenge.pv import PVConfig

    pv = PVConfig(
        capacity_kw=capacity_kw,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )
    battery_config = BatteryConfig(capacity_kwh=5.0) if with_battery else None
    return HomeConfig(
        pv_config=pv,
        load_config=_make_load_config(),
        location=Location.bristol(),
        battery_config=battery_config,
    )


def _make_sim_results(
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    export_revenue_gbp_per_year: float = 0.0,
    n_minutes: int = 525600,  # 365 days
) -> "SimulationResults":  # type: ignore[name-defined]
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)
    exp_rev_per_min = export_revenue_gbp_per_year / n_minutes if n_minutes > 0 else 0.0
    export_revenue_series = pd.Series(exp_rev_per_min, index=idx)

    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=export_revenue_series,
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _make_fleet_results(
    n_homes: int = _N_HOMES,
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
) -> "FleetResults":  # type: ignore[name-defined]
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [
        _make_sim_results(self_kwh, export_kwh, import_kwh)
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    battery_cost_per_kwh_gbp: float = 250.0,
    grid_services_income: float = 0.0,
    asset_life_years: int = 25,
) -> "FinanceConfig":  # type: ignore[name-defined]
    from solar_challenge.config import FinanceConfig

    return FinanceConfig(
        standing_charge_pence_per_day=28.0,
        asset_life_years=asset_life_years,
        loan_term_years=min(asset_life_years, 15),
        own_use_rate_pence_per_kwh=own_use_rate_pence_per_kwh,
        retained_cash_floor_per_home_per_year_gbp=retained_cash_floor,
        retail_baseline_rate_pence_per_kwh=retail_baseline_rate,
        pv_cost_per_kwp_gbp=pv_cost_per_kwp_gbp,
        grant_gbp=grant_gbp,
        vat_rate=0.05,
        battery_cost_per_kwh_gbp=battery_cost_per_kwh_gbp,
        grid_services_income_per_kw_per_year_gbp=grid_services_income,
    )


def _make_scenario(
    n_homes: int = _N_HOMES,
    start: str = "2020-01-01",
    end: str = "2020-12-31",
    seg_tariff_pence: float = 5.0,
    finance: "Optional[FinanceConfig]" = None,  # type: ignore[name-defined]
    with_battery: bool = False,
) -> "ScenarioConfig":  # type: ignore[name-defined]
    from solar_challenge.config import ScenarioConfig, SimulationPeriod

    homes = [_make_home_config(with_battery=with_battery) for _ in range(n_homes)]
    return ScenarioConfig(
        name="sensitivity-test",
        period=SimulationPeriod(start_date=start, end_date=end),
        description="W3 sensitivity integration test scenario",
        homes=homes,
        seg_tariff_pence_per_kwh=seg_tariff_pence,
        finance=finance,
    )


def _interior_finance() -> "FinanceConfig":  # type: ignore[name-defined]
    """Finance params that produce an interior 'floor' solve (no grid_services)."""
    return _make_finance(
        pv_cost_per_kwp_gbp=1200.0,
        grant_gbp=5000.0,
        own_use_rate_pence_per_kwh=15.0,
        retained_cash_floor=50.0,
        retail_baseline_rate=30.0,
        battery_cost_per_kwh_gbp=250.0,
        grid_services_income=0.0,
    )


def _const_simulate(fc, s, e):  # type: ignore[no-untyped-def]
    """Constant simulate: same FleetResults regardless of config.

    Isolates capex/grid-services coupling from simulation outputs — the finance
    model computes battery-capex and grid-services income from the SCENARIO's
    homes (not from the FleetResults), so sweeping those knobs has full effect
    even under a constant simulate.
    """
    return _make_fleet_results(n_homes=_N_HOMES)


# ---------------------------------------------------------------------------
# step-1: TestSensitivityDataclasses (RED — imports fail until step-2)
# ---------------------------------------------------------------------------


class TestSensitivityDataclasses:
    """SensitivityAxis and SensitivityPanel: construction, field access, frozen, validation."""

    # --- SensitivityAxis ---

    def test_sensitivity_axis_fields_read_back(self) -> None:
        """All fields read back after valid construction."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="battery_cost_per_kwh_gbp",
            values=(100.0, 250.0, 500.0),
            rankings=((pt,), (pt,), (pt,)),
            top_config_per_value=(pt, pt, pt),
        )
        assert axis.name == "battery_cost_per_kwh_gbp"
        assert axis.values == (100.0, 250.0, 500.0)
        assert axis.rankings == ((pt,), (pt,), (pt,))
        assert axis.top_config_per_value == (pt, pt, pt)

    def test_sensitivity_axis_none_in_top_config_per_value(self) -> None:
        """top_config_per_value may contain None entries (no feasible config)."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="retained_cash_floor_per_home_per_year_gbp",
            values=(50.0, 9999.0),
            rankings=((pt,), ()),
            top_config_per_value=(pt, None),
        )
        assert axis.top_config_per_value[0] is pt
        assert axis.top_config_per_value[1] is None

    def test_sensitivity_axis_frozen(self) -> None:
        """Assigning any field raises FrozenInstanceError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="x",
            values=(1.0,),
            rankings=((pt,),),
            top_config_per_value=(pt,),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            axis.name = "y"  # type: ignore[misc]

    def test_sensitivity_axis_empty_values_raises(self) -> None:
        """Empty values tuple raises ValueError."""
        from solar_challenge.optimize import SensitivityAxis

        with pytest.raises(ValueError, match="values must not be empty"):
            SensitivityAxis(
                name="x",
                values=(),
                rankings=(),
                top_config_per_value=(),
            )

    def test_sensitivity_axis_length_mismatch_rankings(self) -> None:
        """len(values) != len(rankings) raises ValueError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        with pytest.raises(ValueError):
            SensitivityAxis(
                name="x",
                values=(1.0, 2.0),  # length 2
                rankings=((pt,),),   # length 1
                top_config_per_value=(pt, pt),
            )

    def test_sensitivity_axis_length_mismatch_tops(self) -> None:
        """len(values) != len(top_config_per_value) raises ValueError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        with pytest.raises(ValueError):
            SensitivityAxis(
                name="x",
                values=(1.0, 2.0),          # length 2
                rankings=((pt,), (pt,)),
                top_config_per_value=(pt,),  # length 1
            )

    # --- SensitivityPanel ---

    def test_sensitivity_panel_fields_read_back(self) -> None:
        """All fields read back after valid construction."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis, SensitivityPanel

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="x",
            values=(1.0,),
            rankings=((pt,),),
            top_config_per_value=(pt,),
        )
        panel = SensitivityPanel(
            axes=(axis,),
            baseline_top=pt,
            rank_stability=0.75,
        )
        assert panel.axes == (axis,)
        assert panel.baseline_top is pt
        assert panel.rank_stability == pytest.approx(0.75)

    def test_sensitivity_panel_frozen(self) -> None:
        """Assigning any field raises FrozenInstanceError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis, SensitivityPanel

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="x",
            values=(1.0,),
            rankings=((pt,),),
            top_config_per_value=(pt,),
        )
        panel = SensitivityPanel(axes=(axis,), baseline_top=pt, rank_stability=0.5)
        with pytest.raises(dataclasses.FrozenInstanceError):
            panel.rank_stability = 0.9  # type: ignore[misc]

    def test_sensitivity_panel_rank_stability_out_of_range_raises(self) -> None:
        """rank_stability outside [0, 1] raises ValueError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityAxis, SensitivityPanel

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        axis = SensitivityAxis(
            name="x",
            values=(1.0,),
            rankings=((pt,),),
            top_config_per_value=(pt,),
        )
        with pytest.raises(ValueError, match="rank_stability"):
            SensitivityPanel(axes=(axis,), baseline_top=pt, rank_stability=1.5)
        with pytest.raises(ValueError, match="rank_stability"):
            SensitivityPanel(axes=(axis,), baseline_top=pt, rank_stability=-0.1)

    def test_sensitivity_panel_empty_axes_raises(self) -> None:
        """Empty axes tuple raises ValueError."""
        from solar_challenge.optimize import ConfigPoint, SensitivityPanel

        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        with pytest.raises(ValueError, match="axes"):
            SensitivityPanel(axes=(), baseline_top=pt, rank_stability=1.0)
