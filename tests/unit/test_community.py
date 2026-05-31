"""Tests for solar_challenge.community module.

TDD test suite for:
  - CommunityConfig / CommunityBillingConfig (step-1 / step-2)
  - simulate_community p2p netting (step-3 / step-4)
  - validate_community_balance (step-5 / step-6)
"""
from __future__ import annotations

import dataclasses
import pickle

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import (
    CommunityBillingConfig,
    CommunityConfig,
)
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig


# ---------------------------------------------------------------------------
# Helpers / Fixtures shared across test classes
# ---------------------------------------------------------------------------

def _make_home_result(
    index: pd.DatetimeIndex,
    gen: list[float],
    dem: list[float],
) -> SimulationResults:
    """Build a minimal, individually-balanced SimulationResults (no battery)."""
    n = len(index)
    assert len(gen) == n
    assert len(dem) == n
    exp = [max(0.0, g - d) for g, d in zip(gen, dem)]
    imp = [max(0.0, d - g) for g, d in zip(gen, dem)]
    zeros = [0.0] * n
    return SimulationResults(
        generation=pd.Series(gen, index=index, dtype=float),
        demand=pd.Series(dem, index=index, dtype=float),
        self_consumption=pd.Series([min(g, d) for g, d in zip(gen, dem)], index=index, dtype=float),
        battery_charge=pd.Series(zeros, index=index, dtype=float),
        battery_discharge=pd.Series(zeros, index=index, dtype=float),
        battery_soc=pd.Series(zeros, index=index, dtype=float),
        grid_import=pd.Series(imp, index=index, dtype=float),
        grid_export=pd.Series(exp, index=index, dtype=float),
        import_cost=pd.Series(zeros, index=index, dtype=float),
        export_revenue=pd.Series(zeros, index=index, dtype=float),
        tariff_rate=pd.Series(zeros, index=index, dtype=float),
    )


def _make_fleet(
    index: pd.DatetimeIndex,
    homes: list[tuple[list[float], list[float]]],
) -> FleetResults:
    """Build a synthetic FleetResults from (gen, dem) pairs per home."""
    per_home = [_make_home_result(index, g, d) for g, d in homes]
    configs = [
        HomeConfig(pv_config=PVConfig(capacity_kw=1.0), load_config=LoadConfig())
        for _ in homes
    ]
    return FleetResults(per_home_results=per_home, home_configs=configs)


def _make_home_result_with_battery(
    index: pd.DatetimeIndex,
    gen: list[float],
    dem: list[float],
    bch: list[float],
    bdis: list[float],
) -> SimulationResults:
    """Build a balanced SimulationResults with home battery series.

    Grid flows are derived so that the per-home energy balance holds:
    ``gen + imp + bdis == dem + exp + bch``.
    """
    n = len(index)
    # net = gen - dem + bdis - bch; positive → export, negative → import
    exp = [max(0.0, g - d + dis - ch) for g, d, ch, dis in zip(gen, dem, bch, bdis)]
    imp = [max(0.0, d - g + ch - dis) for g, d, ch, dis in zip(gen, dem, bch, bdis)]
    zeros = [0.0] * n
    return SimulationResults(
        generation=pd.Series(gen, index=index, dtype=float),
        demand=pd.Series(dem, index=index, dtype=float),
        self_consumption=pd.Series([min(g, d) for g, d in zip(gen, dem)], index=index, dtype=float),
        battery_charge=pd.Series(bch, index=index, dtype=float),
        battery_discharge=pd.Series(bdis, index=index, dtype=float),
        battery_soc=pd.Series(zeros, index=index, dtype=float),
        grid_import=pd.Series(imp, index=index, dtype=float),
        grid_export=pd.Series(exp, index=index, dtype=float),
        import_cost=pd.Series(zeros, index=index, dtype=float),
        export_revenue=pd.Series(zeros, index=index, dtype=float),
        tariff_rate=pd.Series(zeros, index=index, dtype=float),
    )


