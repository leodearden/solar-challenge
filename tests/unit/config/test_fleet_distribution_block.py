# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a fleet_distribution: block and the distribution specs that vary each home's parameters."""

import copy
import dataclasses
import pickle
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from solar_challenge.config import (
    ComponentDistribution,
    FleetDistributionConfig,
    NormalDistribution,
    ProportionalDistribution,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from tests._non_booleans import NON_BOOLEANS


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


def _number_spec_refusal(path: str, spec: object) -> str:
    """The refusal of *spec*, given the number or count field at *path*, whose kind draws no such spec."""
    return (
        f"Invalid {path} {spec!r}; valid specs: null, a number, "
        "or a weighted_discrete, normal, uniform, shuffled_pool or proportional_to of numbers"
    )


def _number_value_refusal(path: str, value: object) -> str:
    """The refusal of *value*, listed in the spec of the number or count field at *path*, which is not a number."""
    return f"Invalid {path} value {value!r}; valid values: null or a number"


def _heat_pump_type_spec_refusal(spec: object) -> str:
    """The refusal of *spec*, given a fleet's heat_pump.heat_pump_type, whose kind draws no such spec."""
    return (
        f"Invalid fleet_distribution.heat_pump.heat_pump_type {spec!r}; "
        "valid specs: null, one of ['ASHP', 'GSHP'], or a weighted_discrete or shuffled_pool of them and nulls"
    )


#: The refusal of 'XSHP', given or listed as a fleet's heat_pump.heat_pump_type, which names no heat pump type.
_XSHP_HEAT_PUMP_TYPE_REFUSAL = (
    "Invalid fleet_distribution.heat_pump.heat_pump_type value 'XSHP'; valid values: null or one of ['ASHP', 'GSHP']"
)


def _proportional_to(source: str, **spec: float) -> dict[str, Any]:
    """A proportional_to spec scaling *source*, with *spec*'s multiplier or offset."""
    return {"type": "proportional_to", "source": source, **spec}


def _source_refusal(path: str, source: str, sources: list[str]) -> str:
    """The refusal of *source*, the source of the proportional_to at *path*, where *sources*, in draw order, are those it may name."""
    return (
        f"Invalid {path} source {source!r}; valid sources: a number or count field drawn earlier "
        f"for every home that draws it, one of {sources!r}"
    )


def _pickle_round_trip(fleet: FleetDistributionConfig) -> FleetDistributionConfig:
    """*fleet* restored from its pickle."""
    clone: FleetDistributionConfig = pickle.loads(pickle.dumps(fleet))
    return clone


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
        result = _parsed_fleet_distribution(pv={"capacity_kw": None}).pv.draws["capacity_kw"]
        assert result is None

    def test_parse_scalar_int(self) -> None:
        """Test parsing scalar int converts to float."""
        result = _parsed_fleet_distribution(pv={"capacity_kw": 5}).pv.draws["capacity_kw"]
        assert result == 5.0
        assert isinstance(result, float)

    def test_parse_weighted_discrete(self) -> None:
        """Test parsing weighted_discrete distribution."""
        data = {
            "type": "weighted_discrete",
            "values": [3.0, 4.0, 5.0],
            "weights": [20, 50, 30],
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
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
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
        assert isinstance(result, WeightedDiscreteDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_shuffled_pool(self) -> None:
        """Test parsing shuffled_pool distribution."""
        data = {
            "type": "shuffled_pool",
            "values": [3.0, 4.0, 5.0, 6.0],
            "counts": [20, 40, 30, 10],
        }
        result = _parsed_fleet_distribution(n_homes=100, pv={"capacity_kw": data}).pv.draws["capacity_kw"]
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
        result = _parsed_fleet_distribution(n_homes=100, pv={"capacity_kw": data}).pv.draws["capacity_kw"]
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_normal(self) -> None:
        """Test parsing normal distribution."""
        data = {
            "type": "normal",
            "mean": 3400,
            "std": 800,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
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
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
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
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
        assert isinstance(result, UniformDistribution)
        assert result.min == 3.0
        assert result.max == 6.0

    def test_parse_fixed(self) -> None:
        """Test parsing fixed distribution (explicit scalar)."""
        data = {
            "type": "fixed",
            "value": 4.5,
        }
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.draws["capacity_kw"]
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
        assert config.pv.draws["capacity_kw"] == 4.0
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
        assert isinstance(config.pv.draws["capacity_kw"], WeightedDiscreteDistribution)
        assert config.pv.draws["azimuth"] == 180.0
        assert config.battery is not None
        assert isinstance(config.battery.draws["capacity_kwh"], WeightedDiscreteDistribution)
        assert isinstance(config.load.draws["annual_consumption_kwh"], NormalDistribution)

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
                pv=ComponentDistribution({"capacity_kw": 4.0}),
            )

    def test_a_dispatch_strategy_no_home_dispatches_by_is_refused(self) -> None:
        """Task 568: the fleet's copy of the home-level dispatch strategy is checked where it is built."""
        with pytest.raises(ConfigurationError) as refused:
            FleetDistributionConfig(
                n_homes=1, pv=ComponentDistribution({"capacity_kw": 4.0}), dispatch_strategy="tou_optimised"
            )

        for named in ["FleetDistributionConfig.dispatch_strategy", "'tou_optimised'", "'greedy'", "'tou_optimized'"]:
            assert named in str(refused.value), (named, str(refused.value))

    @pytest.mark.parametrize("dispatch_strategy", [None, "greedy", "tou_optimized"])
    def test_no_dispatch_strategy_or_one_a_home_dispatches_by_builds(self, dispatch_strategy: str | None) -> None:
        fleet = FleetDistributionConfig(
            n_homes=1, pv=ComponentDistribution({"capacity_kw": 4.0}), dispatch_strategy=dispatch_strategy
        )

        assert fleet.dispatch_strategy == dispatch_strategy


class TestAFleetDistributionIsFrozen:
    """A FleetDistributionConfig is frozen: a changed fleet is a new one, made with dataclasses.replace, which checks it as construction does."""

    @pytest.mark.parametrize("name", [each.name for each in dataclasses.fields(FleetDistributionConfig)])
    def test_assigning_any_field_raises_frozen_instance_error(self, name: str) -> None:
        fleet = FleetDistributionConfig(n_homes=1, pv=ComponentDistribution({"capacity_kw": 4.0}))

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(fleet, name, getattr(fleet, name))

    def test_a_fleet_changed_through_replace_is_refused_as_construction_refuses_it(self) -> None:
        """A 3-home fleet whose pool holds 3 values, grown to 4 homes, is refused in the words building a 4-home fleet with that pool gives."""
        fleet = FleetDistributionConfig(
            n_homes=3,
            pv=ComponentDistribution({"capacity_kw": ShuffledPoolDistribution(values=(4.0,), counts=(3,))}),
        )

        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(fleet, n_homes=4)

        assert str(refusal.value) == _pool_size_refusal("pv.capacity_kw", 4, 3)


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
                pv=ComponentDistribution({
                    "capacity_kw": ShuffledPoolDistribution(values=(4.0,), counts=(2,))
                }),
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
        assert config.pv.draws["capacity_kw"] == ShuffledPoolDistribution(values=(3.0, 4.0), counts=(1, 2))


class TestPVDistributionDegradationParsing:
    """parse_fleet_distribution_config draws the pv section's degradation keys it is given, and draws none it is not."""

    def test_explicit_keys_are_parsed(self) -> None:
        """system_age_years and degradation_rate_per_year from data are drawn as given."""
        data = {
            "capacity_kw": 4.0,
            "system_age_years": 20.0,
            "degradation_rate_per_year": 0.008,
        }
        pv_dist = _parsed_fleet_distribution(pv=data).pv
        assert pv_dist.draws["system_age_years"] == 20.0
        assert pv_dist.draws["degradation_rate_per_year"] == 0.008

    def test_omitted_keys_are_not_drawn(self) -> None:
        """Omitting both keys draws neither, so each home takes PVConfig's default for them."""
        pv_dist = _parsed_fleet_distribution(pv={"capacity_kw": 4.0}).pv
        assert "system_age_years" not in pv_dist.draws
        assert "degradation_rate_per_year" not in pv_dist.draws


class TestPVDistributionModuleEfficiencyDefault:
    """A pv section that sets no module_efficiency draws none, so each home's module keeps its own."""

    def test_a_given_key_is_drawn(self) -> None:
        parsed = parse_fleet_distribution_config({"n_homes": 2, "pv": {"capacity_kw": 4.0, "module_efficiency": 0.2}})

        assert parsed.pv.draws["module_efficiency"] == 0.2

    def test_an_omitted_key_is_not_drawn(self) -> None:
        parsed = parse_fleet_distribution_config({"n_homes": 2, "pv": {"capacity_kw": 4.0}})

        assert "module_efficiency" not in parsed.pv.draws


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
        "charger_type",
        [
            pytest.param(["7kW", "3.6kW"], id="a bare list of charger types"),
            pytest.param(7, id="a number"),
            pytest.param({"type": "fixed", "value": 22}, id="a fixed number"),
            pytest.param({"type": "normal", "mean": 7, "std": 1}, id="normal"),
            pytest.param({"type": "uniform", "min": 3, "max": 22}, id="uniform"),
            pytest.param({"type": "proportional_to", "source": "pv.capacity_kw"}, id="proportional_to"),
        ],
    )
    def test_a_spec_other_than_null_weighted_discrete_or_shuffled_pool_is_refused_at_read_naming_its_key_path(
        self, charger_type: object
    ) -> None:
        """A bare list or number, or a spec that draws numbers, is refused as the block is read, naming fleet_distribution.ev.charger_type, the spec as written and every charger type."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(pv={"capacity_kw": 4.0}, ev={"charger_type": charger_type})
        assert str(refusal.value) == (
            f"Invalid fleet_distribution.ev.charger_type {charger_type!r}; "
            "valid specs: null, one of ['3.6kW', '7kW', '22kW'], "
            "or a weighted_discrete or shuffled_pool of them and nulls"
        )

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


class TestAChoiceIsOneOfItsChoices:
    """A heat_pump_type or charger_type is null, one of its choices given bare, or a weighted_discrete or shuffled_pool of them and nulls, and is read when the block is read."""

    @pytest.mark.parametrize(
        ("component", "key", "value", "read"),
        [
            pytest.param("ev", "charger_type", "7kW", lambda home: home.ev_config.charger_type, id="charger_type"),
            pytest.param(
                "heat_pump",
                "heat_pump_type",
                "GSHP",
                lambda home: home.heat_pump_config.heat_pump_type,
                id="heat_pump_type",
            ),
        ],
    )
    def test_a_bare_choice_gives_every_home_it(
        self, component: str, key: str, value: str, read: Callable[[HomeConfig], str]
    ) -> None:
        config = _parsed_fleet_distribution(3, pv={"capacity_kw": 4.0}, **{component: {key: value}})

        homes = generate_homes_from_distribution(config, Location.bristol())

        assert [read(home) for home in homes] == [value] * 3

    @pytest.mark.parametrize(
        "heat_pump_type",
        [
            pytest.param("XSHP", id="bare"),
            pytest.param({"type": "weighted_discrete", "values": ["ASHP", "XSHP"], "weights": [1, 0]}, id="weighted_discrete"),
        ],
    )
    def test_a_heat_pump_type_outside_heat_pump_types_is_refused_at_read_naming_its_key_path_and_every_type(
        self, heat_pump_type: object
    ) -> None:
        """XSHP is no heat pump type, so the block is refused as it is read, even when no home would draw it."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(pv={"capacity_kw": 4.0}, heat_pump={"heat_pump_type": heat_pump_type})
        assert str(refusal.value) == (
            "Invalid fleet_distribution.heat_pump.heat_pump_type value 'XSHP'; valid values: null or one of ['ASHP', 'GSHP']"
        )


class TestAComponentBlockGivesItsRequiredKeys:
    """A pv block gives capacity_kw, a battery block capacity_kwh and an ev block charger_type, null or not."""

    @pytest.mark.parametrize(
        ("sections", "path"),
        [
            pytest.param({"pv": {"tilt": 30.0}}, "fleet_distribution.pv.capacity_kw", id="pv"),
            pytest.param({"battery": {"max_charge_kw": 3.0}}, "fleet_distribution.battery.capacity_kwh", id="battery"),
            pytest.param({"ev": {"arrival_hour": 18}}, "fleet_distribution.ev.charger_type", id="ev"),
        ],
    )
    def test_a_block_leaving_out_its_required_key_is_refused_naming_its_path(
        self, sections: dict[str, Any], path: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(**{"pv": {"capacity_kw": 4.0}, **sections})
        block_path = path.rsplit(".", 1)[0]
        assert str(refusal.value) == f"Missing required keys in {block_path}: {path}"

    def test_a_null_battery_capacity_is_drawn_as_null_and_gives_no_battery(self) -> None:
        config = _parsed_fleet_distribution(2, pv={"capacity_kw": 4.0}, battery={"capacity_kwh": None})

        assert config.battery is not None
        assert config.battery.draws == {"capacity_kwh": None}
        assert [home.battery_config for home in generate_homes_from_distribution(config, Location.bristol())] == [None, None]


class TestAComponentDistributionHoldsOnlyItsRowsKeysEachInItsPlace:
    """A ComponentDistribution built in code holds only its component's fleet keys, a drawn one in its draws and a SETTING or FLAG in its settings; the fleet is refused as it is built otherwise."""

    @pytest.mark.parametrize(
        ("component", "distribution", "block", "key"),
        [
            pytest.param(
                "pv",
                ComponentDistribution({"capacity_kw": 4.0, "tilts": 10.0}),
                {"capacity_kw": 4.0, "tilts": 10.0},
                "tilts",
                id="a key no row has, in pv's draws",
            ),
            pytest.param(
                "pv",
                ComponentDistribution({"capacity_kw": 4.0}, settings={"name": "x"}),
                {"capacity_kw": 4.0, "name": "x"},
                "name",
                id="a key the fleet grammar leaves out, in pv's settings",
            ),
            pytest.param(
                "battery",
                ComponentDistribution({"capacity_kwh": 5.0, "colour": 1.0}),
                {"capacity_kwh": 5.0, "colour": 1.0},
                "colour",
                id="a key no row has, in battery's draws",
            ),
        ],
    )
    def test_a_key_outside_the_components_fleet_rows_is_refused_as_the_parser_refuses_it(
        self, component: str, distribution: ComponentDistribution, block: dict[str, Any], key: str
    ) -> None:
        """The fleet built in code is refused in the words reading *block* as the component's fleet_distribution: block gives."""
        with pytest.raises(ConfigurationError) as parser_refusal:
            _parsed_fleet_distribution(**{"pv": {"capacity_kw": 4.0}, component: block})
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(
                n_homes=1, **{"pv": ComponentDistribution({"capacity_kw": 4.0}), component: distribution}
            )

        assert str(parser_refusal.value).startswith(f"Unrecognised keys in fleet_distribution.{component}: {key!r};")
        assert str(construction_refusal.value) == str(parser_refusal.value)

    @pytest.mark.parametrize(
        ("components", "refusal"),
        [
            pytest.param(
                {"load": ComponentDistribution({"use_stochastic": False})},
                "fleet_distribution.load.use_stochastic is a flag key, "
                "which a ComponentDistribution holds in its settings, not its draws",
                id="a flag in the draws",
            ),
            pytest.param(
                {"battery": ComponentDistribution({"capacity_kwh": 5.0, "grid_charging": None})},
                "fleet_distribution.battery.grid_charging is a setting key, "
                "which a ComponentDistribution holds in its settings, not its draws",
                id="a setting in the draws",
            ),
            pytest.param(
                {"pv": ComponentDistribution({"capacity_kw": 4.0}, settings={"tilt": 30.0})},
                "fleet_distribution.pv.tilt is a number key, "
                "which a ComponentDistribution holds in its draws, not its settings",
                id="a number in the settings",
            ),
            pytest.param(
                {"pv": ComponentDistribution({"capacity_kw": 4.0, "tilt": 30.0}, settings={"tilt": 30.0})},
                "fleet_distribution.pv.tilt is a number key, "
                "which a ComponentDistribution holds in its draws, not its settings",
                id="a number in both",
            ),
        ],
    )
    def test_a_key_in_the_wrong_one_of_draws_and_settings_is_refused_naming_its_path_and_kind(
        self, components: dict[str, ComponentDistribution], refusal: str
    ) -> None:
        """The fleet is refused as it is built, so no home is drawn with a flag skipped or a key given twice."""
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(n_homes=1, **{"pv": ComponentDistribution({"capacity_kw": 4.0}), **components})

        assert str(construction_refusal.value) == refusal


class TestAComponentDistributionDrawsItsRequiredKeys:
    """A ComponentDistribution built in code draws its component's required key, null or not, as a component block gives it."""

    @pytest.mark.parametrize(
        ("component", "draws", "path"),
        [
            pytest.param("pv", {"tilt": 30.0}, "fleet_distribution.pv.capacity_kw", id="pv"),
            pytest.param("battery", {"max_charge_kw": 3.0}, "fleet_distribution.battery.capacity_kwh", id="battery"),
            pytest.param("ev", {"arrival_hour": 18.0}, "fleet_distribution.ev.charger_type", id="ev"),
        ],
    )
    def test_a_required_key_left_out_of_a_code_built_component_is_refused_as_the_parser_refuses_it(
        self, component: str, draws: dict[str, float], path: str
    ) -> None:
        """The fleet is refused as it is built, naming the key's path, where a battery or EV that drew no presence key was no such component for any home."""
        with pytest.raises(ConfigurationError) as parser_refusal:
            _parsed_fleet_distribution(**{"pv": {"capacity_kw": 4.0}, component: draws})
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(
                n_homes=1, **{"pv": ComponentDistribution({"capacity_kw": 4.0}), component: ComponentDistribution(draws)}
            )

        assert str(parser_refusal.value) == f"Missing required keys in fleet_distribution.{component}: {path}"
        assert str(construction_refusal.value) == str(parser_refusal.value)


class TestASpecIsOneItsFieldsKindDraws:
    """A drawn key's spec is one its field's kind draws, and each value it lists one the kind admits: a number or count field's is no string, a choice field's is one of its choices or null; the fleet is refused otherwise, naming the key's path, as the block is read or the fleet is built."""

    @pytest.mark.parametrize(
        ("sections", "path", "value"),
        [
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": {"type": "weighted_discrete", "values": [30, "35"], "weights": [1, 1]}}},
                "fleet_distribution.pv.tilt",
                "35",
                id="a string among a number's weighted values",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": {"type": "shuffled_pool", "values": ["30"], "counts": [1]}}},
                "fleet_distribution.pv.tilt",
                "30",
                id="a string in a number's pool",
            ),
            pytest.param(
                {
                    "pv": {"capacity_kw": 4.0},
                    "load": {"household_occupants": {"type": "weighted_discrete", "values": ["2"], "weights": [1]}},
                },
                "fleet_distribution.load.household_occupants",
                "2",
                id="a string among a count's weighted values",
            ),
        ],
    )
    def test_a_string_among_a_number_fields_values_is_refused_at_read_naming_its_path_and_the_value(
        self, sections: dict[str, Any], path: str, value: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(**sections)

        assert str(refusal.value) == _number_value_refusal(path, value)

    @pytest.mark.parametrize(
        ("tilt", "refusal"),
        [
            pytest.param("30", _number_spec_refusal("fleet_distribution.pv.tilt", "30"), id="a string"),
            pytest.param(
                WeightedDiscreteDistribution(values=(30.0, "35"), weights=(1.0, 1.0)),
                _number_value_refusal("fleet_distribution.pv.tilt", "35"),
                id="a string among weighted values",
            ),
        ],
    )
    def test_a_number_field_given_a_spec_its_kind_does_not_draw_is_refused_at_construction(
        self, tilt: object, refusal: str
    ) -> None:
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(n_homes=1, pv=ComponentDistribution({"capacity_kw": 4.0, "tilt": tilt}))

        assert str(construction_refusal.value) == refusal

    _A_NORMAL = NormalDistribution(mean=1.0, std=0.1)
    _A_PROPORTIONAL_TO = ProportionalDistribution(source="pv.capacity_kw")

    @pytest.mark.parametrize(
        ("components", "refusal"),
        [
            pytest.param(
                {"heat_pump": ComponentDistribution({"heat_pump_type": _A_NORMAL})},
                _heat_pump_type_spec_refusal(_A_NORMAL),
                id="a normal on a heat pump type",
            ),
            pytest.param(
                {"ev": ComponentDistribution({"charger_type": _A_PROPORTIONAL_TO})},
                f"Invalid fleet_distribution.ev.charger_type {_A_PROPORTIONAL_TO!r}; "
                "valid specs: null, one of ['3.6kW', '7kW', '22kW'], "
                "or a weighted_discrete or shuffled_pool of them and nulls",
                id="a proportional_to on a charger type",
            ),
            pytest.param(
                {"heat_pump": ComponentDistribution({"heat_pump_type": "XSHP"})},
                _XSHP_HEAT_PUMP_TYPE_REFUSAL,
                id="a bare heat pump type outside its choices",
            ),
            pytest.param(
                {
                    "heat_pump": ComponentDistribution(
                        {"heat_pump_type": WeightedDiscreteDistribution(values=("ASHP", "XSHP"), weights=(1.0, 0.0))}
                    )
                },
                _XSHP_HEAT_PUMP_TYPE_REFUSAL,
                id="a listed heat pump type outside its choices that no home draws",
            ),
        ],
    )
    def test_a_choice_field_given_a_spec_or_value_its_kind_does_not_draw_is_refused_at_construction(
        self, components: dict[str, ComponentDistribution], refusal: str
    ) -> None:
        """A fleet built in code is refused in the words the parser refuses such a block with."""
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(n_homes=1, **{"pv": ComponentDistribution({"capacity_kw": 4.0}), **components})

        assert str(construction_refusal.value) == refusal


class TestAProportionalToSourceIsDrawnEarlierForEveryHomeThatDrawsIt:
    """A proportional_to's source is a number or count field drawn earlier for every home that draws the dependent: one pv or load draws, or one the dependent's own component draws before it; the fleet is refused otherwise as it is read, whatever it draws."""

    @pytest.mark.parametrize(
        ("sections", "path", "source", "sources"),
        [
            pytest.param(
                {"battery": {"capacity_kwh": _proportional_to("pv.capacity")}},
                "fleet_distribution.battery.capacity_kwh",
                "pv.capacity",
                ["pv.capacity_kw"],
                id="a path no field has",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "azimuth": _proportional_to("pv.tilt"), "tilt": 30}},
                "fleet_distribution.pv.azimuth",
                "pv.tilt",
                ["pv.capacity_kw"],
                id="a later field of the same component",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": _proportional_to("battery.capacity_kwh")}, "battery": {"capacity_kwh": 5.0}},
                "fleet_distribution.pv.tilt",
                "battery.capacity_kwh",
                ["pv.capacity_kw"],
                id="a later component",
            ),
            pytest.param(
                {
                    "battery": {"capacity_kwh": 5.0, "max_charge_kw": 2.0},
                    "heat_pump": {"heat_pump_type": "ASHP", "thermal_capacity_kw": _proportional_to("battery.max_charge_kw")},
                },
                "fleet_distribution.heat_pump.thermal_capacity_kw",
                "battery.max_charge_kw",
                ["pv.capacity_kw"],
                id="another optional component, though every home has it",
            ),
            pytest.param(
                {"heat_pump": {"heat_pump_type": "ASHP", "thermal_capacity_kw": _proportional_to("heat_pump.heat_pump_type")}},
                "fleet_distribution.heat_pump.thermal_capacity_kw",
                "heat_pump.heat_pump_type",
                ["pv.capacity_kw"],
                id="a choice",
            ),
            pytest.param(
                {
                    "load": {"use_stochastic": False},
                    "heat_pump": {"heat_pump_type": "ASHP", "thermal_capacity_kw": _proportional_to("load.use_stochastic")},
                },
                "fleet_distribution.heat_pump.thermal_capacity_kw",
                "load.use_stochastic",
                ["pv.capacity_kw"],
                id="a flag",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": _proportional_to("pv.azimuth")}},
                "fleet_distribution.pv.tilt",
                "pv.azimuth",
                ["pv.capacity_kw"],
                id="a field the fleet does not draw",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": _proportional_to("pv.tilt")}},
                "fleet_distribution.pv.tilt",
                "pv.tilt",
                ["pv.capacity_kw"],
                id="itself",
            ),
            pytest.param(
                {
                    "pv": {"capacity_kw": 4.0, "tilt": 30.0},
                    "load": {"annual_consumption_kwh": 3400.0, "household_occupants": 3},
                    "ev": {"charger_type": "7kW", "arrival_hour": _proportional_to("ev.departure_hour"), "departure_hour": 8},
                },
                "fleet_distribution.ev.arrival_hour",
                "ev.departure_hour",
                ["pv.capacity_kw", "pv.tilt", "load.annual_consumption_kwh", "load.household_occupants"],
                id="a later field of its own component, beside the fields drawn earlier for every home",
            ),
        ],
    )
    def test_a_source_not_drawn_earlier_for_every_home_is_refused_at_read_naming_the_path_the_source_and_the_valid_sources(
        self, sections: dict[str, Any], path: str, source: str, sources: list[str]
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(2, **{"pv": {"capacity_kw": 4.0}, **sections})

        assert str(refusal.value) == _source_refusal(path, source, sources)

    def test_a_code_built_fleet_is_refused_as_a_parsed_one_is(self) -> None:
        with pytest.raises(ConfigurationError) as parser_refusal:
            _parsed_fleet_distribution(
                2, pv={"capacity_kw": 4.0}, battery={"capacity_kwh": _proportional_to("pv.capacity")}
            )
        with pytest.raises(ConfigurationError) as construction_refusal:
            FleetDistributionConfig(
                n_homes=2,
                pv=ComponentDistribution({"capacity_kw": 4.0}),
                battery=ComponentDistribution({"capacity_kwh": ProportionalDistribution(source="pv.capacity")}),
            )

        assert str(construction_refusal.value) == str(parser_refusal.value)

    @pytest.mark.parametrize(
        ("sections", "read", "expected"),
        [
            pytest.param(
                {"battery": {"capacity_kwh": _proportional_to("pv.capacity_kw", multiplier=2.0)}},
                lambda home: home.battery_config.capacity_kwh,
                8.0,
                id="battery.capacity_kwh from pv.capacity_kw",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "max_charge_kw": _proportional_to("battery.capacity_kwh", multiplier=0.5)}},
                lambda home: home.battery_config.max_charge_kw,
                2.5,
                id="battery.max_charge_kw from battery.capacity_kwh",
            ),
            pytest.param(
                {
                    "load": {"annual_consumption_kwh": 3600.0},
                    "heat_pump": {
                        "heat_pump_type": "ASHP",
                        "thermal_capacity_kw": _proportional_to("load.annual_consumption_kwh", multiplier=0.002),
                    },
                },
                lambda home: home.heat_pump_config.thermal_capacity_kw,
                7.2,
                id="heat_pump.thermal_capacity_kw from load.annual_consumption_kwh",
            ),
            pytest.param(
                {"load": {"household_occupants": _proportional_to("pv.capacity_kw", multiplier=0.75)}},
                lambda home: home.load_config.household_occupants,
                3,
                id="load.household_occupants from pv.capacity_kw",
            ),
            pytest.param(
                {
                    "load": {"annual_consumption_kwh": 3600.0},
                    "ev": {"charger_type": "7kW", "arrival_hour": _proportional_to("load.annual_consumption_kwh", multiplier=0.005)},
                },
                lambda home: home.ev_config.arrival_hour,
                18,
                id="ev.arrival_hour from load.annual_consumption_kwh",
            ),
        ],
    )
    def test_a_source_drawn_earlier_for_every_home_that_draws_it_is_accepted(
        self, sections: dict[str, Any], read: Callable[[HomeConfig], object], expected: object
    ) -> None:
        """Each home's value is the multiplier times the value it drew earlier for the source."""
        fleet = _parsed_fleet_distribution(2, **{"pv": {"capacity_kw": 4.0}, **sections})

        homes = generate_homes_from_distribution(fleet, Location.bristol())

        assert [read(home) for home in homes] == [expected, expected]


