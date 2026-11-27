# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.fleet_config, called directly."""

from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    FleetDistributionConfig,
    parse_fleet_distribution_config,
)
from solar_challenge.web import fleet_config
from solar_challenge.web.fleet_components import MAX_FLEET_HOMES, MAX_FLEET_SEED
from tests._falsy_json_values import FALSY_NON_NULL_VALUES
from tests._fleet_form import FLEET_FORM_COMPONENT_BLOCKS


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

    @pytest.mark.parametrize(
        ("spec", "got"),
        [
            pytest.param(None, "null", id="a-cleared-fixed-value"),
            pytest.param(
                {"type": "shuffled_pool", "values": [3.0, None], "counts": [3, 1]},
                "a null at values[1]",
                id="a-blank-pool-value",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [None, 5.0], "weights": [1, 3]},
                "a null at values[0]",
                id="a-blank-weighted-value",
            ),
        ],
    )
    def test_pvs_capacity_that_a_home_may_draw_null_is_refused_naming_the_forms_field(
        self, spec: object, got: str
    ) -> None:
        """Every home needs a PV capacity, so a spec some home may draw null from is refused before any home is generated, under pv.capacity_kw, the field the page posted."""
        blocks = {**_FORM_FLEET_BLOCKS, "pv": {"capacity_kw": spec}}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == f"pv.capacity_kw: required, so no home may draw null, got {got}"

    @pytest.mark.parametrize(
        "component",
        [
            pytest.param(
                {"pv": {"capacity_kw": {"type": "shuffled_pool", "values": [3.0, None], "counts": [4, 0]}}},
                id="a-pv-pool-value-no-home-draws",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "shuffled_pool", "values": [None, 5.0], "counts": [3, 1]}}},
                id="a-battery-pool-value-a-home-without-a-battery",
            ),
            pytest.param({"battery": {"capacity_kwh": None}}, id="a-battery-every-home-is-without"),
            pytest.param({"load": {"annual_consumption_kwh": None}}, id="a-load-left-to-its-default"),
        ],
    )
    def test_a_null_no_home_needs_a_value_for_is_read_as_the_grammar_reads_it(self, component: dict[str, Any]) -> None:
        """A null no home draws, a battery capacity's null, a home without a battery, and a load consumption's null, its default, are the grammar's."""
        blocks = {**_FORM_FLEET_BLOCKS, **component}
        assert fleet_config.read_form_fleet(blocks) == parse_fleet_distribution_config(blocks, block_path="")

    def test_a_battery_block_setting_a_dispatch_strategy_is_refused_naming_it(self) -> None:
        blocks = {**_FORM_FLEET_BLOCKS, "battery": {"capacity_kwh": 5.0, "dispatch_strategy": "tou_optimized"}}
        with pytest.raises(ConfigurationError) as refused:
            fleet_config.read_form_fleet(blocks)
        assert str(refused.value) == (
            "battery.dispatch_strategy must be absent or null: a dashboard form gives every "
            "battery one dispatch strategy, its own or the default, got 'tou_optimized'"
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

    @pytest.mark.parametrize(
        ("path", "field"),
        [
            pytest.param("fleet_distribution", "fleet_distribution.pv.capacity_kw", id="import"),
            pytest.param("", "pv.capacity_kw", id="fleet-form"),
        ],
    )
    def test_a_pv_capacity_a_home_may_draw_null_is_refused_naming_it_under_the_path(
        self, path: str, field: str
    ) -> None:
        """Every home needs a PV capacity, so a pool value left null that a home draws is refused before any home is generated, under *path*."""
        fleet = self._fleet(pv={"capacity_kw": {"type": "shuffled_pool", "values": [4.0, None], "counts": [1, 1]}})
        with pytest.raises(ConfigurationError) as exc_info:
            fleet_config.refuse_a_fleet_the_dashboard_cannot_run(fleet, path)
        assert str(exc_info.value) == f"{field}: required, so no home may draw null, got a null at values[1]"
