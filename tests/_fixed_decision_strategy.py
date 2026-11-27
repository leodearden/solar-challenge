# SPDX-License-Identifier: AGPL-3.0-or-later
"""A test double for a dispatch strategy of a caller's own that returns one fixed decision whatever the step.

FixedDecisionStrategy checks none of its inputs, unlike the built-in strategies, so a test that runs it
through simulate_timestep sees the step's own checks alone refuse what it decides. It records each call's
generation and demand in ``calls``, so a test can also see whether it was asked at all.

Usage::

    from tests._fixed_decision_strategy import FixedDecisionStrategy

    strategy = FixedDecisionStrategy(DispatchDecision(0.0, 1.0), name="over_limit")
    result = simulate_timestep(0.0, 1.0, battery, 60, strategy=strategy)
"""

from datetime import datetime
from typing import Optional

from solar_challenge.dispatch import DispatchDecision, DispatchStrategy, GridChargeContext


class FixedDecisionStrategy(DispatchStrategy):
    """A strategy of a consumer's own, which checks none of its inputs, records each call's generation and demand, and returns one decision whatever the step."""

    def __init__(self, decision: DispatchDecision, *, name: str = "consumer") -> None:
        self._decision = decision
        self._name = name
        self.calls: list[tuple[float, float]] = []

    @property
    def name(self) -> str:
        """Return the name this double was built with."""
        return self._name

    def decide_action(
        self,
        timestamp: datetime,
        generation_kw: float,
        demand_kw: float,
        battery_soc_kwh: float,
        battery_capacity_kwh: float,
        timestep_minutes: float,
        *,
        grid_charge_ctx: Optional[GridChargeContext] = None,
    ) -> DispatchDecision:
        """Record generation_kw and demand_kw, and return the decision this double was built with."""
        self.calls.append((generation_kw, demand_kw))
        return self._decision
