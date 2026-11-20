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
from solar_challenge.config import load_community_config
from solar_challenge.errors import ConfigurationError


LoadCommunityBlock: TypeAlias = Callable[[dict[str, Any]], CommunityConfig | None]


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

    def test_minimal_p2p(self, load_community_block: LoadCommunityBlock) -> None:
        """A minimal dict with sharing_mode='p2p' returns a valid CommunityConfig."""
        cfg = load_community_block({"sharing_mode": "p2p"})
        assert isinstance(cfg, CommunityConfig)
        assert cfg.sharing_mode == "p2p"
        assert cfg.community_battery is None
        assert cfg.billing is None

    # ------------------------------------------------------------------
    # community_battery mode + invalid combinations
    # ------------------------------------------------------------------

    def test_community_battery_mode_without_battery_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """community_battery mode without a community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block({"sharing_mode": "community_battery"})

    def test_p2p_with_battery_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """p2p + community_battery block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "community_battery": {"capacity_kwh": 50.0},
                }
            )

    def test_bogus_mode_raises(self, load_community_block: LoadCommunityBlock) -> None:
        """An unrecognised sharing_mode raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block({"sharing_mode": "bogus"})

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
            "sharing_mode": "community_battery",
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
            "sharing_mode": "community_battery",
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
        """Supplying both seg_rate_pence_per_kwh and seg block raises ConfigurationError."""
        with pytest.raises(ConfigurationError):
            load_community_block(
                {
                    "sharing_mode": "p2p",
                    "billing": {
                        "seg_rate_pence_per_kwh": 4.1,
                        "seg": {"preset": "Octopus"},
                    },
                }
            )

    def test_billing_seg_non_dict_raises(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """A bare scalar for the seg key raises ConfigurationError, not TypeError."""
        with pytest.raises(ConfigurationError, match="mapping"):
            load_community_block(
                {
                    "sharing_mode": "p2p",
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
                    "sharing_mode": "p2p",
                    "billing": {"seg": "Octopus"},
                }
            )

    def test_empty_billing_block_returns_none_billing(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        """An empty billing: {} block normalises to billing=None (same as absent key)."""
        cfg = load_community_block({"sharing_mode": "p2p", "billing": {}})
        assert cfg is not None
        assert cfg.billing is None


class TestCommunityBatteryEfficiency:
    """A community_battery block's efficiency is the round trip, as a home battery block's is."""

    def test_a_round_trip_efficiency_reads_as_the_pair_it_splits_into(
        self, load_community_block: LoadCommunityBlock
    ) -> None:
        cfg = load_community_block(
            {"sharing_mode": "community_battery", "community_battery": {"capacity_kwh": 10, "efficiency": 0.95}}
        )
        assert cfg is not None
        assert cfg.community_battery == BatteryConfig(capacity_kwh=10).with_round_trip(0.95)
        assert cfg.community_battery.efficiency is None

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
                    "sharing_mode": "community_battery",
                    "community_battery": {"capacity_kwh": 10, "efficiency": 0.95, **per_direction},
                }
            )
        assert str(refusal.value) == (
            "community.community_battery sets both forms of a battery's efficiency: "
            f"efficiency and {keys_named}; "
            "set efficiency, the round trip, or charge_efficiency and discharge_efficiency, not both"
        )


class TestLoadCommunityConfig:
    """Tests for load_community_config."""

    def test_load_yaml_with_community_block(self, tmp_path: Path) -> None:
        """YAML file with community: block returns a populated CommunityConfig."""
        yaml_content = """\
community:
  sharing_mode: community_battery
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

    def test_load_non_dict_yaml_returns_none(self, tmp_path: Path) -> None:
        """A YAML file whose top-level value is a list (not a dict) returns None
        instead of raising AttributeError on .get('community').
        """
        path = tmp_path / "community.yaml"
        path.write_text("- item1\n- item2\n")  # top-level list, no community key

        result = load_community_config(path)
        assert result is None


class TestCommunityConfigFrozenPicklable:
    """Contract guard: full CommunityConfig object graph is frozen and picklable."""

    @pytest.fixture
    def full_community_config(
        self, load_community_block: LoadCommunityBlock
    ) -> CommunityConfig:
        """Return a CommunityConfig that exercises every nested dataclass."""
        cfg = load_community_block(
            {
                "sharing_mode": "community_battery",
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
            cfg.sharing_mode = "p2p"  # type: ignore[misc]

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
