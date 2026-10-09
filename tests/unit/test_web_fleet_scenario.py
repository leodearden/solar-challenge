# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_scenario, called directly with fleet forms: the bodies fleet-simulator.js's buildPayload() posts."""

import re
from datetime import datetime
from typing import Any

import pytest
import yaml

pytest.importorskip("flask")

from solar_challenge.config import ConfigurationError
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES, MAX_FLEET_SEED
from solar_challenge.web.fleet_scenario import (
    ImportedFleetForm,
    fleet_form_from_scenario,
    scenario_from_fleet_form,
)
from solar_challenge.web.shared import resolve_location
from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS
from tests._unusable_numbers import UNUSABLE_NUMBERS

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
            pytest.param(
                {
                    **_FLEET_FORM,
                    "pv": {"capacity_kw": 5.5},
                    "battery": {"capacity_kwh": 5.0},
                    "load": {"annual_consumption_kwh": 3400.0},
                },
                id="fixed-values",
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

    def test_a_period_of_midnight_timestamps_loads_as_its_days(self) -> None:
        """YAML reads `2024-07-01 00:00:00` as a timestamp; at midnight it is that day, which the page's date fields hold as an ISO date."""
        period = yaml.safe_load("start_date: 2024-07-01 00:00:00\nend_date: 2024-07-10 00:00:00\n")
        assert isinstance(period["start_date"], datetime), "premise: YAML reads a timestamp"

        assert fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period}) == ImportedFleetForm(
            form=_FLEET_FORM, not_loaded=()
        )

    @pytest.mark.parametrize("key", ["start_date", "end_date"])
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("2024/07/01", id="slashes"),
            pytest.param("2024-02-30", id="no-such-day"),
            pytest.param("", id="empty-string"),
            pytest.param(20240701, id="number"),
            pytest.param(None, id="null"),
        ],
    )
    def test_a_period_date_that_is_not_an_iso_date_is_refused_naming_it(
        self, key: str, value: object
    ) -> None:
        """A period date that is neither a YAML date nor an ISO 8601 date string (YYYY-MM-DD) is refused with a ValueError naming it as period.<key> and the value as written; the other date is the round trip's."""
        period = {**_FLEET_SCENARIO["period"], key: value}
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period})
        assert str(exc_info.value) == f"period.{key} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}"

    @pytest.mark.parametrize(
        ("period", "message"),
        [
            pytest.param(
                {"start_date": "2024-06-10", "end_date": "2024-06-01"},
                "period.end_date must not be before period.start_date, "
                "got period.start_date '2024-06-10' and period.end_date '2024-06-01'",
                id="end-before-start",
            ),
            pytest.param(
                yaml.safe_load("start_date: 2024-06-10\nend_date: 2024-06-01\n"),
                "period.end_date must not be before period.start_date, "
                "got period.start_date '2024-06-10' and period.end_date '2024-06-01'",
                id="yaml-dates-end-before-start",
            ),
            pytest.param(
                {"start_date": "2024-01-01", "end_date": "2025-12-31"},
                f"period.start_date to period.end_date must span at most {MAX_WINDOW_DAYS} days, "
                "got period.start_date '2024-01-01' and period.end_date '2025-12-31', 731 days",
                id="longer-than-the-page-runs",
            ),
        ],
    )
    def test_a_period_the_page_cannot_run_is_refused_naming_start_date_and_end_date(
        self, period: dict[str, Any], message: str
    ) -> None:
        """A period that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is refused with a ValueError naming the scenario's period.start_date and period.end_date as read."""
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario({**_FLEET_SCENARIO, "period": period})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    @pytest.mark.parametrize(
        "value", [*UNUSABLE_NUMBERS, pytest.param("x", id="non-numeric-string")]
    )
    def test_a_fleet_size_or_seed_that_is_not_a_finite_number_is_refused_naming_it(
        self, key: str, value: object
    ) -> None:
        """An n_homes or seed that is not a finite number, a boolean included, is refused with a ValueError naming it as fleet_distribution.<key> and the value as written."""
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(**{key: value}))
        assert str(exc_info.value) == f"fleet_distribution.{key} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    def test_a_fleet_size_or_seed_with_a_fractional_part_is_refused_naming_it(self, key: str) -> None:
        """An n_homes or seed with a fractional part is refused with a ValueError naming it as fleet_distribution.<key> and the value as written.

        Loading it would run a different fleet: the page runs a whole number of homes, and a seed
        of 2.5 samples another fleet than a seed of 2, since random.Random(2.5) is not
        random.Random(2), while the page has no seed field to show it.
        """
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(**{key: 2.5}))
        assert str(exc_info.value) == f"fleet_distribution.{key} must be a whole number, got 2.5"

    def test_a_seed_the_fleet_page_cannot_hold_exactly_is_refused_naming_it(self) -> None:
        """A seed beyond MAX_FLEET_SEED is refused with a ValueError naming fleet_distribution.seed, the range and the value as written.

        The fleet page holds the seed as a JavaScript number, which reads 2**53 + 1 as 2**53, so
        loading it would run another fleet than the scenario's.
        """
        seed = MAX_FLEET_SEED + 2
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(seed=seed))
        assert str(exc_info.value) == (
            f"fleet_distribution.seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, "
            f"got {seed!r}"
        )

    @pytest.mark.parametrize(
        "n_homes",
        [
            pytest.param(0, id="no-homes"),
            pytest.param(MAX_FLEET_HOMES + 1, id="more-homes-than-the-page-runs"),
        ],
    )
    def test_a_fleet_size_outside_1_to_max_fleet_homes_is_refused_naming_it(self, n_homes: int) -> None:
        """An n_homes outside 1 to the dashboard's fleet limit is refused with a ValueError naming fleet_distribution.n_homes, the range and the value as written."""
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(_with_fleet_distribution(n_homes=n_homes))
        assert str(exc_info.value) == (
            f"fleet_distribution.n_homes must be between 1 and {MAX_FLEET_HOMES}, got {n_homes!r}"
        )

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "fleet_distribution": _without(_FLEET_SCENARIO["fleet_distribution"], "n_homes"),
                },
                id="absent",
            ),
            pytest.param(_with_fleet_distribution(n_homes=None), id="null"),
        ],
    )
    def test_a_fleet_without_a_size_is_refused_naming_fleet_distribution_n_homes(
        self, document: dict[str, Any]
    ) -> None:
        """A fleet_distribution that leaves n_homes out or sets it null is refused with a ValueError naming fleet_distribution.n_homes: a missing size reads as None, as a missing period date does."""
        with pytest.raises(ValueError) as exc_info:
            fleet_form_from_scenario(document)
        assert str(exc_info.value) == "fleet_distribution.n_homes must be a finite number, got None"

    def test_a_fleet_size_and_seed_written_as_whole_floats_load_as_the_ints_they_equal(self) -> None:
        """An n_homes of 3.0 and a seed of 7.0 load as the ints 3 and 7, the fleet they run: random.Random(7.0) draws as random.Random(7) does."""
        imported = fleet_form_from_scenario(_with_fleet_distribution(n_homes=3.0, seed=7.0))

        assert imported == ImportedFleetForm(form=_FLEET_FORM, not_loaded=())
        assert type(imported.form["n_homes"]) is int
        assert type(imported.form["seed"]) is int

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
                {**_FLEET_SCENARIO, "fleet_distribution": [_FLEET_SCENARIO["fleet_distribution"]]},
                "fleet_distribution must be a mapping, got list",
                id="list-fleet-distribution",
            ),
            pytest.param(
                {**_FLEET_SCENARIO, "fleet_distribution": None},
                "fleet_distribution must be a mapping, got NoneType",
                id="null-fleet-distribution",
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
                {
                    **_FLEET_SCENARIO,
                    "period": yaml.safe_load(
                        "start_date: 2024-07-01 12:30:00\nend_date: 2024-07-10\n"
                    ),
                },
                "period.start_date",
                id="a-timestamp-with-a-time-of-day",
            ),
            pytest.param(
                {
                    **_FLEET_SCENARIO,
                    "period": yaml.safe_load(
                        "start_date: 2024-07-01\nend_date: 2024-07-10T00:00:00Z\n"
                    ),
                },
                "period.end_date",
                id="a-timestamp-with-a-time-zone",
            ),
        ],
    )
    def test_a_scenario_the_form_cannot_hold_is_refused(self, document: object, reason: str) -> None:
        """A scenario whose fleet, period, tariff or dispatch the form cannot hold exactly is refused, naming the setting: loading it anyway would run a different fleet."""
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
