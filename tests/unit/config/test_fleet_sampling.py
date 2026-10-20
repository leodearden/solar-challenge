# SPDX-License-Identifier: AGPL-3.0-or-later
"""How generate_homes_from_distribution draws a fleet's settings: each stateless spec draws itself, each setting keeps its own pool and pre-sampled draws, and each random order draws ahead in the order it documents."""

import dataclasses
import random
from collections.abc import Callable, Sequence
from typing import Any, Optional

import pytest

from solar_challenge.config import (
    DistributionSpec,
    FleetDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    PVDistributionConfig,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    _DistributionSampler,
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location


def _draws(
    spec: WeightedDiscreteDistribution | NormalDistribution | UniformDistribution, *, seed: int, n: int
) -> list[Optional[float]]:
    """Return the first *n* values *spec* draws from an RNG seeded with *seed*."""
    rng = random.Random(seed)
    return [spec.draw(rng) for _ in range(n)]


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

        assert [home.pv_config.tilt for home in homes] == _draws(spec, seed=17, n=8)

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


class TestAPoolOnAnySettingIsDrawnInEitherRandomOrder:
    """A shuffled pool on any component's setting gives the fleet's homes its values in its counts, in either random order."""

    @pytest.mark.parametrize(
        ("block", "key", "values", "read"),
        [
            pytest.param("pv", "tilt", (30.0, 40.0), lambda home: home.pv_config.tilt, id="pv.tilt"),
            pytest.param(
                "load",
                "household_occupants",
                (2.0, 4.0),
                lambda home: home.load_config.household_occupants,
                id="load.household_occupants",
            ),
            pytest.param(
                "battery",
                "max_charge_kw",
                (2.0, 3.0),
                lambda home: home.battery_config.max_charge_kw,
                id="battery.max_charge_kw",
            ),
            pytest.param(
                "heat_pump",
                "thermal_capacity_kw",
                (6.0, 8.0),
                lambda home: home.heat_pump_config.thermal_capacity_kw,
                id="heat_pump.thermal_capacity_kw",
            ),
            pytest.param("ev", "arrival_hour", (17.0, 19.0), lambda home: home.ev_config.arrival_hour, id="ev.arrival_hour"),
        ],
    )
    @pytest.mark.parametrize("random_order", ["default", "bristol_legacy"])
    def test_its_homes_hold_its_values_in_its_counts(
        self,
        random_order: str,
        block: str,
        key: str,
        values: tuple[float, float],
        read: Callable[[HomeConfig], float],
    ) -> None:
        """Every home of the fleet draws the pooled setting, so its 4 homes hold each of the pool's 2 values twice."""
        a, b = values
        fleet_block: dict[str, Any] = {
            "n_homes": 4,
            "seed": 3,
            "random_order": random_order,
            "pv": {"capacity_kw": 4.0},
            "load": {"use_stochastic": False},
            "battery": {"capacity_kwh": 5.0},
            "heat_pump": {"heat_pump_type": "ASHP"},
            "ev": {"charger_type": {"type": "weighted_discrete", "values": ["7kW"], "weights": [1]}},
        }
        fleet_block[block] = {**fleet_block[block], key: {"type": "shuffled_pool", "values": [a, b], "counts": [2, 2]}}

        homes = generate_homes_from_distribution(parse_fleet_distribution_config(fleet_block), Location.bristol())

        assert sorted(read(home) for home in homes) == [a, a, b, b]


class TestOneSpecObjectOnTwoSettings:
    """One spec object given to two settings is drawn for each setting on its own."""

    @pytest.mark.parametrize("random_order", ["default", "bristol_legacy"])
    def test_one_pool_gives_each_setting_its_own_counts(self, random_order: str) -> None:
        """Each setting the pool is given to hands out its own copy of the pool, so each holds each value twice."""
        pool = ShuffledPoolDistribution(values=(30.0, 60.0), counts=(2, 2))
        fleet = FleetDistributionConfig(
            n_homes=4,
            pv=PVDistributionConfig(capacity_kw=4.0, tilt=pool, azimuth=pool),
            load=LoadDistributionConfig(),
            seed=1,
            random_order=random_order,
        )

        homes = generate_homes_from_distribution(fleet, Location.bristol())

        assert sorted(home.pv_config.tilt for home in homes) == [30.0, 30.0, 60.0, 60.0]
        assert sorted(home.pv_config.azimuth for home in homes) == [30.0, 30.0, 60.0, 60.0]

    def test_one_normal_gives_a_pre_sampled_setting_and_another_their_own_draws(self) -> None:
        """bristol_legacy draws every home's consumption ahead, and then each home's tilt afresh, from the one normal."""
        normal = NormalDistribution(mean=45.0, std=10.0, min=10.0, max=80.0)
        fleet = FleetDistributionConfig(
            n_homes=4,
            pv=PVDistributionConfig(capacity_kw=4.0, tilt=normal),
            load=LoadDistributionConfig(annual_consumption_kwh=normal),
            seed=1,
            random_order="bristol_legacy",
        )

        homes = generate_homes_from_distribution(fleet, Location.bristol())

        draws = _draws(normal, seed=1, n=8)
        assert [home.load_config.annual_consumption_kwh for home in homes] == draws[:4]
        assert [home.pv_config.tilt for home in homes] == draws[4:]


#: The pools of a fleet of 12 homes in which every home draws every pooled setting, as (component, key, values, counts).
_POOLS_OF_12_HOMES: tuple[tuple[str, str, tuple[Any, ...], tuple[int, ...]], ...] = (
    ("pv", "capacity_kw", (3.0, 4.0, 5.0), (4, 4, 4)),
    ("pv", "tilt", (25.0, 35.0, 45.0), (4, 4, 4)),
    ("load", "household_occupants", (1.0, 2.0, 3.0), (4, 4, 4)),
    ("battery", "capacity_kwh", (5.0, 10.0), (6, 6)),
    ("battery", "max_charge_kw", (2.5, 3.0), (6, 6)),
    ("heat_pump", "heat_pump_type", ("ASHP", "GSHP"), (6, 6)),
    ("ev", "charger_type", ("7kW", "3.6kW"), (6, 6)),
    ("ev", "departure_hour", (6.0, 7.0, 8.0), (4, 4, 4)),
)

#: The consumption of the fleet of 12 homes, the one setting it draws neither from a pool nor as a fixed value.
_CONSUMPTION_OF_12_HOMES = NormalDistribution(mean=3400.0, std=800.0, min=2000.0, max=6000.0)


def _fleet_of_12_pools(random_order: str) -> FleetDistributionConfig:
    """Return the fleet of 12 homes that _POOLS_OF_12_HOMES and _CONSUMPTION_OF_12_HOMES describe, seeded with 21."""
    block: dict[str, Any] = {
        "n_homes": 12,
        "seed": 21,
        "random_order": random_order,
        "load": {"annual_consumption_kwh": {"type": "normal", **dataclasses.asdict(_CONSUMPTION_OF_12_HOMES)}},
    }
    for component, key, values, counts in _POOLS_OF_12_HOMES:
        block.setdefault(component, {})[key] = {"type": "shuffled_pool", "values": list(values), "counts": list(counts)}
    return parse_fleet_distribution_config(block)


#: Each pool of _POOLS_OF_12_HOMES, under the path of its setting.
_POOL_OF_12_HOMES_BY_PATH: dict[str, ShuffledPoolDistribution] = {
    f"{component}.{key}": ShuffledPoolDistribution(values=values, counts=counts)
    for component, key, values, counts in _POOLS_OF_12_HOMES
}


def _shuffled(pool: ShuffledPoolDistribution, rng: random.Random) -> list[Any]:
    """Return *pool*'s values, expanded to its counts, then shuffled by *rng*."""
    values = pool.create_pool()
    rng.shuffle(values)
    return values


def _drawn_settings(home: HomeConfig) -> dict[str, object]:
    """Return what a home of the fleet of 12 homes holds for each setting it draws, but its heat pump's."""
    assert home.battery_config is not None and home.ev_config is not None
    return {
        "pv.capacity_kw": home.pv_config.capacity_kw,
        "pv.tilt": home.pv_config.tilt,
        "load.annual_consumption_kwh": home.load_config.annual_consumption_kwh,
        "load.household_occupants": home.load_config.household_occupants,
        "battery.capacity_kwh": home.battery_config.capacity_kwh,
        "battery.max_charge_kw": home.battery_config.max_charge_kw,
        "ev.charger_type": home.ev_config.charger_type,
        "ev.departure_hour": home.ev_config.departure_hour,
    }


def _modelled_settings(pools: dict[str, list[Any]], consumptions: Sequence[Optional[float]], index: int) -> dict[str, object]:
    """Return what the home at *index* holds for each setting _drawn_settings reads, given the modelled draws."""
    return {
        "pv.capacity_kw": pools["pv.capacity_kw"][index],
        "pv.tilt": pools["pv.tilt"][index],
        "load.annual_consumption_kwh": consumptions[index],
        "load.household_occupants": int(pools["load.household_occupants"][index]),
        "battery.capacity_kwh": pools["battery.capacity_kwh"][index],
        "battery.max_charge_kw": pools["battery.max_charge_kw"][index],
        "ev.charger_type": pools["ev.charger_type"][index],
        "ev.departure_hour": int(pools["ev.departure_hour"][index]),
    }


class TestEachRandomOrderDrawsAheadInTheOrderItDocuments:
    """Before its first home, each random order draws ahead what it documents, in the order it documents."""

    @pytest.mark.parametrize(
        ("random_order", "consumptions_drawn_ahead", "pool_order"),
        [
            pytest.param(
                "default",
                0,
                (
                    "pv.capacity_kw",
                    "pv.tilt",
                    "load.household_occupants",
                    "battery.capacity_kwh",
                    "battery.max_charge_kw",
                    "heat_pump.heat_pump_type",
                    "ev.charger_type",
                    "ev.departure_hour",
                ),
                id="default",
            ),
            pytest.param(
                "bristol_legacy",
                12,
                (
                    "pv.capacity_kw",
                    "battery.capacity_kwh",
                    "heat_pump.heat_pump_type",
                    "ev.charger_type",
                    "pv.tilt",
                    "load.household_occupants",
                    "battery.max_charge_kw",
                    "ev.departure_hour",
                ),
                id="bristol_legacy",
            ),
        ],
    )
    def test_the_fleet_draws_ahead_in_the_documented_order(
        self, random_order: str, consumptions_drawn_ahead: int, pool_order: tuple[str, ...]
    ) -> None:
        """The homes hold what a model of the documented order draws from an RNG seeded alike.

        The model draws the consumptions the order draws ahead, shuffles every pool in the order's sequence, and then
        draws the other consumptions, one per home: a home of this fleet draws nothing else afresh. Its heat pumps go
        unread: the heat_pump_type pool takes its place in the sequence, but no home draws from it.
        """
        homes = generate_homes_from_distribution(_fleet_of_12_pools(random_order), Location.bristol())

        rng = random.Random(21)
        consumptions = [_CONSUMPTION_OF_12_HOMES.draw(rng) for _ in range(consumptions_drawn_ahead)]
        pools = {path: _shuffled(_POOL_OF_12_HOMES_BY_PATH[path], rng) for path in pool_order}
        consumptions += [_CONSUMPTION_OF_12_HOMES.draw(rng) for _ in range(12 - consumptions_drawn_ahead)]
        assert [_drawn_settings(home) for home in homes] == [
            _modelled_settings(pools, consumptions, index) for index in range(12)
        ]

    def test_a_random_order_outside_the_two_is_refused(self) -> None:
        """A fleet's random order is one of the two, and the refusal names both."""
        with pytest.raises(ConfigurationError) as refusal:
            FleetDistributionConfig(
                n_homes=1,
                pv=PVDistributionConfig(capacity_kw=4.0),
                load=LoadDistributionConfig(),
                random_order="shuffled",
            )

        assert str(refusal.value) == (
            "FleetDistributionConfig: random_order must be 'default' or 'bristol_legacy', got 'shuffled'"
        )


_TILT_POOL_OF_2_HOMES = ShuffledPoolDistribution(values=(30.0, 40.0), counts=(1, 1))

_CONSUMPTION_OF_2_HOMES = NormalDistribution(mean=3400.0, std=800.0)


class TestTheSamplerRefusesASettingDrawnPastItsValues:
    """A setting drawn ahead holds one value per home, and the sampler refuses a draw past them, naming the setting.

    The fleet generator refuses a pool not sized to the fleet before it draws, so no fleet it generates draws past a
    setting's values: only the sampler, asked directly, can be.
    """

    @pytest.mark.parametrize(
        ("fleet", "setting", "spec", "values"),
        [
            pytest.param(
                FleetDistributionConfig(
                    n_homes=2,
                    pv=PVDistributionConfig(capacity_kw=4.0, tilt=_TILT_POOL_OF_2_HOMES),
                    load=LoadDistributionConfig(),
                ),
                "pv.tilt",
                _TILT_POOL_OF_2_HOMES,
                [30.0, 40.0],
                id="shuffled-pool",
            ),
            pytest.param(
                FleetDistributionConfig(
                    n_homes=2,
                    pv=PVDistributionConfig(capacity_kw=4.0),
                    load=LoadDistributionConfig(annual_consumption_kwh=_CONSUMPTION_OF_2_HOMES),
                    seed=4,
                    random_order="bristol_legacy",
                ),
                "load.annual_consumption_kwh",
                _CONSUMPTION_OF_2_HOMES,
                _draws(_CONSUMPTION_OF_2_HOMES, seed=4, n=2),
                id="bristol-legacy-pre-sample",
            ),
        ],
    )
    def test_a_draw_past_the_values_of_a_setting_is_refused_naming_it(
        self, fleet: FleetDistributionConfig, setting: str, spec: DistributionSpec, values: list[Optional[float]]
    ) -> None:
        """The two homes' draws hand out the setting's 2 values, and a third draw is refused."""
        sampler = _DistributionSampler(fleet)

        assert sorted([sampler.sample(spec, setting), sampler.sample(spec, setting)]) == sorted(values)
        with pytest.raises(ConfigurationError) as refusal:
            sampler.sample(spec, setting)
        assert str(refusal.value) == f"{setting} has no value left to draw: its 2 values, one per home, are all drawn"


class TestASpecTheSamplerCannotDrawIsRefusedNamingTheSetting:
    """A spec the sampler cannot draw for a setting is refused, naming the setting and the spec."""

    def test_a_proportional_to_drawn_without_its_source_is_refused(self) -> None:
        """The generator hands a proportional_to its source's value for battery and heat pump settings, never for pv.tilt."""
        fleet = parse_fleet_distribution_config(
            {
                "n_homes": 2,
                "seed": 1,
                "pv": {
                    "capacity_kw": 4.0,
                    "tilt": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 5},
                },
            }
        )

        with pytest.raises(ConfigurationError) as refusal:
            generate_homes_from_distribution(fleet, Location.bristol())

        assert str(refusal.value) == (
            "pv.tilt cannot be drawn from ProportionalDistribution(source='pv.capacity_kw', multiplier=5.0, offset=0.0)"
        )
