# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test doubles for a dispatch strategy of a caller's own, a DispatchStrategy subclass the library does not know.

ConsumerStrategy defines only name and decide_action, so it reads charges_from_the_grid as the
base class declares it. ConsumerStrategyThatIgnoresTheGrid overrides charges_from_the_grid to
False, as a consumer's strategy that ignores a GridChargeContext declares itself.
"""

from datetime import datetime
from typing import Optional

from solar_challenge.dispatch import DispatchDecision, DispatchStrategy, GridChargeContext


class ConsumerStrategy(DispatchStrategy):
    """A strategy of a caller's own, named 'consumer', which leaves the battery alone."""

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "consumer"

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
        """Leave the battery alone."""
        return DispatchDecision(charge_kw=0.0, discharge_kw=0.0)


class ConsumerStrategyThatIgnoresTheGrid(ConsumerStrategy):
    """A strategy of a caller's own, named 'consumer_that_ignores_the_grid', which declares that it does not charge from the grid."""

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "consumer_that_ignores_the_grid"

    @property
    def charges_from_the_grid(self) -> bool:
        """False: it leaves the battery alone, whatever GridChargeContext it is offered."""
        return False
