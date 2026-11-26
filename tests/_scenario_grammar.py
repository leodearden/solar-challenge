# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario grammar's modules and the strata they import in, lowest first, for the guards that read the grammar's source (docs/prds/scenario-grammar-partition.md §3, §4.2).

Usage::

    from tests._scenario_grammar import GRAMMAR_MODULES, GRAMMAR_STRATA

    for module in GRAMMAR_MODULES:
        ...
"""

_PACKAGE = "solar_challenge"
SCENARIO_BLOCKS = f"{_PACKAGE}.scenario_blocks"
FLEET_DISTRIBUTION = f"{_PACKAGE}.fleet_distribution"
CONFIG = f"{_PACKAGE}.config"
#: The scenario grammar's strata, lowest first: no module of one imports a module of a higher one.
GRAMMAR_STRATA: tuple[tuple[str, ...], ...] = (
    (f"{_PACKAGE}.errors", f"{_PACKAGE}.number_fields"),
    (SCENARIO_BLOCKS,),
    (FLEET_DISTRIBUTION,),
    (CONFIG,),
)
#: The grammar modules: those of every stratum above the lowest, whose leaves the grammar imports.
GRAMMAR_MODULES: tuple[str, ...] = tuple(
    module for stratum in GRAMMAR_STRATA[1:] for module in stratum
)
