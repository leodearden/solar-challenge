# SPDX-License-Identifier: AGPL-3.0-or-later
"""The SOH-derated SOC envelope, read without building a Battery: docs/prds/dispatch-configuration-below-config.md §9 row 11.

The PRD's §5.4 δ bullet specifies it: battery.SocEnvelope holds a battery's effective capacity and its SOC limits
within it, in kWh, and its target_kwh(fraction) holds γ's cap, so a target above the ceiling is the ceiling.
"""

import dataclasses
import math
import re

import pytest
from solar_challenge.battery import Battery, BatteryConfig, SocEnvelope, compute_soh
from solar_challenge.dispatch import GridChargeConfig
from solar_challenge.errors import ConfigurationError
from tests._unusable_numbers import UNUSABLE_NUMBERS

_ROW_11_ENVELOPE = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=1.4, max_soc_kwh=5.6)
"""Row 11's envelope built directly: a 10 kWh battery at SOH 0.7 with SOC limits of 0.2 and 0.8."""

_ROW_11_CONFIG = BatteryConfig(capacity_kwh=10.0, soh=0.7, min_soc_fraction=0.2, max_soc_fraction=0.8)
"""Row 11's battery: 10 kWh at SOH 0.7, with SOC limits of 0.2 and 0.8."""


def _refusal_of(field: str, value: object) -> str:
    """The pattern of the refusal of *value* for *field* alone, "<field> must be <requirement>, got <value!r>".

    The order refusal names every field and its value too, so a pattern that only looks for the
    field and the value would also match it.
    """
    return rf"^{re.escape(field)} must be .+, got {re.escape(repr(value))}$"


class TestSocEnvelope:
    """A SocEnvelope built directly holds an effective capacity and the SOC limits within it, and caps a target at its ceiling."""

    def test_a_target_is_its_fraction_of_the_effective_capacity(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.5) == pytest.approx(3.5)

    def test_a_target_at_the_ceiling_is_the_ceiling(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.8) == pytest.approx(5.6)

    def test_a_target_above_the_ceiling_is_the_ceiling(self) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(0.95) == _ROW_11_ENVELOPE.max_soc_kwh == 5.6

    @pytest.mark.parametrize(
        ("fraction", "target_kwh"),
        [
            pytest.param(0.0, 0.0, id="0-is-an-empty-battery"),
            pytest.param(1.0, 5.6, id="1-is-the-ceiling"),
        ],
    )
    def test_a_target_fraction_of_0_or_1_is_accepted(self, fraction: float, target_kwh: float) -> None:
        assert _ROW_11_ENVELOPE.target_kwh(fraction) == target_kwh

    @pytest.mark.parametrize(
        "fraction", [*UNUSABLE_NUMBERS, pytest.param(-0.1, id="below-0"), pytest.param(1.5, id="above-1")]
    )
    def test_a_target_fraction_that_is_not_a_finite_number_from_0_to_1_is_refused_naming_it(
        self, fraction: float
    ) -> None:
        with pytest.raises(ConfigurationError, match=_refusal_of("fraction", fraction)):
            _ROW_11_ENVELOPE.target_kwh(fraction)

    def test_a_field_cannot_be_assigned(self) -> None:
        envelope = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=1.4, max_soc_kwh=5.6)
        with pytest.raises(dataclasses.FrozenInstanceError):
            envelope.max_soc_kwh = 6.0

    def test_whole_numbers_are_held_as_the_floats_they_equal(self) -> None:
        envelope = SocEnvelope(10, 1, 9)
        assert dataclasses.astuple(envelope) == (10.0, 1.0, 9.0)
        assert [type(value) for value in dataclasses.astuple(envelope)] == [float, float, float]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("effective_capacity_kwh", 0.0),
            ("effective_capacity_kwh", math.nan),
            ("min_soc_kwh", -0.1),
            ("min_soc_kwh", math.inf),
            ("max_soc_kwh", math.nan),
        ],
    )
    def test_a_field_that_is_not_a_finite_number_in_its_range_is_refused_naming_it_and_the_value(
        self, field: str, value: float
    ) -> None:
        with pytest.raises(ConfigurationError, match=_refusal_of(field, value)):
            dataclasses.replace(_ROW_11_ENVELOPE, **{field: value})

    def test_an_envelope_with_no_capacity_is_refused_though_its_limits_are_in_order(self) -> None:
        """0 <= 0 <= 0 is in order, so only the effective capacity's own bound, above 0, refuses it."""
        with pytest.raises(ConfigurationError, match=_refusal_of("effective_capacity_kwh", 0.0)):
            SocEnvelope(effective_capacity_kwh=0.0, min_soc_kwh=0.0, max_soc_kwh=0.0)

    @pytest.mark.parametrize(
        ("min_soc_kwh", "max_soc_kwh"),
        [
            pytest.param(6.0, 5.6, id="min-above-max"),
            pytest.param(1.4, 7.5, id="max-above-the-effective-capacity"),
        ],
    )
    def test_limits_out_of_order_are_refused_naming_all_three_values(
        self, min_soc_kwh: float, max_soc_kwh: float
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=min_soc_kwh, max_soc_kwh=max_soc_kwh)
        named = (("effective_capacity_kwh", 7.0), ("min_soc_kwh", min_soc_kwh), ("max_soc_kwh", max_soc_kwh))
        for field, value in named:
            assert f"{field}={value!r}" in str(refusal.value)

    @pytest.mark.parametrize(
        ("min_soc_kwh", "max_soc_kwh"),
        [
            pytest.param(5.6, 5.6, id="min-at-max"),
            pytest.param(1.4, 7.0, id="max-at-the-effective-capacity"),
            pytest.param(0.0, 5.6, id="min-at-zero"),
        ],
    )
    def test_limits_at_their_bounds_are_accepted(self, min_soc_kwh: float, max_soc_kwh: float) -> None:
        """The order is not strict: two SOC fractions a Battery admits can round to the same kWh."""
        envelope = SocEnvelope(effective_capacity_kwh=7.0, min_soc_kwh=min_soc_kwh, max_soc_kwh=max_soc_kwh)
        assert (envelope.min_soc_kwh, envelope.max_soc_kwh) == (min_soc_kwh, max_soc_kwh)


