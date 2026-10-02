# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for DispatchDecision, the charge, discharge and grid-charge powers a strategy returns for one timestep."""

import pytest

from solar_challenge.dispatch import DispatchDecision


class TestDispatchDecisionBasics:
    """Test basic DispatchDecision functionality."""

    def test_create_with_charge(self):
        """DispatchDecision can be created with charge power."""
        decision = DispatchDecision(charge_kw=2.5, discharge_kw=0.0)
        assert decision.charge_kw == 2.5
        assert decision.discharge_kw == 0.0

    def test_create_with_discharge(self):
        """DispatchDecision can be created with discharge power."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=3.0)
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 3.0

    def test_create_with_no_action(self):
        """DispatchDecision can be created with no action."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        assert decision.charge_kw == 0.0
        assert decision.discharge_kw == 0.0

    def test_decision_is_frozen(self):
        """DispatchDecision is immutable (frozen dataclass)."""
        decision = DispatchDecision(charge_kw=1.0, discharge_kw=0.0)
        with pytest.raises(Exception):  # FrozenInstanceError
            decision.charge_kw = 2.0


class TestDispatchDecisionValidation:
    """Test DispatchDecision validation."""

    def test_negative_charge_raises(self):
        """Negative charge power raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=-1.0, discharge_kw=0.0)

    def test_negative_discharge_raises(self):
        """Negative discharge power raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=0.0, discharge_kw=-1.0)

    def test_simultaneous_charge_discharge_raises(self):
        """Cannot charge and discharge at the same time."""
        with pytest.raises(ValueError, match="simultaneously"):
            DispatchDecision(charge_kw=1.0, discharge_kw=1.0)

    def test_simultaneous_small_values_raises(self):
        """Even small simultaneous charge/discharge raises error."""
        with pytest.raises(ValueError, match="simultaneously"):
            DispatchDecision(charge_kw=0.1, discharge_kw=0.1)


class TestDispatchDecisionGridCharge:
    """Test grid_charge_kw field on DispatchDecision."""

    def test_default_grid_charge_kw_is_zero(self):
        """Existing 2-keyword construction still valid; grid_charge_kw defaults to 0.0."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0)
        assert decision.grid_charge_kw == 0.0

    def test_grid_charge_kw_stored(self):
        """grid_charge_kw field stores the supplied value."""
        decision = DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=2.0)
        assert decision.grid_charge_kw == 2.0

    def test_negative_grid_charge_kw_raises(self):
        """Negative grid_charge_kw raises ValueError with 'non-negative' message."""
        with pytest.raises(ValueError, match="non-negative"):
            DispatchDecision(charge_kw=0.0, discharge_kw=0.0, grid_charge_kw=-0.5)

    def test_grid_charge_and_discharge_simultaneously_raises(self):
        """grid_charge_kw > 0 and discharge_kw > 0 is physically impossible."""
        with pytest.raises(ValueError, match="grid.charge|discharge"):
            DispatchDecision(charge_kw=0.0, discharge_kw=1.0, grid_charge_kw=2.0)

    def test_grid_charge_with_pv_charge_is_allowed(self):
        """grid_charge_kw > 0 alongside charge_kw > 0 is permitted (both charging)."""
        decision = DispatchDecision(charge_kw=1.5, discharge_kw=0.0, grid_charge_kw=2.0)
        assert decision.charge_kw == 1.5
        assert decision.grid_charge_kw == 2.0
