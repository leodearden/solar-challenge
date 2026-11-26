# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for sensitivity_panel (W3 task D/#67).

All tests are offline/fast — no PVGIS/network is touched.  An injected
synthetic simulate stands in for the real fleet simulator: it answers each fleet
with constant energy, paired with that fleet's homes, through
tests/_fleet_simulate_stand_in.py.  The synthetic homes, scenarios and
simulation results come from tests/_finance_builders.py.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Optional

import pytest

from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.gridservices import GridServicesEventsConfig
from solar_challenge.home import RunPricing, SimulationResults
from solar_challenge.optimize import (
    ConfigPoint,
    SensitivityAxis,
    SensitivityPanel,
    enumerate_configs,
    run_sweep,
    sensitivity_panel,
)
from solar_challenge.scenario_knobs import KNOBS, Knob, flat_rate_pricing
from solar_challenge.seg import SEGTariff
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_scenario,
    make_sim_results,
)
from tests._fleet_simulate_stand_in import answering_with
from tests._recording_simulate import recording


# ---------------------------------------------------------------------------
# Shared offline scaffolding
# ---------------------------------------------------------------------------

_N_HOMES = 5  # default fleet size for all sensitivity tests

_SELF_KWH = 2000.0
_EXPORT_KWH = 800.0
_IMPORT_KWH = 1200.0


def _make_finance(
    pv_cost_per_kwp_gbp: float = 1200.0,
    grant_gbp: float = 5000.0,
    own_use_rate_pence_per_kwh: float = 15.0,
    retained_cash_floor: float = 50.0,
    retail_baseline_rate: float = 30.0,
    battery_cost_per_kwh_gbp: float = 250.0,
    grid_services_income: float = 0.0,
    asset_life_years: int = 25,
) -> FinanceConfig:
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
        grid_services_model=flat_rate_pricing(grid_services_income),
    )


def _make_scenario(n_homes: int = _N_HOMES, finance: FinanceConfig | None = None) -> ScenarioConfig:
    """make_scenario's *n_homes* default homes carrying *finance*, pinned to a 5 p/kWh scenario SEG rate."""
    return make_scenario(n_homes=n_homes, seg_tariff_pence_per_kwh=5.0, finance=finance)


def _interior_finance() -> FinanceConfig:
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


_CONST_FLEET_RESULTS: FleetResults = make_fleet_results(
    n_homes=_N_HOMES, self_kwh=_SELF_KWH, export_kwh=_EXPORT_KWH, import_kwh=_IMPORT_KWH
)


_paired_const_simulate: FleetSimulate = answering_with(_CONST_FLEET_RESULTS)


def _panel(
    base_configs: list[tuple[ConfigPoint, ScenarioConfig]],
    axes: Mapping[Knob, Sequence[float]],
    *,
    simulate: FleetSimulate = _paired_const_simulate,
) -> SensitivityPanel:
    """sensitivity_panel over *base_configs*, given the baseline that run_sweep returns for them."""
    return sensitivity_panel(
        base_configs, axes, baseline=run_sweep(base_configs, simulate=simulate), simulate=simulate
    )


def _home_seg_rates(homes) -> list[Optional[float]]:  # type: ignore[no-untyped-def]
    """Each home's own SEG export rate in p/kWh; None for a home without a tariff."""
    return [
        None if home.seg_tariff is None else home.seg_tariff.rate_pence_per_kwh
        for home in homes
    ]


def _make_seg_priced_scenario(seg_rate: float, finance) -> ScenarioConfig:  # type: ignore[no-untyped-def]
    """Build the fleet shape `optimize configs` produces: the seg: rate on the scenario AND on every home."""
    scenario = make_scenario(n_homes=_N_HOMES, seg_tariff_pence_per_kwh=seg_rate, finance=finance)
    tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)
    return dataclasses.replace(
        scenario,
        homes=[dataclasses.replace(home, seg_tariff=tariff) for home in scenario.homes],
    )


