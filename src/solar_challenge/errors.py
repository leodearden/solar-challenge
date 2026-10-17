# SPDX-License-Identifier: AGPL-3.0-or-later
"""The package's exception types: this module imports no other solar_challenge module, so any module can import it at top level."""


class ConfigurationError(ValueError):
    """Raised for a value that an input type or the scenario grammar refuses; the message names the value and why.

    An input value object, such as a component config or the finance or grid-services
    settings, raises it from its constructor for a value it is given; the scenario grammar
    raises it for a scenario it refuses. A computed result whose own invariant breaks, such
    as an EnergyFlowResult or a BillBreakdown, is a defect, not a refusal, and raises plain
    ValueError.

    It is a ValueError, so code that catches ValueError catches every refusal. A handler
    that treats a refusal apart from other ValueErrors names ConfigurationError before
    ValueError.

    Where an input type still raises plain ValueError, docs/prds/errors-leaf.md (contract C4
    and §11) names the work that converts it.
    """
