# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_scenario, called directly with fleet forms: the bodies fleet-simulator.js's buildPayload() posts."""

from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.config import ConfigurationError
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_scenario import scenario_from_fleet_form

_FLEET_FORM: dict[str, Any] = {
    "name": "Round Trip Fleet",
    "n_homes": 3,
    "seed": 7,
    "pv": {
        "capacity_kw": {
            "type": "weighted_discrete",
            "values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 3}],
        }
    },
    "battery": {
        "capacity_kwh": {
            "type": "shuffled_pool",
            "entries": [{"value": 0, "count": 1}, {"value": 5.0, "count": 2}],
        }
    },
    "load": {
        "annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800, "min": 2000, "max": 6000}
    },
    "start": "2024-07-01",
    "end": "2024-07-10",
    "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
    "seg": {"preset": "Octopus"},
    "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5},
}


def _without(form: dict[str, Any], *keys: str) -> dict[str, Any]:
    """*form* without *keys*, as buildPayload leaves out a disabled block."""
    return {key: value for key, value in form.items() if key not in keys}


class TestScenarioFromFleetForm:
    """The fleet scenario document scenario_from_fleet_form builds from a fleet form, and its refusals."""

    def test_a_fleet_form_is_the_scenario_document_it_describes(self) -> None:
        """Its distributions are written in config.py's grammar with the dispatch under the battery; its dates, location, tariff and SEG are their blocks.

        The blocks come in the order the scenario builder writes them.
        """
        expected = {
            "name": "Round Trip Fleet",
            "period": {"start_date": "2024-07-01", "end_date": "2024-07-10"},
            "location": location_block(Location.bristol()),
            "fleet_distribution": {
                "n_homes": 3,
                "seed": 7,
                "pv": {
                    "capacity_kw": {
                        "type": "weighted_discrete",
                        "values": [3.0, 5.0],
                        "weights": [1.0, 3.0],
                    }
                },
                "battery": {
                    "capacity_kwh": {"type": "shuffled_pool", "values": [0.0, 5.0], "counts": [1, 2]},
                    "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5},
                },
                "load": {
                    "annual_consumption_kwh": {
                        "type": "normal",
                        "mean": 3400.0,
                        "std": 800.0,
                        "min": 2000.0,
                        "max": 6000.0,
                    }
                },
            },
            "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
            "seg": {"preset": "Octopus"},
        }

        assert list(scenario_from_fleet_form(_FLEET_FORM).items()) == list(expected.items())

    def test_a_fleet_form_without_overlays_writes_no_tariff_seg_or_battery_dispatch(self) -> None:
        """A form with no tariff, SEG or dispatch writes null tariff: and seg: blocks and a battery block of its capacity alone; its days give the period."""
        form = {
            **_without(_FLEET_FORM, "start", "end", "tariff", "seg", "dispatch_strategy"),
            "days": 7,
        }

        document = scenario_from_fleet_form(form)

        assert document["period"] == {"start_date": "2024-06-01", "end_date": "2024-06-07"}
        assert (document["tariff"], document["seg"]) == (None, None)
        assert document["fleet_distribution"]["battery"].keys() == {"capacity_kwh"}

    def test_a_dispatch_strategy_sent_without_a_battery_is_not_written(self) -> None:
        """The simulate endpoint's overlay gives that dispatch to no home, so the document is the one the form without it describes."""
        without_battery = _without(_FLEET_FORM, "battery")

        document = scenario_from_fleet_form(without_battery)

        assert "battery" not in document["fleet_distribution"]
        assert document == scenario_from_fleet_form(_without(without_battery, "dispatch_strategy"))

    @pytest.mark.parametrize(
        ("form", "reason"),
        [
            pytest.param({**_FLEET_FORM, "tariff": {"type": "flat_rate"}}, "rate_per_kwh", id="tariff"),
            pytest.param({**_FLEET_FORM, "seg": {}}, "seg", id="seg"),
            pytest.param(
                {**_without(_FLEET_FORM, "battery"), "dispatch_strategy": {"strategy_type": "turbo"}},
                "turbo",
                id="dispatch-without-battery",
            ),
            pytest.param(
                {**_FLEET_FORM, "start": "not-a-date", "end": "2024-07-10"}, "not-a-date", id="start-date"
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {
                        "capacity_kw": {"type": "weighted_discrete", "values": [{"value": 0, "weight": 1}]}
                    },
                },
                "PV capacity must be positive",
                id="pv-capacity-zero",
            ),
        ],
    )
    def test_a_fleet_form_the_loaders_would_refuse_is_refused(
        self, form: dict[str, Any], reason: str
    ) -> None:
        """A block the loaders or the simulate endpoint refuse is refused with their reason, so no YAML is written for it.

        A dispatch is checked even without a battery to carry it, as the simulate endpoint checks it.
        A fleet whose homes cannot be generated is refused too: load_fleet_config generates them.
        """
        with pytest.raises((ValueError, ConfigurationError), match=reason):
            scenario_from_fleet_form(form)
