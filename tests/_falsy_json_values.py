# SPDX-License-Identifier: AGPL-3.0-or-later
"""Falsy JSON values other than null, as tests send them where a block, a JSON object, is expected, and the refusal a web request's reader gives a block that is not a mapping.

Null is left out because it means the block is absent, and {} because it is a mapping, an
empty block a grammar reads.

Usage::

    from tests._falsy_json_values import FALSY_NON_NULL_VALUES, non_mapping_block_refusal

    @pytest.mark.parametrize(("value", "type_name"), FALSY_NON_NULL_VALUES)
    def test_a_falsy_tariff_is_refused_naming_its_type(value: object, type_name: str) -> None:
        refusal = re.escape(non_mapping_block_refusal("tariff", type_name))
        with pytest.raises(ValueError, match=refusal):
            parse_home_config({**VALID_HOME_PAYLOAD, "tariff": value})
"""

import pytest

#: Each falsy JSON value other than null, with the type name a "must be a mapping" refusal names.
FALSY_NON_NULL_VALUES = (
    pytest.param("", "str", id="empty-string"),
    pytest.param(False, "bool", id="false"),
    pytest.param(0, "int", id="zero"),
    pytest.param([], "list", id="empty-array"),
)

#: The blocks of a web request that the scenario grammar's readers read, refusing one that is not a
#: mapping as "<block>: must be a mapping, got <type>"; the web's own readers refuse the others.
GRAMMAR_READ_BLOCKS = frozenset({"tariff", "dispatch_strategy", "seg"})


def non_mapping_block_refusal(block: str, type_name: str) -> str:
    """The refusal of a web request's *block* sent as a *type_name*, not a mapping, as the block's reader words it."""
    if block in GRAMMAR_READ_BLOCKS:
        return f"{block}: must be a mapping, got {type_name}"
    return f"{block} must be a mapping, got {type_name}"
