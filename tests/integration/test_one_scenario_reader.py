# SPDX-License-Identifier: AGPL-3.0-or-later
"""G1 and G2 of docs/prds/one-scenario-reader.md §5: every scenario entry point simulates load_scenario(path).with_window(flags).simulated_homes() over its simulation_bounds(), and refuses what the reader refuses.

Each row's id names the leaf that turned it green, so a red node-id names the leaf whose entry point
re-reads a block of the file for itself. The expected homes, bounds and refusal messages are the
reader's own, never a literal copy of them.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest
import yaml

from solar_challenge.config import ScenarioConfig, load_scenario
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.scenario_blocks import parse_tariff_config
from solar_challenge.scenario_writer import location_block
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY

_PERIOD = {"start_date": "2024-06-03", "end_date": "2024-06-09"}
_TARIFF = {"type": "economy_7"}
_SEG = {"rate_pence_per_kwh": 12.0}
_FINANCE = {"standing_charge_pence_per_day": 28.0}

_HOME_BLOCK = {"pv": {"capacity_kw": 3.5}, "battery": {"capacity_kwh": 5.0}, "load": {"annual_consumption_kwh": 3200}}
_LARGER_PV_HOME_BLOCK = {**_HOME_BLOCK, "pv": {"capacity_kw": 5.0}}

_EDINBURGH = LOCATION_PRESETS["edinburgh"]
_BRISTOL = Location.bristol()

_SHARED_BLOCKS: dict[str, Any] = {"period": _PERIOD, "tariff": _TARIFF, "seg": _SEG, "finance": _FINANCE}

HOME: dict[str, Any] = {"name": "one home", "location": location_block(_EDINBURGH), **_SHARED_BLOCKS, "home": _HOME_BLOCK}
HOMES: dict[str, Any] = {
    "name": "two homes",
    "location": location_block(_EDINBURGH),
    **_SHARED_BLOCKS,
    "homes": [_HOME_BLOCK, _LARGER_PV_HOME_BLOCK],
}
FLEET_DISTRIBUTION: dict[str, Any] = {
    "name": "a fleet page fleet",
    "period": _PERIOD,
    "location": location_block(_BRISTOL),
    "fleet_distribution": {
        "n_homes": 3,
        "seed": 7,
        "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 0.5, "min": 2.5, "max": 6.0}},
        "battery": {
            "capacity_kwh": {"type": "uniform", "min": 3.0, "max": 8.0},
            "dispatch_strategy": {"strategy_type": "self_consumption"},
        },
        "load": {"annual_consumption_kwh": 3300.0},
    },
    "tariff": _TARIFF,
    "seg": _SEG,
    "finance": _FINANCE,
}


@dataclasses.dataclass(frozen=True)
class _Flags:
    """The days a run's --start and --end replace, as the CLI's flags, the fleet form's start and end and the reader's with_window give them."""

    first_day: Optional[date] = None
    last_day: Optional[date] = None

    def cli_args(self) -> tuple[str, ...]:
        """The --start and --end arguments that replace these days."""
        start = ("--start", self.first_day.isoformat()) if self.first_day is not None else ()
        end = ("--end", self.last_day.isoformat()) if self.last_day is not None else ()
        return (*start, *end)

    def on_form(self, form: Mapping[str, Any]) -> dict[str, Any]:
        """*form* with its start and end replaced by these days."""
        replaced = dict(form)
        if self.first_day is not None:
            replaced["start"] = self.first_day.isoformat()
        if self.last_day is not None:
            replaced["end"] = self.last_day.isoformat()
        return replaced

    def applied(self, scenario: ScenarioConfig) -> ScenarioConfig:
        """*scenario* as the reader's with_window replaces these days."""
        return scenario.with_window(first_day=self.first_day, last_day=self.last_day)


FLAG_VARIANTS = (
    pytest.param(_Flags(), id="no-flags"),
    pytest.param(_Flags(first_day=date(2024, 6, 5)), id="start-flag"),
    pytest.param(_Flags(last_day=date(2024, 6, 6)), id="end-flag"),
)


def _written(tmp_path: Path, document: Mapping[str, Any], *, name: str = "scenario.yaml") -> Path:
    """The path of *document*, written to *name* under *tmp_path* as YAML."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump(dict(document), sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("document", "location"),
    [
        pytest.param(HOME, _EDINBURGH, id="home-doc"),
        pytest.param(HOMES, _EDINBURGH, id="homes-doc"),
        pytest.param(FLEET_DISTRIBUTION, _BRISTOL, id="fleet-distribution-doc"),
    ],
)
def test_the_reader_gives_each_documents_homes_its_location_tariff_and_seg_over_its_period(
    tmp_path: Path, document: Mapping[str, Any], location: Location
) -> None:
    """Every row below compares against homes that carry the document's location, tariff and SEG over its period, so an entry point that drops one of them (task 957, γ) or runs the default year (task 956, β) cannot equal them."""
    scenario = load_scenario(_written(tmp_path, document))

    window = scenario.window()
    homes = scenario.simulated_homes()
    assert scenario.get_location() == location
    assert {home.location for home in homes} == {location}
    assert {home.tariff_config for home in homes} == {parse_tariff_config(_TARIFF)}
    assert {home.seg_tariff.rate_pence_per_kwh for home in homes if home.seg_tariff is not None} == {12.0}
    assert all(home.seg_tariff is not None for home in homes)
    assert (window.first_day, window.last_day) == (date(2024, 6, 3), date(2024, 6, 9))
    assert (window.first_day, window.last_day) != (DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)
