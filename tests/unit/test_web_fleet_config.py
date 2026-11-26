# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_config, called directly."""

import re
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    FleetDistributionConfig,
    parse_fleet_distribution_config,
)
from solar_challenge.number_fields import as_finite_floats, as_whole_numbers
from solar_challenge.scenario_blocks import require_mapping
from solar_challenge.web import fleet_config
from solar_challenge.web.fleet_components import MAX_FLEET_HOMES, MAX_FLEET_SEED
from solar_challenge.web.fleet_config import sample_distribution
from tests._falsy_json_values import FALSY_NON_NULL_VALUES
from tests._fleet_form import FLEET_FORM_COMPONENT_BLOCKS
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests._whole_number_forms import WHOLE_NUMBER, WHOLE_NUMBER_FORMS

class TestFleetConfigHelpers:
    """Tests for fleet_config.py helper functions."""

    def test_sample_distribution_normal(self) -> None:
        """Test normal distribution sampling produces correct count and bounds."""
        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}
        )
        assert len(samples) == 100
        assert all(1.0 <= s <= 8.0 for s in samples)

    def test_sample_distribution_normal_custom_count(self) -> None:
        """Test normal distribution with custom n_samples."""
        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}, n_samples=50
        )
        assert len(samples) == 50

    def test_sample_distribution_uniform(self) -> None:
        """Test uniform distribution sampling produces correct count and bounds."""
        samples = sample_distribution("uniform", {"min": 2.0, "max": 6.0})
        assert len(samples) == 100
        assert all(2.0 <= s <= 6.0 for s in samples)

    def test_sample_distribution_weighted_discrete(self) -> None:
        """Test weighted discrete distribution sampling."""
        samples = sample_distribution(
            "weighted_discrete",
            {"values": [3.0, 5.0], "weights": [50, 50]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_shuffled_pool(self) -> None:
        """Test shuffled pool distribution sampling."""
        samples = sample_distribution(
            "shuffled_pool",
            {"values": [3.0, 5.0], "counts": [30, 70]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_refuses_a_type_the_editor_does_not_offer_naming_type(
        self,
    ) -> None:
        """A preview of a type the distribution editor does not offer is refused naming type, the field that carries it, and the type sent."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution("bogus", {})
        assert str(exc_info.value) == (
            "type must be one of normal, uniform, weighted_discrete, shuffled_pool, got 'bogus'"
        )

    @pytest.mark.parametrize(
        ("dist_type", "params", "message"),
        [
            pytest.param(
                "normal",
                {},
                "params.mean must be given: the preview draws a normal distribution from its "
                "mean and std",
                id="normal-without-its-parameters",
            ),
            pytest.param(
                "normal",
                {"mean": 4},
                "params.std must be given: the preview draws a normal distribution from its "
                "mean and std",
                id="normal-without-its-std",
            ),
            pytest.param(
                "uniform",
                {"max": 3},
                "params.min must be given: the preview draws a uniform distribution from its "
                "min and max",
                id="uniform-without-its-min",
            ),
            pytest.param(
                "weighted_discrete",
                {},
                "params.values must be given: the preview draws a weighted_discrete distribution "
                "from its values and weights",
                id="weighted-discrete-without-its-lists",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": [3.0]},
                "params.weights must be given: the preview draws a weighted_discrete distribution "
                "from its values and weights",
                id="weighted-discrete-without-its-weights",
            ),
            pytest.param(
                "shuffled_pool",
                {"values": None, "counts": [1]},
                "params.values must be given: the preview draws a shuffled_pool distribution "
                "from its values and counts",
                id="shuffled-pool-with-null-values",
            ),
            pytest.param(
                "shuffled_pool",
                {"values": [3.0], "counts": None},
                "params.counts must be given: the preview draws a shuffled_pool distribution "
                "from its values and counts",
                id="shuffled-pool-with-null-counts",
            ),
        ],
    )
    def test_sample_distribution_refuses_params_without_what_its_type_is_drawn_from_naming_the_field(
        self, dist_type: str, params: dict, message: str
    ) -> None:
        """A preview never runs fleet_distribution.py's grammar, so params without a parameter or the rows its type is drawn from, left out or null, are refused naming the field under params, not drawn with an invented default."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution(dist_type, params, 3)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        "params",
        [
            pytest.param("x", id="str-params"),
            pytest.param([2.0, 6.0], id="list-params"),
            pytest.param(None, id="null-params"),
        ],
    )
    def test_sample_distribution_refuses_params_that_are_not_a_mapping_as_require_mapping_refuses_them(
        self, params: object
    ) -> None:
        """Params that are not a mapping are refused by the one 'must be a mapping' rule the scenario grammar's blocks are read by, naming params and the type sent."""
        with pytest.raises(ConfigurationError) as expected:
            require_mapping("params", params)
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution("normal", params)
        assert str(exc_info.value) == str(expected.value)

    @pytest.mark.parametrize(
        ("dist_type", "params", "list_key", "list_reader"),
        [
            pytest.param(
                "weighted_discrete",
                {"values": "ab", "weights": [1]},
                "values",
                as_finite_floats,
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": [3.0], "weights": {"w": 1}},
                "weights",
                as_finite_floats,
                id="weighted-discrete-mapping-weights",
            ),
            pytest.param(
                "shuffled_pool",
                {"values": {"value": 3.0}, "counts": [1]},
                "values",
                as_finite_floats,
                id="shuffled-pool-mapping-values",
            ),
            pytest.param(
                "shuffled_pool",
                {"values": [3.0], "counts": 1},
                "counts",
                as_whole_numbers,
                id="shuffled-pool-int-counts",
            ),
        ],
    )
    def test_sample_distribution_refuses_a_list_that_is_not_a_list_naming_it_under_params(
        self,
        dist_type: str,
        params: dict,
        list_key: str,
        list_reader: Callable[[object, str], object],
    ) -> None:
        """A weighted_discrete's or a shuffled_pool's values, or its paired list, sent as something other than a list is refused as number_fields' list reader of its kind, the one fleet_distribution.py reads the list with, refuses it, naming the list under params."""
        with pytest.raises(ConfigurationError) as expected:
            list_reader(params[list_key], f"params.{list_key}")
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution(dist_type, params, 3)
        assert str(exc_info.value) == str(expected.value)

    @pytest.mark.parametrize(
        ("dist_type", "params", "message"),
        [
            pytest.param(
                "weighted_discrete",
                {"values": [3.0, 5.0], "weights": [1]},
                "params.values and params.weights must have the same length, got 2 and 1",
                id="weighted-discrete-fewer-weights",
            ),
            pytest.param(
                "shuffled_pool",
                {"values": [3.0], "counts": [1, 1]},
                "params.values and params.counts must have the same length, got 1 and 2",
                id="shuffled-pool-more-counts",
            ),
        ],
    )
    def test_sample_distribution_refuses_parallel_lists_of_unequal_length_naming_both(
        self, dist_type: str, params: dict, message: str
    ) -> None:
        """A weighted_discrete's or a shuffled_pool's values and paired list are parallel lists, so lists of unequal length are refused naming both and their lengths."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution(dist_type, params, 3)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        "n_samples",
        [
            *UNUSABLE_NUMBERS,
            pytest.param("x", id="non-numeric-string"),
            pytest.param(None, id="null"),
            pytest.param([100], id="list"),
        ],
    )
    def test_sample_distribution_refuses_an_n_samples_that_is_not_a_finite_number(
        self, n_samples: object
    ) -> None:
        """An n_samples that is not a finite number, a boolean included, is refused, naming n_samples and the value sent."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution("normal", {"mean": 4.0, "std": 1.0}, n_samples)
        assert str(exc_info.value) == f"n_samples must be a finite number, got {n_samples!r}"

    @pytest.mark.parametrize(
        "n_samples",
        [
            pytest.param(2.5, id="in-range"),
            pytest.param(0.5, id="a-fraction-int-reads-as-zero"),
            pytest.param("2.5", id="numeric-string"),
        ],
    )
    def test_sample_distribution_refuses_an_n_samples_with_a_fractional_part(
        self, n_samples: object
    ) -> None:
        """An n_samples with a fractional part is refused, not truncated, naming n_samples and the value sent."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution("normal", {"mean": 4.0, "std": 1.0}, n_samples)
        assert str(exc_info.value) == f"n_samples must be a whole number, got {n_samples!r}"

    @pytest.mark.parametrize(
        "n_samples",
        [
            pytest.param(0, id="zero"),
            pytest.param(-1, id="negative"),
            pytest.param(1e300, id="huge-float"),
            pytest.param(MAX_FLEET_HOMES + 1, id="one-above-the-fleet-limit"),
        ],
    )
    def test_sample_distribution_refuses_an_n_samples_outside_1_to_max_fleet_homes(
        self, n_samples: float
    ) -> None:
        """An n_samples below 1 or above the dashboard's fleet limit is refused, naming n_samples, the range and the value sent."""
        with pytest.raises(
            ConfigurationError,
            match=re.escape(
                f"n_samples must be between 1 and {MAX_FLEET_HOMES}, got {n_samples!r}"
            ),
        ):
            sample_distribution("normal", {"mean": 4.0, "std": 1.0}, n_samples)

    @pytest.mark.parametrize("n_samples", [1, MAX_FLEET_HOMES])
    def test_sample_distribution_draws_n_samples_from_1_to_max_fleet_homes(
        self, n_samples: int
    ) -> None:
        """A preview draws any number of samples from 1 to the dashboard's fleet limit."""
        result = sample_distribution("normal", {"mean": 4.0, "std": 1.0}, n_samples)

        assert len(result) == n_samples

    @pytest.mark.parametrize("n_samples", WHOLE_NUMBER_FORMS)
    def test_sample_distribution_reads_an_n_samples_that_is_a_whole_number_in_another_form_as_the_int_it_equals(
        self, n_samples: object
    ) -> None:
        """An n_samples that is a whole number sent as a float or a numeric string draws the samples the int it equals draws."""
        params = {"mean": 4.0, "std": 1.0}
        assert sample_distribution("normal", params, n_samples) == (
            sample_distribution("normal", params, WHOLE_NUMBER)
        )

    @pytest.mark.parametrize(
        ("count", "message"),
        [
            pytest.param(
                float("inf"), "params.counts[1] must be a finite number, got inf", id="infinity"
            ),
            pytest.param(2.5, "params.counts[1] must be a whole number, got 2.5", id="fraction"),
            pytest.param(
                1e300,
                f"params.counts[1] must be between 0 and {MAX_FLEET_HOMES}, got 1e+300",
                id="huge-float",
            ),
            pytest.param(
                -1,
                f"params.counts[1] must be between 0 and {MAX_FLEET_HOMES}, got -1",
                id="negative",
            ),
            pytest.param(
                MAX_FLEET_HOMES - 1,
                f"params.counts must total at most {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="pool-total-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_sample_distribution_refuses_a_shuffled_pool_count_it_cannot_use(
        self, count: float, message: str
    ) -> None:
        """A preview refuses a shuffled_pool count that is not a whole number, a fraction included, or one outside 0 to the dashboard's fleet limit, naming the count under params and the value sent; it refuses counts that take the pool's total above that limit, naming params.counts and the total."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution("shuffled_pool", {"values": [3.0, 5.0], "counts": [2, count]})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("dist_type", "params", "field"),
        [
            pytest.param(
                "normal", lambda v: {"mean": v, "std": 1.0}, "params.mean", id="normal-mean"
            ),
            pytest.param(
                "normal", lambda v: {"mean": 4.0, "std": v}, "params.std", id="normal-std"
            ),
            pytest.param(
                "normal",
                lambda v: {"mean": 4.0, "std": 1.0, "min": v},
                "params.min",
                id="normal-min",
            ),
            pytest.param(
                "normal",
                lambda v: {"mean": 4.0, "std": 1.0, "max": v},
                "params.max",
                id="normal-max",
            ),
            pytest.param(
                "uniform", lambda v: {"min": v, "max": 6.0}, "params.min", id="uniform-min"
            ),
            pytest.param(
                "uniform", lambda v: {"min": 2.0, "max": v}, "params.max", id="uniform-max"
            ),
            pytest.param(
                "weighted_discrete",
                lambda v: {"values": [3.0, v], "weights": [1, 1]},
                "params.values[1]",
                id="weighted-discrete-value",
            ),
            pytest.param(
                "weighted_discrete",
                lambda v: {"values": [3.0], "weights": [v]},
                "params.weights[0]",
                id="weighted-discrete-weight",
            ),
            pytest.param(
                "shuffled_pool",
                lambda v: {"values": [v], "counts": [2]},
                "params.values[0]",
                id="shuffled-pool-value",
            ),
        ],
    )
    def test_sample_distribution_refuses_a_params_number_that_is_not_finite_naming_it(
        self, dist_type: str, params: Callable[[object], dict], field: str, value: object
    ) -> None:
        """A preview's params number that is not a finite number, a boolean included, is refused naming its field under params and the value sent."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution(dist_type, params(value), 3)
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        ("dist_type", "params", "sample"),
        [
            pytest.param(
                "uniform",
                {"min": -1.7e308, "max": 1.7e308},
                float("inf"),
                id="uniform-range-wider-than-a-float",
            ),
            pytest.param(
                "normal",
                {"mean": 1.7e308, "std": 1e308},
                float("inf"),
                id="normal-drawing-above-the-largest-float",
            ),
            pytest.param(
                "normal",
                {"mean": -1.7e308, "std": 1e308},
                float("-inf"),
                id="normal-drawing-below-the-lowest-float",
            ),
        ],
    )
    def test_sample_distribution_refuses_finite_params_whose_draws_are_not_finite_naming_the_sample(
        self, dist_type: str, params: dict, sample: float
    ) -> None:
        """A preview whose finite params draw a sample a float cannot hold is refused naming params and that sample."""
        with pytest.raises(ConfigurationError) as exc_info:
            sample_distribution(dist_type, params, 100)
        assert str(exc_info.value) == (
            f"params must draw samples that are finite numbers, got a sample of {sample!r}"
        )

    def test_sample_distribution_returns_a_normals_clamped_samples_when_its_draws_overflow(
        self,
    ) -> None:
        """A normal whose draws overflow a float but whose min and max clamp them returns its clamped samples, each a finite number within them."""
        samples = sample_distribution(
            "normal", {"mean": 1.7e308, "std": 1e308, "min": 0.0, "max": 1.0}, 100
        )
        assert len(samples) == 100
        assert all(0.0 <= sample <= 1.0 for sample in samples)


def _grammar_refusal(blocks: dict[str, Any]) -> str:
    """The refusal fleet_distribution.py's grammar gives *blocks*, a dashboard form's fleet blocks, read as a fleet_distribution: block at the form's own paths."""
    with pytest.raises(ConfigurationError) as refused:
        parse_fleet_distribution_config(blocks, block_path="")
    return str(refused.value)


#: A dashboard form's fleet blocks, each component's field a grammar spec.
_FORM_FLEET_BLOCKS: dict[str, Any] = {
    "n_homes": 4,
    "seed": 7,
    "pv": {"capacity_kw": {"type": "shuffled_pool", "values": [3.0, 5.0], "counts": [3, 1]}},
    "battery": {"capacity_kwh": {"type": "weighted_discrete", "values": [None, 5.0], "weights": [1, 3]}},
    "load": {"annual_consumption_kwh": 3500},
}


class TestReadFormFleet:
    """read_form_fleet, the fleet a dashboard form's n_homes, seed and pv, battery and load blocks describe, read as a fleet_distribution: block's are, at the form's own paths, with nothing invented."""

    def test_the_blocks_read_to_the_fleet_the_grammar_reads_at_the_forms_paths(self) -> None:
        """A shuffled pool's values and counts lists, a weighted_discrete's values and weights, and a fixed number read as the grammar reads them."""
        assert fleet_config.read_form_fleet(_FORM_FLEET_BLOCKS) == parse_fleet_distribution_config(
            _FORM_FLEET_BLOCKS, block_path=""
        )

    @pytest.mark.parametrize(
        ("spec", "named"),
        [
            pytest.param({"type": "normal"}, ("pv.capacity_kw", "'mean'", "'std'"), id="E2-normal-without-parameters"),
            pytest.param(
                {"type": "normal", "mean": 4, "std": 1, "min": 9, "max": 2},
                ("pv.capacity_kw", "min cannot be greater than max"),
                id="E6-inverted-clamps",
            ),
            pytest.param(
                {"type": "normal", "mena": 4, "std": 1},
                ("pv.capacity_kw", "mena"),
                id="a-key-the-type-does-not-read",
            ),
        ],
    )
    def test_a_spec_the_grammar_refuses_is_refused_as_the_grammar_refuses_it_naming_the_forms_field(
        self, spec: dict[str, Any], named: tuple[str, ...]
    ) -> None:
        """Nothing is invented for a parameter the spec leaves out: the grammar names it under pv.capacity_kw, the field the page posted."""
        blocks = {**_FORM_FLEET_BLOCKS, "pv": {"capacity_kw": spec}}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == _grammar_refusal(blocks)
        assert all(each in str(refused.value) for each in named)
        assert "fleet_distribution." not in str(refused.value)

    def test_E7_a_pool_too_large_for_its_fleet_is_refused_naming_its_total_and_n_homes(self) -> None:
        """The grammar's F6 refuses the pool before any home is generated: read_form_fleet returns a fleet, never homes."""
        blocks = {
            **_FORM_FLEET_BLOCKS,
            "n_homes": 10,
            "pv": {"capacity_kw": {"type": "shuffled_pool", "values": [4.0], "counts": [10**12]}},
        }
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == _grammar_refusal(blocks)
        assert all(each in str(refused.value) for each in ("pv.capacity_kw", str(10**12), "n_homes (10)"))

    def test_a_battery_block_setting_a_dispatch_strategy_is_refused_naming_it(self) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, "battery": {"capacity_kwh": 5.0, "dispatch_strategy": "tou_optimized"}}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == (
            "battery.dispatch_strategy must be absent or null: every battery takes the "
            "fleet's dispatch_strategy, got 'tou_optimized'"
        )

    def test_a_battery_block_whose_dispatch_strategy_is_null_is_read_as_the_grammar_reads_it(self) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, "battery": {"capacity_kwh": 5.0, "dispatch_strategy": None}}
        assert fleet_config.read_form_fleet(blocks) == parse_fleet_distribution_config(blocks, block_path="")

    @pytest.mark.parametrize(
        ("settings", "message"),
        [
            pytest.param(
                {"n_homes": MAX_FLEET_HOMES + 1},
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="n-homes",
            ),
            pytest.param(
                {"seed": MAX_FLEET_SEED + 1},
                f"seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, got {MAX_FLEET_SEED + 1}",
                id="seed",
            ),
        ],
    )
    def test_a_fleet_the_dashboard_cannot_run_is_refused_naming_its_setting_at_the_forms_path(
        self, settings: dict[str, Any], message: str
    ) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, "pv": {"capacity_kw": 4.0}, **settings}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == message

    def test_a_pv_block_that_is_itself_a_distribution_is_refused_as_the_grammar_refuses_its_keys_naming_pv(
        self,
    ) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, "pv": {"type": "normal", "mean": 4.0, "std": 1.0}}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == _grammar_refusal(blocks)
        assert str(refused.value).startswith("pv")

    @pytest.mark.parametrize(("value", "_type_name"), FALSY_NON_NULL_VALUES)
    @pytest.mark.parametrize("key", FLEET_FORM_COMPONENT_BLOCKS)
    def test_a_component_block_that_is_no_mapping_is_refused_as_the_grammar_refuses_it(
        self, key: str, value: object, _type_name: str
    ) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, key: value}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == _grammar_refusal(blocks)