class _SegPricingSimulate:
    """Simulate stand-in that prices each home's export at that home's own SEG tariff.

    A home without a tariff earns nothing, as in simulate_home.  ``rates_per_call``
    records the SEG rates carried by every fleet it is asked to simulate.
    """

    def __init__(self) -> None:
        self.rates_per_call: list[frozenset[Optional[float]]] = []
        self._results_by_rate: dict[Optional[float], SimulationResults] = {}

    def __call__(self, fleet_config, start, end):  # type: ignore[no-untyped-def]
        rates = _home_seg_rates(fleet_config.homes)
        self.rates_per_call.append(frozenset(rates))
        return make_fleet_results_of(
            [self._results_at(rate) for rate in rates], homes=fleet_config.homes
        )

    def _results_at(self, rate: Optional[float]) -> SimulationResults:
        if rate not in self._results_by_rate:
            self._results_by_rate[rate] = make_sim_results(
                self_kwh=_SELF_KWH,
                export_kwh=_EXPORT_KWH,
                import_kwh=_IMPORT_KWH,
                pricing=RunPricing(None, rate),
            )
        return self._results_by_rate[rate]


# ---------------------------------------------------------------------------
# TestSensitivityDataclasses
# ---------------------------------------------------------------------------


class TestSensitivityDataclasses:
    """SensitivityAxis and SensitivityPanel: construction, field access, frozen, validation."""

    # --- SensitivityAxis ---

    def test_sensitivity_axis_fields_read_back(self) -> None:
        """All fields read back after valid construction."""
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
        with pytest.raises(ValueError, match="values must not be empty"):
            SensitivityAxis(
                name="x",
                values=(),
                rankings=(),
                top_config_per_value=(),
            )

    def test_sensitivity_axis_repeated_value_raises(self) -> None:
        """A value repeated within an axis raises ValueError naming the axis and the value."""
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        with pytest.raises(ValueError) as refusal:
            SensitivityAxis(
                name="x",
                values=(1.0, 2.0, 1.0),
                rankings=((pt,), (pt,), (pt,)),
                top_config_per_value=(pt, pt, pt),
            )
        assert "'x'" in str(refusal.value)
        assert "1.0" in str(refusal.value)

    def test_sensitivity_axis_length_mismatch_rankings(self) -> None:
        """len(values) != len(rankings) raises ValueError."""
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
        pt = ConfigPoint(pv_kwp=4.0, battery_kwh=0.0, inverter_kw=3.6)
        with pytest.raises(ValueError, match="axes"):
            SensitivityPanel(axes=(), baseline_top=pt, rank_stability=1.0)


# ---------------------------------------------------------------------------
# TestSensitivityPanelStructure
# ---------------------------------------------------------------------------


class TestSensitivityPanelStructure:
    """Structural invariants of sensitivity_panel output."""

    def _setup(self):  # type: ignore[no-untyped-def]
        """Return (base_configs, simulate) for a 2-config grid."""
        finance = _interior_finance()  # grid_services=0, baseline Config A on top
        scenario = _make_scenario(n_homes=_N_HOMES, finance=finance)
        base_configs = enumerate_configs(
            scenario,
            pv_kwp=[4.0],
            battery_kwh=[0.0, 6.0],
            inverter_kw=[3.6],
        )
        return base_configs, _paired_const_simulate

    def test_one_axis_length(self) -> None:
        """Panel has exactly one SensitivityAxis when one axis is swept."""
        base_configs, simulate = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert len(panel.axes) == 1

    def test_axis_values_preserved(self) -> None:
        """SensitivityAxis.values equals the input sequence as a float tuple."""
        base_configs, simulate = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert panel.axes[0].values == (0.0, 12.0, 48.0)

    def test_rankings_and_tops_have_correct_length(self) -> None:
        """rankings and top_config_per_value both have length == len(values)."""
        base_configs, simulate = self._setup()
        n_values = 3
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        axis = panel.axes[0]
        assert len(axis.rankings) == n_values
        assert len(axis.top_config_per_value) == n_values

    def test_baseline_top_equals_run_sweep_cheapest_feasible(self) -> None:
        """panel.baseline_top == run_sweep(base_configs, simulate=...).cheapest_feasible."""
        base_configs, simulate = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [0.0, 12.0]},
            simulate=simulate,
        )
        baseline = run_sweep(base_configs, simulate=simulate)
        assert panel.baseline_top == baseline.cheapest_feasible

    def test_rank_stability_in_range(self) -> None:
        """panel.rank_stability is in [0.0, 1.0]."""
        base_configs, simulate = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [0.0, 12.0, 48.0]},
            simulate=simulate,
        )
        assert 0.0 <= panel.rank_stability <= 1.0