class TestBatteryConfigResolvedSoh:
    """BatteryConfig.resolved_soh is the one SOH resolution: the soh override as given, else calendar fade alone."""

    def test_the_override_wins(self) -> None:
        assert BatteryConfig(capacity_kwh=10.0, soh=0.7, system_age_years=5.0).resolved_soh == 0.7

    def test_an_override_below_the_floor_is_used_as_given(self) -> None:
        config = BatteryConfig(capacity_kwh=10.0, soh=0.3)
        assert config.soh_floor == 0.5
        assert config.resolved_soh == 0.3

    @pytest.mark.parametrize(("system_age_years", "soh"), [(5.0, 0.9), (0.0, 1.0)])
    def test_without_an_override_it_is_the_calendar_fade_alone(self, system_age_years: float, soh: float) -> None:
        """A single run accrues no throughput, so there is no cycle fade."""
        config = BatteryConfig(capacity_kwh=10.0, system_age_years=system_age_years)
        assert config.resolved_soh == compute_soh(system_age_years, 0.0, config.nominal_usable_capacity_kwh, config)
        assert config.resolved_soh == pytest.approx(soh)

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param(BatteryConfig(capacity_kwh=10.0, soh=0.7, system_age_years=5.0), id="override"),
            pytest.param(BatteryConfig(capacity_kwh=10.0, soh=0.3), id="override-below-the-floor"),
            pytest.param(BatteryConfig(capacity_kwh=10.0, system_age_years=5.0), id="calendar-faded"),
            pytest.param(BatteryConfig(capacity_kwh=10.0), id="new"),
        ],
    )
    def test_a_battery_holds_its_configs_resolved_soh(self, config: BatteryConfig) -> None:
        assert Battery(config).soh == config.resolved_soh


