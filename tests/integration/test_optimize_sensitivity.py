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


# ---------------------------------------------------------------------------
# step-3: TestBuildAxisConfigs (RED — _build_axis_configs doesn't exist yet)
# ---------------------------------------------------------------------------


class TestBuildAxisConfigs:
    """Unit tests for _build_axis_configs: pure routing, no run_sweep calls."""

    def _base_configs(self, finance: "Optional[FinanceConfig]" = None):  # type: ignore[no-untyped-def]
        """Return a minimal base_configs list: one (ConfigPoint, ScenarioConfig) pair."""
        from solar_challenge.optimize import ConfigPoint, enumerate_configs

        scenario = _make_scenario(n_homes=2, finance=finance or _interior_finance())
        return enumerate_configs(scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6])

    def test_finance_field_battery_cost_replaced(self) -> None:
        """battery_cost_per_kwh_gbp is replaced on every pair's scenario.finance."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "battery_cost_per_kwh_gbp", 999.0)

        assert len(result) == len(base)
        for (orig_pt, orig_sc), (new_pt, new_sc) in zip(base, result):
            assert new_pt is orig_pt, "ConfigPoint must be reused unchanged"
            assert new_sc.finance is not None
            assert new_sc.finance.battery_cost_per_kwh_gbp == pytest.approx(999.0)
            # Other finance fields must be preserved
            assert new_sc.finance.pv_cost_per_kwp_gbp == pytest.approx(
                orig_sc.finance.pv_cost_per_kwp_gbp  # type: ignore[union-attr]
            )

    def test_finance_field_grid_services_replaced(self) -> None:
        """grid_services_income_per_kw_per_year_gbp is replaced on every pair."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "grid_services_income_per_kw_per_year_gbp", 42.0)

        for _, new_sc in result:
            assert new_sc.finance is not None
            assert new_sc.finance.grid_services_income_per_kw_per_year_gbp == pytest.approx(42.0)

    def test_seg_alias_replaced(self) -> None:
        """'seg' alias replaces ScenarioConfig.seg_tariff_pence_per_kwh."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "seg", 7.5)

        for (_, orig_sc), (_, new_sc) in zip(base, result):
            assert new_sc.seg_tariff_pence_per_kwh == pytest.approx(7.5)
            # Finance block is unchanged
            assert new_sc.finance is orig_sc.finance

    def test_seg_tariff_full_name_replaced(self) -> None:
        """'seg_tariff_pence_per_kwh' replaces ScenarioConfig.seg_tariff_pence_per_kwh."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "seg_tariff_pence_per_kwh", 9.0)

        for _, new_sc in result:
            assert new_sc.seg_tariff_pence_per_kwh == pytest.approx(9.0)

    def test_degradation_alias_replaced(self) -> None:
        """'degradation' alias replaces degradation_rate_per_year on every home."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "degradation", 0.01)

        for _, new_sc in result:
            for home in new_sc.homes:
                assert home.pv_config.degradation_rate_per_year == pytest.approx(0.01)

    def test_degradation_full_name_replaced(self) -> None:
        """'degradation_rate_per_year' replaces degradation on every home."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        result = _build_axis_configs(base, "degradation_rate_per_year", 0.02)

        for _, new_sc in result:
            for home in new_sc.homes:
                assert home.pv_config.degradation_rate_per_year == pytest.approx(0.02)

    def test_unknown_knob_raises_value_error(self) -> None:
        """An unrecognised knob name raises ValueError."""
        from solar_challenge.optimize import _build_axis_configs

        base = self._base_configs()
        with pytest.raises(ValueError, match="Unknown sensitivity knob"):
            _build_axis_configs(base, "nonexistent_knob_xyz", 1.0)

    def test_none_finance_raises_for_finance_knob(self) -> None:
        """scenario.finance is None raises ValueError for a FinanceConfig knob."""
        from solar_challenge.optimize import _build_axis_configs

        # Build base_configs where the scenario has NO finance block
        base = self._base_configs(finance=None)
        # Manually clear finance on the scenarios
        import dataclasses as dc
        cleared = [
            (pt, dc.replace(sc, finance=None))
            for pt, sc in base
        ]
        with pytest.raises(ValueError, match="finance"):
            _build_axis_configs(cleared, "battery_cost_per_kwh_gbp", 999.0)


# ---------------------------------------------------------------------------
# step-5: TestSensitivityPanelStructure (RED — sensitivity_panel not yet impl)
# ---------------------------------------------------------------------------