# ---------------------------------------------------------------------------
# TestBaseline — the panel takes its caller's baseline sweep
# ---------------------------------------------------------------------------


def _overridden(scenario: ScenarioConfig, override: float) -> FinanceConfig:
    """*scenario*'s finance with its own-use overridden to the fraction *override*."""
    assert scenario.finance is not None
    return dataclasses.replace(scenario.finance, self_consumption_override=override)


class TestBaseline:
    """sensitivity_panel takes the baseline sweep its caller ran over base_configs: it sweeps
    each axis value once, reuses the baseline for a value that leaves every scenario equal, and
    refuses, before any simulation, a baseline of other points, another floor or another own-use
    assumption, and a repeated value.
    """

    def _base_configs(self, pv_kwp: float = 4.0) -> list[tuple[ConfigPoint, ScenarioConfig]]:
        """One with-battery config at *pv_kwp* on _interior_finance (floor 50, battery cost 250, grid services 0)."""
        return enumerate_configs(
            _make_scenario(n_homes=_N_HOMES, finance=_interior_finance()),
            pv_kwp=[pv_kwp],
            battery_kwh=[6.0],
            inverter_kw=[3.6],
        )

    def test_the_panel_sweeps_each_value_once_and_never_its_baseline(self) -> None:
        base_configs = self._base_configs()
        one_sweep: list[FleetConfig] = []
        baseline = run_sweep(base_configs, simulate=recording(one_sweep, _paired_const_simulate))
        panel_asked: list[FleetConfig] = []

        sensitivity_panel(
            base_configs,
            {KNOBS["battery_cost_per_kwh_gbp"]: [200.0, 400.0]},
            baseline=baseline,
            simulate=recording(panel_asked, _paired_const_simulate),
        )

        assert len(panel_asked) == 2 * len(one_sweep)

    @pytest.mark.parametrize(
        ("knob_name", "own_value", "other_value"),
        [
            ("retained_cash_floor_per_home_per_year_gbp", 50.0, 60.0),
            ("battery_cost_per_kwh_gbp", 250.0, 400.0),
            ("grid_services_income_per_kw_per_year_gbp", 0.0, 12.0),
        ],
    )
    def test_a_value_that_leaves_every_scenario_equal_reuses_the_baseline(
        self, knob_name: str, own_value: float, other_value: float
    ) -> None:
        scenario = _make_scenario(finance=_interior_finance())
        assert KNOBS[knob_name].apply(scenario, own_value) == scenario
        base_configs = self._base_configs()
        one_sweep: list[FleetConfig] = []
        baseline = run_sweep(base_configs, simulate=recording(one_sweep, _paired_const_simulate))
        panel_asked: list[FleetConfig] = []

        panel = sensitivity_panel(
            base_configs,
            {KNOBS[knob_name]: [own_value, other_value]},
            baseline=baseline,
            simulate=recording(panel_asked, _paired_const_simulate),
        )

        axis = panel.axes[0]
        assert len(panel_asked) == len(one_sweep)
        assert axis.rankings[0] == tuple(r.config for r in baseline.results)
        assert axis.top_config_per_value[0] == baseline.cheapest_feasible

    def test_a_baseline_of_other_points_is_refused_naming_both(self) -> None:
        base_configs = self._base_configs(pv_kwp=4.0)
        baseline = run_sweep(self._base_configs(pv_kwp=5.0), simulate=_paired_const_simulate)
        panel_asked: list[FleetConfig] = []

        with pytest.raises(ValueError) as refusal:
            sensitivity_panel(
                base_configs,
                {KNOBS["battery_cost_per_kwh_gbp"]: [400.0]},
                baseline=baseline,
                simulate=recording(panel_asked, _paired_const_simulate),
            )

        assert "pv_kwp=4.0" in str(refusal.value)
        assert "pv_kwp=5.0" in str(refusal.value)
        assert panel_asked == []

    def test_a_baseline_at_another_floor_is_refused_naming_both_floors(self) -> None:
        base_configs = self._base_configs()
        floor_knob = KNOBS["retained_cash_floor_per_home_per_year_gbp"]
        baseline = run_sweep(
            [(point, floor_knob.apply(scenario, 60.0)) for point, scenario in base_configs],
            simulate=_paired_const_simulate,
        )
        panel_asked: list[FleetConfig] = []

        with pytest.raises(ValueError) as refusal:
            sensitivity_panel(
                base_configs,
                {KNOBS["battery_cost_per_kwh_gbp"]: [400.0]},
                baseline=baseline,
                simulate=recording(panel_asked, _paired_const_simulate),
            )

        assert "50.0" in str(refusal.value)
        assert "60.0" in str(refusal.value)
        assert panel_asked == []

    def test_a_baseline_on_another_own_use_assumption_is_refused_naming_both(self) -> None:
        base_configs = self._base_configs()
        baseline = run_sweep(
            [
                (point, dataclasses.replace(scenario, finance=_overridden(scenario, 0.6)))
                for point, scenario in base_configs
            ],
            simulate=_paired_const_simulate,
        )
        panel_asked: list[FleetConfig] = []

        with pytest.raises(ValueError) as refusal:
            sensitivity_panel(
                base_configs,
                {KNOBS["battery_cost_per_kwh_gbp"]: [400.0]},
                baseline=baseline,
                simulate=recording(panel_asked, _paired_const_simulate),
            )

        assert "None" in str(refusal.value)
        assert "0.6" in str(refusal.value)
        assert panel_asked == []

    def test_base_configs_at_two_floors_are_refused_naming_both_floors_and_no_run_sweep(self) -> None:
        """The panel refuses base_configs at two floors as any cost-recovery sweep does: its refusal names both floors, not a run_sweep its caller never called."""
        floor_knob = KNOBS["retained_cash_floor_per_home_per_year_gbp"]
        base_configs = self._base_configs(pv_kwp=4.0) + [
            (point, floor_knob.apply(scenario, 60.0)) for point, scenario in self._base_configs(pv_kwp=5.0)
        ]
        baseline = run_sweep(
            self._base_configs(pv_kwp=4.0) + self._base_configs(pv_kwp=5.0), simulate=_paired_const_simulate
        )
        panel_asked: list[FleetConfig] = []

        with pytest.raises(ValueError, match="one retained-cash floor") as refusal:
            sensitivity_panel(
                base_configs,
                {KNOBS["battery_cost_per_kwh_gbp"]: [400.0]},
                baseline=baseline,
                simulate=recording(panel_asked, _paired_const_simulate),
            )

        assert "50.0" in str(refusal.value)
        assert "60.0" in str(refusal.value)
        assert "run_sweep" not in str(refusal.value)
        assert panel_asked == []

    def test_a_repeated_axis_value_is_refused_before_any_simulation(self) -> None:
        base_configs = self._base_configs()
        baseline = run_sweep(base_configs, simulate=_paired_const_simulate)
        panel_asked: list[FleetConfig] = []

        with pytest.raises(ValueError) as refusal:
            sensitivity_panel(
                base_configs,
                {KNOBS["battery_cost_per_kwh_gbp"]: [300.0, 300.0]},
                baseline=baseline,
                simulate=recording(panel_asked, _paired_const_simulate),
            )

        assert "battery_cost_per_kwh_gbp" in str(refusal.value)
        assert "300.0" in str(refusal.value)
        assert panel_asked == []


