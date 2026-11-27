# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_pv_refusals.py, the PV tests' check that a PVConfig refused at construction is refused with the same message at use."""

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import PVConfig
from tests._pv_modules import default_module
from tests._pv_refusals import one_refusal_at_construction_and_at_use


def test_returns_the_message_constructing_the_edited_config_raises() -> None:
    module = default_module()
    config = PVConfig(capacity_kw=4.0, custom_module_params=module)
    module["T_NOCT"] = 20.0

    with pytest.raises(ConfigurationError) as constructing:
        PVConfig(capacity_kw=4.0, custom_module_params=module)

    assert one_refusal_at_construction_and_at_use(config) == str(constructing.value)


def test_fails_a_config_construction_accepts() -> None:
    with pytest.raises(pytest.fail.Exception):
        one_refusal_at_construction_and_at_use(PVConfig.default_4kw())
