# SPDX-License-Identifier: AGPL-3.0-or-later
"""The package's exception types: this module imports no other solar_challenge module, so any module can import it at top level."""

from typing import Self


class ConfigurationError(ValueError):
    """Raised for a value that an input type, the scenario grammar or a web request reader refuses; the message names the value and why.

    An input value object, such as a component config or the finance, grid-services or
    flexibility settings, raises it from its constructor for a value it is given; the
    scenario grammar raises it for a scenario it refuses; and the web's request readers,
    solar_challenge.web.request_boundary and the form readers built on it, raise it for a
    request they refuse. A computed result whose own invariant breaks, such as an
    EnergyFlowResult or a BillBreakdown, is a defect, not a refusal, and raises plain
    ValueError.

    The web boundary answers a ConfigurationError as a refusal: HTTP 400, or the site's own
    refusal answer. It gives any other ValueError the same answer, but
    request_boundary.refusal_text first logs it at ERROR as a probable defect. Anything
    else is not a refusal, and an /api view answers it HTTP 500 with a JSON body
    (docs/prds/web-request-boundary.md §3, its reading of D2).

    It is a ValueError, so code that catches ValueError catches every refusal. A handler
    that treats a refusal apart from other ValueErrors names ConfigurationError before
    ValueError.

    Where an input type still raises plain ValueError, docs/prds/errors-leaf.md (contract C4
    and §11) names the work that converts it.
    """

    def __init__(self, *args: object) -> None:
        """Take the arguments ValueError takes; defined with def so inspect reads one signature on every Python minor (docs/surface-forms-inspect-readings.md)."""
        super().__init__(*args)

    @classmethod
    def must_be(cls, field: str, requirement: str, *, got: object) -> Self:
        """Return the refusal of *got*, the value given for *field*, which must be *requirement*: "<field> must be <requirement>, got <got!r>"; the caller raises it."""
        return cls(f"{field} must be {requirement}, got {got!r}")
