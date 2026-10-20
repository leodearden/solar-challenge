# SPDX-License-Identifier: AGPL-3.0-or-later
"""How generate_homes_from_distribution draws a fleet's settings: each stateless spec draws itself, each setting keeps its own pool and pre-sampled draws, and each random order draws ahead in the order it documents."""

import random

import pytest

from solar_challenge.config import (
    FleetDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    UniformDistribution,
    WeightedDiscreteDistribution,
    generate_homes_from_distribution,
)
from solar_challenge.location import Location


class TestAStatelessSpecDrawsItself:
    """A weighted discrete, normal or uniform spec draws its values itself, from the RNG it is handed."""

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(
                WeightedDiscreteDistribution(values=(30.0, 35.0, 40.0), weights=(1.0, 2.0, 1.0)),
                id="weighted_discrete",
            ),
            pytest.param(NormalDistribution(mean=35.0, std=8.0, min=15.0, max=50.0), id="normal"),
            pytest.param(UniformDistribution(min=20.0, max=45.0), id="uniform"),
        ],
    )
    def test_its_draws_are_the_values_the_fleet_gives_its_homes(
        self, spec: WeightedDiscreteDistribution | NormalDistribution | UniformDistribution
    ) -> None:
        """A spec's draws are the values the generator gives the fleet's homes, so a preview drawing through the spec matches the run.

        The fleet's pv.tilt is the only setting it draws from its RNG.
        """
        fleet = FleetDistributionConfig(
            n_homes=8, pv=PVDistributionConfig(capacity_kw=4.0, tilt=spec), load=LoadDistributionConfig(), seed=17
        )
        homes = generate_homes_from_distribution(fleet, Location.bristol())

        rng = random.Random(17)
        assert [home.pv_config.tilt for home in homes] == [spec.draw(rng) for _ in range(8)]

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(NormalDistribution(mean=1.0, std=0.1, min=2.5), id="min"),
            pytest.param(NormalDistribution(mean=10.0, std=0.1, max=2.5), id="max"),
        ],
    )
    def test_a_normal_draw_is_clamped_to_its_bound(self, spec: NormalDistribution) -> None:
        """Each mean lies at least 15 standard deviations past its bound, so every draw is clamped to it whatever the seed."""
        assert spec.draw(random.Random(0)) == 2.5
