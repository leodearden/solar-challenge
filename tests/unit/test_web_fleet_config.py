# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_config, called directly."""

import re
from collections.abc import Callable

import pytest

pytest.importorskip("flask")

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.fleet_config import (
    MAX_FLEET_HOMES,
    MAX_FLEET_SEED,
    apply_fleet_overlay,
    distribution_form_spec,
    distribution_grammar_spec,
    form_to_fleet_distribution_config,
    sample_distribution,
)
from tests._falsy_json_values import FALSY_NON_NULL_VALUES
from tests._fleet_form import FLEET_FORM_COMPONENT_BLOCKS, valid_distribution_form
from tests._unusable_numbers import UNUSABLE_NON_BOOLEAN_NUMBERS, UNUSABLE_NUMBERS
from tests._whole_number_forms import WHOLE_NUMBER, WHOLE_NUMBER_FORMS

#: Fields of a fleet form block that hold one number: each block's fixed value, sent in its distribution's field, and another block setting.
_SINGLE_NUMBER_FIELDS = [
    pytest.param("pv", "capacity_kw", id="pv-fixed"),
    pytest.param("battery", "capacity_kwh", id="battery-fixed"),
    pytest.param("load", "annual_consumption_kwh", id="load-fixed"),
    pytest.param("pv", "tilt", id="pv-tilt"),
]

#: The keys of a distribution as the distribution editor holds it, each sent in the field x.<key>.
_FIELDS = {key: f"x.{key}" for key in ("type", "mean", "std", "min", "max", "values", "entries")}

#: The keys of the editor's distribution, each mapped to the field the scenario builder sends a PV distribution's in.
_BUILDER_PV_FIELDS = {
    "type": "pv_distribution_type",
    "mean": "pv_mean",
    "std": "pv_std",
    "min": "pv_min",
    "max": "pv_max",
    "values": "pv_wd_values",
    "entries": "pv_sp_entries",
}


def _types(spec: dict[str, object]) -> dict[str, object]:
    """The type of each value of *spec*, a list's as the types of its items."""
    return {
        key: [type(item) for item in value] if isinstance(value, list) else type(value)
        for key, value in spec.items()
    }


def _make_test_homes() -> tuple:
    """Build two HomeConfig instances for overlay tests.

    Returns:
        (home_a, home_b) where home_a has a BatteryConfig and home_b does not.
    """
    pv_a = PVConfig(capacity_kw=4.0)
    pv_b = PVConfig(capacity_kw=3.0)
    load_a = LoadConfig(annual_consumption_kwh=3500.0)
    load_b = LoadConfig(annual_consumption_kwh=2800.0)
    battery_a = BatteryConfig(capacity_kwh=5.0)

    home_a = HomeConfig(pv_config=pv_a, load_config=load_a, battery_config=battery_a)
    home_b = HomeConfig(pv_config=pv_b, load_config=load_b, battery_config=None)
    return home_a, home_b


