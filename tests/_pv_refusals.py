# SPDX-License-Identifier: AGPL-3.0-or-later
"""The PV tests' check that a PVConfig refused at construction is refused with the same message at use.

A PVConfig keeps the caller's module dict, so a test edits that dict after construction to reach the use-time checks.

Usage::

    from tests._pv_refusals import one_refusal_at_construction_and_at_use

    module = default_module()
    config = PVConfig(capacity_kw=4.0, custom_module_params=module)
    module["T_NOCT"] = 20.0
    message = one_refusal_at_construction_and_at_use(config)
"""

import dataclasses

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import PVConfig, create_pv_system, wired_dc_capacity_kw


def one_refusal_at_construction_and_at_use(config: PVConfig) -> str:
    """The message with which PVConfig refuses config built again, its custom module edited since, asserting that create_pv_system and wired_dc_capacity_kw refuse config with that same message."""
    with pytest.raises(ConfigurationError) as constructing:
        dataclasses.replace(config)
    with pytest.raises(ConfigurationError) as building:
        create_pv_system(config)
    with pytest.raises(ConfigurationError) as wiring:
        wired_dc_capacity_kw(config)

    message = str(constructing.value)
    assert str(building.value) == message, f"create_pv_system: {building.value}\nconstruction: {message}"
    assert str(wiring.value) == message, f"wired_dc_capacity_kw: {wiring.value}\nconstruction: {message}"
    return message
