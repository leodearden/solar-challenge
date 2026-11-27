# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heat pump blocks that scenario_blocks.parse_heat_pump_block refuses for a key it does not recognise, each with that key.

parse_home_config's tests and the POST /api/simulate/home tests share them, so the parser and
the endpoint are held to the same blocks.

Usage::

    from tests._heat_pump_block_refusals import UNRECOGNISED_KEY_HEAT_PUMP_BLOCKS

    @pytest.mark.parametrize(("block", "key"), UNRECOGNISED_KEY_HEAT_PUMP_BLOCKS)
    def test_a_block_the_grammar_refuses_is_refused(block: dict, key: str) -> None:
        with pytest.raises(ConfigurationError, match=re.escape(repr(key))):
            parse_home_config({**VALID_HOME_PAYLOAD, "heat_pump": block})
"""

import pytest

#: Each heat pump block whose one unrecognised key is a slip a sender could make, with that key.
UNRECOGNISED_KEY_HEAT_PUMP_BLOCKS = (
    pytest.param({"heat_pump_type": "GSHP", "thermal_capacity": 12}, "thermal_capacity", id="misspelt-key"),
    pytest.param({"type": "GSHP", "thermal_capacity_kw": 12}, "type", id="form-key"),
)
