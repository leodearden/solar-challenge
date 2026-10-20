# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a fleet_distribution: block and the distribution specs that vary each home's parameters."""

from typing import Any

import pytest

from solar_challenge.config import (
    FleetDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location


def _parsed_fleet_distribution(n_homes: int = 1, **sections: Any) -> FleetDistributionConfig:
    """Parse a ``fleet_distribution:`` block of *n_homes* homes, one unless given, holding *sections*."""
    return parse_fleet_distribution_config({"n_homes": n_homes, **sections})


def _pool_size_refusal(path: str, n_homes: int, total: int) -> str:
    """The refusal of the shuffled pool at *path* whose counts total *total* in a fleet of *n_homes* homes."""
    return (
        f"FleetDistributionConfig: shuffled_pool counts for '{path}' must total n_homes "
        f"({n_homes}), got {total}"
    )


def _charger_type_value_refusal(value: object) -> str:
    """The refusal of *value*, listed in a fleet's ev.charger_type, which names no charger type."""
    return (
        f"Invalid fleet_distribution.ev.charger_type value {value!r}; "
        "valid values: null or one of ['3.6kW', '7kW', '22kW']"
    )


_TWO_VALUE_POOL: dict[str, Any] = {"type": "shuffled_pool", "values": [1.0, 2.0], "counts": [1, 1]}


class TestDistributionDataclasses:
    """Tests for distribution dataclasses."""

    def test_weighted_discrete_basic(self) -> None:
        """Test basic WeightedDiscreteDistribution."""
        dist = WeightedDiscreteDistribution(
            values=(3.0, 4.0, 5.0),
            weights=(20.0, 50.0, 30.0),
        )
        assert dist.values == (3.0, 4.0, 5.0)
        assert dist.weights == (20.0, 50.0, 30.0)

    def test_weighted_discrete_with_none(self) -> None:
        """Test WeightedDiscreteDistribution with None values."""
        dist = WeightedDiscreteDistribution(
            values=(None, 5.0, 10.0),
            weights=(40.0, 40.0, 20.0),
        )
        assert dist.values == (None, 5.0, 10.0)

    def test_weighted_discrete_mismatched_length_raises(self) -> None:
        """Test WeightedDiscreteDistribution with mismatched lengths raises."""
        with pytest.raises(ConfigurationError, match="same length"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(1.0,))

    def test_weighted_discrete_negative_weight_raises(self) -> None:
        """Test WeightedDiscreteDistribution with negative weight raises."""
        with pytest.raises(ConfigurationError, match="negative"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(1.0, -1.0))

    def test_weighted_discrete_all_zero_weights_raises(self) -> None:
        """Test WeightedDiscreteDistribution with all zero weights raises."""
        with pytest.raises(ConfigurationError, match="all be zero"):
            WeightedDiscreteDistribution(values=(1.0, 2.0), weights=(0.0, 0.0))

    def test_normal_distribution_basic(self) -> None:
        """Test basic NormalDistribution."""
        dist = NormalDistribution(mean=3400.0, std=800.0)
        assert dist.mean == 3400.0
        assert dist.std == 800.0
        assert dist.min is None
        assert dist.max is None

    def test_normal_distribution_with_bounds(self) -> None:
        """Test NormalDistribution with bounds."""
        dist = NormalDistribution(mean=3400.0, std=800.0, min=2000.0, max=6000.0)
        assert dist.min == 2000.0
        assert dist.max == 6000.0

    def test_normal_distribution_negative_std_raises(self) -> None:
        """Test NormalDistribution with negative std raises."""
        with pytest.raises(ConfigurationError, match="negative"):
            NormalDistribution(mean=100.0, std=-1.0)

    def test_normal_distribution_invalid_bounds_raises(self) -> None:
        """Test NormalDistribution with min > max raises."""
        with pytest.raises(ConfigurationError, match="greater than max"):
            NormalDistribution(mean=100.0, std=10.0, min=200.0, max=100.0)

    def test_uniform_distribution_basic(self) -> None:
        """Test basic UniformDistribution."""
        dist = UniformDistribution(min=0.0, max=10.0)
        assert dist.min == 0.0
        assert dist.max == 10.0

    def test_uniform_distribution_invalid_bounds_raises(self) -> None:
        """Test UniformDistribution with min > max raises."""
        with pytest.raises(ConfigurationError, match="greater than max"):
            UniformDistribution(min=10.0, max=5.0)

    def test_shuffled_pool_distribution_basic(self) -> None:
        """Test basic ShuffledPoolDistribution."""
        dist = ShuffledPoolDistribution(
            values=(3.0, 4.0, 5.0, 6.0),
            counts=(20, 40, 30, 10),
        )
        assert dist.values == (3.0, 4.0, 5.0, 6.0)
        assert dist.counts == (20, 40, 30, 10)

    def test_shuffled_pool_distribution_with_none(self) -> None:
        """Test ShuffledPoolDistribution with None values."""
        dist = ShuffledPoolDistribution(
            values=(None, 5.0, 10.0),
            counts=(40, 40, 20),
        )
        assert dist.values == (None, 5.0, 10.0)

    def test_shuffled_pool_distribution_create_pool(self) -> None:
        """Test ShuffledPoolDistribution creates correct pool."""
        dist = ShuffledPoolDistribution(
            values=(1.0, 2.0),
            counts=(3, 2),
        )
        pool = dist.create_pool()
        assert len(pool) == 5
        assert pool.count(1.0) == 3
        assert pool.count(2.0) == 2

    def test_shuffled_pool_distribution_mismatched_length_raises(self) -> None:
        """Test ShuffledPoolDistribution with mismatched lengths raises."""
        with pytest.raises(ConfigurationError, match="same length"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(1,))

    def test_shuffled_pool_distribution_negative_count_raises(self) -> None:
        """Test ShuffledPoolDistribution with negative count raises."""
        with pytest.raises(ConfigurationError, match="negative"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(1, -1))

    def test_shuffled_pool_distribution_all_zero_counts_raises(self) -> None:
        """Test ShuffledPoolDistribution with all zero counts raises."""
        with pytest.raises(ConfigurationError, match="all be zero"):
            ShuffledPoolDistribution(values=(1.0, 2.0), counts=(0, 0))


class TestDistributionParsing:
    """The distribution-spec grammar, read as a fleet distribution's pv.capacity_kw."""

    def test_parse_none(self) -> None:
        """Test parsing None value."""
        result = _parsed_fleet_distribution(pv={"capacity_kw": None}).pv.capacity_kw
        assert result is None

    def test_parse_scalar_int(self) -> None:
        """Test parsing scalar int converts to float."""
        result = _parsed_fleet_distribution(pv={"capacity_kw": 5}).pv.capacity_kw
        assert result == 5.0
        assert isinstance(result, float)

    def test_parse_weighted_discrete(self) -> None:
        """Test parsing weighted_discrete distribution."""
        data = {
            "type": "weighted_discrete",
            "values": [3.0, 4.0, 5.0],
            "weights": [20, 50, 30],
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, WeightedDiscreteDistribution)
        assert result.values == (3.0, 4.0, 5.0)
        assert result.weights == (20.0, 50.0, 30.0)

    def test_parse_weighted_discrete_with_null(self) -> None:
        """Test parsing weighted_discrete with null values."""
        data = {
            "type": "weighted_discrete",
            "values": [None, 5.0, 10.0],
            "weights": [40, 40, 20],
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, WeightedDiscreteDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_shuffled_pool(self) -> None:
        """Test parsing shuffled_pool distribution."""
        data = {
            "type": "shuffled_pool",
            "values": [3.0, 4.0, 5.0, 6.0],
            "counts": [20, 40, 30, 10],
        }
        result = _parsed_fleet_distribution(n_homes=100, pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (3.0, 4.0, 5.0, 6.0)
        assert result.counts == (20, 40, 30, 10)

    def test_parse_shuffled_pool_with_null(self) -> None:
        """Test parsing shuffled_pool with null values."""
        data = {
            "type": "shuffled_pool",
            "values": [None, 5.0, 10.0],
            "counts": [40, 40, 20],
        }
        result = _parsed_fleet_distribution(n_homes=100, pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_normal(self) -> None:
        """Test parsing normal distribution."""
        data = {
            "type": "normal",
            "mean": 3400,
            "std": 800,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, NormalDistribution)
        assert result.mean == 3400.0
        assert result.std == 800.0

    def test_parse_normal_with_bounds(self) -> None:
        """Test parsing normal distribution with bounds."""
        data = {
            "type": "normal",
            "mean": 3400,
            "std": 800,
            "min": 2000,
            "max": 6000,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, NormalDistribution)
        assert result.min == 2000.0
        assert result.max == 6000.0

    def test_parse_uniform(self) -> None:
        """Test parsing uniform distribution."""
        data = {
            "type": "uniform",
            "min": 3.0,
            "max": 6.0,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, UniformDistribution)
        assert result.min == 3.0
        assert result.max == 6.0

    def test_parse_fixed(self) -> None:
        """Test parsing fixed distribution (explicit scalar)."""
        data = {
            "type": "fixed",
            "value": 4.5,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert result == 4.5


class TestFleetDistributionConfig:
    """Tests for FleetDistributionConfig parsing."""

    def test_parse_basic_fleet_distribution(self) -> None:
        """Test parsing basic fleet distribution config."""
        data = {
            "n_homes": 10,
            "pv": {
                "capacity_kw": 4.0,
            },
            "load": {},
        }
        config = parse_fleet_distribution_config(data)
        assert config.n_homes == 10
        assert config.pv.capacity_kw == 4.0
        assert config.battery is None

    def test_parse_full_fleet_distribution(self) -> None:
        """Test parsing full fleet distribution config."""
        data = {
            "n_homes": 100,
            "seed": 42,
            "pv": {
                "capacity_kw": {
                    "type": "weighted_discrete",
                    "values": [3.0, 4.0, 5.0],
                    "weights": [30, 50, 20],
                },
                "azimuth": 180,
                "tilt": 35,
            },
            "battery": {
                "capacity_kwh": {
                    "type": "weighted_discrete",
                    "values": [None, 5.0, 10.0],
                    "weights": [40, 40, 20],
                },
            },
            "load": {
                "annual_consumption_kwh": {
                    "type": "normal",
                    "mean": 3400,
                    "std": 800,
                    "min": 2000,
                    "max": 6000,
                },
            },
        }
        config = parse_fleet_distribution_config(data)
        assert config.n_homes == 100
        assert config.seed == 42
        assert isinstance(config.pv.capacity_kw, WeightedDiscreteDistribution)
        assert config.pv.azimuth == 180.0
        assert config.battery is not None
        assert isinstance(config.battery.capacity_kwh, WeightedDiscreteDistribution)
        assert isinstance(config.load.annual_consumption_kwh, NormalDistribution)

    def test_parse_missing_n_homes_raises(self) -> None:
        """Test parsing without n_homes raises."""
        with pytest.raises(ConfigurationError, match="requires 'n_homes'"):
            parse_fleet_distribution_config({"pv": {"capacity_kw": 4.0}})

    def test_parse_missing_pv_raises(self) -> None:
        """Test parsing without pv raises."""
        with pytest.raises(ConfigurationError, match="requires 'pv'"):
            parse_fleet_distribution_config({"n_homes": 10})

    def test_fleet_distribution_config_validation(self) -> None:
        """Test FleetDistributionConfig validation."""
        with pytest.raises(ConfigurationError, match="at least 1"):
            FleetDistributionConfig(
                n_homes=0,
                pv=PVDistributionConfig(capacity_kw=4.0),
                load=LoadDistributionConfig(),
            )


class TestShuffledPoolHoldsOneValuePerHome:
    """A fleet distribution's shuffled pool holds exactly one value per home, so its counts total n_homes."""

    @pytest.mark.parametrize(
        ("n_homes", "values", "counts", "total"),
        [
            pytest.param(100, [3.0, 4.0, 5.0], [20, 40, 30], 90, id="90 values for 100 homes"),
            pytest.param(4, [3.0, 4.0], [50, 50], 100, id="100 values for 4 homes"),
        ],
    )
    def test_a_pool_not_sized_to_n_homes_is_refused_naming_its_path_n_homes_and_its_size(
        self, n_homes: int, values: list[float], counts: list[int], total: int
    ) -> None:
        """A pool short of n_homes would run dry, and one beyond it would leave values undrawn: both are refused."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config(
                {
                    "n_homes": n_homes,
                    "pv": {
                        "capacity_kw": {"type": "shuffled_pool", "values": values, "counts": counts}
                    },
                }
            )
        assert str(refusal.value) == _pool_size_refusal("pv.capacity_kw", n_homes, total)

    @pytest.mark.parametrize(
        ("sections", "path"),
        [
            pytest.param({"pv": {"capacity_kw": 4.0, "tilt": _TWO_VALUE_POOL}}, "pv.tilt", id="pv"),
            pytest.param(
                {"load": {"household_occupants": _TWO_VALUE_POOL}},
                "load.household_occupants",
                id="load",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "max_discharge_kw": _TWO_VALUE_POOL}},
                "battery.max_discharge_kw",
                id="battery",
            ),
            pytest.param(
                {"heat_pump": {"heat_pump_type": "ASHP", "annual_heat_demand_kwh": _TWO_VALUE_POOL}},
                "heat_pump.annual_heat_demand_kwh",
                id="heat_pump",
            ),
            pytest.param(
                {"ev": {"charger_type": {"type": "shuffled_pool", "values": ["7kW"], "counts": [2]}}},
                "ev.charger_type",
                id="ev",
            ),
        ],
    )
    def test_a_pool_not_sized_to_n_homes_is_refused_in_every_component(
        self, sections: dict[str, Any], path: str
    ) -> None:
        """The rule holds for every component's parameters, including those only battery or heat-pump homes draw."""
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config({"n_homes": 3, "pv": {"capacity_kw": 4.0}, **sections})
        assert str(refusal.value) == _pool_size_refusal(path, 3, 2)

    def test_a_fleet_distribution_built_in_code_is_refused_as_a_parsed_one_is(self) -> None:
        """The refusal comes from FleetDistributionConfig itself, not only from the parser."""
        with pytest.raises(ConfigurationError) as refusal:
            FleetDistributionConfig(
                n_homes=3,
                pv=PVDistributionConfig(
                    capacity_kw=ShuffledPoolDistribution(values=(4.0,), counts=(2,))
                ),
                load=LoadDistributionConfig(),
            )
        assert str(refusal.value) == _pool_size_refusal("pv.capacity_kw", 3, 2)

    def test_a_pool_of_exactly_n_homes_values_is_accepted(self) -> None:
        config = parse_fleet_distribution_config(
            {
                "n_homes": 3,
                "pv": {
                    "capacity_kw": {"type": "shuffled_pool", "values": [3.0, 4.0], "counts": [1, 2]}
                },
            }
        )
        assert config.pv.capacity_kw == ShuffledPoolDistribution(values=(3.0, 4.0), counts=(1, 2))


class TestPVDistributionDegradationParsing:
    """parse_fleet_distribution_config threads the pv section's degradation keys into PVDistributionConfig."""

    def test_explicit_keys_are_parsed(self) -> None:
        """system_age_years and degradation_rate_per_year from data reach PVDistributionConfig."""
        data = {
            "capacity_kw": 4.0,
            "system_age_years": 20.0,
            "degradation_rate_per_year": 0.008,
        }
        pv_dist = _parsed_fleet_distribution(pv=data).pv
        assert pv_dist.system_age_years == 20.0
        assert pv_dist.degradation_rate_per_year == 0.008

    def test_defaults_apply_when_keys_omitted(self) -> None:
        """Omitting both keys yields defaults: system_age_years=0.0, degradation_rate_per_year=0.005."""
        data = {"capacity_kw": 4.0}
        pv_dist = _parsed_fleet_distribution(pv=data).pv
        assert pv_dist.system_age_years == 0.0
        assert pv_dist.degradation_rate_per_year == 0.005


class TestEVChargerTypeValuesAreChargerTypes:
    """An ev block's charger_type lists EVChargerType values and nulls, and is read when the block is read, not when homes are generated."""

    @pytest.mark.parametrize(
        ("n_homes", "charger_type", "value"),
        [
            pytest.param(
                1,
                {"type": "weighted_discrete", "values": ["11kW"], "weights": [1]},
                "11kW",
                id="a charger type no charger has",
            ),
            pytest.param(
                3,
                {"type": "shuffled_pool", "values": [None, "7kW", "7KW"], "counts": [1, 1, 1]},
                "7KW",
                id="a charger type in the wrong case",
            ),
            pytest.param(
                1,
                {"type": "weighted_discrete", "values": ["7kW", 22], "weights": [1, 1]},
                22,
                id="a number",
            ),
            pytest.param(
                1,
                {"type": "weighted_discrete", "values": ["7kW", "11kW"], "weights": [1, 0]},
                "11kW",
                id="a value no home draws",
            ),
        ],
    )
    def test_a_listed_value_that_names_no_charger_type_is_refused_at_read_naming_its_key_path_and_value(
        self, n_homes: int, charger_type: dict[str, Any], value: object
    ) -> None:
        """A listed value that is not a charger type is refused as the block is read, naming fleet_distribution.ev.charger_type and the value as written, even when no home draws it."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(
                n_homes, pv={"capacity_kw": 4.0}, ev={"charger_type": charger_type}
            )
        assert str(refusal.value) == _charger_type_value_refusal(value)

    @pytest.mark.parametrize(
        ("charger_type", "expected"),
        [
            pytest.param(
                {
                    "type": "shuffled_pool",
                    "values": [None, "3.6kW", "7kW", "22kW"],
                    "counts": [1, 1, 1, 1],
                },
                sorted(["22kW", "3.6kW", "7kW", "no EV"]),
                id="a pool of every charger type and a null",
            ),
            pytest.param(None, ["no EV"] * 4, id="null"),
        ],
    )
    def test_charger_types_and_nulls_are_read_and_each_home_gets_the_charger_type_it_draws(
        self, charger_type: dict[str, Any] | None, expected: list[str]
    ) -> None:
        """Charger types and nulls pass the read, and each generated home gets the charger type it draws, or no EV for a null."""
        config = _parsed_fleet_distribution(
            4,
            pv={"capacity_kw": 4.0},
            load={"annual_consumption_kwh": 3400.0, "use_stochastic": False},
            ev={"charger_type": charger_type},
        )

        homes = generate_homes_from_distribution(config, Location.bristol())

        assert (
            sorted(home.ev_config.charger_type if home.ev_config else "no EV" for home in homes)
            == expected
        )