# ---------------------------------------------------------------------------
# TestWH4Coupling — W-H4 user-observable rank-flip signal
# ---------------------------------------------------------------------------


class TestWH4Coupling:
    """W-H4: capex/grid-services knobs move the rank under a constant-energy simulate paired with each config's homes.

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
        base_configs, pt_a, pt_b = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["battery_cost_per_kwh_gbp"]: [self._BATT_COST_LOW, self._BATT_COST_HIGH]},
            simulate=_paired_const_simulate,
        )
        assert panel.baseline_top == pt_b, (
            f"Expected battery config B as baseline_top, got {panel.baseline_top}"
        )

    def test_battery_cost_high_makes_battery_infeasible(self) -> None:
        """At high battery_cost, B is infeasible: absent from rankings and top flips to A."""
        base_configs, pt_a, pt_b = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["battery_cost_per_kwh_gbp"]: [self._BATT_COST_LOW, self._BATT_COST_HIGH]},
            simulate=_paired_const_simulate,
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
        base_configs, pt_a, pt_b = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["grid_services_income_per_kw_per_year_gbp"]: [self._GS_ZERO, self._GS_HIGH]},
            simulate=_paired_const_simulate,
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
        base_configs, pt_a, pt_b = self._setup()
        panel = _panel(
            base_configs,
            axes={
                KNOBS["battery_cost_per_kwh_gbp"]: [self._BATT_COST_LOW, self._BATT_COST_HIGH],
                KNOBS["grid_services_income_per_kw_per_year_gbp"]: [self._GS_ZERO, self._GS_HIGH],
            },
            simulate=_paired_const_simulate,
        )
        # battery_cost: [stable(B=B), unstable(A≠B)] + grid_services: [unstable(A≠B), stable(B=B)]
        # = 2 stable / 4 total = 0.5
        assert panel.rank_stability == pytest.approx(0.5), (
            f"Expected rank_stability == 0.5 (2 stable / 4 total), got {panel.rank_stability}"
        )


# ---------------------------------------------------------------------------
# TestRetainedFloorAxis — the floor is an ordinary knob axis
# ---------------------------------------------------------------------------


class TestRetainedFloorAxis:
    """The retained_cash_floor axis is an ordinary knob axis: each value sweeps the
    base scenarios with the floor knob applied, and None tops at a high floor don't crash.
    """

    def _setup(self):  # type: ignore[no-untyped-def]
        """Return base_configs for a 2-config no-battery / with-battery grid."""
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
        """Per-value rankings/tops match run_sweep over the base scenarios with the floor knob applied at that value."""
        base_configs = self._setup()
        floor_low = 50.0
        floor_high = 500.0  # feasible at this level but different from baseline
        panel = _panel(
            base_configs,
            axes={KNOBS["retained_cash_floor_per_home_per_year_gbp"]: [floor_low, floor_high]},
            simulate=_paired_const_simulate,
        )

        axis = panel.axes[0]
        assert axis.name == "retained_cash_floor_per_home_per_year_gbp"
        assert axis.values == (floor_low, floor_high)

        floor_knob = KNOBS["retained_cash_floor_per_home_per_year_gbp"]
        for i, v in enumerate([floor_low, floor_high]):
            expected = run_sweep(
                [(point, floor_knob.apply(scenario, v)) for point, scenario in base_configs],
                simulate=_paired_const_simulate,
            )
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
        base_configs = self._setup()
        # 9,999,999 GBP floor is far above any solved rate — all infeasible
        panel = _panel(
            base_configs,
            axes={KNOBS["retained_cash_floor_per_home_per_year_gbp"]: [50.0, 9_999_999.0]},
            simulate=_paired_const_simulate,
        )

        axis = panel.axes[0]
        # At floor=50 the config is feasible → non-None top
        assert axis.top_config_per_value[0] is not None
        # At very high floor: all infeasible → None top
        assert axis.top_config_per_value[1] is None

    def test_none_top_counts_as_unstable(self) -> None:
        """A None top at a swept value counts as unstable in rank_stability."""
        base_configs = self._setup()
        panel = _panel(
            base_configs,
            axes={KNOBS["retained_cash_floor_per_home_per_year_gbp"]: [50.0, 9_999_999.0]},
            simulate=_paired_const_simulate,
        )
        # The low-floor value (50.0) is the scenarios' own floor, so its top is baseline_top → 1 stable.
        # The high-floor value is None → unstable.
        # Exactly 1 stable / 2 total = 0.5
        assert panel.rank_stability == pytest.approx(0.5), (
            f"Expected rank_stability == 0.5 (1 stable / 2 total), got {panel.rank_stability}"
        )

    def test_floor_axis_does_not_mutate_finance_in_base_configs(self) -> None:
        """After sensitivity_panel, base_configs scenarios still have original finance."""
        base_configs = self._setup()
        original_floors = [
            sc.finance.retained_cash_floor_per_home_per_year_gbp  # type: ignore[union-attr]
            for _, sc in base_configs
        ]
        _panel(
            base_configs,
            axes={KNOBS["retained_cash_floor_per_home_per_year_gbp"]: [50.0, 500.0]},
            simulate=_paired_const_simulate,
        )
        after_floors = [
            sc.finance.retained_cash_floor_per_home_per_year_gbp  # type: ignore[union-attr]
            for _, sc in base_configs
        ]
        assert original_floors == after_floors, (
            "base_configs finance.retained_cash_floor was mutated (should be immutable)"
        )


# ---------------------------------------------------------------------------
# TestSegAxis — the SEG knob sets the scenario's SEG rate
# ---------------------------------------------------------------------------


class TestSegAxis:
    """The SEG knob sets the scenario's rate, at which each home without a tariff of its own exports."""

    def test_every_fleet_a_sweep_simulates_exports_at_that_sweeps_rate(self) -> None:
        """On homes with no tariff of their own, the baseline sweep's fleets, its age-0 outlay fleet
        included, export at the scenario's 4.1 p/kWh, and each swept value's fleets at that value.
        """
        scenario = make_scenario(
            n_homes=_N_HOMES, seg_tariff_pence_per_kwh=4.1, finance=_interior_finance()
        )
        base_configs = enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
        )
        simulate = _SegPricingSimulate()

        panel = _panel(base_configs, axes={KNOBS["seg_tariff_pence_per_kwh"]: [4.1, 6.0]}, simulate=simulate)

        assert panel.axes[0].values == (4.1, 6.0)
        assert set(simulate.rates_per_call) == {
            frozenset({4.1}),
            frozenset({6.0}),
        }, f"fleets were simulated at SEG rates {set(simulate.rates_per_call)}"

    def test_sweeping_another_rate_than_the_homes_carry_is_refused(self) -> None:
        """On the fleet `optimize configs` builds, whose homes carry the seg: rate of 4.1 p/kWh,
        sweeping 6.0 p/kWh is refused, naming the first home and both rates, not overwritten.
        """
        base_configs = enumerate_configs(
            _make_seg_priced_scenario(4.1, finance=_interior_finance()),
            pv_kwp=[4.0],
            battery_kwh=[0.0],
            inverter_kw=[3.6],
        )

        with pytest.raises(ConfigurationError, match=r"homes\[0\].*4\.1.*6\.0"):
            _panel(base_configs, axes={KNOBS["seg_tariff_pence_per_kwh"]: [6.0]}, simulate=_SegPricingSimulate())