class TestRefuseAFleetTheDashboardCannotRun:
    """refuse_a_fleet_the_dashboard_cannot_run, the dashboard's bounds on a fleet fleet_distribution.py's grammar has read, called with the path its settings are named under."""

    @staticmethod
    def _fleet(**settings: object) -> FleetDistributionConfig:
        """The fleet fleet_distribution.py's grammar reads from a block with *settings* over 2 homes of 4 kW PV."""
        return parse_fleet_distribution_config({"n_homes": 2, "pv": {"capacity_kw": 4.0}, **settings})

    @pytest.mark.parametrize(
        "settings",
        [
            pytest.param({"n_homes": 1}, id="one-home"),
            pytest.param({"n_homes": MAX_FLEET_HOMES}, id="the-fleet-limit"),
            pytest.param({"seed": MAX_FLEET_SEED}, id="the-largest-seed"),
            pytest.param({"seed": -MAX_FLEET_SEED}, id="the-smallest-seed"),
            pytest.param({"seed": None}, id="no-seed"),
        ],
    )
    def test_a_fleet_within_the_dashboards_bounds_passes(self, settings: dict) -> None:
        """A fleet of 1 to MAX_FLEET_HOMES homes, with a seed from -MAX_FLEET_SEED to MAX_FLEET_SEED or none, is one the dashboard runs."""
        fleet_config.refuse_a_fleet_the_dashboard_cannot_run(self._fleet(**settings), "fleet_distribution")

    @pytest.mark.parametrize(
        ("path", "field"),
        [pytest.param("fleet_distribution", "fleet_distribution.n_homes", id="import"), pytest.param("", "n_homes", id="fleet-form")],
    )
    def test_a_fleet_above_the_fleet_limit_is_refused_naming_n_homes_under_the_path(
        self, path: str, field: str
    ) -> None:
        """A fleet of MAX_FLEET_HOMES + 1 homes is refused naming n_homes under *path*, the range and the size."""
        fleet = self._fleet(n_homes=MAX_FLEET_HOMES + 1)
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_config.refuse_a_fleet_the_dashboard_cannot_run(fleet, path)
        assert str(exc_info.value) == (
            f"{field} must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}"
        )

    @pytest.mark.parametrize("seed", [MAX_FLEET_SEED + 1, -MAX_FLEET_SEED - 1])
    @pytest.mark.parametrize(
        ("path", "field"),
        [pytest.param("fleet_distribution", "fleet_distribution.seed", id="import"), pytest.param("", "seed", id="fleet-form")],
    )
    def test_a_seed_beyond_max_fleet_seed_is_refused_naming_seed_under_the_path(
        self, path: str, field: str, seed: int
    ) -> None:
        """A seed beyond MAX_FLEET_SEED, positive or negative, which the page's JavaScript number cannot hold exactly, is refused naming seed under *path*, the range and the seed."""
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_config.refuse_a_fleet_the_dashboard_cannot_run(self._fleet(seed=seed), path)
        assert str(exc_info.value) == (
            f"{field} must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, got {seed}"
        )
