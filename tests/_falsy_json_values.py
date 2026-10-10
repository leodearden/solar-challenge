# SPDX-License-Identifier: AGPL-3.0-or-later
"""Falsy JSON values other than null, as tests send them where a block, a JSON object, is expected.

Null is left out because it means the block is absent, and {} because it is a mapping, an
empty block a grammar reads.

Usage::

    from tests._falsy_json_values import FALSY_NON_NULL_VALUES

    @pytest.mark.parametrize(("value", "type_name"), FALSY_NON_NULL_VALUES)
    def test_a_falsy_tariff_is_refused_naming_its_type(value: object, type_name: str) -> None:
        refusal = re.escape(f"tariff must be a mapping, got {type_name}")
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