# ---------------------------------------------------------------------------
# TestSensitivityPanelGuards — TypeError without a simulator, ValueError on bad inputs
# ---------------------------------------------------------------------------


class TestSensitivityPanelGuards:
    """sensitivity_panel raises TypeError when passed no simulator, and ValueError on
    empty inputs and an all-infeasible baseline.
    """

    def _base_configs(self):  # type: ignore[no-untyped-def]
        """Return a valid minimal base_configs list (one no-battery config)."""
        scenario = _make_scenario(n_homes=_N_HOMES, finance=_interior_finance())
        return enumerate_configs(
            scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
        )

    def test_empty_base_configs_raises(self) -> None:
        """Empty base_configs raises ValueError."""
        baseline = run_sweep(self._base_configs(), simulate=_paired_const_simulate)
        with pytest.raises(ValueError, match="base_configs"):
            sensitivity_panel(
                [],
                axes={KNOBS["battery_cost_per_kwh_gbp"]: [250.0]},
                baseline=baseline,
                simulate=_paired_const_simulate,
            )

    def test_empty_axes_raises(self) -> None:
        """Empty axes mapping raises ValueError."""
        base_configs = self._base_configs()
        baseline = run_sweep(base_configs, simulate=_paired_const_simulate)
        with pytest.raises(ValueError, match="axes"):
            sensitivity_panel(base_configs, axes={}, baseline=baseline, simulate=_paired_const_simulate)

    def test_empty_axis_values_raises(self) -> None:
        """An axis with an empty values sequence raises ValueError."""
        base_configs = self._base_configs()
        baseline = run_sweep(base_configs, simulate=_paired_const_simulate)
        with pytest.raises(ValueError, match="values must not be empty"):
            sensitivity_panel(
                base_configs,
                axes={KNOBS["battery_cost_per_kwh_gbp"]: []},
                baseline=baseline,
                simulate=_paired_const_simulate,
            )

    def test_all_infeasible_baseline_raises(self) -> None:
        """A baseline with no feasible config raises ValueError (cheapest_feasible is None)."""
        # A floor so high that no config is feasible at baseline
        scenario = _make_scenario(n_homes=_N_HOMES, finance=_make_finance(retained_cash_floor=9_999_999.0))
        base_configs = enumerate_configs(scenario, pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6])
        baseline = run_sweep(base_configs, simulate=_paired_const_simulate)
        with pytest.raises(ValueError, match="no feasible config"):
            sensitivity_panel(
                base_configs,
                axes={KNOBS["battery_cost_per_kwh_gbp"]: [250.0]},
                baseline=baseline,
                simulate=_paired_const_simulate,
            )

    def test_a_call_without_simulate_raises_type_error_naming_simulate(self) -> None:
        """sensitivity_panel runs only the simulator its caller passes: a call passing none is refused by name."""
        base_configs = self._base_configs()
        baseline = run_sweep(base_configs, simulate=_paired_const_simulate)
        with pytest.raises(TypeError, match="simulate"):
            sensitivity_panel(
                base_configs, axes={KNOBS["battery_cost_per_kwh_gbp"]: [250.0]}, baseline=baseline
            )


