# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the community: block, as load_community_config reads it into a CommunityConfig."""

import dataclasses
import pickle
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias

import pytest
import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityConfig
from solar_challenge.config import load_community_config, load_community_configs, load_scenario
from solar_challenge.errors import ConfigurationError


LoadCommunityBlock: TypeAlias = Callable[[dict[str, Any]], CommunityConfig | None]

_SHARING_MODE_RETIRED = (
    "the sharing mode follows community_battery; "
    "a community with a community_battery block shares through that battery, "
    "and one without nets peer to peer, so delete sharing_mode"
)

_A_COMMUNITY_BATTERY_BLOCK: dict[str, Any] = {"community_battery": {"capacity_kwh": 20.0}}
_A_SCENARIO_SETTING_SHARING_MODE: dict[str, Any] = {"homes": [{}], "community": {"sharing_mode": "p2p"}}


def _scenario_file(tmp_path: Path, document: dict[str, Any], *, name: str = "scenario.yaml") -> Path:
    """The path of *document*, written as YAML to *name* under *tmp_path*."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document))
    return path


@pytest.fixture
def load_community_block(tmp_path: Path) -> LoadCommunityBlock:
    """Read a ``community:`` block the way the CLI does: from a YAML file, through load_community_config."""
    path = tmp_path / "community.yaml"

    def load(block: dict[str, Any]) -> CommunityConfig | None:
        path.write_text(yaml.safe_dump({"community": block}))
        return load_community_config(path)

    return load


class TestCommunityBlockParsing:
    """The community: block, as load_community_config reads it from a file."""

    def test_an_empty_community_block_is_a_p2p_community(self, load_community_block: LoadCommunityBlock) -> None:
        cfg = load_community_block({})
        assert isinstance(cfg, CommunityConfig)
        assert cfg.community_battery is None
        assert cfg.billing is None
        assert cfg.sharing_mode == "p2p"

    def test_a_block_with_a_community_battery_shares_through_it(self, load_community_block: LoadCommunityBlock) -> None:
        cfg = load_community_block({"community_battery": {"capacity_kwh": 20.0}})
        assert cfg is not None
        assert cfg.sharing_mode == "community_battery"
        assert cfg.community_battery is not None
        assert cfg.community_battery.capacity_kwh == 20.0

    @pytest.mark.parametrize(
        "block",
        [
            pytest.param({"sharing_mode": "p2p"}, id="p2p"),
            pytest.param(
                {"sharing_mode": "community_battery", "community_battery": {"capacity_kwh": 20.0}},
                id="community-battery",
            ),
            pytest.param({"sharing_mode": None}, id="null"),
        ],
    )
    def test_a_block_setting_sharing_mode_is_refused_naming_it(
        self, load_community_block: LoadCommunityBlock, block: dict[str, Any]
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            load_community_block(block)
        assert str(refusal.value) == f"community.sharing_mode: {_SHARING_MODE_RETIRED}"

    # ------------------------------------------------------------------
    # community_battery: a grid_charging its dispatch would ignore
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "billing_entry",
        [
            pytest.param({}, id="no-billing"),
            pytest.param({"billing": {"tariff": {"type": "economy_7"}}}, id="billing-tariff"),
        ],
    )
    def test_a_self_consumption_community_battery_that_grid_charges_is_refused(
        self, load_community_block: LoadCommunityBlock, billing_entry: dict[str, Any]
    ) -> None:
        """A community_battery block naming no dispatch_strategy dispatches by self-consumption, which never grid-charges."""
        block = {
            "community_battery": {"capacity_kwh": 20.0, "grid_charging": {"target_soc_fraction": 0.9}},
            **billing_entry,
        }
        with pytest.raises(ConfigurationError) as exc_info:
            load_community_block(block)
        message = str(exc_info.value)
        assert "grid_charging" in message
        assert "'self_consumption'" in message

    @pytest.mark.parametrize(
        "billing_entry",
        [
            pytest.param({}, id="no-billing"),
            pytest.param({"billing": {"seg_rate_pence_per_kwh": 4.1}}, id="billing-seg-rate-only"),
        ],
    )
    def test_a_grid_charging_community_battery_without_a_billing_tariff_is_refused(
        self, load_community_block: LoadCommunityBlock, billing_entry: dict[str, Any]
    ) -> None:
        """A peak_shaving community battery grid-charges in a cheap period of the billing tariff, so it needs one."""
        block = {
            "community_battery": {
                "capacity_kwh": 20.0,
                "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 3.0},
                "grid_charging": {"target_soc_fraction": 0.9},
            },
            **billing_entry,
        }
        with pytest.raises(ConfigurationError) as exc_info:
            load_community_block(block)
        message = str(exc_info.value)
        assert "grid_charging" in message
        assert "no tariff" in message

    # ------------------------------------------------------------------
    # billing: nested SEG forms
    # ------------------------------------------------------------------

    def test_billing_both_scalar_and_seg_block_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """Supplying both seg_rate_pence_per_kwh and seg block is refused, naming the billing block."""
        with pytest.raises(ConfigurationError) as refusal:
            load_community_block(
                {
                    "billing": {
                        "seg_rate_pence_per_kwh": 4.1,
                        "seg": {"preset": "Octopus"},
                    },
                }
            )
        assert str(refusal.value) == "community.billing: sets both seg_rate_pence_per_kwh and seg; set one, not both"

    def test_billing_seg_non_dict_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """A bare scalar for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            load_community_block(
                {
                    "billing": {"seg": 4.1},
                }
            )

    def test_billing_seg_string_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """A bare string for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            load_community_block(
                {
                    "billing": {"seg": "Octopus"},
                }
            )

    def test_empty_billing_block_returns_none_billing(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """An empty billing: {} block normalises to billing=None (same as absent key)."""
        cfg = load_community_block({"billing": {}})
        assert cfg is not None
        assert cfg.billing is None


class TestCommunityBatteryEfficiency:
    """A community_battery block's efficiency is the round trip, as a home battery block's is."""

    def test_a_round_trip_efficiency_reads_as_the_pair_it_splits_into(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        cfg = load_community_block(
            {"community_battery": {"capacity_kwh": 10, "efficiency": 0.95}}
        )
        assert cfg is not None
        assert cfg.community_battery == BatteryConfig(capacity_kwh=10).with_round_trip(0.95)

    @pytest.mark.parametrize(
        ("per_direction", "keys_named"),
        [
            pytest.param({"charge_efficiency": 0.975}, "charge_efficiency", id="charge-at-its-default"),
            pytest.param({"discharge_efficiency": 0.7}, "discharge_efficiency", id="discharge"),
            pytest.param(
                {"charge_efficiency": 0.99, "discharge_efficiency": 0.7},
                "charge_efficiency and discharge_efficiency",
                id="both",
            ),
        ],
    )
    def test_a_block_setting_both_efficiency_forms_is_refused_naming_it_and_each_key(
        self, load_community_block: LoadCommunityBlock, per_direction: dict[str, float], keys_named: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            load_community_block(
                {
                    "community_battery": {"capacity_kwh": 10, "efficiency": 0.95, **per_direction},
                }
            )
        assert str(refusal.value) == (
            "community.community_battery: sets both forms of a battery's efficiency: "
            f"efficiency and {keys_named}; "
            "set efficiency, the round trip, or charge_efficiency and discharge_efficiency, not both"
        )


class TestLoadCommunityConfig:
    """Tests for load_community_config."""

    def test_load_yaml_with_community_block(self, tmp_path: Path) -> None:
        """YAML file with community: block returns a populated CommunityConfig."""
        yaml_content = """\
