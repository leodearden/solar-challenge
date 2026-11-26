# SPDX-License-Identifier: AGPL-3.0-or-later
"""Falsy JSON values other than null, as tests send them where a block, a JSON object, is expected.

Null is left out because it means the block is absent, and {} because it is a mapping, an
empty block a grammar reads.  FALSY_NON_NULL_VALUES holds "" too, for a reader that sits
below a form body's presence rule; FALSY_SENT_VALUES leaves it out, for a form body's
top-level field, which request_boundary.present_fields reads as not sent when "".

Usage::

    from tests._falsy_json_values import FALSY_NON_NULL_VALUES

    @pytest.mark.parametrize(("value", "type_name"), FALSY_NON_NULL_VALUES)
    def test_a_falsy_pv_block_is_refused_naming_its_type(value: object, type_name: str) -> None:
        refusal = re.escape(f"pv must be a mapping, got {type_name}")
        with pytest.raises(ValueError, match=refusal):
            form_to_fleet_distribution_config({**valid_distribution_form(), "pv": value})
"""

import pytest

#: Each falsy JSON value other than null, with the type name a "must be a mapping" refusal names.
FALSY_NON_NULL_VALUES = (
    pytest.param("", "str", id="empty-string"),
    pytest.param(False, "bool", id="false"),
    pytest.param(0, "int", id="zero"),
    pytest.param([], "list", id="empty-array"),
)

#: The falsy values a form body's top-level field sends, with the type name a "must be a
#: mapping" refusal names: those FALSY_NON_NULL_VALUES holds but "", which reads as not sent.
FALSY_SENT_VALUES = (
    pytest.param(False, "bool", id="false"),
    pytest.param(0, "int", id="zero"),
    pytest.param([], "list", id="empty-array"),
)
