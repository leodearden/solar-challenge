# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refusal a web request's reader gives a block that is not a mapping, in the form of the module that reads the block.

The scenario grammar's readers word it "<block>: must be a mapping, got <type>", and the web's
own readers "<block> must be a mapping, got <type>". Task 509 is to collapse this to one form
once the web's readers build their refusals through scenario_blocks.refusal.

Usage::

    from tests._non_mapping_block_refusals import non_mapping_block_refusal

    refusal = re.escape(non_mapping_block_refusal("tariff", "str"))
    with pytest.raises(ValueError, match=refusal):
        parse_home_config({**VALID_HOME_PAYLOAD, "tariff": ""})
"""

#: The blocks of a web request that the scenario grammar's readers read.
GRAMMAR_READ_BLOCKS = frozenset({"tariff", "dispatch_strategy", "seg"})


def non_mapping_block_refusal(block: str, type_name: str) -> str:
    """The refusal of a web request's *block* sent as a *type_name*, not a mapping, as the block's reader words it."""
    if block in GRAMMAR_READ_BLOCKS:
        return f"{block}: must be a mapping, got {type_name}"
    return f"{block} must be a mapping, got {type_name}"
