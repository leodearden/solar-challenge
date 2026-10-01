# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a fleet_distribution: block and the distribution specs that vary each home's parameters."""

from typing import Any

import pytest

from solar_challenge.config import (
    ConfigurationError,
    FleetDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    parse_fleet_distribution_config,
)


def _parsed_fleet_distribution(**sections: Any) -> FleetDistributionConfig:
    """Parse a one-home ``fleet_distribution:`` block holding *sections*."""
    return parse_fleet_distribution_config({"n_homes": 1, **sections})


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
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
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
        result = _parsed_fleet_distribution(pv={"capacity_kw": data}).pv.capacity_kw
        assert isinstance(result, ShuffledPoolDistribution)
        assert result.values == (None, 5.0, 10.0)

    def test_parse_shuffled_pool_missing_counts_raises(self) -> None:
        """Test parsing shuffled_pool without counts raises."""
        with pytest.raises(ConfigurationError, match="requires 'values' and 'counts'"):
            _parsed_fleet_distribution(
                pv={"capacity_kw": {"type": "shuffled_pool", "values": [1, 2, 3]}}
            )

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

    def test_parse_missing_type_raises(self) -> None:
        """Test parsing dict without type raises error."""
        with pytest.raises(ConfigurationError, match="requires 'type'"):
            _parsed_fleet_distribution(pv={"capacity_kw": {"values": [1, 2, 3]}})

    def test_parse_unknown_type_raises(self) -> None:
        """Test parsing unknown type raises error."""
        with pytest.raises(ConfigurationError, match="Unknown distribution type"):
            _parsed_fleet_distribution(pv={"capacity_kw": {"type": "unknown"}})

    def test_parse_weighted_discrete_missing_values_raises(self) -> None:
        """Test parsing weighted_discrete without values raises."""
        with pytest.raises(ConfigurationError, match="requires 'values' and 'weights'"):
            _parsed_fleet_distribution(
                pv={"capacity_kw": {"type": "weighted_discrete", "weights": [1, 2]}}
            )

    def test_parse_normal_missing_std_raises(self) -> None:
        """Test parsing normal without std raises."""
        with pytest.raises(ConfigurationError, match="requires 'mean' and 'std'"):
            _parsed_fleet_distribution(
                pv={"capacity_kw": {"type": "normal", "mean": 100}}
            )

    def test_parse_uniform_missing_max_raises(self) -> None:
        """Test parsing uniform without max raises."""
        with pytest.raises(ConfigurationError, match="requires 'min' and 'max'"):
            _parsed_fleet_distribution(
                pv={"capacity_kw": {"type": "uniform", "min": 0}}
            )


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