class TestApplyFleetOverlay:
    """Unit tests for the pure helper apply_fleet_overlay in web/fleet_config.py."""

    def test_tariff_applied_to_all_homes(self) -> None:
        """Passing tariff_config sets tariff_config on every home in the fleet."""
        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)

        result = apply_fleet_overlay([home_a, home_b], tariff_config=tariff)

        assert len(result) == 2
        assert result[0].tariff_config is tariff
        assert result[1].tariff_config is tariff

    def test_dispatch_applied_only_to_homes_with_battery(self) -> None:
        """dispatch_strategy is set on BatteryConfig only when battery_config is not None."""
        home_a, home_b = _make_test_homes()
        dispatch = DispatchStrategyConfig(
            strategy_type="tou_optimized", peak_hours=[(16, 21)]
        )

        result = apply_fleet_overlay([home_a, home_b], dispatch_strategy=dispatch)

        # Home A (has battery) — dispatch_strategy applied
        assert result[0].battery_config is not None
        assert result[0].battery_config.dispatch_strategy is dispatch
        # Home B (no battery) — battery_config stays None, no fabricated battery
        assert result[1].battery_config is None

    def test_seg_tariff_applied_to_all_homes(self) -> None:
        """Passing seg_tariff sets seg_tariff on every home in the fleet."""
        home_a, home_b = _make_test_homes()
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        result = apply_fleet_overlay([home_a, home_b], seg_tariff=seg)

        assert result[0].seg_tariff is seg
        assert result[1].seg_tariff is seg

    def test_original_homes_are_immutable(self) -> None:
        """After the call the original HomeConfig objects are unchanged (frozen dataclass)."""
        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        apply_fleet_overlay([home_a, home_b], tariff_config=tariff, seg_tariff=seg)

        # Originals must be unchanged
        assert home_a.tariff_config is None
        assert home_a.seg_tariff is None
        assert home_b.tariff_config is None
        assert home_b.seg_tariff is None

    def test_all_none_overlay_is_noop(self) -> None:
        """Calling with all None args returns homes that match the inputs field-for-field."""
        home_a, home_b = _make_test_homes()

        result = apply_fleet_overlay([home_a, home_b])

        # Should return the same objects (or equal ones) — no mutations
        assert result[0] is home_a
        assert result[1] is home_b


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
            {"values": [{"value": 3.0, "weight": 50}, {"value": 5.0, "weight": 50}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_shuffled_pool(self) -> None:
        """Test shuffled pool distribution sampling."""
        samples = sample_distribution(
            "shuffled_pool",
            {"entries": [{"value": 3.0, "count": 30}, {"value": 5.0, "count": 70}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_refuses_a_type_the_editor_does_not_offer_naming_type(
        self,
    ) -> None:
        """A preview of a type the distribution editor does not offer is refused naming type, the field that carries it, and the type sent."""
        with pytest.raises(ValueError) as exc_info:
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
                "from its values",
                id="weighted-discrete-without-its-rows",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": None},
                "params.entries must be given: the preview draws a shuffled_pool distribution "
                "from its entries",
                id="shuffled-pool-with-null-entries",
            ),
        ],
    )
    def test_sample_distribution_refuses_params_without_what_its_type_is_drawn_from_naming_the_field(
        self, dist_type: str, params: dict, message: str
    ) -> None:
        """A preview never runs config.py's grammar, so params without a parameter or the rows its type is drawn from, left out or null, are refused naming the field under params, not drawn with an invented default."""
        with pytest.raises(ValueError) as exc_info:
            sample_distribution(dist_type, params, 3)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        ("dist_type", "params", "message"),
        [
            pytest.param(
                "normal", "x", "params must be a mapping, got str", id="normal-str-params"
            ),
            pytest.param(
                "uniform",
                [2.0, 6.0],
                "params must be a mapping, got list",
                id="uniform-list-params",
            ),
            pytest.param(
                "normal", None, "params must be a mapping, got NoneType", id="normal-null-params"
            ),
            pytest.param(
                "weighted_discrete",
                {"values": ["x"]},
                "values[0] must be a mapping, got str",
                id="weighted-discrete-str-row",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": [{"value": 3.0, "count": 1}, 1]},
                "entries[1] must be a mapping, got int",
                id="shuffled-pool-int-row-after-a-valid-one",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": "ab"},
                "values must be a list, got str",
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": {"value": 3.0}},
                "entries must be a list, got dict",
                id="shuffled-pool-object-entries",
            ),
        ],
    )
    def test_sample_distribution_refuses_malformed_params(
        self, dist_type: str, params: object, message: str
    ) -> None:
        """Params that are not a mapping, a row that is not a mapping, or a row list that is not a list, is refused, naming it and the type sent."""
        with pytest.raises(ValueError, match=re.escape(message)):
            sample_distribution(dist_type, params)

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
        with pytest.raises(ValueError) as exc_info:
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
        with pytest.raises(ValueError) as exc_info:
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
            ValueError,
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
                float("inf"), "entries[1].count must be a finite number, got inf", id="infinity"
            ),
            pytest.param(2.5, "entries[1].count must be a whole number, got 2.5", id="fraction"),
            pytest.param(
                1e300,
                f"entries[1].count must be between 0 and {MAX_FLEET_HOMES}, got 1e+300",
                id="huge-float",
            ),
            pytest.param(
                -1,
                f"entries[1].count must be between 0 and {MAX_FLEET_HOMES}, got -1",
                id="negative",
            ),
            pytest.param(
                MAX_FLEET_HOMES - 1,
                f"entries counts must total at most {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="pool-total-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_sample_distribution_refuses_a_shuffled_pool_count_it_cannot_use(
        self, count: float, message: str
    ) -> None:
        """A preview refuses a shuffled_pool count that is not a whole number, a fraction included, or one outside 0 to the dashboard's fleet limit, naming the row's count and the value sent; it refuses a count that takes the pool's total above that limit, naming the total."""
        with pytest.raises(ValueError, match=re.escape(message)):
            sample_distribution(
                "shuffled_pool",
                {"entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": count}]},
            )

    @pytest.mark.parametrize(
        ("dist_type", "params", "message"),
        [
            pytest.param(
                "weighted_discrete",
                {"values": [1]},
                "params.values[0] must be a mapping, got int",
                id="weighted-discrete-int-row",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": "ab"},
                "params.values must be a list, got str",
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                "weighted_discrete",
                {"values": [{"value": 3.0}]},
                "params.values[0] must be a mapping with 'value' and 'weight', got {'value': 3.0}",
                id="weighted-discrete-row-without-its-weight",
            ),
            pytest.param(
                "shuffled_pool",
                {"entries": [{"value": 3.0, "count": float("inf")}]},
                "params.entries[0].count must be a finite number, got inf",
                id="shuffled-pool-infinite-count",
            ),
            pytest.param(
                "shuffled_pool",
                {
                    "entries": [
                        {"value": 3.0, "count": MAX_FLEET_HOMES},
                        {"value": 5.0, "count": 1},
                    ]
                },
                f"params.entries counts must total at most {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="shuffled-pool-total-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_sample_distribution_names_a_row_or_count_refusal_under_params(
        self, dist_type: str, params: dict, message: str
    ) -> None:
        """A preview's malformed row list, row or count is refused naming its field under params, the distribution the preview reads."""
        with pytest.raises(ValueError) as exc_info:
            sample_distribution(dist_type, params, 3)
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
                lambda v: {"values": [{"value": v, "weight": 1}]},
                "params.values[0].value",
                id="weighted-discrete-value",
            ),
            pytest.param(
                "weighted_discrete",
                lambda v: {"values": [{"value": 3.0, "weight": v}]},
                "params.values[0].weight",
                id="weighted-discrete-weight",
            ),
            pytest.param(
                "shuffled_pool",
                lambda v: {"entries": [{"value": v, "count": 2}]},
                "params.entries[0].value",
                id="shuffled-pool-value",
            ),
        ],
    )
    def test_sample_distribution_refuses_a_params_number_that_is_not_finite_naming_it(
        self, dist_type: str, params: Callable[[object], dict], field: str, value: object
    ) -> None:
        """A preview's params number that is not a finite number, a boolean included, is refused naming its field under params and the value sent."""
        with pytest.raises(ValueError) as exc_info:
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
        with pytest.raises(ValueError) as exc_info:
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

    def test_form_to_fleet_distribution_config(self) -> None:
        """Test converting form data to fleet distribution config."""
        form_data = {
            "n_homes": 50,
            "pv": {
                "capacity_kw": {
                    "type": "normal",
                    "mean": 4.0,
                    "std": 1.0,
                    "min": 2.0,
                    "max": 8.0,
                }
            },
            "load": {
                "annual_consumption_kwh": {
                    "type": "uniform",
                    "min": 2000,
                    "max": 5000,
                }
            },
        }
        config = form_to_fleet_distribution_config(form_data)
        assert config["n_homes"] == 50
        assert "pv" in config
        assert "load" in config

    @pytest.mark.parametrize(
        "value",
        [
            *UNUSABLE_NUMBERS,
            pytest.param("x", id="non-numeric-string"),
            pytest.param(None, id="null"),
        ],
    )
    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    def test_form_to_fleet_distribution_config_refuses_an_n_homes_or_seed_that_is_not_a_finite_number(
        self, key: str, value: object
    ) -> None:
        """An n_homes or seed that is not a finite number, a boolean included, is refused, naming the field and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), key: value})
        assert str(exc_info.value) == f"{key} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    def test_form_to_fleet_distribution_config_refuses_an_n_homes_or_seed_with_a_fractional_part(
        self, key: str
    ) -> None:
        """An n_homes or seed with a fractional part is refused, not truncated, naming the field and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), key: 2.5})
        assert str(exc_info.value) == f"{key} must be a whole number, got 2.5"

    @pytest.mark.parametrize("value", WHOLE_NUMBER_FORMS)
    @pytest.mark.parametrize("key", ["n_homes", "seed"])
    def test_form_to_fleet_distribution_config_reads_an_n_homes_or_seed_that_is_a_whole_number_in_another_form_as_the_int_it_equals(
        self, key: str, value: object
    ) -> None:
        """An n_homes or seed that is a whole number sent as a float or a numeric string converts to the int it equals, not to a float or a string."""
        config = form_to_fleet_distribution_config({**valid_distribution_form(), key: value})

        assert (type(config[key]), config[key]) == (int, WHOLE_NUMBER)

    @pytest.mark.parametrize(
        "n_homes",
        [
            pytest.param(0, id="zero"),
            pytest.param(MAX_FLEET_HOMES + 1, id="one-above-the-fleet-limit"),
            pytest.param(1e300, id="huge-float"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_an_n_homes_outside_1_to_max_fleet_homes(
        self, n_homes: object
    ) -> None:
        """An n_homes outside 1 to the dashboard's fleet limit is refused, naming the field, the range and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), "n_homes": n_homes})
        assert str(exc_info.value) == (
            f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {n_homes!r}"
        )

    def test_form_to_fleet_distribution_config_accepts_a_fleet_of_max_fleet_homes(self) -> None:
        """A fleet form may ask for as many homes as a dashboard fleet holds."""
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "n_homes": MAX_FLEET_HOMES}
        )

        assert config["n_homes"] == MAX_FLEET_HOMES

    @pytest.mark.parametrize(
        "seed",
        [
            pytest.param(MAX_FLEET_SEED + 1, id="one-above-the-largest"),
            pytest.param(MAX_FLEET_SEED + 2, id="one-a-float-reads-as-the-one-below"),
            pytest.param(-MAX_FLEET_SEED - 1, id="one-below-the-smallest"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_seed_beyond_max_fleet_seed(
        self, seed: int
    ) -> None:
        """A seed beyond MAX_FLEET_SEED, positive or negative, is refused, not read as the whole number a float rounds it to, naming the field, the range and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), "seed": seed})
        assert str(exc_info.value) == (
            f"seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, got {seed!r}"
        )

    @pytest.mark.parametrize(
        "seed", [pytest.param(MAX_FLEET_SEED, id="largest"), pytest.param(-MAX_FLEET_SEED, id="smallest")]
    )
    def test_form_to_fleet_distribution_config_reads_a_seed_up_to_max_fleet_seed_exactly(
        self, seed: int
    ) -> None:
        """A seed as large as MAX_FLEET_SEED, positive or negative, is read as the int sent."""
        config = form_to_fleet_distribution_config({**valid_distribution_form(), "seed": seed})

        assert config["seed"] == seed

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [
            pytest.param("x", "str", id="str"),
            pytest.param(True, "bool", id="true"),
            pytest.param(3500, "int", id="int"),
            pytest.param([4.0], "list", id="list"),
            *FALSY_NON_NULL_VALUES,
        ],
    )
    @pytest.mark.parametrize("key", FLEET_FORM_COMPONENT_BLOCKS)
    def test_form_to_fleet_distribution_config_refuses_a_non_mapping_component_block(
        self, key: str, value: object, type_name: str
    ) -> None:
        """A pv/battery/load block that is neither null nor a mapping, a falsy one included, is refused, naming the block and the type sent."""
        with pytest.raises(ValueError, match=re.escape(f"{key} must be a mapping, got {type_name}")):
            form_to_fleet_distribution_config({**valid_distribution_form(), key: value})

    @pytest.mark.parametrize(
        "key", [pytest.param(key, id=f"{key}-null") for key in FLEET_FORM_COMPONENT_BLOCKS]
    )
    def test_form_to_fleet_distribution_config_reads_a_null_component_block_as_absent(
        self, key: str
    ) -> None:
        """A null pv/battery/load block converts exactly as if the block were left out."""
        without_block = {k: v for k, v in valid_distribution_form().items() if k != key}
        assert form_to_fleet_distribution_config(
            {**valid_distribution_form(), key: None}
        ) == form_to_fleet_distribution_config(without_block)

    @pytest.mark.parametrize(
        ("block", "primary_field"),
        [
            pytest.param("pv", "capacity_kw", id="pv"),
            pytest.param("battery", "capacity_kwh", id="battery"),
            pytest.param("load", "annual_consumption_kwh", id="load"),
        ],
    )
    def test_form_to_fleet_distribution_config_reads_a_null_distribution_as_absent(
        self, block: str, primary_field: str
    ) -> None:
        """A pv/battery/load block's null distribution converts exactly as if it were left out."""
        form = valid_distribution_form()
        without_distribution = {k: v for k, v in form[block].items() if k != primary_field}
        assert form_to_fleet_distribution_config(
            {**form, block: {**form[block], primary_field: None}}
        ) == form_to_fleet_distribution_config({**form, block: without_distribution})

    @pytest.mark.parametrize(
        ("block", "primary_field", "value"),
        [
            pytest.param(
                "pv",
                "capacity_kw",
                {"type": "normal", "mean": 4.0, "std": 1.0},
                id="pv-normal-without-its-capacity",
            ),
            pytest.param(
                "pv",
                "capacity_kw",
                {"type": "weighted_discrete", "values": [{"value": 4.0, "weight": 1}]},
                id="pv-weighted-discrete-without-its-capacity",
            ),
            pytest.param("pv", "capacity_kw", {"type": "uniform"}, id="pv-type-alone"),
            pytest.param(
                "pv",
                "capacity_kw",
                {"capacity_kw": 4.0, "type": "normal"},
                id="pv-type-beside-its-capacity",
            ),
            pytest.param(
                "battery",
                "capacity_kwh",
                {"type": "uniform", "min": 3.0, "max": 10.0},
                id="battery-uniform-without-its-capacity",
            ),
            pytest.param(
                "load",
                "annual_consumption_kwh",
                {"type": "shuffled_pool", "entries": [{"value": 3500.0, "count": 2}]},
                id="load-shuffled-pool-without-its-consumption",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_component_block_that_is_itself_a_distribution_naming_where_its_distribution_goes(
        self, block: str, primary_field: str, value: dict
    ) -> None:
        """A pv/battery/load block with a type, itself a distribution, is refused whatever else it holds, naming its type and the field its distribution goes in."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), block: value})
        assert str(exc_info.value) == (
            f"{block}.type must be absent: the {block} block's distribution goes in "
            f"{block}.{primary_field}, got {value['type']!r}"
        )

    @pytest.mark.parametrize(
        ("spec", "converted"),
        [
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2}, {"value": 5.0, "weight": 1}],
                },
                {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [2.0, 1.0]},
                id="weighted-discrete",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": 1}],
                },
                {"type": "shuffled_pool", "values": [3.0, 5.0], "counts": [2, 1]},
                id="shuffled-pool",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_converts_distribution_rows(
        self, spec: dict, converted: dict
    ) -> None:
        """A weighted_discrete/shuffled_pool row list converts to parallel value and weight/count lists."""
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
        )
        assert config["pv"] == {"capacity_kw": converted}

    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            pytest.param(
                {"type": "weighted_discrete", "values": ["x"]},
                "values[0] must be a mapping, got str",
                id="weighted-discrete-str-row",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [{"value": 4.0, "weight": 1}, 3500]},
                "values[1] must be a mapping, got int",
                id="weighted-discrete-int-row-after-a-valid-one",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [1]},
                "entries[0] must be a mapping, got int",
                id="shuffled-pool-int-row",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [[4.0, 2]]},
                "entries[0] must be a mapping, got list",
                id="shuffled-pool-list-row",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": "ab"},
                "values must be a list, got str",
                id="weighted-discrete-str-values",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": {"value": 4.0}},
                "values must be a list, got dict",
                id="weighted-discrete-object-values",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_malformed_distribution_rows(
        self, spec: dict, message: str
    ) -> None:
        """A weighted_discrete/shuffled_pool row that is not a mapping, or a row list that is not a list, is refused, naming it and the type sent."""
        with pytest.raises(ValueError, match=re.escape(message)):
            form_to_fleet_distribution_config(
                {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
            )

    @pytest.mark.parametrize(
        ("patch", "block", "key", "converted"),
        [
            pytest.param(
                {"pv": {"capacity_kw": {"type": "normal", "mean": 4.0}}},
                "pv",
                "capacity_kw",
                {"type": "normal", "mean": 4.0},
                id="pv-normal-without-its-std",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "uniform"}}},
                "battery",
                "capacity_kwh",
                {"type": "uniform"},
                id="battery-uniform-without-its-range",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": {"type": "weighted_discrete"}}},
                "load",
                "annual_consumption_kwh",
                {"type": "weighted_discrete"},
                id="load-weighted-discrete-without-its-rows",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": {"type": "shuffled_pool", "entries": None}}},
                "load",
                "annual_consumption_kwh",
                {"type": "shuffled_pool"},
                id="load-shuffled-pool-with-null-entries",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": {"type": "normal", "mean": 20, "std": None}}},
                "pv",
                "tilt",
                {"type": "normal", "mean": 20.0},
                id="pv-tilt-normal-with-a-null-std",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_leaves_a_distributions_absent_or_null_parameter_out_for_the_grammar_to_name(
        self, patch: dict, block: str, key: str, converted: dict
    ) -> None:
        """A distribution's parameter or row list that the form leaves out, or sends as null, is left out of its conversion, not given a default, so config.py's grammar names what is missing."""
        config = form_to_fleet_distribution_config({**valid_distribution_form(), **patch})
        assert config[block][key] == converted

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "weighted_discrete",
                            "values": [{"value": 3.0, "weight": 2}, {"value": 5.0}],
                        }
                    }
                },
                "pv.capacity_kw.values[1] must be a mapping with 'value' and 'weight', "
                "got {'value': 5.0}",
                id="pv-weighted-discrete-row-without-its-weight",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "shuffled_pool", "entries": [{"value": 5.0}]}}},
                "battery.capacity_kwh.entries[0] must be a mapping with 'value' and 'count', "
                "got {'value': 5.0}",
                id="battery-shuffled-pool-row-without-its-count",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": 4.0,
                        "tilt": {"type": "weighted_discrete", "values": [{"weight": 1}]},
                    }
                },
                "pv.tilt.values[0] must be a mapping with 'value' and 'weight', got {'weight': 1}",
                id="pv-tilt-weighted-discrete-row-without-its-value",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_row_without_its_value_or_its_weight_or_count_naming_it(
        self, patch: dict, message: str
    ) -> None:
        """A row's value, weight or count is one of the grammar's parallel lists, so a row cannot leave one out: a row without one is refused naming the row and the row sent, not given a default."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), **patch})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        ("patch", "type_field", "dist_type"),
        [
            pytest.param(
                {"pv": {"capacity_kw": {"type": "fixed", "value": 4}}},
                "pv.capacity_kw.type",
                "fixed",
                id="pv-capacity-fixed",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": 4.0,
                        "tilt": {
                            "type": "proportional_to",
                            "source": "pv.capacity_kw",
                            "multiplier": 2,
                        },
                    }
                },
                "pv.tilt.type",
                "proportional_to",
                id="pv-tilt-proportional-to",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "banana"}}},
                "battery.capacity_kwh.type",
                "banana",
                id="battery-capacity-unknown-type",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_distribution_type_the_editor_does_not_offer_naming_its_type(
        self, patch: dict, type_field: str, dist_type: str
    ) -> None:
        """A distribution, a block's own or another setting's, of a type the fleet page's editor does not offer is refused naming its type field and the type sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), **patch})
        assert str(exc_info.value) == (
            f"{type_field} must be one of normal, uniform, weighted_discrete, shuffled_pool, "
            f"got {dist_type!r}"
        )

    @pytest.mark.parametrize(
        "count",
        [
            *UNUSABLE_NUMBERS,
            pytest.param("x", id="non-numeric-string"),
            pytest.param(None, id="null"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_shuffled_pool_count_that_is_not_a_finite_number(
        self, count: object
    ) -> None:
        """A shuffled_pool count that is not a finite number, a boolean included, is refused, naming the row's count and the value sent."""
        spec = {
            "type": "shuffled_pool",
            "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": count}],
        }
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config(
                {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
            )
        assert str(exc_info.value) == (
            f"pv.capacity_kw.entries[1].count must be a finite number, got {count!r}"
        )

    @pytest.mark.parametrize(
        "count",
        [
            pytest.param(2.5, id="in-range"),
            pytest.param(0.5, id="a-fraction-int-reads-as-zero"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_shuffled_pool_count_with_a_fractional_part(
        self, count: float
    ) -> None:
        """A shuffled_pool count with a fractional part is refused, not truncated, naming the row's count and the value sent."""
        spec = {
            "type": "shuffled_pool",
            "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": count}],
        }
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config(
                {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
            )
        assert str(exc_info.value) == (
            f"pv.capacity_kw.entries[1].count must be a whole number, got {count!r}"
        )

    @pytest.mark.parametrize(
        ("count", "message"),
        [
            pytest.param(
                -1,
                f"entries[1].count must be between 0 and {MAX_FLEET_HOMES}, got -1",
                id="negative",
            ),
            pytest.param(
                MAX_FLEET_HOMES + 1,
                f"entries[1].count must be between 0 and {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="one-above-the-fleet-limit",
            ),
            pytest.param(
                1e300,
                f"entries[1].count must be between 0 and {MAX_FLEET_HOMES}, got 1e+300",
                id="huge-float",
            ),
            pytest.param(
                MAX_FLEET_HOMES - 1,
                f"entries counts must total at most {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="pool-total-one-above-the-fleet-limit",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_shuffled_pool_count_it_cannot_use(
        self, count: object, message: str
    ) -> None:
        """A shuffled_pool count outside 0 to the dashboard's fleet limit is refused, naming the row's count, the range and the value sent; so is a count that takes the pool's total above that limit, naming the total."""
        spec = {
            "type": "shuffled_pool",
            "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": count}],
        }
        with pytest.raises(ValueError, match=re.escape(message)):
            form_to_fleet_distribution_config(
                {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
            )

    def test_form_to_fleet_distribution_config_accepts_shuffled_pool_counts_from_0_to_max_fleet_homes(
        self,
    ) -> None:
        """A shuffled_pool row may assign its value to no home, or to as many homes as a dashboard fleet holds; the pool may total exactly that many values."""
        spec = {
            "type": "shuffled_pool",
            "entries": [{"value": 3.0, "count": 0}, {"value": 5.0, "count": MAX_FLEET_HOMES}],
        }
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
        )

        assert config["pv"]["capacity_kw"]["counts"] == [0, MAX_FLEET_HOMES]

    @pytest.mark.parametrize("count", WHOLE_NUMBER_FORMS)
    def test_form_to_fleet_distribution_config_reads_a_shuffled_pool_count_that_is_a_whole_number_in_another_form_as_the_int_it_equals(
        self, count: object
    ) -> None:
        """A shuffled_pool count that is a whole number sent as a float or a numeric string converts to the int it equals, not to a float or a string."""
        spec = {
            "type": "shuffled_pool",
            "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": count}],
        }
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
        )

        counts = config["pv"]["capacity_kw"]["counts"]
        assert [(type(read), read) for read in counts] == [(int, 2), (int, WHOLE_NUMBER)]

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "weighted_discrete", "values": ["x"]}}},
                "battery.capacity_kwh.values[0] must be a mapping, got str",
                id="battery-weighted-discrete-str-row",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": {"type": "shuffled_pool", "entries": "ab"}}},
                "load.annual_consumption_kwh.entries must be a list, got str",
                id="load-shuffled-pool-str-entries",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "shuffled_pool",
                            "entries": [{"value": 4.0, "count": -1}],
                        }
                    }
                },
                f"pv.capacity_kw.entries[0].count must be between 0 and {MAX_FLEET_HOMES}, got -1",
                id="pv-shuffled-pool-negative-count",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "shuffled_pool",
                            "entries": [{"value": 4.0, "count": "x"}],
                        }
                    }
                },
                "pv.capacity_kw.entries[0].count must be a finite number, got 'x'",
                id="pv-shuffled-pool-str-count",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": {
                            "type": "shuffled_pool",
                            "entries": [
                                {"value": 4.0, "count": MAX_FLEET_HOMES},
                                {"value": 5.0, "count": 1},
                            ],
                        }
                    }
                },
                f"pv.capacity_kw.entries counts must total at most {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="pv-shuffled-pool-total-one-above-the-fleet-limit",
            ),
            pytest.param(
                {
                    "pv": {
                        "capacity_kw": 4.0,
                        "tilt": {"type": "weighted_discrete", "values": ["x"]},
                    }
                },
                "pv.tilt.values[0] must be a mapping, got str",
                id="pv-tilt-distribution-str-row",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_names_a_row_or_count_refusal_by_its_distribution(
        self, patch: dict, message: str
    ) -> None:
        """A malformed row list, row or count is refused naming its distribution's field."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), **patch})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("form_patch", "field"),
        [
            pytest.param(lambda v: {"pv": {"capacity_kw": v}}, "pv.capacity_kw", id="pv-fixed"),
            pytest.param(
                lambda v: {"battery": {"capacity_kwh": v}},
                "battery.capacity_kwh",
                id="battery-fixed",
            ),
            pytest.param(
                lambda v: {"load": {"annual_consumption_kwh": v}},
                "load.annual_consumption_kwh",
                id="load-fixed",
            ),
            pytest.param(
                lambda v: {"pv": {"capacity_kw": {"type": "normal", "mean": v, "std": 1.0}}},
                "pv.capacity_kw.mean",
                id="pv-normal-mean",
            ),
            pytest.param(
                lambda v: {"pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": v}}},
                "pv.capacity_kw.std",
                id="pv-normal-std",
            ),
            pytest.param(
                lambda v: {
                    "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0, "min": v}}
                },
                "pv.capacity_kw.min",
                id="pv-normal-min",
            ),
            pytest.param(
                lambda v: {
                    "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0, "max": v}}
                },
                "pv.capacity_kw.max",
                id="pv-normal-max",
            ),
            pytest.param(
                lambda v: {
                    "battery": {"capacity_kwh": {"type": "uniform", "min": v, "max": 10.0}}
                },
                "battery.capacity_kwh.min",
                id="battery-uniform-min",
            ),
            pytest.param(
                lambda v: {
                    "battery": {"capacity_kwh": {"type": "uniform", "min": 3.0, "max": v}}
                },
                "battery.capacity_kwh.max",
                id="battery-uniform-max",
            ),
            pytest.param(
                lambda v: {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "weighted_discrete",
                            "values": [{"value": 3500.0, "weight": 1}, {"value": v, "weight": 1}],
                        }
                    }
                },
                "load.annual_consumption_kwh.values[1].value",
                id="load-weighted-discrete-value",
            ),
            pytest.param(
                lambda v: {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "weighted_discrete",
                            "values": [
                                {"value": 3500.0, "weight": 1},
                                {"value": 4000.0, "weight": v},
                            ],
                        }
                    }
                },
                "load.annual_consumption_kwh.values[1].weight",
                id="load-weighted-discrete-weight",
            ),
            pytest.param(
                lambda v: {
                    "pv": {
                        "capacity_kw": {
                            "type": "shuffled_pool",
                            "entries": [{"value": v, "count": 2}],
                        }
                    }
                },
                "pv.capacity_kw.entries[0].value",
                id="pv-shuffled-pool-value",
            ),
            pytest.param(
                lambda v: {
                    "pv": {"capacity_kw": 4.0, "tilt": {"type": "normal", "mean": v, "std": 1.0}}
                },
                "pv.tilt.mean",
                id="pv-tilt-distribution-mean",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_distribution_number_that_is_not_finite_naming_it(
        self, form_patch: Callable[[object], dict], field: str, value: object
    ) -> None:
        """A distribution's fixed value, parameter or row number that is not a finite number, a boolean included, is refused naming its field under its distribution's and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), **form_patch(value)})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("value", UNUSABLE_NON_BOOLEAN_NUMBERS)
    @pytest.mark.parametrize(
        ("block", "distribution", "key"),
        [
            pytest.param("pv", {"capacity_kw": 4.0}, "tilt", id="pv-tilt"),
            pytest.param("battery", {"capacity_kwh": 5.0}, "max_charge_kw", id="battery-max-charge"),
            pytest.param(
                "load",
                {"annual_consumption_kwh": 3500.0},
                "household_occupants",
                id="load-household-occupants",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_another_block_setting_that_is_not_finite_naming_it(
        self, block: str, distribution: dict, key: str, value: object
    ) -> None:
        """A block setting other than its distribution that is not a finite number is refused naming <block>.<key> and the value sent."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config(
                {**valid_distribution_form(), block: {**distribution, key: value}}
            )
        assert str(exc_info.value) == f"{block}.{key} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        "strategy",
        [
            pytest.param({"strategy_type": "self_consumption"}, id="mapping"),
            pytest.param({}, id="empty-mapping"),
            pytest.param("self_consumption", id="str"),
            pytest.param(False, id="false"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_a_battery_dispatch_strategy_naming_the_fleets(
        self, strategy: object
    ) -> None:
        """A battery block's own dispatch_strategy, any value but null, is refused naming it and the fleet's dispatch_strategy, which every battery takes."""
        form = valid_distribution_form()
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config(
                {**form, "battery": {**form["battery"], "dispatch_strategy": strategy}}
            )
        assert str(exc_info.value) == (
            "battery.dispatch_strategy must be absent or null: every battery takes the "
            f"fleet's dispatch_strategy, got {strategy!r}"
        )

    @pytest.mark.parametrize(
        ("block", "key", "value"),
        [
            pytest.param("load", "use_stochastic", False, id="load-use-stochastic-false"),
            pytest.param("load", "use_stochastic", True, id="load-use-stochastic-true"),
            pytest.param("pv", "tilt", None, id="pv-tilt-null"),
            pytest.param("battery", "dispatch_strategy", None, id="battery-dispatch-strategy-null"),
        ],
    )
    def test_form_to_fleet_distribution_config_passes_null_and_boolean_block_settings_on_as_given(
        self, block: str, key: str, value: object
    ) -> None:
        """A block setting that is null or a boolean passes on to config.py's grammar as given."""
        form = valid_distribution_form()
        config = form_to_fleet_distribution_config({**form, block: {**form[block], key: value}})
        assert config[block][key] is value

    @pytest.mark.parametrize(
        "value",
        [pytest.param(True, id="true"), pytest.param(False, id="false"), pytest.param(None, id="null")],
    )
    @pytest.mark.parametrize("block", FLEET_FORM_COMPONENT_BLOCKS)
    def test_form_to_fleet_distribution_config_passes_a_blocks_enabled_on_as_given_dropping_no_block(
        self, block: str, value: object
    ) -> None:
        """The fleet form has no toggle for a block: a pv/battery/load block's enabled, true, false or null, is a setting like any other, passed on to config.py's grammar as given beside the block's conversion, and no value of it drops the block."""
        form = valid_distribution_form()
        config = form_to_fleet_distribution_config({**form, block: {**form[block], "enabled": value}})
        assert config.get(block) == {
            **form_to_fleet_distribution_config(form)[block],
            "enabled": value,
        }

    @pytest.mark.parametrize(
        ("block", "key", "spec", "converted"),
        [
            pytest.param(
                "pv",
                "tilt",
                {"type": "normal", "mean": 20.0, "std": 1.0},
                {"type": "normal", "mean": 20.0, "std": 1.0},
                id="pv-tilt-normal",
            ),
            pytest.param(
                "pv",
                "azimuth",
                {"type": "uniform", "min": 150, "max": 210},
                {"type": "uniform", "min": 150.0, "max": 210.0},
                id="pv-azimuth-uniform",
            ),
            pytest.param(
                "battery",
                "max_charge_kw",
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 2.5, "weight": 3}, {"value": 3.6, "weight": 1}],
                },
                {"type": "weighted_discrete", "values": [2.5, 3.6], "weights": [3.0, 1.0]},
                id="battery-max-charge-weighted-discrete",
            ),
            pytest.param(
                "load",
                "household_occupants",
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 2, "count": 1}, {"value": 4, "count": 1}],
                },
                {"type": "shuffled_pool", "values": [2.0, 4.0], "counts": [1, 1]},
                id="load-household-occupants-shuffled-pool",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_converts_a_block_settings_distribution_as_its_own(
        self, block: str, key: str, spec: dict, converted: dict
    ) -> None:
        """A block setting sent as a distribution, a mapping with a type, converts to config.py's grammar as the block's own distribution does."""
        form = valid_distribution_form()
        config = form_to_fleet_distribution_config({**form, block: {**form[block], key: spec}})
        assert config[block].get(key) == converted

    @pytest.mark.parametrize(
        ("block", "key", "value"),
        [
            pytest.param(
                "battery", "grid_charging", {"target_soc_fraction": 0.5}, id="battery-grid-charging"
            ),
            pytest.param("pv", "tilt", {"mean": 20.0}, id="pv-tilt-mapping-without-a-type"),
            pytest.param(
                "pv", "capacity_kw", {"mean": 4.0}, id="pv-capacity-mapping-without-a-type"
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_passes_a_block_setting_mapping_without_a_type_on_as_given(
        self, block: str, key: str, value: dict
    ) -> None:
        """A block setting, the block's distribution included, sent as a mapping without a type passes on to config.py's grammar as given, for the grammar to read or refuse."""
        form = valid_distribution_form()
        config = form_to_fleet_distribution_config({**form, block: {**form[block], key: value}})
        assert config[block].get(key) == value

    @pytest.mark.parametrize(("block", "key"), _SINGLE_NUMBER_FIELDS)
    def test_form_to_fleet_distribution_config_reads_a_numeric_string_fixed_value_or_setting_as_its_number(
        self, block: str, key: str
    ) -> None:
        """A fixed value, like a block's other settings, is read as float() reads it: a numeric string as its number."""
        form = valid_distribution_form()
        config = form_to_fleet_distribution_config({**form, block: {**form[block], key: "4.5"}})
        got = config[block][key]
        assert (type(got), got) == (float, 4.5)

    @pytest.mark.parametrize(
        "value", [pytest.param("abc", id="non-numeric-string"), pytest.param([4.0], id="list")]
    )
    @pytest.mark.parametrize(("block", "key"), _SINGLE_NUMBER_FIELDS)
    def test_form_to_fleet_distribution_config_refuses_a_fixed_value_or_setting_float_cannot_read_naming_it(
        self, block: str, key: str, value: object
    ) -> None:
        """A fixed value, like a block's other settings, that float() cannot read is refused naming <block>.<key> and the value sent."""
        form = valid_distribution_form()
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**form, block: {**form[block], key: value}})
        assert str(exc_info.value) == f"{block}.{key} must be a finite number, got {value!r}"

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(5.5, id="fixed-value"),
            pytest.param(
                {"type": "normal", "mean": 4.0, "std": 1.0, "min": 2.0, "max": 8.0}, id="normal"
            ),
            pytest.param({"type": "uniform", "min": 3.0, "max": 6.0}, id="uniform"),
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2.0}, {"value": 5.0, "weight": 1.0}],
                },
                id="weighted-discrete",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3.0, "count": 2}, {"value": 5.0, "count": 1}],
                },
                id="shuffled-pool",
            ),
        ],
    )
    def test_distribution_form_spec_is_the_inverse_of_the_forms_conversion(
        self, spec: float | dict
    ) -> None:
        """A distribution the fleet page's editor sends, its Fixed Value's number included, converts to config.py's grammar and reads back as itself."""
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
        )

        assert (
            distribution_form_spec(config["pv"]["capacity_kw"], "fleet_distribution.pv.capacity_kw")
            == spec
        )

    @pytest.mark.parametrize(
        ("spec", "number"),
        [
            pytest.param(5.5, 5.5, id="number"),
            pytest.param(3400, 3400.0, id="whole-number"),
            pytest.param({"type": "fixed", "value": 5.5}, 5.5, id="fixed-distribution"),
            pytest.param(
                {"type": "fixed", "value": "5.5"}, 5.5, id="fixed-distribution-numeric-string"
            ),
        ],
    )
    def test_distribution_form_spec_reads_a_fixed_value_as_the_number_the_form_sends(
        self, spec: object, number: float
    ) -> None:
        """A fixed value, which config.py's grammar spells as a number or a fixed distribution, reads as the float the editor's Fixed Value sends, as the form's conversion reads it."""
        got = distribution_form_spec(spec, "fleet_distribution.pv.capacity_kw")
        assert (type(got), got) == (float, number)

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(True, id="boolean"),
            pytest.param(
                {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 2.0},
                id="proportional-to",
            ),
            pytest.param({"type": "normal", "mean": 5.0, "std": 2.0}, id="normal-without-clamps"),
            pytest.param(
                {"type": "normal", "mean": 5.0, "std": 2.0, "min": 0.0}, id="normal-without-max"
            ),
        ],
    )
    def test_distribution_form_spec_refuses_a_distribution_the_editor_cannot_hold(
        self, spec: object
    ) -> None:
        """A boolean, which config.py's grammar reads as 1 or 0 but the form's conversion refuses, a type the editor has no form for, or a normal without both of the clamps the editor always sends is refused, naming its path."""
        with pytest.raises(ValueError, match=re.escape("fleet_distribution.battery.capacity_kwh")):
            distribution_form_spec(spec, "fleet_distribution.battery.capacity_kwh")

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param({"type": "fixed"}, id="no-value"),
            pytest.param({"type": "fixed", "value": True}, id="boolean-value"),
            pytest.param({"type": "fixed", "value": float("inf")}, id="infinite-value"),
            pytest.param({"type": "fixed", "value": "five"}, id="non-numeric-value"),
        ],
    )
    def test_distribution_form_spec_refuses_a_fixed_distribution_without_a_finite_value_naming_its_value(
        self, spec: dict
    ) -> None:
        """A fixed distribution without a value, or whose value is a boolean or not a finite number, is refused naming its value's path and the value sent, not read as some default."""
        with pytest.raises(ValueError) as exc_info:
            distribution_form_spec(spec, "fleet_distribution.battery.capacity_kwh")
        assert str(exc_info.value) == (
            "fleet_distribution.battery.capacity_kwh.value must be a finite number, "
            f"got {spec.get('value')!r}"
        )

    @pytest.mark.parametrize(
        ("spec", "form_spec"),
        [
            pytest.param(
                {"type": "normal", "mean": "4.5", "std": 1.0, "min": 2.0, "max": 8.0},
                {"type": "normal", "mean": 4.5, "std": 1.0, "min": 2.0, "max": 8.0},
                id="normal-numeric-string-mean",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": ["2", 1]},
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2.0}, {"value": 5.0, "weight": 1.0}],
                },
                id="weighted-discrete-numeric-string-weight",
            ),
        ],
    )
    def test_distribution_form_spec_reads_a_numeric_string_as_its_number(
        self, spec: dict, form_spec: dict
    ) -> None:
        """A scenario's numeric string, which the loaders read as its number, reads into the fleet form as that number, as the form's conversion reads it."""
        assert distribution_form_spec(spec, "fleet_distribution.pv.capacity_kw") == form_spec

    def test_distribution_form_spec_refuses_a_number_too_large_for_a_float_naming_it(self) -> None:
        """A scenario's number too large for a float is refused naming its path and the value, not raised as an OverflowError."""
        with pytest.raises(ValueError) as exc_info:
            distribution_form_spec(
                {"type": "uniform", "min": 10**400, "max": 8.0}, "fleet_distribution.pv.capacity_kw"
            )
        assert str(exc_info.value) == (
            f"fleet_distribution.pv.capacity_kw.min must be a finite number, got {10**400!r}"
        )


