# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_config, called directly."""

import re

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
    apply_fleet_overlay,
    distribution_form_spec,
    form_to_fleet_distribution_config,
    sample_distribution,
)
from tests._fleet_form import (
    FALSY_NON_NULL_VALUES,
    FLEET_FORM_COMPONENT_BLOCKS,
    valid_distribution_form,
)


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

    def test_sample_distribution_unknown_type_raises(self) -> None:
        """Test that unknown distribution type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown distribution type"):
            sample_distribution("bogus", {})

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
            pytest.param("x", id="str"),
            pytest.param(None, id="null"),
            pytest.param(float("inf"), id="infinity"),
            pytest.param(float("-inf"), id="negative-infinity"),
            pytest.param(float("nan"), id="nan"),
            pytest.param([100], id="list"),
            pytest.param("2.5", id="decimal-str"),
        ],
    )
    def test_sample_distribution_refuses_an_n_samples_int_cannot_read(
        self, n_samples: object
    ) -> None:
        """An n_samples that int() cannot read is refused, naming n_samples and the value sent."""
        with pytest.raises(
            ValueError, match=re.escape(f"n_samples must be an integer, got {n_samples!r}")
        ):
            sample_distribution("normal", {"mean": 4.0, "std": 1.0}, n_samples)

    @pytest.mark.parametrize(
        "n_samples",
        [
            pytest.param(0, id="zero"),
            pytest.param(-1, id="negative"),
            pytest.param(0.5, id="fraction-read-as-zero"),
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

    @pytest.mark.parametrize(
        ("count", "message"),
        [
            pytest.param(
                float("inf"), "entries[1].count must be an integer, got inf", id="infinity"
            ),
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
        """A preview refuses a shuffled_pool count that int() cannot read, or one outside 0 to the dashboard's fleet limit, naming the row's count and the value sent; it refuses a count that takes the pool's total above that limit, naming the total."""
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
                "shuffled_pool",
                {"entries": [{"value": 3.0, "count": float("inf")}]},
                "params.entries[0].count must be an integer, got inf",
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
        ("key", "value", "message"),
        [
            pytest.param(
                "n_homes", float("inf"), "n_homes must be an integer, got inf", id="n_homes-infinity"
            ),
            pytest.param("n_homes", "x", "n_homes must be an integer, got 'x'", id="n_homes-str"),
            pytest.param("n_homes", None, "n_homes must be an integer, got None", id="n_homes-null"),
            pytest.param(
                "n_homes",
                0,
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got 0",
                id="n_homes-zero",
            ),
            pytest.param(
                "n_homes",
                MAX_FLEET_HOMES + 1,
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="n_homes-one-above-the-fleet-limit",
            ),
            pytest.param(
                "n_homes",
                1e300,
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got 1e+300",
                id="n_homes-huge-float",
            ),
            pytest.param("seed", float("inf"), "seed must be an integer, got inf", id="seed-infinity"),
            pytest.param(
                "seed", float("-inf"), "seed must be an integer, got -inf", id="seed-negative-infinity"
            ),
            pytest.param("seed", "x", "seed must be an integer, got 'x'", id="seed-str"),
            pytest.param("seed", None, "seed must be an integer, got None", id="seed-null"),
        ],
    )
    def test_form_to_fleet_distribution_config_refuses_an_n_homes_or_seed_it_cannot_use(
        self, key: str, value: object, message: str
    ) -> None:
        """An n_homes or seed that int() cannot read, or an n_homes outside 1 to the dashboard's fleet limit, is refused, naming the field and the value sent."""
        with pytest.raises(ValueError, match=re.escape(message)):
            form_to_fleet_distribution_config({**valid_distribution_form(), key: value})

    def test_form_to_fleet_distribution_config_accepts_a_fleet_of_max_fleet_homes(self) -> None:
        """A fleet form may ask for as many homes as a dashboard fleet holds."""
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "n_homes": MAX_FLEET_HOMES}
        )

        assert config["n_homes"] == MAX_FLEET_HOMES

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
        ("spec", "converted"),
        [
            pytest.param(
                {
                    "type": "weighted_discrete",
                    "values": [{"value": 3.0, "weight": 2}, {"value": 5.0}],
                },
                {"type": "weighted_discrete", "values": [3.0, 5.0], "weights": [2.0, 1.0]},
                id="weighted-discrete",
            ),
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "entries": [{"value": 3.0, "count": 2}, {"value": 5.0}],
                },
                {"type": "shuffled_pool", "values": [3.0, 5.0], "counts": [2, 1]},
                id="shuffled-pool",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_converts_distribution_rows(
        self, spec: dict, converted: dict
    ) -> None:
        """A weighted_discrete/shuffled_pool row list converts to parallel value and weight/count lists, a missing weight or count reading as 1."""
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
            pytest.param(
                {"type": "shuffled_pool", "entries": None},
                "entries must be a list, got NoneType",
                id="shuffled-pool-null-entries",
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
        ("count", "message"),
        [
            pytest.param(
                float("inf"), "entries[1].count must be an integer, got inf", id="infinity"
            ),
            pytest.param(
                float("-inf"),
                "entries[1].count must be an integer, got -inf",
                id="negative-infinity",
            ),
            pytest.param(float("nan"), "entries[1].count must be an integer, got nan", id="nan"),
            pytest.param("x", "entries[1].count must be an integer, got 'x'", id="str"),
            pytest.param(None, "entries[1].count must be an integer, got None", id="null"),
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
        """A shuffled_pool count that int() cannot read, or one outside 0 to the dashboard's fleet limit, is refused, naming the row's count and the value sent; so is a count that takes the pool's total above that limit, naming the total."""
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
                "pv.capacity_kw.entries[0].count must be an integer, got 'x'",
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
                {"pv": {"type": "weighted_discrete", "values": ["x"]}},
                "pv.values[0] must be a mapping, got str",
                id="pv-block-that-is-the-distribution-str-row",
            ),
        ],
    )
    def test_form_to_fleet_distribution_config_names_a_row_or_count_refusal_by_its_distribution(
        self, patch: dict, message: str
    ) -> None:
        """A malformed row list, row or count is refused naming its distribution's field, which is the block itself when the block is the distribution."""
        with pytest.raises(ValueError) as exc_info:
            form_to_fleet_distribution_config({**valid_distribution_form(), **patch})
        assert str(exc_info.value) == message

    @pytest.mark.parametrize(
        "spec",
        [
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
    def test_distribution_form_spec_is_the_inverse_of_the_forms_conversion(self, spec: dict) -> None:
        """A distribution the fleet page's editor sends converts to config.py's grammar and reads back as itself."""
        config = form_to_fleet_distribution_config(
            {**valid_distribution_form(), "pv": {"capacity_kw": spec}}
        )

        assert (
            distribution_form_spec(config["pv"]["capacity_kw"], "fleet_distribution.pv.capacity_kw")
            == spec
        )

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(5.5, id="fixed-number"),
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
        """A fixed value, a type the editor has no form for, or a normal without both of the clamps the editor always sends is refused, naming its path."""
        with pytest.raises(ValueError, match=re.escape("fleet_distribution.battery.capacity_kwh")):
            distribution_form_spec(spec, "fleet_distribution.battery.capacity_kwh")