class TestANullSettingReadsAsAbsent:
    """A setting given null in a fleet's component block reads as the block without it."""

    @pytest.mark.parametrize(
        ("component", "block"),
        [
            pytest.param("load", {"annual_consumption_kwh": 3400.0}, id="load.use_stochastic"),
            pytest.param("ev", {"charger_type": "7kW"}, id="ev.smart_charging_mode"),
        ],
    )
    def test_a_null_setting_parses_as_the_block_without_it(self, component: str, block: dict[str, Any]) -> None:
        setting = {"load": "use_stochastic", "ev": "smart_charging_mode"}[component]

        with_null = _parsed_fleet_distribution(pv={"capacity_kw": 4.0}, **{component: {**block, setting: None}})

        assert with_null == _parsed_fleet_distribution(pv={"capacity_kw": 4.0}, **{component: block})


class TestUseStochasticIsTrueOrFalse:
    """A fleet's load.use_stochastic is a flag: true or false, read when the block is read and given to every home; null reads as absent, the default true."""

    @pytest.mark.parametrize("value", NON_BOOLEANS)
    def test_a_value_that_is_not_a_bool_is_refused_at_read_naming_its_key_path(self, value: object) -> None:
        """The refusal comes from parsing the block; no home is generated."""
        with pytest.raises(ConfigurationError) as refusal:
            _parsed_fleet_distribution(
                pv={"capacity_kw": 4.0}, load={"annual_consumption_kwh": 3400.0, "use_stochastic": value}
            )
        assert str(refusal.value) == f"fleet_distribution.load.use_stochastic must be true or false, got {value!r}"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(True, True, id="true"),
            pytest.param(False, False, id="false"),
            pytest.param(np.False_, False, id="numpy-false"),
            pytest.param(None, True, id="null"),
        ],
    )
    def test_each_home_is_given_the_flag_as_the_python_bool(self, value: object, expected: bool) -> None:
        config = _parsed_fleet_distribution(
            2, pv={"capacity_kw": 4.0}, load={"annual_consumption_kwh": 3400.0, "use_stochastic": value}
        )

        flags = [home.load_config.use_stochastic for home in generate_homes_from_distribution(config, Location.bristol())]

        assert flags == [expected, expected]
        assert all(type(flag) is bool for flag in flags)