# ---------------------------------------------------------------------------
# A flat-rate axis under the events model is refused
# ---------------------------------------------------------------------------


def test_a_flat_rate_axis_under_the_events_model_is_refused() -> None:
    """A flat grid-services rate swept over a capacity_at_events scenario is refused by the grid-services knob, which reads no flat rate there, so a library caller of sensitivity_panel gets the refusal too."""
    finance = dataclasses.replace(_interior_finance(), grid_services_model=GridServicesEventsConfig())
    base_configs = enumerate_configs(
        _make_scenario(finance=finance), pv_kwp=[4.0], battery_kwh=[0.0], inverter_kw=[3.6]
    )

    with pytest.raises(ConfigurationError) as refusal:
        _panel(
            base_configs,
            {KNOBS["grid_services_income_per_kw_per_year_gbp"]: (12.0,)},
            simulate=_paired_const_simulate,
        )

    message = str(refusal.value)
    assert "capacity_at_events" in message
    assert "grid_services_income_per_kw_per_year_gbp" in message


# ---------------------------------------------------------------------------
# The rows each sweep evaluation re-sums
# ---------------------------------------------------------------------------


def test_each_home_a_simulate_stand_in_answers_is_a_year_of_hourly_steps() -> None:
    """Every sweep evaluation re-sums each home's series, so the steps per home set this module's cost."""
    fleet_config = FleetConfig(
        homes=_make_seg_priced_scenario(4.1, finance=_interior_finance()).homes
    )
    answers = {
        "_paired_const_simulate": _paired_const_simulate(fleet_config, None, None),
        "_SegPricingSimulate": _SegPricingSimulate()(fleet_config, None, None),
    }
    steps_per_home = {
        name: sorted({len(result.generation) for result in fleet.per_home_results})
        for name, fleet in answers.items()
    }
    assert steps_per_home == {name: [24 * 365] for name in answers}, (
        f"Steps per home: {steps_per_home}, not a year of hourly steps ({24 * 365}). "
        "Build the stand-ins' results with tests/_finance_builders.py::make_sim_results, "
        "whose docstring says why its hourly steps give exact totals."
    )