class TestDistributionGrammarSpec:
    """distribution_grammar_spec, the one writer of an editor distribution in config.py's grammar, called with the field each of its keys is sent in."""

    @pytest.mark.parametrize(
        ("distribution", "spec"),
        [
            pytest.param(
                {"type": "normal", "mean": 4, "std": 1, "min": 2, "max": 8},
                {"type": "normal", "mean": 4.0, "std": 1.0, "min": 2.0, "max": 8.0},
                id="normal",
            ),
            pytest.param(
                {"type": "uniform", "mean": 5, "std": 1, "min": 2, "max": 8},
                {"type": "uniform", "min": 2.0, "max": 8.0},
                id="uniform-beside-the-normals-parameters",
            ),
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3, "weight": 2}, {"value": 5, "weight": 1}],
                },
                {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [2.0, 1.0]},
                id="weighted-discrete",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3, "count": 2}, {"value": 5, "count": 1}],
                },
                {"type": "shuffled_pool", "values": [3.0, 5.0], "counts": [2, 1]},
                id="shuffled-pool",
            ),
        ],
    )
    def test_each_editor_distribution_is_written_as_config_grammar_spells_it(
        self, distribution: dict, spec: dict
    ) -> None:
        """Each of the editor's distributions is written as config.py's grammar spells it: its numbers as floats, a pool's counts as ints, and its rows as parallel lists; a key its type does not read is ignored, as the builder, which sends a normal's parameters beside a uniform's, needs."""
        written = distribution_grammar_spec(distribution, _FIELDS)

        assert written == spec
        assert _types(written) == _types(spec)

    @pytest.mark.parametrize(
        ("distribution", "spec"),
        [
            pytest.param({"type": "normal"}, {"type": "normal"}, id="normal-without-its-parameters"),
            pytest.param(
                {"type": "normal", "mean": 4, "std": None},
                {"type": "normal", "mean": 4.0},
                id="normal-with-a-null-std",
            ),
            pytest.param(
                {"type": "normal", "mean": 4, "std": 1, "min": None, "max": None},
                {"type": "normal", "mean": 4.0, "std": 1.0},
                id="normal-with-null-clamps",
            ),
            pytest.param(
                {"type": "uniform", "min": 2},
                {"type": "uniform", "min": 2.0},
                id="uniform-without-its-max",
            ),
            pytest.param(
                {"type": "weighted_discrete"},
                {"type": "weighted_discrete"},
                id="weighted-discrete-without-its-rows",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": None},
                {"type": "weighted_discrete"},
                id="weighted-discrete-with-null-rows",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": None},
                {"type": "shuffled_pool"},
                id="shuffled-pool-with-null-entries",
            ),
        ],
    )
    def test_a_parameter_or_row_list_left_out_or_null_is_left_out_for_config_grammar_to_name(
        self, distribution: dict, spec: dict
    ) -> None:
        """A parameter or row list the distribution leaves out, or sends as null, is left out of the spec, not given a default, so config.py's grammar names what is missing."""
        assert distribution_grammar_spec(distribution, _FIELDS) == spec

    @pytest.mark.parametrize(
        ("distribution", "message"),
        [
            pytest.param(
                {"type": "weighted_discrete", "values": [{"value": 4, "weight": 1}, {"value": 5}]},
                "x.values[1] must be a mapping with 'value' and 'weight', got {'value': 5}",
                id="weighted-discrete-row-without-its-weight",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [{"weight": 2}]},
                "x.values[0] must be a mapping with 'value' and 'weight', got {'weight': 2}",
                id="weighted-discrete-row-without-its-value",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [{"value": 4}]},
                "x.entries[0] must be a mapping with 'value' and 'count', got {'value': 4}",
                id="shuffled-pool-row-without-its-count",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [{}]},
                "x.entries[0] must be a mapping with 'value' and 'count', got {}",
                id="shuffled-pool-empty-row",
            ),
        ],
    )
    def test_a_row_without_its_value_or_its_weight_or_count_is_refused_naming_the_row(
        self, distribution: dict, message: str
    ) -> None:
        """A row's value and its weight or count each go in one of the grammar's parallel lists, so a row without one is refused naming the row and the row sent."""
        with pytest.raises(ValueError) as exc_info:
            distribution_grammar_spec(distribution, _FIELDS)
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        "distribution",
        [
            pytest.param({"type": "banana"}, id="unknown"),
            pytest.param({"type": "fixed", "value": 4}, id="fixed"),
            pytest.param(
                {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 2},
                id="proportional-to",
            ),
            pytest.param({"type": None}, id="null"),
            pytest.param({"type": ["normal"]}, id="list"),
            pytest.param({"mean": 4, "std": 1}, id="no-type"),
        ],
    )
    def test_a_type_the_editor_does_not_offer_is_refused_naming_its_field(
        self, distribution: dict
    ) -> None:
        """A type the distribution editor does not offer, config.py's grammar's other types included, or a type that is null, not a string or left out, is refused naming the type's field and the type sent."""
        with pytest.raises(ValueError) as exc_info:
            distribution_grammar_spec(distribution, _FIELDS)
        assert str(exc_info.value) == (
            "x.type must be one of normal, uniform, weighted_discrete, shuffled_pool, "
            f"got {distribution.get('type')!r}"
        )

    @pytest.mark.parametrize(
        ("distribution", "message"),
        [
            pytest.param(
                {"type": "normal", "mean": float("inf"), "std": 1},
                "pv_mean must be a finite number, got inf",
                id="parameter",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": "ab"},
                "pv_wd_values must be a list, got str",
                id="row-list",
            ),
            pytest.param(
                {"type": "shuffled_pool", "entries": [3]},
                "pv_sp_entries[0] must be a mapping, got int",
                id="row",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [{"value": 3, "weight": float("nan")}]},
                "pv_wd_values[0].weight must be a finite number, got nan",
                id="row-weight",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3, "count": MAX_FLEET_HOMES}, {"value": 5, "count": 1}],
                },
                f"pv_sp_entries counts must total at most {MAX_FLEET_HOMES}, "
                f"got {MAX_FLEET_HOMES + 1}",
                id="pool-total",
            ),
        ],
    )
    def test_each_refusal_names_the_field_the_form_sends_it_in(
        self, distribution: dict, message: str
    ) -> None:
        """Each refusal names the field the form sends the refused key in, here the scenario builder's flat fields for a PV distribution, with a row's index and cell under its row list's field."""
        with pytest.raises(ValueError) as exc_info:
            distribution_grammar_spec(distribution, _BUILDER_PV_FIELDS)
        assert str(exc_info.value) == message