def _make_fleet_from_sim_results(per_home: list[SimulationResults]) -> FleetResults:
    """Build a FleetResults directly from pre-built SimulationResults."""
    configs = [
        HomeConfig(pv_config=PVConfig(capacity_kw=1.0), load_config=LoadConfig())
        for _ in per_home
    ]
    return FleetResults(per_home_results=per_home, home_configs=configs)


# ---------------------------------------------------------------------------
# Step-1: TestCommunityConfig
# ---------------------------------------------------------------------------

class TestCommunityConfig:
    """RED tests for CommunityConfig validation, frozen, and picklable."""

    def test_valid_p2p_config(self) -> None:
        """p2p config with no community_battery constructs OK."""
        cfg = CommunityConfig(sharing_mode="p2p")
        assert cfg.sharing_mode == "p2p"
        assert cfg.community_battery is None

    def test_valid_community_battery_config(self) -> None:
        """community_battery mode with a battery config constructs OK."""
        batt = BatteryConfig(capacity_kwh=10.0)
        cfg = CommunityConfig(sharing_mode="community_battery", community_battery=batt)
        assert cfg.sharing_mode == "community_battery"
        assert cfg.community_battery is batt

    def test_p2p_with_battery_raises(self) -> None:
        """p2p + community_battery set → ValueError."""
        batt = BatteryConfig(capacity_kwh=5.0)
        with pytest.raises(ValueError, match="p2p"):
            CommunityConfig(sharing_mode="p2p", community_battery=batt)

    def test_community_battery_mode_without_battery_raises(self) -> None:
        """community_battery mode without a battery → ValueError."""
        with pytest.raises(ValueError, match="community_battery"):
            CommunityConfig(sharing_mode="community_battery")

    def test_unknown_sharing_mode_raises(self) -> None:
        """Unknown sharing_mode → ValueError."""
        with pytest.raises(ValueError):
            CommunityConfig(sharing_mode="virtual_net_metering")  # type: ignore[arg-type]

    def test_frozen(self) -> None:
        """CommunityConfig is frozen (immutable)."""
        cfg = CommunityConfig(sharing_mode="p2p")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            cfg.sharing_mode = "community_battery"  # type: ignore[misc]

    def test_picklable_without_battery(self) -> None:
        """CommunityConfig(p2p) round-trips through pickle unchanged."""
        cfg = CommunityConfig(sharing_mode="p2p")
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg

    def test_picklable_with_battery(self) -> None:
        """CommunityConfig(community_battery) round-trips through pickle unchanged."""
        batt = BatteryConfig(capacity_kwh=5.0)
        cfg = CommunityConfig(sharing_mode="community_battery", community_battery=batt)
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg

    def test_billing_config_container(self) -> None:
        """CommunityBillingConfig is a forward-compatible container."""
        billing = CommunityBillingConfig()
        assert billing.tariff is None
        assert billing.seg_rate_pence_per_kwh is None

    def test_billing_config_frozen(self) -> None:
        """CommunityBillingConfig is frozen."""
        billing = CommunityBillingConfig()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            billing.seg_rate_pence_per_kwh = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Step-3: TestSimulateCommunityP2P
# ---------------------------------------------------------------------------

