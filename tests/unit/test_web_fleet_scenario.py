# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_scenario, called directly with fleet forms: the bodies fleet-simulator.js's buildPayload() posts."""

import re
from typing import Any

import pytest
import yaml

pytest.importorskip("flask")

from solar_challenge.config import ConfigurationError
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES
from solar_challenge.web.fleet_scenario import (
    ImportedFleetForm,
    fleet_form_from_scenario,
    scenario_from_fleet_form,
)
from solar_challenge.web.shared import resolve_location

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


#: The scenario document _FLEET_FORM describes.
_FLEET_SCENARIO: dict[str, Any] = {
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


def _without(form: dict[str, Any], *keys: str) -> dict[str, Any]:
    """*form* without *keys*, as buildPayload leaves out a disabled block."""
    return {key: value for key, value in form.items() if key not in keys}


def _with_fleet_distribution(**blocks: Any) -> dict[str, Any]:
    """_FLEET_SCENARIO with *blocks* in place of those of its fleet_distribution block."""
    return {
        **_FLEET_SCENARIO,
        "fleet_distribution": {**_FLEET_SCENARIO["fleet_distribution"], **blocks},
    }


class TestScenarioFromFleetForm:
    """The fleet scenario document scenario_from_fleet_form builds from a fleet form, and its refusals."""

    def test_a_fleet_form_is_the_scenario_document_it_describes(self) -> None:
        """Its distributions are written in config.py's grammar with the dispatch under the battery; its dates, location, tariff and SEG are their blocks.

        The blocks come in the order the scenario builder writes them.
        """
        assert list(scenario_from_fleet_form(_FLEET_FORM).items()) == list(_FLEET_SCENARIO.items())

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


_BRISTOL_LIKE_SCENARIO_YAML = """\
name: Bristol Phase 1
location:
  latitude: 51.45
  longitude: -2.58
  timezone: Europe/London
  altitude: 11.0
  name: Bristol, UK
seg:
  rate_pence_per_kwh: 4.1
fleet_distribution:
  n_homes: 100
  seed: 42
  random_order: bristol_legacy
  pv:
    capacity_kw:
      type: shuffled_pool
      values: [3.0, 4.0, 5.0, 6.0]
      counts: [20, 40, 30, 10]
    azimuth: 180
    tilt: 35
  battery:
    capacity_kwh:
      type: shuffled_pool
      values: [null, 5.0, 10.0]
      counts: [40, 40, 20]
  load:
    annual_consumption_kwh:
      type: normal
      mean: 3400
      std: 800
      min: 2000
      max: 6000
finance:
  standing_charge_pence_per_day: 60.0
"""


class TestFleetFormFromScenario:
    """The fleet form fleet_form_from_scenario reads from a fleet scenario, the settings it names as not loaded, and its refusals."""

    def test_a_fleet_scenario_is_the_fleet_form_it_describes(self) -> None:
        """The scenario a fleet form describes reads back as that form: its distributions as the editors' rows, its battery's dispatch as the form's dispatch strategy, and its period as start and end dates."""
        assert fleet_form_from_scenario(_FLEET_SCENARIO) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=()
        )

    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(_FLEET_FORM, id="every-overlay"),
            pytest.param(
                _without(_FLEET_FORM, "battery", "tariff", "seg", "dispatch_strategy"),
                id="no-battery-or-overlay",
            ),
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
                    "battery": {
                        "capacity_kwh": {"type": "normal", "mean": 5.0, "std": 2.0, "min": 0.0, "max": 10.0}
                    },
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "shuffled_pool",
                            "entries": [{"value": 2900, "count": 2}, {"value": 4500, "count": 1}],
                        }
                    },
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.28},
                    "seg": {"rate_pence_per_kwh": 4.5},
                    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 21]]},
                },
                id="uniform-normal-and-pool-editors",
            ),
        ],
    )
    def test_an_exported_fleet_form_imports_back_to_the_same_scenario(
        self, form: dict[str, Any]
    ) -> None:
        """Every setting of a scenario the page exports is one the form holds, and the form read back describes that scenario."""
        document = scenario_from_fleet_form(form)

        imported = fleet_form_from_scenario(document)

        assert imported.not_loaded == ()
        assert scenario_from_fleet_form(imported.form) == document

    def test_a_scenario_file_loads_what_the_form_holds_and_names_the_rest(self) -> None:
        """A scenario file loads its name, fleet size, seed, distributions and SEG; the settings the form has no control for are named, in document order.

        A null battery capacity reads as 0 kWh: either way the home has no battery.
        """
        imported = fleet_form_from_scenario(yaml.safe_load(_BRISTOL_LIKE_SCENARIO_YAML))

        assert imported.form == {
            "name": "Bristol Phase 1",
            "n_homes": 100,
            "seed": 42,
            "pv": {
                "capacity_kw": {
                    "type": "shuffled_pool",
                    "entries": [
                        {"value": 3.0, "count": 20},
                        {"value": 4.0, "count": 40},
                        {"value": 5.0, "count": 30},
                        {"value": 6.0, "count": 10},
                    ],
                }
            },
            "battery": {
                "capacity_kwh": {
                    "type": "shuffled_pool",
                    "entries": [
                        {"value": 0.0, "count": 40},
                        {"value": 5.0, "count": 40},
                        {"value": 10.0, "count": 20},
                    ],
                }
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
            "seg": {"rate_pence_per_kwh": 4.1},
        }
        assert imported.not_loaded == (
            "fleet_distribution.random_order",
            "fleet_distribution.pv.azimuth",
            "fleet_distribution.pv.tilt",
            "finance",
        )

    def test_a_location_other_than_bristol_is_not_loaded(self) -> None:
        """The fleet page has no location control and runs its fleet at Bristol, so a London scenario loads the rest and names its location."""
        london = {**_FLEET_SCENARIO, "location": location_block(resolve_location("london"))}

        assert fleet_form_from_scenario(london) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=("location",)
        )

    def test_a_tariff_key_the_form_has_no_field_for_is_not_loaded(self) -> None:
        """An Economy 7 tariff loads its type and rates, and names the off-peak start the page has no field for."""
        tariff = {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1, "off_peak_start": "01:00"}

        assert fleet_form_from_scenario({**_FLEET_SCENARIO, "tariff": tariff}) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=("tariff.off_peak_start",)
        )

    @pytest.mark.parametrize(
        ("document", "reason"),
        [
            pytest.param([_FLEET_SCENARIO], "mapping", id="list-document"),
            pytest.param(
                {"name": "One Home", "home": {"pv": {"capacity_kw": 4.0}}},
                "fleet_distribution",
                id="home-scenario",
            ),
            pytest.param(
                _with_fleet_distribution(pv={"capacity_kw": 5.5}),
                "fleet_distribution.pv.capacity_kw",
                id="fixed-pv-capacity",
            ),
            pytest.param(
                _with_fleet_distribution(
                    battery={
                        "capacity_kwh": {
                            "type": "proportional_to",
                            "source": "pv.capacity_kw",
                            "multiplier": 2.0,
                        }
                    }
                ),
                "fleet_distribution.battery.capacity_kwh",
                id="proportional-battery-capacity",
            ),
            pytest.param(
                _with_fleet_distribution(
                    pv={"capacity_kw": {"type": "shuffled_pool", "values": [None, 4.0], "counts": [1, 2]}}
                ),
                "fleet_distribution.pv.capacity_kw",
                id="null-in-a-pv-pool",
            ),
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "tariff": {
                        "type": "custom",
                        "periods": [{"start_time": "00:00", "end_time": "00:00", "rate_per_kwh": 0.25}],
                    },
                },
                "tariff.type",
                id="custom-tariff",
            ),
            pytest.param(
                {**_FLEET_SCENARIO, "tariff": {"type": "economy_7", "off_peak_rate": 0.1}},
                "tariff.peak_rate",
                id="economy-7-without-a-peak-rate",
            ),
            pytest.param(
                _with_fleet_distribution(
                    battery={
                        **_FLEET_SCENARIO["fleet_distribution"]["battery"],
                        "dispatch_strategy": {
                            "strategy_type": "tou_optimized",
                            "peak_hours": [[7, 9], [16, 19]],
                        },
                    }
                ),
                "fleet_distribution.battery.dispatch_strategy.peak_hours",
                id="two-peak-windows",
            ),
            pytest.param(
                _with_fleet_distribution(n_homes=MAX_FLEET_HOMES + 1),
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}",
                id="more-homes-than-the-page-runs",
            ),
        ],
    )
    def test_a_scenario_the_form_cannot_hold_is_refused(self, document: object, reason: str) -> None:
        """A scenario whose fleet, tariff or dispatch the form cannot hold exactly is refused, naming the setting: loading it anyway would run a different fleet."""
        with pytest.raises(ValueError, match=re.escape(reason)):
            fleet_form_from_scenario(document)

    def test_a_scenario_the_loaders_refuse_is_refused_with_their_message(self) -> None:
        """The loaders' refusal of a scenario is the import's refusal."""
        document = _with_fleet_distribution(
            pv={"capacity_kw": {"type": "weighted_discrete", "values": [3.0, 5.0]}}
        )

        with pytest.raises(
            ConfigurationError,
            match=re.escape(
                "weighted_discrete distribution for 'fleet_distribution.pv.capacity_kw' "
                "requires 'values' and 'weights'"
            ),
        ):
            fleet_form_from_scenario(document)