class TestSensitivityPanelStructure:
    """Structural invariants of sensitivity_panel output."""

    def _setup(self):  # type: ignore[no-untyped-def]
        """Return (base_configs, simulate) for a 2-config grid."""
        from solar_challenge.optimize import enumerate_configs

        finance = _interior_finance()  # grid_services=0, baseline Config A on top
        scenario = _make_scenario(n_homes=_N_HOMES, finance=finance)
        base_configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[0.0, 6.0],
            inverter_kw=[3.6],
        )
        return base_configs, _const_simulate

    def test_one_axis_length(self) -> None:
        """Panel has exactly one SensitivityAxis when one axis is swept."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, simulate = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert len(panel.axes) == 1

    def test_axis_values_preserved(self) -> None:
        """SensitivityAxis.values equals the input sequence as a float tuple."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, simulate = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert panel.axes[0].values == (0.0, 12.0, 48.0)

    def test_rankings_and_tops_have_correct_length(self) -> None:
        """rankings and top_config_per_value both have length == len(values)."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, simulate = self._setup()
        n_values = 3
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        axis = panel.axes[0]
        assert len(axis.rankings) == n_values
        assert len(axis.top_config_per_value) == n_values

    def test_baseline_top_equals_run_sweep_cheapest_feasible(self) -> None:
        """panel.baseline_top == run_sweep(base_configs, simulate=...).cheapest_feasible."""
        from solar_challenge.optimize import run_sweep, sensitivity_panel

        base_configs, simulate = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [0.0, 12.0]},
            simulate=simulate,
        )
        baseline = run_sweep(base_configs, simulate=simulate)
        assert panel.baseline_top == baseline.cheapest_feasible

    def test_rank_stability_in_range(self) -> None:
        """panel.rank_stability is in [0.0, 1.0]."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, simulate = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert 0.0 <= panel.rank_stability <= 1.0


# ---------------------------------------------------------------------------
# step-7: TestWH4Coupling — W-H4 user-observable rank-flip signal
# ---------------------------------------------------------------------------


class TestWH4Coupling:
    """W-H4: capex/grid-services knobs move the rank under a constant simulate.

    Setup: 2-config grid (no-battery A vs with-battery B).  Base finance has
    grid_services_income=100 GBP/kW/yr, which makes B the cheaper config at
    baseline (income > extra capex).  Then:
      - battery_cost axis [250→10000]: B's extra capex explodes → B becomes
        infeasible → top flips from B to A.
      - grid_services axis [0→200]: B's income collapses at 0 (A on top) or
        surges at 200 (B clearly on top), demonstrating the knob matters.
    """

    _BATT_COST_LOW = 250.0    # baseline: B feasible and cheap
    _BATT_COST_HIGH = 10000.0  # B capex ≈ 300 k£ → infeasible
    _GS_ZERO = 0.0            # no income → A on top
    _GS_HIGH = 200.0          # huge income → B clearly on top

    def _setup(self):  # type: ignore[no-untyped-def]
        """Return (base_configs, pt_A, pt_B) for the W-H4 coupling test."""
        from solar_challenge.optimize import ConfigPoint, enumerate_configs

        # Finance with grid_services=100 makes B cheaper at baseline
        finance = _make_finance(
            pv_cost_per_kwp_gbp=1200.0,
            grant_gbp=5000.0,
            retained_cash_floor=50.0,
            retail_baseline_rate=30.0,
            battery_cost_per_kwh_gbp=self._BATT_COST_LOW,
            grid_services_income=100.0,
        )
        scenario = _make_scenario(n_homes=_N_HOMES, finance=finance)
        base_configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[0.0, 6.0],
            inverter_kw=[3.6],
        )
        pt_a = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        pt_b = ConfigPoint(pv_kwp=4.0, battery_kwh=6.0, inverter_kw=3.6)
        return base_configs, pt_a, pt_b

    def test_baseline_top_is_battery_config(self) -> None:
        """With grid_services=100, Config B (battery) is cheaper → baseline_top==B."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, pt_a, pt_b = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"battery_cost_per_kwh_gbp": [self._BATT_COST_LOW, self._BATT_COST_HIGH]},
            simulate=_const_simulate,
        )
        assert panel.baseline_top == pt_b, (
            f"Expected battery config B as baseline_top, got {panel.baseline_top}"
        )

    def test_battery_cost_high_makes_battery_infeasible(self) -> None:
        """At high battery_cost, B is infeasible: absent from rankings and top flips to A."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, pt_a, pt_b = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"battery_cost_per_kwh_gbp": [self._BATT_COST_LOW, self._BATT_COST_HIGH]},
            simulate=_const_simulate,
        )
        batt_axis = panel.axes[0]
        assert batt_axis.name == "battery_cost_per_kwh_gbp"

        # At low cost (idx 0): B is on top (same as baseline)
        assert batt_axis.top_config_per_value[0] == pt_b

        # At high cost (idx 1): B is infeasible → absent from feasible rankings
        assert pt_b not in batt_axis.rankings[1], (
            "Battery config B should be absent from feasible rankings at high battery_cost"
        )
        # Top flips to A (or is None if both somehow infeasible, but A must be feasible)
        assert batt_axis.top_config_per_value[1] == pt_a, (
            f"Expected Config A as top at high battery_cost, got {batt_axis.top_config_per_value[1]}"
        )

    def test_grid_services_flip(self) -> None:
        """At grid_services=0 A is on top; at grid_services=200 B is on top."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, pt_a, pt_b = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"grid_services_income_per_kw_per_year_gbp": [self._GS_ZERO, self._GS_HIGH]},
            simulate=_const_simulate,
        )
        gs_axis = panel.axes[0]
        assert gs_axis.name == "grid_services_income_per_kw_per_year_gbp"

        # At 0 grid_services: no income for B → A is cheaper (lower capex)
        assert gs_axis.top_config_per_value[0] == pt_a, (
            f"Expected A on top at gs=0, got {gs_axis.top_config_per_value[0]}"
        )

        # At high grid_services: B gets large income → B is cheaper
        assert gs_axis.top_config_per_value[1] == pt_b, (
            f"Expected B on top at gs={self._GS_HIGH}, got {gs_axis.top_config_per_value[1]}"
        )

    def test_rank_stability_less_than_one_with_flips(self) -> None:
        """Both axes together produce rank_stability < 1 due to flips."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs, pt_a, pt_b = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={
                "battery_cost_per_kwh_gbp": [self._BATT_COST_LOW, self._BATT_COST_HIGH],
                "grid_services_income_per_kw_per_year_gbp": [self._GS_ZERO, self._GS_HIGH],
            },
            simulate=_const_simulate,
        )
        # battery_cost: [stable(B=B), unstable(A≠B)] + grid_services: [unstable(A≠B), stable(B=B)]
        # = 2 stable / 4 total = 0.5
        assert panel.rank_stability < 1.0, (
            f"rank_stability should be < 1.0 due to flips, got {panel.rank_stability}"
        )


