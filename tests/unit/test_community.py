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
