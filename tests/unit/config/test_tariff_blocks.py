# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the two pricing blocks: the tariff: block for imported energy and the seg: block for exported energy."""

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from solar_challenge.config import (
    ConfigurationError,
    load_community_config,
    load_scenarios,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig, TariffPeriod


class TestTariffConfigParsing:
    """Tests for parse_tariff_config's public contract."""

    def test_absent_block_parses_to_no_tariff(self) -> None:
        """parse_tariff_config(None) returns None (no tariff block)."""
        assert parse_tariff_config(None) is None

    def test_flat_rate_block_matches_the_flat_rate_preset(self) -> None:
        """A flat_rate block parses to TariffConfig.flat_rate at its rate."""
        parsed = parse_tariff_config({"type": "flat_rate", "rate_per_kwh": 0.25})
        assert parsed == TariffConfig.flat_rate(rate_per_kwh=0.25)

    def test_bare_economy_7_block_matches_the_economy_7_preset(self) -> None:
        """An economy_7 block without overrides parses to TariffConfig.economy_7()."""
        assert parse_tariff_config({"type": "economy_7"}) == TariffConfig.economy_7()

    def test_custom_block_keeps_its_periods_in_order(self) -> None:
        """A custom block parses each period, in order, under the block's name."""
        data = {
            "type": "custom",
            "name": "Two-rate",
            "periods": [
                {
                    "start_time": "00:00",
                    "end_time": "07:00",
                    "rate_per_kwh": 0.10,
                    "name": "Night",
                },
                {
                    "start_time": "07:00",
                    "end_time": "00:00",
                    "rate_per_kwh": 0.30,
                    "name": "Day",
                },
            ],
        }
        assert parse_tariff_config(data) == TariffConfig(
            periods=(
                TariffPeriod("00:00", "07:00", 0.10, "Night"),
                TariffPeriod("07:00", "00:00", 0.30, "Day"),
            ),
            name="Two-rate",
        )

    def test_missing_type_raises(self) -> None:
        """A tariff block without 'type' raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires 'type'"):
            parse_tariff_config({})

    def test_unknown_type_raises(self) -> None:
        """An unrecognised tariff type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Unknown tariff type"):
            parse_tariff_config({"type": "bogus"})


class TestScenarioSegBlock:
    """One grammar for the top-level ``seg:`` block and ``community.billing.seg``.

    A block names exactly one of a SEG_PRESETS ``preset`` or a finite, non-negative
    ``rate_pence_per_kwh``; billing's scalar ``seg_rate_pence_per_kwh`` reads rates the same way.
    """

    _SCENARIO = {
        "name": "SEG block",
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        "home": {"pv": {"capacity_kw": 4.0}, "load": {"annual_consumption_kwh": 3400}},
    }

    _MALFORMED_RATES = [
        pytest.param(None, id="null"),
        pytest.param("abc", id="non-numeric"),
        pytest.param(-1.0, id="negative"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinite"),
        pytest.param(True, id="boolean"),
    ]

    @pytest.fixture(params=["scenario", "community billing", "parse_seg_rate"])
    def read_seg_rate(
        self, request: pytest.FixtureRequest, tmp_path: Path
    ) -> Callable[[object], float | None]:
        """Read a ``seg`` block's rate through a public entry point.

        The entry points are a scenario file, a community-billing file, and parse_seg_rate itself.
        """
        path = tmp_path / "seg.yaml"

        def through_scenario(seg: object) -> float | None:
            path.write_text(yaml.safe_dump({**self._SCENARIO, "seg": seg}))
            return load_scenarios(path)[0].seg_tariff_pence_per_kwh

        def through_community_billing(seg: object) -> float | None:
            community = {"sharing_mode": "p2p", "billing": {"seg": seg}}
            path.write_text(yaml.safe_dump({"community": community}))
            config = load_community_config(path)
            assert config is not None
            assert config.billing is not None
            return config.billing.seg_rate_pence_per_kwh

        readers = {
            "scenario": through_scenario,
            "community billing": through_community_billing,
            "parse_seg_rate": parse_seg_rate,
        }
        return readers[request.param]

    @pytest.mark.parametrize("preset", sorted(SEG_PRESETS))
    def test_preset_resolves_to_the_supplier_rate(
        self, read_seg_rate: Callable[[object], float | None], preset: str
    ) -> None:
        """Every SEG_PRESETS key resolves to that supplier's export rate."""
        assert read_seg_rate({"preset": preset}) == SEG_PRESETS[preset].rate_pence_per_kwh

    def test_explicit_rate_is_read_as_a_float(
        self, read_seg_rate: Callable[[object], float | None]
    ) -> None:
        """An integer ``rate_pence_per_kwh`` is read back as a float."""
        rate = read_seg_rate({"rate_pence_per_kwh": 5})
        assert rate == 5.0
        assert isinstance(rate, float)

    @pytest.mark.parametrize(
        "seg",
        [
            pytest.param({"preset": "Octopus", "rate_pence_per_kwh": 5.5}, id="preset-and-rate"),
            pytest.param({}, id="empty"),
            pytest.param({"rate": 4.1}, id="unrecognised-key"),
            pytest.param({"preset": "Nonexistent"}, id="unknown-preset"),
            pytest.param(4.1, id="bare-number"),
            pytest.param("Octopus", id="bare-string"),
        ],
    )
    def test_malformed_block_is_refused(
        self, read_seg_rate: Callable[[object], float | None], seg: object
    ) -> None:
        """A malformed block raises ConfigurationError: never a silent rate or None, never a raw error."""
        with pytest.raises(ConfigurationError):
            read_seg_rate(seg)

    @pytest.mark.parametrize("rate", _MALFORMED_RATES)
    def test_malformed_rate_is_refused(
        self, read_seg_rate: Callable[[object], float | None], rate: object
    ) -> None:
        """A ``rate_pence_per_kwh`` that is not a finite, non-negative number is refused by name."""
        with pytest.raises(ConfigurationError, match="rate_pence_per_kwh"):
            read_seg_rate({"rate_pence_per_kwh": rate})

    @pytest.mark.parametrize("rate", _MALFORMED_RATES)
    def test_billing_scalar_rate_refuses_what_the_block_refuses(
        self, tmp_path: Path, rate: object
    ) -> None:
        """``community.billing.seg_rate_pence_per_kwh`` refuses every rate the ``seg`` block refuses."""
        path = tmp_path / "seg.yaml"
        community = {"sharing_mode": "p2p", "billing": {"seg_rate_pence_per_kwh": rate}}
        path.write_text(yaml.safe_dump({"community": community}))
        with pytest.raises(ConfigurationError, match="seg_rate_pence_per_kwh"):
            load_community_config(path)

    def test_unknown_preset_error_names_the_available_presets(
        self, read_seg_rate: Callable[[object], float | None]
    ) -> None:
        """Refusing an unknown preset names it and every preset that is available."""
        with pytest.raises(ConfigurationError) as excinfo:
            read_seg_rate({"preset": "Nonexistent"})
        message = str(excinfo.value)
        assert "Nonexistent" in message
        assert [preset for preset in SEG_PRESETS if preset not in message] == []

    def test_scenario_without_seg_block_has_no_seg_rate(self, tmp_path: Path) -> None:
        """A scenario with no ``seg:`` block carries no SEG rate."""
        path = tmp_path / "no-seg.yaml"
        path.write_text(yaml.safe_dump(self._SCENARIO))
        assert load_scenarios(path)[0].seg_tariff_pence_per_kwh is None

    def test_absent_block_parses_to_no_seg_rate(self) -> None:
        """parse_seg_rate reads an absent ``seg:`` block as no SEG rate."""
        assert parse_seg_rate(None) is None