# ---------------------------------------------------------------------------
# step-9: TestRetainedFloorAxis — floor axis uses run_sweep's first-class override
# ---------------------------------------------------------------------------


class TestRetainedFloorAxis:
    """The retained_cash_floor axis is routed through run_sweep's retained_cash_floor_gbp
    parameter (not via finance replace), and None tops at a high floor don't crash.
    """

    def _setup(self):  # type: ignore[no-untyped-def]
        """Return base_configs for a 2-config no-battery / with-battery grid."""
        from solar_challenge.optimize import enumerate_configs

        finance = _make_finance(
            retained_cash_floor=50.0,
            grid_services_income=0.0,
        )
        scenario = _make_scenario(n_homes=_N_HOMES, finance=finance)
        base_configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[0.0],
            inverter_kw=[3.6],
        )
        return base_configs

    def test_floor_axis_per_value_matches_run_sweep(self) -> None:
        """Per-value rankings/tops match run_sweep called with the same floor override."""
        from solar_challenge.optimize import run_sweep, sensitivity_panel

        base_configs = self._setup()
        floor_low = 50.0
        floor_high = 500.0  # feasible at this level but different from baseline
        panel = sensitivity_panel(
            base_configs,
            axes={"retained_cash_floor_per_home_per_year_gbp": [floor_low, floor_high]},
            simulate=_const_simulate,
        )

        axis = panel.axes[0]
        assert axis.name == "retained_cash_floor_per_home_per_year_gbp"
        assert axis.values == (floor_low, floor_high)

        # Verify per-value results match direct run_sweep calls
        for i, v in enumerate([floor_low, floor_high]):
            expected = run_sweep(base_configs, retained_cash_floor_gbp=v, simulate=_const_simulate)
            expected_ranking = tuple(r.config for r in expected.results)
            assert axis.rankings[i] == expected_ranking, (
                f"rankings[{i}] mismatch at floor={v}: "
                f"got {axis.rankings[i]}, expected {expected_ranking}"
            )
            assert axis.top_config_per_value[i] == expected.cheapest_feasible, (
                f"top_config_per_value[{i}] mismatch at floor={v}"
            )

    def test_floor_axis_very_high_yields_none_top(self) -> None:
        """A sufficiently high floor makes all configs infeasible → None top, no crash."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._setup()
        # 9,999,999 GBP floor is far above any solved rate — all infeasible
        panel = sensitivity_panel(
            base_configs,
            axes={"retained_cash_floor_per_home_per_year_gbp": [50.0, 9_999_999.0]},
            simulate=_const_simulate,
        )

        axis = panel.axes[0]
        # At floor=50 the config is feasible → non-None top
        assert axis.top_config_per_value[0] is not None
        # At very high floor: all infeasible → None top
        assert axis.top_config_per_value[1] is None

    def test_none_top_counts_as_unstable(self) -> None:
        """A None top at a swept value counts as unstable in rank_stability."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._setup()
        panel = sensitivity_panel(
            base_configs,
            axes={"retained_cash_floor_per_home_per_year_gbp": [50.0, 9_999_999.0]},
            simulate=_const_simulate,
        )
        # baseline_top is the config at panel_floor (None here) — run_sweep at baseline floor
        # The low-floor value should match baseline_top if they share the floor.
        # The high-floor value is None → unstable.
        # At minimum rank_stability < 1.0 because of the None top
        assert panel.rank_stability < 1.0, (
            f"Expected rank_stability < 1.0 with a None top, got {panel.rank_stability}"
        )

    def test_floor_axis_does_not_mutate_finance_in_base_configs(self) -> None:
        """After sensitivity_panel, base_configs scenarios still have original finance."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._setup()
        original_floors = [
            sc.finance.retained_cash_floor_per_home_per_year_gbp  # type: ignore[union-attr]
            for _, sc in base_configs
        ]
        sensitivity_panel(
            base_configs,
            axes={"retained_cash_floor_per_home_per_year_gbp": [50.0, 500.0]},
            simulate=_const_simulate,
        )
        after_floors = [
            sc.finance.retained_cash_floor_per_home_per_year_gbp  # type: ignore[union-attr]
            for _, sc in base_configs
        ]
        assert original_floors == after_floors, (
            "base_configs finance.retained_cash_floor was mutated (should be immutable)"
        )


# ---------------------------------------------------------------------------
# step-11: TestSensitivityPanelGuards — ValueError on bad inputs
# ---------------------------------------------------------------------------


class TestSensitivityPanelGuards:
    """sensitivity_panel raises ValueError on empty inputs and all-infeasible baseline."""

    def _base_configs(self):  # type: ignore[no-untyped-def]
        """Return a valid minimal base_configs list (one no-battery config)."""
        from solar_challenge.optimize import enumerate_configs

        scenario = _make_scenario(n_homes=_N_HOMES, finance=_interior_finance())
        return enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
        )

    def test_empty_base_configs_raises(self) -> None:
        """Empty base_configs raises ValueError."""
        from solar_challenge.optimize import sensitivity_panel

        with pytest.raises(ValueError, match="base_configs"):
            sensitivity_panel(
                [],
                axes={"battery_cost_per_kwh_gbp": [250.0]},
                simulate=_const_simulate,
            )

    def test_empty_axes_raises(self) -> None:
        """Empty axes mapping raises ValueError."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._base_configs()
        with pytest.raises(ValueError, match="axes"):
            sensitivity_panel(
                base_configs,
                axes={},
                simulate=_const_simulate,
            )

    def test_empty_axis_values_raises(self) -> None:
        """An axis with an empty values sequence raises ValueError."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._base_configs()
        with pytest.raises(ValueError):
            sensitivity_panel(
                base_configs,
                axes={"battery_cost_per_kwh_gbp": []},
                simulate=_const_simulate,
            )

    def test_all_infeasible_baseline_raises(self) -> None:
        """A baseline with no feasible config raises ValueError (cheapest_feasible is None)."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._base_configs()
        # Use a floor so high that no config is feasible at baseline
        with pytest.raises(ValueError, match="baseline"):
            sensitivity_panel(
                base_configs,
                axes={"battery_cost_per_kwh_gbp": [250.0]},
                retained_cash_floor_gbp=9_999_999.0,
                simulate=_const_simulate,
            )

    def test_unknown_knob_propagates_value_error(self) -> None:
        """Unknown knob name in axes raises ValueError (propagated from _build_axis_configs)."""
        from solar_challenge.optimize import sensitivity_panel

        base_configs = self._base_configs()
        with pytest.raises(ValueError, match="Unknown sensitivity knob"):
            sensitivity_panel(
                base_configs,
                axes={"completely_unknown_knob_xyz": [1.0, 2.0]},
                simulate=_const_simulate,
            )
