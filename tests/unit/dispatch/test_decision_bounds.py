# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 rows 8-12: a decision's powers are finite and at least 0, and simulate_timestep refuses one that asks for more than its step allows, before the battery moves."""

import dataclasses
import math
import re

import pytest

from solar_challenge.dispatch import DispatchDecision

NOT_FINITE_AND_AT_LEAST_0 = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="-inf"),
    pytest.param(-1.0, id="negative"),
]


class TestADecisionRefusesAPowerThatIsNotFiniteAndAtLeast0:
    """§9 row 11, the decision's half: each of a decision's three powers is finite and at least 0, whatever its step."""

    @pytest.mark.parametrize("value", NOT_FINITE_AND_AT_LEAST_0)
    @pytest.mark.parametrize("field", ["charge_kw", "discharge_kw", "grid_charge_kw"])
    def test_the_decision_refuses_the_power_naming_its_field_and_value(self, field: str, value: float) -> None:
        powers = {"charge_kw": 0.0, "discharge_kw": 0.0, "grid_charge_kw": 0.0, field: value}
        refusal = f"{field} must be non-negative and finite, got {value!r} kW"
        with pytest.raises(ValueError, match=f"^{re.escape(refusal)}$"):
            DispatchDecision(**powers)

    def test_finite_powers_at_least_0_construct_and_the_exclusivity_refusals_still_fire(self) -> None:
        assert dataclasses.astuple(DispatchDecision(0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
        assert dataclasses.astuple(DispatchDecision(1.5, 0.0, 2.0)) == (1.5, 0.0, 2.0)
        with pytest.raises(ValueError, match="^Cannot charge and discharge simultaneously"):
            DispatchDecision(1.0, 1.0, 0.0)
        with pytest.raises(ValueError, match="^Cannot grid-charge and discharge simultaneously"):
            DispatchDecision(0.0, 1.0, 1.0)