community:
  community_battery:
    capacity_kwh: 50.0
    max_charge_kw: 20.0
    max_discharge_kw: 20.0
  billing:
    tariff:
      type: flat_rate
      rate_per_kwh: 0.30
    seg_rate_pence_per_kwh: 4.1
"""
        path = tmp_path / "community.yaml"
        path.write_text(yaml_content)

        cfg = load_community_config(path)
        assert isinstance(cfg, CommunityConfig)
        assert cfg.sharing_mode == "community_battery"
        assert cfg.community_battery is not None
        assert cfg.community_battery.capacity_kwh == pytest.approx(50.0)
        assert cfg.billing is not None
        assert cfg.billing.tariff is not None
        assert cfg.billing.seg_rate_pence_per_kwh == pytest.approx(4.1)

    def test_load_yaml_without_community_block_returns_none(self, tmp_path: Path) -> None:
        """YAML file with no community: key returns None."""
        yaml_content = """\
name: Bristol Phase 1
period:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
"""
        path = tmp_path / "community.yaml"
        path.write_text(yaml_content)

        result = load_community_config(path)
        assert result is None

    def test_a_yaml_file_that_is_a_list_is_refused_naming_the_top_level(self, tmp_path: Path) -> None:
        """A document is a mapping of blocks, so a list is refused, where it was read as a file with no community block."""
        path = tmp_path / "community.yaml"
        path.write_text("- item1\n- item2\n")

        with pytest.raises(ConfigurationError) as refusal:
            load_community_config(path)
        assert str(refusal.value) == "the top level: must be a mapping, got list"

    def test_a_scenario_blocks_community_block_reads_as_a_bare_documents_does(self, tmp_path: Path) -> None:
        bare = load_community_config(
            _scenario_file(tmp_path, {"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}, name="bare.yaml")
        )
        wrapped = load_community_config(
            _scenario_file(tmp_path, {"scenario": {"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}})
        )

        assert wrapped is not None
        assert wrapped == bare

    def test_a_scenario_blocks_community_block_setting_sharing_mode_is_refused_naming_its_path(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            load_community_config(_scenario_file(tmp_path, {"scenario": _A_SCENARIO_SETTING_SHARING_MODE}))

        assert str(refusal.value) == f"scenario.community.sharing_mode: {_SHARING_MODE_RETIRED}"

    def test_a_scenarios_document_is_refused_as_load_scenario_refuses_it(self, tmp_path: Path) -> None:
        path = _scenario_file(tmp_path, {"scenarios": [{"homes": [{}], "community": {}}, {"homes": [{}]}]})
        with pytest.raises(ConfigurationError) as scenario_refusal:
            load_scenario(path)

        with pytest.raises(ConfigurationError) as refusal:
            load_community_config(path)

        assert str(refusal.value) == str(scenario_refusal.value)

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}, id="bare"),
            pytest.param({"scenario": {"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}}, id="scenario-block"),
        ],
    )
    def test_load_community_configs_reads_a_one_scenario_document_as_load_community_config_does(
        self, tmp_path: Path, document: dict[str, Any]
    ) -> None:
        path = _scenario_file(tmp_path, document)

        assert load_community_configs(path) == [load_community_config(path)]


class TestTheCommunityBlockOfEachScenario:
    """Every scenario's community: block, as load_community_configs reads it at that scenario's path."""

    def test_load_community_configs_reads_each_scenarios_community_block_in_order(self, tmp_path: Path) -> None:
        path = _scenario_file(
            tmp_path, {"scenarios": [{"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}, {"homes": [{}]}]}
        )

        first, second = load_community_configs(path)

        assert first is not None
        assert first.community_battery is not None
        assert first.community_battery.capacity_kwh == 20.0
        assert second is None

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}, id="bare"),
            pytest.param({"scenario": {"homes": [{}], "community": _A_COMMUNITY_BATTERY_BLOCK}}, id="scenario-block"),
        ],
    )
    def test_load_community_configs_reads_the_community_block_of_a_one_scenario_document(
        self, tmp_path: Path, document: dict[str, Any]
    ) -> None:
        (community,) = load_community_configs(_scenario_file(tmp_path, document))

        assert community is not None
        assert community.community_battery is not None
        assert community.community_battery.capacity_kwh == 20.0

    @pytest.mark.parametrize(
        ("document", "path"),
        [
            pytest.param(_A_SCENARIO_SETTING_SHARING_MODE, "community.sharing_mode", id="bare"),
            pytest.param(
                {"scenario": _A_SCENARIO_SETTING_SHARING_MODE}, "scenario.community.sharing_mode", id="scenario-block"
            ),
            pytest.param(
                {"scenarios": [{"homes": [{}]}, _A_SCENARIO_SETTING_SHARING_MODE]},
                "scenarios[1].community.sharing_mode",
                id="scenarios-entry",
            ),
        ],
    )
    def test_a_community_block_setting_sharing_mode_is_refused_naming_its_scenarios_path(
        self, tmp_path: Path, document: dict[str, Any], path: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            load_community_configs(_scenario_file(tmp_path, document))

        assert str(refusal.value) == f"{path}: {_SHARING_MODE_RETIRED}"


class TestCommunityConfigFrozenPicklable:
    """Contract guard: full CommunityConfig object graph is frozen and picklable."""

    @pytest.fixture
    def full_community_config(
        self, load_community_block: LoadCommunityBlock
    ) -> CommunityConfig:
        """Return a CommunityConfig that exercises every nested dataclass."""
        cfg = load_community_block(
            {
                "community_battery": {
                    "capacity_kwh": 50.0,
                    "max_charge_kw": 20.0,
                    "max_discharge_kw": 20.0,
                },
                "billing": {
                    "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
                    "seg_rate_pence_per_kwh": 4.1,
                },
            }
        )
        assert cfg is not None
        return cfg

    def test_picklable_round_trip(self, full_community_config: CommunityConfig) -> None:
        """CommunityConfig (with nested BatteryConfig + CommunityBillingConfig + TariffConfig)
        round-trips through pickle with structural equality."""
        cfg = full_community_config
        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg

    def test_frozen_top_level(self, full_community_config: CommunityConfig) -> None:
        """Assigning a new attribute on CommunityConfig raises FrozenInstanceError."""
        cfg = full_community_config
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.community_battery = None  # type: ignore[misc]

    def test_frozen_nested_battery(self, full_community_config: CommunityConfig) -> None:
        """BatteryConfig inside CommunityConfig is also frozen."""
        cfg = full_community_config
        assert cfg.community_battery is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.community_battery.capacity_kwh = 99.0  # type: ignore[misc]

    def test_frozen_nested_billing(self, full_community_config: CommunityConfig) -> None:
        """CommunityBillingConfig inside CommunityConfig is also frozen."""
        cfg = full_community_config
        assert cfg.billing is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.billing.seg_rate_pence_per_kwh = 0.0  # type: ignore[misc]