class TestBatteryConfigSocEnvelope:
    """BatteryConfig.soc_envelope() is the envelope a Battery built from the config answers, read without building one."""

    def test_row_11s_envelope(self) -> None:
        assert dataclasses.astuple(_ROW_11_CONFIG.soc_envelope()) == pytest.approx((7.0, 1.4, 5.6))

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param(_ROW_11_CONFIG, id="row-11"),
            pytest.param(BatteryConfig(capacity_kwh=10.0), id="defaults"),
            pytest.param(
                BatteryConfig(capacity_kwh=10.0, min_soc_fraction=0.2, system_age_years=5.0), id="calendar-faded"
            ),
        ],
    )
    def test_it_is_the_envelope_a_battery_built_from_the_config_answers(self, config: BatteryConfig) -> None:
        envelope = config.soc_envelope()
        battery = Battery(config)
        assert (envelope.effective_capacity_kwh, envelope.min_soc_kwh, envelope.max_soc_kwh) == (
            battery.effective_capacity_kwh,
            battery.min_soc_kwh,
            battery.max_soc_kwh,
        )

    @pytest.mark.parametrize("target_soc_fraction", [0.5, 0.95])
    def test_its_target_is_the_grid_charge_target_a_battery_answers(self, target_soc_fraction: float) -> None:
        """0.95 is above row 11's ceiling of 0.8, so both land on max_soc_kwh."""
        config = dataclasses.replace(_ROW_11_CONFIG, grid_charging=GridChargeConfig(target_soc_fraction))
        assert config.soc_envelope().target_kwh(target_soc_fraction) == Battery(config).grid_charge_target_kwh


class TestBatterySocEnvelope:
    """Battery.soc_envelope is the envelope at the battery's current SOC fractions, and its kWh answers derive from it."""

    def test_a_new_battery_answers_its_configs_envelope(self) -> None:
        assert Battery(_ROW_11_CONFIG).soc_envelope == _ROW_11_CONFIG.soc_envelope()

    def test_fractions_the_constructor_is_given_move_the_batterys_envelope_and_not_its_configs(self) -> None:
        battery = Battery(_ROW_11_CONFIG, min_soc_fraction=0.3, max_soc_fraction=0.7)
        assert dataclasses.astuple(battery.soc_envelope) == pytest.approx((7.0, 2.1, 4.9))
        assert dataclasses.astuple(_ROW_11_CONFIG.soc_envelope()) == pytest.approx((7.0, 1.4, 5.6))

    def test_an_assigned_max_soc_fraction_moves_the_ceiling_it_answers(self) -> None:
        battery = Battery(_ROW_11_CONFIG)
        battery.max_soc_fraction = 0.6
        envelope = battery.soc_envelope
        assert envelope.max_soc_kwh == pytest.approx(4.2)
        assert battery.max_soc_kwh == envelope.max_soc_kwh
        assert battery.usable_capacity_kwh == envelope.max_soc_kwh - envelope.min_soc_kwh
        assert _ROW_11_CONFIG.soc_envelope().max_soc_kwh == pytest.approx(5.6)

    def test_an_assigned_min_soc_fraction_moves_the_floor_it_answers(self) -> None:
        battery = Battery(_ROW_11_CONFIG)
        battery.min_soc_fraction = 0.3
        assert battery.soc_envelope.min_soc_kwh == pytest.approx(2.1)
        assert battery.min_soc_kwh == battery.soc_envelope.min_soc_kwh

    def test_a_grid_charge_target_above_an_assigned_ceiling_is_the_envelopes_ceiling(self) -> None:
        battery = Battery(dataclasses.replace(_ROW_11_CONFIG, grid_charging=GridChargeConfig(0.95)))
        battery.max_soc_fraction = 0.6
        assert battery.grid_charge_target_kwh == battery.soc_envelope.target_kwh(0.95) == battery.soc_envelope.max_soc_kwh

    @pytest.mark.parametrize("efficiency", ["charge_efficiency", "discharge_efficiency"])
    def test_an_assigned_efficiency_leaves_the_envelope_as_it_was(self, efficiency: str) -> None:
        battery = Battery(_ROW_11_CONFIG)
        before = battery.soc_envelope
        setattr(battery, efficiency, 0.9)
        assert battery.soc_envelope == before

    def test_a_refused_assignment_leaves_the_envelope_as_it_was(self) -> None:
        battery = Battery(_ROW_11_CONFIG)
        before = battery.soc_envelope
        with pytest.raises(ConfigurationError):
            battery.min_soc_fraction = 0.9
        assert battery.soc_envelope == before

    def test_the_soc_fraction_and_effective_capacity_are_the_envelopes(self) -> None:
        battery = Battery(_ROW_11_CONFIG)
        assert battery.soc_fraction == battery.soc_kwh / battery.soc_envelope.effective_capacity_kwh
        assert battery.effective_capacity_kwh == battery.soc_envelope.effective_capacity_kwh
