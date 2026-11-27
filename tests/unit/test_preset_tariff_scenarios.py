# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board-facing scenarios on Economy 7 name the preset and nothing else, so they are charged tariff.PRESET_RATES' rates.

A scenario that restates the preset's rates keeps charging them when PRESET_RATES moves; one
that names only the preset follows the table. Each file's validity is
tests/unit/test_cli_validate.py::TestValidateConfig::test_every_committed_scenario_is_valid's check.
"""

from typing import Any

import pandas as pd
import pytest

from solar_challenge.config import load_config
from solar_challenge.scenario_blocks import parse_tariff_config
from solar_challenge.tariff import PRESET_RATES, TariffConfig
from tests._repository_paths import SCENARIOS_DIR

#: Each board-facing scenario on Economy 7, with the keys leading to its tariff block.
_PRESET_TARIFF_SCENARIOS = [
    pytest.param("example-economy7.yaml", ("home", "tariff"), id="example-economy7"),
    pytest.param("bristol-arbitrage.yaml", ("home", "tariff"), id="bristol-arbitrage"),
    pytest.param("bristol-phase1-flex.yaml", ("tariff",), id="bristol-phase1-flex"),
]


def _tariff_block(file_name: str, keys: tuple[str, ...]) -> Any:
    """The tariff block of the committed scenario *file_name*, reached through *keys*."""
    block: Any = load_config(SCENARIOS_DIR / file_name)
    for key in keys:
        block = block[key]
    return block


@pytest.mark.parametrize(("file_name", "keys"), _PRESET_TARIFF_SCENARIOS)
def test_the_scenario_states_no_economy_rate_or_window(file_name: str, keys: tuple[str, ...]) -> None:
    block = _tariff_block(file_name, keys)

    assert block.keys() == {"type"}
    assert block["type"] == "economy_7"


@pytest.mark.parametrize(("file_name", "keys"), _PRESET_TARIFF_SCENARIOS)
def test_the_scenario_is_charged_the_presets_rates_at_03_00_and_18_00(
    file_name: str, keys: tuple[str, ...]
) -> None:
    tariff = parse_tariff_config(_tariff_block(file_name, keys))

    assert tariff == TariffConfig.economy_7()
    assert tariff.get_rate(pd.Timestamp("2024-01-15 03:00", tz="Europe/London")) == (
        PRESET_RATES["economy_7"].off_peak_rate
    )
    assert tariff.get_rate(pd.Timestamp("2024-01-15 18:00", tz="Europe/London")) == (
        PRESET_RATES["economy_7"].peak_rate
    )