class TestSimulateCommunityP2P:
    """RED tests for simulate_community p2p netting on synthetic data."""

    @pytest.fixture
    def index(self) -> pd.DatetimeIndex:
        return pd.date_range("2024-06-21 12:00", periods=3, freq="1min")

    @pytest.fixture
    def fleet(self, index: pd.DatetimeIndex) -> FleetResults:
        """2-home fleet: steps cover E>D, D>E, E==D."""
        # step0: home A exports 4.0, home B imports 1.0 → surplus > deficit
        # step1: home A exports 1.0, home B imports 3.0 → deficit > surplus
        # step2: home A exports 2.0, home B imports 2.0 → balanced
        home_a = ([4.0, 1.0, 2.0], [0.0, 0.0, 0.0])  # gen, dem → exp=gen, imp=0
        home_b = ([0.0, 0.0, 0.0], [1.0, 3.0, 2.0])  # gen=0 → imp=dem, exp=0
        return _make_fleet(index, [home_a, home_b])

    def test_community_results_returned(self, fleet: FleetResults) -> None:
        """simulate_community returns a CommunityResults object."""
        from solar_challenge.community import CommunityResults, simulate_community

        cfg = CommunityConfig(sharing_mode="p2p")
        result = simulate_community(fleet, cfg)
        assert isinstance(result, CommunityResults)

    def test_fleet_results_reference(self, fleet: FleetResults) -> None:
        """CommunityResults.fleet_results references the input FleetResults."""
        from solar_challenge.community import simulate_community

        cfg = CommunityConfig(sharing_mode="p2p")
        result = simulate_community(fleet, cfg)
        assert result.fleet_results is fleet

    def test_grid_export_reduced_by_netting(
        self, fleet: FleetResults, index: pd.DatetimeIndex
    ) -> None:
        """Community grid_export = max(0, E-D) at each step."""
        from solar_challenge.community import simulate_community

        cfg = CommunityConfig(sharing_mode="p2p")
        result = simulate_community(fleet, cfg)
        # step0: E=4, D=1 → cg_exp=3; step1: E=1, D=3 → cg_exp=0; step2: E=2, D=2 → 0
        expected_exp = [3.0, 0.0, 0.0]
        for i, exp_val in enumerate(expected_exp):
            assert result.grid_export.iloc[i] == pytest.approx(exp_val, abs=1e-9), (
                f"step {i}: expected grid_export={exp_val}, got {result.grid_export.iloc[i]}"
            )

    def test_grid_import_reduced_by_netting(
        self, fleet: FleetResults, index: pd.DatetimeIndex
    ) -> None:
        """Community grid_import = max(0, D-E) at each step."""
        from solar_challenge.community import simulate_community

        cfg = CommunityConfig(sharing_mode="p2p")
        result = simulate_community(fleet, cfg)
        # step0: E=4, D=1 → cg_imp=0; step1: E=1, D=3 → cg_imp=2; step2: →0
        expected_imp = [0.0, 2.0, 0.0]
        for i, imp_val in enumerate(expected_imp):
            assert result.grid_import.iloc[i] == pytest.approx(imp_val, abs=1e-9), (
                f"step {i}: expected grid_import={imp_val}, got {result.grid_import.iloc[i]}"
            )

    def test_battery_series_all_zero(self, fleet: FleetResults) -> None:
        """Battery series (charge, discharge, soc) are all 0.0 in p2p (no battery)."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        assert (result.battery_charge == 0.0).all()
        assert (result.battery_discharge == 0.0).all()
        assert (result.battery_soc == 0.0).all()

    def test_series_share_common_index(
        self, fleet: FleetResults, index: pd.DatetimeIndex
    ) -> None:
        """All result series share the fleet's time index."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        pd.testing.assert_index_equal(result.grid_export.index, index)
        pd.testing.assert_index_equal(result.grid_import.index, index)
        pd.testing.assert_index_equal(result.battery_charge.index, index)

    def test_netting_reduces_vs_unshared_totals(
        self, fleet: FleetResults
    ) -> None:
        """Community export + import ≤ unshared fleet totals (netting never increases flows)."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        # Community export must be ≤ fleet total export at every step
        assert (result.grid_export.values <= fleet.total_grid_export.values + 1e-9).all()
        assert (result.grid_import.values <= fleet.total_grid_import.values + 1e-9).all()


# ---------------------------------------------------------------------------
# Step-5: TestValidateCommunityBalance
# ---------------------------------------------------------------------------

class TestValidateCommunityBalance:
    """RED tests for validate_community_balance."""

    @pytest.fixture
    def index(self) -> pd.DatetimeIndex:
        return pd.date_range("2024-06-21 12:00", periods=3, freq="1min")

    @pytest.fixture
    def fleet(self, index: pd.DatetimeIndex) -> FleetResults:
        home_a = ([4.0, 1.0, 2.0], [0.0, 0.0, 0.0])
        home_b = ([0.0, 0.0, 0.0], [1.0, 3.0, 2.0])
        return _make_fleet(index, [home_a, home_b])

    def test_balance_returns_true(self, fleet: FleetResults) -> None:
        """validate_community_balance returns True for a correctly computed result."""
        from solar_challenge.community import (
            simulate_community,
            validate_community_balance,
        )

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        assert validate_community_balance(fleet, result) is True

    def test_balance_raises_on_corrupt_import(self, fleet: FleetResults) -> None:
        """validate_community_balance raises ValueError if grid_import is perturbed."""
        from solar_challenge.community import (
            simulate_community,
            validate_community_balance,
        )

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        # Corrupt: add +5.0 kW to first grid_import value
        bad_import = result.grid_import.copy()
        bad_import.iloc[0] += 5.0
        import dataclasses as dc
        corrupted = dc.replace(result, grid_import=bad_import)
        with pytest.raises(ValueError, match="balance"):
            validate_community_balance(fleet, corrupted)

    def test_balance_accepts_custom_tolerance(self, fleet: FleetResults) -> None:
        """validate_community_balance accepts a non-default tolerance argument."""
        from solar_challenge.community import (
            simulate_community,
            validate_community_balance,
        )

        result = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
        assert validate_community_balance(fleet, result, tolerance=0.01) is True

    @pytest.fixture
    def battery_fleet(self, index: pd.DatetimeIndex) -> FleetResults:
        """2-home fleet with asymmetric non-zero home battery series.

        home_a: all generation is stored in a battery (gen=6, bch=4, exp=2, imp=0)
        home_b: battery covers all demand     (dem=4, bdis=4, exp=0, imp=0)

        Per-home balance:
          A: 6+0+0 == 0+2+4  (6==6) ✓
          B: 0+0+4 == 4+0+0  (4==4) ✓

        Fleet aggregates (per step): gen=6, dem=4, bch=4, bdis=4, exp=2, imp=0
        P2P netting: surplus=2, deficit=0 → cg_exp=2, cg_imp=0
        Community balance: 6+0 == 4+2+(4-4)+0  (6==6) ✓
        """
        home_a = _make_home_result_with_battery(
            index,
            gen=[6.0] * 3,
            dem=[0.0] * 3,
            bch=[4.0] * 3,
            bdis=[0.0] * 3,
        )
        home_b = _make_home_result_with_battery(
            index,
            gen=[0.0] * 3,
            dem=[4.0] * 3,
            bch=[0.0] * 3,
            bdis=[4.0] * 3,
        )
        return _make_fleet_from_sim_results([home_a, home_b])

    def test_balance_returns_true_with_home_batteries(
        self, battery_fleet: FleetResults
    ) -> None:
        """validate_community_balance returns True when homes have non-zero battery series.

        This locks in the Σ(bch_i − bdis_i) term: with bch=4, bdis=4 per step, the
        home battery net is 0 and the balance equation closes correctly.  Any sign
        error or omission of that term would break this fixture's equation.
        """
        from solar_challenge.community import (
            simulate_community,
            validate_community_balance,
        )

        result = simulate_community(battery_fleet, CommunityConfig(sharing_mode="p2p"))
        assert validate_community_balance(battery_fleet, result) is True

    def test_balance_raises_on_corrupt_community_battery_charge(
        self, battery_fleet: FleetResults
    ) -> None:
        """validate_community_balance raises when community battery_charge is perturbed.

        Setting cb_ch = +1.0 kW adds 1.0 to the RHS while LHS stays the same,
        violating the (cb_ch − cb_dis) term in COMMUNITY-BALANCE.
        """
        import dataclasses as dc

        from solar_challenge.community import (
            CommunityResults,
            simulate_community,
            validate_community_balance,
        )

        result = simulate_community(battery_fleet, CommunityConfig(sharing_mode="p2p"))
        # Inject a non-zero community battery charge; balance must break
        bad_cb_ch = result.battery_charge.copy()
        bad_cb_ch.iloc[0] = 1.0  # cb_ch was 0.0; adding 1.0 increases RHS by 1.0
        corrupted = dc.replace(result, battery_charge=bad_cb_ch)
        with pytest.raises(ValueError, match="balance"):
            validate_community_balance(battery_fleet, corrupted)


# ---------------------------------------------------------------------------
# TestSimulateCommunityBattery (step-1 RED, step-3 RED boundary)
# ---------------------------------------------------------------------------

class TestSimulateCommunityBattery:
    """Tests for the community_battery dispatch path in simulate_community."""

    @pytest.fixture
    def index5(self) -> pd.DatetimeIndex:
        """5-step 1-min index for surplus→deficit profile."""
        return pd.date_range("2024-06-21 12:00", periods=5, freq="1min")

    @pytest.fixture
    def cb_cfg(self) -> CommunityConfig:
        """Community battery config with large power limits (no saturation)."""
        return CommunityConfig(
            sharing_mode="community_battery",
            community_battery=BatteryConfig(
                capacity_kwh=10.0,
                max_charge_kw=30.0,
                max_discharge_kw=30.0,
            ),
        )

    @pytest.fixture
    def fleet5(self, index5: pd.DatetimeIndex) -> FleetResults:
        """2-home fleet with surplus on steps 0-2, deficit on steps 3-4.

        Home A: gen=[10,10,10,0,0], dem=[0,0,0,0,0] → exports 10 every step when sunny
        Home B: gen=[0,0,0,0,0],  dem=[2,2,2,10,10] → imports demand every step

        Fleet totals:
          total_grid_export = [10,10,10,0,0]
          total_grid_import = [2,2,2,10,10]
          net_surplus = [8,8,8,0,0]
          net_deficit = [0,0,0,10,10]
        """
        home_a = ([10.0, 10.0, 10.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0])
        home_b = ([0.0, 0.0, 0.0, 0.0, 0.0], [2.0, 2.0, 2.0, 10.0, 10.0])
        return _make_fleet(index5, [home_a, home_b])

    # --- (a) returns CommunityResults (no longer raises) ---

    def test_returns_community_results(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """simulate_community no longer raises NotImplementedError and returns CommunityResults."""
        from solar_challenge.community import CommunityResults, simulate_community

        result = simulate_community(fleet5, cb_cfg)
        assert isinstance(result, CommunityResults)

    # --- (b) charges on net-surplus steps, SOC strictly rises ---

    def test_battery_charges_on_surplus_steps(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """battery_charge > 0 on the first net-surplus step."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        assert result.battery_charge.iloc[0] > 0, (
            f"Expected battery_charge > 0 at step 0, got {result.battery_charge.iloc[0]}"
        )

    def test_soc_rises_on_surplus_steps(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """battery_soc strictly rises across the 3 net-surplus steps."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        soc = result.battery_soc
        assert soc.iloc[0] < soc.iloc[1] < soc.iloc[2], (
            f"Expected rising SOC across steps 0-2, got {soc.iloc[:3].tolist()}"
        )

    # --- (c) discharges on net-deficit steps, SOC falls ---

    def test_battery_discharges_on_deficit_steps(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """battery_discharge > 0 on the first net-deficit step."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        assert result.battery_discharge.iloc[3] > 0, (
            f"Expected battery_discharge > 0 at step 3, got {result.battery_discharge.iloc[3]}"
        )

    def test_soc_falls_on_deficit_step(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """battery_soc falls from step 2 to step 3 when battery discharges."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        soc = result.battery_soc
        assert soc.iloc[3] < soc.iloc[2], (
            f"Expected SOC to fall from step 2 to 3, got {soc.iloc[2]:.4f} → {soc.iloc[3]:.4f}"
        )

    # --- (d) community battery reduces grid import vs p2p ---

    def test_cb_import_less_than_p2p_at_deficit_step(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig, index5: pd.DatetimeIndex
    ) -> None:
        """Community battery grid_import < p2p grid_import at the deficit step."""
        from solar_challenge.community import simulate_community

        p2p_cfg = CommunityConfig(sharing_mode="p2p")
        cb_result = simulate_community(fleet5, cb_cfg)
        p2p_result = simulate_community(fleet5, p2p_cfg)
        assert cb_result.grid_import.iloc[3] < p2p_result.grid_import.iloc[3], (
            f"Expected CB grid_import < p2p at step 3; "
            f"CB={cb_result.grid_import.iloc[3]:.4f}, p2p={p2p_result.grid_import.iloc[3]:.4f}"
        )

    def test_cb_total_import_less_than_p2p(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """Community battery total grid_import.sum() < p2p total over all steps."""
        from solar_challenge.community import simulate_community

        p2p_cfg = CommunityConfig(sharing_mode="p2p")
        cb_result = simulate_community(fleet5, cb_cfg)
        p2p_result = simulate_community(fleet5, p2p_cfg)
        assert cb_result.grid_import.sum() < p2p_result.grid_import.sum(), (
            f"Expected CB total import < p2p; CB={cb_result.grid_import.sum():.4f}, "
            f"p2p={p2p_result.grid_import.sum():.4f}"
        )

    # --- (e) all result series share the fleet index ---

    def test_result_series_share_fleet_index(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig, index5: pd.DatetimeIndex
    ) -> None:
        """All CommunityResults series are on the same fleet DatetimeIndex."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        pd.testing.assert_index_equal(result.grid_import.index, index5)
        pd.testing.assert_index_equal(result.grid_export.index, index5)
        pd.testing.assert_index_equal(result.battery_charge.index, index5)
        pd.testing.assert_index_equal(result.battery_discharge.index, index5)
        pd.testing.assert_index_equal(result.battery_soc.index, index5)

    # --- boundary tests (step-3 RED/boundary) ---

    def test_community_balance_holds_with_cb(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """validate_community_balance returns True with a non-None community battery.

        This exercises the (cb_ch − cb_dis) term in COMMUNITY-BALANCE and confirms
        the balance closes at every step including the battery contribution.
        """
        from solar_challenge.community import simulate_community, validate_community_balance

        result = simulate_community(fleet5, cb_cfg)
        assert validate_community_balance(fleet5, result) is True

    def test_soc_within_battery_capacity(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig
    ) -> None:
        """battery_soc stays in [0, capacity_kwh] at every step."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg)
        capacity = cb_cfg.community_battery.capacity_kwh  # type: ignore[union-attr]
        assert (result.battery_soc >= 0).all(), (
            f"battery_soc has negative values: {result.battery_soc.values}"
        )
        assert (result.battery_soc <= capacity + 1e-9).all(), (
            f"battery_soc exceeds capacity {capacity}: {result.battery_soc.values}"
        )

    # --- power-limit saturation fixture ---

    @pytest.fixture
    def sat_cfg(self) -> CommunityConfig:
        """Community battery config with tight power limits to force saturation."""
        return CommunityConfig(
            sharing_mode="community_battery",
            community_battery=BatteryConfig(
                capacity_kwh=50.0,
                max_charge_kw=20.0,
                max_discharge_kw=20.0,
            ),
        )

    @pytest.fixture
    def sat_fleet(self) -> FleetResults:
        """2-step fleet: step 0 net_surplus=100 (charge-saturates), step 1 net_deficit=100.

        Home A: gen=[100, 0], dem=[0,   0]
        Home B: gen=[0,   0], dem=[0, 100]

        net_surplus=[100, 0], net_deficit=[0, 100]
        With max_charge_kw=20 → battery can only absorb 20kW at step 0;
        residual 80kW spills to cg_exp. At step 1, battery can only supply
        20kW → residual 80kW must be imported.
        """
        index2 = pd.date_range("2024-06-21 12:00", periods=2, freq="1min")
        home_a = ([100.0, 0.0], [0.0, 0.0])
        home_b = ([0.0, 0.0], [0.0, 100.0])
        return _make_fleet(index2, [home_a, home_b])

    def test_charge_capped_at_max_charge_kw(
        self, sat_fleet: FleetResults, sat_cfg: CommunityConfig
    ) -> None:
        """battery_charge never exceeds max_charge_kw when net_surplus is large."""
        from solar_challenge.community import simulate_community

        result = simulate_community(sat_fleet, sat_cfg)
        max_kw = sat_cfg.community_battery.max_charge_kw  # type: ignore[union-attr]
        assert (result.battery_charge <= max_kw + 1e-9).all(), (
            f"battery_charge exceeds max_charge_kw={max_kw}: {result.battery_charge.values}"
        )

    def test_discharge_capped_at_max_discharge_kw(
        self, sat_fleet: FleetResults, sat_cfg: CommunityConfig
    ) -> None:
        """battery_discharge never exceeds max_discharge_kw when net_deficit is large."""
        from solar_challenge.community import simulate_community

        result = simulate_community(sat_fleet, sat_cfg)
        max_kw = sat_cfg.community_battery.max_discharge_kw  # type: ignore[union-attr]
        assert (result.battery_discharge <= max_kw + 1e-9).all(), (
            f"battery_discharge exceeds max_discharge_kw={max_kw}: {result.battery_discharge.values}"
        )

    def test_surplus_residual_spills_to_grid_export(
        self, sat_fleet: FleetResults, sat_cfg: CommunityConfig
    ) -> None:
        """Excess surplus beyond charge cap spills to grid_export at step 0."""
        from solar_challenge.community import simulate_community

        result = simulate_community(sat_fleet, sat_cfg)
        assert result.grid_export.iloc[0] > 0, (
            f"Expected grid_export > 0 (charge capped), got {result.grid_export.iloc[0]}"
        )

    def test_deficit_residual_imported_from_grid(
        self, sat_fleet: FleetResults, sat_cfg: CommunityConfig
    ) -> None:
        """Unmet deficit beyond discharge cap is still imported at step 1."""
        from solar_challenge.community import simulate_community

        result = simulate_community(sat_fleet, sat_cfg)
        assert result.grid_import.iloc[1] > 0, (
            f"Expected grid_import > 0 (discharge capped), got {result.grid_import.iloc[1]}"
        )

    def test_saturation_balance_holds(
        self, sat_fleet: FleetResults, sat_cfg: CommunityConfig
    ) -> None:
        """COMMUNITY-BALANCE holds even under power-limit saturation."""
        from solar_challenge.community import simulate_community, validate_community_balance

        result = simulate_community(sat_fleet, sat_cfg)
        assert validate_community_balance(sat_fleet, result) is True

    def test_validate_balance_false_returns_same_shape(
        self, fleet5: FleetResults, cb_cfg: CommunityConfig, index5: pd.DatetimeIndex
    ) -> None:
        """validate_balance=False returns result with same shape and index (no side-effects)."""
        from solar_challenge.community import simulate_community

        result = simulate_community(fleet5, cb_cfg, validate_balance=False)
        assert len(result.grid_import) == len(index5)
        assert len(result.battery_soc) == len(index5)
        pd.testing.assert_index_equal(result.grid_import.index, index5)