class TestAFleetDistributionPicklesAndDeepCopies:
    """A pickled or deep-copied fleet distribution rebuilds each ComponentDistribution through its constructor, so the copy equals the fleet and its components hold their draws and settings read-only."""

    @pytest.fixture
    def fleet(self) -> FleetDistributionConfig:
        """Every component, drawing pooled, fixed and chosen values, with bool, grid-charging and dispatch-strategy settings."""
        return _parsed_fleet_distribution(
            2,
            seed=7,
            pv={"capacity_kw": {"type": "shuffled_pool", "values": [3.0, 4.0], "counts": [1, 1]}, "tilt": 30},
            load={"annual_consumption_kwh": 3400, "use_stochastic": False},
            battery={
                "capacity_kwh": 5.0,
                "grid_charging": {"target_soc_fraction": 0.9},
                "dispatch_strategy": {"strategy_type": "self_consumption"},
            },
            heat_pump={"heat_pump_type": {"type": "weighted_discrete", "values": ["ASHP", None], "weights": [1, 1]}},
            ev={"charger_type": "7kW", "arrival_hour": 18},
        )

    @pytest.mark.parametrize("copied", [_pickle_round_trip, copy.deepcopy], ids=["pickled", "deep-copied"])
    def test_the_copy_equals_the_fleet(
        self, fleet: FleetDistributionConfig, copied: Callable[[FleetDistributionConfig], FleetDistributionConfig]
    ) -> None:
        assert copied(fleet) == fleet

    @pytest.mark.parametrize("copied", [_pickle_round_trip, copy.deepcopy], ids=["pickled", "deep-copied"])
    @pytest.mark.parametrize(
        "component_of",
        [
            pytest.param(lambda fleet: fleet.pv, id="pv"),
            pytest.param(lambda fleet: fleet.load, id="load"),
            pytest.param(lambda fleet: fleet.battery, id="battery"),
            pytest.param(lambda fleet: fleet.heat_pump, id="heat_pump"),
            pytest.param(lambda fleet: fleet.ev, id="ev"),
        ],
    )
    def test_each_component_of_the_copy_holds_its_draws_and_settings_read_only(
        self,
        fleet: FleetDistributionConfig,
        copied: Callable[[FleetDistributionConfig], FleetDistributionConfig],
        component_of: Callable[[FleetDistributionConfig], ComponentDistribution | None],
    ) -> None:
        """Assigning a key in the copied component's draws, or in its settings, raises TypeError."""
        component = component_of(copied(fleet))

        assert component is not None
        with pytest.raises(TypeError):
            component.draws["added"] = None
        with pytest.raises(TypeError):
            component.settings["added"] = None
