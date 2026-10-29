# SPDX-License-Identifier: AGPL-3.0-or-later
"""The package's exception types: this module imports no other solar_challenge module, so any module can import it at top level."""

from typing import Self


class ConfigurationError(ValueError):
    """Raised for a value that an input type or the scenario grammar refuses; the message names the value and why.

    An input value object, such as a component config or the finance, grid-services or
    flexibility settings, raises it from its constructor for a value it is given; the
    scenario grammar raises it for a scenario it refuses. A computed result whose own
    invariant breaks, such as an EnergyFlowResult or a BillBreakdown, is a defect, not a
    refusal, and raises plain ValueError.

    It is a ValueError, so code that catches ValueError catches every refusal. A handler
    that treats a refusal apart from other ValueErrors names ConfigurationError before
    ValueError.

    Where an input type still raises plain ValueError, docs/prds/errors-leaf.md (contract C4
    and §11) names the work that converts it.
    """

    @classmethod
    def must_be(cls, field: str, requirement: str, *, got: object) -> Self:
        """Return the refusal of *got*, the value given for *field*, which must be *requirement*: "<field> must be <requirement>, got <got!r>"; the caller raises it."""
        return cls(f"{field} must be {requirement}, got {got!r}")
